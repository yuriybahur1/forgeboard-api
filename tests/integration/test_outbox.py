import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from workstream.infrastructure.outbox import ClaimedEvent, claim_events, mark_failed, mark_processed
from workstream.modules.models import Organization, OutboxEvent

pytestmark = pytest.mark.integration


@pytest.fixture
def sync_sessions(migrated_database, clean_database) -> sessionmaker[Session]:
    engine = create_engine(migrated_database.sync_database)
    return sessionmaker(engine, expire_on_commit=False)


def add_event(sessions: sessionmaker[Session], token: str = "sensitive") -> OutboxEvent:
    with sessions.begin() as db:
        event = OutboxEvent(
            topic="email.verification", payload={"email": "a@example.com", "token": token}
        )
        db.add(event)
        db.flush()
        event_id = event.id
    with sessions() as db:
        return db.get(OutboxEvent, event_id)  # type: ignore[return-value]


def test_business_state_and_outbox_commit_and_rollback(
    sync_sessions: sessionmaker[Session],
) -> None:
    with sync_sessions.begin() as db:
        db.add(Organization(name="Committed", slug="committed"))
        db.add(OutboxEvent(topic="test", payload={}))
    with pytest.raises(RuntimeError), sync_sessions.begin() as db:
        db.add(Organization(name="Rolled back", slug="rolled-back"))
        db.add(OutboxEvent(topic="rollback", payload={}))
        raise RuntimeError
    with sync_sessions() as db:
        assert db.scalar(select(func.count()).select_from(Organization)) == 1
        assert db.scalar(select(func.count()).select_from(OutboxEvent)) == 1


async def test_concurrent_claimers_do_not_duplicate(sync_sessions: sessionmaker[Session]) -> None:
    event = add_event(sync_sessions)
    first, second = await asyncio.gather(
        asyncio.to_thread(claim_events, sync_sessions, "one", 10, 60),
        asyncio.to_thread(claim_events, sync_sessions, "two", 10, 60),
    )
    assert [item.id for item in first + second] == [event.id]
    # The claim transaction has committed before delivery begins and is visible independently.
    with sync_sessions() as db:
        assert db.get(OutboxEvent, event.id).locked_by in {"one", "two"}  # type: ignore[union-attr]


def test_success_failure_backoff_dead_state_and_sensitive_cleanup(
    sync_sessions: sessionmaker[Session],
) -> None:
    event = add_event(sync_sessions)
    claimed = claim_events(sync_sessions, "worker", 1, 60)[0]
    mark_processed(sync_sessions, claimed, "worker")
    with sync_sessions() as db:
        row = db.get(OutboxEvent, event.id)
        assert row and row.processed_at and row.payload == {"delivered": True, "topic": event.topic}
    failed = add_event(sync_sessions)
    claim = claim_events(sync_sessions, "worker", 1, 60)[0]
    before = datetime.now(UTC)
    mark_failed(sync_sessions, claim, "worker", OSError("secret token"), 3)
    with sync_sessions() as db:
        row = db.get(OutboxEvent, failed.id)
        assert row and row.attempts == 1 and row.available_at > before
        assert "secret token" not in (row.last_error or "")
        row.available_at = datetime.now(UTC)
        db.commit()
    for _ in range(2):
        claim = claim_events(sync_sessions, "worker", 1, 60)[0]
        mark_failed(sync_sessions, claim, "worker", OSError("x"), 3)
        with sync_sessions() as db:
            row = db.get(OutboxEvent, failed.id)
            if row and not row.failed_at:
                row.available_at = datetime.now(UTC)
                db.commit()
    with sync_sessions() as db:
        assert db.get(OutboxEvent, failed.id).failed_at is not None  # type: ignore[union-attr]


def test_stale_lease_is_recovered(sync_sessions: sessionmaker[Session]) -> None:
    event = add_event(sync_sessions)
    with sync_sessions.begin() as db:
        row = db.get(OutboxEvent, event.id)
        assert row
        row.locked_by = "dead"
        row.locked_at = datetime.now(UTC) - timedelta(minutes=5)
    claims = claim_events(sync_sessions, "replacement", 1, 30)
    assert claims == [ClaimedEvent(event.id, event.topic, event.payload)]

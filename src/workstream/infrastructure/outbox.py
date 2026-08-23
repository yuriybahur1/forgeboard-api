import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from workstream.modules.models import OutboxEvent


@dataclass(frozen=True, slots=True)
class ClaimedEvent:
    id: UUID
    topic: str
    payload: dict[str, Any]


def claim_events(
    sessions: sessionmaker[Session], worker_id: str, batch_size: int, lease_seconds: int
) -> list[ClaimedEvent]:
    now = datetime.now(UTC)
    stale_before = now - timedelta(seconds=lease_seconds)
    with sessions.begin() as db:
        events = list(
            db.scalars(
                select(OutboxEvent)
                .where(
                    OutboxEvent.processed_at.is_(None),
                    OutboxEvent.failed_at.is_(None),
                    OutboxEvent.available_at <= now,
                    or_(OutboxEvent.locked_at.is_(None), OutboxEvent.locked_at < stale_before),
                )
                .order_by(OutboxEvent.occurred_at, OutboxEvent.id)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
        )
        for event in events:
            event.locked_at = now
            event.locked_by = worker_id
        claimed = [ClaimedEvent(event.id, event.topic, dict(event.payload)) for event in events]
    return claimed


def mark_processed(sessions: sessionmaker[Session], event: ClaimedEvent, worker_id: str) -> None:
    with sessions.begin() as db:
        db.execute(
            update(OutboxEvent)
            .where(OutboxEvent.id == event.id, OutboxEvent.locked_by == worker_id)
            .values(
                processed_at=datetime.now(UTC),
                locked_at=None,
                locked_by=None,
                last_error=None,
                # Raw delivery credentials are no longer needed after successful delivery.
                payload={"delivered": True, "topic": event.topic},
            )
        )


def mark_failed(
    sessions: sessionmaker[Session],
    event: ClaimedEvent,
    worker_id: str,
    error: Exception,
    max_attempts: int,
) -> None:
    now = datetime.now(UTC)
    with sessions.begin() as db:
        row = db.scalar(
            select(OutboxEvent)
            .where(OutboxEvent.id == event.id, OutboxEvent.locked_by == worker_id)
            .with_for_update()
        )
        if row is None:
            return
        row.attempts += 1
        row.last_error = f"{type(error).__name__}: delivery failed"[:2000]
        row.locked_at = None
        row.locked_by = None
        if row.attempts >= max_attempts:
            row.failed_at = now
        else:
            base = min(3600, 2**row.attempts)
            row.available_at = now + timedelta(seconds=base + random.uniform(0, base * 0.2))  # noqa: S311

from typing import Any

import pytest
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import sessionmaker

from workstream.modules.models import Organization, User

pytestmark = pytest.mark.integration

LEGACY_DEMO_USER_EMAILS = (
    "owner@demo.local",
    "member@demo.local",
    "viewer@demo.local",
)


@pytest.mark.usefixtures("clean_database")
async def test_seed_reconciles_legacy_users_and_remains_idempotent(
    migrated_database: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from workstream import seed

    database_url = migrated_database.sync_database
    engine = create_engine(database_url)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(seed, "sync_session_factory", factory)

    try:
        seed.main()
        with factory.begin() as db:
            for role, legacy_email in zip(
                ("owner", "member", "viewer"), LEGACY_DEMO_USER_EMAILS, strict=True
            ):
                db.execute(update(User).where(User.id == seed.uid(role)).values(email=legacy_email))

        seed.main()
        seed.main()

        with factory() as db:
            users = db.scalars(
                select(User).where(
                    User.id.in_(seed.uid(role) for role in ("owner", "member", "viewer"))
                )
            ).all()
            assert {user.email for user in users} == set(seed.DEMO_USER_EMAILS)
            assert db.scalar(select(func.count()).select_from(User)) == 3
            assert db.scalar(select(func.count()).select_from(Organization)) == 2
    finally:
        engine.dispose()

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration


async def test_alembic_built_expected_postgresql_schema(test_engine: AsyncEngine) -> None:
    async with test_engine.connect() as connection:
        tables = set(
            (
                await connection.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                )
            ).scalars()
        )
        extensions = set(
            (await connection.execute(text("SELECT extname FROM pg_extension"))).scalars()
        )
    assert {"users", "organizations", "issues", "auth_sessions", "outbox_events"} <= tables
    assert "pg_trgm" in extensions

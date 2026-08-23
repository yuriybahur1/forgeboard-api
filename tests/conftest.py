import os
import shutil
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from workstream.core.config import get_settings
from workstream.core.security import hash_password
from workstream.db.session import get_session
from workstream.modules.models import Issue, Membership, Organization, Project, User

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ServiceURLs:
    sync_database: str
    async_database: str
    redis: str


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        path = str(item.path)
        if "/unit/" in path or path.endswith(
            (
                "test_app.py",
                "test_core.py",
                "test_policies.py",
                "test_rate_limit.py",
                "test_security.py",
            )
        ):
            item.add_marker(pytest.mark.unit)


@pytest.fixture(scope="session")
def service_urls() -> Iterator[ServiceURLs]:
    sync_url = os.getenv("WORKSTREAM_TEST_DATABASE_URL")
    async_url = os.getenv("WORKSTREAM_TEST_ASYNC_DATABASE_URL")
    redis_url = os.getenv("WORKSTREAM_TEST_REDIS_URL")
    if sync_url and async_url and redis_url:
        yield ServiceURLs(sync_url, async_url, redis_url)
        return
    if shutil.which("docker") is None:
        pytest.fail("Integration tests require WORKSTREAM_TEST_* URLs or Docker/Testcontainers")
    with (
        PostgresContainer("postgres:17-alpine", driver="psycopg") as postgres,
        RedisContainer("redis:8-alpine") as redis,
    ):
        sync_url = postgres.get_connection_url().replace("psycopg2", "psycopg")
        async_url = sync_url.replace("postgresql+psycopg://", "postgresql+psycopg_async://")
        yield ServiceURLs(sync_url, async_url, redis.get_connection_url())


@pytest.fixture(scope="session")
def migrated_database(service_urls: ServiceURLs) -> ServiceURLs:
    os.environ["WORKSTREAM_DATABASE_URL"] = service_urls.sync_database
    os.environ["WORKSTREAM_ASYNC_DATABASE_URL"] = service_urls.async_database
    os.environ["WORKSTREAM_REDIS_URL"] = service_urls.redis
    get_settings.cache_clear()
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", service_urls.sync_database)
    command.upgrade(config, "head")
    return service_urls


@pytest_asyncio.fixture(scope="session")
async def test_engine(migrated_database: ServiceURLs) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(migrated_database.async_database, pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def clean_database(test_engine: AsyncEngine) -> AsyncIterator[None]:
    async with test_engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE outbox_events, one_time_tokens, auth_sessions, audit_events, "
                "notifications, comments, issue_labels, labels, issues, projects, invitations, "
                "memberships, organizations, users CASCADE"
            )
        )
    yield


@pytest.fixture
def session_factory(
    test_engine: AsyncEngine, clean_database: None
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(test_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def db(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def redis_client(migrated_database: ServiceURLs) -> AsyncIterator[Redis]:
    client = Redis.from_url(migrated_database.redis, decode_responses=True)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest_asyncio.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession], redis_client: Redis
) -> AsyncIterator[AsyncClient]:
    from workstream.main import app

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.state.redis = redis_client
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://testserver"
    ) as http:
        yield http
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def user(db: AsyncSession) -> User:
    row = User(
        email="owner@example.com",
        display_name="Owner",
        password_hash=hash_password("ValidPassword123!"),
    )
    db.add(row)
    await db.commit()
    return row


@pytest_asyncio.fixture
async def organization(db: AsyncSession, user: User) -> Organization:
    row = Organization(name="Forge", slug="forge")
    db.add(row)
    await db.flush()
    db.add(Membership(organization_id=row.id, user_id=user.id, role="owner"))
    await db.commit()
    return row


@pytest_asyncio.fixture
async def project(db: AsyncSession, organization: Organization) -> Project:
    row = Project(organization_id=organization.id, name="Engineering", key="ENG")
    db.add(row)
    await db.commit()
    return row


@pytest_asyncio.fixture
async def issue(
    db: AsyncSession, organization: Organization, project: Project, user: User
) -> Issue:
    row = Issue(
        organization_id=organization.id,
        project_id=project.id,
        number=1,
        title="Issue",
        reporter_id=user.id,
    )
    db.add(row)
    project.next_issue_number = 2
    await db.commit()
    return row


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient, user: User) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "ValidPassword123!"}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}

# ruff: noqa: E402 -- test environment must be isolated before application imports

import os
import shutil
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

test_sync_url = os.getenv("WORKSTREAM_TEST_DATABASE_URL")
test_async_url = os.getenv("WORKSTREAM_TEST_ASYNC_DATABASE_URL")
test_redis_url = os.getenv("WORKSTREAM_TEST_REDIS_URL")
explicit_service_urls = bool(test_sync_url and test_async_url and test_redis_url)
os.environ.update(
    {
        "WORKSTREAM_ENVIRONMENT": "test",
        "WORKSTREAM_APP_NAME": "Workstream",
        "WORKSTREAM_DATABASE_URL": (test_sync_url if explicit_service_urls else None)
        or "postgresql+psycopg://workstream:workstream@localhost:5432/workstream_test",
        "WORKSTREAM_ASYNC_DATABASE_URL": (test_async_url if explicit_service_urls else None)
        or "postgresql+psycopg_async://workstream:workstream@localhost:5432/workstream_test",
        "WORKSTREAM_REDIS_URL": (test_redis_url if explicit_service_urls else None)
        or "redis://localhost:6379/15",
        "WORKSTREAM_JWT_SECRET": "test-only-secret-with-at-least-32-characters",
        "WORKSTREAM_JWT_ISSUER": "workstream",
        "WORKSTREAM_JWT_AUDIENCE": "workstream-api",
        "WORKSTREAM_ACCESS_TOKEN_MINUTES": "15",
        "WORKSTREAM_REFRESH_TOKEN_DAYS": "30",
        "WORKSTREAM_ALLOWED_HOSTS": '["localhost","127.0.0.1","testserver"]',
        "WORKSTREAM_CORS_ORIGINS": "[]",
        "WORKSTREAM_SMTP_HOST": "localhost",
        "WORKSTREAM_SMTP_PORT": "1025",
        "WORKSTREAM_EMAIL_FROM": "noreply@workstream.test",
        "WORKSTREAM_PUBLIC_URL": "http://testserver",
        "WORKSTREAM_LOG_JSON": "false",
        "WORKSTREAM_LOGIN_RATE_LIMIT": "10",
        "WORKSTREAM_PASSWORD_RESET_RATE_LIMIT": "5",
        "WORKSTREAM_VERIFICATION_RATE_LIMIT": "3",
        "WORKSTREAM_INVITATION_RATE_LIMIT": "20",
        "WORKSTREAM_OUTBOX_CLAIM_SECONDS": "120",
        "WORKSTREAM_OUTBOX_MAX_ATTEMPTS": "10",
    }
)

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
    sync_url = test_sync_url
    async_url = test_async_url
    redis_url = test_redis_url
    if explicit_service_urls:
        assert sync_url and async_url and redis_url
        yield ServiceURLs(sync_url, async_url, redis_url)
        return
    if any((sync_url, async_url, redis_url)):
        pytest.fail("Set all three WORKSTREAM_TEST_* service URLs or leave all three unset")
    if shutil.which("docker") is None:
        pytest.fail("Integration tests require WORKSTREAM_TEST_* URLs or Docker/Testcontainers")
    with (
        PostgresContainer("postgres:17-alpine", driver="psycopg") as postgres,
        RedisContainer("redis:8-alpine") as redis,
    ):
        sync_url = postgres.get_connection_url().replace("psycopg2", "psycopg")
        async_url = sync_url.replace("postgresql+psycopg://", "postgresql+psycopg_async://")
        redis_host = redis.get_container_host_ip()
        redis_port = redis.get_exposed_port(6379)
        redis_authority = f"[{redis_host}]" if ":" in redis_host else redis_host
        yield ServiceURLs(sync_url, async_url, f"redis://{redis_authority}:{redis_port}/0")


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
    from workstream.db.session import get_session
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

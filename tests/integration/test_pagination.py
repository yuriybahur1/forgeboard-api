from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from workstream.modules.models import (
    AuditEvent,
    Comment,
    Issue,
    Notification,
    Organization,
    Project,
    User,
)

pytestmark = pytest.mark.integration


def assert_pages(first: dict, second: dict) -> None:
    first_ids = {item["id"] for item in first["items"]}
    second_ids = {item["id"] for item in second["items"]}
    assert first_ids and second_ids and first_ids.isdisjoint(second_ids)


async def test_issue_keyset_equal_timestamps(
    client: AsyncClient,
    db: AsyncSession,
    organization: Organization,
    project: Project,
    user: User,
    auth_headers: dict[str, str],
) -> None:
    stamp = datetime.now(UTC)
    db.add_all(
        [
            Issue(
                organization_id=organization.id,
                project_id=project.id,
                number=i,
                title=f"Issue {i}",
                reporter_id=user.id,
                created_at=stamp,
            )
            for i in range(1, 6)
        ]
    )
    await db.commit()
    path = f"/api/v1/organizations/{organization.id}/issues"
    first = (await client.get(path, params={"limit": 2}, headers=auth_headers)).json()
    second = (
        await client.get(
            path, params={"limit": 2, "cursor": first["next_cursor"]}, headers=auth_headers
        )
    ).json()
    assert_pages(first, second)
    assert (
        await client.get(path, params={"cursor": "broken"}, headers=auth_headers)
    ).status_code == 400
    assert (await client.get(path, params={"limit": 101}, headers=auth_headers)).status_code == 422


async def test_comment_keyset(
    client: AsyncClient,
    db: AsyncSession,
    issue: Issue,
    organization: Organization,
    user: User,
    auth_headers: dict[str, str],
) -> None:
    stamp = datetime.now(UTC)
    db.add_all(
        [
            Comment(
                organization_id=organization.id,
                issue_id=issue.id,
                author_id=user.id,
                body=str(i),
                created_at=stamp,
            )
            for i in range(5)
        ]
    )
    await db.commit()
    path = f"/api/v1/organizations/{organization.id}/issues/{issue.id}/comments"
    first = (await client.get(path, params={"limit": 2}, headers=auth_headers)).json()
    second = (
        await client.get(
            path, params={"limit": 2, "cursor": first["next_cursor"]}, headers=auth_headers
        )
    ).json()
    assert_pages(first, second)


async def test_notification_keyset(
    client: AsyncClient, db: AsyncSession, user: User, auth_headers: dict[str, str]
) -> None:
    stamp = datetime.now(UTC)
    db.add_all(
        [
            Notification(user_id=user.id, kind="test", payload={"n": i}, created_at=stamp)
            for i in range(5)
        ]
    )
    await db.commit()
    first = (
        await client.get("/api/v1/notifications", params={"limit": 2}, headers=auth_headers)
    ).json()
    second = (
        await client.get(
            "/api/v1/notifications",
            params={"limit": 2, "cursor": first["next_cursor"]},
            headers=auth_headers,
        )
    ).json()
    assert_pages(first, second)


async def test_audit_keyset(
    client: AsyncClient,
    db: AsyncSession,
    organization: Organization,
    user: User,
    auth_headers: dict[str, str],
) -> None:
    stamp = datetime.now(UTC)
    db.add_all(
        [
            AuditEvent(
                actor_id=user.id,
                organization_id=organization.id,
                action=f"test.{i}",
                entity_type="test",
                created_at=stamp,
            )
            for i in range(5)
        ]
    )
    await db.commit()
    path = f"/api/v1/organizations/{organization.id}/audit"
    first = (await client.get(path, params={"limit": 2}, headers=auth_headers)).json()
    second = (
        await client.get(
            path, params={"limit": 2, "cursor": first["next_cursor"]}, headers=auth_headers
        )
    ).json()
    assert_pages(first, second)

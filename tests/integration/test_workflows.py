import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from workstream.modules.models import Notification, User

pytestmark = pytest.mark.integration


async def test_project_issue_label_comment_notification_workflows(
    client: AsyncClient, db: AsyncSession, user: User, auth_headers: dict[str, str]
) -> None:
    org_response = await client.post(
        "/api/v1/organizations", headers=auth_headers, json={"name": "Workflow", "slug": "workflow"}
    )
    assert org_response.status_code == 201
    org_id = org_response.json()["id"]
    project = await client.post(
        f"/api/v1/organizations/{org_id}/projects",
        headers=auth_headers,
        json={"name": "Engineering", "key": "ENG"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]
    assert (
        await client.patch(
            f"/api/v1/organizations/{org_id}/projects/{project_id}",
            headers=auth_headers,
            json={"description": "Updated"},
        )
    ).status_code == 200
    assert (
        await client.post(
            f"/api/v1/organizations/{org_id}/projects/{project_id}/archive", headers=auth_headers
        )
    ).status_code == 204
    assert (
        await client.post(
            f"/api/v1/organizations/{org_id}/projects/{project_id}/unarchive", headers=auth_headers
        )
    ).status_code == 204
    issue = await client.post(
        f"/api/v1/organizations/{org_id}/issues",
        headers=auth_headers,
        json={"project_id": project_id, "title": "Workflow issue"},
    )
    assert issue.status_code == 201
    issue_id = issue.json()["id"]
    updated = await client.patch(
        f"/api/v1/organizations/{org_id}/issues/{issue_id}",
        headers=auth_headers,
        json={"expected_version": 1, "priority": "high"},
    )
    assert updated.status_code == 200
    status = await client.post(
        f"/api/v1/organizations/{org_id}/issues/{issue_id}/status",
        headers=auth_headers,
        json={"expected_version": 2, "status": "todo"},
    )
    assert status.status_code == 200
    assignment = await client.post(
        f"/api/v1/organizations/{org_id}/issues/{issue_id}/assignment",
        headers=auth_headers,
        json={"expected_version": 3, "assignee_id": str(user.id)},
    )
    assert assignment.status_code == 200
    label = await client.post(
        f"/api/v1/organizations/{org_id}/labels",
        headers=auth_headers,
        json={"name": "backend", "color": "#112233"},
    )
    assert label.status_code == 201
    label_id = label.json()["id"]
    assert (
        await client.put(
            f"/api/v1/organizations/{org_id}/issues/{issue_id}/labels/{label_id}",
            headers=auth_headers,
        )
    ).status_code == 204
    assert (
        await client.delete(
            f"/api/v1/organizations/{org_id}/issues/{issue_id}/labels/{label_id}",
            headers=auth_headers,
        )
    ).status_code == 204
    assert (
        await client.patch(
            f"/api/v1/organizations/{org_id}/labels/{label_id}",
            headers=auth_headers,
            json={"name": "api", "color": "#223344"},
        )
    ).status_code == 200
    comment = await client.post(
        f"/api/v1/organizations/{org_id}/issues/{issue_id}/comments",
        headers=auth_headers,
        json={"body": "First"},
    )
    assert comment.status_code == 201
    comment_id = comment.json()["id"]
    assert (
        await client.patch(
            f"/api/v1/organizations/{org_id}/comments/{comment_id}",
            headers=auth_headers,
            json={"body": "Edited"},
        )
    ).status_code == 200
    assert (
        await client.delete(
            f"/api/v1/organizations/{org_id}/comments/{comment_id}", headers=auth_headers
        )
    ).status_code == 204
    notification = Notification(user_id=user.id, organization_id=org_id, kind="test", payload={})
    db.add(notification)
    await db.commit()
    assert (await client.get("/api/v1/notifications/unread-count", headers=auth_headers)).json()[
        "count"
    ] == 1
    assert (
        await client.post(f"/api/v1/notifications/{notification.id}/read", headers=auth_headers)
    ).status_code == 204
    assert (
        await client.post("/api/v1/notifications/read-all", headers=auth_headers)
    ).status_code == 204
    assert (
        await client.delete(
            f"/api/v1/organizations/{org_id}/labels/{label_id}", headers=auth_headers
        )
    ).status_code == 204
    assert (
        await client.delete(
            f"/api/v1/organizations/{org_id}/issues/{issue_id}", headers=auth_headers
        )
    ).status_code == 204

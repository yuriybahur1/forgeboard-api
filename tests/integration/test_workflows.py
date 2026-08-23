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
    organizations = await client.get("/api/v1/organizations", headers=auth_headers)
    assert {item["id"] for item in organizations.json()} == {org_id}
    organization = await client.get(f"/api/v1/organizations/{org_id}", headers=auth_headers)
    assert organization.status_code == 200 and organization.json()["slug"] == "workflow"
    members = await client.get(f"/api/v1/organizations/{org_id}/members", headers=auth_headers)
    assert members.status_code == 200
    assert members.json() == [
        {
            "user_id": str(user.id),
            "role": "owner",
            "email": user.email,
            "display_name": user.display_name,
        }
    ]
    project = await client.post(
        f"/api/v1/organizations/{org_id}/projects",
        headers=auth_headers,
        json={"name": "Engineering", "key": "ENG"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]
    projects = await client.get(f"/api/v1/organizations/{org_id}/projects", headers=auth_headers)
    assert [item["id"] for item in projects.json()] == [project_id]
    project_detail = await client.get(
        f"/api/v1/organizations/{org_id}/projects/{project_id}", headers=auth_headers
    )
    assert project_detail.status_code == 200 and project_detail.json()["key"] == "ENG"
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
    active_projects = await client.get(
        f"/api/v1/organizations/{org_id}/projects", headers=auth_headers
    )
    archived_projects = await client.get(
        f"/api/v1/organizations/{org_id}/projects?include_archived=true", headers=auth_headers
    )
    assert active_projects.json() == []
    assert [item["id"] for item in archived_projects.json()] == [project_id]
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
    issue_detail = await client.get(
        f"/api/v1/organizations/{org_id}/issues/{issue_id}", headers=auth_headers
    )
    issue_search = await client.get(
        f"/api/v1/organizations/{org_id}/issues?search=Workflow&priority=no_priority",
        headers=auth_headers,
    )
    assert issue_detail.status_code == 200 and issue_detail.json()["id"] == issue_id
    assert [item["id"] for item in issue_search.json()["items"]] == [issue_id]
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
    labels = await client.get(f"/api/v1/organizations/{org_id}/labels", headers=auth_headers)
    assert [item["id"] for item in labels.json()] == [label_id]
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

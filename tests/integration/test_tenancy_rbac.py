import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from workstream.core.security import hash_password
from workstream.modules.models import (
    AuditEvent,
    Comment,
    Issue,
    Label,
    Membership,
    Organization,
    Project,
    User,
)

pytestmark = pytest.mark.integration


async def login(client: AsyncClient, user: User) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "ValidPassword123!"}
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_cross_tenant_exact_ids_are_hidden(
    client: AsyncClient, db: AsyncSession, organization: Organization, auth_headers: dict[str, str]
) -> None:
    outsider = User(
        email="other@example.com",
        display_name="Other",
        password_hash=hash_password("ValidPassword123!"),
    )
    db.add(outsider)
    other = Organization(name="Other", slug="other")
    db.add(other)
    await db.flush()
    db.add(Membership(organization_id=other.id, user_id=outsider.id, role="owner"))
    project = Project(organization_id=other.id, name="Secret", key="SEC")
    db.add(project)
    await db.flush()
    issue = Issue(
        organization_id=other.id,
        project_id=project.id,
        number=1,
        title="Secret",
        reporter_id=outsider.id,
    )
    label = Label(organization_id=other.id, name="secret", color="#112233")
    db.add_all([issue, label])
    await db.flush()
    comment = Comment(
        organization_id=other.id, issue_id=issue.id, author_id=outsider.id, body="secret"
    )
    db.add(comment)
    db.add(
        AuditEvent(
            actor_id=outsider.id,
            organization_id=other.id,
            action="secret",
            entity_type="issue",
            entity_id=issue.id,
        )
    )
    await db.commit()
    checks = [
        ("GET", f"/api/v1/organizations/{organization.id}/projects/{project.id}", None),
        (
            "PATCH",
            f"/api/v1/organizations/{organization.id}/projects/{project.id}",
            {"name": "stolen"},
        ),
        ("GET", f"/api/v1/organizations/{organization.id}/issues/{issue.id}", None),
        (
            "PATCH",
            f"/api/v1/organizations/{organization.id}/issues/{issue.id}",
            {"expected_version": 1, "title": "stolen"},
        ),
        (
            "PATCH",
            f"/api/v1/organizations/{organization.id}/labels/{label.id}",
            {"name": "x", "color": "#112233"},
        ),
        (
            "PATCH",
            f"/api/v1/organizations/{organization.id}/comments/{comment.id}",
            {"body": "stolen"},
        ),
        ("GET", f"/api/v1/organizations/{other.id}/audit", None),
    ]
    for method, path, payload in checks:
        response = await client.request(method, path, headers=auth_headers, json=payload)
        assert response.status_code in {403, 404}, (method, path, response.text)


@pytest.mark.parametrize(
    "role,project_status,issue_status,audit_status",
    [
        ("owner", 201, 201, 200),
        ("admin", 201, 201, 200),
        ("member", 201, 201, 403),
        ("viewer", 403, 403, 403),
    ],
)
async def test_role_matrix(
    client: AsyncClient,
    db: AsyncSession,
    role: str,
    project_status: int,
    issue_status: int,
    audit_status: int,
) -> None:
    owner = User(
        email="owner2@example.com",
        display_name="Owner",
        password_hash=hash_password("ValidPassword123!"),
    )
    actor = User(
        email=f"{role}@example.com",
        display_name=role,
        password_hash=hash_password("ValidPassword123!"),
    )
    org = Organization(name="Roles", slug=f"roles-{role}")
    db.add_all([owner, actor, org])
    await db.flush()
    db.add_all(
        [
            Membership(organization_id=org.id, user_id=owner.id, role="owner"),
            Membership(organization_id=org.id, user_id=actor.id, role=role),
        ]
    )
    await db.commit()
    headers = await login(client, actor)
    project_response = await client.post(
        f"/api/v1/organizations/{org.id}/projects",
        headers=headers,
        json={"name": "Project", "key": "ROLE"},
    )
    assert project_response.status_code == project_status
    project = project_response.json() if project_status == 201 else None
    if project is None:
        fallback = Project(organization_id=org.id, name="Fallback", key="FB")
        db.add(fallback)
        await db.commit()
        project_id = fallback.id
    else:
        project_id = project["id"]
    issue_response = await client.post(
        f"/api/v1/organizations/{org.id}/issues",
        headers=headers,
        json={"project_id": str(project_id), "title": "Role issue"},
    )
    assert issue_response.status_code == issue_status
    assert (
        await client.get(f"/api/v1/organizations/{org.id}/audit", headers=headers)
    ).status_code == audit_status
    invitation = await client.post(
        f"/api/v1/organizations/{org.id}/invitations",
        headers=headers,
        json={"email": "invitee@example.com", "role": "member"},
    )
    assert invitation.status_code == (201 if role in {"owner", "admin"} else 403)


async def test_membership_role_change_and_removal_permissions(
    client: AsyncClient, db: AsyncSession
) -> None:
    owner = User(
        email="rbac-owner@example.com",
        display_name="Owner",
        password_hash=hash_password("ValidPassword123!"),
    )
    admin = User(
        email="rbac-admin@example.com",
        display_name="Admin",
        password_hash=hash_password("ValidPassword123!"),
    )
    member = User(
        email="rbac-member@example.com",
        display_name="Member",
        password_hash=hash_password("ValidPassword123!"),
    )
    org = Organization(name="Membership RBAC", slug="membership-rbac")
    db.add_all([owner, admin, member, org])
    await db.flush()
    db.add_all(
        [
            Membership(organization_id=org.id, user_id=owner.id, role="owner"),
            Membership(organization_id=org.id, user_id=admin.id, role="admin"),
            Membership(organization_id=org.id, user_id=member.id, role="member"),
        ]
    )
    await db.commit()
    admin_headers = await login(client, admin)
    owner_headers = await login(client, owner)
    denied = await client.patch(
        f"/api/v1/organizations/{org.id}/members/{member.id}",
        headers=admin_headers,
        json={"role": "viewer"},
    )
    assert denied.status_code == 403
    changed = await client.patch(
        f"/api/v1/organizations/{org.id}/members/{member.id}",
        headers=owner_headers,
        json={"role": "viewer"},
    )
    assert changed.status_code == 204
    removed = await client.delete(
        f"/api/v1/organizations/{org.id}/members/{member.id}", headers=admin_headers
    )
    assert removed.status_code == 204

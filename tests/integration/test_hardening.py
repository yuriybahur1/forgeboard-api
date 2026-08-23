from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from workstream.core.security import hash_password, opaque_token, token_hash
from workstream.modules.models import AuditEvent, Invitation, Membership, Organization, User

pytestmark = pytest.mark.integration
PASSWORD = "ValidPassword123!"


async def login(client: AsyncClient, user: User) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": PASSWORD}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_expected_unique_conflicts_return_stable_409_responses(
    client: AsyncClient,
    organization: Organization,
    auth_headers: dict[str, str],
) -> None:
    duplicate_org = await client.post(
        "/api/v1/organizations",
        headers=auth_headers,
        json={"name": "Duplicate", "slug": organization.slug},
    )
    assert duplicate_org.status_code == 409
    assert duplicate_org.json()["code"] == "organization_slug_conflict"

    first_project = await client.post(
        f"/api/v1/organizations/{organization.id}/projects",
        headers=auth_headers,
        json={"name": "First", "key": "DUP"},
    )
    duplicate_project = await client.post(
        f"/api/v1/organizations/{organization.id}/projects",
        headers=auth_headers,
        json={"name": "Second", "key": "DUP"},
    )
    assert first_project.status_code == 201
    assert duplicate_project.status_code == 409
    assert duplicate_project.json()["code"] == "project_key_conflict"

    first_label = await client.post(
        f"/api/v1/organizations/{organization.id}/labels",
        headers=auth_headers,
        json={"name": "duplicate", "color": "#112233"},
    )
    duplicate_label = await client.post(
        f"/api/v1/organizations/{organization.id}/labels",
        headers=auth_headers,
        json={"name": "duplicate", "color": "#445566"},
    )
    assert first_label.status_code == 201
    assert duplicate_label.status_code == 409
    assert duplicate_label.json()["code"] == "label_name_conflict"

    # Each conflict handler must leave its request session usable.
    listed = await client.get(
        f"/api/v1/organizations/{organization.id}/labels", headers=auth_headers
    )
    assert listed.status_code == 200


async def test_status_audit_records_the_exact_transition(
    client: AsyncClient,
    db: AsyncSession,
    organization: Organization,
    issue,
    auth_headers: dict[str, str],
) -> None:
    response = await client.post(
        f"/api/v1/organizations/{organization.id}/issues/{issue.id}/status",
        headers=auth_headers,
        json={"expected_version": 1, "status": "todo"},
    )
    assert response.status_code == 200
    event = await db.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "issue.status_changed", AuditEvent.entity_id == issue.id
        )
    )
    assert event is not None
    assert event.metadata_ == {"from": "backlog", "to": "todo"}


async def test_command_and_filter_validation_is_consistent(
    client: AsyncClient,
    organization: Organization,
    issue,
    auth_headers: dict[str, str],
) -> None:
    assignment = await client.post(
        f"/api/v1/organizations/{organization.id}/issues/{issue.id}/assignment",
        headers=auth_headers,
        json={"expected_version": 0, "assignee_id": None},
    )
    invalid_status = await client.get(
        f"/api/v1/organizations/{organization.id}/issues?status=unknown", headers=auth_headers
    )
    invalid_priority = await client.get(
        f"/api/v1/organizations/{organization.id}/issues?priority=critical",
        headers=auth_headers,
    )
    short_token = await client.post(
        "/api/v1/organizations/invitations/accept",
        headers=auth_headers,
        json={"token": "short"},
    )
    long_token = await client.post(
        "/api/v1/organizations/invitations/accept",
        headers=auth_headers,
        json={"token": "x" * 513},
    )

    assert {
        response.status_code
        for response in (assignment, invalid_status, invalid_priority, short_token, long_token)
    } == {422}


async def test_pending_invitations_exclude_expired_rows(
    client: AsyncClient,
    db: AsyncSession,
    organization: Organization,
    user: User,
    auth_headers: dict[str, str],
) -> None:
    expired = Invitation(
        organization_id=organization.id,
        invited_email="expired@example.com",
        role="member",
        token_hash=token_hash(opaque_token()),
        inviter_id=user.id,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    active = Invitation(
        organization_id=organization.id,
        invited_email="active@example.com",
        role="member",
        token_hash=token_hash(opaque_token()),
        inviter_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add_all([expired, active])
    await db.commit()

    response = await client.get(
        f"/api/v1/organizations/{organization.id}/invitations", headers=auth_headers
    )
    assert response.status_code == 200
    assert {row["id"] for row in response.json()} == {str(active.id)}


async def test_admin_cannot_remove_owner_but_owner_can_remove_nonfinal_owner(
    client: AsyncClient,
    db: AsyncSession,
    organization: Organization,
    user: User,
    auth_headers: dict[str, str],
) -> None:
    admin = User(
        email="hierarchy-admin@example.com",
        display_name="Admin",
        password_hash=hash_password(PASSWORD),
    )
    other_owner = User(
        email="hierarchy-owner@example.com",
        display_name="Other Owner",
        password_hash=hash_password(PASSWORD),
    )
    db.add_all([admin, other_owner])
    await db.flush()
    db.add_all(
        [
            Membership(organization_id=organization.id, user_id=admin.id, role="admin"),
            Membership(organization_id=organization.id, user_id=other_owner.id, role="owner"),
        ]
    )
    await db.commit()
    admin_headers = await login(client, admin)

    denied = await client.delete(
        f"/api/v1/organizations/{organization.id}/members/{other_owner.id}",
        headers=admin_headers,
    )
    allowed = await client.delete(
        f"/api/v1/organizations/{organization.id}/members/{other_owner.id}",
        headers=auth_headers,
    )

    assert denied.status_code == 403
    assert denied.json()["code"] == "insufficient_permission"
    assert allowed.status_code == 204
    assert await db.get(Membership, (organization.id, user.id)) is not None

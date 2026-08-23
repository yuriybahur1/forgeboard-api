from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from workstream.api.schemas import InvitationAccept
from workstream.core.security import hash_password, opaque_token, token_hash
from workstream.modules.models import (
    AuthSession,
    Invitation,
    Label,
    Membership,
    Notification,
    OneTimeToken,
    Organization,
    OutboxEvent,
    Project,
    User,
)
from workstream.modules.organizations import service as organization_service

pytestmark = pytest.mark.integration
PASSWORD = "ValidPassword123!"


async def login(client: AsyncClient, user: User) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": PASSWORD}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_auth_inactive_invalid_refresh_and_expired_reset(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    user.is_active = False
    await db.commit()
    denied = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": PASSWORD}
    )
    assert denied.status_code == 401
    user.is_active = True
    expired_raw = opaque_token()
    db.add(
        OneTimeToken(
            user_id=user.id,
            purpose="password_reset",
            token_hash=token_hash(expired_raw),
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )
    await db.commit()
    invalid_refresh = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": opaque_token()}
    )
    assert invalid_refresh.status_code == 401
    expired_reset = await client.post(
        "/api/v1/auth/password-reset",
        json={"token": expired_raw, "new_password": "AnotherValidPassword123!"},
    )
    assert expired_reset.status_code == 400


async def test_expired_and_revoked_refresh_credentials(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    for expired, revoked in [(True, False), (False, True)]:
        raw = opaque_token()
        db.add(
            AuthSession(
                user_id=user.id,
                family_id=user.id,
                refresh_token_hash=token_hash(raw),
                expires_at=(
                    datetime.now(UTC) - timedelta(seconds=1)
                    if expired
                    else datetime.now(UTC) + timedelta(hours=1)
                ),
                revoked_at=datetime.now(UTC) if revoked else None,
            )
        )
        await db.commit()
        response = await client.post("/api/v1/auth/refresh", json={"refresh_token": raw})
        assert response.status_code == 401


async def test_deactivated_user_cannot_rotate_refresh_session(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": PASSWORD}
    )
    assert response.status_code == 200
    refresh_token = response.json()["refresh_token"]
    user.is_active = False
    await db.commit()

    denied = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert denied.status_code == 401
    session = await db.scalar(
        select(AuthSession).where(AuthSession.refresh_token_hash == token_hash(refresh_token))
    )
    assert session is not None and session.revoked_at is not None


async def test_organization_update_invitation_revoke_and_acceptance_errors(
    client: AsyncClient,
    db: AsyncSession,
    organization: Organization,
    user: User,
    auth_headers: dict[str, str],
) -> None:
    updated = await client.patch(
        f"/api/v1/organizations/{organization.id}",
        headers=auth_headers,
        json={"name": "Renamed"},
    )
    assert updated.status_code == 200 and updated.json()["name"] == "Renamed"
    invitation = await client.post(
        f"/api/v1/organizations/{organization.id}/invitations",
        headers=auth_headers,
        json={"email": "invited@example.com", "role": "member"},
    )
    assert invitation.status_code == 201
    invitation_id = invitation.json()["id"]
    listed = await client.get(
        f"/api/v1/organizations/{organization.id}/invitations", headers=auth_headers
    )
    assert {row["id"] for row in listed.json()} == {invitation_id}
    assert (
        await client.delete(
            f"/api/v1/organizations/{organization.id}/invitations/{invitation_id}",
            headers=auth_headers,
        )
    ).status_code == 204
    event = await db.scalar(select(OutboxEvent).where(OutboxEvent.topic == "email.invitation"))
    assert event
    revoked = await client.post(
        "/api/v1/organizations/invitations/accept",
        headers=auth_headers,
        json={"token": event.payload["token"]},
    )
    assert revoked.status_code == 400


async def test_invitation_email_mismatch_and_expiry(
    client: AsyncClient,
    db: AsyncSession,
    organization: Organization,
    user: User,
    auth_headers: dict[str, str],
) -> None:
    mismatch_raw = opaque_token()
    expired_raw = opaque_token()
    db.add_all(
        [
            Invitation(
                organization_id=organization.id,
                invited_email="someone@example.com",
                role="member",
                token_hash=token_hash(mismatch_raw),
                inviter_id=user.id,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            ),
            Invitation(
                organization_id=organization.id,
                invited_email=user.email,
                role="member",
                token_hash=token_hash(expired_raw),
                inviter_id=user.id,
                expires_at=datetime.now(UTC) - timedelta(seconds=1),
            ),
        ]
    )
    await db.commit()
    mismatch = await client.post(
        "/api/v1/organizations/invitations/accept",
        headers=auth_headers,
        json={"token": mismatch_raw},
    )
    expired = await client.post(
        "/api/v1/organizations/invitations/accept",
        headers=auth_headers,
        json={"token": expired_raw},
    )
    assert mismatch.status_code == 403
    assert expired.status_code == 400


async def test_accepted_invitation_cannot_resurrect_removed_membership(
    db: AsyncSession, organization: Organization, user: User
) -> None:
    invitee = User(
        email="one-time-invite@example.com",
        display_name="One Time Invitee",
        password_hash=hash_password(PASSWORD),
    )
    raw = opaque_token()
    db.add(invitee)
    await db.flush()
    db.add(
        Invitation(
            organization_id=organization.id,
            invited_email=invitee.email,
            role="member",
            token_hash=token_hash(raw),
            inviter_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await db.commit()

    await organization_service.accept(db, invitee, InvitationAccept(token=raw))
    membership = await db.get(Membership, (organization.id, invitee.id))
    assert membership is not None
    await db.delete(membership)
    await db.commit()

    await organization_service.accept(db, invitee, InvitationAccept(token=raw))
    assert await db.get(Membership, (organization.id, invitee.id)) is None


async def test_issue_archived_project_invalid_assignee_transition_and_assignment(
    client: AsyncClient,
    db: AsyncSession,
    organization: Organization,
    project: Project,
    user: User,
    issue,
    auth_headers: dict[str, str],
) -> None:
    project.archived = True
    await db.commit()
    archived = await client.post(
        f"/api/v1/organizations/{organization.id}/issues",
        headers=auth_headers,
        json={"project_id": str(project.id), "title": "Blocked"},
    )
    assert archived.status_code == 409 and archived.json()["code"] == "project_archived"
    invalid_priority = await client.post(
        f"/api/v1/organizations/{organization.id}/issues",
        headers=auth_headers,
        json={"project_id": str(project.id), "title": "Invalid", "priority": "critical"},
    )
    assert invalid_priority.status_code == 422
    invalid_status = await client.post(
        f"/api/v1/organizations/{organization.id}/issues/{issue.id}/status",
        headers=auth_headers,
        json={"expected_version": 1, "status": "unknown"},
    )
    assert invalid_status.status_code == 422
    project.archived = False
    outsider = User(
        email="outsider-assignee@example.com",
        display_name="Outsider",
        password_hash=hash_password(PASSWORD),
    )
    db.add(outsider)
    await db.commit()
    invalid = await client.post(
        f"/api/v1/organizations/{organization.id}/issues",
        headers=auth_headers,
        json={"project_id": str(project.id), "title": "Invalid", "assignee_id": str(outsider.id)},
    )
    assert invalid.status_code == 422 and invalid.json()["code"] == "invalid_assignee"
    transition = await client.post(
        f"/api/v1/organizations/{organization.id}/issues/{issue.id}/status",
        headers=auth_headers,
        json={"expected_version": 1, "status": "done"},
    )
    assert transition.status_code == 409
    member = User(
        email="assignee@example.com", display_name="Assignee", password_hash=hash_password(PASSWORD)
    )
    db.add(member)
    await db.flush()
    db.add(Membership(organization_id=organization.id, user_id=member.id, role="member"))
    await db.commit()
    assigned = await client.post(
        f"/api/v1/organizations/{organization.id}/issues/{issue.id}/assignment",
        headers=auth_headers,
        json={"expected_version": 1, "assignee_id": str(member.id)},
    )
    assert assigned.status_code == 200
    notification = await db.scalar(select(Notification).where(Notification.user_id == member.id))
    assert notification and notification.payload["issue_id"] == str(issue.id)
    member.is_active = False
    await db.commit()
    inactive = await client.post(
        f"/api/v1/organizations/{organization.id}/issues/{issue.id}/assignment",
        headers=auth_headers,
        json={"expected_version": 2, "assignee_id": str(member.id)},
    )
    assert inactive.status_code == 422 and inactive.json()["code"] == "invalid_assignee"


async def test_label_and_comment_permission_and_missing_resource_branches(
    client: AsyncClient,
    db: AsyncSession,
    organization: Organization,
    issue,
    user: User,
    auth_headers: dict[str, str],
) -> None:
    missing = uuid4()
    assert (
        await client.patch(
            f"/api/v1/organizations/{organization.id}/labels/{missing}",
            headers=auth_headers,
            json={"name": "missing", "color": "#112233"},
        )
    ).status_code == 404
    label = Label(organization_id=organization.id, name="edge", color="#112233")
    other = User(
        email="commenter@example.com",
        display_name="Commenter",
        password_hash=hash_password(PASSWORD),
    )
    db.add_all([label, other])
    await db.flush()
    db.add(Membership(organization_id=organization.id, user_id=other.id, role="member"))
    await db.commit()
    other_headers = await login(client, other)
    comment = await client.post(
        f"/api/v1/organizations/{organization.id}/issues/{issue.id}/comments",
        headers=other_headers,
        json={"body": "Other author's comment"},
    )
    assert comment.status_code == 201
    forbidden = await client.patch(
        f"/api/v1/organizations/{organization.id}/comments/{comment.json()['id']}",
        headers=auth_headers,
        json={"body": "Not mine"},
    )
    assert forbidden.status_code == 403
    member = User(
        email="moderation-member@example.com",
        display_name="Moderation Member",
        password_hash=hash_password(PASSWORD),
    )
    db.add(member)
    await db.flush()
    db.add(Membership(organization_id=organization.id, user_id=member.id, role="member"))
    await db.commit()
    member_headers = await login(client, member)
    forbidden_delete = await client.delete(
        f"/api/v1/organizations/{organization.id}/comments/{comment.json()['id']}",
        headers=member_headers,
    )
    assert forbidden_delete.status_code == 403
    moderated = await client.delete(
        f"/api/v1/organizations/{organization.id}/comments/{comment.json()['id']}",
        headers=auth_headers,
    )
    assert moderated.status_code == 204

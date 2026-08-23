from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import select

from workstream.api.dependencies import DB, Config, CurrentUser, require_membership
from workstream.api.rate_limit import enforce_rate_limit
from workstream.api.schemas import (
    InvitationAccept,
    InvitationCreate,
    OrganizationCreate,
    OrganizationOut,
    OrganizationUpdate,
    RoleChange,
)
from workstream.core.errors import AppError
from workstream.core.security import opaque_token, token_hash
from workstream.modules.models import (
    AuditEvent,
    Invitation,
    Membership,
    Organization,
    OutboxEvent,
    User,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.post("", response_model=OrganizationOut, status_code=201)
async def create(
    body: OrganizationCreate, user: CurrentUser, db: DB, request: Request
) -> Organization:
    org = Organization(name=body.name, slug=body.slug)
    db.add(org)
    await db.flush()
    db.add(Membership(organization_id=org.id, user_id=user.id, role="owner"))
    db.add(
        AuditEvent(
            actor_id=user.id,
            organization_id=org.id,
            action="organization.created",
            entity_type="organization",
            entity_id=org.id,
            request_id=request.state.request_id,
        )
    )
    await db.commit()
    return org


@router.get("", response_model=list[OrganizationOut])
async def list_orgs(user: CurrentUser, db: DB) -> list[Organization]:
    return list(
        (
            await db.execute(
                select(Organization)
                .join(Membership)
                .where(Membership.user_id == user.id)
                .order_by(Organization.name)
                .limit(100)
            )
        ).scalars()
    )


@router.get("/{organization_id}", response_model=OrganizationOut)
async def get_org(organization_id: UUID, user: CurrentUser, db: DB) -> Organization:
    await require_membership(db, organization_id, user.id)
    org = await db.get(Organization, organization_id)
    if org is None:
        raise AppError(404, "resource_not_found", "Organization not found")
    return org


@router.patch("/{organization_id}", response_model=OrganizationOut)
async def update_org(
    organization_id: UUID, body: OrganizationUpdate, user: CurrentUser, db: DB
) -> Organization:
    await require_membership(db, organization_id, user.id, {"owner", "admin"})
    org = await db.get(Organization, organization_id)
    assert org
    org.name = body.name
    await db.commit()
    return org


@router.get("/{organization_id}/members")
async def members(organization_id: UUID, user: CurrentUser, db: DB) -> list[dict[str, object]]:
    await require_membership(db, organization_id, user.id)
    rows = await db.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.organization_id == organization_id)
        .order_by(User.display_name)
    )
    return [
        {"user_id": m.user_id, "role": m.role, "email": u.email, "display_name": u.display_name}
        for m, u in rows
    ]


async def lock_org_and_member(db: DB, organization_id: UUID, user_id: UUID) -> Membership:
    await db.execute(
        select(Organization.id).where(Organization.id == organization_id).with_for_update()
    )
    member = await db.get(Membership, (organization_id, user_id))
    if member is None:
        raise AppError(404, "resource_not_found", "Member not found")
    return member


async def protect_final_owner(db: DB, organization_id: UUID, member: Membership) -> None:
    if member.role == "owner":
        owners = (
            await db.execute(
                select(Membership.user_id).where(
                    Membership.organization_id == organization_id, Membership.role == "owner"
                )
            )
        ).all()
        if len(owners) <= 1:
            raise AppError(409, "final_owner", "An organization must retain at least one owner")


@router.patch("/{organization_id}/members/{member_id}", status_code=204)
async def change_role(
    organization_id: UUID, member_id: UUID, body: RoleChange, user: CurrentUser, db: DB
) -> None:
    await require_membership(db, organization_id, user.id, {"owner"})
    member = await lock_org_and_member(db, organization_id, member_id)
    if body.role != "owner":
        await protect_final_owner(db, organization_id, member)
    member.role = body.role
    await db.commit()


@router.delete("/{organization_id}/members/{member_id}", status_code=204)
async def remove_member(organization_id: UUID, member_id: UUID, user: CurrentUser, db: DB) -> None:
    await require_membership(db, organization_id, user.id, {"owner", "admin"})
    member = await lock_org_and_member(db, organization_id, member_id)
    await protect_final_owner(db, organization_id, member)
    await db.delete(member)
    await db.commit()


@router.post("/{organization_id}/invitations", status_code=201)
async def invite(
    organization_id: UUID,
    body: InvitationCreate,
    user: CurrentUser,
    db: DB,
    request: Request,
    settings: Config,
) -> dict[str, object]:
    await enforce_rate_limit(
        request,
        scope="invitation",
        account=str(body.email),
        limit=settings.invitation_rate_limit,
        window=3600,
    )
    await require_membership(db, organization_id, user.id, {"owner", "admin"})
    raw = opaque_token()
    invitation = Invitation(
        organization_id=organization_id,
        invited_email=str(body.email).lower(),
        role=body.role,
        token_hash=token_hash(raw),
        inviter_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db.add(invitation)
    await db.flush()
    db.add(
        OutboxEvent(
            topic="email.invitation",
            payload={
                "invitation_id": str(invitation.id),
                "email": invitation.invited_email,
                "token": raw,
            },
        )
    )
    await db.commit()
    return {"id": invitation.id, "expires_at": invitation.expires_at}


@router.get("/{organization_id}/invitations")
async def invitations(organization_id: UUID, user: CurrentUser, db: DB) -> list[dict[str, object]]:
    await require_membership(db, organization_id, user.id, {"owner", "admin"})
    rows = (
        await db.execute(
            select(Invitation)
            .where(
                Invitation.organization_id == organization_id,
                Invitation.accepted_at.is_(None),
                Invitation.revoked_at.is_(None),
            )
            .limit(100)
        )
    ).scalars()
    return [
        {"id": x.id, "email": x.invited_email, "role": x.role, "expires_at": x.expires_at}
        for x in rows
    ]


@router.delete("/{organization_id}/invitations/{invitation_id}", status_code=204)
async def revoke_invitation(
    organization_id: UUID, invitation_id: UUID, user: CurrentUser, db: DB
) -> None:
    await require_membership(db, organization_id, user.id, {"owner", "admin"})
    invitation = (
        await db.execute(
            select(Invitation)
            .where(Invitation.id == invitation_id, Invitation.organization_id == organization_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if invitation is None:
        raise AppError(404, "resource_not_found", "Invitation not found")
    invitation.revoked_at = datetime.now(UTC)
    await db.commit()


@router.post("/invitations/accept", status_code=204)
async def accept_invitation(body: InvitationAccept, user: CurrentUser, db: DB) -> None:
    invitation = (
        await db.execute(
            select(Invitation)
            .where(Invitation.token_hash == token_hash(body.token))
            .with_for_update()
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if invitation is None or invitation.revoked_at or invitation.expires_at <= now:
        raise AppError(400, "invalid_invitation", "Invitation is invalid or expired")
    if invitation.invited_email != user.email:
        raise AppError(403, "invitation_email_mismatch", "Invitation belongs to another account")
    existing = await db.get(Membership, (invitation.organization_id, user.id))
    if existing is None:
        db.add(
            Membership(
                organization_id=invitation.organization_id, user_id=user.id, role=invitation.role
            )
        )
    invitation.accepted_at = invitation.accepted_at or now
    await db.commit()

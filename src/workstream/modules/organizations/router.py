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
from workstream.modules.models import (
    Invitation,
    Membership,
    Organization,
    User,
)
from workstream.modules.organizations import service

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.post("", response_model=OrganizationOut, status_code=201)
async def create(
    body: OrganizationCreate, user: CurrentUser, db: DB, request: Request
) -> Organization:
    return await service.create(db, user, body, request.state.request_id)


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
    return await service.update(db, organization_id, user, body)


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


@router.patch("/{organization_id}/members/{member_id}", status_code=204)
async def change_role(
    organization_id: UUID, member_id: UUID, body: RoleChange, user: CurrentUser, db: DB
) -> None:
    await service.change_role(db, organization_id, member_id, user, body)


@router.delete("/{organization_id}/members/{member_id}", status_code=204)
async def remove_member(organization_id: UUID, member_id: UUID, user: CurrentUser, db: DB) -> None:
    await service.remove_member(db, organization_id, member_id, user)


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
    invitation = await service.invite(db, organization_id, user, body)
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
    await service.revoke_invitation(db, organization_id, invitation_id, user)


@router.post("/invitations/accept", status_code=204)
async def accept_invitation(body: InvitationAccept, user: CurrentUser, db: DB) -> None:
    await service.accept(db, user, body)

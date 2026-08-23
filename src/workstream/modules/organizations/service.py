from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from workstream.api.dependencies import require_membership
from workstream.api.schemas import (
    InvitationAccept,
    InvitationCreate,
    OrganizationCreate,
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


async def create(
    db: AsyncSession, user: User, body: OrganizationCreate, request_id: str
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
            request_id=request_id,
        )
    )
    await db.commit()
    return org


async def update(
    db: AsyncSession, organization_id: UUID, user: User, body: OrganizationUpdate
) -> Organization:
    await require_membership(db, organization_id, user.id, {"owner", "admin"})
    org = await db.get(Organization, organization_id)
    if org is None:
        raise AppError(404, "resource_not_found", "Organization not found")
    org.name = body.name
    db.add(
        AuditEvent(
            actor_id=user.id,
            organization_id=organization_id,
            action="organization.updated",
            entity_type="organization",
            entity_id=org.id,
        )
    )
    await db.commit()
    return org


async def lock_member(db: AsyncSession, organization_id: UUID, user_id: UUID) -> Membership:
    await db.execute(
        select(Organization.id).where(Organization.id == organization_id).with_for_update()
    )
    member = await db.get(Membership, (organization_id, user_id))
    if member is None:
        raise AppError(404, "resource_not_found", "Member not found")
    return member


async def protect_owner(db: AsyncSession, organization_id: UUID, member: Membership) -> None:
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


async def change_role(
    db: AsyncSession, organization_id: UUID, member_id: UUID, actor: User, body: RoleChange
) -> None:
    await require_membership(db, organization_id, actor.id, {"owner"})
    member = await lock_member(db, organization_id, member_id)
    if body.role != "owner":
        await protect_owner(db, organization_id, member)
    previous = member.role
    member.role = body.role
    db.add(
        AuditEvent(
            actor_id=actor.id,
            organization_id=organization_id,
            action="membership.role_changed",
            entity_type="membership",
            entity_id=member_id,
            metadata_={"from": previous, "to": body.role},
        )
    )
    await db.commit()


async def remove_member(
    db: AsyncSession, organization_id: UUID, member_id: UUID, actor: User
) -> None:
    await require_membership(db, organization_id, actor.id, {"owner", "admin"})
    member = await lock_member(db, organization_id, member_id)
    await protect_owner(db, organization_id, member)
    await db.delete(member)
    db.add(
        AuditEvent(
            actor_id=actor.id,
            organization_id=organization_id,
            action="membership.removed",
            entity_type="membership",
            entity_id=member_id,
        )
    )
    await db.commit()


async def invite(
    db: AsyncSession, organization_id: UUID, actor: User, body: InvitationCreate
) -> Invitation:
    await require_membership(db, organization_id, actor.id, {"owner", "admin"})
    raw = opaque_token()
    invitation = Invitation(
        organization_id=organization_id,
        invited_email=str(body.email).lower(),
        role=body.role,
        token_hash=token_hash(raw),
        inviter_id=actor.id,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db.add(invitation)
    await db.flush()
    db.add(
        AuditEvent(
            actor_id=actor.id,
            organization_id=organization_id,
            action="invitation.created",
            entity_type="invitation",
            entity_id=invitation.id,
            metadata_={"email": invitation.invited_email, "role": invitation.role},
        )
    )
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
    return invitation


async def revoke_invitation(
    db: AsyncSession, organization_id: UUID, invitation_id: UUID, actor: User
) -> None:
    await require_membership(db, organization_id, actor.id, {"owner", "admin"})
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
    db.add(
        AuditEvent(
            actor_id=actor.id,
            organization_id=organization_id,
            action="invitation.revoked",
            entity_type="invitation",
            entity_id=invitation.id,
        )
    )
    await db.commit()


async def accept(db: AsyncSession, actor: User, body: InvitationAccept) -> None:
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
    if invitation.invited_email != actor.email:
        raise AppError(403, "invitation_email_mismatch", "Invitation belongs to another account")
    if invitation.accepted_at is not None:
        return
    if await db.get(Membership, (invitation.organization_id, actor.id)) is None:
        db.add(
            Membership(
                organization_id=invitation.organization_id, user_id=actor.id, role=invitation.role
            )
        )
    invitation.accepted_at = invitation.accepted_at or now
    db.add(
        AuditEvent(
            actor_id=actor.id,
            organization_id=invitation.organization_id,
            action="invitation.accepted",
            entity_type="invitation",
            entity_id=invitation.id,
        )
    )
    await db.commit()

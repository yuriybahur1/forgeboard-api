from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import and_, or_, select

from workstream.api.dependencies import DB, CurrentUser, require_membership
from workstream.api.pagination import decode_cursor, encode_cursor
from workstream.modules.audit.schemas import AuditPage
from workstream.modules.models import AuditEvent

router = APIRouter(prefix="/organizations/{organization_id}/audit", tags=["audit"])


@router.get("", response_model=AuditPage)
async def list_(
    organization_id: UUID,
    user: CurrentUser,
    db: DB,
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=100),
) -> dict[str, object]:
    await require_membership(db, organization_id, user.id, {"owner", "admin"})
    stmt = select(AuditEvent).where(AuditEvent.organization_id == organization_id)
    if cursor:
        created, id_ = decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                AuditEvent.created_at < created,
                and_(AuditEvent.created_at == created, AuditEvent.id < id_),
            )
        )
    rows = list(
        (
            await db.scalars(
                stmt.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(limit + 1)
            )
        ).all()
    )
    items = rows[:limit]
    payload = [
        {
            "id": e.id,
            "actor_id": e.actor_id,
            "action": e.action,
            "entity_type": e.entity_type,
            "entity_id": e.entity_id,
            "metadata": e.metadata_,
            "request_id": e.request_id,
            "created_at": e.created_at,
        }
        for e in items
    ]
    return {
        "items": payload,
        "next_cursor": encode_cursor(items[-1].created_at, items[-1].id)
        if len(rows) > limit
        else None,
    }

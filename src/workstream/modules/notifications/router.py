from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import and_, or_, select

from workstream.api.dependencies import DB, CurrentUser
from workstream.api.pagination import decode_cursor, encode_cursor
from workstream.modules.models import Notification
from workstream.modules.notifications import service
from workstream.modules.notifications.schemas import NotificationPage, UnreadCount

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationPage)
async def list_(
    user: CurrentUser, db: DB, cursor: str | None = None, limit: int = Query(50, ge=1, le=100)
) -> dict[str, object]:
    stmt = select(Notification).where(Notification.user_id == user.id)
    if cursor:
        created, id_ = decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                Notification.created_at < created,
                and_(Notification.created_at == created, Notification.id < id_),
            )
        )
    rows = list(
        (
            await db.scalars(
                stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(
                    limit + 1
                )
            )
        ).all()
    )
    items = rows[:limit]
    return {
        "items": items,
        "next_cursor": encode_cursor(items[-1].created_at, items[-1].id)
        if len(rows) > limit
        else None,
    }


@router.get("/unread-count", response_model=UnreadCount)
async def unread(user: CurrentUser, db: DB) -> UnreadCount:
    return UnreadCount(count=await service.unread_count(db, user))


@router.post("/{notification_id}/read", status_code=204)
async def read(notification_id: UUID, user: CurrentUser, db: DB) -> None:
    await service.mark_read(db, user, notification_id)


@router.post("/read-all", status_code=204)
async def read_all(user: CurrentUser, db: DB) -> None:
    await service.mark_all_read(db, user)

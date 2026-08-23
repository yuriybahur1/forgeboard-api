from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from workstream.modules.models import Notification, User


async def unread_count(db: AsyncSession, user: User) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        )
    ).scalar_one()


async def mark_read(db: AsyncSession, user: User, notification_id: UUID) -> None:
    await db.execute(
        update(Notification)
        .where(Notification.id == notification_id, Notification.user_id == user.id)
        .values(read_at=datetime.now(UTC))
    )
    await db.commit()


async def mark_all_read(db: AsyncSession, user: User) -> None:
    await db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    await db.commit()

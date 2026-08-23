from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from workstream.api.dependencies import require_membership
from workstream.api.schemas import CommentCreate
from workstream.core.errors import AppError
from workstream.modules.issues.service import get_issue
from workstream.modules.models import Comment, User


async def get(db: AsyncSession, organization_id: UUID, comment_id: UUID) -> Comment:
    row = (
        await db.execute(
            select(Comment).where(
                Comment.id == comment_id, Comment.organization_id == organization_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise AppError(404, "resource_not_found", "Comment not found")
    return row


async def create(
    db: AsyncSession, organization_id: UUID, issue_id: UUID, user: User, body: CommentCreate
) -> Comment:
    await require_membership(db, organization_id, user.id, {"owner", "admin", "member"})
    await get_issue(db, organization_id, issue_id)
    row = Comment(
        organization_id=organization_id, issue_id=issue_id, author_id=user.id, body=body.body
    )
    db.add(row)
    await db.commit()
    return row


async def update(
    db: AsyncSession, organization_id: UUID, comment_id: UUID, user: User, body: CommentCreate
) -> Comment:
    await require_membership(db, organization_id, user.id)
    row = await get(db, organization_id, comment_id)
    if row.author_id != user.id:
        raise AppError(403, "insufficient_permission", "Only the author may edit this comment")
    row.body = body.body
    row.edited_at = datetime.now(UTC)
    await db.commit()
    return row


async def delete(db: AsyncSession, organization_id: UUID, comment_id: UUID, user: User) -> None:
    membership = await require_membership(db, organization_id, user.id)
    row = await get(db, organization_id, comment_id)
    if row.author_id != user.id and membership.role not in {"owner", "admin"}:
        raise AppError(403, "insufficient_permission", "Comment deletion is not permitted")
    await db.delete(row)
    await db.commit()

from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import and_, or_, select

from workstream.api.dependencies import DB, CurrentUser, require_membership
from workstream.api.pagination import decode_cursor, encode_cursor
from workstream.api.schemas import CommentCreate, CommentOut
from workstream.modules.comments import service
from workstream.modules.comments.schemas import CommentPage
from workstream.modules.issues.service import get_issue
from workstream.modules.models import Comment

router = APIRouter(tags=["comments"])


@router.post(
    "/organizations/{organization_id}/issues/{issue_id}/comments",
    response_model=CommentOut,
    status_code=201,
)
async def create(
    organization_id: UUID, issue_id: UUID, body: CommentCreate, user: CurrentUser, db: DB
) -> Comment:
    return await service.create(db, organization_id, issue_id, user, body)


@router.get(
    "/organizations/{organization_id}/issues/{issue_id}/comments", response_model=CommentPage
)
async def list_(
    organization_id: UUID,
    issue_id: UUID,
    user: CurrentUser,
    db: DB,
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=100),
) -> dict[str, object]:
    await require_membership(db, organization_id, user.id)
    await get_issue(db, organization_id, issue_id)
    stmt = select(Comment).where(
        Comment.issue_id == issue_id, Comment.organization_id == organization_id
    )
    if cursor:
        created, id_ = decode_cursor(cursor)
        stmt = stmt.where(
            or_(Comment.created_at < created, and_(Comment.created_at == created, Comment.id < id_))
        )
    rows = list(
        (
            await db.scalars(
                stmt.order_by(Comment.created_at.desc(), Comment.id.desc()).limit(limit + 1)
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


@router.patch("/organizations/{organization_id}/comments/{comment_id}", response_model=CommentOut)
async def update(
    organization_id: UUID, comment_id: UUID, body: CommentCreate, user: CurrentUser, db: DB
) -> Comment:
    return await service.update(db, organization_id, comment_id, user, body)


@router.delete("/organizations/{organization_id}/comments/{comment_id}", status_code=204)
async def delete(organization_id: UUID, comment_id: UUID, user: CurrentUser, db: DB) -> None:
    await service.delete(db, organization_id, comment_id, user)

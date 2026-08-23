from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import and_, asc, desc, or_, select

from workstream.api.dependencies import DB, CurrentUser, require_membership
from workstream.api.pagination import decode_cursor, encode_cursor
from workstream.api.schemas import (
    Assignment,
    CursorPage,
    IssueCreate,
    IssueOut,
    IssueUpdate,
    StatusChange,
)
from workstream.modules.issues import service
from workstream.modules.models import Issue, IssueLabel

router = APIRouter(prefix="/organizations/{organization_id}/issues", tags=["issues"])


@router.post("", response_model=IssueOut, status_code=201)
async def create(organization_id: UUID, body: IssueCreate, user: CurrentUser, db: DB) -> Issue:
    return await service.create_issue(db, organization_id, user, body)


@router.get("", response_model=CursorPage)
async def list_(
    organization_id: UUID,
    user: CurrentUser,
    db: DB,
    project_id: UUID | None = None,
    status: str | None = None,
    priority: str | None = None,
    assignee_id: UUID | None = None,
    reporter_id: UUID | None = None,
    label_id: UUID | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    due_from: date | None = None,
    due_to: date | None = None,
    search: str | None = None,
    sort: str = Query("created_desc", pattern="^(created_desc|created_asc)$"),
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=100),
) -> dict[str, object]:
    await require_membership(db, organization_id, user.id)
    stmt = select(Issue).where(
        Issue.organization_id == organization_id, Issue.archived_at.is_(None)
    )
    filters = [
        (Issue.project_id, project_id),
        (Issue.status, status),
        (Issue.priority, priority),
        (Issue.assignee_id, assignee_id),
        (Issue.reporter_id, reporter_id),
    ]
    for column, value in filters:
        if value is not None:
            stmt = stmt.where(column == value)
    if label_id:
        stmt = stmt.join(IssueLabel).where(IssueLabel.label_id == label_id)
    if created_from:
        stmt = stmt.where(Issue.created_at >= created_from)
    if created_to:
        stmt = stmt.where(Issue.created_at <= created_to)
    if due_from:
        stmt = stmt.where(Issue.due_date >= due_from)
    if due_to:
        stmt = stmt.where(Issue.due_date <= due_to)
    if search:
        stmt = stmt.where((Issue.title + " " + Issue.description).ilike(f"%{search}%"))
    descending = sort == "created_desc"
    if cursor:
        created, id_ = decode_cursor(cursor)
        comparison = (
            or_(Issue.created_at < created, and_(Issue.created_at == created, Issue.id < id_))
            if descending
            else or_(Issue.created_at > created, and_(Issue.created_at == created, Issue.id > id_))
        )
        stmt = stmt.where(comparison)
    direction = desc if descending else asc
    rows = list(
        (
            await db.scalars(
                stmt.order_by(direction(Issue.created_at), direction(Issue.id)).limit(limit + 1)
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


@router.get("/{issue_id}", response_model=IssueOut)
async def get(organization_id: UUID, issue_id: UUID, user: CurrentUser, db: DB) -> Issue:
    await require_membership(db, organization_id, user.id)
    return await service.get_issue(db, organization_id, issue_id)


@router.patch("/{issue_id}", response_model=IssueOut)
async def update(
    organization_id: UUID, issue_id: UUID, body: IssueUpdate, user: CurrentUser, db: DB
) -> Issue:
    return await service.update_issue(db, organization_id, issue_id, user, body)


@router.post("/{issue_id}/status", response_model=IssueOut)
async def status_(
    organization_id: UUID, issue_id: UUID, body: StatusChange, user: CurrentUser, db: DB
) -> Issue:
    return await service.change_status(db, organization_id, issue_id, user, body)


@router.post("/{issue_id}/assignment", response_model=IssueOut)
async def assignment(
    organization_id: UUID, issue_id: UUID, body: Assignment, user: CurrentUser, db: DB
) -> Issue:
    return await service.assign(db, organization_id, issue_id, user, body)


@router.delete("/{issue_id}", status_code=204)
async def delete(organization_id: UUID, issue_id: UUID, user: CurrentUser, db: DB) -> None:
    await service.archive(db, organization_id, issue_id, user)

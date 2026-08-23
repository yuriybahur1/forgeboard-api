import base64
import json
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import and_, delete, func, or_, select, update

from workstream.api.dependencies import DB, CurrentUser, require_membership
from workstream.api.schemas import (
    Assignment,
    CommentCreate,
    CommentOut,
    CursorPage,
    IssueCreate,
    IssueOut,
    IssueUpdate,
    LabelCreate,
    LabelOut,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
    StatusChange,
)
from workstream.core.errors import AppError
from workstream.modules.models import (
    AuditEvent,
    Comment,
    Issue,
    IssueLabel,
    Label,
    Membership,
    Notification,
    Project,
)

router = APIRouter(tags=["work management"])
TRANSITIONS = {
    "backlog": {"todo", "canceled"},
    "todo": {"backlog", "in_progress", "canceled"},
    "in_progress": {"todo", "done", "canceled"},
    "done": {"in_progress"},
    "canceled": {"backlog"},
}


@router.post(
    "/organizations/{organization_id}/projects", response_model=ProjectOut, status_code=201
)
async def create_project(
    organization_id: UUID, body: ProjectCreate, user: CurrentUser, db: DB
) -> Project:
    await require_membership(db, organization_id, user.id, {"owner", "admin", "member"})
    project = Project(organization_id=organization_id, **body.model_dump())
    db.add(project)
    await db.flush()
    db.add(
        AuditEvent(
            actor_id=user.id,
            organization_id=organization_id,
            action="project.created",
            entity_type="project",
            entity_id=project.id,
        )
    )
    await db.commit()
    return project


@router.get("/organizations/{organization_id}/projects", response_model=list[ProjectOut])
async def list_projects(
    organization_id: UUID, user: CurrentUser, db: DB, include_archived: bool = False
) -> list[Project]:
    await require_membership(db, organization_id, user.id)
    stmt = select(Project).where(Project.organization_id == organization_id)
    if not include_archived:
        stmt = stmt.where(Project.archived.is_(False))
    return list((await db.execute(stmt.order_by(Project.name).limit(100))).scalars())


async def scoped_project(db: DB, organization_id: UUID, project_id: UUID) -> Project:
    row = (
        await db.execute(
            select(Project).where(
                Project.id == project_id, Project.organization_id == organization_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise AppError(404, "resource_not_found", "Project not found")
    return row


@router.get("/organizations/{organization_id}/projects/{project_id}", response_model=ProjectOut)
async def get_project(
    organization_id: UUID, project_id: UUID, user: CurrentUser, db: DB
) -> Project:
    await require_membership(db, organization_id, user.id)
    return await scoped_project(db, organization_id, project_id)


@router.patch("/organizations/{organization_id}/projects/{project_id}", response_model=ProjectOut)
async def update_project(
    organization_id: UUID, project_id: UUID, body: ProjectUpdate, user: CurrentUser, db: DB
) -> Project:
    await require_membership(db, organization_id, user.id, {"owner", "admin", "member"})
    project = await scoped_project(db, organization_id, project_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(project, key, value)
    await db.commit()
    return project


@router.post("/organizations/{organization_id}/projects/{project_id}/archive", status_code=204)
async def archive_project(
    organization_id: UUID, project_id: UUID, user: CurrentUser, db: DB
) -> None:
    await require_membership(db, organization_id, user.id, {"owner", "admin"})
    (await scoped_project(db, organization_id, project_id)).archived = True
    await db.commit()


@router.post("/organizations/{organization_id}/projects/{project_id}/unarchive", status_code=204)
async def unarchive_project(
    organization_id: UUID, project_id: UUID, user: CurrentUser, db: DB
) -> None:
    await require_membership(db, organization_id, user.id, {"owner", "admin"})
    (await scoped_project(db, organization_id, project_id)).archived = False
    await db.commit()


async def validate_assignee(db: DB, organization_id: UUID, assignee_id: UUID | None) -> None:
    if assignee_id is not None and await db.get(Membership, (organization_id, assignee_id)) is None:
        raise AppError(422, "invalid_assignee", "Assignee must be an organization member")


@router.post("/organizations/{organization_id}/issues", response_model=IssueOut, status_code=201)
async def create_issue(
    organization_id: UUID, body: IssueCreate, user: CurrentUser, db: DB
) -> Issue:
    await require_membership(db, organization_id, user.id, {"owner", "admin", "member"})
    project = await scoped_project(db, organization_id, body.project_id)
    if project.archived:
        raise AppError(409, "project_archived", "Issues cannot be created in an archived project")
    await validate_assignee(db, organization_id, body.assignee_id)
    number = (
        await db.execute(
            update(Project)
            .where(Project.id == project.id)
            .values(next_issue_number=Project.next_issue_number + 1)
            .returning(Project.next_issue_number - 1)
        )
    ).scalar_one()
    issue = Issue(
        organization_id=organization_id, reporter_id=user.id, number=number, **body.model_dump()
    )
    db.add(issue)
    await db.flush()
    db.add(
        AuditEvent(
            actor_id=user.id,
            organization_id=organization_id,
            action="issue.created",
            entity_type="issue",
            entity_id=issue.id,
        )
    )
    if issue.assignee_id and issue.assignee_id != user.id:
        db.add(
            Notification(
                user_id=issue.assignee_id,
                organization_id=organization_id,
                kind="issue.assigned",
                payload={"issue_id": str(issue.id)},
            )
        )
    await db.commit()
    return issue


async def scoped_issue(db: DB, organization_id: UUID, issue_id: UUID) -> Issue:
    issue = (
        await db.execute(
            select(Issue).where(
                Issue.id == issue_id,
                Issue.organization_id == organization_id,
                Issue.archived_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if issue is None:
        raise AppError(404, "resource_not_found", "Issue not found")
    return issue


def encode_cursor(issue: Issue) -> str:
    return (
        base64.urlsafe_b64encode(json.dumps([issue.created_at.isoformat(), str(issue.id)]).encode())
        .decode()
        .rstrip("=")
    )


def decode_cursor(value: str) -> tuple[datetime, UUID]:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        created, id_ = json.loads(raw)
        return datetime.fromisoformat(created), UUID(id_)
    except (ValueError, TypeError, json.JSONDecodeError):
        raise AppError(400, "invalid_cursor", "Cursor is malformed") from None


@router.get("/organizations/{organization_id}/issues", response_model=CursorPage)
async def list_issues(
    organization_id: UUID,
    user: CurrentUser,
    db: DB,
    project_id: UUID | None = None,
    status: str | None = None,
    priority: str | None = None,
    assignee_id: UUID | None = None,
    label_id: UUID | None = None,
    search: str | None = None,
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=100),
) -> dict[str, object]:
    await require_membership(db, organization_id, user.id)
    stmt = select(Issue).where(
        Issue.organization_id == organization_id, Issue.archived_at.is_(None)
    )
    if project_id:
        stmt = stmt.where(Issue.project_id == project_id)
    if status:
        stmt = stmt.where(Issue.status == status)
    if priority:
        stmt = stmt.where(Issue.priority == priority)
    if assignee_id:
        stmt = stmt.where(Issue.assignee_id == assignee_id)
    if label_id:
        stmt = stmt.join(IssueLabel).where(IssueLabel.label_id == label_id)
    if search:
        stmt = stmt.where(
            or_(Issue.title.ilike(f"%{search}%"), Issue.description.ilike(f"%{search}%"))
        )
    if cursor:
        created, id_ = decode_cursor(cursor)
        stmt = stmt.where(
            or_(Issue.created_at < created, and_(Issue.created_at == created, Issue.id < id_))
        )
    rows = list(
        (
            await db.execute(
                stmt.order_by(Issue.created_at.desc(), Issue.id.desc()).limit(limit + 1)
            )
        ).scalars()
    )
    more = len(rows) > limit
    items = rows[:limit]
    return {"items": items, "next_cursor": encode_cursor(items[-1]) if more else None}


@router.get("/organizations/{organization_id}/issues/{issue_id}", response_model=IssueOut)
async def get_issue(organization_id: UUID, issue_id: UUID, user: CurrentUser, db: DB) -> Issue:
    await require_membership(db, organization_id, user.id)
    return await scoped_issue(db, organization_id, issue_id)


async def optimistic_update(
    db: DB, issue: Issue, expected: int, values: dict[str, object]
) -> Issue:
    values["version"] = Issue.version + 1
    result = await db.execute(
        update(Issue)
        .where(
            Issue.id == issue.id,
            Issue.organization_id == issue.organization_id,
            Issue.version == expected,
        )
        .values(**values)
        .returning(Issue)
    )
    updated = result.scalar_one_or_none()
    if updated is None:
        raise AppError(409, "stale_issue_version", "Issue was modified by another client")
    return updated


@router.patch("/organizations/{organization_id}/issues/{issue_id}", response_model=IssueOut)
async def update_issue(
    organization_id: UUID, issue_id: UUID, body: IssueUpdate, user: CurrentUser, db: DB
) -> Issue:
    await require_membership(db, organization_id, user.id, {"owner", "admin", "member"})
    issue = await scoped_issue(db, organization_id, issue_id)
    values = body.model_dump(exclude={"expected_version"}, exclude_unset=True)
    updated = await optimistic_update(db, issue, body.expected_version, values)
    await db.commit()
    return updated


@router.post("/organizations/{organization_id}/issues/{issue_id}/status", response_model=IssueOut)
async def change_status(
    organization_id: UUID, issue_id: UUID, body: StatusChange, user: CurrentUser, db: DB
) -> Issue:
    await require_membership(db, organization_id, user.id, {"owner", "admin", "member"})
    issue = await scoped_issue(db, organization_id, issue_id)
    if body.status not in TRANSITIONS.get(issue.status, set()):
        raise AppError(
            409,
            "invalid_status_transition",
            f"Cannot transition from {issue.status} to {body.status}",
        )
    updated = await optimistic_update(db, issue, body.expected_version, {"status": body.status})
    db.add(
        AuditEvent(
            actor_id=user.id,
            organization_id=organization_id,
            action="issue.status_changed",
            entity_type="issue",
            entity_id=issue.id,
            metadata_={"from": issue.status, "to": body.status},
        )
    )
    await db.commit()
    return updated


@router.post(
    "/organizations/{organization_id}/issues/{issue_id}/assignment", response_model=IssueOut
)
async def assign(
    organization_id: UUID, issue_id: UUID, body: Assignment, user: CurrentUser, db: DB
) -> Issue:
    await require_membership(db, organization_id, user.id, {"owner", "admin", "member"})
    await validate_assignee(db, organization_id, body.assignee_id)
    issue = await scoped_issue(db, organization_id, issue_id)
    updated = await optimistic_update(
        db, issue, body.expected_version, {"assignee_id": body.assignee_id}
    )
    if body.assignee_id and body.assignee_id != user.id:
        db.add(
            Notification(
                user_id=body.assignee_id,
                organization_id=organization_id,
                kind="issue.assigned",
                payload={"issue_id": str(issue.id)},
            )
        )
    await db.commit()
    return updated


@router.delete("/organizations/{organization_id}/issues/{issue_id}", status_code=204)
async def archive_issue(organization_id: UUID, issue_id: UUID, user: CurrentUser, db: DB) -> None:
    await require_membership(db, organization_id, user.id, {"owner", "admin"})
    issue = await scoped_issue(db, organization_id, issue_id)
    issue.archived_at = datetime.now(UTC)
    await db.commit()


@router.post("/organizations/{organization_id}/labels", response_model=LabelOut, status_code=201)
async def create_label(
    organization_id: UUID, body: LabelCreate, user: CurrentUser, db: DB
) -> Label:
    await require_membership(db, organization_id, user.id, {"owner", "admin", "member"})
    label = Label(organization_id=organization_id, **body.model_dump())
    db.add(label)
    await db.commit()
    return label


@router.get("/organizations/{organization_id}/labels", response_model=list[LabelOut])
async def list_labels(organization_id: UUID, user: CurrentUser, db: DB) -> list[Label]:
    await require_membership(db, organization_id, user.id)
    return list(
        (
            await db.execute(
                select(Label)
                .where(Label.organization_id == organization_id)
                .order_by(Label.name)
                .limit(200)
            )
        ).scalars()
    )


@router.patch("/organizations/{organization_id}/labels/{label_id}", response_model=LabelOut)
async def update_label(
    organization_id: UUID, label_id: UUID, body: LabelCreate, user: CurrentUser, db: DB
) -> Label:
    await require_membership(db, organization_id, user.id, {"owner", "admin", "member"})
    label = (
        await db.execute(
            select(Label).where(Label.id == label_id, Label.organization_id == organization_id)
        )
    ).scalar_one_or_none()
    if label is None:
        raise AppError(404, "resource_not_found", "Label not found")
    label.name, label.color = body.name, body.color
    await db.commit()
    return label


@router.delete("/organizations/{organization_id}/labels/{label_id}", status_code=204)
async def delete_label(organization_id: UUID, label_id: UUID, user: CurrentUser, db: DB) -> None:
    await require_membership(db, organization_id, user.id, {"owner", "admin"})
    await db.execute(
        delete(Label).where(Label.id == label_id, Label.organization_id == organization_id)
    )
    await db.commit()


@router.put("/organizations/{organization_id}/issues/{issue_id}/labels/{label_id}", status_code=204)
async def attach_label(
    organization_id: UUID, issue_id: UUID, label_id: UUID, user: CurrentUser, db: DB
) -> None:
    await require_membership(db, organization_id, user.id, {"owner", "admin", "member"})
    await scoped_issue(db, organization_id, issue_id)
    label = (
        await db.execute(
            select(Label.id).where(Label.id == label_id, Label.organization_id == organization_id)
        )
    ).scalar_one_or_none()
    if label is None:
        raise AppError(404, "resource_not_found", "Label not found")
    if await db.get(IssueLabel, (issue_id, label_id)) is None:
        db.add(IssueLabel(issue_id=issue_id, label_id=label_id))
    await db.commit()


@router.delete(
    "/organizations/{organization_id}/issues/{issue_id}/labels/{label_id}", status_code=204
)
async def detach_label(
    organization_id: UUID, issue_id: UUID, label_id: UUID, user: CurrentUser, db: DB
) -> None:
    await require_membership(db, organization_id, user.id, {"owner", "admin", "member"})
    await scoped_issue(db, organization_id, issue_id)
    await db.execute(
        delete(IssueLabel).where(IssueLabel.issue_id == issue_id, IssueLabel.label_id == label_id)
    )
    await db.commit()


@router.post(
    "/organizations/{organization_id}/issues/{issue_id}/comments",
    response_model=CommentOut,
    status_code=201,
)
async def create_comment(
    organization_id: UUID, issue_id: UUID, body: CommentCreate, user: CurrentUser, db: DB
) -> Comment:
    await require_membership(db, organization_id, user.id, {"owner", "admin", "member"})
    await scoped_issue(db, organization_id, issue_id)
    comment = Comment(
        organization_id=organization_id, issue_id=issue_id, author_id=user.id, body=body.body
    )
    db.add(comment)
    await db.commit()
    return comment


@router.get(
    "/organizations/{organization_id}/issues/{issue_id}/comments", response_model=list[CommentOut]
)
async def list_comments(
    organization_id: UUID,
    issue_id: UUID,
    user: CurrentUser,
    db: DB,
    limit: int = Query(50, ge=1, le=100),
) -> list[Comment]:
    await require_membership(db, organization_id, user.id)
    await scoped_issue(db, organization_id, issue_id)
    return list(
        (
            await db.execute(
                select(Comment)
                .where(Comment.issue_id == issue_id, Comment.organization_id == organization_id)
                .order_by(Comment.created_at.desc(), Comment.id.desc())
                .limit(limit)
            )
        ).scalars()
    )


@router.patch("/organizations/{organization_id}/comments/{comment_id}", response_model=CommentOut)
async def update_comment(
    organization_id: UUID, comment_id: UUID, body: CommentCreate, user: CurrentUser, db: DB
) -> Comment:
    await require_membership(db, organization_id, user.id)
    comment = (
        await db.execute(
            select(Comment).where(
                Comment.id == comment_id, Comment.organization_id == organization_id
            )
        )
    ).scalar_one_or_none()
    if comment is None:
        raise AppError(404, "resource_not_found", "Comment not found")
    if comment.author_id != user.id:
        raise AppError(403, "insufficient_permission", "Only the author may edit this comment")
    comment.body, comment.edited_at = body.body, datetime.now(UTC)
    await db.commit()
    return comment


@router.delete("/organizations/{organization_id}/comments/{comment_id}", status_code=204)
async def delete_comment(
    organization_id: UUID, comment_id: UUID, user: CurrentUser, db: DB
) -> None:
    membership = await require_membership(db, organization_id, user.id)
    comment = (
        await db.execute(
            select(Comment).where(
                Comment.id == comment_id, Comment.organization_id == organization_id
            )
        )
    ).scalar_one_or_none()
    if comment is None:
        raise AppError(404, "resource_not_found", "Comment not found")
    if comment.author_id != user.id and membership.role not in {"owner", "admin"}:
        raise AppError(403, "insufficient_permission", "Comment deletion is not permitted")
    await db.delete(comment)
    await db.commit()


@router.get("/notifications")
async def notifications(
    user: CurrentUser, db: DB, limit: int = Query(50, ge=1, le=100)
) -> list[dict[str, object]]:
    rows = (
        await db.execute(
            select(Notification)
            .where(Notification.user_id == user.id)
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(limit)
        )
    ).scalars()
    return [
        {
            "id": n.id,
            "kind": n.kind,
            "payload": n.payload,
            "created_at": n.created_at,
            "read_at": n.read_at,
        }
        for n in rows
    ]


@router.get("/notifications/unread-count")
async def unread_count(user: CurrentUser, db: DB) -> dict[str, int]:
    count = (
        await db.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        )
    ).scalar_one()
    return {"count": count}


@router.post("/notifications/{notification_id}/read", status_code=204)
async def mark_read(notification_id: UUID, user: CurrentUser, db: DB) -> None:
    await db.execute(
        update(Notification)
        .where(Notification.id == notification_id, Notification.user_id == user.id)
        .values(read_at=datetime.now(UTC))
    )
    await db.commit()


@router.post("/notifications/read-all", status_code=204)
async def mark_all_read(user: CurrentUser, db: DB) -> None:
    await db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    await db.commit()


@router.get("/organizations/{organization_id}/audit")
async def audit_log(
    organization_id: UUID, user: CurrentUser, db: DB, limit: int = Query(50, ge=1, le=100)
) -> list[dict[str, object]]:
    await require_membership(db, organization_id, user.id, {"owner", "admin"})
    rows = (
        await db.execute(
            select(AuditEvent)
            .where(AuditEvent.organization_id == organization_id)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(limit)
        )
    ).scalars()
    return [
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
        for e in rows
    ]

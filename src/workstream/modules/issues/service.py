from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from workstream.api.dependencies import require_membership
from workstream.api.schemas import Assignment, IssueCreate, IssueUpdate, StatusChange
from workstream.core.errors import AppError
from workstream.modules.issues.policies import can_transition
from workstream.modules.models import AuditEvent, Issue, Membership, Notification, Project, User
from workstream.modules.projects.service import get_project


async def get_issue(db: AsyncSession, organization_id: UUID, issue_id: UUID) -> Issue:
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


async def validate_assignee(
    db: AsyncSession, organization_id: UUID, assignee_id: UUID | None
) -> None:
    if assignee_id is None:
        return
    active_member = await db.scalar(
        select(Membership.user_id)
        .join(User, User.id == Membership.user_id)
        .where(
            Membership.organization_id == organization_id,
            Membership.user_id == assignee_id,
            User.is_active.is_(True),
        )
    )
    if active_member is None:
        raise AppError(422, "invalid_assignee", "Assignee must be an organization member")


async def create_issue(
    db: AsyncSession, organization_id: UUID, user: User, body: IssueCreate
) -> Issue:
    await require_membership(db, organization_id, user.id, {"owner", "admin", "member"})
    project = await get_project(db, organization_id, body.project_id)
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


async def optimistic_update(
    db: AsyncSession, issue: Issue, expected: int, values: dict[str, object]
) -> Issue:
    values["version"] = Issue.version + 1
    updated = (
        await db.execute(
            update(Issue)
            .where(
                Issue.id == issue.id,
                Issue.organization_id == issue.organization_id,
                Issue.version == expected,
            )
            .values(**values)
            .returning(Issue)
        )
    ).scalar_one_or_none()
    if updated is None:
        raise AppError(409, "stale_issue_version", "Issue was modified by another client")
    return updated


async def update_issue(
    db: AsyncSession, organization_id: UUID, issue_id: UUID, user: User, body: IssueUpdate
) -> Issue:
    await require_membership(db, organization_id, user.id, {"owner", "admin", "member"})
    issue = await get_issue(db, organization_id, issue_id)
    result = await optimistic_update(
        db,
        issue,
        body.expected_version,
        body.model_dump(exclude={"expected_version"}, exclude_unset=True),
    )
    await db.commit()
    return result


async def change_status(
    db: AsyncSession, organization_id: UUID, issue_id: UUID, user: User, body: StatusChange
) -> Issue:
    await require_membership(db, organization_id, user.id, {"owner", "admin", "member"})
    issue = await get_issue(db, organization_id, issue_id)
    if not can_transition(issue.status, body.status):
        raise AppError(
            409,
            "invalid_status_transition",
            f"Cannot transition from {issue.status} to {body.status}",
        )
    result = await optimistic_update(db, issue, body.expected_version, {"status": body.status})
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
    return result


async def assign(
    db: AsyncSession, organization_id: UUID, issue_id: UUID, user: User, body: Assignment
) -> Issue:
    await require_membership(db, organization_id, user.id, {"owner", "admin", "member"})
    await validate_assignee(db, organization_id, body.assignee_id)
    issue = await get_issue(db, organization_id, issue_id)
    result = await optimistic_update(
        db, issue, body.expected_version, {"assignee_id": body.assignee_id}
    )
    db.add(
        AuditEvent(
            actor_id=user.id,
            organization_id=organization_id,
            action="issue.assigned",
            entity_type="issue",
            entity_id=issue.id,
            metadata_={"assignee_id": str(body.assignee_id) if body.assignee_id else None},
        )
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
    return result


async def archive(db: AsyncSession, organization_id: UUID, issue_id: UUID, user: User) -> None:
    await require_membership(db, organization_id, user.id, {"owner", "admin"})
    issue = await get_issue(db, organization_id, issue_id)
    issue.archived_at = datetime.now(UTC)
    await db.commit()

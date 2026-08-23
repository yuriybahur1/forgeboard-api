from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from workstream.api.dependencies import require_membership
from workstream.api.schemas import LabelCreate
from workstream.core.errors import AppError
from workstream.modules.issues.service import get_issue
from workstream.modules.models import IssueLabel, Label, User


async def create(db: AsyncSession, organization_id: UUID, user: User, body: LabelCreate) -> Label:
    await require_membership(db, organization_id, user.id, {"owner", "admin", "member"})
    label = Label(organization_id=organization_id, **body.model_dump())
    db.add(label)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if getattr(getattr(exc.orig, "diag", None), "constraint_name", None) == (
            "uq_labels_organization_id_name"
        ):
            raise AppError(
                409, "label_name_conflict", "Label name is already in use in this organization"
            ) from exc
        raise
    return label


async def get(db: AsyncSession, organization_id: UUID, label_id: UUID) -> Label:
    label = (
        await db.execute(
            select(Label).where(Label.id == label_id, Label.organization_id == organization_id)
        )
    ).scalar_one_or_none()
    if label is None:
        raise AppError(404, "resource_not_found", "Label not found")
    return label


async def update_(
    db: AsyncSession, organization_id: UUID, label_id: UUID, user: User, body: LabelCreate
) -> Label:
    await require_membership(db, organization_id, user.id, {"owner", "admin", "member"})
    label = await get(db, organization_id, label_id)
    label.name = body.name
    label.color = body.color
    await db.commit()
    return label


async def delete_(db: AsyncSession, organization_id: UUID, label_id: UUID, user: User) -> None:
    await require_membership(db, organization_id, user.id, {"owner", "admin"})
    await get(db, organization_id, label_id)
    await db.execute(delete(Label).where(Label.id == label_id))
    await db.commit()


async def attach(
    db: AsyncSession, organization_id: UUID, issue_id: UUID, label_id: UUID, user: User
) -> None:
    await require_membership(db, organization_id, user.id, {"owner", "admin", "member"})
    await get_issue(db, organization_id, issue_id)
    await get(db, organization_id, label_id)
    await db.execute(
        insert(IssueLabel)
        .values(issue_id=issue_id, label_id=label_id)
        .on_conflict_do_nothing(index_elements=[IssueLabel.issue_id, IssueLabel.label_id])
    )
    await db.commit()


async def detach(
    db: AsyncSession, organization_id: UUID, issue_id: UUID, label_id: UUID, user: User
) -> None:
    await require_membership(db, organization_id, user.id, {"owner", "admin", "member"})
    await get_issue(db, organization_id, issue_id)
    await get(db, organization_id, label_id)
    await db.execute(
        delete(IssueLabel).where(IssueLabel.issue_id == issue_id, IssueLabel.label_id == label_id)
    )
    await db.commit()

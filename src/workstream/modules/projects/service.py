from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from workstream.api.dependencies import require_membership
from workstream.api.schemas import ProjectCreate, ProjectUpdate
from workstream.core.errors import AppError
from workstream.modules.models import AuditEvent, Project, User


async def get_project(db: AsyncSession, organization_id: UUID, project_id: UUID) -> Project:
    project = (
        await db.execute(
            select(Project).where(
                Project.id == project_id, Project.organization_id == organization_id
            )
        )
    ).scalar_one_or_none()
    if project is None:
        raise AppError(404, "resource_not_found", "Project not found")
    return project


async def create_project(
    db: AsyncSession, organization_id: UUID, user: User, body: ProjectCreate
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


async def update_project(
    db: AsyncSession, organization_id: UUID, project_id: UUID, user: User, body: ProjectUpdate
) -> Project:
    await require_membership(db, organization_id, user.id, {"owner", "admin", "member"})
    project = await get_project(db, organization_id, project_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(project, key, value)
    await db.commit()
    return project


async def set_archived(
    db: AsyncSession, organization_id: UUID, project_id: UUID, user: User, archived: bool
) -> None:
    await require_membership(db, organization_id, user.id, {"owner", "admin"})
    project = await get_project(db, organization_id, project_id)
    project.archived = archived
    db.add(
        AuditEvent(
            actor_id=user.id,
            organization_id=organization_id,
            action="project.archived" if archived else "project.unarchived",
            entity_type="project",
            entity_id=project.id,
        )
    )
    await db.commit()

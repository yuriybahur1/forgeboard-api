from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import select

from workstream.api.dependencies import DB, CurrentUser, require_membership
from workstream.api.schemas import ProjectCreate, ProjectOut, ProjectUpdate
from workstream.modules.models import Project
from workstream.modules.projects import service

router = APIRouter(prefix="/organizations/{organization_id}/projects", tags=["projects"])


@router.post("", response_model=ProjectOut, status_code=201)
async def create(organization_id: UUID, body: ProjectCreate, user: CurrentUser, db: DB) -> Project:
    return await service.create_project(db, organization_id, user, body)


@router.get("", response_model=list[ProjectOut])
async def list_(
    organization_id: UUID, user: CurrentUser, db: DB, include_archived: bool = False
) -> list[Project]:
    await require_membership(db, organization_id, user.id)
    stmt = select(Project).where(Project.organization_id == organization_id)
    if not include_archived:
        stmt = stmt.where(Project.archived.is_(False))
    return list((await db.scalars(stmt.order_by(Project.name).limit(100))).all())


@router.get("/{project_id}", response_model=ProjectOut)
async def get(organization_id: UUID, project_id: UUID, user: CurrentUser, db: DB) -> Project:
    await require_membership(db, organization_id, user.id)
    return await service.get_project(db, organization_id, project_id)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update(
    organization_id: UUID, project_id: UUID, body: ProjectUpdate, user: CurrentUser, db: DB
) -> Project:
    return await service.update_project(db, organization_id, project_id, user, body)


@router.post("/{project_id}/archive", status_code=204)
async def archive(organization_id: UUID, project_id: UUID, user: CurrentUser, db: DB) -> None:
    await service.set_archived(db, organization_id, project_id, user, True)


@router.post("/{project_id}/unarchive", status_code=204)
async def unarchive(organization_id: UUID, project_id: UUID, user: CurrentUser, db: DB) -> None:
    await service.set_archived(db, organization_id, project_id, user, False)

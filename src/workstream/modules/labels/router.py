from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import select

from workstream.api.dependencies import DB, CurrentUser, require_membership
from workstream.api.schemas import LabelCreate, LabelOut
from workstream.modules.labels import service
from workstream.modules.models import Label

router = APIRouter(tags=["labels"])


@router.post("/organizations/{organization_id}/labels", response_model=LabelOut, status_code=201)
async def create(organization_id: UUID, body: LabelCreate, user: CurrentUser, db: DB) -> Label:
    return await service.create(db, organization_id, user, body)


@router.get("/organizations/{organization_id}/labels", response_model=list[LabelOut])
async def list_(organization_id: UUID, user: CurrentUser, db: DB) -> list[Label]:
    await require_membership(db, organization_id, user.id)
    return list(
        (
            await db.scalars(
                select(Label)
                .where(Label.organization_id == organization_id)
                .order_by(Label.name)
                .limit(200)
            )
        ).all()
    )


@router.patch("/organizations/{organization_id}/labels/{label_id}", response_model=LabelOut)
async def update(
    organization_id: UUID, label_id: UUID, body: LabelCreate, user: CurrentUser, db: DB
) -> Label:
    return await service.update_(db, organization_id, label_id, user, body)


@router.delete("/organizations/{organization_id}/labels/{label_id}", status_code=204)
async def delete(organization_id: UUID, label_id: UUID, user: CurrentUser, db: DB) -> None:
    await service.delete_(db, organization_id, label_id, user)


@router.put("/organizations/{organization_id}/issues/{issue_id}/labels/{label_id}", status_code=204)
async def attach(
    organization_id: UUID, issue_id: UUID, label_id: UUID, user: CurrentUser, db: DB
) -> None:
    await service.attach(db, organization_id, issue_id, label_id, user)


@router.delete(
    "/organizations/{organization_id}/issues/{issue_id}/labels/{label_id}", status_code=204
)
async def detach(
    organization_id: UUID, issue_id: UUID, label_id: UUID, user: CurrentUser, db: DB
) -> None:
    await service.detach(db, organization_id, issue_id, label_id, user)

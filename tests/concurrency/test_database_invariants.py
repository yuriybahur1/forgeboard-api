import asyncio

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from workstream.api.schemas import InvitationAccept, IssueCreate, IssueUpdate, RoleChange
from workstream.core.errors import AppError
from workstream.core.security import hash_password, opaque_token, token_hash
from workstream.modules.issues.service import create_issue, update_issue
from workstream.modules.labels.service import attach
from workstream.modules.models import (
    Invitation,
    Issue,
    IssueLabel,
    Label,
    Membership,
    Organization,
    Project,
    User,
)
from workstream.modules.organizations.router import accept_invitation, change_role, remove_member

pytestmark = [pytest.mark.integration, pytest.mark.concurrency]


async def test_concurrent_registration_uniqueness(client: AsyncClient) -> None:
    payload = {"email": "race@example.com", "password": "ValidPassword123!", "display_name": "Race"}
    responses = await asyncio.gather(
        client.post("/api/v1/auth/register", json=payload),
        client.post("/api/v1/auth/register", json=payload),
    )
    assert sorted(response.status_code for response in responses) == [201, 409]


async def test_concurrent_organization_slug_conflict_is_stable(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    payloads = [
        {"name": "Race One", "slug": "organization-race"},
        {"name": "Race Two", "slug": "organization-race"},
    ]
    responses = await asyncio.gather(
        *(client.post("/api/v1/organizations", headers=auth_headers, json=row) for row in payloads)
    )
    assert sorted(response.status_code for response in responses) == [201, 409]
    conflict = next(response for response in responses if response.status_code == 409)
    assert conflict.json()["code"] == "organization_slug_conflict"


async def test_atomic_issue_numbering(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as db:
        user = User(
            email="numbers@example.com",
            display_name="Numbers",
            password_hash=hash_password("ValidPassword123!"),
        )
        org = Organization(name="Numbers", slug="numbers")
        db.add_all([user, org])
        await db.flush()
        db.add(Membership(organization_id=org.id, user_id=user.id, role="owner"))
        project = Project(organization_id=org.id, name="Engineering", key="ENG")
        db.add(project)
        await db.commit()
        user_id, org_id, project_id = user.id, org.id, project.id

    async def create_one(index: int) -> int:
        async with session_factory() as db:
            actor = await db.get(User, user_id)
            assert actor
            issue = await create_issue(
                db, org_id, actor, IssueCreate(project_id=project_id, title=f"Issue {index}")
            )
            return issue.number

    numbers = await asyncio.gather(*(create_one(i) for i in range(12)))
    assert sorted(numbers) == list(range(1, 13)) and len(set(numbers)) == 12


async def test_concurrent_label_attachment_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        user = User(email="labels@example.com", display_name="Labels", password_hash="x")
        org = Organization(name="Labels", slug="labels")
        db.add_all([user, org])
        await db.flush()
        db.add(Membership(organization_id=org.id, user_id=user.id, role="owner"))
        project = Project(organization_id=org.id, name="Labels", key="LBL")
        db.add(project)
        await db.flush()
        issue = Issue(
            organization_id=org.id,
            project_id=project.id,
            number=1,
            title="Attach label",
            reporter_id=user.id,
        )
        label = Label(organization_id=org.id, name="race", color="#112233")
        db.add_all([issue, label])
        await db.commit()
        ids = user.id, org.id, issue.id, label.id

    async def attach_once() -> None:
        async with session_factory() as db:
            actor = await db.get(User, ids[0])
            assert actor is not None
            await attach(db, ids[1], ids[2], ids[3], actor)

    await asyncio.gather(attach_once(), attach_once())

    async with session_factory() as db:
        count = await db.scalar(
            select(func.count())
            .select_from(IssueLabel)
            .where(IssueLabel.issue_id == ids[2], IssueLabel.label_id == ids[3])
        )
        assert count == 1


async def test_concurrent_invitation_acceptance_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    raw = opaque_token()
    async with session_factory() as db:
        owner = User(email="inviter@example.com", display_name="Inviter", password_hash="x")
        invitee = User(email="invitee@example.com", display_name="Invitee", password_hash="x")
        org = Organization(name="Invite", slug="invite")
        db.add_all([owner, invitee, org])
        await db.flush()
        db.add(Membership(organization_id=org.id, user_id=owner.id, role="owner"))
        db.add(
            Invitation(
                organization_id=org.id,
                invited_email=invitee.email,
                role="member",
                token_hash=token_hash(raw),
                inviter_id=owner.id,
                expires_at=__import__("datetime").datetime.now(__import__("datetime").UTC)
                + __import__("datetime").timedelta(hours=1),
            )
        )
        await db.commit()
        invitee_id, org_id = invitee.id, org.id

    async def accept() -> object:
        async with session_factory() as db:
            actor = await db.get(User, invitee_id)
            assert actor
            try:
                return await accept_invitation(InvitationAccept(token=raw), actor, db)
            except AppError as exc:
                return exc.code

    await asyncio.gather(accept(), accept())
    async with session_factory() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(Membership)
                .where(Membership.organization_id == org_id, Membership.user_id == invitee_id)
            )
            == 1
        )
        invitation = await db.scalar(select(Invitation).where(Invitation.organization_id == org_id))
        assert invitation and invitation.accepted_at


async def test_concurrent_final_owner_demotion(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        one = User(email="one@example.com", display_name="One", password_hash="x")
        two = User(email="two@example.com", display_name="Two", password_hash="x")
        org = Organization(name="Owners", slug="owners")
        db.add_all([one, two, org])
        await db.flush()
        db.add_all(
            [
                Membership(organization_id=org.id, user_id=one.id, role="owner"),
                Membership(organization_id=org.id, user_id=two.id, role="owner"),
            ]
        )
        await db.commit()
        ids = one.id, two.id, org.id

    async def demote(actor_id, target_id):
        async with session_factory() as db:
            actor = await db.get(User, actor_id)
            assert actor
            try:
                await change_role(ids[2], target_id, RoleChange(role="member"), actor, db)
                return "ok"
            except AppError as exc:
                await db.rollback()
                return exc.code

    results = await asyncio.gather(demote(ids[0], ids[0]), demote(ids[1], ids[1]))
    assert sorted(results) == ["final_owner", "ok"]
    async with session_factory() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(Membership)
                .where(Membership.organization_id == ids[2], Membership.role == "owner")
            )
            == 1
        )


async def test_concurrent_final_owner_removal(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        one = User(email="remove-one@example.com", display_name="One", password_hash="x")
        two = User(email="remove-two@example.com", display_name="Two", password_hash="x")
        org = Organization(name="Remove Owners", slug="remove-owners")
        db.add_all([one, two, org])
        await db.flush()
        db.add_all(
            [
                Membership(organization_id=org.id, user_id=one.id, role="owner"),
                Membership(organization_id=org.id, user_id=two.id, role="owner"),
            ]
        )
        await db.commit()
        ids = one.id, two.id, org.id

    async def remove(actor_id, target_id):
        async with session_factory() as db:
            actor = await db.get(User, actor_id)
            assert actor
            try:
                await remove_member(ids[2], target_id, actor, db)
                return "ok"
            except AppError as exc:
                await db.rollback()
                return exc.code

    results = await asyncio.gather(remove(ids[0], ids[0]), remove(ids[1], ids[1]))
    assert sorted(results) == ["final_owner", "ok"]
    async with session_factory() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(Membership)
                .where(Membership.organization_id == ids[2], Membership.role == "owner")
            )
            == 1
        )


async def test_optimistic_update_allows_one_writer(
    session_factory: async_sessionmaker[AsyncSession], issue: Issue, user: User
) -> None:
    async def write(title: str):
        async with session_factory() as db:
            actor = await db.get(User, user.id)
            assert actor
            try:
                return await update_issue(
                    db,
                    issue.organization_id,
                    issue.id,
                    actor,
                    IssueUpdate(expected_version=1, title=title),
                )
            except AppError as exc:
                await db.rollback()
                return exc.code

    results = await asyncio.gather(write("one"), write("two"))
    assert sum(result == "stale_issue_version" for result in results) == 1

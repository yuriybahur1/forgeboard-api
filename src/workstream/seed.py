from uuid import NAMESPACE_DNS, UUID, uuid5

from sqlalchemy import select

from workstream.core.security import hash_password
from workstream.db.session import sync_session_factory
from workstream.modules.models import Comment, Issue, Label, Membership, Organization, Project, User

DEMO_USER_EMAILS = (
    "owner@demo.example.com",
    "member@demo.example.com",
    "viewer@demo.example.com",
)


def uid(name: str) -> UUID:
    return uuid5(NAMESPACE_DNS, f"workstream.local/{name}")


def main() -> None:
    with sync_session_factory.begin() as db:
        seed_user_ids = tuple(uid(role) for role in ("owner", "member", "viewer"))
        existing_seed_users = {
            user.id: user
            for user in db.scalars(select(User).where(User.id.in_(seed_user_ids))).all()
        }
        if seed_user_ids[0] in existing_seed_users:
            for user_id, email in zip(seed_user_ids, DEMO_USER_EMAILS, strict=True):
                if user := existing_seed_users.get(user_id):
                    user.email = email
            return
        users = [
            User(
                id=uid("owner"),
                email=DEMO_USER_EMAILS[0],
                display_name="Olivia Owner",
                password_hash=hash_password("DemoPassword123!"),
            ),
            User(
                id=uid("member"),
                email=DEMO_USER_EMAILS[1],
                display_name="Morgan Member",
                password_hash=hash_password("DemoPassword123!"),
            ),
            User(
                id=uid("viewer"),
                email=DEMO_USER_EMAILS[2],
                display_name="Val Viewer",
                password_hash=hash_password("DemoPassword123!"),
            ),
        ]
        db.add_all(users)
        org1 = Organization(id=uid("acme"), name="Acme Engineering", slug="acme-engineering")
        org2 = Organization(id=uid("northstar"), name="Northstar Labs", slug="northstar-labs")
        db.add_all([org1, org2])
        db.flush()
        db.add_all(
            [
                Membership(organization_id=org1.id, user_id=users[0].id, role="owner"),
                Membership(organization_id=org1.id, user_id=users[1].id, role="member"),
                Membership(organization_id=org1.id, user_id=users[2].id, role="viewer"),
                Membership(organization_id=org2.id, user_id=users[0].id, role="admin"),
                Membership(organization_id=org2.id, user_id=users[1].id, role="owner"),
            ]
        )
        project = Project(
            id=uid("project-eng"),
            organization_id=org1.id,
            name="Engineering",
            key="ENG",
            description="Core platform",
            next_issue_number=4,
        )
        db.add(project)
        db.flush()
        issues = [
            Issue(
                organization_id=org1.id,
                project_id=project.id,
                number=i,
                title=title,
                status=state,
                priority=priority,
                reporter_id=users[0].id,
                assignee_id=users[1].id,
            )
            for i, title, state, priority in [
                (1, "Ship API", "in_progress", "high"),
                (2, "Improve metrics", "todo", "medium"),
                (3, "Archive imports", "backlog", "low"),
            ]
        ]
        db.add_all(issues)
        db.flush()
        db.add(Label(organization_id=org1.id, name="backend", color="#3366CC"))
        db.add(
            Comment(
                organization_id=org1.id,
                issue_id=issues[0].id,
                author_id=users[1].id,
                body="Initial implementation is ready for review.",
            )
        )


if __name__ == "__main__":
    main()

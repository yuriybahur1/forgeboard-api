"""SQLAlchemy model import aggregator for Alembic and compatibility imports."""

from workstream.infrastructure.outbox_models import OutboxEvent
from workstream.modules.audit.models import AuditEvent
from workstream.modules.auth.models import AuthSession, OneTimeToken
from workstream.modules.issues.models import (
    Comment,
    Issue,
    IssueLabel,
    IssueStatus,
    Label,
    Priority,
)
from workstream.modules.notifications.models import Notification
from workstream.modules.organizations.models import Invitation, Membership, Organization, Role
from workstream.modules.projects.models import Project
from workstream.modules.users.models import User

__all__ = [
    "AuditEvent",
    "AuthSession",
    "Comment",
    "Invitation",
    "Issue",
    "IssueLabel",
    "IssueStatus",
    "Label",
    "Membership",
    "Notification",
    "OneTimeToken",
    "Organization",
    "OutboxEvent",
    "Priority",
    "Project",
    "Role",
    "User",
]

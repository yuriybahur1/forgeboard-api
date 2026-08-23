from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from workstream.db.base import Base, Timestamped, UUIDPrimaryKey


class IssueStatus(StrEnum):
    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELED = "canceled"


class Priority(StrEnum):
    NO_PRIORITY = "no_priority"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class Issue(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "issues"
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="backlog")
    priority: Mapped[str] = mapped_column(String(20), nullable=False, server_default="no_priority")
    reporter_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    assignee_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    due_date: Mapped[date | None] = mapped_column(Date)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("project_id", "number"),
        CheckConstraint(
            "status IN ('backlog','todo','in_progress','done','canceled')",
            name="valid_status",
        ),
        CheckConstraint(
            "priority IN ('no_priority','low','medium','high','urgent')",
            name="valid_priority",
        ),
        CheckConstraint("version >= 1", name="positive_version"),
        Index("ix_issues_org_created_id", "organization_id", text("created_at DESC"), "id"),
        Index("ix_issues_project_status", "project_id", "status"),
        Index("ix_issues_assignee", "organization_id", "assignee_id"),
        Index(
            "ix_issues_search_trgm",
            text("(title || ' ' || description) gin_trgm_ops"),
            postgresql_using="gin",
        ),
    )


class Label(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "labels"
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    color: Mapped[str] = mapped_column(String(7), nullable=False)
    __table_args__ = (
        UniqueConstraint("organization_id", "name"),
        CheckConstraint("color ~ '^#[0-9A-Fa-f]{6}$'", name="color_hex"),
    )


class IssueLabel(Base):
    __tablename__ = "issue_labels"
    issue_id: Mapped[UUID] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"), primary_key=True
    )
    label_id: Mapped[UUID] = mapped_column(
        ForeignKey("labels.id", ondelete="CASCADE"), primary_key=True
    )


class Comment(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "comments"
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    issue_id: Mapped[UUID] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"), nullable=False
    )
    author_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_comments_issue_created_id", "issue_id", "created_at", "id"),)

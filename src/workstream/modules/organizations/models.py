from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from workstream.db.base import Base, Timestamped, UUIDPrimaryKey


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class Organization(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "organizations"
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(63), unique=True, nullable=False)
    __table_args__ = (CheckConstraint("slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'", name="slug_format"),)


class Membership(Timestamped, Base):
    __tablename__ = "memberships"
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    __table_args__ = (
        CheckConstraint("role IN ('owner','admin','member','viewer')", name="valid_role"),
        Index("ix_memberships_user_org", "user_id", "organization_id"),
    )


class Invitation(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "invitations"
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    invited_email: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    inviter_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        Index(
            "ix_invitations_org_pending",
            "organization_id",
            "expires_at",
            postgresql_where=text("accepted_at IS NULL AND revoked_at IS NULL"),
        ),
    )

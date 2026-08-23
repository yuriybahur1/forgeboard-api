from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from workstream.db.base import Base, Timestamped, UUIDPrimaryKey


class Project(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "projects"
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    key: Mapped[str] = mapped_column(String(10), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    next_issue_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    __table_args__ = (
        UniqueConstraint("organization_id", "key"),
        CheckConstraint("key ~ '^[A-Z][A-Z0-9]{1,9}$'", name="key_format"),
    )

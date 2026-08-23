from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from workstream.db.base import Base, Timestamped, UUIDPrimaryKey


class User(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    __table_args__ = (Index("uq_users_email_normalized", text("lower(email)"), unique=True),)

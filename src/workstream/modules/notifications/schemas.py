from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class NotificationResponse(BaseModel):
    id: UUID
    kind: str
    payload: dict[str, Any]
    created_at: datetime
    read_at: datetime | None


class NotificationPage(BaseModel):
    items: list[NotificationResponse]
    next_cursor: str | None


class UnreadCount(BaseModel):
    count: int

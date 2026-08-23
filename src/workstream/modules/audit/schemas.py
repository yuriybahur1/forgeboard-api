from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class AuditEventResponse(BaseModel):
    id: UUID
    actor_id: UUID | None
    action: str
    entity_type: str
    entity_id: UUID | None
    metadata: dict[str, Any]
    request_id: str | None
    created_at: datetime


class AuditPage(BaseModel):
    items: list[AuditEventResponse]
    next_cursor: str | None

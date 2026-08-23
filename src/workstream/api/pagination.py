import base64
import json
from datetime import datetime
from uuid import UUID

from workstream.core.errors import AppError


def encode_cursor(created_at: datetime, id_: UUID) -> str:
    payload = json.dumps([created_at.isoformat(), str(id_)], separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_cursor(value: str) -> tuple[datetime, UUID]:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        created_at, id_ = json.loads(raw)
        return datetime.fromisoformat(created_at), UUID(id_)
    except (ValueError, TypeError, json.JSONDecodeError):
        raise AppError(400, "invalid_cursor", "Cursor is malformed") from None

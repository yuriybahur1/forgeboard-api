from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from workstream.core.config import Settings
from workstream.core.errors import AppError
from workstream.modules.models import Issue
from workstream.modules.work.router import decode_cursor, encode_cursor


def test_cursor_round_trip_and_rejects_malformed() -> None:
    issue = Issue(id=uuid4(), created_at=datetime.now(UTC))
    assert decode_cursor(encode_cursor(issue)) == (issue.created_at, issue.id)
    with pytest.raises(AppError) as caught:
        decode_cursor("not-a-cursor")
    assert caught.value.code == "invalid_cursor"


def test_production_settings_reject_default_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="production", log_json=True)

"""Compatibility imports for callers predating the domain router split."""

from workstream.api.pagination import decode_cursor
from workstream.modules.issues.policies import TRANSITIONS
from workstream.modules.models import Issue


def encode_cursor(issue: Issue) -> str:
    from workstream.api.pagination import encode_cursor as encode

    return encode(issue.created_at, issue.id)


__all__ = ["TRANSITIONS", "decode_cursor", "encode_cursor"]

from pydantic import BaseModel

from workstream.api.schemas import CommentOut


class CommentPage(BaseModel):
    items: list[CommentOut]
    next_cursor: str | None

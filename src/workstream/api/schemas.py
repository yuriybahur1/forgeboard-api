from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Register(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)
    display_name: str = Field(min_length=1, max_length=120)


class Login(BaseModel):
    email: EmailStr
    password: str


class Refresh(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 -- OAuth token type, not a credential.
    expires_in: int


class UserOut(ORMModel):
    id: UUID
    email: EmailStr
    display_name: str
    email_verified_at: datetime | None
    is_active: bool


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=63)


class OrganizationUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class OrganizationOut(ORMModel):
    id: UUID
    name: str
    slug: str
    created_at: datetime
    updated_at: datetime


class MemberOut(BaseModel):
    user_id: UUID
    role: str
    email: EmailStr
    display_name: str


class RoleChange(BaseModel):
    role: str = Field(pattern="^(owner|admin|member|viewer)$")


class InvitationCreate(BaseModel):
    email: EmailStr
    role: str = Field(pattern="^(admin|member|viewer)$")


class InvitationAccept(BaseModel):
    token: str


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    key: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,9}$")
    description: str = Field(default="", max_length=10000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=10000)


class ProjectOut(ORMModel):
    id: UUID
    organization_id: UUID
    name: str
    key: str
    description: str
    archived: bool
    next_issue_number: int
    created_at: datetime


class IssueCreate(BaseModel):
    project_id: UUID
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=100000)
    priority: str = "no_priority"
    assignee_id: UUID | None = None
    due_date: date | None = None


class IssueUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=100000)
    priority: str | None = None
    due_date: date | None = None


class StatusChange(BaseModel):
    expected_version: int
    status: str


class Assignment(BaseModel):
    expected_version: int
    assignee_id: UUID | None


class IssueOut(ORMModel):
    id: UUID
    organization_id: UUID
    project_id: UUID
    number: int
    title: str
    description: str
    status: str
    priority: str
    reporter_id: UUID
    assignee_id: UUID | None
    due_date: date | None
    version: int
    created_at: datetime
    updated_at: datetime


class LabelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")


class LabelOut(ORMModel):
    id: UUID
    organization_id: UUID
    name: str
    color: str


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=20000)


class CommentOut(ORMModel):
    id: UUID
    issue_id: UUID
    author_id: UUID
    body: str
    edited_at: datetime | None
    created_at: datetime


class CursorPage(BaseModel):
    items: list[IssueOut]
    next_cursor: str | None


class Cursor(BaseModel):
    created_at: datetime
    id: UUID

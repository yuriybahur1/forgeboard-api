from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)
    display_name: str = Field(min_length=1, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=256)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=32, max_length=512)


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=32, max_length=512)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=32, max_length=512)
    new_password: str = Field(min_length=12, max_length=256)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 -- OAuth token type, not a credential.
    expires_in: int


class SessionResponse(BaseModel):
    id: UUID
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    user_agent: str | None
    ip_address: str | None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: EmailStr
    display_name: str
    email_verified_at: datetime | None
    is_active: bool


class GenericAcceptedResponse(BaseModel):
    detail: str

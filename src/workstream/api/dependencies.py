from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from workstream.core.config import Settings, get_settings
from workstream.core.errors import AppError
from workstream.core.security import decode_access_token
from workstream.db.session import get_session
from workstream.modules.models import AuthSession, Membership, User

DB = Annotated[AsyncSession, Depends(get_session)]
Config = Annotated[Settings, Depends(get_settings)]


async def current_user(
    db: DB, settings: Config, authorization: Annotated[str | None, Header()] = None
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise AppError(401, "authentication_required", "A valid bearer token is required")
    try:
        user_id, session_id = decode_access_token(authorization[7:], settings)
    except (jwt.PyJWTError, ValueError):
        raise AppError(
            401, "invalid_access_token", "The access token is invalid or expired"
        ) from None
    result = await db.execute(
        select(User)
        .join(AuthSession, AuthSession.user_id == User.id)
        .where(
            User.id == user_id,
            User.is_active,
            AuthSession.id == session_id,
            AuthSession.revoked_at.is_(None),
        )
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise AppError(401, "session_revoked", "The session is no longer active")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


async def require_membership(
    db: AsyncSession, organization_id: UUID, user_id: UUID, roles: set[str] | None = None
) -> Membership:
    membership = await db.get(Membership, (organization_id, user_id))
    if membership is None:
        raise AppError(404, "resource_not_found", "The requested resource was not found")
    if roles and membership.role not in roles:
        raise AppError(
            403, "insufficient_permission", "Your organization role does not permit this action"
        )
    return membership

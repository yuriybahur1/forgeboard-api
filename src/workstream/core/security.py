import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from workstream.core.config import Settings

password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        return password_hasher.verify(encoded, password)
    except VerifyMismatchError:
        return False


def opaque_token() -> str:
    return secrets.token_urlsafe(48)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def access_token(user_id: UUID, session_id: UUID, settings: Settings) -> str:
    now = datetime.now(UTC)
    return cast(
        str,
        jwt.encode(
            {
                "sub": str(user_id),
                "sid": str(session_id),
                "iss": settings.jwt_issuer,
                "aud": settings.jwt_audience,
                "iat": now,
                "exp": now + timedelta(minutes=settings.access_token_minutes),
                "jti": str(uuid4()),
            },
            settings.jwt_secret.get_secret_value(),
            algorithm="HS256",
        ),
    )


def decode_access_token(token: str, settings: Settings) -> tuple[UUID, UUID]:
    claims = jwt.decode(
        token,
        settings.jwt_secret.get_secret_value(),
        algorithms=["HS256"],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
        options={"require": ["sub", "sid", "iat", "exp", "jti"]},
    )
    return UUID(claims["sub"]), UUID(claims["sid"])

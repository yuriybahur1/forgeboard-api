from uuid import uuid4

import jwt

from workstream.core.config import Settings
from workstream.core.security import (
    access_token,
    decode_access_token,
    hash_password,
    token_hash,
    verify_password,
)


def test_password_hash_and_tokens() -> None:
    encoded = hash_password("A sufficiently long password")
    assert verify_password("A sufficiently long password", encoded)
    assert not verify_password("wrong", encoded)
    assert "A sufficiently long password" not in encoded
    assert token_hash("secret") == token_hash("secret")


def test_access_token_claims() -> None:
    settings = Settings()
    user_id, session_id = uuid4(), uuid4()
    token = access_token(user_id, session_id, settings)
    assert decode_access_token(token, settings) == (user_id, session_id)
    claims = jwt.decode(
        token,
        settings.jwt_secret.get_secret_value(),
        algorithms=["HS256"],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
    )
    assert {"sub", "sid", "iss", "aud", "iat", "exp", "jti"} <= claims.keys()

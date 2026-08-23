from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from workstream.core.config import get_settings
from workstream.core.security import decode_access_token, opaque_token, token_hash
from workstream.modules.models import AuthSession, OneTimeToken, OutboxEvent, User

pytestmark = pytest.mark.integration
PASSWORD = "ValidPassword123!"


async def register(client: AsyncClient, email: str = "New.User@Example.COM"):
    return await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "display_name": "New User"},
    )


async def test_registration_normalization_duplicate_and_login(
    client: AsyncClient, db: AsyncSession
) -> None:
    response = await register(client)
    assert response.status_code == 201
    assert (await db.scalar(select(User.email))) == "new.user@example.com"
    assert (await register(client, "new.user@example.com")).status_code == 409
    login = await client.post(
        "/api/v1/auth/login", json={"email": "NEW.USER@example.com", "password": PASSWORD}
    )
    assert login.status_code == 200
    assert (
        await client.post(
            "/api/v1/auth/login", json={"email": "new.user@example.com", "password": "wrong"}
        )
    ).status_code == 401


async def test_refresh_rotation_reuse_revokes_family(
    client: AsyncClient, user: User, db: AsyncSession
) -> None:
    login = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": PASSWORD}
    )
    first = login.json()
    rotated = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )
    assert rotated.status_code == 200
    reuse = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )
    assert reuse.status_code == 401 and reuse.json()["code"] == "refresh_token_reuse"
    assert (
        await db.scalar(
            select(func.count()).select_from(AuthSession).where(AuthSession.revoked_at.is_(None))
        )
        == 0
    )
    protected = await client.get(
        "/api/v1/organizations",
        headers={"Authorization": f"Bearer {rotated.json()['access_token']}"},
    )
    assert protected.status_code == 401


async def test_current_selected_and_global_session_revocation(
    client: AsyncClient, user: User
) -> None:
    one = (
        await client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
    ).json()
    two = (
        await client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
    ).json()
    h1 = {"Authorization": f"Bearer {one['access_token']}"}
    sessions = await client.get("/api/v1/auth/sessions", headers=h1)
    assert len(sessions.json()) == 2
    _, second_family = decode_access_token(two["access_token"], get_settings())
    selected = next(s for s in sessions.json() if s["id"] == str(second_family))
    assert (
        await client.delete(f"/api/v1/auth/sessions/{selected['id']}", headers=h1)
    ).status_code == 204
    await client.post("/api/v1/auth/logout", headers=h1)
    assert (await client.get("/api/v1/organizations", headers=h1)).status_code == 401
    # A fresh device can revoke every active logical session.
    fresh = (
        await client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
    ).json()
    hf = {"Authorization": f"Bearer {fresh['access_token']}"}
    assert (await client.delete("/api/v1/auth/sessions", headers=hf)).status_code == 204
    assert (await client.get("/api/v1/organizations", headers=hf)).status_code == 401


async def test_password_reset_generic_success_one_time_and_session_revoke(
    client: AsyncClient, user: User, db: AsyncSession
) -> None:
    login = (
        await client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
    ).json()
    unknown = await client.post(
        "/api/v1/auth/password-reset/request", json={"email": "missing@example.com"}
    )
    known = await client.post("/api/v1/auth/password-reset/request", json={"email": user.email})
    assert unknown.status_code == known.status_code == 202 and unknown.json() == known.json()
    event = await db.scalar(select(OutboxEvent).where(OutboxEvent.topic == "email.password_reset"))
    assert event
    raw = str(event.payload["token"])
    new_password = "AnotherValidPassword123!"
    reset = await client.post(
        "/api/v1/auth/password-reset", json={"token": raw, "new_password": new_password}
    )
    assert reset.status_code == 204
    assert (
        await client.post(
            "/api/v1/auth/password-reset", json={"token": raw, "new_password": new_password}
        )
    ).status_code == 400
    assert (
        await client.get(
            "/api/v1/organizations", headers={"Authorization": f"Bearer {login['access_token']}"}
        )
    ).status_code == 401
    assert (
        await client.post(
            "/api/v1/auth/login", json={"email": user.email, "password": new_password}
        )
    ).status_code == 200


async def test_verification_one_time_and_expiry(
    client: AsyncClient, user: User, db: AsyncSession
) -> None:
    raw = opaque_token()
    token = OneTimeToken(
        user_id=user.id,
        purpose="verify_email",
        token_hash=token_hash(raw),
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    db.add(token)
    await db.commit()
    assert (await client.post("/api/v1/auth/verify-email", json={"token": raw})).status_code == 204
    assert (await client.post("/api/v1/auth/verify-email", json={"token": raw})).status_code == 400
    expired = opaque_token()
    db.add(
        OneTimeToken(
            user_id=user.id,
            purpose="verify_email",
            token_hash=token_hash(expired),
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )
    await db.commit()
    assert (
        await client.post("/api/v1/auth/verify-email", json={"token": expired})
    ).status_code == 400


async def test_verification_resend_creates_outbox(
    client: AsyncClient, user: User, db: AsyncSession, auth_headers: dict[str, str]
) -> None:
    response = await client.post("/api/v1/auth/email-verification/resend", headers=auth_headers)
    assert response.status_code == 202
    assert (
        await db.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(OutboxEvent.topic == "email.verification")
        )
        == 1
    )

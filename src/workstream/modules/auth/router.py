from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Request, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from workstream.api.dependencies import DB, Config, CurrentPrincipal, CurrentUser
from workstream.api.rate_limit import enforce_rate_limit
from workstream.core.errors import AppError
from workstream.core.security import (
    access_token,
    hash_password,
    opaque_token,
    token_hash,
    verify_password,
)
from workstream.modules.auth.schemas import (
    GenericAcceptedResponse,
    LoginRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshRequest,
    RegisterRequest,
    SessionResponse,
    TokenPair,
    UserResponse,
    VerifyEmailRequest,
)
from workstream.modules.models import AuditEvent, AuthSession, OneTimeToken, OutboxEvent, User

router = APIRouter(prefix="/auth", tags=["authentication"])


def pair(user: User, session: AuthSession, raw: str, settings: Config) -> TokenPair:
    return TokenPair(
        access_token=access_token(user.id, session.family_id, settings),
        refresh_token=raw,
        expires_in=settings.access_token_minutes * 60,
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: DB, request: Request) -> User:
    user = User(
        email=str(body.email).lower(),
        password_hash=hash_password(body.password),
        display_name=body.display_name,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise AppError(
            409, "email_already_registered", "An account with this email already exists"
        ) from None
    raw = opaque_token()
    db.add(
        OneTimeToken(
            user_id=user.id,
            purpose="verify_email",
            token_hash=token_hash(raw),
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
    )
    db.add(
        OutboxEvent(
            topic="email.verification",
            payload={"user_id": str(user.id), "email": user.email, "token": raw},
        )
    )
    db.add(
        AuditEvent(
            actor_id=user.id,
            action="account.registered",
            entity_type="user",
            entity_id=user.id,
            request_id=request.state.request_id,
        )
    )
    await db.commit()
    return user


@router.post("/login", response_model=TokenPair)
async def login(body: LoginRequest, db: DB, settings: Config, request: Request) -> TokenPair:
    await enforce_rate_limit(
        request, scope="login", account=str(body.email), limit=settings.login_rate_limit, window=60
    )
    user = (
        await db.execute(select(User).where(User.email == str(body.email).lower()))
    ).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise AppError(401, "invalid_credentials", "Email or password is incorrect")
    raw = opaque_token()
    session = AuthSession(
        user_id=user.id,
        family_id=uuid4(),
        refresh_token_hash=token_hash(raw),
        expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_days),
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    db.add(session)
    await db.flush()
    db.add(
        AuditEvent(
            actor_id=user.id,
            action="session.created",
            entity_type="session",
            entity_id=session.id,
            request_id=request.state.request_id,
        )
    )
    await db.commit()
    return pair(user, session, raw, settings)


@router.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshRequest, db: DB, settings: Config) -> TokenPair:
    digest = token_hash(body.refresh_token)
    session = (
        await db.execute(
            select(AuthSession).where(AuthSession.refresh_token_hash == digest).with_for_update()
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if session is None:
        raise AppError(401, "invalid_refresh_token", "Refresh token is invalid")
    if session.rotated_at is not None:
        await db.execute(
            update(AuthSession)
            .where(AuthSession.family_id == session.family_id)
            .values(revoked_at=now)
        )
        await db.commit()
        raise AppError(
            401,
            "refresh_token_reuse",
            "Refresh token reuse detected; the session family was revoked",
        )
    if session.revoked_at or session.expires_at <= now:
        raise AppError(401, "invalid_refresh_token", "Refresh token is expired or revoked")
    user = await db.get(User, session.user_id)
    if user is None or not user.is_active:
        await db.execute(
            update(AuthSession)
            .where(AuthSession.family_id == session.family_id)
            .values(revoked_at=now)
        )
        await db.commit()
        raise AppError(401, "invalid_refresh_token", "Refresh token is expired or revoked")
    session.rotated_at = now
    raw = opaque_token()
    successor = AuthSession(
        user_id=session.user_id,
        family_id=session.family_id,
        refresh_token_hash=token_hash(raw),
        expires_at=session.expires_at,
        user_agent=session.user_agent,
        ip_address=session.ip_address,
    )
    db.add(successor)
    await db.flush()
    await db.commit()
    return pair(user, successor, raw, settings)


@router.post("/logout", status_code=204)
async def logout(principal: CurrentPrincipal, db: DB) -> None:
    await db.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == principal.user.id,
            AuthSession.family_id == principal.session_id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    await db.commit()


@router.get("/sessions", response_model=list[SessionResponse])
async def sessions(user: CurrentUser, db: DB) -> list[SessionResponse]:
    rows = (
        await db.execute(
            select(AuthSession)
            .where(AuthSession.user_id == user.id, AuthSession.rotated_at.is_(None))
            .order_by(AuthSession.created_at.desc())
        )
    ).scalars()
    return [
        SessionResponse(
            id=s.family_id,
            created_at=s.created_at,
            expires_at=s.expires_at,
            revoked_at=s.revoked_at,
            user_agent=s.user_agent,
            ip_address=s.ip_address,
        )
        for s in rows
    ]


@router.delete("/sessions/{session_id}", status_code=204)
async def revoke_session(session_id: UUID, user: CurrentUser, db: DB) -> None:
    await db.execute(
        update(AuthSession)
        .where(AuthSession.family_id == session_id, AuthSession.user_id == user.id)
        .values(revoked_at=datetime.now(UTC))
    )
    await db.commit()


@router.delete("/sessions", status_code=204)
async def revoke_all(user: CurrentUser, db: DB) -> None:
    await db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    await db.commit()


@router.post("/verify-email", status_code=204)
async def verify_email(body: VerifyEmailRequest, db: DB) -> None:
    row = (
        await db.execute(
            select(OneTimeToken)
            .where(
                OneTimeToken.token_hash == token_hash(body.token),
                OneTimeToken.purpose == "verify_email",
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if row is None or row.used_at or row.expires_at <= now:
        raise AppError(400, "invalid_token", "Token is invalid or expired")
    row.used_at = now
    user = await db.get(User, row.user_id)
    assert user
    user.email_verified_at = now
    await db.commit()


@router.post("/email-verification/resend", response_model=GenericAcceptedResponse, status_code=202)
async def resend_verification(
    user: CurrentUser, db: DB, request: Request, settings: Config
) -> GenericAcceptedResponse:
    await enforce_rate_limit(
        request,
        scope="verify-resend",
        account=user.email,
        limit=settings.verification_rate_limit,
        window=3600,
    )
    if user.email_verified_at is None:
        raw = opaque_token()
        db.add(
            OneTimeToken(
                user_id=user.id,
                purpose="verify_email",
                token_hash=token_hash(raw),
                expires_at=datetime.now(UTC) + timedelta(hours=24),
            )
        )
        db.add(
            OutboxEvent(
                topic="email.verification",
                payload={"user_id": str(user.id), "email": user.email, "token": raw},
            )
        )
        await db.commit()
    return GenericAcceptedResponse(detail="Verification instructions will be sent if needed")


@router.post("/password-reset/request", response_model=GenericAcceptedResponse, status_code=202)
async def request_reset(
    body: PasswordResetRequest, db: DB, request: Request, settings: Config
) -> GenericAcceptedResponse:
    await enforce_rate_limit(
        request,
        scope="password-reset",
        account=str(body.email),
        limit=settings.password_reset_rate_limit,
        window=3600,
    )
    user = (
        await db.execute(select(User).where(User.email == str(body.email).lower()))
    ).scalar_one_or_none()
    if user:
        raw = opaque_token()
        db.add(
            OneTimeToken(
                user_id=user.id,
                purpose="password_reset",
                token_hash=token_hash(raw),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        db.add(
            OutboxEvent(
                topic="email.password_reset",
                payload={"user_id": str(user.id), "email": user.email, "token": raw},
            )
        )
        await db.commit()
    return GenericAcceptedResponse(detail="If the account exists, reset instructions will be sent")


@router.post("/password-reset", status_code=204)
async def reset_password(body: PasswordResetConfirm, db: DB) -> None:
    row = (
        await db.execute(
            select(OneTimeToken)
            .where(
                OneTimeToken.token_hash == token_hash(body.token),
                OneTimeToken.purpose == "password_reset",
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if row is None or row.used_at or row.expires_at <= now:
        raise AppError(400, "invalid_token", "Token is invalid or expired")
    user = await db.get(User, row.user_id)
    assert user
    user.password_hash = hash_password(body.new_password)
    row.used_at = now
    await db.execute(
        update(AuthSession).where(AuthSession.user_id == user.id).values(revoked_at=now)
    )
    await db.commit()

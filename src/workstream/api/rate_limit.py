import hashlib

from fastapi import Request
from redis.exceptions import RedisError

from workstream.core.errors import AppError
from workstream.infrastructure.redis import RateLimiter


def account_key(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()[:32]


async def enforce_rate_limit(
    request: Request, *, scope: str, account: str | None, limit: int, window: int
) -> None:
    client = request.client.host if request.client else "unknown"
    identity = account_key(account) if account else "anonymous"
    limiter = RateLimiter(request.app.state.redis)
    try:
        allowed, retry_after = await limiter.hit(f"{scope}:{client}:{identity}", limit, window)
    except RedisError:
        # Authentication controls fail closed. Read-only application traffic remains available.
        raise AppError(
            503, "security_service_unavailable", "Security controls are unavailable"
        ) from None
    if not allowed:
        raise AppError(
            429,
            "rate_limit_exceeded",
            "Too many requests",
            headers={"Retry-After": str(retry_after)},
        )

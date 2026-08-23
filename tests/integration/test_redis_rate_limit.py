import asyncio

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis

from workstream.infrastructure.redis import RateLimiter
from workstream.modules.models import User

pytestmark = pytest.mark.integration


async def test_real_redis_counter_ttl_and_recovery(redis_client: Redis) -> None:
    limiter = RateLimiter(redis_client)
    assert await limiter.hit("integration", 2, 1) == (True, 1)
    allowed, ttl = await limiter.hit("integration", 2, 1)
    assert allowed and ttl > 0
    allowed, ttl = await limiter.hit("integration", 2, 1)
    assert not allowed and ttl > 0
    await asyncio.sleep(1.1)
    assert (await limiter.hit("integration", 2, 1))[0]


async def test_login_returns_429_and_retry_after(client: AsyncClient, user: User) -> None:
    responses = []
    for _ in range(11):
        responses.append(
            await client.post("/api/v1/auth/login", json={"email": user.email, "password": "wrong"})
        )
    blocked = responses[-1]
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0
    assert blocked.json()["code"] == "rate_limit_exceeded"

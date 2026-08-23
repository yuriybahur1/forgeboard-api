from unittest.mock import AsyncMock

import pytest

from workstream.infrastructure.redis import RateLimiter


async def test_atomic_rate_limiter_allows_and_blocks() -> None:
    redis = AsyncMock()
    redis.eval.side_effect = [[1, 60], [3, 58]]
    limiter = RateLimiter(redis)

    assert await limiter.hit("login:client:account", 2, 60) == (True, 60)
    assert await limiter.hit("login:client:account", 2, 60) == (False, 58)
    redis.eval.assert_awaited()


@pytest.mark.parametrize("ttl", [-1, 0])
async def test_rate_limiter_never_returns_nonpositive_retry_after(ttl: int) -> None:
    redis = AsyncMock()
    redis.eval.return_value = [2, ttl]
    assert await RateLimiter(redis).hit("key", 1, 60) == (False, 1)

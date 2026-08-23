from typing import Any, cast

from redis.asyncio import Redis

RATE_LIMIT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""


class RateLimiter:
    def __init__(self, redis: Redis):
        self.redis = redis

    async def hit(self, key: str, limit: int, window: int) -> tuple[bool, int]:
        count, ttl = await cast(Any, self.redis.eval)(
            RATE_LIMIT_SCRIPT, 1, f"workstream:rate:{key}", str(window)
        )
        return int(count) <= limit, max(int(ttl), 1)

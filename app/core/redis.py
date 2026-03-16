import logging

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

_redis_client: aioredis.Redis | None = None


async def init_redis() -> None:
    global _redis_client
    try:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
        )
        await _redis_client.ping()
        logger.info("Connected to Redis at %s", settings.REDIS_URL)
    except Exception:
        logger.warning("Could not connect to Redis — rate limiting disabled", exc_info=True)
        _redis_client = None


async def close_redis() -> None:
    global _redis_client
    if _redis_client is not None:
        await _redis_client.close()
        _redis_client = None


def get_redis() -> aioredis.Redis | None:
    return _redis_client

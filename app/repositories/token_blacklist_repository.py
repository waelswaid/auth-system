import logging
from datetime import datetime, timezone

from redis.exceptions import RedisError

from app.core.redis import get_redis

logger = logging.getLogger(__name__)

BLACKLIST_PREFIX = "blacklist:"


async def add_to_blacklist(jti: str, expires_at: datetime) -> None:
    r = get_redis()
    if r is None:
        logger.warning("Redis unavailable — could not blacklist jti=%s", jti)
        return

    ttl = int((expires_at - datetime.now(timezone.utc)).total_seconds())
    if ttl <= 0:
        return

    try:
        await r.setex(f"{BLACKLIST_PREFIX}{jti}", ttl, "1")
    except RedisError:
        logger.warning("Redis error while blacklisting jti=%s — failing open", jti, exc_info=True)


async def is_blacklisted(jti: str) -> bool:
    r = get_redis()
    if r is None:
        logger.warning("Redis unavailable — blacklist check skipped for jti=%s", jti)
        return False

    try:
        return await r.exists(f"{BLACKLIST_PREFIX}{jti}") > 0
    except RedisError:
        logger.warning("Redis error during blacklist check — failing open", exc_info=True)
        return False

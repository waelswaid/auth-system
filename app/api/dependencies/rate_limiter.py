import json
import logging
import time

from fastapi import HTTPException, Request
from redis.exceptions import RedisError

from app.core.config import settings
from app.core.redis import get_redis

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 3600

# Lua script: sliding window counter (atomic)
# Keys: [prev_window_key, curr_window_key]
# Args: [max_requests, window_seconds, now_ts]
# Returns: [allowed (0/1), weighted_count, window_reset_ts]
_LUA_SCRIPT = """
local prev_key = KEYS[1]
local curr_key = KEYS[2]
local max_requests = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

local window_id = math.floor(now / window)
local window_start = window_id * window
local elapsed = now - window_start
local fraction = elapsed / window

local prev_count = tonumber(redis.call('GET', prev_key) or '0') or 0
local curr_count = tonumber(redis.call('GET', curr_key) or '0') or 0

local weighted = prev_count * (1 - fraction) + curr_count

if weighted >= max_requests then
    local reset_at = window_start + window
    return {0, math.ceil(weighted), reset_at}
end

redis.call('INCR', curr_key)
redis.call('EXPIRE', curr_key, window * 2)

return {1, math.ceil(weighted + 1), window_start + window}
"""


class RateLimiter:

    def __init__(self, name: str, max_requests: int, window_seconds: int = WINDOW_SECONDS, use_email_key: bool = False):
        self.name = name
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.use_email_key = use_email_key
        self._script_sha: str | None = None

    def _build_client_key(self, request: Request, body_bytes: bytes) -> str:
        ip = request.client.host if request.client else "unknown"
        if self.use_email_key:
            try:
                data = json.loads(body_bytes)
                email = data.get("email", "")
            except (json.JSONDecodeError, UnicodeDecodeError):
                email = ""
            return f"{ip}:{email}"
        return ip

    def _redis_keys(self, client_key: str, now: float) -> tuple[str, str]:
        window_id = int(now // self.window_seconds)
        prev_id = window_id - 1
        prefix = f"ratelimit:{self.name}"
        return f"{prefix}:{prev_id}:{client_key}", f"{prefix}:{window_id}:{client_key}"

    async def __call__(self, request: Request) -> None:
        body_bytes = await request.body()
        client_key = self._build_client_key(request, body_bytes)

        r = get_redis()
        if r is None:
            # Fail open — no Redis available
            return

        now = time.time()
        prev_key, curr_key = self._redis_keys(client_key, now)

        try:
            result = await r.eval(
                _LUA_SCRIPT,
                2,
                prev_key,
                curr_key,
                self.max_requests,
                self.window_seconds,
                int(now),
            )
            allowed, count, reset_at = int(result[0]), int(result[1]), int(result[2])

            # Store metadata on request.state for the middleware to pick up
            request.state.rate_limit_limit = self.max_requests
            request.state.rate_limit_remaining = max(0, self.max_requests - count)
            request.state.rate_limit_reset = reset_at

            if not allowed:
                retry_after = max(1, reset_at - int(now))
                raise HTTPException(
                    status_code=429,
                    detail="Too many requests. Please try again later.",
                    headers={
                        "Retry-After": str(retry_after),
                        "X-RateLimit-Limit": str(self.max_requests),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(reset_at),
                    },
                )
        except RedisError:
            logger.warning("Redis error during rate limiting — failing open", exc_info=True)


# --- Limiter instances ---

forgot_password_limiter = RateLimiter(
    name="forgot_password",
    max_requests=settings.RATE_LIMIT_FORGOT_PASSWORD,
    use_email_key=True,
)
resend_verification_limiter = RateLimiter(
    name="resend_verification",
    max_requests=settings.RATE_LIMIT_RESEND_VERIFICATION,
    use_email_key=True,
)
reset_password_limiter = RateLimiter(
    name="reset_password",
    max_requests=settings.RATE_LIMIT_RESET_PASSWORD,
)
login_limiter = RateLimiter(
    name="login",
    max_requests=settings.RATE_LIMIT_LOGIN,
    use_email_key=True,
)
login_global_limiter = RateLimiter(
    name="login_global",
    max_requests=settings.RATE_LIMIT_LOGIN_GLOBAL,
)
registration_limiter = RateLimiter(
    name="registration",
    max_requests=settings.RATE_LIMIT_REGISTRATION,
)
refresh_limiter = RateLimiter(
    name="refresh",
    max_requests=settings.RATE_LIMIT_REFRESH,
)
verify_email_limiter = RateLimiter(
    name="verify_email",
    max_requests=settings.RATE_LIMIT_VERIFY_EMAIL,
)
validate_reset_code_limiter = RateLimiter(
    name="validate_reset_code",
    max_requests=settings.RATE_LIMIT_VALIDATE_RESET_CODE,
)

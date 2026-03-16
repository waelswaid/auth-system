# Redis Rate Limiting — Architecture & Walkthrough

This document explains how Redis-backed rate limiting works in this project, from request to response.

---

## Why Redis?

The previous implementation used an in-memory `defaultdict(list)` with a `threading.Lock`. That approach had three problems:

1. **State lost on restart** — all counters reset when the server restarts
2. **Not shared across workers** — if you run multiple uvicorn workers (or multiple containers behind a load balancer), each has its own counter, so limits are effectively multiplied
3. **O(n) memory per key** — every single request timestamp was stored in a list

Redis solves all three: it's an external process that persists across restarts, is shared by all workers, and we use a constant-memory algorithm (two integers per key instead of a list of timestamps).

---

## High-Level Flow

```
Client Request
     |
     v
FastAPI Dependency Injection
     |
     v
RateLimiter.__call__(request)
     |
     +-- 1. Extract client key (IP, or IP+email)
     +-- 2. Get Redis client via get_redis()
     |       |
     |       +-- If None (Redis down): ALLOW request (fail open)
     |
     +-- 3. Execute Lua script atomically in Redis
     |       |
     |       +-- Returns: [allowed, count, reset_timestamp]
     |
     +-- 4. Store metadata on request.state
     +-- 5. If not allowed: raise HTTPException(429)
     |
     v
Route Handler (runs normally if allowed)
     |
     v
rate_limit_headers_middleware
     |
     +-- Reads request.state, copies to response headers
     |
     v
Response to Client
     (with X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset)
```

---

## File-by-File Breakdown

### `app/core/redis.py` — Redis Client Lifecycle

This module manages a single Redis connection for the entire application.

```
_redis_client: global variable, holds the async Redis instance (or None)

init_redis()   — Called once at app startup (in lifespan). Creates the client
                 and pings Redis. If Redis is unreachable, sets client to None
                 and logs a warning instead of crashing.

close_redis()  — Called once at app shutdown (in lifespan). Closes the connection.

get_redis()    — Returns the current client (or None). Called by every
                 RateLimiter instance on every request.
```

The client is **not** injected via FastAPI's `Depends()`. It's a plain module-level import because rate limiters are themselves dependencies — nesting `Depends()` inside `Depends()` adds unnecessary complexity.

### `app/core/config.py` — Configuration

All rate limit settings are env-configurable via pydantic-settings:

| Setting | Default | Meaning |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `RATE_LIMIT_LOGIN` | 10 | Per IP+email, per hour |
| `RATE_LIMIT_LOGIN_GLOBAL` | 30 | Per IP (all accounts), per hour |
| `RATE_LIMIT_REGISTRATION` | 5 | Per IP, per hour |
| `RATE_LIMIT_FORGOT_PASSWORD` | 5 | Per IP+email, per hour |
| `RATE_LIMIT_RESET_PASSWORD` | 10 | Per IP, per hour |
| `RATE_LIMIT_RESEND_VERIFICATION` | 5 | Per IP+email, per hour |
| `RATE_LIMIT_REFRESH` | 30 | Per IP, per hour |
| `RATE_LIMIT_VERIFY_EMAIL` | 10 | Per IP, per hour |
| `RATE_LIMIT_VALIDATE_RESET_CODE` | 10 | Per IP, per hour |

To override in production, set the environment variable (e.g. `RATE_LIMIT_LOGIN=20`).

### `app/main.py` — Lifespan & Middleware

**Lifespan** (startup/shutdown):
```python
async def lifespan(app):
    # ... existing DB cleanup ...
    await init_redis()      # <-- connect to Redis
    yield
    await close_redis()     # <-- disconnect on shutdown
```

**Middleware** — a simple pass-through that copies rate limit metadata from `request.state` to response headers. This runs on *every* response, but only adds headers if a rate limiter actually ran (i.e., `request.state.rate_limit_limit` exists). The 429 response headers (`Retry-After`, etc.) are set directly by the `HTTPException` in the rate limiter, not by this middleware.

### `app/api/dependencies/rate_limiter.py` — The Core

This is where the algorithm lives. Each `RateLimiter` is a callable class used as a FastAPI dependency.

#### The Algorithm: Sliding Window Counter

Instead of storing every timestamp (old approach), we use **two fixed-window counters** with weighted interpolation. This gives us the smoothness of a sliding window with O(1) memory.

**Concept:**

Imagine the window is 1 hour. The current time is 2:15 PM.

```
Previous window: 1:00 PM - 2:00 PM  (count: 8)
Current window:  2:00 PM - 3:00 PM  (count: 3)

Elapsed fraction of current window: 15min / 60min = 0.25
Remaining fraction of previous window: 1 - 0.25 = 0.75

Weighted count = 8 * 0.75 + 3 = 9
```

If max_requests is 10, this request is allowed (9 < 10). The current window counter is incremented to 4.

At 2:45 PM, the previous window's weight drops to 0.25, so old requests naturally "fade out" without explicit cleanup.

#### The Lua Script

The algorithm runs as an **atomic Lua script** inside Redis. This is critical — without atomicity, two concurrent requests could both read the count as 9 (below the limit of 10), both increment, and end up with 11. The Lua script makes the read-check-increment a single atomic operation.

```lua
-- Simplified version of what the script does:

prev_count = GET(prev_key) or 0
curr_count = GET(curr_key) or 0
weighted = prev_count * (1 - fraction) + curr_count

if weighted >= max_requests then
    return [DENIED, count, reset_time]
end

INCR(curr_key)
EXPIRE(curr_key, window * 2)    -- auto-cleanup
return [ALLOWED, count, reset_time]
```

**Redis keys** follow the pattern: `ratelimit:{name}:{window_id}:{client_key}`

- `name` — limiter name (e.g., `login`, `forgot_password`)
- `window_id` — `floor(timestamp / window_seconds)`, increments every hour
- `client_key` — IP address, or `IP:email` for email-keyed limiters

Example keys:
```
ratelimit:login:482547:192.168.1.1:user@example.com      (current window)
ratelimit:login:482546:192.168.1.1:user@example.com      (previous window)
```

Each key gets a TTL of `2 * window_seconds` (2 hours for a 1-hour window), so Redis automatically cleans up old keys. No cron jobs or manual expiry needed.

#### Fail-Open Strategy

If Redis is down (either at startup or mid-request), the limiter **allows the request through** and logs a warning:

```python
r = get_redis()
if r is None:
    return  # No Redis → allow

try:
    result = await r.eval(...)
except RedisError:
    logger.warning("Redis error — failing open")
    return  # Redis error → allow
```

The rationale: temporarily losing rate limiting is better than a total auth outage. If Redis goes down for 5 minutes, users can still log in — they just aren't rate-limited during that window.

#### Client Key Construction

Two modes, controlled by `use_email_key`:

- **IP only** (`use_email_key=False`): Used for endpoints where the attacker doesn't supply an identifier (reset-password POST, registration, refresh, verify-email GET, validate-reset-code GET). Key = `192.168.1.1`

- **IP + email** (`use_email_key=True`): Used for credential-based endpoints (login, forgot-password, resend-verification). Key = `192.168.1.1:user@example.com`. This prevents an attacker from locking out a victim by flooding requests for the victim's email from a different IP — each IP+email combo has its own counter.

#### Dual Limiters on Login

Login has **two** rate limiters applied simultaneously:

```python
@auth_router.post("/login", dependencies=[Depends(login_limiter), Depends(login_global_limiter)])
```

- `login_limiter` (10/hr, IP+email) — stops brute-force against a single account
- `login_global_limiter` (30/hr, IP only) — stops credential stuffing (trying many accounts from one IP)

Both must pass for the request to proceed. FastAPI evaluates dependencies in order — if the first rejects, the second doesn't run.

### Route Wiring

Each limiter is attached via `dependencies=[Depends(limiter)]` on the route decorator. This runs the limiter *before* the route handler. If the limiter raises `HTTPException(429)`, the route handler never executes.

```python
# Existing (already had limiters):
@auth_router.post("/forgot-password", dependencies=[Depends(forgot_password_limiter)])
@auth_router.post("/reset-password",  dependencies=[Depends(reset_password_limiter)])
@auth_router.post("/resend-verification", dependencies=[Depends(resend_verification_limiter)])

# New:
@auth_router.post("/login", dependencies=[Depends(login_limiter), Depends(login_global_limiter)])
@auth_router.post("/refresh", dependencies=[Depends(refresh_limiter)])
@auth_router.get("/verify-email", dependencies=[Depends(verify_email_limiter)])
@auth_router.get("/reset-password", dependencies=[Depends(validate_reset_code_limiter)])
@user_router.post("/users/create", dependencies=[Depends(registration_limiter)])
```

---

## Response Headers

Every rate-limited endpoint returns these headers on **successful** responses:

```
X-RateLimit-Limit: 10          # max requests allowed in the window
X-RateLimit-Remaining: 7       # requests remaining before hitting the limit
X-RateLimit-Reset: 1710590400  # unix timestamp when the current window resets
```

On **429 responses**, the `HTTPException` also includes:

```
Retry-After: 2345              # seconds until the client should retry
```

---

## Testing

### fakeredis

Tests use `fakeredis[lua]` — an in-process Python implementation of Redis that supports Lua scripting. No real Redis server is needed to run tests or CI.

The `fake_redis` fixture in `conftest.py` (autouse) does three things:

1. Creates a `FakeRedis` instance
2. Monkeypatches `app.core.redis._redis_client` with it
3. Monkeypatches `init_redis`/`close_redis` to no-ops (so the lifespan doesn't overwrite the fake with a real connection attempt)

Each test gets a fresh `FakeRedis` instance, so counters don't leak between tests.

### What's tested

| Test | What it verifies |
|---|---|
| `test_forgot_password_rate_limit` | 6th request returns 429 (limit 5) |
| `test_resend_verification_rate_limit` | 6th request returns 429 (limit 5) |
| `test_reset_password_rate_limit` | 11th request returns 429 (limit 10) |
| `test_rate_limit_different_emails_independent` | Different emails have separate counters |
| `test_login_rate_limit` | 11th login to same account returns 429 |
| `test_login_global_rate_limit` | 31st login from same IP (different accounts) returns 429 |
| `test_registration_rate_limit` | 6th registration from same IP returns 429 |
| `test_refresh_rate_limit` | 31st refresh from same IP returns 429 |
| `test_verify_email_rate_limit` | 11th verify-email from same IP returns 429 |
| `test_validate_reset_code_rate_limit` | 11th validate-reset-code from same IP returns 429 |
| `test_rate_limit_response_headers` | Successful responses include X-RateLimit-* headers |
| `test_429_includes_retry_after` | 429 responses include Retry-After header |
| `test_fail_open_when_redis_down` | Requests succeed when Redis is None |
| `test_limiters_are_independent` | Exhausting one limiter doesn't affect another |

---

## Production Considerations

- **Redis should be persistent** (RDB or AOF) if you don't want counters to reset on Redis restart. However, since keys auto-expire after 2 hours, losing them is not catastrophic.
- **Redis Sentinel or Cluster** can be used for HA — just change `REDIS_URL` to a sentinel:// or redis+cluster:// URL.
- **Reverse proxy IPs**: If behind nginx/ALB, make sure `request.client.host` returns the real client IP (configure trusted proxies in uvicorn or use `X-Forwarded-For`).
- **Key cardinality**: Each unique IP (or IP+email) creates 2 keys that expire after 2 hours. Under normal traffic this is negligible. Under a DDoS with millions of unique IPs, Redis memory could spike — consider adding a firewall/WAF layer before this.

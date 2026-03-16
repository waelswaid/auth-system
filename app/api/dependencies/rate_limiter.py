import time
import json
from collections import defaultdict
from threading import Lock
from fastapi import HTTPException, Request


class RateLimiter:

    def __init__(self, max_requests: int, window_seconds: int, use_email_key: bool = False):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.use_email_key = use_email_key
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def _build_key(self, request: Request, body_bytes: bytes) -> str:
        ip = request.client.host if request.client else "unknown"
        if self.use_email_key:
            try:
                data = json.loads(body_bytes)
                email = data.get("email", "")
            except (json.JSONDecodeError, UnicodeDecodeError):
                email = ""
            return f"{ip}:{email}"
        return ip

    def _prune(self, key: str) -> None:
        cutoff = time.monotonic() - self.window_seconds
        self._hits[key] = [t for t in self._hits[key] if t > cutoff]

    async def __call__(self, request: Request) -> None:
        body_bytes = await request.body()
        key = self._build_key(request, body_bytes)

        with self._lock:
            self._prune(key)
            if len(self._hits[key]) >= self.max_requests:
                raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")
            self._hits[key].append(time.monotonic())


forgot_password_limiter = RateLimiter(max_requests=5, window_seconds=3600, use_email_key=True)
resend_verification_limiter = RateLimiter(max_requests=5, window_seconds=3600, use_email_key=True)
reset_password_limiter = RateLimiter(max_requests=10, window_seconds=3600)

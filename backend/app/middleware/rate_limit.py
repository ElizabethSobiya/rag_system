"""Simple in-memory rate limiter for document upload and query endpoints."""
import time
from collections import defaultdict

from fastapi import HTTPException, Request


class RateLimiter:
    """Token-bucket rate limiter keyed by client IP."""

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)

    def _client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _prune(self, key: str, now: float) -> None:
        cutoff = now - self.window_seconds
        self._hits[key] = [t for t in self._hits[key] if t > cutoff]

    def check(self, request: Request) -> None:
        """Raise 429 if the client has exceeded the rate limit."""
        now = time.monotonic()
        key = self._client_ip(request)
        self._prune(key, now)
        if len(self._hits[key]) >= self.max_requests:
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Please try again later.",
            )
        self._hits[key].append(now)


# 10 uploads per minute per IP
upload_limiter = RateLimiter(max_requests=10, window_seconds=60)

# 30 queries per minute per IP
query_limiter = RateLimiter(max_requests=30, window_seconds=60)

"""
Rate limiting middleware for FastAPI.
Implements in-memory token bucket rate limiting with per-IP tracking.

v3.2.0: Hard Security
"""
import os
import time
from collections import defaultdict
from typing import Dict, Tuple, Optional
from dataclasses import dataclass, field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from prometheus_client import Counter


# Environment configuration
RL_LOGIN_PER_IP_PER_MIN = int(os.getenv("RL_LOGIN_PER_IP_PER_MIN", "10"))
RL_INVITE_ACCEPT_PER_IP_PER_MIN = int(os.getenv("RL_INVITE_ACCEPT_PER_IP_PER_MIN", "10"))
RL_SHARE_ACCESS_PER_IP_PER_MIN = int(os.getenv("RL_SHARE_ACCESS_PER_IP_PER_MIN", "30"))
RL_GLOBAL_PER_IP_PER_MIN = int(os.getenv("RL_GLOBAL_PER_IP_PER_MIN", "120"))

# TTL for bucket cleanup (seconds)
BUCKET_TTL_SECONDS = 300  # 5 minutes


# Prometheus metrics
RATE_LIMITED_TOTAL = Counter(
    "bess_rate_limited_total",
    "Total number of rate limited requests",
    ["bucket"]
)

RATE_LIMIT_BUCKET_SIZE = Counter(
    "bess_rate_limit_bucket_requests_total",
    "Total requests per rate limit bucket (for debugging)",
    ["bucket"]
)


@dataclass
class TokenBucket:
    """Token bucket for rate limiting."""
    tokens: float
    max_tokens: int
    refill_rate: float  # tokens per second
    last_refill: float = field(default_factory=time.time)

    def consume(self) -> Tuple[bool, float]:
        """
        Try to consume a token.

        Returns:
            Tuple of (allowed, retry_after_seconds)
        """
        now = time.time()
        # Refill tokens based on time elapsed
        elapsed = now - self.last_refill
        self.tokens = min(self.max_tokens, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

        if self.tokens >= 1:
            self.tokens -= 1
            return True, 0

        # Calculate retry after
        tokens_needed = 1 - self.tokens
        retry_after = tokens_needed / self.refill_rate
        return False, retry_after


class RateLimitStore:
    """In-memory store for rate limit buckets."""

    def __init__(self):
        # {bucket_name: {ip: TokenBucket}}
        self._buckets: Dict[str, Dict[str, TokenBucket]] = defaultdict(dict)
        self._last_cleanup = time.time()

    def get_or_create_bucket(
        self,
        bucket_name: str,
        ip: str,
        max_tokens: int,
        refill_per_minute: int
    ) -> TokenBucket:
        """Get or create a token bucket for IP in specified bucket."""
        self._maybe_cleanup()

        if ip not in self._buckets[bucket_name]:
            self._buckets[bucket_name][ip] = TokenBucket(
                tokens=max_tokens,
                max_tokens=max_tokens,
                refill_rate=refill_per_minute / 60.0
            )
        return self._buckets[bucket_name][ip]

    def _maybe_cleanup(self):
        """Clean up old buckets periodically."""
        now = time.time()
        if now - self._last_cleanup < 60:  # cleanup every minute
            return

        self._last_cleanup = now
        cutoff = now - BUCKET_TTL_SECONDS

        for bucket_name in list(self._buckets.keys()):
            for ip in list(self._buckets[bucket_name].keys()):
                bucket = self._buckets[bucket_name][ip]
                if bucket.last_refill < cutoff:
                    del self._buckets[bucket_name][ip]


# Global store instance
_store = RateLimitStore()


def get_client_ip(request: Request) -> str:
    """Extract client IP from request."""
    # Check X-Forwarded-For header first (for proxied requests)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # Take first IP in chain
        return forwarded.split(",")[0].strip()

    # Fall back to direct client
    if request.client:
        return request.client.host
    return "unknown"


def get_bucket_for_path(path: str) -> Optional[Tuple[str, int]]:
    """
    Determine rate limit bucket and limit for a path.

    Returns:
        Tuple of (bucket_name, limit_per_minute) or None if no specific bucket
    """
    path_lower = path.lower()

    # Login endpoints
    if "/auth/login" in path_lower or path_lower.endswith("/login"):
        return ("login", RL_LOGIN_PER_IP_PER_MIN)

    # Invite accept endpoints
    if "/invite" in path_lower and "/accept" in path_lower:
        return ("invite_accept", RL_INVITE_ACCEPT_PER_IP_PER_MIN)

    # Share access endpoints
    if "/shared/" in path_lower or "/share/" in path_lower:
        return ("share_access", RL_SHARE_ACCESS_PER_IP_PER_MIN)

    return None


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware.

    Applies bucket-specific limits for sensitive endpoints and
    a global limit for all requests.
    """

    async def dispatch(self, request: Request, call_next):
        client_ip = get_client_ip(request)
        path = request.url.path

        # Check bucket-specific limit first
        bucket_info = get_bucket_for_path(path)
        if bucket_info:
            bucket_name, limit = bucket_info
            bucket = _store.get_or_create_bucket(
                bucket_name, client_ip, limit, limit
            )
            allowed, retry_after = bucket.consume()

            RATE_LIMIT_BUCKET_SIZE.labels(bucket=bucket_name).inc()

            if not allowed:
                RATE_LIMITED_TOTAL.labels(bucket=bucket_name).inc()
                return self._rate_limit_response(retry_after)

        # Check global limit
        global_bucket = _store.get_or_create_bucket(
            "global", client_ip, RL_GLOBAL_PER_IP_PER_MIN, RL_GLOBAL_PER_IP_PER_MIN
        )
        allowed, retry_after = global_bucket.consume()

        RATE_LIMIT_BUCKET_SIZE.labels(bucket="global").inc()

        if not allowed:
            RATE_LIMITED_TOTAL.labels(bucket="global").inc()
            return self._rate_limit_response(retry_after)

        return await call_next(request)

    def _rate_limit_response(self, retry_after: float) -> JSONResponse:
        """Create 429 rate limit response."""
        retry_seconds = max(1, int(retry_after) + 1)
        return JSONResponse(
            status_code=429,
            content={
                "error_code": "RATE_LIMITED",
                "detail": "Too many requests. Please try again later.",
                "retry_after_seconds": retry_seconds
            },
            headers={"Retry-After": str(retry_seconds)}
        )


def reset_rate_limits():
    """Reset all rate limit buckets (for testing)."""
    global _store
    _store = RateLimitStore()

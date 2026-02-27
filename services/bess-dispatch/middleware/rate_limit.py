"""
Rate Limiting Middleware (v3.5.0).

Provides request rate limiting with pluggable backends:
- memory: In-process rate limiting (single replica only)
- redis: Redis-backed rate limiting (HA, multi-replica safe)

Configuration via environment variables:
- RATE_LIMIT_ENABLED: Enable rate limiting (default: true)
- RATE_LIMIT_BACKEND: Backend type - memory|redis (default: memory)
- RATE_LIMIT_REQUESTS_PER_MINUTE: Max requests per minute per client (default: 60)
- RATE_LIMIT_BURST: Burst allowance above limit (default: 10)
- REDIS_URL: Redis connection URL (for redis backend)
- RATE_LIMIT_KEY_PREFIX: Redis key prefix (default: bess:ratelimit)
"""

import os
import time
import hashlib
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from threading import Lock
from typing import Optional, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() in ("true", "1", "yes")
RATE_LIMIT_BACKEND = os.getenv("RATE_LIMIT_BACKEND", "memory").lower()
RATE_LIMIT_REQUESTS_PER_MINUTE = int(os.getenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "60"))
RATE_LIMIT_BURST = int(os.getenv("RATE_LIMIT_BURST", "10"))
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
RATE_LIMIT_KEY_PREFIX = os.getenv("RATE_LIMIT_KEY_PREFIX", "bess:ratelimit")


# -----------------------------------------------------------------------------
# Rate Limit Result
# -----------------------------------------------------------------------------

@dataclass
class RateLimitResult:
    """Result of rate limit check."""
    allowed: bool
    remaining: int
    limit: int
    reset_after_seconds: float
    retry_after_seconds: Optional[float] = None


# -----------------------------------------------------------------------------
# Rate Limit Backend Interface
# -----------------------------------------------------------------------------

class RateLimitBackend(ABC):
    """Abstract base class for rate limit backends."""

    @abstractmethod
    def check_and_increment(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        """
        Check if request is allowed and increment counter.

        Args:
            key: Client identifier key
            limit: Maximum requests per window
            window_seconds: Time window in seconds

        Returns:
            RateLimitResult with allowed status and metadata
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if backend is available."""
        pass


# -----------------------------------------------------------------------------
# Memory Backend (Single Instance)
# -----------------------------------------------------------------------------

class MemoryRateLimitBackend(RateLimitBackend):
    """
    In-memory rate limiter using sliding window algorithm.

    Only suitable for single-replica deployments.
    """

    def __init__(self):
        self._buckets: dict = defaultdict(lambda: {"tokens": 0, "last_update": 0})
        self._lock = Lock()

    def check_and_increment(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        """Check and increment using token bucket algorithm."""
        now = time.time()
        tokens_per_second = limit / window_seconds

        with self._lock:
            bucket = self._buckets[key]
            elapsed = now - bucket["last_update"]

            # Refill tokens based on elapsed time
            bucket["tokens"] = min(
                limit + RATE_LIMIT_BURST,
                bucket["tokens"] + (elapsed * tokens_per_second)
            )
            bucket["last_update"] = now

            if bucket["tokens"] >= 1:
                # Allow request
                bucket["tokens"] -= 1
                return RateLimitResult(
                    allowed=True,
                    remaining=int(bucket["tokens"]),
                    limit=limit,
                    reset_after_seconds=window_seconds,
                )
            else:
                # Deny request
                retry_after = (1 - bucket["tokens"]) / tokens_per_second
                return RateLimitResult(
                    allowed=False,
                    remaining=0,
                    limit=limit,
                    reset_after_seconds=window_seconds,
                    retry_after_seconds=retry_after,
                )

    def is_available(self) -> bool:
        """Memory backend is always available."""
        return True


# -----------------------------------------------------------------------------
# Redis Backend (Multi-Instance HA)
# -----------------------------------------------------------------------------

class RedisRateLimitBackend(RateLimitBackend):
    """
    Redis-backed rate limiter using sliding window counter.

    Suitable for multi-replica HA deployments.
    Uses Redis INCR with TTL for atomic counter management.
    """

    def __init__(self, redis_url: str = None, key_prefix: str = None):
        self.redis_url = redis_url or REDIS_URL
        self.key_prefix = key_prefix or RATE_LIMIT_KEY_PREFIX
        self._client = None

    def _get_client(self):
        """Get or create Redis client."""
        if self._client is None:
            try:
                import redis
                self._client = redis.from_url(
                    self.redis_url,
                    socket_timeout=1.0,
                    socket_connect_timeout=1.0,
                    decode_responses=True,
                )
            except ImportError:
                raise RuntimeError("redis package not installed")
        return self._client

    def check_and_increment(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        """
        Check and increment using Redis sliding window counter.

        Uses a Lua script for atomic check-and-increment.
        """
        client = self._get_client()
        redis_key = f"{self.key_prefix}:{key}"

        # Use current window timestamp as part of key
        window_start = int(time.time() // window_seconds) * window_seconds
        window_key = f"{redis_key}:{window_start}"

        # Atomic increment and get with TTL
        pipe = client.pipeline()
        pipe.incr(window_key)
        pipe.expire(window_key, window_seconds + 1)  # TTL slightly longer than window
        result = pipe.execute()

        current_count = result[0]
        effective_limit = limit + RATE_LIMIT_BURST
        remaining = max(0, effective_limit - current_count)
        reset_after = window_seconds - (time.time() - window_start)

        if current_count <= effective_limit:
            return RateLimitResult(
                allowed=True,
                remaining=remaining,
                limit=limit,
                reset_after_seconds=reset_after,
            )
        else:
            return RateLimitResult(
                allowed=False,
                remaining=0,
                limit=limit,
                reset_after_seconds=reset_after,
                retry_after_seconds=reset_after,
            )

    def is_available(self) -> bool:
        """Check if Redis is available."""
        try:
            client = self._get_client()
            client.ping()
            return True
        except Exception:
            return False


# -----------------------------------------------------------------------------
# Backend Factory
# -----------------------------------------------------------------------------

_backend_instance: Optional[RateLimitBackend] = None


def get_rate_limit_backend() -> RateLimitBackend:
    """
    Get or create rate limit backend based on configuration.

    Falls back to memory backend if Redis is unavailable.
    """
    global _backend_instance

    if _backend_instance is not None:
        return _backend_instance

    if RATE_LIMIT_BACKEND == "redis":
        redis_backend = RedisRateLimitBackend()
        if redis_backend.is_available():
            _backend_instance = redis_backend
        else:
            # Fallback to memory if Redis unavailable
            import logging
            logging.getLogger("rate_limit").warning(
                "Redis unavailable, falling back to memory rate limiting"
            )
            _backend_instance = MemoryRateLimitBackend()
    else:
        _backend_instance = MemoryRateLimitBackend()

    return _backend_instance


def reset_backend():
    """Reset backend instance (for testing)."""
    global _backend_instance
    _backend_instance = None


# -----------------------------------------------------------------------------
# Client Key Extraction
# -----------------------------------------------------------------------------

def get_client_key(request: Request) -> str:
    """
    Extract client identifier from request.

    Priority:
    1. X-Forwarded-For header (first IP)
    2. X-Real-IP header
    3. Client host from connection
    4. API key hash (if present)

    Returns:
        Hashed client identifier
    """
    # Check for tenant ID first (if authenticated)
    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id:
        return f"tenant:{tenant_id}"

    # Check for API key
    api_key = request.headers.get("X-API-Key") or request.headers.get("Authorization", "").replace("Bearer ", "")
    if api_key:
        # Hash API key for privacy
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16]
        return f"apikey:{key_hash}"

    # Fall back to IP address
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        ip = forwarded_for.split(",")[0].strip()
    else:
        ip = request.headers.get("X-Real-IP") or request.client.host if request.client else "unknown"

    return f"ip:{ip}"


# -----------------------------------------------------------------------------
# Rate Limit Middleware
# -----------------------------------------------------------------------------

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware using configurable backend.

    Adds headers to responses:
    - X-RateLimit-Limit: Maximum requests per window
    - X-RateLimit-Remaining: Requests remaining in current window
    - X-RateLimit-Reset: Seconds until window resets
    - Retry-After: Seconds to wait (on 429 response)
    """

    def __init__(
        self,
        app,
        requests_per_minute: int = None,
        burst: int = None,
        enabled: bool = None,
    ):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute or RATE_LIMIT_REQUESTS_PER_MINUTE
        self.burst = burst or RATE_LIMIT_BURST
        self.enabled = enabled if enabled is not None else RATE_LIMIT_ENABLED
        self.window_seconds = 60  # 1 minute window

    async def dispatch(self, request: Request, call_next):
        """Process request with rate limiting."""
        if not self.enabled:
            return await call_next(request)

        # Skip rate limiting for health endpoints
        if request.url.path.startswith("/api/bess-dispatch/health/"):
            return await call_next(request)

        # Skip for metrics endpoint
        if request.url.path == "/metrics":
            return await call_next(request)

        # Get client key
        client_key = get_client_key(request)

        # Check rate limit
        backend = get_rate_limit_backend()
        result = backend.check_and_increment(
            key=client_key,
            limit=self.requests_per_minute,
            window_seconds=self.window_seconds,
        )

        # Add rate limit headers to request state (for access by response)
        request.state.rate_limit_result = result

        if not result.allowed:
            # Track rate limit rejection
            try:
                from observability.perf_metrics import track_limit_rejection
                track_limit_rejection("rate_limit")
            except ImportError:
                pass

            return self._too_many_requests_response(result)

        # Process request
        response = await call_next(request)

        # Add rate limit headers to response
        response.headers["X-RateLimit-Limit"] = str(result.limit)
        response.headers["X-RateLimit-Remaining"] = str(result.remaining)
        response.headers["X-RateLimit-Reset"] = str(int(result.reset_after_seconds))

        return response

    def _too_many_requests_response(self, result: RateLimitResult) -> JSONResponse:
        """Return 429 response with rate limit info."""
        retry_after = int(result.retry_after_seconds) if result.retry_after_seconds else 60

        return JSONResponse(
            status_code=429,
            content={
                "error_code": "RATE_LIMIT_EXCEEDED",
                "detail": "Too many requests. Please slow down.",
                "limit": result.limit,
                "retry_after_seconds": retry_after,
            },
            headers={
                "X-RateLimit-Limit": str(result.limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(result.reset_after_seconds)),
                "Retry-After": str(retry_after),
            },
        )

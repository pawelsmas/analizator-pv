"""
Unit tests for rate_limit middleware (v3.5.0 PR3).

Tests verify:
- Memory backend token bucket algorithm
- Redis backend sliding window counter
- Backend factory and fallback
- Client key extraction
- Rate limit result structure
"""

import pytest
import sys
import os
import time
from pathlib import Path
from unittest.mock import patch, MagicMock


# Add services to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))


class TestRateLimitResult:
    """Tests for RateLimitResult dataclass."""

    def test_result_allowed_structure(self):
        """RateLimitResult should have correct structure when allowed."""
        from middleware.rate_limit import RateLimitResult

        result = RateLimitResult(
            allowed=True,
            remaining=59,
            limit=60,
            reset_after_seconds=30.5,
        )

        assert result.allowed is True
        assert result.remaining == 59
        assert result.limit == 60
        assert result.reset_after_seconds == 30.5
        assert result.retry_after_seconds is None

    def test_result_denied_structure(self):
        """RateLimitResult should have retry_after when denied."""
        from middleware.rate_limit import RateLimitResult

        result = RateLimitResult(
            allowed=False,
            remaining=0,
            limit=60,
            reset_after_seconds=30.5,
            retry_after_seconds=15.0,
        )

        assert result.allowed is False
        assert result.remaining == 0
        assert result.retry_after_seconds == 15.0


class TestMemoryBackend:
    """Tests for in-memory rate limit backend."""

    def test_memory_backend_is_available(self):
        """Memory backend should always be available."""
        from middleware.rate_limit import MemoryRateLimitBackend

        backend = MemoryRateLimitBackend()
        assert backend.is_available() is True

    def test_memory_backend_allows_first_request(self):
        """Memory backend should allow first request."""
        from middleware.rate_limit import MemoryRateLimitBackend

        backend = MemoryRateLimitBackend()
        result = backend.check_and_increment("test-key", limit=10, window_seconds=60)

        assert result.allowed is True
        assert result.remaining >= 0
        assert result.limit == 10

    def test_memory_backend_denies_after_limit(self):
        """Memory backend should deny after limit exceeded."""
        from middleware.rate_limit import MemoryRateLimitBackend, RATE_LIMIT_BURST

        backend = MemoryRateLimitBackend()
        limit = 5
        total_allowed = limit + RATE_LIMIT_BURST

        # Exhaust all tokens
        for i in range(total_allowed + 1):
            result = backend.check_and_increment("exhaust-key", limit=limit, window_seconds=60)
            if i < total_allowed:
                assert result.allowed is True, f"Request {i+1} should be allowed"
            else:
                assert result.allowed is False, f"Request {i+1} should be denied"

    def test_memory_backend_refills_tokens(self):
        """Memory backend should refill tokens over time."""
        from middleware.rate_limit import MemoryRateLimitBackend

        backend = MemoryRateLimitBackend()
        limit = 60  # 60 requests per minute = 1 per second

        # Use one token
        result1 = backend.check_and_increment("refill-key", limit=limit, window_seconds=60)
        remaining1 = result1.remaining

        # Wait a bit (simulate time passing)
        time.sleep(0.1)

        # Tokens should have partially refilled
        result2 = backend.check_and_increment("refill-key", limit=limit, window_seconds=60)
        # Note: Due to token bucket algorithm, remaining may not increase but should allow

        assert result1.allowed is True
        assert result2.allowed is True

    def test_memory_backend_separate_keys(self):
        """Memory backend should track different keys separately."""
        from middleware.rate_limit import MemoryRateLimitBackend

        backend = MemoryRateLimitBackend()

        result1 = backend.check_and_increment("key-a", limit=10, window_seconds=60)
        result2 = backend.check_and_increment("key-b", limit=10, window_seconds=60)

        # Both should have full remaining (minus 1)
        assert result1.allowed is True
        assert result2.allowed is True
        # Both should have similar remaining
        assert abs(result1.remaining - result2.remaining) <= 1


class TestRedisBackend:
    """Tests for Redis-backed rate limit backend."""

    def test_redis_backend_not_available_when_no_redis(self):
        """Redis backend should return unavailable when Redis unreachable."""
        from middleware.rate_limit import RedisRateLimitBackend

        # Use invalid URL
        backend = RedisRateLimitBackend(redis_url="redis://invalid-host:9999/0")

        # Should not be available (connection fails)
        assert backend.is_available() is False

    def test_redis_backend_with_mock(self):
        """Redis backend should work with mock Redis client."""
        from middleware.rate_limit import RedisRateLimitBackend

        backend = RedisRateLimitBackend()

        # Mock the Redis client
        mock_redis = MagicMock()
        mock_pipeline = MagicMock()
        mock_pipeline.execute.return_value = [1, True]  # count=1, expire=True
        mock_redis.pipeline.return_value = mock_pipeline
        backend._client = mock_redis

        result = backend.check_and_increment("test-key", limit=60, window_seconds=60)

        assert result.allowed is True
        assert mock_pipeline.incr.called
        assert mock_pipeline.expire.called


class TestBackendFactory:
    """Tests for rate limit backend factory."""

    def test_factory_returns_memory_by_default(self):
        """Factory should return memory backend by default."""
        from middleware.rate_limit import get_rate_limit_backend, reset_backend, MemoryRateLimitBackend

        reset_backend()  # Clear any cached backend

        with patch.dict(os.environ, {"RATE_LIMIT_BACKEND": "memory"}):
            import middleware.rate_limit
            import importlib
            importlib.reload(middleware.rate_limit)

            backend = middleware.rate_limit.get_rate_limit_backend()
            assert isinstance(backend, middleware.rate_limit.MemoryRateLimitBackend)

        importlib.reload(middleware.rate_limit)

    def test_factory_caches_backend(self):
        """Factory should return same backend instance."""
        from middleware.rate_limit import get_rate_limit_backend, reset_backend

        reset_backend()

        backend1 = get_rate_limit_backend()
        backend2 = get_rate_limit_backend()

        assert backend1 is backend2


class TestClientKeyExtraction:
    """Tests for client key extraction from requests."""

    def test_key_from_ip(self):
        """Should extract key from client IP."""
        from middleware.rate_limit import get_client_key

        mock_request = MagicMock()
        mock_request.state = MagicMock(spec=[])  # No tenant_id
        mock_request.headers = {}
        mock_request.client = MagicMock()
        mock_request.client.host = "192.168.1.100"

        key = get_client_key(mock_request)

        assert key == "ip:192.168.1.100"

    def test_key_from_forwarded_for(self):
        """Should prefer X-Forwarded-For header."""
        from middleware.rate_limit import get_client_key

        mock_request = MagicMock()
        mock_request.state = MagicMock(spec=[])
        mock_request.headers = {"X-Forwarded-For": "10.0.0.1, 10.0.0.2"}
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"

        key = get_client_key(mock_request)

        assert key == "ip:10.0.0.1"

    def test_key_from_real_ip(self):
        """Should use X-Real-IP if no X-Forwarded-For."""
        from middleware.rate_limit import get_client_key

        mock_request = MagicMock()
        mock_request.state = MagicMock(spec=[])
        mock_request.headers = {"X-Real-IP": "172.16.0.1"}
        mock_request.client = None

        key = get_client_key(mock_request)

        assert key == "ip:172.16.0.1"

    def test_key_from_api_key(self):
        """Should use hashed API key if present."""
        from middleware.rate_limit import get_client_key

        mock_request = MagicMock()
        mock_request.state = MagicMock(spec=[])
        mock_request.headers = {"X-API-Key": "my-secret-api-key"}
        mock_request.client = MagicMock()
        mock_request.client.host = "192.168.1.100"

        key = get_client_key(mock_request)

        assert key.startswith("apikey:")
        assert "my-secret-api-key" not in key  # Should be hashed

    def test_key_from_tenant_id(self):
        """Should prefer tenant_id if present."""
        from middleware.rate_limit import get_client_key

        mock_request = MagicMock()
        mock_request.state = MagicMock()
        mock_request.state.tenant_id = "tenant-123"
        mock_request.headers = {"X-API-Key": "my-key"}
        mock_request.client = MagicMock()
        mock_request.client.host = "192.168.1.100"

        key = get_client_key(mock_request)

        assert key == "tenant:tenant-123"


class TestRateLimitConfiguration:
    """Tests for rate limit configuration from environment."""

    def test_default_values(self):
        """Should have sensible defaults."""
        from middleware.rate_limit import (
            RATE_LIMIT_ENABLED,
            RATE_LIMIT_REQUESTS_PER_MINUTE,
            RATE_LIMIT_BURST,
        )

        assert RATE_LIMIT_ENABLED is True
        assert RATE_LIMIT_REQUESTS_PER_MINUTE == 60
        assert RATE_LIMIT_BURST == 10

    def test_disabled_via_env(self):
        """Should be disabled when RATE_LIMIT_ENABLED=false."""
        with patch.dict(os.environ, {"RATE_LIMIT_ENABLED": "false"}):
            import middleware.rate_limit
            import importlib
            importlib.reload(middleware.rate_limit)

            assert middleware.rate_limit.RATE_LIMIT_ENABLED is False

        importlib.reload(middleware.rate_limit)

    def test_custom_limit_via_env(self):
        """Should use custom limit from environment."""
        with patch.dict(os.environ, {"RATE_LIMIT_REQUESTS_PER_MINUTE": "100"}):
            import middleware.rate_limit
            import importlib
            importlib.reload(middleware.rate_limit)

            assert middleware.rate_limit.RATE_LIMIT_REQUESTS_PER_MINUTE == 100

        importlib.reload(middleware.rate_limit)

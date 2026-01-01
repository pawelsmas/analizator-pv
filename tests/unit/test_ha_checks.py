"""
Unit tests for HA dependency checks (v3.5.0 PR6).

Tests verify:
- Health helper dependency checks
- Rate limit backend fallback
- Artifact store backend fallback
- Backend availability detection
"""

import pytest
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock


# Add services to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))


class TestHealthHelperDependencyChecks:
    """Tests for health helper dependency checks."""

    def test_db_check_returns_dict(self):
        """DB check should return dict with required fields."""
        from health_helper import check_db

        result = check_db()

        assert isinstance(result, dict)
        assert "status" in result
        assert "latency_ms" in result

    def test_redis_check_returns_dict(self):
        """Redis check should return dict with required fields."""
        from health_helper import check_redis

        result = check_redis()

        assert isinstance(result, dict)
        assert "status" in result
        assert "latency_ms" in result

    def test_s3_check_returns_dict(self):
        """S3 check should return dict with required fields."""
        from health_helper import check_s3

        result = check_s3()

        assert isinstance(result, dict)
        assert "status" in result
        assert "latency_ms" in result

    def test_readiness_aggregates_all_checks(self):
        """Readiness should aggregate all dependency checks."""
        from health_helper import check_readiness

        result = check_readiness()

        assert "db" in result.checks
        assert "redis" in result.checks
        assert "s3" in result.checks


class TestRateLimitBackendFallback:
    """Tests for rate limit backend fallback behavior."""

    def test_memory_backend_always_available(self):
        """Memory backend should always be available."""
        from middleware.rate_limit import MemoryRateLimitBackend

        backend = MemoryRateLimitBackend()
        assert backend.is_available() is True

    def test_redis_backend_unavailable_with_bad_url(self):
        """Redis backend should be unavailable with invalid URL."""
        from middleware.rate_limit import RedisRateLimitBackend

        backend = RedisRateLimitBackend(redis_url="redis://nonexistent:9999/0")
        assert backend.is_available() is False

    def test_factory_falls_back_to_memory(self):
        """Factory should fall back to memory if Redis unavailable."""
        from middleware.rate_limit import reset_backend

        reset_backend()

        with patch.dict(os.environ, {"RATE_LIMIT_BACKEND": "redis", "REDIS_URL": "redis://nonexistent:9999/0"}):
            import middleware.rate_limit
            import importlib
            importlib.reload(middleware.rate_limit)

            backend = middleware.rate_limit.get_rate_limit_backend()
            assert isinstance(backend, middleware.rate_limit.MemoryRateLimitBackend)

        importlib.reload(middleware.rate_limit)


class TestArtifactStoreBackendFallback:
    """Tests for artifact store backend fallback behavior."""

    def test_local_backend_always_available(self):
        """Local backend should be available with valid path."""
        import tempfile
        from artifact_store import LocalArtifactStore

        with tempfile.TemporaryDirectory() as tmpdir:
            store = LocalArtifactStore(base_path=tmpdir)
            assert store.is_available() is True

    def test_s3_backend_unavailable_without_config(self):
        """S3 backend should be unavailable without proper config."""
        from artifact_store import S3ArtifactStore

        store = S3ArtifactStore(endpoint="", bucket="")
        assert store.is_available() is False

    def test_factory_falls_back_to_local(self):
        """Factory should fall back to local if S3 unavailable."""
        from artifact_store import reset_store

        reset_store()

        with patch.dict(os.environ, {
            "ARTIFACT_STORE_BACKEND": "s3",
            "S3_ENDPOINT": "http://nonexistent:9000",
            "S3_BUCKET": "test"
        }):
            import artifact_store
            import importlib
            importlib.reload(artifact_store)

            store = artifact_store.get_artifact_store()
            assert isinstance(store, artifact_store.LocalArtifactStore)

        importlib.reload(artifact_store)


class TestBackendAvailabilityDetection:
    """Tests for backend availability detection."""

    def test_redis_availability_cached(self):
        """Redis availability check should be performed on first request."""
        from middleware.rate_limit import reset_backend, get_rate_limit_backend

        reset_backend()

        # First call creates backend
        backend1 = get_rate_limit_backend()
        # Second call returns cached backend
        backend2 = get_rate_limit_backend()

        assert backend1 is backend2

    def test_artifact_store_availability_cached(self):
        """Artifact store availability check should be performed on first request."""
        from artifact_store import reset_store, get_artifact_store

        reset_store()

        # First call creates store
        store1 = get_artifact_store()
        # Second call returns cached store
        store2 = get_artifact_store()

        assert store1 is store2


class TestHAConfigurationVariables:
    """Tests for HA configuration via environment variables."""

    def test_rate_limit_backend_default(self):
        """Rate limit backend should default to memory."""
        with patch.dict(os.environ, {}, clear=False):
            # Remove any existing RATE_LIMIT_BACKEND
            os.environ.pop("RATE_LIMIT_BACKEND", None)

            import middleware.rate_limit
            import importlib
            importlib.reload(middleware.rate_limit)

            assert middleware.rate_limit.RATE_LIMIT_BACKEND == "memory"

        importlib.reload(middleware.rate_limit)

    def test_artifact_store_backend_default(self):
        """Artifact store backend should default to local."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ARTIFACT_STORE_BACKEND", None)

            import artifact_store
            import importlib
            importlib.reload(artifact_store)

            assert artifact_store.ARTIFACT_STORE_BACKEND == "local"

        importlib.reload(artifact_store)

    def test_redis_url_default(self):
        """Redis URL should have sensible default."""
        import middleware.rate_limit

        assert "localhost:6379" in middleware.rate_limit.REDIS_URL

    def test_s3_bucket_default(self):
        """S3 bucket should have sensible default."""
        import artifact_store

        assert artifact_store.S3_BUCKET == "bess-artifacts"


class TestGracefulDegradation:
    """Tests for graceful degradation when backends unavailable."""

    def test_rate_limit_works_without_redis(self):
        """Rate limiting should work in memory mode without Redis."""
        from middleware.rate_limit import reset_backend, MemoryRateLimitBackend

        reset_backend()

        with patch.dict(os.environ, {"RATE_LIMIT_BACKEND": "memory"}):
            import middleware.rate_limit
            import importlib
            importlib.reload(middleware.rate_limit)

            backend = middleware.rate_limit.get_rate_limit_backend()
            assert isinstance(backend, MemoryRateLimitBackend)

            # Should work
            result = backend.check_and_increment("test", 10, 60)
            assert result.allowed is True

        importlib.reload(middleware.rate_limit)

    def test_artifact_store_works_without_s3(self):
        """Artifact store should work in local mode without S3."""
        import tempfile
        import io
        from artifact_store import reset_store, LocalArtifactStore

        reset_store()

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {
                "ARTIFACT_STORE_BACKEND": "local",
                "ARTIFACT_STORE_PATH": tmpdir
            }):
                import artifact_store
                import importlib
                importlib.reload(artifact_store)

                store = artifact_store.get_artifact_store()
                assert isinstance(store, LocalArtifactStore)

                # Should work
                metadata = store.store("job-1", "test.txt", io.BytesIO(b"content"))
                assert metadata.artifact_id is not None

            importlib.reload(artifact_store)

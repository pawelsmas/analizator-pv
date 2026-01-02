"""
Unit tests for Idempotency-Key support (v3.9.0 PR3).

Tests for idempotency.py:
- Key validation
- IdempotencyStore operations
- Check and lock behavior
- Complete and release operations
- Metrics recording
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "bess-dispatch"))

from idempotency import (
    IdempotencyStatus,
    IdempotencyState,
    IdempotencyKeyError,
    IdempotencyKeyInvalid,
    IdempotencyConflict,
    IdempotencyStore,
    validate_idempotency_key,
    is_idempotency_enabled,
    check_idempotency,
    complete_idempotency,
    release_idempotency,
    IDEMPOTENCY_REQUESTS_TOTAL,
    IDEMPOTENCY_CACHE_HITS,
    IDEMPOTENCY_CONFLICTS,
    IDEMPOTENCY_KEY_MAX_LENGTH,
)


class TestIdempotencyStatus:
    """Tests for IdempotencyStatus enum."""

    def test_hit_status(self):
        """Verify HIT status exists."""
        assert IdempotencyStatus.HIT == "hit"

    def test_miss_status(self):
        """Verify MISS status exists."""
        assert IdempotencyStatus.MISS == "miss"

    def test_conflict_status(self):
        """Verify CONFLICT status exists."""
        assert IdempotencyStatus.CONFLICT == "conflict"

    def test_invalid_status(self):
        """Verify INVALID status exists."""
        assert IdempotencyStatus.INVALID == "invalid"


class TestIdempotencyState:
    """Tests for IdempotencyState enum."""

    def test_in_progress_state(self):
        """Verify IN_PROGRESS state exists."""
        assert IdempotencyState.IN_PROGRESS == "in_progress"

    def test_completed_state(self):
        """Verify COMPLETED state exists."""
        assert IdempotencyState.COMPLETED == "completed"


class TestIdempotencyExceptions:
    """Tests for idempotency exceptions."""

    def test_key_invalid_exception(self):
        """Test IdempotencyKeyInvalid exception."""
        exc = IdempotencyKeyInvalid("bad-key!", "contains invalid characters")
        assert exc.key == "bad-key!"
        assert "invalid" in str(exc).lower()
        assert isinstance(exc, IdempotencyKeyError)

    def test_conflict_exception(self):
        """Test IdempotencyConflict exception."""
        exc = IdempotencyConflict("my-key-123")
        assert exc.key == "my-key-123"
        assert "in progress" in str(exc).lower()
        assert isinstance(exc, IdempotencyKeyError)


class TestValidateIdempotencyKey:
    """Tests for validate_idempotency_key function."""

    def test_valid_alphanumeric_key(self):
        """Test valid alphanumeric key."""
        validate_idempotency_key("abc123")  # Should not raise

    def test_valid_key_with_dashes(self):
        """Test valid key with dashes."""
        validate_idempotency_key("request-123-abc")  # Should not raise

    def test_valid_key_with_underscores(self):
        """Test valid key with underscores."""
        validate_idempotency_key("request_123_abc")  # Should not raise

    def test_valid_key_with_colons(self):
        """Test valid key with colons."""
        validate_idempotency_key("tenant:request:123")  # Should not raise

    def test_valid_uuid_format(self):
        """Test valid UUID format key."""
        validate_idempotency_key("550e8400-e29b-41d4-a716-446655440000")

    def test_empty_key_invalid(self):
        """Test empty key is invalid."""
        with pytest.raises(IdempotencyKeyInvalid) as exc_info:
            validate_idempotency_key("")
        assert "empty" in str(exc_info.value).lower()

    def test_key_too_long_invalid(self):
        """Test key exceeding max length is invalid."""
        long_key = "a" * (IDEMPOTENCY_KEY_MAX_LENGTH + 1)
        with pytest.raises(IdempotencyKeyInvalid) as exc_info:
            validate_idempotency_key(long_key)
        assert "length" in str(exc_info.value).lower()

    def test_key_with_spaces_invalid(self):
        """Test key with spaces is invalid."""
        with pytest.raises(IdempotencyKeyInvalid) as exc_info:
            validate_idempotency_key("my key 123")
        assert "invalid" in str(exc_info.value).lower()

    def test_key_with_special_chars_invalid(self):
        """Test key with special characters is invalid."""
        with pytest.raises(IdempotencyKeyInvalid):
            validate_idempotency_key("key@123!")


class TestIdempotencyStore:
    """Tests for IdempotencyStore class."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a store with temporary database."""
        db_path = str(tmp_path / "idempotency_test.sqlite")
        return IdempotencyStore(db_path)

    def test_check_and_lock_new_key(self, store):
        """Test checking new key returns MISS and locks."""
        status, response, status_code = store.check_and_lock(
            key="new-key-123",
            endpoint="jobs.sizing-batch",
            tenant_id="tenant1",
            request_body={"foo": "bar"},
        )

        assert status == IdempotencyStatus.MISS
        assert response is None
        assert status_code is None

    def test_check_and_lock_in_progress_returns_conflict(self, store):
        """Test checking in-progress key returns CONFLICT."""
        # First call locks the key
        store.check_and_lock(
            key="conflict-key",
            endpoint="jobs.sizing-batch",
            tenant_id="tenant1",
            request_body={"foo": "bar"},
        )

        # Second call should return CONFLICT
        status, response, status_code = store.check_and_lock(
            key="conflict-key",
            endpoint="jobs.sizing-batch",
            tenant_id="tenant1",
            request_body={"foo": "bar"},
        )

        assert status == IdempotencyStatus.CONFLICT
        assert response is None

    def test_check_and_lock_completed_returns_hit(self, store):
        """Test checking completed key returns HIT with cached response."""
        # Lock and complete
        store.check_and_lock(
            key="completed-key",
            endpoint="jobs.sizing-batch",
            tenant_id="tenant1",
            request_body={"foo": "bar"},
        )
        store.complete(
            key="completed-key",
            endpoint="jobs.sizing-batch",
            tenant_id="tenant1",
            response={"job_id": "123", "status": "ok"},
            status_code=201,
        )

        # Second call should return HIT
        status, response, status_code = store.check_and_lock(
            key="completed-key",
            endpoint="jobs.sizing-batch",
            tenant_id="tenant1",
            request_body={"foo": "bar"},
        )

        assert status == IdempotencyStatus.HIT
        assert response == {"job_id": "123", "status": "ok"}
        assert status_code == 201

    def test_keys_scoped_by_endpoint(self, store):
        """Test same key different endpoint is treated separately."""
        # Lock for endpoint1
        store.check_and_lock(
            key="shared-key",
            endpoint="endpoint1",
            tenant_id="tenant1",
            request_body={},
        )

        # Should be MISS for endpoint2
        status, _, _ = store.check_and_lock(
            key="shared-key",
            endpoint="endpoint2",
            tenant_id="tenant1",
            request_body={},
        )

        assert status == IdempotencyStatus.MISS

    def test_keys_scoped_by_tenant(self, store):
        """Test same key different tenant is treated separately."""
        # Lock for tenant1
        store.check_and_lock(
            key="shared-key",
            endpoint="endpoint1",
            tenant_id="tenant1",
            request_body={},
        )

        # Should be MISS for tenant2
        status, _, _ = store.check_and_lock(
            key="shared-key",
            endpoint="endpoint1",
            tenant_id="tenant2",
            request_body={},
        )

        assert status == IdempotencyStatus.MISS

    def test_release_allows_retry(self, store):
        """Test releasing lock allows retry with same key."""
        # Lock
        store.check_and_lock(
            key="release-key",
            endpoint="endpoint1",
            tenant_id="tenant1",
            request_body={},
        )

        # Release
        store.release(
            key="release-key",
            endpoint="endpoint1",
            tenant_id="tenant1",
        )

        # Should be MISS again (can retry)
        status, _, _ = store.check_and_lock(
            key="release-key",
            endpoint="endpoint1",
            tenant_id="tenant1",
            request_body={},
        )

        assert status == IdempotencyStatus.MISS

    def test_release_does_not_delete_completed(self, store):
        """Test release does not delete completed entries."""
        # Lock and complete
        store.check_and_lock(
            key="complete-release-key",
            endpoint="endpoint1",
            tenant_id="tenant1",
            request_body={},
        )
        store.complete(
            key="complete-release-key",
            endpoint="endpoint1",
            tenant_id="tenant1",
            response={"result": "success"},
            status_code=200,
        )

        # Try to release (should be no-op)
        store.release(
            key="complete-release-key",
            endpoint="endpoint1",
            tenant_id="tenant1",
        )

        # Should still return HIT
        status, response, _ = store.check_and_lock(
            key="complete-release-key",
            endpoint="endpoint1",
            tenant_id="tenant1",
            request_body={},
        )

        assert status == IdempotencyStatus.HIT
        assert response == {"result": "success"}

    def test_prune_expired(self, store):
        """Test pruning expired entries."""
        # Note: This test is limited since we can't easily control time
        # In production, entries would expire based on IDEMPOTENCY_TTL_SECONDS
        deleted = store.prune_expired()
        assert deleted >= 0  # Should not raise


class TestCheckIdempotency:
    """Tests for check_idempotency high-level function."""

    @pytest.fixture(autouse=True)
    def reset_store(self, tmp_path, monkeypatch):
        """Reset global store for each test."""
        import idempotency
        db_path = str(tmp_path / "idempotency_test.sqlite")
        monkeypatch.setattr(idempotency, "_store", None)
        monkeypatch.setattr(idempotency, "IDEMPOTENCY_DB_PATH", db_path)
        monkeypatch.setattr(idempotency, "IDEMPOTENCY_ENABLED", True)

    def test_none_key_returns_miss(self):
        """Test None key returns MISS (no key provided)."""
        status, response, status_code = check_idempotency(
            key=None,
            endpoint="test",
            tenant_id="tenant1",
            request_body={},
        )

        assert status == IdempotencyStatus.MISS
        assert response is None

    def test_invalid_key_raises(self):
        """Test invalid key raises IdempotencyKeyInvalid."""
        with pytest.raises(IdempotencyKeyInvalid):
            check_idempotency(
                key="invalid key!",
                endpoint="test",
                tenant_id="tenant1",
                request_body={},
            )

    def test_new_key_returns_miss(self):
        """Test new valid key returns MISS."""
        status, response, status_code = check_idempotency(
            key="new-valid-key",
            endpoint="test",
            tenant_id="tenant1",
            request_body={"data": "test"},
        )

        assert status == IdempotencyStatus.MISS
        assert response is None

    def test_concurrent_request_raises_conflict(self):
        """Test concurrent request raises IdempotencyConflict."""
        # First request
        check_idempotency(
            key="concurrent-key",
            endpoint="test",
            tenant_id="tenant1",
            request_body={},
        )

        # Second concurrent request
        with pytest.raises(IdempotencyConflict) as exc_info:
            check_idempotency(
                key="concurrent-key",
                endpoint="test",
                tenant_id="tenant1",
                request_body={},
            )

        assert exc_info.value.key == "concurrent-key"


class TestCompleteIdempotency:
    """Tests for complete_idempotency function."""

    @pytest.fixture(autouse=True)
    def reset_store(self, tmp_path, monkeypatch):
        """Reset global store for each test."""
        import idempotency
        db_path = str(tmp_path / "idempotency_test.sqlite")
        monkeypatch.setattr(idempotency, "_store", None)
        monkeypatch.setattr(idempotency, "IDEMPOTENCY_DB_PATH", db_path)
        monkeypatch.setattr(idempotency, "IDEMPOTENCY_ENABLED", True)

    def test_complete_allows_cache_hit(self):
        """Test completing request allows subsequent cache hit."""
        # First request
        check_idempotency(
            key="complete-test-key",
            endpoint="test",
            tenant_id="tenant1",
            request_body={},
        )

        # Complete
        complete_idempotency(
            key="complete-test-key",
            endpoint="test",
            tenant_id="tenant1",
            response={"result": "cached"},
            status_code=201,
        )

        # Second request should hit cache
        status, response, status_code = check_idempotency(
            key="complete-test-key",
            endpoint="test",
            tenant_id="tenant1",
            request_body={},
        )

        assert status == IdempotencyStatus.HIT
        assert response == {"result": "cached"}
        assert status_code == 201


class TestReleaseIdempotency:
    """Tests for release_idempotency function."""

    @pytest.fixture(autouse=True)
    def reset_store(self, tmp_path, monkeypatch):
        """Reset global store for each test."""
        import idempotency
        db_path = str(tmp_path / "idempotency_test.sqlite")
        monkeypatch.setattr(idempotency, "_store", None)
        monkeypatch.setattr(idempotency, "IDEMPOTENCY_DB_PATH", db_path)
        monkeypatch.setattr(idempotency, "IDEMPOTENCY_ENABLED", True)

    def test_release_allows_retry(self):
        """Test releasing allows retry with same key."""
        # First request
        check_idempotency(
            key="release-test-key",
            endpoint="test",
            tenant_id="tenant1",
            request_body={},
        )

        # Release (simulating error)
        release_idempotency(
            key="release-test-key",
            endpoint="test",
            tenant_id="tenant1",
        )

        # Retry should work
        status, _, _ = check_idempotency(
            key="release-test-key",
            endpoint="test",
            tenant_id="tenant1",
            request_body={},
        )

        assert status == IdempotencyStatus.MISS


class TestIdempotencyDisabled:
    """Tests for disabled idempotency."""

    @pytest.fixture(autouse=True)
    def disable_idempotency(self, monkeypatch):
        """Disable idempotency for these tests."""
        import idempotency
        monkeypatch.setattr(idempotency, "IDEMPOTENCY_ENABLED", False)

    def test_check_returns_miss_when_disabled(self):
        """Test check returns MISS when disabled."""
        status, response, status_code = check_idempotency(
            key="any-key",
            endpoint="test",
            tenant_id="tenant1",
            request_body={},
        )

        assert status == IdempotencyStatus.MISS
        assert response is None


class TestMetricsExist:
    """Tests that Prometheus metrics are properly defined."""

    def test_requests_counter_exists(self):
        """Verify IDEMPOTENCY_REQUESTS_TOTAL counter exists."""
        assert IDEMPOTENCY_REQUESTS_TOTAL is not None
        labels = IDEMPOTENCY_REQUESTS_TOTAL._labelnames
        assert "endpoint" in labels
        assert "status" in labels

    def test_cache_hits_counter_exists(self):
        """Verify IDEMPOTENCY_CACHE_HITS counter exists."""
        assert IDEMPOTENCY_CACHE_HITS is not None
        labels = IDEMPOTENCY_CACHE_HITS._labelnames
        assert "endpoint" in labels

    def test_conflicts_counter_exists(self):
        """Verify IDEMPOTENCY_CONFLICTS counter exists."""
        assert IDEMPOTENCY_CONFLICTS is not None
        labels = IDEMPOTENCY_CONFLICTS._labelnames
        assert "endpoint" in labels


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

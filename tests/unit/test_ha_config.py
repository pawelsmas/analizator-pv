"""
Unit tests for HA (High Availability) configuration (v3.9.0 PR2).

Tests for ha_config.py:
- HAMode enum
- Strict vs permissive mode behavior
- Dependency state tracking
- HAUnavailableError
- HA decision functions
"""

import os
import sys
from unittest.mock import patch

import pytest

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "bess-dispatch"))

from ha_config import (
    HAMode,
    HAUnavailableError,
    DependencyState,
    is_ha_strict,
    is_ha_permissive,
    get_ha_mode_label,
    get_dependency_state,
    get_ha_status,
    check_redis_available,
    check_s3_available,
    check_database_available,
    update_redis_health,
    update_s3_health,
    update_database_health,
    HA_DEPENDENCY_CHECKS_TOTAL,
    HA_FALLBACK_USED_TOTAL,
    HA_REQUEST_REJECTED_TOTAL,
)


class TestHAMode:
    """Tests for HAMode enum."""

    def test_permissive_mode_exists(self):
        """Verify permissive mode is defined."""
        assert HAMode.PERMISSIVE == "permissive"

    def test_strict_mode_exists(self):
        """Verify strict mode is defined."""
        assert HAMode.STRICT == "strict"

    def test_mode_from_string(self):
        """Test creating mode from string."""
        assert HAMode("permissive") == HAMode.PERMISSIVE
        assert HAMode("strict") == HAMode.STRICT


class TestDependencyState:
    """Tests for DependencyState class."""

    def test_initial_state_all_available(self):
        """Verify initial state has all dependencies available."""
        state = DependencyState()
        assert state.redis_available is True
        assert state.s3_available is True
        assert state.database_available is True
        assert state.all_available() is True

    def test_set_redis_unavailable(self):
        """Test setting Redis as unavailable."""
        state = DependencyState()
        state.redis_available = False
        assert state.redis_available is False
        assert state.all_available() is False

    def test_set_s3_unavailable(self):
        """Test setting S3 as unavailable."""
        state = DependencyState()
        state.s3_available = False
        assert state.s3_available is False
        assert state.all_available() is False

    def test_set_database_unavailable(self):
        """Test setting database as unavailable."""
        state = DependencyState()
        state.database_available = False
        assert state.database_available is False
        assert state.all_available() is False

    def test_to_dict(self):
        """Test converting state to dictionary."""
        state = DependencyState()
        state.redis_available = False

        result = state.to_dict()

        assert result["redis"] is False
        assert result["s3"] is True
        assert result["database"] is True
        assert result["all_available"] is False


class TestHAUnavailableError:
    """Tests for HAUnavailableError exception."""

    def test_error_with_dependency(self):
        """Test creating error with dependency name."""
        error = HAUnavailableError("redis")
        assert error.dependency == "redis"
        assert "redis" in str(error)
        assert "unavailable" in str(error).lower()

    def test_error_with_custom_message(self):
        """Test creating error with custom message."""
        error = HAUnavailableError("s3", "Custom error message")
        assert error.dependency == "s3"
        assert error.message == "Custom error message"
        assert str(error) == "Custom error message"

    def test_error_is_exception(self):
        """Verify error is an Exception."""
        error = HAUnavailableError("database")
        assert isinstance(error, Exception)


class TestHAModeHelpers:
    """Tests for HA mode helper functions."""

    @patch("ha_config.HA_MODE", HAMode.STRICT)
    def test_is_ha_strict_when_strict(self):
        """Test is_ha_strict returns True in strict mode."""
        assert is_ha_strict() is True
        assert is_ha_permissive() is False

    @patch("ha_config.HA_MODE", HAMode.PERMISSIVE)
    def test_is_ha_permissive_when_permissive(self):
        """Test is_ha_permissive returns True in permissive mode."""
        assert is_ha_permissive() is True
        assert is_ha_strict() is False

    @patch("ha_config.HA_MODE", HAMode.STRICT)
    def test_get_ha_mode_label_strict(self):
        """Test get_ha_mode_label returns 'strict'."""
        assert get_ha_mode_label() == "strict"

    @patch("ha_config.HA_MODE", HAMode.PERMISSIVE)
    def test_get_ha_mode_label_permissive(self):
        """Test get_ha_mode_label returns 'permissive'."""
        assert get_ha_mode_label() == "permissive"


class TestCheckRedisAvailable:
    """Tests for check_redis_available function."""

    def setup_method(self):
        """Reset dependency state before each test."""
        state = get_dependency_state()
        state.redis_available = True
        state.s3_available = True
        state.database_available = True

    def test_returns_true_when_available(self):
        """Test returns True when Redis is available."""
        state = get_dependency_state()
        state.redis_available = True

        result = check_redis_available("test_operation")

        assert result is True

    @patch("ha_config.is_ha_strict", return_value=False)
    def test_returns_false_when_unavailable_permissive(self, mock_strict):
        """Test returns False when Redis unavailable in permissive mode."""
        state = get_dependency_state()
        state.redis_available = False

        result = check_redis_available("test_operation")

        assert result is False

    @patch("ha_config.is_ha_strict", return_value=True)
    def test_raises_when_unavailable_strict(self, mock_strict):
        """Test raises HAUnavailableError when Redis unavailable in strict mode."""
        state = get_dependency_state()
        state.redis_available = False

        with pytest.raises(HAUnavailableError) as exc_info:
            check_redis_available("test_operation")

        assert exc_info.value.dependency == "redis"
        assert "strict" in str(exc_info.value).lower()


class TestCheckS3Available:
    """Tests for check_s3_available function."""

    def setup_method(self):
        """Reset dependency state before each test."""
        state = get_dependency_state()
        state.redis_available = True
        state.s3_available = True
        state.database_available = True

    def test_returns_true_when_available(self):
        """Test returns True when S3 is available."""
        state = get_dependency_state()
        state.s3_available = True

        result = check_s3_available("test_operation")

        assert result is True

    @patch("ha_config.is_ha_strict", return_value=False)
    def test_returns_false_when_unavailable_permissive(self, mock_strict):
        """Test returns False when S3 unavailable in permissive mode."""
        state = get_dependency_state()
        state.s3_available = False

        result = check_s3_available("test_operation")

        assert result is False

    @patch("ha_config.is_ha_strict", return_value=True)
    def test_raises_when_unavailable_strict(self, mock_strict):
        """Test raises HAUnavailableError when S3 unavailable in strict mode."""
        state = get_dependency_state()
        state.s3_available = False

        with pytest.raises(HAUnavailableError) as exc_info:
            check_s3_available("test_operation")

        assert exc_info.value.dependency == "s3"


class TestCheckDatabaseAvailable:
    """Tests for check_database_available function."""

    def setup_method(self):
        """Reset dependency state before each test."""
        state = get_dependency_state()
        state.redis_available = True
        state.s3_available = True
        state.database_available = True

    def test_returns_true_when_available(self):
        """Test returns True when database is available."""
        state = get_dependency_state()
        state.database_available = True

        result = check_database_available("test_operation")

        assert result is True

    @patch("ha_config.is_ha_strict", return_value=False)
    def test_returns_false_when_unavailable_permissive(self, mock_strict):
        """Test returns False when database unavailable in permissive mode."""
        state = get_dependency_state()
        state.database_available = False

        result = check_database_available("test_operation")

        assert result is False

    @patch("ha_config.is_ha_strict", return_value=True)
    def test_raises_when_unavailable_strict(self, mock_strict):
        """Test raises HAUnavailableError when database unavailable in strict mode."""
        state = get_dependency_state()
        state.database_available = False

        with pytest.raises(HAUnavailableError) as exc_info:
            check_database_available("test_operation")

        assert exc_info.value.dependency == "database"


class TestHealthUpdates:
    """Tests for health update functions."""

    def setup_method(self):
        """Reset dependency state before each test."""
        state = get_dependency_state()
        state.redis_available = True
        state.s3_available = True
        state.database_available = True

    def test_update_redis_health_false(self):
        """Test updating Redis health to unavailable."""
        update_redis_health(False)
        assert get_dependency_state().redis_available is False

    def test_update_redis_health_true(self):
        """Test updating Redis health to available."""
        update_redis_health(False)
        update_redis_health(True)
        assert get_dependency_state().redis_available is True

    def test_update_s3_health(self):
        """Test updating S3 health."""
        update_s3_health(False)
        assert get_dependency_state().s3_available is False

    def test_update_database_health(self):
        """Test updating database health."""
        update_database_health(False)
        assert get_dependency_state().database_available is False


class TestGetHAStatus:
    """Tests for get_ha_status function."""

    def setup_method(self):
        """Reset dependency state before each test."""
        state = get_dependency_state()
        state.redis_available = True
        state.s3_available = True
        state.database_available = True

    @patch("ha_config.HA_MODE", HAMode.PERMISSIVE)
    def test_status_healthy_permissive(self):
        """Test status when all dependencies healthy in permissive mode."""
        status = get_ha_status()

        assert status["ha_mode"] == "permissive"
        assert status["status"] == "healthy"
        assert status["fail_closed"] is False
        assert status["dependencies"]["all_available"] is True

    @patch("ha_config.HA_MODE", HAMode.STRICT)
    def test_status_healthy_strict(self):
        """Test status when all dependencies healthy in strict mode."""
        status = get_ha_status()

        assert status["ha_mode"] == "strict"
        assert status["status"] == "healthy"
        assert status["fail_closed"] is True

    @patch("ha_config.HA_MODE", HAMode.STRICT)
    def test_status_degraded_when_redis_down(self):
        """Test status is degraded when Redis is unavailable."""
        update_redis_health(False)

        status = get_ha_status()

        assert status["status"] == "degraded"
        assert status["dependencies"]["redis"] is False
        assert status["dependencies"]["all_available"] is False


class TestMetricsExist:
    """Tests that Prometheus metrics are properly defined."""

    def test_dependency_checks_counter_exists(self):
        """Verify HA_DEPENDENCY_CHECKS_TOTAL counter exists."""
        assert HA_DEPENDENCY_CHECKS_TOTAL is not None
        labels = HA_DEPENDENCY_CHECKS_TOTAL._labelnames
        assert "dependency" in labels
        assert "result" in labels

    def test_fallback_counter_exists(self):
        """Verify HA_FALLBACK_USED_TOTAL counter exists."""
        assert HA_FALLBACK_USED_TOTAL is not None
        labels = HA_FALLBACK_USED_TOTAL._labelnames
        assert "dependency" in labels

    def test_rejected_counter_exists(self):
        """Verify HA_REQUEST_REJECTED_TOTAL counter exists."""
        assert HA_REQUEST_REJECTED_TOTAL is not None
        labels = HA_REQUEST_REJECTED_TOTAL._labelnames
        assert "dependency" in labels


class TestMetricsIncrement:
    """Tests that metrics are incremented correctly."""

    def setup_method(self):
        """Reset dependency state before each test."""
        state = get_dependency_state()
        state.redis_available = True
        state.s3_available = True
        state.database_available = True

    def test_success_increments_dependency_checks(self):
        """Test successful check increments dependency_checks counter."""
        before = HA_DEPENDENCY_CHECKS_TOTAL.labels(
            dependency="redis", result="success"
        )._value.get()

        check_redis_available("test")

        after = HA_DEPENDENCY_CHECKS_TOTAL.labels(
            dependency="redis", result="success"
        )._value.get()

        assert after == before + 1

    @patch("ha_config.is_ha_strict", return_value=False)
    def test_fallback_increments_counters(self, mock_strict):
        """Test fallback increments appropriate counters."""
        state = get_dependency_state()
        state.redis_available = False

        before_checks = HA_DEPENDENCY_CHECKS_TOTAL.labels(
            dependency="redis", result="fallback"
        )._value.get()
        before_fallback = HA_FALLBACK_USED_TOTAL.labels(
            dependency="redis"
        )._value.get()

        check_redis_available("test")

        after_checks = HA_DEPENDENCY_CHECKS_TOTAL.labels(
            dependency="redis", result="fallback"
        )._value.get()
        after_fallback = HA_FALLBACK_USED_TOTAL.labels(
            dependency="redis"
        )._value.get()

        assert after_checks == before_checks + 1
        assert after_fallback == before_fallback + 1

    @patch("ha_config.is_ha_strict", return_value=True)
    def test_rejection_increments_counters(self, mock_strict):
        """Test rejection increments appropriate counters."""
        state = get_dependency_state()
        state.s3_available = False

        before_checks = HA_DEPENDENCY_CHECKS_TOTAL.labels(
            dependency="s3", result="unavailable"
        )._value.get()
        before_rejected = HA_REQUEST_REJECTED_TOTAL.labels(
            dependency="s3"
        )._value.get()

        with pytest.raises(HAUnavailableError):
            check_s3_available("test")

        after_checks = HA_DEPENDENCY_CHECKS_TOTAL.labels(
            dependency="s3", result="unavailable"
        )._value.get()
        after_rejected = HA_REQUEST_REJECTED_TOTAL.labels(
            dependency="s3"
        )._value.get()

        assert after_checks == before_checks + 1
        assert after_rejected == before_rejected + 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""
Unit tests for limits configuration (v2.5.0 PR1).

Tests verify:
- Default limits are set correctly
- get_limits_info returns all expected keys
- ErrorCode constants are defined
"""

import pytest
import sys
import os

# Add services/bess-dispatch to path
sys.path.insert(0, "services/bess-dispatch")


class TestLimitsDefaults:
    """Tests for default limit values."""

    def test_max_request_bytes_default(self):
        """MAX_REQUEST_BYTES should have reasonable default."""
        from limits_config import MAX_REQUEST_BYTES
        assert MAX_REQUEST_BYTES == 2_500_000  # 2.5 MB

    def test_max_steps_default(self):
        """MAX_STEPS should have reasonable default."""
        from limits_config import MAX_STEPS
        assert MAX_STEPS == 35040  # Full year at 15-min

    def test_max_variants_default(self):
        """MAX_VARIANTS should have reasonable default."""
        from limits_config import MAX_VARIANTS
        assert MAX_VARIANTS == 50

    def test_max_durations_default(self):
        """MAX_DURATIONS should have reasonable default."""
        from limits_config import MAX_DURATIONS
        assert MAX_DURATIONS == 10

    def test_max_trace_steps_default(self):
        """MAX_TRACE_STEPS should have reasonable default."""
        from limits_config import MAX_TRACE_STEPS
        assert MAX_TRACE_STEPS == 10000

    def test_default_preview_rows_default(self):
        """DEFAULT_PREVIEW_ROWS should have reasonable default."""
        from limits_config import DEFAULT_PREVIEW_ROWS
        assert DEFAULT_PREVIEW_ROWS == 48


class TestErrorCodes:
    """Tests for error code constants."""

    def test_request_too_large_defined(self):
        """REQUEST_TOO_LARGE error code should be defined."""
        from limits_config import ErrorCode
        assert hasattr(ErrorCode, "REQUEST_TOO_LARGE")
        assert ErrorCode.REQUEST_TOO_LARGE == "REQUEST_TOO_LARGE"

    def test_steps_limit_exceeded_defined(self):
        """STEPS_LIMIT_EXCEEDED error code should be defined."""
        from limits_config import ErrorCode
        assert hasattr(ErrorCode, "STEPS_LIMIT_EXCEEDED")
        assert ErrorCode.STEPS_LIMIT_EXCEEDED == "STEPS_LIMIT_EXCEEDED"

    def test_variants_limit_exceeded_defined(self):
        """VARIANTS_LIMIT_EXCEEDED error code should be defined."""
        from limits_config import ErrorCode
        assert hasattr(ErrorCode, "VARIANTS_LIMIT_EXCEEDED")
        assert ErrorCode.VARIANTS_LIMIT_EXCEEDED == "VARIANTS_LIMIT_EXCEEDED"

    def test_durations_limit_exceeded_defined(self):
        """DURATIONS_LIMIT_EXCEEDED error code should be defined."""
        from limits_config import ErrorCode
        assert hasattr(ErrorCode, "DURATIONS_LIMIT_EXCEEDED")
        assert ErrorCode.DURATIONS_LIMIT_EXCEEDED == "DURATIONS_LIMIT_EXCEEDED"

    def test_timeseries_too_large_defined(self):
        """TIMESERIES_TOO_LARGE error code should be defined."""
        from limits_config import ErrorCode
        assert hasattr(ErrorCode, "TIMESERIES_TOO_LARGE")
        assert ErrorCode.TIMESERIES_TOO_LARGE == "TIMESERIES_TOO_LARGE"


class TestGetLimitsInfo:
    """Tests for get_limits_info helper function."""

    def test_returns_dict(self):
        """get_limits_info should return a dict."""
        from limits_config import get_limits_info
        result = get_limits_info()
        assert isinstance(result, dict)

    def test_contains_all_keys(self):
        """get_limits_info should contain all expected keys."""
        from limits_config import get_limits_info
        result = get_limits_info()

        expected_keys = [
            "max_request_bytes",
            "max_steps",
            "max_variants",
            "max_durations",
            "max_trace_steps",
            "default_preview_rows",
        ]

        for key in expected_keys:
            assert key in result, f"Missing key: {key}"

    def test_values_are_integers(self):
        """All limit values should be integers."""
        from limits_config import get_limits_info
        result = get_limits_info()

        for key, value in result.items():
            assert isinstance(value, int), f"{key} should be int, got {type(value)}"

    def test_values_are_positive(self):
        """All limit values should be positive."""
        from limits_config import get_limits_info
        result = get_limits_info()

        for key, value in result.items():
            assert value > 0, f"{key} should be positive, got {value}"

    def test_matches_module_constants(self):
        """get_limits_info values should match module constants."""
        from limits_config import (
            get_limits_info,
            MAX_REQUEST_BYTES,
            MAX_STEPS,
            MAX_VARIANTS,
            MAX_DURATIONS,
            MAX_TRACE_STEPS,
            DEFAULT_PREVIEW_ROWS,
        )

        result = get_limits_info()

        assert result["max_request_bytes"] == MAX_REQUEST_BYTES
        assert result["max_steps"] == MAX_STEPS
        assert result["max_variants"] == MAX_VARIANTS
        assert result["max_durations"] == MAX_DURATIONS
        assert result["max_trace_steps"] == MAX_TRACE_STEPS
        assert result["default_preview_rows"] == DEFAULT_PREVIEW_ROWS

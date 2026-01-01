"""
Unit tests for timeseries throttle helper (v2.5.0 PR2).

Tests verify:
- Mode resolution with backward compatibility
- Preview rows validation and clamping
- Full timeseries limit checking
- Array and dict truncation
- Timeseries info generation
"""

import pytest
import sys

sys.path.insert(0, "services/bess-dispatch")

from limits_config import TimeseriesMode, MAX_TRACE_STEPS, DEFAULT_PREVIEW_ROWS, MIN_PREVIEW_ROWS, MAX_PREVIEW_ROWS
from timeseries_throttle import (
    resolve_timeseries_mode,
    validate_preview_rows,
    check_full_timeseries_limit,
    truncate_timeseries_array,
    truncate_timeseries_dict,
    get_timeseries_info,
)


class TestResolveTimeseriesMode:
    """Tests for resolve_timeseries_mode function."""

    def test_default_is_none(self):
        """Default (no flag, no mode) should return NONE."""
        result = resolve_timeseries_mode()
        assert result == TimeseriesMode.NONE

    def test_include_flag_true_returns_full(self):
        """include_flag=True with no mode returns FULL (backward compat)."""
        result = resolve_timeseries_mode(include_flag=True)
        assert result == TimeseriesMode.FULL

    def test_include_flag_false_returns_none(self):
        """include_flag=False with no mode returns NONE."""
        result = resolve_timeseries_mode(include_flag=False)
        assert result == TimeseriesMode.NONE

    def test_mode_param_none_returns_none(self):
        """Explicit mode='none' returns NONE."""
        result = resolve_timeseries_mode(mode_param="none")
        assert result == TimeseriesMode.NONE

    def test_mode_param_preview_returns_preview(self):
        """Explicit mode='preview' returns PREVIEW."""
        result = resolve_timeseries_mode(mode_param="preview")
        assert result == TimeseriesMode.PREVIEW

    def test_mode_param_full_returns_full(self):
        """Explicit mode='full' returns FULL."""
        result = resolve_timeseries_mode(mode_param="full")
        assert result == TimeseriesMode.FULL

    def test_mode_param_uppercase_works(self):
        """Mode parameter should be case-insensitive."""
        result = resolve_timeseries_mode(mode_param="PREVIEW")
        assert result == TimeseriesMode.PREVIEW

    def test_mode_param_mixed_case_works(self):
        """Mode parameter should be case-insensitive."""
        result = resolve_timeseries_mode(mode_param="Full")
        assert result == TimeseriesMode.FULL

    def test_mode_param_overrides_include_flag(self):
        """mode_param takes precedence over include_flag."""
        result = resolve_timeseries_mode(include_flag=True, mode_param="none")
        assert result == TimeseriesMode.NONE

    def test_mode_param_overrides_include_flag_preview(self):
        """mode_param='preview' overrides include_flag=True."""
        result = resolve_timeseries_mode(include_flag=True, mode_param="preview")
        assert result == TimeseriesMode.PREVIEW

    def test_invalid_mode_falls_back_to_include_flag(self):
        """Invalid mode_param falls back to include_flag behavior."""
        result = resolve_timeseries_mode(include_flag=True, mode_param="invalid")
        assert result == TimeseriesMode.FULL

    def test_invalid_mode_with_false_flag_returns_none(self):
        """Invalid mode_param with include_flag=False returns NONE."""
        result = resolve_timeseries_mode(include_flag=False, mode_param="invalid")
        assert result == TimeseriesMode.NONE


class TestValidatePreviewRows:
    """Tests for validate_preview_rows function."""

    def test_none_returns_default(self):
        """None input returns DEFAULT_PREVIEW_ROWS."""
        result = validate_preview_rows(None)
        assert result == DEFAULT_PREVIEW_ROWS

    def test_valid_value_returned_as_is(self):
        """Valid value within range is returned as-is."""
        result = validate_preview_rows(100)
        assert result == 100

    def test_below_minimum_clamped(self):
        """Value below MIN_PREVIEW_ROWS is clamped to minimum."""
        result = validate_preview_rows(5)
        assert result == MIN_PREVIEW_ROWS

    def test_above_maximum_clamped(self):
        """Value above MAX_PREVIEW_ROWS is clamped to maximum."""
        result = validate_preview_rows(500)
        assert result == MAX_PREVIEW_ROWS

    def test_exact_minimum_allowed(self):
        """Exact MIN_PREVIEW_ROWS is allowed."""
        result = validate_preview_rows(MIN_PREVIEW_ROWS)
        assert result == MIN_PREVIEW_ROWS

    def test_exact_maximum_allowed(self):
        """Exact MAX_PREVIEW_ROWS is allowed."""
        result = validate_preview_rows(MAX_PREVIEW_ROWS)
        assert result == MAX_PREVIEW_ROWS

    def test_zero_clamped_to_minimum(self):
        """Zero is clamped to minimum."""
        result = validate_preview_rows(0)
        assert result == MIN_PREVIEW_ROWS

    def test_negative_clamped_to_minimum(self):
        """Negative value is clamped to minimum."""
        result = validate_preview_rows(-10)
        assert result == MIN_PREVIEW_ROWS


class TestCheckFullTimeseriesLimit:
    """Tests for check_full_timeseries_limit function."""

    def test_within_limit_returns_ok(self):
        """Steps within limit returns (True, None)."""
        is_ok, error = check_full_timeseries_limit(1000)
        assert is_ok is True
        assert error is None

    def test_at_limit_returns_ok(self):
        """Exact MAX_TRACE_STEPS returns (True, None)."""
        is_ok, error = check_full_timeseries_limit(MAX_TRACE_STEPS)
        assert is_ok is True
        assert error is None

    def test_over_limit_returns_error(self):
        """Steps over limit returns (False, error_dict)."""
        n_steps = MAX_TRACE_STEPS + 1
        is_ok, error = check_full_timeseries_limit(n_steps)
        assert is_ok is False
        assert error is not None

    def test_error_contains_error_code(self):
        """Error dict contains error_code field."""
        n_steps = MAX_TRACE_STEPS + 1
        _, error = check_full_timeseries_limit(n_steps)
        assert "error_code" in error
        assert error["error_code"] == "TIMESERIES_TOO_LARGE"

    def test_error_contains_max_trace_steps(self):
        """Error dict contains max_trace_steps field."""
        n_steps = MAX_TRACE_STEPS + 100
        _, error = check_full_timeseries_limit(n_steps)
        assert "max_trace_steps" in error
        assert error["max_trace_steps"] == MAX_TRACE_STEPS

    def test_error_contains_steps(self):
        """Error dict contains steps field with actual value."""
        n_steps = MAX_TRACE_STEPS + 500
        _, error = check_full_timeseries_limit(n_steps)
        assert "steps" in error
        assert error["steps"] == n_steps

    def test_error_contains_detail(self):
        """Error dict contains detail field."""
        n_steps = MAX_TRACE_STEPS + 1
        _, error = check_full_timeseries_limit(n_steps)
        assert "detail" in error
        assert "preview" in error["detail"].lower()

    def test_zero_steps_returns_ok(self):
        """Zero steps returns ok."""
        is_ok, error = check_full_timeseries_limit(0)
        assert is_ok is True
        assert error is None


class TestTruncateTimeseriesArray:
    """Tests for truncate_timeseries_array function."""

    def test_none_mode_returns_empty(self):
        """Mode NONE returns empty array."""
        data = [1, 2, 3, 4, 5]
        result = truncate_timeseries_array(data, TimeseriesMode.NONE)
        assert result == []

    def test_preview_mode_truncates(self):
        """Mode PREVIEW truncates to preview_rows."""
        data = list(range(100))
        result = truncate_timeseries_array(data, TimeseriesMode.PREVIEW, preview_rows=10)
        assert len(result) == 10
        assert result == list(range(10))

    def test_full_mode_returns_all(self):
        """Mode FULL returns all data."""
        data = list(range(100))
        result = truncate_timeseries_array(data, TimeseriesMode.FULL)
        assert result == data

    def test_preview_with_short_array(self):
        """Preview mode with array shorter than preview_rows returns all."""
        data = [1, 2, 3]
        result = truncate_timeseries_array(data, TimeseriesMode.PREVIEW, preview_rows=10)
        assert result == [1, 2, 3]

    def test_preview_with_default_rows(self):
        """Preview mode uses DEFAULT_PREVIEW_ROWS when not specified."""
        data = list(range(1000))
        result = truncate_timeseries_array(data, TimeseriesMode.PREVIEW)
        assert len(result) == DEFAULT_PREVIEW_ROWS

    def test_empty_array_none_mode(self):
        """Empty array with NONE mode returns empty."""
        result = truncate_timeseries_array([], TimeseriesMode.NONE)
        assert result == []

    def test_empty_array_full_mode(self):
        """Empty array with FULL mode returns empty."""
        result = truncate_timeseries_array([], TimeseriesMode.FULL)
        assert result == []


class TestTruncateTimeseriesDict:
    """Tests for truncate_timeseries_dict function."""

    def test_none_mode_returns_empty_arrays(self):
        """Mode NONE returns dict with empty arrays."""
        data = {"a": [1, 2, 3], "b": [4, 5, 6]}
        result = truncate_timeseries_dict(data, TimeseriesMode.NONE)
        assert result == {"a": [], "b": []}

    def test_preview_mode_truncates_all_arrays(self):
        """Mode PREVIEW truncates all arrays in dict."""
        data = {"a": list(range(100)), "b": list(range(100, 200))}
        result = truncate_timeseries_dict(data, TimeseriesMode.PREVIEW, preview_rows=10)
        assert len(result["a"]) == 10
        assert len(result["b"]) == 10
        assert result["a"] == list(range(10))
        assert result["b"] == list(range(100, 110))

    def test_full_mode_returns_all(self):
        """Mode FULL returns all data."""
        data = {"a": [1, 2, 3], "b": [4, 5, 6]}
        result = truncate_timeseries_dict(data, TimeseriesMode.FULL)
        assert result == data

    def test_empty_dict(self):
        """Empty dict returns empty dict."""
        result = truncate_timeseries_dict({}, TimeseriesMode.PREVIEW)
        assert result == {}

    def test_mixed_length_arrays(self):
        """Arrays of different lengths are handled independently."""
        data = {"short": [1, 2], "long": list(range(100))}
        result = truncate_timeseries_dict(data, TimeseriesMode.PREVIEW, preview_rows=10)
        assert result["short"] == [1, 2]
        assert len(result["long"]) == 10


class TestGetTimeseriesInfo:
    """Tests for get_timeseries_info function."""

    def test_none_mode_returns_zero_included(self):
        """Mode NONE returns 0 included_steps."""
        result = get_timeseries_info(TimeseriesMode.NONE, total_steps=100)
        assert result["mode"] == "none"
        assert result["included_steps"] == 0
        assert result["total_steps"] == 100
        assert result["truncated"] is True

    def test_preview_mode_returns_preview_rows(self):
        """Mode PREVIEW returns preview_rows as included_steps."""
        result = get_timeseries_info(TimeseriesMode.PREVIEW, total_steps=100, preview_rows=20)
        assert result["mode"] == "preview"
        assert result["included_steps"] == 20
        assert result["total_steps"] == 100
        assert result["truncated"] is True

    def test_full_mode_returns_total_steps(self):
        """Mode FULL returns total_steps as included_steps."""
        result = get_timeseries_info(TimeseriesMode.FULL, total_steps=100)
        assert result["mode"] == "full"
        assert result["included_steps"] == 100
        assert result["total_steps"] == 100
        assert result["truncated"] is False

    def test_preview_mode_short_data(self):
        """Preview mode with data shorter than preview_rows."""
        result = get_timeseries_info(TimeseriesMode.PREVIEW, total_steps=5, preview_rows=20)
        assert result["included_steps"] == 5
        assert result["truncated"] is False

    def test_none_mode_zero_total(self):
        """NONE mode with zero total_steps."""
        result = get_timeseries_info(TimeseriesMode.NONE, total_steps=0)
        assert result["included_steps"] == 0
        assert result["truncated"] is False

    def test_uses_default_preview_rows(self):
        """Uses DEFAULT_PREVIEW_ROWS when not specified."""
        result = get_timeseries_info(TimeseriesMode.PREVIEW, total_steps=1000)
        assert result["included_steps"] == DEFAULT_PREVIEW_ROWS

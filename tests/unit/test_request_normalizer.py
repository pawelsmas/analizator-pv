"""
Unit tests for request_normalizer module (v2.7.0 PR3).

Tests verify:
- Deprecated field normalization
- New field not overwritten
- Deprecation tracking
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))


class TestNormalizeRequest:
    """Tests for normalize_request function."""

    def test_normalizes_include_battery_trace_true(self):
        """include_battery_trace=true should become battery_trace_mode=full."""
        from request_normalizer import normalize_request
        from deprecations_usage import clear_request_deprecations

        clear_request_deprecations()

        request = {"include_battery_trace": True}
        result, deprecated = normalize_request(request)

        assert result["battery_trace_mode"] == "full"
        assert "include_battery_trace" in deprecated

    def test_normalizes_include_battery_trace_false(self):
        """include_battery_trace=false should become battery_trace_mode=none."""
        from request_normalizer import normalize_request
        from deprecations_usage import clear_request_deprecations

        clear_request_deprecations()

        request = {"include_battery_trace": False}
        result, deprecated = normalize_request(request)

        assert result["battery_trace_mode"] == "none"
        # False usage is not tracked as deprecated usage
        assert "include_battery_trace" not in deprecated

    def test_normalizes_include_price_timeseries(self):
        """include_price_timeseries should be normalized."""
        from request_normalizer import normalize_request
        from deprecations_usage import clear_request_deprecations

        clear_request_deprecations()

        request = {"include_price_timeseries": True}
        result, deprecated = normalize_request(request)

        assert result["price_timeseries_mode"] == "full"
        assert "include_price_timeseries" in deprecated

    def test_normalizes_include_ledger_timeseries(self):
        """include_ledger_timeseries should be normalized."""
        from request_normalizer import normalize_request
        from deprecations_usage import clear_request_deprecations

        clear_request_deprecations()

        request = {"include_ledger_timeseries": True}
        result, deprecated = normalize_request(request)

        assert result["ledger_timeseries_mode"] == "full"
        assert "include_ledger_timeseries" in deprecated

    def test_does_not_overwrite_existing_new_field(self):
        """If new field already set, don't overwrite."""
        from request_normalizer import normalize_request
        from deprecations_usage import clear_request_deprecations

        clear_request_deprecations()

        request = {
            "include_battery_trace": True,
            "battery_trace_mode": "preview",  # Already set
        }
        result, deprecated = normalize_request(request)

        assert result["battery_trace_mode"] == "preview"  # Not overwritten

    def test_preserves_other_fields(self):
        """Other request fields should be preserved."""
        from request_normalizer import normalize_request
        from deprecations_usage import clear_request_deprecations

        clear_request_deprecations()

        request = {
            "load_kw": [100, 200],
            "pv_generation_kw": [50, 100],
            "include_battery_trace": True,
        }
        result, deprecated = normalize_request(request)

        assert result["load_kw"] == [100, 200]
        assert result["pv_generation_kw"] == [50, 100]

    def test_multiple_deprecated_fields(self):
        """Multiple deprecated fields should all be normalized."""
        from request_normalizer import normalize_request
        from deprecations_usage import clear_request_deprecations

        clear_request_deprecations()

        request = {
            "include_battery_trace": True,
            "include_price_timeseries": True,
            "include_ledger_timeseries": True,
        }
        result, deprecated = normalize_request(request)

        assert result["battery_trace_mode"] == "full"
        assert result["price_timeseries_mode"] == "full"
        assert result["ledger_timeseries_mode"] == "full"
        assert len(deprecated) == 3


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_get_deprecated_request_fields(self):
        """get_deprecated_request_fields should return list."""
        from request_normalizer import get_deprecated_request_fields

        fields = get_deprecated_request_fields()
        assert isinstance(fields, list)
        assert "include_battery_trace" in fields
        assert "include_price_timeseries" in fields
        assert "include_ledger_timeseries" in fields

    def test_is_request_field_deprecated(self):
        """is_request_field_deprecated should check correctly."""
        from request_normalizer import is_request_field_deprecated

        assert is_request_field_deprecated("include_battery_trace") is True
        assert is_request_field_deprecated("load_kw") is False

    def test_get_field_replacement(self):
        """get_field_replacement should return new field name."""
        from request_normalizer import get_field_replacement

        assert get_field_replacement("include_battery_trace") == "battery_trace_mode"
        assert get_field_replacement("include_price_timeseries") == "price_timeseries_mode"
        assert get_field_replacement("unknown_field") is None

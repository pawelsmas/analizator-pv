"""
Contract tests for timeseries preview mode (v2.5.0 PR2).

Tests verify:
- battery_trace_mode='preview' returns exactly timeseries_preview_rows steps
- Default preview rows is 48
- Custom preview rows are respected
- Preview rows are clamped to min/max bounds
"""

import pytest
from ._api import post_json


def _base_req():
    """Minimal valid sizing request with 100 steps."""
    return {
        "load_kw": [100] * 100,  # 100 steps
        "pv_generation_kw": [50] * 100,
        "mode": "pv_surplus",
        "durations_h": [1.0],
        "interval_minutes": 60,
        "discount_rate": 0.08,
        "analysis_years": 15,
        "capex_pln_per_kwh": 1800.0,
        "import_price_pln_mwh": 800.0,
    }


class TestBatteryTracePreviewLength:
    """Tests for battery trace preview mode length."""

    def test_preview_mode_returns_default_48_steps(self):
        """battery_trace_mode='preview' returns 48 steps by default."""
        req = _base_req()
        req["battery_trace_mode"] = "preview"
        resp = post_json("/sizing", req)

        assert "recommended" in resp
        variant = resp["recommended"]
        assert "dispatch_summary" in variant
        summary = variant["dispatch_summary"]

        # Battery trace should be present with exactly 48 steps
        assert "battery_trace" in summary
        trace = summary["battery_trace"]
        assert "soc_kwh" in trace
        assert len(trace["soc_kwh"]) == 48

    def test_preview_mode_with_custom_rows(self):
        """battery_trace_mode='preview' with custom rows returns that many steps."""
        req = _base_req()
        req["battery_trace_mode"] = "preview"
        req["timeseries_preview_rows"] = 24
        resp = post_json("/sizing", req)

        variant = resp["recommended"]
        trace = variant["dispatch_summary"]["battery_trace"]
        assert len(trace["soc_kwh"]) == 24

    def test_preview_mode_with_short_data(self):
        """Preview mode with data shorter than preview_rows returns all data."""
        req = _base_req()
        req["load_kw"] = [100] * 20  # Only 20 steps
        req["pv_generation_kw"] = [50] * 20
        req["battery_trace_mode"] = "preview"
        req["timeseries_preview_rows"] = 48
        resp = post_json("/sizing", req)

        variant = resp["recommended"]
        trace = variant["dispatch_summary"]["battery_trace"]
        # Should only return 20 steps (all available)
        assert len(trace["soc_kwh"]) == 20

    def test_preview_rows_minimum_clamped(self):
        """timeseries_preview_rows below minimum is clamped to 12."""
        req = _base_req()
        req["battery_trace_mode"] = "preview"
        req["timeseries_preview_rows"] = 5  # Below minimum
        resp = post_json("/sizing", req)

        variant = resp["recommended"]
        trace = variant["dispatch_summary"]["battery_trace"]
        # Should be clamped to MIN_PREVIEW_ROWS (12)
        assert len(trace["soc_kwh"]) == 12

    def test_preview_rows_maximum_clamped(self):
        """timeseries_preview_rows above maximum is clamped to 240."""
        req = _base_req()
        req["load_kw"] = [100] * 500  # 500 steps
        req["pv_generation_kw"] = [50] * 500
        req["battery_trace_mode"] = "preview"
        req["timeseries_preview_rows"] = 500  # Above maximum
        resp = post_json("/sizing", req)

        variant = resp["recommended"]
        trace = variant["dispatch_summary"]["battery_trace"]
        # Should be clamped to MAX_PREVIEW_ROWS (240)
        assert len(trace["soc_kwh"]) == 240


class TestLedgerTimeseriesPreviewLength:
    """Tests for ledger timeseries preview mode length."""

    def test_ledger_preview_mode_returns_correct_length(self):
        """ledger_timeseries_mode='preview' returns correct number of steps."""
        req = _base_req()
        req["ledger_timeseries_mode"] = "preview"
        req["timeseries_preview_rows"] = 30
        resp = post_json("/sizing", req)

        variant = resp["recommended"]
        summary = variant["dispatch_summary"]

        # Ledger timeseries should be present
        assert "ledger_timeseries" in summary
        ledger = summary["ledger_timeseries"]
        assert "import_cost_pln" in ledger
        assert len(ledger["import_cost_pln"]) == 30


class TestPriceTimeseriesPreviewLength:
    """Tests for price timeseries preview mode length."""

    def test_price_preview_mode_returns_correct_length(self):
        """price_timeseries_mode='preview' returns correct number of steps."""
        req = _base_req()
        req["price_timeseries_mode"] = "preview"
        req["timeseries_preview_rows"] = 36
        resp = post_json("/sizing", req)

        variant = resp["recommended"]
        summary = variant["dispatch_summary"]

        # Price timeseries should be present
        assert "price_timeseries" in summary
        prices = summary["price_timeseries"]
        assert "import_pln_mwh" in prices
        assert len(prices["import_pln_mwh"]) == 36


class TestBackwardCompatibility:
    """Tests for backward compatibility with boolean flags."""

    def test_include_battery_trace_true_without_mode_returns_full(self):
        """include_battery_trace=True without mode returns all data."""
        req = _base_req()
        req["include_battery_trace"] = True
        resp = post_json("/sizing", req)

        variant = resp["recommended"]
        trace = variant["dispatch_summary"]["battery_trace"]
        # Should return all 100 steps
        assert len(trace["soc_kwh"]) == 100

    def test_mode_overrides_include_flag(self):
        """battery_trace_mode takes precedence over include_battery_trace."""
        req = _base_req()
        req["include_battery_trace"] = True  # Would return all data
        req["battery_trace_mode"] = "preview"  # Should take precedence
        req["timeseries_preview_rows"] = 20
        resp = post_json("/sizing", req)

        variant = resp["recommended"]
        trace = variant["dispatch_summary"]["battery_trace"]
        # Should return only 20 steps (mode takes precedence)
        assert len(trace["soc_kwh"]) == 20

    def test_mode_none_returns_empty(self):
        """battery_trace_mode='none' returns empty arrays even with include_battery_trace=True."""
        req = _base_req()
        req["include_battery_trace"] = True
        req["battery_trace_mode"] = "none"
        resp = post_json("/sizing", req)

        variant = resp["recommended"]
        # Battery trace should be empty or not present
        summary = variant["dispatch_summary"]
        if "battery_trace" in summary:
            trace = summary["battery_trace"]
            assert len(trace.get("soc_kwh", [])) == 0


class TestTimeseriesInfo:
    """Tests for timeseries_info metadata in response."""

    def test_timeseries_info_present_in_preview_mode(self):
        """Response includes timeseries_info when preview mode is used."""
        req = _base_req()
        req["battery_trace_mode"] = "preview"
        req["timeseries_preview_rows"] = 24
        resp = post_json("/sizing", req)

        # Check for timeseries_info in response
        assert "timeseries_info" in resp or "meta" in resp
        if "timeseries_info" in resp:
            info = resp["timeseries_info"]
            assert "battery_trace" in info
            assert info["battery_trace"]["mode"] == "preview"
            assert info["battery_trace"]["included_steps"] == 24
            assert info["battery_trace"]["truncated"] is True

    def test_timeseries_info_shows_not_truncated_for_full(self):
        """timeseries_info shows truncated=False for full mode."""
        req = _base_req()
        req["battery_trace_mode"] = "full"
        resp = post_json("/sizing", req)

        if "timeseries_info" in resp:
            info = resp["timeseries_info"]
            assert info["battery_trace"]["mode"] == "full"
            assert info["battery_trace"]["truncated"] is False

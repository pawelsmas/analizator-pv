"""
Contract tests for timeseries full mode limit rejection (v2.5.0 PR2).

Tests verify:
- battery_trace_mode='full' with steps > MAX_TRACE_STEPS returns 422
- Error response contains error_code=TIMESERIES_TOO_LARGE
- Error response contains max_trace_steps and steps fields
- Error detail suggests using preview mode
- Same behavior for ledger and price timeseries modes
"""

import pytest
import requests
from ._api import post_json, DEFAULT_BASE_URL


def _base_req_large():
    """Sizing request with steps exceeding MAX_TRACE_STEPS (10000)."""
    n_steps = 12000  # > MAX_TRACE_STEPS
    return {
        "load_kw": [100] * n_steps,
        "pv_generation_kw": [50] * n_steps,
        "mode": "pv_surplus",
        "durations_h": [1.0],
        "interval_minutes": 60,
        "discount_rate": 0.08,
        "analysis_years": 15,
        "capex_pln_per_kwh": 1800.0,
        "import_price_pln_mwh": 800.0,
    }


def _base_req_within_limit():
    """Sizing request with steps within MAX_TRACE_STEPS."""
    n_steps = 5000  # < MAX_TRACE_STEPS
    return {
        "load_kw": [100] * n_steps,
        "pv_generation_kw": [50] * n_steps,
        "mode": "pv_surplus",
        "durations_h": [1.0],
        "interval_minutes": 60,
        "discount_rate": 0.08,
        "analysis_years": 15,
        "capex_pln_per_kwh": 1800.0,
        "import_price_pln_mwh": 800.0,
    }


def post_raw(endpoint, json_body):
    """Post and return raw response for status code checking."""
    url = f"{DEFAULT_BASE_URL}{endpoint}"
    return requests.post(url, json=json_body)


class TestBatteryTraceModeFullRejection:
    """Tests for battery_trace_mode='full' rejection when over limit."""

    def test_full_mode_over_limit_returns_422(self):
        """battery_trace_mode='full' with > MAX_TRACE_STEPS returns 422."""
        req = _base_req_large()
        req["battery_trace_mode"] = "full"
        resp = post_raw("/api/bess-dispatch/sizing", req)

        assert resp.status_code == 422

    def test_error_contains_error_code(self):
        """Error response contains error_code=TIMESERIES_TOO_LARGE."""
        req = _base_req_large()
        req["battery_trace_mode"] = "full"
        resp = post_raw("/api/bess-dispatch/sizing", req)

        assert resp.status_code == 422
        body = resp.json()
        assert "error_code" in body
        assert body["error_code"] == "TIMESERIES_TOO_LARGE"

    def test_error_contains_max_trace_steps(self):
        """Error response contains max_trace_steps field."""
        req = _base_req_large()
        req["battery_trace_mode"] = "full"
        resp = post_raw("/api/bess-dispatch/sizing", req)

        body = resp.json()
        assert "max_trace_steps" in body
        assert body["max_trace_steps"] == 10000  # Default MAX_TRACE_STEPS

    def test_error_contains_steps(self):
        """Error response contains steps field with actual value."""
        req = _base_req_large()
        req["battery_trace_mode"] = "full"
        resp = post_raw("/api/bess-dispatch/sizing", req)

        body = resp.json()
        assert "steps" in body
        assert body["steps"] == 12000

    def test_error_detail_suggests_preview(self):
        """Error detail suggests using preview mode."""
        req = _base_req_large()
        req["battery_trace_mode"] = "full"
        resp = post_raw("/api/bess-dispatch/sizing", req)

        body = resp.json()
        assert "detail" in body
        assert "preview" in body["detail"].lower()

    def test_full_mode_within_limit_succeeds(self):
        """battery_trace_mode='full' within limit returns 200."""
        req = _base_req_within_limit()
        req["battery_trace_mode"] = "full"
        resp = post_raw("/api/bess-dispatch/sizing", req)

        assert resp.status_code == 200

    def test_preview_mode_over_limit_succeeds(self):
        """battery_trace_mode='preview' works even with large data."""
        req = _base_req_large()
        req["battery_trace_mode"] = "preview"
        resp = post_raw("/api/bess-dispatch/sizing", req)

        assert resp.status_code == 200
        body = resp.json()
        trace = body["recommended"]["dispatch_summary"]["battery_trace"]
        assert len(trace["soc_kwh"]) == 48  # Default preview rows


class TestLedgerTimeseriesModeFullRejection:
    """Tests for ledger_timeseries_mode='full' rejection when over limit."""

    def test_ledger_full_mode_over_limit_returns_422(self):
        """ledger_timeseries_mode='full' with > MAX_TRACE_STEPS returns 422."""
        req = _base_req_large()
        req["ledger_timeseries_mode"] = "full"
        resp = post_raw("/api/bess-dispatch/sizing", req)

        assert resp.status_code == 422

    def test_ledger_error_contains_error_code(self):
        """Ledger error response contains error_code=TIMESERIES_TOO_LARGE."""
        req = _base_req_large()
        req["ledger_timeseries_mode"] = "full"
        resp = post_raw("/api/bess-dispatch/sizing", req)

        body = resp.json()
        assert body["error_code"] == "TIMESERIES_TOO_LARGE"

    def test_ledger_preview_mode_succeeds(self):
        """ledger_timeseries_mode='preview' works with large data."""
        req = _base_req_large()
        req["ledger_timeseries_mode"] = "preview"
        resp = post_raw("/api/bess-dispatch/sizing", req)

        assert resp.status_code == 200


class TestPriceTimeseriesModeFullRejection:
    """Tests for price_timeseries_mode='full' rejection when over limit."""

    def test_price_full_mode_over_limit_returns_422(self):
        """price_timeseries_mode='full' with > MAX_TRACE_STEPS returns 422."""
        req = _base_req_large()
        req["price_timeseries_mode"] = "full"
        resp = post_raw("/api/bess-dispatch/sizing", req)

        assert resp.status_code == 422

    def test_price_error_contains_error_code(self):
        """Price error response contains error_code=TIMESERIES_TOO_LARGE."""
        req = _base_req_large()
        req["price_timeseries_mode"] = "full"
        resp = post_raw("/api/bess-dispatch/sizing", req)

        body = resp.json()
        assert body["error_code"] == "TIMESERIES_TOO_LARGE"

    def test_price_preview_mode_succeeds(self):
        """price_timeseries_mode='preview' works with large data."""
        req = _base_req_large()
        req["price_timeseries_mode"] = "preview"
        resp = post_raw("/api/bess-dispatch/sizing", req)

        assert resp.status_code == 200


class TestIncludeFlagBackwardCompatibility:
    """Tests for include_X=True backward compatibility with large data."""

    def test_include_battery_trace_true_over_limit_returns_422(self):
        """include_battery_trace=True with > MAX_TRACE_STEPS returns 422."""
        req = _base_req_large()
        req["include_battery_trace"] = True  # Maps to FULL mode
        resp = post_raw("/api/bess-dispatch/sizing", req)

        assert resp.status_code == 422
        body = resp.json()
        assert body["error_code"] == "TIMESERIES_TOO_LARGE"

    def test_include_ledger_timeseries_true_over_limit_returns_422(self):
        """include_ledger_timeseries=True with > MAX_TRACE_STEPS returns 422."""
        req = _base_req_large()
        req["include_ledger_timeseries"] = True
        resp = post_raw("/api/bess-dispatch/sizing", req)

        assert resp.status_code == 422
        body = resp.json()
        assert body["error_code"] == "TIMESERIES_TOO_LARGE"

    def test_include_price_timeseries_true_over_limit_returns_422(self):
        """include_price_timeseries=True with > MAX_TRACE_STEPS returns 422."""
        req = _base_req_large()
        req["include_price_timeseries"] = True
        resp = post_raw("/api/bess-dispatch/sizing", req)

        assert resp.status_code == 422
        body = resp.json()
        assert body["error_code"] == "TIMESERIES_TOO_LARGE"


class TestMultipleModesCombined:
    """Tests for multiple timeseries modes combined."""

    def test_one_full_mode_rejects_entire_request(self):
        """If any timeseries mode is full and over limit, request is rejected."""
        req = _base_req_large()
        req["battery_trace_mode"] = "preview"  # OK
        req["ledger_timeseries_mode"] = "full"  # Will trigger rejection
        resp = post_raw("/api/bess-dispatch/sizing", req)

        assert resp.status_code == 422

    def test_all_preview_modes_succeed(self):
        """All timeseries in preview mode succeeds with large data."""
        req = _base_req_large()
        req["battery_trace_mode"] = "preview"
        req["ledger_timeseries_mode"] = "preview"
        req["price_timeseries_mode"] = "preview"
        resp = post_raw("/api/bess-dispatch/sizing", req)

        assert resp.status_code == 200

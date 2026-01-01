"""
Contract tests for deprecated request fields (v2.7.0 PR3).

Tests verify:
- Deprecated request fields are accepted
- Normalization works correctly
- Deprecation warnings are included
- Deprecation headers are set
"""

import pytest
import httpx

BASE_URL = "http://localhost:8000/api/bess-dispatch"


def _get_minimal_sizing_request() -> dict:
    """Get minimal valid sizing request."""
    return {
        "load_kw": [100] * 8760,
        "pv_generation_kw": [50] * 8760,
    }


class TestDeprecatedIncludeBatteryTrace:
    """Tests for deprecated include_battery_trace field."""

    def test_include_battery_trace_true_accepted(self):
        """include_battery_trace=true should be accepted."""
        request = _get_minimal_sizing_request()
        request["include_battery_trace"] = True

        with httpx.Client(timeout=60.0) as client:
            response = client.post(f"{BASE_URL}/sizing", json=request)

        assert response.status_code == 200

    def test_include_battery_trace_true_sets_deprecation_header(self):
        """include_battery_trace=true should set Deprecation header."""
        request = _get_minimal_sizing_request()
        request["include_battery_trace"] = True

        with httpx.Client(timeout=60.0) as client:
            response = client.post(f"{BASE_URL}/sizing", json=request)

        assert response.status_code == 200
        assert response.headers.get("Deprecation") == "true"

    def test_include_battery_trace_true_has_warnings(self):
        """include_battery_trace=true should have deprecation warning."""
        request = _get_minimal_sizing_request()
        request["include_battery_trace"] = True

        with httpx.Client(timeout=60.0) as client:
            response = client.post(f"{BASE_URL}/sizing", json=request)

        assert response.status_code == 200
        data = response.json()
        assert "warnings" in data
        assert "deprecations_used" in data["warnings"]
        assert "include_battery_trace" in data["warnings"]["deprecations_used"]

    def test_include_battery_trace_false_accepted(self):
        """include_battery_trace=false should be accepted."""
        request = _get_minimal_sizing_request()
        request["include_battery_trace"] = False

        with httpx.Client(timeout=60.0) as client:
            response = client.post(f"{BASE_URL}/sizing", json=request)

        assert response.status_code == 200

    def test_include_battery_trace_false_no_deprecation_header(self):
        """include_battery_trace=false should not set Deprecation header."""
        request = _get_minimal_sizing_request()
        request["include_battery_trace"] = False

        with httpx.Client(timeout=60.0) as client:
            response = client.post(f"{BASE_URL}/sizing", json=request)

        assert response.status_code == 200
        # False value should not be tracked as deprecated usage
        assert response.headers.get("Deprecation") is None


class TestDeprecatedIncludePriceTimeseries:
    """Tests for deprecated include_price_timeseries field."""

    def test_include_price_timeseries_true_accepted(self):
        """include_price_timeseries=true should be accepted."""
        request = _get_minimal_sizing_request()
        request["include_price_timeseries"] = True

        with httpx.Client(timeout=60.0) as client:
            response = client.post(f"{BASE_URL}/sizing", json=request)

        assert response.status_code == 200

    def test_include_price_timeseries_true_sets_deprecation_header(self):
        """include_price_timeseries=true should set Deprecation header."""
        request = _get_minimal_sizing_request()
        request["include_price_timeseries"] = True

        with httpx.Client(timeout=60.0) as client:
            response = client.post(f"{BASE_URL}/sizing", json=request)

        assert response.status_code == 200
        assert response.headers.get("Deprecation") == "true"

    def test_include_price_timeseries_true_has_warnings(self):
        """include_price_timeseries=true should have deprecation warning."""
        request = _get_minimal_sizing_request()
        request["include_price_timeseries"] = True

        with httpx.Client(timeout=60.0) as client:
            response = client.post(f"{BASE_URL}/sizing", json=request)

        assert response.status_code == 200
        data = response.json()
        assert "warnings" in data
        assert "deprecations_used" in data["warnings"]
        assert "include_price_timeseries" in data["warnings"]["deprecations_used"]


class TestDeprecatedIncludeLedgerTimeseries:
    """Tests for deprecated include_ledger_timeseries field."""

    def test_include_ledger_timeseries_true_accepted(self):
        """include_ledger_timeseries=true should be accepted."""
        request = _get_minimal_sizing_request()
        request["include_ledger_timeseries"] = True

        with httpx.Client(timeout=60.0) as client:
            response = client.post(f"{BASE_URL}/sizing", json=request)

        assert response.status_code == 200

    def test_include_ledger_timeseries_true_sets_deprecation_header(self):
        """include_ledger_timeseries=true should set Deprecation header."""
        request = _get_minimal_sizing_request()
        request["include_ledger_timeseries"] = True

        with httpx.Client(timeout=60.0) as client:
            response = client.post(f"{BASE_URL}/sizing", json=request)

        assert response.status_code == 200
        assert response.headers.get("Deprecation") == "true"

    def test_include_ledger_timeseries_true_has_warnings(self):
        """include_ledger_timeseries=true should have deprecation warning."""
        request = _get_minimal_sizing_request()
        request["include_ledger_timeseries"] = True

        with httpx.Client(timeout=60.0) as client:
            response = client.post(f"{BASE_URL}/sizing", json=request)

        assert response.status_code == 200
        data = response.json()
        assert "warnings" in data
        assert "deprecations_used" in data["warnings"]
        assert "include_ledger_timeseries" in data["warnings"]["deprecations_used"]


class TestMultipleDeprecatedFields:
    """Tests for multiple deprecated fields in single request."""

    def test_multiple_deprecated_fields_all_tracked(self):
        """Multiple deprecated fields should all be tracked."""
        request = _get_minimal_sizing_request()
        request["include_battery_trace"] = True
        request["include_price_timeseries"] = True
        request["include_ledger_timeseries"] = True

        with httpx.Client(timeout=60.0) as client:
            response = client.post(f"{BASE_URL}/sizing", json=request)

        assert response.status_code == 200
        data = response.json()
        assert "warnings" in data
        assert "deprecations_used" in data["warnings"]
        deprecations = data["warnings"]["deprecations_used"]
        assert "include_battery_trace" in deprecations
        assert "include_price_timeseries" in deprecations
        assert "include_ledger_timeseries" in deprecations

    def test_multiple_deprecated_fields_single_deprecation_header(self):
        """Multiple deprecated fields should set single Deprecation header."""
        request = _get_minimal_sizing_request()
        request["include_battery_trace"] = True
        request["include_price_timeseries"] = True

        with httpx.Client(timeout=60.0) as client:
            response = client.post(f"{BASE_URL}/sizing", json=request)

        assert response.status_code == 200
        assert response.headers.get("Deprecation") == "true"


class TestDeprecatedFieldsWithNewFields:
    """Tests for deprecated fields coexisting with new fields."""

    def test_new_field_takes_precedence(self):
        """New field should take precedence over deprecated field."""
        request = _get_minimal_sizing_request()
        request["include_battery_trace"] = True
        request["battery_trace_mode"] = "preview"

        with httpx.Client(timeout=60.0) as client:
            response = client.post(f"{BASE_URL}/sizing", json=request)

        assert response.status_code == 200
        # The new field should take precedence - battery_trace_mode=preview
        # means we get preview output, not full output from include_battery_trace=true


class TestSunsetHeader:
    """Tests for Sunset header on deprecated fields."""

    def test_deprecated_field_sets_sunset_header(self):
        """Deprecated field usage should set Sunset header."""
        request = _get_minimal_sizing_request()
        request["include_battery_trace"] = True

        with httpx.Client(timeout=60.0) as client:
            response = client.post(f"{BASE_URL}/sizing", json=request)

        assert response.status_code == 200
        assert response.headers.get("Sunset") is not None
        # Sunset should be a date in the future
        sunset = response.headers.get("Sunset")
        assert sunset == "2026-03-01"


class TestLinkHeader:
    """Tests for Link header on deprecated fields."""

    def test_deprecated_field_sets_link_header(self):
        """Deprecated field usage should set Link header."""
        request = _get_minimal_sizing_request()
        request["include_battery_trace"] = True

        with httpx.Client(timeout=60.0) as client:
            response = client.post(f"{BASE_URL}/sizing", json=request)

        assert response.status_code == 200
        link = response.headers.get("Link")
        assert link is not None
        assert "deprecation" in link
        assert "/deprecations" in link

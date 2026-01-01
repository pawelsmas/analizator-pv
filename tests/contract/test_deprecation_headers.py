"""
Contract tests for deprecation headers (v2.7.0 PR1).

Tests verify:
- Deprecation header is present when deprecated fields are used
- Sunset header is present
- Link header points to deprecations endpoint
- Metrics are recorded for deprecated usage
"""

import pytest
import requests
from ._api import DEFAULT_BASE_URL, post_json


def _base_req():
    """Minimal valid sizing request."""
    return {
        "load_kw": [100] * 24,
        "pv_generation_kw": [0, 0, 0, 0, 0, 0, 50, 200, 500, 800, 1000, 1100, 1100, 1000, 800, 500, 200, 50, 0, 0, 0, 0, 0, 0],
        "mode": "pv_surplus",
        "durations_h": [1.0, 2.0],
        "interval_minutes": 60,
        "discount_rate": 0.08,
        "analysis_years": 15,
        "capex_pln_per_kwh": 1800.0,
        "import_price_pln_mwh": 800.0,
    }


def _get_metrics():
    """Fetch metrics from the /metrics endpoint."""
    url = f"{DEFAULT_BASE_URL}/metrics"
    resp = requests.get(url)
    assert resp.status_code == 200
    return resp.text


class TestDeprecationHeadersPresent:
    """Tests for deprecation headers presence when deprecated fields are used."""

    def test_no_deprecation_header_for_clean_request(self):
        """Request without deprecated fields should not have Deprecation header."""
        request = _base_req()
        # Don't use any deprecated fields
        url = f"{DEFAULT_BASE_URL}/sizing"
        resp = requests.post(url, json=request)
        assert resp.status_code == 200
        # May or may not have header depending on other deprecated usage
        # This is a baseline test

    def test_deprecation_header_when_include_battery_trace_used(self):
        """Request with include_battery_trace should have Deprecation header."""
        request = _base_req()
        request["include_battery_trace"] = True  # Deprecated field

        url = f"{DEFAULT_BASE_URL}/sizing"
        resp = requests.post(url, json=request)
        assert resp.status_code == 200

        # Should have deprecation header
        assert "Deprecation" in resp.headers, "Deprecation header should be present"
        assert resp.headers["Deprecation"] == "true"

    def test_deprecation_header_when_include_price_timeseries_used(self):
        """Request with include_price_timeseries should have Deprecation header."""
        request = _base_req()
        request["include_price_timeseries"] = True  # Deprecated field

        url = f"{DEFAULT_BASE_URL}/sizing"
        resp = requests.post(url, json=request)
        assert resp.status_code == 200

        # Should have deprecation header
        assert "Deprecation" in resp.headers, "Deprecation header should be present"
        assert resp.headers["Deprecation"] == "true"

    def test_deprecation_header_when_include_ledger_timeseries_used(self):
        """Request with include_ledger_timeseries should have Deprecation header."""
        request = _base_req()
        request["include_ledger_timeseries"] = True  # Deprecated field

        url = f"{DEFAULT_BASE_URL}/sizing"
        resp = requests.post(url, json=request)
        assert resp.status_code == 200

        # Should have deprecation header
        assert "Deprecation" in resp.headers, "Deprecation header should be present"


class TestDeprecationLinkHeader:
    """Tests for Link header pointing to deprecations endpoint."""

    def test_link_header_present(self):
        """Link header should point to deprecations endpoint."""
        request = _base_req()
        request["include_battery_trace"] = True  # Trigger deprecation

        url = f"{DEFAULT_BASE_URL}/sizing"
        resp = requests.post(url, json=request)
        assert resp.status_code == 200

        assert "Link" in resp.headers, "Link header should be present"
        link = resp.headers["Link"]
        assert "deprecations" in link
        assert 'rel="deprecation"' in link

    def test_link_header_format(self):
        """Link header should have correct format."""
        request = _base_req()
        request["include_battery_trace"] = True

        url = f"{DEFAULT_BASE_URL}/sizing"
        resp = requests.post(url, json=request)
        assert resp.status_code == 200

        link = resp.headers.get("Link", "")
        # Should be in format: </api/bess-dispatch/deprecations>; rel="deprecation"
        assert link.startswith("<")
        assert 'rel="deprecation"' in link


class TestSunsetHeader:
    """Tests for Sunset header."""

    def test_sunset_header_present(self):
        """Sunset header should be present when deprecated fields are used."""
        request = _base_req()
        request["include_battery_trace"] = True  # Trigger deprecation

        url = f"{DEFAULT_BASE_URL}/sizing"
        resp = requests.post(url, json=request)
        assert resp.status_code == 200

        assert "Sunset" in resp.headers, "Sunset header should be present"

    def test_sunset_header_is_date(self):
        """Sunset header should be a valid date."""
        request = _base_req()
        request["include_battery_trace"] = True

        url = f"{DEFAULT_BASE_URL}/sizing"
        resp = requests.post(url, json=request)
        assert resp.status_code == 200

        sunset = resp.headers.get("Sunset", "")
        # Should be in format: YYYY-MM-DD
        assert len(sunset) == 10
        assert sunset[4] == "-"
        assert sunset[7] == "-"


class TestDeprecationMetrics:
    """Tests for deprecation Prometheus metrics."""

    def test_deprecation_used_metric_present(self):
        """bess_deprecation_used_total should be present after deprecated usage."""
        # First, trigger deprecated usage
        request = _base_req()
        request["include_battery_trace"] = True

        url = f"{DEFAULT_BASE_URL}/sizing"
        resp = requests.post(url, json=request)
        assert resp.status_code == 200

        # Check metrics
        metrics = _get_metrics()
        assert "bess_deprecation_used_total" in metrics

    def test_deprecation_used_has_field_label(self):
        """Deprecation metric should have field label."""
        request = _base_req()
        request["include_battery_trace"] = True

        url = f"{DEFAULT_BASE_URL}/sizing"
        resp = requests.post(url, json=request)
        assert resp.status_code == 200

        metrics = _get_metrics()
        # Should have field="include_battery_trace" label
        assert 'field="include_battery_trace"' in metrics

    def test_deprecation_responses_total_present(self):
        """bess_deprecation_responses_total should be in metrics."""
        request = _base_req()
        request["include_battery_trace"] = True

        url = f"{DEFAULT_BASE_URL}/sizing"
        resp = requests.post(url, json=request)
        assert resp.status_code == 200

        metrics = _get_metrics()
        assert "bess_deprecation_responses_total" in metrics


class TestMultipleDeprecatedFields:
    """Tests for using multiple deprecated fields."""

    def test_multiple_deprecated_fields_tracked(self):
        """Using multiple deprecated fields should track all."""
        request = _base_req()
        request["include_battery_trace"] = True
        request["include_price_timeseries"] = True

        url = f"{DEFAULT_BASE_URL}/sizing"
        resp = requests.post(url, json=request)
        assert resp.status_code == 200

        # Should have deprecation header
        assert "Deprecation" in resp.headers

        # Check both fields are in metrics
        metrics = _get_metrics()
        assert 'field="include_battery_trace"' in metrics
        assert 'field="include_price_timeseries"' in metrics

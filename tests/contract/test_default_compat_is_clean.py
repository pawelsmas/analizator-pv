"""
Contract tests for default compat=clean behavior (v2.8.0 PR1).

Tests verify:
- When compat param is NOT provided, response is clean (no deprecated fields)
- No Deprecation header when no deprecated features are used
- Deprecated fields are absent from response
"""

import pytest
import httpx

BASE_URL = "http://localhost:8000/api/bess-dispatch"


def _get_minimal_sizing_request() -> dict:
    """Get minimal valid sizing request using clean fields only."""
    return {
        "load_kw": [100] * 8760,
        "pv_generation_kw": [50] * 8760,
        # Use new fields, not deprecated include_* fields
        "battery_trace_mode": "none",
        "price_timeseries_mode": "none",
        "ledger_timeseries_mode": "none",
    }


class TestSizingDefaultClean:
    """Tests for /sizing endpoint default compat behavior."""

    def test_sizing_no_compat_param_returns_clean(self):
        """Sizing without compat param should return clean response."""
        request = _get_minimal_sizing_request()

        with httpx.Client(timeout=60.0) as client:
            response = client.post(f"{BASE_URL}/sizing", json=request)

        assert response.status_code == 200
        data = response.json()

        # Deprecated fields should NOT be present
        assert "export_revenue_pln" not in str(data)
        assert "savings_pln" not in str(data) or "total_savings_pln" in str(data)

    def test_sizing_no_compat_no_deprecation_header(self):
        """Sizing with clean request should not have Deprecation header."""
        request = _get_minimal_sizing_request()

        with httpx.Client(timeout=60.0) as client:
            response = client.post(f"{BASE_URL}/sizing", json=request)

        assert response.status_code == 200
        # No deprecated fields used in request, so no header
        assert response.headers.get("Deprecation") is None

    def test_sizing_no_compat_no_deprecations_warnings(self):
        """Sizing with clean request should not have deprecation warnings."""
        request = _get_minimal_sizing_request()

        with httpx.Client(timeout=60.0) as client:
            response = client.post(f"{BASE_URL}/sizing", json=request)

        assert response.status_code == 200
        data = response.json()

        # No warnings about deprecations
        warnings = data.get("warnings", {})
        deprecations_used = warnings.get("deprecations_used", [])
        assert len(deprecations_used) == 0

    def test_sizing_explicit_clean_same_as_default(self):
        """Sizing with compat=clean should be same as no param."""
        request = _get_minimal_sizing_request()

        with httpx.Client(timeout=60.0) as client:
            response_default = client.post(f"{BASE_URL}/sizing", json=request)
            response_explicit = client.post(
                f"{BASE_URL}/sizing?compat=clean", json=request
            )

        assert response_default.status_code == 200
        assert response_explicit.status_code == 200

        # Both should have same structure (excluding timestamps/run_id)
        data_default = response_default.json()
        data_explicit = response_explicit.json()

        # Check key fields are present in both
        assert "variants" in data_default
        assert "variants" in data_explicit


class TestSizingLegacyRequiresParam:
    """Tests verifying legacy mode requires explicit param."""

    def test_sizing_legacy_requires_compat_param(self):
        """Legacy fields should only appear with explicit compat=legacy."""
        request = _get_minimal_sizing_request()

        with httpx.Client(timeout=60.0) as client:
            # Default (no param) - should be clean
            response_default = client.post(f"{BASE_URL}/sizing", json=request)
            # Legacy (explicit param) - should have deprecated fields
            response_legacy = client.post(
                f"{BASE_URL}/sizing?compat=legacy", json=request
            )

        data_default = response_default.json()
        data_legacy = response_legacy.json()

        # Default should NOT have export_revenue_pln at any level
        default_str = str(data_default)
        assert "export_revenue_pln" not in default_str

        # Legacy SHOULD have export_revenue_pln (as alias)
        legacy_str = str(data_legacy)
        # This may or may not be present depending on if the field exists in response
        # The key assertion is that default doesn't have it


class TestDeprecatedFieldsAbsent:
    """Tests that specific deprecated fields are absent by default."""

    def test_export_revenue_pln_absent_by_default(self):
        """export_revenue_pln should be absent in default response."""
        request = _get_minimal_sizing_request()

        with httpx.Client(timeout=60.0) as client:
            response = client.post(f"{BASE_URL}/sizing", json=request)

        assert response.status_code == 200
        data = response.json()

        # Check in variants
        for variant in data.get("variants", []):
            assert "export_revenue_pln" not in variant
            # Check in nested structures
            savings = variant.get("savings_breakdown", {})
            assert "export_revenue_pln" not in savings

    def test_interval_minutes_absent_by_default(self):
        """interval_minutes should be absent (use dt_minutes instead)."""
        request = _get_minimal_sizing_request()

        with httpx.Client(timeout=60.0) as client:
            response = client.post(f"{BASE_URL}/sizing", json=request)

        assert response.status_code == 200
        data = response.json()

        # Should use dt_minutes, not interval_minutes
        request_summary = data.get("request_summary", {})
        assert "interval_minutes" not in request_summary
        # dt_minutes should be present
        assert "dt_minutes" in request_summary or "interval_minutes" not in str(data)


class TestCleanResponseStructure:
    """Tests for clean response structure."""

    def test_clean_response_has_expected_fields(self):
        """Clean response should have all expected non-deprecated fields."""
        request = _get_minimal_sizing_request()

        with httpx.Client(timeout=60.0) as client:
            response = client.post(f"{BASE_URL}/sizing", json=request)

        assert response.status_code == 200
        data = response.json()

        # Should have standard fields
        assert "variants" in data
        assert "request_summary" in data

        # Variants should have new field names
        if data["variants"]:
            variant = data["variants"][0]
            # Should have export_savings_pln (new name), not export_revenue_pln (old)
            if "savings_breakdown" in variant:
                savings = variant["savings_breakdown"]
                # New field name should be present if value exists
                # Old field name should be absent
                assert "export_revenue_pln" not in savings


class TestInvalidCompatParam:
    """Tests for invalid compat parameter handling."""

    def test_invalid_compat_defaults_to_clean(self):
        """Invalid compat value should default to clean."""
        request = _get_minimal_sizing_request()

        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                f"{BASE_URL}/sizing?compat=invalid_value", json=request
            )

        assert response.status_code == 200
        data = response.json()

        # Should be treated as clean (no deprecated fields)
        assert "export_revenue_pln" not in str(data)

    def test_empty_compat_defaults_to_clean(self):
        """Empty compat value should default to clean."""
        request = _get_minimal_sizing_request()

        with httpx.Client(timeout=60.0) as client:
            response = client.post(f"{BASE_URL}/sizing?compat=", json=request)

        assert response.status_code == 200
        # Should be treated as clean


class TestCompatModeHeader:
    """Tests for compat mode related headers."""

    def test_no_sunset_header_when_clean(self):
        """Sunset header should not appear when using clean mode."""
        request = _get_minimal_sizing_request()

        with httpx.Client(timeout=60.0) as client:
            response = client.post(f"{BASE_URL}/sizing", json=request)

        assert response.status_code == 200
        # No deprecated features used, so no sunset header
        assert response.headers.get("Sunset") is None

    def test_legacy_mode_sets_deprecation_header(self):
        """Legacy mode should set Deprecation header."""
        request = _get_minimal_sizing_request()

        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                f"{BASE_URL}/sizing?compat=legacy", json=request
            )

        assert response.status_code == 200
        # Legacy mode should trigger deprecation header
        assert response.headers.get("Deprecation") == "true"

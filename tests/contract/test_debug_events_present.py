"""
Contract tests for debug_events in sizing response (v1.8.0).

Tests verify:
- debug_events is present in dispatch_summary
- All required fields are present and have correct types
- Steps count matches period_info.steps
- All values are non-negative
"""
import pytest
import requests

BASE_URL = "http://localhost:8031"


def get_sizing_result():
    """Get a sizing result for testing."""
    # Use a minimal 24h profile with pv_surplus mode (simplest)
    n_hours = 24
    request = {
        "pv_generation_kw": [50.0] * n_hours,  # Constant 50kW PV
        "load_kw": [30.0] * n_hours,  # Constant 30kW load
        "interval_minutes": 60,
        "battery_power_kw": 50.0,
        "battery_energy_kwh": 100.0,
        "mode": "pv_surplus",
        "prices": {
            "import_price_pln_kwh": 0.8,
            "export_price_pln_kwh": 0.4,
        },
    }
    response = requests.post(f"{BASE_URL}/sizing", json=request, timeout=60)
    assert response.status_code == 200, f"Sizing request failed: {response.text}"
    return response.json()


class TestDebugEventsPresent:
    """Contract tests for debug_events presence."""

    def test_debug_events_in_recommended_variant(self):
        """Verify debug_events is present in recommended variant's dispatch_summary."""
        result = get_sizing_result()

        # Find recommended variant
        variants = result.get("variants", [])
        assert len(variants) > 0, "Should have at least one variant"

        recommended = next((v for v in variants if v.get("is_recommended")), variants[0])
        dispatch_summary = recommended.get("dispatch_summary", {})

        assert "debug_events" in dispatch_summary, (
            "dispatch_summary should contain debug_events"
        )

    def test_debug_events_has_steps(self):
        """Verify debug_events.steps equals period timesteps."""
        result = get_sizing_result()

        variants = result.get("variants", [])
        recommended = next((v for v in variants if v.get("is_recommended")), variants[0])
        dispatch_summary = recommended.get("dispatch_summary", {})
        debug_events = dispatch_summary.get("debug_events", {})

        assert "steps" in debug_events
        assert debug_events["steps"] == 24, (
            f"Steps should be 24, got {debug_events['steps']}"
        )

    def test_debug_events_has_export_limited_fields(self):
        """Verify debug_events has export_limited_steps and export_limited_mwh."""
        result = get_sizing_result()

        variants = result.get("variants", [])
        recommended = next((v for v in variants if v.get("is_recommended")), variants[0])
        dispatch_summary = recommended.get("dispatch_summary", {})
        debug_events = dispatch_summary.get("debug_events", {})

        assert "export_limited_steps" in debug_events
        assert "export_limited_mwh" in debug_events
        assert isinstance(debug_events["export_limited_steps"], int)
        assert isinstance(debug_events["export_limited_mwh"], (int, float))

    def test_debug_events_has_import_limited_fields(self):
        """Verify debug_events has import_limited_steps and import_limited_mwh."""
        result = get_sizing_result()

        variants = result.get("variants", [])
        recommended = next((v for v in variants if v.get("is_recommended")), variants[0])
        dispatch_summary = recommended.get("dispatch_summary", {})
        debug_events = dispatch_summary.get("debug_events", {})

        assert "import_limited_steps" in debug_events
        assert "import_limited_mwh" in debug_events
        assert isinstance(debug_events["import_limited_steps"], int)
        assert isinstance(debug_events["import_limited_mwh"], (int, float))

    def test_debug_events_has_pv_curtail_fields(self):
        """Verify debug_events has pv_curtail_steps and pv_curtail_mwh."""
        result = get_sizing_result()

        variants = result.get("variants", [])
        recommended = next((v for v in variants if v.get("is_recommended")), variants[0])
        dispatch_summary = recommended.get("dispatch_summary", {})
        debug_events = dispatch_summary.get("debug_events", {})

        assert "pv_curtail_steps" in debug_events
        assert "pv_curtail_mwh" in debug_events
        assert isinstance(debug_events["pv_curtail_steps"], int)
        assert isinstance(debug_events["pv_curtail_mwh"], (int, float))

    def test_debug_events_has_unserved_load_fields(self):
        """Verify debug_events has unserved_load_steps and unserved_load_kwh."""
        result = get_sizing_result()

        variants = result.get("variants", [])
        recommended = next((v for v in variants if v.get("is_recommended")), variants[0])
        dispatch_summary = recommended.get("dispatch_summary", {})
        debug_events = dispatch_summary.get("debug_events", {})

        assert "unserved_load_steps" in debug_events
        assert "unserved_load_kwh" in debug_events
        assert isinstance(debug_events["unserved_load_steps"], int)
        assert isinstance(debug_events["unserved_load_kwh"], (int, float))

    def test_debug_events_all_values_non_negative(self):
        """Verify all debug_events values are >= 0."""
        result = get_sizing_result()

        variants = result.get("variants", [])
        recommended = next((v for v in variants if v.get("is_recommended")), variants[0])
        dispatch_summary = recommended.get("dispatch_summary", {})
        debug_events = dispatch_summary.get("debug_events", {})

        assert debug_events.get("steps", 0) >= 0
        assert debug_events.get("export_limited_steps", 0) >= 0
        assert debug_events.get("export_limited_mwh", 0) >= 0
        assert debug_events.get("import_limited_steps", 0) >= 0
        assert debug_events.get("import_limited_mwh", 0) >= 0
        assert debug_events.get("pv_curtail_steps", 0) >= 0
        assert debug_events.get("pv_curtail_mwh", 0) >= 0
        assert debug_events.get("unserved_load_steps", 0) >= 0
        assert debug_events.get("unserved_load_kwh", 0) >= 0

    def test_debug_events_in_all_variants(self):
        """Verify debug_events is present in all variants."""
        result = get_sizing_result()

        variants = result.get("variants", [])
        for i, variant in enumerate(variants):
            dispatch_summary = variant.get("dispatch_summary", {})
            assert "debug_events" in dispatch_summary, (
                f"Variant {i} dispatch_summary should contain debug_events"
            )

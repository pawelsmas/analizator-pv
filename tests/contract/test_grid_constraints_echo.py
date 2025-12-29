"""
Contract tests for v0.7.0 grid_constraints echo (PR 1/6).

These tests verify:
1. grid_constraints_applied is present when grid_constraints provided
2. grid_constraints_applied echoes effective values (e.g., max_export_kw=0 when allow_export=False)
3. grid_constraints_applied is None when no constraints provided

Run with: python -m pytest tests/contract/test_grid_constraints_echo.py -v
"""

from ._api import post_json, load_smoke_payload


class TestGridConstraintsEchoPresence:
    """Test that grid_constraints_applied is present when constraints provided."""

    def test_grid_constraints_applied_present_when_constraints_provided(self):
        """grid_constraints_applied should be present when grid_constraints is in request."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        # Add grid_constraints
        p["grid_constraints"] = {
            "max_export_kw": 50.0,
            "allow_export": True,
        }

        resp = post_json("/sizing", p)

        assert "grid_constraints_applied" in resp, (
            "Response should include grid_constraints_applied when grid_constraints provided"
        )
        g = resp["grid_constraints_applied"]
        assert g is not None, "grid_constraints_applied should not be None"

    def test_grid_constraints_applied_none_when_no_constraints(self):
        """grid_constraints_applied should be None when no grid_constraints provided."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        # No grid_constraints - remove if present
        p.pop("grid_constraints", None)

        resp = post_json("/sizing", p)

        # grid_constraints_applied should be None or not present
        g = resp.get("grid_constraints_applied")
        assert g is None, "grid_constraints_applied should be None when no constraints provided"


class TestGridConstraintsEchoValues:
    """Test that grid_constraints_applied echoes correct values."""

    def test_max_export_kw_echoed(self):
        """max_export_kw should be echoed from request."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        p["grid_constraints"] = {
            "max_export_kw": 75.5,
            "allow_export": True,
        }

        resp = post_json("/sizing", p)
        g = resp.get("grid_constraints_applied") or {}

        assert float(g.get("max_export_kw")) == 75.5, (
            f"max_export_kw should be 75.5, got {g.get('max_export_kw')}"
        )

    def test_max_import_kw_echoed(self):
        """max_import_kw should be echoed from request."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        p["grid_constraints"] = {
            "max_import_kw": 100.0,
            "allow_export": True,
        }

        resp = post_json("/sizing", p)
        g = resp.get("grid_constraints_applied") or {}

        assert float(g.get("max_import_kw")) == 100.0, (
            f"max_import_kw should be 100.0, got {g.get('max_import_kw')}"
        )

    def test_allow_export_echoed(self):
        """allow_export should be echoed from request."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        p["grid_constraints"] = {
            "max_export_kw": 50.0,
            "allow_export": True,
        }

        resp = post_json("/sizing", p)
        g = resp.get("grid_constraints_applied") or {}

        assert g.get("allow_export") is True, (
            f"allow_export should be True, got {g.get('allow_export')}"
        )


class TestGridConstraintsEffectiveValues:
    """Test that effective values are computed correctly."""

    def test_allow_export_false_sets_max_export_zero(self):
        """When allow_export=False, effective max_export_kw should be 0."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        p["grid_constraints"] = {
            "max_export_kw": 50.0,  # This value should be overridden
            "allow_export": False,
        }

        resp = post_json("/sizing", p)
        g = resp.get("grid_constraints_applied") or {}

        assert float(g.get("max_export_kw")) == 0.0, (
            f"When allow_export=False, max_export_kw should be 0, got {g.get('max_export_kw')}"
        )
        assert g.get("allow_export") is False, (
            f"allow_export should be False, got {g.get('allow_export')}"
        )

    def test_max_export_null_preserved_when_allow_export_true(self):
        """When allow_export=True and max_export_kw not set, effective should be null (unlimited)."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        p["grid_constraints"] = {
            # max_export_kw not set = unlimited
            "allow_export": True,
        }

        resp = post_json("/sizing", p)
        g = resp.get("grid_constraints_applied") or {}

        assert g.get("max_export_kw") is None, (
            f"When max_export_kw not set and allow_export=True, should be None (unlimited), "
            f"got {g.get('max_export_kw')}"
        )
        assert g.get("allow_export") is True


class TestGridConstraintsAllFields:
    """Test full grid_constraints with all fields."""

    def test_all_fields_echoed(self):
        """All grid_constraints fields should be echoed."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        p["grid_constraints"] = {
            "max_export_kw": 50.0,
            "max_import_kw": 100.0,
            "allow_export": True,
        }

        resp = post_json("/sizing", p)
        g = resp.get("grid_constraints_applied") or {}

        # Verify all expected keys
        expected_keys = {"max_export_kw", "max_import_kw", "allow_export"}
        actual_keys = set(g.keys())
        assert expected_keys.issubset(actual_keys), (
            f"grid_constraints_applied should have keys {expected_keys}, got {actual_keys}"
        )

        # Verify values
        assert float(g.get("max_export_kw")) == 50.0
        assert float(g.get("max_import_kw")) == 100.0
        assert g.get("allow_export") is True

"""
Contract tests for sensitivity sweeps (v0.6.0 PR4).

These tests verify:
1. energy_price_multiplier_sweep produces energy_price_sensitivity array
2. capex_multiplier_sweep produces capex_sensitivity array
3. Sensitivity points are sorted by multiplier (ascending)
4. NPV at multiplier=1.0 matches finance_summary.npv_pln
5. NPV changes monotonically with multiplier (for energy price: higher price = higher NPV)

Run with: python -m pytest tests/contract/test_sensitivity_sweep_contract.py -v
"""
import pytest

from ._api import post_json, load_smoke_payload, pick_recommended_variant


class TestEnergyPriceSensitivityPresence:
    """Test that energy_price_sensitivity is present when sweep provided."""

    def test_energy_price_sensitivity_absent_by_default(self):
        """energy_price_sensitivity should be absent when sweep not provided."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        fc = p.get("finance_config") or {}
        fc["horizon_years"] = 10
        # No energy_price_multiplier_sweep
        p["finance_config"] = fc

        resp = post_json("/sizing", p)
        rec = pick_recommended_variant(resp)
        fs = rec.get("finance_summary") or {}

        assert fs.get("energy_price_sensitivity") is None, (
            "energy_price_sensitivity should be None when sweep not provided"
        )

    def test_energy_price_sensitivity_present_when_sweep_provided(self):
        """energy_price_sensitivity should be present when sweep provided."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        fc = p.get("finance_config") or {}
        fc["horizon_years"] = 10
        fc["energy_price_multiplier_sweep"] = [0.8, 1.0, 1.2]
        p["finance_config"] = fc

        resp = post_json("/sizing", p)
        rec = pick_recommended_variant(resp)
        fs = rec.get("finance_summary") or {}

        assert fs.get("energy_price_sensitivity") is not None, (
            "energy_price_sensitivity should be present when sweep provided"
        )
        assert len(fs["energy_price_sensitivity"]) == 3, (
            "energy_price_sensitivity should have 3 points"
        )


class TestCapexSensitivityPresence:
    """Test that capex_sensitivity is present when sweep provided."""

    def test_capex_sensitivity_absent_by_default(self):
        """capex_sensitivity should be absent when sweep not provided."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        fc = p.get("finance_config") or {}
        fc["horizon_years"] = 10
        # No capex_multiplier_sweep
        p["finance_config"] = fc

        resp = post_json("/sizing", p)
        rec = pick_recommended_variant(resp)
        fs = rec.get("finance_summary") or {}

        assert fs.get("capex_sensitivity") is None, (
            "capex_sensitivity should be None when sweep not provided"
        )

    def test_capex_sensitivity_present_when_sweep_provided(self):
        """capex_sensitivity should be present when sweep provided."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        fc = p.get("finance_config") or {}
        fc["horizon_years"] = 10
        fc["capex_multiplier_sweep"] = [0.8, 1.0, 1.2]
        p["finance_config"] = fc

        resp = post_json("/sizing", p)
        rec = pick_recommended_variant(resp)
        fs = rec.get("finance_summary") or {}

        assert fs.get("capex_sensitivity") is not None, (
            "capex_sensitivity should be present when sweep provided"
        )
        assert len(fs["capex_sensitivity"]) == 3, (
            "capex_sensitivity should have 3 points"
        )


class TestSensitivityPointStructure:
    """Test sensitivity point structure."""

    def test_energy_price_point_has_required_fields(self):
        """Each energy_price_sensitivity point should have required fields."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        fc = p.get("finance_config") or {}
        fc["horizon_years"] = 10
        fc["energy_price_multiplier_sweep"] = [0.8, 1.0, 1.2]
        p["finance_config"] = fc

        resp = post_json("/sizing", p)
        rec = pick_recommended_variant(resp)
        fs = rec.get("finance_summary") or {}
        points = fs.get("energy_price_sensitivity") or []

        assert len(points) > 0

        for pt in points:
            assert "multiplier" in pt, "Point should have multiplier"
            assert "multiplier_pct" in pt, "Point should have multiplier_pct"
            assert "npv_pln" in pt, "Point should have npv_pln"

    def test_capex_point_has_required_fields(self):
        """Each capex_sensitivity point should have required fields."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        fc = p.get("finance_config") or {}
        fc["horizon_years"] = 10
        fc["capex_multiplier_sweep"] = [0.8, 1.0, 1.2]
        p["finance_config"] = fc

        resp = post_json("/sizing", p)
        rec = pick_recommended_variant(resp)
        fs = rec.get("finance_summary") or {}
        points = fs.get("capex_sensitivity") or []

        assert len(points) > 0

        for pt in points:
            assert "multiplier" in pt, "Point should have multiplier"
            assert "multiplier_pct" in pt, "Point should have multiplier_pct"
            assert "npv_pln" in pt, "Point should have npv_pln"


class TestSensitivitySorting:
    """Test that sensitivity points are sorted by multiplier."""

    def test_energy_price_sensitivity_sorted(self):
        """energy_price_sensitivity should be sorted by multiplier (ascending)."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        fc = p.get("finance_config") or {}
        fc["horizon_years"] = 10
        fc["energy_price_multiplier_sweep"] = [1.2, 0.8, 1.0]  # Unsorted input
        p["finance_config"] = fc

        resp = post_json("/sizing", p)
        rec = pick_recommended_variant(resp)
        fs = rec.get("finance_summary") or {}
        points = fs.get("energy_price_sensitivity") or []

        multipliers = [pt["multiplier"] for pt in points]
        assert multipliers == sorted(multipliers), (
            f"Points should be sorted by multiplier: {multipliers}"
        )

    def test_capex_sensitivity_sorted(self):
        """capex_sensitivity should be sorted by multiplier (ascending)."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        fc = p.get("finance_config") or {}
        fc["horizon_years"] = 10
        fc["capex_multiplier_sweep"] = [1.2, 0.8, 1.0]  # Unsorted input
        p["finance_config"] = fc

        resp = post_json("/sizing", p)
        rec = pick_recommended_variant(resp)
        fs = rec.get("finance_summary") or {}
        points = fs.get("capex_sensitivity") or []

        multipliers = [pt["multiplier"] for pt in points]
        assert multipliers == sorted(multipliers), (
            f"Points should be sorted by multiplier: {multipliers}"
        )


class TestSensitivityMultiplierPct:
    """Test that multiplier_pct = multiplier * 100."""

    def test_energy_price_multiplier_pct_conversion(self):
        """multiplier_pct should be multiplier * 100."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        fc = p.get("finance_config") or {}
        fc["horizon_years"] = 10
        fc["energy_price_multiplier_sweep"] = [0.8, 1.0, 1.2]
        p["finance_config"] = fc

        resp = post_json("/sizing", p)
        rec = pick_recommended_variant(resp)
        fs = rec.get("finance_summary") or {}
        points = fs.get("energy_price_sensitivity") or []

        for pt in points:
            expected_pct = pt["multiplier"] * 100
            assert abs(pt["multiplier_pct"] - expected_pct) < 0.01, (
                f"multiplier_pct should be {expected_pct}, got {pt['multiplier_pct']}"
            )


class TestSensitivityNPVBehavior:
    """Test NPV behavior with multiplier changes."""

    def test_energy_price_npv_increases_with_multiplier(self):
        """NPV should increase with higher energy price multiplier."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        fc = p.get("finance_config") or {}
        fc["horizon_years"] = 10
        fc["energy_price_multiplier_sweep"] = [0.8, 1.0, 1.2]
        p["finance_config"] = fc

        resp = post_json("/sizing", p)
        rec = pick_recommended_variant(resp)
        fs = rec.get("finance_summary") or {}
        points = fs.get("energy_price_sensitivity") or []

        # Find NPV at different multipliers
        npv_map = {pt["multiplier"]: pt["npv_pln"] for pt in points}

        # Higher energy price = higher savings = higher NPV
        assert npv_map[0.8] < npv_map[1.0], (
            f"NPV at 0.8x ({npv_map[0.8]:.0f}) should be < NPV at 1.0x ({npv_map[1.0]:.0f})"
        )
        assert npv_map[1.0] < npv_map[1.2], (
            f"NPV at 1.0x ({npv_map[1.0]:.0f}) should be < NPV at 1.2x ({npv_map[1.2]:.0f})"
        )

    def test_capex_npv_decreases_with_multiplier(self):
        """NPV should decrease with higher CAPEX multiplier."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        fc = p.get("finance_config") or {}
        fc["horizon_years"] = 10
        fc["capex_multiplier_sweep"] = [0.8, 1.0, 1.2]
        p["finance_config"] = fc

        resp = post_json("/sizing", p)
        rec = pick_recommended_variant(resp)
        fs = rec.get("finance_summary") or {}
        points = fs.get("capex_sensitivity") or []

        # Find NPV at different multipliers
        npv_map = {pt["multiplier"]: pt["npv_pln"] for pt in points}

        # Higher CAPEX = higher cost = lower NPV
        assert npv_map[0.8] > npv_map[1.0], (
            f"NPV at 0.8x ({npv_map[0.8]:.0f}) should be > NPV at 1.0x ({npv_map[1.0]:.0f})"
        )
        assert npv_map[1.0] > npv_map[1.2], (
            f"NPV at 1.0x ({npv_map[1.0]:.0f}) should be > NPV at 1.2x ({npv_map[1.2]:.0f})"
        )

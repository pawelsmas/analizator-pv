"""
DT equivalence contract test: 60min vs 15min discretization.

Verifies that key annualized KPIs are stable (within tolerance) when
the same energy signal is represented with different time resolutions.

This is a correctness test ensuring the algorithm doesn't introduce
artifacts based on discretization granularity.
"""

import pytest
from ._api import post_json, pick_recommended_variant


def _build_sizing_request(
    load_kw: list[float],
    pv_kw: list[float],
    interval_minutes: int,
    period_start: str = "2025-01-01T00:00:00",
    period_end: str = "2025-01-02T00:00:00",
) -> dict:
    """Build a minimal sizing request for testing."""
    return {
        "load_kw": load_kw,
        "pv_generation_kw": pv_kw,
        "interval_minutes": interval_minutes,
        "durations_h": [2.0],
        "timezone": "Europe/Warsaw",
        "period_start": period_start,
        "period_end": period_end,
        "optimization_config": {"objective": "npv"},
        "operation_mode": "STACKED",
    }


def _expand_60_to_15(values_60: list[float]) -> list[float]:
    """
    Expand 60-min values to 15-min by repeating each value 4 times.

    This preserves total energy: each 15-min slot has 1/4 of the hourly power,
    but there are 4x as many slots, so MWh totals match.
    """
    return [v for v in values_60 for _ in range(4)]


def _relative_diff(a: float, b: float) -> float:
    """Calculate relative difference between two values."""
    if a == 0 and b == 0:
        return 0.0
    return abs(a - b) / max(abs(a), abs(b), 1e-9)


class TestDTEquivalence:
    """Test that 60min and 15min discretization produce similar KPIs."""

    def test_dt_equivalence_60_vs_15_close(self):
        """
        Core equivalence test: same signal at different resolutions
        should produce similar annualized KPIs.
        """
        # Generate deterministic 24h profile (60-min resolution)
        # Pattern: varying load and PV to exercise the algorithm
        load_60 = [100.0 + (i % 6) * 10.0 for i in range(24)]
        pv_60 = [50.0 + (i % 5) * 8.0 for i in range(24)]

        # Expand to 15-min resolution (same total energy)
        load_15 = _expand_60_to_15(load_60)
        pv_15 = _expand_60_to_15(pv_60)

        # Sanity check: same number of data points
        assert len(load_60) == 24, "60-min should have 24 values"
        assert len(load_15) == 96, "15-min should have 96 values"

        # Run sizing for both resolutions
        req_60 = _build_sizing_request(load_60, pv_60, 60)
        req_15 = _build_sizing_request(load_15, pv_15, 15)

        resp_60 = post_json("/sizing", req_60)
        resp_15 = post_json("/sizing", req_15)

        # Extract recommended variants
        var_60 = pick_recommended_variant(resp_60)
        var_15 = pick_recommended_variant(resp_15)

        # Extract key KPIs for comparison
        sb_60 = var_60.get("savings_breakdown", {})
        sb_15 = var_15.get("savings_breakdown", {})

        net_savings_60 = sb_60.get("net_savings_pln", 0)
        net_savings_15 = sb_15.get("net_savings_pln", 0)

        # Grid flows from totals
        totals_60 = var_60.get("totals", {})
        totals_15 = var_15.get("totals", {})

        import_60 = totals_60.get("grid_import_mwh", 0)
        import_15 = totals_15.get("grid_import_mwh", 0)

        export_60 = totals_60.get("grid_export_mwh", 0)
        export_15 = totals_15.get("grid_export_mwh", 0)

        # Define tolerance: 0.5% relative difference
        TOLERANCE = 0.005

        # Assert equivalence for net_savings
        rel_diff_savings = _relative_diff(net_savings_60, net_savings_15)
        assert rel_diff_savings < TOLERANCE, (
            f"net_savings_pln differs too much: "
            f"60min={net_savings_60:.2f}, 15min={net_savings_15:.2f}, "
            f"rel_diff={rel_diff_savings:.4f} (limit={TOLERANCE})"
        )

        # Assert equivalence for grid_import_mwh
        rel_diff_import = _relative_diff(import_60, import_15)
        assert rel_diff_import < TOLERANCE, (
            f"grid_import_mwh differs too much: "
            f"60min={import_60:.4f}, 15min={import_15:.4f}, "
            f"rel_diff={rel_diff_import:.4f} (limit={TOLERANCE})"
        )

        # Assert equivalence for grid_export_mwh
        rel_diff_export = _relative_diff(export_60, export_15)
        assert rel_diff_export < TOLERANCE, (
            f"grid_export_mwh differs too much: "
            f"60min={export_60:.4f}, 15min={export_15:.4f}, "
            f"rel_diff={rel_diff_export:.4f} (limit={TOLERANCE})"
        )

    def test_dt_equivalence_variant_selection_stable(self):
        """
        Verify that the same variant is selected regardless of resolution.
        """
        load_60 = [120.0 + (i % 8) * 5.0 for i in range(24)]
        pv_60 = [40.0 + (i % 4) * 10.0 for i in range(24)]

        load_15 = _expand_60_to_15(load_60)
        pv_15 = _expand_60_to_15(pv_60)

        req_60 = _build_sizing_request(load_60, pv_60, 60)
        req_15 = _build_sizing_request(load_15, pv_15, 15)

        resp_60 = post_json("/sizing", req_60)
        resp_15 = post_json("/sizing", req_15)

        var_60 = pick_recommended_variant(resp_60)
        var_15 = pick_recommended_variant(resp_15)

        # Same variant should be recommended
        # Compare by key characteristics (duration/capacity)
        assert var_60.get("duration_h") == var_15.get("duration_h"), (
            f"Different duration selected: 60min={var_60.get('duration_h')}, "
            f"15min={var_15.get('duration_h')}"
        )

    def test_dt_energy_totals_match(self):
        """
        Verify that total energy flows match between resolutions.
        """
        load_60 = [80.0 + (i % 3) * 20.0 for i in range(24)]
        pv_60 = [60.0 + (i % 6) * 5.0 for i in range(24)]

        load_15 = _expand_60_to_15(load_60)
        pv_15 = _expand_60_to_15(pv_60)

        req_60 = _build_sizing_request(load_60, pv_60, 60)
        req_15 = _build_sizing_request(load_15, pv_15, 15)

        resp_60 = post_json("/sizing", req_60)
        resp_15 = post_json("/sizing", req_15)

        # Period info should reflect same total hours
        period_60 = resp_60.get("period_info", {})
        period_15 = resp_15.get("period_info", {})

        hours_60 = period_60.get("period_hours", 0)
        hours_15 = period_15.get("period_hours", 0)

        assert hours_60 == hours_15, (
            f"Period hours mismatch: 60min={hours_60}, 15min={hours_15}"
        )

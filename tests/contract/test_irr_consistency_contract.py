"""
Contract tests for IRR self-consistency (v0.6.0 PR1).

These tests verify:
1. irr_pct is present in finance_summary when cashflow_timeseries is requested
2. irr_pct equals the rate where NPV of nominal_cashflow_pln array equals zero
3. The bisection algorithm matches the backend calculation

Key invariant: NPV(irr) = sum(CF[t] / (1+irr)^t) = 0

Run with: python -m pytest tests/contract/test_irr_consistency_contract.py -v
"""
import math
from typing import List, Optional

from ._api import post_json, load_smoke_payload, pick_recommended_variant


def _npv(rate: float, cfs: List[float]) -> float:
    """Calculate NPV at given discount rate."""
    s = 0.0
    for t, cf in enumerate(cfs):
        s += float(cf) / ((1.0 + rate) ** t)
    return s


def _irr_bisect(cfs: List[float], lo: float = -0.9, hi: float = 3.0, iterations: int = 80) -> Optional[float]:
    """
    Calculate IRR using bisection method.

    This is the test-side implementation that should match the backend.
    """
    f_lo = _npv(lo, cfs)
    f_hi = _npv(hi, cfs)

    if f_lo == 0:
        return lo
    if f_hi == 0:
        return hi

    # No sign change means no root in interval
    if f_lo * f_hi > 0:
        return None

    for _ in range(iterations):
        mid = (lo + hi) / 2.0
        f_mid = _npv(mid, cfs)

        if abs(f_mid) < 1e-6:
            return mid

        if f_lo * f_mid <= 0:
            hi = mid
            f_hi = f_mid
        else:
            lo = mid
            f_lo = f_mid

    return (lo + hi) / 2.0


class TestIRRPresence:
    """Test that irr_pct is present in finance_summary."""

    def test_irr_pct_present_when_cashflow_requested(self):
        """irr_pct should be present when include_cashflow_timeseries=True."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        # Use minimal data for faster test
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        fc = p.get("finance_config") or {}
        fc["horizon_years"] = 10
        fc["discount_rate"] = 0.08
        fc["include_cashflow_timeseries"] = True
        p["finance_config"] = fc

        resp = post_json("/sizing", p)
        rec = pick_recommended_variant(resp)
        fs = rec.get("finance_summary") or {}

        assert "irr_pct" in fs, "finance_summary should have irr_pct field"

    def test_irr_pct_can_be_none_for_negative_projects(self):
        """irr_pct can be None if no valid IRR exists (all negative cashflows)."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = [0] * 24  # No PV = no savings
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        fc = p.get("finance_config") or {}
        fc["horizon_years"] = 10
        fc["discount_rate"] = 0.08
        fc["include_cashflow_timeseries"] = True
        fc["capex_override_pln"] = 1000000.0  # High CAPEX
        p["finance_config"] = fc

        resp = post_json("/sizing", p)
        rec = pick_recommended_variant(resp)
        fs = rec.get("finance_summary") or {}

        # irr_pct should be present (even if None)
        assert "irr_pct" in fs, "finance_summary should have irr_pct field"
        # For unprofitable projects, irr_pct may be None
        # (we don't assert None here because it depends on savings)


class TestIRRConsistency:
    """Test that irr_pct matches NPV root of cashflow."""

    def test_irr_pct_matches_cashflow_root_when_defined(self):
        """
        Key invariant: irr_pct should equal the rate where NPV = 0.

        This test:
        1. Gets cashflow_timeseries from API
        2. Extracts nominal_cashflow_pln array
        3. Calculates IRR locally using bisection
        4. Compares with backend irr_pct (tolerance: 0.5%)

        Note: If the project has negative savings (no IRR exists), test passes
        as long as backend irr_pct is also None.
        """
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        # Use full week for more realistic savings
        p["load_kw"] = p["load_kw"][:168]  # 1 week
        p["pv_generation_kw"] = p["pv_generation_kw"][:168]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-08T00:00:00"

        fc = p.get("finance_config") or {}
        fc["horizon_years"] = 10
        fc["discount_rate"] = 0.08
        fc["include_cashflow_timeseries"] = True
        fc["opex_pln_per_year"] = 0.0
        p["finance_config"] = fc

        resp = post_json("/sizing", p)
        rec = pick_recommended_variant(resp)
        fs = rec.get("finance_summary") or {}
        irr_pct = fs.get("irr_pct")

        # Get cashflow timeseries
        ct = fs.get("cashflow_timeseries") or []
        assert len(ct) == 11, f"Expected 11 years (0-10), got {len(ct)}"

        # Extract nominal cashflows
        cfs = [y.get("nominal_cashflow_pln") or y.get("net_cashflow_pln") for y in ct]
        assert all(cf is not None for cf in cfs), "All cashflow years should have nominal_cashflow_pln"

        # Calculate IRR locally
        local_irr = _irr_bisect(cfs)

        # If operating cashflows are all negative, no IRR exists
        # Check that backend agrees (irr_pct should be None)
        if all(cf <= 0 for cf in cfs[1:]):
            assert irr_pct is None, (
                f"Project has negative operating cashflows, irr_pct should be None, got {irr_pct}"
            )
            return  # Test passes

        # If local IRR can't be found, backend should also return None
        if local_irr is None:
            assert irr_pct is None, (
                f"Local IRR not found, backend irr_pct should be None, got {irr_pct}"
            )
            return  # Test passes

        # Both should have valid IRR values
        assert irr_pct is not None, (
            f"Local IRR found ({local_irr*100:.2f}%), but backend irr_pct is None"
        )

        # Convert backend percentage to decimal for comparison
        backend_irr = float(irr_pct) / 100.0

        # Tolerance: 0.5 percentage points (absolute)
        assert abs(backend_irr - local_irr) < 0.005, (
            f"IRR mismatch: backend={irr_pct}% ({backend_irr}), "
            f"local={local_irr*100}% ({local_irr})"
        )

    def test_npv_at_irr_is_zero(self):
        """NPV calculated at irr_pct should be approximately zero."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        # Use full week for more realistic savings
        p["load_kw"] = p["load_kw"][:168]  # 1 week
        p["pv_generation_kw"] = p["pv_generation_kw"][:168]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-08T00:00:00"

        fc = p.get("finance_config") or {}
        fc["horizon_years"] = 10
        fc["discount_rate"] = 0.08
        fc["include_cashflow_timeseries"] = True
        fc["opex_pln_per_year"] = 0.0
        p["finance_config"] = fc

        resp = post_json("/sizing", p)
        rec = pick_recommended_variant(resp)
        fs = rec.get("finance_summary") or {}
        irr_pct = fs.get("irr_pct")

        if irr_pct is None:
            return  # Skip if IRR not defined (unprofitable project)

        ct = fs.get("cashflow_timeseries") or []
        cfs = [y.get("nominal_cashflow_pln") or y.get("net_cashflow_pln") for y in ct]

        # Calculate NPV at the backend's IRR
        irr_decimal = float(irr_pct) / 100.0
        npv_at_irr = _npv(irr_decimal, cfs)

        # NPV at IRR should be very close to zero
        # Tolerance: 1 PLN (for numerical precision)
        assert abs(npv_at_irr) < 1.0, (
            f"NPV at IRR should be ~0, got {npv_at_irr:.2f} PLN at IRR={irr_pct}%"
        )


class TestNominalCashflowField:
    """Test that nominal_cashflow_pln field is present."""

    def test_nominal_cashflow_pln_present_in_cashflow(self):
        """Each CashflowYear should have nominal_cashflow_pln field."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        fc = p.get("finance_config") or {}
        fc["horizon_years"] = 5
        fc["include_cashflow_timeseries"] = True
        p["finance_config"] = fc

        resp = post_json("/sizing", p)
        rec = pick_recommended_variant(resp)
        fs = rec.get("finance_summary") or {}
        ct = fs.get("cashflow_timeseries") or []

        assert len(ct) > 0, "Should have cashflow_timeseries"

        for year_data in ct:
            assert "nominal_cashflow_pln" in year_data, (
                f"Year {year_data.get('year')} should have nominal_cashflow_pln"
            )

    def test_nominal_equals_net_cashflow(self):
        """nominal_cashflow_pln should equal net_cashflow_pln (undiscounted)."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        fc = p.get("finance_config") or {}
        fc["horizon_years"] = 5
        fc["include_cashflow_timeseries"] = True
        p["finance_config"] = fc

        resp = post_json("/sizing", p)
        rec = pick_recommended_variant(resp)
        fs = rec.get("finance_summary") or {}
        ct = fs.get("cashflow_timeseries") or []

        for year_data in ct:
            nominal = year_data.get("nominal_cashflow_pln")
            net = year_data.get("net_cashflow_pln")

            assert nominal is not None, f"Year {year_data.get('year')}: nominal_cashflow_pln is None"
            assert net is not None, f"Year {year_data.get('year')}: net_cashflow_pln is None"

            # They should be equal (both are undiscounted)
            assert abs(nominal - net) < 0.01, (
                f"Year {year_data.get('year')}: nominal ({nominal}) != net ({net})"
            )

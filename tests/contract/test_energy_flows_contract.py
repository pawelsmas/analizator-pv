"""
Contract tests for Energy Flows SSoT.

Verifies:
1. energy_flows.totals_mwh is always present
2. timeseries_kwh only present when requested
3. totals match sums of timeseries
4. Load balance invariant holds per step
"""
import math
import pytest
from ._api import post_json, load_smoke_payload, pick_recommended_variant


TOL = 1e-6


def _sum(arr):
    """Sum array, handling None."""
    return float(sum(arr or []))


class TestEnergyFlowsTotalsPresent:
    """Test that energy_flows.totals_mwh is always present."""

    def test_energy_flows_totals_present_by_default(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify energy_flows.totals_mwh is present without requesting timeseries."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        # Explicitly don't request timeseries
        payload.pop("include_energy_flows_timeseries", None)

        resp = post_json("/sizing", payload)
        rec = pick_recommended_variant(resp)

        dispatch = rec.get("dispatch_summary") or {}
        flows = dispatch.get("energy_flows")

        assert flows is not None, "dispatch_summary.energy_flows missing"
        assert "totals_mwh" in flows, "energy_flows.totals_mwh missing"

        # Timeseries should NOT be present by default (to keep response small)
        timeseries = flows.get("timeseries_kwh")
        assert timeseries is None or timeseries == {}, \
            "timeseries_kwh should not be returned by default"

    def test_totals_have_required_fields(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify totals_mwh has all required fields."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")

        resp = post_json("/sizing", payload)
        rec = pick_recommended_variant(resp)

        flows = (rec.get("dispatch_summary") or {}).get("energy_flows") or {}
        totals = flows.get("totals_mwh") or {}

        required_fields = [
            "grid_import_mwh",
            "grid_export_mwh",
            "pv_to_load_mwh",
            "pv_to_batt_mwh",
            "pv_curtail_mwh",
            "batt_to_load_mwh",
            "batt_charge_from_grid_mwh",
            "batt_losses_mwh",
        ]

        for field in required_fields:
            assert field in totals, f"totals_mwh.{field} missing"
            assert isinstance(totals[field], (int, float)), f"{field} should be numeric"


class TestEnergyFlowsTimeseries:
    """Test timeseries when explicitly requested."""

    def test_timeseries_present_when_requested(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify timeseries_kwh is present when include_energy_flows_timeseries=True."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        payload["include_energy_flows_timeseries"] = True

        resp = post_json("/sizing", payload)
        rec = pick_recommended_variant(resp)

        flows = (rec.get("dispatch_summary") or {}).get("energy_flows") or {}
        ts = flows.get("timeseries_kwh")

        assert ts is not None, "timeseries_kwh should be present when requested"
        assert isinstance(ts, dict), "timeseries_kwh should be a dict"

    def test_timeseries_lengths_match_period(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify all timeseries arrays have correct length."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        payload["include_energy_flows_timeseries"] = True

        resp = post_json("/sizing", payload)
        rec = pick_recommended_variant(resp)

        flows = (rec.get("dispatch_summary") or {}).get("energy_flows") or {}
        ts = flows.get("timeseries_kwh") or {}

        # Get expected length from input
        n_expected = len(payload.get("load_kw", []))

        timeseries_fields = [
            "grid_import_kwh",
            "grid_export_kwh",
            "pv_to_load_kwh",
            "pv_to_batt_kwh",
            "pv_curtail_kwh",
            "batt_to_load_kwh",
            "batt_charge_from_grid_kwh",
            "batt_losses_kwh",
            "soc_kwh",
        ]

        for field in timeseries_fields:
            arr = ts.get(field) or []
            assert len(arr) == n_expected, \
                f"{field} length {len(arr)} != expected {n_expected}"


class TestEnergyFlowsInvariants:
    """Test energy flow invariants (totals = sum of timeseries)."""

    def test_totals_equal_sum_of_timeseries(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify totals_mwh ≈ sum(timeseries_kwh) / 1000."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        payload["include_energy_flows_timeseries"] = True

        resp = post_json("/sizing", payload)
        rec = pick_recommended_variant(resp)

        flows = (rec.get("dispatch_summary") or {}).get("energy_flows") or {}
        totals = flows.get("totals_mwh") or {}
        ts = flows.get("timeseries_kwh") or {}

        # Check each field: totals_mwh ≈ sum(timeseries_kwh) / 1000
        mappings = [
            ("grid_import_kwh", "grid_import_mwh"),
            ("grid_export_kwh", "grid_export_mwh"),
            ("pv_to_load_kwh", "pv_to_load_mwh"),
            ("pv_to_batt_kwh", "pv_to_batt_mwh"),
            ("pv_curtail_kwh", "pv_curtail_mwh"),
            ("batt_to_load_kwh", "batt_to_load_mwh"),
            ("batt_charge_from_grid_kwh", "batt_charge_from_grid_mwh"),
            ("batt_losses_kwh", "batt_losses_mwh"),
        ]

        for ts_key, total_key in mappings:
            sum_mwh = _sum(ts.get(ts_key)) / 1000.0
            total_val = float(totals.get(total_key) or 0.0)

            assert math.isclose(sum_mwh, total_val, rel_tol=1e-4, abs_tol=1e-6), \
                f"{total_key} ({total_val}) != sum({ts_key})/1000 ({sum_mwh})"

    def test_load_balance_per_step(
        self, wait_for_services, bess_dispatch_url
    ):
        """
        Verify load balance invariant per step:
        load_kwh[t] ≈ pv_to_load[t] + batt_to_load[t] + grid_import[t]
        """
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        payload["include_energy_flows_timeseries"] = True

        resp = post_json("/sizing", payload)
        rec = pick_recommended_variant(resp)

        # Get inputs
        load_kw = payload.get("load_kw", [])
        interval_minutes = float(payload.get("interval_minutes") or 60)
        dt_h = interval_minutes / 60.0

        flows = (rec.get("dispatch_summary") or {}).get("energy_flows") or {}
        ts = flows.get("timeseries_kwh") or {}

        grid_import = ts.get("grid_import_kwh") or []
        pv_to_load = ts.get("pv_to_load_kwh") or []
        batt_to_load = ts.get("batt_to_load_kwh") or []

        n = len(grid_import)
        assert n == len(load_kw), "timeseries length mismatch vs inputs"

        # Check balance at each step
        for i in range(n):
            load_kwh = float(load_kw[i]) * dt_h
            supply_kwh = float(pv_to_load[i]) + float(batt_to_load[i]) + float(grid_import[i])

            assert math.isclose(load_kwh, supply_kwh, rel_tol=1e-4, abs_tol=1e-3), \
                f"Load balance failed at step {i}: load={load_kwh} vs supply={supply_kwh}"


class TestEnergyFlowsValues:
    """Test that energy flow values are sensible."""

    def test_grid_import_non_negative(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify grid import values are non-negative."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        payload["include_energy_flows_timeseries"] = True

        resp = post_json("/sizing", payload)
        rec = pick_recommended_variant(resp)

        flows = (rec.get("dispatch_summary") or {}).get("energy_flows") or {}
        ts = flows.get("timeseries_kwh") or {}
        totals = flows.get("totals_mwh") or {}

        # Totals should be non-negative
        assert float(totals.get("grid_import_mwh") or 0) >= 0

        # All timeseries values should be non-negative
        for val in (ts.get("grid_import_kwh") or []):
            assert float(val) >= -1e-6, f"Negative grid import: {val}"

    def test_pv_flows_sum_to_total_pv(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify PV splits sum to total PV generation."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        payload["include_energy_flows_timeseries"] = True

        resp = post_json("/sizing", payload)
        rec = pick_recommended_variant(resp)

        # Total PV from input
        pv_kw = payload.get("pv_generation_kw", [])
        interval_minutes = float(payload.get("interval_minutes") or 60)
        dt_h = interval_minutes / 60.0
        total_pv_kwh = sum(pv_kw) * dt_h
        total_pv_mwh = total_pv_kwh / 1000.0

        flows = (rec.get("dispatch_summary") or {}).get("energy_flows") or {}
        totals = flows.get("totals_mwh") or {}

        # PV splits: to_load + to_batt + curtail + export should equal total PV
        pv_to_load = float(totals.get("pv_to_load_mwh") or 0)
        pv_to_batt = float(totals.get("pv_to_batt_mwh") or 0)
        pv_curtail = float(totals.get("pv_curtail_mwh") or 0)
        grid_export = float(totals.get("grid_export_mwh") or 0)

        pv_accounted = pv_to_load + pv_to_batt + pv_curtail + grid_export

        assert math.isclose(pv_accounted, total_pv_mwh, rel_tol=0.01, abs_tol=0.1), \
            f"PV accounting mismatch: {pv_accounted} vs {total_pv_mwh}"

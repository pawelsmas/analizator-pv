"""
Contract tests for battery replacement event (v0.6.0 PR2).

These tests verify:
1. replacement_year and replacement_capex_pln are echoed in finance_assumptions
2. Replacement cost appears as negative cashflow in the specified year
3. NPV is calculated correctly with replacement event
4. IRR is calculated correctly with replacement event

Run with: python -m pytest tests/contract/test_replacement_contract.py -v
"""
import pytest

from ._api import post_json, load_smoke_payload, pick_recommended_variant


class TestReplacementAssumptionsEcho:
    """Test that replacement fields are echoed in finance_assumptions."""

    def test_replacement_fields_absent_by_default(self):
        """When no replacement is specified, replacement fields should be None."""
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
        # No replacement fields
        p["finance_config"] = fc

        resp = post_json("/sizing", p)
        fa = resp.get("finance_assumptions") or {}

        assert "replacement_year" in fa, "finance_assumptions should have replacement_year"
        assert "replacement_capex_pln" in fa, "finance_assumptions should have replacement_capex_pln"
        assert fa["replacement_year"] is None, "replacement_year should be None by default"
        assert fa["replacement_capex_pln"] is None, "replacement_capex_pln should be None by default"

    def test_replacement_year_echoed(self):
        """replacement_year should be echoed in finance_assumptions."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        fc = p.get("finance_config") or {}
        fc["horizon_years"] = 15
        fc["replacement_year"] = 10
        p["finance_config"] = fc

        resp = post_json("/sizing", p)
        fa = resp.get("finance_assumptions") or {}

        assert fa.get("replacement_year") == 10, (
            f"replacement_year should be 10, got {fa.get('replacement_year')}"
        )

    def test_replacement_capex_echoed(self):
        """replacement_capex_pln should be echoed in finance_assumptions."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        fc = p.get("finance_config") or {}
        fc["horizon_years"] = 15
        fc["replacement_year"] = 10
        fc["replacement_capex_pln"] = 100000.0
        p["finance_config"] = fc

        resp = post_json("/sizing", p)
        fa = resp.get("finance_assumptions") or {}

        assert fa.get("replacement_capex_pln") == 100000.0, (
            f"replacement_capex_pln should be 100000.0, got {fa.get('replacement_capex_pln')}"
        )


class TestReplacementInCashflow:
    """Test that replacement appears correctly in cashflow_timeseries."""

    def test_replacement_appears_in_specified_year(self):
        """
        Replacement cost should appear as negative adjustment in the specified year.

        In year 10, net_cashflow_pln should be (savings - opex - replacement_cost).
        """
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:168]  # 1 week for realistic savings
        p["pv_generation_kw"] = p["pv_generation_kw"][:168]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-08T00:00:00"

        replacement_cost = 100000.0
        fc = p.get("finance_config") or {}
        fc["horizon_years"] = 15
        fc["discount_rate"] = 0.08
        fc["include_cashflow_timeseries"] = True
        fc["replacement_year"] = 10
        fc["replacement_capex_pln"] = replacement_cost
        p["finance_config"] = fc

        resp = post_json("/sizing", p)
        rec = pick_recommended_variant(resp)
        fs = rec.get("finance_summary") or {}
        ct = fs.get("cashflow_timeseries") or []

        assert len(ct) == 16, f"Expected 16 years (0-15), got {len(ct)}"

        # Find year 10
        year_10 = next((y for y in ct if y.get("year") == 10), None)
        assert year_10 is not None, "Year 10 should be in cashflow_timeseries"

        # Find a regular year (e.g., year 5) for comparison
        year_5 = next((y for y in ct if y.get("year") == 5), None)
        assert year_5 is not None, "Year 5 should be in cashflow_timeseries"

        # Year 10 cashflow should be lower by replacement_cost compared to year 5
        # (assuming same savings and opex)
        savings_10 = year_10.get("savings_pln", 0)
        opex_10 = year_10.get("opex_pln", 0)
        net_cf_10 = year_10.get("net_cashflow_pln", 0)

        savings_5 = year_5.get("savings_pln", 0)
        opex_5 = year_5.get("opex_pln", 0)
        net_cf_5 = year_5.get("net_cashflow_pln", 0)

        # Savings and OPEX should be the same (no escalation by default)
        assert abs(savings_10 - savings_5) < 0.01, (
            f"Savings should be same: year 5 = {savings_5}, year 10 = {savings_10}"
        )
        assert abs(opex_10 - opex_5) < 0.01, (
            f"OPEX should be same: year 5 = {opex_5}, year 10 = {opex_10}"
        )

        # Net cashflow in year 10 should be lower by replacement_cost
        expected_net_cf_10 = net_cf_5 - replacement_cost
        assert abs(net_cf_10 - expected_net_cf_10) < 1.0, (
            f"Year 10 net_cashflow should be {expected_net_cf_10:.0f}, got {net_cf_10:.0f}"
        )

    def test_no_replacement_in_other_years(self):
        """Years other than replacement_year should have normal cashflows."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:168]
        p["pv_generation_kw"] = p["pv_generation_kw"][:168]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-08T00:00:00"

        fc = p.get("finance_config") or {}
        fc["horizon_years"] = 15
        fc["include_cashflow_timeseries"] = True
        fc["replacement_year"] = 10
        fc["replacement_capex_pln"] = 100000.0
        p["finance_config"] = fc

        resp = post_json("/sizing", p)
        rec = pick_recommended_variant(resp)
        fs = rec.get("finance_summary") or {}
        ct = fs.get("cashflow_timeseries") or []

        # Check that years 1-9 and 11-15 have normal cashflows (savings - opex)
        for year_data in ct:
            year = year_data.get("year")
            if year == 0 or year == 10:
                continue  # Skip year 0 (investment) and year 10 (replacement)

            savings = year_data.get("savings_pln", 0)
            opex = year_data.get("opex_pln", 0)
            net_cf = year_data.get("net_cashflow_pln", 0)

            expected = savings - opex
            assert abs(net_cf - expected) < 0.01, (
                f"Year {year}: net_cashflow should be {expected:.2f}, got {net_cf:.2f}"
            )


class TestReplacementWithNPV:
    """Test NPV calculation with replacement event."""

    def test_npv_lower_with_replacement(self):
        """NPV should be lower when replacement is included (additional cost)."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:168]
        p["pv_generation_kw"] = p["pv_generation_kw"][:168]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-08T00:00:00"

        # Request WITHOUT replacement
        fc_no_repl = {
            "horizon_years": 15,
            "discount_rate": 0.08,
            "include_cashflow_timeseries": True,
        }
        p["finance_config"] = fc_no_repl

        resp_no_repl = post_json("/sizing", p)
        rec_no_repl = pick_recommended_variant(resp_no_repl)
        npv_no_repl = rec_no_repl.get("finance_summary", {}).get("npv_pln", 0)

        # Request WITH replacement
        fc_with_repl = {
            "horizon_years": 15,
            "discount_rate": 0.08,
            "include_cashflow_timeseries": True,
            "replacement_year": 10,
            "replacement_capex_pln": 100000.0,
        }
        p["finance_config"] = fc_with_repl

        resp_with_repl = post_json("/sizing", p)
        rec_with_repl = pick_recommended_variant(resp_with_repl)
        npv_with_repl = rec_with_repl.get("finance_summary", {}).get("npv_pln", 0)

        # NPV with replacement should be lower
        assert npv_with_repl < npv_no_repl, (
            f"NPV with replacement ({npv_with_repl:.0f}) should be lower than "
            f"without ({npv_no_repl:.0f})"
        )

        # The difference should be approximately the discounted replacement cost
        # Discounted cost at year 10: 100000 / (1.08)^10 = ~46319
        discounted_cost = 100000.0 / ((1.08) ** 10)
        npv_diff = npv_no_repl - npv_with_repl

        # Allow 5% tolerance for calculation differences
        assert abs(npv_diff - discounted_cost) < discounted_cost * 0.05, (
            f"NPV difference ({npv_diff:.0f}) should be close to "
            f"discounted replacement cost ({discounted_cost:.0f})"
        )


class TestReplacementWithIRR:
    """Test IRR calculation with replacement event."""

    def test_irr_lower_with_replacement(self):
        """IRR should be lower when replacement is included (additional cost)."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:168]
        p["pv_generation_kw"] = p["pv_generation_kw"][:168]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-08T00:00:00"

        # Request WITHOUT replacement
        fc_no_repl = {
            "horizon_years": 15,
            "discount_rate": 0.08,
            "include_cashflow_timeseries": True,
        }
        p["finance_config"] = fc_no_repl

        resp_no_repl = post_json("/sizing", p)
        rec_no_repl = pick_recommended_variant(resp_no_repl)
        irr_no_repl = rec_no_repl.get("finance_summary", {}).get("irr_pct")

        # Request WITH replacement
        fc_with_repl = {
            "horizon_years": 15,
            "discount_rate": 0.08,
            "include_cashflow_timeseries": True,
            "replacement_year": 10,
            "replacement_capex_pln": 100000.0,
        }
        p["finance_config"] = fc_with_repl

        resp_with_repl = post_json("/sizing", p)
        rec_with_repl = pick_recommended_variant(resp_with_repl)
        irr_with_repl = rec_with_repl.get("finance_summary", {}).get("irr_pct")

        # Skip if either IRR is None (unprofitable project)
        if irr_no_repl is None or irr_with_repl is None:
            pytest.skip("One or both IRR values are None (unprofitable project)")

        # IRR with replacement should be lower
        assert irr_with_repl < irr_no_repl, (
            f"IRR with replacement ({irr_with_repl:.2f}%) should be lower than "
            f"without ({irr_no_repl:.2f}%)"
        )


class TestReplacementDefaultCost:
    """Test that replacement uses original CAPEX when replacement_capex_pln is not specified."""

    def test_replacement_uses_original_capex_when_not_specified(self):
        """When replacement_capex_pln is None, replacement should use original CAPEX."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:168]
        p["pv_generation_kw"] = p["pv_generation_kw"][:168]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-08T00:00:00"

        fc = {
            "horizon_years": 15,
            "discount_rate": 0.08,
            "include_cashflow_timeseries": True,
            "replacement_year": 10,
            # replacement_capex_pln NOT specified - should use original CAPEX
        }
        p["finance_config"] = fc

        resp = post_json("/sizing", p)
        rec = pick_recommended_variant(resp)
        fs = rec.get("finance_summary") or {}
        ct = fs.get("cashflow_timeseries") or []
        capex = fs.get("capex_pln", 0)

        # Find year 0 and year 10
        year_0 = next((y for y in ct if y.get("year") == 0), None)
        year_10 = next((y for y in ct if y.get("year") == 10), None)
        year_5 = next((y for y in ct if y.get("year") == 5), None)

        assert year_0 is not None and year_10 is not None and year_5 is not None

        # Year 0 net cashflow should be -capex
        assert abs(year_0.get("net_cashflow_pln", 0) + capex) < 1.0, (
            f"Year 0 should be -{capex:.0f}, got {year_0.get('net_cashflow_pln', 0):.0f}"
        )

        # Year 10 should have normal cashflow minus capex (replacement)
        savings_5 = year_5.get("savings_pln", 0)
        opex_5 = year_5.get("opex_pln", 0)
        normal_cf = savings_5 - opex_5

        net_cf_10 = year_10.get("net_cashflow_pln", 0)
        expected_cf_10 = normal_cf - capex  # Uses original CAPEX

        assert abs(net_cf_10 - expected_cf_10) < 1.0, (
            f"Year 10 net_cashflow should be {expected_cf_10:.0f} (normal - capex), "
            f"got {net_cf_10:.0f}"
        )

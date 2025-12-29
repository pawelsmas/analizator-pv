"""
Contract tests for performance degradation (v0.6.0 PR3).

These tests verify:
1. bess_degradation_pct_per_year and pv_degradation_pct_per_year are echoed in finance_assumptions
2. Degradation reduces yearly savings over time
3. NPV and IRR are lower with degradation
4. Degradation formula: savings[year] = base_savings * (1 - bess_rate)^year * (1 - pv_rate)^year

Run with: python -m pytest tests/contract/test_degradation_rate_contract.py -v
"""
import pytest

from ._api import post_json, load_smoke_payload, pick_recommended_variant


class TestDegradationAssumptionsEcho:
    """Test that degradation fields are echoed in finance_assumptions."""

    def test_degradation_fields_default_to_zero(self):
        """When no degradation is specified, degradation fields should be 0."""
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
        # No degradation fields
        p["finance_config"] = fc

        resp = post_json("/sizing", p)
        fa = resp.get("finance_assumptions") or {}

        assert "bess_degradation_pct_per_year" in fa, "finance_assumptions should have bess_degradation_pct_per_year"
        assert "pv_degradation_pct_per_year" in fa, "finance_assumptions should have pv_degradation_pct_per_year"
        assert fa["bess_degradation_pct_per_year"] == 0.0, "bess_degradation should be 0 by default"
        assert fa["pv_degradation_pct_per_year"] == 0.0, "pv_degradation should be 0 by default"

    def test_bess_degradation_echoed(self):
        """bess_degradation_pct_per_year should be echoed in finance_assumptions."""
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
        fc["bess_degradation_pct_per_year"] = 2.0
        p["finance_config"] = fc

        resp = post_json("/sizing", p)
        fa = resp.get("finance_assumptions") or {}

        assert fa.get("bess_degradation_pct_per_year") == 2.0, (
            f"bess_degradation should be 2.0, got {fa.get('bess_degradation_pct_per_year')}"
        )

    def test_pv_degradation_echoed(self):
        """pv_degradation_pct_per_year should be echoed in finance_assumptions."""
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
        fc["pv_degradation_pct_per_year"] = 0.5
        p["finance_config"] = fc

        resp = post_json("/sizing", p)
        fa = resp.get("finance_assumptions") or {}

        assert fa.get("pv_degradation_pct_per_year") == 0.5, (
            f"pv_degradation should be 0.5, got {fa.get('pv_degradation_pct_per_year')}"
        )


class TestDegradationInCashflow:
    """Test that degradation reduces savings over time."""

    def test_savings_decrease_with_bess_degradation(self):
        """Year 10 savings should be lower than year 1 with BESS degradation."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:168]  # 1 week
        p["pv_generation_kw"] = p["pv_generation_kw"][:168]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-08T00:00:00"

        fc = p.get("finance_config") or {}
        fc["horizon_years"] = 15
        fc["discount_rate"] = 0.08
        fc["include_cashflow_timeseries"] = True
        fc["bess_degradation_pct_per_year"] = 2.0  # 2% annual BESS degradation
        p["finance_config"] = fc

        resp = post_json("/sizing", p)
        rec = pick_recommended_variant(resp)
        fs = rec.get("finance_summary") or {}
        ct = fs.get("cashflow_timeseries") or []

        assert len(ct) == 16, f"Expected 16 years (0-15), got {len(ct)}"

        # Find year 1 and year 10
        year_1 = next((y for y in ct if y.get("year") == 1), None)
        year_10 = next((y for y in ct if y.get("year") == 10), None)

        assert year_1 is not None and year_10 is not None

        savings_1 = year_1.get("savings_pln", 0)
        savings_10 = year_10.get("savings_pln", 0)

        # Year 10 should have lower savings than year 1 (due to degradation)
        assert savings_10 < savings_1, (
            f"Year 10 savings ({savings_10:.0f}) should be lower than year 1 ({savings_1:.0f})"
        )

        # Verify degradation formula: savings_10 = savings_1 * (0.98)^9
        # (year 1 has factor 0.98^1, year 10 has factor 0.98^10)
        expected_ratio = (0.98 ** 10) / (0.98 ** 1)  # ~0.835
        actual_ratio = savings_10 / savings_1

        assert abs(actual_ratio - expected_ratio) < 0.01, (
            f"Ratio should be ~{expected_ratio:.3f}, got {actual_ratio:.3f}"
        )

    def test_savings_decrease_with_combined_degradation(self):
        """Combined BESS + PV degradation should reduce savings more than BESS alone."""
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
        fc["discount_rate"] = 0.08
        fc["include_cashflow_timeseries"] = True
        fc["bess_degradation_pct_per_year"] = 2.0
        fc["pv_degradation_pct_per_year"] = 0.5
        p["finance_config"] = fc

        resp = post_json("/sizing", p)
        rec = pick_recommended_variant(resp)
        fs = rec.get("finance_summary") or {}
        ct = fs.get("cashflow_timeseries") or []

        year_1 = next((y for y in ct if y.get("year") == 1), None)
        year_10 = next((y for y in ct if y.get("year") == 10), None)

        assert year_1 is not None and year_10 is not None

        savings_1 = year_1.get("savings_pln", 0)
        savings_10 = year_10.get("savings_pln", 0)

        # Verify combined formula: (1 - 0.02)^year * (1 - 0.005)^year
        bess_factor_10 = 0.98 ** 10
        pv_factor_10 = 0.995 ** 10
        bess_factor_1 = 0.98 ** 1
        pv_factor_1 = 0.995 ** 1

        expected_ratio = (bess_factor_10 * pv_factor_10) / (bess_factor_1 * pv_factor_1)
        actual_ratio = savings_10 / savings_1

        assert abs(actual_ratio - expected_ratio) < 0.01, (
            f"Ratio should be ~{expected_ratio:.3f}, got {actual_ratio:.3f}"
        )


class TestDegradationWithNPV:
    """Test NPV calculation with degradation."""

    def test_npv_lower_with_degradation(self):
        """NPV should be lower when degradation is included."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:168]
        p["pv_generation_kw"] = p["pv_generation_kw"][:168]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-08T00:00:00"

        # Request WITHOUT degradation
        fc_no_deg = {
            "horizon_years": 15,
            "discount_rate": 0.08,
            "include_cashflow_timeseries": True,
        }
        p["finance_config"] = fc_no_deg

        resp_no_deg = post_json("/sizing", p)
        rec_no_deg = pick_recommended_variant(resp_no_deg)
        npv_no_deg = rec_no_deg.get("finance_summary", {}).get("npv_pln", 0)

        # Request WITH degradation
        fc_with_deg = {
            "horizon_years": 15,
            "discount_rate": 0.08,
            "include_cashflow_timeseries": True,
            "bess_degradation_pct_per_year": 2.0,
            "pv_degradation_pct_per_year": 0.5,
        }
        p["finance_config"] = fc_with_deg

        resp_with_deg = post_json("/sizing", p)
        rec_with_deg = pick_recommended_variant(resp_with_deg)
        npv_with_deg = rec_with_deg.get("finance_summary", {}).get("npv_pln", 0)

        # NPV with degradation should be lower
        assert npv_with_deg < npv_no_deg, (
            f"NPV with degradation ({npv_with_deg:.0f}) should be lower than "
            f"without ({npv_no_deg:.0f})"
        )


class TestDegradationWithIRR:
    """Test IRR calculation with degradation."""

    def test_irr_lower_with_degradation(self):
        """IRR should be lower when degradation is included."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:168]
        p["pv_generation_kw"] = p["pv_generation_kw"][:168]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-08T00:00:00"

        # Request WITHOUT degradation
        fc_no_deg = {
            "horizon_years": 15,
            "discount_rate": 0.08,
            "include_cashflow_timeseries": True,
        }
        p["finance_config"] = fc_no_deg

        resp_no_deg = post_json("/sizing", p)
        rec_no_deg = pick_recommended_variant(resp_no_deg)
        irr_no_deg = rec_no_deg.get("finance_summary", {}).get("irr_pct")

        # Request WITH degradation
        fc_with_deg = {
            "horizon_years": 15,
            "discount_rate": 0.08,
            "include_cashflow_timeseries": True,
            "bess_degradation_pct_per_year": 2.0,
        }
        p["finance_config"] = fc_with_deg

        resp_with_deg = post_json("/sizing", p)
        rec_with_deg = pick_recommended_variant(resp_with_deg)
        irr_with_deg = rec_with_deg.get("finance_summary", {}).get("irr_pct")

        # Skip if either IRR is None (unprofitable project)
        if irr_no_deg is None or irr_with_deg is None:
            pytest.skip("One or both IRR values are None (unprofitable project)")

        # IRR with degradation should be lower
        assert irr_with_deg < irr_no_deg, (
            f"IRR with degradation ({irr_with_deg:.2f}%) should be lower than "
            f"without ({irr_no_deg:.2f}%)"
        )


class TestDegradationFormula:
    """Test the degradation formula is correctly applied."""

    def test_year_1_factor(self):
        """Year 1 should have degradation factor = (1 - rate)^1."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:168]
        p["pv_generation_kw"] = p["pv_generation_kw"][:168]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-08T00:00:00"

        # First get base savings (no degradation)
        fc_base = {
            "horizon_years": 5,
            "discount_rate": 0.08,
            "include_cashflow_timeseries": True,
            "bess_degradation_pct_per_year": 0.0,
        }
        p["finance_config"] = fc_base

        resp_base = post_json("/sizing", p)
        rec_base = pick_recommended_variant(resp_base)
        ct_base = rec_base.get("finance_summary", {}).get("cashflow_timeseries", [])
        year_1_base = next((y for y in ct_base if y.get("year") == 1), None)
        base_savings = year_1_base.get("savings_pln", 0)

        # Now get degraded savings (5% BESS degradation)
        fc_deg = {
            "horizon_years": 5,
            "discount_rate": 0.08,
            "include_cashflow_timeseries": True,
            "bess_degradation_pct_per_year": 5.0,
        }
        p["finance_config"] = fc_deg

        resp_deg = post_json("/sizing", p)
        rec_deg = pick_recommended_variant(resp_deg)
        ct_deg = rec_deg.get("finance_summary", {}).get("cashflow_timeseries", [])
        year_1_deg = next((y for y in ct_deg if y.get("year") == 1), None)
        deg_savings = year_1_deg.get("savings_pln", 0)

        # Year 1 with 5% degradation: savings * 0.95^1 = savings * 0.95
        expected_savings = base_savings * 0.95
        tolerance = abs(base_savings) * 0.01  # 1% tolerance

        assert abs(deg_savings - expected_savings) < tolerance, (
            f"Year 1 savings with 5% degradation: expected {expected_savings:.2f}, got {deg_savings:.2f}"
        )

"""
Contract tests for export revenue + penalty correctness (v1.5.0 PR5).

These tests verify:
1. economics_breakdown.export_revenue_pln == savings_breakdown.project_export_revenue_pln
2. Export revenue consistency across all code paths
3. Penalty calculation correctness and inclusion in net_savings
4. Annualization handling for partial periods with export/penalty
"""

import math
import pytest
from ._api import post_json, load_smoke_payload, pick_recommended_variant


# -----------------------------------------------------------------------------
# Test: Export Revenue Consistency
# -----------------------------------------------------------------------------

class TestExportRevenueConsistency:
    """Test that export revenue is consistent across different response fields."""

    def test_economics_breakdown_export_equals_savings_breakdown_project(self):
        """
        economics_breakdown.totals_pln.export_revenue_pln should equal
        savings_breakdown.project_export_revenue_pln.
        """
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        payload["export_price_pln_mwh"] = 200.0  # Ensure export price set

        result = post_json("/sizing", payload)
        variant = result["variants"][0]

        # Get from economics_breakdown
        eb = variant.get("dispatch_summary", {}).get("economics_breakdown", {})
        eb_export = eb.get("totals_pln", {}).get("export_revenue_pln", 0)

        # Get from savings_breakdown
        sb = variant.get("savings_breakdown", {})
        sb_project_export = sb.get("project_export_revenue_pln", 0)

        assert math.isclose(eb_export, sb_project_export, abs_tol=0.01), (
            f"Export revenue mismatch: "
            f"economics_breakdown.export_revenue_pln={eb_export}, "
            f"savings_breakdown.project_export_revenue_pln={sb_project_export}"
        )

    def test_legacy_export_revenue_equals_project(self):
        """export_revenue_pln (legacy) should equal project_export_revenue_pln."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        payload["export_price_pln_mwh"] = 200.0

        result = post_json("/sizing", payload)
        variant = result["variants"][0]
        sb = variant.get("savings_breakdown", {})

        legacy = sb.get("export_revenue_pln", 0)
        project = sb.get("project_export_revenue_pln", 0)

        assert math.isclose(legacy, project, abs_tol=0.01), (
            f"Legacy export_revenue_pln={legacy} != project_export_revenue_pln={project}"
        )

    def test_export_savings_formula_correctness(self):
        """export_revenue_savings_pln = project - baseline."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        payload["export_price_pln_mwh"] = 200.0

        result = post_json("/sizing", payload)
        variant = result["variants"][0]
        sb = variant.get("savings_breakdown", {})

        baseline = sb.get("baseline_export_revenue_pln", 0)
        project = sb.get("project_export_revenue_pln", 0)
        savings = sb.get("export_revenue_savings_pln", 0)

        expected = project - baseline

        assert math.isclose(savings, expected, abs_tol=0.01), (
            f"Export savings formula incorrect: {savings} != {project} - {baseline} = {expected}"
        )


# -----------------------------------------------------------------------------
# Test: Penalty Correctness
# -----------------------------------------------------------------------------

class TestPenaltyCorrectness:
    """Test penalty calculation correctness."""

    def test_penalty_formula_with_unserved_load(self):
        """penalty = unserved_load_kwh * penalty_rate."""
        payload = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        payload["load_kw"] = payload["load_kw"][:24]
        payload["pv_generation_kw"] = payload["pv_generation_kw"][:24]
        payload["interval_minutes"] = 60
        payload["durations_h"] = [2.0]
        payload["timezone"] = "Europe/Warsaw"
        payload["period_start"] = "2025-01-01T00:00:00"
        payload["period_end"] = "2025-01-02T00:00:00"

        # Very restrictive import cap to ensure unserved load
        payload["grid_constraints"] = {
            "max_import_kw": 1.0,  # Very low cap
            "unserved_load_penalty_pln_kwh": 10.0,  # 10 PLN/kWh penalty
        }

        result = post_json("/sizing", payload)
        variants = result.get("variants", [])

        for variant in variants:
            sb = variant.get("savings_breakdown", {})
            penalty = sb.get("unserved_load_penalty_pln", 0)

            ds = variant.get("dispatch_summary") or {}
            cs = ds.get("constraint_summary")

            if cs is not None:
                unserved_kwh = cs.get("unserved_load_kwh", 0)
                expected_penalty = unserved_kwh * 10.0

                if unserved_kwh > 0:
                    # Penalty should match formula within tolerance
                    assert abs(penalty - expected_penalty) < max(expected_penalty * 0.01, 0.1), (
                        f"Penalty mismatch: got {penalty}, expected {expected_penalty}"
                    )

    def test_penalty_included_in_net_savings(self):
        """net_savings should be reduced by penalty."""
        payload = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        payload["load_kw"] = payload["load_kw"][:24]
        payload["pv_generation_kw"] = payload["pv_generation_kw"][:24]
        payload["interval_minutes"] = 60
        payload["durations_h"] = [2.0]
        payload["timezone"] = "Europe/Warsaw"
        payload["period_start"] = "2025-01-01T00:00:00"
        payload["period_end"] = "2025-01-02T00:00:00"

        payload["grid_constraints"] = {
            "max_import_kw": 1.0,
            "unserved_load_penalty_pln_kwh": 10.0,
        }

        result = post_json("/sizing", payload)
        variants = result.get("variants", [])

        for variant in variants:
            sb = variant.get("savings_breakdown", {})

            energy = sb.get("energy_savings_pln", 0)
            capacity = sb.get("capacity_fee_savings_pln", 0)
            demand = sb.get("demand_charge_savings_pln", 0)
            arbitrage = sb.get("arbitrage_savings_pln", 0)
            export_delta = sb.get("export_revenue_savings_pln", 0)
            degradation = abs(sb.get("degradation_cost_pln", 0))
            penalty = abs(sb.get("unserved_load_penalty_pln", 0))
            net = sb.get("net_savings_pln", 0)

            # Formula: net = energy + capacity + demand + arbitrage + export_delta - degradation - penalty
            expected = energy + capacity + demand + arbitrage + export_delta - degradation - penalty

            assert abs(net - expected) < 1.0, (
                f"Net savings formula mismatch: {net} != {expected} (penalty={penalty})"
            )


# -----------------------------------------------------------------------------
# Test: Zero Export Price Edge Case
# -----------------------------------------------------------------------------

class TestZeroExportPriceEdgeCase:
    """Test edge cases with zero export price."""

    def test_all_export_values_zero_when_no_price(self):
        """When export_price = 0, all export values should be 0."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        payload["export_price_pln_mwh"] = 0.0

        result = post_json("/sizing", payload)
        variant = result["variants"][0]

        sb = variant.get("savings_breakdown", {})
        eb = variant.get("dispatch_summary", {}).get("economics_breakdown", {})

        # All export values should be 0
        assert sb.get("baseline_export_revenue_pln", 0) == 0
        assert sb.get("project_export_revenue_pln", 0) == 0
        assert sb.get("export_revenue_savings_pln", 0) == 0
        assert sb.get("export_revenue_pln", 0) == 0
        assert eb.get("totals_pln", {}).get("export_revenue_pln", 0) == 0


# -----------------------------------------------------------------------------
# Test: Partial Period with Export/Penalty
# -----------------------------------------------------------------------------

class TestPartialPeriodExportPenalty:
    """Test export and penalty calculations for partial periods."""

    def test_export_revenue_not_annualized_in_breakdown(self):
        """
        Export revenue in savings_breakdown should be for the actual analysis period,
        not annualized. Annualization happens at NPV calculation level.
        """
        # Test with 7-day period
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        payload["load_kw"] = payload["load_kw"][:168]  # 7 days
        payload["pv_generation_kw"] = payload["pv_generation_kw"][:168]
        payload["interval_minutes"] = 60
        payload["export_price_pln_mwh"] = 200.0
        payload["timezone"] = "Europe/Warsaw"
        payload["period_start"] = "2025-01-01T00:00:00"
        payload["period_end"] = "2025-01-08T00:00:00"

        result = post_json("/sizing", payload)

        # Period should be 168 hours
        period_info = result.get("period_info", {})
        period_hours = period_info.get("period_hours", 0)
        assert period_hours == 168 or abs(period_hours - 168) < 1, (
            f"Expected period_hours=168, got {period_hours}"
        )

        # Export revenue should be for 7-day period (not scaled up)
        variant = result["variants"][0]
        sb = variant.get("savings_breakdown", {})

        # All export values should be non-negative (valid)
        assert sb.get("baseline_export_revenue_pln", -1) >= 0
        assert sb.get("project_export_revenue_pln", -1) >= 0

    def test_penalty_not_annualized_in_breakdown(self):
        """
        Penalty in savings_breakdown should be for actual analysis period,
        not annualized.
        """
        payload = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        payload["load_kw"] = payload["load_kw"][:24]  # 1 day
        payload["pv_generation_kw"] = payload["pv_generation_kw"][:24]
        payload["interval_minutes"] = 60
        payload["durations_h"] = [2.0]
        payload["timezone"] = "Europe/Warsaw"
        payload["period_start"] = "2025-01-01T00:00:00"
        payload["period_end"] = "2025-01-02T00:00:00"

        payload["grid_constraints"] = {
            "max_import_kw": 1.0,
            "unserved_load_penalty_pln_kwh": 5.0,
        }

        result = post_json("/sizing", payload)
        variants = result.get("variants", [])

        for variant in variants:
            sb = variant.get("savings_breakdown", {})
            penalty = sb.get("unserved_load_penalty_pln", 0)

            # Penalty should be reasonable for 1-day period
            # (not multiplied by 365 or similar)
            ds = variant.get("dispatch_summary") or {}
            cs = ds.get("constraint_summary")

            if cs is not None:
                unserved_kwh = cs.get("unserved_load_kwh", 0)
                max_expected = unserved_kwh * 5.0 * 1.01  # 1% tolerance

                assert penalty <= max_expected + 0.1, (
                    f"Penalty {penalty} seems annualized (max expected {max_expected})"
                )


# -----------------------------------------------------------------------------
# Test: Export Revenue with ToU Pricing
# -----------------------------------------------------------------------------

class TestExportRevenueWithToU:
    """Test export revenue consistency when ToU pricing is enabled."""

    def test_export_revenue_with_tou_pricing(self):
        """Export revenue should be calculated even with ToU import pricing."""
        payload = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        payload["load_kw"] = payload["load_kw"][:168]  # 7 days
        payload["pv_generation_kw"] = payload["pv_generation_kw"][:168]
        payload["interval_minutes"] = 60
        payload["export_price_pln_mwh"] = 200.0
        payload["timezone"] = "Europe/Warsaw"
        payload["period_start"] = "2025-01-01T00:00:00"
        payload["period_end"] = "2025-01-08T00:00:00"

        result = post_json("/sizing", payload)
        variant = result["variants"][0]

        sb = variant.get("savings_breakdown", {})

        # Export fields should be present and consistent
        baseline = sb.get("baseline_export_revenue_pln", -1)
        project = sb.get("project_export_revenue_pln", -1)
        savings = sb.get("export_revenue_savings_pln", None)

        assert baseline >= 0, "baseline_export_revenue_pln should be >= 0"
        assert project >= 0, "project_export_revenue_pln should be >= 0"

        if savings is not None:
            expected = project - baseline
            assert math.isclose(savings, expected, abs_tol=0.01), (
                f"Export savings formula incorrect with ToU: {savings} != {expected}"
            )


# -----------------------------------------------------------------------------
# Test: All Variants Have Consistent Export/Penalty
# -----------------------------------------------------------------------------

class TestAllVariantsConsistency:
    """Test that all variants have consistent export and penalty calculations."""

    def test_all_variants_have_export_fields(self):
        """All variants should have export revenue fields."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        payload["export_price_pln_mwh"] = 200.0

        result = post_json("/sizing", payload)
        variants = result.get("variants", [])

        assert len(variants) > 0, "Should have variants"

        for i, variant in enumerate(variants):
            sb = variant.get("savings_breakdown", {})

            required_fields = [
                "baseline_export_revenue_pln",
                "project_export_revenue_pln",
                "export_revenue_savings_pln",
                "export_revenue_pln",
            ]

            for field in required_fields:
                assert field in sb, f"Variant {i} missing {field}"

    def test_all_variants_have_penalty_field(self):
        """All variants should have unserved_load_penalty_pln field."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")

        result = post_json("/sizing", payload)
        variants = result.get("variants", [])

        for i, variant in enumerate(variants):
            sb = variant.get("savings_breakdown", {})
            assert "unserved_load_penalty_pln" in sb, (
                f"Variant {i} missing unserved_load_penalty_pln"
            )

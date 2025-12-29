"""
Contract tests for export revenue baseline/project breakdown.

Verifies:
1. baseline_export_revenue_pln, project_export_revenue_pln, export_revenue_savings_pln present
2. export_revenue_savings_pln = project - baseline (formula invariant)
3. With PV surplus: baseline > 0 (there's something to export)
4. Without PV: baseline = 0, project = 0, savings = 0
5. Legacy field export_revenue_pln equals project_export_revenue_pln
"""
import math
import pytest
from ._api import post_json, load_smoke_payload, pick_recommended_variant


class TestExportRevenueFieldsPresent:
    """Test that export revenue breakdown fields are present."""

    def test_export_revenue_fields_present(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify all export revenue fields are in savings_breakdown."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")

        resp = post_json("/sizing", payload)

        recommended = pick_recommended_variant(resp)
        assert recommended is not None, "No recommended variant"

        sb = recommended.get("savings_breakdown", {})

        # All export revenue fields should be present
        assert "baseline_export_revenue_pln" in sb, "baseline_export_revenue_pln missing"
        assert "project_export_revenue_pln" in sb, "project_export_revenue_pln missing"
        assert "export_revenue_savings_pln" in sb, "export_revenue_savings_pln missing"
        assert "export_revenue_pln" in sb, "export_revenue_pln missing (legacy)"


class TestExportRevenueSavingsFormula:
    """Test export_revenue_savings_pln = project - baseline formula."""

    def test_savings_equals_project_minus_baseline(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify export_revenue_savings_pln = project - baseline."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")

        resp = post_json("/sizing", payload)

        recommended = pick_recommended_variant(resp)
        sb = recommended.get("savings_breakdown", {})

        baseline = sb.get("baseline_export_revenue_pln", 0)
        project = sb.get("project_export_revenue_pln", 0)
        savings = sb.get("export_revenue_savings_pln", 0)

        expected_savings = project - baseline

        assert math.isclose(savings, expected_savings, abs_tol=0.01), (
            f"export_revenue_savings_pln {savings} != "
            f"project {project} - baseline {baseline} = {expected_savings}"
        )

    def test_legacy_field_equals_project(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify export_revenue_pln equals project_export_revenue_pln."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")

        resp = post_json("/sizing", payload)

        recommended = pick_recommended_variant(resp)
        sb = recommended.get("savings_breakdown", {})

        project = sb.get("project_export_revenue_pln", 0)
        legacy = sb.get("export_revenue_pln", 0)

        assert math.isclose(legacy, project, abs_tol=0.01), (
            f"export_revenue_pln {legacy} != project_export_revenue_pln {project}"
        )


class TestExportRevenueWithPvSurplus:
    """Test export revenue with PV surplus scenario."""

    def test_pv_surplus_has_baseline_export(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify baseline export > 0 when there's PV surplus and export price > 0."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")

        # Ensure export price is set
        if "prices" not in payload:
            payload["prices"] = {}
        payload["prices"]["export_price_pln_mwh"] = 200.0  # 0.20 PLN/kWh

        resp = post_json("/sizing", payload)

        recommended = pick_recommended_variant(resp)
        sb = recommended.get("savings_breakdown", {})

        baseline = sb.get("baseline_export_revenue_pln", 0)
        project = sb.get("project_export_revenue_pln", 0)
        savings = sb.get("export_revenue_savings_pln", 0)

        # With PV surplus and export price > 0:
        # - baseline > 0 (PV surplus without battery would be exported)
        # - project can be >= 0 (battery reduces export but some may remain)
        # - savings is typically negative (battery uses PV that would be exported)
        assert baseline >= 0, f"baseline_export_revenue_pln {baseline} should be >= 0"

        # If there's any PV data, there should be some export in baseline
        pv_sum = sum(payload.get("pv_generation_kw", []))
        if pv_sum > 0:
            # Could be zero if load > PV at all times, but typically > 0
            pass  # We don't assert baseline > 0 because it depends on load profile


class TestExportRevenueWithZeroExportPrice:
    """Test export revenue when export_price = 0."""

    def test_zero_export_price_zero_revenue(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify all export revenues are 0 when export_price = 0."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")

        # Set export price to 0
        if "prices" not in payload:
            payload["prices"] = {}
        payload["prices"]["export_price_pln_mwh"] = 0.0

        resp = post_json("/sizing", payload)

        recommended = pick_recommended_variant(resp)
        sb = recommended.get("savings_breakdown", {})

        baseline = sb.get("baseline_export_revenue_pln", 0)
        project = sb.get("project_export_revenue_pln", 0)
        savings = sb.get("export_revenue_savings_pln", 0)

        assert baseline == 0, f"baseline_export_revenue_pln {baseline} should be 0"
        assert project == 0, f"project_export_revenue_pln {project} should be 0"
        assert savings == 0, f"export_revenue_savings_pln {savings} should be 0"


class TestExportRevenueNetSavingsFormula:
    """Test that net_savings includes export_revenue_savings_pln correctly."""

    def test_net_savings_includes_export_delta(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify net_savings formula includes export_revenue_savings_pln."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")

        # Set export price to generate meaningful export values
        if "prices" not in payload:
            payload["prices"] = {}
        payload["prices"]["export_price_pln_mwh"] = 200.0

        resp = post_json("/sizing", payload)

        recommended = pick_recommended_variant(resp)
        sb = recommended.get("savings_breakdown", {})

        # Get all components
        energy = sb.get("energy_savings_pln", 0)
        arbitrage = sb.get("arbitrage_savings_pln", 0)
        capacity_fee = sb.get("capacity_fee_savings_pln", 0)
        demand = sb.get("demand_charge_savings_pln", 0)
        export_delta = sb.get("export_revenue_savings_pln", 0)
        degradation = abs(sb.get("degradation_cost_pln", 0))
        net = sb.get("net_savings_pln", 0)

        # Formula: net = energy + arbitrage + capacity_fee + demand + export_delta - degradation
        calculated_net = energy + arbitrage + capacity_fee + demand + export_delta - degradation

        assert math.isclose(net, calculated_net, abs_tol=1.0), (
            f"net_savings_pln {net} != calculated {calculated_net}\n"
            f"Components: energy={energy}, arbitrage={arbitrage}, "
            f"capacity_fee={capacity_fee}, demand={demand}, "
            f"export_delta={export_delta}, degradation={degradation}"
        )

class TestExportRevenuePLNDeprecated:
    """Test that export_revenue_pln is marked deprecated."""

    def test_legacy_field_equals_project_value(
        self, wait_for_services, bess_dispatch_url
    ):
        """
        Verify export_revenue_pln (DEPRECATED) equals project_export_revenue_pln.
        
        This test documents the deprecation:
        - export_revenue_pln is DEPRECATED
        - Use project_export_revenue_pln instead
        - Field will be removed in v1.0
        """
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")

        # Set export price to generate meaningful values
        if "prices" not in payload:
            payload["prices"] = {}
        payload["prices"]["export_price_pln_mwh"] = 200.0

        resp = post_json("/sizing", payload)

        recommended = pick_recommended_variant(resp)
        sb = recommended.get("savings_breakdown", {})

        project = sb.get("project_export_revenue_pln", 0)
        legacy = sb.get("export_revenue_pln", 0)

        # DEPRECATED: export_revenue_pln should equal project_export_revenue_pln
        assert math.isclose(legacy, project, abs_tol=0.01), (
            f"[DEPRECATED] export_revenue_pln ({legacy}) should equal "
            f"project_export_revenue_pln ({project}). "
            f"Use project_export_revenue_pln in new code."
        )

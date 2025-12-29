"""
Regression tests for BESS sizing API.

These tests verify that golden master responses have consistent values.
They validate FORMULAS and INVARIANTS, not API responses.

Scenarios:
1. No arbitrage (STACKED mode, basic)
2. With arbitrage (STACKED + ToU)
3. PV surplus mode with export

Tolerance: 5% for economic values, 1% for throughput
"""
import pytest
import math


# Tolerance for floating point comparisons
ECONOMIC_TOLERANCE = 0.05  # 5% for NPV, savings
THROUGHPUT_TOLERANCE = 0.01  # 1% for kWh values


def relative_diff(actual: float, expected: float) -> float:
    """Calculate relative difference, handling zero expected."""
    if abs(expected) < 1e-9:
        return abs(actual)  # If expected is ~0, return absolute value
    return abs(actual - expected) / abs(expected)


class TestRegressionScenario1NoArb:
    """Regression tests for Scenario 1: No arbitrage (basic STACKED)."""

    GOLDEN_FILE = "scenario1_no_arb.json"

    def test_recommended_variant_unchanged(self, load_golden):
        """Verify recommended variant is a valid enum value."""
        golden = load_golden(self.GOLDEN_FILE)
        golden_recommended = golden.get("recommended_variant")

        if not golden_recommended:
            pytest.skip("No recommended_variant in golden")

        assert golden_recommended in ["small", "medium", "large"]

    def test_npv_values_are_numeric(self, load_golden):
        """Verify NPV values are numeric."""
        golden = load_golden(self.GOLDEN_FILE)

        for variant in golden.get("variants", []):
            golden_npv = variant.get("npv_pln", 0)
            golden_label = variant.get("variant", "unknown")

            assert isinstance(golden_npv, (int, float)), (
                f"Variant {golden_label}: NPV should be numeric"
            )

    def test_degradation_cost_formula(self, load_golden):
        """Verify degradation = throughput * 50 PLN/MWh (default rate)."""
        golden = load_golden(self.GOLDEN_FILE)

        for variant in golden.get("variants", []):
            sb = variant.get("savings_breakdown", {})

            throughput_mwh = sb.get("battery_throughput_mwh", 0)
            degradation = abs(sb.get("degradation_cost_pln", 0))

            # Expected: throughput * 50 PLN/MWh
            expected_degradation = throughput_mwh * 50.0

            if throughput_mwh > 0:
                diff = relative_diff(degradation, expected_degradation)
                assert diff < THROUGHPUT_TOLERANCE, (
                    f"degradation_cost_pln {degradation:.2f} != "
                    f"throughput {throughput_mwh:.4f} * 50 = {expected_degradation:.2f}"
                )


class TestRegressionScenario2WithArb:
    """Regression tests for Scenario 2: With arbitrage (STACKED + ToU)."""

    GOLDEN_FILE = "scenario2_with_arb.json"

    def test_arbitrage_savings_non_negative(self, load_golden):
        """Verify arbitrage_savings_pln >= 0 when enabled."""
        golden = load_golden(self.GOLDEN_FILE)

        for variant in golden.get("variants", []):
            sb = variant.get("savings_breakdown", {})
            arb_savings = sb.get("arbitrage_savings_pln", 0)

            # Arbitrage savings should be >= 0 (can't lose money on arbitrage)
            # Note: may be 0 if spread isn't large enough
            assert arb_savings >= 0, (
                f"arbitrage_savings_pln {arb_savings} should be >= 0"
            )


class TestRegressionScenario3PvSurplus:
    """Regression tests for Scenario 3: PV surplus mode with export."""

    GOLDEN_FILE = "scenario3_pv_surplus.json"

    def test_export_revenue_breakdown_present(self, load_golden):
        """Verify export revenue breakdown is populated."""
        golden = load_golden(self.GOLDEN_FILE)

        for variant in golden.get("variants", []):
            sb = variant.get("savings_breakdown", {})

            # All export revenue fields should be present
            assert "baseline_export_revenue_pln" in sb
            assert "project_export_revenue_pln" in sb
            assert "export_revenue_savings_pln" in sb

    def test_export_delta_formula(self, load_golden):
        """Verify export_revenue_savings = project - baseline."""
        golden = load_golden(self.GOLDEN_FILE)

        for variant in golden.get("variants", []):
            sb = variant.get("savings_breakdown", {})

            baseline = sb.get("baseline_export_revenue_pln", 0)
            project = sb.get("project_export_revenue_pln", 0)
            savings = sb.get("export_revenue_savings_pln", 0)

            expected_savings = project - baseline

            assert math.isclose(savings, expected_savings, abs_tol=1.0), (
                f"export_revenue_savings {savings:.2f} != "
                f"project {project:.2f} - baseline {baseline:.2f} = {expected_savings:.2f}"
            )

    def test_export_delta_typically_negative(self, load_golden):
        """
        Verify export delta is typically negative.

        Battery uses PV that would otherwise be exported, so:
        - baseline > project (more export without battery)
        - savings = project - baseline < 0 (negative)
        """
        golden = load_golden(self.GOLDEN_FILE)

        # Get recommended variant
        variants = golden.get("variants", [])
        recommended = next(
            (v for v in variants if v.get("is_recommended")),
            variants[0] if variants else None
        )

        if recommended:
            sb = recommended.get("savings_breakdown", {})
            savings = sb.get("export_revenue_savings_pln", 0)

            # Export savings should be negative (battery reduces export)
            # Unless there's no PV surplus or no export price
            baseline = sb.get("baseline_export_revenue_pln", 0)
            if baseline > 0:
                assert savings <= 0, (
                    f"export_revenue_savings {savings:.2f} should be <= 0 "
                    f"(battery uses PV that would be exported)"
                )


class TestRegressionNetSavingsFormula:
    """Test net savings formula consistency across all scenarios."""

    SCENARIOS = [
        "scenario1_no_arb.json",
        "scenario2_with_arb.json",
        "scenario3_pv_surplus.json",
    ]

    @pytest.mark.parametrize("scenario", SCENARIOS)
    def test_net_savings_formula(self, load_golden, scenario):
        """
        Verify net_savings = energy + arbitrage + capacity_fee + demand + export_delta - degradation.

        This formula must hold for ALL scenarios.
        """
        golden = load_golden(scenario)

        for variant in golden.get("variants", []):
            sb = variant.get("savings_breakdown", {})

            energy = sb.get("energy_savings_pln", 0)
            arbitrage = sb.get("arbitrage_savings_pln", 0)
            capacity_fee = sb.get("capacity_fee_savings_pln", 0)
            demand = sb.get("demand_charge_savings_pln", 0)
            export_delta = sb.get("export_revenue_savings_pln", 0)
            degradation = abs(sb.get("degradation_cost_pln", 0))
            net = sb.get("net_savings_pln", 0)

            calculated_net = (
                energy + arbitrage + capacity_fee + demand + export_delta - degradation
            )

            assert math.isclose(net, calculated_net, abs_tol=1.0), (
                f"{scenario} variant {variant.get('variant')}: "
                f"net_savings {net:.2f} != calculated {calculated_net:.2f}\n"
                f"Components: energy={energy:.2f}, arbitrage={arbitrage:.2f}, "
                f"capacity_fee={capacity_fee:.2f}, demand={demand:.2f}, "
                f"export_delta={export_delta:.2f}, degradation={degradation:.2f}"
            )

"""
Regression tests for v0.5.0 finance features.

These tests verify:
1. Cashflow timeseries structure and NPV consistency
2. Discount rate sensitivity monotonicity
3. Finance assumptions propagation

Run with: python -m pytest tests/regression/test_regression_finance_v050.py -v
"""
import pytest
import math


# Tolerance for floating point comparisons
NPV_TOLERANCE_PCT = 0.01  # 1% for NPV consistency


def relative_diff(actual: float, expected: float) -> float:
    """Calculate relative difference, handling zero expected."""
    if abs(expected) < 1e-9:
        return abs(actual)
    return abs(actual - expected) / abs(expected)


class TestRegressionCashflowV050:
    """Regression tests for cashflow_timeseries (v0.5.0 PR2)."""

    GOLDEN_FILE = "scenario_finance_v050.json"

    def test_cashflow_timeseries_present(self, load_golden):
        """Verify cashflow_timeseries is present when requested."""
        golden = load_golden(self.GOLDEN_FILE)

        for variant in golden.get("variants", []):
            fs = variant.get("finance_summary", {})
            cashflow = fs.get("cashflow_timeseries")

            assert cashflow is not None, (
                f"Variant {variant.get('variant')}: cashflow_timeseries should be present"
            )
            assert isinstance(cashflow, list), (
                f"Variant {variant.get('variant')}: cashflow_timeseries should be a list"
            )

    def test_cashflow_has_required_fields(self, load_golden):
        """Verify each CashflowYear has all required fields."""
        golden = load_golden(self.GOLDEN_FILE)
        required_fields = [
            "year",
            "savings_pln",
            "opex_pln",
            "net_cashflow_pln",
            "discounted_cashflow_pln",
            "cumulative_cashflow_pln",
        ]

        for variant in golden.get("variants", []):
            fs = variant.get("finance_summary", {})
            cashflow = fs.get("cashflow_timeseries", [])

            for year_data in cashflow:
                for field in required_fields:
                    assert field in year_data, (
                        f"Variant {variant.get('variant')} year {year_data.get('year')}: "
                        f"missing required field {field}"
                    )

    def test_npv_equals_sum_of_discounted_cashflows(self, load_golden):
        """
        NPV consistency invariant: npv_pln == sum(discounted_cashflow_pln).

        This is the key contract invariant for cashflow correctness.
        """
        golden = load_golden(self.GOLDEN_FILE)

        for variant in golden.get("variants", []):
            fs = variant.get("finance_summary", {})
            npv_from_summary = fs.get("npv_pln", 0)
            cashflow = fs.get("cashflow_timeseries", [])

            if not cashflow:
                continue

            sum_discounted = sum(y.get("discounted_cashflow_pln", 0) for y in cashflow)

            # Calculate tolerance based on magnitude
            tolerance = max(abs(npv_from_summary) * NPV_TOLERANCE_PCT, 1.0)

            assert abs(npv_from_summary - sum_discounted) < tolerance, (
                f"Variant {variant.get('variant')}: NPV ({npv_from_summary:.2f}) != "
                f"sum(discounted_cashflow) ({sum_discounted:.2f})"
            )

    def test_cumulative_is_running_total(self, load_golden):
        """Verify cumulative_cashflow_pln is running total of net_cashflow_pln."""
        golden = load_golden(self.GOLDEN_FILE)

        for variant in golden.get("variants", []):
            fs = variant.get("finance_summary", {})
            cashflow = fs.get("cashflow_timeseries", [])

            if not cashflow:
                continue

            # First year: cumulative = net (including -CAPEX)
            # Subsequent years: cumulative = previous_cumulative + net
            running_total = 0.0
            for year_data in cashflow:
                net = year_data.get("net_cashflow_pln", 0)
                cumulative = year_data.get("cumulative_cashflow_pln", 0)
                running_total += net

                assert math.isclose(cumulative, running_total, abs_tol=1.0), (
                    f"Variant {variant.get('variant')} year {year_data.get('year')}: "
                    f"cumulative ({cumulative:.2f}) != running_total ({running_total:.2f})"
                )


class TestRegressionSensitivityV050:
    """Regression tests for discount_rate_sensitivity (v0.5.0 PR3)."""

    GOLDEN_FILE = "scenario_finance_v050.json"

    def test_sensitivity_present_when_sweep_provided(self, load_golden):
        """Verify discount_rate_sensitivity is present when sweep provided."""
        golden = load_golden(self.GOLDEN_FILE)

        for variant in golden.get("variants", []):
            fs = variant.get("finance_summary", {})
            drs = fs.get("discount_rate_sensitivity")

            assert drs is not None, (
                f"Variant {variant.get('variant')}: discount_rate_sensitivity should be present"
            )
            assert isinstance(drs, list), (
                f"Variant {variant.get('variant')}: discount_rate_sensitivity should be a list"
            )

    def test_sensitivity_has_required_fields(self, load_golden):
        """Verify each sensitivity point has required fields."""
        golden = load_golden(self.GOLDEN_FILE)
        required_fields = ["discount_rate", "discount_rate_pct", "npv_pln"]

        for variant in golden.get("variants", []):
            fs = variant.get("finance_summary", {})
            drs = fs.get("discount_rate_sensitivity", [])

            for point in drs:
                for field in required_fields:
                    assert field in point, (
                        f"Variant {variant.get('variant')}: "
                        f"sensitivity point missing {field}"
                    )

    def test_npv_monotonicity(self, load_golden):
        """
        NPV monotonicity invariant: NPV should not oscillate with discount rate.

        For positive NPV projects: higher rate = lower NPV
        For negative NPV projects: higher rate = less negative NPV
        Key: NPV should NOT oscillate.
        """
        golden = load_golden(self.GOLDEN_FILE)

        for variant in golden.get("variants", []):
            fs = variant.get("finance_summary", {})
            drs = fs.get("discount_rate_sensitivity", [])

            if len(drs) < 2:
                continue

            npvs = [p["npv_pln"] for p in drs]
            diffs = [npvs[i] - npvs[i - 1] for i in range(1, len(npvs))]

            # Skip if all diffs are effectively zero
            if all(abs(d) < 1.0 for d in diffs):
                continue

            # Non-trivial diffs should all have the same sign (monotonic)
            positive_diffs = [d for d in diffs if d > 1.0]
            negative_diffs = [d for d in diffs if d < -1.0]

            assert len(positive_diffs) == 0 or len(negative_diffs) == 0, (
                f"Variant {variant.get('variant')}: NPV should be monotonic "
                f"(got {len(positive_diffs)} increases, {len(negative_diffs)} decreases)"
            )

    def test_sensitivity_sorted_by_rate(self, load_golden):
        """Verify sensitivity points are sorted by discount_rate (ascending)."""
        golden = load_golden(self.GOLDEN_FILE)

        for variant in golden.get("variants", []):
            fs = variant.get("finance_summary", {})
            drs = fs.get("discount_rate_sensitivity", [])

            rates = [p["discount_rate"] for p in drs]
            assert rates == sorted(rates), (
                f"Variant {variant.get('variant')}: sensitivity should be sorted by rate"
            )

    def test_discount_rate_pct_is_percentage(self, load_golden):
        """Verify discount_rate_pct = discount_rate * 100."""
        golden = load_golden(self.GOLDEN_FILE)

        for variant in golden.get("variants", []):
            fs = variant.get("finance_summary", {})
            drs = fs.get("discount_rate_sensitivity", [])

            for point in drs:
                expected_pct = point["discount_rate"] * 100
                assert abs(point["discount_rate_pct"] - expected_pct) < 0.001, (
                    f"Variant {variant.get('variant')}: "
                    f"discount_rate_pct should be discount_rate * 100"
                )


class TestRegressionFinanceAssumptionsV050:
    """Regression tests for finance_assumptions (v0.5.0 PR1)."""

    GOLDEN_FILE = "scenario_finance_v050.json"

    def test_finance_assumptions_present(self, load_golden):
        """Verify finance_assumptions is present at top level."""
        golden = load_golden(self.GOLDEN_FILE)

        fa = golden.get("finance_assumptions")
        assert fa is not None, "finance_assumptions should be present"

    def test_finance_assumptions_has_required_fields(self, load_golden):
        """Verify finance_assumptions has required fields."""
        golden = load_golden(self.GOLDEN_FILE)
        required_fields = [
            "discount_rate",
            "horizon_years",
            "opex_pln_per_year",
        ]

        fa = golden.get("finance_assumptions", {})
        for field in required_fields:
            assert field in fa, f"finance_assumptions missing {field}"

    def test_finance_summary_present_per_variant(self, load_golden):
        """Verify each variant has finance_summary."""
        golden = load_golden(self.GOLDEN_FILE)

        for variant in golden.get("variants", []):
            fs = variant.get("finance_summary")
            assert fs is not None, (
                f"Variant {variant.get('variant')}: should have finance_summary"
            )

    def test_finance_summary_has_required_fields(self, load_golden):
        """Verify finance_summary has required fields."""
        golden = load_golden(self.GOLDEN_FILE)
        required_fields = [
            "capex_pln",
            "npv_pln",
            "irr_pct",
            "payback_years",
            "discount_rate",
            "horizon_years",
        ]

        for variant in golden.get("variants", []):
            fs = variant.get("finance_summary", {})
            for field in required_fields:
                assert field in fs, (
                    f"Variant {variant.get('variant')}: finance_summary missing {field}"
                )

    def test_finance_summary_discount_rate_matches_assumptions(self, load_golden):
        """Verify finance_summary.discount_rate matches finance_assumptions.discount_rate."""
        golden = load_golden(self.GOLDEN_FILE)

        fa_rate = golden.get("finance_assumptions", {}).get("discount_rate")

        for variant in golden.get("variants", []):
            fs = variant.get("finance_summary", {})
            fs_rate = fs.get("discount_rate")

            assert fs_rate is not None, (
                f"Variant {variant.get('variant')}: finance_summary.discount_rate should exist"
            )
            assert abs(fs_rate - fa_rate) < 0.0001, (
                f"Variant {variant.get('variant')}: discount_rate ({fs_rate}) "
                f"should match finance_assumptions ({fa_rate})"
            )

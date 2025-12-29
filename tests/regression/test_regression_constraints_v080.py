"""
Regression tests for BESS sizing API v0.8.0 (Constraints + Pareto).

These tests verify that:
1. constraints_report is present when constraints_config provided
2. pareto_frontier has correct dominance logic
3. Per-variant is_feasible and constraint_violations are consistent

Scenarios:
- scenario_constraints_v080.json: With constraints_config (max_capex, max_payback)
"""
import pytest
import math


class TestRegressionConstraintsReportV080:
    """Regression tests for constraints_report (v0.8.0)."""

    GOLDEN_FILE = "scenario_constraints_v080.json"

    def test_constraints_report_present(self, load_golden):
        """Verify constraints_report is present when constraints_config used."""
        golden = load_golden(self.GOLDEN_FILE)
        assert "constraints_report" in golden
        assert golden["constraints_report"] is not None

    def test_constraints_report_has_required_fields(self, load_golden):
        """Verify constraints_report has required fields."""
        golden = load_golden(self.GOLDEN_FILE)
        report = golden.get("constraints_report", {})

        required_fields = [
            "applied",
            "feasible_count",
            "feasible_variants",
            "none_feasible"
        ]

        for field in required_fields:
            assert field in report, f"Missing field: {field}"

    def test_applied_is_true_when_constraints_provided(self, load_golden):
        """Verify applied=True when constraints_config was provided."""
        golden = load_golden(self.GOLDEN_FILE)
        report = golden.get("constraints_report", {})
        assert report.get("applied") is True

    def test_feasible_count_matches_feasible_variants_length(self, load_golden):
        """Verify feasible_count == len(feasible_variants)."""
        golden = load_golden(self.GOLDEN_FILE)
        report = golden.get("constraints_report", {})

        feasible_count = report.get("feasible_count", 0)
        feasible_variants = report.get("feasible_variants", [])

        assert feasible_count == len(feasible_variants), (
            f"feasible_count {feasible_count} != len(feasible_variants) {len(feasible_variants)}"
        )

    def test_none_feasible_consistency(self, load_golden):
        """Verify none_feasible == (feasible_count == 0)."""
        golden = load_golden(self.GOLDEN_FILE)
        report = golden.get("constraints_report", {})

        feasible_count = report.get("feasible_count", 0)
        none_feasible = report.get("none_feasible", False)

        assert none_feasible == (feasible_count == 0), (
            f"none_feasible {none_feasible} should be {feasible_count == 0}"
        )


class TestRegressionParetoFrontierV080:
    """Regression tests for pareto_frontier (v0.8.0)."""

    GOLDEN_FILE = "scenario_constraints_v080.json"

    def test_pareto_frontier_present(self, load_golden):
        """Verify pareto_frontier is present."""
        golden = load_golden(self.GOLDEN_FILE)
        assert "pareto_frontier" in golden
        assert golden["pareto_frontier"] is not None

    def test_pareto_frontier_has_all_variants(self, load_golden):
        """Verify pareto_frontier has same count as variants."""
        golden = load_golden(self.GOLDEN_FILE)
        variants = golden.get("variants", [])
        pareto = golden.get("pareto_frontier", [])

        assert len(pareto) == len(variants), (
            f"pareto_frontier has {len(pareto)} items, variants has {len(variants)}"
        )

    def test_pareto_point_has_required_fields(self, load_golden):
        """Verify each Pareto point has required fields."""
        golden = load_golden(self.GOLDEN_FILE)
        pareto = golden.get("pareto_frontier", [])

        required_fields = ["variant", "npv_pln", "payback_years", "is_dominated"]

        for point in pareto:
            for field in required_fields:
                assert field in point, f"Missing field: {field} in Pareto point"

    def test_pareto_npv_matches_variant_npv(self, load_golden):
        """Verify Pareto point NPV matches variant NPV."""
        golden = load_golden(self.GOLDEN_FILE)
        variants = golden.get("variants", [])
        pareto = golden.get("pareto_frontier", [])

        variant_npvs = {v["variant"]: v["npv_pln"] for v in variants}

        for point in pareto:
            variant_name = point["variant"]
            pareto_npv = point["npv_pln"]
            variant_npv = variant_npvs.get(variant_name)

            assert variant_npv is not None, f"Variant {variant_name} not found"
            assert math.isclose(pareto_npv, variant_npv, rel_tol=1e-9), (
                f"Pareto NPV {pareto_npv} != Variant NPV {variant_npv}"
            )

    def test_pareto_payback_matches_variant_payback(self, load_golden):
        """Verify Pareto point payback matches variant payback."""
        golden = load_golden(self.GOLDEN_FILE)
        variants = golden.get("variants", [])
        pareto = golden.get("pareto_frontier", [])

        variant_paybacks = {v["variant"]: v["simple_payback_years"] for v in variants}

        for point in pareto:
            variant_name = point["variant"]
            pareto_payback = point["payback_years"]
            variant_payback = variant_paybacks.get(variant_name)

            assert variant_payback is not None, f"Variant {variant_name} not found"
            assert math.isclose(pareto_payback, variant_payback, rel_tol=1e-9), (
                f"Pareto payback {pareto_payback} != Variant payback {variant_payback}"
            )

    def test_pareto_dominance_is_transitive(self, load_golden):
        """
        Verify Pareto dominance is transitive.

        If A dominates B and B dominates C, then A must dominate C.
        (Logically: dominated points cannot dominate other points.)
        """
        golden = load_golden(self.GOLDEN_FILE)
        pareto = golden.get("pareto_frontier", [])

        # Get non-dominated (frontier) points
        frontier_points = [p for p in pareto if not p["is_dominated"]]
        dominated_points = [p for p in pareto if p["is_dominated"]]

        # Dominated points should never dominate frontier points
        for dom in dominated_points:
            for front in frontier_points:
                # dom dominates front if dom.npv > front.npv AND dom.payback < front.payback
                dom_dominates_front = (
                    dom["npv_pln"] > front["npv_pln"] and
                    dom["payback_years"] < front["payback_years"]
                )
                assert not dom_dominates_front, (
                    f"Dominated {dom['variant']} should not dominate frontier {front['variant']}"
                )


class TestRegressionParetoDominanceLogicV080:
    """Regression tests for Pareto dominance logic (v0.8.0)."""

    GOLDEN_FILE = "scenario_constraints_v080.json"

    def test_dominated_means_strictly_worse(self, load_golden):
        """
        Verify dominated point is strictly worse than some frontier point.

        A is dominated if there exists B such that:
        - B.npv >= A.npv (B at least as good on NPV)
        - B.payback <= A.payback (B at least as good on payback)
        - At least one is strictly better
        """
        golden = load_golden(self.GOLDEN_FILE)
        pareto = golden.get("pareto_frontier", [])

        dominated_points = [p for p in pareto if p["is_dominated"]]
        frontier_points = [p for p in pareto if not p["is_dominated"]]

        for dom in dominated_points:
            # Check that some frontier point dominates this one
            is_dominated_by_frontier = False

            for front in frontier_points:
                npv_at_least = front["npv_pln"] >= dom["npv_pln"]
                payback_at_least = front["payback_years"] <= dom["payback_years"]
                strictly_better = (
                    front["npv_pln"] > dom["npv_pln"] or
                    front["payback_years"] < dom["payback_years"]
                )

                if npv_at_least and payback_at_least and strictly_better:
                    is_dominated_by_frontier = True
                    break

            assert is_dominated_by_frontier, (
                f"Dominated point {dom['variant']} is not dominated by any frontier point"
            )

    def test_frontier_points_are_pareto_optimal(self, load_golden):
        """
        Verify frontier (non-dominated) points are truly Pareto optimal.

        No other point should dominate a frontier point.
        """
        golden = load_golden(self.GOLDEN_FILE)
        pareto = golden.get("pareto_frontier", [])

        frontier_points = [p for p in pareto if not p["is_dominated"]]

        for front in frontier_points:
            for other in pareto:
                if other["variant"] == front["variant"]:
                    continue

                # Check if other dominates front
                other_dominates_front = (
                    other["npv_pln"] > front["npv_pln"] and
                    other["payback_years"] < front["payback_years"]
                )

                assert not other_dominates_front, (
                    f"Frontier {front['variant']} is dominated by {other['variant']}"
                )


class TestRegressionConstraintsAcrossScenarios:
    """Test constraints_report presence across different scenarios."""

    def test_no_constraints_report_when_not_provided(self, load_golden):
        """Verify constraints_report not present without constraints_config."""
        # scenario1 was created without constraints_config
        try:
            golden = load_golden("scenario1_no_arb.json")
            report = golden.get("constraints_report")
            # Old golden files may not have constraints_report at all
            # or have it as None/null - both are acceptable
            if report is not None:
                assert report.get("applied") is False or report.get("applied") is None
        except FileNotFoundError:
            pytest.skip("scenario1_no_arb.json not found")

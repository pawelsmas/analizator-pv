"""
Contract tests for v0.8.0 Pareto frontier (PR 2/6).

These tests verify:
1. pareto_frontier is present in response
2. Each point has required fields (variant, npv_pln, payback_years, is_dominated)
3. Pareto dominance logic is correct
4. Non-dominated points form the Pareto frontier

Run with: python -m pytest tests/contract/test_pareto_frontier_contract.py -v
"""

from ._api import post_json, load_smoke_payload


class TestParetoFrontierPresence:
    """Test that pareto_frontier is present in sizing response."""

    def test_pareto_frontier_present_in_response(self):
        """pareto_frontier should be present in sizing response."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [1.0, 2.0]  # Two variants
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        resp = post_json("/sizing", p)

        assert "pareto_frontier" in resp, "pareto_frontier should be in response"
        assert resp["pareto_frontier"] is not None, "pareto_frontier should not be None"

    def test_pareto_frontier_length_matches_variants(self):
        """pareto_frontier should have one point per variant."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [1.0, 2.0, 4.0]  # Three variants
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        resp = post_json("/sizing", p)
        pf = resp.get("pareto_frontier", [])
        variants = resp.get("variants", [])

        assert len(pf) == len(variants), (
            f"pareto_frontier should have {len(variants)} points, got {len(pf)}"
        )


class TestParetoPointStructure:
    """Test the structure of each Pareto point."""

    def test_pareto_point_has_required_fields(self):
        """Each Pareto point should have variant, npv_pln, payback_years, is_dominated."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        resp = post_json("/sizing", p)
        pf = resp.get("pareto_frontier", [])

        assert len(pf) > 0, "pareto_frontier should have at least one point"

        required_fields = ["variant", "npv_pln", "payback_years", "is_dominated"]
        for pt in pf:
            for field in required_fields:
                assert field in pt, f"Pareto point should have '{field}' field"

    def test_pareto_point_npv_is_numeric(self):
        """npv_pln should be a number."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        resp = post_json("/sizing", p)
        pf = resp.get("pareto_frontier", [])

        for pt in pf:
            assert isinstance(pt["npv_pln"], (int, float)), "npv_pln should be numeric"

    def test_pareto_point_payback_is_numeric(self):
        """payback_years should be a number."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        resp = post_json("/sizing", p)
        pf = resp.get("pareto_frontier", [])

        for pt in pf:
            assert isinstance(pt["payback_years"], (int, float)), "payback_years should be numeric"

    def test_pareto_point_is_dominated_is_bool(self):
        """is_dominated should be a boolean."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        resp = post_json("/sizing", p)
        pf = resp.get("pareto_frontier", [])

        for pt in pf:
            assert isinstance(pt["is_dominated"], bool), "is_dominated should be bool"


class TestParetoDominance:
    """Test the Pareto dominance logic."""

    def test_dominance_correctly_computed(self):
        """
        A point is dominated if another point has BOTH:
        - Higher NPV AND lower payback

        This test verifies the dominance computation is correct.
        """
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [1.0, 2.0, 4.0]  # Three variants for better test
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        resp = post_json("/sizing", p)
        pf = resp.get("pareto_frontier", [])

        # Verify dominance logic for each point
        for pt in pf:
            if pt["is_dominated"]:
                # There must be at least one point that dominates this one
                is_actually_dominated = False
                for other in pf:
                    if other["variant"] == pt["variant"]:
                        continue
                    # other dominates pt if: higher NPV AND lower payback
                    if other["npv_pln"] > pt["npv_pln"] and other["payback_years"] < pt["payback_years"]:
                        is_actually_dominated = True
                        break
                assert is_actually_dominated, (
                    f"Variant {pt['variant']} marked as dominated but no dominating point found"
                )

    def test_non_dominated_points_form_frontier(self):
        """Non-dominated points should form the Pareto frontier."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [1.0, 2.0, 4.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        resp = post_json("/sizing", p)
        pf = resp.get("pareto_frontier", [])

        # Get non-dominated points
        frontier_points = [pt for pt in pf if not pt["is_dominated"]]

        # Verify no frontier point is dominated by another frontier point
        for pt in frontier_points:
            for other in frontier_points:
                if other["variant"] == pt["variant"]:
                    continue
                # other should NOT dominate pt (both in frontier)
                dominates = (
                    other["npv_pln"] > pt["npv_pln"] and
                    other["payback_years"] < pt["payback_years"]
                )
                assert not dominates, (
                    f"Frontier point {pt['variant']} is dominated by {other['variant']}"
                )

    def test_at_least_one_non_dominated_point(self):
        """There should be at least one non-dominated point."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [1.0, 2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        resp = post_json("/sizing", p)
        pf = resp.get("pareto_frontier", [])

        frontier_count = sum(1 for pt in pf if not pt["is_dominated"])
        assert frontier_count >= 1, "At least one point should be on the Pareto frontier"


class TestParetoConsistency:
    """Test consistency between pareto_frontier and variants."""

    def test_pareto_variants_match_response_variants(self):
        """pareto_frontier variants should match response variants."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [1.0, 2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        resp = post_json("/sizing", p)
        pf = resp.get("pareto_frontier", [])
        variants = resp.get("variants", [])

        pf_variants = set(pt["variant"] for pt in pf)
        variant_names = set(v["variant"] for v in variants)

        assert pf_variants == variant_names, (
            f"Pareto variants {pf_variants} should match response variants {variant_names}"
        )

    def test_pareto_npv_matches_variant_npv(self):
        """pareto_frontier npv_pln should match variant npv_pln."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        resp = post_json("/sizing", p)
        pf = resp.get("pareto_frontier", [])
        variants = resp.get("variants", [])

        for pt in pf:
            # Find matching variant
            matching = [v for v in variants if v["variant"] == pt["variant"]]
            assert len(matching) == 1, f"Should find exactly one variant for {pt['variant']}"
            v = matching[0]

            assert abs(pt["npv_pln"] - v["npv_pln"]) < 1.0, (
                f"Pareto npv_pln ({pt['npv_pln']}) should match variant npv_pln ({v['npv_pln']})"
            )

    def test_pareto_payback_matches_variant_payback(self):
        """pareto_frontier payback_years should match variant simple_payback_years."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        resp = post_json("/sizing", p)
        pf = resp.get("pareto_frontier", [])
        variants = resp.get("variants", [])

        for pt in pf:
            # Find matching variant
            matching = [v for v in variants if v["variant"] == pt["variant"]]
            assert len(matching) == 1
            v = matching[0]

            # Allow small tolerance for floating point
            assert abs(pt["payback_years"] - v["simple_payback_years"]) < 0.01, (
                f"Pareto payback ({pt['payback_years']}) should match variant payback ({v['simple_payback_years']})"
            )

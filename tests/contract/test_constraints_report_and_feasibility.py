"""
Contract tests for v0.8.0 constraints_report and feasibility (PR 1/6).

These tests verify:
1. constraints_report is present in response when constraints_config is provided
2. Per-variant feasibility is calculated correctly
3. Recommended variant selection respects feasibility constraints
4. Fallback behavior when no variants are feasible

Run with: python -m pytest tests/contract/test_constraints_report_and_feasibility.py -v
"""

from ._api import post_json, load_smoke_payload


class TestConstraintsReportPresence:
    """Test that constraints_report is present in response."""

    def test_constraints_report_present_when_config_provided(self):
        """constraints_report should be present when constraints_config is provided."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        # Add constraints_config
        p["constraints_config"] = {
            "max_capex_pln": 500000.0,
        }

        resp = post_json("/sizing", p)

        assert "constraints_report" in resp, "constraints_report should be in response"
        cr = resp["constraints_report"]
        assert cr is not None, "constraints_report should not be None"

    def test_constraints_report_has_required_fields(self):
        """constraints_report should have all required fields."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        p["constraints_config"] = {
            "max_capex_pln": 500000.0,
        }

        resp = post_json("/sizing", p)
        cr = resp.get("constraints_report", {})

        required_fields = ["applied", "feasible_count", "feasible_variants", "none_feasible"]
        for field in required_fields:
            assert field in cr, f"constraints_report should have '{field}' field"

    def test_applied_is_true_when_config_provided(self):
        """applied should be True when constraints_config is provided."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        p["constraints_config"] = {
            "max_capex_pln": 500000.0,
        }

        resp = post_json("/sizing", p)
        cr = resp.get("constraints_report", {})

        assert cr.get("applied") is True, "applied should be True when config provided"

    def test_applied_is_false_without_config(self):
        """applied should be False when constraints_config is not provided."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        # No constraints_config
        p.pop("constraints_config", None)

        resp = post_json("/sizing", p)
        cr = resp.get("constraints_report", {})

        assert cr.get("applied") is False, "applied should be False without config"


class TestFeasibilityPresence:
    """Test that feasibility is present per variant."""

    def test_feasibility_present_per_variant(self):
        """Each variant should have feasibility field."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        p["constraints_config"] = {
            "max_capex_pln": 500000.0,
        }

        resp = post_json("/sizing", p)
        variants = resp.get("variants", [])

        assert len(variants) > 0, "Should have at least one variant"
        for v in variants:
            assert "feasibility" in v, f"Variant {v.get('variant')} should have feasibility"
            feas = v["feasibility"]
            assert "is_feasible" in feas, "feasibility should have is_feasible"
            assert "violations" in feas, "feasibility should have violations"

    def test_feasibility_has_correct_structure(self):
        """Feasibility should have is_feasible (bool) and violations (list)."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        p["constraints_config"] = {
            "max_capex_pln": 500000.0,
        }

        resp = post_json("/sizing", p)
        variants = resp.get("variants", [])

        for v in variants:
            feas = v.get("feasibility", {})
            assert isinstance(feas.get("is_feasible"), bool), "is_feasible should be bool"
            assert isinstance(feas.get("violations"), list), "violations should be list"


class TestFeasibilityViolations:
    """Test that violations are correctly reported."""

    def test_max_capex_violation_reported(self):
        """MAX_CAPEX violation should be reported when exceeded."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        # Very low CAPEX limit to trigger violation
        p["constraints_config"] = {
            "max_capex_pln": 1000.0,  # Very low - should violate
        }

        resp = post_json("/sizing", p)
        variants = resp.get("variants", [])

        # At least one variant should have MAX_CAPEX violation
        has_violation = False
        for v in variants:
            feas = v.get("feasibility", {})
            for violation in feas.get("violations", []):
                if violation.get("code") == "MAX_CAPEX":
                    has_violation = True
                    assert violation.get("unit") == "PLN"
                    assert violation.get("limit") == 1000.0
                    assert violation.get("actual") > 1000.0

        assert has_violation, "At least one variant should have MAX_CAPEX violation"

    def test_min_npv_violation_reported(self):
        """MIN_NPV violation should be reported when NPV is below threshold."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        # Very high NPV requirement to trigger violation
        p["constraints_config"] = {
            "min_npv_pln": 999999999.0,  # Very high - should violate
        }

        resp = post_json("/sizing", p)
        variants = resp.get("variants", [])

        # At least one variant should have MIN_NPV violation
        has_violation = False
        for v in variants:
            feas = v.get("feasibility", {})
            for violation in feas.get("violations", []):
                if violation.get("code") == "MIN_NPV":
                    has_violation = True
                    assert violation.get("unit") == "PLN"
                    assert violation.get("limit") == 999999999.0

        assert has_violation, "At least one variant should have MIN_NPV violation"

    def test_violation_has_required_fields(self):
        """Each violation should have code, limit, actual, unit, message."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        # Low CAPEX limit to trigger violation
        p["constraints_config"] = {
            "max_capex_pln": 1000.0,
        }

        resp = post_json("/sizing", p)
        variants = resp.get("variants", [])

        for v in variants:
            feas = v.get("feasibility", {})
            for violation in feas.get("violations", []):
                assert "code" in violation, "violation should have code"
                assert "limit" in violation, "violation should have limit"
                assert "actual" in violation, "violation should have actual"
                assert "unit" in violation, "violation should have unit"
                assert "message" in violation, "violation should have message"


class TestFeasibleVariantsCount:
    """Test that feasible_count and feasible_variants are correct."""

    def test_feasible_count_matches_feasible_variants_length(self):
        """feasible_count should equal len(feasible_variants)."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        p["constraints_config"] = {
            "max_capex_pln": 500000.0,
        }

        resp = post_json("/sizing", p)
        cr = resp.get("constraints_report", {})

        assert cr.get("feasible_count") == len(cr.get("feasible_variants", [])), (
            "feasible_count should match feasible_variants length"
        )

    def test_all_variants_feasible_with_loose_constraints(self):
        """All variants should be feasible with very loose constraints."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [1.0, 2.0]  # Two variants
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        # Very loose constraints - only constrain CAPEX which is always finite
        # Don't constrain payback as it can be very high with low savings data
        p["constraints_config"] = {
            "max_capex_pln": 999999999.0,
        }

        resp = post_json("/sizing", p)
        cr = resp.get("constraints_report", {})
        variants = resp.get("variants", [])

        assert cr.get("feasible_count") == len(variants), "All variants should be feasible"
        assert cr.get("none_feasible") is False, "none_feasible should be False"


class TestNoneFeasibleFallback:
    """Test fallback behavior when no variants are feasible."""

    def test_none_feasible_is_true_when_all_violate(self):
        """none_feasible should be True when all variants violate constraints."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        # Impossible constraints
        p["constraints_config"] = {
            "max_capex_pln": 1.0,  # Impossible
        }

        resp = post_json("/sizing", p)
        cr = resp.get("constraints_report", {})

        assert cr.get("none_feasible") is True, "none_feasible should be True"
        assert cr.get("feasible_count") == 0, "feasible_count should be 0"
        assert len(cr.get("feasible_variants", [])) == 0, "feasible_variants should be empty"

    def test_recommended_is_fallback_when_none_feasible(self):
        """When none_feasible, recommended should still be set (fallback)."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        # Impossible constraints
        p["constraints_config"] = {
            "max_capex_pln": 1.0,
        }

        resp = post_json("/sizing", p)
        cr = resp.get("constraints_report", {})

        assert cr.get("none_feasible") is True
        # Recommended should still be set as fallback
        assert resp.get("recommended_variant") is not None, (
            "recommended_variant should be set even in fallback"
        )

    def test_reason_code_is_fallback_when_none_feasible(self):
        """When none_feasible, recommended_reason_code should indicate fallback."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        # Impossible constraints
        p["constraints_config"] = {
            "max_capex_pln": 1.0,
        }

        resp = post_json("/sizing", p)
        cr = resp.get("constraints_report", {})

        if cr.get("none_feasible"):
            assert resp.get("recommended_reason_code") == "constrained_fallback", (
                "reason_code should be 'constrained_fallback' when none feasible"
            )


class TestRecommendedFromFeasibleSet:
    """Test that recommended is selected from feasible variants."""

    def test_recommended_is_feasible_when_some_feasible(self):
        """Recommended variant should be feasible when some variants are feasible."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        # Loose constraints - all should pass
        p["constraints_config"] = {
            "max_capex_pln": 999999999.0,
        }

        resp = post_json("/sizing", p)
        cr = resp.get("constraints_report", {})
        variants = resp.get("variants", [])

        if not cr.get("none_feasible"):
            # Find recommended variant
            recommended_name = resp.get("recommended_variant")
            for v in variants:
                if v.get("variant") == recommended_name:
                    feas = v.get("feasibility", {})
                    assert feas.get("is_feasible") is True, (
                        "Recommended variant should be feasible"
                    )
                    break

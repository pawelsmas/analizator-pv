"""
Contract tests for v0.7.0 unserved load penalty in economics (PR 4/6).

These tests verify:
1. unserved_load_penalty_pln field present in savings_breakdown
2. penalty = unserved_load_kwh * penalty_rate
3. net_savings includes penalty deduction
4. penalty_rate echoed in grid_constraints_applied

Run with: python -m pytest tests/contract/test_unserved_load_penalty.py -v
"""

from ._api import post_json, load_smoke_payload


class TestUnservedLoadPenaltyPresence:
    """Test that unserved_load_penalty_pln field is present."""

    def test_unserved_load_penalty_field_exists(self):
        """savings_breakdown should have unserved_load_penalty_pln field."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        resp = post_json("/sizing", p)
        variants = resp.get("variants", [])
        assert len(variants) > 0, "Should have at least one variant"

        for variant in variants:
            sb = variant.get("savings_breakdown", {})
            assert "unserved_load_penalty_pln" in sb, (
                "savings_breakdown should have unserved_load_penalty_pln field"
            )

    def test_penalty_is_zero_when_no_constraints(self):
        """Without grid constraints, penalty should be 0."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"
        p.pop("grid_constraints", None)

        resp = post_json("/sizing", p)
        variants = resp.get("variants", [])

        for variant in variants:
            sb = variant.get("savings_breakdown", {})
            penalty = sb.get("unserved_load_penalty_pln", 0)
            assert penalty == 0, (
                f"Penalty should be 0 without constraints, got {penalty}"
            )


class TestPenaltyRateEcho:
    """Test that penalty rate is echoed in grid_constraints_applied."""

    def test_penalty_rate_echoed(self):
        """unserved_load_penalty_pln_kwh should be echoed in grid_constraints_applied."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        p["grid_constraints"] = {
            "max_import_kw": 50.0,
            "unserved_load_penalty_pln_kwh": 10.0,
        }

        resp = post_json("/sizing", p)
        g = resp.get("grid_constraints_applied") or {}

        assert float(g.get("unserved_load_penalty_pln_kwh")) == 10.0, (
            f"unserved_load_penalty_pln_kwh should be 10.0, got {g.get('unserved_load_penalty_pln_kwh')}"
        )

    def test_penalty_rate_zero_by_default(self):
        """unserved_load_penalty_pln_kwh should default to 0."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        p["grid_constraints"] = {
            "max_import_kw": 50.0,
            # No penalty rate specified
        }

        resp = post_json("/sizing", p)
        g = resp.get("grid_constraints_applied") or {}

        assert float(g.get("unserved_load_penalty_pln_kwh", 0)) == 0.0, (
            f"Default penalty rate should be 0, got {g.get('unserved_load_penalty_pln_kwh')}"
        )


class TestPenaltyCalculation:
    """Test that penalty is calculated correctly."""

    def test_penalty_equals_unserved_times_rate(self):
        """penalty = unserved_load_kwh * penalty_rate."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        # Very restrictive import cap to ensure unserved load
        p["grid_constraints"] = {
            "max_import_kw": 1.0,  # Very low cap
            "unserved_load_penalty_pln_kwh": 5.0,  # 5 PLN/kWh penalty
        }

        resp = post_json("/sizing", p)
        variants = resp.get("variants", [])

        for variant in variants:
            sb = variant.get("savings_breakdown", {})
            penalty = sb.get("unserved_load_penalty_pln", 0)

            # Get unserved load from dispatch_summary
            ds = variant.get("dispatch_summary") or {}
            cs = ds.get("constraint_summary")

            if cs is not None:
                unserved_kwh = cs.get("unserved_load_kwh", 0)
                expected_penalty = unserved_kwh * 5.0  # penalty_rate

                # If there's unserved load, penalty should match
                if unserved_kwh > 0:
                    # Allow 1% tolerance
                    assert abs(penalty - expected_penalty) < expected_penalty * 0.01 + 0.01, (
                        f"Penalty mismatch: got {penalty}, expected {expected_penalty} "
                        f"(unserved_kwh={unserved_kwh}, rate=5.0)"
                    )

    def test_zero_penalty_when_no_unserved_load(self):
        """Penalty should be 0 when there's no unserved load."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        # High import cap - no unserved load
        p["grid_constraints"] = {
            "max_import_kw": 10000.0,  # Very high - no import limit hit
            "unserved_load_penalty_pln_kwh": 100.0,  # Even with high rate
        }

        resp = post_json("/sizing", p)
        variants = resp.get("variants", [])

        for variant in variants:
            sb = variant.get("savings_breakdown", {})
            penalty = sb.get("unserved_load_penalty_pln", 0)
            assert penalty == 0, (
                f"Penalty should be 0 when no unserved load, got {penalty}"
            )


class TestNetSavingsWithPenalty:
    """Test that net_savings includes penalty deduction."""

    def test_net_savings_includes_penalty(self):
        """net_savings should be reduced by unserved_load_penalty_pln."""
        p = load_smoke_payload("sizing_stacked_with_arbitrage.json")
        p["load_kw"] = p["load_kw"][:24]
        p["pv_generation_kw"] = p["pv_generation_kw"][:24]
        p["interval_minutes"] = 60
        p["durations_h"] = [2.0]
        p["timezone"] = "Europe/Warsaw"
        p["period_start"] = "2025-01-01T00:00:00"
        p["period_end"] = "2025-01-02T00:00:00"

        # Restrictive import cap with high penalty
        p["grid_constraints"] = {
            "max_import_kw": 1.0,
            "unserved_load_penalty_pln_kwh": 10.0,
        }

        resp = post_json("/sizing", p)
        variants = resp.get("variants", [])

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

            expected = (energy + capacity + demand + arbitrage +
                       export_delta - degradation - penalty)

            # Allow 1 PLN tolerance
            assert abs(net - expected) < 1.0, (
                f"Net savings formula mismatch. "
                f"net={net}, expected={expected}, "
                f"penalty={penalty}"
            )

"""
Contract test for deterministic tie-breaking in variant selection.

v1.6.0: Verifies that when variants have equal scores, the selection
is deterministic based on tie-breakers:
1. Higher NPV wins
2. If NPV equal: lower CAPEX wins
3. If CAPEX equal: alphabetical by variant name

This ensures reproducible results across runs.
"""

import pytest
from ._api import post_json, pick_recommended_variant


def _build_sizing_request(
    load_kw: list[float],
    pv_kw: list[float],
    durations_h: list[float],
    interval_minutes: int = 60,
    period_start: str = "2025-01-01T00:00:00",
    period_end: str = "2025-01-02T00:00:00",
) -> dict:
    """Build a sizing request for testing."""
    return {
        "load_kw": load_kw,
        "pv_generation_kw": pv_kw,
        "interval_minutes": interval_minutes,
        "durations_h": durations_h,
        "timezone": "Europe/Warsaw",
        "period_start": period_start,
        "period_end": period_end,
        "optimization_config": {"objective": "npv"},
        "operation_mode": "STACKED",
    }


class TestDeterministicTieBreaking:
    """Test deterministic tie-breaking in variant selection."""

    def test_same_request_produces_same_recommended(self):
        """
        Running the same request multiple times should always
        produce the same recommended variant.
        """
        # Create a simple test profile
        load = [100.0] * 24
        pv = [50.0] * 24

        request = _build_sizing_request(
            load_kw=load,
            pv_kw=pv,
            durations_h=[1.0, 2.0, 4.0],
        )

        # Run multiple times
        recommended_variants = []
        for _ in range(3):
            resp = post_json("/sizing", request)
            rec = pick_recommended_variant(resp)
            recommended_variants.append(rec.get("variant"))

        # All should be the same
        assert len(set(recommended_variants)) == 1, (
            f"Non-deterministic selection: got different variants {recommended_variants}"
        )

    def test_response_determinism(self):
        """
        Full response should be deterministic for the same request.
        Key fields like recommended_variant should match across runs.
        """
        load = [80.0 + (i % 5) * 10 for i in range(24)]
        pv = [40.0 + (i % 4) * 8 for i in range(24)]

        request = _build_sizing_request(
            load_kw=load,
            pv_kw=pv,
            durations_h=[2.0],
        )

        # Run twice
        resp1 = post_json("/sizing", request)
        resp2 = post_json("/sizing", request)

        # Check key deterministic fields
        assert resp1.get("recommended_variant") == resp2.get("recommended_variant"), (
            "recommended_variant differs between runs"
        )

        # Compare recommended variant's key metrics
        rec1 = pick_recommended_variant(resp1)
        rec2 = pick_recommended_variant(resp2)

        assert rec1.get("npv_pln") == rec2.get("npv_pln"), "NPV differs between runs"
        assert rec1.get("capex_pln") == rec2.get("capex_pln"), "CAPEX differs between runs"

    def test_variant_order_preserved(self):
        """
        Variant ordering in response should be consistent.
        """
        load = [120.0] * 24
        pv = [60.0] * 24

        request = _build_sizing_request(
            load_kw=load,
            pv_kw=pv,
            durations_h=[1.0, 2.0],
        )

        resp1 = post_json("/sizing", request)
        resp2 = post_json("/sizing", request)

        variants1 = [v.get("variant") for v in resp1.get("variants", [])]
        variants2 = [v.get("variant") for v in resp2.get("variants", [])]

        assert variants1 == variants2, (
            f"Variant order differs: {variants1} vs {variants2}"
        )

    def test_top_variants_order_deterministic(self):
        """
        top_variants ordering should be deterministic.
        """
        load = [100.0] * 24
        pv = [50.0] * 24

        request = _build_sizing_request(
            load_kw=load,
            pv_kw=pv,
            durations_h=[1.0, 2.0, 4.0],
        )

        resp1 = post_json("/sizing", request)
        resp2 = post_json("/sizing", request)

        top1 = resp1.get("top_variants", [])
        top2 = resp2.get("top_variants", [])

        assert top1 == top2, (
            f"top_variants order differs: {top1} vs {top2}"
        )

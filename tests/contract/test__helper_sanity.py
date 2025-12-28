"""
Sanity tests for contract test helpers.

These tests verify that the helper functions work correctly
and can load smoke payloads from the repository.
"""
from tests.contract._api import load_smoke_payload, pick_recommended_variant


def test_load_smoke_payload_exists():
    """Verify smoke payload can be loaded."""
    payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
    assert isinstance(payload, dict)
    assert "load_kw" in payload
    assert "pv_generation_kw" in payload
    assert "mode" in payload


def test_load_smoke_payload_with_arbitrage():
    """Verify arbitrage smoke payload can be loaded."""
    payload = load_smoke_payload("sizing_stacked_with_arbitrage.json")
    assert isinstance(payload, dict)
    assert "load_kw" in payload


def test_pick_recommended_variant_returns_recommended():
    """Verify pick_recommended_variant finds the is_recommended variant."""
    mock_response = {
        "variants": [
            {"power_kw": 100, "is_recommended": False},
            {"power_kw": 200, "is_recommended": True},
            {"power_kw": 300, "is_recommended": False},
        ]
    }
    rec = pick_recommended_variant(mock_response)
    assert rec["power_kw"] == 200


def test_pick_recommended_variant_returns_first_if_none_recommended():
    """Verify pick_recommended_variant returns first if none marked."""
    mock_response = {
        "variants": [
            {"power_kw": 100},
            {"power_kw": 200},
        ]
    }
    rec = pick_recommended_variant(mock_response)
    assert rec["power_kw"] == 100

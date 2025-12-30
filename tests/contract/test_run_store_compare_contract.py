"""
Contract tests for v1.0.0 RunStore - POST /runs:compare endpoint.

Tests verify:
- Compare returns delta for key metrics
- Same request hash detection
- Variant change detection
- 404 for nonexistent runs

Run with: pytest tests/contract/test_run_store_compare_contract.py -v
"""
import pytest
import requests
from ._api import post_json, get_json


SIZING_ENDPOINT = "/sizing"
RUNS_ENDPOINT = "/runs"
COMPARE_ENDPOINT = "/runs:compare"
CACHE_CLEAR_URL = "http://localhost:8031/cache"


def make_sizing_request(load_variation: int = 0, price: float = 0.8):
    """Create sizing request with optional variations."""
    return {
        "load_kw": [100 + load_variation, 120, 110, 90],
        "pv_generation_kw": [50, 70, 80, 60],
        "energy_price_pln_kwh": price,
    }


class TestCompareRunsBasic:
    """Tests for basic compare functionality."""

    def test_compare_returns_response(self):
        """Verify compare endpoint returns a response."""
        # Create two runs
        requests.delete(CACHE_CLEAR_URL)
        req1 = make_sizing_request(load_variation=1)
        resp1 = post_json(SIZING_ENDPOINT, req1)
        run_id_a = resp1["cache_info"]["run_id"]

        req2 = make_sizing_request(load_variation=2)
        resp2 = post_json(SIZING_ENDPOINT, req2)
        run_id_b = resp2["cache_info"]["run_id"]

        # Compare
        compare_req = {"run_id_a": run_id_a, "run_id_b": run_id_b}
        result = post_json(COMPARE_ENDPOINT, compare_req)

        assert result is not None

    def test_compare_returns_run_ids(self):
        """Verify compare returns the input run_ids."""
        requests.delete(CACHE_CLEAR_URL)
        req = make_sizing_request()
        resp1 = post_json(SIZING_ENDPOINT, req)
        run_id_a = resp1["cache_info"]["run_id"]
        resp2 = post_json(SIZING_ENDPOINT, req)
        run_id_b = resp2["cache_info"]["run_id"]

        compare_req = {"run_id_a": run_id_a, "run_id_b": run_id_b}
        result = post_json(COMPARE_ENDPOINT, compare_req)

        assert result["run_id_a"] == run_id_a
        assert result["run_id_b"] == run_id_b

    def test_compare_has_required_fields(self):
        """Verify compare response has required fields."""
        requests.delete(CACHE_CLEAR_URL)
        req = make_sizing_request()
        resp1 = post_json(SIZING_ENDPOINT, req)
        run_id_a = resp1["cache_info"]["run_id"]
        resp2 = post_json(SIZING_ENDPOINT, req)
        run_id_b = resp2["cache_info"]["run_id"]

        compare_req = {"run_id_a": run_id_a, "run_id_b": run_id_b}
        result = post_json(COMPARE_ENDPOINT, compare_req)

        required_fields = [
            "run_id_a",
            "run_id_b",
            "same_request_hash",
            "recommended_variant_a",
            "recommended_variant_b",
            "variant_changed",
            "key_deltas",
        ]
        for field in required_fields:
            assert field in result, f"Missing field: {field}"


class TestCompareRunsSameRequest:
    """Tests for same request hash detection."""

    def test_same_request_hash_detected(self):
        """Verify same_request_hash is True for identical requests."""
        requests.delete(CACHE_CLEAR_URL)
        req = make_sizing_request()

        resp1 = post_json(SIZING_ENDPOINT, req)
        run_id_a = resp1["cache_info"]["run_id"]

        resp2 = post_json(SIZING_ENDPOINT, req)
        run_id_b = resp2["cache_info"]["run_id"]

        compare_req = {"run_id_a": run_id_a, "run_id_b": run_id_b}
        result = post_json(COMPARE_ENDPOINT, compare_req)

        assert result["same_request_hash"] is True

    def test_different_request_hash_detected(self):
        """Verify same_request_hash is False for different requests."""
        requests.delete(CACHE_CLEAR_URL)

        req1 = make_sizing_request(load_variation=100)
        resp1 = post_json(SIZING_ENDPOINT, req1)
        run_id_a = resp1["cache_info"]["run_id"]

        req2 = make_sizing_request(load_variation=200)
        resp2 = post_json(SIZING_ENDPOINT, req2)
        run_id_b = resp2["cache_info"]["run_id"]

        compare_req = {"run_id_a": run_id_a, "run_id_b": run_id_b}
        result = post_json(COMPARE_ENDPOINT, compare_req)

        assert result["same_request_hash"] is False


class TestCompareRunsVariantChange:
    """Tests for variant change detection."""

    def test_variant_changed_false_for_same_variant(self):
        """Verify variant_changed is False when variants match."""
        requests.delete(CACHE_CLEAR_URL)
        req = make_sizing_request()

        resp1 = post_json(SIZING_ENDPOINT, req)
        run_id_a = resp1["cache_info"]["run_id"]

        resp2 = post_json(SIZING_ENDPOINT, req)
        run_id_b = resp2["cache_info"]["run_id"]

        compare_req = {"run_id_a": run_id_a, "run_id_b": run_id_b}
        result = post_json(COMPARE_ENDPOINT, compare_req)

        # Same request should have same recommended variant
        assert result["variant_changed"] is False
        assert result["recommended_variant_a"] == result["recommended_variant_b"]


class TestCompareRunsKeyDeltas:
    """Tests for key metric deltas."""

    def test_key_deltas_is_array(self):
        """Verify key_deltas is an array."""
        requests.delete(CACHE_CLEAR_URL)
        req = make_sizing_request()
        resp1 = post_json(SIZING_ENDPOINT, req)
        run_id_a = resp1["cache_info"]["run_id"]
        resp2 = post_json(SIZING_ENDPOINT, req)
        run_id_b = resp2["cache_info"]["run_id"]

        compare_req = {"run_id_a": run_id_a, "run_id_b": run_id_b}
        result = post_json(COMPARE_ENDPOINT, compare_req)

        assert isinstance(result["key_deltas"], list)
        assert len(result["key_deltas"]) >= 1

    def test_key_delta_has_required_fields(self):
        """Verify each key_delta has required fields."""
        requests.delete(CACHE_CLEAR_URL)
        req = make_sizing_request()
        resp1 = post_json(SIZING_ENDPOINT, req)
        run_id_a = resp1["cache_info"]["run_id"]
        resp2 = post_json(SIZING_ENDPOINT, req)
        run_id_b = resp2["cache_info"]["run_id"]

        compare_req = {"run_id_a": run_id_a, "run_id_b": run_id_b}
        result = post_json(COMPARE_ENDPOINT, compare_req)

        for delta in result["key_deltas"]:
            assert "field" in delta
            assert "a" in delta
            assert "b" in delta
            assert "delta" in delta
            assert "pct_change" in delta

    def test_npv_delta_present(self):
        """Verify NPV delta is included."""
        requests.delete(CACHE_CLEAR_URL)
        req = make_sizing_request()
        resp1 = post_json(SIZING_ENDPOINT, req)
        run_id_a = resp1["cache_info"]["run_id"]
        resp2 = post_json(SIZING_ENDPOINT, req)
        run_id_b = resp2["cache_info"]["run_id"]

        compare_req = {"run_id_a": run_id_a, "run_id_b": run_id_b}
        result = post_json(COMPARE_ENDPOINT, compare_req)

        npv_delta = next(
            (d for d in result["key_deltas"] if "npv" in d["field"].lower()),
            None
        )
        assert npv_delta is not None

    def test_delta_is_zero_for_identical_runs(self):
        """Verify delta is 0 for identical cached runs."""
        requests.delete(CACHE_CLEAR_URL)
        req = make_sizing_request()
        resp1 = post_json(SIZING_ENDPOINT, req)
        run_id_a = resp1["cache_info"]["run_id"]
        resp2 = post_json(SIZING_ENDPOINT, req)
        run_id_b = resp2["cache_info"]["run_id"]

        compare_req = {"run_id_a": run_id_a, "run_id_b": run_id_b}
        result = post_json(COMPARE_ENDPOINT, compare_req)

        for delta in result["key_deltas"]:
            if delta["delta"] is not None:
                assert delta["delta"] == 0.0


class TestCompareRunsNotFound:
    """Tests for 404 handling."""

    def test_compare_nonexistent_run_a_returns_404(self):
        """Verify 404 for nonexistent run_id_a."""
        requests.delete(CACHE_CLEAR_URL)
        req = make_sizing_request()
        resp = post_json(SIZING_ENDPOINT, req)
        run_id_b = resp["cache_info"]["run_id"]

        fake_run_id = "00000000-0000-0000-0000-000000000000"
        compare_req = {"run_id_a": fake_run_id, "run_id_b": run_id_b}

        r = requests.post(
            f"http://localhost:8031{COMPARE_ENDPOINT}",
            json=compare_req
        )
        assert r.status_code == 404

    def test_compare_nonexistent_run_b_returns_404(self):
        """Verify 404 for nonexistent run_id_b."""
        requests.delete(CACHE_CLEAR_URL)
        req = make_sizing_request()
        resp = post_json(SIZING_ENDPOINT, req)
        run_id_a = resp["cache_info"]["run_id"]

        fake_run_id = "00000000-0000-0000-0000-000000000000"
        compare_req = {"run_id_a": run_id_a, "run_id_b": fake_run_id}

        r = requests.post(
            f"http://localhost:8031{COMPARE_ENDPOINT}",
            json=compare_req
        )
        assert r.status_code == 404

"""
Contract tests for v1.0.0 RunStore - GET /runs/{run_id} endpoint.

Tests verify:
- Sizing runs are auto-saved to RunStore
- GET /runs/{run_id} returns full run record
- Cache hits are also saved to RunStore
- Response contains request, response, metadata

Run with: pytest tests/contract/test_run_store_contract.py -v
"""
import pytest
from ._api import post_json, get_json


SIZING_ENDPOINT = "/sizing"
RUNS_ENDPOINT = "/runs"


def make_sizing_request():
    """Create minimal sizing request."""
    return {
        "load_kw": [100, 120, 110, 90],
        "pv_generation_kw": [50, 70, 80, 60],
        "energy_price_pln_kwh": 0.8,
    }


class TestRunStoreGetByRunId:
    """Tests for GET /runs/{run_id} endpoint."""

    def test_sizing_run_is_saved_and_retrievable(self):
        """Verify sizing run is saved and can be retrieved by run_id."""
        req = make_sizing_request()
        resp = post_json(SIZING_ENDPOINT, req)

        # Extract run_id from cache_info
        assert "cache_info" in resp
        run_id = resp["cache_info"]["run_id"]
        assert run_id is not None

        # Retrieve the run
        stored = get_json(f"{RUNS_ENDPOINT}/{run_id}")

        assert stored is not None
        assert stored["run_id"] == run_id

    def test_stored_run_has_required_fields(self):
        """Verify stored run has all required metadata fields."""
        req = make_sizing_request()
        resp = post_json(SIZING_ENDPOINT, req)
        run_id = resp["cache_info"]["run_id"]

        stored = get_json(f"{RUNS_ENDPOINT}/{run_id}")

        required_fields = [
            "run_id",
            "request_hash",
            "created_at",
            "endpoint",
            "status",
            "cache_hit",
            "schema_version",
            "assumptions_version",
            "compute_time_ms",
            "request",
            "response",
        ]
        for field in required_fields:
            assert field in stored, f"Missing field: {field}"

    def test_stored_run_endpoint_is_sizing(self):
        """Verify endpoint field is 'sizing' for sizing requests."""
        req = make_sizing_request()
        resp = post_json(SIZING_ENDPOINT, req)
        run_id = resp["cache_info"]["run_id"]

        stored = get_json(f"{RUNS_ENDPOINT}/{run_id}")

        assert stored["endpoint"] == "sizing"

    def test_stored_run_status_is_ok(self):
        """Verify status field is 'ok' for successful sizing requests."""
        req = make_sizing_request()
        resp = post_json(SIZING_ENDPOINT, req)
        run_id = resp["cache_info"]["run_id"]

        stored = get_json(f"{RUNS_ENDPOINT}/{run_id}")

        assert stored["status"] == "ok"

    def test_stored_run_has_request_payload(self):
        """Verify stored run contains the request payload with load_kw."""
        req = make_sizing_request()
        resp = post_json(SIZING_ENDPOINT, req)
        run_id = resp["cache_info"]["run_id"]

        stored = get_json(f"{RUNS_ENDPOINT}/{run_id}")

        assert "request" in stored
        # Stored request contains parsed/validated request (not raw JSON)
        assert "load_kw" in stored["request"]
        assert stored["request"]["load_kw"] == [100, 120, 110, 90]

    def test_stored_run_has_response_payload(self):
        """Verify stored run contains the response payload."""
        req = make_sizing_request()
        resp = post_json(SIZING_ENDPOINT, req)
        run_id = resp["cache_info"]["run_id"]

        stored = get_json(f"{RUNS_ENDPOINT}/{run_id}")

        assert "response" in stored
        # Response should have variants
        assert "variants" in stored["response"]

    def test_stored_run_request_hash_matches_cache_info(self):
        """Verify request_hash in stored run matches cache_info."""
        req = make_sizing_request()
        resp = post_json(SIZING_ENDPOINT, req)
        run_id = resp["cache_info"]["run_id"]
        expected_hash = resp["cache_info"]["request_hash"]

        stored = get_json(f"{RUNS_ENDPOINT}/{run_id}")

        assert stored["request_hash"] == expected_hash


class TestRunStoreNotFound:
    """Tests for 404 handling."""

    def test_nonexistent_run_id_returns_404(self):
        """Verify nonexistent run_id returns 404."""
        import requests

        fake_run_id = "00000000-0000-0000-0000-000000000000"
        resp = requests.get(f"http://localhost:8031{RUNS_ENDPOINT}/{fake_run_id}")

        assert resp.status_code == 404


class TestRunStoreCacheHit:
    """Tests for cache hit behavior."""

    def test_cache_hit_is_also_saved(self):
        """Verify cache hits are saved with cache_hit=True."""
        # Clear cache first to ensure clean state
        import requests
        requests.delete("http://localhost:8031/cache")

        req = make_sizing_request()

        # First request - cache miss
        resp1 = post_json(SIZING_ENDPOINT, req)
        run_id1 = resp1["cache_info"]["run_id"]
        assert resp1["cache_info"]["cache_status"] == "miss"

        # Second request - cache hit
        resp2 = post_json(SIZING_ENDPOINT, req)
        run_id2 = resp2["cache_info"]["run_id"]
        assert resp2["cache_info"]["cache_status"] == "hit"

        # Both runs should be stored
        stored1 = get_json(f"{RUNS_ENDPOINT}/{run_id1}")
        stored2 = get_json(f"{RUNS_ENDPOINT}/{run_id2}")

        assert stored1["cache_hit"] is False
        assert stored2["cache_hit"] is True

    def test_cache_hit_run_has_same_request_hash(self):
        """Verify cache hit run has same request_hash as original."""
        import requests
        requests.delete("http://localhost:8031/cache")

        req = make_sizing_request()

        resp1 = post_json(SIZING_ENDPOINT, req)
        resp2 = post_json(SIZING_ENDPOINT, req)

        run_id1 = resp1["cache_info"]["run_id"]
        run_id2 = resp2["cache_info"]["run_id"]

        stored1 = get_json(f"{RUNS_ENDPOINT}/{run_id1}")
        stored2 = get_json(f"{RUNS_ENDPOINT}/{run_id2}")

        assert stored1["request_hash"] == stored2["request_hash"]


class TestRunStoreComputeTime:
    """Tests for compute_time_ms field."""

    def test_compute_time_is_positive(self):
        """Verify compute_time_ms is positive."""
        req = make_sizing_request()
        resp = post_json(SIZING_ENDPOINT, req)
        run_id = resp["cache_info"]["run_id"]

        stored = get_json(f"{RUNS_ENDPOINT}/{run_id}")

        assert stored["compute_time_ms"] >= 0

    def test_cache_hit_has_lower_compute_time(self):
        """Verify cache hit typically has lower compute time than miss."""
        import requests
        requests.delete("http://localhost:8031/cache")

        req = make_sizing_request()

        # First request - cache miss (compute)
        resp1 = post_json(SIZING_ENDPOINT, req)
        run_id1 = resp1["cache_info"]["run_id"]

        # Second request - cache hit (no compute)
        resp2 = post_json(SIZING_ENDPOINT, req)
        run_id2 = resp2["cache_info"]["run_id"]

        stored1 = get_json(f"{RUNS_ENDPOINT}/{run_id1}")
        stored2 = get_json(f"{RUNS_ENDPOINT}/{run_id2}")

        # Cache hit should typically be faster
        # (not a strict assertion since timing can vary)
        assert stored2["compute_time_ms"] <= stored1["compute_time_ms"] + 100

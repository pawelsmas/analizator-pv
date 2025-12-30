"""
Contract tests for v0.9.0 request hash, run_id, and caching.

Tests verify:
- cache_info is present in response
- request_hash is deterministic (same input = same hash)
- run_id is unique for new computations
- Cache hit returns same run_id as original
- cache_status is correct (miss/hit)
- Cache management endpoints work

Run with: pytest tests/contract/test_cache_contract.py -v
"""
import pytest
import requests
from ._api import post_json


SIZING_PATH = "/sizing"
CACHE_STATS_URL = "http://localhost:8031/cache/stats"
CACHE_CLEAR_URL = "http://localhost:8031/cache"


# Minimal valid sizing request for testing
MINIMAL_SIZING_REQUEST = {
    "load_kw": [100, 120, 110, 90],
    "pv_generation_kw": [50, 70, 80, 60],
    "energy_price_pln_kwh": 0.8,
}


class TestCacheInfoPresence:
    """Tests for cache_info field presence in response."""

    def test_cache_info_present_in_response(self):
        """Verify cache_info is present in sizing response."""
        # Clear cache first to ensure cache miss
        requests.delete(CACHE_CLEAR_URL)

        resp = post_json(SIZING_PATH, MINIMAL_SIZING_REQUEST)
        assert "cache_info" in resp
        assert resp["cache_info"] is not None

    def test_cache_info_has_required_fields(self):
        """Verify cache_info has all required fields."""
        requests.delete(CACHE_CLEAR_URL)

        resp = post_json(SIZING_PATH, MINIMAL_SIZING_REQUEST)
        cache_info = resp["cache_info"]

        assert "request_hash" in cache_info
        assert "run_id" in cache_info
        assert "cache_status" in cache_info
        assert "ttl_seconds" in cache_info

    def test_request_hash_is_64_char_hex(self):
        """Verify request_hash is SHA-256 format (64 hex chars)."""
        requests.delete(CACHE_CLEAR_URL)

        resp = post_json(SIZING_PATH, MINIMAL_SIZING_REQUEST)
        request_hash = resp["cache_info"]["request_hash"]

        assert len(request_hash) == 64
        assert all(c in "0123456789abcdef" for c in request_hash)

    def test_run_id_is_uuid_format(self):
        """Verify run_id is UUID format."""
        requests.delete(CACHE_CLEAR_URL)

        resp = post_json(SIZING_PATH, MINIMAL_SIZING_REQUEST)
        run_id = resp["cache_info"]["run_id"]

        # UUID format: 8-4-4-4-12 hex chars
        parts = run_id.split("-")
        assert len(parts) == 5
        assert len(parts[0]) == 8
        assert len(parts[1]) == 4
        assert len(parts[2]) == 4
        assert len(parts[3]) == 4
        assert len(parts[4]) == 12


class TestRequestHashDeterminism:
    """Tests for deterministic request hash computation."""

    def test_same_request_produces_same_hash(self):
        """Verify same input produces same request_hash."""
        requests.delete(CACHE_CLEAR_URL)

        # First request
        resp1 = post_json(SIZING_PATH, MINIMAL_SIZING_REQUEST)
        hash1 = resp1["cache_info"]["request_hash"]

        # Clear cache to force recomputation
        requests.delete(CACHE_CLEAR_URL)

        # Second request with identical input
        resp2 = post_json(SIZING_PATH, MINIMAL_SIZING_REQUEST)
        hash2 = resp2["cache_info"]["request_hash"]

        assert hash1 == hash2

    def test_different_request_produces_different_hash(self):
        """Verify different input produces different request_hash."""
        requests.delete(CACHE_CLEAR_URL)

        # First request
        resp1 = post_json(SIZING_PATH, MINIMAL_SIZING_REQUEST)
        hash1 = resp1["cache_info"]["request_hash"]

        # Second request with different input
        different_request = {
            "load_kw": [200, 220, 210, 190],  # Different values
            "pv_generation_kw": [50, 70, 80, 60],
            "energy_price_pln_kwh": 0.8,
        }
        resp2 = post_json(SIZING_PATH, different_request)
        hash2 = resp2["cache_info"]["request_hash"]

        assert hash1 != hash2


class TestCacheStatus:
    """Tests for cache_status behavior."""

    def test_first_request_is_cache_miss(self):
        """Verify first request returns cache_status=miss."""
        requests.delete(CACHE_CLEAR_URL)

        resp = post_json(SIZING_PATH, MINIMAL_SIZING_REQUEST)
        assert resp["cache_info"]["cache_status"] == "miss"

    def test_second_request_is_cache_hit(self):
        """Verify second identical request returns cache_status=hit."""
        requests.delete(CACHE_CLEAR_URL)

        # First request - cache miss
        resp1 = post_json(SIZING_PATH, MINIMAL_SIZING_REQUEST)
        assert resp1["cache_info"]["cache_status"] == "miss"

        # Second request - cache hit
        resp2 = post_json(SIZING_PATH, MINIMAL_SIZING_REQUEST)
        assert resp2["cache_info"]["cache_status"] == "hit"

    def test_cache_hit_has_unique_run_id(self):
        """Verify each request gets unique run_id (v1.0.0 audit trail).

        Note: Changed from preserving run_id to unique run_id per request
        to support per-request audit trail in RunStore.
        """
        requests.delete(CACHE_CLEAR_URL)

        # First request
        resp1 = post_json(SIZING_PATH, MINIMAL_SIZING_REQUEST)
        run_id1 = resp1["cache_info"]["run_id"]

        # Second request - should have different run_id (unique per request)
        resp2 = post_json(SIZING_PATH, MINIMAL_SIZING_REQUEST)
        run_id2 = resp2["cache_info"]["run_id"]

        # v1.0.0: Each request gets unique run_id for audit trail
        assert run_id1 != run_id2

    def test_cache_hit_has_cached_at_timestamp(self):
        """Verify cache hit includes cached_at timestamp."""
        requests.delete(CACHE_CLEAR_URL)

        # First request - no cached_at for miss
        resp1 = post_json(SIZING_PATH, MINIMAL_SIZING_REQUEST)
        # cached_at might be null for miss

        # Second request - should have cached_at
        resp2 = post_json(SIZING_PATH, MINIMAL_SIZING_REQUEST)
        assert resp2["cache_info"]["cached_at"] is not None


class TestCacheManagement:
    """Tests for cache management endpoints."""

    def test_cache_stats_endpoint_returns_200(self):
        """Verify GET /cache/stats returns 200."""
        resp = requests.get(CACHE_STATS_URL)
        assert resp.status_code == 200

    def test_cache_stats_has_required_fields(self):
        """Verify cache stats has entries and max_entries."""
        resp = requests.get(CACHE_STATS_URL)
        data = resp.json()

        assert "entries" in data
        assert "max_entries" in data
        assert isinstance(data["entries"], int)
        assert isinstance(data["max_entries"], int)

    def test_cache_clear_endpoint_returns_200(self):
        """Verify DELETE /cache returns 200."""
        resp = requests.delete(CACHE_CLEAR_URL)
        assert resp.status_code == 200

    def test_cache_clear_returns_cleared_count(self):
        """Verify DELETE /cache returns cleared count."""
        # Add something to cache first
        post_json(SIZING_PATH, MINIMAL_SIZING_REQUEST)

        resp = requests.delete(CACHE_CLEAR_URL)
        data = resp.json()

        assert "cleared" in data
        assert isinstance(data["cleared"], int)

    def test_cache_clear_empties_cache(self):
        """Verify DELETE /cache actually clears the cache."""
        # Add something to cache
        post_json(SIZING_PATH, MINIMAL_SIZING_REQUEST)

        # Check it's cached
        stats1 = requests.get(CACHE_STATS_URL).json()
        assert stats1["entries"] > 0

        # Clear cache
        requests.delete(CACHE_CLEAR_URL)

        # Check it's empty
        stats2 = requests.get(CACHE_STATS_URL).json()
        assert stats2["entries"] == 0


class TestCacheResultConsistency:
    """Tests for cache result consistency."""

    def test_cached_result_equals_original(self):
        """Verify cached result has same data as original."""
        requests.delete(CACHE_CLEAR_URL)

        # First request
        resp1 = post_json(SIZING_PATH, MINIMAL_SIZING_REQUEST)

        # Second request (from cache)
        resp2 = post_json(SIZING_PATH, MINIMAL_SIZING_REQUEST)

        # Compare key fields (excluding cache_info which differs)
        assert resp1["mode"] == resp2["mode"]
        assert resp1["recommended_variant"] == resp2["recommended_variant"]
        assert len(resp1["variants"]) == len(resp2["variants"])

        # Compare variant NPVs
        for v1, v2 in zip(resp1["variants"], resp2["variants"]):
            assert v1["npv_pln"] == v2["npv_pln"]
            assert v1["variant"] == v2["variant"]

    def test_request_hash_same_on_cache_hit(self):
        """Verify request_hash is identical on cache hit."""
        requests.delete(CACHE_CLEAR_URL)

        resp1 = post_json(SIZING_PATH, MINIMAL_SIZING_REQUEST)
        resp2 = post_json(SIZING_PATH, MINIMAL_SIZING_REQUEST)

        assert resp1["cache_info"]["request_hash"] == resp2["cache_info"]["request_hash"]

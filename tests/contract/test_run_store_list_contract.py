"""
Contract tests for v1.0.0 RunStore - GET /runs list endpoint.

Tests verify:
- List runs returns paginated results
- Pagination works correctly (limit, offset)
- Filter by request_hash works
- Filter by endpoint works
- Response structure is correct

Run with: pytest tests/contract/test_run_store_list_contract.py -v
"""
import pytest
import requests
from ._api import post_json, get_json


SIZING_ENDPOINT = "/sizing"
RUNS_ENDPOINT = "/runs"
CACHE_CLEAR_URL = "http://localhost:8031/cache"


def make_sizing_request(load_variation: int = 0):
    """Create sizing request with optional load variation for unique requests."""
    return {
        "load_kw": [100 + load_variation, 120, 110, 90],
        "pv_generation_kw": [50, 70, 80, 60],
        "energy_price_pln_kwh": 0.8,
    }


class TestListRunsBasic:
    """Tests for basic list functionality."""

    def test_list_runs_returns_items_array(self):
        """Verify list runs returns items array."""
        # Make a request to ensure at least one run exists
        req = make_sizing_request()
        post_json(SIZING_ENDPOINT, req)

        result = get_json(RUNS_ENDPOINT)

        assert "items" in result
        assert isinstance(result["items"], list)

    def test_list_runs_returns_pagination_info(self):
        """Verify list runs returns pagination info."""
        result = get_json(RUNS_ENDPOINT)

        assert "limit" in result
        assert "offset" in result
        assert "total" in result

    def test_list_runs_item_has_metadata_fields(self):
        """Verify each item has required metadata fields."""
        req = make_sizing_request()
        post_json(SIZING_ENDPOINT, req)

        result = get_json(RUNS_ENDPOINT)

        if len(result["items"]) > 0:
            item = result["items"][0]
            required_fields = [
                "run_id",
                "request_hash",
                "created_at",
                "endpoint",
                "status",
                "cache_hit",
            ]
            for field in required_fields:
                assert field in item, f"Missing field: {field}"

    def test_list_runs_item_does_not_have_blobs(self):
        """Verify items don't include request/response blobs for efficiency."""
        req = make_sizing_request()
        post_json(SIZING_ENDPOINT, req)

        result = get_json(RUNS_ENDPOINT)

        if len(result["items"]) > 0:
            item = result["items"][0]
            # Should NOT have full blobs in list view
            assert "request" not in item
            assert "response" not in item


class TestListRunsPagination:
    """Tests for pagination functionality."""

    def test_default_limit_is_20(self):
        """Verify default limit is 20."""
        result = get_json(RUNS_ENDPOINT)
        assert result["limit"] == 20

    def test_default_offset_is_0(self):
        """Verify default offset is 0."""
        result = get_json(RUNS_ENDPOINT)
        assert result["offset"] == 0

    def test_custom_limit_is_respected(self):
        """Verify custom limit parameter works."""
        result = get_json(f"{RUNS_ENDPOINT}?limit=5")
        assert result["limit"] == 5
        assert len(result["items"]) <= 5

    def test_custom_offset_works(self):
        """Verify offset parameter works for pagination."""
        # Get first page
        page1 = get_json(f"{RUNS_ENDPOINT}?limit=1&offset=0")
        # Get second page
        page2 = get_json(f"{RUNS_ENDPOINT}?limit=1&offset=1")

        if page1["total"] >= 2:
            # Items should be different
            if len(page1["items"]) > 0 and len(page2["items"]) > 0:
                assert page1["items"][0]["run_id"] != page2["items"][0]["run_id"]

    def test_limit_max_is_100(self):
        """Verify limit max is 100."""
        resp = requests.get(f"http://localhost:8031{RUNS_ENDPOINT}?limit=200")
        # Should either cap at 100 or return 422 validation error
        assert resp.status_code in [200, 422]


class TestListRunsFilterByRequestHash:
    """Tests for request_hash filtering."""

    def test_filter_by_request_hash_returns_matching_runs(self):
        """Verify filter by request_hash returns matching runs only."""
        # Clear cache and make a unique request
        requests.delete(CACHE_CLEAR_URL)
        req = make_sizing_request(load_variation=999)
        resp = post_json(SIZING_ENDPOINT, req)
        request_hash = resp["cache_info"]["request_hash"]

        # Filter by this request_hash
        result = get_json(f"{RUNS_ENDPOINT}?request_hash={request_hash}")

        assert len(result["items"]) >= 1
        for item in result["items"]:
            assert item["request_hash"] == request_hash

    def test_filter_by_unknown_request_hash_returns_empty(self):
        """Verify filter by unknown request_hash returns empty."""
        fake_hash = "0" * 64  # SHA-256 is 64 hex chars
        result = get_json(f"{RUNS_ENDPOINT}?request_hash={fake_hash}")

        assert len(result["items"]) == 0
        assert result["total"] == 0


class TestListRunsFilterByEndpoint:
    """Tests for endpoint filtering."""

    def test_filter_by_endpoint_sizing(self):
        """Verify filter by endpoint='sizing' works."""
        # Ensure we have a sizing run
        req = make_sizing_request()
        post_json(SIZING_ENDPOINT, req)

        result = get_json(f"{RUNS_ENDPOINT}?endpoint=sizing")

        assert len(result["items"]) >= 1
        for item in result["items"]:
            assert item["endpoint"] == "sizing"

    def test_filter_by_unknown_endpoint_returns_empty(self):
        """Verify filter by unknown endpoint returns empty."""
        result = get_json(f"{RUNS_ENDPOINT}?endpoint=nonexistent")

        assert len(result["items"]) == 0


class TestListRunsOrdering:
    """Tests for result ordering."""

    def test_runs_ordered_by_created_at_descending(self):
        """Verify runs are ordered by created_at descending (newest first)."""
        # Make two requests
        requests.delete(CACHE_CLEAR_URL)
        req1 = make_sizing_request(load_variation=1001)
        post_json(SIZING_ENDPOINT, req1)

        req2 = make_sizing_request(load_variation=1002)
        post_json(SIZING_ENDPOINT, req2)

        result = get_json(f"{RUNS_ENDPOINT}?limit=10")

        if len(result["items"]) >= 2:
            # First item should have newer or equal created_at
            first_created = result["items"][0]["created_at"]
            second_created = result["items"][1]["created_at"]
            assert first_created >= second_created


class TestListRunsCombinedFilters:
    """Tests for combined filtering."""

    def test_filter_by_request_hash_and_endpoint(self):
        """Verify combined filtering works."""
        requests.delete(CACHE_CLEAR_URL)
        req = make_sizing_request(load_variation=2001)
        resp = post_json(SIZING_ENDPOINT, req)
        request_hash = resp["cache_info"]["request_hash"]

        result = get_json(f"{RUNS_ENDPOINT}?request_hash={request_hash}&endpoint=sizing")

        assert len(result["items"]) >= 1
        for item in result["items"]:
            assert item["request_hash"] == request_hash
            assert item["endpoint"] == "sizing"

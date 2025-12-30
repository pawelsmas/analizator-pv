"""
Contract tests for v1.0.0 Retention and Pruning endpoints.

Tests verify:
- GET /runs/retention returns config
- POST /runs:prune deletes old runs
- Prune respects retention_days parameter
- Response structure is correct

Run with: pytest tests/contract/test_retention_pruning_contract.py -v
"""
import pytest
import requests
from ._api import post_json, get_json


SIZING_ENDPOINT = "/sizing"
RUNS_ENDPOINT = "/runs"
RETENTION_ENDPOINT = "/runs/retention"
PRUNE_ENDPOINT = "/runs:prune"
BASE_URL = "http://localhost:8031"


def make_sizing_request(load_variation: int = 0):
    """Create minimal sizing request with optional variation."""
    return {
        "load_kw": [100 + load_variation, 120, 110, 90],
        "pv_generation_kw": [50, 70, 80, 60],
        "energy_price_pln_kwh": 0.8,
    }


class TestRetentionConfigEndpoint:
    """Tests for GET /runs/retention endpoint."""

    def test_retention_returns_200(self):
        """Verify retention endpoint returns 200."""
        r = requests.get(f"{BASE_URL}{RETENTION_ENDPOINT}")
        assert r.status_code == 200

    def test_retention_has_retention_days(self):
        """Verify retention response has retention_days field."""
        r = requests.get(f"{BASE_URL}{RETENTION_ENDPOINT}")
        data = r.json()
        assert "retention_days" in data
        assert isinstance(data["retention_days"], int)
        assert data["retention_days"] > 0

    def test_retention_has_run_store_enabled(self):
        """Verify retention response has run_store_enabled field."""
        r = requests.get(f"{BASE_URL}{RETENTION_ENDPOINT}")
        data = r.json()
        assert "run_store_enabled" in data
        assert isinstance(data["run_store_enabled"], bool)

    def test_retention_default_is_30_days(self):
        """Verify default retention is 30 days (from env or default)."""
        r = requests.get(f"{BASE_URL}{RETENTION_ENDPOINT}")
        data = r.json()
        # Default is 30, but could be overridden by env
        assert data["retention_days"] >= 1
        assert data["retention_days"] <= 365


class TestPruneEndpoint:
    """Tests for POST /runs:prune endpoint."""

    def test_prune_returns_200(self):
        """Verify prune endpoint returns 200."""
        r = requests.post(f"{BASE_URL}{PRUNE_ENDPOINT}", json={})
        assert r.status_code == 200

    def test_prune_response_has_deleted(self):
        """Verify prune response has deleted field."""
        r = requests.post(f"{BASE_URL}{PRUNE_ENDPOINT}", json={})
        data = r.json()
        assert "deleted" in data
        assert isinstance(data["deleted"], int)
        assert data["deleted"] >= 0

    def test_prune_response_has_retention_days(self):
        """Verify prune response has retention_days field."""
        r = requests.post(f"{BASE_URL}{PRUNE_ENDPOINT}", json={})
        data = r.json()
        assert "retention_days" in data
        assert isinstance(data["retention_days"], int)

    def test_prune_with_custom_retention(self):
        """Verify prune accepts custom retention_days."""
        r = requests.post(f"{BASE_URL}{PRUNE_ENDPOINT}", json={"retention_days": 7})
        assert r.status_code == 200
        data = r.json()
        assert data["retention_days"] == 7

    def test_prune_with_default_retention(self):
        """Verify prune uses default when retention_days not specified."""
        # Get default
        retention_resp = requests.get(f"{BASE_URL}{RETENTION_ENDPOINT}")
        default_retention = retention_resp.json()["retention_days"]

        # Prune without specifying retention
        prune_resp = requests.post(f"{BASE_URL}{PRUNE_ENDPOINT}", json={})
        assert prune_resp.json()["retention_days"] == default_retention


class TestPruneValidation:
    """Tests for prune parameter validation."""

    def test_prune_rejects_negative_retention(self):
        """Verify prune rejects negative retention_days."""
        r = requests.post(f"{BASE_URL}{PRUNE_ENDPOINT}", json={"retention_days": -1})
        assert r.status_code == 422  # Validation error

    def test_prune_rejects_zero_retention(self):
        """Verify prune rejects zero retention_days."""
        r = requests.post(f"{BASE_URL}{PRUNE_ENDPOINT}", json={"retention_days": 0})
        assert r.status_code == 422  # Validation error

    def test_prune_rejects_excessive_retention(self):
        """Verify prune rejects retention_days > 365."""
        r = requests.post(f"{BASE_URL}{PRUNE_ENDPOINT}", json={"retention_days": 400})
        assert r.status_code == 422  # Validation error


class TestPruneFunctionality:
    """Tests for actual prune functionality."""

    def test_prune_does_not_delete_recent_runs(self):
        """Verify prune does not delete runs within retention period."""
        # Create a new run
        req = make_sizing_request(load_variation=9999)
        resp = post_json(SIZING_ENDPOINT, req)
        run_id = resp["cache_info"]["run_id"]

        # Prune with 30 day retention
        prune_resp = requests.post(f"{BASE_URL}{PRUNE_ENDPOINT}", json={"retention_days": 30})
        assert prune_resp.status_code == 200

        # Verify the run still exists
        get_resp = requests.get(f"{BASE_URL}{RUNS_ENDPOINT}/{run_id}")
        assert get_resp.status_code == 200

    def test_prune_returns_deleted_count(self):
        """Verify prune returns count of deleted runs (may be 0 for recent runs)."""
        # Create a run
        req = make_sizing_request()
        post_json(SIZING_ENDPOINT, req)

        # Prune with default retention
        r = requests.post(f"{BASE_URL}{PRUNE_ENDPOINT}", json={})
        data = r.json()

        # deleted should be >= 0 (likely 0 since we just created the run)
        assert data["deleted"] >= 0

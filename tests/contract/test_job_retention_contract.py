"""
Contract tests for v1.2.0 job retention, pruning, vacuum endpoints.

Tests verify:
- GET /jobs/retention returns configuration
- POST /jobs:prune deletes old jobs
- POST /jobs:vacuum reclaims space
- GET /jobs/stats returns database statistics
"""
import time

import pytest
import requests

from ._api import post_json


# API paths
JOBS_BATCH_PATH = "/api/bess-dispatch/jobs/sizing-batch"
JOBS_RETENTION_PATH = "/api/bess-dispatch/jobs/retention"
JOBS_PRUNE_PATH = "/api/bess-dispatch/jobs:prune"
JOBS_VACUUM_PATH = "/api/bess-dispatch/jobs:vacuum"
JOBS_STATS_PATH = "/api/bess-dispatch/jobs/stats"
BASE_URL = "http://localhost:8031"


def create_test_job():
    """Create a job for testing."""
    payload = {
        "batch_id": f"retention_test_{int(time.time() * 1000)}",
        "wait": True,
        "items": [
            {
                "item_id": "test_item",
                "request": {
                    "load_kw": [50, 60, 70, 80, 90, 100] * 4,
                    "pv_generation_kw": [0, 0, 0, 5, 20, 40] * 4,
                    "energy_price_pln_kwh": 0.8,
                    "mode": "stacked",
                    "peak_limit_kw": 80,
                },
            }
        ],
    }
    return post_json(JOBS_BATCH_PATH, payload)


class TestJobRetentionEndpoint:
    """Test GET /jobs/retention endpoint."""

    def test_retention_endpoint_returns_200(self):
        """Verify retention endpoint exists and returns 200."""
        response = requests.get(f"{BASE_URL}{JOBS_RETENTION_PATH}")

        assert response.status_code == 200

    def test_retention_has_retention_days(self):
        """Verify response has retention_days field."""
        response = requests.get(f"{BASE_URL}{JOBS_RETENTION_PATH}")
        data = response.json()

        assert "retention_days" in data
        assert isinstance(data["retention_days"], int)
        assert data["retention_days"] > 0

    def test_retention_has_job_store_enabled(self):
        """Verify response has job_store_enabled field."""
        response = requests.get(f"{BASE_URL}{JOBS_RETENTION_PATH}")
        data = response.json()

        assert "job_store_enabled" in data
        assert isinstance(data["job_store_enabled"], bool)


class TestJobPruneEndpoint:
    """Test POST /jobs:prune endpoint."""

    def test_prune_endpoint_returns_200(self):
        """Verify prune endpoint exists and returns 200."""
        response = requests.post(f"{BASE_URL}{JOBS_PRUNE_PATH}", json={})

        assert response.status_code == 200

    def test_prune_returns_deleted_count(self):
        """Verify prune returns deleted count."""
        response = requests.post(f"{BASE_URL}{JOBS_PRUNE_PATH}", json={})
        data = response.json()

        assert "deleted" in data
        assert isinstance(data["deleted"], int)
        assert data["deleted"] >= 0

    def test_prune_returns_retention_days(self):
        """Verify prune returns retention_days used."""
        response = requests.post(f"{BASE_URL}{JOBS_PRUNE_PATH}", json={})
        data = response.json()

        assert "retention_days" in data
        assert isinstance(data["retention_days"], int)

    def test_prune_accepts_custom_retention(self):
        """Verify prune accepts custom retention_days."""
        response = requests.post(
            f"{BASE_URL}{JOBS_PRUNE_PATH}",
            json={"retention_days": 30}
        )
        data = response.json()

        assert response.status_code == 200
        assert data["retention_days"] == 30

    def test_prune_validates_retention_min(self):
        """Verify retention_days minimum validation (>= 1)."""
        response = requests.post(
            f"{BASE_URL}{JOBS_PRUNE_PATH}",
            json={"retention_days": 0}
        )

        assert response.status_code == 422

    def test_prune_validates_retention_max(self):
        """Verify retention_days maximum validation (<= 365)."""
        response = requests.post(
            f"{BASE_URL}{JOBS_PRUNE_PATH}",
            json={"retention_days": 400}
        )

        assert response.status_code == 422


class TestJobVacuumEndpoint:
    """Test POST /jobs:vacuum endpoint."""

    def test_vacuum_endpoint_returns_200(self):
        """Verify vacuum endpoint exists and returns 200."""
        response = requests.post(f"{BASE_URL}{JOBS_VACUUM_PATH}")

        assert response.status_code == 200

    def test_vacuum_returns_size_before(self):
        """Verify vacuum returns size_before_bytes."""
        response = requests.post(f"{BASE_URL}{JOBS_VACUUM_PATH}")
        data = response.json()

        assert "size_before_bytes" in data
        assert isinstance(data["size_before_bytes"], int)
        assert data["size_before_bytes"] >= 0

    def test_vacuum_returns_size_after(self):
        """Verify vacuum returns size_after_bytes."""
        response = requests.post(f"{BASE_URL}{JOBS_VACUUM_PATH}")
        data = response.json()

        assert "size_after_bytes" in data
        assert isinstance(data["size_after_bytes"], int)
        assert data["size_after_bytes"] >= 0

    def test_vacuum_returns_freed_bytes(self):
        """Verify vacuum returns freed_bytes."""
        response = requests.post(f"{BASE_URL}{JOBS_VACUUM_PATH}")
        data = response.json()

        assert "freed_bytes" in data
        assert isinstance(data["freed_bytes"], int)

    def test_vacuum_freed_equals_difference(self):
        """Verify freed_bytes = size_before - size_after."""
        response = requests.post(f"{BASE_URL}{JOBS_VACUUM_PATH}")
        data = response.json()

        expected_freed = data["size_before_bytes"] - data["size_after_bytes"]
        assert data["freed_bytes"] == expected_freed


class TestJobStatsEndpoint:
    """Test GET /jobs/stats endpoint."""

    def test_stats_endpoint_returns_200(self):
        """Verify stats endpoint exists and returns 200."""
        # Create a job first to ensure database exists
        create_test_job()

        response = requests.get(f"{BASE_URL}{JOBS_STATS_PATH}")

        assert response.status_code == 200

    def test_stats_has_total_jobs(self):
        """Verify stats has total_jobs field."""
        create_test_job()

        response = requests.get(f"{BASE_URL}{JOBS_STATS_PATH}")
        data = response.json()

        assert "total_jobs" in data
        assert isinstance(data["total_jobs"], int)
        assert data["total_jobs"] >= 0

    def test_stats_has_size_bytes(self):
        """Verify stats has size_bytes field."""
        create_test_job()

        response = requests.get(f"{BASE_URL}{JOBS_STATS_PATH}")
        data = response.json()

        assert "size_bytes" in data
        assert isinstance(data["size_bytes"], int)
        assert data["size_bytes"] >= 0

    def test_stats_has_by_status(self):
        """Verify stats has by_status field."""
        create_test_job()

        response = requests.get(f"{BASE_URL}{JOBS_STATS_PATH}")
        data = response.json()

        assert "by_status" in data
        assert isinstance(data["by_status"], dict)

    def test_stats_has_by_type(self):
        """Verify stats has by_type field."""
        create_test_job()

        response = requests.get(f"{BASE_URL}{JOBS_STATS_PATH}")
        data = response.json()

        assert "by_type" in data
        assert isinstance(data["by_type"], dict)

    def test_stats_has_job_store_enabled(self):
        """Verify stats has job_store_enabled field."""
        response = requests.get(f"{BASE_URL}{JOBS_STATS_PATH}")
        data = response.json()

        assert "job_store_enabled" in data
        assert isinstance(data["job_store_enabled"], bool)

    def test_stats_reflects_created_job(self):
        """Verify stats total increases after creating job."""
        # Get initial count
        response1 = requests.get(f"{BASE_URL}{JOBS_STATS_PATH}")
        initial_total = response1.json().get("total_jobs", 0)

        # Create a job
        create_test_job()

        # Get new count
        response2 = requests.get(f"{BASE_URL}{JOBS_STATS_PATH}")
        new_total = response2.json()["total_jobs"]

        assert new_total >= initial_total + 1

    def test_stats_done_count_increases(self):
        """Verify done count increases after completed job."""
        create_test_job()  # Creates a done job (wait=True)

        response = requests.get(f"{BASE_URL}{JOBS_STATS_PATH}")
        data = response.json()

        # Should have at least one done job
        assert data["by_status"].get("done", 0) >= 1


class TestPruneAndVacuumFlow:
    """Test combined prune + vacuum flow."""

    def test_prune_then_vacuum_workflow(self):
        """Verify prune + vacuum workflow returns valid responses."""
        # Create a job to ensure DB exists
        create_test_job()

        # Prune with very long retention (won't delete recent jobs)
        prune_response = requests.post(
            f"{BASE_URL}{JOBS_PRUNE_PATH}",
            json={"retention_days": 365}
        )
        assert prune_response.status_code == 200

        # Vacuum to reclaim space
        vacuum_response = requests.post(f"{BASE_URL}{JOBS_VACUUM_PATH}")
        assert vacuum_response.status_code == 200

        # Verify vacuum response structure
        vacuum_data = vacuum_response.json()
        assert "size_before_bytes" in vacuum_data
        assert "size_after_bytes" in vacuum_data
        assert "freed_bytes" in vacuum_data

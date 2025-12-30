#!/usr/bin/env python3
"""
Generate golden master files for v1.1.0 jobs API regression tests.

Usage:
    python tests/regression/generate_jobs_golden.py

Requires:
    - bess-dispatch service running on localhost:8031
"""

import json
import time
import requests
from pathlib import Path

# API base URL
BASE_URL = "http://localhost:8031"

# Output directory
GOLDEN_DIR = Path(__file__).parent / "golden"


def generate_job_response_golden():
    """Generate golden master for job creation and status."""

    # Create valid sizing requests for STACKED mode
    batch_items = [
        {
            "item_id": "scenario_A",
            "request": {
                "load_kw": [50, 60, 70, 80, 90, 100] * 4,  # 24 hours
                "pv_generation_kw": [0, 0, 0, 5, 20, 40] * 4,  # 24 hours
                "energy_price_pln_kwh": 0.8,
                "mode": "stacked",
                "peak_limit_kw": 80  # Required for STACKED mode
            }
        },
        {
            "item_id": "scenario_B",
            "request": {
                "load_kw": [30, 40, 50, 60, 70, 80] * 4,  # 24 hours
                "pv_generation_kw": [0, 0, 5, 15, 30, 50] * 4,  # 24 hours
                "energy_price_pln_kwh": 0.75,
                "mode": "stacked",
                "peak_limit_kw": 60  # Required for STACKED mode
            }
        }
    ]

    # Sync request (wait=true in body)
    sync_request = {
        "batch_id": "regression_test_jobs",
        "wait": True,
        "items": batch_items
    }

    # Save request
    request_file = GOLDEN_DIR / "scenario_jobs_v110_request.json"
    with open(request_file, "w") as f:
        json.dump(sync_request, f, indent=2)
    print(f"Saved request: {request_file}")

    # Call jobs API with wait=true (in body, not query param)
    print("Creating job with wait=true...")
    response = requests.post(
        f"{BASE_URL}/api/bess-dispatch/jobs/sizing-batch",
        json=sync_request,
        headers={"Content-Type": "application/json"}
    )
    response.raise_for_status()
    job_status = response.json()
    job_id = job_status["job_id"]

    # Get full job detail (includes result)
    response = requests.get(f"{BASE_URL}/api/bess-dispatch/jobs/{job_id}")
    response.raise_for_status()
    job_result = response.json()

    # Save full job result with result field
    result_file = GOLDEN_DIR / "scenario_jobs_v110_sync.json"
    with open(result_file, "w") as f:
        json.dump(job_result, f, indent=2)
    print(f"Saved sync job response: {result_file}")

    # Now test async mode (wait=false, default)
    print("Creating job with wait=false...")
    async_request = {
        "batch_id": "regression_test_jobs_async",
        "wait": False,
        "items": batch_items[:1]  # Just one item for async test
    }

    response = requests.post(
        f"{BASE_URL}/api/bess-dispatch/jobs/sizing-batch",
        json=async_request,
        headers={"Content-Type": "application/json"}
    )
    response.raise_for_status()
    async_job = response.json()

    # Save async job creation response
    async_file = GOLDEN_DIR / "scenario_jobs_v110_async.json"
    with open(async_file, "w") as f:
        json.dump(async_job, f, indent=2)
    print(f"Saved async job response: {async_file}")

    # Async jobs need a worker to process. For regression tests, we simulate
    # by running a sync job and treating it as "completed"
    # Get the sync job again as the "completed" example
    completed_file = GOLDEN_DIR / "scenario_jobs_v110_completed.json"
    with open(completed_file, "w") as f:
        json.dump(job_result, f, indent=2)
    print(f"Saved completed job: {completed_file}")

    # Get job list
    print("Getting job list...")
    response = requests.get(f"{BASE_URL}/api/bess-dispatch/jobs?limit=10")
    response.raise_for_status()
    jobs_list = response.json()

    list_file = GOLDEN_DIR / "scenario_jobs_v110_list.json"
    with open(list_file, "w") as f:
        json.dump(jobs_list, f, indent=2)
    print(f"Saved job list: {list_file}")

    print("\nDone! Generated golden master files for v1.1.0 jobs API.")


if __name__ == "__main__":
    generate_job_response_golden()

#!/usr/bin/env python3
"""
Generate golden master file for batch sizing regression tests.

Run with services up:
  python tests/regression/generate_batch_golden.py

Generates:
  tests/regression/golden/scenario_batch_v090.json
  tests/regression/golden/scenario_batch_v090_request.json
"""
import json
import requests
from pathlib import Path


BASE_URL = "http://localhost:8031"
GOLDEN_DIR = Path(__file__).parent / "golden"


def generate_batch_request():
    """Create a batch sizing request with 3 items."""
    return {
        "items": [
            {
                "item_id": "scenario_A",
                "request": {
                    "load_kw": [100, 120, 110, 90, 80, 100, 120, 130],
                    "pv_generation_kw": [0, 10, 50, 70, 80, 60, 30, 0],
                    "energy_price_pln_kwh": 0.8,
                }
            },
            {
                "item_id": "scenario_B",
                "request": {
                    "load_kw": [150, 180, 160, 140, 120, 150, 180, 200],
                    "pv_generation_kw": [0, 20, 80, 100, 120, 90, 50, 0],
                    "energy_price_pln_kwh": 0.9,
                }
            },
            {
                "item_id": "scenario_C",
                "request": {
                    "load_kw": [80, 90, 85, 75, 70, 80, 90, 100],
                    "pv_generation_kw": [0, 5, 30, 45, 50, 40, 20, 0],
                    "energy_price_pln_kwh": 0.75,
                }
            }
        ]
    }


def main():
    """Generate golden master files."""
    # Create request
    request = generate_batch_request()

    # Call batch endpoint
    print(f"Calling {BASE_URL}/sizing:batch ...")
    resp = requests.post(f"{BASE_URL}/sizing:batch", json=request)
    resp.raise_for_status()
    response = resp.json()

    # Save request
    request_file = GOLDEN_DIR / "scenario_batch_v090_request.json"
    with open(request_file, "w") as f:
        json.dump(request, f, indent=2)
    print(f"Saved request to {request_file}")

    # Save response
    response_file = GOLDEN_DIR / "scenario_batch_v090.json"
    with open(response_file, "w") as f:
        json.dump(response, f, indent=2)
    print(f"Saved response to {response_file}")

    # Print summary
    print(f"\nBatch summary:")
    print(f"  Total items: {response['summary']['total_items']}")
    print(f"  OK count: {response['summary']['ok_count']}")
    print(f"  Error count: {response['summary']['error_count']}")

    if response.get("portfolio_summary"):
        ps = response["portfolio_summary"]
        print(f"\nPortfolio summary:")
        print(f"  Total NPV: {ps['total_npv_pln']:.2f} PLN")
        print(f"  Avg NPV: {ps['avg_npv_pln']:.2f} PLN")
        print(f"  Optimal variant: {ps['portfolio_optimal_variant']}")

    print("\nDone!")


if __name__ == "__main__":
    main()

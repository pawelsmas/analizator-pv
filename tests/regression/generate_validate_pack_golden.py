#!/usr/bin/env python3
"""
Generate golden master files for v1.7.0 validate-pack API regression tests.

Usage:
    python tests/regression/generate_validate_pack_golden.py

Requires:
    - bess-dispatch service running on localhost:8031
"""

import json
import requests
from pathlib import Path

# API base URL
BASE_URL = "http://localhost:8031"

# Output directory
GOLDEN_DIR = Path(__file__).parent / "golden"


def generate_validate_pack_golden():
    """Generate golden master for validate-pack job."""
    print("Generating validate-pack golden files...")

    # Create validate-pack job with wait=true
    response = requests.post(
        f"{BASE_URL}/api/bess-dispatch/jobs/validate-pack",
        json={"pack": "baseline", "wait": True},
        timeout=120,
    )

    if response.status_code != 200:
        print(f"Failed to create validate-pack job: {response.status_code}")
        print(response.text)
        return

    job_response = response.json()
    print(f"Job response: status={job_response['status']}, "
          f"items={job_response.get('items_done', 0)}/{job_response.get('items_total', 0)}")

    # Save golden file
    golden_path = GOLDEN_DIR / "scenario_validate_pack_v170.json"
    with open(golden_path, "w", encoding="utf-8") as f:
        json.dump(job_response, f, indent=2, ensure_ascii=False)
    print(f"Saved: {golden_path}")


def generate_packs_list_golden():
    """Generate golden master for packs list."""
    print("Generating packs list golden file...")

    response = requests.get(f"{BASE_URL}/api/bess-dispatch/validation/packs")

    if response.status_code != 200:
        print(f"Failed to get packs list: {response.status_code}")
        print(response.text)
        return

    packs_response = response.json()
    print(f"Packs: {packs_response.get('packs', [])}")

    # Save golden file
    golden_path = GOLDEN_DIR / "scenario_packs_list_v170.json"
    with open(golden_path, "w", encoding="utf-8") as f:
        json.dump(packs_response, f, indent=2, ensure_ascii=False)
    print(f"Saved: {golden_path}")


def main():
    """Generate all v1.7.0 validate-pack golden files."""
    # Ensure golden directory exists
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)

    # Generate golden files
    generate_packs_list_golden()
    generate_validate_pack_golden()

    print("\nDone! Golden files generated.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Scenario validation runner for BESS sizing correctness tests.

Usage:
    python scripts/validate_scenarios.py                    # Run all scenarios
    python scripts/validate_scenarios.py baseline_stacked   # Run single scenario
    python scripts/validate_scenarios.py --list             # List available scenarios
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests


# Configuration
SCENARIOS_DIR = Path("docs/scenarios")
API_BASE_URL = os.environ.get("BESS_API_URL", "http://localhost:8031")
VALIDATE_ENDPOINT = f"{API_BASE_URL}/validate/sizing"


def load_scenario(scenario_path: Path) -> Dict:
    """Load scenario definition from JSON file."""
    with open(scenario_path) as f:
        return json.load(f)


def load_request(request_file: str) -> Dict:
    """Load sizing request from file path (relative to repo root)."""
    with open(request_file) as f:
        return json.load(f)


def run_validation(scenario: Dict) -> Tuple[bool, Dict]:
    """
    Run validation for a scenario.

    Returns:
        Tuple of (passed, response_data)
    """
    # Load sizing request
    request = load_request(scenario["request_file"])

    # Build validation request
    validate_req = {
        "request": request,
        "expected_kpis": scenario["expected_kpis"],
        "tolerances": scenario.get("tolerances"),
        "scenario_id": scenario["scenario_id"],
    }

    # Call API
    try:
        resp = requests.post(VALIDATE_ENDPOINT, json=validate_req, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        return data.get("passed", False), data
    except requests.RequestException as e:
        return False, {"error": str(e)}


def list_scenarios() -> List[Dict]:
    """List all available scenarios."""
    scenarios = []
    for f in SCENARIOS_DIR.glob("*.json"):
        try:
            scenario = load_scenario(f)
            scenarios.append({
                "file": f.name,
                "scenario_id": scenario.get("scenario_id", f.stem),
                "description": scenario.get("description", ""),
            })
        except Exception as e:
            print(f"Warning: Could not load {f}: {e}", file=sys.stderr)
    return scenarios


def find_scenario_file(scenario_id: str) -> Optional[Path]:
    """Find scenario file by ID or filename pattern."""
    # Try exact match first
    exact = SCENARIOS_DIR / f"{scenario_id}.json"
    if exact.exists():
        return exact

    # Try partial match
    for f in SCENARIOS_DIR.glob("*.json"):
        if scenario_id in f.stem:
            return f
        try:
            scenario = load_scenario(f)
            if scenario.get("scenario_id") == scenario_id:
                return f
        except Exception:
            pass

    return None


def format_diff(diff: Dict) -> str:
    """Format a single diff for display."""
    status = "PASS" if diff.get("pass") else "FAIL"
    field = diff["field"]
    expected = diff["expected"]
    actual = diff["actual"]
    abs_diff = diff["abs_diff"]

    if diff.get("rel_diff") is not None:
        rel_pct = diff["rel_diff"] * 100
        return f"  [{status}] {field}: expected={expected:.4f}, actual={actual:.4f}, diff={abs_diff:.4f} ({rel_pct:.2f}%)"
    else:
        return f"  [{status}] {field}: expected={expected:.4f}, actual={actual:.4f}, diff={abs_diff:.4f}"


def main():
    parser = argparse.ArgumentParser(description="Validate BESS sizing scenarios")
    parser.add_argument("scenario", nargs="?", help="Scenario ID or filename pattern to run")
    parser.add_argument("--list", action="store_true", help="List available scenarios")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    if args.list:
        scenarios = list_scenarios()
        if args.json:
            print(json.dumps(scenarios, indent=2))
        else:
            print("Available scenarios:")
            for s in scenarios:
                print(f"  {s['scenario_id']}: {s['description']}")
        return 0

    # Determine which scenarios to run
    if args.scenario:
        scenario_file = find_scenario_file(args.scenario)
        if not scenario_file:
            print(f"Error: Scenario '{args.scenario}' not found", file=sys.stderr)
            return 1
        scenario_files = [scenario_file]
    else:
        scenario_files = list(SCENARIOS_DIR.glob("*.json"))
        if not scenario_files:
            print("No scenarios found in docs/scenarios/", file=sys.stderr)
            return 1

    # Run validations
    results = []
    all_passed = True

    for f in scenario_files:
        try:
            scenario = load_scenario(f)
        except Exception as e:
            print(f"Error loading {f}: {e}", file=sys.stderr)
            results.append({"file": str(f), "error": str(e), "passed": False})
            all_passed = False
            continue

        scenario_id = scenario.get("scenario_id", f.stem)
        print(f"\nRunning: {scenario_id}")
        print(f"  {scenario.get('description', '')}")

        passed, data = run_validation(scenario)

        result = {
            "scenario_id": scenario_id,
            "file": str(f),
            "passed": passed,
            "run_id": data.get("run_id"),
            "failed_fields": data.get("failed_fields", []),
            "passed_fields": data.get("passed_fields", []),
        }
        results.append(result)

        if passed:
            print(f"  Result: PASS")
            if args.verbose:
                for diff in data.get("diffs", []):
                    print(format_diff(diff))
        else:
            all_passed = False
            print(f"  Result: FAIL")
            if "error" in data:
                print(f"  Error: {data['error']}")
            else:
                print(f"  Failed fields: {', '.join(data.get('failed_fields', []))}")
                if args.verbose or True:  # Always show failed diffs
                    for diff in data.get("diffs", []):
                        if not diff.get("pass"):
                            print(format_diff(diff))

    # Summary
    passed_count = sum(1 for r in results if r["passed"])
    total_count = len(results)

    print(f"\n{'='*60}")
    print(f"Summary: {passed_count}/{total_count} scenarios passed")

    if args.json:
        print(json.dumps({
            "passed": all_passed,
            "passed_count": passed_count,
            "total_count": total_count,
            "results": results,
        }, indent=2))

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())

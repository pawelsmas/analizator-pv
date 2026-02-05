#!/usr/bin/env python3
"""
Scenario validation runner for BESS sizing correctness tests.

Usage:
    python scripts/validate_scenarios.py                    # Run all scenarios
    python scripts/validate_scenarios.py baseline_stacked   # Run single scenario
    python scripts/validate_scenarios.py --list             # List available scenarios
    python scripts/validate_scenarios.py --pack docs/scenarios/packs/baseline.yml  # Run pack

v3.4.0 PR5: Added step-based scenario support with submit_job and wait_job actions.
"""

import argparse
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import requests

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore


# Configuration
SCENARIOS_DIR = Path("docs/scenarios")
PACKS_DIR = Path("docs/scenarios/packs")
API_BASE_URL = os.environ.get("BESS_API_URL", "http://localhost:8031")
VALIDATE_ENDPOINT = f"{API_BASE_URL}/validate/sizing"

# Job polling defaults
DEFAULT_POLL_INTERVAL = 1  # seconds
DEFAULT_TIMEOUT = 120  # seconds


def load_scenario(scenario_path: Path) -> Dict:
    """Load scenario definition from JSON file."""
    with open(scenario_path) as f:
        return json.load(f)


def load_request(request_file: str) -> Dict:
    """Load sizing request from file path (relative to repo root)."""
    with open(request_file) as f:
        return json.load(f)


def load_pack(pack_path: Path) -> Dict:
    """
    Load scenario pack from YAML file.

    Returns dict with 'name' and 'scenarios' list.
    """
    if yaml is None:
        raise ImportError("PyYAML is required for --pack support. Install with: pip install pyyaml")

    with open(pack_path) as f:
        return yaml.safe_load(f)


def parse_pack_scenarios(pack_data: Dict) -> List[str]:
    """Extract scenario IDs from pack data (legacy format)."""
    return pack_data.get("scenarios", [])


def get_scenario_files_from_pack(pack_path: Path) -> List[Path]:
    """
    Load pack and resolve scenario IDs to file paths.

    Returns list of scenario file paths in pack order.
    """
    pack_data = load_pack(pack_path)
    scenario_ids = parse_pack_scenarios(pack_data)

    scenario_files = []
    for scenario_id in scenario_ids:
        scenario_file = find_scenario_file(scenario_id)
        if scenario_file:
            scenario_files.append(scenario_file)
        else:
            print(f"Warning: Scenario '{scenario_id}' from pack not found", file=sys.stderr)

    return scenario_files


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


# -------------------------------------------------------------------------
# Step-based scenario execution (v3.4.0 PR5)
# -------------------------------------------------------------------------

class StepContext:
    """Context for step-based scenario execution."""

    def __init__(self, api_base_url: str, poll_interval: int = DEFAULT_POLL_INTERVAL, timeout: int = DEFAULT_TIMEOUT):
        self.api_base_url = api_base_url.rstrip("/")
        self.poll_interval = poll_interval
        self.timeout = timeout
        self.variables: Dict[str, Any] = {
            "RANDOM_SUFFIX": str(uuid.uuid4())[:8],
        }
        # Load from environment
        for key, value in os.environ.items():
            if key.startswith("TEST_") or key.startswith("BESS_"):
                self.variables[key] = value

    def resolve_variable(self, text: str) -> str:
        """Resolve ${var} placeholders in text."""
        if not isinstance(text, str):
            return text

        def replace_var(match):
            var_expr = match.group(1)
            # Handle default value syntax: ${VAR:-default}
            if ":-" in var_expr:
                var_name, default = var_expr.split(":-", 1)
                return self.variables.get(var_name, default)
            return self.variables.get(var_expr, match.group(0))

        return re.sub(r"\$\{([^}]+)\}", replace_var, text)

    def resolve_variables_in_dict(self, obj: Any) -> Any:
        """Recursively resolve variables in dict/list structures."""
        if isinstance(obj, str):
            return self.resolve_variable(obj)
        elif isinstance(obj, dict):
            return {k: self.resolve_variables_in_dict(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self.resolve_variables_in_dict(v) for v in obj]
        return obj

    def capture_value(self, data: Dict, path: str) -> Any:
        """Extract value from response using JSONPath-like syntax ($.key.subkey)."""
        if not path.startswith("$."):
            return data.get(path)

        keys = path[2:].split(".")
        value = data
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            elif isinstance(value, list) and key.isdigit():
                value = value[int(key)]
            else:
                return None
        return value


def execute_http_step(ctx: StepContext, step: Dict) -> Tuple[bool, Dict]:
    """Execute an HTTP request step."""
    method = step.get("method", "GET").upper()
    endpoint = ctx.resolve_variable(step.get("endpoint", ""))
    url = f"{ctx.api_base_url}{endpoint}"
    body = ctx.resolve_variables_in_dict(step.get("body"))
    headers = ctx.resolve_variables_in_dict(step.get("headers", {}))

    try:
        if method == "GET":
            resp = requests.get(url, headers=headers, timeout=30)
        elif method == "POST":
            resp = requests.post(url, json=body, headers=headers, timeout=30)
        elif method == "PUT":
            resp = requests.put(url, json=body, headers=headers, timeout=30)
        elif method == "DELETE":
            resp = requests.delete(url, headers=headers, timeout=30)
        else:
            return False, {"error": f"Unsupported HTTP method: {method}"}

        result = {
            "status_code": resp.status_code,
            "headers": dict(resp.headers),
        }

        try:
            result["body"] = resp.json()
        except Exception:
            result["body"] = resp.text

        return True, result

    except requests.RequestException as e:
        return False, {"error": str(e)}


def execute_submit_job_step(ctx: StepContext, step: Dict) -> Tuple[bool, Dict]:
    """Execute a submit_job step (POST /jobs)."""
    endpoint = ctx.resolve_variable(step.get("endpoint", "/api/bess-dispatch/jobs"))
    payload = ctx.resolve_variables_in_dict(step.get("payload", {}))

    url = f"{ctx.api_base_url}{endpoint}"

    try:
        resp = requests.post(url, json=payload, timeout=30)
        result = {
            "status_code": resp.status_code,
        }

        try:
            result["body"] = resp.json()
        except Exception:
            result["body"] = resp.text

        return True, result

    except requests.RequestException as e:
        return False, {"error": str(e)}


def execute_wait_job_step(ctx: StepContext, step: Dict) -> Tuple[bool, Dict]:
    """
    Execute a wait_job step - poll job status until completion.

    Polls GET /jobs/{job_id} until status is succeeded, failed, or cancelled,
    or timeout is reached.
    """
    job_id = ctx.resolve_variable(step.get("job_id", ""))
    timeout = step.get("timeout_seconds", ctx.timeout)
    poll_interval = step.get("poll_interval_seconds", ctx.poll_interval)

    if not job_id:
        return False, {"error": "job_id is required for wait_job"}

    url = f"{ctx.api_base_url}/api/bess-dispatch/jobs/{job_id}"
    start_time = time.time()
    last_status = None

    while True:
        elapsed = time.time() - start_time
        if elapsed >= timeout:
            return False, {
                "error": f"Timeout waiting for job {job_id} after {timeout}s",
                "last_status": last_status,
            }

        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code != 200:
                return False, {
                    "error": f"Failed to get job status: HTTP {resp.status_code}",
                }

            data = resp.json()
            last_status = data.get("status")

            # Check for terminal states
            if last_status in ("succeeded", "failed", "cancelled"):
                return True, {
                    "status": last_status,
                    "job": data,
                }

            # Still running, wait and poll again
            time.sleep(poll_interval)

        except requests.RequestException as e:
            return False, {"error": f"Request failed: {e}"}


def check_expectations(result: Dict, expect: Dict) -> Tuple[bool, List[str]]:
    """Check if result matches expectations."""
    errors = []

    # Check status code
    if "status_code" in expect:
        expected_code = expect["status_code"]
        actual_code = result.get("status_code")
        if actual_code != expected_code:
            errors.append(f"Expected status_code {expected_code}, got {actual_code}")

    # Check status (for wait_job)
    if "status" in expect:
        expected_status = expect["status"]
        actual_status = result.get("status")
        if actual_status != expected_status:
            errors.append(f"Expected status '{expected_status}', got '{actual_status}'")

    # Check body fields
    if "body" in expect and isinstance(expect["body"], dict):
        body = result.get("body", {})
        if isinstance(body, dict):
            for key, expected_value in expect["body"].items():
                actual_value = body.get(key)
                # Handle array expectation (just check it's a list)
                if isinstance(expected_value, list) and len(expected_value) == 0:
                    if not isinstance(actual_value, list):
                        errors.append(f"Expected body.{key} to be array, got {type(actual_value).__name__}")
                # Handle nested dict
                elif isinstance(expected_value, dict):
                    if not isinstance(actual_value, dict):
                        errors.append(f"Expected body.{key} to be object, got {type(actual_value).__name__}")
                    else:
                        for subkey, subval in expected_value.items():
                            if actual_value.get(subkey) != subval:
                                errors.append(f"Expected body.{key}.{subkey}={subval}, got {actual_value.get(subkey)}")
                elif actual_value != expected_value:
                    errors.append(f"Expected body.{key}={expected_value}, got {actual_value}")

    # Check headers
    if "headers" in expect and isinstance(expect["headers"], dict):
        headers = result.get("headers", {})
        for key, expected_value in expect["headers"].items():
            # Headers are case-insensitive
            actual_value = None
            for h_key, h_val in headers.items():
                if h_key.lower() == key.lower():
                    actual_value = h_val
                    break
            if expected_value not in (actual_value or ""):
                errors.append(f"Expected header {key} to contain '{expected_value}', got '{actual_value}'")

    return len(errors) == 0, errors


def run_step_scenario(scenario: Dict, ctx: StepContext, verbose: bool = False) -> Tuple[bool, Dict]:
    """
    Run a step-based scenario.

    Returns:
        Tuple of (passed, result_data)
    """
    scenario_id = scenario.get("id", "unknown")
    steps = scenario.get("steps", [])

    results = []
    all_passed = True

    for i, step in enumerate(steps):
        action = step.get("action", "http")
        step_name = f"Step {i+1}: {action}"

        if verbose:
            print(f"    {step_name}...")

        # Execute step based on action type
        if action == "http":
            success, result = execute_http_step(ctx, step)
        elif action == "submit_job":
            success, result = execute_submit_job_step(ctx, step)
        elif action == "wait_job":
            success, result = execute_wait_job_step(ctx, step)
        else:
            success = False
            result = {"error": f"Unknown action: {action}"}

        if not success:
            all_passed = False
            results.append({
                "step": i + 1,
                "action": action,
                "passed": False,
                "error": result.get("error", "Step execution failed"),
            })
            break

        # Check expectations
        expect = step.get("expect", {})
        if expect:
            passed, errors = check_expectations(result, expect)
            if not passed:
                all_passed = False
                results.append({
                    "step": i + 1,
                    "action": action,
                    "passed": False,
                    "errors": errors,
                })
                if verbose:
                    for err in errors:
                        print(f"      FAIL: {err}")
                break

        # Capture variables
        capture = step.get("capture", {})
        if capture and isinstance(result.get("body"), dict):
            for var_name, json_path in capture.items():
                value = ctx.capture_value(result["body"], json_path)
                if value is not None:
                    ctx.variables[var_name] = value
                    if verbose:
                        print(f"      Captured {var_name}={value}")

        results.append({
            "step": i + 1,
            "action": action,
            "passed": True,
        })

    return all_passed, {
        "scenario_id": scenario_id,
        "passed": all_passed,
        "steps": results,
    }


def is_step_based_pack(pack_data: Dict) -> bool:
    """Check if pack uses step-based scenarios (v3.4.0 format)."""
    scenarios = pack_data.get("scenarios", [])
    if scenarios and isinstance(scenarios[0], dict):
        return "steps" in scenarios[0]
    return False


def run_step_pack(pack_path: Path, verbose: bool = False) -> Tuple[bool, List[Dict]]:
    """
    Run a step-based scenario pack.

    Returns:
        Tuple of (all_passed, results)
    """
    pack_data = load_pack(pack_path)
    pack_name = pack_data.get("name", pack_path.stem)

    print(f"Running step pack: {pack_name}")

    # Get config
    config = pack_data.get("config", {})
    api_base_url = os.environ.get("BESS_API_URL", config.get("api_base_url", API_BASE_URL))
    poll_interval = config.get("poll_interval_seconds", DEFAULT_POLL_INTERVAL)
    timeout = config.get("timeout_seconds", DEFAULT_TIMEOUT)

    ctx = StepContext(
        api_base_url=api_base_url,
        poll_interval=poll_interval,
        timeout=timeout,
    )

    scenarios = pack_data.get("scenarios", [])
    results = []
    all_passed = True

    for scenario in scenarios:
        scenario_id = scenario.get("id", "unknown")
        description = scenario.get("description", "")

        print(f"\nRunning: {scenario_id}")
        if description:
            print(f"  {description}")

        passed, result = run_step_scenario(scenario, ctx, verbose=verbose)
        results.append(result)

        if passed:
            print(f"  Result: PASS")
        else:
            all_passed = False
            print(f"  Result: FAIL")
            if "steps" in result:
                for step_result in result["steps"]:
                    if not step_result.get("passed"):
                        errors = step_result.get("errors", [step_result.get("error", "Unknown error")])
                        for err in errors:
                            print(f"    - {err}")

    return all_passed, results


def main():
    parser = argparse.ArgumentParser(description="Validate BESS sizing scenarios")
    parser.add_argument("scenario", nargs="?", help="Scenario ID or filename pattern to run")
    parser.add_argument("--list", action="store_true", help="List available scenarios")
    parser.add_argument("--pack", type=str, help="Path to scenario pack YAML file")
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

    # Handle pack with step-based scenarios
    if args.pack:
        pack_path = Path(args.pack)
        if not pack_path.exists():
            print(f"Error: Pack file '{args.pack}' not found", file=sys.stderr)
            return 1

        try:
            pack_data = load_pack(pack_path)
        except ImportError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

        # Check if step-based pack
        if is_step_based_pack(pack_data):
            all_passed, results = run_step_pack(pack_path, verbose=args.verbose)

            # Summary
            passed_count = sum(1 for r in results if r.get("passed"))
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

        # Legacy pack format
        print(f"Running pack: {pack_data.get('name', pack_path.stem)}")
        scenario_files = get_scenario_files_from_pack(pack_path)

        if not scenario_files:
            print("No valid scenarios found in pack", file=sys.stderr)
            return 1

    elif args.scenario:
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

    # Run validations (legacy format)
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

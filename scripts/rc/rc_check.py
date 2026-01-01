#!/usr/bin/env python3
"""
Release Candidate check script (v2.6.0 PR5).

Runs all validation checks required before creating an RC:
1. Unit tests
2. Smoke tests (if backend running)
3. Contract tests (if backend running)
4. Contract drift check
5. Scenario freeze check

Usage:
    python scripts/rc/rc_check.py [--skip-backend]

Exit codes:
    0 - All checks passed
    1 - One or more checks failed
"""

import subprocess
import sys
import os
import argparse
from pathlib import Path
from typing import List, Tuple


# ANSI colors for output
class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


def print_header(msg: str) -> None:
    """Print a section header."""
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'=' * 60}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{msg}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'=' * 60}{Colors.RESET}\n")


def print_result(name: str, passed: bool, details: str = "") -> None:
    """Print a check result."""
    if passed:
        status = f"{Colors.GREEN}[PASS]{Colors.RESET}"
    else:
        status = f"{Colors.RED}[FAIL]{Colors.RESET}"
    print(f"{status} {name}")
    if details and not passed:
        print(f"       {Colors.YELLOW}{details}{Colors.RESET}")


def run_command(cmd: List[str], cwd: str = None, timeout: int = 300) -> Tuple[bool, str]:
    """Run a command and return (success, output)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
        )
        output = result.stdout + result.stderr
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, "Command timed out"
    except Exception as e:
        return False, str(e)


def check_backend_running() -> bool:
    """Check if backend is running on localhost:8031."""
    try:
        import urllib.request
        req = urllib.request.urlopen("http://localhost:8031/health", timeout=5)
        return req.status == 200
    except Exception:
        return False


def run_unit_tests(project_root: Path) -> Tuple[bool, str]:
    """Run unit tests."""
    cmd = [
        sys.executable, "-m", "pytest",
        str(project_root / "tests" / "unit"),
        "-q", "--tb=short"
    ]
    return run_command(cmd, cwd=str(project_root), timeout=120)


def run_smoke_tests(project_root: Path) -> Tuple[bool, str]:
    """Run smoke tests (requires backend)."""
    # Check if backend is running
    if not check_backend_running():
        return True, "Skipped (backend not running)"

    cmd = [
        sys.executable, "-m", "pytest",
        str(project_root / "tests" / "smoke"),
        "-q", "--tb=short"
    ]
    return run_command(cmd, cwd=str(project_root), timeout=60)


def run_contract_tests(project_root: Path) -> Tuple[bool, str]:
    """Run contract tests (requires backend)."""
    # Check if backend is running
    if not check_backend_running():
        return True, "Skipped (backend not running)"

    cmd = [
        sys.executable, "-m", "pytest",
        str(project_root / "tests" / "contract"),
        "-q", "--tb=short"
    ]
    return run_command(cmd, cwd=str(project_root), timeout=180)


def run_contract_drift_check(project_root: Path) -> Tuple[bool, str]:
    """Check for contract schema drift."""
    script = project_root / "scripts" / "contracts" / "export_contracts.py"
    if not script.exists():
        return True, "Skipped (script not found)"

    cmd = [sys.executable, str(script), "--check"]
    return run_command(cmd, cwd=str(project_root), timeout=30)


def run_scenario_freeze_check(project_root: Path) -> Tuple[bool, str]:
    """Check for scenario freeze violations."""
    script = project_root / "scripts" / "check_scenario_updates.py"
    if not script.exists():
        return True, "Skipped (script not found)"

    cmd = [sys.executable, str(script)]
    return run_command(cmd, cwd=str(project_root), timeout=30)


def check_deprecations_registry(project_root: Path) -> Tuple[bool, str]:
    """Validate deprecations.json exists and is valid."""
    deprecations_file = project_root / "docs" / "api" / "deprecations.json"
    if not deprecations_file.exists():
        return False, "deprecations.json not found"

    try:
        import json
        with open(deprecations_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "items" not in data:
            return False, "Invalid format: missing 'items'"
        return True, f"{len(data['items'])} deprecations tracked"
    except Exception as e:
        return False, str(e)


def run_no_legacy_guard(project_root: Path) -> Tuple[bool, str]:
    """Run no-legacy guard to check for legacy references (v2.8.0)."""
    script = project_root / "scripts" / "guards" / "check_no_legacy.py"
    if not script.exists():
        return True, "Skipped (guard not found)"

    cmd = [sys.executable, str(script)]
    return run_command(cmd, cwd=str(project_root), timeout=60)


def check_clean_contract_pack(project_root: Path) -> Tuple[bool, str]:
    """Verify clean contract pack exists (v2.8.0)."""
    pack_file = project_root / "docs" / "scenarios" / "packs" / "clean_contract.yml"
    if not pack_file.exists():
        return False, "clean_contract.yml not found"

    try:
        import yaml
        with open(pack_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if "name" not in data or data["name"] != "clean_contract":
            return False, "Invalid pack: missing 'name' or wrong name"
        if "validation" not in data:
            return False, "Invalid pack: missing 'validation'"
        return True, f"Pack v{data.get('version', 'unknown')} with {len(data.get('scenarios', []))} scenarios"
    except Exception as e:
        return False, str(e)


def main() -> int:
    """Run all RC checks."""
    parser = argparse.ArgumentParser(description="RC check script")
    parser.add_argument(
        "--skip-backend",
        action="store_true",
        help="Skip tests that require backend"
    )
    args = parser.parse_args()

    # Find project root
    project_root = Path(__file__).parent.parent.parent

    print_header("Release Candidate Check")
    print(f"Project root: {project_root}")

    if args.skip_backend:
        print(f"{Colors.YELLOW}Note: Backend tests will be skipped{Colors.RESET}")

    results = []

    # 1. Unit tests
    print_header("1. Unit Tests")
    passed, output = run_unit_tests(project_root)
    results.append(("Unit tests", passed))
    print_result("Unit tests", passed, output.split("\n")[-2] if not passed else "")

    # 2. Smoke tests
    print_header("2. Smoke Tests")
    if args.skip_backend:
        print_result("Smoke tests", True, "Skipped (--skip-backend)")
        results.append(("Smoke tests", True))
    else:
        passed, output = run_smoke_tests(project_root)
        results.append(("Smoke tests", passed))
        if "Skipped" in output:
            print_result("Smoke tests", True, output)
        else:
            print_result("Smoke tests", passed, output.split("\n")[-2] if not passed else "")

    # 3. Contract tests
    print_header("3. Contract Tests")
    if args.skip_backend:
        print_result("Contract tests", True, "Skipped (--skip-backend)")
        results.append(("Contract tests", True))
    else:
        passed, output = run_contract_tests(project_root)
        results.append(("Contract tests", passed))
        if "Skipped" in output:
            print_result("Contract tests", True, output)
        else:
            print_result("Contract tests", passed, output.split("\n")[-2] if not passed else "")

    # 4. Contract drift check
    print_header("4. Contract Drift Check")
    passed, output = run_contract_drift_check(project_root)
    results.append(("Contract drift check", passed))
    print_result("Contract drift check", passed, output if not passed else "")

    # 5. Scenario freeze check
    print_header("5. Scenario Freeze Check")
    passed, output = run_scenario_freeze_check(project_root)
    results.append(("Scenario freeze check", passed))
    print_result("Scenario freeze check", passed, output if not passed else "")

    # 6. Deprecations registry
    print_header("6. Deprecations Registry")
    passed, output = check_deprecations_registry(project_root)
    results.append(("Deprecations registry", passed))
    print_result("Deprecations registry", passed, output if not passed else output)

    # 7. No-legacy guard (v2.8.0)
    print_header("7. No-Legacy Guard")
    passed, output = run_no_legacy_guard(project_root)
    results.append(("No-legacy guard", passed))
    if "Skipped" in output:
        print_result("No-legacy guard", True, output)
    else:
        print_result("No-legacy guard", passed, output if not passed else "No legacy references in critical paths")

    # 8. Clean contract pack (v2.8.0)
    print_header("8. Clean Contract Pack")
    passed, output = check_clean_contract_pack(project_root)
    results.append(("Clean contract pack", passed))
    print_result("Clean contract pack", passed, output if not passed else output)

    # Summary
    print_header("Summary")
    all_passed = all(r[1] for r in results)

    for name, passed in results:
        print_result(name, passed)

    print()
    if all_passed:
        print(f"{Colors.GREEN}{Colors.BOLD}All RC checks passed!{Colors.RESET}")
        return 0
    else:
        print(f"{Colors.RED}{Colors.BOLD}Some RC checks failed.{Colors.RESET}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

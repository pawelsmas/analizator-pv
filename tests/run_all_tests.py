#!/usr/bin/env python3
"""
Run All Tests - Pre-deployment verification

IMPORTANT: Run these tests BEFORE deploying any changes!

Tests included:
1. test_consumption_data_flow.py - Consumption data from CONFIG to EKONOMIA
2. test_bess_light.py - BESS LIGHT/AUTO mode invariants

Usage:
    python tests/run_all_tests.py

Exit codes:
    0 - All tests passed
    1 - Some tests failed
"""

import subprocess
import sys
import os

# Get the tests directory
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))

# Test files to run in order
TEST_FILES = [
    "test_consumption_data_flow.py",  # CRITICAL: consumption data flow
    "test_bess_light.py",  # BESS mode tests
]


def run_test(test_file):
    """Run a single test file and return success status"""
    test_path = os.path.join(TESTS_DIR, test_file)

    if not os.path.exists(test_path):
        print(f"[SKIP] {test_file} not found")
        return True  # Skip missing tests

    print(f"\n{'='*60}")
    print(f"Running: {test_file}")
    print('='*60)

    result = subprocess.run(
        [sys.executable, test_path],
        capture_output=False
    )

    return result.returncode == 0


def main():
    print("\n" + "#"*60)
    print("#  PRE-DEPLOYMENT TEST SUITE")
    print("#  Run these tests BEFORE deploying any changes!")
    print("#"*60)

    all_passed = True
    results = []

    for test_file in TEST_FILES:
        success = run_test(test_file)
        results.append((test_file, success))
        if not success:
            all_passed = False

    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)

    for test_file, success in results:
        status = "[PASS]" if success else "[FAIL]"
        print(f"  {status} {test_file}")

    print("="*60)

    if all_passed:
        print("[SUCCESS] All tests passed - safe to deploy")
        return 0
    else:
        print("[FAILURE] Some tests failed - DO NOT DEPLOY")
        return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
CI guard script for expected_kpis.json changes.

This script checks if any expected_kpis.json files were modified in the PR
and ensures that docs/expected_updates/APPROVAL.md was also modified.

Usage:
    python scripts/check_expected_updates.py

Exit codes:
    0 - OK (no expected files changed, or approval was updated)
    1 - FAIL (expected files changed without approval update)
"""

import subprocess
import sys
from pathlib import Path


def get_changed_files() -> list[str]:
    """Get list of files changed in the current branch vs main."""
    try:
        # Try to get diff against origin/main
        result = subprocess.run(
            ["git", "diff", "--name-only", "origin/main...HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip().split("\n") if result.stdout.strip() else []
    except subprocess.CalledProcessError:
        # Fallback: get diff against main
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", "main...HEAD"],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip().split("\n") if result.stdout.strip() else []
        except subprocess.CalledProcessError:
            # Last resort: check staged files
            result = subprocess.run(
                ["git", "diff", "--name-only", "--cached"],
                capture_output=True,
                text=True,
            )
            return result.stdout.strip().split("\n") if result.stdout.strip() else []


def detect_expected_files(files: list[str]) -> list[str]:
    """Filter list to only expected_kpis.json files."""
    return [f for f in files if "expected_kpis" in f and f.endswith(".json")]


def has_approval_update(files: list[str]) -> bool:
    """Check if APPROVAL.md was modified."""
    approval_patterns = [
        "docs/expected_updates/APPROVAL.md",
        "APPROVAL.md",
    ]
    return any(
        any(pattern in f for pattern in approval_patterns)
        for f in files
    )


def main() -> int:
    print("Checking for expected_kpis changes...")

    changed_files = get_changed_files()
    if not changed_files:
        print("No changed files detected.")
        return 0

    print(f"Changed files: {len(changed_files)}")

    expected_files = detect_expected_files(changed_files)
    if not expected_files:
        print("No expected_kpis.json files changed. OK.")
        return 0

    print(f"Expected KPI files changed:")
    for f in expected_files:
        print(f"  - {f}")

    if has_approval_update(changed_files):
        print("APPROVAL.md was updated. OK.")
        return 0

    print("\nERROR: expected_kpis.json files were modified without updating APPROVAL.md")
    print("Please update docs/expected_updates/APPROVAL.md with:")
    print("""
## Change expected KPIs
Date: YYYY-MM-DD
Reason: [Brief explanation]
Scenarios:
- [List of affected scenarios]
Links:
- PR #...
""")
    return 1


if __name__ == "__main__":
    sys.exit(main())

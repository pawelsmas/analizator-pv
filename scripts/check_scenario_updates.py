#!/usr/bin/env python3
"""
CI guard script for scenario configuration changes (v2.6.0 PR2).

This script checks if any scenario request/tolerances/packs files were modified
in the PR and ensures that docs/scenario_updates/APPROVAL.md was also modified.

Protected files:
- docs/scenarios/**/request.json
- docs/scenarios/**/tolerances.json
- docs/scenarios/packs/*.yml

Usage:
    python scripts/check_scenario_updates.py

Exit codes:
    0 - OK (no protected files changed, or approval was updated)
    1 - FAIL (protected files changed without approval update)
"""

import subprocess
import sys
from pathlib import Path
from typing import List


# Patterns for protected scenario files
PROTECTED_PATTERNS = [
    "request.json",
    "tolerances.json",
]

PROTECTED_DIRS = [
    "docs/scenarios/",
]

PACKS_DIR = "docs/scenarios/packs/"


def get_changed_files() -> List[str]:
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


def is_scenario_request_file(filepath: str) -> bool:
    """Check if file is a scenario request.json file."""
    return (
        any(filepath.startswith(d) for d in PROTECTED_DIRS)
        and filepath.endswith("request.json")
    )


def is_scenario_tolerances_file(filepath: str) -> bool:
    """Check if file is a scenario tolerances.json file."""
    return (
        any(filepath.startswith(d) for d in PROTECTED_DIRS)
        and filepath.endswith("tolerances.json")
    )


def is_pack_file(filepath: str) -> bool:
    """Check if file is a pack configuration file."""
    return (
        filepath.startswith(PACKS_DIR)
        and filepath.endswith(".yml")
    )


def detect_protected_files(files: List[str]) -> List[str]:
    """Filter list to only protected scenario files."""
    protected = []
    for f in files:
        if is_scenario_request_file(f):
            protected.append(f)
        elif is_scenario_tolerances_file(f):
            protected.append(f)
        elif is_pack_file(f):
            protected.append(f)
    return protected


def has_approval_update(files: List[str]) -> bool:
    """Check if scenario APPROVAL.md was modified."""
    approval_patterns = [
        "docs/scenario_updates/APPROVAL.md",
    ]
    return any(
        any(pattern in f for pattern in approval_patterns)
        for f in files
    )


def main() -> int:
    print("Checking for scenario configuration changes...")

    changed_files = get_changed_files()
    if not changed_files:
        print("No changed files detected.")
        return 0

    print(f"Changed files: {len(changed_files)}")

    protected_files = detect_protected_files(changed_files)
    if not protected_files:
        print("No protected scenario files changed. OK.")
        return 0

    print(f"Protected scenario files changed:")
    for f in protected_files:
        print(f"  - {f}")

    if has_approval_update(changed_files):
        print("docs/scenario_updates/APPROVAL.md was updated. OK.")
        return 0

    print("\nERROR: Scenario configuration files were modified without updating APPROVAL.md")
    print("Please update docs/scenario_updates/APPROVAL.md with:")
    print("""
## [Description]
Date: YYYY-MM-DD
Reason: [Brief explanation of why scenarios needed to change]
Scenarios:
- [List of affected scenarios]
Changes:
- [What was changed]
Links:
- PR #...
""")
    return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
CI guard for deprecations.json changes (v2.7.0 PR5).

This script validates that:
1. deprecations.json is valid JSON
2. All required fields are present
3. No duplicate entries
4. Status values are valid
5. Version format is correct

Usage:
    python scripts/deprecations/ci_check.py

Exit codes:
    0 - All checks passed
    1 - Validation errors found
"""

import json
import sys
from pathlib import Path
from typing import List, Tuple


def find_deprecations_file() -> Path:
    """Find deprecations.json file."""
    possible_paths = [
        Path(__file__).parent.parent.parent / "docs" / "api" / "deprecations.json",
        Path("docs/api/deprecations.json"),
        Path("/app/docs/api/deprecations.json"),
    ]
    for p in possible_paths:
        if p.exists():
            return p
    raise FileNotFoundError("deprecations.json not found")


def validate_deprecations(data: dict) -> Tuple[List[str], List[str]]:
    """
    Validate deprecations data.

    Returns:
        Tuple of (errors, warnings)
    """
    errors = []
    warnings = []

    # Check top-level required fields
    if "version" not in data:
        errors.append("Missing required field: 'version'")
    if "items" not in data:
        errors.append("Missing required field: 'items'")
    if "last_updated" not in data:
        warnings.append("Missing field: 'last_updated'")
    if "sunset_date" not in data:
        warnings.append("Missing field: 'sunset_date'")

    # Validate version format
    version = data.get("version", "")
    if version:
        parts = version.split(".")
        if len(parts) < 2:
            errors.append(f"Invalid version format: {version} (expected semver)")

    # Validate items
    items = data.get("items", [])
    if not isinstance(items, list):
        errors.append("'items' must be an array")
        return errors, warnings

    fields_seen = set()
    required_item_fields = ["field", "location", "status", "since", "remove_in"]
    valid_statuses = ["deprecated", "warning", "removed"]

    for i, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"Item {i}: Must be an object")
            continue

        # Check required fields
        for field in required_item_fields:
            if field not in item:
                errors.append(f"Item {i}: Missing required field '{field}'")

        # Get field name for better error messages
        field_name = item.get("field", f"item_{i}")

        # Check for duplicates
        if field_name in fields_seen:
            errors.append(f"Duplicate field: {field_name}")
        fields_seen.add(field_name)

        # Validate status
        status = item.get("status", "")
        if status and status not in valid_statuses:
            errors.append(f"{field_name}: Invalid status '{status}' (must be one of {valid_statuses})")

        # Validate version strings
        since = item.get("since", "")
        if since and not since.startswith("v"):
            warnings.append(f"{field_name}: 'since' should start with 'v' (got: {since})")

        remove_in = item.get("remove_in", "")
        if remove_in and not remove_in.startswith("v"):
            warnings.append(f"{field_name}: 'remove_in' should start with 'v' (got: {remove_in})")

        # Check replacement is provided
        if "replacement" not in item:
            warnings.append(f"{field_name}: Missing 'replacement' field")

    return errors, warnings


def main():
    print("=" * 60)
    print("Deprecations CI Check")
    print("=" * 60)

    try:
        path = find_deprecations_file()
        print(f"Found: {path}")
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        print("JSON: Valid ✓")
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON - {e}")
        sys.exit(1)

    errors, warnings = validate_deprecations(data)

    print(f"Version: {data.get('version', 'unknown')}")
    print(f"Items: {len(data.get('items', []))}")
    print("")

    if errors:
        print("ERRORS:")
        for e in errors:
            print(f"  ❌ {e}")
        print("")

    if warnings:
        print("WARNINGS:")
        for w in warnings:
            print(f"  ⚠️ {w}")
        print("")

    if errors:
        print("❌ CI Check FAILED")
        sys.exit(1)
    else:
        print("✅ CI Check PASSED")
        sys.exit(0)


if __name__ == "__main__":
    main()

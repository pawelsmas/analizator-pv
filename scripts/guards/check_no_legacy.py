#!/usr/bin/env python3
"""
CI guard: No legacy references in new code (v2.8.0 PR3).

Scans critical paths for compat=legacy usage that should have been migrated.
Focus on ensuring new code uses clean API patterns.

Usage:
    python scripts/guards/check_no_legacy.py [--strict]

Exit codes:
    0: No critical legacy references found
    1: Legacy references found (or error)

The guard checks for:
1. compat=legacy in frontend code (should use clean)
2. compat=legacy in new test files (should test clean by default)
3. New files using deprecated response field names directly (export_revenue_pln, etc.)

Files that are allowed to reference legacy patterns:
- legacy_adapter.py (the adapter itself)
- compat_mode.py (mode switching logic)
- test_legacy_adapter.py (legacy adapter tests)
- test_default_compat_clean.py (compat mode tests)
- docs/api/* (deprecation documentation)
- docs/DEPRECATIONS.md (migration guide)
"""

import argparse
import re
import sys
from pathlib import Path
from typing import List, Set, Tuple


# Critical patterns that indicate compat=legacy usage
CRITICAL_LEGACY_PATTERNS = [
    # compat=legacy in code (not allowed in frontend or new tests)
    r"compat\s*=\s*[\"']?legacy[\"']?",
    r'compat:\s*["\']legacy["\']',
    r"\?compat=legacy",
]

# Response fields that are deprecated (only for strict mode)
DEPRECATED_RESPONSE_FIELDS = [
    r'\["export_revenue_pln"\]',  # Direct dict access
    r"\.export_revenue_pln\b",  # Attribute access
    r'data\.get\(["\']export_revenue_pln',  # dict.get() access
]

# Paths that MUST NOT contain legacy references (except in allowed files)
CRITICAL_PATHS = {
    "services/frontend-bess/",  # Frontend must use clean API
}

# Files that are ALLOWED to contain legacy references
ALLOWED_FILES = {
    # The adapter itself
    "services/bess-dispatch/legacy_adapter.py",
    "services/bess-dispatch/compat_mode.py",
    # Test files that specifically test legacy behavior
    "tests/unit/test_legacy_adapter.py",
    "tests/unit/test_default_compat_clean.py",
    "tests/contract/test_legacy_adapter.py",
    "tests/contract/test_default_compat_is_clean.py",
    # This guard script itself
    "scripts/guards/check_no_legacy.py",
}

# Path prefixes to skip entirely (not critical paths)
SKIP_PREFIXES = {
    ".claude/",
    "docs/",
    "monitoring/grafana/",
    "scripts/deprecations/",
}

# Directories to skip
SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "dist",
    "build",
    ".venv",
    "venv",
    "env",
}


def is_critical_path(path: Path, root: Path) -> bool:
    """Check if path is in a critical path that must not contain legacy."""
    relative = str(path.relative_to(root)).replace("\\", "/")
    for critical in CRITICAL_PATHS:
        if relative.startswith(critical):
            return True
    return False


def is_allowed(path: Path, root: Path) -> bool:
    """Check if path is allowed to contain legacy references."""
    relative = str(path.relative_to(root)).replace("\\", "/")

    # Check exact matches
    if relative in ALLOWED_FILES:
        return True

    # Check skip prefixes
    for prefix in SKIP_PREFIXES:
        if relative.startswith(prefix):
            return True

    return False


def should_skip_dir(dir_name: str) -> bool:
    """Check if directory should be skipped."""
    return dir_name in SKIP_DIRS


def scan_file(file_path: Path, patterns: List[re.Pattern]) -> List[Tuple[int, str, str]]:
    """
    Scan a file for legacy patterns.

    Returns list of (line_number, line_content, matched_pattern) tuples.
    """
    violations = []

    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            for line_num, line in enumerate(f, 1):
                for pattern in patterns:
                    if pattern.search(line):
                        violations.append((line_num, line.rstrip(), pattern.pattern))
                        break  # Only report first match per line
    except Exception as e:
        print(f"Warning: Could not read {file_path}: {e}", file=sys.stderr)

    return violations


def scan_critical_paths(root: Path, strict: bool = False) -> List[Tuple[Path, int, str, str]]:
    """
    Scan critical paths for legacy patterns.

    Args:
        root: Root directory
        strict: If True, also check for deprecated field access patterns

    Returns:
        List of (file_path, line_number, line_content, pattern) tuples
    """
    patterns = CRITICAL_LEGACY_PATTERNS.copy()
    if strict:
        patterns.extend(DEPRECATED_RESPONSE_FIELDS)

    compiled = [re.compile(p, re.IGNORECASE) for p in patterns]
    all_violations = []

    for path in root.rglob("*"):
        # Skip directories
        if path.is_dir():
            continue

        # Skip unwanted directories
        if any(skip in path.parts for skip in SKIP_DIRS):
            continue

        # Check if allowed
        if is_allowed(path, root):
            continue

        # Only scan critical paths (or all paths in strict mode)
        if not strict and not is_critical_path(path, root):
            continue

        # Only scan relevant extensions
        if path.suffix.lower() not in {".py", ".ts", ".tsx", ".js", ".jsx"}:
            continue

        # Scan file
        violations = scan_file(path, compiled)
        for line_num, line_content, pattern in violations:
            all_violations.append((path, line_num, line_content, pattern))

    return all_violations


def format_violations(violations: List[Tuple[Path, int, str, str]], root: Path) -> str:
    """Format violations for output."""
    if not violations:
        return "No critical legacy references found. OK"

    lines = [f"Found {len(violations)} legacy reference(s) in critical paths:\n"]

    # Group by file
    by_file = {}
    for path, line_num, content, pattern in violations:
        relative = str(path.relative_to(root)).replace("\\", "/")
        if relative not in by_file:
            by_file[relative] = []
        by_file[relative].append((line_num, content, pattern))

    for file_path in sorted(by_file.keys()):
        lines.append(f"\n{file_path}:")
        for line_num, content, pattern in by_file[file_path]:
            lines.append(f"  L{line_num}: {content[:80]}")
            lines.append(f"         ^ matches: {pattern}")

    lines.append(f"\n\nTo fix: Remove compat=legacy usage and use clean API.")
    lines.append("See docs/DEPRECATIONS.md for migration guide.")

    return "\n".join(lines)


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Check for legacy references in critical paths"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).parent.parent.parent,
        help="Root directory to scan",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Also check for deprecated field access patterns",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output",
    )
    args = parser.parse_args()

    root = args.root.resolve()

    if args.verbose:
        mode = "strict" if args.strict else "critical paths only"
        print(f"Scanning {root} for legacy references ({mode})...")

    violations = scan_critical_paths(root, strict=args.strict)

    output = format_violations(violations, root)
    try:
        print(output)
    except UnicodeEncodeError:
        print(output.encode("ascii", errors="replace").decode("ascii"))

    if violations:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

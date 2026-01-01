#!/usr/bin/env python3
"""
Deprecations report generator (v2.7.0 PR5).

Generates reports on deprecated field usage from:
- docs/api/deprecations.json SSoT
- Prometheus metrics (if available)

Usage:
    python scripts/deprecations/report.py [--format json|text|markdown]
    python scripts/deprecations/report.py --check  # CI check mode
"""

import argparse
import json
import sys
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Any


def load_deprecations(path: Optional[Path] = None) -> dict:
    """Load deprecations from SSoT file."""
    if path is None:
        # Try multiple possible paths
        possible_paths = [
            Path(__file__).parent.parent.parent / "docs" / "api" / "deprecations.json",
            Path("docs/api/deprecations.json"),
            Path("/app/docs/api/deprecations.json"),
        ]
        for p in possible_paths:
            if p.exists():
                path = p
                break

    if path is None or not path.exists():
        raise FileNotFoundError("deprecations.json not found")

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_days_until_sunset(sunset_date: str) -> int:
    """Calculate days until sunset date."""
    try:
        sunset = datetime.strptime(sunset_date, "%Y-%m-%d").date()
        today = date.today()
        return (sunset - today).days
    except ValueError:
        return -1


def format_status_icon(status: str) -> str:
    """Get icon for deprecation status."""
    icons = {
        "deprecated": "⚠️",
        "warning": "⚡",
        "removed": "❌",
    }
    return icons.get(status, "❓")


def generate_text_report(data: dict) -> str:
    """Generate text format report."""
    lines = []
    lines.append("=" * 60)
    lines.append("BESS Dispatch API Deprecations Report")
    lines.append("=" * 60)
    lines.append(f"Generated: {datetime.now().isoformat()}")
    lines.append(f"Registry Version: {data.get('version', 'unknown')}")
    lines.append(f"Last Updated: {data.get('last_updated', 'unknown')}")

    sunset_date = data.get("sunset_date", "unknown")
    days_until = get_days_until_sunset(sunset_date)
    lines.append(f"Sunset Date: {sunset_date} ({days_until} days remaining)")
    lines.append("")

    items = data.get("items", [])
    lines.append(f"Total Deprecated Fields: {len(items)}")
    lines.append("-" * 60)

    for item in items:
        icon = format_status_icon(item.get("status", ""))
        lines.append(f"\n{icon} {item['field']}")
        lines.append(f"   Location: {item.get('location', 'unknown')}")
        lines.append(f"   Status: {item.get('status', 'unknown')}")
        lines.append(f"   Since: {item.get('since', 'unknown')}")
        lines.append(f"   Remove In: {item.get('remove_in', 'unknown')}")
        lines.append(f"   Replacement: {item.get('replacement', 'none')}")
        if item.get("notes"):
            lines.append(f"   Notes: {item['notes']}")

    lines.append("\n" + "=" * 60)
    return "\n".join(lines)


def generate_markdown_report(data: dict) -> str:
    """Generate markdown format report."""
    lines = []
    lines.append("# BESS Dispatch API Deprecations Report")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now().isoformat()}")
    lines.append(f"**Registry Version:** {data.get('version', 'unknown')}")
    lines.append(f"**Last Updated:** {data.get('last_updated', 'unknown')}")

    sunset_date = data.get("sunset_date", "unknown")
    days_until = get_days_until_sunset(sunset_date)
    lines.append(f"**Sunset Date:** {sunset_date} ({days_until} days remaining)")
    lines.append("")

    items = data.get("items", [])
    lines.append(f"## Summary")
    lines.append(f"Total Deprecated Fields: **{len(items)}**")
    lines.append("")

    # Group by status
    by_status: Dict[str, List[dict]] = {}
    for item in items:
        status = item.get("status", "unknown")
        if status not in by_status:
            by_status[status] = []
        by_status[status].append(item)

    lines.append("| Status | Count |")
    lines.append("|--------|-------|")
    for status, items_list in by_status.items():
        icon = format_status_icon(status)
        lines.append(f"| {icon} {status} | {len(items_list)} |")
    lines.append("")

    lines.append("## Deprecated Fields")
    lines.append("")
    lines.append("| Field | Location | Status | Since | Remove In | Replacement |")
    lines.append("|-------|----------|--------|-------|-----------|-------------|")

    for item in items:
        icon = format_status_icon(item.get("status", ""))
        lines.append(
            f"| `{item['field']}` | {item.get('location', '')} | {icon} {item.get('status', '')} | "
            f"{item.get('since', '')} | {item.get('remove_in', '')} | `{item.get('replacement', '')}` |"
        )

    lines.append("")
    lines.append("## Migration Guide")
    lines.append("")
    for item in items:
        if item.get("replacement"):
            lines.append(f"### {item['field']} → {item['replacement']}")
            lines.append("")
            lines.append(f"- **Since:** {item.get('since', 'unknown')}")
            lines.append(f"- **Remove In:** {item.get('remove_in', 'unknown')}")
            if item.get("notes"):
                lines.append(f"- **Notes:** {item['notes']}")
            lines.append("")

    return "\n".join(lines)


def generate_json_report(data: dict) -> str:
    """Generate JSON format report."""
    report = {
        "generated_at": datetime.now().isoformat(),
        "registry_version": data.get("version", "unknown"),
        "last_updated": data.get("last_updated", "unknown"),
        "sunset_date": data.get("sunset_date", "unknown"),
        "days_until_sunset": get_days_until_sunset(data.get("sunset_date", "")),
        "total_deprecations": len(data.get("items", [])),
        "items": data.get("items", []),
    }
    return json.dumps(report, indent=2)


def check_deprecations(data: dict) -> bool:
    """
    CI check mode: Verify deprecations registry is valid.

    Returns True if all checks pass, False otherwise.
    """
    errors = []
    warnings = []

    # Check required fields
    if "version" not in data:
        errors.append("Missing 'version' field")
    if "items" not in data:
        errors.append("Missing 'items' field")
    if "sunset_date" not in data:
        warnings.append("Missing 'sunset_date' field")

    # Check sunset date
    sunset_date = data.get("sunset_date", "")
    days_until = get_days_until_sunset(sunset_date)
    if days_until < 0:
        warnings.append(f"Sunset date {sunset_date} is invalid or in the past")
    elif days_until < 30:
        warnings.append(f"Sunset date {sunset_date} is in {days_until} days")

    # Check items
    items = data.get("items", [])
    fields_seen = set()
    for i, item in enumerate(items):
        field = item.get("field", "")

        # Required fields check
        for required in ["field", "location", "status", "since", "remove_in"]:
            if required not in item:
                errors.append(f"Item {i}: Missing required field '{required}'")

        # Duplicate check
        if field in fields_seen:
            errors.append(f"Duplicate field: {field}")
        fields_seen.add(field)

        # Status check
        valid_statuses = ["deprecated", "warning", "removed"]
        if item.get("status") not in valid_statuses:
            errors.append(f"Item {field}: Invalid status '{item.get('status')}'")

    # Print results
    print("=" * 60)
    print("Deprecations Registry Check")
    print("=" * 60)
    print(f"Registry Version: {data.get('version', 'unknown')}")
    print(f"Total Items: {len(items)}")
    print(f"Sunset Date: {sunset_date}")
    print(f"Days Until Sunset: {days_until}")
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

    if not errors and not warnings:
        print("✅ All checks passed")

    print("=" * 60)

    return len(errors) == 0


def main():
    parser = argparse.ArgumentParser(
        description="Generate deprecations report from SSoT"
    )
    parser.add_argument(
        "--format", "-f",
        choices=["text", "markdown", "json"],
        default="text",
        help="Output format (default: text)"
    )
    parser.add_argument(
        "--check", "-c",
        action="store_true",
        help="CI check mode: verify registry is valid"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file (default: stdout)"
    )
    parser.add_argument(
        "--path", "-p",
        help="Path to deprecations.json"
    )

    args = parser.parse_args()

    try:
        path = Path(args.path) if args.path else None
        data = load_deprecations(path)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}", file=sys.stderr)
        sys.exit(1)

    if args.check:
        success = check_deprecations(data)
        sys.exit(0 if success else 1)

    # Generate report
    if args.format == "text":
        report = generate_text_report(data)
    elif args.format == "markdown":
        report = generate_markdown_report(data)
    else:
        report = generate_json_report(data)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"Report written to {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()

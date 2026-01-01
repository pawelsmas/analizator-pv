"""
Deprecations usage tracking helper (v2.7.0 PR1).

Provides centralized deprecation tracking:
- Register deprecated fields with metadata
- Mark field usage per request
- Generate deprecation headers
- Emit Prometheus metrics

Usage:
    from deprecations_usage import (
        register_deprecation,
        mark_used,
        get_deprecations_used,
        get_deprecation_headers,
        clear_request_deprecations,
    )

    # At startup, register known deprecations
    register_deprecation("export_revenue_pln", "v0.3.2", "v2.7.0")

    # In request handling, mark used deprecated fields
    mark_used("export_revenue_pln")

    # Get headers for response
    headers = get_deprecation_headers()

    # Clear for next request
    clear_request_deprecations()
"""

import json
import os
from datetime import datetime
from pathlib import Path
from threading import local
from typing import Dict, List, Optional, Set

# Thread-local storage for per-request deprecation tracking
_request_context = local()

# Global registry of deprecated fields
_deprecation_registry: Dict[str, dict] = {}

# Sunset date for deprecated features (ISO format)
SUNSET_DATE = "2026-03-01"


# -----------------------------------------------------------------------------
# Prometheus Metrics
# -----------------------------------------------------------------------------

try:
    from prometheus_client import Counter

    DEPRECATION_USED_TOTAL = Counter(
        "bess_deprecation_used_total",
        "Count of deprecated field usage",
        ["field"]
    )

    DEPRECATION_RESPONSES_TOTAL = Counter(
        "bess_deprecation_responses_total",
        "Count of responses containing deprecated field usage"
    )

    COMPAT_LEGACY_RESPONSES_TOTAL = Counter(
        "bess_compat_legacy_responses_total",
        "Count of responses using compat=legacy mode"
    )

    _METRICS_AVAILABLE = True
except ImportError:
    _METRICS_AVAILABLE = False
    DEPRECATION_USED_TOTAL = None
    DEPRECATION_RESPONSES_TOTAL = None
    COMPAT_LEGACY_RESPONSES_TOTAL = None


# -----------------------------------------------------------------------------
# Registry Management
# -----------------------------------------------------------------------------

def register_deprecation(
    field: str,
    since: str,
    remove_in: str,
    replacement: Optional[str] = None,
    notes: Optional[str] = None,
) -> None:
    """
    Register a deprecated field.

    Args:
        field: Name of the deprecated field
        since: Version when deprecation was announced (e.g., "v0.3.2")
        remove_in: Version when field will be removed (e.g., "v2.7.0")
        replacement: Suggested replacement field/approach
        notes: Additional notes about the deprecation
    """
    _deprecation_registry[field] = {
        "field": field,
        "since": since,
        "remove_in": remove_in,
        "replacement": replacement or "",
        "notes": notes or "",
    }


def load_deprecations_from_file() -> None:
    """Load deprecations from docs/api/deprecations.json."""
    possible_paths = [
        Path(__file__).parent.parent.parent / "docs" / "api" / "deprecations.json",
        Path("docs/api/deprecations.json"),
        Path("/app/docs/api/deprecations.json"),
    ]

    for path in possible_paths:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for item in data.get("items", []):
                    register_deprecation(
                        field=item["field"],
                        since=item["since"],
                        remove_in=item["remove_in"],
                        replacement=item.get("replacement"),
                        notes=item.get("notes"),
                    )
                return
            except Exception:
                pass


def get_deprecation_info(field: str) -> Optional[dict]:
    """Get deprecation info for a field."""
    return _deprecation_registry.get(field)


def get_all_deprecations() -> Dict[str, dict]:
    """Get all registered deprecations."""
    return _deprecation_registry.copy()


# -----------------------------------------------------------------------------
# Per-Request Tracking
# -----------------------------------------------------------------------------

def _get_used_set() -> Set[str]:
    """Get the set of deprecated fields used in current request."""
    if not hasattr(_request_context, "deprecations_used"):
        _request_context.deprecations_used = set()
    return _request_context.deprecations_used


def mark_used(field: str) -> None:
    """
    Mark a deprecated field as used in the current request.

    Args:
        field: Name of the deprecated field that was used
    """
    used = _get_used_set()
    if field not in used:
        used.add(field)
        # Emit metric
        if _METRICS_AVAILABLE and DEPRECATION_USED_TOTAL:
            DEPRECATION_USED_TOTAL.labels(field=field).inc()


def get_deprecations_used() -> List[str]:
    """Get list of deprecated fields used in current request."""
    return sorted(_get_used_set())


def has_deprecations_used() -> bool:
    """Check if any deprecated fields were used in current request."""
    return len(_get_used_set()) > 0


def clear_request_deprecations() -> None:
    """Clear deprecation tracking for current request."""
    if hasattr(_request_context, "deprecations_used"):
        _request_context.deprecations_used = set()


# -----------------------------------------------------------------------------
# Response Headers
# -----------------------------------------------------------------------------

def get_deprecation_headers() -> Dict[str, str]:
    """
    Get deprecation headers for the response.

    Returns headers dict with:
    - Deprecation: true (if deprecated fields were used)
    - Link: </api/bess-dispatch/deprecations>; rel="deprecation"
    - Sunset: YYYY-MM-DD

    Returns:
        Dict of header name -> value
    """
    if not has_deprecations_used():
        return {}

    # Emit response metric
    if _METRICS_AVAILABLE and DEPRECATION_RESPONSES_TOTAL:
        DEPRECATION_RESPONSES_TOTAL.inc()

    return {
        "Deprecation": "true",
        "Link": '</api/bess-dispatch/deprecations>; rel="deprecation"',
        "Sunset": SUNSET_DATE,
    }


def track_compat_legacy() -> None:
    """Track usage of compat=legacy mode."""
    if _METRICS_AVAILABLE and COMPAT_LEGACY_RESPONSES_TOTAL:
        COMPAT_LEGACY_RESPONSES_TOTAL.inc()


# -----------------------------------------------------------------------------
# Warnings Block
# -----------------------------------------------------------------------------

def get_warnings_block() -> Optional[dict]:
    """
    Get warnings block to include in response.

    Returns:
        Dict with deprecations_used list, or None if no deprecations
    """
    used = get_deprecations_used()
    if not used:
        return None
    return {
        "deprecations_used": used,
    }


def add_warnings_to_response(response: dict) -> dict:
    """
    Add warnings block to response dict if deprecations were used.

    Args:
        response: The response dict to modify

    Returns:
        Modified response dict with warnings added if applicable
    """
    warnings = get_warnings_block()
    if warnings:
        if "warnings" not in response:
            response["warnings"] = {}
        response["warnings"].update(warnings)
    return response


# -----------------------------------------------------------------------------
# Initialization
# -----------------------------------------------------------------------------

# Load deprecations from file on module import
load_deprecations_from_file()

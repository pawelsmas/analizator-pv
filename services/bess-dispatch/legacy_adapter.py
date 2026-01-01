"""
Central Legacy Response Adapter (v2.8.0 PR2).

Single source of truth for applying legacy compatibility mode.
All deprecated field aliases and legacy response shaping go through here.

Usage:
    from legacy_adapter import apply_legacy_compat

    if compat_mode == CompatMode.LEGACY:
        response = apply_legacy_compat(response, endpoint="sizing")
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from deprecations_usage import mark_used, track_compat_legacy


# -----------------------------------------------------------------------------
# Deprecated Field Registry (loaded from SSoT)
# -----------------------------------------------------------------------------

# Response fields that are deprecated
_DEPRECATED_RESPONSE_FIELDS: Set[str] = set()

# Field aliases: deprecated_name -> source_name (to populate deprecated field)
_FIELD_ALIASES: Dict[str, str] = {}


def _load_deprecations_registry() -> None:
    """Load deprecated fields and aliases from docs/api/deprecations.json."""
    global _DEPRECATED_RESPONSE_FIELDS, _FIELD_ALIASES

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
                    field = item["field"]
                    location = item.get("location", "")
                    replacement = item.get("replacement", "")

                    # Only process response fields (not request fields)
                    if "Request" in location:
                        continue

                    _DEPRECATED_RESPONSE_FIELDS.add(field)

                    # Build alias mapping if replacement is specified
                    if replacement:
                        # Handle nested replacements like "economics_breakdown.total_savings_pln"
                        source = replacement.split(".")[-1] if "." in replacement else replacement
                        _FIELD_ALIASES[field] = source

                return
            except Exception:
                pass

    # Fallback hardcoded aliases (should match deprecations.json)
    _FIELD_ALIASES = {
        "export_revenue_pln": "export_savings_pln",
        "savings_pln": "total_savings_pln",
    }
    _DEPRECATED_RESPONSE_FIELDS = {"export_revenue_pln", "savings_pln", "payback_years", "interval_minutes"}


# Load on module import
_load_deprecations_registry()


# -----------------------------------------------------------------------------
# Legacy Adapter Functions
# -----------------------------------------------------------------------------

def apply_legacy_compat(
    response: Dict[str, Any],
    endpoint: str = "",
) -> Dict[str, Any]:
    """
    Apply legacy compatibility mode to a response.

    Adds deprecated field aliases to the response and marks them as used.
    This is the SINGLE entry point for legacy mode transformations.

    Args:
        response: Clean response dict to transform
        endpoint: Endpoint name for tracking (e.g., "sizing", "dispatch")

    Returns:
        Response dict with deprecated aliases added
    """
    # Track that legacy mode was used
    track_compat_legacy()
    mark_used("compat=legacy")

    # Recursively add deprecated field aliases
    return _add_legacy_fields(response)


def _add_legacy_fields(obj: Any, path: str = "") -> Any:
    """
    Recursively add deprecated field aliases to response.

    Args:
        obj: Object to process (dict, list, or value)
        path: Current path for debugging

    Returns:
        Object with legacy aliases added
    """
    if isinstance(obj, dict):
        result = {}

        # First, process all existing fields
        for k, v in obj.items():
            result[k] = _add_legacy_fields(v, f"{path}.{k}")

        # Then add aliases for deprecated fields
        for deprecated_name, source_name in _FIELD_ALIASES.items():
            if source_name in result and deprecated_name not in result:
                result[deprecated_name] = result[source_name]
                mark_used(deprecated_name)

        return result

    elif isinstance(obj, list):
        return [_add_legacy_fields(item, f"{path}[]") for item in obj]

    else:
        return obj


def get_legacy_field_aliases() -> Dict[str, str]:
    """Get the mapping of deprecated field -> source field."""
    return _FIELD_ALIASES.copy()


def get_deprecated_response_fields() -> Set[str]:
    """Get set of all deprecated response fields."""
    return _DEPRECATED_RESPONSE_FIELDS.copy()


def is_field_deprecated(field: str) -> bool:
    """Check if a field name is deprecated."""
    return field in _DEPRECATED_RESPONSE_FIELDS


def add_legacy_warnings(response: Dict[str, Any]) -> Dict[str, Any]:
    """
    Add legacy mode warning to response.

    Adds "compat=legacy" to the deprecations_used warnings list.

    Args:
        response: Response dict to modify

    Returns:
        Response with warnings added
    """
    if "warnings" not in response:
        response["warnings"] = {}

    if "deprecations_used" not in response["warnings"]:
        response["warnings"]["deprecations_used"] = []

    if "compat=legacy" not in response["warnings"]["deprecations_used"]:
        response["warnings"]["deprecations_used"].append("compat=legacy")

    return response


def validate_legacy_aliases_consistent(response: Dict[str, Any]) -> List[str]:
    """
    Validate that legacy alias values match their source fields.

    Used in contract tests to ensure consistency.

    Args:
        response: Response dict with legacy aliases

    Returns:
        List of inconsistency messages (empty if all consistent)
    """
    inconsistencies = []

    def check_dict(obj: Dict[str, Any], path: str = "") -> None:
        for deprecated_name, source_name in _FIELD_ALIASES.items():
            if deprecated_name in obj and source_name in obj:
                if obj[deprecated_name] != obj[source_name]:
                    inconsistencies.append(
                        f"{path}{deprecated_name}={obj[deprecated_name]} != "
                        f"{source_name}={obj[source_name]}"
                    )

        # Check nested dicts
        for k, v in obj.items():
            if isinstance(v, dict):
                check_dict(v, f"{path}{k}.")
            elif isinstance(v, list):
                for i, item in enumerate(v):
                    if isinstance(item, dict):
                        check_dict(item, f"{path}{k}[{i}].")

    check_dict(response)
    return inconsistencies

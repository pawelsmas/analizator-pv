"""
Compatibility mode helper for response shaping (v2.7.0 PR2).

Provides:
- compat=clean: Omit deprecated fields from response (default)
- compat=legacy: Include deprecated fields as aliases

This allows API consumers to migrate gradually while we remove
deprecated fields in future versions.
"""

import json
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from deprecations_usage import mark_used, track_compat_legacy


class CompatMode(str, Enum):
    """Compatibility mode for response shaping."""
    CLEAN = "clean"
    LEGACY = "legacy"


# Deprecated fields that should be omitted in clean mode
# Loaded from deprecations.json
_DEPRECATED_RESPONSE_FIELDS: Set[str] = set()

# Field mappings: deprecated_name -> source_name
# Used to populate deprecated fields in legacy mode
_FIELD_ALIASES: Dict[str, str] = {
    "export_revenue_pln": "export_savings_pln",
    "savings_pln": "total_savings_pln",
}


def _load_deprecated_fields() -> None:
    """Load deprecated field names from registry."""
    global _DEPRECATED_RESPONSE_FIELDS

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
                    # Only include response fields (not request fields)
                    location = item.get("location", "")
                    if "Request" not in location:
                        _DEPRECATED_RESPONSE_FIELDS.add(item["field"])
                return
            except Exception:
                pass


def parse_compat_mode(compat_param: Optional[str]) -> CompatMode:
    """
    Parse compat query parameter.

    Args:
        compat_param: Value from query string (clean or legacy)

    Returns:
        CompatMode enum (defaults to CLEAN)
    """
    if compat_param is None:
        return CompatMode.CLEAN

    try:
        return CompatMode(compat_param.lower())
    except ValueError:
        return CompatMode.CLEAN


def apply_compat_mode(
    response: Dict[str, Any],
    mode: CompatMode,
    path: str = "",
) -> Dict[str, Any]:
    """
    Apply compatibility mode to response dict.

    In CLEAN mode: Removes deprecated fields
    In LEGACY mode: Adds deprecated field aliases and marks them as used

    Args:
        response: Response dict to modify
        mode: Compatibility mode
        path: Current path for nested traversal (for debugging)

    Returns:
        Modified response dict
    """
    if mode == CompatMode.LEGACY:
        track_compat_legacy()
        return _add_legacy_fields(response)
    else:
        return _remove_deprecated_fields(response)


def _remove_deprecated_fields(obj: Any, path: str = "") -> Any:
    """
    Recursively remove deprecated fields from response.

    Args:
        obj: Object to process (dict, list, or value)
        path: Current path for tracking

    Returns:
        Cleaned object
    """
    if isinstance(obj, dict):
        return {
            k: _remove_deprecated_fields(v, f"{path}.{k}")
            for k, v in obj.items()
            if k not in _DEPRECATED_RESPONSE_FIELDS
        }
    elif isinstance(obj, list):
        return [_remove_deprecated_fields(item, f"{path}[]") for item in obj]
    else:
        return obj


def _add_legacy_fields(obj: Any, path: str = "") -> Any:
    """
    Recursively add deprecated field aliases to response.

    Args:
        obj: Object to process
        path: Current path for tracking

    Returns:
        Object with legacy aliases added
    """
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            result[k] = _add_legacy_fields(v, f"{path}.{k}")

        # Add aliases for deprecated fields
        for deprecated_name, source_name in _FIELD_ALIASES.items():
            if source_name in result and deprecated_name not in result:
                result[deprecated_name] = result[source_name]
                mark_used(deprecated_name)

        return result
    elif isinstance(obj, list):
        return [_add_legacy_fields(item, f"{path}[]") for item in obj]
    else:
        return obj


def get_deprecated_response_fields() -> Set[str]:
    """Get set of deprecated response fields."""
    return _DEPRECATED_RESPONSE_FIELDS.copy()


def is_field_deprecated(field: str) -> bool:
    """Check if a field is deprecated."""
    return field in _DEPRECATED_RESPONSE_FIELDS


# Load deprecated fields on module import
_load_deprecated_fields()

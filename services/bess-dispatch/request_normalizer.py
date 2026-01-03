"""
Request normalizer for deprecated field mapping (v2.7.0 PR3, updated v4.5.0).

Normalizes deprecated request fields to new equivalents:
- include_battery_trace=true -> battery_trace_mode="full"
- include_price_timeseries=true -> price_timeseries_mode="full"
- include_ledger_timeseries=true -> ledger_timeseries_mode="full"

Also handles objective aliases (v4.5.0):
- lcoe -> lcos (LCOE maps to LCOS for storage)
- self_consumption_rate -> self_consumption (alias normalization)

This allows old API consumers to continue working while we
deprecate the old field names.
"""

from typing import Any, Dict, List, Optional, Tuple

from deprecations_usage import mark_used


# Mapping of deprecated request fields to their normalization
# Format: deprecated_field -> (new_field, value_transform_fn)
REQUEST_FIELD_MAPPINGS: Dict[str, Tuple[str, Any]] = {
    "include_battery_trace": ("battery_trace_mode", lambda v: "full" if v else "none"),
    "include_price_timeseries": ("price_timeseries_mode", lambda v: "full" if v else "none"),
    "include_ledger_timeseries": ("ledger_timeseries_mode", lambda v: "full" if v else "none"),
}

# Objective alias mappings (v4.5.0)
# Maps common synonyms/typos to canonical objective names
OBJECTIVE_ALIASES: Dict[str, str] = {
    "lcoe": "lcos",  # LCOE is a misnomer for storage; LCOS is correct
    "self_consumption_rate": "self_consumption",  # Both accepted
}


def normalize_request(request_dict: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """
    Normalize deprecated request fields to new equivalents.

    Transforms deprecated fields to new format and tracks usage.

    Args:
        request_dict: Request dictionary (mutable)

    Returns:
        Tuple of (normalized_dict, list of deprecated fields used)
    """
    deprecated_used = []
    result = request_dict.copy()

    for old_field, (new_field, transform_fn) in REQUEST_FIELD_MAPPINGS.items():
        if old_field in result:
            old_value = result[old_field]
            # Only transform if new field not already set
            if new_field not in result:
                result[new_field] = transform_fn(old_value)

            # Track deprecated usage
            if old_value:  # Only track if the deprecated feature was actually used
                mark_used(old_field)
                deprecated_used.append(old_field)

    return result, deprecated_used


def get_deprecated_request_fields() -> List[str]:
    """Get list of deprecated request field names."""
    return list(REQUEST_FIELD_MAPPINGS.keys())


def is_request_field_deprecated(field: str) -> bool:
    """Check if a request field is deprecated."""
    return field in REQUEST_FIELD_MAPPINGS


def get_field_replacement(field: str) -> Optional[str]:
    """Get the new field name for a deprecated field."""
    if field in REQUEST_FIELD_MAPPINGS:
        return REQUEST_FIELD_MAPPINGS[field][0]
    return None

"""
Timeseries throttling helper (v2.5.0 PR2).

Provides utilities for:
- Resolving timeseries mode from legacy boolean flags
- Applying preview truncation to timeseries data
- Enforcing MAX_TRACE_STEPS limit for full mode

This module ensures backward compatibility with existing
include_battery_trace=True flags while enabling new preview/full modes.
"""

from typing import List, Optional, Any, Dict, Tuple
from limits_config import (
    TimeseriesMode,
    MAX_TRACE_STEPS,
    DEFAULT_PREVIEW_ROWS,
    MIN_PREVIEW_ROWS,
    MAX_PREVIEW_ROWS,
    ErrorCode,
)


def resolve_timeseries_mode(
    include_flag: bool = False,
    mode_param: Optional[str] = None,
) -> TimeseriesMode:
    """
    Resolve the effective timeseries mode from request parameters.

    Backward compatibility:
    - include_flag=True with no mode_param → FULL (original behavior)
    - include_flag=False with no mode_param → NONE
    - mode_param takes precedence when provided

    Args:
        include_flag: Legacy boolean flag (e.g., include_battery_trace)
        mode_param: New mode parameter (e.g., battery_trace_mode)

    Returns:
        TimeseriesMode enum value
    """
    if mode_param is not None:
        try:
            return TimeseriesMode(mode_param.lower())
        except ValueError:
            # Invalid mode, fall back to legacy behavior
            pass

    # Legacy behavior: bool flag maps to FULL or NONE
    return TimeseriesMode.FULL if include_flag else TimeseriesMode.NONE


def validate_preview_rows(rows: Optional[int]) -> int:
    """
    Validate and clamp preview rows to allowed range.

    Args:
        rows: Requested preview rows (or None for default)

    Returns:
        Valid preview rows value
    """
    if rows is None:
        return DEFAULT_PREVIEW_ROWS

    return max(MIN_PREVIEW_ROWS, min(MAX_PREVIEW_ROWS, rows))


def check_full_timeseries_limit(n_steps: int) -> Tuple[bool, Optional[dict]]:
    """
    Check if full timeseries would exceed MAX_TRACE_STEPS limit.

    Args:
        n_steps: Number of steps in the timeseries

    Returns:
        Tuple of (is_ok, error_dict or None)
        If not ok, error_dict contains 422 error response body
    """
    if n_steps > MAX_TRACE_STEPS:
        return False, {
            "error_code": ErrorCode.TIMESERIES_TOO_LARGE,
            "detail": f"Full timeseries with {n_steps} steps exceeds limit of {MAX_TRACE_STEPS}. "
                      f"Use mode='preview' to get first {DEFAULT_PREVIEW_ROWS} steps only.",
            "max_trace_steps": MAX_TRACE_STEPS,
            "steps": n_steps,
        }
    return True, None


def truncate_timeseries_array(
    data: List[Any],
    mode: TimeseriesMode,
    preview_rows: int = DEFAULT_PREVIEW_ROWS,
) -> List[Any]:
    """
    Truncate a timeseries array based on mode.

    Args:
        data: Full timeseries array
        mode: TimeseriesMode (NONE, PREVIEW, FULL)
        preview_rows: Number of rows for preview mode

    Returns:
        Truncated or full array based on mode
    """
    if mode == TimeseriesMode.NONE:
        return []
    elif mode == TimeseriesMode.PREVIEW:
        return data[:preview_rows]
    else:  # FULL
        return data


def truncate_timeseries_dict(
    data: Dict[str, List[Any]],
    mode: TimeseriesMode,
    preview_rows: int = DEFAULT_PREVIEW_ROWS,
) -> Dict[str, List[Any]]:
    """
    Truncate all arrays in a timeseries dict based on mode.

    Args:
        data: Dict with timeseries arrays as values
        mode: TimeseriesMode (NONE, PREVIEW, FULL)
        preview_rows: Number of rows for preview mode

    Returns:
        Dict with truncated arrays based on mode
    """
    if mode == TimeseriesMode.NONE:
        return {k: [] for k in data}
    elif mode == TimeseriesMode.PREVIEW:
        return {k: v[:preview_rows] for k, v in data.items()}
    else:  # FULL
        return data


def get_timeseries_info(
    mode: TimeseriesMode,
    total_steps: int,
    preview_rows: int = DEFAULT_PREVIEW_ROWS,
) -> Dict[str, Any]:
    """
    Get metadata about timeseries output for response.

    Args:
        mode: Active timeseries mode
        total_steps: Total number of steps in source data
        preview_rows: Preview rows if in preview mode

    Returns:
        Dict with mode, included_steps, total_steps, truncated flag
    """
    if mode == TimeseriesMode.NONE:
        included = 0
    elif mode == TimeseriesMode.PREVIEW:
        included = min(preview_rows, total_steps)
    else:  # FULL
        included = total_steps

    return {
        "mode": mode.value,
        "included_steps": included,
        "total_steps": total_steps,
        "truncated": included < total_steps,
    }

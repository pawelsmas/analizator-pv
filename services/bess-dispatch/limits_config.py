"""
Request limits configuration (v2.5.0).

Provides configurable limits for request size and computation steps.
All limits can be overridden via environment variables.
"""

import os
from enum import Enum


# -----------------------------------------------------------------------------
# Request Size Limits
# -----------------------------------------------------------------------------

# Maximum request body size in bytes (default: 2.5 MB)
MAX_REQUEST_BYTES = int(os.environ.get("MAX_REQUEST_BYTES", "2500000"))

# Maximum number of time steps (default: 35040 = full year at 15-min intervals)
MAX_STEPS = int(os.environ.get("MAX_STEPS", "35040"))

# Maximum number of variants to compute (optional, default: 50)
MAX_VARIANTS = int(os.environ.get("MAX_VARIANTS", "50"))

# Maximum number of durations to test (optional, default: 10)
MAX_DURATIONS = int(os.environ.get("MAX_DURATIONS", "10"))


# -----------------------------------------------------------------------------
# Timeseries Limits (v2.5.0 PR2)
# -----------------------------------------------------------------------------

# Maximum steps for full timeseries output (default: 10000)
MAX_TRACE_STEPS = int(os.environ.get("MAX_TRACE_STEPS", "10000"))

# Default preview rows when timeseries is in preview mode
DEFAULT_PREVIEW_ROWS = int(os.environ.get("DEFAULT_PREVIEW_ROWS", "48"))

# Minimum and maximum preview rows
MIN_PREVIEW_ROWS = 12
MAX_PREVIEW_ROWS = 240


# -----------------------------------------------------------------------------
# Timeseries Mode Enum (v2.5.0 PR2)
# -----------------------------------------------------------------------------

class TimeseriesMode(str, Enum):
    """Mode for timeseries output in responses."""
    NONE = "none"      # Do not include timeseries
    PREVIEW = "preview"  # Include first N rows only (preview_rows)
    FULL = "full"      # Include all rows (subject to MAX_TRACE_STEPS)


# -----------------------------------------------------------------------------
# Error Codes
# -----------------------------------------------------------------------------

class ErrorCode:
    """Stable error codes for limit violations."""
    REQUEST_TOO_LARGE = "REQUEST_TOO_LARGE"
    STEPS_LIMIT_EXCEEDED = "STEPS_LIMIT_EXCEEDED"
    VARIANTS_LIMIT_EXCEEDED = "VARIANTS_LIMIT_EXCEEDED"
    DURATIONS_LIMIT_EXCEEDED = "DURATIONS_LIMIT_EXCEEDED"
    TIMESERIES_TOO_LARGE = "TIMESERIES_TOO_LARGE"


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

def get_limits_info() -> dict:
    """Return current limit configuration for diagnostics."""
    return {
        "max_request_bytes": MAX_REQUEST_BYTES,
        "max_steps": MAX_STEPS,
        "max_variants": MAX_VARIANTS,
        "max_durations": MAX_DURATIONS,
        "max_trace_steps": MAX_TRACE_STEPS,
        "default_preview_rows": DEFAULT_PREVIEW_ROWS,
        "min_preview_rows": MIN_PREVIEW_ROWS,
        "max_preview_rows": MAX_PREVIEW_ROWS,
    }

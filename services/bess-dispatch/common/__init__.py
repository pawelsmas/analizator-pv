"""
Common utilities shared across bess-dispatch modules.

Contains:
- calendar_pl: Polish calendar with holidays and day types
- time_utils: Time handling utilities with ClockMode support
- versioning: API versioning helpers
"""

from .calendar_pl import (
    DayType,
    get_polish_holidays,
    is_polish_holiday,
    is_workday,
    get_day_type,
    get_workdays_in_month,
    get_workdays_in_year,
    count_workdays_in_year,
)

from .time_utils import (
    ClockMode,
    minute_of_day,
    datetime_to_local_minute,
    get_effective_day_type,
)

from .versioning import (
    get_schema_version,
    get_assumptions_version,
    get_version_info,
    SCHEMA_VERSION,
)

from .logging_structured import (
    log_sizing_request,
    log_sizing_response,
    log_dispatch_request,
    log_dispatch_response,
    log_error,
    log_warning,
    record_sizing_metrics,
    record_dispatch_metrics,
    PROMETHEUS_AVAILABLE,
)

__all__ = [
    # Calendar
    "DayType",
    "get_polish_holidays",
    "is_polish_holiday",
    "is_workday",
    "get_day_type",
    "get_workdays_in_month",
    "get_workdays_in_year",
    "count_workdays_in_year",
    # Time utils
    "ClockMode",
    "minute_of_day",
    "datetime_to_local_minute",
    "get_effective_day_type",
    # Versioning
    "get_schema_version",
    "get_assumptions_version",
    "get_version_info",
    "SCHEMA_VERSION",
    # Structured logging
    "log_sizing_request",
    "log_sizing_response",
    "log_dispatch_request",
    "log_dispatch_response",
    "log_error",
    "log_warning",
    "record_sizing_metrics",
    "record_dispatch_metrics",
    "PROMETHEUS_AVAILABLE",
]

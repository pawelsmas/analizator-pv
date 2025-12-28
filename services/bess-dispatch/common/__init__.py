"""
Common utilities shared across bess-dispatch modules.

Contains:
- calendar_pl: Polish calendar with holidays and day types
- time_utils: Time handling utilities with ClockMode support
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
]

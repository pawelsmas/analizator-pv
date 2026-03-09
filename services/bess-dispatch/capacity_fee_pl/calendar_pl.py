"""
Polish calendar utilities for capacity fee calculation.

Re-exports from common.calendar_pl — SINGLE SOURCE OF TRUTH.
Do NOT duplicate holiday logic here.
"""

# Re-export everything from the canonical module
from common.calendar_pl import (
    DayType,
    POLISH_HOLIDAYS_FIXED,
    WIGILIA_START_YEAR,
    get_polish_holidays,
    is_polish_holiday,
    is_workday,
    get_day_type,
    get_workdays_in_month,
    get_workdays_in_year,
    count_workdays_in_year,
    get_decadal_periods,
    get_quarter,
    DAY_TYPE_PRIORITY,
    compare_day_type_priority,
)

__all__ = [
    "DayType",
    "POLISH_HOLIDAYS_FIXED",
    "WIGILIA_START_YEAR",
    "get_polish_holidays",
    "is_polish_holiday",
    "is_workday",
    "get_day_type",
    "get_workdays_in_month",
    "get_workdays_in_year",
    "count_workdays_in_year",
    "get_decadal_periods",
    "get_quarter",
    "DAY_TYPE_PRIORITY",
    "compare_day_type_priority",
]

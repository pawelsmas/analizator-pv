"""
DST (Daylight Saving Time) handling utilities for Polish energy calculations.

This module provides functions to:
1. Detect DST transition days (23h and 25h days)
2. Map hourly data indices to correct local hours
3. Handle zone assignments during DST transitions

Key DST rules for Poland (EU):
- Spring forward: Last Sunday of March, 02:00 CET -> 03:00 CEST (23-hour day)
- Fall back: Last Sunday of October, 03:00 CEST -> 02:00 CET (25-hour day)

Usage:
    from common.dst_helper import (
        is_spring_forward_day,
        is_fall_back_day,
        get_day_hours_count,
        get_dst_info,
    )

    # Check if a specific date has DST transition
    info = get_dst_info(date(2025, 3, 30))  # Spring forward
    # Returns: DSTInfo(is_dst_day=True, hours=23, missing_hour=2, duplicate_hour=None)
"""

from datetime import datetime, date, timedelta, timezone
from dataclasses import dataclass
from typing import Optional, List, Tuple
from zoneinfo import ZoneInfo

# Standard Polish timezone
WARSAW_TZ = ZoneInfo("Europe/Warsaw")


@dataclass
class DSTInfo:
    """
    DST information for a specific date.

    Attributes:
        is_dst_day: True if this day has a DST transition
        hours: Number of hours in this day (23, 24, or 25)
        is_spring_forward: True if this is spring forward (23h)
        is_fall_back: True if this is fall back (25h)
        missing_hour: Hour that doesn't exist (2 for spring forward), None otherwise
        duplicate_hour: Hour that occurs twice (2 for fall back), None otherwise
    """
    is_dst_day: bool
    hours: int
    is_spring_forward: bool
    is_fall_back: bool
    missing_hour: Optional[int]
    duplicate_hour: Optional[int]


def get_last_sunday_of_month(year: int, month: int) -> date:
    """
    Get the last Sunday of a given month.

    Args:
        year: Year
        month: Month (1-12)

    Returns:
        Date of the last Sunday
    """
    # Find the last day of the month
    if month == 12:
        first_of_next = date(year + 1, 1, 1)
    else:
        first_of_next = date(year, month + 1, 1)

    last_day = first_of_next - timedelta(days=1)

    # Find the last Sunday (weekday 6 = Sunday)
    days_since_sunday = (last_day.weekday() + 1) % 7
    return last_day - timedelta(days=days_since_sunday)


def get_spring_forward_date(year: int) -> date:
    """
    Get the spring forward (DST start) date for a given year.

    In Poland/EU: Last Sunday of March.

    Args:
        year: Year to check

    Returns:
        Date of spring forward transition
    """
    return get_last_sunday_of_month(year, 3)


def get_fall_back_date(year: int) -> date:
    """
    Get the fall back (DST end) date for a given year.

    In Poland/EU: Last Sunday of October.

    Args:
        year: Year to check

    Returns:
        Date of fall back transition
    """
    return get_last_sunday_of_month(year, 10)


def is_spring_forward_day(d: date) -> bool:
    """
    Check if a date is a spring forward day (23 hours).

    Args:
        d: Date to check

    Returns:
        True if this is the spring forward day
    """
    return d == get_spring_forward_date(d.year)


def is_fall_back_day(d: date) -> bool:
    """
    Check if a date is a fall back day (25 hours).

    Args:
        d: Date to check

    Returns:
        True if this is the fall back day
    """
    return d == get_fall_back_date(d.year)


def get_day_hours_count(d: date) -> int:
    """
    Get the number of hours in a specific day.

    Args:
        d: Date to check

    Returns:
        23 for spring forward, 25 for fall back, 24 otherwise
    """
    if is_spring_forward_day(d):
        return 23
    elif is_fall_back_day(d):
        return 25
    return 24


def get_dst_info(d: date) -> DSTInfo:
    """
    Get complete DST information for a date.

    Args:
        d: Date to check

    Returns:
        DSTInfo dataclass with all DST information
    """
    if is_spring_forward_day(d):
        return DSTInfo(
            is_dst_day=True,
            hours=23,
            is_spring_forward=True,
            is_fall_back=False,
            missing_hour=2,  # 02:00 CET doesn't exist (jumps to 03:00)
            duplicate_hour=None,
        )
    elif is_fall_back_day(d):
        return DSTInfo(
            is_dst_day=True,
            hours=25,
            is_spring_forward=False,
            is_fall_back=True,
            missing_hour=None,
            duplicate_hour=2,  # 02:00 CET occurs twice
        )
    else:
        return DSTInfo(
            is_dst_day=False,
            hours=24,
            is_spring_forward=False,
            is_fall_back=False,
            missing_hour=None,
            duplicate_hour=None,
        )


def get_dst_transition_dates(year: int) -> Tuple[date, date]:
    """
    Get both DST transition dates for a year.

    Args:
        year: Year to check

    Returns:
        Tuple of (spring_forward_date, fall_back_date)
    """
    return get_spring_forward_date(year), get_fall_back_date(year)


def map_hourly_index_to_cet_hour(
    index: int,
    start_date: date,
    is_local_tz: bool = False
) -> Tuple[date, int]:
    """
    Map a 0-based hourly index to (date, CET hour).

    For CET_FIXED mode (default), hour 0 = 00:00 CET of start_date.
    For LOCAL_TZ mode, handles DST transitions.

    Args:
        index: 0-based hourly index
        start_date: Starting date of the period
        is_local_tz: If True, use LOCAL_TZ mode with DST

    Returns:
        Tuple of (date, hour) in CET
    """
    if not is_local_tz:
        # CET_FIXED mode: Simple calculation
        days = index // 24
        hour = index % 24
        return start_date + timedelta(days=days), hour

    # LOCAL_TZ mode: Account for DST
    current_date = start_date
    remaining = index

    while True:
        hours_in_day = get_day_hours_count(current_date)
        if remaining < hours_in_day:
            # Handle the special hours during DST
            dst_info = get_dst_info(current_date)

            if dst_info.is_spring_forward and remaining >= 2:
                # Skip hour 2 (doesn't exist)
                hour = remaining + 1 if remaining >= 2 else remaining
            elif dst_info.is_fall_back and remaining >= 2:
                # Hour 2 occurs twice (indices 2 and 3 both map to hour 2)
                if remaining <= 2:
                    hour = remaining
                elif remaining == 3:
                    hour = 2  # Second occurrence of hour 2
                else:
                    hour = remaining - 1
            else:
                hour = remaining

            return current_date, min(hour, 23)

        remaining -= hours_in_day
        current_date += timedelta(days=1)


def get_period_hours_with_dst(start_date: date, end_date: date) -> int:
    """
    Calculate total hours in a period accounting for DST.

    Args:
        start_date: Start date (inclusive)
        end_date: End date (exclusive)

    Returns:
        Total hours in the period
    """
    total = 0
    current = start_date
    while current < end_date:
        total += get_day_hours_count(current)
        current += timedelta(days=1)
    return total


def get_year_dst_dates_list(year: int) -> List[Tuple[date, str]]:
    """
    Get list of DST dates for a year with their types.

    Args:
        year: Year to check

    Returns:
        List of (date, type) tuples where type is 'spring_forward' or 'fall_back'
    """
    return [
        (get_spring_forward_date(year), "spring_forward"),
        (get_fall_back_date(year), "fall_back"),
    ]

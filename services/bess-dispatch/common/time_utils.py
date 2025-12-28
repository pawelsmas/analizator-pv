"""
Time handling utilities for Polish OSD tariffs.

Key concept: ClockMode
- CET_FIXED: Tariff always uses CET (UTC+1), ignoring DST.
  This is how Polish OSD tariffs define zones ("czas zimowy").
- LOCAL_TZ: Use Europe/Warsaw with full DST handling.

Most Polish tariffs use CET_FIXED ("czas zimowy" = winter time).
"""

from datetime import datetime, date, timedelta, timezone
from enum import Enum
from typing import Tuple, Optional
from zoneinfo import ZoneInfo

from .calendar_pl import DayType, get_day_type


class ClockMode(str, Enum):
    """
    Clock mode for tariff time interpretation.

    CET_FIXED: Use CET (UTC+1) always, ignoring DST.
               This is how Polish OSD tariffs define zones.
               "Strefa szczytowa: 7:00-13:00, 16:00-21:00" means CET hours.

    LOCAL_TZ:  Use Europe/Warsaw with proper DST handling.
               Use this for real-time systems that need accurate local time.
    """
    CET_FIXED = "cet_fixed"    # UTC+1 always (Polish "czas zimowy")
    LOCAL_TZ = "local_tz"      # Europe/Warsaw with DST


# Standard Polish timezone
WARSAW_TZ = ZoneInfo("Europe/Warsaw")

# Fixed CET offset (UTC+1, no DST)
CET_FIXED_OFFSET = timezone(timedelta(hours=1))


def minute_of_day(hour: int, minute: int = 0) -> int:
    """
    Convert hour:minute to minute of day (0-1439).

    Args:
        hour: Hour (0-23)
        minute: Minute (0-59)

    Returns:
        Minute of day (0-1439)

    Examples:
        >>> minute_of_day(0, 0)
        0
        >>> minute_of_day(7, 30)
        450
        >>> minute_of_day(23, 59)
        1439
    """
    if not (0 <= hour <= 23):
        raise ValueError(f"Hour must be 0-23, got {hour}")
    if not (0 <= minute <= 59):
        raise ValueError(f"Minute must be 0-59, got {minute}")
    return hour * 60 + minute


def minute_of_day_to_time(minute: int) -> Tuple[int, int]:
    """
    Convert minute of day to (hour, minute) tuple.

    Args:
        minute: Minute of day (0-1439)

    Returns:
        Tuple of (hour, minute)

    Examples:
        >>> minute_of_day_to_time(0)
        (0, 0)
        >>> minute_of_day_to_time(450)
        (7, 30)
        >>> minute_of_day_to_time(1439)
        (23, 59)
    """
    if not (0 <= minute <= 1439):
        raise ValueError(f"Minute must be 0-1439, got {minute}")
    return divmod(minute, 60)


def datetime_to_cet_fixed(dt: datetime) -> datetime:
    """
    Convert datetime to CET fixed (UTC+1) representation.

    This is the core function for CET_FIXED clock mode.
    Takes a UTC datetime and returns it as UTC+1.

    Args:
        dt: Datetime in UTC (should be tz-aware)

    Returns:
        Datetime in CET fixed (UTC+1)

    Example:
        # During CEST (summer), 14:00 local Warsaw = 12:00 UTC = 13:00 CET fixed
        >>> dt_utc = datetime(2025, 7, 15, 12, 0, tzinfo=timezone.utc)
        >>> datetime_to_cet_fixed(dt_utc)
        datetime(2025, 7, 15, 13, 0, tzinfo=timezone(timedelta(hours=1)))
    """
    if dt.tzinfo is None:
        raise ValueError("Datetime must be timezone-aware (preferably UTC)")

    # Convert to UTC first, then add 1 hour for CET
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.astimezone(CET_FIXED_OFFSET)


def datetime_to_local_minute(
    dt: datetime,
    clock_mode: ClockMode = ClockMode.CET_FIXED
) -> Tuple[date, int]:
    """
    Convert a datetime to (date, minute_of_day) based on clock mode.

    This is the main entry point for tariff time calculations.

    Args:
        dt: Datetime to convert (should be tz-aware, preferably UTC)
        clock_mode: How to interpret time (CET_FIXED or LOCAL_TZ)

    Returns:
        Tuple of (date, minute_of_day)

    Examples:
        # Winter time (CET = CEST, no difference)
        >>> dt = datetime(2025, 1, 15, 12, 0, tzinfo=timezone.utc)  # 12:00 UTC
        >>> datetime_to_local_minute(dt, ClockMode.CET_FIXED)
        (date(2025, 1, 15), 780)  # 13:00 CET = minute 780

        # Summer time (CEST = CET + 1h)
        >>> dt = datetime(2025, 7, 15, 12, 0, tzinfo=timezone.utc)  # 12:00 UTC
        >>> datetime_to_local_minute(dt, ClockMode.CET_FIXED)
        (date(2025, 7, 15), 780)  # 13:00 CET = minute 780
        >>> datetime_to_local_minute(dt, ClockMode.LOCAL_TZ)
        (date(2025, 7, 15), 840)  # 14:00 CEST = minute 840
    """
    if dt.tzinfo is None:
        raise ValueError("Datetime must be timezone-aware (preferably UTC)")

    if clock_mode == ClockMode.CET_FIXED:
        local_dt = datetime_to_cet_fixed(dt)
    else:  # LOCAL_TZ
        local_dt = dt.astimezone(WARSAW_TZ)

    return local_dt.date(), local_dt.hour * 60 + local_dt.minute


def get_effective_day_type(
    dt: datetime,
    clock_mode: ClockMode = ClockMode.CET_FIXED
) -> DayType:
    """
    Get the effective day type for a datetime based on clock mode.

    This handles the edge case where UTC date differs from local date
    (around midnight).

    Args:
        dt: Datetime to check (should be tz-aware)
        clock_mode: How to interpret time

    Returns:
        DayType for the effective local date
    """
    effective_date, _ = datetime_to_local_minute(dt, clock_mode)
    return get_day_type(effective_date)


def format_minute_range(start_minute: int, end_minute: int) -> str:
    """
    Format a minute range as HH:MM-HH:MM string.

    Args:
        start_minute: Start minute of day (0-1439)
        end_minute: End minute of day (1-1440)

    Returns:
        Formatted string like "07:00-13:00" or "22:00-06:00" (wrap)

    Examples:
        >>> format_minute_range(420, 780)
        '07:00-13:00'
        >>> format_minute_range(1320, 360)  # wraps midnight
        '22:00-06:00'
    """
    start_h, start_m = divmod(start_minute, 60)

    # Handle end_minute = 1440 (midnight next day)
    if end_minute == 1440:
        end_h, end_m = 24, 0
    else:
        end_h, end_m = divmod(end_minute, 60)

    return f"{start_h:02d}:{start_m:02d}-{end_h:02d}:{end_m:02d}"


def is_dst_active(dt: datetime) -> bool:
    """
    Check if DST is active in Poland for a given datetime.

    Args:
        dt: Datetime to check (can be naive or aware)

    Returns:
        True if DST (CEST) is active, False if CET
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    local = dt.astimezone(WARSAW_TZ)

    # In Poland: CET = UTC+1, CEST = UTC+2
    # If offset is +2 hours, DST is active
    return local.utcoffset() == timedelta(hours=2)


def get_dst_transitions(year: int) -> Tuple[datetime, datetime]:
    """
    Get DST transition dates for Poland in a given year.

    Poland follows EU rules:
    - Spring forward: Last Sunday of March at 02:00 CET -> 03:00 CEST
    - Fall back: Last Sunday of October at 03:00 CEST -> 02:00 CET

    Args:
        year: Year to check

    Returns:
        Tuple of (spring_forward_utc, fall_back_utc) datetimes in UTC
    """
    # Find last Sunday of March
    march_31 = date(year, 3, 31)
    days_since_sunday = march_31.weekday() + 1  # Sunday = 6, so +1 to get days back
    if days_since_sunday == 7:
        days_since_sunday = 0
    spring_sunday = march_31 - timedelta(days=days_since_sunday)
    # Transition at 02:00 CET = 01:00 UTC
    spring_forward = datetime(spring_sunday.year, spring_sunday.month, spring_sunday.day, 1, 0, tzinfo=timezone.utc)

    # Find last Sunday of October
    october_31 = date(year, 10, 31)
    days_since_sunday = october_31.weekday() + 1
    if days_since_sunday == 7:
        days_since_sunday = 0
    fall_sunday = october_31 - timedelta(days=days_since_sunday)
    # Transition at 03:00 CEST = 01:00 UTC
    fall_back = datetime(fall_sunday.year, fall_sunday.month, fall_sunday.day, 1, 0, tzinfo=timezone.utc)

    return spring_forward, fall_back

"""
Polish calendar utilities for tariff and capacity fee calculation.

Handles:
- Polish public holidays (fixed and moveable)
- Workday/weekend classification
- Day type determination for fee and tariff calculation

Note: Capacity fee is only calculated for workdays (Pon-Pt, excluding holidays).
OSD tariffs use day types for zone determination.
"""

from datetime import datetime, date, timedelta
from enum import Enum
from typing import List, Set, Dict
from functools import lru_cache


class DayType(str, Enum):
    """
    Type of day for tariff and capacity fee calculation.

    Priority order (highest to lowest):
    1. HOLIDAY - always takes precedence
    2. SUNDAY - includes some holidays
    3. SATURDAY - regular Saturday
    4. WORKDAY - Monday-Friday, not a holiday
    """
    WORKDAY = "workday"      # Mon-Fri, not a holiday
    SATURDAY = "saturday"
    SUNDAY = "sunday"
    HOLIDAY = "holiday"      # Polish public holiday


# Fixed Polish public holidays (month, day)
# These apply to ALL years
POLISH_HOLIDAYS_FIXED = [
    (1, 1),    # Nowy Rok
    (1, 6),    # Trzech Króli (Objawienie Pańskie)
    (5, 1),    # Święto Pracy
    (5, 3),    # Święto Konstytucji 3 Maja
    (8, 15),   # Wniebowzięcie Najświętszej Maryi Panny
    (11, 1),   # Wszystkich Świętych
    (11, 11),  # Święto Niepodległości
    (12, 25),  # Boże Narodzenie (pierwszy dzień)
    (12, 26),  # Boże Narodzenie (drugi dzień)
]

# Wigilia — holiday only from 2025 (Dz.U. 2024 poz. 1911)
WIGILIA_START_YEAR = 2025


def _calculate_easter(year: int) -> date:
    """
    Calculate Easter Sunday date using the Anonymous Gregorian algorithm.

    This is the standard algorithm for calculating Easter date,
    also known as the "Computus" or Meeus/Jones/Butcher algorithm.
    """
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1

    return date(year, month, day)


@lru_cache(maxsize=50)
def get_polish_holidays(year: int) -> Set[date]:
    """
    Get all Polish public holidays for a given year.

    Returns a set of dates that are public holidays in Poland.
    Cached for performance.

    Polish public holidays:
    - Fixed: Nowy Rok, Trzech Króli, 1 Maja, 3 Maja, 15 Sierpnia,
             1 Listopada, 11 Listopada, 25-26 Grudnia
    - Moveable: Wielkanoc (Niedziela + Poniedziałek),
                Zielone Świątki (Niedziela), Boże Ciało (Czwartek)
    """
    holidays = set()

    # Add fixed holidays
    for month, day in POLISH_HOLIDAYS_FIXED:
        try:
            holidays.add(date(year, month, day))
        except ValueError:
            pass

    # Wigilia — only from 2025 (Dz.U. 2024 poz. 1911)
    if year >= WIGILIA_START_YEAR:
        holidays.add(date(year, 12, 24))

    # Calculate Easter-based moveable holidays
    easter = _calculate_easter(year)

    # Wielkanoc (Easter Sunday) - always Sunday, but included for completeness
    holidays.add(easter)

    # Poniedziałek Wielkanocny (Easter Monday)
    holidays.add(easter + timedelta(days=1))

    # Zielone Świątki (Pentecost Sunday) - 49 days after Easter
    holidays.add(easter + timedelta(days=49))

    # Boże Ciało (Corpus Christi) - 60 days after Easter (Thursday)
    holidays.add(easter + timedelta(days=60))

    return holidays


def is_polish_holiday(dt: date) -> bool:
    """Check if a date is a Polish public holiday."""
    if isinstance(dt, datetime):
        dt = dt.date()

    holidays = get_polish_holidays(dt.year)
    return dt in holidays


def is_workday(dt: date) -> bool:
    """
    Check if a date is a workday for capacity fee purposes.

    A workday is Monday-Friday that is NOT a public holiday.
    """
    if isinstance(dt, datetime):
        dt = dt.date()

    # Weekend check (Saturday=5, Sunday=6)
    if dt.weekday() >= 5:
        return False

    # Holiday check
    if is_polish_holiday(dt):
        return False

    return True


def get_day_type(dt: date) -> DayType:
    """
    Get the day type for tariff and capacity fee calculation.

    Priority order:
    1. HOLIDAY (takes precedence over SATURDAY/SUNDAY)
    2. SUNDAY
    3. SATURDAY
    4. WORKDAY

    Returns:
        DayType: WORKDAY, SATURDAY, SUNDAY, or HOLIDAY
    """
    if isinstance(dt, datetime):
        dt = dt.date()

    # Check if it's a holiday first (takes precedence)
    if is_polish_holiday(dt):
        return DayType.HOLIDAY

    # Check day of week
    weekday = dt.weekday()
    if weekday == 5:
        return DayType.SATURDAY
    elif weekday == 6:
        return DayType.SUNDAY
    else:
        return DayType.WORKDAY


def get_workdays_in_month(year: int, month: int) -> List[date]:
    """Get all workdays in a given month."""
    workdays = []

    # First day of month
    first_day = date(year, month, 1)

    # Find last day of month
    if month == 12:
        last_day = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = date(year, month + 1, 1) - timedelta(days=1)

    # Iterate through all days
    current = first_day
    while current <= last_day:
        if is_workday(current):
            workdays.append(current)
        current += timedelta(days=1)

    return workdays


def get_workdays_in_year(year: int) -> List[date]:
    """Get all workdays in a given year."""
    workdays = []
    for month in range(1, 13):
        workdays.extend(get_workdays_in_month(year, month))
    return workdays


def count_workdays_in_year(year: int) -> int:
    """Count total workdays in a year."""
    return len(get_workdays_in_year(year))


def get_decadal_periods(year: int, month: int) -> List[List[date]]:
    """
    Get decadal (10-day) periods for a month.

    Used for 2023-2024 qualification period.

    Returns:
        List of 3 lists: [days 1-10], [days 11-20], [days 21-end]
    """
    periods = [[], [], []]

    # First day of month
    first_day = date(year, month, 1)

    # Find last day of month
    if month == 12:
        last_day = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = date(year, month + 1, 1) - timedelta(days=1)

    # Iterate through all days
    current = first_day
    while current <= last_day:
        day = current.day
        if day <= 10:
            periods[0].append(current)
        elif day <= 20:
            periods[1].append(current)
        else:
            periods[2].append(current)
        current += timedelta(days=1)

    return periods


def get_quarter(month: int) -> str:
    """Get quarter string for a month (Q1, Q2, Q3, Q4)."""
    if month <= 3:
        return "Q1"
    elif month <= 6:
        return "Q2"
    elif month <= 9:
        return "Q3"
    else:
        return "Q4"


# Day type priority for overlap resolution
DAY_TYPE_PRIORITY = {
    DayType.HOLIDAY: 4,   # Highest priority
    DayType.SUNDAY: 3,
    DayType.SATURDAY: 2,
    DayType.WORKDAY: 1,   # Lowest priority
}


def compare_day_type_priority(dt1: DayType, dt2: DayType) -> int:
    """
    Compare two day types by priority.

    Returns:
        Positive if dt1 > dt2, negative if dt1 < dt2, 0 if equal
    """
    return DAY_TYPE_PRIORITY[dt1] - DAY_TYPE_PRIORITY[dt2]


# Pre-calculate holidays for common years (optimization)
_PRECALCULATED_YEARS = range(2020, 2040)
_HOLIDAY_CACHE: Dict[int, Set[date]] = {}

for _year in _PRECALCULATED_YEARS:
    _HOLIDAY_CACHE[_year] = get_polish_holidays(_year)

"""
Annualization helper module (v1.5.0).

Provides centralized annualization logic as Single Source of Truth (SSoT).

Key constants:
- HOURS_PER_YEAR = 8760 (standard non-leap year)
- DAYS_PER_YEAR = 365

Functions:
- compute_annualization_factor(period_hours): Returns scale factor to annual
- annualize_value(value, period_hours): Scales a value to annual equivalent
- is_full_year(period_hours): Returns True if period >= 8760 hours
- get_period_hours(n_points, interval_minutes): Compute period hours from inputs

Usage:
    from annualization_helper import annualize_value, compute_annualization_factor

    # Scale a 30-day savings to annual
    annual_savings = annualize_value(monthly_savings, period_hours=720)

    # Get factor for partial period
    factor = compute_annualization_factor(period_hours=720)  # Returns ~12.17
"""

from typing import Optional
from dataclasses import dataclass

# Standard year constants (non-leap year)
HOURS_PER_YEAR = 8760
DAYS_PER_YEAR = 365


def compute_annualization_factor(
    period_hours: float,
    cap_at_one: bool = True
) -> float:
    """
    Compute annualization factor: 8760 / period_hours.

    Args:
        period_hours: Analysis period length in hours
        cap_at_one: If True, return 1.0 for periods >= 8760 hours (default: True)

    Returns:
        Annualization factor (8760 / period_hours)
        Returns 1.0 if period_hours >= 8760 and cap_at_one is True.

    Raises:
        ValueError: If period_hours <= 0

    Examples:
        >>> compute_annualization_factor(8760)  # Full year
        1.0
        >>> compute_annualization_factor(720)   # ~30 days
        12.166666666666666
        >>> compute_annualization_factor(168)   # 1 week
        52.14285714285714
    """
    if period_hours <= 0:
        raise ValueError(f"period_hours must be positive, got {period_hours}")

    if cap_at_one and period_hours >= HOURS_PER_YEAR:
        return 1.0

    return HOURS_PER_YEAR / period_hours


def annualize_value(
    value: float,
    period_hours: float,
    cap_at_one: bool = True
) -> float:
    """
    Annualize a value based on period length.

    Scales the value to annual equivalent using the formula:
        annual_value = value * (8760 / period_hours)

    Args:
        value: Value to annualize (e.g., savings in PLN, energy in kWh)
        period_hours: Analysis period length in hours
        cap_at_one: If True, don't scale up values for periods >= 8760 hours

    Returns:
        Annualized value

    Raises:
        ValueError: If period_hours <= 0

    Examples:
        >>> annualize_value(1000, 720)   # 1000 PLN in 30 days -> annual
        12166.666666666666
        >>> annualize_value(8760, 8760)  # Full year, no scaling
        8760.0
    """
    factor = compute_annualization_factor(period_hours, cap_at_one=cap_at_one)
    return value * factor


def is_full_year(period_hours: float) -> bool:
    """
    Check if period covers at least one full year.

    Args:
        period_hours: Analysis period length in hours

    Returns:
        True if period_hours >= 8760

    Examples:
        >>> is_full_year(8760)
        True
        >>> is_full_year(8759)
        False
        >>> is_full_year(17520)  # 2 years
        True
    """
    return period_hours >= HOURS_PER_YEAR


def get_period_hours(n_points: int, interval_minutes: int) -> float:
    """
    Compute period hours from number of points and interval.

    Args:
        n_points: Number of data points
        interval_minutes: Time resolution in minutes (e.g., 60 for hourly, 15 for 15-min)

    Returns:
        Period length in hours

    Raises:
        ValueError: If n_points <= 0 or interval_minutes <= 0

    Examples:
        >>> get_period_hours(8760, 60)   # Hourly data for a year
        8760.0
        >>> get_period_hours(168, 60)    # 1 week of hourly data
        168.0
        >>> get_period_hours(672, 15)    # 1 week of 15-min data
        168.0
    """
    if n_points <= 0:
        raise ValueError(f"n_points must be positive, got {n_points}")
    if interval_minutes <= 0:
        raise ValueError(f"interval_minutes must be positive, got {interval_minutes}")

    return (n_points * interval_minutes) / 60.0


def get_period_days(period_hours: float) -> float:
    """
    Convert period hours to days.

    Args:
        period_hours: Analysis period length in hours

    Returns:
        Period length in days

    Examples:
        >>> get_period_days(8760)
        365.0
        >>> get_period_days(168)
        7.0
    """
    return period_hours / 24.0


@dataclass
class AnnualizationInfo:
    """
    Complete annualization info for a given period.

    Attributes:
        period_hours: Analysis period length in hours
        period_days: Analysis period length in days
        is_full_year: True if period >= 8760 hours
        annualization_factor: Scale factor (8760 / period_hours)
    """
    period_hours: float
    period_days: float
    is_full_year: bool
    annualization_factor: float


def get_annualization_info(
    period_hours: Optional[float] = None,
    n_points: Optional[int] = None,
    interval_minutes: Optional[int] = None,
) -> AnnualizationInfo:
    """
    Get complete annualization info from period parameters.

    Args:
        period_hours: Direct period hours (if known)
        n_points: Number of data points (alternative to period_hours)
        interval_minutes: Time resolution in minutes (required if n_points given)

    Returns:
        AnnualizationInfo dataclass with all computed values

    Raises:
        ValueError: If neither period_hours nor (n_points, interval_minutes) provided

    Examples:
        >>> info = get_annualization_info(period_hours=720)
        >>> info.annualization_factor
        12.166666666666666
        >>> info.period_days
        30.0
    """
    if period_hours is not None:
        hours = period_hours
    elif n_points is not None and interval_minutes is not None:
        hours = get_period_hours(n_points, interval_minutes)
    else:
        raise ValueError(
            "Either period_hours or both (n_points, interval_minutes) must be provided"
        )

    return AnnualizationInfo(
        period_hours=hours,
        period_days=get_period_days(hours),
        is_full_year=is_full_year(hours),
        annualization_factor=compute_annualization_factor(hours),
    )

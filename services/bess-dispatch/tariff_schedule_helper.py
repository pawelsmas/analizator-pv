"""
Tariff Schedule Helper (v2.1.0).

Generates price timeseries from custom tariff schedules with DST-safe mapping.

This module is the SINGLE SOURCE OF TRUTH for:
- Mapping timesteps to weekday/weekend schedules
- Handling holiday overrides
- DST-safe hour determination
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional, Set

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

from models import TariffScheduleConfig, PriceTimeseriesPlnPerMwh

logger = logging.getLogger(__name__)


def generate_price_timeseries_from_schedule(
    schedule: TariffScheduleConfig,
    n_steps: int,
    step_minutes: int,
    start_datetime: str,
    timezone: str = None,
) -> PriceTimeseriesPlnPerMwh:
    """
    Generate price timeseries from a custom tariff schedule.

    DST-safe implementation:
    - Converts each step to local time using proper timezone handling
    - 23-hour and 25-hour days during DST transitions are handled correctly

    Args:
        schedule: TariffScheduleConfig with 24-hour price arrays
        n_steps: Number of timesteps
        step_minutes: Time resolution (15 or 60)
        start_datetime: Period start (ISO 8601)
        timezone: Override timezone (defaults to schedule.timezone)

    Returns:
        PriceTimeseriesPlnPerMwh with per-step prices
    """
    # Use schedule timezone if not overridden
    tz_name = timezone or schedule.timezone
    tz = ZoneInfo(tz_name)

    # Parse start datetime
    try:
        start_dt = datetime.fromisoformat(start_datetime.replace('Z', '+00:00'))
    except ValueError:
        start_dt = datetime.fromisoformat(start_datetime)

    # Ensure start_dt is timezone-aware
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=tz)

    # Build holiday set for O(1) lookup
    holiday_set: Set[str] = set(schedule.holiday_dates)

    # Generate per-step prices
    import_prices = []
    export_prices = []
    other_fees = []

    for i in range(n_steps):
        # Calculate step datetime in local timezone
        step_dt = start_dt + timedelta(minutes=i * step_minutes)
        local_dt = step_dt.astimezone(tz)

        # Get date string for holiday check
        date_str = local_dt.strftime("%Y-%m-%d")

        # Determine if this is a weekend or holiday
        weekday = local_dt.weekday()  # 0=Monday, 6=Sunday
        is_weekend = weekday >= 5
        is_holiday = date_str in holiday_set

        # Use weekend schedule for weekends and holidays
        use_weekend_schedule = is_weekend or is_holiday

        # Get hour (0-23) for price lookup
        hour = local_dt.hour

        if use_weekend_schedule:
            import_prices.append(schedule.weekend_import_price_pln_per_mwh[hour])
            export_prices.append(schedule.weekend_export_price_pln_per_mwh[hour])
            other_fees.append(schedule.weekend_other_fees_pln_per_mwh[hour])
        else:
            import_prices.append(schedule.weekday_import_price_pln_per_mwh[hour])
            export_prices.append(schedule.weekday_export_price_pln_per_mwh[hour])
            other_fees.append(schedule.weekday_other_fees_pln_per_mwh[hour])

    # Calculate period end
    end_dt = start_dt + timedelta(minutes=(n_steps - 1) * step_minutes)

    return PriceTimeseriesPlnPerMwh(
        import_price_pln_per_mwh=import_prices,
        export_price_pln_per_mwh=export_prices,
        other_fees_pln_per_mwh=other_fees,
        unserved_penalty_pln_per_kwh=[10.0] * n_steps,
        step_minutes=step_minutes,
        steps=n_steps,
        timezone=tz_name,
        period_start=start_datetime,
        period_end=end_dt.isoformat(),
    )


def validate_schedule(schedule: TariffScheduleConfig) -> List[str]:
    """
    Validate tariff schedule configuration.

    Returns:
        List of error messages (empty if valid)
    """
    errors = []

    # Check weekday import prices length
    if len(schedule.weekday_import_price_pln_per_mwh) != 24:
        errors.append(
            f"weekday_import_price must have 24 values, got {len(schedule.weekday_import_price_pln_per_mwh)}"
        )

    # Check weekend import prices length
    if len(schedule.weekend_import_price_pln_per_mwh) != 24:
        errors.append(
            f"weekend_import_price must have 24 values, got {len(schedule.weekend_import_price_pln_per_mwh)}"
        )

    # Check for negative prices
    for name, arr in [
        ("weekday_import_price", schedule.weekday_import_price_pln_per_mwh),
        ("weekend_import_price", schedule.weekend_import_price_pln_per_mwh),
        ("weekday_export_price", schedule.weekday_export_price_pln_per_mwh),
        ("weekend_export_price", schedule.weekend_export_price_pln_per_mwh),
    ]:
        for i, v in enumerate(arr):
            if v < 0:
                errors.append(f"{name}[{i}] is negative: {v}")

    # Validate holiday date format
    for date_str in schedule.holiday_dates:
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            errors.append(f"Invalid holiday date format: {date_str} (expected YYYY-MM-DD)")

    # Validate timezone
    try:
        ZoneInfo(schedule.timezone)
    except Exception:
        errors.append(f"Invalid timezone: {schedule.timezone}")

    return errors

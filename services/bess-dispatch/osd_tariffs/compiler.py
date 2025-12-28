"""
Tariff Compiler - converts timestamps to zones and prices.

The compiler takes a tariff definition and produces:
1. Zone assignments for each minute/hour
2. Rate lookups for specific timestamps
3. Pre-compiled day schedules for performance

Key concepts:
- ClockMode: Determines how timestamps are interpreted (CET_FIXED vs LOCAL_TZ)
- Compiled schedule: Pre-computed zone map for each day type
- Rate resolution: Zone -> component -> rate
"""

from datetime import datetime, date, timedelta, timezone
from typing import List, Dict, Optional, Tuple, NamedTuple
from functools import lru_cache
import numpy as np

from .models import (
    OsdTariff,
    ScheduleBlock,
    Segment,
    ZoneId,
    TariffComponent,
    CompiledTariffHour,
    ChargeBasis,
    TimeDependency,
)
from .validators import get_minute_zones

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from common.calendar_pl import DayType, get_day_type
from common.time_utils import (
    ClockMode,
    datetime_to_local_minute,
    get_effective_day_type,
    WARSAW_TZ,
    CET_FIXED_OFFSET,
)


class CompiledDay(NamedTuple):
    """Pre-compiled zone and rate data for a single day."""
    date: date
    day_type: DayType
    zones: List[ZoneId]  # 1440 minute zones
    hourly_zones: List[ZoneId]  # 24 hour zones (majority vote)
    hourly_rates: List[float]  # 24 hour rates


class TariffCompiler:
    """
    Compiles OSD tariffs for efficient lookups.

    Usage:
        compiler = TariffCompiler(tariff)
        zone = compiler.get_zone_for_datetime(dt)
        rate = compiler.get_rate_for_datetime(dt)
        compiled = compiler.compile_day(target_date)
    """

    def __init__(self, tariff: OsdTariff):
        """
        Initialize compiler with a tariff.

        Args:
            tariff: The OSD tariff to compile
        """
        self.tariff = tariff
        self._schedule_cache: Dict[date, ScheduleBlock] = {}
        self._day_cache: Dict[date, CompiledDay] = {}

    def get_active_schedule(self, target_date: date) -> Optional[ScheduleBlock]:
        """
        Get the active schedule block for a date.

        Uses caching for performance.
        """
        if target_date in self._schedule_cache:
            return self._schedule_cache[target_date]

        schedule = self.tariff.get_active_schedule(target_date)
        self._schedule_cache[target_date] = schedule
        return schedule

    def compile_day(self, target_date: date) -> Optional[CompiledDay]:
        """
        Compile zone and rate data for a specific date.

        Returns:
            CompiledDay with minute-by-minute zones and hourly aggregates,
            or None if no schedule is active for this date.
        """
        if target_date in self._day_cache:
            return self._day_cache[target_date]

        schedule = self.get_active_schedule(target_date)
        if schedule is None:
            return None

        day_type = get_day_type(target_date)

        # Get minute-by-minute zone assignments
        minute_zones = get_minute_zones(schedule.segments, day_type)

        # Fill any None values with FLAT (fallback)
        zones = [z if z is not None else ZoneId.FLAT for z in minute_zones]

        # Calculate hourly zones (majority vote within each hour)
        hourly_zones = self._aggregate_to_hourly_zones(zones)

        # Calculate hourly rates
        hourly_rates = [
            self._get_zone_rate(zone) for zone in hourly_zones
        ]

        compiled = CompiledDay(
            date=target_date,
            day_type=day_type,
            zones=zones,
            hourly_zones=hourly_zones,
            hourly_rates=hourly_rates,
        )

        self._day_cache[target_date] = compiled
        return compiled

    def _aggregate_to_hourly_zones(self, minute_zones: List[ZoneId]) -> List[ZoneId]:
        """
        Aggregate 1440 minute zones to 24 hourly zones.

        Uses majority vote within each hour.
        """
        hourly_zones = []

        for hour in range(24):
            start_minute = hour * 60
            end_minute = start_minute + 60
            hour_zones = minute_zones[start_minute:end_minute]

            # Count occurrences of each zone
            zone_counts: Dict[ZoneId, int] = {}
            for zone in hour_zones:
                zone_counts[zone] = zone_counts.get(zone, 0) + 1

            # Find the zone with most minutes (majority)
            majority_zone = max(zone_counts, key=zone_counts.get)
            hourly_zones.append(majority_zone)

        return hourly_zones

    def _get_zone_rate(self, zone_id: ZoneId) -> float:
        """
        Get the energy rate for a zone.

        Looks for first energy component with zone-based rates.
        """
        for component in self.tariff.components:
            if (component.charge_basis == ChargeBasis.ENERGY and
                component.time_dependency == TimeDependency.ZONE_BASED):
                rate = component.rates.get(zone_id)
                if rate is not None:
                    return rate

        # Fallback to first energy component with any rate
        for component in self.tariff.components:
            if component.charge_basis == ChargeBasis.ENERGY:
                rate = component.get_rate(zone_id)
                if rate is not None:
                    return rate

        return 0.0

    def get_zone_for_datetime(
        self,
        dt: datetime,
        clock_mode: Optional[ClockMode] = None
    ) -> Optional[ZoneId]:
        """
        Get the zone for a specific datetime.

        Args:
            dt: Datetime to look up (should be tz-aware, preferably UTC)
            clock_mode: Override tariff's clock mode if specified

        Returns:
            ZoneId or None if no schedule active
        """
        mode = clock_mode or self.tariff.clock_mode
        effective_date, minute = datetime_to_local_minute(dt, mode)

        compiled = self.compile_day(effective_date)
        if compiled is None:
            return None

        return compiled.zones[minute]

    def get_rate_for_datetime(
        self,
        dt: datetime,
        clock_mode: Optional[ClockMode] = None
    ) -> Optional[float]:
        """
        Get the energy rate for a specific datetime.

        Args:
            dt: Datetime to look up
            clock_mode: Override tariff's clock mode if specified

        Returns:
            Rate in PLN/kWh or None if no schedule active
        """
        zone = self.get_zone_for_datetime(dt, clock_mode)
        if zone is None:
            return None
        return self._get_zone_rate(zone)

    def compile_hour(
        self,
        dt: datetime,
        clock_mode: Optional[ClockMode] = None
    ) -> Optional[CompiledTariffHour]:
        """
        Compile tariff data for a specific hour.

        Returns:
            CompiledTariffHour or None if no schedule active
        """
        mode = clock_mode or self.tariff.clock_mode
        effective_date, minute = datetime_to_local_minute(dt, mode)
        hour = minute // 60

        compiled = self.compile_day(effective_date)
        if compiled is None:
            return None

        return CompiledTariffHour(
            hour=hour,
            zone_id=compiled.hourly_zones[hour],
            rate=compiled.hourly_rates[hour],
            day_type=compiled.day_type,
        )

    def compile_day_hours(
        self,
        target_date: date
    ) -> Optional[List[CompiledTariffHour]]:
        """
        Compile all 24 hours for a date.

        Returns list of CompiledTariffHour or None if no schedule active.
        """
        compiled = self.compile_day(target_date)
        if compiled is None:
            return None

        return [
            CompiledTariffHour(
                hour=hour,
                zone_id=compiled.hourly_zones[hour],
                rate=compiled.hourly_rates[hour],
                day_type=compiled.day_type,
            )
            for hour in range(24)
        ]

    def compile_range(
        self,
        start_date: date,
        end_date: date
    ) -> Dict[date, CompiledDay]:
        """
        Compile tariff data for a date range.

        Args:
            start_date: First date (inclusive)
            end_date: Last date (inclusive)

        Returns:
            Dict mapping dates to CompiledDay objects
        """
        result = {}
        current = start_date

        while current <= end_date:
            compiled = self.compile_day(current)
            if compiled is not None:
                result[current] = compiled
            current += timedelta(days=1)

        return result

    def get_hourly_rates_array(
        self,
        start_date: date,
        end_date: date
    ) -> np.ndarray:
        """
        Get a numpy array of hourly rates for a date range.

        Useful for vectorized calculations in dispatch engine.

        Returns:
            numpy array of shape (n_days, 24) with rates
        """
        compiled_range = self.compile_range(start_date, end_date)

        n_days = (end_date - start_date).days + 1
        rates = np.zeros((n_days, 24))

        for i, d in enumerate(range(n_days)):
            current_date = start_date + timedelta(days=d)
            if current_date in compiled_range:
                rates[i] = compiled_range[current_date].hourly_rates

        return rates

    def clear_cache(self):
        """Clear all cached data."""
        self._schedule_cache.clear()
        self._day_cache.clear()


# Convenience functions for single-use compilation


def compile_tariff_for_date(
    tariff: OsdTariff,
    target_date: date
) -> Optional[CompiledDay]:
    """
    Compile a tariff for a single date.

    Convenience function for one-off compilations.
    """
    compiler = TariffCompiler(tariff)
    return compiler.compile_day(target_date)


def compile_tariff_for_range(
    tariff: OsdTariff,
    start_date: date,
    end_date: date
) -> Dict[date, CompiledDay]:
    """
    Compile a tariff for a date range.

    Convenience function for one-off compilations.
    """
    compiler = TariffCompiler(tariff)
    return compiler.compile_range(start_date, end_date)


def get_zone_for_timestamp(
    tariff: OsdTariff,
    dt: datetime
) -> Optional[ZoneId]:
    """
    Get zone for a timestamp.

    Convenience function for one-off lookups.
    """
    compiler = TariffCompiler(tariff)
    return compiler.get_zone_for_datetime(dt)


def get_rate_for_timestamp(
    tariff: OsdTariff,
    dt: datetime
) -> Optional[float]:
    """
    Get rate for a timestamp.

    Convenience function for one-off lookups.
    """
    compiler = TariffCompiler(tariff)
    return compiler.get_rate_for_datetime(dt)


class TariffCalculator:
    """
    Calculator for tariff-based energy costs.

    Integrates with dispatch engine for cost calculations.
    """

    def __init__(self, tariff: OsdTariff):
        self.tariff = tariff
        self.compiler = TariffCompiler(tariff)

    def calculate_energy_cost(
        self,
        consumption_kwh: np.ndarray,
        timestamps: List[datetime]
    ) -> Tuple[float, Dict[str, float]]:
        """
        Calculate energy cost for a consumption profile.

        Args:
            consumption_kwh: Array of energy consumption values
            timestamps: List of timestamps corresponding to consumption

        Returns:
            Tuple of (total_cost, zone_breakdown)
        """
        total_cost = 0.0
        zone_costs: Dict[str, float] = {}
        zone_consumption: Dict[str, float] = {}

        for i, (kwh, dt) in enumerate(zip(consumption_kwh, timestamps)):
            zone = self.compiler.get_zone_for_datetime(dt)
            if zone is None:
                continue

            rate = self.compiler._get_zone_rate(zone)
            cost = kwh * rate

            total_cost += cost

            zone_key = zone.value
            zone_costs[zone_key] = zone_costs.get(zone_key, 0.0) + cost
            zone_consumption[zone_key] = zone_consumption.get(zone_key, 0.0) + kwh

        return total_cost, {
            "zone_costs": zone_costs,
            "zone_consumption": zone_consumption,
        }

    def calculate_savings_potential(
        self,
        consumption_kwh: np.ndarray,
        timestamps: List[datetime]
    ) -> Dict[str, float]:
        """
        Calculate potential savings from load shifting.

        Returns dict with:
        - current_cost: Current energy cost
        - min_possible_cost: Cost if all consumption was in cheapest zone
        - max_savings: Maximum possible savings
        - savings_percent: Percentage savings potential
        """
        zones_used = self.tariff.get_zones_used()

        # Find cheapest and most expensive rates
        rates = {}
        for zone in zones_used:
            rate = self.compiler._get_zone_rate(zone)
            rates[zone] = rate

        min_rate = min(rates.values()) if rates else 0.0
        max_rate = max(rates.values()) if rates else 0.0

        # Calculate current cost
        current_cost, _ = self.calculate_energy_cost(consumption_kwh, timestamps)

        # Calculate minimum possible cost
        total_consumption = float(np.sum(consumption_kwh))
        min_possible_cost = total_consumption * min_rate

        return {
            "current_cost": current_cost,
            "min_possible_cost": min_possible_cost,
            "max_savings": current_cost - min_possible_cost,
            "savings_percent": (
                (current_cost - min_possible_cost) / current_cost * 100
                if current_cost > 0 else 0.0
            ),
            "cheapest_zone": min(rates, key=rates.get).value if rates else None,
            "cheapest_rate": min_rate,
        }

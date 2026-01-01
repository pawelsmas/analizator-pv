"""
Cycle Accounting Helper (v2.2.0 SSoT).

Single source of truth for battery cycle calculations:
- Equivalent Full Cycles (EFC) = discharge_kwh / usable_capacity_kwh
- Cycles per day tracking
- Throughput tracking
- Cycle limit enforcement

Tie-breakers for determinism (v2.1.0):
1. Higher NPV
2. Lower CAPEX
3. Alphabetical variant name
"""

from typing import Optional, List, Tuple
from dataclasses import dataclass
import numpy as np


@dataclass
class CycleAccountingState:
    """State for cycle accounting during dispatch."""
    discharge_kwh_today: float = 0.0
    charge_kwh_today: float = 0.0
    current_day: int = 0
    daily_discharge_kwh: List[float] = None  # Track per-day discharge
    daily_charge_kwh: List[float] = None  # Track per-day charge

    def __post_init__(self):
        if self.daily_discharge_kwh is None:
            self.daily_discharge_kwh = []
        if self.daily_charge_kwh is None:
            self.daily_charge_kwh = []


@dataclass
class CycleSummary:
    """Summary of cycle accounting for a dispatch period."""
    total_discharge_kwh: float
    total_charge_kwh: float
    total_throughput_kwh: float
    efc_total: float
    cycles_per_day: List[float]  # EFC per calendar day
    max_daily_efc: float
    avg_daily_efc: float
    days_exceeding_limit: int  # Days where EFC > max_cycles_per_day


def compute_efc(
    discharge_kwh: float,
    usable_capacity_kwh: float,
) -> float:
    """
    Compute Equivalent Full Cycles.

    EFC = discharge_kwh / usable_capacity_kwh

    Args:
        discharge_kwh: Total discharge energy [kWh]
        usable_capacity_kwh: Usable battery capacity [kWh]

    Returns:
        EFC value (cycles)
    """
    if usable_capacity_kwh <= 0:
        return 0.0
    return discharge_kwh / usable_capacity_kwh


def compute_throughput_mwh(
    charge_kwh: float,
    discharge_kwh: float,
) -> float:
    """
    Compute total throughput in MWh.

    Throughput = (charge + discharge) / 1000

    Args:
        charge_kwh: Total charge energy [kWh]
        discharge_kwh: Total discharge energy [kWh]

    Returns:
        Throughput [MWh]
    """
    return (charge_kwh + discharge_kwh) / 1000.0


def get_day_index(
    step: int,
    step_minutes: int,
) -> int:
    """
    Get calendar day index for a given timestep.

    Assumes step 0 starts at midnight of day 0.

    Args:
        step: Timestep index (0-based)
        step_minutes: Duration of each step in minutes

    Returns:
        Day index (0-based)
    """
    minutes_from_start = step * step_minutes
    hours_from_start = minutes_from_start / 60.0
    return int(hours_from_start // 24)


def compute_cycles_per_day(
    discharge_kw: np.ndarray,
    step_minutes: int,
    usable_capacity_kwh: float,
) -> List[float]:
    """
    Compute EFC for each calendar day.

    Args:
        discharge_kw: Discharge power per step [kW]
        step_minutes: Duration of each step in minutes
        usable_capacity_kwh: Usable battery capacity [kWh]

    Returns:
        List of EFC per day
    """
    n = len(discharge_kw)
    if n == 0:
        return []

    dt_hours = step_minutes / 60.0

    # Determine number of days
    max_day = get_day_index(n - 1, step_minutes)
    daily_discharge_kwh = [0.0] * (max_day + 1)

    # Accumulate discharge per day
    for t in range(n):
        day = get_day_index(t, step_minutes)
        daily_discharge_kwh[day] += discharge_kw[t] * dt_hours

    # Convert to EFC
    cycles_per_day = [
        compute_efc(d, usable_capacity_kwh) for d in daily_discharge_kwh
    ]

    return cycles_per_day


def compute_cycle_summary(
    charge_kw: np.ndarray,
    discharge_kw: np.ndarray,
    step_minutes: int,
    usable_capacity_kwh: float,
    max_cycles_per_day: Optional[float] = None,
) -> CycleSummary:
    """
    Compute comprehensive cycle summary for a dispatch period.

    Args:
        charge_kw: Charge power per step [kW]
        discharge_kw: Discharge power per step [kW]
        step_minutes: Duration of each step in minutes
        usable_capacity_kwh: Usable battery capacity [kWh]
        max_cycles_per_day: Optional limit (for counting exceeded days)

    Returns:
        CycleSummary with all metrics
    """
    n = len(discharge_kw)
    dt_hours = step_minutes / 60.0

    total_discharge_kwh = float(np.sum(discharge_kw) * dt_hours)
    total_charge_kwh = float(np.sum(charge_kw) * dt_hours)
    total_throughput_kwh = total_discharge_kwh + total_charge_kwh
    efc_total = compute_efc(total_discharge_kwh, usable_capacity_kwh)

    cycles_per_day = compute_cycles_per_day(
        discharge_kw, step_minutes, usable_capacity_kwh
    )

    max_daily_efc = max(cycles_per_day) if cycles_per_day else 0.0
    avg_daily_efc = sum(cycles_per_day) / len(cycles_per_day) if cycles_per_day else 0.0

    # Count days exceeding limit
    days_exceeding_limit = 0
    if max_cycles_per_day is not None:
        days_exceeding_limit = sum(1 for c in cycles_per_day if c > max_cycles_per_day)

    return CycleSummary(
        total_discharge_kwh=total_discharge_kwh,
        total_charge_kwh=total_charge_kwh,
        total_throughput_kwh=total_throughput_kwh,
        efc_total=efc_total,
        cycles_per_day=cycles_per_day,
        max_daily_efc=max_daily_efc,
        avg_daily_efc=avg_daily_efc,
        days_exceeding_limit=days_exceeding_limit,
    )


def compute_remaining_discharge_headroom(
    discharge_kwh_today: float,
    usable_capacity_kwh: float,
    max_cycles_per_day: float,
) -> float:
    """
    Compute remaining discharge headroom for the current day.

    Args:
        discharge_kwh_today: Discharge already done today [kWh]
        usable_capacity_kwh: Usable battery capacity [kWh]
        max_cycles_per_day: Maximum EFC per day

    Returns:
        Remaining discharge headroom [kWh] (0 if limit reached)
    """
    max_daily_discharge_kwh = max_cycles_per_day * usable_capacity_kwh
    remaining = max_daily_discharge_kwh - discharge_kwh_today
    return max(0.0, remaining)


def clamp_discharge_for_cycle_limit(
    desired_discharge_kw: float,
    discharge_kwh_today: float,
    usable_capacity_kwh: float,
    max_cycles_per_day: float,
    dt_hours: float,
) -> Tuple[float, float]:
    """
    Clamp discharge power to respect daily cycle limit.

    Args:
        desired_discharge_kw: Desired discharge power [kW]
        discharge_kwh_today: Discharge already done today [kWh]
        usable_capacity_kwh: Usable battery capacity [kWh]
        max_cycles_per_day: Maximum EFC per day
        dt_hours: Timestep duration [hours]

    Returns:
        Tuple of (clamped_discharge_kw, actual_discharge_kwh)
    """
    if desired_discharge_kw <= 0:
        return 0.0, 0.0

    # Compute remaining headroom
    remaining_kwh = compute_remaining_discharge_headroom(
        discharge_kwh_today, usable_capacity_kwh, max_cycles_per_day
    )

    if remaining_kwh <= 0:
        # Limit reached, no discharge allowed
        return 0.0, 0.0

    # Compute desired energy this step
    desired_kwh = desired_discharge_kw * dt_hours

    # Clamp to remaining headroom
    actual_kwh = min(desired_kwh, remaining_kwh)
    actual_kw = actual_kwh / dt_hours if dt_hours > 0 else 0.0

    return actual_kw, actual_kwh


class CycleAccountingTracker:
    """
    Tracker for real-time cycle accounting during dispatch.

    Usage:
        tracker = CycleAccountingTracker(usable_capacity_kwh, max_cycles_per_day, step_minutes)
        for t in range(n_steps):
            discharge_kw, clamped = tracker.process_step(t, desired_discharge_kw, dt_hours)
            # Use discharge_kw in dispatch
    """

    def __init__(
        self,
        usable_capacity_kwh: float,
        max_cycles_per_day: Optional[float],
        step_minutes: int,
    ):
        self.usable_capacity_kwh = usable_capacity_kwh
        self.max_cycles_per_day = max_cycles_per_day
        self.step_minutes = step_minutes

        self.current_day = -1
        self.discharge_kwh_today = 0.0
        self.charge_kwh_today = 0.0

        # Track per-day stats
        self.daily_discharge_kwh: List[float] = []
        self.daily_charge_kwh: List[float] = []
        self.total_clamped_events = 0

    def process_step(
        self,
        step: int,
        desired_discharge_kw: float,
        dt_hours: float,
        charge_kw: float = 0.0,
    ) -> Tuple[float, bool]:
        """
        Process a timestep and return allowed discharge.

        Args:
            step: Timestep index
            desired_discharge_kw: Desired discharge power [kW]
            dt_hours: Timestep duration [hours]
            charge_kw: Charge power this step [kW] (for tracking)

        Returns:
            Tuple of (allowed_discharge_kw, was_clamped)
        """
        # Check for day boundary
        day = get_day_index(step, self.step_minutes)
        if day != self.current_day:
            # Save previous day's stats
            if self.current_day >= 0:
                self.daily_discharge_kwh.append(self.discharge_kwh_today)
                self.daily_charge_kwh.append(self.charge_kwh_today)

            # Reset for new day
            self.current_day = day
            self.discharge_kwh_today = 0.0
            self.charge_kwh_today = 0.0

        # Track charge
        self.charge_kwh_today += charge_kw * dt_hours

        # If no cycle limit, return desired discharge
        if self.max_cycles_per_day is None:
            self.discharge_kwh_today += desired_discharge_kw * dt_hours
            return desired_discharge_kw, False

        # Apply cycle limit
        clamped_kw, actual_kwh = clamp_discharge_for_cycle_limit(
            desired_discharge_kw,
            self.discharge_kwh_today,
            self.usable_capacity_kwh,
            self.max_cycles_per_day,
            dt_hours,
        )

        self.discharge_kwh_today += actual_kwh
        was_clamped = clamped_kw < desired_discharge_kw
        if was_clamped:
            self.total_clamped_events += 1

        return clamped_kw, was_clamped

    def finalize(self) -> CycleSummary:
        """
        Finalize tracking and return summary.

        Call after processing all steps.
        """
        # Save last day's stats
        if self.current_day >= 0:
            self.daily_discharge_kwh.append(self.discharge_kwh_today)
            self.daily_charge_kwh.append(self.charge_kwh_today)

        total_discharge = sum(self.daily_discharge_kwh)
        total_charge = sum(self.daily_charge_kwh)

        cycles_per_day = [
            compute_efc(d, self.usable_capacity_kwh)
            for d in self.daily_discharge_kwh
        ]

        max_daily = max(cycles_per_day) if cycles_per_day else 0.0
        avg_daily = sum(cycles_per_day) / len(cycles_per_day) if cycles_per_day else 0.0

        days_exceeding = 0
        if self.max_cycles_per_day is not None:
            days_exceeding = sum(
                1 for c in cycles_per_day if c > self.max_cycles_per_day
            )

        return CycleSummary(
            total_discharge_kwh=total_discharge,
            total_charge_kwh=total_charge,
            total_throughput_kwh=total_discharge + total_charge,
            efc_total=compute_efc(total_discharge, self.usable_capacity_kwh),
            cycles_per_day=cycles_per_day,
            max_daily_efc=max_daily,
            avg_daily_efc=avg_daily,
            days_exceeding_limit=days_exceeding,
        )

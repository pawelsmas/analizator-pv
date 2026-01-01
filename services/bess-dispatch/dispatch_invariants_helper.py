"""
Dispatch Invariants Helper (v2.2.0 SSoT).

Single source of truth for dispatch correctness invariants:
1. SOC bounds: 0 <= soc_kwh <= energy_kwh
2. Power limits: charge/discharge <= power_kw
3. No simultaneous charge/discharge: not (charge > 0 and discharge > 0)
4. Energy balance: soc changes match charge/discharge

STRICT_INVARIANTS env var:
- When True: raise exception on any violation (fail-fast for debugging)
- When False: log warning and continue (default for production)
"""

import os
from typing import List, Tuple, Optional
from dataclasses import dataclass, field
import numpy as np


# Check for strict mode from environment
def is_strict_mode() -> bool:
    """Check if STRICT_INVARIANTS is enabled."""
    return os.environ.get("STRICT_INVARIANTS", "").lower() in ("true", "1", "yes")


@dataclass
class InvariantViolation:
    """Single invariant violation record."""
    step: int
    invariant: str  # "soc_min", "soc_max", "power_charge", "power_discharge", "simultaneous", "energy_balance"
    message: str
    actual_value: float
    expected_bound: float
    severity: str = "error"  # "error" or "warning"


@dataclass
class InvariantCheckResult:
    """Result of invariant checks on dispatch arrays."""
    all_ok: bool = True
    violations: List[InvariantViolation] = field(default_factory=list)

    # Summary counts
    soc_min_violations: int = 0
    soc_max_violations: int = 0
    power_charge_violations: int = 0
    power_discharge_violations: int = 0
    simultaneous_violations: int = 0
    energy_balance_violations: int = 0

    # For compatibility with existing invariants field
    def to_dict(self) -> dict:
        """Convert to dict for JSON response."""
        return {
            "all_ok": self.all_ok,
            "soc_bounds_ok": self.soc_min_violations == 0 and self.soc_max_violations == 0,
            "power_limits_ok": self.power_charge_violations == 0 and self.power_discharge_violations == 0,
            "no_simultaneous_ok": self.simultaneous_violations == 0,
            "energy_balance_ok": self.energy_balance_violations == 0,
            "violations_count": len(self.violations),
            "violations": [
                {
                    "step": v.step,
                    "invariant": v.invariant,
                    "message": v.message,
                }
                for v in self.violations[:10]  # Limit to first 10
            ],
        }


class DispatchInvariantViolationError(Exception):
    """Exception raised in strict mode when invariant is violated."""

    def __init__(self, result: InvariantCheckResult):
        self.result = result
        super().__init__(
            f"Dispatch invariant violation: {result.violations[0].message if result.violations else 'unknown'}"
        )


def check_soc_bounds(
    soc_kwh: np.ndarray,
    energy_kwh: float,
    tolerance: float = 1e-6,
) -> List[InvariantViolation]:
    """
    Check SOC bounds invariant: 0 <= soc <= energy_kwh.

    Args:
        soc_kwh: SOC array [kWh]
        energy_kwh: Battery capacity [kWh]
        tolerance: Floating-point tolerance

    Returns:
        List of violations (empty if OK)
    """
    violations = []

    for t, soc in enumerate(soc_kwh):
        if soc < -tolerance:
            violations.append(InvariantViolation(
                step=t,
                invariant="soc_min",
                message=f"SOC below zero: {soc:.6f} kWh",
                actual_value=soc,
                expected_bound=0.0,
            ))
        elif soc > energy_kwh + tolerance:
            violations.append(InvariantViolation(
                step=t,
                invariant="soc_max",
                message=f"SOC exceeds capacity: {soc:.6f} > {energy_kwh:.6f} kWh",
                actual_value=soc,
                expected_bound=energy_kwh,
            ))

    return violations


def check_power_limits(
    charge_kw: np.ndarray,
    discharge_kw: np.ndarray,
    power_kw: float,
    tolerance: float = 1e-6,
) -> List[InvariantViolation]:
    """
    Check power limits invariant: charge/discharge <= power_kw.

    Args:
        charge_kw: Charge power array [kW]
        discharge_kw: Discharge power array [kW]
        power_kw: Battery power rating [kW]
        tolerance: Floating-point tolerance

    Returns:
        List of violations (empty if OK)
    """
    violations = []

    for t, (ch, dis) in enumerate(zip(charge_kw, discharge_kw)):
        if ch > power_kw + tolerance:
            violations.append(InvariantViolation(
                step=t,
                invariant="power_charge",
                message=f"Charge exceeds power rating: {ch:.6f} > {power_kw:.6f} kW",
                actual_value=ch,
                expected_bound=power_kw,
            ))
        if dis > power_kw + tolerance:
            violations.append(InvariantViolation(
                step=t,
                invariant="power_discharge",
                message=f"Discharge exceeds power rating: {dis:.6f} > {power_kw:.6f} kW",
                actual_value=dis,
                expected_bound=power_kw,
            ))

    return violations


def check_no_simultaneous(
    charge_kw: np.ndarray,
    discharge_kw: np.ndarray,
    tolerance: float = 1e-6,
) -> List[InvariantViolation]:
    """
    Check no-simultaneous invariant: not (charge > 0 and discharge > 0).

    Args:
        charge_kw: Charge power array [kW]
        discharge_kw: Discharge power array [kW]
        tolerance: Floating-point tolerance

    Returns:
        List of violations (empty if OK)
    """
    violations = []

    for t, (ch, dis) in enumerate(zip(charge_kw, discharge_kw)):
        if ch > tolerance and dis > tolerance:
            violations.append(InvariantViolation(
                step=t,
                invariant="simultaneous",
                message=f"Simultaneous charge/discharge: {ch:.6f} kW charge, {dis:.6f} kW discharge",
                actual_value=ch,
                expected_bound=0.0,
            ))

    return violations


def check_energy_balance(
    soc_kwh: np.ndarray,
    charge_kw: np.ndarray,
    discharge_kw: np.ndarray,
    dt_hours: float,
    eta_charge: float,
    eta_discharge: float,
    tolerance: float = 0.1,  # Larger tolerance for accumulated errors
) -> List[InvariantViolation]:
    """
    Check energy balance invariant: soc[t+1] = soc[t] + charge*eta - discharge/eta.

    Note: This is an approximate check due to efficiency losses being
    distributed across charge/discharge. Larger tolerance used.

    Args:
        soc_kwh: SOC array [kWh] with length n+1
        charge_kw: Charge power array [kW] with length n
        discharge_kw: Discharge power array [kW] with length n
        dt_hours: Timestep duration [hours]
        eta_charge: Charge efficiency (0-1)
        eta_discharge: Discharge efficiency (0-1)
        tolerance: Energy balance tolerance [kWh]

    Returns:
        List of violations (empty if OK)
    """
    violations = []
    n = len(charge_kw)

    for t in range(n):
        # Expected SOC change
        energy_in = charge_kw[t] * dt_hours * eta_charge
        energy_out = discharge_kw[t] * dt_hours / eta_discharge if eta_discharge > 0 else 0

        expected_soc = soc_kwh[t] + energy_in - energy_out
        actual_soc = soc_kwh[t + 1] if t + 1 < len(soc_kwh) else soc_kwh[t]

        diff = abs(actual_soc - expected_soc)
        if diff > tolerance:
            violations.append(InvariantViolation(
                step=t,
                invariant="energy_balance",
                message=f"Energy balance mismatch: expected {expected_soc:.3f}, got {actual_soc:.3f} kWh (diff={diff:.3f})",
                actual_value=diff,
                expected_bound=tolerance,
                severity="warning",
            ))

    return violations


def check_dispatch_invariants(
    soc_kwh: np.ndarray,
    charge_kw: np.ndarray,
    discharge_kw: np.ndarray,
    energy_kwh: float,
    power_kw: float,
    dt_hours: float = 1.0,
    eta_charge: float = 0.95,
    eta_discharge: float = 0.95,
    tolerance: float = 1e-6,
) -> InvariantCheckResult:
    """
    Run all dispatch invariant checks.

    Args:
        soc_kwh: SOC array [kWh] (length n or n+1)
        charge_kw: Charge power array [kW] (length n)
        discharge_kw: Discharge power array [kW] (length n)
        energy_kwh: Battery capacity [kWh]
        power_kw: Battery power rating [kW]
        dt_hours: Timestep duration [hours]
        eta_charge: Charge efficiency
        eta_discharge: Discharge efficiency
        tolerance: Floating-point tolerance

    Returns:
        InvariantCheckResult with all checks
    """
    result = InvariantCheckResult()

    # 1. SOC bounds
    soc_violations = check_soc_bounds(soc_kwh, energy_kwh, tolerance)
    result.soc_min_violations = sum(1 for v in soc_violations if v.invariant == "soc_min")
    result.soc_max_violations = sum(1 for v in soc_violations if v.invariant == "soc_max")
    result.violations.extend(soc_violations)

    # 2. Power limits
    power_violations = check_power_limits(charge_kw, discharge_kw, power_kw, tolerance)
    result.power_charge_violations = sum(1 for v in power_violations if v.invariant == "power_charge")
    result.power_discharge_violations = sum(1 for v in power_violations if v.invariant == "power_discharge")
    result.violations.extend(power_violations)

    # 3. No simultaneous
    simultaneous_violations = check_no_simultaneous(charge_kw, discharge_kw, tolerance)
    result.simultaneous_violations = len(simultaneous_violations)
    result.violations.extend(simultaneous_violations)

    # 4. Energy balance (optional, larger tolerance)
    if len(soc_kwh) == len(charge_kw) + 1:
        balance_violations = check_energy_balance(
            soc_kwh, charge_kw, discharge_kw,
            dt_hours, eta_charge, eta_discharge,
            tolerance=0.1,
        )
        result.energy_balance_violations = len(balance_violations)
        result.violations.extend(balance_violations)

    # Set overall result
    result.all_ok = len([v for v in result.violations if v.severity == "error"]) == 0

    # Check strict mode
    if not result.all_ok and is_strict_mode():
        raise DispatchInvariantViolationError(result)

    return result


def check_battery_trace_invariants(
    trace: "BatteryTraceTimeseries",
    tolerance: float = 1e-6,
) -> InvariantCheckResult:
    """
    Check invariants on a BatteryTraceTimeseries object.

    Args:
        trace: BatteryTraceTimeseries to check
        tolerance: Floating-point tolerance

    Returns:
        InvariantCheckResult
    """
    return check_dispatch_invariants(
        soc_kwh=np.array(trace.soc_kwh),
        charge_kw=np.array(trace.charge_kw),
        discharge_kw=np.array(trace.discharge_kw),
        energy_kwh=trace.battery_energy_kwh,
        power_kw=trace.battery_power_kw,
        dt_hours=trace.step_minutes / 60.0,
        tolerance=tolerance,
    )

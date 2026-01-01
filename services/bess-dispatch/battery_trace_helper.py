"""
Battery Trace Helper (v2.2.0 SSoT).

Generates BatteryTraceTimeseries from dispatch data.
Single source of truth for per-timestep battery state tracking.
"""

from typing import List, Optional
import numpy as np

from models import BatteryTraceTimeseries


def create_battery_trace(
    soc_kwh: np.ndarray,
    charge_kw: np.ndarray,
    discharge_kw: np.ndarray,
    charge_from_pv_kw: np.ndarray,
    charge_from_grid_kw: Optional[np.ndarray],
    discharge_to_load_kw: np.ndarray,
    discharge_to_grid_kw: Optional[np.ndarray],
    step_minutes: int,
    battery_energy_kwh: float,
    battery_power_kw: float,
) -> BatteryTraceTimeseries:
    """
    Create BatteryTraceTimeseries from dispatch arrays.

    Args:
        soc_kwh: SOC at end of each timestep [kWh]. Length = n_steps.
                 Note: dispatch engines typically output n+1 SOC values
                 (including initial SOC). This function expects just the
                 n_steps end-of-step values (soc[1:]).
        charge_kw: Total charge power at each step [kW].
        discharge_kw: Total discharge power at each step [kW].
        charge_from_pv_kw: Charge from PV at each step [kW].
        charge_from_grid_kw: Charge from grid at each step [kW]. None = zeros.
        discharge_to_load_kw: Discharge to load at each step [kW].
        discharge_to_grid_kw: Discharge to grid at each step [kW]. None = zeros.
        step_minutes: Duration of each timestep in minutes.
        battery_energy_kwh: Battery energy capacity [kWh].
        battery_power_kw: Battery power rating [kW].

    Returns:
        BatteryTraceTimeseries with all arrays and metadata.
    """
    n = len(soc_kwh)

    # Handle optional arrays
    if charge_from_grid_kw is None:
        charge_from_grid_kw = np.zeros(n)
    if discharge_to_grid_kw is None:
        discharge_to_grid_kw = np.zeros(n)

    return BatteryTraceTimeseries(
        soc_kwh=soc_kwh.tolist() if isinstance(soc_kwh, np.ndarray) else list(soc_kwh),
        charge_kw=charge_kw.tolist() if isinstance(charge_kw, np.ndarray) else list(charge_kw),
        discharge_kw=discharge_kw.tolist() if isinstance(discharge_kw, np.ndarray) else list(discharge_kw),
        charge_from_pv_kw=charge_from_pv_kw.tolist() if isinstance(charge_from_pv_kw, np.ndarray) else list(charge_from_pv_kw),
        charge_from_grid_kw=charge_from_grid_kw.tolist() if isinstance(charge_from_grid_kw, np.ndarray) else list(charge_from_grid_kw),
        discharge_to_load_kw=discharge_to_load_kw.tolist() if isinstance(discharge_to_load_kw, np.ndarray) else list(discharge_to_load_kw),
        discharge_to_grid_kw=discharge_to_grid_kw.tolist() if isinstance(discharge_to_grid_kw, np.ndarray) else list(discharge_to_grid_kw),
        steps=n,
        step_minutes=step_minutes,
        battery_energy_kwh=battery_energy_kwh,
        battery_power_kw=battery_power_kw,
    )


def create_battery_trace_from_dispatch_result(
    soc_array: np.ndarray,
    charge_array: np.ndarray,
    discharge_array: np.ndarray,
    charge_from_pv_array: np.ndarray,
    charge_from_grid_array: Optional[np.ndarray],
    discharge_to_load_array: np.ndarray,
    discharge_to_grid_array: Optional[np.ndarray],
    interval_minutes: int,
    battery_energy_kwh: float,
    battery_power_kw: float,
) -> BatteryTraceTimeseries:
    """
    Create BatteryTraceTimeseries from typical dispatch engine outputs.

    This handles the common case where SOC has n+1 values (including initial).

    Args:
        soc_array: SOC array [kWh]. Length = n+1 (includes initial SOC at index 0).
                   We return soc[1:] (end-of-step values).
        charge_array: Charge power [kW]. Length = n.
        discharge_array: Discharge power [kW]. Length = n.
        charge_from_pv_array: Charge from PV [kW]. Length = n.
        charge_from_grid_array: Charge from grid [kW]. Length = n. None = zeros.
        discharge_to_load_array: Discharge to load [kW]. Length = n.
        discharge_to_grid_array: Discharge to grid [kW]. Length = n. None = zeros.
        interval_minutes: Timestep duration in minutes.
        battery_energy_kwh: Battery energy capacity [kWh].
        battery_power_kw: Battery power rating [kW].

    Returns:
        BatteryTraceTimeseries.
    """
    n = len(charge_array)

    # SOC array from dispatch has n+1 values - take end-of-step values
    soc_end_of_step = soc_array[1:n+1]

    return create_battery_trace(
        soc_kwh=soc_end_of_step,
        charge_kw=charge_array,
        discharge_kw=discharge_array,
        charge_from_pv_kw=charge_from_pv_array,
        charge_from_grid_kw=charge_from_grid_array,
        discharge_to_load_kw=discharge_to_load_array,
        discharge_to_grid_kw=discharge_to_grid_array,
        step_minutes=interval_minutes,
        battery_energy_kwh=battery_energy_kwh,
        battery_power_kw=battery_power_kw,
    )


def validate_battery_trace(
    trace: BatteryTraceTimeseries,
    tolerance: float = 1e-6,
) -> dict:
    """
    Validate battery trace for correctness.

    Returns dict with validation results for each check:
    - lengths_ok: All arrays have correct length (== steps)
    - soc_bounds_ok: SOC within [0, energy_kwh] with tolerance
    - power_non_negative_ok: All power values >= 0
    - charge_split_ok: charge_from_pv + charge_from_grid == charge (with tolerance)
    - discharge_split_ok: discharge_to_load + discharge_to_grid == discharge (with tolerance)

    Args:
        trace: BatteryTraceTimeseries to validate.
        tolerance: Tolerance for floating-point comparisons.

    Returns:
        Dict with check results and any error messages.
    """
    results = {
        "lengths_ok": True,
        "soc_bounds_ok": True,
        "power_non_negative_ok": True,
        "charge_split_ok": True,
        "discharge_split_ok": True,
        "errors": [],
    }

    n = trace.steps

    # Check lengths
    if not trace.validate_lengths():
        results["lengths_ok"] = False
        results["errors"].append(f"Array length mismatch: expected {n} steps")

    # Check SOC bounds
    if not trace.validate_soc_bounds(tolerance):
        results["soc_bounds_ok"] = False
        min_soc = min(trace.soc_kwh)
        max_soc = max(trace.soc_kwh)
        results["errors"].append(
            f"SOC bounds violation: min={min_soc:.3f}, max={max_soc:.3f}, "
            f"capacity={trace.battery_energy_kwh:.3f}"
        )

    # Check power non-negative
    if not trace.validate_power_non_negative():
        results["power_non_negative_ok"] = False
        results["errors"].append("Negative power values detected")

    # Check charge split
    for i in range(n):
        charge_sum = trace.charge_from_pv_kw[i] + trace.charge_from_grid_kw[i]
        if abs(charge_sum - trace.charge_kw[i]) > tolerance:
            results["charge_split_ok"] = False
            results["errors"].append(
                f"Charge split mismatch at step {i}: "
                f"pv={trace.charge_from_pv_kw[i]:.3f} + grid={trace.charge_from_grid_kw[i]:.3f} "
                f"!= total={trace.charge_kw[i]:.3f}"
            )
            break

    # Check discharge split
    for i in range(n):
        discharge_sum = trace.discharge_to_load_kw[i] + trace.discharge_to_grid_kw[i]
        if abs(discharge_sum - trace.discharge_kw[i]) > tolerance:
            results["discharge_split_ok"] = False
            results["errors"].append(
                f"Discharge split mismatch at step {i}: "
                f"load={trace.discharge_to_load_kw[i]:.3f} + grid={trace.discharge_to_grid_kw[i]:.3f} "
                f"!= total={trace.discharge_kw[i]:.3f}"
            )
            break

    results["all_ok"] = all([
        results["lengths_ok"],
        results["soc_bounds_ok"],
        results["power_non_negative_ok"],
        results["charge_split_ok"],
        results["discharge_split_ok"],
    ])

    return results

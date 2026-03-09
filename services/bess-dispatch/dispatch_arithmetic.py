"""
Arithmetic dispatch modes — simple, fast, no-solver-required.

These modes complement the LP solver by providing:
1. Fast benchmarks for sizing
2. Simple strategies for standard tariffs
3. Fallbacks when LP is infeasible

Modes:
- zeroExport: Charge BESS from PV surplus, never export to grid
- zeroImport: Discharge BESS to cover deficit, minimize grid import
- maxAutoConsumption: Combine zeroExport + zeroImport
- naiveArbitrage: Sort hours by price, charge cheapest N, discharge most expensive N
- fixedHoursArbitrage: Charge in configured hours, discharge in configured hours

All functions return numpy arrays matching the dispatch_engine interface.
"""

from __future__ import annotations

import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class ArithmeticDispatchResult:
    """Result from arithmetic dispatch modes."""
    soc_kwh: np.ndarray           # (n_hours,) State of charge
    charge_kw: np.ndarray         # (n_hours,) Charge power
    discharge_kw: np.ndarray      # (n_hours,) Discharge power
    grid_import_kw: np.ndarray    # (n_hours,) Grid import
    grid_export_kw: np.ndarray    # (n_hours,) Grid export
    total_charge_kwh: float
    total_discharge_kwh: float
    total_grid_import_kwh: float
    total_grid_export_kwh: float
    total_cycles: float
    mode: str


def _apply_battery_constraints(
    wanted_charge: float,
    wanted_discharge: float,
    soc: float,
    power_kw: float,
    energy_kwh: float,
    eta_charge: float,
    eta_discharge: float,
    soc_min: float,
    soc_max: float,
    dt_hours: float = 1.0,
) -> Tuple[float, float]:
    """Apply physical battery constraints. Returns (actual_charge, actual_discharge)."""
    soc_min_kwh = soc_min * energy_kwh
    soc_max_kwh = soc_max * energy_kwh

    # Clamp to max power
    charge = min(wanted_charge, power_kw)
    discharge = min(wanted_discharge, power_kw)

    # Can't charge and discharge simultaneously
    if charge > 0 and discharge > 0:
        if charge > discharge:
            discharge = 0.0
        else:
            charge = 0.0

    # SoC limits
    space = (soc_max_kwh - soc) / eta_charge / dt_hours
    charge = min(charge, max(space, 0.0))

    available = (soc - soc_min_kwh) * eta_discharge / dt_hours
    discharge = min(discharge, max(available, 0.0))

    return charge, discharge


# =============================================================================
# Zero Export
# =============================================================================

def dispatch_zero_export(
    load_kw: np.ndarray,
    pv_kw: np.ndarray,
    power_kw: float,
    energy_kwh: float,
    eta_charge: float = 0.9487,
    eta_discharge: float = 0.9487,
    soc_min: float = 0.10,
    soc_max: float = 0.90,
    soc_initial: float = 0.50,
    dt_hours: float = 1.0,
) -> ArithmeticDispatchResult:
    """
    Zero Export: Charge BESS from PV surplus, never export to grid.

    Priority: PV → Load → BESS charge → Curtailment (no grid export).
    Battery only discharges when load > PV (optional autoconsumption).
    """
    n = len(load_kw)
    soc = np.zeros(n)
    charge = np.zeros(n)
    discharge = np.zeros(n)
    grid_import = np.zeros(n)
    grid_export = np.zeros(n)

    current_soc = soc_initial * energy_kwh

    for h in range(n):
        net = load_kw[h] - pv_kw[h]  # positive = deficit

        if net < 0:
            # PV surplus → charge battery
            surplus = -net
            ch, _ = _apply_battery_constraints(
                surplus, 0.0, current_soc,
                power_kw, energy_kwh, eta_charge, eta_discharge,
                soc_min, soc_max, dt_hours,
            )
            charge[h] = ch
            current_soc += ch * eta_charge * dt_hours
            # Remaining surplus is curtailed (NOT exported)
            grid_export[h] = 0.0
            grid_import[h] = 0.0
        else:
            # Deficit → discharge battery for autoconsumption
            _, dis = _apply_battery_constraints(
                0.0, net, current_soc,
                power_kw, energy_kwh, eta_charge, eta_discharge,
                soc_min, soc_max, dt_hours,
            )
            discharge[h] = dis
            current_soc -= dis / eta_discharge * dt_hours
            grid_import[h] = max(net - dis, 0.0)

        soc[h] = current_soc

    return ArithmeticDispatchResult(
        soc_kwh=soc, charge_kw=charge, discharge_kw=discharge,
        grid_import_kw=grid_import, grid_export_kw=grid_export,
        total_charge_kwh=float(charge.sum() * dt_hours),
        total_discharge_kwh=float(discharge.sum() * dt_hours),
        total_grid_import_kwh=float(grid_import.sum() * dt_hours),
        total_grid_export_kwh=float(grid_export.sum() * dt_hours),
        total_cycles=float(discharge.sum() * dt_hours / energy_kwh),
        mode="zero_export",
    )


# =============================================================================
# Zero Import
# =============================================================================

def dispatch_zero_import(
    load_kw: np.ndarray,
    pv_kw: np.ndarray,
    power_kw: float,
    energy_kwh: float,
    eta_charge: float = 0.9487,
    eta_discharge: float = 0.9487,
    soc_min: float = 0.10,
    soc_max: float = 0.90,
    soc_initial: float = 0.50,
    dt_hours: float = 1.0,
) -> ArithmeticDispatchResult:
    """
    Zero Import: Maximize battery discharge to avoid grid import.

    Priority: PV → Load, BESS discharge → Load, PV surplus → BESS charge → Grid export.
    Minimizes grid_import_kw at every timestep.
    """
    n = len(load_kw)
    soc = np.zeros(n)
    charge = np.zeros(n)
    discharge = np.zeros(n)
    grid_import = np.zeros(n)
    grid_export = np.zeros(n)

    current_soc = soc_initial * energy_kwh

    for h in range(n):
        net = load_kw[h] - pv_kw[h]

        if net < 0:
            # PV surplus → charge
            surplus = -net
            ch, _ = _apply_battery_constraints(
                surplus, 0.0, current_soc,
                power_kw, energy_kwh, eta_charge, eta_discharge,
                soc_min, soc_max, dt_hours,
            )
            charge[h] = ch
            current_soc += ch * eta_charge * dt_hours
            grid_export[h] = max(surplus - ch, 0.0)
        else:
            # Deficit → discharge battery to avoid grid import
            _, dis = _apply_battery_constraints(
                0.0, net, current_soc,
                power_kw, energy_kwh, eta_charge, eta_discharge,
                soc_min, soc_max, dt_hours,
            )
            discharge[h] = dis
            current_soc -= dis / eta_discharge * dt_hours
            grid_import[h] = max(net - dis, 0.0)

        soc[h] = current_soc

    return ArithmeticDispatchResult(
        soc_kwh=soc, charge_kw=charge, discharge_kw=discharge,
        grid_import_kw=grid_import, grid_export_kw=grid_export,
        total_charge_kwh=float(charge.sum() * dt_hours),
        total_discharge_kwh=float(discharge.sum() * dt_hours),
        total_grid_import_kwh=float(grid_import.sum() * dt_hours),
        total_grid_export_kwh=float(grid_export.sum() * dt_hours),
        total_cycles=float(discharge.sum() * dt_hours / energy_kwh),
        mode="zero_import",
    )


# =============================================================================
# Max Auto-Consumption (zeroExport + zeroImport combined)
# =============================================================================

def dispatch_max_autoconsumption(
    load_kw: np.ndarray,
    pv_kw: np.ndarray,
    power_kw: float,
    energy_kwh: float,
    eta_charge: float = 0.9487,
    eta_discharge: float = 0.9487,
    soc_min: float = 0.10,
    soc_max: float = 0.90,
    soc_initial: float = 0.50,
    dt_hours: float = 1.0,
) -> ArithmeticDispatchResult:
    """
    Max Auto-Consumption: Minimize both grid import AND grid export.

    Combines zeroExport + zeroImport strategies:
    - PV surplus → charge battery (not export)
    - Load deficit → discharge battery (not import)
    - Grid is last resort in both directions.
    """
    # This is functionally identical to zeroImport with zero export
    n = len(load_kw)
    soc = np.zeros(n)
    charge = np.zeros(n)
    discharge = np.zeros(n)
    grid_import = np.zeros(n)
    grid_export = np.zeros(n)

    current_soc = soc_initial * energy_kwh

    for h in range(n):
        net = load_kw[h] - pv_kw[h]

        if net < 0:
            # PV surplus → charge (minimize export)
            surplus = -net
            ch, _ = _apply_battery_constraints(
                surplus, 0.0, current_soc,
                power_kw, energy_kwh, eta_charge, eta_discharge,
                soc_min, soc_max, dt_hours,
            )
            charge[h] = ch
            current_soc += ch * eta_charge * dt_hours
            # Only export what battery can't absorb
            grid_export[h] = max(surplus - ch, 0.0)
        else:
            # Deficit → discharge (minimize import)
            _, dis = _apply_battery_constraints(
                0.0, net, current_soc,
                power_kw, energy_kwh, eta_charge, eta_discharge,
                soc_min, soc_max, dt_hours,
            )
            discharge[h] = dis
            current_soc -= dis / eta_discharge * dt_hours
            grid_import[h] = max(net - dis, 0.0)

        soc[h] = current_soc

    return ArithmeticDispatchResult(
        soc_kwh=soc, charge_kw=charge, discharge_kw=discharge,
        grid_import_kw=grid_import, grid_export_kw=grid_export,
        total_charge_kwh=float(charge.sum() * dt_hours),
        total_discharge_kwh=float(discharge.sum() * dt_hours),
        total_grid_import_kwh=float(grid_import.sum() * dt_hours),
        total_grid_export_kwh=float(grid_export.sum() * dt_hours),
        total_cycles=float(discharge.sum() * dt_hours / energy_kwh),
        mode="max_autoconsumption",
    )


# =============================================================================
# Naive Arbitrage (sort by price)
# =============================================================================

def dispatch_naive_arbitrage(
    load_kw: np.ndarray,
    pv_kw: np.ndarray,
    prices_pln_mwh: np.ndarray,
    power_kw: float,
    energy_kwh: float,
    eta_charge: float = 0.9487,
    eta_discharge: float = 0.9487,
    soc_min: float = 0.10,
    soc_max: float = 0.90,
    soc_initial: float = 0.50,
    dt_hours: float = 1.0,
    charge_percentile: float = 25.0,
    discharge_percentile: float = 75.0,
) -> ArithmeticDispatchResult:
    """
    Naive Arbitrage: Charge when price < P25, discharge when price > P75.

    Simple threshold-based strategy without look-ahead.
    Good as upper-bound benchmark for LP solver.
    """
    n = len(load_kw)
    soc = np.zeros(n)
    charge = np.zeros(n)
    discharge = np.zeros(n)
    grid_import = np.zeros(n)
    grid_export = np.zeros(n)

    buy_thresh = np.percentile(prices_pln_mwh, charge_percentile)
    sell_thresh = np.percentile(prices_pln_mwh, discharge_percentile)

    current_soc = soc_initial * energy_kwh

    for h in range(n):
        net = load_kw[h] - pv_kw[h]
        price = prices_pln_mwh[h]

        wanted_charge = 0.0
        wanted_discharge = 0.0

        # PV surplus always charges
        if net < 0:
            wanted_charge = -net

        # Price-based decisions
        if price < buy_thresh:
            wanted_charge = max(wanted_charge, power_kw)
        elif price > sell_thresh and net > 0:
            wanted_discharge = min(net, power_kw)

        ch, dis = _apply_battery_constraints(
            wanted_charge, wanted_discharge, current_soc,
            power_kw, energy_kwh, eta_charge, eta_discharge,
            soc_min, soc_max, dt_hours,
        )

        charge[h] = ch
        discharge[h] = dis
        current_soc += (ch * eta_charge - dis / eta_discharge) * dt_hours

        # Grid balance
        actual_net = net + ch - dis
        grid_import[h] = max(actual_net, 0.0)
        grid_export[h] = max(-actual_net, 0.0)
        soc[h] = current_soc

    return ArithmeticDispatchResult(
        soc_kwh=soc, charge_kw=charge, discharge_kw=discharge,
        grid_import_kw=grid_import, grid_export_kw=grid_export,
        total_charge_kwh=float(charge.sum() * dt_hours),
        total_discharge_kwh=float(discharge.sum() * dt_hours),
        total_grid_import_kwh=float(grid_import.sum() * dt_hours),
        total_grid_export_kwh=float(grid_export.sum() * dt_hours),
        total_cycles=float(discharge.sum() * dt_hours / energy_kwh),
        mode="naive_arbitrage",
    )


# =============================================================================
# Fixed Hours Arbitrage
# =============================================================================

def dispatch_fixed_hours_arbitrage(
    load_kw: np.ndarray,
    pv_kw: np.ndarray,
    power_kw: float,
    energy_kwh: float,
    charge_hours: List[int] = None,
    discharge_hours: List[int] = None,
    eta_charge: float = 0.9487,
    eta_discharge: float = 0.9487,
    soc_min: float = 0.10,
    soc_max: float = 0.90,
    soc_initial: float = 0.50,
    dt_hours: float = 1.0,
) -> ArithmeticDispatchResult:
    """
    Fixed Hours Arbitrage: Charge in specified hours, discharge in specified hours.

    Default: charge 0-6 (night), discharge 14-20 (peak).
    Ideal for simple ToU tariffs (G12, C12a).
    """
    if charge_hours is None:
        charge_hours = list(range(0, 7))    # 00:00 - 06:00
    if discharge_hours is None:
        discharge_hours = list(range(14, 21))  # 14:00 - 20:00

    charge_set = set(charge_hours)
    discharge_set = set(discharge_hours)

    n = len(load_kw)
    soc = np.zeros(n)
    charge = np.zeros(n)
    discharge = np.zeros(n)
    grid_import = np.zeros(n)
    grid_export = np.zeros(n)

    current_soc = soc_initial * energy_kwh

    for h in range(n):
        hod = h % 24  # hour of day
        net = load_kw[h] - pv_kw[h]

        wanted_charge = 0.0
        wanted_discharge = 0.0

        # PV surplus always charges
        if net < 0:
            wanted_charge = -net

        # Scheduled charge/discharge
        if hod in charge_set:
            wanted_charge = max(wanted_charge, power_kw)
        if hod in discharge_set and net > 0:
            wanted_discharge = min(net, power_kw)

        ch, dis = _apply_battery_constraints(
            wanted_charge, wanted_discharge, current_soc,
            power_kw, energy_kwh, eta_charge, eta_discharge,
            soc_min, soc_max, dt_hours,
        )

        charge[h] = ch
        discharge[h] = dis
        current_soc += (ch * eta_charge - dis / eta_discharge) * dt_hours

        actual_net = net + ch - dis
        grid_import[h] = max(actual_net, 0.0)
        grid_export[h] = max(-actual_net, 0.0)
        soc[h] = current_soc

    return ArithmeticDispatchResult(
        soc_kwh=soc, charge_kw=charge, discharge_kw=discharge,
        grid_import_kw=grid_import, grid_export_kw=grid_export,
        total_charge_kwh=float(charge.sum() * dt_hours),
        total_discharge_kwh=float(discharge.sum() * dt_hours),
        total_grid_import_kwh=float(grid_import.sum() * dt_hours),
        total_grid_export_kwh=float(grid_export.sum() * dt_hours),
        total_cycles=float(discharge.sum() * dt_hours / energy_kwh),
        mode="fixed_hours_arbitrage",
    )


# =============================================================================
# Battery Warranty Guard
# =============================================================================

@dataclass
class WarrantyConstraints:
    """Battery manufacturer warranty constraints."""
    max_cycles_per_year: float = 365.0      # Max full equivalent cycles/year
    max_dod_pct: float = 80.0               # Max depth of discharge %
    min_soc_pct: float = 10.0               # Minimum SoC %
    max_c_rate: float = 1.0                 # Max C-rate (power/capacity)
    max_temperature_c: float = 45.0         # Max operating temperature


def apply_warranty_guard(
    result: ArithmeticDispatchResult,
    energy_kwh: float,
    constraints: WarrantyConstraints,
    dt_hours: float = 1.0,
) -> Dict[str, any]:
    """
    Check dispatch result against warranty constraints.

    Returns violation report.
    """
    violations = []
    warnings = []

    # Cycle count
    annual_cycles = result.total_cycles
    if annual_cycles > constraints.max_cycles_per_year:
        violations.append({
            "constraint": "max_cycles_per_year",
            "limit": constraints.max_cycles_per_year,
            "actual": annual_cycles,
            "severity": "VIOLATION",
        })
    elif annual_cycles > constraints.max_cycles_per_year * 0.9:
        warnings.append({
            "constraint": "max_cycles_per_year",
            "limit": constraints.max_cycles_per_year,
            "actual": annual_cycles,
            "severity": "WARNING",
        })

    # DoD check
    soc_min_actual = result.soc_kwh.min() / energy_kwh * 100
    actual_dod = 100 - soc_min_actual
    if actual_dod > constraints.max_dod_pct:
        violations.append({
            "constraint": "max_dod_pct",
            "limit": constraints.max_dod_pct,
            "actual": actual_dod,
            "severity": "VIOLATION",
        })

    # C-rate check
    max_charge_rate = result.charge_kw.max() / energy_kwh if energy_kwh > 0 else 0
    max_discharge_rate = result.discharge_kw.max() / energy_kwh if energy_kwh > 0 else 0
    max_c = max(max_charge_rate, max_discharge_rate)
    if max_c > constraints.max_c_rate:
        violations.append({
            "constraint": "max_c_rate",
            "limit": constraints.max_c_rate,
            "actual": max_c,
            "severity": "VIOLATION",
        })

    return {
        "warranty_compliant": len(violations) == 0,
        "violations": violations,
        "warnings": warnings,
        "annual_cycles": annual_cycles,
        "max_dod_pct": actual_dod,
        "max_c_rate": max_c,
    }

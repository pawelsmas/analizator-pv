"""
BESS Dispatch Engine
====================
Core dispatch algorithms for BESS simulation.

Implements:
1. PV-Surplus dispatch (autokonsumpcja) - greedy time-based
2. Peak Shaving dispatch - priority discharge on peaks
3. STACKED dispatch (PV + Peak) - dual-service with SOC reserve

All algorithms:
- Support 15-min and 60-min intervals
- Track per-timestep energy flows
- Calculate degradation metrics
- Handle SOC constraints properly
"""

import numpy as np
from typing import Tuple, List, Optional, Dict, Any
from dataclasses import dataclass

from models import (
    BatteryParams,
    DispatchRequest,
    DispatchResult,
    DispatchMode,
    DegradationMetrics,
    DegradationStatus,
    HourlyDispatch,
    StackedModeParams,
    DegradationBudget,
    PriceConfig,
    ProfileUnit,
    ResamplingMethod,
    AuditMetadata,
    TopologyType,
    ENGINE_VERSION,
)


@dataclass
class DispatchState:
    """Internal state for dispatch simulation"""
    soc_kwh: float  # Current SOC in kWh
    timestep: int


def dispatch_pv_surplus(
    pv_kw: np.ndarray,
    load_kw: np.ndarray,
    battery: BatteryParams,
    dt_hours: float,
    prices: Optional[PriceConfig] = None,
    return_hourly: bool = True,
    audit_metadata: Optional[AuditMetadata] = None,
) -> DispatchResult:
    """
    PV-Surplus (Autokonsumpcja) Dispatch Algorithm
    ===============================================

    Greedy algorithm that:
    1. First uses PV directly for load (direct consumption)
    2. Charges battery from PV surplus (up to power/SOC limits)
    3. Discharges battery for load deficit (up to power/SOC limits)
    4. Curtails excess PV if battery full
    5. Imports from grid if deficit > battery discharge

    Model 0-Export: No export to grid (curtailment instead)

    Parameters:
    -----------
    pv_kw : np.ndarray
        PV generation power [kW] per timestep
    load_kw : np.ndarray
        Load consumption power [kW] per timestep
    battery : BatteryParams
        Battery parameters
    dt_hours : float
        Timestep duration in hours
    prices : PriceConfig
        Energy prices for economic calculation
    return_hourly : bool
        Include hourly arrays in result

    Returns:
    --------
    DispatchResult with all energy flows and metrics
    """
    n = len(pv_kw)
    prices = prices or PriceConfig()

    # Initialize arrays
    direct_pv = np.zeros(n)
    charge = np.zeros(n)
    discharge = np.zeros(n)
    grid_import = np.zeros(n)
    grid_export = np.zeros(n)
    curtailment = np.zeros(n)
    soc = np.zeros(n + 1)

    # Initial SOC
    soc[0] = battery.energy_kwh * battery.soc_initial

    # SOC limits in kWh
    soc_min_kwh = battery.energy_kwh * battery.soc_min
    soc_max_kwh = battery.energy_kwh * battery.soc_max

    # Power limits
    p_max = battery.power_kw
    eta_ch = battery.eta_charge
    eta_dis = battery.eta_discharge

    # Dispatch loop
    for t in range(n):
        pv_t = pv_kw[t]
        load_t = load_kw[t]

        # Step 1: Direct PV consumption
        direct = min(pv_t, load_t)
        direct_pv[t] = direct

        surplus = pv_t - direct
        deficit = load_t - direct

        current_soc = soc[t]

        # Step 2: Handle surplus (charge battery or curtail)
        if surplus > 0:
            # How much can we charge?
            charge_power_limit = min(surplus, p_max)
            space_available = soc_max_kwh - current_soc
            # Energy stored = power * eta * dt
            max_charge_energy = charge_power_limit * eta_ch * dt_hours

            if max_charge_energy > space_available:
                # Limit by SOC space
                actual_charge_energy = space_available
                charge_power = actual_charge_energy / (eta_ch * dt_hours)
            else:
                charge_power = charge_power_limit
                actual_charge_energy = max_charge_energy

            charge[t] = charge_power
            current_soc += actual_charge_energy

            # Curtail the rest
            curtailment[t] = surplus - charge_power

        # Step 3: Handle deficit (discharge battery or import)
        if deficit > 0:
            # How much can we discharge?
            discharge_power_limit = min(deficit, p_max)
            energy_available = current_soc - soc_min_kwh
            # Energy from SOC = power / eta * dt
            max_discharge_from_soc = discharge_power_limit / eta_dis * dt_hours

            if max_discharge_from_soc > energy_available:
                # Limit by available energy
                actual_discharge_from_soc = energy_available
                discharge_power = actual_discharge_from_soc * eta_dis / dt_hours
            else:
                discharge_power = discharge_power_limit
                actual_discharge_from_soc = max_discharge_from_soc

            discharge[t] = discharge_power
            current_soc -= actual_discharge_from_soc

            # Import the rest
            grid_import[t] = deficit - discharge_power

        # Update SOC for next timestep
        soc[t + 1] = current_soc

    # Calculate totals (convert power*dt to energy)
    total_pv = float(np.sum(pv_kw) * dt_hours)
    total_load = float(np.sum(load_kw) * dt_hours)
    total_direct = float(np.sum(direct_pv) * dt_hours)
    total_charge = float(np.sum(charge) * dt_hours)
    total_discharge = float(np.sum(discharge) * dt_hours)
    total_import = float(np.sum(grid_import) * dt_hours)
    total_export = float(np.sum(grid_export) * dt_hours)  # 0 in 0-export mode
    total_curtail = float(np.sum(curtailment) * dt_hours)

    # Self-consumption
    self_consumption = total_direct + total_discharge
    self_consumption_pct = (self_consumption / total_pv * 100) if total_pv > 0 else 0
    grid_independence = ((total_load - total_import) / total_load * 100) if total_load > 0 else 0

    # Degradation metrics
    degradation = calculate_degradation_metrics(
        total_charge, total_discharge, battery, n * dt_hours
    )

    # Economic calculation
    import_price = prices.import_price_pln_mwh / 1000  # PLN/kWh
    export_price = prices.export_price_pln_mwh / 1000  # PLN/kWh

    # Baseline: no battery
    baseline_import = np.maximum(load_kw - pv_kw, 0)
    baseline_export = np.maximum(pv_kw - load_kw, 0)
    baseline_import_kwh = float(np.sum(baseline_import) * dt_hours)
    baseline_export_kwh = float(np.sum(baseline_export) * dt_hours)
    baseline_cost = baseline_import_kwh * import_price - baseline_export_kwh * export_price

    # Project cost
    project_cost = total_import * import_price - total_export * export_price
    annual_savings = baseline_cost - project_cost

    # Build audit info
    audit = audit_metadata or AuditMetadata(
        engine_version=ENGINE_VERSION,
        interval_minutes=int(dt_hours * 60),
    )
    info_dict = {
        "audit": audit.dict(),
    }

    # Build result
    result = DispatchResult(
        mode=DispatchMode.PV_SURPLUS,
        battery_power_kw=battery.power_kw,
        battery_energy_kwh=battery.energy_kwh,
        interval_minutes=int(dt_hours * 60),
        n_timesteps=n,
        total_pv_kwh=total_pv,
        total_load_kwh=total_load,
        total_direct_pv_kwh=total_direct,
        total_charge_kwh=total_charge,
        total_discharge_kwh=total_discharge,
        total_grid_import_kwh=total_import,
        total_grid_export_kwh=total_export,
        total_curtailment_kwh=total_curtail,
        self_consumption_kwh=self_consumption,
        self_consumption_pct=self_consumption_pct,
        grid_independence_pct=grid_independence,
        degradation=degradation,
        baseline_cost_pln=baseline_cost,
        project_cost_pln=project_cost,
        annual_savings_pln=annual_savings,
        warnings=[],
        info=info_dict,
    )

    if return_hourly:
        result.hourly_charge_kw = charge.tolist()
        result.hourly_discharge_kw = discharge.tolist()
        result.hourly_soc_pct = (soc[:-1] / battery.energy_kwh * 100).tolist()
        result.hourly_grid_import_kw = grid_import.tolist()
        result.hourly_grid_export_kw = grid_export.tolist()

    return result


def dispatch_peak_shaving(
    pv_kw: np.ndarray,
    load_kw: np.ndarray,
    battery: BatteryParams,
    dt_hours: float,
    peak_limit_kw: float,
    prices: Optional[PriceConfig] = None,
    return_hourly: bool = True,
    audit_metadata: Optional[AuditMetadata] = None,
) -> DispatchResult:
    """
    Peak Shaving Dispatch Algorithm
    ================================

    Discharges battery when net load (load - PV) exceeds peak limit.
    Charges from grid when net load is below limit (and SOC below max).

    Parameters:
    -----------
    peak_limit_kw : float
        Maximum grid import power [kW]

    Returns:
    --------
    DispatchResult with peak reduction metrics
    """
    n = len(pv_kw)
    prices = prices or PriceConfig()

    # Net load (grid perspective without battery)
    net_load = load_kw - pv_kw

    # Initialize arrays
    direct_pv = np.zeros(n)
    charge = np.zeros(n)
    discharge = np.zeros(n)
    grid_import = np.zeros(n)
    grid_export = np.zeros(n)
    curtailment = np.zeros(n)
    soc = np.zeros(n + 1)

    soc[0] = battery.energy_kwh * battery.soc_initial
    soc_min_kwh = battery.energy_kwh * battery.soc_min
    soc_max_kwh = battery.energy_kwh * battery.soc_max
    p_max = battery.power_kw
    eta_ch = battery.eta_charge
    eta_dis = battery.eta_discharge

    original_peak = 0.0
    new_peak = 0.0

    for t in range(n):
        pv_t = pv_kw[t]
        load_t = load_kw[t]
        net_t = net_load[t]

        # Direct PV consumption
        direct = min(pv_t, load_t)
        direct_pv[t] = direct

        current_soc = soc[t]

        # Track original peak
        if net_t > 0:
            original_peak = max(original_peak, net_t)

        if net_t > peak_limit_kw:
            # Need to discharge to shave peak
            required_discharge = net_t - peak_limit_kw
            discharge_power_limit = min(required_discharge, p_max)
            energy_available = current_soc - soc_min_kwh
            max_discharge_from_soc = discharge_power_limit / eta_dis * dt_hours

            if max_discharge_from_soc > energy_available:
                actual_discharge_from_soc = energy_available
                discharge_power = actual_discharge_from_soc * eta_dis / dt_hours
            else:
                discharge_power = discharge_power_limit
                actual_discharge_from_soc = max_discharge_from_soc

            discharge[t] = discharge_power
            current_soc -= actual_discharge_from_soc

            # Actual grid import after battery
            actual_net = net_t - discharge_power
            grid_import[t] = max(0, actual_net)
            new_peak = max(new_peak, grid_import[t])

        elif net_t > 0:
            # Below limit, import from grid
            grid_import[t] = net_t
            new_peak = max(new_peak, net_t)

            # Optionally charge if capacity available
            headroom = peak_limit_kw - net_t
            if headroom > 0 and current_soc < soc_max_kwh:
                charge_power = min(headroom, p_max)
                space_available = soc_max_kwh - current_soc
                max_charge_energy = charge_power * eta_ch * dt_hours

                if max_charge_energy > space_available:
                    actual_charge_energy = space_available
                    charge_power = actual_charge_energy / (eta_ch * dt_hours)
                else:
                    actual_charge_energy = max_charge_energy

                charge[t] = charge_power
                current_soc += actual_charge_energy
                grid_import[t] += charge_power

        else:
            # PV surplus - curtail or export
            surplus = -net_t
            curtailment[t] = surplus  # 0-export mode

        soc[t + 1] = current_soc

    # Calculate totals
    total_pv = float(np.sum(pv_kw) * dt_hours)
    total_load = float(np.sum(load_kw) * dt_hours)
    total_direct = float(np.sum(direct_pv) * dt_hours)
    total_charge = float(np.sum(charge) * dt_hours)
    total_discharge = float(np.sum(discharge) * dt_hours)
    total_import = float(np.sum(grid_import) * dt_hours)
    total_export = float(np.sum(grid_export) * dt_hours)
    total_curtail = float(np.sum(curtailment) * dt_hours)

    self_consumption = total_direct + total_discharge
    self_consumption_pct = (self_consumption / total_pv * 100) if total_pv > 0 else 0
    grid_independence = ((total_load - total_import) / total_load * 100) if total_load > 0 else 0

    peak_reduction = original_peak - new_peak
    peak_reduction_pct = (peak_reduction / original_peak * 100) if original_peak > 0 else 0

    degradation = calculate_degradation_metrics(
        total_charge, total_discharge, battery, n * dt_hours
    )

    # Economics
    import_price = prices.import_price_pln_mwh / 1000
    baseline_import_kwh = float(np.sum(np.maximum(net_load, 0)) * dt_hours)
    baseline_cost = baseline_import_kwh * import_price
    project_cost = total_import * import_price
    annual_savings = baseline_cost - project_cost

    # Build audit info
    audit = audit_metadata or AuditMetadata(
        engine_version=ENGINE_VERSION,
        interval_minutes=int(dt_hours * 60),
    )
    info_dict = {
        "audit": audit.dict(),
        "peak_limit_kw": peak_limit_kw,
    }

    result = DispatchResult(
        mode=DispatchMode.PEAK_SHAVING,
        battery_power_kw=battery.power_kw,
        battery_energy_kwh=battery.energy_kwh,
        interval_minutes=int(dt_hours * 60),
        n_timesteps=n,
        total_pv_kwh=total_pv,
        total_load_kwh=total_load,
        total_direct_pv_kwh=total_direct,
        total_charge_kwh=total_charge,
        total_discharge_kwh=total_discharge,
        total_grid_import_kwh=total_import,
        total_grid_export_kwh=total_export,
        total_curtailment_kwh=total_curtail,
        self_consumption_kwh=self_consumption,
        self_consumption_pct=self_consumption_pct,
        grid_independence_pct=grid_independence,
        original_peak_kw=original_peak,
        new_peak_kw=new_peak,
        peak_reduction_kw=peak_reduction,
        peak_reduction_pct=peak_reduction_pct,
        degradation=degradation,
        baseline_cost_pln=baseline_cost,
        project_cost_pln=project_cost,
        annual_savings_pln=annual_savings,
        warnings=[],
        info=info_dict,
    )

    if return_hourly:
        result.hourly_charge_kw = charge.tolist()
        result.hourly_discharge_kw = discharge.tolist()
        result.hourly_soc_pct = (soc[:-1] / battery.energy_kwh * 100).tolist()
        result.hourly_grid_import_kw = grid_import.tolist()
        result.hourly_grid_export_kw = grid_export.tolist()

    return result


def dispatch_stacked(
    pv_kw: np.ndarray,
    load_kw: np.ndarray,
    battery: BatteryParams,
    dt_hours: float,
    stacked_params: StackedModeParams,
    prices: Optional[PriceConfig] = None,
    return_hourly: bool = True,
    audit_metadata: Optional[AuditMetadata] = None,
) -> DispatchResult:
    """
    STACKED Dispatch Algorithm (PV Shifting + Peak Shaving)
    =======================================================

    One battery provides two services with priority:
    1. Peak Shaving (priority 1): Protect against grid peaks
    2. PV Shifting (priority 2): Maximize self-consumption

    SOC Reserve mechanism:
    - A portion of SOC is reserved for peak shaving
    - PV shifting can only use SOC above reserve level
    - Peak shaving can use full SOC (including reserve)

    Parameters:
    -----------
    stacked_params : StackedModeParams
        - peak_limit_kw: Grid import limit [kW]
        - reserve_fraction: SOC fraction reserved for peak shaving (e.g., 0.3)
        - allow_reserve_breach: Allow PV shifting to use reserve in emergency

    Algorithm:
    ----------
    For each timestep:
    1. Calculate net load (load - PV)
    2. If net > peak_limit: discharge for peak shaving (use full SOC)
    3. If net <= peak_limit and PV surplus: charge from PV (up to soc_max)
    4. If net <= peak_limit and deficit: discharge for PV shifting (only above reserve)
    5. Track throughput separately for each service

    Returns:
    --------
    DispatchResult with per-service degradation breakdown
    """
    n = len(pv_kw)
    prices = prices or PriceConfig()
    peak_limit = stacked_params.peak_limit_kw
    reserve_frac = stacked_params.reserve_fraction

    # Net load
    net_load = load_kw - pv_kw

    # Initialize arrays
    direct_pv = np.zeros(n)
    charge = np.zeros(n)
    charge_from_pv = np.zeros(n)   # Track charge source: PV
    charge_from_grid = np.zeros(n) # Track charge source: grid
    discharge = np.zeros(n)
    discharge_peak = np.zeros(n)  # For peak shaving service
    discharge_pv = np.zeros(n)    # For PV shifting service
    grid_import = np.zeros(n)
    grid_export = np.zeros(n)
    curtailment = np.zeros(n)
    soc = np.zeros(n + 1)

    soc[0] = battery.energy_kwh * battery.soc_initial
    soc_min_kwh = battery.energy_kwh * battery.soc_min
    soc_max_kwh = battery.energy_kwh * battery.soc_max
    # Reserve SOC for peak shaving
    reserve_soc_kwh = battery.energy_kwh * reserve_frac
    # Effective min SOC for PV shifting (above reserve)
    pv_soc_min_kwh = max(soc_min_kwh, reserve_soc_kwh)

    p_max = battery.power_kw
    eta_ch = battery.eta_charge
    eta_dis = battery.eta_discharge

    original_peak = 0.0
    new_peak = 0.0
    warnings = []

    for t in range(n):
        pv_t = pv_kw[t]
        load_t = load_kw[t]
        net_t = net_load[t]

        # Direct PV consumption
        direct = min(pv_t, load_t)
        direct_pv[t] = direct

        surplus = max(0, pv_t - load_t)
        deficit = max(0, load_t - pv_t)

        current_soc = soc[t]

        # Track original peak (net import without battery)
        if net_t > 0:
            original_peak = max(original_peak, net_t)

        # ===== PRIORITY 1: Peak Shaving =====
        if net_t > peak_limit:
            # Discharge to shave peak - can use full SOC including reserve
            required_discharge = net_t - peak_limit
            discharge_power_limit = min(required_discharge, p_max)
            energy_available = current_soc - soc_min_kwh  # Full SOC available
            max_discharge_from_soc = discharge_power_limit / eta_dis * dt_hours

            if max_discharge_from_soc > energy_available:
                actual_discharge_from_soc = energy_available
                discharge_power = actual_discharge_from_soc * eta_dis / dt_hours
            else:
                discharge_power = discharge_power_limit
                actual_discharge_from_soc = max_discharge_from_soc

            discharge[t] = discharge_power
            discharge_peak[t] = discharge_power  # Track as peak service
            current_soc -= actual_discharge_from_soc

            # Actual grid import after peak shaving
            actual_net = net_t - discharge_power
            grid_import[t] = max(0, actual_net)
            new_peak = max(new_peak, grid_import[t])

        # ===== PRIORITY 2: PV Shifting =====
        elif surplus > 0:
            # Charge from PV surplus
            charge_power_limit = min(surplus, p_max)
            space_available = soc_max_kwh - current_soc
            max_charge_energy = charge_power_limit * eta_ch * dt_hours

            if max_charge_energy > space_available:
                actual_charge_energy = space_available
                charge_power = actual_charge_energy / (eta_ch * dt_hours)
            else:
                charge_power = charge_power_limit
                actual_charge_energy = max_charge_energy

            charge[t] = charge_power
            charge_from_pv[t] = charge_power  # All charge from PV surplus
            current_soc += actual_charge_energy

            # Curtail excess
            curtailment[t] = surplus - charge_power

        elif deficit > 0:
            # Discharge for PV shifting - only use SOC above reserve
            energy_available_pv = max(0, current_soc - pv_soc_min_kwh)

            if energy_available_pv > 0:
                discharge_power_limit = min(deficit, p_max)
                max_discharge_from_soc = discharge_power_limit / eta_dis * dt_hours

                if max_discharge_from_soc > energy_available_pv:
                    actual_discharge_from_soc = energy_available_pv
                    discharge_power = actual_discharge_from_soc * eta_dis / dt_hours
                else:
                    discharge_power = discharge_power_limit
                    actual_discharge_from_soc = max_discharge_from_soc

                discharge[t] = discharge_power
                discharge_pv[t] = discharge_power  # Track as PV service
                current_soc -= actual_discharge_from_soc

                # Remaining deficit from grid
                grid_import[t] = deficit - discharge_power
            else:
                # No energy above reserve - import from grid
                grid_import[t] = deficit

            new_peak = max(new_peak, grid_import[t])

        soc[t + 1] = current_soc

    # Calculate totals
    total_pv = float(np.sum(pv_kw) * dt_hours)
    total_load = float(np.sum(load_kw) * dt_hours)
    total_direct = float(np.sum(direct_pv) * dt_hours)
    total_charge = float(np.sum(charge) * dt_hours)
    total_charge_pv = float(np.sum(charge_from_pv) * dt_hours)
    total_charge_grid = float(np.sum(charge_from_grid) * dt_hours)
    total_discharge = float(np.sum(discharge) * dt_hours)
    total_discharge_peak = float(np.sum(discharge_peak) * dt_hours)
    total_discharge_pv = float(np.sum(discharge_pv) * dt_hours)
    total_import = float(np.sum(grid_import) * dt_hours)
    total_export = float(np.sum(grid_export) * dt_hours)
    total_curtail = float(np.sum(curtailment) * dt_hours)

    # Peak shaving event statistics
    peak_events_count = int(np.sum(discharge_peak > 0))
    peak_max_discharge = float(np.max(discharge_peak)) if peak_events_count > 0 else 0.0

    self_consumption = total_direct + total_discharge
    self_consumption_pct = (self_consumption / total_pv * 100) if total_pv > 0 else 0
    grid_independence = ((total_load - total_import) / total_load * 100) if total_load > 0 else 0

    peak_reduction = original_peak - new_peak
    peak_reduction_pct = (peak_reduction / original_peak * 100) if original_peak > 0 else 0

    # Degradation with per-service breakdown (now with extra metrics)
    degradation = calculate_degradation_metrics_stacked(
        total_charge=total_charge,
        total_discharge=total_discharge,
        discharge_peak=total_discharge_peak,
        discharge_pv=total_discharge_pv,
        battery=battery,
        total_hours=n * dt_hours,
        peak_events_count=peak_events_count,
        peak_max_discharge_kw=peak_max_discharge,
        charge_from_pv_kwh=total_charge_pv,
        charge_from_grid_kwh=total_charge_grid,
    )

    # Economics
    import_price = prices.import_price_pln_mwh / 1000
    baseline_import_kwh = float(np.sum(np.maximum(net_load, 0)) * dt_hours)
    baseline_cost = baseline_import_kwh * import_price
    project_cost = total_import * import_price
    annual_savings = baseline_cost - project_cost

    # Build audit info
    audit = audit_metadata or AuditMetadata(
        engine_version=ENGINE_VERSION,
        interval_minutes=int(dt_hours * 60),
    )
    info_dict = {
        "audit": audit.dict(),
        "reserve_soc_kwh": reserve_soc_kwh,
        "reserve_fraction": reserve_frac,
        "peak_limit_kw": peak_limit,
        "discharge_peak_kwh": total_discharge_peak,
        "discharge_pv_kwh": total_discharge_pv,
    }

    result = DispatchResult(
        mode=DispatchMode.STACKED,
        battery_power_kw=battery.power_kw,
        battery_energy_kwh=battery.energy_kwh,
        interval_minutes=int(dt_hours * 60),
        n_timesteps=n,
        total_pv_kwh=total_pv,
        total_load_kwh=total_load,
        total_direct_pv_kwh=total_direct,
        total_charge_kwh=total_charge,
        total_discharge_kwh=total_discharge,
        total_grid_import_kwh=total_import,
        total_grid_export_kwh=total_export,
        total_curtailment_kwh=total_curtail,
        self_consumption_kwh=self_consumption,
        self_consumption_pct=self_consumption_pct,
        grid_independence_pct=grid_independence,
        original_peak_kw=original_peak,
        new_peak_kw=new_peak,
        peak_reduction_kw=peak_reduction,
        peak_reduction_pct=peak_reduction_pct,
        degradation=degradation,
        baseline_cost_pln=baseline_cost,
        project_cost_pln=project_cost,
        annual_savings_pln=annual_savings,
        warnings=warnings,
        info=info_dict,
    )

    if return_hourly:
        result.hourly_charge_kw = charge.tolist()
        result.hourly_discharge_kw = discharge.tolist()
        result.hourly_soc_pct = (soc[:-1] / battery.energy_kwh * 100).tolist()
        result.hourly_grid_import_kw = grid_import.tolist()
        result.hourly_grid_export_kw = grid_export.tolist()

    return result


def calculate_degradation_metrics(
    total_charge_kwh: float,
    total_discharge_kwh: float,
    battery: BatteryParams,
    total_hours: float,
) -> DegradationMetrics:
    """
    Calculate degradation metrics for single-service dispatch.

    Metrics:
    - Throughput: total energy charged + discharged [MWh]
    - EFC: Equivalent Full Cycles = discharge / usable_capacity
    """
    throughput_total = (total_charge_kwh + total_discharge_kwh) / 1000  # MWh

    usable_capacity = battery.usable_capacity_kwh
    efc = total_discharge_kwh / usable_capacity if usable_capacity > 0 else 0

    return DegradationMetrics(
        throughput_charge_kwh=total_charge_kwh,
        throughput_discharge_kwh=total_discharge_kwh,
        throughput_total_mwh=throughput_total,
        efc_total=efc,
        throughput_pv_mwh=throughput_total,  # All is PV in single-service
        throughput_peak_mwh=0.0,
        efc_pv=efc,
        efc_peak=0.0,
        budget_status=DegradationStatus.OK,
        budget_utilization_pct=0.0,
        budget_warnings=[],
    )


def calculate_degradation_metrics_stacked(
    total_charge: float,
    total_discharge: float,
    discharge_peak: float,
    discharge_pv: float,
    battery: BatteryParams,
    total_hours: float,
    peak_events_count: int = 0,
    peak_max_discharge_kw: float = 0.0,
    charge_from_pv_kwh: float = 0.0,
    charge_from_grid_kwh: float = 0.0,
) -> DegradationMetrics:
    """
    Calculate degradation metrics for STACKED (dual-service) dispatch.

    Approximation for charge split:
    - Assume charge is proportional to discharge per service

    New metrics:
    - peak_events_count: number of hours with peak shaving discharge
    - peak_max_discharge_kw: maximum discharge power for peak shaving
    - charge_from_pv_kwh: energy charged from PV surplus
    - charge_from_grid_kwh: energy charged from grid
    """
    usable_capacity = battery.usable_capacity_kwh
    if usable_capacity <= 0:
        usable_capacity = 1  # Avoid division by zero

    # Total metrics
    throughput_total = (total_charge + total_discharge) / 1000  # MWh
    efc_total = total_discharge / usable_capacity

    # Per-service split (approximate charge proportionally)
    if total_discharge > 0:
        peak_ratio = discharge_peak / total_discharge
        pv_ratio = discharge_pv / total_discharge
    else:
        peak_ratio = 0
        pv_ratio = 0

    charge_peak = total_charge * peak_ratio
    charge_pv = total_charge * pv_ratio

    throughput_peak = (charge_peak + discharge_peak) / 1000
    throughput_pv = (charge_pv + discharge_pv) / 1000

    efc_peak = discharge_peak / usable_capacity
    efc_pv = discharge_pv / usable_capacity

    # Charge source percentage
    charge_pv_pct = (charge_from_pv_kwh / total_charge * 100) if total_charge > 0 else 0.0

    return DegradationMetrics(
        throughput_charge_kwh=total_charge,
        throughput_discharge_kwh=total_discharge,
        throughput_total_mwh=throughput_total,
        efc_total=efc_total,
        throughput_pv_mwh=throughput_pv,
        throughput_peak_mwh=throughput_peak,
        efc_pv=efc_pv,
        efc_peak=efc_peak,
        peak_events_count=peak_events_count,
        peak_events_energy_kwh=discharge_peak,
        peak_max_discharge_kw=peak_max_discharge_kw,
        charge_from_pv_kwh=charge_from_pv_kwh,
        charge_from_grid_kwh=charge_from_grid_kwh,
        charge_pv_pct=charge_pv_pct,
        budget_status=DegradationStatus.OK,
        budget_utilization_pct=0.0,
        budget_warnings=[],
    )


def check_degradation_budget(
    metrics: DegradationMetrics,
    budget: Optional[DegradationBudget],
) -> DegradationMetrics:
    """
    Check degradation metrics against budget and update status.

    Warning Thresholds:
    - 80%: Early warning (OK status, informational)
    - 90%: Warning status (approaching limit)
    - 100%: Exceeded status (over budget)

    This allows operators to monitor degradation trajectory and adjust
    dispatch strategy before warranty limits are breached.
    """
    if not budget or not budget.has_limits():
        return metrics

    warnings = []
    utilization = 0.0
    status = DegradationStatus.OK

    # Check EFC budget
    if budget.max_efc_per_year is not None:
        efc_util = (metrics.efc_total / budget.max_efc_per_year) * 100
        utilization = max(utilization, efc_util)

        if efc_util > 100:
            status = DegradationStatus.EXCEEDED
            warnings.append(
                f"EFC EXCEEDED: {metrics.efc_total:.0f} cycles "
                f"(budget: {budget.max_efc_per_year:.0f}, utilization: {efc_util:.0f}%)"
            )
        elif efc_util > 90:
            status = DegradationStatus.WARNING
            warnings.append(
                f"EFC WARNING: {metrics.efc_total:.0f} cycles at {efc_util:.0f}% of budget "
                f"({budget.max_efc_per_year:.0f})"
            )
        elif efc_util > 80:
            # Informational warning, doesn't change status
            warnings.append(
                f"EFC INFO: {metrics.efc_total:.0f} cycles at {efc_util:.0f}% of budget "
                f"({budget.max_efc_per_year:.0f})"
            )

    # Check throughput budget
    if budget.max_throughput_mwh_per_year is not None:
        tp_util = (metrics.throughput_total_mwh / budget.max_throughput_mwh_per_year) * 100
        utilization = max(utilization, tp_util)

        if tp_util > 100:
            status = DegradationStatus.EXCEEDED
            warnings.append(
                f"THROUGHPUT EXCEEDED: {metrics.throughput_total_mwh:.1f} MWh "
                f"(budget: {budget.max_throughput_mwh_per_year:.1f} MWh, utilization: {tp_util:.0f}%)"
            )
        elif tp_util > 90:
            if status != DegradationStatus.EXCEEDED:
                status = DegradationStatus.WARNING
            warnings.append(
                f"THROUGHPUT WARNING: {metrics.throughput_total_mwh:.1f} MWh at {tp_util:.0f}% of budget"
            )
        elif tp_util > 80:
            warnings.append(
                f"THROUGHPUT INFO: {metrics.throughput_total_mwh:.1f} MWh at {tp_util:.0f}% of budget"
            )

    metrics.budget_status = status
    metrics.budget_utilization_pct = min(utilization, 999)
    metrics.budget_warnings = warnings

    return metrics


def dispatch_load_only(
    load_kw: np.ndarray,
    battery: BatteryParams,
    dt_hours: float,
    peak_limit_kw: float,
    prices: Optional[PriceConfig] = None,
    return_hourly: bool = True,
    audit_metadata: Optional[AuditMetadata] = None,
) -> DispatchResult:
    """
    Load-Only (Stand-alone BESS) Dispatch Algorithm
    ================================================

    For systems without PV - BESS charges from grid during off-peak
    and discharges to shave peaks. This is a pure peak-shaving mode.

    Algorithm:
    1. Discharge when load exceeds peak_limit_kw
    2. Charge from grid when load is below peak_limit_kw (headroom charging)
    3. All charging is from grid (no PV)

    Use case:
    - Industrial sites without PV but with demand charges
    - Grid arbitrage with time-of-use tariffs (future)

    Parameters:
    -----------
    load_kw : np.ndarray
        Load consumption power [kW] per timestep
    battery : BatteryParams
        Battery parameters
    dt_hours : float
        Timestep duration in hours
    peak_limit_kw : float
        Maximum grid import power [kW] - target peak to maintain
    prices : PriceConfig
        Energy prices for economic calculation
    return_hourly : bool
        Include hourly arrays in result

    Returns:
    --------
    DispatchResult with peak reduction metrics
    """
    n = len(load_kw)
    prices = prices or PriceConfig()

    # No PV in this mode
    pv_kw = np.zeros(n)

    # Initialize arrays
    charge = np.zeros(n)
    discharge = np.zeros(n)
    grid_import = np.zeros(n)
    soc = np.zeros(n + 1)

    soc[0] = battery.energy_kwh * battery.soc_initial
    soc_min_kwh = battery.energy_kwh * battery.soc_min
    soc_max_kwh = battery.energy_kwh * battery.soc_max
    p_max = battery.power_kw
    eta_ch = battery.eta_charge
    eta_dis = battery.eta_discharge

    original_peak = 0.0
    new_peak = 0.0
    charge_from_grid_kwh = 0.0

    for t in range(n):
        load_t = load_kw[t]
        current_soc = soc[t]

        # Track original peak (without battery)
        original_peak = max(original_peak, load_t)

        if load_t > peak_limit_kw:
            # Need to discharge to shave peak
            required_discharge = load_t - peak_limit_kw
            discharge_power_limit = min(required_discharge, p_max)
            energy_available = current_soc - soc_min_kwh
            max_discharge_from_soc = discharge_power_limit / eta_dis * dt_hours

            if max_discharge_from_soc > energy_available:
                actual_discharge_from_soc = energy_available
                discharge_power = actual_discharge_from_soc * eta_dis / dt_hours
            else:
                discharge_power = discharge_power_limit
                actual_discharge_from_soc = max_discharge_from_soc

            discharge[t] = discharge_power
            current_soc -= actual_discharge_from_soc

            # Actual grid import after battery
            actual_load = load_t - discharge_power
            grid_import[t] = max(0, actual_load)
            new_peak = max(new_peak, grid_import[t])

        else:
            # Below limit, import from grid
            grid_import[t] = load_t
            new_peak = max(new_peak, load_t)

            # Charge if capacity available (headroom charging)
            headroom = peak_limit_kw - load_t
            if headroom > 0 and current_soc < soc_max_kwh:
                charge_power = min(headroom, p_max)
                space_available = soc_max_kwh - current_soc
                max_charge_energy = charge_power * eta_ch * dt_hours

                if max_charge_energy > space_available:
                    actual_charge_energy = space_available
                    charge_power = actual_charge_energy / (eta_ch * dt_hours)
                else:
                    actual_charge_energy = max_charge_energy

                charge[t] = charge_power
                current_soc += actual_charge_energy
                grid_import[t] += charge_power  # Charging adds to grid import
                charge_from_grid_kwh += charge_power * dt_hours

        soc[t + 1] = current_soc

    # Calculate totals
    total_pv = 0.0  # No PV
    total_load = float(np.sum(load_kw) * dt_hours)
    total_direct = 0.0  # No direct PV consumption
    total_charge = float(np.sum(charge) * dt_hours)
    total_discharge = float(np.sum(discharge) * dt_hours)
    total_import = float(np.sum(grid_import) * dt_hours)
    total_export = 0.0  # No export
    total_curtail = 0.0  # No curtailment

    # Self-consumption metrics (N/A for load-only)
    self_consumption = total_discharge  # Battery discharge is the "self-consumption"
    self_consumption_pct = 0.0  # No PV to reference
    grid_independence = (total_discharge / total_load * 100) if total_load > 0 else 0

    peak_reduction = original_peak - new_peak
    peak_reduction_pct = (peak_reduction / original_peak * 100) if original_peak > 0 else 0

    # Degradation metrics with grid charge tracking
    degradation = calculate_degradation_metrics_stacked(
        total_charge=total_charge,
        total_discharge=total_discharge,
        discharge_peak=total_discharge,  # All discharge is for peak shaving
        discharge_pv=0.0,  # No PV shifting
        battery=battery,
        total_hours=n * dt_hours,
        peak_events_count=int(np.sum(discharge > 0)),
        peak_max_discharge_kw=float(np.max(discharge)) if np.any(discharge > 0) else 0.0,
        charge_from_pv_kwh=0.0,  # No PV
        charge_from_grid_kwh=total_charge,  # All charge from grid
    )

    # Economics - Energy cost (note: in LOAD_ONLY mode, battery increases energy import due to losses)
    import_price = prices.import_price_pln_mwh / 1000
    baseline_import_kwh = total_load  # Without battery, all load is from grid
    baseline_energy_cost = baseline_import_kwh * import_price
    project_energy_cost = total_import * import_price
    energy_savings = baseline_energy_cost - project_energy_cost  # Usually negative (losses)

    # Demand charge savings (this is the main value driver for peak shaving)
    demand_charge_per_kw = prices.annual_demand_charge_pln_kw
    baseline_demand_cost = original_peak * demand_charge_per_kw
    project_demand_cost = new_peak * demand_charge_per_kw
    demand_savings = baseline_demand_cost - project_demand_cost  # Savings from peak reduction

    # Total costs and savings
    baseline_cost = baseline_energy_cost + baseline_demand_cost
    project_cost = project_energy_cost + project_demand_cost
    annual_savings = energy_savings + demand_savings  # Energy (negative) + Demand (positive)

    # Build audit info
    audit = audit_metadata or AuditMetadata(
        engine_version=ENGINE_VERSION,
        interval_minutes=int(dt_hours * 60),
    )
    info_dict = {
        "audit": audit.dict(),
        "topology": "load_only",
        "peak_limit_kw": peak_limit_kw,
        "charge_source": "grid",
    }

    result = DispatchResult(
        mode=DispatchMode.LOAD_ONLY,
        battery_power_kw=battery.power_kw,
        battery_energy_kwh=battery.energy_kwh,
        interval_minutes=int(dt_hours * 60),
        n_timesteps=n,
        total_pv_kwh=total_pv,
        total_load_kwh=total_load,
        total_direct_pv_kwh=total_direct,
        total_charge_kwh=total_charge,
        total_discharge_kwh=total_discharge,
        total_grid_import_kwh=total_import,
        total_grid_export_kwh=total_export,
        total_curtailment_kwh=total_curtail,
        self_consumption_kwh=self_consumption,
        self_consumption_pct=self_consumption_pct,
        grid_independence_pct=grid_independence,
        original_peak_kw=original_peak,
        new_peak_kw=new_peak,
        peak_reduction_kw=peak_reduction,
        peak_reduction_pct=peak_reduction_pct,
        degradation=degradation,
        baseline_cost_pln=baseline_cost,
        project_cost_pln=project_cost,
        annual_savings_pln=annual_savings,
        warnings=[],
        info=info_dict,
    )

    if return_hourly:
        result.hourly_charge_kw = charge.tolist()
        result.hourly_discharge_kw = discharge.tolist()
        result.hourly_soc_pct = (soc[:-1] / battery.energy_kwh * 100).tolist()
        result.hourly_grid_import_kw = grid_import.tolist()
        result.hourly_grid_export_kw = [0.0] * n

    return result


def run_dispatch(request: DispatchRequest) -> DispatchResult:
    """
    Main dispatch entry point - routes to appropriate algorithm.

    Supports both PV+Load and Load-only topologies.
    """
    # Use effective_pv_kw which handles LOAD_ONLY topology (returns zeros)
    pv = np.array(request.effective_pv_kw)
    load = np.array(request.load_kw)
    dt_hours = request.dt_hours

    if request.mode == DispatchMode.PV_SURPLUS:
        result = dispatch_pv_surplus(
            pv, load, request.battery, dt_hours, request.prices
        )

    elif request.mode == DispatchMode.PEAK_SHAVING:
        if request.peak_limit_kw is None:
            raise ValueError("peak_limit_kw required for PEAK_SHAVING mode")
        result = dispatch_peak_shaving(
            pv, load, request.battery, dt_hours,
            request.peak_limit_kw, request.prices
        )

    elif request.mode == DispatchMode.STACKED:
        if request.stacked_params is None:
            raise ValueError("stacked_params required for STACKED mode")
        result = dispatch_stacked(
            pv, load, request.battery, dt_hours,
            request.stacked_params, request.prices
        )

    elif request.mode == DispatchMode.LOAD_ONLY:
        if request.peak_limit_kw is None:
            raise ValueError("peak_limit_kw required for LOAD_ONLY mode")
        result = dispatch_load_only(
            load, request.battery, dt_hours,
            request.peak_limit_kw, request.prices
        )

    else:
        raise ValueError(f"Unsupported dispatch mode: {request.mode}")

    # Check degradation budget
    if request.degradation_budget:
        result.degradation = check_degradation_budget(
            result.degradation, request.degradation_budget
        )

    return result

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

from energy_flows_helper import create_energy_flows

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
    ArbitrageConfig,
    SavingsBreakdown,
    PricesSummary,
    EnergyFlows,
    EnergyFlowsTotalsMwh,
    EnergyFlowsTimeseriesKwh,
    ENGINE_VERSION,
)


@dataclass
class DispatchState:
    """Internal state for dispatch simulation"""
    soc_kwh: float  # Current SOC in kWh
    timestep: int


# =============================================================================
# Helper Functions
# =============================================================================

def calculate_energy_cost(
    grid_import_kw: np.ndarray,
    import_prices_pln_kwh: float | np.ndarray,
    dt_hours: float
) -> float:
    """
    Calculate energy cost supporting both constant and time-varying prices.

    Uses np.isscalar for robust type detection (handles numpy scalar types).

    Args:
        grid_import_kw: Grid import power profile [kW]
        import_prices_pln_kwh: Price per kWh (constant float or array)
        dt_hours: Time step duration in hours

    Returns:
        Total energy cost [PLN]
    """
    grid_import_kw = np.asarray(grid_import_kw, dtype=float)

    if np.isscalar(import_prices_pln_kwh):
        price = float(import_prices_pln_kwh)
        return float(np.sum(grid_import_kw) * dt_hours * price)

    prices = np.asarray(import_prices_pln_kwh, dtype=float)
    if prices.shape[0] != grid_import_kw.shape[0]:
        raise ValueError(f"Price series length ({prices.shape[0]}) != grid_import length ({grid_import_kw.shape[0]})")
    return float(np.sum(grid_import_kw * prices) * dt_hours)


def create_prices_summary(prices: PriceConfig, tariff_type: str = "flat") -> PricesSummary:
    """
    Create PricesSummary from PriceConfig.

    Args:
        prices: Price configuration
        tariff_type: Type of tariff used ("flat", "two_zone", "three_zone")

    Returns:
        PricesSummary for inclusion in DispatchResult
    """
    return PricesSummary(
        import_price_pln_mwh=prices.import_price_pln_mwh,
        export_price_pln_mwh=prices.export_price_pln_mwh,
        demand_charge_pln_kw_month=prices.demand_charge_pln_kw_month,
        demand_charge_pln_kw_year=prices.demand_charge_pln_kw_year,
        tariff_type=tariff_type,
        tariff_id=None,
        zone_rates=None
    )


def create_savings_breakdown(
    energy_savings_pln: float,
    demand_charge_savings_pln: float,
    arbitrage_savings_pln: float = 0.0,
    capacity_fee_savings_pln: float = 0.0,
    degradation_cost_pln: float = 0.0
) -> SavingsBreakdown:
    """
    Create SavingsBreakdown with calculated net savings.

    Note: degradation_cost impacts only net_savings and UI display,
    not annual_savings_pln which goes to NPV calculation.

    Args:
        energy_savings_pln: Savings from self-consumption / reduced import
        demand_charge_savings_pln: Savings from peak shaving (demand charge)
        arbitrage_savings_pln: Savings from ToU arbitrage (incremental vs no-arb)
        capacity_fee_savings_pln: Savings from capacity fee PL (separate module)
        degradation_cost_pln: Battery degradation cost (throughput-based)

    Returns:
        SavingsBreakdown instance
    """
    net_savings = (
        energy_savings_pln +
        demand_charge_savings_pln +
        arbitrage_savings_pln +
        capacity_fee_savings_pln -
        abs(degradation_cost_pln)
    )

    return SavingsBreakdown(
        energy_savings_pln=energy_savings_pln,
        demand_charge_savings_pln=demand_charge_savings_pln,
        arbitrage_savings_pln=arbitrage_savings_pln,
        capacity_fee_savings_pln=capacity_fee_savings_pln,
        degradation_cost_pln=degradation_cost_pln,
        net_savings_pln=net_savings
    )


# =============================================================================
# Dispatch Algorithms
# =============================================================================

def dispatch_pv_surplus(
    pv_kw: np.ndarray,
    load_kw: np.ndarray,
    battery: BatteryParams,
    dt_hours: float,
    prices: Optional[PriceConfig] = None,
    return_hourly: bool = True,
    audit_metadata: Optional[AuditMetadata] = None,
    include_energy_flows_timeseries: bool = False,
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
    batt_losses_kwh = np.zeros(n)  # Track losses per step

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

    # === SAVINGS BREAKDOWN ===

    # 1. Energy savings (autokonsumpcja + redukcja importu)
    energy_savings_pln = baseline_cost - project_cost

    # 2. Demand charge savings (peak shaving)
    # PV_SURPLUS mode may have some peak reduction, calculate it
    baseline_peak = float(np.max(baseline_import))
    project_peak = float(np.max(grid_import))
    demand_charge_rate_annual = prices.annual_demand_charge_pln_kw
    demand_charge_savings_pln = (baseline_peak - project_peak) * demand_charge_rate_annual

    # 3. Arbitrage savings - 0 in PV_SURPLUS
    arbitrage_savings_pln = 0.0

    # 4. Capacity fee savings - 0 (separate overlay)
    capacity_fee_savings_pln = 0.0

    # 5. Degradation cost - 0 (default)
    degradation_cost_pln = 0.0

    # annual_savings_pln = energy + demand (goes to NPV)
    annual_savings = energy_savings_pln + demand_charge_savings_pln

    # Create breakdown
    savings_breakdown = create_savings_breakdown(
        energy_savings_pln=energy_savings_pln,
        demand_charge_savings_pln=demand_charge_savings_pln,
        arbitrage_savings_pln=arbitrage_savings_pln,
        capacity_fee_savings_pln=capacity_fee_savings_pln,
        degradation_cost_pln=degradation_cost_pln
    )

    # Create prices summary
    prices_summary = create_prices_summary(prices, tariff_type="flat")

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
        original_peak_kw=baseline_peak,
        new_peak_kw=project_peak,
        peak_reduction_kw=baseline_peak - project_peak,
        peak_reduction_pct=((baseline_peak - project_peak) / baseline_peak * 100) if baseline_peak > 0 else 0,
        degradation=degradation,
        baseline_cost_pln=baseline_cost,
        project_cost_pln=project_cost,
        annual_savings_pln=annual_savings,
        savings_breakdown=savings_breakdown,
        prices_summary=prices_summary,
        warnings=[],
        info=info_dict,
    )

    if return_hourly:
        result.hourly_charge_kw = charge.tolist()
        result.hourly_discharge_kw = discharge.tolist()
        result.hourly_soc_pct = (soc[:-1] / battery.energy_kwh * 100).tolist()
        result.hourly_grid_import_kw = grid_import.tolist()
        result.hourly_grid_export_kw = grid_export.tolist()

    # === ENERGY FLOWS SSoT ===
    # Convert power arrays (kW) to energy arrays (kWh) for flows
    pv_to_load_kwh_arr = direct_pv * dt_hours
    pv_to_batt_kwh_arr = charge * dt_hours  # All charge is from PV surplus
    pv_curtail_kwh_arr = curtailment * dt_hours
    batt_to_load_kwh_arr = discharge * dt_hours
    batt_charge_grid_kwh_arr = np.zeros(n)  # No grid charging in PV_SURPLUS
    grid_import_kwh_arr = grid_import * dt_hours
    grid_export_kwh_arr = grid_export * dt_hours
    soc_kwh_arr = soc[:-1]

    # Calculate battery losses per step (proportional to throughput)
    total_energy_in = np.sum(charge * dt_hours)
    total_energy_out = np.sum(discharge * dt_hours)
    total_loss = total_energy_in - total_energy_out + (soc[0] - soc[-1])
    throughput_per_step = charge + discharge
    total_throughput = np.sum(throughput_per_step)
    if total_throughput > 0 and total_loss > 0:
        batt_losses_kwh_arr = throughput_per_step / total_throughput * total_loss
    else:
        batt_losses_kwh_arr = np.zeros(n)

    result.energy_flows = create_energy_flows(
        grid_import_kwh=grid_import_kwh_arr,
        grid_export_kwh=grid_export_kwh_arr,
        pv_to_load_kwh=pv_to_load_kwh_arr,
        pv_to_batt_kwh=pv_to_batt_kwh_arr,
        pv_curtail_kwh=pv_curtail_kwh_arr,
        batt_to_load_kwh=batt_to_load_kwh_arr,
        batt_charge_from_grid_kwh=batt_charge_grid_kwh_arr,
        batt_losses_kwh=batt_losses_kwh_arr,
        soc_kwh=soc_kwh_arr,
        include_timeseries=include_energy_flows_timeseries,
    )

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
    include_energy_flows_timeseries: bool = False,
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
    batt_losses_kwh = np.zeros(n)  # Track losses per step

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

    # === ENERGY FLOWS SSoT ===
    # Convert power arrays (kW) to energy arrays (kWh) for flows
    pv_to_load_kwh_arr = direct_pv * dt_hours
    pv_to_batt_kwh_arr = np.zeros(n)  # Peak shaving charges from grid, not PV
    pv_curtail_kwh_arr = curtailment * dt_hours
    batt_to_load_kwh_arr = discharge * dt_hours
    batt_charge_grid_kwh_arr = charge * dt_hours  # All charge is from grid in peak shaving
    grid_import_kwh_arr = grid_import * dt_hours
    grid_export_kwh_arr = grid_export * dt_hours
    soc_kwh_arr = soc[:-1]

    # Calculate battery losses per step (proportional to throughput)
    total_energy_in = np.sum(charge * dt_hours)
    total_energy_out = np.sum(discharge * dt_hours)
    total_loss = total_energy_in - total_energy_out + (soc[0] - soc[-1])
    throughput_per_step = charge + discharge
    total_throughput = np.sum(throughput_per_step)
    if total_throughput > 0 and total_loss > 0:
        batt_losses_kwh_arr = throughput_per_step / total_throughput * total_loss
    else:
        batt_losses_kwh_arr = np.zeros(n)

    result.energy_flows = create_energy_flows(
        grid_import_kwh=grid_import_kwh_arr,
        grid_export_kwh=grid_export_kwh_arr,
        pv_to_load_kwh=pv_to_load_kwh_arr,
        pv_to_batt_kwh=pv_to_batt_kwh_arr,
        pv_curtail_kwh=pv_curtail_kwh_arr,
        batt_to_load_kwh=batt_to_load_kwh_arr,
        batt_charge_from_grid_kwh=batt_charge_grid_kwh_arr,
        batt_losses_kwh=batt_losses_kwh_arr,
        soc_kwh=soc_kwh_arr,
        include_timeseries=include_energy_flows_timeseries,
    )

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
    # Arbitrage parameters (optional)
    import_prices: Optional[np.ndarray] = None,
    arb_config: Optional[ArbitrageConfig] = None,
    include_energy_flows_timeseries: bool = False,
) -> DispatchResult:
    """
    STACKED Dispatch Algorithm (PV Shifting + Peak Shaving + Optional Arbitrage)
    =============================================================================

    One battery provides two or three services with priority:
    1. Peak Shaving (priority 1): Protect against grid peaks - uses FULL SOC
    2. PV Surplus Charging (priority 2): Always charge from PV first - FREE energy
    3. Arbitrage Grid Charge (priority 3): Charge from grid when price low (if enabled)
    4. Arbitrage Discharge (priority 4): Discharge when price high (if enabled)
    5. PV Shifting Discharge (priority 5): Discharge for load deficit (above reserve)

    CRITICAL: PV charging has priority over grid charging to avoid curtailing free energy.

    SOC Reserve mechanism:
    - reserve_soc: Reserved for peak shaving (PV shifting can't go below)
    - arb_soc_min: Additional floor for arbitrage discharge
    - Effective discharge floor = max(reserve_soc, arb_soc_min, soc_min)

    Arbitrage gating:
    - When price <= charge_threshold (cheap): allow grid charging, but NO PV-shifting discharge
    - When price >= discharge_threshold (expensive): allow arbitrage discharge
    - In neutral band: hold (no discharge except for peak shaving)

    Parameters:
    -----------
    stacked_params : StackedModeParams
        - peak_limit_kw: Grid import limit [kW]
        - reserve_fraction: SOC fraction reserved for peak shaving (e.g., 0.3)
    import_prices : np.ndarray, optional
        Time-varying import prices [PLN/kWh] per timestep (for arbitrage)
    arb_config : ArbitrageConfig, optional
        Arbitrage configuration (thresholds, limits, etc.)

    Returns:
    --------
    DispatchResult with per-service degradation breakdown including arbitrage metrics
    """
    n = len(pv_kw)
    prices = prices or PriceConfig()
    peak_limit = stacked_params.peak_limit_kw
    reserve_frac = stacked_params.reserve_fraction

    # Arbitrage setup
    arb_enabled = (arb_config is not None and arb_config.enabled and import_prices is not None)
    allow_grid_charging = arb_config.allow_grid_charging if arb_config else True
    if arb_enabled:
        # Calculate thresholds from price distribution
        charge_threshold = float(np.percentile(import_prices, arb_config.charge_below_percentile))
        discharge_threshold = float(np.percentile(import_prices, arb_config.discharge_above_percentile))
        arb_soc_min_kwh = battery.energy_kwh * arb_config.arbitrage_soc_min
        # Grid charging only if allowed
        max_grid_charge = (arb_config.max_grid_charge_kw or battery.power_kw) if allow_grid_charging else 0.0
    else:
        charge_threshold = 0.0
        discharge_threshold = float('inf')
        arb_soc_min_kwh = 0.0
        max_grid_charge = 0.0

    # Net load
    net_load = load_kw - pv_kw

    # Initialize arrays
    direct_pv = np.zeros(n)
    charge = np.zeros(n)
    charge_from_pv = np.zeros(n)   # Track charge source: PV
    charge_from_grid = np.zeros(n) # Track charge source: grid (arbitrage)
    discharge = np.zeros(n)
    discharge_peak = np.zeros(n)  # For peak shaving service
    discharge_pv = np.zeros(n)    # For PV shifting service
    discharge_arb = np.zeros(n)   # For arbitrage service
    grid_import = np.zeros(n)
    grid_export = np.zeros(n)
    curtailment = np.zeros(n)
    soc = np.zeros(n + 1)
    batt_losses_kwh = np.zeros(n)  # Track losses per step

    soc[0] = battery.energy_kwh * battery.soc_initial
    soc_min_kwh = battery.energy_kwh * battery.soc_min
    soc_max_kwh = battery.energy_kwh * battery.soc_max
    # Reserve SOC for peak shaving
    reserve_soc_kwh = battery.energy_kwh * reserve_frac
    # Effective min SOC for PV shifting (above reserve)
    pv_soc_min_kwh = max(soc_min_kwh, reserve_soc_kwh)
    # Effective floor for arbitrage discharge = max(reserve, arb_min, soc_min)
    arb_discharge_floor_kwh = max(reserve_soc_kwh, arb_soc_min_kwh, soc_min_kwh)

    p_max = battery.power_kw
    eta_ch = battery.eta_charge
    eta_dis = battery.eta_discharge

    original_peak = 0.0
    new_peak = 0.0
    warnings = []

    # Arbitrage metrics
    arb_charge_kwh = 0.0
    arb_discharge_kwh = 0.0
    arb_cycles = 0

    for t in range(n):
        pv_t = pv_kw[t]
        load_t = load_kw[t]
        net_t = net_load[t]
        price_t = import_prices[t] if arb_enabled else 0.0

        # Direct PV consumption
        direct = min(pv_t, load_t)
        direct_pv[t] = direct

        surplus = max(0, pv_t - load_t)
        deficit = max(0, load_t - pv_t)

        current_soc = soc[t]

        # Track original peak (net import without battery)
        if net_t > 0:
            original_peak = max(original_peak, net_t)

        # Remaining charging capacity after this timestep (updated as we go)
        remaining_charge_capacity = p_max

        # ===== PRIORITY 1: Peak Shaving (discharge) =====
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

        else:
            # No peak shaving needed - proceed with other priorities

            # ===== PRIORITY 2: PV Surplus Charging (ALWAYS FIRST for charging) =====
            if surplus > 0 and current_soc < soc_max_kwh:
                charge_power_limit = min(surplus, p_max)
                space_available = soc_max_kwh - current_soc
                max_charge_energy = charge_power_limit * eta_ch * dt_hours

                if max_charge_energy > space_available:
                    actual_charge_energy = space_available
                    pv_charge_power = actual_charge_energy / (eta_ch * dt_hours)
                else:
                    pv_charge_power = charge_power_limit
                    actual_charge_energy = max_charge_energy

                charge[t] += pv_charge_power
                charge_from_pv[t] = pv_charge_power
                current_soc += actual_charge_energy
                remaining_charge_capacity -= pv_charge_power

                # Curtail excess PV that couldn't be stored
                curtailment[t] = surplus - pv_charge_power

            elif surplus > 0:
                # Battery full, curtail all surplus
                curtailment[t] = surplus

            # ===== PRIORITY 3: Arbitrage Grid Charging (if price low) =====
            if arb_enabled and price_t <= charge_threshold:
                # Cheap energy - charge from grid (but only if spare capacity)
                if remaining_charge_capacity > 0 and current_soc < soc_max_kwh:
                    # Calculate headroom to stay under peak_limit
                    current_import = max(0, deficit) if deficit > 0 else 0
                    headroom = peak_limit - current_import

                    if headroom > 0:
                        arb_charge_limit = min(remaining_charge_capacity, max_grid_charge, headroom)
                        space_available = soc_max_kwh - current_soc
                        max_charge_energy = arb_charge_limit * eta_ch * dt_hours

                        if max_charge_energy > space_available:
                            actual_charge_energy = space_available
                            grid_charge_power = actual_charge_energy / (eta_ch * dt_hours)
                        else:
                            grid_charge_power = arb_charge_limit
                            actual_charge_energy = max_charge_energy

                        if grid_charge_power > 0.01:  # Threshold to avoid tiny charges
                            charge[t] += grid_charge_power
                            charge_from_grid[t] = grid_charge_power
                            current_soc += actual_charge_energy
                            arb_charge_kwh += grid_charge_power * dt_hours

                # In cheap zone: NO PV-shifting discharge (hold energy for later)
                # Just import deficit from grid
                if deficit > 0:
                    grid_import[t] = deficit + charge_from_grid[t]
                else:
                    grid_import[t] = charge_from_grid[t]
                new_peak = max(new_peak, grid_import[t])

            # ===== PRIORITY 4: Arbitrage Discharge (if price high) =====
            elif arb_enabled and price_t >= discharge_threshold and deficit > 0:
                # Expensive energy - discharge to cover load (above arb floor)
                energy_available_arb = max(0, current_soc - arb_discharge_floor_kwh)

                if energy_available_arb > 0:
                    discharge_power_limit = min(deficit, p_max)
                    max_discharge_from_soc = discharge_power_limit / eta_dis * dt_hours

                    if max_discharge_from_soc > energy_available_arb:
                        actual_discharge_from_soc = energy_available_arb
                        arb_dis_power = actual_discharge_from_soc * eta_dis / dt_hours
                    else:
                        arb_dis_power = discharge_power_limit
                        actual_discharge_from_soc = max_discharge_from_soc

                    discharge[t] = arb_dis_power
                    discharge_arb[t] = arb_dis_power
                    current_soc -= actual_discharge_from_soc
                    arb_discharge_kwh += arb_dis_power * dt_hours
                    arb_cycles += 1

                    # Remaining deficit from grid
                    grid_import[t] = deficit - arb_dis_power
                else:
                    grid_import[t] = deficit

                new_peak = max(new_peak, grid_import[t])

            # ===== PRIORITY 5: PV Shifting Discharge (neutral zone or arb disabled) =====
            elif deficit > 0:
                # Not in cheap zone - can discharge for PV shifting (above reserve)
                # Skip if in cheap zone (handled above with hold strategy)
                if not arb_enabled or price_t > charge_threshold:
                    energy_available_pv = max(0, current_soc - pv_soc_min_kwh)

                    if energy_available_pv > 0:
                        discharge_power_limit = min(deficit, p_max)
                        max_discharge_from_soc = discharge_power_limit / eta_dis * dt_hours

                        if max_discharge_from_soc > energy_available_pv:
                            actual_discharge_from_soc = energy_available_pv
                            pv_dis_power = actual_discharge_from_soc * eta_dis / dt_hours
                        else:
                            pv_dis_power = discharge_power_limit
                            actual_discharge_from_soc = max_discharge_from_soc

                        discharge[t] = pv_dis_power
                        discharge_pv[t] = pv_dis_power
                        current_soc -= actual_discharge_from_soc

                        # Remaining deficit from grid
                        grid_import[t] = deficit - pv_dis_power
                    else:
                        grid_import[t] = deficit
                else:
                    # In cheap zone but already handled above
                    pass

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
    total_discharge_arb = float(np.sum(discharge_arb) * dt_hours)
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

    # Degradation with per-service breakdown (now with arbitrage metrics)
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

    # Add arbitrage metrics to degradation
    if arb_enabled:
        degradation.throughput_arb_mwh = (arb_charge_kwh + arb_discharge_kwh) / 1000
        degradation.efc_arb = arb_discharge_kwh / battery.usable_capacity_kwh if battery.usable_capacity_kwh > 0 else 0
        degradation.arb_charge_from_grid_kwh = arb_charge_kwh
        degradation.arb_discharge_kwh = arb_discharge_kwh
        degradation.arb_cycles_count = arb_cycles

    # Economics - use time-varying prices if available
    if arb_enabled:
        # Time-varying prices: calculate actual costs
        baseline_import_profile = np.maximum(net_load, 0)
        baseline_cost = float(np.sum(baseline_import_profile * import_prices) * dt_hours)
        project_cost = float(np.sum(grid_import * import_prices) * dt_hours)

        # Calculate arbitrage spread for info
        if arb_discharge_kwh > 0 and arb_charge_kwh > 0:
            avg_charge_price = float(np.mean(import_prices[charge_from_grid > 0])) if np.any(charge_from_grid > 0) else 0
            avg_discharge_price = float(np.mean(import_prices[discharge_arb > 0])) if np.any(discharge_arb > 0) else 0
            arb_spread = avg_discharge_price - avg_charge_price
        else:
            avg_charge_price = 0.0
            avg_discharge_price = 0.0
            arb_spread = 0.0
    else:
        # Flat price
        import_price = prices.import_price_pln_mwh / 1000
        baseline_import_kwh = float(np.sum(np.maximum(net_load, 0)) * dt_hours)
        baseline_cost = baseline_import_kwh * import_price
        project_cost = total_import * import_price
        avg_charge_price = 0.0
        avg_discharge_price = 0.0
        arb_spread = 0.0

    # === SAVINGS BREAKDOWN ===

    # 1. Energy savings (autokonsumpcja + redukcja importu)
    energy_savings_pln = baseline_cost - project_cost

    # 2. Demand charge savings (peak shaving)
    # demand_charge_pln_kw_month * 12 + demand_charge_pln_kw_year = annual rate
    demand_charge_rate_annual = prices.annual_demand_charge_pln_kw
    baseline_demand_cost = original_peak * demand_charge_rate_annual
    project_demand_cost = new_peak * demand_charge_rate_annual
    demand_charge_savings_pln = baseline_demand_cost - project_demand_cost

    # 3. Arbitrage savings
    # On MVP: 0 in STACKED (arbitrage only in /arbitrage/dispatch as incremental benefit)
    arbitrage_savings_pln = 0.0

    # 4. Capacity fee savings
    # On MVP: 0 (separate overlay /capacity-fee/savings)
    capacity_fee_savings_pln = 0.0

    # 5. Degradation cost (default 0, enabled only if user provides params)
    # Uses throughput_total (charge + discharge) from degradation metrics
    degradation_cost_pln = 0.0

    # IMPORTANT: annual_savings_pln = energy + demand (goes to NPV)
    annual_savings = energy_savings_pln + demand_charge_savings_pln

    # Create breakdown
    savings_breakdown = create_savings_breakdown(
        energy_savings_pln=energy_savings_pln,
        demand_charge_savings_pln=demand_charge_savings_pln,
        arbitrage_savings_pln=arbitrage_savings_pln,
        capacity_fee_savings_pln=capacity_fee_savings_pln,
        degradation_cost_pln=degradation_cost_pln
    )

    # Create prices summary
    prices_summary = create_prices_summary(prices, tariff_type="flat")

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
        "discharge_arb_kwh": total_discharge_arb,
    }

    # Add arbitrage info if enabled
    if arb_enabled:
        info_dict["arbitrage"] = {
            "enabled": True,
            "tariff_id": arb_config.tariff_id,
            "charge_threshold_pln_kwh": charge_threshold,
            "discharge_threshold_pln_kwh": discharge_threshold,
            "charge_kwh": arb_charge_kwh,
            "discharge_kwh": arb_discharge_kwh,
            "avg_charge_price": avg_charge_price,
            "avg_discharge_price": avg_discharge_price,
            "spread_pln_kwh": arb_spread,
            "energy_savings_pln": energy_savings_pln,
            "cycles_count": arb_cycles,
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
        savings_breakdown=savings_breakdown,
        prices_summary=prices_summary,
        warnings=warnings,
        info=info_dict,
    )

    if return_hourly:
        result.hourly_charge_kw = charge.tolist()
        result.hourly_discharge_kw = discharge.tolist()
        result.hourly_soc_pct = (soc[:-1] / battery.energy_kwh * 100).tolist()
        result.hourly_grid_import_kw = grid_import.tolist()
        result.hourly_grid_export_kw = grid_export.tolist()

    # === ENERGY FLOWS SSoT ===
    # Convert power arrays (kW) to energy arrays (kWh) for flows
    pv_to_load_kwh_arr = direct_pv * dt_hours
    pv_to_batt_kwh_arr = charge_from_pv * dt_hours
    pv_curtail_kwh_arr = curtailment * dt_hours
    batt_to_load_kwh_arr = discharge * dt_hours
    batt_charge_grid_kwh_arr = charge_from_grid * dt_hours
    grid_import_kwh_arr = grid_import * dt_hours
    grid_export_kwh_arr = grid_export * dt_hours
    soc_kwh_arr = soc[:-1]

    # Calculate battery losses per step (proportional to throughput)
    total_energy_in = np.sum(charge * dt_hours)
    total_energy_out = np.sum(discharge * dt_hours)
    total_loss = total_energy_in - total_energy_out + (soc[0] - soc[-1])
    throughput_per_step = charge + discharge
    total_throughput = np.sum(throughput_per_step)
    if total_throughput > 0 and total_loss > 0:
        batt_losses_kwh_arr = throughput_per_step / total_throughput * total_loss
    else:
        batt_losses_kwh_arr = np.zeros(n)

    result.energy_flows = create_energy_flows(
        grid_import_kwh=grid_import_kwh_arr,
        grid_export_kwh=grid_export_kwh_arr,
        pv_to_load_kwh=pv_to_load_kwh_arr,
        pv_to_batt_kwh=pv_to_batt_kwh_arr,
        pv_curtail_kwh=pv_curtail_kwh_arr,
        batt_to_load_kwh=batt_to_load_kwh_arr,
        batt_charge_from_grid_kwh=batt_charge_grid_kwh_arr,
        batt_losses_kwh=batt_losses_kwh_arr,
        soc_kwh=soc_kwh_arr,
        include_timeseries=include_energy_flows_timeseries,
    )

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
    include_energy_flows_timeseries: bool = False,
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
    batt_losses_kwh = np.zeros(n)  # Track losses per step

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

    # === SAVINGS BREAKDOWN ===
    # Note: energy_savings may be negative in LOAD_ONLY (battery losses)
    # demand_savings is the main value driver

    # Create breakdown
    savings_breakdown = create_savings_breakdown(
        energy_savings_pln=energy_savings,
        demand_charge_savings_pln=demand_savings,
        arbitrage_savings_pln=0.0,
        capacity_fee_savings_pln=0.0,
        degradation_cost_pln=0.0
    )

    # Create prices summary
    prices_summary = create_prices_summary(prices, tariff_type="flat")

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
        savings_breakdown=savings_breakdown,
        prices_summary=prices_summary,
        warnings=[],
        info=info_dict,
    )

    if return_hourly:
        result.hourly_charge_kw = charge.tolist()
        result.hourly_discharge_kw = discharge.tolist()
        result.hourly_soc_pct = (soc[:-1] / battery.energy_kwh * 100).tolist()
        result.hourly_grid_import_kw = grid_import.tolist()
        result.hourly_grid_export_kw = [0.0] * n

    # === ENERGY FLOWS SSoT ===
    # Convert power arrays (kW) to energy arrays (kWh) for flows
    pv_to_load_kwh_arr = np.zeros(n)  # No PV in LOAD_ONLY
    pv_to_batt_kwh_arr = np.zeros(n)  # No PV charging
    pv_curtail_kwh_arr = np.zeros(n)  # No curtailment
    batt_to_load_kwh_arr = discharge * dt_hours
    batt_charge_grid_kwh_arr = charge * dt_hours  # All charge is from grid
    grid_import_kwh_arr = grid_import * dt_hours
    grid_export_kwh_arr = np.zeros(n)  # No export
    soc_kwh_arr = soc[:-1]

    # Calculate battery losses per step (proportional to throughput)
    total_energy_in = np.sum(charge * dt_hours)
    total_energy_out = np.sum(discharge * dt_hours)
    total_loss = total_energy_in - total_energy_out + (soc[0] - soc[-1])
    throughput_per_step = charge + discharge
    total_throughput = np.sum(throughput_per_step)
    if total_throughput > 0 and total_loss > 0:
        batt_losses_kwh_arr = throughput_per_step / total_throughput * total_loss
    else:
        batt_losses_kwh_arr = np.zeros(n)

    result.energy_flows = create_energy_flows(
        grid_import_kwh=grid_import_kwh_arr,
        grid_export_kwh=grid_export_kwh_arr,
        pv_to_load_kwh=pv_to_load_kwh_arr,
        pv_to_batt_kwh=pv_to_batt_kwh_arr,
        pv_curtail_kwh=pv_curtail_kwh_arr,
        batt_to_load_kwh=batt_to_load_kwh_arr,
        batt_charge_from_grid_kwh=batt_charge_grid_kwh_arr,
        batt_losses_kwh=batt_losses_kwh_arr,
        soc_kwh=soc_kwh_arr,
        include_timeseries=include_energy_flows_timeseries,
    )

    return result


def run_dispatch(
    request: DispatchRequest,
    import_prices: Optional[np.ndarray] = None,
) -> DispatchResult:
    """
    Main dispatch entry point - routes to appropriate algorithm.

    Supports both PV+Load and Load-only topologies.

    Parameters:
    -----------
    request : DispatchRequest
        Dispatch request with all configuration
    import_prices : np.ndarray, optional
        Time-varying import prices [PLN/kWh] per timestep.
        Required if request.arbitrage_config.enabled is True.
        Should be fetched from price_engine before calling this function.

    Returns:
    --------
    DispatchResult with dispatch results and optional arbitrage metrics
    """
    # Use effective_pv_kw which handles LOAD_ONLY topology (returns zeros)
    pv = np.array(request.effective_pv_kw)
    load = np.array(request.load_kw)
    dt_hours = request.dt_hours

    # Validate arbitrage requirements
    arb_config = request.arbitrage_config
    if arb_config and arb_config.enabled:
        if import_prices is None:
            raise ValueError(
                "import_prices required when arbitrage_config.enabled=True. "
                "Fetch prices using price_engine before calling run_dispatch."
            )
        if len(import_prices) != len(load):
            raise ValueError(
                f"import_prices length ({len(import_prices)}) must match load_kw length ({len(load)})"
            )

    if request.mode == DispatchMode.PV_SURPLUS:
        result = dispatch_pv_surplus(
            pv, load, request.battery, dt_hours, request.prices,
            include_energy_flows_timeseries=request.include_energy_flows_timeseries,
        )

    elif request.mode == DispatchMode.PEAK_SHAVING:
        if request.peak_limit_kw is None:
            raise ValueError("peak_limit_kw required for PEAK_SHAVING mode")
        result = dispatch_peak_shaving(
            pv, load, request.battery, dt_hours,
            request.peak_limit_kw, request.prices,
            include_energy_flows_timeseries=request.include_energy_flows_timeseries,
        )

    elif request.mode == DispatchMode.STACKED:
        if request.stacked_params is None:
            raise ValueError("stacked_params required for STACKED mode")
        result = dispatch_stacked(
            pv, load, request.battery, dt_hours,
            request.stacked_params, request.prices,
            import_prices=import_prices,
            arb_config=arb_config,
            include_energy_flows_timeseries=request.include_energy_flows_timeseries,
        )

    elif request.mode == DispatchMode.LOAD_ONLY:
        if request.peak_limit_kw is None:
            raise ValueError("peak_limit_kw required for LOAD_ONLY mode")
        result = dispatch_load_only(
            load, request.battery, dt_hours,
            request.peak_limit_kw, request.prices,
            include_energy_flows_timeseries=request.include_energy_flows_timeseries,
        )

    else:
        raise ValueError(f"Unsupported dispatch mode: {request.mode}")

    # Check degradation budget
    if request.degradation_budget:
        result.degradation = check_degradation_budget(
            result.degradation, request.degradation_budget
        )

    return result

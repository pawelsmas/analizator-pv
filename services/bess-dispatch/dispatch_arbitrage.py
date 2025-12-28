"""
ToU Arbitrage Dispatch Algorithm
================================

Price-driven dispatch for Time-of-Use tariff arbitrage.

This module provides:
- dispatch_tou_arbitrage: Core arbitrage algorithm
- run_arbitrage_with_price_bundle: Convenience wrapper using PriceBundle

The algorithm:
1. Charges from grid when price < charge_threshold (P25)
2. Discharges when price > discharge_threshold (P75)
3. Optionally enforces peak_limit_kw constraint
4. Prioritizes load coverage over pure arbitrage

Version: 1.0.0
"""

import numpy as np
from typing import Optional, Dict, Any, List
from datetime import date

from models import (
    BatteryParams,
    DispatchResult,
    DispatchMode,
    PriceConfig,
    AuditMetadata,
    ENGINE_VERSION,
)
from dispatch_engine import calculate_degradation_metrics_stacked
from price_engine import (
    PriceBundle,
    EconomicDispatchConfig,
    calculate_arbitrage_thresholds,
)


def dispatch_tou_arbitrage(
    load_kw: np.ndarray,
    battery: BatteryParams,
    dt_hours: float,
    import_prices: np.ndarray,
    export_prices: np.ndarray,
    charge_threshold: float,
    discharge_threshold: float,
    peak_limit_kw: Optional[float] = None,
    prices: Optional[PriceConfig] = None,
    return_hourly: bool = True,
    audit_metadata: Optional[AuditMetadata] = None,
) -> DispatchResult:
    """
    ToU Arbitrage Dispatch Algorithm

    Price-driven dispatch that:
    1. Charges from grid when price < charge_threshold
    2. Discharges when price > discharge_threshold (and has load)
    3. Optionally respects peak_limit_kw constraint

    Strategy:
    - Uses percentile-based thresholds (P25/P75 typical)
    - Prioritizes load coverage over pure arbitrage
    - No grid export (prosumer model)

    Parameters:
    -----------
    load_kw : np.ndarray
        Load consumption power [kW] per timestep
    battery : BatteryParams
        Battery parameters
    dt_hours : float
        Timestep duration in hours
    import_prices : np.ndarray
        Import price [PLN/kWh] per timestep
    export_prices : np.ndarray
        Export price [PLN/kWh] per timestep (usually 0)
    charge_threshold : float
        Price threshold below which to charge [PLN/kWh]
    discharge_threshold : float
        Price threshold above which to discharge [PLN/kWh]
    peak_limit_kw : float, optional
        Grid import limit (for hybrid peak+arbitrage)
    prices : PriceConfig
        Legacy price config for demand charge calculation

    Returns:
    --------
    DispatchResult with all energy flows and arbitrage metrics
    """
    n = len(load_kw)
    prices = prices or PriceConfig()

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
    arbitrage_charge_kwh = 0.0
    arbitrage_discharge_kwh = 0.0

    for t in range(n):
        load_t = load_kw[t]
        price_t = import_prices[t]
        current_soc = soc[t]

        original_peak = max(original_peak, load_t)
        effective_limit = peak_limit_kw if peak_limit_kw else float('inf')

        # ==== PRIORITY 1: Peak shaving (if limit set) ====
        if load_t > effective_limit:
            required = load_t - effective_limit
            power_limit = min(required, p_max)
            available = current_soc - soc_min_kwh
            max_dis = power_limit / eta_dis * dt_hours

            if max_dis > available:
                actual_dis = available
                dis_power = actual_dis * eta_dis / dt_hours
            else:
                dis_power = power_limit
                actual_dis = max_dis

            discharge[t] = dis_power
            current_soc -= actual_dis
            grid_import[t] = max(0, load_t - dis_power)
            new_peak = max(new_peak, grid_import[t])

        # ==== PRIORITY 2: Low price - charge from grid ====
        elif price_t <= charge_threshold:
            grid_import[t] = load_t  # First cover load
            new_peak = max(new_peak, grid_import[t])

            # Calculate headroom for charging
            headroom = effective_limit - load_t if peak_limit_kw else p_max
            if headroom > 0 and current_soc < soc_max_kwh:
                ch_power = min(headroom, p_max)
                space = soc_max_kwh - current_soc
                max_ch = ch_power * eta_ch * dt_hours

                if max_ch > space:
                    actual_ch = space
                    ch_power = actual_ch / (eta_ch * dt_hours)
                else:
                    actual_ch = max_ch

                charge[t] = ch_power
                current_soc += actual_ch
                grid_import[t] += ch_power  # Charging adds to grid import
                arbitrage_charge_kwh += ch_power * dt_hours
                new_peak = max(new_peak, grid_import[t])

        # ==== PRIORITY 3: High price - discharge to offset load ====
        elif price_t >= discharge_threshold:
            power_limit = min(load_t, p_max)
            available = current_soc - soc_min_kwh
            max_dis = power_limit / eta_dis * dt_hours

            if available > 0 and max_dis > 0:
                if max_dis > available:
                    actual_dis = available
                    dis_power = actual_dis * eta_dis / dt_hours
                else:
                    dis_power = power_limit
                    actual_dis = max_dis

                discharge[t] = dis_power
                current_soc -= actual_dis
                arbitrage_discharge_kwh += dis_power * dt_hours
                grid_import[t] = max(0, load_t - dis_power)
            else:
                grid_import[t] = load_t

            new_peak = max(new_peak, grid_import[t])

        # ==== MID PRICE - just cover load from grid ====
        else:
            grid_import[t] = load_t
            new_peak = max(new_peak, grid_import[t])

        soc[t + 1] = current_soc

    # Calculate totals
    total_load = float(np.sum(load_kw) * dt_hours)
    total_charge = float(np.sum(charge) * dt_hours)
    total_discharge = float(np.sum(discharge) * dt_hours)
    total_import = float(np.sum(grid_import) * dt_hours)

    peak_reduction = original_peak - new_peak
    peak_reduction_pct = (peak_reduction / original_peak * 100) if original_peak > 0 else 0

    # Degradation metrics
    degradation = calculate_degradation_metrics_stacked(
        total_charge=total_charge,
        total_discharge=total_discharge,
        discharge_peak=0.0 if not peak_limit_kw else total_discharge,
        discharge_pv=0.0,
        battery=battery,
        total_hours=n * dt_hours,
        peak_events_count=int(np.sum(discharge > 0)),
        peak_max_discharge_kw=float(np.max(discharge)) if np.any(discharge > 0) else 0.0,
        charge_from_pv_kwh=0.0,
        charge_from_grid_kwh=total_charge,
    )

    # Economics - time-varying prices
    baseline_energy_cost = float(np.sum(load_kw * import_prices) * dt_hours)
    project_energy_cost = float(np.sum(grid_import * import_prices) * dt_hours)

    avg_ch_price = float(np.mean(import_prices[charge > 0])) if np.any(charge > 0) else 0
    avg_dis_price = float(np.mean(import_prices[discharge > 0])) if np.any(discharge > 0) else 0

    energy_savings = baseline_energy_cost - project_energy_cost

    # Demand charge (if peak_limit set)
    demand_rate = prices.annual_demand_charge_pln_kw
    baseline_demand = original_peak * demand_rate
    project_demand = new_peak * demand_rate
    demand_savings = baseline_demand - project_demand

    annual_savings = energy_savings + demand_savings

    # Build audit info
    audit = audit_metadata or AuditMetadata(
        engine_version=ENGINE_VERSION,
        interval_minutes=int(dt_hours * 60),
    )
    info_dict = {
        "audit": audit.dict(),
        "mode": "tou_arbitrage",
        "charge_threshold_pln_kwh": charge_threshold,
        "discharge_threshold_pln_kwh": discharge_threshold,
        "peak_limit_kw": peak_limit_kw,
        "arbitrage_metrics": {
            "charge_kwh": arbitrage_charge_kwh,
            "discharge_kwh": arbitrage_discharge_kwh,
            "avg_charge_price": avg_ch_price,
            "avg_discharge_price": avg_dis_price,
            "spread_pln_kwh": avg_dis_price - avg_ch_price,
            "energy_savings_pln": energy_savings,
            "demand_savings_pln": demand_savings,
        },
    }

    result = DispatchResult(
        mode=DispatchMode.ARBITRAGE,
        battery_power_kw=battery.power_kw,
        battery_energy_kwh=battery.energy_kwh,
        interval_minutes=int(dt_hours * 60),
        n_timesteps=n,
        total_pv_kwh=0.0,
        total_load_kwh=total_load,
        total_direct_pv_kwh=0.0,
        total_charge_kwh=total_charge,
        total_discharge_kwh=total_discharge,
        total_grid_import_kwh=total_import,
        total_grid_export_kwh=0.0,
        total_curtailment_kwh=0.0,
        self_consumption_kwh=total_discharge,
        self_consumption_pct=0.0,
        grid_independence_pct=(total_discharge / total_load * 100) if total_load > 0 else 0,
        original_peak_kw=original_peak,
        new_peak_kw=new_peak,
        peak_reduction_kw=peak_reduction,
        peak_reduction_pct=peak_reduction_pct,
        degradation=degradation,
        baseline_cost_pln=baseline_energy_cost + baseline_demand,
        project_cost_pln=project_energy_cost + project_demand,
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


def run_arbitrage_with_price_bundle(
    load_kw: List[float],
    battery: BatteryParams,
    price_bundle: PriceBundle,
    config: Optional[EconomicDispatchConfig] = None,
    peak_limit_kw: Optional[float] = None,
    legacy_prices: Optional[PriceConfig] = None,
) -> DispatchResult:
    """
    Convenience wrapper to run arbitrage dispatch with PriceBundle.

    Automatically calculates thresholds from price distribution.

    Parameters:
    -----------
    load_kw : List[float]
        Load consumption power [kW] per timestep
    battery : BatteryParams
        Battery parameters
    price_bundle : PriceBundle
        Price signals from PriceEngine
    config : EconomicDispatchConfig, optional
        Arbitrage configuration (thresholds, degradation cost)
    peak_limit_kw : float, optional
        Grid import limit for hybrid mode
    legacy_prices : PriceConfig, optional
        For demand charge calculation

    Returns:
    --------
    DispatchResult with arbitrage metrics
    """
    config = config or EconomicDispatchConfig()
    legacy_prices = legacy_prices or PriceConfig()

    # Convert to numpy
    load = np.array(load_kw)
    import_prices = price_bundle.get_import_array()
    export_prices = price_bundle.get_export_array()

    # Validate lengths
    if len(load) != len(import_prices):
        raise ValueError(
            f"Load length ({len(load)}) must match price bundle length ({len(import_prices)})"
        )

    # Calculate thresholds from price distribution
    thresholds = calculate_arbitrage_thresholds(price_bundle, config)

    # Determine dt_hours from resolution
    dt_hours = price_bundle.resolution_minutes / 60.0

    # Run dispatch
    return dispatch_tou_arbitrage(
        load_kw=load,
        battery=battery,
        dt_hours=dt_hours,
        import_prices=import_prices,
        export_prices=export_prices,
        charge_threshold=thresholds["charge_threshold"],
        discharge_threshold=thresholds["discharge_threshold"],
        peak_limit_kw=peak_limit_kw,
        prices=legacy_prices,
        return_hourly=True,
    )

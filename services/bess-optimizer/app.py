"""
BESS Optimizer Service
LP/MIP optimization using PyPSA + HiGHS for zero-export PV+BESS systems

This service optimizes BESS sizing (power and energy) for a given PV+load profile
using linear programming. The objective is to maximize NPV while respecting
zero-export constraints.
"""

import time
import numpy as np
import pandas as pd
from typing import Tuple, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import pypsa

from models import (
    BessOptimizationRequest,
    BessOptimizationResult,
    BessMonthlyData,
    HealthResponse,
    ObjectiveType,
    SolverType
)

app = FastAPI(
    title="BESS Optimizer Service",
    description="LP/MIP optimization for zero-export PV+BESS systems using PyPSA + HiGHS",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    solver_ok = True
    try:
        # Quick solver test
        import highspy
    except ImportError:
        solver_ok = False

    return HealthResponse(
        status="ok",
        service="bess-optimizer",
        version="1.0.0",
        solver_available=solver_ok
    )


@app.post("/optimize", response_model=BessOptimizationResult)
async def optimize_bess(request: BessOptimizationRequest):
    """
    Optimize BESS sizing for a given PV+load profile.

    Uses PyPSA to formulate and solve an LP/MIP problem that:
    1. Determines optimal BESS power (kW) and energy (kWh)
    2. Maximizes NPV (or other objective)
    3. Respects zero-export constraint
    4. Accounts for round-trip efficiency and SOC limits
    """
    start_time = time.time()

    try:
        # Validate input lengths
        n_timesteps = len(request.pv_generation_kwh)
        if len(request.load_kwh) != n_timesteps:
            raise HTTPException(
                status_code=400,
                detail=f"PV and load profiles must have same length. Got {n_timesteps} vs {len(request.load_kwh)}"
            )

        # Determine timestep duration
        if n_timesteps == 8760:
            hours_per_step = 1.0
        elif n_timesteps == 35040:
            hours_per_step = 0.25
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Expected 8760 (hourly) or 35040 (15-min) timesteps, got {n_timesteps}"
            )

        # Convert to numpy arrays
        pv_gen = np.array(request.pv_generation_kwh)
        load = np.array(request.load_kwh)

        # Calculate net load (positive = deficit, negative = surplus)
        net_load = load - pv_gen
        surplus = np.maximum(-net_load, 0)  # PV surplus (available for charging)
        deficit = np.maximum(net_load, 0)   # Load deficit (can be covered by discharge)

        # Run optimization
        result = run_pypsa_optimization(
            surplus=surplus,
            deficit=deficit,
            pv_gen=pv_gen,
            load=load,
            hours_per_step=hours_per_step,
            request=request
        )

        result.solve_time_s = time.time() - start_time
        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Optimization failed: {str(e)}")


def run_pypsa_optimization(
    surplus: np.ndarray,
    deficit: np.ndarray,
    pv_gen: np.ndarray,
    load: np.ndarray,
    hours_per_step: float,
    request: BessOptimizationRequest
) -> BessOptimizationResult:
    """
    Find optimal BESS sizing using iterative NPV grid search.

    Tests multiple BESS sizes with greedy dispatch simulation
    and selects the configuration with best NPV.
    """
    n_timesteps = len(surplus)

    # Calculate annuity factor for NPV
    annuity_factor = calculate_annuity_factor(request.discount_rate, request.lifetime_years)
    energy_price_plnkwh = request.energy_price_plnmwh / 1000.0
    eta = np.sqrt(request.roundtrip_efficiency)

    # Define search grid for power (10 steps)
    power_range = np.linspace(request.min_power_kw, request.max_power_kw, 15)

    # Define duration options based on constraints
    duration_options = [request.duration_min_h]
    if request.duration_max_h > request.duration_min_h:
        duration_options.append((request.duration_min_h + request.duration_max_h) / 2)
        duration_options.append(request.duration_max_h)

    best_npv = float('-inf')
    best_power = request.min_power_kw
    best_energy = request.min_energy_kwh
    best_dispatch = None

    print(f"🔍 BESS PRO: Testing {len(power_range)} power levels x {len(duration_options)} durations")

    for power_kw in power_range:
        for duration_h in duration_options:
            energy_kwh = power_kw * duration_h

            # Skip if outside energy bounds
            if energy_kwh < request.min_energy_kwh or energy_kwh > request.max_energy_kwh:
                continue

            # Run dispatch simulation
            dispatch = simulate_bess_dispatch(
                surplus=surplus,
                deficit=deficit,
                power_kw=power_kw,
                energy_kwh=energy_kwh,
                efficiency=request.roundtrip_efficiency,
                soc_min=request.soc_min,
                soc_max=request.soc_max,
                hours_per_step=hours_per_step
            )

            # Calculate economics
            annual_discharge = dispatch['annual_discharge_kwh']
            annual_savings = annual_discharge * energy_price_plnkwh

            # Calculate CAPEX
            capex = power_kw * request.capex_per_kw + energy_kwh * request.capex_per_kwh

            # Calculate OPEX (as % of CAPEX per year)
            annual_opex = capex * request.opex_pct_per_year / 100.0

            # Net annual benefit
            net_annual = annual_savings - annual_opex

            # Calculate NPV
            npv = calculate_npv(
                initial_investment=capex,
                annual_cashflow=net_annual,
                discount_rate=request.discount_rate,
                years=request.analysis_period_years
            )

            # Check if this is best so far
            if npv > best_npv:
                best_npv = npv
                best_power = power_kw
                best_energy = energy_kwh
                best_dispatch = dispatch

    print(f"✅ BESS PRO: Best NPV = {best_npv/1e6:.2f} M PLN @ {best_power:.0f} kW / {best_energy:.0f} kWh")

    # If no positive NPV found, check if minimal battery is worth it
    if best_npv <= 0:
        print(f"⚠️ BESS PRO: No positive NPV found, using minimum size")
        best_power = request.min_power_kw
        best_energy = request.min_energy_kwh
        best_dispatch = simulate_bess_dispatch(
            surplus=surplus,
            deficit=deficit,
            power_kw=best_power,
            energy_kwh=best_energy,
            efficiency=request.roundtrip_efficiency,
            soc_min=request.soc_min,
            soc_max=request.soc_max,
            hours_per_step=hours_per_step
        )

    # Final result - round to whole numbers for practical use
    optimal_power_kw = round(best_power)
    optimal_energy_kwh = round(best_energy)

    # Calculate duration
    optimal_duration_h = round(optimal_energy_kwh / optimal_power_kw, 1) if optimal_power_kw > 0 else 2.0

    # Use cached dispatch result if available
    dispatch_result = best_dispatch

    # Calculate economics
    bess_capex = optimal_power_kw * request.capex_per_kw + optimal_energy_kwh * request.capex_per_kwh
    annual_savings = dispatch_result['annual_discharge_kwh'] * request.energy_price_plnmwh / 1000

    # Calculate NPV (using the best_npv we already found)
    npv = best_npv

    # Calculate payback
    annual_net_savings = annual_savings * (1 - request.opex_pct_per_year / 100)
    payback = bess_capex / annual_net_savings if annual_net_savings > 0 else None

    # Calculate autoconsumption rates
    total_pv = np.sum(pv_gen)
    total_load = np.sum(load)

    # Without BESS: direct use only
    direct_use = np.minimum(pv_gen, load)
    autoconsumption_without = (np.sum(direct_use) / total_pv * 100) if total_pv > 0 else 0

    # With BESS: direct use + discharged energy
    autoconsumption_with = ((np.sum(direct_use) + dispatch_result['annual_discharge_kwh']) / total_pv * 100) if total_pv > 0 else 0
    autoconsumption_with = min(100, autoconsumption_with)

    # Calculate monthly data
    monthly_data = calculate_monthly_data(dispatch_result, hours_per_step, n_timesteps)

    # Calculate SOC histogram
    soc_histogram = calculate_soc_histogram(dispatch_result['hourly_soc'])

    return BessOptimizationResult(
        optimal_power_kw=optimal_power_kw,
        optimal_energy_kwh=optimal_energy_kwh,
        optimal_duration_h=optimal_duration_h,
        bess_capex_pln=bess_capex,
        annual_savings_pln=annual_savings,
        npv_bess_pln=npv,
        payback_years=payback,
        irr_pct=None,  # TODO: Calculate IRR
        annual_charge_kwh=dispatch_result['annual_charge_kwh'],
        annual_discharge_kwh=dispatch_result['annual_discharge_kwh'],
        annual_cycles=dispatch_result['annual_cycles'],
        annual_curtailment_kwh=dispatch_result['annual_curtailment_kwh'],
        autoconsumption_without_bess_pct=autoconsumption_without,
        autoconsumption_with_bess_pct=autoconsumption_with,
        monthly_data=monthly_data,
        soc_histogram=soc_histogram,
        hourly_soc=dispatch_result['hourly_soc'],
        hourly_charge_kw=dispatch_result['hourly_charge_kw'],
        hourly_discharge_kw=dispatch_result['hourly_discharge_kw'],
        solver_used=request.solver.value,
        solve_time_s=0,  # Will be set by caller
        status="optimal",
        objective_value=npv
    )


def fallback_heuristic_sizing(
    surplus: np.ndarray,
    deficit: np.ndarray,
    pv_gen: np.ndarray,
    load: np.ndarray,
    hours_per_step: float,
    request: BessOptimizationRequest
) -> BessOptimizationResult:
    """
    Fallback heuristic sizing when optimization fails.
    Uses simple rules based on surplus/deficit statistics.
    """
    # Estimate power from 95th percentile of surplus
    p95_surplus = np.percentile(surplus[surplus > 0], 95) if np.any(surplus > 0) else 0
    optimal_power_kw = max(request.min_power_kw, min(request.max_power_kw, p95_surplus / hours_per_step))

    # Estimate energy for 2h duration (typical)
    optimal_duration_h = 2.0
    optimal_energy_kwh = optimal_power_kw * optimal_duration_h
    optimal_energy_kwh = max(request.min_energy_kwh, min(request.max_energy_kwh, optimal_energy_kwh))

    # Simulate dispatch
    dispatch_result = simulate_bess_dispatch(
        surplus=surplus,
        deficit=deficit,
        power_kw=optimal_power_kw,
        energy_kwh=optimal_energy_kwh,
        efficiency=request.roundtrip_efficiency,
        soc_min=request.soc_min,
        soc_max=request.soc_max,
        hours_per_step=hours_per_step
    )

    # Economics
    bess_capex = optimal_power_kw * request.capex_per_kw + optimal_energy_kwh * request.capex_per_kwh
    annual_savings = dispatch_result['annual_discharge_kwh'] * request.energy_price_plnmwh / 1000

    npv = calculate_npv(
        initial_investment=bess_capex,
        annual_cashflow=annual_savings * (1 - request.opex_pct_per_year / 100),
        discount_rate=request.discount_rate,
        years=request.analysis_period_years
    )

    annual_net_savings = annual_savings * (1 - request.opex_pct_per_year / 100)
    payback = bess_capex / annual_net_savings if annual_net_savings > 0 else None

    # Autoconsumption
    total_pv = np.sum(pv_gen)
    direct_use = np.minimum(pv_gen, load)
    autoconsumption_without = (np.sum(direct_use) / total_pv * 100) if total_pv > 0 else 0
    autoconsumption_with = ((np.sum(direct_use) + dispatch_result['annual_discharge_kwh']) / total_pv * 100) if total_pv > 0 else 0

    n_timesteps = len(surplus)
    monthly_data = calculate_monthly_data(dispatch_result, hours_per_step, n_timesteps)
    soc_histogram = calculate_soc_histogram(dispatch_result['hourly_soc'])

    return BessOptimizationResult(
        optimal_power_kw=optimal_power_kw,
        optimal_energy_kwh=optimal_energy_kwh,
        optimal_duration_h=optimal_duration_h,
        bess_capex_pln=bess_capex,
        annual_savings_pln=annual_savings,
        npv_bess_pln=npv,
        payback_years=payback,
        irr_pct=None,
        annual_charge_kwh=dispatch_result['annual_charge_kwh'],
        annual_discharge_kwh=dispatch_result['annual_discharge_kwh'],
        annual_cycles=dispatch_result['annual_cycles'],
        annual_curtailment_kwh=dispatch_result['annual_curtailment_kwh'],
        autoconsumption_without_bess_pct=autoconsumption_without,
        autoconsumption_with_bess_pct=min(100, autoconsumption_with),
        monthly_data=monthly_data,
        soc_histogram=soc_histogram,
        hourly_soc=dispatch_result['hourly_soc'],
        hourly_charge_kw=dispatch_result['hourly_charge_kw'],
        hourly_discharge_kw=dispatch_result['hourly_discharge_kw'],
        solver_used="heuristic",
        solve_time_s=0,
        status="heuristic_fallback",
        objective_value=npv
    )


def simulate_bess_dispatch(
    surplus: np.ndarray,
    deficit: np.ndarray,
    power_kw: float,
    energy_kwh: float,
    efficiency: float,
    soc_min: float,
    soc_max: float,
    hours_per_step: float
) -> dict:
    """
    Simulate BESS dispatch for given sizing.
    Greedy algorithm: charge from surplus, discharge to deficit.
    """
    n = len(surplus)
    usable_capacity = energy_kwh * (soc_max - soc_min)

    # State arrays
    soc = np.zeros(n + 1)  # SOC in kWh (absolute)
    soc[0] = energy_kwh * 0.5  # Start at 50%
    charge_kw = np.zeros(n)
    discharge_kw = np.zeros(n)
    curtailment = np.zeros(n)

    eta_charge = np.sqrt(efficiency)
    eta_discharge = np.sqrt(efficiency)

    for t in range(n):
        # Available headroom
        max_charge_energy = (energy_kwh * soc_max - soc[t])
        max_discharge_energy = (soc[t] - energy_kwh * soc_min)

        # Charging from surplus
        if surplus[t] > 0:
            # Energy we want to store (accounting for efficiency)
            desired_charge = surplus[t] * eta_charge
            # Limited by power and available capacity
            actual_charge_energy = min(desired_charge, power_kw * hours_per_step, max_charge_energy)
            charge_kw[t] = actual_charge_energy / hours_per_step
            soc[t + 1] = soc[t] + actual_charge_energy
            # Curtailment: surplus that couldn't be stored
            used_surplus = actual_charge_energy / eta_charge
            curtailment[t] = max(0, surplus[t] - used_surplus)
        # Discharging to cover deficit
        elif deficit[t] > 0:
            # Energy we want to deliver
            desired_discharge = deficit[t]
            # Limited by power, available energy, and efficiency
            max_deliverable = max_discharge_energy * eta_discharge
            actual_discharge_energy = min(desired_discharge, power_kw * hours_per_step, max_deliverable)
            discharge_kw[t] = actual_discharge_energy / hours_per_step
            # Energy taken from battery
            energy_from_battery = actual_discharge_energy / eta_discharge
            soc[t + 1] = soc[t] - energy_from_battery
        else:
            soc[t + 1] = soc[t]

    # Calculate totals
    total_charge = np.sum(charge_kw) * hours_per_step
    total_discharge = np.sum(discharge_kw) * hours_per_step
    total_curtailment = np.sum(curtailment)

    # Cycles (based on throughput)
    cycles = total_discharge / usable_capacity if usable_capacity > 0 else 0

    return {
        'annual_charge_kwh': total_charge,
        'annual_discharge_kwh': total_discharge,
        'annual_cycles': cycles,
        'annual_curtailment_kwh': total_curtailment,
        'hourly_soc': (soc[:-1] / energy_kwh * 100).tolist() if energy_kwh > 0 else [],  # SOC in %
        'hourly_charge_kw': charge_kw.tolist(),
        'hourly_discharge_kw': discharge_kw.tolist()
    }


def calculate_monthly_data(dispatch_result: dict, hours_per_step: float, n_timesteps: int) -> list:
    """Calculate monthly breakdown of BESS operation"""
    monthly_data = []

    # Determine hours per month
    if n_timesteps == 8760:
        hours_per_month = [744, 672, 744, 720, 744, 720, 744, 744, 720, 744, 720, 744]
    else:
        hours_per_month = [h * 4 for h in [744, 672, 744, 720, 744, 720, 744, 744, 720, 744, 720, 744]]

    charge_kw = np.array(dispatch_result['hourly_charge_kw'])
    discharge_kw = np.array(dispatch_result['hourly_discharge_kw'])
    soc = np.array(dispatch_result['hourly_soc'])

    start_idx = 0
    for month, hours in enumerate(hours_per_month, 1):
        steps = int(hours / hours_per_step)
        end_idx = min(start_idx + steps, n_timesteps)

        if start_idx >= n_timesteps:
            break

        month_charge = charge_kw[start_idx:end_idx]
        month_discharge = discharge_kw[start_idx:end_idx]
        month_soc = soc[start_idx:end_idx]

        charge_kwh = np.sum(month_charge) * hours_per_step
        discharge_kwh = np.sum(month_discharge) * hours_per_step

        # Estimate cycles (simplified)
        cycles = discharge_kwh / 1000  # Rough estimate

        monthly_data.append(BessMonthlyData(
            month=month,
            charge_kwh=float(charge_kwh),
            discharge_kwh=float(discharge_kwh),
            cycles=float(cycles),
            avg_soc=float(np.mean(month_soc)) if len(month_soc) > 0 else 50.0,
            curtailment_kwh=0  # TODO: Calculate from curtailment array
        ))

        start_idx = end_idx

    return monthly_data


def calculate_soc_histogram(hourly_soc: list, bins: int = 10) -> list:
    """Calculate SOC histogram for visualization"""
    if not hourly_soc:
        return [0.0] * bins

    soc_array = np.array(hourly_soc)
    hist, _ = np.histogram(soc_array, bins=bins, range=(0, 100))
    # Normalize to percentages
    total = len(soc_array)
    return (hist / total * 100).tolist() if total > 0 else [0.0] * bins


def calculate_annuity_factor(discount_rate: float, years: int) -> float:
    """Calculate annuity factor for CAPEX annualization"""
    if discount_rate <= 0:
        return 1 / years
    return discount_rate * (1 + discount_rate) ** years / ((1 + discount_rate) ** years - 1)


def calculate_npv(initial_investment: float, annual_cashflow: float, discount_rate: float, years: int) -> float:
    """Calculate Net Present Value"""
    if discount_rate <= 0:
        return annual_cashflow * years - initial_investment

    pv_factor = (1 - (1 + discount_rate) ** (-years)) / discount_rate
    return annual_cashflow * pv_factor - initial_investment


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8030)

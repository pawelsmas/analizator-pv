"""
BESS Sizing Runner
==================
Optimization of BESS size (P, E) for different duration variants.

Implements:
- Grid search over power levels for each duration (1h, 2h, 4h)
- NPV-based selection of optimal configuration
- Degradation budget checking
- S/M/L variant comparison with recommendation
"""

import numpy as np
from typing import List, Optional, Tuple, Dict, Any
from dataclasses import dataclass

from models import (
    BatteryParams,
    DispatchMode,
    DispatchResult,
    SizingRequest,
    SizingResult,
    SizingVariant,
    SizingVariantResult,
    DegradationMetrics,
    DegradationStatus,
    DegradationBudget,
    PriceConfig,
    StackedModeParams,
)
from dispatch_engine import (
    dispatch_pv_surplus,
    dispatch_peak_shaving,
    dispatch_stacked,
    check_degradation_budget,
)


def calculate_npv(
    annual_savings: float,
    capex: float,
    opex_pct: float,
    discount_rate: float,
    years: int,
) -> float:
    """
    Calculate Net Present Value.

    NPV = sum(t=1..n) [(savings - opex) / (1+r)^t] - CAPEX
    """
    annual_opex = capex * opex_pct
    npv = -capex

    for t in range(1, years + 1):
        net_cash_flow = annual_savings - annual_opex
        npv += net_cash_flow / ((1 + discount_rate) ** t)

    return npv


def calculate_simple_payback(
    annual_savings: float,
    capex: float,
) -> float:
    """Calculate simple payback period in years."""
    if annual_savings <= 0:
        return float('inf')
    return capex / annual_savings


def calculate_irr(
    annual_savings: float,
    capex: float,
    opex_pct: float,
    years: int,
    max_iterations: int = 100,
    tolerance: float = 0.0001,
) -> Optional[float]:
    """
    Calculate Internal Rate of Return using Newton-Raphson method.
    Returns None if IRR cannot be found.
    """
    if annual_savings <= 0 or capex <= 0:
        return None

    annual_opex = capex * opex_pct
    net_cf = annual_savings - annual_opex

    # Initial guess
    irr = 0.10

    for _ in range(max_iterations):
        npv = -capex
        d_npv = 0  # Derivative

        for t in range(1, years + 1):
            discount = (1 + irr) ** t
            npv += net_cf / discount
            d_npv -= t * net_cf / ((1 + irr) ** (t + 1))

        if abs(npv) < tolerance:
            return irr * 100  # Return as percentage

        if abs(d_npv) < 1e-10:
            break

        irr = irr - npv / d_npv

        if irr < -0.99:  # IRR can't be less than -100%
            return None

    return irr * 100 if abs(npv) < 1 else None


def run_sizing_for_variant(
    pv_kw: np.ndarray,
    load_kw: np.ndarray,
    dt_hours: float,
    mode: DispatchMode,
    duration_h: float,
    power_kw: float,
    request: SizingRequest,
) -> Tuple[DispatchResult, float, float]:
    """
    Run dispatch simulation for a single sizing configuration.

    Returns:
    --------
    Tuple of (dispatch_result, capex, npv)
    """
    energy_kwh = power_kw * duration_h

    battery = BatteryParams.from_roundtrip(
        power_kw=power_kw,
        energy_kwh=energy_kwh,
        roundtrip_eff=request.roundtrip_efficiency,
        soc_min=request.soc_min,
        soc_max=request.soc_max,
    )

    # Run dispatch based on mode
    if mode == DispatchMode.PV_SURPLUS:
        result = dispatch_pv_surplus(
            pv_kw, load_kw, battery, dt_hours, request.prices, return_hourly=False
        )
    elif mode == DispatchMode.PEAK_SHAVING:
        result = dispatch_peak_shaving(
            pv_kw, load_kw, battery, dt_hours,
            request.peak_limit_kw, request.prices, return_hourly=False
        )
    elif mode == DispatchMode.STACKED:
        result = dispatch_stacked(
            pv_kw, load_kw, battery, dt_hours,
            request.stacked_params, request.prices, return_hourly=False
        )
    else:
        raise ValueError(f"Unsupported mode: {mode}")

    # Check degradation budget
    if request.degradation_budget:
        result.degradation = check_degradation_budget(
            result.degradation, request.degradation_budget
        )

    # Calculate economics
    capex = energy_kwh * request.capex_per_kwh + power_kw * request.capex_per_kw
    npv = calculate_npv(
        result.annual_savings_pln,
        capex,
        request.opex_pct_per_year,
        request.discount_rate,
        request.analysis_years,
    )

    return result, capex, npv


def find_optimal_power_for_duration(
    pv_kw: np.ndarray,
    load_kw: np.ndarray,
    dt_hours: float,
    mode: DispatchMode,
    duration_h: float,
    request: SizingRequest,
) -> Tuple[float, float, DispatchResult, float]:
    """
    Find optimal power for a given duration using grid search.

    Returns:
    --------
    Tuple of (optimal_power_kw, optimal_energy_kwh, best_result, best_npv)
    """
    # Calculate surplus statistics for proper sizing
    surplus = np.maximum(pv_kw - load_kw, 0)
    daily_surplus_kwh = np.zeros(365)
    n_hours = len(pv_kw)
    hours_per_day = int(n_hours / 365) if n_hours >= 8760 else 24

    # Calculate daily surplus energy
    for day in range(min(365, n_hours // hours_per_day)):
        start_h = day * hours_per_day
        end_h = min(start_h + hours_per_day, n_hours)
        daily_surplus_kwh[day] = np.sum(surplus[start_h:end_h]) * dt_hours

    # Determine power search range based on realistic sizing criteria
    if mode == DispatchMode.PV_SURPLUS:
        # For PV surplus: size based on DAILY shiftable energy and duration
        # Use P75 of daily surplus / duration to get reasonable power
        p75_daily_surplus = np.percentile(daily_surplus_kwh[daily_surplus_kwh > 0], 75) if np.any(daily_surplus_kwh > 0) else 100
        # Power = Energy / Duration, with safety margin
        p_max_candidate = p75_daily_surplus / duration_h

        # Also consider: power should be able to charge battery in ~4-6 peak sun hours
        max_surplus_kw = np.percentile(surplus[surplus > 0], 90) if np.any(surplus > 0) else 100
        # Use the larger of the two estimates
        p_max_candidate = max(p_max_candidate, max_surplus_kw * 0.8)

    elif mode in [DispatchMode.PEAK_SHAVING, DispatchMode.STACKED]:
        # For peak shaving: use max excess over threshold
        if request.peak_limit_kw:
            net_load = load_kw - pv_kw
            excess = np.maximum(net_load - request.peak_limit_kw, 0)
            p_max_candidate = np.percentile(excess[excess > 0], 95) if np.any(excess > 0) else 100
        elif request.stacked_params:
            net_load = load_kw - pv_kw
            excess = np.maximum(net_load - request.stacked_params.peak_limit_kw, 0)
            p_max_candidate = np.percentile(excess[excess > 0], 95) if np.any(excess > 0) else 100
        else:
            p_max_candidate = np.percentile(load_kw, 95)

        # For STACKED mode, also consider PV surplus sizing
        if mode == DispatchMode.STACKED:
            pv_power_candidate = np.percentile(surplus[surplus > 0], 90) if np.any(surplus > 0) else 100
            p_max_candidate = max(p_max_candidate, pv_power_candidate * 0.8)
    else:
        p_max_candidate = 100

    # Ensure minimum sensible power based on system size
    pv_peak = np.max(pv_kw) if len(pv_kw) > 0 else 100
    min_sensible_power = pv_peak * 0.05  # At least 5% of PV peak
    p_max_candidate = max(p_max_candidate, min_sensible_power)

    # Clamp to request limits with wider search range
    p_min = max(request.min_power_kw, p_max_candidate * 0.2)
    p_max = min(request.max_power_kw, p_max_candidate * 2.0)

    # Ensure we have a valid range
    if p_min >= p_max:
        p_min = request.min_power_kw
        p_max = max(p_min * 10, request.max_power_kw, pv_peak * 0.5)

    # Generate power steps
    power_steps = np.linspace(p_min, p_max, request.power_steps)

    best_npv = float('-inf')
    best_power = power_steps[0]
    best_result = None

    for power in power_steps:
        result, capex, npv = run_sizing_for_variant(
            pv_kw, load_kw, dt_hours, mode, duration_h, power, request
        )

        # Apply degradation penalty if budget exceeded
        if result.degradation.budget_status == DegradationStatus.EXCEEDED:
            npv -= capex * 0.3  # 30% penalty for exceeded budget

        if npv > best_npv:
            best_npv = npv
            best_power = power
            best_result = result

    return best_power, best_power * duration_h, best_result, best_npv


def run_sizing(request: SizingRequest) -> SizingResult:
    """
    Run BESS sizing optimization for all duration variants.

    Process:
    1. For each duration (1h, 2h, 4h by default):
       - Grid search over power levels
       - Select power with highest NPV
    2. Compare variants and recommend best one
    3. Check degradation budgets

    Returns:
    --------
    SizingResult with all variant details and recommendation
    """
    pv_kw = np.array(request.pv_generation_kw)
    load_kw = np.array(request.load_kw)
    dt_hours = request.interval_minutes / 60.0
    n = len(pv_kw)

    # Annual totals
    total_pv_mwh = float(np.sum(pv_kw) * dt_hours / 1000)
    total_load_mwh = float(np.sum(load_kw) * dt_hours / 1000)
    surplus = np.maximum(pv_kw - load_kw, 0)
    annual_surplus_mwh = float(np.sum(surplus) * dt_hours / 1000)

    variants = []
    variant_labels = {
        1.0: (SizingVariant.SMALL, "Small (1h)"),
        2.0: (SizingVariant.MEDIUM, "Medium (2h)"),
        4.0: (SizingVariant.LARGE, "Large (4h)"),
    }

    for duration_h in request.durations_h:
        # Find optimal power for this duration
        power_kw, energy_kwh, dispatch_result, npv = find_optimal_power_for_duration(
            pv_kw, load_kw, dt_hours, request.mode, duration_h, request
        )

        # Get variant type and label
        if duration_h in variant_labels:
            variant_type, label = variant_labels[duration_h]
        else:
            variant_type = SizingVariant.CUSTOM
            label = f"Custom ({duration_h}h)"

        # Calculate economics
        capex = energy_kwh * request.capex_per_kwh + power_kw * request.capex_per_kw
        annual_opex = capex * request.opex_pct_per_year
        payback = calculate_simple_payback(dispatch_result.annual_savings_pln, capex)
        irr = calculate_irr(
            dispatch_result.annual_savings_pln, capex,
            request.opex_pct_per_year, request.analysis_years
        )

        # Calculate score (0-100) based on NPV and degradation
        base_score = min(100, max(0, (npv / capex + 0.5) * 50)) if capex > 0 else 0
        if dispatch_result.degradation.budget_status == DegradationStatus.EXCEEDED:
            base_score *= 0.5
        elif dispatch_result.degradation.budget_status == DegradationStatus.WARNING:
            base_score *= 0.8

        variant_result = SizingVariantResult(
            variant=variant_type,
            variant_label=label,
            duration_h=duration_h,
            power_kw=power_kw,
            energy_kwh=energy_kwh,
            c_rate=power_kw / energy_kwh if energy_kwh > 0 else 0,
            capex_pln=capex,
            annual_opex_pln=annual_opex,
            annual_savings_pln=dispatch_result.annual_savings_pln,
            npv_pln=npv,
            simple_payback_years=payback,
            irr_pct=irr,
            dispatch_summary=dispatch_result,
            degradation=dispatch_result.degradation,
            degradation_status=dispatch_result.degradation.budget_status,
            score=base_score,
            is_recommended=False,
        )

        variants.append(variant_result)

    # Find recommended variant (highest score)
    if variants:
        best_idx = max(range(len(variants)), key=lambda i: variants[i].score)
        variants[best_idx].is_recommended = True
        recommended = variants[best_idx]
    else:
        recommended = None

    warnings = []
    for v in variants:
        if v.degradation_status == DegradationStatus.EXCEEDED:
            warnings.append(f"{v.variant_label}: Przekroczony budżet degradacji")

    return SizingResult(
        mode=request.mode,
        total_pv_mwh=total_pv_mwh,
        total_load_mwh=total_load_mwh,
        annual_surplus_mwh=annual_surplus_mwh,
        variants=variants,
        recommended_variant=recommended.variant if recommended else None,
        recommended_power_kw=recommended.power_kw if recommended else 0,
        recommended_energy_kwh=recommended.energy_kwh if recommended else 0,
        warnings=warnings,
    )


def run_quick_sizing(
    pv_kw: np.ndarray,
    load_kw: np.ndarray,
    dt_hours: float,
    duration_h: float = 2.0,
    roundtrip_eff: float = 0.90,
    capex_per_kwh: float = 1500,
    capex_per_kw: float = 300,
    import_price_pln_mwh: float = 800,
    power_steps: int = 10,
) -> Tuple[float, float, float]:
    """
    Quick sizing for LIGHT mode (PV surplus only).

    Returns:
    --------
    Tuple of (power_kw, energy_kwh, annual_savings_pln)
    """
    prices = PriceConfig(import_price_pln_mwh=import_price_pln_mwh)

    request = SizingRequest(
        pv_generation_kw=pv_kw.tolist(),
        load_kw=load_kw.tolist(),
        interval_minutes=int(dt_hours * 60),
        mode=DispatchMode.PV_SURPLUS,
        durations_h=[duration_h],
        roundtrip_efficiency=roundtrip_eff,
        capex_per_kwh=capex_per_kwh,
        capex_per_kw=capex_per_kw,
        prices=prices,
        power_steps=power_steps,
    )

    result = run_sizing(request)

    if result.variants:
        v = result.variants[0]
        return v.power_kw, v.energy_kwh, v.annual_savings_pln

    return 0, 0, 0

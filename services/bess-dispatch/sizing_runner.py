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
    OptimizationObjective,
    OptimizationConfig,
    ConstraintType,
    SizingConstraint,
)
from dispatch_engine import (
    dispatch_pv_surplus,
    dispatch_peak_shaving,
    dispatch_stacked,
    dispatch_load_only,
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
    """Calculate simple payback period in years.
    Returns 999.0 (instead of inf) when annual_savings <= 0 for JSON compatibility.
    """
    if annual_savings <= 0:
        return 999.0  # Use large number instead of inf (JSON-compatible)
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


def calculate_objective_score(
    objective: OptimizationObjective,
    result: DispatchResult,
    capex: float,
    npv: float,
    payback: float,
    max_efc_budget: Optional[float] = None,
) -> float:
    """
    Calculate objective score based on optimization goal.

    Returns a score where HIGHER is always better (even for payback).
    """
    if objective == OptimizationObjective.NPV:
        return npv

    elif objective == OptimizationObjective.PAYBACK:
        # Invert payback so higher is better (max 100 years)
        if payback == float('inf') or payback > 100:
            return -1000000
        return -payback  # Negative because we want to minimize

    elif objective == OptimizationObjective.SELF_CONSUMPTION:
        return result.self_consumption_pct

    elif objective == OptimizationObjective.PEAK_REDUCTION:
        return result.peak_reduction_pct

    elif objective == OptimizationObjective.EFC_UTILIZATION:
        # Maximize EFC utilization within budget (higher is better up to budget)
        if max_efc_budget and max_efc_budget > 0:
            utilization = min(result.degradation.efc_total / max_efc_budget, 1.0)
            return utilization * 100  # 0-100 scale
        return result.degradation.efc_total

    return npv  # Default to NPV


def check_constraints(
    optimization: Optional[OptimizationConfig],
    capex: float,
    npv: float,
    payback: float,
    result: DispatchResult,
) -> Tuple[bool, float, List[str]]:
    """
    Check if constraints are satisfied.

    Returns:
    --------
    Tuple of (passes_hard, penalty, violations)
    - passes_hard: True if all hard constraints are satisfied
    - penalty: Penalty score for soft constraint violations (0-1)
    - violations: List of constraint violation messages
    """
    if not optimization or not optimization.constraints:
        return True, 0.0, []

    passes_hard = True
    penalty = 0.0
    violations = []

    for constraint in optimization.constraints:
        violated = False
        violation_msg = ""

        if constraint.constraint_type == ConstraintType.MAX_CAPEX:
            if capex > constraint.value:
                violated = True
                violation_msg = f"CAPEX {capex:.0f} PLN > max {constraint.value:.0f} PLN"
                penalty += (capex - constraint.value) / constraint.value

        elif constraint.constraint_type == ConstraintType.MAX_PAYBACK:
            if payback > constraint.value:
                violated = True
                violation_msg = f"Payback {payback:.1f}y > max {constraint.value:.1f}y"
                penalty += (payback - constraint.value) / constraint.value

        elif constraint.constraint_type == ConstraintType.MIN_NPV:
            if npv < constraint.value:
                violated = True
                violation_msg = f"NPV {npv:.0f} PLN < min {constraint.value:.0f} PLN"
                penalty += abs(npv - constraint.value) / max(abs(constraint.value), 1)

        elif constraint.constraint_type == ConstraintType.MAX_EFC:
            if result.degradation.efc_total > constraint.value:
                violated = True
                violation_msg = f"EFC {result.degradation.efc_total:.0f} > max {constraint.value:.0f}"
                penalty += (result.degradation.efc_total - constraint.value) / constraint.value

        elif constraint.constraint_type == ConstraintType.MIN_SELF_CONSUMPTION:
            if result.self_consumption_pct < constraint.value:
                violated = True
                violation_msg = f"Self-consumption {result.self_consumption_pct:.1f}% < min {constraint.value:.1f}%"
                penalty += (constraint.value - result.self_consumption_pct) / constraint.value

        if violated:
            violations.append(violation_msg)
            if constraint.hard:
                passes_hard = False

    return passes_hard, min(penalty, 1.0), violations


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
    elif mode == DispatchMode.LOAD_ONLY:
        # LOAD_ONLY mode: peak shaving without PV
        peak_limit = request.peak_limit_kw or (np.max(load_kw) * 0.7)
        result = dispatch_load_only(
            load_kw, battery, dt_hours, peak_limit, request.prices, return_hourly=False
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
) -> Tuple[float, float, DispatchResult, float, List[str]]:
    """
    Find optimal power for a given duration using grid search.

    Supports multi-objective optimization via request.optimization config.

    Returns:
    --------
    Tuple of (optimal_power_kw, optimal_energy_kwh, best_result, best_score, constraint_violations)
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

    elif mode == DispatchMode.LOAD_ONLY:
        # LOAD_ONLY: peak shaving without PV - analyze actual load peaks
        # Use peak_limit_kw if provided, otherwise calculate threshold from load
        # NOTE: Must match the threshold used in run_sizing_for_variant() dispatch
        if request.peak_limit_kw:
            peak_threshold = request.peak_limit_kw
        else:
            # Default: use 70% of max load (consistent with dispatch_load_only default)
            peak_threshold = np.max(load_kw) * 0.7

        # Calculate excess over threshold (this is what BESS needs to shave)
        excess = np.maximum(load_kw - peak_threshold, 0)

        if np.any(excess > 0):
            # Power: P95 of excess determines required discharge power
            p_max_candidate = np.percentile(excess[excess > 0], 95)

            # Also analyze peak events for proper sizing:
            # Find peak events (consecutive hours above threshold)
            max_single_peak_power = np.max(excess)
            max_peak_event_energy = 0.0
            current_event_energy = 0.0

            for i in range(len(excess)):
                if excess[i] > 0:
                    current_event_energy += excess[i] * dt_hours
                else:
                    if current_event_energy > max_peak_event_energy:
                        max_peak_event_energy = current_event_energy
                    current_event_energy = 0

            # Don't forget last event if it ends at array end
            if current_event_energy > max_peak_event_energy:
                max_peak_event_energy = current_event_energy

            # Ensure power is sufficient for the largest peak
            p_max_candidate = max(p_max_candidate, max_single_peak_power * 0.9)

            # Log for debugging
            import logging
            logging.info(f"LOAD_ONLY sizing: threshold={peak_threshold:.0f}kW, "
                        f"max_excess={max_single_peak_power:.0f}kW, "
                        f"max_event_energy={max_peak_event_energy:.1f}kWh, "
                        f"p_max_candidate={p_max_candidate:.0f}kW")
        else:
            # No peaks above threshold - use a percentage of max load
            p_max_candidate = np.max(load_kw) * 0.2

        # Ensure minimum sensible power for LOAD_ONLY based on load profile
        load_peak = np.max(load_kw)
        min_load_only_power = load_peak * 0.05  # At least 5% of peak load
        p_max_candidate = max(p_max_candidate, min_load_only_power)

    else:
        # Fallback for unknown modes - use load profile
        p_max_candidate = np.percentile(load_kw, 90) if len(load_kw) > 0 else 100

    # Ensure minimum sensible power based on system size
    # For LOAD_ONLY mode, use load peak instead of PV peak
    pv_peak = np.max(pv_kw) if len(pv_kw) > 0 and np.max(pv_kw) > 0 else 0
    load_peak_for_sizing = np.max(load_kw) if len(load_kw) > 0 else 100

    if mode == DispatchMode.LOAD_ONLY or pv_peak == 0:
        min_sensible_power = load_peak_for_sizing * 0.05  # At least 5% of load peak
    else:
        min_sensible_power = pv_peak * 0.05  # At least 5% of PV peak
    p_max_candidate = max(p_max_candidate, min_sensible_power)

    # Clamp to request limits with wider search range
    p_min = max(request.min_power_kw, p_max_candidate * 0.2)
    p_max = min(request.max_power_kw, p_max_candidate * 2.0)

    # Ensure we have a valid range
    reference_peak = pv_peak if pv_peak > 0 else load_peak_for_sizing
    if p_min >= p_max:
        p_min = request.min_power_kw
        p_max = max(p_min * 10, request.max_power_kw, reference_peak * 0.5)

    # Generate power steps
    power_steps = np.linspace(p_min, p_max, request.power_steps)

    # Get optimization config (use defaults if not specified)
    opt_config = request.optimization or OptimizationConfig()
    objective = opt_config.objective

    # Get EFC budget for EFC_UTILIZATION objective
    max_efc = None
    if request.degradation_budget and request.degradation_budget.max_efc_per_year:
        max_efc = request.degradation_budget.max_efc_per_year

    best_score = float('-inf')
    best_power = power_steps[0]
    best_result = None
    best_violations = []

    for power in power_steps:
        result, capex, npv = run_sizing_for_variant(
            pv_kw, load_kw, dt_hours, mode, duration_h, power, request
        )

        payback = calculate_simple_payback(result.annual_savings_pln, capex)

        # Check constraints
        passes_hard, penalty, violations = check_constraints(
            opt_config, capex, npv, payback, result
        )

        # NOTE: We no longer skip on hard constraint violations
        # Instead, we apply a severe penalty and show warnings
        # This ensures variants are always shown with their constraint status
        hard_constraint_penalty = 0.0
        if not passes_hard:
            hard_constraint_penalty = 10.0  # Severe penalty for hard violations

        # Calculate objective score
        score = calculate_objective_score(
            objective, result, capex, npv, payback, max_efc
        )

        # Apply penalty for soft constraint violations
        if penalty > 0:
            penalty_weight = opt_config.constraint_penalty_weight
            score -= abs(score) * penalty * penalty_weight

        # Apply severe penalty for hard constraint violations
        if hard_constraint_penalty > 0:
            score -= abs(score) * hard_constraint_penalty

        # Apply degradation penalty if budget exceeded (legacy behavior)
        if result.degradation.budget_status == DegradationStatus.EXCEEDED:
            score -= abs(score) * 0.3  # 30% penalty

        if score > best_score:
            best_score = score
            best_power = power
            best_result = result
            best_violations = violations

    # If no valid configuration found, return first with constraint violations noted
    if best_result is None:
        power = power_steps[0]
        result, capex, npv = run_sizing_for_variant(
            pv_kw, load_kw, dt_hours, mode, duration_h, power, request
        )
        payback = calculate_simple_payback(result.annual_savings_pln, capex)
        _, _, violations = check_constraints(opt_config, capex, npv, payback, result)
        return power, power * duration_h, result, float('-inf'), violations

    return best_power, best_power * duration_h, best_result, best_score, best_violations


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
    # Use effective_pv_kw which returns zeros for LOAD_ONLY topology
    pv_kw = np.array(request.effective_pv_kw)
    load_kw = np.array(request.load_kw)
    dt_hours = request.interval_minutes / 60.0
    n = len(load_kw)  # Use load length as reference (more reliable)

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
        power_kw, energy_kwh, dispatch_result, score, constraint_violations = find_optimal_power_for_duration(
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
        npv = calculate_npv(
            dispatch_result.annual_savings_pln, capex,
            request.opex_pct_per_year, request.discount_rate, request.analysis_years
        )
        irr = calculate_irr(
            dispatch_result.annual_savings_pln, capex,
            request.opex_pct_per_year, request.analysis_years
        )

        # Calculate score (0-100) based on objective score and degradation
        # Normalize score for comparison across variants
        base_score = min(100, max(0, (score / max(abs(capex), 1) + 0.5) * 50)) if capex > 0 else score
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

    # Add constraint violation warnings from optimization
    for v_idx, v in enumerate(variants):
        # Re-check constraints for final warnings
        capex_v = v.energy_kwh * request.capex_per_kwh + v.power_kw * request.capex_per_kw
        opt_config = request.optimization
        if opt_config and opt_config.constraints:
            for constraint in opt_config.constraints:
                violated = False
                violation_msg = ""
                hard_or_soft = "[TWARDE]" if constraint.hard else "[MIĘKKIE]"

                if constraint.constraint_type == ConstraintType.MAX_CAPEX:
                    if capex_v > constraint.value:
                        violated = True
                        violation_msg = f"CAPEX {capex_v:.0f} PLN > max {constraint.value:.0f} PLN"

                elif constraint.constraint_type == ConstraintType.MAX_PAYBACK:
                    if v.simple_payback_years > constraint.value:
                        violated = True
                        violation_msg = f"Payback {v.simple_payback_years:.1f}y > max {constraint.value:.1f}y"

                elif constraint.constraint_type == ConstraintType.MIN_NPV:
                    if v.npv_pln < constraint.value:
                        violated = True
                        violation_msg = f"NPV {v.npv_pln:.0f} PLN < min {constraint.value:.0f} PLN"

                elif constraint.constraint_type == ConstraintType.MAX_EFC:
                    efc = v.dispatch_summary.degradation.efc_total
                    if efc > constraint.value:
                        violated = True
                        violation_msg = f"EFC {efc:.0f} cykli > max {constraint.value:.0f} cykli"

                elif constraint.constraint_type == ConstraintType.MIN_SELF_CONSUMPTION:
                    sc = v.dispatch_summary.self_consumption_pct
                    if sc < constraint.value:
                        violated = True
                        violation_msg = f"Autokonsumpcja {sc:.1f}% < min {constraint.value:.1f}%"

                if violated:
                    warnings.append(f"{v.variant_label}: {hard_or_soft} {violation_msg}")

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

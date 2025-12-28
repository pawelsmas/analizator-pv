"""
Sensitivity Analysis Runner for BESS
=====================================

Performs tornado-style sensitivity analysis for a fixed BESS configuration.
Varies each parameter independently and measures impact on NPV.

Usage:
    result = run_sensitivity_analysis(request)
    # Result contains sorted parameter impacts for tornado chart
"""

import numpy as np
from typing import List, Dict, Tuple, Optional

from models import (
    SensitivityRequest,
    SensitivityResult,
    SensitivityParameter,
    SensitivityRange,
    SensitivityPoint,
    SensitivityParameterResult,
    BatteryParams,
    DispatchRequest,
    DispatchMode,
    StackedModeParams,
    PriceConfig,
)
from dispatch_engine import run_dispatch


# Parameter metadata for labels and units
PARAMETER_INFO = {
    SensitivityParameter.ENERGY_PRICE: ("Cena energii", "PLN/MWh"),
    SensitivityParameter.CAPEX_PER_KWH: ("CAPEX/kWh", "PLN/kWh"),
    SensitivityParameter.CAPEX_PER_KW: ("CAPEX/kW", "PLN/kW"),
    SensitivityParameter.DISCOUNT_RATE: ("Stopa dyskontowa", "%"),
    SensitivityParameter.ROUNDTRIP_EFFICIENCY: ("Sprawność", "%"),
    SensitivityParameter.OPEX_PCT: ("OPEX %/rok", "%"),
}


def calculate_npv(
    annual_savings: float,
    capex: float,
    opex_pct: float,
    discount_rate: float,
    years: int,
) -> float:
    """Calculate NPV using discounted cash flow"""
    annual_opex = capex * opex_pct
    annual_cf = annual_savings - annual_opex

    if discount_rate == 0:
        return annual_cf * years - capex

    pv_factor = (1 - (1 + discount_rate) ** (-years)) / discount_rate
    return annual_cf * pv_factor - capex


def calculate_payback(annual_savings: float, capex: float, opex_pct: float) -> float:
    """Calculate simple payback period"""
    annual_opex = capex * opex_pct
    net_annual = annual_savings - annual_opex
    if net_annual <= 0:
        return 999.0
    return capex / net_annual


def get_base_value(param: SensitivityParameter, request: SensitivityRequest) -> float:
    """Get base value for a parameter from request"""
    if param == SensitivityParameter.ENERGY_PRICE:
        return request.import_price_pln_mwh
    elif param == SensitivityParameter.CAPEX_PER_KWH:
        return request.capex_per_kwh
    elif param == SensitivityParameter.CAPEX_PER_KW:
        return request.capex_per_kw
    elif param == SensitivityParameter.DISCOUNT_RATE:
        return request.discount_rate * 100  # Convert to percentage
    elif param == SensitivityParameter.ROUNDTRIP_EFFICIENCY:
        return request.roundtrip_efficiency * 100  # Convert to percentage
    elif param == SensitivityParameter.OPEX_PCT:
        return request.opex_pct_per_year * 100  # Convert to percentage
    return 0.0


def run_dispatch_with_params(
    request: SensitivityRequest,
    energy_price: float,
    efficiency: float,
) -> float:
    """Run dispatch and return annual savings"""
    battery = BatteryParams.from_roundtrip(
        power_kw=request.battery_power_kw,
        energy_kwh=request.battery_energy_kwh,
        roundtrip_eff=efficiency,
        soc_min=request.soc_min,
        soc_max=request.soc_max,
        soc_initial=0.5,
    )

    # Determine effective mode and peak_limit_kw
    effective_mode = request.mode
    effective_peak_limit = request.peak_limit_kw

    # For STACKED mode, we need a valid peak_limit_kw > 0
    if effective_mode == DispatchMode.STACKED:
        if not effective_peak_limit or effective_peak_limit <= 0:
            # Calculate peak_limit from load profile (90th percentile)
            load_array = np.array(request.load_kw)
            effective_peak_limit = float(np.percentile(load_array, 90))
            if effective_peak_limit <= 0:
                # Fallback to PV_SURPLUS if no valid peak can be calculated
                effective_mode = DispatchMode.PV_SURPLUS

    stacked_params = None
    if effective_mode == DispatchMode.STACKED:
        stacked_params = StackedModeParams(
            peak_limit_kw=effective_peak_limit,
            reserve_fraction=request.reserve_fraction,
        )

    prices = PriceConfig(
        import_price_pln_mwh=energy_price,
        export_price_pln_mwh=0.0,
    )

    dispatch_request = DispatchRequest(
        pv_generation_kw=request.pv_generation_kw,
        load_kw=request.load_kw,
        interval_minutes=request.interval_minutes,
        battery=battery,
        mode=effective_mode,
        stacked_params=stacked_params,
        peak_limit_kw=effective_peak_limit,
        prices=prices,
    )

    result = run_dispatch(dispatch_request)
    return result.annual_savings_pln


def evaluate_point(
    request: SensitivityRequest,
    param: SensitivityParameter,
    deviation_pct: float,
    base_npv: float,
    base_annual_savings: float,
) -> SensitivityPoint:
    """Evaluate a single sensitivity point"""
    base_value = get_base_value(param, request)
    label, unit = PARAMETER_INFO[param]

    # Apply deviation
    if param in [SensitivityParameter.DISCOUNT_RATE,
                 SensitivityParameter.ROUNDTRIP_EFFICIENCY,
                 SensitivityParameter.OPEX_PCT]:
        # For percentages, deviation is additive (e.g., 7% + 20% = 7% * 1.2 = 8.4%)
        param_value = base_value * (1 + deviation_pct / 100)
    else:
        # For absolute values, deviation is multiplicative
        param_value = base_value * (1 + deviation_pct / 100)

    # Determine which parameters to use
    energy_price = request.import_price_pln_mwh
    efficiency = request.roundtrip_efficiency
    capex_per_kwh = request.capex_per_kwh
    capex_per_kw = request.capex_per_kw
    discount_rate = request.discount_rate
    opex_pct = request.opex_pct_per_year

    # Override the varied parameter
    if param == SensitivityParameter.ENERGY_PRICE:
        energy_price = param_value
    elif param == SensitivityParameter.CAPEX_PER_KWH:
        capex_per_kwh = param_value
    elif param == SensitivityParameter.CAPEX_PER_KW:
        capex_per_kw = param_value
    elif param == SensitivityParameter.DISCOUNT_RATE:
        discount_rate = param_value / 100  # Convert back from percentage
    elif param == SensitivityParameter.ROUNDTRIP_EFFICIENCY:
        efficiency = min(param_value / 100, 0.99)  # Convert back from percentage, cap at 99%
    elif param == SensitivityParameter.OPEX_PCT:
        opex_pct = param_value / 100  # Convert back from percentage

    # Run dispatch if efficiency or price changed (affects savings)
    if param in [SensitivityParameter.ENERGY_PRICE,
                 SensitivityParameter.ROUNDTRIP_EFFICIENCY]:
        annual_savings = run_dispatch_with_params(request, energy_price, efficiency)
    else:
        annual_savings = base_annual_savings

    # Calculate CAPEX
    capex = (request.battery_energy_kwh * capex_per_kwh +
             request.battery_power_kw * capex_per_kw)

    # Calculate NPV
    npv = calculate_npv(annual_savings, capex, opex_pct, discount_rate, request.analysis_years)
    payback = calculate_payback(annual_savings, capex, opex_pct)

    npv_delta = npv - base_npv
    npv_delta_pct = (npv_delta / abs(base_npv) * 100) if base_npv != 0 else 0

    return SensitivityPoint(
        parameter=param,
        parameter_label=label,
        deviation_pct=deviation_pct,
        parameter_value=param_value,
        npv_pln=npv,
        npv_delta_pln=npv_delta,
        npv_delta_pct=npv_delta_pct,
        payback_years=payback,
    )


def run_sensitivity_analysis(request: SensitivityRequest) -> SensitivityResult:
    """
    Run tornado-style sensitivity analysis.

    For each parameter in request.parameters:
    1. Evaluate at low deviation (e.g., -20%)
    2. Evaluate at base (0%)
    3. Evaluate at high deviation (e.g., +20%)

    Results are sorted by NPV swing for tornado chart display.
    """
    # Calculate base case
    base_capex = (request.battery_energy_kwh * request.capex_per_kwh +
                  request.battery_power_kw * request.capex_per_kw)

    base_annual_savings = run_dispatch_with_params(
        request,
        request.import_price_pln_mwh,
        request.roundtrip_efficiency,
    )

    base_npv = calculate_npv(
        base_annual_savings,
        base_capex,
        request.opex_pct_per_year,
        request.discount_rate,
        request.analysis_years,
    )

    base_payback = calculate_payback(
        base_annual_savings,
        base_capex,
        request.opex_pct_per_year,
    )

    # Analyze each parameter
    all_points: List[SensitivityPoint] = []
    param_results: List[SensitivityParameterResult] = []
    breakeven_scenarios: List[str] = []

    for param_range in request.parameters:
        param = param_range.parameter
        label, unit = PARAMETER_INFO[param]
        base_value = get_base_value(param, request)

        # Evaluate low, base, high
        low_point = evaluate_point(
            request, param, param_range.low_pct, base_npv, base_annual_savings
        )
        base_point = evaluate_point(
            request, param, 0.0, base_npv, base_annual_savings
        )
        high_point = evaluate_point(
            request, param, param_range.high_pct, base_npv, base_annual_savings
        )

        all_points.extend([low_point, base_point, high_point])

        # Calculate swing
        npv_swing = abs(high_point.npv_pln - low_point.npv_pln)
        npv_swing_pct = (npv_swing / abs(base_npv) * 100) if base_npv != 0 else 0

        # Check for breakeven crossing
        if (low_point.npv_pln * high_point.npv_pln) < 0:
            breakeven_scenarios.append(f"{label}: NPV crosses zero between {param_range.low_pct:+.0f}% and {param_range.high_pct:+.0f}%")

        param_results.append(SensitivityParameterResult(
            parameter=param,
            parameter_label=label,
            base_value=base_value,
            unit=unit,
            low_value=low_point.parameter_value,
            low_npv_pln=low_point.npv_pln,
            low_npv_delta_pct=low_point.npv_delta_pct,
            high_value=high_point.parameter_value,
            high_npv_pln=high_point.npv_pln,
            high_npv_delta_pct=high_point.npv_delta_pct,
            npv_swing_pln=npv_swing,
            npv_swing_pct=npv_swing_pct,
        ))

    # Sort by swing (descending) for tornado chart
    param_results.sort(key=lambda x: x.npv_swing_pln, reverse=True)

    most_sensitive = param_results[0].parameter_label if param_results else "N/A"
    least_sensitive = param_results[-1].parameter_label if param_results else "N/A"

    duration_h = request.battery_energy_kwh / request.battery_power_kw

    return SensitivityResult(
        battery_power_kw=request.battery_power_kw,
        battery_energy_kwh=request.battery_energy_kwh,
        duration_h=duration_h,
        base_npv_pln=base_npv,
        base_payback_years=base_payback,
        base_annual_savings_pln=base_annual_savings,
        base_capex_pln=base_capex,
        parameters=param_results,
        all_points=all_points,
        most_sensitive_parameter=most_sensitive,
        least_sensitive_parameter=least_sensitive,
        breakeven_scenarios=breakeven_scenarios,
    )

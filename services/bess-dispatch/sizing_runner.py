"""
BESS Sizing Runner
==================
Optimization of BESS size (P, E) for different duration variants.

Implements:
- Grid search over power levels for each duration (1h, 2h, 4h)
- NPV-based selection of optimal configuration
- ToU Arbitrage integration with transparent savings breakdown
- Capacity fee (opłata mocowa) post-dispatch calculation
- Degradation budget checking
- S/M/L variant comparison with recommendation

Version: 1.1.0 - Added arbitrage sizing support
"""

import logging
import numpy as np
from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Dict, Any
from dataclasses import dataclass

from models import (
    AppliedParameters,
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
    ArbitrageConfig,
    SavingsBreakdown,
    AnalyticalPeriodConfig,
    PeriodInfo,
    RecommendedReasonCode,
)
from dispatch_engine import (
    dispatch_pv_surplus,
    dispatch_peak_shaving,
    dispatch_stacked,
    dispatch_load_only,
    check_degradation_budget,
)
from common.versioning import get_version_info
from common.logging_structured import (
    log_sizing_request,
    log_sizing_response,
    record_sizing_metrics,
)
from economics_helper import (
    PricingConfig,
    CostBreakdown,
    calculate_total_energy_cost,
    calculate_savings,
    build_time_index_cet_fixed,
    build_time_index_from_period,
    get_time_index_for_request,
)

logger = logging.getLogger(__name__)


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


# =============================================================================
# Price and Capacity Fee Helpers
# =============================================================================

def get_price_bundle_for_sizing(
    request: SizingRequest,
    n_hours: int,
) -> Optional[Tuple[np.ndarray, Any]]:
    """
    Get price bundle for arbitrage-enabled sizing.

    Returns:
    --------
    Tuple of (import_prices_array, price_bundle) or None if arbitrage not enabled
    """
    arb_config = request.arbitrage_config
    if not arb_config or not arb_config.enabled:
        return None

    if not request.start_date:
        logger.warning("Arbitrage enabled but start_date not provided")
        return None

    try:
        # Import price engine components
        from price_engine import ToUPriceProvider, ToUPriceConfig, PriceBundle
        from osd_tariffs.presets.templates import ALL_PRESETS

        # Get tariff
        tariff = ALL_PRESETS.get(arb_config.tariff_id)
        if tariff is None:
            # Try searching by tariff.id
            for t in ALL_PRESETS.values():
                if t.id == arb_config.tariff_id:
                    tariff = t
                    break

        if tariff is None:
            logger.warning(f"Tariff not found: {arb_config.tariff_id}")
            return None

        # Parse start date
        start_date = datetime.strptime(request.start_date, "%Y-%m-%d").date()
        n_days = (n_hours + 23) // 24
        end_date = start_date + timedelta(days=n_days - 1)

        # Create price provider - NOTE: capacity_fee = 0 for steering!
        price_config = ToUPriceConfig(
            osd_tariff=tariff,
            capacity_fee_pln_kwh=0.0,  # NOT in steering prices
            other_components_pln_kwh=arb_config.other_components_pln_kwh,
        )
        provider = ToUPriceProvider(price_config)

        # Get prices
        dt_minutes = request.interval_minutes
        price_bundle = provider.get_series(start_date, end_date, dt_minutes)

        # Truncate or pad to match load length
        import_prices = np.array(price_bundle.import_total[:n_hours])
        if len(import_prices) < n_hours:
            # Pad with last price
            pad_value = import_prices[-1] if len(import_prices) > 0 else 0.65
            import_prices = np.pad(
                import_prices,
                (0, n_hours - len(import_prices)),
                'constant',
                constant_values=pad_value
            )

        return import_prices, price_bundle

    except Exception as e:
        logger.error(f"Failed to get price bundle: {e}")
        return None


def calculate_capacity_fee_savings(
    grid_import_before_kw: np.ndarray,
    grid_import_after_kw: np.ndarray,
    dt_hours: float,
    start_date: Optional[str] = None,
    analytical_period: Optional[AnalyticalPeriodConfig] = None,
) -> float:
    """
    Calculate capacity fee (opłata mocowa) savings from BESS.

    Args:
        grid_import_before_kw: Grid import power BEFORE BESS [kW]
        grid_import_after_kw: Grid import power AFTER BESS [kW]
        dt_hours: Timestep duration in hours
        start_date: Start date for time index (YYYY-MM-DD) - DEPRECATED, use analytical_period
        analytical_period: Time axis config (PREFERRED - uses actual start date)

    Returns:
        Annual capacity fee savings [PLN]
    """
    try:
        from capacity_fee_pl.calculator import compute_capacity_fee_savings
        from capacity_fee_pl.models import CapacityFeeConfig

        n_timesteps = len(grid_import_before_kw)
        interval_minutes = int(dt_hours * 60)

        # Use analytical_period if available (PREFERRED), otherwise fall back to start_date
        if analytical_period is not None:
            time_index = get_time_index_for_request(
                analytical_period=analytical_period,
                n_timesteps=n_timesteps,
                interval_minutes=interval_minutes,
                fallback_year=2025,
            )
            # Extract year from analytical_period for CapacityFeeConfig
            start_dt = datetime.fromisoformat(analytical_period.start_datetime)
            year = start_dt.year
        elif start_date:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            time_index = [
                start_dt + timedelta(minutes=i * interval_minutes)
                for i in range(n_timesteps)
            ]
            year = start_dt.year
        else:
            # Default to 2025-01-01 with WARNING
            logger.warning(
                "⚠️ No analytical_period or start_date provided for capacity fee calculation. "
                "Using fallback 2025-01-01. This may cause incorrect workday detection."
            )
            start_dt = datetime(2025, 1, 1, 0, 0)
            time_index = [
                start_dt + timedelta(minutes=i * interval_minutes)
                for i in range(n_timesteps)
            ]
            year = 2025

        # Convert power to energy (kWh per timestep)
        # capacity_fee expects kWh values
        grid_import_before_kwh = grid_import_before_kw * dt_hours
        grid_import_after_kwh = grid_import_after_kw * dt_hours

        config = CapacityFeeConfig(year=year)

        # Calculate savings
        savings_result = compute_capacity_fee_savings(
            grid_import_before_kwh=grid_import_before_kwh,
            grid_import_after_kwh=grid_import_after_kwh,
            time_index=time_index,
            config=config,
        )

        return savings_result.savings_pln

    except ImportError:
        logger.warning("capacity_fee_pl module not available, skipping capacity fee calculation")
        return 0.0
    except Exception as e:
        logger.error(f"Capacity fee calculation failed: {e}")
        return 0.0


def calculate_arbitrage_energy_savings(
    grid_import_before_kw: np.ndarray,
    grid_import_after_kw: np.ndarray,
    import_prices: np.ndarray,
    dt_hours: float,
) -> float:
    """
    Calculate energy savings from arbitrage (price-weighted).

    Args:
        grid_import_before_kw: Grid import power BEFORE BESS [kW]
        grid_import_after_kw: Grid import power AFTER BESS [kW]
        import_prices: Import prices per timestep [PLN/kWh]
        dt_hours: Timestep duration in hours

    Returns:
        Annual energy savings [PLN] (positive = savings)
    """
    # Calculate energy per timestep [kWh]
    import_before_kwh = grid_import_before_kw * dt_hours
    import_after_kwh = grid_import_after_kw * dt_hours

    # Price-weighted cost
    cost_before = float(np.sum(import_before_kwh * import_prices))
    cost_after = float(np.sum(import_after_kwh * import_prices))

    return cost_before - cost_after


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


@dataclass
class StructuredReasonInfo:
    """Structured info about recommendation reason for machine consumption."""
    code: str  # RecommendedReasonCode value
    metric: str  # Metric name (npv_pln, payback_years, etc.)
    value: float  # Metric value
    unit: str  # Unit string (PLN, years, %, cycles)


def get_structured_reason_info(
    recommended: "SizingVariantResult",
    objective: OptimizationObjective,
) -> StructuredReasonInfo:
    """
    Get structured machine-readable info about recommendation reason.

    Args:
        recommended: The recommended variant
        objective: The optimization objective used

    Returns:
        StructuredReasonInfo with code, metric, value, unit
    """
    if objective == OptimizationObjective.NPV:
        return StructuredReasonInfo(
            code=RecommendedReasonCode.NPV_MAX.value,
            metric="npv_pln",
            value=recommended.npv_pln,
            unit="PLN",
        )
    elif objective == OptimizationObjective.PAYBACK:
        return StructuredReasonInfo(
            code=RecommendedReasonCode.PAYBACK_MIN.value,
            metric="payback_years",
            value=recommended.simple_payback_years,
            unit="years",
        )
    elif objective == OptimizationObjective.SELF_CONSUMPTION:
        sc_pct = recommended.dispatch_summary.self_consumption_pct
        return StructuredReasonInfo(
            code=RecommendedReasonCode.SELF_CONSUMPTION_MAX.value,
            metric="self_consumption_pct",
            value=sc_pct,
            unit="%",
        )
    elif objective == OptimizationObjective.PEAK_REDUCTION:
        pr_pct = recommended.dispatch_summary.peak_reduction_pct
        return StructuredReasonInfo(
            code=RecommendedReasonCode.PEAK_REDUCTION_MAX.value,
            metric="peak_reduction_pct",
            value=pr_pct,
            unit="%",
        )
    elif objective == OptimizationObjective.EFC_UTILIZATION:
        efc = recommended.dispatch_summary.degradation.efc_total
        return StructuredReasonInfo(
            code=RecommendedReasonCode.EFC_UTILIZATION_MAX.value,
            metric="efc_total",
            value=efc,
            unit="cycles",
        )
    else:
        # Default fallback
        return StructuredReasonInfo(
            code=RecommendedReasonCode.NPV_MAX.value,
            metric="npv_pln",
            value=recommended.npv_pln,
            unit="PLN",
        )


def generate_recommended_reason(
    recommended: "SizingVariantResult",
    all_variants: list,
    objective: OptimizationObjective,
    constraints: Optional[list] = None,
) -> str:
    """
    Generate human-readable explanation for why a variant was recommended.

    Args:
        recommended: The recommended variant
        all_variants: List of all variants
        objective: The optimization objective used
        constraints: Optional list of constraints applied

    Returns:
        Human-readable explanation string
    """
    # Format numbers for Polish locale
    def fmt_pln(value: float) -> str:
        """Format PLN value with thousand separators."""
        return f"{value:,.0f}".replace(",", " ")

    # Base explanation depends on objective
    if objective == OptimizationObjective.NPV:
        reason = f"Najwyższe NPV ({fmt_pln(recommended.npv_pln)} PLN)"
    elif objective == OptimizationObjective.PAYBACK:
        reason = f"Najkrótszy okres zwrotu ({recommended.simple_payback_years:.1f} lat)"
    elif objective == OptimizationObjective.SELF_CONSUMPTION:
        sc_pct = recommended.dispatch_summary.self_consumption_pct
        reason = f"Najwyższa autokonsumpcja ({sc_pct:.1f}%)"
    elif objective == OptimizationObjective.PEAK_REDUCTION:
        pr_pct = recommended.dispatch_summary.peak_reduction_pct
        reason = f"Najwyższa redukcja szczytów ({pr_pct:.1f}%)"
    elif objective == OptimizationObjective.EFC_UTILIZATION:
        efc = recommended.dispatch_summary.degradation.efc_total
        reason = f"Optymalne wykorzystanie cykli ({efc:.0f} EFC)"
    else:
        reason = f"Najwyższy score ({recommended.score:.0f})"

    # Add context about other variants
    other_variants = [v for v in all_variants if v.variant != recommended.variant]
    if other_variants:
        # Show comparison
        if objective == OptimizationObjective.NPV:
            others_npv = [v.npv_pln for v in other_variants]
            max_other = max(others_npv) if others_npv else 0
            if recommended.npv_pln > max_other > 0:
                delta = recommended.npv_pln - max_other
                reason += f", o {fmt_pln(delta)} PLN więcej niż kolejny wariant"
        elif objective == OptimizationObjective.PAYBACK:
            others_payback = [v.simple_payback_years for v in other_variants if v.simple_payback_years < 100]
            min_other = min(others_payback) if others_payback else 999
            if recommended.simple_payback_years < min_other < 100:
                delta = min_other - recommended.simple_payback_years
                reason += f", o {delta:.1f} lat krótszy niż kolejny wariant"

    # Add constraint info if applicable
    if constraints:
        active_constraints = [c for c in constraints if c.hard]
        if active_constraints:
            constraint_names = []
            for c in active_constraints:
                if c.constraint_type == ConstraintType.MAX_CAPEX:
                    constraint_names.append(f"CAPEX ≤ {fmt_pln(c.value)} PLN")
                elif c.constraint_type == ConstraintType.MAX_PAYBACK:
                    constraint_names.append(f"payback ≤ {c.value:.0f} lat")
                elif c.constraint_type == ConstraintType.MIN_NPV:
                    constraint_names.append(f"NPV ≥ {fmt_pln(c.value)} PLN")
            if constraint_names:
                reason += f" (przy ograniczeniach: {', '.join(constraint_names)})"

    return reason


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
    import_prices: Optional[np.ndarray] = None,
) -> Tuple[DispatchResult, float, float, Optional[SavingsBreakdown]]:
    """
    Run dispatch simulation for a single sizing configuration.

    Enhanced to support:
    - ToU arbitrage with price-weighted energy savings
    - Capacity fee post-dispatch calculation
    - Transparent savings breakdown

    Returns:
    --------
    Tuple of (dispatch_result, capex, npv, savings_breakdown)
    """
    energy_kwh = power_kw * duration_h
    n_timesteps = len(load_kw)

    battery = BatteryParams.from_roundtrip(
        power_kw=power_kw,
        energy_kwh=energy_kwh,
        roundtrip_eff=request.roundtrip_efficiency,
        soc_min=request.soc_min,
        soc_max=request.soc_max,
    )

    # Check if arbitrage is enabled
    arb_enabled = (
        request.arbitrage_config is not None and
        request.arbitrage_config.enabled and
        import_prices is not None
    )

    # Run dispatch based on mode
    # Pass include_energy_flows_timeseries from request to dispatch functions
    include_timeseries = request.include_energy_flows_timeseries

    if mode == DispatchMode.PV_SURPLUS:
        result = dispatch_pv_surplus(
            pv_kw, load_kw, battery, dt_hours, request.prices, return_hourly=True,
            include_energy_flows_timeseries=include_timeseries,
        )
    elif mode == DispatchMode.PEAK_SHAVING:
        result = dispatch_peak_shaving(
            pv_kw, load_kw, battery, dt_hours,
            request.peak_limit_kw, request.prices, return_hourly=True,
            include_energy_flows_timeseries=include_timeseries,
        )
    elif mode == DispatchMode.STACKED:
        # Pass arbitrage parameters to dispatch_stacked
        result = dispatch_stacked(
            pv_kw, load_kw, battery, dt_hours,
            request.stacked_params, request.prices, return_hourly=True,
            import_prices=import_prices if arb_enabled else None,
            arb_config=request.arbitrage_config if arb_enabled else None,
            include_energy_flows_timeseries=include_timeseries,
        )
    elif mode == DispatchMode.LOAD_ONLY:
        # LOAD_ONLY mode: peak shaving without PV
        peak_limit = request.peak_limit_kw or (np.max(load_kw) * 0.7)
        result = dispatch_load_only(
            load_kw, battery, dt_hours, peak_limit, request.prices, return_hourly=True,
            include_energy_flows_timeseries=include_timeseries,
        )
    else:
        raise ValueError(f"Unsupported mode: {mode}")

    # Check degradation budget
    if request.degradation_budget:
        result.degradation = check_degradation_budget(
            result.degradation, request.degradation_budget
        )

    # ==========================================================================
    # Calculate Savings Breakdown (transparent NPV components)
    # ==========================================================================

    savings_breakdown = SavingsBreakdown()

    # Baseline grid import/export (no BESS)
    # For modes with PV: net_load = load - pv, clipped to >= 0
    # For LOAD_ONLY: net_load = load, no export
    if mode == DispatchMode.LOAD_ONLY:
        baseline_grid_import_kw = load_kw.copy()
        baseline_grid_export_kw = np.zeros_like(load_kw)
    else:
        baseline_grid_import_kw = np.maximum(load_kw - pv_kw, 0)
        baseline_grid_export_kw = np.maximum(pv_kw - load_kw, 0)  # PV surplus

    # Get actual grid import from dispatch result
    if result.hourly_grid_import_kw is not None:
        actual_grid_import_kw = np.array(result.hourly_grid_import_kw)
    else:
        # Fallback: estimate from totals (less accurate)
        actual_grid_import_kw = np.full(n_timesteps, result.total_grid_import_kwh / (n_timesteps * dt_hours))

    # =========================================================================
    # NEW: Use economics_helper for ToU pricing (Opcja B)
    # =========================================================================
    if request.prices.is_tou_enabled:
        # Convert PriceConfig -> PricingConfig for economics_helper
        pricing_config = PricingConfig(
            tariff_id=request.prices.tariff_id,
            flat_import_pln_mwh=request.prices.import_price_pln_mwh,
            flat_export_pln_mwh=request.prices.export_price_pln_mwh,
            other_fees_pln_mwh=request.prices.other_fees_pln_mwh,
            capacity_fee_method=request.prices.capacity_fee_method,
            capacity_fee_som_pln_kwh=request.prices.capacity_fee_som_pln_kwh,
            capacity_fee_fixed_pln_mwh=request.prices.capacity_fee_fixed_pln_mwh,
            analysis_year=request.prices.analysis_year,
            export_policy="zero_export",  # Same policy for baseline and project
        )

        # Calculate full cost breakdown for baseline and project
        interval_minutes = int(dt_hours * 60)
        savings_result = calculate_savings(
            baseline_grid_import_kw,
            actual_grid_import_kw,
            pricing_config,
            interval_minutes,
            analytical_period=request.analytical_period,  # Use period from request
        )

        # Extract savings breakdown
        savings_breakdown.energy_savings_pln = (
            savings_result['savings']['tou_savings_pln'] +
            savings_result['savings']['other_savings_pln']
        )
        savings_breakdown.capacity_fee_savings_pln = savings_result['savings']['capacity_fee_savings_pln']

        # Store detailed cost breakdown in result for UI
        result.prices_summary = {
            'baseline': savings_result['baseline'],
            'project': savings_result['project'],
            'savings': savings_result['savings'],
            'config': savings_result['config'],
        }

        logger.info(
            f"ToU pricing: baseline={savings_result['baseline']['total_cost_pln']:.0f} PLN, "
            f"project={savings_result['project']['total_cost_pln']:.0f} PLN, "
            f"savings={savings_result['savings']['total_savings_pln']:.0f} PLN"
        )

    # =========================================================================
    # Legacy path: Flat pricing or arbitrage-specific calculations
    # =========================================================================
    elif arb_enabled and import_prices is not None:
        # Calculate total ToU savings (price-weighted)
        tou_total_savings = calculate_arbitrage_energy_savings(
            baseline_grid_import_kw,
            actual_grid_import_kw,
            import_prices,
            dt_hours
        )

        # Calculate flat-price savings (volume-based, no ToU benefit)
        flat_price = request.prices.import_price_pln_mwh / 1000.0  # PLN/kWh
        import_reduction_kwh = (np.sum(baseline_grid_import_kw) - np.sum(actual_grid_import_kw)) * dt_hours
        flat_savings = import_reduction_kwh * flat_price

        # Split into components to avoid double counting in calculate_net():
        # - energy_savings_pln: base savings at flat price (from reduced consumption)
        # - arbitrage_savings_pln: ADDITIONAL savings from ToU price spread
        # Total = energy_savings + arbitrage_savings = tou_total_savings
        savings_breakdown.energy_savings_pln = flat_savings
        savings_breakdown.arbitrage_savings_pln = max(0.0, tou_total_savings - flat_savings)

        # Capacity fee savings for arbitrage mode
        savings_breakdown.capacity_fee_savings_pln = calculate_capacity_fee_savings(
            baseline_grid_import_kw,
            actual_grid_import_kw,
            dt_hours,
            start_date=request.start_date,
            analytical_period=request.analytical_period,  # Use period from request
        )
    else:
        # Flat pricing - simple calculation
        flat_price = request.prices.import_price_pln_mwh / 1000.0  # PLN/kWh
        import_reduction_kwh = (np.sum(baseline_grid_import_kw) - np.sum(actual_grid_import_kw)) * dt_hours
        savings_breakdown.energy_savings_pln = import_reduction_kwh * flat_price

        # Capacity fee savings for non-arbitrage modes with peak shaving
        if mode in [DispatchMode.STACKED, DispatchMode.PEAK_SHAVING, DispatchMode.LOAD_ONLY]:
            savings_breakdown.capacity_fee_savings_pln = calculate_capacity_fee_savings(
                baseline_grid_import_kw,
                actual_grid_import_kw,
                dt_hours,
                start_date=request.start_date,
                analytical_period=request.analytical_period,  # Use period from request
            )

    # 3. Demand charge savings (from peak reduction) - applies to all modes
    if result.peak_reduction_kw > 0 and request.prices.annual_demand_charge_pln_kw > 0:
        savings_breakdown.demand_charge_savings_pln = (
            result.peak_reduction_kw * request.prices.annual_demand_charge_pln_kw
        )

    # 4. Export revenue breakdown (baseline vs project)
    # Baseline: PV surplus without battery (all excess goes to grid)
    # Project: With battery (some PV is stored, so less export)
    export_price_pln_kwh = request.prices.export_price_pln_mwh / 1000.0 if request.prices.export_price_pln_mwh > 0 else 0.0

    # Calculate baseline export (no battery) - in kWh
    baseline_export_kwh = np.sum(baseline_grid_export_kw) * dt_hours
    savings_breakdown.baseline_export_revenue_pln = baseline_export_kwh * export_price_pln_kwh

    # Calculate project export (with battery) - in kWh
    project_export_kwh = result.total_grid_export_kwh
    savings_breakdown.project_export_revenue_pln = project_export_kwh * export_price_pln_kwh

    # Export revenue change = project - baseline (typically NEGATIVE because battery uses PV)
    savings_breakdown.export_revenue_savings_pln = (
        savings_breakdown.project_export_revenue_pln - savings_breakdown.baseline_export_revenue_pln
    )

    # Legacy field for backward compatibility
    savings_breakdown.export_revenue_pln = savings_breakdown.project_export_revenue_pln

    # 5. Battery throughput and degradation cost
    # Always set battery_throughput_mwh (SSoT for throughput)
    throughput_mwh = result.degradation.throughput_total_mwh if result.degradation else 0.0
    savings_breakdown.battery_throughput_mwh = throughput_mwh

    # Calculate degradation cost using general degradation_cost_pln_mwh parameter
    # (applies to all modes, not just arbitrage)
    if throughput_mwh > 0 and request.degradation_cost_pln_mwh > 0:
        savings_breakdown.degradation_cost_pln = throughput_mwh * request.degradation_cost_pln_mwh
    # Legacy: also check arbitrage config for backward compatibility
    elif arb_enabled and request.arbitrage_config.degradation_cost_pln_kwh > 0:
        total_throughput_kwh = throughput_mwh * 1000
        savings_breakdown.degradation_cost_pln = (
            total_throughput_kwh * request.arbitrage_config.degradation_cost_pln_kwh
        )

    # Calculate net savings
    savings_breakdown.net_savings_pln = savings_breakdown.calculate_net()

    # Always attach savings_breakdown to result for transparency
    result.savings_breakdown = savings_breakdown

    # SSoT: annual_savings_pln ALWAYS equals savings_breakdown.net_savings_pln
    # This ensures consistency between frontend display (uses annual_savings_pln)
    # and economics calculations (uses savings_breakdown components)
    result.annual_savings_pln = savings_breakdown.net_savings_pln

    # ==========================================================================
    # Calculate Economics (CAPEX, NPV)
    # ==========================================================================

    capex = energy_kwh * request.capex_per_kwh + power_kw * request.capex_per_kw
    npv = calculate_npv(
        result.annual_savings_pln,
        capex,
        request.opex_pct_per_year,
        request.discount_rate,
        request.analysis_years,
    )

    # Remove hourly arrays to save memory (we only needed them for calculations)
    result.hourly_charge_kw = None
    result.hourly_discharge_kw = None
    result.hourly_soc_pct = None
    result.hourly_grid_import_kw = None
    result.hourly_grid_export_kw = None

    return result, capex, npv, savings_breakdown


def find_optimal_power_for_duration(
    pv_kw: np.ndarray,
    load_kw: np.ndarray,
    dt_hours: float,
    mode: DispatchMode,
    duration_h: float,
    request: SizingRequest,
    import_prices: Optional[np.ndarray] = None,
) -> Tuple[float, float, DispatchResult, float, List[str]]:
    """
    Find optimal power for a given duration using grid search.

    Supports multi-objective optimization via request.optimization config.
    When import_prices is provided, uses price-weighted energy savings.

    Returns:
    --------
    Tuple of (optimal_power_kw, optimal_energy_kwh, best_result, best_score, constraint_violations)
    """
    # Calculate surplus statistics for proper sizing
    surplus = np.maximum(pv_kw - load_kw, 0)
    n_timesteps = len(pv_kw)

    # Calculate actual period length from data or analytical_period
    # DO NOT assume 365 days - use actual data length!
    if request.analytical_period is not None:
        period_days = int(np.ceil(request.analytical_period.period_days))
        timesteps_per_day = int(24 * 60 / request.analytical_period.interval_minutes)
    else:
        # Fallback: calculate from data assuming interval_minutes
        timesteps_per_day = int(24 * 60 / request.interval_minutes)
        period_days = int(np.ceil(n_timesteps / timesteps_per_day))

    # Allocate daily surplus array for ACTUAL period, not hardcoded 365
    daily_surplus_kwh = np.zeros(period_days)

    # Calculate daily surplus energy using groupby-like logic
    for day in range(period_days):
        start_idx = day * timesteps_per_day
        end_idx = min(start_idx + timesteps_per_day, n_timesteps)
        if start_idx < n_timesteps:
            daily_surplus_kwh[day] = np.sum(surplus[start_idx:end_idx]) * dt_hours

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
        # DEBUG: Log sizing algorithm inputs
        logger.info(f"🔍 SIZING DEBUG for mode={mode.value}:")
        logger.info(f"   PV: max={np.max(pv_kw):.0f}kW, mean={np.mean(pv_kw):.0f}kW, sum={np.sum(pv_kw)*dt_hours/1000:.0f}MWh/y")
        logger.info(f"   Load: max={np.max(load_kw):.0f}kW, mean={np.mean(load_kw):.0f}kW, sum={np.sum(load_kw)*dt_hours/1000:.0f}MWh/y")
        logger.info(f"   Surplus (PV-Load): max={np.max(surplus):.0f}kW, hours>0={np.sum(surplus>0)}, P90={np.percentile(surplus[surplus>0], 90) if np.any(surplus>0) else 0:.0f}kW")
        logger.info(f"   peak_limit_kw={request.peak_limit_kw}, stacked_params={request.stacked_params}")

        if request.peak_limit_kw:
            net_load = load_kw - pv_kw
            excess = np.maximum(net_load - request.peak_limit_kw, 0)
            p_max_candidate = np.percentile(excess[excess > 0], 95) if np.any(excess > 0) else 100
            logger.info(f"   net_load (load-pv): min={np.min(net_load):.0f}kW, max={np.max(net_load):.0f}kW")
            logger.info(f"   excess (net_load - peak_limit): hours>0={np.sum(excess>0)}, P95={p_max_candidate:.0f}kW")
        elif request.stacked_params:
            net_load = load_kw - pv_kw
            excess = np.maximum(net_load - request.stacked_params.peak_limit_kw, 0)
            p_max_candidate = np.percentile(excess[excess > 0], 95) if np.any(excess > 0) else 100
            logger.info(f"   net_load (load-pv): min={np.min(net_load):.0f}kW, max={np.max(net_load):.0f}kW")
            logger.info(f"   excess (net_load - stacked.peak_limit): hours>0={np.sum(excess>0)}, P95={p_max_candidate:.0f}kW")
        else:
            p_max_candidate = np.percentile(load_kw, 95)
            logger.info(f"   NO peak_limit set - using P95 load: {p_max_candidate:.0f}kW")

        # For STACKED mode, also consider PV surplus sizing
        # This is CRITICAL for large PV installations where net_load is often negative
        if mode == DispatchMode.STACKED:
            # Method 1: Power-based - P90 of instantaneous surplus
            pv_power_candidate = np.percentile(surplus[surplus > 0], 90) if np.any(surplus > 0) else 100

            # Method 2: Energy-based - size battery to store daily surplus
            # Use P75 of daily surplus / duration to get energy capacity, then power
            daily_surplus_nonzero = daily_surplus_kwh[daily_surplus_kwh > 0]
            if len(daily_surplus_nonzero) > 0:
                p75_daily_surplus_kwh = np.percentile(daily_surplus_nonzero, 75)
                pv_energy_power_candidate = p75_daily_surplus_kwh / duration_h
                logger.info(f"   STACKED PV surplus: P75_daily_surplus={p75_daily_surplus_kwh:.0f}kWh -> power={pv_energy_power_candidate:.0f}kW (for {duration_h}h)")
            else:
                pv_energy_power_candidate = 100

            # Use the MAXIMUM of all estimates - BESS should be sized for largest requirement
            old_p_max = p_max_candidate
            p_max_candidate = max(
                p_max_candidate,           # Peak shaving requirement
                pv_power_candidate,        # P90 of PV surplus power (NO 0.8 reduction!)
                pv_energy_power_candidate  # Energy-based sizing
            )

            logger.info(f"   STACKED correction:")
            logger.info(f"      peak_shaving_power: {old_p_max:.0f}kW")
            logger.info(f"      pv_power_P90: {pv_power_candidate:.0f}kW")
            logger.info(f"      pv_energy_power: {pv_energy_power_candidate:.0f}kW")
            logger.info(f"      FINAL p_max_candidate: {p_max_candidate:.0f}kW")

        logger.info(f"   FINAL p_max_candidate={p_max_candidate:.0f}kW for duration={duration_h}h -> energy={p_max_candidate*duration_h:.0f}kWh")

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

    # DEBUG: Log final search range
    logger.info(f"🔍 POWER SEARCH RANGE: p_min={p_min:.0f}kW, p_max={p_max:.0f}kW, steps={request.power_steps}")
    logger.info(f"   request.min_power_kw={request.min_power_kw}, request.max_power_kw={request.max_power_kw}")

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
        result, capex, npv, _ = run_sizing_for_variant(
            pv_kw, load_kw, dt_hours, mode, duration_h, power, request,
            import_prices=import_prices
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
        result, capex, npv, _ = run_sizing_for_variant(
            pv_kw, load_kw, dt_hours, mode, duration_h, power, request,
            import_prices=import_prices
        )
        payback = calculate_simple_payback(result.annual_savings_pln, capex)
        _, _, violations = check_constraints(opt_config, capex, npv, payback, result)
        return power, power * duration_h, result, float('-inf'), violations

    return best_power, best_power * duration_h, best_result, best_score, best_violations


def run_sizing(request: SizingRequest) -> SizingResult:
    """
    Run BESS sizing optimization for all duration variants.

    Process:
    1. Fetch price bundle if arbitrage enabled
    2. For each duration (1h, 2h, 4h by default):
       - Grid search over power levels
       - Select power with highest NPV (including arbitrage savings)
    3. Compare variants and recommend best one
    4. Check degradation budgets

    Returns:
    --------
    SizingResult with all variant details and recommendation
    """
    import time
    start_time = time.time()

    # Use effective_pv_kw which returns zeros for LOAD_ONLY topology
    pv_kw = np.array(request.effective_pv_kw)
    load_kw = np.array(request.load_kw)
    dt_hours = request.interval_minutes / 60.0
    n = len(load_kw)  # Use load length as reference (more reliable)

    # Determine arbitrage enabled
    arbitrage_enabled = bool(
        request.arbitrage_config and request.arbitrage_config.enabled
    )
    objective = "npv"
    if request.optimization:
        objective = request.optimization.objective.value

    # Structured log: sizing request
    log_sizing_request(
        mode=request.mode.value,
        period_hours=n * dt_hours,
        arbitrage_enabled=arbitrage_enabled,
        objective=objective,
        extra={
            "load_points": n,
            "durations": request.durations_h,
        },
    )

    # =========================================================================
    # Fetch price bundle if arbitrage enabled
    # =========================================================================
    import_prices = None
    if request.arbitrage_config and request.arbitrage_config.enabled:
        price_result = get_price_bundle_for_sizing(request, n)
        if price_result is not None:
            import_prices, _ = price_result
            logger.info(f"Arbitrage sizing enabled with tariff: {request.arbitrage_config.tariff_id}")
        else:
            logger.warning("Failed to get price bundle, proceeding without arbitrage")

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
            pv_kw, load_kw, dt_hours, request.mode, duration_h, request,
            import_prices=import_prices
        )

        # =========================================================================
        # EOL (End-of-Life) Degradation Adjustment
        # =========================================================================
        # If eol_capacity_factor is set (e.g., 0.70), size battery larger so that
        # at end of life (after analysis_years) it still has target capacity.
        #
        # Formula: BOL_capacity = EOL_target_capacity / predicted_eol_factor
        # where predicted_eol_factor = (1 - annual_degradation)^years
        #
        # Example: If we need 800 kWh at EOL, and at 15 years with 2%/year degradation
        # we'll have 0.98^15 = 0.74 of BOL capacity, we need BOL = 800 / 0.74 = 1081 kWh
        eol_adjusted_energy_kwh = energy_kwh
        eol_adjusted_power_kw = power_kw

        if request.eol_capacity_factor > 0:
            # Calculate predicted EOL factor based on annual degradation
            years = request.analysis_years
            annual_deg = request.annual_degradation_pct / 100.0
            predicted_eol_factor = (1 - annual_deg) ** years

            # If we want X at EOL, and predicted EOL factor is Y, we need X/Y at BOL
            # But only if predicted EOL < target EOL (meaning we'd lose more than target allows)
            if predicted_eol_factor < request.eol_capacity_factor:
                # Size up battery so EOL capacity meets target
                oversizing_factor = request.eol_capacity_factor / predicted_eol_factor
                eol_adjusted_energy_kwh = energy_kwh * oversizing_factor
                eol_adjusted_power_kw = power_kw * oversizing_factor

                logger.info(f"   📈 EOL Sizing Adjustment for duration={duration_h}h:")
                logger.info(f"      Predicted EOL factor: {predicted_eol_factor:.2%} (after {years}y at {request.annual_degradation_pct}%/y)")
                logger.info(f"      Target EOL factor: {request.eol_capacity_factor:.2%}")
                logger.info(f"      Oversizing factor: {oversizing_factor:.2f}x")
                logger.info(f"      Energy: {energy_kwh:.0f} kWh -> {eol_adjusted_energy_kwh:.0f} kWh")
                logger.info(f"      Power: {power_kw:.0f} kW -> {eol_adjusted_power_kw:.0f} kW")

        # Get variant type and label
        if duration_h in variant_labels:
            variant_type, label = variant_labels[duration_h]
        else:
            variant_type = SizingVariant.CUSTOM
            label = f"Custom ({duration_h}h)"

        # Calculate economics (use EOL-adjusted values for CAPEX)
        capex = eol_adjusted_energy_kwh * request.capex_per_kwh + eol_adjusted_power_kw * request.capex_per_kw
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

        # Recalculate objective score using final NPV (after EOL adjustment)
        # This ensures score reflects the actual economics of the sized variant
        opt_config = request.optimization
        objective = opt_config.objective if opt_config else OptimizationObjective.NPV
        # Get max_efc from degradation_budget, not from optimization config
        max_efc = None
        if request.degradation_budget and request.degradation_budget.max_efc_per_year:
            max_efc = request.degradation_budget.max_efc_per_year
        objective_score = calculate_objective_score(
            objective, dispatch_result, capex, npv, payback, max_efc
        )

        variant_result = SizingVariantResult(
            variant=variant_type,
            variant_label=label,
            duration_h=duration_h,
            # Use EOL-adjusted values for final sizing recommendation
            power_kw=eol_adjusted_power_kw,
            energy_kwh=eol_adjusted_energy_kwh,
            c_rate=eol_adjusted_power_kw / eol_adjusted_energy_kwh if eol_adjusted_energy_kwh > 0 else 0,
            capex_pln=capex,
            annual_opex_pln=annual_opex,
            annual_savings_pln=dispatch_result.annual_savings_pln,
            npv_pln=npv,
            simple_payback_years=payback,
            irr_pct=irr,
            dispatch_summary=dispatch_result,
            degradation=dispatch_result.degradation,
            degradation_status=dispatch_result.degradation.budget_status,
            score=objective_score,
            is_recommended=False,
        )

        variants.append(variant_result)

    # Determine objective used (v0.4)
    opt_config = request.optimization
    objective = opt_config.objective if opt_config else OptimizationObjective.NPV
    objective_used = objective.value  # Convert enum to string

    # Find recommended variant (highest score)
    recommended_reason = None
    structured_reason = None
    if variants:
        best_idx = max(range(len(variants)), key=lambda i: variants[i].score)
        variants[best_idx].is_recommended = True
        recommended = variants[best_idx]

        # Generate human-readable explanation (v0.4)
        try:
            constraints = opt_config.constraints if opt_config else None
            recommended_reason = generate_recommended_reason(
                recommended, variants, objective, constraints
            )
        except Exception as e:
            logger.error(f"Failed to generate recommended_reason: {e}")
            # Fallback to simple reason
            recommended_reason = f"Najwyższy score ({recommended.score:.0f})"

        # Generate structured reason info (v0.4.1)
        try:
            structured_reason = get_structured_reason_info(recommended, objective)
        except Exception as e:
            logger.error(f"Failed to generate structured_reason: {e}")
            structured_reason = None
    else:
        recommended = None

    # Calculate top_variants (sorted by score, highest first, max 3)
    top_variants = None
    if variants:
        sorted_variants = sorted(variants, key=lambda v: v.score, reverse=True)
        top_variants = [v.variant for v in sorted_variants[:3]]

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

    # Build period_info for response (SSoT for time axis)
    period_hours = n * dt_hours
    period_days = period_hours / 24.0
    is_full_year = period_hours >= 8760
    annualization_factor = 1.0 if is_full_year else (8760 / period_hours)

    # Get step_minutes from request
    step_minutes = request.interval_minutes

    # Get timezone from request (or analytical_period)
    timezone_str = getattr(request, 'timezone', None)
    if timezone_str is None and request.analytical_period is not None:
        timezone_str = getattr(request.analytical_period, 'timezone', None)

    # Determine start/end datetime - prefer explicit period_start/period_end
    period_start_req = getattr(request, 'period_start', None)
    period_end_req = getattr(request, 'period_end', None)

    if period_start_req and period_end_req:
        # Use explicit period_start/period_end from request
        start_dt = period_start_req
        end_dt = period_end_req
    elif request.analytical_period is not None:
        start_dt = request.analytical_period.start_datetime
        end_dt = request.analytical_period.end_datetime
    elif request.start_date:
        start_dt = f"{request.start_date}T00:00:00"
        end_dt_obj = datetime.fromisoformat(start_dt) + timedelta(hours=period_hours)
        end_dt = end_dt_obj.isoformat()
    else:
        # Fallback
        start_dt = "2025-01-01T00:00:00"
        end_dt = (datetime(2025, 1, 1) + timedelta(hours=period_hours)).isoformat()

    period_info = PeriodInfo(
        period_hours=period_hours,
        period_days=period_days,
        is_full_year=is_full_year,
        annualization_factor=annualization_factor,
        start_datetime=start_dt,
        end_datetime=end_dt,
        # New fields (v0.3.3)
        steps=n,
        step_minutes=step_minutes,
        timezone=timezone_str,
    )

    # Get version info for API response
    version_info = get_version_info()

    # Compute total time
    compute_time_ms = (time.time() - start_time) * 1000

    # Structured log: sizing response (SSoT traceability)
    log_sizing_response(
        schema_version=version_info["schema_version"],
        assumptions_version=version_info["assumptions_version"],
        period_hours=period_hours,
        is_full_year=is_full_year,
        mode=request.mode.value,
        arbitrage_enabled=arbitrage_enabled,
        recommended_variant=recommended.variant.value if recommended else None,
        recommended_npv=recommended.npv_pln if recommended else None,
        num_variants=len(variants),
        compute_time_ms=compute_time_ms,
    )

    # Record Prometheus metrics (if available)
    record_sizing_metrics(
        mode=request.mode.value,
        arbitrage_enabled=arbitrage_enabled,
        duration_seconds=compute_time_ms / 1000,
    )

    # Build applied_parameters for transparency (v0.3.4)
    # Determine degradation cost source
    degradation_cost_source = "default"
    degradation_cost_used = request.degradation_cost_pln_mwh
    if request.degradation_cost_pln_mwh != 50.0:  # Non-default value means explicit request
        degradation_cost_source = "request"
    elif arbitrage_enabled and request.arbitrage_config.degradation_cost_pln_kwh > 0:
        # Legacy: arbitrage_config overrides default
        degradation_cost_source = "arbitrage_config"
        degradation_cost_used = request.arbitrage_config.degradation_cost_pln_kwh * 1000  # kWh to MWh

    applied_parameters = AppliedParameters(
        degradation_cost_pln_mwh=degradation_cost_used,
        degradation_cost_source=degradation_cost_source,
        discount_rate=request.discount_rate,
        analysis_years=request.analysis_years,
        opex_pct_per_year=request.opex_pct_per_year,
        import_price_pln_mwh=request.prices.import_price_pln_mwh,
        export_price_pln_mwh=request.prices.export_price_pln_mwh,
    )

    return SizingResult(
        schema_version=version_info["schema_version"],
        assumptions_version=version_info["assumptions_version"],
        mode=request.mode,
        total_pv_mwh=total_pv_mwh,
        total_load_mwh=total_load_mwh,
        annual_surplus_mwh=annual_surplus_mwh,
        period_info=period_info,
        variants=variants,
        recommended_variant=recommended.variant if recommended else None,
        recommended_power_kw=recommended.power_kw if recommended else 0,
        recommended_energy_kwh=recommended.energy_kwh if recommended else 0,
        recommended_reason=recommended_reason,
        recommended_reason_code=structured_reason.code if structured_reason else None,
        recommended_reason_metric=structured_reason.metric if structured_reason else None,
        recommended_reason_value=structured_reason.value if structured_reason else None,
        recommended_reason_unit=structured_reason.unit if structured_reason else None,
        top_variants=top_variants,
        objective_used=objective_used,
        applied_parameters=applied_parameters,
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

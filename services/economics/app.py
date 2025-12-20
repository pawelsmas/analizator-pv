from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Optional, Literal
import numpy as np
import io
import csv

# Prometheus metrics
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(title="Economics Service", version="1.1.0")

# Initialize Prometheus metrics
Instrumentator().instrument(app).expose(app)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============== Models ==============
class EconomicParameters(BaseModel):
    energy_price: float = 450.0  # PLN/MWh
    feed_in_tariff: float = 0.0  # PLN/MWh
    investment_cost: float = 3500.0  # PLN/kWp
    export_mode: str = "zero"  # zero, limited, full
    discount_rate: float = 0.07
    degradation_rate: float = 0.005
    opex_per_kwp: float = 15.0  # PLN/kWp/year
    analysis_period: int = 25  # years
    # NEW: Inflation settings for IRR calculation
    use_inflation: bool = False  # True = nominal IRR (cash flows indexed by inflation), False = real IRR
    inflation_rate: float = 0.025  # 2.5% annual inflation rate
    irr_mode: Literal["nominal", "real"] = "real"  # Alternative to use_inflation for clarity
    # BESS economic parameters
    bess_capex_per_kwh: float = 1500.0  # PLN/kWh for energy capacity
    bess_capex_per_kw: float = 300.0    # PLN/kW for power capacity
    bess_opex_pct_per_year: float = 1.5  # % of BESS CAPEX per year
    bess_lifetime_years: int = 15        # Battery replacement year
    bess_degradation_pct_per_year: float = 2.0  # Capacity degradation per year

class VariantData(BaseModel):
    capacity: float  # kWp
    production: float  # kWh
    self_consumed: float  # kWh
    exported: float  # kWh
    auto_consumption_pct: float
    coverage_pct: float
    # BESS fields (optional, for PV+BESS systems)
    bess_power_kw: Optional[float] = None
    bess_energy_kwh: Optional[float] = None
    bess_charged_kwh: Optional[float] = None
    bess_discharged_kwh: Optional[float] = None
    bess_curtailed_kwh: Optional[float] = None
    bess_grid_import_kwh: Optional[float] = None
    bess_self_consumed_direct_kwh: Optional[float] = None
    bess_self_consumed_from_bess_kwh: Optional[float] = None
    bess_cycles_equivalent: Optional[float] = None

class EconomicAnalysisRequest(BaseModel):
    variant: VariantData
    parameters: EconomicParameters

class CashFlow(BaseModel):
    year: int
    production: float
    self_consumed: float  # kWh - actual self-consumed energy with degradation
    revenue: float
    opex: float
    net_cash_flow: float
    cumulative_cash_flow: float
    discounted_cash_flow: float

class IRRResult(BaseModel):
    """IRR calculation result with status information"""
    value: Optional[float] = None  # IRR value (None if not calculable)
    status: Literal["converged", "no_root", "invalid_cashflows", "failed"] = "converged"
    mode: Literal["nominal", "real"] = "real"
    message: Optional[str] = None  # Human-readable message for errors
    iterations: int = 0  # Number of iterations used

class EconomicResult(BaseModel):
    investment: float
    annual_savings: float
    annual_export_revenue: float
    annual_total_revenue: float
    simple_payback: float
    npv: float
    irr: Optional[float]  # Can be None if calculation fails
    irr_details: IRRResult  # Detailed IRR result with status
    lcoe: float  # Levelized Cost of Energy
    cash_flows: List[CashFlow]
    metrics: Dict[str, float]

class SensitivityPoint(BaseModel):
    parameter_name: str
    parameter_value: float
    variation_pct: float
    npv: float
    irr: float
    payback: float
    lcoe: float

class SensitivityAnalysisResult(BaseModel):
    base_case: Dict[str, float]
    parameters_analyzed: List[str]
    sensitivity_data: List[SensitivityPoint]
    tornado_chart_data: Dict[str, Dict[str, float]]  # parameter -> {low_impact, high_impact}
    most_sensitive_parameter: str
    insights: List[str]


# ============== EaaS (Energy-as-a-Service) Models ==============

class EaasParameters(BaseModel):
    capacity_kw: float
    capex_per_kwp: float
    opex_per_kwp: float
    insurance_rate: float = 0.005  # annual share of CAPEX
    land_lease_per_kwp: float = 0.0  # annual PLN/kWp
    duration_years: int = 10
    target_irr: float = 0.119  # 11.9% default
    indexation: Literal["fixed", "cpi"] = "fixed"
    cpi: float = 0.025  # annual CPI
    currency: str = "PLN"


class EaasLogRow(BaseModel):
    month: int
    year: int
    subscription: float
    opex: float
    insurance: float
    lease: float
    net_cf: float
    discounted_cf: float
    cumulative_cf: float
    index_factor: float


class EaasResult(BaseModel):
    subscription_monthly: float
    subscription_annual_year1: float
    achieved_irr_annual: Optional[float]
    irr_status: str
    message: Optional[str]
    log: List[EaasLogRow]
    log_csv: str  # CSV content ready for download

# ============== Calculation Functions ==============

def _npv_at_rate(cash_flows: List[float], rate: float) -> float:
    """Calculate NPV at a given discount rate"""
    npv = 0.0
    for year, cf in enumerate(cash_flows):
        npv += cf / (1 + rate) ** year
    return npv

def _npv_derivative(cash_flows: List[float], rate: float) -> float:
    """Calculate derivative of NPV with respect to rate"""
    dnpv = 0.0
    for year, cf in enumerate(cash_flows):
        if year > 0:
            dnpv -= year * cf / (1 + rate) ** (year + 1)
    return dnpv

def calculate_irr_robust(
    cash_flows: List[float],
    max_iterations: int = 200,
    tolerance: float = 1e-6,
    irr_mode: str = "real"
) -> IRRResult:
    """
    Robust IRR calculation using hybrid bisection + Newton-Raphson method.

    Features:
    - Validates cash flows (requires at least one negative and one positive)
    - Uses bracketing to find sign change in NPV
    - Falls back to bisection if Newton-Raphson diverges
    - Returns detailed status information

    Args:
        cash_flows: List of cash flows (negative for initial investment, year 0 first)
        max_iterations: Maximum iterations for solver
        tolerance: Convergence tolerance (default 1e-6)
        irr_mode: "nominal" or "real" for display purposes

    Returns:
        IRRResult with value, status, mode, and message
    """
    # Validate cash flows
    if len(cash_flows) < 2:
        return IRRResult(
            value=None,
            status="invalid_cashflows",
            mode=irr_mode,
            message="Zbyt mało przepływów pieniężnych (min. 2 wymagane)",
            iterations=0
        )

    has_negative = any(cf < 0 for cf in cash_flows)
    has_positive = any(cf > 0 for cf in cash_flows)

    if not has_negative or not has_positive:
        return IRRResult(
            value=None,
            status="no_root",
            mode=irr_mode,
            message="IRR niedostępne - brak przepływów ujemnych i dodatnich (wymagane oba znaki)",
            iterations=0
        )

    # Search for sign change in NPV within bracket [-0.99, 10.0]
    low, high = -0.99, 10.0
    npv_low = _npv_at_rate(cash_flows, low)
    npv_high = _npv_at_rate(cash_flows, high)

    # Check for sign change
    if npv_low * npv_high > 0:
        # No sign change - try to find one with finer search
        test_rates = np.linspace(-0.99, 10.0, 100)
        found_bracket = False
        for i in range(len(test_rates) - 1):
            npv1 = _npv_at_rate(cash_flows, test_rates[i])
            npv2 = _npv_at_rate(cash_flows, test_rates[i + 1])
            if npv1 * npv2 <= 0:
                low, high = test_rates[i], test_rates[i + 1]
                npv_low, npv_high = npv1, npv2
                found_bracket = True
                break

        if not found_bracket:
            return IRRResult(
                value=None,
                status="no_root",
                mode=irr_mode,
                message="IRR niedostępne - brak zmiany znaku NPV w przedziale [-99%, 1000%]",
                iterations=0
            )

    # Hybrid solver: start with Newton-Raphson, fall back to bisection
    irr = (low + high) / 2  # Initial guess at midpoint

    for iteration in range(max_iterations):
        npv = _npv_at_rate(cash_flows, irr)

        # Check convergence
        if abs(npv) < tolerance:
            return IRRResult(
                value=irr,
                status="converged",
                mode=irr_mode,
                message=None,
                iterations=iteration + 1
            )

        # Try Newton-Raphson step
        dnpv = _npv_derivative(cash_flows, irr)

        if abs(dnpv) > 1e-10:
            newton_step = irr - npv / dnpv

            # Accept Newton step only if it stays in bracket and makes progress
            if low < newton_step < high:
                # Update bracket based on sign of NPV
                if npv * npv_low < 0:
                    high = irr
                    npv_high = npv
                else:
                    low = irr
                    npv_low = npv

                irr = newton_step
                continue

        # Fall back to bisection
        mid = (low + high) / 2
        npv_mid = _npv_at_rate(cash_flows, mid)

        if npv_mid * npv_low < 0:
            high = mid
            npv_high = npv_mid
        else:
            low = mid
            npv_low = npv_mid

        irr = (low + high) / 2

        # Check if bracket is small enough
        if high - low < tolerance:
            return IRRResult(
                value=irr,
                status="converged",
                mode=irr_mode,
                message=None,
                iterations=iteration + 1
            )

    # Max iterations reached but still within tolerance range
    return IRRResult(
        value=irr,
        status="converged" if abs(_npv_at_rate(cash_flows, irr)) < tolerance * 100 else "failed",
        mode=irr_mode,
        message="Osiągnięto limit iteracji" if abs(_npv_at_rate(cash_flows, irr)) >= tolerance * 100 else None,
        iterations=max_iterations
    )

def calculate_irr(cash_flows: List[float], max_iterations: int = 100, tolerance: float = 0.01) -> float:
    """
    Legacy IRR calculation - wrapper for backwards compatibility.
    Use calculate_irr_robust for new code.

    Args:
        cash_flows: List of cash flows (negative for initial investment)
        max_iterations: Maximum iterations
        tolerance: Convergence tolerance

    Returns:
        IRR as decimal (e.g., 0.12 = 12%), or 0.0 if calculation fails
    """
    result = calculate_irr_robust(cash_flows, max_iterations, tolerance * 0.01)
    return result.value if result.value is not None else 0.0

def calculate_lcoe(
    investment: float,
    annual_production: float,
    opex: float,
    discount_rate: float,
    degradation_rate: float,
    years: int
) -> float:
    """
    Calculate Levelized Cost of Energy (LCOE)

    Args:
        investment: Initial investment
        annual_production: First year production (kWh)
        opex: Annual O&M costs
        discount_rate: Discount rate
        degradation_rate: Annual degradation
        years: Analysis period

    Returns:
        LCOE in PLN/kWh
    """
    total_costs_pv = investment
    total_energy_pv = 0.0

    for year in range(1, years + 1):
        degrad_factor = (1 - degradation_rate) ** year
        energy = annual_production * degrad_factor
        discount_factor = (1 + discount_rate) ** year

        total_costs_pv += opex / discount_factor
        total_energy_pv += energy / discount_factor

    if total_energy_pv == 0:
        return float('inf')

    return total_costs_pv / total_energy_pv


# ============== EaaS Monthly IRR Solver ==============

def _eaas_cash_flows_monthly(params: EaasParameters, subscription_monthly: float):
    """
    Build monthly cash flows for given subscription.
    Returns (npv_at_target, log_rows, cash_flows_monthly)
    """
    capex = params.capacity_kw * params.capex_per_kwp
    months = params.duration_years * 12
    # Monthly costs (kept constant; if indexation needed, extend here)
    opex_month = params.capacity_kw * params.opex_per_kwp / 12
    insurance_month = capex * params.insurance_rate / 12
    lease_month = params.capacity_kw * params.land_lease_per_kwp / 12
    fixed_monthly_cost = opex_month + insurance_month + lease_month

    r_month = (1 + params.target_irr) ** (1 / 12) - 1

    npv = -capex
    cumulative = -capex
    log_rows: List[EaasLogRow] = []
    cash_flows = [-capex]

    for m in range(1, months + 1):
        index_factor = (1 + params.cpi) ** ((m - 1) / 12) if params.indexation == "cpi" else 1.0
        subscription = subscription_monthly * index_factor
        net_cf = subscription - fixed_monthly_cost
        discounted_cf = net_cf / ((1 + r_month) ** m)
        npv += discounted_cf
        cumulative += net_cf
        cash_flows.append(net_cf)
        log_rows.append(EaasLogRow(
            month=m,
            year=(m - 1) // 12 + 1,
            subscription=subscription,
            opex=opex_month,
            insurance=insurance_month,
            lease=lease_month,
            net_cf=net_cf,
            discounted_cf=discounted_cf,
            cumulative_cf=cumulative,
            index_factor=index_factor
        ))

    return npv, log_rows, cash_flows


def solve_eaas_subscription(params: EaasParameters) -> EaasResult:
    """
    Solve for monthly subscription that achieves target IRR using monthly cash flows.
    Uses bisection search to find subscription where NPV at target IRR is ~0.
    """
    capex = params.capacity_kw * params.capex_per_kwp
    # Initial bounds
    low = 0.0
    high = (capex / (params.duration_years * 12)) * (1 + params.target_irr) * 2

    npv_low, _, _ = _eaas_cash_flows_monthly(params, low)
    npv_high, _, _ = _eaas_cash_flows_monthly(params, high)

    # Expand upper bound until sign change or cap reached
    expand_steps = 0
    while npv_low * npv_high > 0 and expand_steps < 10:
        high *= 2
        npv_high, _, _ = _eaas_cash_flows_monthly(params, high)
        expand_steps += 1

    if npv_low * npv_high > 0:
        # Could not bracket root
        _, log_rows, cash_flows = _eaas_cash_flows_monthly(params, high)
        irr_details = calculate_irr_robust(cash_flows, irr_mode="nominal")
        achieved = (1 + irr_details.value) ** 12 - 1 if irr_details.value is not None else None
        return EaasResult(
            subscription_monthly=high,
            subscription_annual_year1=high * 12,
            achieved_irr_annual=achieved,
            irr_status="no_root",
            message="Nie udało się znaleźć abonamentu spełniającego docelowe IRR (brak zmiany znaku NPV)",
            log=log_rows,
            log_csv=_log_rows_to_csv(log_rows)
        )

    # Bisection
    for _ in range(100):
        mid = (low + high) / 2
        npv_mid, log_rows_mid, cash_flows_mid = _eaas_cash_flows_monthly(params, mid)
        if abs(npv_mid) < 1e-4:
            break
        if npv_low * npv_mid < 0:
            high = mid
            npv_high = npv_mid
        else:
            low = mid
            npv_low = npv_mid
    else:
        # Max iterations; use mid as best effort
        log_rows_mid, cash_flows_mid = log_rows_mid, cash_flows_mid

    # Final evaluation at mid
    subscription = (low + high) / 2
    npv_final, log_rows, cash_flows = _eaas_cash_flows_monthly(params, subscription)
    irr_details = calculate_irr_robust(cash_flows, irr_mode="nominal")
    achieved_annual = (1 + irr_details.value) ** 12 - 1 if irr_details.value is not None else None

    return EaasResult(
        subscription_monthly=subscription,
        subscription_annual_year1=subscription * 12,
        achieved_irr_annual=achieved_annual,
        irr_status=irr_details.status,
        message=irr_details.message,
        log=log_rows,
        log_csv=_log_rows_to_csv(log_rows)
    )


def _log_rows_to_csv(rows: List[EaasLogRow]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["month", "year", "subscription", "opex", "insurance", "lease", "net_cf", "discounted_cf", "cumulative_cf", "index_factor"])
    for r in rows:
        writer.writerow([r.month, r.year, r.subscription, r.opex, r.insurance, r.lease, r.net_cf, r.discounted_cf, r.cumulative_cf, r.index_factor])
    return buf.getvalue()

# ============== API Endpoints ==============
@app.get("/")
async def root():
    return {
        "service": "Economics Service",
        "version": "1.0.0",
        "status": "running"
    }

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.post("/analyze", response_model=EconomicResult)
async def analyze_economics(request: EconomicAnalysisRequest):
    """
    Perform comprehensive economic analysis with optional inflation indexing.

    When use_inflation=True (nominal mode):
    - Energy prices, OPEX, and feed-in tariffs are indexed by inflation each year
    - IRR reflects nominal returns (includes inflation)

    When use_inflation=False (real mode, default):
    - All values remain constant (real terms)
    - IRR reflects real returns (excludes inflation)
    """
    try:
        variant = request.variant
        params = request.parameters

        # Determine IRR mode from parameters
        # use_inflation takes precedence, but irr_mode can also be used
        use_inflation = params.use_inflation or params.irr_mode == "nominal"
        irr_mode = "nominal" if use_inflation else "real"
        inflation_rate = params.inflation_rate

        # Calculate investment (always at year 0, no inflation)
        pv_investment = variant.capacity * params.investment_cost

        # Calculate BESS investment if present
        bess_investment = 0.0
        bess_capex = 0.0
        has_bess = variant.bess_power_kw is not None and variant.bess_energy_kwh is not None
        if has_bess:
            bess_capex = (
                variant.bess_energy_kwh * params.bess_capex_per_kwh +
                variant.bess_power_kw * params.bess_capex_per_kw
            )
            bess_investment = bess_capex

        investment = pv_investment + bess_investment

        # Base annual values (year 1, before inflation indexing)
        base_energy_price = params.energy_price
        base_feed_in_tariff = params.feed_in_tariff
        base_pv_opex = variant.capacity * params.opex_per_kwp
        base_bess_opex = bess_capex * (params.bess_opex_pct_per_year / 100.0) if has_bess else 0.0
        base_opex = base_pv_opex + base_bess_opex

        # Calculate first year revenues (for simple payback and display)
        annual_savings = (variant.self_consumed / 1000) * base_energy_price
        annual_export_revenue = 0.0
        if params.export_mode != "zero":
            annual_export_revenue = (variant.exported / 1000) * base_feed_in_tariff
        annual_total_revenue = annual_savings + annual_export_revenue

        # Simple payback (based on year 1 values)
        if annual_total_revenue > 0:
            simple_payback = investment / annual_total_revenue
        else:
            simple_payback = float('inf')

        # NPV and cash flow calculation with degradation and optional inflation
        cash_flows = [-investment]  # Year 0
        cumulative = -investment
        npv = -investment

        cash_flow_details = []

        for year in range(1, params.analysis_period + 1):
            # Apply degradation to production (PV panels)
            degrad_factor = (1 - params.degradation_rate) ** year

            # BESS degradation (separate from PV)
            bess_degrad_factor = 1.0
            if has_bess:
                bess_years_since_install = year % params.bess_lifetime_years
                if bess_years_since_install == 0:
                    bess_years_since_install = params.bess_lifetime_years
                bess_degrad_factor = (1 - params.bess_degradation_pct_per_year / 100.0) ** bess_years_since_install

            # Apply inflation indexing if enabled (nominal mode)
            if use_inflation:
                inflation_factor = (1 + inflation_rate) ** year
                energy_price = base_energy_price * inflation_factor
                feed_in_tariff = base_feed_in_tariff * inflation_factor
                opex = base_opex * inflation_factor
            else:
                # Real mode - constant prices
                energy_price = base_energy_price
                feed_in_tariff = base_feed_in_tariff
                opex = base_opex

            # Production this year
            production = variant.production * degrad_factor

            # Revenue this year (with inflation-adjusted prices if enabled)
            # For BESS: energy from battery is also degraded
            if has_bess and variant.bess_self_consumed_from_bess_kwh:
                # PV direct consumption + BESS contribution (both degraded)
                direct_consumed = (variant.bess_self_consumed_direct_kwh or 0) * degrad_factor
                bess_consumed = (variant.bess_self_consumed_from_bess_kwh or 0) * degrad_factor * bess_degrad_factor
                total_self_consumed = direct_consumed + bess_consumed
                savings = (total_self_consumed / 1000) * energy_price
            else:
                savings = (variant.self_consumed * degrad_factor / 1000) * energy_price

            export_rev = 0.0
            if params.export_mode != "zero":
                export_rev = (variant.exported * degrad_factor / 1000) * feed_in_tariff

            revenue = savings + export_rev

            # BESS replacement cost (if needed in this year)
            bess_replacement_cost = 0.0
            if has_bess and year == params.bess_lifetime_years and year < params.analysis_period:
                # Battery replacement at end of BESS lifetime (only if analysis continues)
                # Assume 70% cost reduction due to falling battery prices
                bess_replacement_cost = bess_capex * 0.7
                if use_inflation:
                    bess_replacement_cost *= (1 + inflation_rate) ** year

            # Net cash flow
            net_cf = revenue - opex - bess_replacement_cost
            cumulative += net_cf

            # Discounted cash flow
            discount_factor = (1 + params.discount_rate) ** year
            discounted_cf = net_cf / discount_factor
            npv += discounted_cf

            cash_flows.append(net_cf)

            # Self consumed with degradation (kWh)
            self_consumed_year = variant.self_consumed * degrad_factor

            cash_flow_details.append(CashFlow(
                year=year,
                production=production,
                self_consumed=self_consumed_year,
                revenue=revenue,
                opex=opex,
                net_cash_flow=net_cf,
                cumulative_cash_flow=cumulative,
                discounted_cash_flow=discounted_cf
            ))

        # Calculate IRR using robust solver
        irr_result = calculate_irr_robust(cash_flows, irr_mode=irr_mode)

        # Calculate LCOE (always uses real terms for consistency)
        lcoe = calculate_lcoe(
            investment=investment,
            annual_production=variant.production,
            opex=base_opex,  # Use base OPEX for LCOE
            discount_rate=params.discount_rate,
            degradation_rate=params.degradation_rate,
            years=params.analysis_period
        )

        # Additional metrics
        metrics = {
            "roi": ((npv + investment) / investment * 100) if investment > 0 else 0,
            "benefit_cost_ratio": (npv + investment) / investment if investment > 0 else 0,
            "annual_roi": (annual_total_revenue - base_opex) / investment * 100 if investment > 0 else 0,
            "specific_investment": investment / variant.capacity if variant.capacity > 0 else 0,
            "specific_production": variant.production / variant.capacity if variant.capacity > 0 else 0,
        }

        return EconomicResult(
            investment=investment,
            annual_savings=annual_savings,
            annual_export_revenue=annual_export_revenue,
            annual_total_revenue=annual_total_revenue,
            simple_payback=simple_payback,
            npv=npv,
            irr=irr_result.value,
            irr_details=irr_result,
            lcoe=lcoe,
            cash_flows=cash_flow_details,
            metrics=metrics
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/compare-scenarios")
async def compare_scenarios(
    scenarios: List[EconomicAnalysisRequest]
):
    """
    Compare multiple economic scenarios
    """
    try:
        results = []

        for scenario in scenarios:
            result = await analyze_economics(scenario)
            results.append({
                "capacity": scenario.variant.capacity,
                "npv": result.npv,
                "irr": result.irr,
                "irr_status": result.irr_details.status,
                "irr_mode": result.irr_details.mode,
                "payback": result.simple_payback,
                "lcoe": result.lcoe
            })

        # Find best scenario by NPV
        best_npv = max(results, key=lambda x: x["npv"])
        # For IRR, filter out None values before finding max
        valid_irr_results = [r for r in results if r["irr"] is not None]
        best_irr = max(valid_irr_results, key=lambda x: x["irr"]) if valid_irr_results else None
        best_payback = min(results, key=lambda x: x["payback"])

        return {
            "scenarios": results,
            "best_by_npv": best_npv,
            "best_by_irr": best_irr,
            "best_by_payback": best_payback
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/eaas-monthly", response_model=EaasResult)
async def eaas_monthly(params: EaasParameters):
    """
    Calculate EaaS subscription to hit target IRR using monthly cash flows.

    - Cash flows monthly (subscription and costs split per month)
    - IRR target interpreted as annual; solver uses monthly discount rate r_m = (1+r)^(1/12)-1
    - Supports CPI indexation for subscription (costs kept w nominal monthly split)
    - Returns detailed monthly log + CSV for download
    """
    try:
        return solve_eaas_subscription(params)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/sensitivity-analysis")
async def sensitivity_analysis(
    base_request: EconomicAnalysisRequest,
    parameter: str,  # energy_price, investment_cost, etc.
    variations: List[float]  # e.g., [-20, -10, 0, 10, 20] for percentage changes
):
    """
    Perform sensitivity analysis on a specific parameter
    """
    try:
        results = []

        for variation_pct in variations:
            # Clone request
            modified_request = base_request.model_copy(deep=True)

            # Apply variation
            multiplier = 1 + (variation_pct / 100)

            if parameter == "energy_price":
                modified_request.parameters.energy_price *= multiplier
            elif parameter == "investment_cost":
                modified_request.parameters.investment_cost *= multiplier
            elif parameter == "feed_in_tariff":
                modified_request.parameters.feed_in_tariff *= multiplier
            elif parameter == "discount_rate":
                modified_request.parameters.discount_rate *= multiplier
            else:
                raise HTTPException(status_code=400, detail=f"Unknown parameter: {parameter}")

            # Calculate economics
            result = await analyze_economics(modified_request)

            results.append({
                "variation_pct": variation_pct,
                "parameter_value": getattr(modified_request.parameters, parameter),
                "npv": result.npv,
                "irr": result.irr,
                "irr_status": result.irr_details.status,
                "payback": result.simple_payback
            })

        return {
            "parameter": parameter,
            "base_value": getattr(base_request.parameters, parameter),
            "results": results
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/default-parameters", response_model=EconomicParameters)
async def get_default_parameters():
    """Get default economic parameters for Poland market"""
    return EconomicParameters()

@app.post("/comprehensive-sensitivity", response_model=SensitivityAnalysisResult)
async def comprehensive_sensitivity_analysis(
    base_request: EconomicAnalysisRequest,
    parameters_to_analyze: Optional[List[str]] = None,
    variation_range: float = 20.0  # +/- percentage
):
    """
    Perform comprehensive multi-parameter sensitivity analysis
    Creates tornado chart data and identifies most influential parameters
    """
    try:
        # Default parameters to analyze
        if parameters_to_analyze is None:
            parameters_to_analyze = [
                "energy_price",
                "investment_cost",
                "feed_in_tariff",
                "discount_rate",
                "degradation_rate",
                "opex_per_kwp"
            ]

        # Calculate base case
        base_result = await analyze_economics(base_request)
        base_case = {
            "npv": base_result.npv,
            "irr": base_result.irr,
            "payback": base_result.simple_payback,
            "lcoe": base_result.lcoe
        }

        # Variations to test for each parameter
        variations = [-variation_range, -variation_range/2, 0, variation_range/2, variation_range]

        sensitivity_data = []
        tornado_data = {}

        # Analyze each parameter
        for param_name in parameters_to_analyze:
            param_impacts = []

            for variation_pct in variations:
                # Clone request
                modified_request = base_request.model_copy(deep=True)

                # Apply variation
                multiplier = 1 + (variation_pct / 100)

                # Modify the specific parameter
                if hasattr(modified_request.parameters, param_name):
                    current_value = getattr(modified_request.parameters, param_name)
                    setattr(modified_request.parameters, param_name, current_value * multiplier)
                else:
                    continue

                # Calculate economics with modified parameter
                result = await analyze_economics(modified_request)

                modified_value = getattr(modified_request.parameters, param_name)

                sensitivity_data.append(SensitivityPoint(
                    parameter_name=param_name,
                    parameter_value=modified_value,
                    variation_pct=variation_pct,
                    npv=result.npv,
                    irr=result.irr,
                    payback=result.simple_payback,
                    lcoe=result.lcoe
                ))

                # Store for tornado chart
                param_impacts.append({
                    "variation_pct": variation_pct,
                    "npv_change": result.npv - base_result.npv,
                    "npv": result.npv
                })

            # Calculate tornado chart data (impact on NPV)
            low_impact = min(param_impacts, key=lambda x: x["npv"])
            high_impact = max(param_impacts, key=lambda x: x["npv"])

            tornado_data[param_name] = {
                "low_impact": low_impact["npv_change"],
                "high_impact": high_impact["npv_change"],
                "total_range": high_impact["npv"] - low_impact["npv"],
                "sensitivity_index": abs(high_impact["npv"] - low_impact["npv"]) / base_result.npv if base_result.npv != 0 else 0
            }

        # Find most sensitive parameter (largest absolute impact on NPV)
        most_sensitive = max(
            tornado_data.items(),
            key=lambda x: abs(x[1]["total_range"])
        )[0]

        # Generate insights
        insights = []

        # Sensitivity ranking
        ranked_params = sorted(
            tornado_data.items(),
            key=lambda x: abs(x[1]["total_range"]),
            reverse=True
        )

        insights.append(f"Most influential parameter: {most_sensitive} "
                       f"(NPV range: {tornado_data[most_sensitive]['total_range']:,.0f} PLN)")

        # Check if project is robust
        all_positive = all(
            point.npv > 0
            for point in sensitivity_data
        )

        if all_positive:
            insights.append("Project remains profitable across all tested parameter variations - robust investment.")
        else:
            risky_params = set()
            for point in sensitivity_data:
                if point.npv < 0:
                    risky_params.add(point.parameter_name)

            insights.append(f"Warning: Project becomes unprofitable when these parameters vary: {', '.join(risky_params)}")

        # Top 3 sensitivity ranking
        top3_names = [name for name, _ in ranked_params[:3]]
        insights.append(f"Top 3 sensitive parameters: {', '.join(top3_names)}")

        # Specific parameter insights
        for param_name, impact in ranked_params[:2]:  # Top 2
            sensitivity_pct = impact["sensitivity_index"] * 100
            if sensitivity_pct > 50:
                insights.append(f"{param_name}: High sensitivity ({sensitivity_pct:.0f}% NPV change) - "
                              f"careful monitoring recommended")

        # IRR variability
        irr_values = [point.irr for point in sensitivity_data]
        irr_range = max(irr_values) - min(irr_values)
        if irr_range > 0.05:  # 5 percentage points
            insights.append(f"IRR varies significantly ({irr_range*100:.1f} percentage points) - "
                          f"return expectations should account for uncertainty")

        return SensitivityAnalysisResult(
            base_case=base_case,
            parameters_analyzed=parameters_to_analyze,
            sensitivity_data=sensitivity_data,
            tornado_chart_data=tornado_data,
            most_sensitive_parameter=most_sensitive,
            insights=insights
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== SCORING ENGINE ENDPOINTS ==============

from scoring import (
    ScoringEngine,
    ScoringRequest,
    ScoringResponse,
    OfferInputs,
    ScoringParameters,
    WeightProfile,
    ProfileType,
    WEIGHT_PROFILES,
)


@app.post("/scoring/analyze", response_model=ScoringResponse)
async def analyze_scoring(request: ScoringRequest):
    """
    Multi-criteria scoring for PV offers.

    Scores offers based on savings vs baseline energy costs.
    Uses 4 buckets: Value (NPV, Year1), Robustness (conservative scenario),
    Tech (auto-consumption, coverage), ESG (CO2 reduction).

    Normalization is done to baseline costs (not min-max across offers).
    Piecewise threshold scoring with linear interpolation.
    """
    try:
        engine = ScoringEngine(request.parameters)
        return engine.score_offers(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/scoring/profiles")
async def get_weight_profiles():
    """Get available weight profiles (CFO, ESG, Operations, Custom)"""
    return {
        profile_type.value: {
            "name": profile_type.value.upper(),
            "value_weight": profile.value_weight,
            "robustness_weight": profile.robustness_weight,
            "tech_weight": profile.tech_weight,
            "esg_weight": profile.esg_weight,
        }
        for profile_type, profile in WEIGHT_PROFILES.items()
    }


@app.get("/scoring/thresholds")
async def get_default_thresholds():
    """Get default threshold configuration for scoring rules"""
    from scoring.models import ThresholdConfig
    config = ThresholdConfig()
    return {
        "npv_mln": {
            "thresholds": config.npv_mln.thresholds,
            "points": config.npv_mln.points,
            "higher_is_better": config.npv_mln.higher_is_better,
            "description": "NPV w milionach PLN",
        },
        "payback_years": {
            "thresholds": config.payback_years.thresholds,
            "points": config.payback_years.points,
            "higher_is_better": config.payback_years.higher_is_better,
            "description": "Okres zwrotu w latach",
        },
        "irr_pct": {
            "thresholds": config.irr_pct.thresholds,
            "points": config.irr_pct.points,
            "higher_is_better": config.irr_pct.higher_is_better,
            "description": "IRR w %",
        },
        "lcoe_pln_mwh": {
            "thresholds": config.lcoe_pln_mwh.thresholds,
            "points": config.lcoe_pln_mwh.points,
            "higher_is_better": config.lcoe_pln_mwh.higher_is_better,
            "description": "LCOE w PLN/MWh",
        },
        "auto_consumption_pct": {
            "thresholds": config.auto_consumption_pct.thresholds,
            "points": config.auto_consumption_pct.points,
            "higher_is_better": config.auto_consumption_pct.higher_is_better,
            "description": "Autokonsumpcja (0-1)",
        },
        "coverage_pct": {
            "thresholds": config.coverage_pct.thresholds,
            "points": config.coverage_pct.points,
            "higher_is_better": config.coverage_pct.higher_is_better,
            "description": "Pokrycie zużycia (0-1)",
        },
        "co2_reduction_tons": {
            "thresholds": config.co2_reduction_tons.thresholds,
            "points": config.co2_reduction_tons.points,
            "higher_is_better": config.co2_reduction_tons.higher_is_better,
            "description": "Redukcja CO2 w tonach/rok",
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)

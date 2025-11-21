from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Optional
import numpy as np

app = FastAPI(title="Economics Service", version="1.0.0")

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

class VariantData(BaseModel):
    capacity: float  # kWp
    production: float  # kWh
    self_consumed: float  # kWh
    exported: float  # kWh
    auto_consumption_pct: float
    coverage_pct: float

class EconomicAnalysisRequest(BaseModel):
    variant: VariantData
    parameters: EconomicParameters

class CashFlow(BaseModel):
    year: int
    production: float
    revenue: float
    opex: float
    net_cash_flow: float
    cumulative_cash_flow: float
    discounted_cash_flow: float

class EconomicResult(BaseModel):
    investment: float
    annual_savings: float
    annual_export_revenue: float
    annual_total_revenue: float
    simple_payback: float
    npv: float
    irr: float
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

# ============== Calculation Functions ==============
def calculate_irr(cash_flows: List[float], max_iterations: int = 100, tolerance: float = 0.01) -> float:
    """
    Calculate Internal Rate of Return using Newton-Raphson method

    Args:
        cash_flows: List of cash flows (negative for initial investment)
        max_iterations: Maximum iterations
        tolerance: Convergence tolerance

    Returns:
        IRR as decimal (e.g., 0.12 = 12%)
    """
    # Initial guess
    irr = 0.1

    for iteration in range(max_iterations):
        npv = 0.0
        dnpv = 0.0

        for year, cf in enumerate(cash_flows):
            npv += cf / (1 + irr) ** year
            if year > 0:
                dnpv -= year * cf / (1 + irr) ** (year + 1)

        if abs(npv) < tolerance:
            return irr

        if dnpv == 0:
            break

        irr = irr - npv / dnpv

        # Keep IRR reasonable
        if irr < -0.99:
            irr = -0.99
        elif irr > 10.0:
            irr = 10.0

    return irr

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
    Perform comprehensive economic analysis
    """
    try:
        variant = request.variant
        params = request.parameters

        # Calculate investment
        investment = variant.capacity * params.investment_cost

        # Calculate annual revenues
        annual_savings = (variant.self_consumed / 1000) * params.energy_price

        annual_export_revenue = 0.0
        if params.export_mode != "zero":
            annual_export_revenue = (variant.exported / 1000) * params.feed_in_tariff

        annual_total_revenue = annual_savings + annual_export_revenue

        # Simple payback
        if annual_total_revenue > 0:
            simple_payback = investment / annual_total_revenue
        else:
            simple_payback = float('inf')

        # Calculate O&M costs
        opex = variant.capacity * params.opex_per_kwp

        # NPV calculation with degradation
        cash_flows = [-investment]  # Year 0
        cumulative = -investment
        npv = -investment

        cash_flow_details = []

        for year in range(1, params.analysis_period + 1):
            # Apply degradation
            degrad_factor = (1 - params.degradation_rate) ** year

            # Production this year
            production = variant.production * degrad_factor

            # Revenue this year
            savings = (variant.self_consumed * degrad_factor / 1000) * params.energy_price
            export_rev = 0.0

            if params.export_mode != "zero":
                export_rev = (variant.exported * degrad_factor / 1000) * params.feed_in_tariff

            revenue = savings + export_rev

            # Net cash flow
            net_cf = revenue - opex
            cumulative += net_cf

            # Discounted cash flow
            discount_factor = (1 + params.discount_rate) ** year
            discounted_cf = net_cf / discount_factor
            npv += discounted_cf

            cash_flows.append(net_cf)

            cash_flow_details.append(CashFlow(
                year=year,
                production=production,
                revenue=revenue,
                opex=opex,
                net_cash_flow=net_cf,
                cumulative_cash_flow=cumulative,
                discounted_cash_flow=discounted_cf
            ))

        # Calculate IRR
        irr = calculate_irr(cash_flows)

        # Calculate LCOE
        lcoe = calculate_lcoe(
            investment=investment,
            annual_production=variant.production,
            opex=opex,
            discount_rate=params.discount_rate,
            degradation_rate=params.degradation_rate,
            years=params.analysis_period
        )

        # Additional metrics
        metrics = {
            "roi": ((npv + investment) / investment * 100) if investment > 0 else 0,
            "benefit_cost_ratio": (npv + investment) / investment if investment > 0 else 0,
            "annual_roi": (annual_total_revenue - opex) / investment * 100 if investment > 0 else 0,
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
            irr=irr,
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
                "payback": result.simple_payback,
                "lcoe": result.lcoe
            })

        # Find best scenario by NPV
        best_npv = max(results, key=lambda x: x["npv"])
        best_irr = max(results, key=lambda x: x["irr"])
        best_payback = min(results, key=lambda x: x["payback"])

        return {
            "scenarios": results,
            "best_by_npv": best_npv,
            "best_by_irr": best_irr,
            "best_by_payback": best_payback
        }

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)

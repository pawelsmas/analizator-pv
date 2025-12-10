"""
Profile Analysis Service v2.0

Advanced hourly analysis of PV + Load profiles to optimize BESS sizing
and PV oversizing for maximum utilization.

Key features:
1. PyPSA-based BESS optimization (integrates with bess-optimizer)
2. Three optimization strategies: NPV Max, Cycles Max, Balanced
3. Pareto frontier analysis for multi-objective optimization
4. Hourly surplus/deficit heatmap (24h x 12 months)
5. Seasonal pattern detection
6. Variant comparison
"""

import numpy as np
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import json
import httpx
from enum import Enum

app = FastAPI(
    title="Profile Analysis Service",
    description="Advanced PV+BESS profile analysis for optimal sizing v2.0",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# BESS Optimizer URL for PyPSA integration
BESS_OPTIMIZER_URL = "http://pv-bess-optimizer:8030"


# ============== Enums ==============

class OptimizationStrategy(str, Enum):
    NPV_MAX = "npv_max"          # Maximize NPV
    CYCLES_MAX = "cycles_max"    # Maximize cycles (smaller battery)
    BALANCED = "balanced"        # Pareto optimal balance


# ============== Models ==============

class ProfileAnalysisRequest(BaseModel):
    """Request for profile analysis"""
    pv_generation_kwh: List[float] = Field(..., description="Hourly PV generation [kWh]")
    load_kwh: List[float] = Field(..., description="Hourly load [kWh]")
    pv_capacity_kwp: float = Field(..., gt=0, description="PV capacity [kWp]")

    # Optional BESS parameters for comparison
    bess_power_kw: Optional[float] = Field(None, description="Current BESS power [kW]")
    bess_energy_kwh: Optional[float] = Field(None, description="Current BESS energy [kWh]")

    # Economic parameters (can be overridden by Settings)
    energy_price_plnmwh: float = Field(default=800, description="Energy price [PLN/MWh]")
    bess_capex_per_kwh: float = Field(default=1500, description="BESS CAPEX [PLN/kWh]")
    bess_capex_per_kw: float = Field(default=300, description="BESS CAPEX [PLN/kW]")
    bess_efficiency: float = Field(default=0.90, description="Round-trip efficiency")
    discount_rate: float = Field(default=0.08, description="Discount rate for NPV")
    project_years: int = Field(default=15, description="Project lifetime")

    # Optimization settings
    strategy: OptimizationStrategy = Field(default=OptimizationStrategy.BALANCED)
    min_cycles_per_year: int = Field(default=200, description="Minimum target cycles")
    max_cycles_per_year: int = Field(default=400, description="Maximum target cycles")

    # Pareto analysis
    pareto_points: int = Field(default=10, description="Number of Pareto points to calculate")


class HourlyPattern(BaseModel):
    """Hourly pattern statistics"""
    hour: int
    avg_pv_kwh: float
    avg_load_kwh: float
    avg_surplus_kwh: float
    avg_deficit_kwh: float
    surplus_frequency_pct: float
    deficit_frequency_pct: float


class MonthlyAnalysis(BaseModel):
    """Monthly analysis results"""
    month: int
    month_name: str
    days: int
    total_pv_mwh: float
    total_load_mwh: float
    total_surplus_mwh: float
    total_deficit_mwh: float
    avg_daily_surplus_kwh: float
    avg_daily_deficit_kwh: float
    surplus_hours_per_day: float
    deficit_hours_per_day: float
    optimal_bess_kwh: float
    current_bess_cycles: Optional[float]


class HeatmapCell(BaseModel):
    """Single cell in surplus/deficit heatmap"""
    hour: int
    month: int
    avg_surplus_kwh: float
    avg_deficit_kwh: float
    net_kwh: float  # positive = surplus, negative = deficit


class BessSizingRecommendation(BaseModel):
    """BESS sizing recommendation"""
    scenario: str
    strategy: str
    power_kw: float
    energy_kwh: float
    duration_h: float
    estimated_annual_cycles: float
    estimated_annual_discharge_mwh: float
    estimated_curtailment_mwh: float
    capex_pln: float
    annual_savings_pln: float
    npv_pln: float
    simple_payback_years: float
    utilization_score: float
    # For Pareto front
    pareto_optimal: bool = False


class ParetoPoint(BaseModel):
    """Point on Pareto frontier"""
    power_kw: float
    energy_kwh: float
    npv_mln_pln: float
    annual_cycles: float
    payback_years: float
    is_selected: bool = False


class PvOversizingRecommendation(BaseModel):
    """PV oversizing recommendation"""
    scenario: str
    pv_capacity_kwp: float
    oversizing_ratio: float
    estimated_surplus_increase_pct: float
    additional_bess_cycles: float
    additional_capex_pln: float
    additional_annual_savings_pln: float


class VariantComparison(BaseModel):
    """Side-by-side variant comparison"""
    variant_id: str
    name: str
    power_kw: float
    energy_kwh: float
    annual_cycles: float
    npv_mln_pln: float
    payback_years: float
    curtailment_pct: float
    is_recommended: bool = False


class ProfileAnalysisResult(BaseModel):
    """Complete profile analysis result v2.0"""
    # Summary
    annual_pv_mwh: float
    annual_load_mwh: float
    annual_surplus_mwh: float
    annual_deficit_mwh: float
    direct_consumption_mwh: float
    direct_consumption_pct: float

    # Hourly patterns
    hourly_patterns: List[HourlyPattern]

    # Heatmap data (24h x 12 months)
    heatmap_data: List[HeatmapCell]

    # Monthly breakdown
    monthly_analysis: List[MonthlyAnalysis]

    # Quarterly summary
    quarterly_cycles: Dict[str, float]
    quarterly_surplus_mwh: Dict[str, float]

    # Current BESS performance (if provided)
    current_bess_annual_cycles: Optional[float]
    current_bess_utilization_pct: Optional[float]
    current_curtailment_ratio: Optional[float]

    # Optimization results
    selected_strategy: str
    bess_recommendations: List[BessSizingRecommendation]
    pareto_frontier: List[ParetoPoint]
    variant_comparison: List[VariantComparison]

    # PV recommendations
    pv_recommendations: List[PvOversizingRecommendation]

    # Key insights
    insights: List[str]


# ============== Analysis Functions ==============

def analyze_hourly_patterns(
    pv_kwh: np.ndarray,
    load_kwh: np.ndarray,
    hours_per_step: float = 1.0
) -> List[HourlyPattern]:
    """Analyze average patterns by hour of day"""

    n = len(pv_kwh)
    steps_per_day = int(24 / hours_per_step)
    n_days = n // steps_per_day

    patterns = []

    for hour in range(24):
        step_in_day = int(hour / hours_per_step)
        indices = [day * steps_per_day + step_in_day for day in range(n_days)]

        hour_pv = pv_kwh[indices]
        hour_load = load_kwh[indices]
        hour_surplus = np.maximum(hour_pv - hour_load, 0)
        hour_deficit = np.maximum(hour_load - hour_pv, 0)

        patterns.append(HourlyPattern(
            hour=hour,
            avg_pv_kwh=float(np.mean(hour_pv)),
            avg_load_kwh=float(np.mean(hour_load)),
            avg_surplus_kwh=float(np.mean(hour_surplus)),
            avg_deficit_kwh=float(np.mean(hour_deficit)),
            surplus_frequency_pct=float(np.sum(hour_surplus > 0) / n_days * 100),
            deficit_frequency_pct=float(np.sum(hour_deficit > 0) / n_days * 100)
        ))

    return patterns


def generate_heatmap(
    pv_kwh: np.ndarray,
    load_kwh: np.ndarray,
    hours_per_step: float = 1.0
) -> List[HeatmapCell]:
    """Generate 24h x 12 month heatmap of surplus/deficit"""

    days_per_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    steps_per_hour = int(1 / hours_per_step)
    steps_per_day = 24 * steps_per_hour

    heatmap = []
    start_idx = 0

    for month in range(12):
        days = days_per_month[month]
        steps_in_month = days * steps_per_day
        end_idx = min(start_idx + steps_in_month, len(pv_kwh))

        if start_idx >= len(pv_kwh):
            break

        month_pv = pv_kwh[start_idx:end_idx]
        month_load = load_kwh[start_idx:end_idx]

        # Group by hour within month
        for hour in range(24):
            hour_indices = []
            for day in range(days):
                idx = day * steps_per_day + int(hour / hours_per_step)
                if idx < len(month_pv):
                    hour_indices.append(idx)

            if hour_indices:
                hour_pv = month_pv[hour_indices]
                hour_load = month_load[hour_indices]
                hour_surplus = np.maximum(hour_pv - hour_load, 0)
                hour_deficit = np.maximum(hour_load - hour_pv, 0)

                heatmap.append(HeatmapCell(
                    hour=hour,
                    month=month + 1,
                    avg_surplus_kwh=float(np.mean(hour_surplus)),
                    avg_deficit_kwh=float(np.mean(hour_deficit)),
                    net_kwh=float(np.mean(hour_pv - hour_load))
                ))

        start_idx = end_idx

    return heatmap


def analyze_monthly(
    pv_kwh: np.ndarray,
    load_kwh: np.ndarray,
    bess_energy_kwh: Optional[float],
    bess_efficiency: float,
    hours_per_step: float = 1.0
) -> List[MonthlyAnalysis]:
    """Analyze patterns by month"""

    days_per_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    month_names = ['Sty', 'Lut', 'Mar', 'Kwi', 'Maj', 'Cze',
                   'Lip', 'Sie', 'Wrz', 'Paź', 'Lis', 'Gru']

    steps_per_hour = int(1 / hours_per_step)
    steps_per_day = 24 * steps_per_hour

    results = []
    start_idx = 0

    for month_idx, (days, name) in enumerate(zip(days_per_month, month_names)):
        steps_in_month = days * steps_per_day
        end_idx = min(start_idx + steps_in_month, len(pv_kwh))

        if start_idx >= len(pv_kwh):
            break

        month_pv = pv_kwh[start_idx:end_idx]
        month_load = load_kwh[start_idx:end_idx]

        surplus = np.maximum(month_pv - month_load, 0)
        deficit = np.maximum(month_load - month_pv, 0)

        total_pv = np.sum(month_pv) * hours_per_step
        total_load = np.sum(month_load) * hours_per_step
        total_surplus = np.sum(surplus) * hours_per_step
        total_deficit = np.sum(deficit) * hours_per_step

        avg_daily_surplus = total_surplus / days
        avg_daily_deficit = total_deficit / days

        surplus_hours = np.sum(surplus > 0) * hours_per_step / days
        deficit_hours = np.sum(deficit > 0) * hours_per_step / days

        optimal_bess = avg_daily_surplus * 0.8 / np.sqrt(bess_efficiency)

        current_cycles = None
        if bess_energy_kwh and bess_energy_kwh > 0:
            usable = bess_energy_kwh * 0.8
            daily_charge = min(avg_daily_surplus * np.sqrt(bess_efficiency), usable)
            current_cycles = daily_charge / usable * days if usable > 0 else 0

        results.append(MonthlyAnalysis(
            month=month_idx + 1,
            month_name=name,
            days=days,
            total_pv_mwh=total_pv / 1000,
            total_load_mwh=total_load / 1000,
            total_surplus_mwh=total_surplus / 1000,
            total_deficit_mwh=total_deficit / 1000,
            avg_daily_surplus_kwh=avg_daily_surplus,
            avg_daily_deficit_kwh=avg_daily_deficit,
            surplus_hours_per_day=surplus_hours,
            deficit_hours_per_day=deficit_hours,
            optimal_bess_kwh=optimal_bess,
            current_bess_cycles=current_cycles
        ))

        start_idx = end_idx

    return results


def calculate_npv(
    annual_savings: float,
    capex: float,
    discount_rate: float,
    project_years: int
) -> float:
    """Calculate Net Present Value"""
    npv = -capex
    for year in range(1, project_years + 1):
        npv += annual_savings / ((1 + discount_rate) ** year)
    return npv


async def call_bess_optimizer(
    pv_kwh: np.ndarray,
    load_kwh: np.ndarray,
    pv_capacity: float,
    energy_kwh: float,
    power_kw: float,
    efficiency: float,
    energy_price: float
) -> Optional[Dict]:
    """Call BESS optimizer service for accurate dispatch simulation"""
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{BESS_OPTIMIZER_URL}/optimize",
                json={
                    "pv_generation_kwh": pv_kwh.tolist(),
                    "load_kwh": load_kwh.tolist(),
                    "pv_capacity_kwp": pv_capacity,
                    "bess_power_kw": power_kw,
                    "bess_energy_kwh": energy_kwh,
                    "roundtrip_efficiency": efficiency,
                    "soc_min": 0.1,
                    "soc_max": 0.9,
                    "energy_price_import": energy_price,
                    "energy_price_export": 0,
                    "zero_export": True
                }
            )
            if response.status_code == 200:
                return response.json()
    except Exception as e:
        print(f"⚠️ BESS optimizer call failed: {e}")
    return None


async def generate_pareto_frontier(
    pv_kwh: np.ndarray,
    load_kwh: np.ndarray,
    monthly_analysis: List[MonthlyAnalysis],
    pv_capacity: float,
    energy_price: float,
    capex_per_kwh: float,
    capex_per_kw: float,
    efficiency: float,
    discount_rate: float,
    project_years: int,
    n_points: int = 10
) -> List[ParetoPoint]:
    """Generate Pareto frontier of NPV vs Cycles"""

    # Calculate range of BESS sizes to explore
    avg_daily_surplus = np.mean([m.avg_daily_surplus_kwh for m in monthly_analysis])
    max_daily_surplus = max(m.avg_daily_surplus_kwh for m in monthly_analysis)

    # Energy range: from small (high cycles) to large (low cycles)
    min_energy = avg_daily_surplus * 0.3
    max_energy = max_daily_surplus * 1.5

    energy_range = np.linspace(min_energy, max_energy, n_points)

    pareto_points = []

    for energy_kwh in energy_range:
        if energy_kwh < 100:
            continue

        # Duration 2-4h based on size
        duration = min(4, max(2, energy_kwh / avg_daily_surplus))
        power_kw = energy_kwh / duration

        # Simulate BESS performance
        usable = energy_kwh * 0.8
        annual_cycles = 0
        annual_discharge = 0

        for m in monthly_analysis:
            daily_available = m.avg_daily_surplus_kwh * np.sqrt(efficiency)
            daily_charge = min(daily_available, usable, power_kw * 8)
            daily_discharge = daily_charge * np.sqrt(efficiency)
            monthly_cycles = daily_discharge / usable * m.days if usable > 0 else 0
            annual_cycles += monthly_cycles
            annual_discharge += daily_discharge * m.days

        capex = power_kw * capex_per_kw + energy_kwh * capex_per_kwh
        annual_savings = annual_discharge * energy_price / 1000
        npv = calculate_npv(annual_savings, capex, discount_rate, project_years)
        payback = capex / annual_savings if annual_savings > 0 else 99

        pareto_points.append(ParetoPoint(
            power_kw=round(power_kw, 0),
            energy_kwh=round(energy_kwh, 0),
            npv_mln_pln=round(npv / 1e6, 2),
            annual_cycles=round(annual_cycles, 0),
            payback_years=round(payback, 1),
            is_selected=False
        ))

    # Mark Pareto-optimal points (non-dominated)
    for i, p1 in enumerate(pareto_points):
        is_dominated = False
        for j, p2 in enumerate(pareto_points):
            if i != j:
                # p2 dominates p1 if better in both objectives
                if p2.npv_mln_pln >= p1.npv_mln_pln and p2.annual_cycles >= p1.annual_cycles:
                    if p2.npv_mln_pln > p1.npv_mln_pln or p2.annual_cycles > p1.annual_cycles:
                        is_dominated = True
                        break
        if not is_dominated:
            pareto_points[i].is_selected = True

    return pareto_points


def select_by_strategy(
    pareto_points: List[ParetoPoint],
    strategy: OptimizationStrategy,
    min_cycles: int,
    max_cycles: int
) -> Optional[ParetoPoint]:
    """Select best point based on strategy"""

    # Filter Pareto-optimal points
    optimal = [p for p in pareto_points if p.is_selected]
    if not optimal:
        optimal = pareto_points

    if strategy == OptimizationStrategy.NPV_MAX:
        # Simply max NPV
        return max(optimal, key=lambda p: p.npv_mln_pln)

    elif strategy == OptimizationStrategy.CYCLES_MAX:
        # Max cycles (smaller battery)
        return max(optimal, key=lambda p: p.annual_cycles)

    else:  # BALANCED
        # Find point with best NPV within cycle constraints
        filtered = [p for p in optimal if min_cycles <= p.annual_cycles <= max_cycles]
        if filtered:
            return max(filtered, key=lambda p: p.npv_mln_pln)
        # Fallback to closest to target range
        target = (min_cycles + max_cycles) / 2
        return min(optimal, key=lambda p: abs(p.annual_cycles - target))


def calculate_bess_recommendations(
    monthly_analysis: List[MonthlyAnalysis],
    pareto_points: List[ParetoPoint],
    strategy: OptimizationStrategy,
    pv_capacity_kwp: float,
    energy_price_plnmwh: float,
    capex_per_kwh: float,
    capex_per_kw: float,
    bess_efficiency: float,
    discount_rate: float,
    project_years: int,
    min_cycles: int,
    max_cycles: int
) -> List[BessSizingRecommendation]:
    """Generate BESS sizing recommendations based on strategy"""

    recommendations = []
    total_annual_surplus = sum(m.total_surplus_mwh for m in monthly_analysis) * 1000

    # Strategy-based recommendations
    strategies_to_show = [
        (OptimizationStrategy.NPV_MAX, "💰 Maksymalne NPV"),
        (OptimizationStrategy.CYCLES_MAX, "🔄 Maksymalne cykle"),
        (OptimizationStrategy.BALANCED, "🎯 Zbalansowany"),
    ]

    for strat, name in strategies_to_show:
        selected = select_by_strategy(pareto_points, strat, min_cycles, max_cycles)
        if not selected:
            continue

        power = selected.power_kw
        energy = selected.energy_kwh
        duration = energy / power if power > 0 else 2
        usable = energy * 0.8

        # Detailed calculation
        annual_cycles = 0
        annual_discharge = 0
        annual_curtailment = 0

        for m in monthly_analysis:
            daily_available = m.avg_daily_surplus_kwh * np.sqrt(bess_efficiency)
            daily_charge = min(daily_available, usable, power * 8)
            daily_discharge = daily_charge * np.sqrt(bess_efficiency)
            daily_curtail = max(0, m.avg_daily_surplus_kwh - daily_charge / np.sqrt(bess_efficiency))

            monthly_cycles = daily_discharge / usable * m.days if usable > 0 else 0
            annual_cycles += monthly_cycles
            annual_discharge += daily_discharge * m.days
            annual_curtailment += daily_curtail * m.days

        capex = power * capex_per_kw + energy * capex_per_kwh
        annual_savings = annual_discharge * energy_price_plnmwh / 1000
        npv = calculate_npv(annual_savings, capex, discount_rate, project_years)
        payback = capex / annual_savings if annual_savings > 0 else 999
        utilization = min(100, annual_cycles / 365 * 100)

        recommendations.append(BessSizingRecommendation(
            scenario=name,
            strategy=strat.value,
            power_kw=round(power, 0),
            energy_kwh=round(energy, 0),
            duration_h=round(duration, 1),
            estimated_annual_cycles=round(annual_cycles, 0),
            estimated_annual_discharge_mwh=round(annual_discharge / 1000, 1),
            estimated_curtailment_mwh=round(annual_curtailment / 1000, 1),
            capex_pln=round(capex, 0),
            annual_savings_pln=round(annual_savings, 0),
            npv_pln=round(npv, 0),
            simple_payback_years=round(payback, 1),
            utilization_score=round(utilization, 0),
            pareto_optimal=strat == strategy
        ))

    return recommendations


def generate_variant_comparison(
    recommendations: List[BessSizingRecommendation],
    annual_surplus_mwh: float
) -> List[VariantComparison]:
    """Generate side-by-side variant comparison"""

    comparisons = []

    for i, rec in enumerate(recommendations):
        curtailment_pct = rec.estimated_curtailment_mwh / annual_surplus_mwh * 100 if annual_surplus_mwh > 0 else 0

        comparisons.append(VariantComparison(
            variant_id=f"V{i+1}",
            name=rec.scenario,
            power_kw=rec.power_kw,
            energy_kwh=rec.energy_kwh,
            annual_cycles=rec.estimated_annual_cycles,
            npv_mln_pln=rec.npv_pln / 1e6,
            payback_years=rec.simple_payback_years,
            curtailment_pct=round(curtailment_pct, 1),
            is_recommended=rec.pareto_optimal
        ))

    return comparisons


def calculate_pv_recommendations(
    monthly_analysis: List[MonthlyAnalysis],
    current_pv_kwp: float,
    bess_energy_kwh: Optional[float],
    bess_efficiency: float,
    energy_price: float
) -> List[PvOversizingRecommendation]:
    """Generate PV oversizing recommendations"""

    recommendations = []

    if not bess_energy_kwh or bess_energy_kwh == 0:
        return recommendations

    usable_bess = bess_energy_kwh * 0.8

    low_util_months = [m for m in monthly_analysis
                       if m.current_bess_cycles and m.current_bess_cycles < m.days * 0.5]

    if not low_util_months:
        return recommendations

    for ratio in [1.2, 1.5, 2.0]:
        additional_cycles = 0

        for m in low_util_months:
            current_surplus = m.avg_daily_surplus_kwh
            new_surplus = current_surplus * ratio
            new_daily_charge = min(new_surplus * np.sqrt(bess_efficiency), usable_bess)
            new_cycles = new_daily_charge / usable_bess * m.days
            current_cycles = m.current_bess_cycles or 0
            additional_cycles += max(0, new_cycles - current_cycles)

        additional_pv = current_pv_kwp * (ratio - 1)
        additional_capex = additional_pv * 2000  # ~2000 PLN/kWp
        additional_discharge = additional_cycles * usable_bess / 1000
        additional_savings = additional_discharge * energy_price / 1000

        recommendations.append(PvOversizingRecommendation(
            scenario=f"PV +{int((ratio-1)*100)}%",
            pv_capacity_kwp=round(current_pv_kwp * ratio, 0),
            oversizing_ratio=ratio,
            estimated_surplus_increase_pct=round((ratio - 1) * 100, 0),
            additional_bess_cycles=round(additional_cycles, 0),
            additional_capex_pln=round(additional_capex, 0),
            additional_annual_savings_pln=round(additional_savings, 0)
        ))

    return recommendations


def generate_insights(
    monthly_analysis: List[MonthlyAnalysis],
    quarterly_cycles: Dict[str, float],
    current_bess_kwh: Optional[float],
    annual_surplus_mwh: float,
    annual_deficit_mwh: float,
    strategy: OptimizationStrategy,
    recommendations: List[BessSizingRecommendation]
) -> List[str]:
    """Generate actionable insights"""

    insights = []

    # Strategy explanation
    if strategy == OptimizationStrategy.NPV_MAX:
        insights.append("Strategia NPV Max: optymalizacja pod kątem maksymalnego zwrotu z inwestycji.")
    elif strategy == OptimizationStrategy.CYCLES_MAX:
        insights.append("Strategia Cycles Max: mniejsza bateria = więcej cykli = szybszy zwrot, ale niższe całkowite oszczędności.")
    else:
        insights.append("Strategia Balanced: kompromis między NPV a liczbą cykli w zadanym zakresie.")

    # Quarterly imbalance
    if quarterly_cycles:
        max_q = max(quarterly_cycles.values())
        min_q = min(quarterly_cycles.values())
        if max_q > min_q * 2 and min_q > 0:
            best_q = max(quarterly_cycles, key=quarterly_cycles.get)
            worst_q = min(quarterly_cycles, key=quarterly_cycles.get)
            insights.append(
                f"Duża nierówność cykli: {best_q} ma {max_q:.0f} cykli, "
                f"{worst_q} tylko {min_q:.0f}. Rozważ przewymiarowanie PV dla wyrównania."
            )

    # Seasonal pattern detection
    summer_surplus = sum(m.total_surplus_mwh for m in monthly_analysis if m.month in [5, 6, 7, 8])
    winter_surplus = sum(m.total_surplus_mwh for m in monthly_analysis if m.month in [11, 12, 1, 2])

    if summer_surplus < winter_surplus:
        insights.append(
            "⚠️ Paradoks: więcej nadwyżki zimą niż latem! "
            "To sugeruje duże obciążenie letnie (klimatyzacja?). "
            "Rozważ większe PV dla letniego szczytu."
        )

    # Curtailment warning
    if recommendations:
        best_rec = next((r for r in recommendations if r.pareto_optimal), recommendations[0])
        if best_rec.estimated_curtailment_mwh > annual_surplus_mwh * 0.3:
            insights.append(
                f"Wysoki curtailment ({best_rec.estimated_curtailment_mwh:.0f} MWh). "
                f"Rozważ większą baterię lub przewymiarowanie PV."
            )

    # Optimal size hint
    optimal_sizes = [m.optimal_bess_kwh for m in monthly_analysis]
    avg_optimal = np.mean(optimal_sizes)

    if current_bess_kwh:
        if current_bess_kwh < avg_optimal * 0.5:
            insights.append(
                f"Obecna bateria ({current_bess_kwh:.0f} kWh) jest mniejsza "
                f"niż optymalna ({avg_optimal:.0f} kWh)."
            )

    # NPV comparison
    if len(recommendations) >= 2:
        npvs = [r.npv_pln for r in recommendations]
        if max(npvs) - min(npvs) > 1e6:
            insights.append(
                f"Różnica NPV między wariantami: {(max(npvs) - min(npvs))/1e6:.1f} mln PLN. "
                f"Warto przeanalizować wszystkie opcje."
            )

    return insights


# ============== API Endpoints ==============

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "profile-analysis",
        "version": "2.0.0",
        "features": ["pareto", "strategies", "heatmap", "comparison"]
    }


@app.post("/analyze", response_model=ProfileAnalysisResult)
async def analyze_profile(request: ProfileAnalysisRequest):
    """
    Perform comprehensive profile analysis v2.0

    Features:
    - Three optimization strategies (NPV Max, Cycles Max, Balanced)
    - Pareto frontier visualization
    - 24h x 12 month heatmap
    - Variant comparison
    """

    try:
        n_pv = len(request.pv_generation_kwh)
        n_load = len(request.load_kwh)

        print(f"📊 Profile analysis v2.0: PV={n_pv}, Load={n_load}, Strategy={request.strategy.value}")

        # Handle mismatched lengths
        pv_arr = np.array(request.pv_generation_kwh)
        load_arr = np.array(request.load_kwh)

        if n_pv == 8760 or n_load == 8760:
            target_n = 8760
            hours_per_step = 1.0
        elif n_pv == 35040 or n_load == 35040:
            target_n = 35040
            hours_per_step = 0.25
        else:
            target_n = min(n_pv, n_load)
            if target_n > 8760:
                target_n = 8760
            hours_per_step = 1.0
            print(f"⚠️ Non-standard lengths, using {target_n} timesteps")

        # Resample arrays
        if n_pv != target_n:
            x_old = np.linspace(0, 1, n_pv)
            x_new = np.linspace(0, 1, target_n)
            pv_arr = np.interp(x_new, x_old, pv_arr)
            print(f"  → PV resampled from {n_pv} to {target_n}")

        if n_load != target_n:
            x_old = np.linspace(0, 1, n_load)
            x_new = np.linspace(0, 1, target_n)
            load_arr = np.interp(x_new, x_old, load_arr)
            print(f"  → Load resampled from {n_load} to {target_n}")

        pv_kwh = pv_arr
        load_kwh = load_arr

        # Basic calculations
        surplus = np.maximum(pv_kwh - load_kwh, 0)
        deficit = np.maximum(load_kwh - pv_kwh, 0)
        direct = np.minimum(pv_kwh, load_kwh)

        annual_pv = np.sum(pv_kwh) * hours_per_step / 1000
        annual_load = np.sum(load_kwh) * hours_per_step / 1000
        annual_surplus = np.sum(surplus) * hours_per_step / 1000
        annual_deficit = np.sum(deficit) * hours_per_step / 1000
        annual_direct = np.sum(direct) * hours_per_step / 1000

        # Hourly patterns
        hourly_patterns = analyze_hourly_patterns(pv_kwh, load_kwh, hours_per_step)

        # Generate heatmap
        heatmap_data = generate_heatmap(pv_kwh, load_kwh, hours_per_step)

        # Monthly analysis
        monthly_analysis = analyze_monthly(
            pv_kwh, load_kwh,
            request.bess_energy_kwh,
            request.bess_efficiency,
            hours_per_step
        )

        # Quarterly summary
        quarterly_cycles = {}
        quarterly_surplus = {}

        for q_name, months in [("Q1", [1,2,3]), ("Q2", [4,5,6]), ("Q3", [7,8,9]), ("Q4", [10,11,12])]:
            q_months = [m for m in monthly_analysis if m.month in months]
            quarterly_cycles[q_name] = sum(m.current_bess_cycles or 0 for m in q_months)
            quarterly_surplus[q_name] = sum(m.total_surplus_mwh for m in q_months)

        # Current BESS performance
        current_annual_cycles = None
        current_utilization = None
        current_curtailment_ratio = None

        if request.bess_energy_kwh and request.bess_energy_kwh > 0:
            current_annual_cycles = sum(m.current_bess_cycles or 0 for m in monthly_analysis)
            current_utilization = current_annual_cycles / 365 * 100

            usable = request.bess_energy_kwh * 0.8
            estimated_discharge = current_annual_cycles * usable / 1000
            if annual_surplus > 0:
                current_curtailment_ratio = 1 - (estimated_discharge / annual_surplus)

        # Generate Pareto frontier
        pareto_frontier = await generate_pareto_frontier(
            pv_kwh, load_kwh,
            monthly_analysis,
            request.pv_capacity_kwp,
            request.energy_price_plnmwh,
            request.bess_capex_per_kwh,
            request.bess_capex_per_kw,
            request.bess_efficiency,
            request.discount_rate,
            request.project_years,
            request.pareto_points
        )

        # Generate recommendations based on strategy
        bess_recommendations = calculate_bess_recommendations(
            monthly_analysis,
            pareto_frontier,
            request.strategy,
            request.pv_capacity_kwp,
            request.energy_price_plnmwh,
            request.bess_capex_per_kwh,
            request.bess_capex_per_kw,
            request.bess_efficiency,
            request.discount_rate,
            request.project_years,
            request.min_cycles_per_year,
            request.max_cycles_per_year
        )

        # Generate variant comparison
        variant_comparison = generate_variant_comparison(bess_recommendations, annual_surplus)

        # PV recommendations
        pv_recommendations = calculate_pv_recommendations(
            monthly_analysis,
            request.pv_capacity_kwp,
            request.bess_energy_kwh,
            request.bess_efficiency,
            request.energy_price_plnmwh
        )

        # Generate insights
        insights = generate_insights(
            monthly_analysis,
            quarterly_cycles,
            request.bess_energy_kwh,
            annual_surplus,
            annual_deficit,
            request.strategy,
            bess_recommendations
        )

        print(f"✓ Analysis complete: {len(pareto_frontier)} Pareto points, {len(bess_recommendations)} recommendations")

        return ProfileAnalysisResult(
            annual_pv_mwh=round(annual_pv, 2),
            annual_load_mwh=round(annual_load, 2),
            annual_surplus_mwh=round(annual_surplus, 2),
            annual_deficit_mwh=round(annual_deficit, 2),
            direct_consumption_mwh=round(annual_direct, 2),
            direct_consumption_pct=round(annual_direct / annual_pv * 100, 1) if annual_pv > 0 else 0,
            hourly_patterns=hourly_patterns,
            heatmap_data=heatmap_data,
            monthly_analysis=monthly_analysis,
            quarterly_cycles=quarterly_cycles,
            quarterly_surplus_mwh=quarterly_surplus,
            current_bess_annual_cycles=round(current_annual_cycles, 1) if current_annual_cycles else None,
            current_bess_utilization_pct=round(current_utilization, 1) if current_utilization else None,
            current_curtailment_ratio=round(current_curtailment_ratio, 2) if current_curtailment_ratio else None,
            selected_strategy=request.strategy.value,
            bess_recommendations=bess_recommendations,
            pareto_frontier=pareto_frontier,
            variant_comparison=variant_comparison,
            pv_recommendations=pv_recommendations,
            insights=insights
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Analysis failed: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8040)

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

# Prometheus metrics
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(
    title="Profile Analysis Service",
    description="Advanced PV+BESS profile analysis for optimal sizing v2.0",
    version="2.0.0"
)

# Initialize Prometheus metrics
Instrumentator().instrument(app).expose(app)

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

    # Timestamps for proper month mapping (ISO format strings)
    # IMPORTANT: Required to correctly assign data to calendar months
    # Analytical year may start from any month (e.g., July 2024 to June 2025)
    timestamps: Optional[List[str]] = Field(None, description="ISO timestamps for each hour")

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

    # BESS auxiliary losses and degradation parameters
    # Auxiliary losses: standby power consumption (% of capacity per day)
    # Typical values: 0.5-2% for Li-ion, represents BMS, cooling, etc.
    bess_auxiliary_loss_pct_per_day: float = Field(
        default=0.1,
        ge=0,
        le=5,
        description="BESS standby power consumption [% of capacity per day]"
    )
    # Degradation Year 1: higher initial capacity fade due to initial settling
    # Typical values: 2-5% for Li-ion first year
    # Note: le=50 to handle legacy data that may have wrong values stored
    bess_degradation_year1_pct: float = Field(
        default=3.0,
        ge=0,
        le=50,
        description="BESS first year capacity degradation [%]"
    )
    # Degradation Years 2+: annual capacity fade (% per year)
    # Typical values: 1-3% for Li-ion at moderate cycling
    bess_degradation_pct_per_year: float = Field(
        default=2.0,
        ge=0,
        le=50,
        description="BESS annual capacity degradation for years 2+ [% per year]"
    )

    # Optimization settings
    strategy: OptimizationStrategy = Field(default=OptimizationStrategy.BALANCED)
    min_cycles_per_year: int = Field(default=200, description="Minimum target cycles")
    max_cycles_per_year: int = Field(default=400, description="Maximum target cycles")

    # Pareto analysis
    pareto_points: int = Field(default=15, description="Number of Pareto points to calculate")

    # ============== Peak Shaving Parameters ==============
    # Peak shaving reduces demand charges by discharging BESS during high load
    peak_shaving_enabled: bool = Field(
        default=False,
        description="Enable peak shaving optimization"
    )
    peak_shaving_mode: str = Field(
        default="auto",
        description="Peak shaving mode: 'auto' (P95), 'manual', 'percentage'"
    )
    peak_shaving_target_kw: float = Field(
        default=0,
        ge=0,
        description="Target peak power [kW] for manual mode (0 = auto)"
    )
    peak_shaving_pct_reduction: float = Field(
        default=15,
        ge=0,
        le=50,
        description="Target % reduction from historical peak (for percentage mode)"
    )
    power_charge_pln_per_kw_month: float = Field(
        default=50,
        ge=0,
        description="Power demand charge [PLN/kW/month] for peak shaving savings"
    )

    # ============== Price Arbitrage Parameters ==============
    # Price arbitrage buys energy when cheap, sells when expensive
    price_arbitrage_enabled: bool = Field(
        default=False,
        description="Enable price arbitrage optimization"
    )
    price_arbitrage_source: str = Field(
        default="manual",
        description="Price source: 'manual', 'tge_api', 'csv_upload'"
    )
    price_arbitrage_buy_threshold: float = Field(
        default=300,
        ge=0,
        description="Buy energy when price below this threshold [PLN/MWh]"
    )
    price_arbitrage_sell_threshold: float = Field(
        default=600,
        ge=0,
        description="Sell energy when price above this threshold [PLN/MWh]"
    )
    price_arbitrage_spread: float = Field(
        default=100,
        ge=0,
        description="Minimum spread to trigger arbitrage [PLN/MWh]"
    )
    # Optional: hourly RDN prices (8760 values)
    rdn_prices_plnmwh: Optional[List[float]] = Field(
        None,
        description="Hourly RDN prices [PLN/MWh] for arbitrage optimization"
    )

    # ============== PyPSA Optimizer Integration (Kraken Protocol) ==============
    use_pypsa_optimizer: bool = Field(
        default=False,
        description="Use PyPSA + HiGHS LP optimizer instead of greedy simulation (Kraken Protocol)"
    )


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
    annual_discharge_mwh: float  # From real hourly simulation - single source of truth!
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


class BaselineVariant(BaseModel):
    """Baseline variant (without BESS)"""
    self_consumption_pct: float
    surplus_lost_mwh: float
    grid_import_mwh: float
    annual_energy_cost_pln: float


class RecommendedVariant(BaseModel):
    """Recommended BESS variant"""
    bess_power_kw: float
    bess_energy_kwh: float
    self_consumption_pct: float
    annual_cycles: float
    grid_import_mwh: float
    capex_pln: float
    annual_savings_pln: float
    npv_pln: float
    payback_years: float


class VariantComparisonResult(BaseModel):
    """Side-by-side variant comparison: baseline vs recommended"""
    baseline: BaselineVariant
    recommended: RecommendedVariant
    project_years: int


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
    current_bess_annual_discharge_mwh: Optional[float]  # From real hourly simulation
    current_bess_utilization_pct: Optional[float]
    current_curtailment_ratio: Optional[float]

    # Hourly BESS simulation data for CURRENT/FORM BESS (from form parameters)
    # These arrays have 8760 elements (hourly for full year)
    hourly_bess_charge: Optional[List[float]] = None  # kWh charged each hour
    hourly_bess_discharge: Optional[List[float]] = None  # kWh discharged each hour
    hourly_bess_soc: Optional[List[float]] = None  # SoC % at end of each hour

    # Hourly BESS simulation data for RECOMMENDED BESS (Best NPV from Pareto)
    # THIS IS THE SINGLE SOURCE OF TRUTH for EKONOMIA and Excel export!
    recommended_bess_power_kw: Optional[float] = None
    recommended_bess_energy_kwh: Optional[float] = None
    recommended_bess_annual_cycles: Optional[float] = None
    recommended_bess_annual_discharge_mwh: Optional[float] = None
    recommended_hourly_bess_charge: Optional[List[float]] = None
    recommended_hourly_bess_discharge: Optional[List[float]] = None
    recommended_hourly_bess_soc: Optional[List[float]] = None

    # BESS degradation and auxiliary parameters used in NPV calculation
    # (from Settings - centralized source of truth for all modules)
    bess_degradation_year1_pct: Optional[float] = None  # First year degradation (higher)
    bess_degradation_pct_per_year: Optional[float] = None  # Years 2+ degradation
    bess_auxiliary_loss_pct_per_day: Optional[float] = None
    bess_capacity_at_project_end_pct: Optional[float] = None  # Remaining capacity after degradation
    project_years: Optional[int] = None  # Project lifetime for UI display

    # Hourly PV and Load data for Excel export (8760 elements)
    # These are needed for complete hourly export with all columns
    hourly_pv_kwh: Optional[List[float]] = None
    hourly_load_kwh: Optional[List[float]] = None

    # ============== Peak Shaving Results ==============
    peak_shaving_enabled: bool = False
    peak_shaving_original_peak_kw: Optional[float] = None  # Original max demand
    peak_shaving_reduced_peak_kw: Optional[float] = None  # After BESS dispatch
    peak_shaving_reduction_pct: Optional[float] = None  # % reduction achieved
    peak_shaving_annual_savings_pln: Optional[float] = None  # PLN/year savings
    peak_shaving_npv_improvement_mln_pln: Optional[float] = None

    # ============== Price Arbitrage Results ==============
    price_arbitrage_enabled: bool = False
    price_arbitrage_buy_hours: Optional[int] = None  # Hours spent buying
    price_arbitrage_sell_hours: Optional[int] = None  # Hours spent selling
    price_arbitrage_avg_buy_price_pln: Optional[float] = None
    price_arbitrage_avg_sell_price_pln: Optional[float] = None
    price_arbitrage_spread_pln: Optional[float] = None  # Avg spread achieved
    price_arbitrage_annual_profit_pln: Optional[float] = None  # PLN/year profit
    price_arbitrage_npv_improvement_mln_pln: Optional[float] = None

    # Optimization results
    selected_strategy: str
    bess_recommendations: List[BessSizingRecommendation]
    pareto_frontier: List[ParetoPoint]
    variant_comparison: Optional[VariantComparisonResult] = None

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
    hours_per_step: float = 1.0,
    timestamps: Optional[List[str]] = None
) -> List[MonthlyAnalysis]:
    """Analyze patterns by month using actual timestamps if provided.

    IMPORTANT: If timestamps are provided, data is grouped by actual calendar months.
    This is critical because analytical year may start from any month (e.g., July 2024).
    Without timestamps, the function assumes data starts from January which may be wrong.
    """
    from datetime import datetime
    from collections import defaultdict

    month_names = ['Sty', 'Lut', 'Mar', 'Kwi', 'Maj', 'Cze',
                   'Lip', 'Sie', 'Wrz', 'Paź', 'Lis', 'Gru']

    # If timestamps provided, group by actual calendar months
    if timestamps and len(timestamps) == len(pv_kwh):
        # Parse timestamps and group data by month
        month_data = defaultdict(lambda: {'pv': [], 'load': [], 'days': set()})

        for i, ts_str in enumerate(timestamps):
            try:
                # Parse ISO timestamp (e.g., "2024-07-01T00:00:00")
                ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00').split('+')[0])
                month_num = ts.month  # 1-12
                day = ts.day
                month_data[month_num]['pv'].append(pv_kwh[i])
                month_data[month_num]['load'].append(load_kwh[i])
                month_data[month_num]['days'].add(day)
            except (ValueError, AttributeError):
                continue

        results = []
        # Iterate through months 1-12 (January to December)
        for month_num in range(1, 13):
            if month_num not in month_data:
                continue

            data = month_data[month_num]
            month_pv = np.array(data['pv'])
            month_load = np.array(data['load'])
            days = len(data['days'])

            if days == 0 or len(month_pv) == 0:
                continue

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
                month=month_num,
                month_name=month_names[month_num - 1],
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

        return results

    # Fallback: old logic (assumes data starts from January)
    days_per_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
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
    """Calculate Net Present Value (simple model without degradation)"""
    npv = -capex
    for year in range(1, project_years + 1):
        npv += annual_savings / ((1 + discount_rate) ** year)
    return npv


def calculate_npv_with_degradation(
    year1_discharge_kwh: float,
    bess_energy_kwh: float,
    energy_price_plnmwh: float,
    capex: float,
    discount_rate: float,
    project_years: int,
    degradation_year1_pct: float = 3.0,
    degradation_pct_per_year: float = 2.0,
    auxiliary_loss_pct_per_day: float = 0.1
) -> dict:
    """
    Calculate NPV with realistic BESS degradation and auxiliary losses.

    This is the advanced NPV model that accounts for:
    1. Battery degradation: two-phase model (year 1 higher, years 2+ lower)
    2. Auxiliary losses: standby power consumption (additional cost)

    Degradation model (matching economics.js for consistency):
    - Year 1: (1 - degradation_year1_pct/100)
    - Year N: (1 - degradation_year1_pct/100) * (1 - degradation_pct_per_year/100)^(N-1)

    Args:
        year1_discharge_kwh: First year annual discharge [kWh] from simulation
        bess_energy_kwh: Nominal BESS capacity [kWh]
        energy_price_plnmwh: Energy price [PLN/MWh]
        capex: Total CAPEX [PLN]
        discount_rate: Discount rate (e.g., 0.08 for 8%)
        project_years: Project lifetime [years]
        degradation_year1_pct: First year capacity fade [%] (higher due to initial settling)
        degradation_pct_per_year: Annual capacity fade for years 2+ [% per year]
        auxiliary_loss_pct_per_day: Standby power consumption [% of capacity per day]

    Returns:
        dict with:
            - npv: Net Present Value [PLN]
            - npv_mln_pln: NPV in millions [mln PLN]
            - total_savings: Total undiscounted savings [PLN]
            - total_auxiliary_cost: Total undiscounted auxiliary costs [PLN]
            - yearly_details: List of yearly breakdowns
            - effective_capacity_year_end: Capacity at end of project [%]
    """
    # Calculate annual auxiliary loss (converted to energy cost)
    # Auxiliary losses = % of capacity * 365 days * energy price
    annual_auxiliary_kwh = bess_energy_kwh * auxiliary_loss_pct_per_day / 100 * 365
    annual_auxiliary_cost_base = annual_auxiliary_kwh * energy_price_plnmwh / 1000  # PLN

    npv = -capex
    total_savings = 0.0
    total_auxiliary_cost = 0.0
    yearly_details = []

    for year in range(1, project_years + 1):
        # Calculate effective capacity using two-phase degradation model
        # Year 1: (1 - year1_deg)
        # Year N: (1 - year1_deg) * (1 - annual_deg)^(N-1)
        # This matches the economics.js model for consistency across portal
        if year == 1:
            effective_capacity_factor = 1 - degradation_year1_pct / 100
        else:
            effective_capacity_factor = (1 - degradation_year1_pct / 100) * \
                                        ((1 - degradation_pct_per_year / 100) ** (year - 1))

        effective_capacity_pct = effective_capacity_factor * 100
        effective_capacity_pct = max(effective_capacity_pct, 0)  # Can't go below 0

        # Discharge scales with remaining capacity
        year_discharge_kwh = year1_discharge_kwh * effective_capacity_factor

        # Savings from discharge
        year_savings = year_discharge_kwh * energy_price_plnmwh / 1000  # PLN

        # Auxiliary costs scale with capacity (smaller as battery degrades)
        year_auxiliary_cost = annual_auxiliary_cost_base * effective_capacity_factor

        # Net cash flow for the year
        year_net_cf = year_savings - year_auxiliary_cost

        # Discount to present value
        discount_factor = 1 / ((1 + discount_rate) ** year)
        npv += year_net_cf * discount_factor

        total_savings += year_savings
        total_auxiliary_cost += year_auxiliary_cost

        yearly_details.append({
            'year': year,
            'effective_capacity_pct': round(effective_capacity_pct, 1),
            'discharge_kwh': round(year_discharge_kwh, 0),
            'savings_pln': round(year_savings, 0),
            'auxiliary_cost_pln': round(year_auxiliary_cost, 0),
            'net_cf_pln': round(year_net_cf, 0),
            'discounted_cf_pln': round(year_net_cf * discount_factor, 0)
        })

    # Final capacity at end of project (using two-phase model)
    effective_capacity_year_end = (1 - degradation_year1_pct / 100) * \
                                   ((1 - degradation_pct_per_year / 100) ** (project_years - 1)) * 100
    effective_capacity_year_end = max(effective_capacity_year_end, 0)

    return {
        'npv': round(npv, 0),
        'npv_mln_pln': round(npv / 1e6, 3),
        'total_savings': round(total_savings, 0),
        'total_auxiliary_cost': round(total_auxiliary_cost, 0),
        'total_discharge_mwh': round(sum(d['discharge_kwh'] for d in yearly_details) / 1000, 1),
        'effective_capacity_year_end_pct': round(effective_capacity_year_end, 1),
        'yearly_details': yearly_details
    }


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


def simulate_bess_hourly(
    pv_kwh: np.ndarray,
    load_kwh: np.ndarray,
    bess_energy_kwh: float,
    bess_power_kw: float,
    efficiency: float,
    soc_min_pct: float = 10.0,
    soc_max_pct: float = 90.0
) -> dict:
    """
    Simulate BESS operation hour by hour with real SoC tracking.

    This is the accurate simulation that should be used for all calculations.
    It replaces the simplified statistical model that overestimates performance.

    Args:
        pv_kwh: Hourly PV generation array [kWh]
        load_kwh: Hourly load array [kWh]
        bess_energy_kwh: Total BESS capacity [kWh]
        bess_power_kw: Maximum charge/discharge power [kW]
        efficiency: Round-trip efficiency (e.g., 0.90 for 90%)
        soc_min_pct: Minimum SoC in % (default 10%)
        soc_max_pct: Maximum SoC in % (default 90%)

    Returns:
        dict with:
            - annual_charge_kwh: Total energy charged from surplus
            - annual_discharge_kwh: Total energy delivered to load
            - annual_cycles: Equivalent full cycles (discharge / usable_capacity)
            - hourly_charge: Array of hourly charge values
            - hourly_discharge: Array of hourly discharge values
            - hourly_soc: Array of hourly SoC values (%)
    """
    n_hours = len(pv_kwh)
    one_way_eff = np.sqrt(efficiency)

    # Usable capacity (DoD)
    usable_capacity = bess_energy_kwh * (soc_max_pct - soc_min_pct) / 100.0

    # Initialize arrays
    hourly_charge = np.zeros(n_hours)
    hourly_discharge = np.zeros(n_hours)
    hourly_soc = np.zeros(n_hours)

    # Start at middle SoC
    soc_pct = (soc_min_pct + soc_max_pct) / 2.0

    total_charge = 0.0
    total_discharge = 0.0

    for i in range(n_hours):
        surplus = max(0, pv_kwh[i] - load_kwh[i])
        deficit = max(0, load_kwh[i] - pv_kwh[i])

        charge = 0.0
        discharge = 0.0

        if surplus > 0 and soc_pct < soc_max_pct:
            # Charge from surplus
            # Available capacity in battery
            available_capacity_kwh = (soc_max_pct - soc_pct) / 100.0 * bess_energy_kwh
            # Maximum we can charge this hour (limited by power and surplus)
            max_charge_from_surplus = min(bess_power_kw, surplus)
            # Energy that will be stored (after charging losses)
            energy_to_store = min(max_charge_from_surplus * one_way_eff, available_capacity_kwh)
            # Energy taken from surplus
            charge = energy_to_store / one_way_eff if one_way_eff > 0 else 0
            # Update SoC
            soc_pct += energy_to_store / bess_energy_kwh * 100.0
            total_charge += charge

        elif deficit > 0 and soc_pct > soc_min_pct:
            # Discharge to cover deficit
            # Available energy in battery
            available_energy_kwh = (soc_pct - soc_min_pct) / 100.0 * bess_energy_kwh
            # Energy needed to cover deficit
            energy_needed = min(bess_power_kw, deficit)
            # Energy we need to extract from battery (to deliver energy_needed after losses)
            energy_from_battery = min(energy_needed / one_way_eff, available_energy_kwh) if one_way_eff > 0 else 0
            # What we actually deliver to load
            discharge = energy_from_battery * one_way_eff
            # Update SoC
            soc_pct -= energy_from_battery / bess_energy_kwh * 100.0
            total_discharge += discharge

        # Ensure SoC bounds
        soc_pct = max(soc_min_pct, min(soc_max_pct, soc_pct))

        hourly_charge[i] = charge
        hourly_discharge[i] = discharge
        hourly_soc[i] = soc_pct

    # Calculate equivalent cycles based on discharge
    annual_cycles = total_discharge / usable_capacity if usable_capacity > 0 else 0

    return {
        'annual_charge_kwh': total_charge,
        'annual_discharge_kwh': total_discharge,
        'annual_cycles': annual_cycles,
        'hourly_charge': hourly_charge,
        'hourly_discharge': hourly_discharge,
        'hourly_soc': hourly_soc
    }


# ============== Kraken Protocol: PyPSA + HiGHS Integration ==============

async def simulate_bess_universal(
    pv_kwh: np.ndarray,
    load_kwh: np.ndarray,
    bess_energy_kwh: float,
    bess_power_kw: float,
    efficiency: float,
    energy_price: float,
    pv_capacity: float,
    use_pypsa: bool = False,
    soc_min_pct: float = 10.0,
    soc_max_pct: float = 90.0
) -> dict:
    """
    Universal BESS simulation wrapper - Kraken Protocol.

    Chooses between:
    - Greedy simulation (fast, good approximation)
    - PyPSA + HiGHS LP optimization (slower, globally optimal)

    Args:
        pv_kwh: Hourly PV generation array [kWh]
        load_kwh: Hourly load array [kWh]
        bess_energy_kwh: Total BESS capacity [kWh]
        bess_power_kw: Maximum charge/discharge power [kW]
        efficiency: Round-trip efficiency (e.g., 0.90)
        energy_price: Energy price [PLN/MWh]
        pv_capacity: PV capacity [kWp]
        use_pypsa: If True, use PyPSA + HiGHS optimizer (Kraken Protocol)
        soc_min_pct: Minimum SoC in % (default 10%)
        soc_max_pct: Maximum SoC in % (default 90%)

    Returns:
        dict with simulation results (same format for both methods)
    """
    if use_pypsa:
        # 🐙 KRAKEN: Use PyPSA + HiGHS LP optimizer
        print(f"🐙 KRAKEN: Using PyPSA + HiGHS optimizer for BESS {bess_power_kw}kW/{bess_energy_kwh}kWh")

        try:
            optimizer_result = await call_bess_optimizer(
                pv_kwh=pv_kwh,
                load_kwh=load_kwh,
                pv_capacity=pv_capacity,
                energy_kwh=bess_energy_kwh,
                power_kw=bess_power_kw,
                efficiency=efficiency,
                energy_price=energy_price
            )

            if optimizer_result:
                # Convert optimizer result to our standard format
                usable_capacity = bess_energy_kwh * (soc_max_pct - soc_min_pct) / 100.0

                # Extract hourly data if available
                hourly_charge = np.zeros(len(pv_kwh))
                hourly_discharge = np.zeros(len(pv_kwh))
                hourly_soc = np.zeros(len(pv_kwh))

                if optimizer_result.get('hourly_charge_kw'):
                    hourly_charge = np.array(optimizer_result['hourly_charge_kw'])
                if optimizer_result.get('hourly_discharge_kw'):
                    hourly_discharge = np.array(optimizer_result['hourly_discharge_kw'])
                if optimizer_result.get('hourly_soc'):
                    hourly_soc = np.array(optimizer_result['hourly_soc']) * 100  # Convert to %

                annual_discharge = optimizer_result.get('annual_discharge_kwh', 0)
                annual_cycles = annual_discharge / usable_capacity if usable_capacity > 0 else 0

                print(f"🐙 KRAKEN: PyPSA result - {annual_discharge/1000:.1f} MWh discharge, {annual_cycles:.0f} cycles")
                print(f"🐙 KRAKEN: Solve time: {optimizer_result.get('solve_time_s', 0):.2f}s, Status: {optimizer_result.get('status', 'unknown')}")

                return {
                    'annual_charge_kwh': optimizer_result.get('annual_charge_kwh', 0),
                    'annual_discharge_kwh': annual_discharge,
                    'annual_cycles': annual_cycles,
                    'hourly_charge': hourly_charge,
                    'hourly_discharge': hourly_discharge,
                    'hourly_soc': hourly_soc,
                    'optimizer_used': 'pypsa_highs',
                    'solve_time_s': optimizer_result.get('solve_time_s', 0),
                    'optimizer_status': optimizer_result.get('status', 'unknown'),
                    'npv_from_optimizer': optimizer_result.get('npv_bess_pln', 0)
                }
            else:
                print("⚠️ KRAKEN: PyPSA optimizer failed, falling back to greedy simulation")

        except Exception as e:
            print(f"⚠️ KRAKEN: PyPSA optimizer error: {e}, falling back to greedy simulation")

    # Default: Use greedy simulation
    result = simulate_bess_hourly(
        pv_kwh=pv_kwh,
        load_kwh=load_kwh,
        bess_energy_kwh=bess_energy_kwh,
        bess_power_kw=bess_power_kw,
        efficiency=efficiency,
        soc_min_pct=soc_min_pct,
        soc_max_pct=soc_max_pct
    )
    result['optimizer_used'] = 'greedy'
    return result


# ============== Peak Shaving Functions ==============

def calculate_peak_shaving_target(
    load_kwh: np.ndarray,
    mode: str = "auto",
    manual_target_kw: float = 0,
    pct_reduction: float = 15
) -> float:
    """Calculate target peak power for peak shaving.

    Args:
        load_kwh: Hourly load array [kWh] (power in kW if hourly)
        mode: "auto" (P95), "manual", or "percentage"
        manual_target_kw: Manual target for "manual" mode
        pct_reduction: % reduction for "percentage" mode

    Returns:
        Target peak power [kW]
    """
    original_peak = float(np.max(load_kwh))

    if mode == "manual" and manual_target_kw > 0:
        return manual_target_kw
    elif mode == "percentage":
        return original_peak * (1 - pct_reduction / 100)
    else:  # auto = P95
        return float(np.percentile(load_kwh, 95))


def simulate_peak_shaving(
    load_kwh: np.ndarray,
    pv_kwh: np.ndarray,
    bess_energy_kwh: float,
    bess_power_kw: float,
    target_peak_kw: float,
    efficiency: float = 0.90,
    soc_min_pct: float = 10.0,
    soc_max_pct: float = 90.0
) -> dict:
    """
    Simulate BESS dispatch for peak shaving.

    Strategy:
    1. When net load (load - PV) > target_peak: discharge BESS to reduce peak
    2. When net load < target_peak and surplus exists: charge BESS
    3. Prioritize peak reduction over surplus absorption

    Args:
        load_kwh: Hourly load [kWh]
        pv_kwh: Hourly PV generation [kWh]
        bess_energy_kwh: Battery capacity [kWh]
        bess_power_kw: Max charge/discharge power [kW]
        target_peak_kw: Target maximum grid power [kW]
        efficiency: Round-trip efficiency
        soc_min_pct, soc_max_pct: SoC limits [%]

    Returns:
        dict with peak shaving results
    """
    n_hours = len(load_kwh)
    one_way_eff = np.sqrt(efficiency)

    # Initialize
    hourly_discharge = np.zeros(n_hours)
    hourly_charge = np.zeros(n_hours)
    hourly_grid_power = np.zeros(n_hours)
    soc_pct = (soc_min_pct + soc_max_pct) / 2.0

    original_peak = float(np.max(load_kwh))
    usable_capacity = bess_energy_kwh * (soc_max_pct - soc_min_pct) / 100.0

    total_discharge = 0.0
    total_charge = 0.0
    peak_events_shaved = 0

    for i in range(n_hours):
        net_load = load_kwh[i] - pv_kwh[i]  # Positive = drawing from grid
        surplus = max(0, -net_load)  # PV surplus
        deficit = max(0, net_load)  # Grid demand

        charge = 0.0
        discharge = 0.0

        # Peak shaving: discharge when deficit exceeds target
        if deficit > target_peak_kw and soc_pct > soc_min_pct:
            # How much to shave off
            needed_reduction = deficit - target_peak_kw
            # Available energy
            available_energy = (soc_pct - soc_min_pct) / 100.0 * bess_energy_kwh
            # Energy to extract (accounting for discharge losses)
            energy_from_battery = min(
                needed_reduction / one_way_eff,
                available_energy,
                bess_power_kw / one_way_eff
            )
            discharge = energy_from_battery * one_way_eff
            soc_pct -= energy_from_battery / bess_energy_kwh * 100.0
            total_discharge += discharge
            peak_events_shaved += 1

        # Charge from surplus when below target
        elif surplus > 0 and soc_pct < soc_max_pct:
            available_capacity = (soc_max_pct - soc_pct) / 100.0 * bess_energy_kwh
            max_charge = min(bess_power_kw, surplus)
            energy_to_store = min(max_charge * one_way_eff, available_capacity)
            charge = energy_to_store / one_way_eff if one_way_eff > 0 else 0
            soc_pct += energy_to_store / bess_energy_kwh * 100.0
            total_charge += charge

        # Also charge when load is below target (valley filling for next peak)
        elif deficit < target_peak_kw * 0.5 and soc_pct < soc_max_pct * 0.8:
            # Charge from grid during low-demand periods to prepare for peaks
            available_capacity = (soc_max_pct - soc_pct) / 100.0 * bess_energy_kwh
            grid_charge = min(bess_power_kw * 0.5, available_capacity / one_way_eff)
            energy_to_store = grid_charge * one_way_eff
            charge = grid_charge
            soc_pct += energy_to_store / bess_energy_kwh * 100.0
            total_charge += charge

        # Ensure bounds
        soc_pct = max(soc_min_pct, min(soc_max_pct, soc_pct))

        hourly_discharge[i] = discharge
        hourly_charge[i] = charge
        hourly_grid_power[i] = load_kwh[i] - pv_kwh[i] - discharge + charge

    # Results
    reduced_peak = float(np.max(np.maximum(hourly_grid_power, 0)))
    reduction_pct = (original_peak - reduced_peak) / original_peak * 100 if original_peak > 0 else 0
    cycles = total_discharge / usable_capacity if usable_capacity > 0 else 0

    return {
        'original_peak_kw': original_peak,
        'reduced_peak_kw': reduced_peak,
        'reduction_pct': reduction_pct,
        'annual_discharge_kwh': total_discharge,
        'annual_charge_kwh': total_charge,
        'annual_cycles': cycles,
        'peak_events_shaved': peak_events_shaved,
        'hourly_discharge': hourly_discharge,
        'hourly_charge': hourly_charge,
        'hourly_grid_power': hourly_grid_power
    }


# ============== Price Arbitrage Functions ==============

def generate_synthetic_rdn_prices(n_hours: int = 8760, base_price: float = 500) -> np.ndarray:
    """
    Generate synthetic hourly RDN prices with typical patterns.

    Price patterns:
    - Lower at night (22:00-06:00): base * 0.6-0.8
    - Higher during morning peak (07:00-09:00): base * 1.2-1.4
    - Higher during evening peak (17:00-21:00): base * 1.3-1.6
    - Seasonal variation: higher in winter
    - Random noise: ±15%

    Returns:
        Array of hourly prices [PLN/MWh]
    """
    prices = np.zeros(n_hours)

    for i in range(n_hours):
        hour_of_day = i % 24
        day_of_year = (i // 24) % 365

        # Base seasonal factor (higher in winter)
        # Winter (Nov-Feb): 1.2, Summer (May-Aug): 0.85
        if day_of_year < 60 or day_of_year > 305:  # Winter
            seasonal = 1.2
        elif 120 < day_of_year < 240:  # Summer
            seasonal = 0.85
        else:
            seasonal = 1.0

        # Hour-of-day factor
        if 22 <= hour_of_day or hour_of_day < 6:  # Night
            hourly = 0.7
        elif 7 <= hour_of_day < 10:  # Morning peak
            hourly = 1.3
        elif 17 <= hour_of_day < 22:  # Evening peak
            hourly = 1.5
        else:  # Midday
            hourly = 1.0

        # Random noise (±15%)
        noise = 1 + np.random.uniform(-0.15, 0.15)

        prices[i] = base_price * seasonal * hourly * noise

    return prices


def simulate_price_arbitrage(
    pv_kwh: np.ndarray,
    load_kwh: np.ndarray,
    prices_plnmwh: np.ndarray,
    bess_energy_kwh: float,
    bess_power_kw: float,
    buy_threshold: float = 300,
    sell_threshold: float = 600,
    efficiency: float = 0.90,
    soc_min_pct: float = 10.0,
    soc_max_pct: float = 90.0
) -> dict:
    """
    Simulate BESS dispatch for price arbitrage.

    Strategy:
    1. Buy (charge) when price < buy_threshold AND there's capacity
    2. Sell (discharge) when price > sell_threshold AND there's energy
    3. Also absorb PV surplus when available (as before)

    Returns:
        dict with arbitrage results
    """
    n_hours = len(pv_kwh)
    one_way_eff = np.sqrt(efficiency)

    # Initialize
    hourly_discharge = np.zeros(n_hours)
    hourly_charge = np.zeros(n_hours)
    hourly_arbitrage_profit = np.zeros(n_hours)
    soc_pct = (soc_min_pct + soc_max_pct) / 2.0

    usable_capacity = bess_energy_kwh * (soc_max_pct - soc_min_pct) / 100.0

    total_discharge = 0.0
    total_charge = 0.0
    total_arbitrage_profit = 0.0
    buy_hours = 0
    sell_hours = 0
    buy_prices_sum = 0.0
    sell_prices_sum = 0.0

    for i in range(n_hours):
        price = prices_plnmwh[i]
        surplus = max(0, pv_kwh[i] - load_kwh[i])
        deficit = max(0, load_kwh[i] - pv_kwh[i])

        charge = 0.0
        discharge = 0.0
        arbitrage_profit = 0.0

        # Arbitrage: sell when price is high
        if price > sell_threshold and soc_pct > soc_min_pct:
            available_energy = (soc_pct - soc_min_pct) / 100.0 * bess_energy_kwh
            energy_from_battery = min(bess_power_kw / one_way_eff, available_energy)
            discharge = energy_from_battery * one_way_eff
            soc_pct -= energy_from_battery / bess_energy_kwh * 100.0
            total_discharge += discharge
            # Profit = energy sold * price (in MWh, then PLN)
            arbitrage_profit = (discharge / 1000) * price
            sell_hours += 1
            sell_prices_sum += price

        # Arbitrage: buy when price is low
        elif price < buy_threshold and soc_pct < soc_max_pct:
            available_capacity = (soc_max_pct - soc_pct) / 100.0 * bess_energy_kwh
            max_charge = min(bess_power_kw, available_capacity / one_way_eff)
            energy_to_store = max_charge * one_way_eff
            charge = max_charge
            soc_pct += energy_to_store / bess_energy_kwh * 100.0
            total_charge += charge
            # Cost = energy bought * price (negative profit)
            arbitrage_profit = -(charge / 1000) * price
            buy_hours += 1
            buy_prices_sum += price

        # Also absorb PV surplus (free energy)
        elif surplus > 0 and soc_pct < soc_max_pct:
            available_capacity = (soc_max_pct - soc_pct) / 100.0 * bess_energy_kwh
            max_charge = min(bess_power_kw, surplus)
            energy_to_store = min(max_charge * one_way_eff, available_capacity)
            charge = energy_to_store / one_way_eff if one_way_eff > 0 else 0
            soc_pct += energy_to_store / bess_energy_kwh * 100.0
            total_charge += charge
            # No cost for PV surplus

        # Ensure bounds
        soc_pct = max(soc_min_pct, min(soc_max_pct, soc_pct))

        hourly_discharge[i] = discharge
        hourly_charge[i] = charge
        hourly_arbitrage_profit[i] = arbitrage_profit
        total_arbitrage_profit += arbitrage_profit

    # Calculate averages
    avg_buy_price = buy_prices_sum / buy_hours if buy_hours > 0 else 0
    avg_sell_price = sell_prices_sum / sell_hours if sell_hours > 0 else 0
    avg_spread = avg_sell_price - avg_buy_price

    cycles = total_discharge / usable_capacity if usable_capacity > 0 else 0

    return {
        'annual_discharge_kwh': total_discharge,
        'annual_charge_kwh': total_charge,
        'annual_cycles': cycles,
        'annual_profit_pln': total_arbitrage_profit,
        'buy_hours': buy_hours,
        'sell_hours': sell_hours,
        'avg_buy_price_pln': avg_buy_price,
        'avg_sell_price_pln': avg_sell_price,
        'avg_spread_pln': avg_spread,
        'hourly_discharge': hourly_discharge,
        'hourly_charge': hourly_charge,
        'hourly_arbitrage_profit': hourly_arbitrage_profit
    }


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
    n_points: int = 10,
    degradation_year1_pct: float = 3.0,
    degradation_pct_per_year: float = 2.0,
    auxiliary_loss_pct_per_day: float = 0.1
) -> List[ParetoPoint]:
    """Generate Pareto frontier of NPV vs Cycles using REAL hourly simulation.

    This function now uses simulate_bess_hourly() for accurate results instead of
    the simplified statistical model that overestimated performance by ~6x.

    BESS sizing range is now based on:
    1. Annual surplus energy (to capture more of available surplus)
    2. Hourly surplus distribution (peak hours need larger power)
    3. Theoretical max useful BESS = annual_surplus / target_cycles

    NPV calculation includes:
    - Battery degradation (capacity fade over years)
    - Auxiliary losses (standby power consumption)
    """

    # Calculate range of BESS sizes to explore
    avg_daily_surplus = np.mean([m.avg_daily_surplus_kwh for m in monthly_analysis])
    max_daily_surplus = max(m.avg_daily_surplus_kwh for m in monthly_analysis)

    # NEW: Calculate annual surplus from monthly data (in kWh)
    annual_surplus_kwh = sum(m.total_surplus_mwh * 1000 for m in monthly_analysis)

    # NEW: Analyze hourly surplus distribution for better power sizing
    surplus_per_hour = np.maximum(pv_kwh - load_kwh, 0)
    hours_with_surplus = np.sum(surplus_per_hour > 0)
    avg_surplus_when_positive = np.mean(surplus_per_hour[surplus_per_hour > 0]) if hours_with_surplus > 0 else 0
    max_hourly_surplus = np.max(surplus_per_hour)
    p95_hourly_surplus = np.percentile(surplus_per_hour[surplus_per_hour > 0], 95) if hours_with_surplus > 0 else 0

    print(f"📊 Pareto analysis inputs:")
    print(f"   Annual surplus: {annual_surplus_kwh/1000:.1f} MWh")
    print(f"   Hours with surplus: {hours_with_surplus}")
    print(f"   Avg surplus/hour (when positive): {avg_surplus_when_positive:.1f} kWh")
    print(f"   Max hourly surplus: {max_hourly_surplus:.1f} kWh")
    print(f"   P95 hourly surplus: {p95_hourly_surplus:.1f} kWh")

    # Energy range calculation (improved):
    # - Minimum: enough to store 0.3x of avg daily surplus (high cycle scenario)
    # - Maximum: enough to capture significant portion of annual surplus
    #   Target: 300 cycles/year means max useful = annual_surplus / 300
    #   But also limited by practical daily charging capacity

    min_energy = max(50, avg_daily_surplus * 0.3)

    # Maximum useful BESS based on annual surplus at ~250-300 cycles
    # Larger BESS means fewer cycles, so there's a practical upper limit
    max_useful_at_250_cycles = annual_surplus_kwh / 250 if annual_surplus_kwh > 0 else 200

    # Also consider peak day capacity (can charge multiple times per day)
    max_from_daily = max_daily_surplus * 2.0  # Allow 2x max daily surplus

    # Take the larger of the two approaches, but cap at reasonable multiple of PV capacity
    max_energy = max(
        min_energy * 3,
        max_useful_at_250_cycles,
        max_from_daily,
        max_daily_surplus * 1.5,  # Original fallback
        200  # Absolute minimum
    )

    # Cap at 3x PV capacity (rarely useful to go higher)
    max_energy = min(max_energy, pv_capacity * 3)

    print(f"   BESS range: {min_energy:.0f} - {max_energy:.0f} kWh")

    energy_range = np.linspace(min_energy, max_energy, n_points)

    pareto_points = []

    for energy_kwh in energy_range:
        # Allow smaller BESS for small PV installations
        if energy_kwh < 20:
            continue

        # Power sizing based on hourly surplus distribution:
        # - Power should be high enough to capture peak surplus hours
        # - But not so high that CAPEX becomes unreasonable
        # - Duration typically 2-4h for industrial BESS

        # Calculate power based on P95 surplus (captures most hours effectively)
        # This ensures power is adequate to charge from typical surplus
        power_from_surplus = min(p95_hourly_surplus, max_hourly_surplus * 0.8)

        # Duration 2-4h based on size
        if avg_daily_surplus > 0:
            duration_from_daily = energy_kwh / avg_daily_surplus
            duration = min(4, max(2, duration_from_daily))
        else:
            duration = 3

        # Take the higher of: power from duration OR power from surplus distribution
        power_kw = max(energy_kwh / duration, power_from_surplus * 0.8)

        # ============================================
        # USE REAL HOURLY SIMULATION (not statistical)
        # ============================================
        sim_result = simulate_bess_hourly(
            pv_kwh=pv_kwh,
            load_kwh=load_kwh,
            bess_energy_kwh=energy_kwh,
            bess_power_kw=power_kw,
            efficiency=efficiency,
            soc_min_pct=10.0,
            soc_max_pct=90.0
        )

        annual_cycles = sim_result['annual_cycles']
        annual_discharge = sim_result['annual_discharge_kwh']

        # Calculate economics with degradation and auxiliary losses
        capex = power_kw * capex_per_kw + energy_kwh * capex_per_kwh

        # Use advanced NPV calculation with degradation and auxiliary losses
        npv_result = calculate_npv_with_degradation(
            year1_discharge_kwh=annual_discharge,
            bess_energy_kwh=energy_kwh,
            energy_price_plnmwh=energy_price,
            capex=capex,
            discount_rate=discount_rate,
            project_years=project_years,
            degradation_year1_pct=degradation_year1_pct,
            degradation_pct_per_year=degradation_pct_per_year,
            auxiliary_loss_pct_per_day=auxiliary_loss_pct_per_day
        )
        npv = npv_result['npv']

        # Payback calculation (simplified - year 1 net savings)
        year1_savings = annual_discharge * energy_price / 1000
        annual_auxiliary_kwh = energy_kwh * auxiliary_loss_pct_per_day / 100 * 365
        year1_aux_cost = annual_auxiliary_kwh * energy_price / 1000
        year1_net = year1_savings - year1_aux_cost
        payback = capex / year1_net if year1_net > 0 else 99

        pareto_points.append(ParetoPoint(
            power_kw=round(power_kw, 0),
            energy_kwh=round(energy_kwh, 0),
            npv_mln_pln=round(npv / 1e6, 2),
            annual_cycles=round(annual_cycles, 1),
            annual_discharge_mwh=round(annual_discharge / 1000, 2),  # kWh -> MWh (Year 1)
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

    # Return None if no points available
    if not optimal:
        return None

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
    pv_kwh: np.ndarray,
    load_kwh: np.ndarray,
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
    """Generate BESS sizing recommendations based on strategy using REAL hourly simulation."""

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

        # ============================================
        # USE REAL HOURLY SIMULATION (not statistical)
        # ============================================
        sim_result = simulate_bess_hourly(
            pv_kwh=pv_kwh,
            load_kwh=load_kwh,
            bess_energy_kwh=energy,
            bess_power_kw=power,
            efficiency=bess_efficiency,
            soc_min_pct=10.0,
            soc_max_pct=90.0
        )

        annual_cycles = sim_result['annual_cycles']
        annual_discharge = sim_result['annual_discharge_kwh']
        annual_charge = sim_result['annual_charge_kwh']

        # Curtailment = surplus that couldn't be charged
        annual_curtailment = max(0, total_annual_surplus - annual_charge)

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
            estimated_annual_cycles=round(annual_cycles, 1),
            estimated_annual_discharge_mwh=round(annual_discharge / 1000, 2),
            estimated_curtailment_mwh=round(annual_curtailment / 1000, 2),
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
    annual_surplus_mwh: float,
    annual_deficit_mwh: float,
    annual_pv_mwh: float,
    annual_load_mwh: float,
    energy_price_pln_per_mwh: float,
    project_years: int
) -> Optional[VariantComparisonResult]:
    """Generate side-by-side variant comparison: baseline vs recommended BESS"""

    if not recommendations:
        return None

    # Find recommended variant (pareto optimal with best NPV)
    pareto_recs = [r for r in recommendations if r.pareto_optimal]
    if not pareto_recs:
        pareto_recs = recommendations

    recommended_rec = max(pareto_recs, key=lambda r: r.npv_pln)

    # Calculate baseline (without BESS)
    direct_consumption = min(annual_pv_mwh, annual_load_mwh) - annual_surplus_mwh + min(annual_surplus_mwh, 0)
    # Simplified: direct consumption = PV - surplus (what's used directly)
    direct_consumption = annual_pv_mwh - annual_surplus_mwh
    baseline_self_consumption_pct = (direct_consumption / annual_pv_mwh * 100) if annual_pv_mwh > 0 else 0
    baseline_grid_import = annual_deficit_mwh
    baseline_annual_cost = baseline_grid_import * energy_price_pln_per_mwh

    baseline = BaselineVariant(
        self_consumption_pct=round(baseline_self_consumption_pct, 1),
        surplus_lost_mwh=round(annual_surplus_mwh, 2),
        grid_import_mwh=round(baseline_grid_import, 2),
        annual_energy_cost_pln=round(baseline_annual_cost, 0)
    )

    # Calculate recommended variant metrics
    # BESS captures part of surplus and reduces grid import
    bess_annual_throughput = recommended_rec.estimated_annual_cycles * recommended_rec.energy_kwh / 1000  # MWh
    energy_shifted = min(bess_annual_throughput * 0.9, annual_surplus_mwh)  # 90% efficiency

    recommended_self_consumption_pct = baseline_self_consumption_pct + (energy_shifted / annual_pv_mwh * 100) if annual_pv_mwh > 0 else 0
    recommended_grid_import = max(0, baseline_grid_import - energy_shifted)

    recommended = RecommendedVariant(
        bess_power_kw=recommended_rec.power_kw,
        bess_energy_kwh=recommended_rec.energy_kwh,
        self_consumption_pct=round(min(recommended_self_consumption_pct, 100), 1),
        annual_cycles=round(recommended_rec.estimated_annual_cycles, 0),
        grid_import_mwh=round(recommended_grid_import, 2),
        capex_pln=round(recommended_rec.capex_pln, 0),
        annual_savings_pln=round(recommended_rec.annual_savings_pln, 0),
        npv_pln=round(recommended_rec.npv_pln, 0),
        payback_years=round(recommended_rec.simple_payback_years, 1)
    )

    return VariantComparisonResult(
        baseline=baseline,
        recommended=recommended,
        project_years=project_years
    )


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

        print(f"📊 Energy balance:")
        print(f"   Annual PV: {annual_pv:.1f} MWh")
        print(f"   Annual Load: {annual_load:.1f} MWh")
        print(f"   Annual Direct (PV self-consumed): {annual_direct:.1f} MWh")
        print(f"   Annual Surplus (PV exported): {annual_surplus:.1f} MWh")

        # Hourly patterns
        hourly_patterns = analyze_hourly_patterns(pv_kwh, load_kwh, hours_per_step)

        # Generate heatmap
        heatmap_data = generate_heatmap(pv_kwh, load_kwh, hours_per_step)

        # Monthly analysis (pass timestamps for correct month mapping)
        monthly_analysis = analyze_monthly(
            pv_kwh, load_kwh,
            request.bess_energy_kwh,
            request.bess_efficiency,
            hours_per_step,
            timestamps=request.timestamps
        )

        # Quarterly summary - surplus from monthly analysis (this is correct)
        quarterly_surplus = {}
        for q_name, months in [("Q1", [1,2,3]), ("Q2", [4,5,6]), ("Q3", [7,8,9]), ("Q4", [10,11,12])]:
            q_months = [m for m in monthly_analysis if m.month in months]
            quarterly_surplus[q_name] = sum(m.total_surplus_mwh for m in q_months)

        # quarterly_cycles will be calculated later from real hourly simulation
        quarterly_cycles = {"Q1": 0, "Q2": 0, "Q3": 0, "Q4": 0}

        # Current BESS performance - using REAL hourly simulation
        current_annual_cycles = None
        current_utilization = None
        current_curtailment_ratio = None
        current_annual_discharge_mwh = None

        # Hourly BESS data for Excel export (single source of truth)
        hourly_bess_charge = None
        hourly_bess_discharge = None
        hourly_bess_soc = None

        if request.bess_energy_kwh and request.bess_energy_kwh > 0:
            # 🐙 KRAKEN: Use PyPSA optimizer if enabled, otherwise greedy simulation
            current_bess_sim = await simulate_bess_universal(
                pv_kwh=pv_kwh,
                load_kwh=load_kwh,
                bess_energy_kwh=request.bess_energy_kwh,
                bess_power_kw=request.bess_power_kw,
                efficiency=request.bess_efficiency,
                energy_price=request.energy_price_plnmwh,
                pv_capacity=request.pv_capacity_kwp,
                use_pypsa=request.use_pypsa_optimizer
            )
            current_annual_cycles = current_bess_sim['annual_cycles']
            current_annual_discharge_mwh = current_bess_sim['annual_discharge_kwh'] / 1000
            current_utilization = current_annual_cycles / 365 * 100

            # Store hourly data for Excel export (single source of truth!)
            # Round to 2 decimals to reduce JSON size
            hourly_bess_charge = [round(x, 2) for x in current_bess_sim['hourly_charge'].tolist()]
            hourly_bess_discharge = [round(x, 2) for x in current_bess_sim['hourly_discharge'].tolist()]
            hourly_bess_soc = [round(x, 1) for x in current_bess_sim['hourly_soc'].tolist()]

            if annual_surplus > 0:
                current_curtailment_ratio = 1 - (current_annual_discharge_mwh / annual_surplus)

            # Calculate quarterly cycles from hourly simulation data
            hourly_discharge = current_bess_sim['hourly_discharge']
            usable_capacity = request.bess_energy_kwh * 0.8  # 80% DoD

            # Quarter definitions (hour ranges for 8760 hours)
            # Q1: Jan-Mar (hours 0-2159), Q2: Apr-Jun (2160-4343), Q3: Jul-Sep (4344-6551), Q4: Oct-Dec (6552-8759)
            # Using approximate hours per quarter (31+28+31=90, 30+31+30=91, 31+31+30=92, 31+30+31=92 days)
            q_hours = {
                "Q1": (0, 90*24),           # Jan-Mar
                "Q2": (90*24, 181*24),      # Apr-Jun
                "Q3": (181*24, 273*24),     # Jul-Sep
                "Q4": (273*24, 365*24)      # Oct-Dec
            }
            for q_name, (start_h, end_h) in q_hours.items():
                end_h = min(end_h, len(hourly_discharge))
                q_discharge = np.sum(hourly_discharge[start_h:end_h])
                quarterly_cycles[q_name] = q_discharge / usable_capacity if usable_capacity > 0 else 0

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
            request.pareto_points,
            request.bess_degradation_year1_pct,
            request.bess_degradation_pct_per_year,
            request.bess_auxiliary_loss_pct_per_day
        )

        # ============================================================
        # SIMULATE RECOMMENDED BESS (Best NPV from Pareto)
        # This is the SINGLE SOURCE OF TRUTH for EKONOMIA and Excel!
        # ============================================================
        recommended_bess_power_kw = None
        recommended_bess_energy_kwh = None
        recommended_bess_annual_cycles = None
        recommended_bess_annual_discharge_mwh = None
        recommended_hourly_charge = None
        recommended_hourly_discharge = None
        recommended_hourly_soc = None

        if pareto_frontier:
            # Find Best NPV point from Pareto frontier
            best_npv_point = max(pareto_frontier, key=lambda p: p.npv_mln_pln)
            print(f"📊 Best NPV from Pareto: {best_npv_point.npv_mln_pln:.2f} mln PLN, "
                  f"{best_npv_point.power_kw:.0f} kW / {best_npv_point.energy_kwh:.0f} kWh")

            # 🐙 KRAKEN: Run hourly simulation for recommended BESS
            recommended_sim = await simulate_bess_universal(
                pv_kwh=pv_kwh,
                load_kwh=load_kwh,
                bess_energy_kwh=best_npv_point.energy_kwh,
                bess_power_kw=best_npv_point.power_kw,
                efficiency=request.bess_efficiency,
                energy_price=request.energy_price_plnmwh,
                pv_capacity=request.pv_capacity_kwp,
                use_pypsa=request.use_pypsa_optimizer
            )

            recommended_bess_power_kw = best_npv_point.power_kw
            recommended_bess_energy_kwh = best_npv_point.energy_kwh
            recommended_bess_annual_cycles = recommended_sim['annual_cycles']
            recommended_bess_annual_discharge_mwh = recommended_sim['annual_discharge_kwh'] / 1000

            # Store hourly data for Excel export (rounded to reduce JSON size)
            recommended_hourly_charge = [round(x, 2) for x in recommended_sim['hourly_charge'].tolist()]
            recommended_hourly_discharge = [round(x, 2) for x in recommended_sim['hourly_discharge'].tolist()]
            recommended_hourly_soc = [round(x, 1) for x in recommended_sim['hourly_soc'].tolist()]

            print(f"✅ Recommended BESS simulation: {recommended_bess_annual_discharge_mwh:.2f} MWh/year, "
                  f"{recommended_bess_annual_cycles:.1f} cycles")

        # Generate recommendations based on strategy (using hourly simulation)
        bess_recommendations = calculate_bess_recommendations(
            pv_kwh,
            load_kwh,
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
        variant_comparison = generate_variant_comparison(
            bess_recommendations,
            annual_surplus,
            annual_deficit,
            annual_pv,
            annual_load,
            request.energy_price_plnmwh,
            request.project_years
        )

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

        # ============== Peak Shaving Analysis ==============
        peak_shaving_results = None
        if request.peak_shaving_enabled and recommended_bess_energy_kwh:
            print(f"📉 Running Peak Shaving analysis...")
            # Calculate target peak
            target_peak = calculate_peak_shaving_target(
                load_kwh,
                mode=request.peak_shaving_mode,
                manual_target_kw=request.peak_shaving_target_kw,
                pct_reduction=request.peak_shaving_pct_reduction
            )
            # Run simulation
            peak_shaving_results = simulate_peak_shaving(
                load_kwh=load_kwh,
                pv_kwh=pv_kwh,
                bess_energy_kwh=recommended_bess_energy_kwh,
                bess_power_kw=recommended_bess_power_kw,
                target_peak_kw=target_peak,
                efficiency=request.bess_efficiency
            )
            # Calculate annual savings
            power_reduction_kw = peak_shaving_results['original_peak_kw'] - peak_shaving_results['reduced_peak_kw']
            annual_savings_pln = power_reduction_kw * request.power_charge_pln_per_kw_month * 12
            peak_shaving_results['annual_savings_pln'] = annual_savings_pln
            # NPV improvement (simplified: savings * project_years * discount factor)
            avg_discount = sum(1 / (1 + request.discount_rate) ** y for y in range(1, request.project_years + 1)) / request.project_years
            peak_shaving_results['npv_improvement_mln_pln'] = annual_savings_pln * request.project_years * avg_discount / 1_000_000

            print(f"   Original peak: {peak_shaving_results['original_peak_kw']:.0f} kW")
            print(f"   Reduced peak: {peak_shaving_results['reduced_peak_kw']:.0f} kW ({peak_shaving_results['reduction_pct']:.1f}% reduction)")
            print(f"   Annual savings: {annual_savings_pln:,.0f} PLN")

        # ============== Price Arbitrage Analysis ==============
        arbitrage_results = None
        if request.price_arbitrage_enabled and recommended_bess_energy_kwh:
            print(f"💹 Running Price Arbitrage analysis...")
            # Get or generate prices
            if request.rdn_prices_plnmwh and len(request.rdn_prices_plnmwh) >= len(pv_kwh):
                prices = np.array(request.rdn_prices_plnmwh[:len(pv_kwh)])
            else:
                # Generate synthetic prices based on typical RDN patterns
                prices = generate_synthetic_rdn_prices(
                    n_hours=len(pv_kwh),
                    base_price=request.energy_price_plnmwh
                )
                print(f"   Using synthetic RDN prices (base: {request.energy_price_plnmwh} PLN/MWh)")

            arbitrage_results = simulate_price_arbitrage(
                pv_kwh=pv_kwh,
                load_kwh=load_kwh,
                prices_plnmwh=prices,
                bess_energy_kwh=recommended_bess_energy_kwh,
                bess_power_kw=recommended_bess_power_kw,
                buy_threshold=request.price_arbitrage_buy_threshold,
                sell_threshold=request.price_arbitrage_sell_threshold,
                efficiency=request.bess_efficiency
            )
            # NPV improvement
            avg_discount = sum(1 / (1 + request.discount_rate) ** y for y in range(1, request.project_years + 1)) / request.project_years
            arbitrage_results['npv_improvement_mln_pln'] = arbitrage_results['annual_profit_pln'] * request.project_years * avg_discount / 1_000_000

            print(f"   Buy hours: {arbitrage_results['buy_hours']}, Sell hours: {arbitrage_results['sell_hours']}")
            print(f"   Avg spread: {arbitrage_results['avg_spread_pln']:.0f} PLN/MWh")
            print(f"   Annual profit: {arbitrage_results['annual_profit_pln']:,.0f} PLN")

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
            current_bess_annual_discharge_mwh=round(current_annual_discharge_mwh, 2) if current_annual_discharge_mwh else None,
            current_bess_utilization_pct=round(current_utilization, 1) if current_utilization else None,
            current_curtailment_ratio=round(current_curtailment_ratio, 2) if current_curtailment_ratio else None,
            # Hourly BESS data for FORM BESS (from request parameters)
            hourly_bess_charge=hourly_bess_charge,
            hourly_bess_discharge=hourly_bess_discharge,
            hourly_bess_soc=hourly_bess_soc,
            # RECOMMENDED BESS data (Best NPV from Pareto) - SINGLE SOURCE OF TRUTH!
            recommended_bess_power_kw=round(recommended_bess_power_kw, 0) if recommended_bess_power_kw else None,
            recommended_bess_energy_kwh=round(recommended_bess_energy_kwh, 0) if recommended_bess_energy_kwh else None,
            recommended_bess_annual_cycles=round(recommended_bess_annual_cycles, 1) if recommended_bess_annual_cycles else None,
            recommended_bess_annual_discharge_mwh=round(recommended_bess_annual_discharge_mwh, 3) if recommended_bess_annual_discharge_mwh else None,
            recommended_hourly_bess_charge=recommended_hourly_charge,
            recommended_hourly_bess_discharge=recommended_hourly_discharge,
            recommended_hourly_bess_soc=recommended_hourly_soc,
            # Degradation and auxiliary parameters (from Settings - centralized)
            bess_degradation_year1_pct=request.bess_degradation_year1_pct,
            bess_degradation_pct_per_year=request.bess_degradation_pct_per_year,
            bess_auxiliary_loss_pct_per_day=request.bess_auxiliary_loss_pct_per_day,
            # Calculate end-of-project capacity using two-phase degradation model
            # Year 1: (1 - year1_deg), then Years 2+: compound degradation
            bess_capacity_at_project_end_pct=round(
                (1 - request.bess_degradation_year1_pct / 100) *
                ((1 - request.bess_degradation_pct_per_year / 100) ** (request.project_years - 1)) * 100,
                1
            ),
            project_years=request.project_years,
            selected_strategy=request.strategy.value,
            bess_recommendations=bess_recommendations,
            pareto_frontier=pareto_frontier,
            variant_comparison=variant_comparison,
            pv_recommendations=pv_recommendations,
            insights=insights,
            # Hourly PV and Load data for Excel export
            hourly_pv_kwh=[round(x, 2) for x in pv_kwh.tolist()],
            hourly_load_kwh=[round(x, 2) for x in load_kwh.tolist()],
            # Peak Shaving results
            peak_shaving_enabled=request.peak_shaving_enabled,
            peak_shaving_original_peak_kw=round(peak_shaving_results['original_peak_kw'], 0) if peak_shaving_results else None,
            peak_shaving_reduced_peak_kw=round(peak_shaving_results['reduced_peak_kw'], 0) if peak_shaving_results else None,
            peak_shaving_reduction_pct=round(peak_shaving_results['reduction_pct'], 1) if peak_shaving_results else None,
            peak_shaving_annual_savings_pln=round(peak_shaving_results['annual_savings_pln'], 0) if peak_shaving_results else None,
            peak_shaving_npv_improvement_mln_pln=round(peak_shaving_results['npv_improvement_mln_pln'], 3) if peak_shaving_results else None,
            # Price Arbitrage results
            price_arbitrage_enabled=request.price_arbitrage_enabled,
            price_arbitrage_buy_hours=arbitrage_results['buy_hours'] if arbitrage_results else None,
            price_arbitrage_sell_hours=arbitrage_results['sell_hours'] if arbitrage_results else None,
            price_arbitrage_avg_buy_price_pln=round(arbitrage_results['avg_buy_price_pln'], 0) if arbitrage_results else None,
            price_arbitrage_avg_sell_price_pln=round(arbitrage_results['avg_sell_price_pln'], 0) if arbitrage_results else None,
            price_arbitrage_spread_pln=round(arbitrage_results['avg_spread_pln'], 0) if arbitrage_results else None,
            price_arbitrage_annual_profit_pln=round(arbitrage_results['annual_profit_pln'], 0) if arbitrage_results else None,
            price_arbitrage_npv_improvement_mln_pln=round(arbitrage_results['npv_improvement_mln_pln'], 3) if arbitrage_results else None
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Analysis failed: {str(e)}")


# ============================================================================
# RDN DYNAMIC PRICING - HOURLY SAVINGS ANALYSIS
# ============================================================================

class RdnSavingsRequest(BaseModel):
    """Request for RDN hourly savings calculation"""
    pv_generation_kwh: List[float] = Field(..., description="Hourly PV generation [kWh]")
    load_kwh: List[float] = Field(..., description="Hourly consumption [kWh]")
    rdn_prices_plnmwh: List[float] = Field(..., description="Hourly RDN energy prices [PLN/MWh]")

    # Fixed network charges (PLN/MWh) - don't vary hourly
    distribution_plnmwh: float = Field(default=200)
    quality_fee_plnmwh: float = Field(default=10)
    oze_fee_plnmwh: float = Field(default=7)
    cogeneration_fee_plnmwh: float = Field(default=10)
    capacity_fee_plnmwh: float = Field(default=219)
    excise_tax_plnmwh: float = Field(default=5)

    # Fixed tariff rate for comparison
    fixed_energy_active_plnmwh: float = Field(default=510, description="Flat energy active rate [PLN/MWh]")

    # Optional timestamps for month mapping
    timestamps: Optional[List[str]] = None


class RdnMonthlyComparison(BaseModel):
    month: int
    rdn_savings_pln: float
    fixed_savings_pln: float
    rdn_avg_price_plnmwh: float
    self_consumed_kwh: float


class RdnSavingsResult(BaseModel):
    # Annual aggregates
    annual_self_consumed_kwh: float
    annual_surplus_kwh: float
    annual_deficit_kwh: float
    annual_production_kwh: float
    annual_consumption_kwh: float

    # RDN savings
    rdn_annual_savings_pln: float
    rdn_avg_effective_price_plnmwh: float  # Weighted avg during self-consumption hours

    # Fixed tariff savings (comparison)
    fixed_annual_savings_pln: float
    fixed_total_price_plnmwh: float

    # Comparison
    rdn_vs_fixed_delta_pln: float
    rdn_vs_fixed_delta_pct: float

    # Price statistics during self-consumption
    rdn_price_stats: dict  # avg, min, max, median, std

    # Monthly breakdown
    monthly_comparison: List[RdnMonthlyComparison]

    # RDN scenario info
    rdn_prices_count: int
    rdn_overall_avg_price: float


@app.post("/analyze-rdn-savings", response_model=RdnSavingsResult)
async def analyze_rdn_savings(request: RdnSavingsRequest):
    """
    Calculate savings with RDN dynamic prices vs fixed tariff.

    For each hour h:
      total_rdn_price[h] = rdn_price[h] + distribution + quality + oze + cogeneration + capacity + excise
      self_consumed[h] = min(pv[h], load[h])
      rdn_savings[h] = self_consumed[h] * total_rdn_price[h] / 1000  (kWh * PLN/MWh / 1000 = PLN)

    Fixed comparison:
      total_fixed_price = fixed_energy_active + all_fixed_charges
      fixed_savings = sum(self_consumed) * total_fixed_price / 1000
    """
    pv = np.array(request.pv_generation_kwh, dtype=float)
    load = np.array(request.load_kwh, dtype=float)
    rdn = np.array(request.rdn_prices_plnmwh, dtype=float)

    # Ensure same length
    n = min(len(pv), len(load), len(rdn))
    if n < 720:
        raise HTTPException(400, f"Insufficient data: {n} hours (need ≥720)")
    pv, load, rdn = pv[:n], load[:n], rdn[:n]

    print(f"💰 RDN Analysis: {n} hours, avg RDN price={np.mean(rdn):.1f} PLN/MWh")

    # Hour-by-hour energy balance
    self_consumed = np.minimum(pv, load)
    surplus = np.maximum(pv - load, 0)
    deficit = np.maximum(load - pv, 0)

    # Fixed charges sum
    fixed_charges = (request.distribution_plnmwh + request.quality_fee_plnmwh +
                     request.oze_fee_plnmwh + request.cogeneration_fee_plnmwh +
                     request.capacity_fee_plnmwh + request.excise_tax_plnmwh)

    # RDN: total price per hour = rdn_energy[h] + fixed_charges
    total_rdn_price = rdn + fixed_charges  # PLN/MWh per hour

    # Hourly savings: self_consumed[h] * total_rdn_price[h] / 1000
    hourly_rdn_savings = self_consumed * total_rdn_price / 1000  # PLN
    rdn_annual = float(np.sum(hourly_rdn_savings))

    # Fixed tariff comparison
    total_fixed_price = request.fixed_energy_active_plnmwh + fixed_charges
    annual_self_consumed = float(np.sum(self_consumed))
    fixed_annual = annual_self_consumed * total_fixed_price / 1000  # PLN

    # Weighted average RDN price during self-consumption hours
    mask = self_consumed > 0.1  # >0.1 kWh to avoid noise
    if mask.any():
        rdn_weighted_avg = float(np.average(total_rdn_price[mask], weights=self_consumed[mask]))
    else:
        rdn_weighted_avg = float(np.mean(total_rdn_price))

    # Price statistics during self-consumption
    if mask.any():
        rdn_during_sc = rdn[mask]
        price_stats = {
            "avg": float(np.mean(rdn_during_sc)),
            "min": float(np.min(rdn_during_sc)),
            "max": float(np.max(rdn_during_sc)),
            "median": float(np.median(rdn_during_sc)),
            "std": float(np.std(rdn_during_sc))
        }
    else:
        price_stats = {"avg": 0, "min": 0, "max": 0, "median": 0, "std": 0}

    # Monthly breakdown
    # Determine month boundaries from timestamps or assume calendar year
    month_days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    # Adjust for data length (might be leap year or partial year)
    total_days = n // 24
    if total_days >= 366:
        month_days[1] = 29  # leap year

    monthly_comparison = []
    hour_offset = 0
    for month_idx in range(12):
        days_in_month = month_days[month_idx]
        hours_in_month = days_in_month * 24
        end_h = min(hour_offset + hours_in_month, n)

        if hour_offset >= n:
            # Pad remaining months with zeros
            monthly_comparison.append(RdnMonthlyComparison(
                month=month_idx + 1, rdn_savings_pln=0, fixed_savings_pln=0,
                rdn_avg_price_plnmwh=0, self_consumed_kwh=0
            ))
            continue

        m_self = self_consumed[hour_offset:end_h]
        m_rdn_savings = hourly_rdn_savings[hour_offset:end_h]
        m_rdn_prices = rdn[hour_offset:end_h]
        m_fixed_savings = float(np.sum(m_self)) * total_fixed_price / 1000

        m_mask = m_self > 0.1
        m_avg_rdn = float(np.average(m_rdn_prices[m_mask], weights=m_self[m_mask])) if m_mask.any() else float(np.mean(m_rdn_prices))

        monthly_comparison.append(RdnMonthlyComparison(
            month=month_idx + 1,
            rdn_savings_pln=round(float(np.sum(m_rdn_savings)), 2),
            fixed_savings_pln=round(m_fixed_savings, 2),
            rdn_avg_price_plnmwh=round(m_avg_rdn, 1),
            self_consumed_kwh=round(float(np.sum(m_self)), 1)
        ))

        hour_offset = end_h

    # Delta
    delta_pln = rdn_annual - fixed_annual
    delta_pct = (delta_pln / fixed_annual * 100) if fixed_annual > 0 else 0

    print(f"💰 RDN Result: RDN savings={rdn_annual:.0f} PLN, Fixed savings={fixed_annual:.0f} PLN, Delta={delta_pln:+.0f} PLN ({delta_pct:+.1f}%)")

    return RdnSavingsResult(
        annual_self_consumed_kwh=round(annual_self_consumed, 1),
        annual_surplus_kwh=round(float(np.sum(surplus)), 1),
        annual_deficit_kwh=round(float(np.sum(deficit)), 1),
        annual_production_kwh=round(float(np.sum(pv)), 1),
        annual_consumption_kwh=round(float(np.sum(load)), 1),
        rdn_annual_savings_pln=round(rdn_annual, 2),
        rdn_avg_effective_price_plnmwh=round(rdn_weighted_avg, 1),
        fixed_annual_savings_pln=round(fixed_annual, 2),
        fixed_total_price_plnmwh=round(total_fixed_price, 1),
        rdn_vs_fixed_delta_pln=round(delta_pln, 2),
        rdn_vs_fixed_delta_pct=round(delta_pct, 1),
        rdn_price_stats=price_stats,
        monthly_comparison=monthly_comparison,
        rdn_prices_count=n,
        rdn_overall_avg_price=round(float(np.mean(rdn)), 1)
    )


# ============================================================================
# TCSL — TOTAL COST TO SERVE LOAD (Unified Cost Engine)
# ============================================================================

# Polish public holidays by year (used for K-class capacity fee calculation)
POLISH_HOLIDAYS = {
    2024: {
        "2024-01-01", "2024-01-06", "2024-03-31", "2024-04-01",
        "2024-05-01", "2024-05-03", "2024-05-30", "2024-06-20",
        "2024-08-15", "2024-11-01", "2024-11-11", "2024-12-25", "2024-12-26"
    },
    2025: {
        "2025-01-01", "2025-01-06", "2025-04-20", "2025-04-21",
        "2025-05-01", "2025-05-03", "2025-06-08", "2025-06-19",
        "2025-08-15", "2025-11-01", "2025-11-11", "2025-12-25", "2025-12-26"
    },
    2026: {
        "2026-01-01", "2026-01-06", "2026-04-05", "2026-04-06",
        "2026-05-01", "2026-05-03", "2026-05-24", "2026-06-04",
        "2026-08-15", "2026-11-01", "2026-11-11", "2026-12-25", "2026-12-26"
    },
    2027: {
        "2027-01-01", "2027-01-06", "2027-03-28", "2027-03-29",
        "2027-05-01", "2027-05-03", "2027-05-16", "2027-05-27",
        "2027-08-15", "2027-11-01", "2027-11-11", "2027-12-25", "2027-12-26"
    },
}


def is_polish_workday(day_of_year: int, start_year: int) -> bool:
    """Check if a given day-of-year is a Polish workday (Mon-Fri, not a holiday)."""
    from datetime import date, timedelta
    d = date(start_year, 1, 1) + timedelta(days=day_of_year)
    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    holidays = POLISH_HOLIDAYS.get(d.year, set())
    return d.isoformat() not in holidays


def get_k_class(delta_s: float) -> tuple:
    """Determine K-class from Δs value. Returns (class_name, coefficient).

    Boundaries per Rozporządzenie Ministra Klimatu i Środowiska (Dz.U. 2023 poz. 503):
      K1: Δs < -10%  → Kz = 0.17
      K2: -10% ≤ Δs < 10%  → Kz = 0.50
      K3: 10% ≤ Δs < 30%  → Kz = 0.83
      K4: Δs ≥ 30%  → Kz = 1.00
    """
    if delta_s < -10:
        return ("K1", 0.17)
    elif delta_s < 10:
        return ("K2", 0.50)
    elif delta_s < 30:
        return ("K3", 0.83)
    else:
        return ("K4", 1.00)


# K-class boundaries and coefficients for stochastic estimation
_K_BOUNDARIES = [-10.0, 10.0, 30.0]  # Δs thresholds per regulation
_K_COEFFICIENTS = [0.17, 0.50, 0.83, 1.00]  # K1, K2, K3, K4


def _norm_cdf(x: float, mu: float = 0.0, sigma: float = 1.0) -> float:
    """Normal CDF using Python built-in math.erf (no scipy needed)."""
    import math
    if sigma <= 0:
        return 1.0 if x >= mu else 0.0
    z = (x - mu) / sigma
    return 0.5 * (1.0 + math.erf(z / 1.4142135623730951))


def _estimate_stochastic_k_class(mean_delta_s: float, avg_R: float) -> dict:
    """
    Estimate K-class probability distribution for averaged/synthetic profiles.

    When a consumption profile is averaged (every working day identical),
    the daily Δs variance is lost, causing all days to get the same K-class.
    This function estimates the true K-class distribution using:

    1. The mean Δs from the average profile
    2. An empirical σ_Δs estimated from the selected/outside consumption ratio R

    Formula: σ_Δs = 25 / (R + 0.4)
    Calibrated against real dairy industry data (MLEKOMA):
      R=1.02 → σ=17.6% (actual measured: 17.1%)

    Returns dict with probabilities and effective coefficient.
    """
    # Estimate σ_Δs from the consumption ratio
    # Flat profiles (R≈1) → high daily variability → σ≈18%
    # Peaky profiles (R≈2) → low daily variability → σ≈10%
    sigma_delta_s = 25.0 / (max(avg_R, 0.5) + 0.4)

    # Compute K-class probabilities using normal distribution
    # P(K1) = P(Δs < -10), P(K2) = P(-10 ≤ Δs < 10), P(K3) = P(10 ≤ Δs < 30), P(K4) = P(Δs ≥ 30)
    probs = []
    prev_cdf = 0.0
    for boundary in _K_BOUNDARIES:
        cdf = _norm_cdf(boundary, mean_delta_s, sigma_delta_s)
        probs.append(cdf - prev_cdf)
        prev_cdf = cdf
    probs.append(1.0 - prev_cdf)  # K4: P(Δs ≥ 30)

    # Effective coefficient = weighted average
    eff_coeff = sum(p * c for p, c in zip(probs, _K_COEFFICIENTS))

    # Determine dominant K-class (highest probability)
    max_idx = max(range(4), key=lambda i: probs[i])
    dominant_k = f"K{max_idx + 1}"

    return {
        "probabilities": {f"K{i+1}": round(probs[i], 4) for i in range(4)},
        "effective_coefficient": round(eff_coeff, 4),
        "sigma_delta_s": round(sigma_delta_s, 2),
        "dominant_k_class": dominant_k,
        "is_stochastic": True,
    }


def calculate_capacity_fee(
    grid_draw: np.ndarray,
    som_rate_pln_kwh: float,
    selected_start: int,
    selected_end: int,
    start_year: int,
    data_start_date: str = None
) -> dict:
    """
    Calculate capacity fee using K-class algorithm.
    Port from consumption.js calculateKClassAnalysis().

    Includes stochastic correction for averaged/synthetic profiles:
    when all working days have identical consumption patterns (std of Δs < 2%),
    the algorithm estimates the true K-class distribution using a statistical
    model, preventing systematic underestimation of capacity fees.

    Args:
        grid_draw: 8760-hour array of grid import [kWh]
        som_rate_pln_kwh: SOM rate [PLN/kWh]
        selected_start: Start of selected hours (e.g. 7)
        selected_end: End of selected hours (e.g. 22)
        start_year: Calendar year for workday/holiday detection (fallback)
        data_start_date: Actual start date of data (ISO YYYY-MM-DD), overrides start_year

    Returns:
        dict with annual_fee_pln, monthly_fees[12], k_class, delta_s, etc.
    """
    n_days = len(grid_draw) // 24
    monthly_fees = np.zeros(12)
    total_fee = 0.0
    total_zs = 0.0
    all_delta_s = []
    # Track per-day data for potential stochastic recalculation
    day_data = []  # list of (date, selected_sum, outside_sum, month_idx)

    from datetime import date, timedelta
    if data_start_date:
        try:
            parts = data_start_date.split('-')
            start_date = date(int(parts[0]), int(parts[1]), int(parts[2]))
        except (ValueError, IndexError):
            start_date = date(start_year, 1, 1)
    else:
        start_date = date(start_year, 1, 1)

    selected_count_per_day = selected_end - selected_start
    outside_count_per_day = 24 - selected_count_per_day

    for day in range(n_days):
        d = start_date + timedelta(days=day)
        workday = d.weekday() < 5
        if workday:
            holidays = POLISH_HOLIDAYS.get(d.year, set())
            if d.isoformat() in holidays:
                workday = False

        if not workday:
            continue

        day_start = day * 24
        selected_sum = 0.0
        outside_sum = 0.0

        for hour in range(24):
            idx = day_start + hour
            if idx >= len(grid_draw):
                break
            val = grid_draw[idx]
            if selected_start <= hour < selected_end:
                selected_sum += val
            else:
                outside_sum += val

        avg_selected = selected_sum / selected_count_per_day if selected_count_per_day > 0 else 0
        avg_outside = outside_sum / outside_count_per_day if outside_count_per_day > 0 else 0
        delta_s = ((avg_selected / avg_outside) - 1) * 100 if avg_outside > 0 else 0

        k_name, k_coeff = get_k_class(delta_s)
        all_delta_s.append(delta_s)
        day_data.append((d, selected_sum, outside_sum, d.month - 1))

        # WOM = A × SOM × ZS (ZS = energy in selected hours in kWh)
        day_fee = k_coeff * som_rate_pln_kwh * selected_sum
        total_fee += day_fee
        total_zs += selected_sum / 1000  # kWh→MWh for reporting

        month_idx = d.month - 1
        monthly_fees[month_idx] += day_fee

    avg_delta_s = float(np.mean(all_delta_s)) if all_delta_s else 0
    overall_k_name, overall_k_coeff = get_k_class(avg_delta_s)
    stochastic_info = None

    # --- Stochastic correction for averaged profiles ---
    # Detection: if std(Δs) < 2%, the profile is averaged/synthetic
    # (real profiles have std typically 10-25%)
    if len(all_delta_s) >= 10:
        delta_s_std = float(np.std(all_delta_s))

        if delta_s_std < 2.0:
            # Profile is averaged - apply stochastic K-class estimation
            total_sel = sum(dd[1] for dd in day_data)
            total_out = sum(dd[2] for dd in day_data)
            n_workdays = len(day_data)

            avg_sel_per_day = total_sel / n_workdays if n_workdays > 0 else 0
            avg_out_per_day = total_out / n_workdays if n_workdays > 0 else 0
            avg_R = (avg_sel_per_day / selected_count_per_day) / \
                    (avg_out_per_day / outside_count_per_day) \
                    if avg_out_per_day > 0 and outside_count_per_day > 0 else 1.0

            stochastic_info = _estimate_stochastic_k_class(avg_delta_s, avg_R)
            eff_coeff = stochastic_info["effective_coefficient"]

            # Recalculate fees using the stochastic effective coefficient
            monthly_fees = np.zeros(12)
            total_fee = 0.0
            for d, sel_sum, out_sum, m_idx in day_data:
                day_fee = eff_coeff * som_rate_pln_kwh * sel_sum
                total_fee += day_fee
                monthly_fees[m_idx] += day_fee

            overall_k_name = stochastic_info["dominant_k_class"]
            overall_k_coeff = eff_coeff

            import logging
            logging.info(
                f"Stochastic K-class correction applied: "
                f"delta_s_std={delta_s_std:.2f}%, R={avg_R:.3f}, "
                f"sigma_est={stochastic_info['sigma_delta_s']}%, "
                f"eff_coeff={eff_coeff:.4f}, "
                f"K-dist={stochastic_info['probabilities']}"
            )

    result = {
        "annual_fee_pln": round(float(total_fee), 2),
        "monthly_fees": [round(float(m), 2) for m in monthly_fees],
        "k_class": overall_k_name,
        "k_coefficient": round(overall_k_coeff, 4),
        "delta_s": round(avg_delta_s, 2),
        "total_zs_mwh": round(float(total_zs), 1),
    }

    if stochastic_info:
        result["stochastic"] = stochastic_info

    return result


# =============================================================================
# Capacity Fee Scenarios (K-class) — multi-scenario endpoint
# =============================================================================

class CapacityFeeScenarioResult(BaseModel):
    """K-class result for a single scenario."""
    scenario: str
    annual_fee_pln: float
    k_class: str
    k_coefficient: float
    delta_s: float
    total_zs_mwh: float
    monthly_fees: List[float]
    stochastic: Optional[dict] = None


class CapacityFeeScenariosRequest(BaseModel):
    """Request for multi-scenario capacity fee calculation."""
    load_kwh: List[float] = Field(..., description="Hourly load profile [kWh], 8760 values")
    pv_kwh: Optional[List[float]] = Field(None, description="Hourly PV production [kWh], 8760 values")
    bess_charge_from_grid_kwh: Optional[List[float]] = Field(None, description="Hourly BESS charging from grid [kWh]")
    bess_discharge_kwh: Optional[List[float]] = Field(None, description="Hourly BESS discharge [kWh]")
    som_rate_pln_kwh: float = Field(0.2194, description="SOM rate [PLN/kWh]")
    selected_start: int = Field(7, ge=0, le=23, description="Selected hours start (e.g. 7)")
    selected_end: int = Field(22, ge=1, le=24, description="Selected hours end (e.g. 22)")
    start_year: int = Field(2026, description="Calendar year for workday/holiday detection")
    data_start_date: Optional[str] = Field(None, description="Actual start date ISO YYYY-MM-DD")


class CapacityFeeScenariosResult(BaseModel):
    """Multi-scenario K-class calculation result."""
    baseline: CapacityFeeScenarioResult
    with_pv: Optional[CapacityFeeScenarioResult] = None
    with_pv_bess: Optional[CapacityFeeScenarioResult] = None

    # Savings (deltas)
    savings_pv_only_pln: float = 0.0
    savings_pv_bess_pln: float = 0.0
    savings_bess_incremental_pln: float = 0.0


@app.post("/compute-capacity-fee-scenarios", response_model=CapacityFeeScenariosResult)
async def compute_capacity_fee_scenarios(request: CapacityFeeScenariosRequest):
    """
    Oblicz opłatę mocową (K-class) dla max 3 scenariuszy:
      S0: Baseline (sam load)
      S1: Z PV (load - pv)
      S2: Z PV + BESS (load - pv - discharge + charge_from_grid)

    Zwraca K-class, współczynnik, opłatę roczną i oszczędności per scenariusz.
    """
    import logging
    logger = logging.getLogger("profile-analysis")

    load = np.array(request.load_kwh, dtype=np.float64)
    n = len(load)

    # --- S0: Baseline (no PV, no BESS) ---
    grid_baseline = load.copy()
    s0 = calculate_capacity_fee(
        grid_baseline, request.som_rate_pln_kwh,
        request.selected_start, request.selected_end,
        request.start_year, request.data_start_date
    )
    baseline = CapacityFeeScenarioResult(
        scenario="baseline", annual_fee_pln=s0["annual_fee_pln"],
        k_class=s0["k_class"], k_coefficient=s0["k_coefficient"],
        delta_s=s0["delta_s"], total_zs_mwh=s0["total_zs_mwh"],
        monthly_fees=s0["monthly_fees"], stochastic=s0.get("stochastic")
    )
    logger.info(f"K-class S0 (baseline): {s0['k_class']} coeff={s0['k_coefficient']:.4f} fee={s0['annual_fee_pln']:.0f} PLN")

    result = CapacityFeeScenariosResult(baseline=baseline)

    # --- S1: With PV (if pv_kwh provided) ---
    if request.pv_kwh and len(request.pv_kwh) > 0:
        pv = np.array(request.pv_kwh[:n], dtype=np.float64)
        if len(pv) < n:
            pv = np.pad(pv, (0, n - len(pv)), constant_values=0)
        grid_pv = np.maximum(load - pv, 0.0)

        s1 = calculate_capacity_fee(
            grid_pv, request.som_rate_pln_kwh,
            request.selected_start, request.selected_end,
            request.start_year, request.data_start_date
        )
        result.with_pv = CapacityFeeScenarioResult(
            scenario="with_pv", annual_fee_pln=s1["annual_fee_pln"],
            k_class=s1["k_class"], k_coefficient=s1["k_coefficient"],
            delta_s=s1["delta_s"], total_zs_mwh=s1["total_zs_mwh"],
            monthly_fees=s1["monthly_fees"], stochastic=s1.get("stochastic")
        )
        result.savings_pv_only_pln = round(s0["annual_fee_pln"] - s1["annual_fee_pln"], 2)
        logger.info(f"K-class S1 (PV): {s1['k_class']} coeff={s1['k_coefficient']:.4f} fee={s1['annual_fee_pln']:.0f} PLN, savings={result.savings_pv_only_pln:.0f}")

        # --- S2: With PV + BESS (if bess profiles provided) ---
        if request.bess_discharge_kwh and len(request.bess_discharge_kwh) > 0:
            discharge = np.array(request.bess_discharge_kwh[:n], dtype=np.float64)
            if len(discharge) < n:
                discharge = np.pad(discharge, (0, n - len(discharge)), constant_values=0)

            charge_from_grid = np.zeros(n, dtype=np.float64)
            if request.bess_charge_from_grid_kwh and len(request.bess_charge_from_grid_kwh) > 0:
                cfg = np.array(request.bess_charge_from_grid_kwh[:n], dtype=np.float64)
                if len(cfg) < n:
                    cfg = np.pad(cfg, (0, n - len(cfg)), constant_values=0)
                charge_from_grid = cfg

            # Grid import with PV + BESS:
            # BESS discharge reduces grid import, BESS charging from grid increases it
            grid_pv_bess = np.maximum(load - pv - discharge + charge_from_grid, 0.0)

            s2 = calculate_capacity_fee(
                grid_pv_bess, request.som_rate_pln_kwh,
                request.selected_start, request.selected_end,
                request.start_year, request.data_start_date
            )
            result.with_pv_bess = CapacityFeeScenarioResult(
                scenario="with_pv_bess", annual_fee_pln=s2["annual_fee_pln"],
                k_class=s2["k_class"], k_coefficient=s2["k_coefficient"],
                delta_s=s2["delta_s"], total_zs_mwh=s2["total_zs_mwh"],
                monthly_fees=s2["monthly_fees"], stochastic=s2.get("stochastic")
            )
            result.savings_pv_bess_pln = round(s0["annual_fee_pln"] - s2["annual_fee_pln"], 2)
            result.savings_bess_incremental_pln = round(s1["annual_fee_pln"] - s2["annual_fee_pln"], 2)
            logger.info(f"K-class S2 (PV+BESS): {s2['k_class']} coeff={s2['k_coefficient']:.4f} fee={s2['annual_fee_pln']:.0f} PLN, bess_incremental={result.savings_bess_incremental_pln:.0f}")

    elif request.bess_discharge_kwh and len(request.bess_discharge_kwh) > 0:
        # BESS without PV (load_only mode)
        discharge = np.array(request.bess_discharge_kwh[:n], dtype=np.float64)
        if len(discharge) < n:
            discharge = np.pad(discharge, (0, n - len(discharge)), constant_values=0)

        charge_from_grid = np.zeros(n, dtype=np.float64)
        if request.bess_charge_from_grid_kwh and len(request.bess_charge_from_grid_kwh) > 0:
            cfg = np.array(request.bess_charge_from_grid_kwh[:n], dtype=np.float64)
            if len(cfg) < n:
                cfg = np.pad(cfg, (0, n - len(cfg)), constant_values=0)
            charge_from_grid = cfg

        grid_bess = np.maximum(load - discharge + charge_from_grid, 0.0)

        s2 = calculate_capacity_fee(
            grid_bess, request.som_rate_pln_kwh,
            request.selected_start, request.selected_end,
            request.start_year, request.data_start_date
        )
        result.with_pv_bess = CapacityFeeScenarioResult(
            scenario="bess_only", annual_fee_pln=s2["annual_fee_pln"],
            k_class=s2["k_class"], k_coefficient=s2["k_coefficient"],
            delta_s=s2["delta_s"], total_zs_mwh=s2["total_zs_mwh"],
            monthly_fees=s2["monthly_fees"], stochastic=s2.get("stochastic")
        )
        result.savings_pv_bess_pln = round(s0["annual_fee_pln"] - s2["annual_fee_pln"], 2)
        result.savings_bess_incremental_pln = result.savings_pv_bess_pln
        logger.info(f"K-class S2 (BESS only): {s2['k_class']} coeff={s2['k_coefficient']:.4f} fee={s2['annual_fee_pln']:.0f} PLN")

    return result


def build_hourly_tariff_prices(tariff_config: dict, num_hours: int, start_year: int, data_start_date: str = None) -> np.ndarray:
    """
    Generate hourly tariff energy-active prices based on tariff config.
    Port from economics.js buildHourlyTariffPrices().

    Returns np.ndarray of num_hours PLN/MWh values.
    """
    t_type = tariff_config.get("type", "flat")
    from datetime import date as dt_date
    if data_start_date:
        try:
            parts = data_start_date.split('-')
            start_dt = dt_date(int(parts[0]), int(parts[1]), int(parts[2]))
            jan1_dow = start_dt.weekday()  # day-of-week of actual data start
        except (ValueError, IndexError):
            jan1_dow = dt_date(start_year, 1, 1).weekday()
    else:
        jan1_dow = dt_date(start_year, 1, 1).weekday()  # 0=Mon, 6=Sun

    prices = np.empty(num_hours, dtype=float)

    if t_type == "flat":
        prices[:] = tariff_config.get("flat_rate", 750)
        return prices

    if t_type == "two_zone":
        tz = tariff_config.get("two_zone", {})
        day_rate = tz.get("day_rate", 850)
        night_rate = tz.get("night_rate", 450)
        wd = tz.get("weekday", {})
        we = tz.get("weekend", {})
        wd_start = wd.get("start", 6)
        wd_end = wd.get("end", 22)
        we_start = we.get("start", 6)
        we_end = we.get("end", 13)

        for h in range(num_hours):
            day_of_year = h // 24
            hour_of_day = h % 24
            dow = (jan1_dow + day_of_year) % 7  # 0=Mon, 6=Sun
            is_weekend = dow >= 5

            if is_weekend:
                prices[h] = day_rate if we_start <= hour_of_day < we_end else night_rate
            else:
                prices[h] = day_rate if wd_start <= hour_of_day < wd_end else night_rate

        return prices

    if t_type == "three_zone":
        tz = tariff_config.get("three_zone", {})
        peak_rate = tz.get("peak_rate", 950)
        partial_rate = tz.get("partial_rate", 700)
        off_peak_rate = tz.get("off_peak_rate", 400)
        p1 = tz.get("peak1", {})
        p2 = tz.get("peak2", {})
        pa = tz.get("partial", {})
        p1s, p1e = p1.get("start", 7), p1.get("end", 13)
        p2s, p2e = p2.get("start", 17), p2.get("end", 21)
        pas, pae = pa.get("start", 13), pa.get("end", 17)

        for h in range(num_hours):
            day_of_year = h // 24
            hour_of_day = h % 24
            dow = (jan1_dow + day_of_year) % 7
            is_weekend = dow >= 5

            if is_weekend:
                prices[h] = off_peak_rate
            elif (p1s <= hour_of_day < p1e) or (p2s <= hour_of_day < p2e):
                prices[h] = peak_rate
            elif pas <= hour_of_day < pae:
                prices[h] = partial_rate
            else:
                prices[h] = off_peak_rate

        return prices

    # Fallback
    prices[:] = 510
    return prices


def compute_tcsl_for_scenario(
    load: np.ndarray,
    pv: np.ndarray,
    active_prices: np.ndarray,
    fees_var_sum: float,
    fees_fixed_monthly_pln: float,
    som_rate: float,
    sel_start: int,
    sel_end: int,
    start_year: int,
    data_start_date: str = None
) -> dict:
    """
    Core TCSL calculation for one scenario (tariff OR RDN) × one PV config.

    Returns dict with cost breakdown.
    """
    n = min(len(load), len(pv), len(active_prices))
    load_n = load[:n]
    pv_n = pv[:n]
    prices_n = active_prices[:n]

    self_consumed = np.minimum(pv_n, load_n)
    grid_import = np.maximum(load_n - pv_n, 0)

    # Variable costs: E_grid[h] × (active_price[h] + fees_var) / 1000
    hourly_total_price = prices_n + fees_var_sum
    hourly_variable_cost = grid_import * hourly_total_price / 1000  # PLN
    total_variable = float(np.sum(hourly_variable_cost))

    # Separate: energy active vs fees var
    energy_active_cost = float(np.sum(grid_import * prices_n / 1000))
    fees_var_cost = float(np.sum(grid_import * fees_var_sum / 1000))

    # Capacity fee (K-class)
    cap_result = calculate_capacity_fee(grid_import, som_rate, sel_start, sel_end, start_year, data_start_date)

    # Fixed monthly × 12
    fixed_annual = fees_fixed_monthly_pln * 12

    # TCSL total
    tcsl = total_variable + cap_result["annual_fee_pln"] + fixed_annual

    # Monthly breakdown — group hours by actual calendar month using data_start_date
    from datetime import date as dt_date, timedelta as dt_td
    if data_start_date:
        try:
            parts = data_start_date.split('-')
            sd = dt_date(int(parts[0]), int(parts[1]), int(parts[2]))
        except (ValueError, IndexError):
            sd = dt_date(start_year, 1, 1)
    else:
        sd = dt_date(start_year, 1, 1)

    # Build hour→calendar_month mapping via day boundaries
    month_hour_ranges = {}  # calendar_month (1-12) → (h_start, h_end)
    n_days_data = (n + 23) // 24
    for day_idx in range(n_days_data):
        d = sd + dt_td(days=day_idx)
        cal_month = d.month
        h_start = day_idx * 24
        h_end = min((day_idx + 1) * 24, n)
        if h_start >= n:
            break
        if cal_month not in month_hour_ranges:
            month_hour_ranges[cal_month] = (h_start, h_end)
        else:
            month_hour_ranges[cal_month] = (month_hour_ranges[cal_month][0], h_end)

    monthly = []
    for cal_month in sorted(month_hour_ranges.keys()):
        h_start, h_end = month_hour_ranges[cal_month]
        m_grid = grid_import[h_start:h_end]
        m_prices = prices_n[h_start:h_end]
        m_load = load_n[h_start:h_end]
        m_pv = pv_n[h_start:h_end]

        m_energy_active = float(np.sum(m_grid * m_prices / 1000))
        m_fees_var = float(np.sum(m_grid * fees_var_sum / 1000))
        m_variable = m_energy_active + m_fees_var
        m_capacity = cap_result["monthly_fees"][cal_month - 1]  # 0-indexed array
        m_fixed = fees_fixed_monthly_pln
        m_tcsl = m_variable + m_capacity + m_fixed

        monthly.append({
            "month": cal_month,
            "consumption_kwh": round(float(np.sum(m_load)), 1),
            "production_kwh": round(float(np.sum(m_pv)), 1),
            "self_consumed_kwh": round(float(np.sum(np.minimum(m_pv, m_load))), 1),
            "grid_import_kwh": round(float(np.sum(m_grid)), 1),
            "energy_active_pln": round(m_energy_active, 2),
            "fees_var_pln": round(m_fees_var, 2),
            "variable_total_pln": round(m_variable, 2),
            "capacity_fee_pln": round(m_capacity, 2),
            "fixed_monthly_pln": round(m_fixed, 2),
            "tcsl_pln": round(m_tcsl, 2),
        })

    return {
        "tcsl_annual_pln": round(tcsl, 2),
        "variable_cost_pln": round(total_variable, 2),
        "energy_active_cost_pln": round(energy_active_cost, 2),
        "fees_var_cost_pln": round(fees_var_cost, 2),
        "capacity_fee_total_pln": cap_result["annual_fee_pln"],
        "fixed_monthly_total_pln": round(fixed_annual, 2),
        "k_class": cap_result["k_class"],
        "k_coefficient": cap_result["k_coefficient"],
        "delta_s": cap_result["delta_s"],
        "stochastic": cap_result.get("stochastic"),
        "monthly": monthly,
        "annual_consumption_kwh": round(float(np.sum(load_n)), 1),
        "annual_production_kwh": round(float(np.sum(pv_n)), 1),
        "annual_self_consumed_kwh": round(float(np.sum(self_consumed)), 1),
        "annual_grid_import_kwh": round(float(np.sum(grid_import)), 1),
    }


class TcslTariffConfig(BaseModel):
    type: str = "flat"
    flat_rate: float = 750
    two_zone: Optional[dict] = None
    three_zone: Optional[dict] = None


class TcslFeesVariable(BaseModel):
    distribution_plnmwh: float = 200
    quality_fee_plnmwh: float = 10
    oze_fee_plnmwh: float = 7
    cogeneration_fee_plnmwh: float = 10
    excise_tax_plnmwh: float = 5


class TcslFeesFixedMonthly(BaseModel):
    dist_fixed_rate_zl_per_kw_month: float = 9.14
    contracted_power_kw: float = 50.0
    osd_subscription_pln_month: float = 5.54
    transition_fee_pln_month: float = 0.0
    supplier_trade_fee_pln_month: float = 0.0


class TcslCapacityFeeConfig(BaseModel):
    som_rate_pln_kwh: float = 0.2194
    selected_hours_start: int = 7
    selected_hours_end: int = 22
    year: int = 2025


class TcslRequest(BaseModel):
    load_kwh: List[float] = Field(..., description="Hourly consumption [kWh], 8760 values")
    pv_generation_kwh: List[float] = Field(..., description="Hourly PV generation [kWh], 8760 values")
    tariff_config: TcslTariffConfig = Field(default_factory=TcslTariffConfig)
    rdn_prices_plnmwh: Optional[List[float]] = Field(None, description="Hourly RDN prices [PLN/MWh]. If None, only tariff scenario computed.")
    fees_variable: TcslFeesVariable = Field(default_factory=TcslFeesVariable)
    fees_fixed_monthly: TcslFeesFixedMonthly = Field(default_factory=TcslFeesFixedMonthly)
    capacity_fee_config: TcslCapacityFeeConfig = Field(default_factory=TcslCapacityFeeConfig)
    start_year: int = 2025
    data_start_date: Optional[str] = Field(None, description="Actual start date of load data (ISO YYYY-MM-DD). When provided, overrides start_year for calendar mapping in K-class and tariff zone calculations.")


class TcslMonthlyBreakdown(BaseModel):
    month: int
    tariff: dict
    rdn: Optional[dict] = None


class TcslResult(BaseModel):
    # Tariff scenario with PV
    tariff_tcsl_annual_pln: float
    tariff_variable_cost_pln: float
    tariff_fixed_monthly_total_pln: float
    tariff_capacity_fee_total_pln: float
    tariff_energy_active_cost_pln: float
    tariff_fees_var_cost_pln: float

    # RDN scenario with PV (optional)
    rdn_tcsl_annual_pln: Optional[float] = None
    rdn_variable_cost_pln: Optional[float] = None
    rdn_fixed_monthly_total_pln: Optional[float] = None
    rdn_capacity_fee_total_pln: Optional[float] = None
    rdn_energy_active_cost_pln: Optional[float] = None
    rdn_fees_var_cost_pln: Optional[float] = None

    # Baseline (no PV)
    nopv_tariff_tcsl_pln: float
    nopv_rdn_tcsl_pln: Optional[float] = None

    # Deltas
    pv_savings_tariff_pln: float
    pv_savings_rdn_pln: Optional[float] = None
    rdn_vs_tariff_delta_pln: Optional[float] = None
    rdn_vs_tariff_delta_pct: Optional[float] = None

    # Energy balance
    annual_consumption_kwh: float
    annual_production_kwh: float
    annual_self_consumed_kwh: float
    annual_grid_import_kwh: float

    # K-class
    kclass_with_pv: str
    kclass_without_pv: str
    capacity_fee_with_pv_pln: float
    capacity_fee_without_pv_pln: float
    kclass_stochastic_nopv: Optional[dict] = None
    kclass_stochastic_pv: Optional[dict] = None

    # Monthly
    monthly_breakdown: List[dict]

    # noPV breakdown (for PV savings reports)
    nopv_tariff_variable_pln: float = 0
    nopv_tariff_energy_active_pln: float = 0
    nopv_tariff_fees_var_pln: float = 0
    nopv_tariff_capacity_fee_pln: float = 0
    nopv_rdn_variable_pln: Optional[float] = None
    nopv_rdn_energy_active_pln: Optional[float] = None
    nopv_rdn_fees_var_pln: Optional[float] = None
    nopv_rdn_capacity_fee_pln: Optional[float] = None
    nopv_monthly_breakdown: Optional[List[dict]] = None

    # Price stats
    rdn_price_stats: Optional[dict] = None
    tariff_avg_price_plnmwh: float


@app.post("/compute-tcsl", response_model=TcslResult)
async def compute_tcsl(request: TcslRequest):
    """
    Unified Total Cost to Serve Load calculation.

    Computes TCSL for tariff (and optionally RDN) scenario,
    both with PV and without PV (baseline), with full 3-bucket fee breakdown:
      - Variable costs (per kWh of grid import)
      - Fixed monthly costs
      - Capacity fee (K-class algorithm)

    TCSL = Σ variable + Σ fixed_monthly + Σ capacity_fee
    Savings = TCSL(noPV) - TCSL(withPV)
    Delta = TCSL(tariff) - TCSL(rdn)
    """
    load = np.array(request.load_kwh, dtype=float)
    pv = np.array(request.pv_generation_kwh, dtype=float)

    n = min(len(load), len(pv))
    if n < 720:
        raise HTTPException(400, f"Insufficient data: {n} hours (need ≥720)")

    load = load[:n]
    pv = pv[:n]

    print(f"⚡ TCSL: {n} hours, consumption={np.sum(load):.0f} kWh, production={np.sum(pv):.0f} kWh")

    # Sum of variable fees (PLN/MWh)
    fv = request.fees_variable
    fees_var_sum = (fv.distribution_plnmwh + fv.quality_fee_plnmwh +
                    fv.oze_fee_plnmwh + fv.cogeneration_fee_plnmwh +
                    fv.excise_tax_plnmwh)

    # Fixed monthly total (PLN/month)
    fm = request.fees_fixed_monthly
    fixed_monthly_pln = (fm.dist_fixed_rate_zl_per_kw_month * fm.contracted_power_kw +
                         fm.osd_subscription_pln_month +
                         fm.transition_fee_pln_month +
                         fm.supplier_trade_fee_pln_month)

    # Capacity fee params
    cf = request.capacity_fee_config
    som = cf.som_rate_pln_kwh
    sel_start = cf.selected_hours_start
    sel_end = cf.selected_hours_end
    year = request.start_year
    dsd = request.data_start_date  # actual start date of data array

    # Build tariff hourly prices
    tc_dict = request.tariff_config.model_dump()
    tariff_prices = build_hourly_tariff_prices(tc_dict, n, year, dsd)
    tariff_avg = float(np.mean(tariff_prices))

    # Zero PV array for baseline
    zero_pv = np.zeros(n)

    # ===== 4 scenarios =====
    # 1. Tariff + PV
    tariff_pv = compute_tcsl_for_scenario(load, pv, tariff_prices, fees_var_sum, fixed_monthly_pln, som, sel_start, sel_end, year, dsd)

    # 2. Tariff + no PV (baseline)
    tariff_nopv = compute_tcsl_for_scenario(load, zero_pv, tariff_prices, fees_var_sum, fixed_monthly_pln, som, sel_start, sel_end, year, dsd)

    # 3 & 4. RDN scenarios (optional)
    rdn_pv_result = None
    rdn_nopv_result = None
    rdn_price_stats = None

    if request.rdn_prices_plnmwh and len(request.rdn_prices_plnmwh) >= 720:
        rdn = np.array(request.rdn_prices_plnmwh[:n], dtype=float)

        rdn_pv_result = compute_tcsl_for_scenario(load, pv, rdn, fees_var_sum, fixed_monthly_pln, som, sel_start, sel_end, year, dsd)
        rdn_nopv_result = compute_tcsl_for_scenario(load, zero_pv, rdn, fees_var_sum, fixed_monthly_pln, som, sel_start, sel_end, year, dsd)

        # Price stats during grid import hours
        grid_import = np.maximum(load - pv, 0)
        mask = grid_import > 0.1
        if mask.any():
            rdn_gi = rdn[mask]
            rdn_price_stats = {
                "avg": round(float(np.mean(rdn_gi)), 1),
                "min": round(float(np.min(rdn_gi)), 1),
                "max": round(float(np.max(rdn_gi)), 1),
                "median": round(float(np.median(rdn_gi)), 1),
                "std": round(float(np.std(rdn_gi)), 1),
            }
        else:
            rdn_price_stats = {"avg": 0, "min": 0, "max": 0, "median": 0, "std": 0}

    # ===== Deltas =====
    pv_savings_tariff = tariff_nopv["tcsl_annual_pln"] - tariff_pv["tcsl_annual_pln"]
    pv_savings_rdn = None
    rdn_vs_tariff_delta = None
    rdn_vs_tariff_pct = None

    if rdn_pv_result:
        pv_savings_rdn = rdn_nopv_result["tcsl_annual_pln"] - rdn_pv_result["tcsl_annual_pln"]
        rdn_vs_tariff_delta = tariff_pv["tcsl_annual_pln"] - rdn_pv_result["tcsl_annual_pln"]
        rdn_vs_tariff_pct = (rdn_vs_tariff_delta / tariff_pv["tcsl_annual_pln"] * 100) if tariff_pv["tcsl_annual_pln"] > 0 else 0

    # ===== Monthly combined =====
    monthly_combined = []
    for m in range(12):
        entry = {"month": m + 1, "tariff": tariff_pv["monthly"][m] if m < len(tariff_pv["monthly"]) else {}}
        if rdn_pv_result and m < len(rdn_pv_result["monthly"]):
            entry["rdn"] = rdn_pv_result["monthly"][m]
        monthly_combined.append(entry)

    rdn_info = ""
    if rdn_pv_result:
        rdn_val = rdn_pv_result['tcsl_annual_pln']
        rdn_info = f", RDN={rdn_val:.0f} PLN, delta={rdn_vs_tariff_delta:.0f} PLN"

    # Detailed debug log
    print(f"⚡ TCSL DETAILED:")
    print(f"  Consumption: {np.sum(load):.0f} kWh ({np.sum(load)/1000:.1f} MWh)")
    print(f"  PV production: {np.sum(pv):.0f} kWh ({np.sum(pv)/1000:.1f} MWh)")
    sc = np.sum(np.minimum(pv, load))
    gi = np.sum(np.maximum(load - pv, 0))
    print(f"  Self-consumed: {sc:.0f} kWh ({sc/1000:.1f} MWh)")
    print(f"  Grid import (with PV): {gi:.0f} kWh ({gi/1000:.1f} MWh)")
    print(f"  Grid import (no PV): {np.sum(load):.0f} kWh")
    print(f"  Tariff avg price: {tariff_avg:.1f} PLN/MWh, fees_var_sum: {fees_var_sum:.1f} PLN/MWh")
    print(f"  ---- TARIFF + PV ----")
    print(f"    Energy active: {tariff_pv['energy_active_cost_pln']:.0f} PLN")
    print(f"    Fees var:      {tariff_pv['fees_var_cost_pln']:.0f} PLN")
    print(f"    Capacity fee:  {tariff_pv['capacity_fee_total_pln']:.0f} PLN (K={tariff_pv['k_class']}, coeff={tariff_pv['k_coefficient']}, delta_s={tariff_pv['delta_s']:.1f}%)")
    print(f"    Fixed monthly: {tariff_pv['fixed_monthly_total_pln']:.0f} PLN")
    print(f"    TCSL TOTAL:    {tariff_pv['tcsl_annual_pln']:.0f} PLN")
    print(f"  ---- TARIFF + NO PV ----")
    print(f"    Energy active: {tariff_nopv['energy_active_cost_pln']:.0f} PLN")
    print(f"    Fees var:      {tariff_nopv['fees_var_cost_pln']:.0f} PLN")
    print(f"    Capacity fee:  {tariff_nopv['capacity_fee_total_pln']:.0f} PLN (K={tariff_nopv['k_class']}, coeff={tariff_nopv['k_coefficient']}, delta_s={tariff_nopv['delta_s']:.1f}%)")
    print(f"    Fixed monthly: {tariff_nopv['fixed_monthly_total_pln']:.0f} PLN")
    print(f"    TCSL TOTAL:    {tariff_nopv['tcsl_annual_pln']:.0f} PLN")
    print(f"  ---- PV SAVINGS ----")
    energy_saving = tariff_nopv['energy_active_cost_pln'] - tariff_pv['energy_active_cost_pln']
    fees_var_saving = tariff_nopv['fees_var_cost_pln'] - tariff_pv['fees_var_cost_pln']
    cap_saving = tariff_nopv['capacity_fee_total_pln'] - tariff_pv['capacity_fee_total_pln']
    print(f"    Energy saving: {energy_saving:.0f} PLN")
    print(f"    Fees var saving: {fees_var_saving:.0f} PLN")
    print(f"    Capacity saving: {cap_saving:.0f} PLN")
    print(f"    TOTAL PV savings: {pv_savings_tariff:.0f} PLN")
    print(f"⚡ TCSL Result: Tariff={tariff_pv['tcsl_annual_pln']:.0f} PLN"
          f", noPV={tariff_nopv['tcsl_annual_pln']:.0f} PLN"
          f", PV savings={pv_savings_tariff:.0f} PLN{rdn_info}")

    return TcslResult(
        # Tariff with PV
        tariff_tcsl_annual_pln=tariff_pv["tcsl_annual_pln"],
        tariff_variable_cost_pln=tariff_pv["variable_cost_pln"],
        tariff_fixed_monthly_total_pln=tariff_pv["fixed_monthly_total_pln"],
        tariff_capacity_fee_total_pln=tariff_pv["capacity_fee_total_pln"],
        tariff_energy_active_cost_pln=tariff_pv["energy_active_cost_pln"],
        tariff_fees_var_cost_pln=tariff_pv["fees_var_cost_pln"],

        # RDN with PV
        rdn_tcsl_annual_pln=rdn_pv_result["tcsl_annual_pln"] if rdn_pv_result else None,
        rdn_variable_cost_pln=rdn_pv_result["variable_cost_pln"] if rdn_pv_result else None,
        rdn_fixed_monthly_total_pln=rdn_pv_result["fixed_monthly_total_pln"] if rdn_pv_result else None,
        rdn_capacity_fee_total_pln=rdn_pv_result["capacity_fee_total_pln"] if rdn_pv_result else None,
        rdn_energy_active_cost_pln=rdn_pv_result["energy_active_cost_pln"] if rdn_pv_result else None,
        rdn_fees_var_cost_pln=rdn_pv_result["fees_var_cost_pln"] if rdn_pv_result else None,

        # Baselines
        nopv_tariff_tcsl_pln=tariff_nopv["tcsl_annual_pln"],
        nopv_rdn_tcsl_pln=rdn_nopv_result["tcsl_annual_pln"] if rdn_nopv_result else None,

        # Deltas
        pv_savings_tariff_pln=round(pv_savings_tariff, 2),
        pv_savings_rdn_pln=round(pv_savings_rdn, 2) if pv_savings_rdn is not None else None,
        rdn_vs_tariff_delta_pln=round(rdn_vs_tariff_delta, 2) if rdn_vs_tariff_delta is not None else None,
        rdn_vs_tariff_delta_pct=round(rdn_vs_tariff_pct, 1) if rdn_vs_tariff_pct is not None else None,

        # Energy balance
        annual_consumption_kwh=tariff_pv["annual_consumption_kwh"],
        annual_production_kwh=tariff_pv["annual_production_kwh"],
        annual_self_consumed_kwh=tariff_pv["annual_self_consumed_kwh"],
        annual_grid_import_kwh=tariff_pv["annual_grid_import_kwh"],

        # K-class
        kclass_with_pv=tariff_pv["k_class"],
        kclass_without_pv=tariff_nopv["k_class"],
        capacity_fee_with_pv_pln=tariff_pv["capacity_fee_total_pln"],
        capacity_fee_without_pv_pln=tariff_nopv["capacity_fee_total_pln"],
        kclass_stochastic_nopv=tariff_nopv.get("stochastic"),
        kclass_stochastic_pv=tariff_pv.get("stochastic"),

        # Monthly
        monthly_breakdown=monthly_combined,

        # noPV breakdown
        nopv_tariff_variable_pln=tariff_nopv["variable_cost_pln"],
        nopv_tariff_energy_active_pln=tariff_nopv["energy_active_cost_pln"],
        nopv_tariff_fees_var_pln=tariff_nopv["fees_var_cost_pln"],
        nopv_tariff_capacity_fee_pln=tariff_nopv["capacity_fee_total_pln"],
        nopv_rdn_variable_pln=rdn_nopv_result["variable_cost_pln"] if rdn_nopv_result else None,
        nopv_rdn_energy_active_pln=rdn_nopv_result["energy_active_cost_pln"] if rdn_nopv_result else None,
        nopv_rdn_fees_var_pln=rdn_nopv_result["fees_var_cost_pln"] if rdn_nopv_result else None,
        nopv_rdn_capacity_fee_pln=rdn_nopv_result["capacity_fee_total_pln"] if rdn_nopv_result else None,
        nopv_monthly_breakdown=[
            {
                "month": m + 1,
                "tariff_nopv": tariff_nopv["monthly"][m] if m < len(tariff_nopv["monthly"]) else {},
                "rdn_nopv": rdn_nopv_result["monthly"][m] if rdn_nopv_result and m < len(rdn_nopv_result["monthly"]) else None,
            }
            for m in range(12)
        ],

        # Price stats
        rdn_price_stats=rdn_price_stats,
        tariff_avg_price_plnmwh=round(tariff_avg, 1),
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8040)

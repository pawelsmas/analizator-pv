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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8040)

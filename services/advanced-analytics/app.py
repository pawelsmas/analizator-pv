from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Optional, Tuple
import numpy as np
from scipy import stats
from collections import defaultdict

# Prometheus metrics
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(title="Advanced Analytics Service", version="1.0.0")

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
class LoadDurationCurveRequest(BaseModel):
    consumption: List[float]  # Hourly consumption data
    pv_production: List[float]  # Hourly PV production
    capacity: float

class LoadDurationCurveResult(BaseModel):
    sorted_load: List[float]
    sorted_net_load: List[float]
    sorted_pv: List[float]
    hours: List[int]
    percentiles: Dict[str, float]
    peak_demand: float
    base_load: float
    load_factor: float

class HourlyStatisticsResult(BaseModel):
    hour: int
    avg_consumption: float
    avg_production: float
    avg_self_consumption: float
    max_consumption: float
    max_production: float
    self_consumption_rate: float

class CurtailmentAnalysisResult(BaseModel):
    total_curtailed: float
    curtailment_hours: int
    curtailment_percentage: float
    monthly_curtailment: List[float]
    hourly_curtailment_pattern: List[float]

class EnergyBalanceResult(BaseModel):
    total_consumption: float
    total_production: float
    total_self_consumed: float
    total_grid_import: float
    total_grid_export: float
    self_sufficiency: float
    self_consumption: float
    monthly_balance: List[Dict[str, float]]

class WeekendAnalysisResult(BaseModel):
    weekday_avg_consumption: float
    weekend_avg_consumption: float
    weekday_avg_production: float
    weekend_avg_production: float
    weekday_self_consumption_rate: float
    weekend_self_consumption_rate: float
    weekend_excess_percentage: float

class AdvancedKPIResult(BaseModel):
    load_duration: LoadDurationCurveResult
    hourly_stats: List[HourlyStatisticsResult]
    curtailment: Optional[CurtailmentAnalysisResult]
    energy_balance: EnergyBalanceResult
    weekend_analysis: Optional[WeekendAnalysisResult]
    insights: List[str]

# ============== Calculation Functions ==============

def calculate_load_duration_curve(
    consumption: np.ndarray,
    pv_production: np.ndarray,
    capacity: float
) -> LoadDurationCurveResult:
    """
    Calculate load duration curve - sorts load from highest to lowest
    to show the distribution of demand over time
    """
    # Calculate net load (consumption - PV production)
    net_load = consumption - pv_production

    # Sort all arrays from highest to lowest
    sorted_indices_load = np.argsort(consumption)[::-1]
    sorted_load = consumption[sorted_indices_load]

    sorted_indices_net = np.argsort(net_load)[::-1]
    sorted_net_load = net_load[sorted_indices_net]

    sorted_indices_pv = np.argsort(pv_production)[::-1]
    sorted_pv = pv_production[sorted_indices_pv]

    # Calculate key percentiles
    percentiles = {
        "p01": float(np.percentile(consumption, 99)),  # 1% exceedance
        "p05": float(np.percentile(consumption, 95)),
        "p10": float(np.percentile(consumption, 90)),
        "p50": float(np.percentile(consumption, 50)),  # Median
        "p90": float(np.percentile(consumption, 10)),
        "p95": float(np.percentile(consumption, 5)),
        "p99": float(np.percentile(consumption, 1))
    }

    # Calculate metrics
    peak_demand = float(np.max(consumption))
    base_load = float(np.percentile(consumption, 1))  # Bottom 1%
    avg_load = float(np.mean(consumption))
    load_factor = avg_load / peak_demand if peak_demand > 0 else 0

    return LoadDurationCurveResult(
        sorted_load=sorted_load.tolist(),
        sorted_net_load=sorted_net_load.tolist(),
        sorted_pv=sorted_pv.tolist(),
        hours=list(range(len(sorted_load))),
        percentiles=percentiles,
        peak_demand=peak_demand,
        base_load=base_load,
        load_factor=load_factor
    )

def calculate_hourly_statistics(
    consumption: np.ndarray,
    pv_production: np.ndarray,
    timestamps: Optional[List[int]] = None
) -> List[HourlyStatisticsResult]:
    """
    Calculate statistics for each hour of the day (0-23)
    """
    hourly_stats = []

    hours_in_data = len(consumption)

    for hour in range(24):
        # Get all values for this hour across all days
        hour_indices = [i for i in range(hours_in_data) if i % 24 == hour]

        if not hour_indices:
            continue

        hour_consumption = consumption[hour_indices]
        hour_production = pv_production[hour_indices]
        hour_self_consumption = np.minimum(hour_consumption, hour_production)

        avg_consumption = float(np.mean(hour_consumption))
        avg_production = float(np.mean(hour_production))
        avg_self_consumed = float(np.mean(hour_self_consumption))

        total_production_hour = np.sum(hour_production)
        total_self_consumed_hour = np.sum(hour_self_consumption)

        self_consumption_rate = (total_self_consumed_hour / total_production_hour * 100) if total_production_hour > 0 else 0

        hourly_stats.append(HourlyStatisticsResult(
            hour=hour,
            avg_consumption=avg_consumption,
            avg_production=avg_production,
            avg_self_consumption=avg_self_consumed,
            max_consumption=float(np.max(hour_consumption)),
            max_production=float(np.max(hour_production)),
            self_consumption_rate=self_consumption_rate
        ))

    return hourly_stats

def calculate_curtailment_analysis(
    consumption: np.ndarray,
    pv_production: np.ndarray,
    inverter_limit: Optional[float] = None
) -> CurtailmentAnalysisResult:
    """
    Analyze PV curtailment (production that cannot be used due to inverter limits or zero export)
    """
    # Calculate excess (production > consumption)
    excess = np.maximum(0, pv_production - consumption)

    # If inverter limit is set, calculate clipped energy
    if inverter_limit:
        clipped = np.maximum(0, pv_production - inverter_limit)
        total_curtailed = float(np.sum(clipped))
    else:
        # Curtailment = excess that cannot be exported (assuming zero export)
        total_curtailed = float(np.sum(excess))

    curtailment_hours = int(np.sum(excess > 0))
    total_production = float(np.sum(pv_production))
    curtailment_percentage = (total_curtailed / total_production * 100) if total_production > 0 else 0

    # Monthly curtailment
    monthly_curtailment = []
    days_in_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    hour_idx = 0

    for days in days_in_month:
        month_hours = days * 24
        month_end = min(hour_idx + month_hours, len(excess))
        month_curtailed = float(np.sum(excess[hour_idx:month_end]))
        monthly_curtailment.append(month_curtailed)
        hour_idx = month_end

    # Hourly curtailment pattern (average by hour of day)
    hourly_pattern = []
    for hour in range(24):
        hour_indices = [i for i in range(len(excess)) if i % 24 == hour]
        if hour_indices:
            hourly_pattern.append(float(np.mean(excess[hour_indices])))
        else:
            hourly_pattern.append(0.0)

    return CurtailmentAnalysisResult(
        total_curtailed=total_curtailed,
        curtailment_hours=curtailment_hours,
        curtailment_percentage=curtailment_percentage,
        monthly_curtailment=monthly_curtailment,
        hourly_curtailment_pattern=hourly_pattern
    )

def calculate_energy_balance(
    consumption: np.ndarray,
    pv_production: np.ndarray
) -> EnergyBalanceResult:
    """
    Calculate detailed energy balance
    """
    self_consumed = np.minimum(consumption, pv_production)
    grid_import = np.maximum(0, consumption - pv_production)
    grid_export = np.maximum(0, pv_production - consumption)

    total_consumption = float(np.sum(consumption))
    total_production = float(np.sum(pv_production))
    total_self_consumed = float(np.sum(self_consumed))
    total_grid_import = float(np.sum(grid_import))
    total_grid_export = float(np.sum(grid_export))

    self_sufficiency = (total_self_consumed / total_consumption * 100) if total_consumption > 0 else 0
    self_consumption_rate = (total_self_consumed / total_production * 100) if total_production > 0 else 0

    # Monthly balance
    monthly_balance = []
    days_in_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    hour_idx = 0

    for month, days in enumerate(days_in_month):
        month_hours = days * 24
        month_end = min(hour_idx + month_hours, len(consumption))

        month_consumption = float(np.sum(consumption[hour_idx:month_end]))
        month_production = float(np.sum(pv_production[hour_idx:month_end]))
        month_self_consumed = float(np.sum(self_consumed[hour_idx:month_end]))
        month_import = float(np.sum(grid_import[hour_idx:month_end]))
        month_export = float(np.sum(grid_export[hour_idx:month_end]))

        monthly_balance.append({
            "month": month + 1,
            "consumption": month_consumption,
            "production": month_production,
            "self_consumed": month_self_consumed,
            "grid_import": month_import,
            "grid_export": month_export,
            "self_sufficiency": (month_self_consumed / month_consumption * 100) if month_consumption > 0 else 0
        })

        hour_idx = month_end

    return EnergyBalanceResult(
        total_consumption=total_consumption,
        total_production=total_production,
        total_self_consumed=total_self_consumed,
        total_grid_import=total_grid_import,
        total_grid_export=total_grid_export,
        self_sufficiency=self_sufficiency,
        self_consumption=self_consumption_rate,
        monthly_balance=monthly_balance
    )

def calculate_weekend_analysis(
    consumption: np.ndarray,
    pv_production: np.ndarray,
    start_date_weekday: int = 0  # 0=Monday, 6=Sunday
) -> WeekendAnalysisResult:
    """
    Analyze differences between weekdays and weekends
    start_date_weekday: day of week for first data point (0=Monday)
    """
    weekday_consumption = []
    weekend_consumption = []
    weekday_production = []
    weekend_production = []
    weekday_self_cons = []
    weekend_self_cons = []

    for i in range(len(consumption)):
        day_of_year = i // 24
        day_of_week = (start_date_weekday + day_of_year) % 7

        is_weekend = day_of_week >= 5  # Saturday=5, Sunday=6

        self_cons = min(consumption[i], pv_production[i])

        if is_weekend:
            weekend_consumption.append(consumption[i])
            weekend_production.append(pv_production[i])
            weekend_self_cons.append(self_cons)
        else:
            weekday_consumption.append(consumption[i])
            weekday_production.append(pv_production[i])
            weekday_self_cons.append(self_cons)

    weekday_avg_cons = float(np.mean(weekday_consumption)) if weekday_consumption else 0
    weekend_avg_cons = float(np.mean(weekend_consumption)) if weekend_consumption else 0
    weekday_avg_prod = float(np.mean(weekday_production)) if weekday_production else 0
    weekend_avg_prod = float(np.mean(weekend_production)) if weekend_production else 0

    weekday_total_prod = sum(weekday_production)
    weekday_total_self = sum(weekday_self_cons)
    weekend_total_prod = sum(weekend_production)
    weekend_total_self = sum(weekend_self_cons)

    weekday_sc_rate = (weekday_total_self / weekday_total_prod * 100) if weekday_total_prod > 0 else 0
    weekend_sc_rate = (weekend_total_self / weekend_total_prod * 100) if weekend_total_prod > 0 else 0

    weekend_excess = sum([max(0, weekend_production[i] - weekend_consumption[i]) for i in range(len(weekend_production))])
    weekend_total = sum(weekend_production) if weekend_production else 1
    weekend_excess_pct = (weekend_excess / weekend_total * 100)

    return WeekendAnalysisResult(
        weekday_avg_consumption=weekday_avg_cons,
        weekend_avg_consumption=weekend_avg_cons,
        weekday_avg_production=weekday_avg_prod,
        weekend_avg_production=weekend_avg_prod,
        weekday_self_consumption_rate=weekday_sc_rate,
        weekend_self_consumption_rate=weekend_sc_rate,
        weekend_excess_percentage=weekend_excess_pct
    )

def generate_insights(
    load_duration: LoadDurationCurveResult,
    energy_balance: EnergyBalanceResult,
    curtailment: Optional[CurtailmentAnalysisResult],
    weekend_analysis: Optional[WeekendAnalysisResult]
) -> List[str]:
    """
    Generate actionable insights based on the analysis
    """
    insights = []

    # Load factor insight
    if load_duration.load_factor < 0.5:
        insights.append(f"Your load factor is {load_duration.load_factor:.1%}, indicating significant peaks. Consider load shifting to improve PV utilization.")
    elif load_duration.load_factor > 0.7:
        insights.append(f"Excellent load factor of {load_duration.load_factor:.1%}. Your consumption pattern is well-suited for PV systems.")

    # Self-consumption insight
    if energy_balance.self_consumption < 70:
        insights.append(f"Self-consumption rate is {energy_balance.self_consumption:.1f}%. Consider adding battery storage or reducing PV capacity.")
    elif energy_balance.self_consumption > 90:
        insights.append(f"High self-consumption rate of {energy_balance.self_consumption:.1f}%. You could potentially increase PV capacity.")

    # Curtailment insight
    if curtailment and curtailment.curtailment_percentage > 5:
        insights.append(f"Significant curtailment detected ({curtailment.curtailment_percentage:.1f}%). Consider battery storage or reviewing inverter sizing.")

    # Weekend insight
    if weekend_analysis and weekend_analysis.weekend_excess_percentage > 50:
        insights.append(f"High weekend excess ({weekend_analysis.weekend_excess_percentage:.1f}%). Weekend consumption is significantly lower than production.")

    return insights

# ============== API Endpoints ==============

@app.get("/")
async def root():
    return {
        "service": "Advanced Analytics Service",
        "version": "1.0.0",
        "status": "running"
    }

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.post("/analyze-kpi", response_model=AdvancedKPIResult)
async def analyze_advanced_kpi(
    consumption: List[float],
    pv_production: List[float],
    capacity: float,
    include_curtailment: bool = True,
    include_weekend: bool = True,
    inverter_limit: Optional[float] = None
):
    """
    Perform comprehensive advanced KPI analysis
    """
    try:
        cons_array = np.array(consumption)
        pv_array = np.array(pv_production)

        if len(cons_array) != len(pv_array):
            raise HTTPException(status_code=400, detail="Consumption and production arrays must have same length")

        # Calculate all metrics
        load_duration = calculate_load_duration_curve(cons_array, pv_array, capacity)
        hourly_stats = calculate_hourly_statistics(cons_array, pv_array)
        energy_balance = calculate_energy_balance(cons_array, pv_array)

        curtailment = None
        if include_curtailment:
            curtailment = calculate_curtailment_analysis(cons_array, pv_array, inverter_limit)

        weekend_analysis = None
        if include_weekend:
            weekend_analysis = calculate_weekend_analysis(cons_array, pv_array)

        # Generate insights
        insights = generate_insights(load_duration, energy_balance, curtailment, weekend_analysis)

        return AdvancedKPIResult(
            load_duration=load_duration,
            hourly_stats=hourly_stats,
            curtailment=curtailment,
            energy_balance=energy_balance,
            weekend_analysis=weekend_analysis,
            insights=insights
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004)

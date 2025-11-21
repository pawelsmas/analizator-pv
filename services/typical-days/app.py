from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Optional
import numpy as np
from scipy import stats
from datetime import datetime, timedelta

app = FastAPI(title="Typical Days Analysis Service", version="1.0.0")

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============== Models ==============
class DayProfile(BaseModel):
    day_index: int
    date: str
    consumption_total: float
    production_total: float
    self_consumption_rate: float
    grid_import: float
    grid_export: float
    net_balance: float
    hourly_consumption: List[float]
    hourly_production: List[float]

class SeasonalPattern(BaseModel):
    season: str  # "winter", "spring", "summer", "fall"
    months: List[int]
    avg_consumption: float
    avg_production: float
    avg_self_consumption_rate: float
    typical_day: DayProfile
    peak_production_hour: int
    peak_consumption_hour: int

class WeekdayPattern(BaseModel):
    day_type: str  # "workday" or "weekend"
    avg_consumption: float
    avg_production: float
    avg_self_consumption_rate: float
    typical_profile: List[float]  # 24 hours average
    peak_hours: List[int]

class TypicalDaysResult(BaseModel):
    best_day: DayProfile
    worst_day: DayProfile
    typical_workday: DayProfile
    typical_weekend: DayProfile
    seasonal_patterns: List[SeasonalPattern]
    workday_pattern: WeekdayPattern
    weekend_pattern: WeekdayPattern
    insights: List[str]

# ============== Calculation Functions ==============

def get_day_profiles(
    consumption: np.ndarray,
    pv_production: np.ndarray,
    start_date: str = "2024-01-01"
) -> List[DayProfile]:
    """
    Extract daily profiles from hourly data
    """
    num_hours = len(consumption)
    num_days = num_hours // 24

    start = datetime.strptime(start_date, "%Y-%m-%d")
    profiles = []

    for day in range(num_days):
        day_start = day * 24
        day_end = day_start + 24

        if day_end > num_hours:
            break

        day_cons = consumption[day_start:day_end]
        day_prod = pv_production[day_start:day_end]

        # Calculate daily metrics
        self_cons = np.minimum(day_cons, day_prod)
        grid_import = np.maximum(0, day_cons - day_prod)
        grid_export = np.maximum(0, day_prod - day_cons)

        total_cons = float(np.sum(day_cons))
        total_prod = float(np.sum(day_prod))
        total_self_cons = float(np.sum(self_cons))
        total_import = float(np.sum(grid_import))
        total_export = float(np.sum(grid_export))

        sc_rate = (total_self_cons / total_prod * 100) if total_prod > 0 else 0
        net_balance = total_prod - total_cons

        current_date = start + timedelta(days=day)

        profiles.append(DayProfile(
            day_index=day,
            date=current_date.strftime("%Y-%m-%d"),
            consumption_total=total_cons,
            production_total=total_prod,
            self_consumption_rate=sc_rate,
            grid_import=total_import,
            grid_export=total_export,
            net_balance=net_balance,
            hourly_consumption=day_cons.tolist(),
            hourly_production=day_prod.tolist()
        ))

    return profiles

def find_typical_day(profiles: List[DayProfile], day_type: str = "all") -> DayProfile:
    """
    Find the most typical day using statistical distance from mean
    Uses Euclidean distance in normalized consumption/production space
    """
    # Filter by day type if specified
    if day_type == "workday":
        # Assuming weekdays are days 0-4, 7-11, etc. (Mon-Fri)
        filtered = [p for p in profiles if (p.day_index % 7) < 5]
    elif day_type == "weekend":
        filtered = [p for p in profiles if (p.day_index % 7) >= 5]
    else:
        filtered = profiles

    if not filtered:
        return profiles[0]

    # Calculate mean profile
    all_hourly_cons = np.array([p.hourly_consumption for p in filtered])
    all_hourly_prod = np.array([p.hourly_production for p in filtered])

    mean_cons = np.mean(all_hourly_cons, axis=0)
    mean_prod = np.mean(all_hourly_prod, axis=0)

    # Normalize to 0-1 range for fair comparison
    max_cons = np.max(all_hourly_cons)
    max_prod = np.max(all_hourly_prod)

    if max_cons > 0:
        mean_cons_norm = mean_cons / max_cons
    else:
        mean_cons_norm = mean_cons

    if max_prod > 0:
        mean_prod_norm = mean_prod / max_prod
    else:
        mean_prod_norm = mean_prod

    # Find day with minimum distance to mean
    min_distance = float('inf')
    typical = filtered[0]

    for profile in filtered:
        cons_norm = np.array(profile.hourly_consumption) / max_cons if max_cons > 0 else np.array(profile.hourly_consumption)
        prod_norm = np.array(profile.hourly_production) / max_prod if max_prod > 0 else np.array(profile.hourly_production)

        # Euclidean distance in normalized space
        distance = np.sqrt(
            np.sum((cons_norm - mean_cons_norm)**2) +
            np.sum((prod_norm - mean_prod_norm)**2)
        )

        if distance < min_distance:
            min_distance = distance
            typical = profile

    return typical

def calculate_seasonal_patterns(
    profiles: List[DayProfile],
    start_date: str = "2024-01-01"
) -> List[SeasonalPattern]:
    """
    Analyze seasonal patterns (winter, spring, summer, fall)
    """
    start = datetime.strptime(start_date, "%Y-%m-%d")

    # Define seasons by month (Northern Hemisphere)
    seasons = {
        "winter": [12, 1, 2],
        "spring": [3, 4, 5],
        "summer": [6, 7, 8],
        "fall": [9, 10, 11]
    }

    seasonal_patterns = []

    for season_name, months in seasons.items():
        # Filter profiles for this season
        season_profiles = []
        for profile in profiles:
            day_date = datetime.strptime(profile.date, "%Y-%m-%d")
            if day_date.month in months:
                season_profiles.append(profile)

        if not season_profiles:
            continue

        # Calculate seasonal statistics
        avg_cons = np.mean([p.consumption_total for p in season_profiles])
        avg_prod = np.mean([p.production_total for p in season_profiles])
        avg_sc_rate = np.mean([p.self_consumption_rate for p in season_profiles])

        # Find typical day for this season
        typical = find_typical_day(season_profiles, "all")

        # Find peak hours
        all_hourly_prod = np.array([p.hourly_production for p in season_profiles])
        all_hourly_cons = np.array([p.hourly_consumption for p in season_profiles])

        avg_hourly_prod = np.mean(all_hourly_prod, axis=0)
        avg_hourly_cons = np.mean(all_hourly_cons, axis=0)

        peak_prod_hour = int(np.argmax(avg_hourly_prod))
        peak_cons_hour = int(np.argmax(avg_hourly_cons))

        seasonal_patterns.append(SeasonalPattern(
            season=season_name,
            months=months,
            avg_consumption=float(avg_cons),
            avg_production=float(avg_prod),
            avg_self_consumption_rate=float(avg_sc_rate),
            typical_day=typical,
            peak_production_hour=peak_prod_hour,
            peak_consumption_hour=peak_cons_hour
        ))

    return seasonal_patterns

def calculate_weekday_patterns(profiles: List[DayProfile]) -> tuple[WeekdayPattern, WeekdayPattern]:
    """
    Calculate patterns for workdays vs weekends
    """
    workday_profiles = [p for p in profiles if (p.day_index % 7) < 5]
    weekend_profiles = [p for p in profiles if (p.day_index % 7) >= 5]

    def create_pattern(day_profiles: List[DayProfile], day_type: str) -> WeekdayPattern:
        if not day_profiles:
            return WeekdayPattern(
                day_type=day_type,
                avg_consumption=0,
                avg_production=0,
                avg_self_consumption_rate=0,
                typical_profile=[0] * 24,
                peak_hours=[]
            )

        avg_cons = np.mean([p.consumption_total for p in day_profiles])
        avg_prod = np.mean([p.production_total for p in day_profiles])
        avg_sc = np.mean([p.self_consumption_rate for p in day_profiles])

        # Calculate average hourly profile
        all_hourly = np.array([p.hourly_consumption for p in day_profiles])
        avg_profile = np.mean(all_hourly, axis=0)

        # Find peak hours (consumption above 75th percentile)
        threshold = np.percentile(avg_profile, 75)
        peak_hours = [i for i, v in enumerate(avg_profile) if v >= threshold]

        return WeekdayPattern(
            day_type=day_type,
            avg_consumption=float(avg_cons),
            avg_production=float(avg_prod),
            avg_self_consumption_rate=float(avg_sc),
            typical_profile=avg_profile.tolist(),
            peak_hours=peak_hours
        )

    workday_pattern = create_pattern(workday_profiles, "workday")
    weekend_pattern = create_pattern(weekend_profiles, "weekend")

    return workday_pattern, weekend_pattern

def generate_insights(
    best_day: DayProfile,
    worst_day: DayProfile,
    seasonal: List[SeasonalPattern],
    workday: WeekdayPattern,
    weekend: WeekdayPattern
) -> List[str]:
    """
    Generate actionable insights from typical day analysis
    """
    insights = []

    # Best/worst day comparison
    improvement_potential = ((best_day.self_consumption_rate - worst_day.self_consumption_rate) /
                            worst_day.self_consumption_rate * 100) if worst_day.self_consumption_rate > 0 else 0

    if improvement_potential > 50:
        insights.append(f"High variability detected: best day is {improvement_potential:.0f}% better than worst. "
                       f"Consistent load shifting could significantly improve performance.")

    # Seasonal insights
    if seasonal:
        summer = next((s for s in seasonal if s.season == "summer"), None)
        winter = next((s for s in seasonal if s.season == "winter"), None)

        if summer and winter:
            seasonal_diff = ((summer.avg_production - winter.avg_production) / winter.avg_production * 100) if winter.avg_production > 0 else 0
            if seasonal_diff > 200:
                insights.append(f"Summer production is {seasonal_diff:.0f}% higher than winter. "
                               f"Consider seasonal load adjustment or summer storage options.")

    # Workday vs weekend
    if workday.avg_consumption > 0 and weekend.avg_consumption > 0:
        weekend_diff = ((workday.avg_consumption - weekend.avg_consumption) / weekend.avg_consumption * 100)
        if abs(weekend_diff) > 30:
            if weekend_diff > 0:
                insights.append(f"Workday consumption is {abs(weekend_diff):.0f}% higher than weekends. "
                               f"Weekend excess could be used for battery charging or flexible loads.")
            else:
                insights.append(f"Weekend consumption is {abs(weekend_diff):.0f}% higher than workdays. "
                               f"This is unusual - consider if this pattern is intentional.")

    # Peak hour alignment
    for season_pattern in seasonal:
        peak_gap = abs(season_pattern.peak_production_hour - season_pattern.peak_consumption_hour)
        if peak_gap > 4:
            insights.append(f"In {season_pattern.season}, peak consumption (hour {season_pattern.peak_consumption_hour}) "
                           f"is {peak_gap} hours away from peak production (hour {season_pattern.peak_production_hour}). "
                           f"Load shifting or storage recommended.")

    return insights

# ============== API Endpoints ==============

@app.get("/")
async def root():
    return {
        "service": "Typical Days Analysis Service",
        "version": "1.0.0",
        "status": "running"
    }

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.post("/analyze-typical-days", response_model=TypicalDaysResult)
async def analyze_typical_days(
    consumption: List[float],
    pv_production: List[float],
    start_date: str = "2024-01-01"
):
    """
    Analyze typical day patterns, seasonal variations, and workday/weekend differences
    """
    try:
        cons_array = np.array(consumption)
        pv_array = np.array(pv_production)

        if len(cons_array) != len(pv_array):
            raise HTTPException(status_code=400, detail="Consumption and production arrays must have same length")

        if len(cons_array) < 24:
            raise HTTPException(status_code=400, detail="Need at least 24 hours of data")

        # Get all day profiles
        profiles = get_day_profiles(cons_array, pv_array, start_date)

        if len(profiles) < 1:
            raise HTTPException(status_code=400, detail="Insufficient data to analyze days")

        # Find best and worst days based on self-consumption rate
        best_day = max(profiles, key=lambda p: p.self_consumption_rate)
        worst_day = min(profiles, key=lambda p: p.self_consumption_rate)

        # Find typical workday and weekend
        typical_workday = find_typical_day(profiles, "workday")
        typical_weekend = find_typical_day(profiles, "weekend")

        # Analyze seasonal patterns
        seasonal_patterns = calculate_seasonal_patterns(profiles, start_date)

        # Analyze workday/weekend patterns
        workday_pattern, weekend_pattern = calculate_weekday_patterns(profiles)

        # Generate insights
        insights = generate_insights(best_day, worst_day, seasonal_patterns, workday_pattern, weekend_pattern)

        return TypicalDaysResult(
            best_day=best_day,
            worst_day=worst_day,
            typical_workday=typical_workday,
            typical_weekend=typical_weekend,
            seasonal_patterns=seasonal_patterns,
            workday_pattern=workday_pattern,
            weekend_pattern=weekend_pattern,
            insights=insights
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8005)

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Tuple
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import calendar
import io
import json

app = FastAPI(title="PV Data Analysis Service", version="2.1.0")

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============== Models ==============
class DataStatistics(BaseModel):
    # Basic stats
    total_consumption_gwh: float
    peak_power_mw: float
    min_power_kw: float
    avg_power_mw: float
    days: int
    hours: int
    avg_daily_mwh: float
    # Calculated metrics
    std_dev_mw: float
    variation_coef_pct: float
    load_factor_pct: float
    # Date range
    date_start: str
    date_end: str
    # Monthly data
    monthly_consumption: List[float]
    monthly_peaks: List[float]
    # Daily profile (24 hours average)
    daily_profile_mw: List[float]
    # Weekly profile (7 days average)
    weekly_profile_mwh: List[float]

class HourlyData(BaseModel):
    timestamps: List[str]
    values: List[float]

class ConsumptionAnalysisRequest(BaseModel):
    month: Optional[int] = 0  # 0 = all months
    display_mode: str = "daily"  # daily, hourly, weekly

class HeatmapData(BaseModel):
    week_hour_matrix: List[List[float]]
    month_day_matrix: List[List[float]]

class AnalyticalYear(BaseModel):
    """
    Rok analityczny = dowolne 365/366 kolejnych dni
    Może zaczynać się od dowolnej daty (np. 2024-07-01 do 2025-06-30)
    """
    start_date: str  # Data początkowa (YYYY-MM-DD)
    end_date: str    # Data końcowa (YYYY-MM-DD)
    total_days: int  # Liczba dni w roku analitycznym
    total_hours: int # Liczba godzin w roku analitycznym
    is_complete: bool  # Czy mamy pełny rok (365/366 dni)
    is_leap_year: bool  # Czy rok analityczny zawiera 29 lutego
    months_coverage: List[dict]  # Lista miesięcy z pokryciem danych

# ============== Global Storage ==============
class DataStore:
    def __init__(self):
        self.hourly_data = []
        self.year_hours = []
        self.raw_dataframe = None
        # Analytical year metadata
        self.analytical_year: Optional[AnalyticalYear] = None
        self.start_date: Optional[datetime] = None
        self.end_date: Optional[datetime] = None

data_store = DataStore()

# ============== Utility Functions ==============

def calculate_analytical_year(start_date: datetime, end_date: datetime) -> AnalyticalYear:
    """
    Oblicz rok analityczny na podstawie zakresu dat.

    Rok analityczny = dowolne 365/366 kolejnych dni, niezależnie od roku kalendarzowego.
    Np. 2024-07-01 do 2025-06-30 = pełny rok analityczny.
    """
    total_days = (end_date.date() - start_date.date()).days + 1
    total_hours = total_days * 24

    # Sprawdź czy mamy pełny rok (365 lub 366 dni)
    is_complete = total_days >= 365

    # Sprawdź czy w zakresie dat jest 29 lutego
    is_leap_year = False
    current = start_date
    while current <= end_date:
        if current.month == 2 and current.day == 29:
            is_leap_year = True
            break
        # Szybkie przeskoczenie do kolejnego roku jeśli już minęliśmy luty
        if current.month > 2:
            current = datetime(current.year + 1, 1, 1)
        else:
            current += timedelta(days=1)

    # Oblicz pokrycie miesięczne
    months_coverage = []
    current_month = datetime(start_date.year, start_date.month, 1)

    while current_month <= end_date:
        year = current_month.year
        month = current_month.month

        # Pierwszy dzień tego miesiąca w naszym zakresie
        month_start = max(start_date, datetime(year, month, 1))

        # Ostatni dzień tego miesiąca
        if month == 12:
            next_month = datetime(year + 1, 1, 1)
        else:
            next_month = datetime(year, month + 1, 1)
        month_end = min(end_date, next_month - timedelta(days=1))

        days_in_month = calendar.monthrange(year, month)[1]
        covered_days = (month_end.date() - month_start.date()).days + 1

        months_coverage.append({
            "year": year,
            "month": month,
            "month_name": calendar.month_name[month],
            "days_total": days_in_month,
            "days_covered": covered_days,
            "coverage_pct": round(covered_days / days_in_month * 100, 1)
        })

        # Przejdź do następnego miesiąca
        current_month = next_month

    return AnalyticalYear(
        start_date=start_date.strftime("%Y-%m-%d"),
        end_date=end_date.strftime("%Y-%m-%d"),
        total_days=total_days,
        total_hours=total_hours,
        is_complete=is_complete,
        is_leap_year=is_leap_year,
        months_coverage=months_coverage
    )

def parse_timestamp(value):
    """Parse various timestamp formats"""
    if pd.isna(value):
        return None

    if isinstance(value, datetime):
        return value

    if isinstance(value, (int, float)):
        # Excel serial date
        if 25000 < value < 50000:
            return pd.Timestamp('1899-12-30') + pd.Timedelta(days=value)
        return pd.Timestamp(value, unit='s')

    # Try parsing string
    try:
        return pd.to_datetime(value, format='mixed', dayfirst=True)
    except:
        return None

def truncate_to_analytical_year(
    hourly_data: np.ndarray,
    year_hours: pd.DatetimeIndex,
    start_date: datetime
) -> Tuple[np.ndarray, pd.DatetimeIndex, datetime]:
    """
    Obcina dane do maksymalnie 365/366 dni (rok analityczny).

    Args:
        hourly_data: Godzinowe dane zużycia
        year_hours: Indeks czasowy (DatetimeIndex)
        start_date: Data początkowa danych

    Returns:
        Tuple: (obcięte_dane, obcięty_indeks_czasowy, data_końcowa)
    """
    total_hours = len(hourly_data)
    total_days = total_hours // 24

    # Sprawdź czy mamy rok przestępny (29 lutego w zakresie)
    max_days = 365

    # Sprawdź czy 29 lutego jest w zakresie pierwszych 366 dni
    potential_end = start_date + timedelta(days=366)
    current = start_date
    while current < potential_end and current <= start_date + timedelta(days=365):
        if current.month == 2 and current.day == 29:
            max_days = 366
            break
        current += timedelta(days=1)

    max_hours = max_days * 24

    if total_hours <= max_hours:
        # Dane mieszczą się w roku analitycznym - zwróć bez zmian
        end_date = start_date + timedelta(hours=total_hours - 1)
        print(f"✅ Dane mieszczą się w roku analitycznym: {total_days} dni <= {max_days} dni")
        return hourly_data, year_hours, end_date

    # Obcięcie danych do roku analitycznego
    print(f"✂️ OBCINANIE: {total_days} dni -> {max_days} dni (usuwamy {total_days - max_days} dni nadmiarowych)")

    truncated_data = hourly_data[:max_hours]
    truncated_hours = year_hours[:max_hours]
    end_date = start_date + timedelta(days=max_days - 1, hours=23)

    print(f"✂️ Nowy zakres: {start_date.strftime('%Y-%m-%d')} do {end_date.strftime('%Y-%m-%d')}")

    return truncated_data, truncated_hours, end_date


def process_uploaded_data(df: pd.DataFrame):
    """Process uploaded consumption data and truncate to analytical year (max 365/366 days)"""
    if df.empty:
        raise HTTPException(status_code=400, detail="No data in file")

    # Find time column
    time_cols = [col for col in df.columns if any(
        keyword in col.lower() for keyword in ['timestamp', 'data', 'czas', 'date', 'datetime', 'time']
    )]

    if not time_cols:
        raise HTTPException(status_code=400, detail="Time column not found")

    time_key = time_cols[0]

    # Find power/energy column
    # First check for exact kW column (not kWh)
    kw_cols = [col for col in df.columns if (
        col.lower() == 'kw' or
        col.lower() == 'moc' or
        ('power' in col.lower() and 'kwh' not in col.lower())
    )]

    kwh_cols = [col for col in df.columns if (
        'kwh' in col.lower() or
        ('energia' in col.lower() and 'energy' in col.lower())
    )]

    kw_key = kw_cols[0] if kw_cols else None
    kwh_key = kwh_cols[0] if kwh_cols else None

    if not kw_key and not kwh_key:
        raise HTTPException(status_code=400, detail="No power or energy column found")

    # Parse timestamps
    print(f"DEBUG: Using time column '{time_key}'")
    print(f"DEBUG: First 3 timestamp values: {df[time_key].head(3).tolist()}")

    df['parsed_time'] = df[time_key].apply(parse_timestamp)
    valid_timestamps = df['parsed_time'].notna().sum()
    print(f"DEBUG: Valid timestamps after parsing: {valid_timestamps}/{len(df)}")

    df = df.dropna(subset=['parsed_time'])
    print(f"DEBUG: Rows after dropping null timestamps: {len(df)}")

    # Parse power values
    # Try kWh first (often has data when kW is empty)
    if kwh_key:
        print(f"DEBUG: Trying kWh column '{kwh_key}' first")
        print(f"DEBUG: First 5 kWh raw values: {df[kwh_key].head(5).tolist()}")
        df['kw'] = pd.to_numeric(df[kwh_key], errors='coerce') * 4  # 15-min kWh to kW
        print(f"DEBUG: After kWh parse, valid values: {df['kw'].notna().sum()}")

        # If kWh column is empty but kW exists, try kW instead
        if df['kw'].notna().sum() == 0 and kw_key:
            print(f"DEBUG: kWh column empty, trying kW column '{kw_key}'")
            print(f"DEBUG: First 5 kW raw values: {df[kw_key].head(5).tolist()}")
            df['kw'] = pd.to_numeric(df[kw_key], errors='coerce')
    elif kw_key:
        print(f"DEBUG: Using kW column '{kw_key}'")
        print(f"DEBUG: First 5 kW raw values: {df[kw_key].head(5).tolist()}")
        df['kw'] = pd.to_numeric(df[kw_key], errors='coerce')

    valid_power = df['kw'].notna().sum()
    print(f"DEBUG: Valid power values after parsing: {valid_power}/{len(df)}")

    df = df.dropna(subset=['kw'])
    print(f"DEBUG: Rows after dropping null kW: {len(df)}")

    df = df[df['kw'] >= 0]
    print(f"DEBUG: Rows after filtering negative kW: {len(df)}")

    df = df.sort_values('parsed_time')

    if len(df) < 10:
        raise HTTPException(status_code=400, detail=f"Not enough valid data points. Only {len(df)} rows remain after processing. Check your timestamp and power column formats.")

    # Use actual date range from data (not padded to full year)
    first_timestamp = df['parsed_time'].iloc[0]
    last_timestamp = df['parsed_time'].iloc[-1]

    # Round start to beginning of hour, end to end of hour
    start = first_timestamp.replace(minute=0, second=0, microsecond=0)
    end = last_timestamp.replace(minute=0, second=0, microsecond=0) + pd.Timedelta(hours=1)

    print(f"📅 Data range: {start} to {end}")
    print(f"📅 Total hours in data: {int((end - start).total_seconds() // 3600)}")

    year_hours = pd.date_range(start=start, end=end, freq='H', inclusive='left')
    hourly_data = np.zeros(len(year_hours))

    # Aggregate to hourly
    for i in range(1, len(df)):
        t0 = df.iloc[i-1]['parsed_time']
        t1 = df.iloc[i]['parsed_time']
        dt = (t1 - t0).total_seconds()

        if dt <= 0 or dt > 6 * 3600:
            continue

        kw = df.iloc[i-1]['kw']
        current_time = t0

        while current_time < t1:
            hour_end = current_time.replace(minute=0, second=0, microsecond=0) + pd.Timedelta(hours=1)
            segment_end = min(hour_end, t1)
            segment_duration = (segment_end - current_time).total_seconds()

            hour_index = int((current_time - start).total_seconds() // 3600)
            if 0 <= hour_index < len(hourly_data):
                hourly_data[hour_index] += kw * (segment_duration / 3600)

            current_time = segment_end

    # Convert pandas Timestamp to datetime for truncation
    start_dt = start.to_pydatetime() if hasattr(start, 'to_pydatetime') else start

    # KLUCZOWE: Obcięcie danych do roku analitycznego (max 365/366 dni)
    # To zapewnia, że wszystkie statystyki i obliczenia używają tylko danych z roku analitycznego
    truncated_data, truncated_hours, end_dt = truncate_to_analytical_year(
        hourly_data,
        year_hours,
        start_dt
    )

    # Store truncated data in global data store
    data_store.hourly_data = truncated_data.tolist()
    data_store.year_hours = [t.isoformat() for t in truncated_hours]
    data_store.raw_dataframe = df

    # Store analytical year metadata
    data_store.start_date = start_dt
    data_store.end_date = end_dt
    data_store.analytical_year = calculate_analytical_year(start_dt, end_dt)

    print(f"📊 Rok analityczny: {data_store.analytical_year.start_date} do {data_store.analytical_year.end_date}")
    print(f"📊 Dni: {data_store.analytical_year.total_days}, Godziny: {data_store.analytical_year.total_hours}")
    print(f"📊 Pełny rok: {data_store.analytical_year.is_complete}, Rok przestępny: {data_store.analytical_year.is_leap_year}")

    return truncated_data, truncated_hours

# ============== API Endpoints ==============
@app.get("/")
async def root():
    return {
        "service": "PV Data Analysis Service",
        "version": "2.1.0",
        "status": "running",
        "features": ["analytical_year", "dynamic_date_range", "auto_truncation"]
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "data_loaded": len(data_store.hourly_data) > 0
    }

@app.get("/analytical-year", response_model=AnalyticalYear)
async def get_analytical_year():
    """
    Pobierz informacje o roku analitycznym.

    Rok analityczny = dowolne 365/366 kolejnych dni, niezależnie od roku kalendarzowego.
    Inne serwisy (pv-calculation, typical-days) używają tego endpointu
    do synchronizacji zakresu dat.
    """
    if not data_store.analytical_year:
        raise HTTPException(status_code=400, detail="No data loaded - analytical year not available")

    return data_store.analytical_year

@app.get("/analytical-year/date-range")
async def get_date_range():
    """
    Pobierz prosty zakres dat roku analitycznego.
    Używane przez inne serwisy do mapowania danych.
    """
    if not data_store.analytical_year:
        raise HTTPException(status_code=400, detail="No data loaded")

    return {
        "start_date": data_store.analytical_year.start_date,
        "end_date": data_store.analytical_year.end_date,
        "total_days": data_store.analytical_year.total_days,
        "total_hours": data_store.analytical_year.total_hours,
        "timestamps": data_store.year_hours
    }

@app.post("/upload/csv")
async def upload_csv(file: UploadFile = File(...)):
    """Upload and process CSV consumption data"""
    try:
        content = await file.read()
        df = pd.read_csv(io.BytesIO(content))

        hourly_data, year_hours = process_uploaded_data(df)

        return {
            "success": True,
            "message": f"Data loaded successfully",
            "data_points": len(hourly_data),
            "year": pd.to_datetime(year_hours[0]).year
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/upload/excel")
async def upload_excel(file: UploadFile = File(...)):
    """Upload and process Excel consumption data"""
    try:
        print(f"Received file: {file.filename}, content_type: {file.content_type}")
        content = await file.read()
        print(f"File size: {len(content)} bytes")

        df = pd.read_excel(io.BytesIO(content))
        print(f"Excel loaded: {len(df)} rows, columns: {df.columns.tolist()}")

        hourly_data, year_hours = process_uploaded_data(df)

        return {
            "success": True,
            "message": f"Data loaded successfully",
            "data_points": len(hourly_data),
            "year": pd.to_datetime(year_hours[0]).year
        }
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"ERROR: {error_details}")
        raise HTTPException(status_code=400, detail=f"{type(e).__name__}: {str(e)}")

@app.get("/statistics", response_model=DataStatistics)
async def get_statistics():
    """Get comprehensive consumption statistics - all calculations done server-side"""
    if not data_store.hourly_data:
        raise HTTPException(status_code=400, detail="No data loaded")

    hourly_data = np.array(data_store.hourly_data)
    timestamps = data_store.year_hours

    # Basic statistics
    total_kwh = hourly_data.sum()
    peak_kw = hourly_data.max()
    min_kw = hourly_data.min()
    avg_kw = hourly_data.mean()
    hours = len(hourly_data)
    days = hours / 24
    avg_daily = total_kwh / days if days > 0 else 0

    # Standard deviation and variation coefficient
    std_dev_kw = np.std(hourly_data)
    variation_coef = (std_dev_kw / avg_kw * 100) if avg_kw > 0 else 0

    # Load factor
    load_factor = (avg_kw / peak_kw * 100) if peak_kw > 0 else 0

    # Date range
    if timestamps:
        date_start = pd.to_datetime(timestamps[0]).strftime('%Y-%m-%d')
        date_end = pd.to_datetime(timestamps[-1]).strftime('%Y-%m-%d')
    else:
        date_start = date_end = ""

    # Monthly statistics (only for months with data)
    monthly_consumption = np.zeros(12)
    monthly_peaks = np.zeros(12)

    for i, timestamp in enumerate(timestamps):
        if i >= len(hourly_data):
            break
        month = pd.to_datetime(timestamp).month - 1
        monthly_consumption[month] += hourly_data[i]
        monthly_peaks[month] = max(monthly_peaks[month], hourly_data[i])

    # Daily profile (24 hours average) - use actual timestamps
    hourly_averages = np.zeros(24)
    hourly_counts = np.zeros(24)

    for i, timestamp in enumerate(timestamps):
        if i >= len(hourly_data):
            break
        hour = pd.to_datetime(timestamp).hour
        hourly_averages[hour] += hourly_data[i]
        hourly_counts[hour] += 1

    daily_profile = np.divide(
        hourly_averages,
        hourly_counts,
        out=np.zeros_like(hourly_averages),
        where=hourly_counts > 0
    ) / 1000  # kW -> MW

    # Weekly profile (7 days average) - Mon=0, Sun=6
    daily_totals = np.zeros(7)
    daily_counts = np.zeros(7)

    for i, timestamp in enumerate(timestamps):
        if i >= len(hourly_data):
            break
        dt = pd.to_datetime(timestamp)
        day_of_week = dt.dayofweek  # Monday = 0
        daily_totals[day_of_week] += hourly_data[i]
        daily_counts[day_of_week] += 1

    # Average daily consumption per day of week (in MWh)
    weekly_profile = np.divide(
        daily_totals,
        daily_counts / 24,  # Convert hour counts to day counts
        out=np.zeros_like(daily_totals),
        where=daily_counts > 0
    ) / 1000  # kWh -> MWh

    return DataStatistics(
        total_consumption_gwh=total_kwh / 1e6,
        peak_power_mw=peak_kw / 1000,
        min_power_kw=min_kw,
        avg_power_mw=avg_kw / 1000,
        days=int(days),
        hours=hours,
        avg_daily_mwh=avg_daily / 1000,
        std_dev_mw=std_dev_kw / 1000,
        variation_coef_pct=float(variation_coef),
        load_factor_pct=float(load_factor),
        date_start=date_start,
        date_end=date_end,
        monthly_consumption=monthly_consumption.tolist(),
        monthly_peaks=monthly_peaks.tolist(),
        daily_profile_mw=daily_profile.tolist(),
        weekly_profile_mwh=weekly_profile.tolist()
    )

@app.get("/hourly-data")
async def get_hourly_data(month: int = 0):
    """Get hourly consumption data, optionally filtered by month"""
    if not data_store.hourly_data:
        raise HTTPException(status_code=400, detail="No data loaded")

    if month == 0:
        return {
            "timestamps": data_store.year_hours,
            "values": data_store.hourly_data
        }
    else:
        filtered_times = []
        filtered_values = []

        for i, timestamp in enumerate(data_store.year_hours):
            if pd.to_datetime(timestamp).month == month:
                filtered_times.append(timestamp)
                filtered_values.append(data_store.hourly_data[i])

        return {
            "timestamps": filtered_times,
            "values": filtered_values
        }

@app.get("/daily-consumption")
async def get_daily_consumption(month: int = 0):
    """Get daily consumption aggregated data"""
    if not data_store.hourly_data:
        raise HTTPException(status_code=400, detail="No data loaded")

    hourly_data = np.array(data_store.hourly_data)
    days = {}

    for i, timestamp in enumerate(data_store.year_hours):
        if i >= len(hourly_data):
            break

        dt = pd.to_datetime(timestamp)

        if month == 0 or dt.month == month:
            day_key = dt.strftime('%Y-%m-%d')
            if day_key not in days:
                days[day_key] = 0
            days[day_key] += hourly_data[i]

    return {
        "dates": list(days.keys()),
        "values": list(days.values())
    }

@app.get("/heatmap", response_model=HeatmapData)
async def get_heatmap_data(month: int = 0):
    """Get heatmap data for visualization"""
    if not data_store.hourly_data:
        raise HTTPException(status_code=400, detail="No data loaded")

    hourly_data = np.array(data_store.hourly_data)

    # Week x Hour heatmap (7 x 24)
    week_hour_matrix = np.zeros((7, 24))
    week_hour_counts = np.zeros((7, 24))

    for i, timestamp in enumerate(data_store.year_hours):
        if i >= len(hourly_data):
            break

        dt = pd.to_datetime(timestamp)

        if month == 0 or dt.month == month:
            dow = dt.dayofweek  # Monday = 0
            hour = dt.hour
            week_hour_matrix[dow, hour] += hourly_data[i]
            week_hour_counts[dow, hour] += 1

    # Average
    with np.errstate(divide='ignore', invalid='ignore'):
        week_hour_matrix = np.where(week_hour_counts > 0,
                                      week_hour_matrix / week_hour_counts,
                                      0)

    # Month day x Hour heatmap (31 x 24)
    month_day_matrix = np.zeros((31, 24))

    for i, timestamp in enumerate(data_store.year_hours):
        if i >= len(hourly_data):
            break

        dt = pd.to_datetime(timestamp)

        if month == 0 or dt.month == month:
            day = dt.day - 1
            hour = dt.hour
            if day < 31:
                month_day_matrix[day, hour] += hourly_data[i]

    return HeatmapData(
        week_hour_matrix=week_hour_matrix.tolist(),
        month_day_matrix=month_day_matrix.tolist()
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)

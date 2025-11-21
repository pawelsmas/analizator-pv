from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import pandas as pd
import numpy as np
from datetime import datetime
import io
import json

app = FastAPI(title="PV Data Analysis Service", version="1.0.0")

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
    total_consumption_gwh: float
    peak_power_mw: float
    days: int
    avg_daily_mwh: float
    monthly_consumption: List[float]
    monthly_peaks: List[float]

class HourlyData(BaseModel):
    timestamps: List[str]
    values: List[float]

class ConsumptionAnalysisRequest(BaseModel):
    month: Optional[int] = 0  # 0 = all months
    display_mode: str = "daily"  # daily, hourly, weekly

class HeatmapData(BaseModel):
    week_hour_matrix: List[List[float]]
    month_day_matrix: List[List[float]]

# ============== Global Storage ==============
class DataStore:
    def __init__(self):
        self.hourly_data = []
        self.year_hours = []
        self.raw_dataframe = None

data_store = DataStore()

# ============== Utility Functions ==============
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

def process_uploaded_data(df: pd.DataFrame):
    """Process uploaded consumption data"""
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

    # Create canonical year hours
    year = df['parsed_time'].iloc[0].year
    start = pd.Timestamp(year, 1, 1, 0, 0, 0)
    end = pd.Timestamp(year + 1, 1, 1, 0, 0, 0)

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

    # Store in global data store
    data_store.hourly_data = hourly_data.tolist()
    data_store.year_hours = [t.isoformat() for t in year_hours]
    data_store.raw_dataframe = df

    return hourly_data, year_hours

# ============== API Endpoints ==============
@app.get("/")
async def root():
    return {
        "service": "PV Data Analysis Service",
        "version": "1.0.0",
        "status": "running"
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "data_loaded": len(data_store.hourly_data) > 0
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
    """Get basic consumption statistics"""
    if not data_store.hourly_data:
        raise HTTPException(status_code=400, detail="No data loaded")

    hourly_data = np.array(data_store.hourly_data)

    total_kwh = hourly_data.sum()
    peak_kw = hourly_data.max()
    days = len(hourly_data) / 24
    avg_daily = total_kwh / days if days > 0 else 0

    # Monthly statistics
    monthly_consumption = np.zeros(12)
    monthly_peaks = np.zeros(12)

    for i, timestamp in enumerate(data_store.year_hours):
        if i >= len(hourly_data):
            break
        month = pd.to_datetime(timestamp).month - 1
        monthly_consumption[month] += hourly_data[i]
        monthly_peaks[month] = max(monthly_peaks[month], hourly_data[i])

    return DataStatistics(
        total_consumption_gwh=total_kwh / 1e6,
        peak_power_mw=peak_kw / 1000,
        days=int(days),
        avg_daily_mwh=avg_daily / 1000,
        monthly_consumption=monthly_consumption.tolist(),
        monthly_peaks=monthly_peaks.tolist()
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

"""
PVGIS Proxy Service
Backend service to bypass CORS restrictions when calling PVGIS API.
Provides endpoints for PVcalc (uncertainty) and Seriescalc (timeseries) methods.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional
import httpx
import math
import statistics
from datetime import datetime
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Prometheus metrics
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(
    title="PVGIS Proxy Service",
    description="Proxy for PVGIS API calls with Pxx factor calculation",
    version="1.0.0"
)

# Initialize Prometheus metrics
Instrumentator().instrument(app).expose(app)

# CORS configuration - allow all origins for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# PVGIS API base URL
PVGIS_BASE_URL = "https://re.jrc.ec.europa.eu/api/v5_3"

# Z-scores for P-values (normal distribution)
Z_P75 = 0.6745  # 75th percentile
Z_P90 = 1.2816  # 90th percentile


class PVCalcRequest(BaseModel):
    """Request model for PVcalc endpoint (uncertainty method)"""
    model_config = {"protected_namespaces": ()}  # Allow field names starting with "model_"

    lat: float = Field(..., description="Latitude", ge=-90, le=90)
    lon: float = Field(..., description="Longitude", ge=-180, le=180)
    peakpower: float = Field(default=1.0, description="Peak power [kWp]")
    loss: float = Field(default=14.0, description="System losses [%]")
    pvtechchoice: str = Field(default="crystSi2025", description="PV technology: crystSi2025 (recommended), crystSi, CIS, CdTe")
    mountingplace: str = Field(default="free", description="Mounting type: free or building")
    raddatabase: str = Field(default="PVGIS-SARAH3", description="Radiation database (SARAH3 data to 2023)")
    angle: Optional[float] = Field(default=None, description="Tilt angle (None=optimal)")
    aspect: float = Field(default=0, description="Azimuth: 0=south, -90=east, 90=west")
    model_uncertainty_pct: float = Field(default=3.0, description="Model uncertainty [%]")
    other_uncertainty_pct: float = Field(default=2.0, description="Other uncertainties [%]")


class SeriesCalcRequest(BaseModel):
    """Request model for Seriescalc endpoint (timeseries method)"""
    lat: float = Field(..., description="Latitude", ge=-90, le=90)
    lon: float = Field(..., description="Longitude", ge=-180, le=180)
    peakpower: float = Field(default=1.0, description="Peak power [kWp]")
    loss: float = Field(default=14.0, description="System losses [%]")
    pvtechchoice: str = Field(default="crystSi2025", description="PV technology: crystSi2025 (recommended), crystSi, CIS, CdTe")
    mountingplace: str = Field(default="free", description="Mounting type: free or building")
    raddatabase: str = Field(default="PVGIS-SARAH3", description="Radiation database (SARAH3 data to 2023)")
    angle: Optional[float] = Field(default=None, description="Tilt angle (None=optimal)")
    aspect: float = Field(default=0, description="Azimuth: 0=south, -90=east, 90=west")
    startyear: int = Field(default=2005, description="Start year for timeseries")
    endyear: int = Field(default=2023, description="End year for timeseries (SARAH3 data available to 2023)")


class PxxResponse(BaseModel):
    """Response model with Pxx factors"""
    p50_factor: float
    p75_factor: float
    p90_factor: float
    e_y_kwh: float  # Expected yearly production
    sigma_rel: Optional[float] = None  # Relative standard deviation (for uncertainty method)
    years_count: Optional[int] = None  # Number of years (for timeseries method)
    method: str
    database: str
    location: dict


# Simple in-memory cache
_cache = {}
CACHE_DURATION_SECONDS = 3600  # 1 hour


def get_cache_key(request_type: str, lat: float, lon: float, **kwargs) -> str:
    """Generate cache key from request parameters"""
    params = f"{request_type}_{lat:.4f}_{lon:.4f}"
    for k, v in sorted(kwargs.items()):
        params += f"_{k}={v}"
    return params


def get_cached(key: str):
    """Get value from cache if not expired"""
    if key in _cache:
        entry = _cache[key]
        if (datetime.now() - entry['timestamp']).total_seconds() < CACHE_DURATION_SECONDS:
            return entry['data']
        else:
            del _cache[key]
    return None


def set_cache(key: str, data):
    """Store value in cache"""
    _cache[key] = {'data': data, 'timestamp': datetime.now()}


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "pvgis-proxy", "version": "1.0.0"}


@app.post("/pvgis/pvcalc", response_model=PxxResponse)
async def pvgis_pvcalc(request: PVCalcRequest):
    """
    Get Pxx factors using PVGIS PVcalc endpoint (uncertainty method).

    This method:
    1. Calls PVGIS PVcalc to get E_y (yearly energy) and sigma (inter-annual variability)
    2. Combines sigma with model and other uncertainties
    3. Calculates P50/P75/P90 factors using normal distribution

    Formula:
    - sigma_total = sqrt(sigma_interannual² + u_model² + u_other²)
    - P75_factor = 1.0 - z_75 * sigma_total_rel
    - P90_factor = 1.0 - z_90 * sigma_total_rel
    """
    # Check cache
    cache_key = get_cache_key(
        "pvcalc", request.lat, request.lon,
        loss=request.loss, db=request.raddatabase,
        u_model=request.model_uncertainty_pct,
        u_other=request.other_uncertainty_pct
    )
    cached = get_cached(cache_key)
    if cached:
        return cached

    # Build PVGIS request URL
    params = {
        "lat": request.lat,
        "lon": request.lon,
        "peakpower": request.peakpower,
        "loss": request.loss,
        "pvtechchoice": request.pvtechchoice,
        "mountingplace": request.mountingplace,
        "raddatabase": request.raddatabase,
        "outputformat": "json"
    }

    if request.angle is not None:
        params["angle"] = request.angle
    else:
        params["optimalangles"] = 1

    if request.aspect != 0:
        params["aspect"] = request.aspect

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{PVGIS_BASE_URL}/PVcalc", params=params)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"PVGIS API error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch from PVGIS: {str(e)}")

    # Extract data from PVGIS response
    try:
        outputs = data.get("outputs", {})
        totals = outputs.get("totals", {})
        fixed = totals.get("fixed", {})

        # E_y: Expected yearly production [kWh]
        e_y = fixed.get("E_y", 0)

        # sigma: Inter-annual variability (standard deviation) [kWh]
        # PVGIS provides SD_y or we can estimate from monthly data
        sd_y = fixed.get("SD_y", 0)

        if e_y <= 0:
            raise ValueError("Invalid E_y value from PVGIS")

        # If SD_y not available, estimate from monthly variability
        if sd_y <= 0:
            monthly = outputs.get("monthly", {}).get("fixed", [])
            if monthly:
                monthly_e = [m.get("E_m", 0) for m in monthly if m.get("E_m", 0) > 0]
                if monthly_e:
                    # Rough estimate: annual sigma ~ 3-5% of E_y for Europe
                    sd_y = e_y * 0.04  # 4% default

        # Relative inter-annual variability
        sigma_interannual_rel = sd_y / e_y if e_y > 0 else 0.04

        # Combined uncertainty (relative)
        u_model_rel = request.model_uncertainty_pct / 100.0
        u_other_rel = request.other_uncertainty_pct / 100.0

        sigma_total_rel = math.sqrt(
            sigma_interannual_rel**2 +
            u_model_rel**2 +
            u_other_rel**2
        )

        # Calculate P-factors
        p50_factor = 1.0  # P50 = median = expected value
        p75_factor = max(0.80, 1.0 - Z_P75 * sigma_total_rel)
        p90_factor = max(0.70, 1.0 - Z_P90 * sigma_total_rel)

        result = PxxResponse(
            p50_factor=round(p50_factor, 4),
            p75_factor=round(p75_factor, 4),
            p90_factor=round(p90_factor, 4),
            e_y_kwh=round(e_y, 2),
            sigma_rel=round(sigma_total_rel, 4),
            method="pvgis_uncertainty",
            database=request.raddatabase,
            location={"lat": request.lat, "lon": request.lon}
        )

        # Cache result
        set_cache(cache_key, result)

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing PVGIS response: {str(e)}")


@app.post("/pvgis/seriescalc", response_model=PxxResponse)
async def pvgis_seriescalc(request: SeriesCalcRequest):
    """
    Get Pxx factors using PVGIS Seriescalc endpoint (timeseries method).

    This method:
    1. Calls PVGIS Seriescalc to get hourly production data for multiple years
    2. Calculates yearly production totals
    3. Derives P50/P75/P90 from actual yearly distribution (quantiles)

    More accurate than uncertainty method but slower (requires more data).
    """
    # Check cache
    cache_key = get_cache_key(
        "seriescalc", request.lat, request.lon,
        loss=request.loss, db=request.raddatabase,
        start=request.startyear, end=request.endyear
    )
    cached = get_cached(cache_key)
    if cached:
        return cached

    # Build PVGIS request URL
    params = {
        "lat": request.lat,
        "lon": request.lon,
        "peakpower": request.peakpower,
        "loss": request.loss,
        "pvtechchoice": request.pvtechchoice,
        "mountingplace": request.mountingplace,
        "raddatabase": request.raddatabase,
        "startyear": request.startyear,
        "endyear": request.endyear,
        "outputformat": "json",
        "pvcalculation": 1
    }

    if request.angle is not None:
        params["angle"] = request.angle
    else:
        params["optimalangles"] = 1

    if request.aspect != 0:
        params["aspect"] = request.aspect

    try:
        logger.info(f"🌐 PVGIS seriescalc request: lat={request.lat}, lon={request.lon}, years={request.startyear}-{request.endyear}")
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.get(f"{PVGIS_BASE_URL}/seriescalc", params=params)
            logger.info(f"📡 PVGIS response status: {response.status_code}")
            response.raise_for_status()
            data = response.json()
            logger.info(f"✅ PVGIS seriescalc success for lat={request.lat}, lon={request.lon}")
    except httpx.TimeoutException as e:
        logger.error(f"⏱️ PVGIS timeout: {str(e)}")
        raise HTTPException(status_code=504, detail=f"PVGIS API timeout (90s exceeded): {str(e)}")
    except httpx.HTTPStatusError as e:
        logger.error(f"❌ PVGIS HTTP error: {e.response.status_code} - {str(e)}")
        raise HTTPException(status_code=e.response.status_code, detail=f"PVGIS API error: {str(e)}")
    except Exception as e:
        logger.error(f"❌ PVGIS fetch failed: {type(e).__name__}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch from PVGIS: {type(e).__name__}: {str(e)}")

    # Process timeseries data
    try:
        outputs = data.get("outputs", {})
        hourly_data = outputs.get("hourly", [])

        if not hourly_data:
            raise ValueError("No hourly data in PVGIS response")

        # Group by year and sum production
        yearly_production = {}

        for entry in hourly_data:
            # Time format: "YYYYMMDD:HHMM"
            time_str = entry.get("time", "")
            if len(time_str) >= 4:
                year = int(time_str[:4])
                # P [W] - PV power output
                power_w = entry.get("P", 0)
                # Convert hourly W to Wh (assuming 1 hour interval)
                energy_wh = power_w

                if year not in yearly_production:
                    yearly_production[year] = 0
                yearly_production[year] += energy_wh

        if not yearly_production:
            raise ValueError("Could not extract yearly production")

        # Convert to kWh
        yearly_kwh = [v / 1000.0 for v in yearly_production.values()]
        years = sorted(yearly_production.keys())

        if len(yearly_kwh) < 3:
            raise ValueError(f"Insufficient years of data ({len(yearly_kwh)})")

        # Calculate statistics
        yearly_kwh_sorted = sorted(yearly_kwh)
        n = len(yearly_kwh_sorted)

        # P50 = median
        if n % 2 == 0:
            p50_kwh = (yearly_kwh_sorted[n//2 - 1] + yearly_kwh_sorted[n//2]) / 2
        else:
            p50_kwh = yearly_kwh_sorted[n//2]

        # P75 = 25th percentile (75% exceedance probability)
        p75_idx = int(0.25 * (n - 1))
        p75_frac = 0.25 * (n - 1) - p75_idx
        p75_kwh = yearly_kwh_sorted[p75_idx] * (1 - p75_frac)
        if p75_idx + 1 < n:
            p75_kwh += yearly_kwh_sorted[p75_idx + 1] * p75_frac

        # P90 = 10th percentile (90% exceedance probability)
        p90_idx = int(0.10 * (n - 1))
        p90_frac = 0.10 * (n - 1) - p90_idx
        p90_kwh = yearly_kwh_sorted[p90_idx] * (1 - p90_frac)
        if p90_idx + 1 < n:
            p90_kwh += yearly_kwh_sorted[p90_idx + 1] * p90_frac

        # Calculate factors relative to P50
        p50_factor = 1.0
        p75_factor = p75_kwh / p50_kwh if p50_kwh > 0 else 0.97
        p90_factor = p90_kwh / p50_kwh if p50_kwh > 0 else 0.94

        # Clamp to reasonable values
        p75_factor = max(0.80, min(1.00, p75_factor))
        p90_factor = max(0.70, min(0.98, p90_factor))

        result = PxxResponse(
            p50_factor=round(p50_factor, 4),
            p75_factor=round(p75_factor, 4),
            p90_factor=round(p90_factor, 4),
            e_y_kwh=round(p50_kwh, 2),
            years_count=len(yearly_kwh),
            method="pvgis_timeseries",
            database=request.raddatabase,
            location={"lat": request.lat, "lon": request.lon}
        )

        # Cache result
        set_cache(cache_key, result)

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing PVGIS timeseries: {str(e)}")


@app.get("/pvgis/databases")
async def list_databases():
    """List available PVGIS radiation databases"""
    return {
        "databases": [
            {"id": "PVGIS-SARAH3", "name": "PVGIS-SARAH3", "region": "Europe, Africa, Asia", "years": "2005-2023"},
            {"id": "PVGIS-SARAH2", "name": "PVGIS-SARAH2", "region": "Europe, Africa, Asia", "years": "2005-2020"},
            {"id": "PVGIS-ERA5", "name": "PVGIS-ERA5", "region": "Global", "years": "2005-2023"},
            {"id": "PVGIS-NSRDB", "name": "PVGIS-NSRDB", "region": "Americas", "years": "1998-2020"}
        ],
        "recommended_for_poland": "PVGIS-SARAH3",
        "note": "PVGIS 5.3 updated SARAH3 and ERA5 data to include years up to 2023"
    }


class HorizonRequest(BaseModel):
    """Request model for horizon profile endpoint"""
    lat: float = Field(..., description="Latitude", ge=-90, le=90)
    lon: float = Field(..., description="Longitude", ge=-180, le=180)
    userhorizon: Optional[list] = Field(default=None, description="User-defined horizon heights in degrees")


class HorizonResponse(BaseModel):
    """Response model for horizon profile"""
    horizon: list  # List of {azimuth, elevation} pairs
    location: dict
    source: str


@app.post("/pvgis/horizon", response_model=HorizonResponse)
async def pvgis_horizon(request: HorizonRequest):
    """
    Get horizon profile for a location using PVGIS printhorizon endpoint.

    Returns horizon elevation angles at various azimuth points (clockwise from North).
    The horizon data shows terrain obstructions that affect solar irradiance.
    """
    # Check cache
    cache_key = get_cache_key("horizon", request.lat, request.lon)
    cached = get_cached(cache_key)
    if cached:
        return cached

    # Build PVGIS request URL
    params = {
        "lat": request.lat,
        "lon": request.lon,
        "outputformat": "json"
    }

    if request.userhorizon:
        params["userhorizon"] = ",".join(str(h) for h in request.userhorizon)

    try:
        logger.info(f"🏔️ PVGIS horizon request: lat={request.lat}, lon={request.lon}")
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{PVGIS_BASE_URL}/printhorizon", params=params)
            logger.info(f"📡 PVGIS horizon response status: {response.status_code}")
            response.raise_for_status()
            data = response.json()
            logger.info(f"✅ PVGIS horizon success for lat={request.lat}, lon={request.lon}")
    except httpx.HTTPStatusError as e:
        logger.error(f"❌ PVGIS horizon HTTP error: {e.response.status_code}")
        raise HTTPException(status_code=e.response.status_code, detail=f"PVGIS API error: {str(e)}")
    except Exception as e:
        logger.error(f"❌ PVGIS horizon fetch failed: {type(e).__name__}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch horizon from PVGIS: {str(e)}")

    # Process horizon data
    try:
        outputs = data.get("outputs", {})
        # PVGIS returns data in "horizon_profile" key
        horizon_data = outputs.get("horizon_profile", outputs.get("horizon", []))

        # Convert to list of {azimuth, elevation} pairs
        horizon_points = []
        for point in horizon_data:
            azimuth = point.get("A", point.get("azimuth", 0))  # Azimuth in degrees
            elevation = point.get("H_hor", point.get("elevation", 0))  # Horizon height in degrees
            horizon_points.append({
                "azimuth": azimuth,
                "elevation": elevation
            })

        # Sort by azimuth
        horizon_points.sort(key=lambda x: x["azimuth"])

        result = HorizonResponse(
            horizon=horizon_points,
            location={"lat": request.lat, "lon": request.lon},
            source="PVGIS 5.3 DEM"
        )

        # Cache result
        set_cache(cache_key, result)

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing horizon data: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8020)

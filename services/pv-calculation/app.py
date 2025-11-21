"""
PV Calculation Service using pvlib-python
==========================================

This service uses pvlib-python (https://github.com/pvlib/pvlib-python)
for accurate photovoltaic system simulation.

pvlib is the industry-standard library for solar resource and PV modeling.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Optional
import numpy as np
import pandas as pd
from datetime import datetime
import pytz
import requests
import io

# Import pvlib
try:
    import pvlib
    from pvlib import location, pvsystem, modelchain, temperature
    from pvlib.irradiance import get_total_irradiance
    from pvlib.atmosphere import get_relative_airmass, get_absolute_airmass
    PVLIB_AVAILABLE = True
    PVLIB_VERSION = pvlib.__version__
    print(f"✓ pvlib-python v{PVLIB_VERSION} loaded successfully")
except ImportError as e:
    PVLIB_AVAILABLE = False
    PVLIB_VERSION = None
    print(f"✗ pvlib-python not available: {e}")

app = FastAPI(title="PV Calculation Service (pvlib)", version="2.0.0")

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============== Models ==============
class DcacTier(BaseModel):
    min: float
    max: float
    ratio: float

class PVConfiguration(BaseModel):
    pv_type: str = "ground_s"  # ground_s, roof_ew, ground_ew
    yield_target: float = 1050.0  # kWh/kWp/year (used for validation)
    dc_ac_ratio: float = 1.2  # Legacy fallback
    dcac_tiers: Optional[List[DcacTier]] = None
    dcac_mode: str = "manual"  # "manual" (use tiers) or "auto" (analyze consumption profile)
    latitude: float = 52.0  # Poland
    longitude: float = 21.0  # Warsaw default
    altitude: float = 100.0  # meters above sea level
    tilt: Optional[float] = None  # Panel tilt angle
    azimuth: Optional[float] = None  # Panel azimuth (180 = South)
    # Module parameters
    module_efficiency: float = 0.20  # Module efficiency at STC (20% typical for modern panels)
    temperature_coefficient: float = -0.004  # %/°C (typical: -0.004 for crystalline silicon)
    # Environmental parameters
    albedo: float = 0.2  # Ground reflectance (0.2 = typical ground, 0.8 = snow)
    soiling_loss: float = 0.02  # Soiling loss factor (0.02 = 2% loss, typical for Europe)
    # Weather data source
    use_pvgis: bool = True  # Use PVGIS TMY data (True) or clearsky model (False)

def get_dcac_for_capacity(capacity: float, dcac_tiers: Optional[List[DcacTier]], fallback: float = 1.2) -> float:
    """Get DC/AC ratio for given capacity from tiers"""
    if not dcac_tiers:
        return fallback

    for tier in dcac_tiers:
        if tier.min <= capacity <= tier.max:
            return tier.ratio

    if capacity > 50000 and dcac_tiers:
        return dcac_tiers[-1].ratio
    if capacity < 150 and dcac_tiers:
        return dcac_tiers[0].ratio

    return fallback

def analyze_consumption_profile(consumption: np.ndarray) -> float:
    """
    Analyze consumption profile and determine optimal DC/AC ratio.

    Logic:
    - Uniform consumption (low variability) → lower DC/AC (1.1-1.2)
      Reasoning: Steady consumption means inverter runs consistently near rated capacity,
      less benefit from oversizing DC array.

    - Consumption with peaks (high variability) → higher DC/AC (1.3-1.5)
      Reasoning: Spiky consumption benefits from larger DC array to capture more energy
      during low-consumption hours, accepting some clipping during peak production.

    Metrics:
    - Peak factor: max/mean - how much higher is peak vs average
    - Coefficient of variation (CV): std/mean - normalized measure of variability
    - Load factor: mean/max - inverse measure (high = uniform, low = spiky)

    Returns:
        Optimal DC/AC ratio between 1.1 and 1.5
    """
    # Handle edge cases
    if len(consumption) == 0:
        return 1.2  # Default fallback

    # Calculate statistics
    mean_consumption = np.mean(consumption)
    max_consumption = np.max(consumption)
    std_consumption = np.std(consumption)

    # Avoid division by zero
    if mean_consumption <= 0 or max_consumption <= 0:
        return 1.2  # Default fallback

    # Calculate metrics
    peak_factor = max_consumption / mean_consumption  # Higher = more spiky
    cv = std_consumption / mean_consumption  # Higher = more variable
    load_factor = mean_consumption / max_consumption  # Higher = more uniform

    # Decision logic
    # Very uniform load: high load factor (>0.7), low peak factor (<1.5), low CV (<0.2)
    if load_factor > 0.7 and peak_factor < 1.5 and cv < 0.2:
        dcac = 1.1
        profile_type = "bardzo równomierne"

    # Uniform load: moderate load factor (>0.5), low peak factor (<2.0), moderate CV (<0.3)
    elif load_factor > 0.5 and peak_factor < 2.0 and cv < 0.3:
        dcac = 1.15
        profile_type = "równomierne"

    # Moderate variability: medium metrics
    elif load_factor > 0.35 and peak_factor < 3.0 and cv < 0.5:
        dcac = 1.25
        profile_type = "umiarkowanie zmienne"

    # High variability: low load factor, high peak factor, high CV
    elif load_factor > 0.25 and peak_factor < 4.0 and cv < 0.7:
        dcac = 1.35
        profile_type = "zmienne z szczytami"

    # Very spiky load: extreme metrics
    else:
        dcac = 1.45
        profile_type = "bardzo zmienne z dużymi szczytami"

    print(f"📊 Analiza profilu zużycia:")
    print(f"   • Typ profilu: {profile_type}")
    print(f"   • Peak factor: {peak_factor:.2f} (max/mean)")
    print(f"   • Load factor: {load_factor:.2f} (mean/max)")
    print(f"   • Współczynnik zmienności (CV): {cv:.2f} (std/mean)")
    print(f"   • Zalecane DC/AC ratio: {dcac:.2f}")

    return dcac

class SimulationResult(BaseModel):
    capacity: float
    dcac_ratio: float  # DC/AC ratio used for this capacity
    production: float
    self_consumed: float
    exported: float
    auto_consumption_pct: float
    coverage_pct: float

class AnalysisRequest(BaseModel):
    pv_config: PVConfiguration
    consumption: List[float]
    timestamps: Optional[List[str]] = None  # ISO format timestamps
    capacity_min: float = 1000.0
    capacity_max: float = 50000.0
    capacity_step: float = 500.0
    thresholds: Dict[str, float] = {"A": 95, "B": 90, "C": 85, "D": 80}

class VariantResult(BaseModel):
    variant: str
    threshold: float
    capacity: float
    dcac_ratio: float  # DC/AC ratio used for this variant
    production: float
    self_consumed: float
    exported: float
    auto_consumption_pct: float
    coverage_pct: float
    meets_threshold: bool

class AnalysisResult(BaseModel):
    scenarios: List[SimulationResult]
    key_variants: Dict[str, VariantResult]
    pv_profile: List[float]
    pvlib_version: Optional[str] = None

# ============== PVGIS Integration ==============

def fetch_pvgis_tmy_data(latitude: float, longitude: float):
    """
    Fetch Typical Meteorological Year (TMY) data from PVGIS API.
    Returns hourly irradiance data for a full year.

    PVGIS: Photovoltaic Geographical Information System
    Free EU service providing solar radiation and PV performance data.
    """
    try:
        url = "https://re.jrc.ec.europa.eu/api/v5_2/tmy"
        params = {
            'lat': latitude,
            'lon': longitude,
            'outputformat': 'json'
        }

        print(f"📡 Fetching PVGIS TMY data for {latitude}°N, {longitude}°E")
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()

        if 'outputs' not in data or 'tmy_hourly' not in data['outputs']:
            raise ValueError("Invalid PVGIS response format")

        hourly_data = data['outputs']['tmy_hourly']
        print(f"✓ Received {len(hourly_data)} hours of TMY data from PVGIS")

        # Convert to pandas DataFrame for easier manipulation
        df = pd.DataFrame(hourly_data)

        # PVGIS returns: time(UTC), T2m (temp), RH (humidity),
        # G(h) (global horizontal), Gb(n) (beam normal), Gd(h) (diffuse horizontal),
        # IR(h) (infrared), WS10m (wind speed), WD10m (wind direction), SP (pressure)

        # Create timestamps (PVGIS TMY is synthesized from multiple years)
        # We'll use 2020 as a reference year (non-leap for simplicity)
        timestamps = pd.date_range('2020-01-01 00:30:00', periods=len(df), freq='H', tz='UTC')

        result = {
            'timestamps': timestamps,
            'ghi': df['G(h)'].values,  # Global Horizontal Irradiance [W/m²]
            'dni': df['Gb(n)'].values,  # Direct Normal Irradiance [W/m²]
            'dhi': df['Gd(h)'].values,  # Diffuse Horizontal Irradiance [W/m²]
            'temp_air': df['T2m'].values,  # Air temperature [°C]
            'wind_speed': df['WS10m'].values if 'WS10m' in df.columns else np.full(len(df), 1.0),
            'metadata': {
                'source': 'PVGIS',
                'location': f"{latitude}°N, {longitude}°E",
                'data_points': len(df)
            }
        }

        return result

    except requests.exceptions.Timeout:
        print("⚠️ PVGIS API timeout - falling back to clearsky")
        return None
    except requests.exceptions.RequestException as e:
        print(f"⚠️ PVGIS API error: {e} - falling back to clearsky")
        return None
    except Exception as e:
        print(f"⚠️ Error processing PVGIS data: {e} - falling back to clearsky")
        return None

# ============== pvlib-based PV Generation ==============

def generate_pv_profile_pvlib(
    timestamps: List[str],
    latitude: float,
    longitude: float,
    altitude: float,
    tilt: float,
    azimuth: float,
    pv_type: str,
    module_efficiency: float = 0.20,
    temperature_coefficient: float = -0.004,
    albedo: float = 0.2,
    soiling_loss: float = 0.02
) -> np.ndarray:
    """
    Generate PV generation profile using pvlib-python.

    Uses:
    - Ineichen clear sky model for irradiance
    - Perez model for transposition to tilted surface
    - SAPM temperature model
    - Physical IAM model

    Args:
        timestamps: List of ISO format timestamps
        latitude: Site latitude
        longitude: Site longitude
        altitude: Site altitude in meters
        tilt: Panel tilt angle in degrees
        azimuth: Panel azimuth (180 = South, 90 = East, 270 = West)
        pv_type: Installation type for E-W splitting
        module_efficiency: Module efficiency at STC
        temperature_coefficient: Power temperature coefficient (%/°C)

    Returns:
        Array of power output per kWp for each timestamp
    """
    if not PVLIB_AVAILABLE:
        raise HTTPException(status_code=500, detail="pvlib-python not available")

    # Parse timestamps to pandas DatetimeIndex
    times = pd.DatetimeIndex(pd.to_datetime(timestamps))

    # Handle timezone - use UTC to avoid DST issues
    # Then convert to Europe/Warsaw for solar position calculations
    if times.tz is None:
        # Localize as UTC first (no DST issues), then convert to Warsaw
        # This handles the DST gap (e.g., 2:00 AM on March 26 doesn't exist in Warsaw)
        try:
            times = times.tz_localize('Europe/Warsaw', ambiguous='infer', nonexistent='shift_forward')
        except Exception as e:
            print(f"⚠️ DST handling: {e}")
            # Fallback: treat as UTC and convert
            times = times.tz_localize('UTC').tz_convert('Europe/Warsaw')

    print(f"📅 Generating PV profile for {len(times)} timestamps")
    print(f"   Period: {times[0]} to {times[-1]}")
    print(f"   Location: {latitude}°N, {longitude}°E, {altitude}m")
    print(f"   Panel: tilt={tilt}°, azimuth={azimuth}°, type={pv_type}")

    # Create location object
    site = location.Location(
        latitude=latitude,
        longitude=longitude,
        altitude=altitude,
        tz='Europe/Warsaw'
    )

    # Get solar position for all timestamps
    solar_position = site.get_solarposition(times)

    # Get clear sky irradiance using Ineichen model with climatological turbidity
    # This uses linke turbidity lookup tables
    clearsky = site.get_clearsky(times, model='ineichen')

    # For East-West systems, calculate both orientations
    if pv_type in ['roof_ew', 'ground_ew']:
        # East-facing panels
        poa_east = get_total_irradiance(
            surface_tilt=tilt,
            surface_azimuth=90,  # East
            solar_zenith=solar_position['apparent_zenith'],
            solar_azimuth=solar_position['azimuth'],
            dni=clearsky['dni'],
            ghi=clearsky['ghi'],
            dhi=clearsky['dhi'],
            albedo=albedo,  # Ground reflectance
            model='isotropic'  # Using isotropic model (simpler, no dni_extra needed)
        )

        # West-facing panels
        poa_west = get_total_irradiance(
            surface_tilt=tilt,
            surface_azimuth=270,  # West
            solar_zenith=solar_position['apparent_zenith'],
            solar_azimuth=solar_position['azimuth'],
            dni=clearsky['dni'],
            ghi=clearsky['ghi'],
            dhi=clearsky['dhi'],
            albedo=albedo,  # Ground reflectance
            model='isotropic'  # Using isotropic model (simpler, no dni_extra needed)
        )

        # Average of East and West (each side is 50% of total capacity)
        poa_global = 0.5 * (poa_east['poa_global'] + poa_west['poa_global'])

        print(f"   E-W system: East max={poa_east['poa_global'].max():.0f} W/m², West max={poa_west['poa_global'].max():.0f} W/m²")
    else:
        # Single orientation (typically South)
        poa = get_total_irradiance(
            surface_tilt=tilt,
            surface_azimuth=azimuth,
            solar_zenith=solar_position['apparent_zenith'],
            solar_azimuth=solar_position['azimuth'],
            dni=clearsky['dni'],
            ghi=clearsky['ghi'],
            dhi=clearsky['dhi'],
            albedo=albedo,  # Ground reflectance
            model='isotropic'  # Using isotropic model (simpler, no dni_extra needed)
        )
        poa_global = poa['poa_global']

        print(f"   Single orientation: max POA={poa_global.max():.0f} W/m²")

    print(f"   Using albedo={albedo:.2f} (ground reflectance)")

    # Calculate cell temperature using SAPM model
    # Using typical open rack glass/polymer parameters
    temp_params = temperature.TEMPERATURE_MODEL_PARAMETERS['sapm']['open_rack_glass_polymer']

    # Get ambient temperature (simplified - using monthly averages for Poland)
    # In production, this should come from weather data
    ambient_temp = get_ambient_temperature(times)

    cell_temp = temperature.sapm_cell(
        poa_global=poa_global,
        temp_air=ambient_temp,
        wind_speed=1.0,  # Assume 1 m/s wind
        a=temp_params['a'],
        b=temp_params['b'],
        deltaT=temp_params['deltaT']
    )

    # Calculate power output
    # At STC: 1000 W/m² irradiance, 25°C cell temperature
    # Power = Irradiance/1000 * efficiency * temperature_derating

    # Temperature derating
    temp_derating = 1 + temperature_coefficient * (cell_temp - 25)
    temp_derating = np.clip(temp_derating, 0.5, 1.1)

    # Convert irradiance to power per kWp
    # 1 kWp = 1000 W at STC (1000 W/m² irradiance)
    power_per_kwp = (poa_global / 1000) * temp_derating

    # Apply system losses (detailed breakdown)
    # Standard losses
    mismatch_loss = 0.02  # 2%
    wiring_loss = 0.02  # 2%
    inverter_efficiency = 0.98  # 98%
    availability = 0.995  # 99.5%

    # Base system efficiency (without soiling - user configurable)
    base_efficiency = (1 - mismatch_loss) * (1 - wiring_loss) * inverter_efficiency * availability

    # Apply soiling loss separately (user-configurable parameter)
    system_efficiency = base_efficiency * (1 - soiling_loss)

    power_output = power_per_kwp * system_efficiency
    power_output = np.maximum(power_output, 0)  # No negative power

    # Calculate annual yield
    annual_yield = power_output.sum()  # kWh/kWp/year for hourly data
    print(f"   Annual yield: {annual_yield:.0f} kWh/kWp")
    print(f"   System efficiency: {system_efficiency:.3f} (incl. {soiling_loss*100:.1f}% soiling loss)")
    print(f"   Peak power: {power_output.max():.3f} kW/kWp")

    return power_output.values

def generate_pv_profile_pvgis(
    pvgis_data: dict,
    consumption_timestamps: List[str],
    latitude: float,
    longitude: float,
    altitude: float,
    tilt: float,
    azimuth: float,
    pv_type: str,
    temperature_coefficient: float = -0.004,
    albedo: float = 0.2,
    soiling_loss: float = 0.02
) -> np.ndarray:
    """
    Generate PV profile using PVGIS TMY data.
    Maps PVGIS hourly data to consumption timestamps.

    PVGIS provides 8760 hours of TMY data.
    Consumption data may be for actual year with 8760 or 8784 hours.
    We'll map PVGIS data to match consumption timestamps by time-of-year.

    Args:
        albedo: Ground reflectance (0.2 = typical, 0.8 = snow)
        soiling_loss: Soiling loss factor (0.02 = 2% typical for Europe)

    Returns:
        Array of power output per kWp [kW/kWp] for each timestamp.
        Annual sum gives kWh/kWp/year.
    """
    if not PVLIB_AVAILABLE:
        raise HTTPException(status_code=500, detail="pvlib-python not available")

    print(f"📊 Generating PV profile using PVGIS data")
    print(f"   Consumption timestamps: {len(consumption_timestamps)}")
    print(f"   PVGIS data points: {len(pvgis_data['ghi'])}")

    # Parse consumption timestamps
    consumption_times = pd.DatetimeIndex(pd.to_datetime(consumption_timestamps))

    # Handle timezone
    if consumption_times.tz is None:
        try:
            consumption_times = consumption_times.tz_localize('Europe/Warsaw', ambiguous='infer', nonexistent='shift_forward')
        except Exception as e:
            print(f"⚠️ Timezone handling: {e}")
            consumption_times = consumption_times.tz_localize('UTC').tz_convert('Europe/Warsaw')

    # PVGIS data is for a typical year - map to consumption year
    # Extract day-of-year and hour from consumption timestamps

    # Create location
    site = location.Location(
        latitude=latitude,
        longitude=longitude,
        altitude=altitude,
        tz='Europe/Warsaw'
    )

    # Calculate solar position for consumption timestamps
    solar_position = site.get_solarposition(consumption_times)

    # Map PVGIS irradiance data to consumption timestamps
    # Match by day-of-year and hour
    mapped_ghi = []
    mapped_dni = []
    mapped_dhi = []
    mapped_temp = []

    for ct in consumption_times:
        # Find matching hour in PVGIS data (by day-of-year and hour)
        doy = ct.dayofyear
        hour = ct.hour

        # PVGIS index: (doy-1) * 24 + hour
        # Handle leap years: if consumption is in leap year and past Feb 29, adjust
        pvgis_idx = min((doy - 1) * 24 + hour, len(pvgis_data['ghi']) - 1)

        mapped_ghi.append(pvgis_data['ghi'][pvgis_idx])
        mapped_dni.append(pvgis_data['dni'][pvgis_idx])
        mapped_dhi.append(pvgis_data['dhi'][pvgis_idx])
        mapped_temp.append(pvgis_data['temp_air'][pvgis_idx])

    ghi = np.array(mapped_ghi)
    dni = np.array(mapped_dni)
    dhi = np.array(mapped_dhi)
    temp_air = np.array(mapped_temp)

    # Calculate POA irradiance using pvlib with albedo (ground reflectance)
    if pv_type in ['roof_ew', 'ground_ew']:
        # East-West system
        poa_east = get_total_irradiance(
            surface_tilt=tilt,
            surface_azimuth=90,
            solar_zenith=solar_position['apparent_zenith'],
            solar_azimuth=solar_position['azimuth'],
            dni=pd.Series(dni, index=consumption_times),
            ghi=pd.Series(ghi, index=consumption_times),
            dhi=pd.Series(dhi, index=consumption_times),
            albedo=albedo,  # Ground reflectance
            model='isotropic'
        )

        poa_west = get_total_irradiance(
            surface_tilt=tilt,
            surface_azimuth=270,
            solar_zenith=solar_position['apparent_zenith'],
            solar_azimuth=solar_position['azimuth'],
            dni=pd.Series(dni, index=consumption_times),
            ghi=pd.Series(ghi, index=consumption_times),
            dhi=pd.Series(dhi, index=consumption_times),
            albedo=albedo,  # Ground reflectance
            model='isotropic'
        )

        poa_global = 0.5 * (poa_east['poa_global'] + poa_west['poa_global'])
        print(f"   E-W system: East max={poa_east['poa_global'].max():.0f} W/m², West max={poa_west['poa_global'].max():.0f} W/m²")
    else:
        # Single orientation
        poa = get_total_irradiance(
            surface_tilt=tilt,
            surface_azimuth=azimuth,
            solar_zenith=solar_position['apparent_zenith'],
            solar_azimuth=solar_position['azimuth'],
            dni=pd.Series(dni, index=consumption_times),
            ghi=pd.Series(ghi, index=consumption_times),
            dhi=pd.Series(dhi, index=consumption_times),
            albedo=albedo,  # Ground reflectance
            model='isotropic'
        )
        poa_global = poa['poa_global']
        print(f"   Single orientation: max POA={poa_global.max():.0f} W/m²")

    print(f"   Using albedo={albedo:.2f} (ground reflectance)")

    # Calculate cell temperature
    temp_params = temperature.TEMPERATURE_MODEL_PARAMETERS['sapm']['open_rack_glass_polymer']
    cell_temp = temperature.sapm_cell(
        poa_global,
        temp_air,
        pvgis_data['wind_speed'][:len(consumption_times)] if len(pvgis_data['wind_speed']) >= len(consumption_times) else np.full(len(consumption_times), 1.0),
        **temp_params
    )

    # Calculate power output per kWp
    # POA is in W/m². At STC (1000 W/m²), 1 kWp produces 1 kW.
    # So power per kWp = POA / 1000 [kW/kWp]
    power_stc_per_kwp = poa_global / 1000.0  # kW/kWp at STC conditions

    # Apply temperature coefficient
    temp_loss_factor = 1 + temperature_coefficient * (cell_temp - 25)
    power_per_kwp = power_stc_per_kwp * temp_loss_factor

    # Apply system losses (detailed breakdown)
    # Standard losses: DC wiring (2%), inverter (2%), availability (0.5%)
    dc_losses = 0.02
    mismatch_loss = 0.02
    inverter_efficiency = 0.98
    availability = 0.995

    # Base system efficiency (without soiling)
    base_efficiency = (1 - dc_losses) * (1 - mismatch_loss) * inverter_efficiency * availability

    # Apply soiling loss separately (user-configurable)
    system_efficiency = base_efficiency * (1 - soiling_loss)

    power_output = power_per_kwp * system_efficiency
    power_output = np.maximum(power_output, 0)

    annual_yield = power_output.sum()
    print(f"   ✓ PVGIS-based annual yield: {annual_yield:.0f} kWh/kWp")
    print(f"   System efficiency: {system_efficiency:.3f} (incl. {soiling_loss*100:.1f}% soiling loss)")
    print(f"   Peak power: {power_output.max():.3f} kW/kWp")

    return power_output.values

def get_ambient_temperature(times: pd.DatetimeIndex) -> pd.Series:
    """
    Get ambient temperature for timestamps.
    Uses monthly average temperatures for Poland.

    In production, this should use actual weather data or TMY data.
    """
    # Monthly average temperatures for Central Poland (°C)
    monthly_temps = {
        1: -1.0, 2: 0.5, 3: 4.5, 4: 9.5, 5: 14.5, 6: 17.5,
        7: 19.5, 8: 19.0, 9: 14.5, 10: 9.5, 11: 4.5, 12: 0.5
    }

    # Add diurnal variation (simplified)
    temps = []
    for t in times:
        base_temp = monthly_temps[t.month]
        # Simple sinusoidal diurnal variation (±5°C)
        hour_factor = np.sin((t.hour - 6) * np.pi / 12)  # Peak at 12:00
        diurnal = 5 * hour_factor if 6 <= t.hour <= 18 else -3
        temps.append(base_temp + diurnal)

    return pd.Series(temps, index=times)

# ============== Fallback Generation (if pvlib not available) ==============

def generate_pv_profile_fallback(
    n_hours: int,
    latitude: float,
    tilt: float,
    azimuth: float,
    pv_type: str,
    yield_target: float
) -> np.ndarray:
    """
    Fallback PV profile generation using simplified solar model.
    Used only if pvlib is not available.
    """
    import math

    profile = np.zeros(n_hours)

    for hour in range(n_hours):
        day_of_year = hour // 24 + 1
        hour_of_day = hour % 24

        # Solar declination
        declination = 23.45 * math.sin(math.radians(360 * (284 + day_of_year) / 365))

        # Hour angle
        hour_angle = 15 * (hour_of_day - 12)

        # Solar elevation
        lat_rad = math.radians(latitude)
        dec_rad = math.radians(declination)
        ha_rad = math.radians(hour_angle)

        sin_elevation = (math.sin(lat_rad) * math.sin(dec_rad) +
                        math.cos(lat_rad) * math.cos(dec_rad) * math.cos(ha_rad))
        elevation = math.degrees(math.asin(max(-1, min(1, sin_elevation))))

        if elevation > 0:
            # Simplified irradiance model
            irradiance = 1000 * math.sin(math.radians(elevation))

            # Apply tilt factor (simplified)
            tilt_factor = math.cos(math.radians(tilt - elevation))

            power = (irradiance / 1000) * max(0, tilt_factor) * 0.85
            profile[hour] = max(0, power)

    # Scale to target yield
    current_yield = profile.sum()
    if current_yield > 0:
        scale = yield_target / current_yield
        profile = profile * scale

    return profile

# ============== Simulation Functions ==============

def simulate_pv_system(
    capacity: float,
    pv_profile: np.ndarray,
    consumption: np.ndarray,
    dc_ac_ratio: float = 1.2
) -> SimulationResult:
    """
    Simulate PV system performance.

    Args:
        capacity: System capacity in kWp
        pv_profile: Hourly generation per kWp
        consumption: Hourly consumption in kW
        dc_ac_ratio: DC to AC capacity ratio

    Returns:
        SimulationResult with production, self-consumption, export
    """
    # Scale profile by capacity
    # DC/AC ratio means we can have more DC panels than AC inverter capacity
    # This clips the AC output when DC production exceeds inverter capacity
    ac_capacity = capacity / dc_ac_ratio

    production = pv_profile * capacity

    # Clip to AC capacity (inverter limit)
    production = np.minimum(production, ac_capacity)

    # Calculate self-consumption and export
    self_consumed = np.minimum(production, consumption)
    exported = production - self_consumed

    total_production = production.sum()
    total_consumed = self_consumed.sum()
    total_exported = exported.sum()
    total_consumption = consumption.sum()

    # Calculate percentages
    auto_consumption_pct = (total_consumed / total_production * 100) if total_production > 0 else 0
    coverage_pct = (total_consumed / total_consumption * 100) if total_consumption > 0 else 0

    return SimulationResult(
        capacity=capacity,
        dcac_ratio=dc_ac_ratio,
        production=total_production,
        self_consumed=total_consumed,
        exported=total_exported,
        auto_consumption_pct=auto_consumption_pct,
        coverage_pct=coverage_pct
    )

def find_variant(scenarios: List[SimulationResult], threshold: float) -> Optional[SimulationResult]:
    """Find the largest installation that meets the autoconsumption threshold"""
    valid = [s for s in scenarios if s.auto_consumption_pct >= threshold]

    if not valid:
        return None

    return max(valid, key=lambda s: s.capacity)

# ============== API Endpoints ==============

@app.get("/")
async def root():
    return {
        "service": "PV Calculation Service",
        "version": "2.0.0",
        "engine": "pvlib-python",
        "pvlib_available": PVLIB_AVAILABLE,
        "pvlib_version": PVLIB_VERSION
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "pvlib_available": PVLIB_AVAILABLE,
        "pvlib_version": PVLIB_VERSION
    }

@app.post("/generate-profile")
async def generate_profile(config: PVConfiguration):
    """Generate PV generation profile"""
    try:
        # Determine panel configuration
        if config.pv_type == "ground_s":
            tilt = config.tilt if config.tilt else config.latitude
            azimuth = config.azimuth if config.azimuth else 180
        elif config.pv_type == "roof_ew":
            tilt = config.tilt if config.tilt else 10
            azimuth = config.azimuth if config.azimuth else 90
        else:  # ground_ew
            tilt = config.tilt if config.tilt else 15
            azimuth = config.azimuth if config.azimuth else 90

        # Generate timestamps for a full year
        year = datetime.now().year
        times = pd.date_range(
            start=f'{year}-01-01',
            end=f'{year}-12-31 23:00:00',
            freq='H',
            tz='Europe/Warsaw'
        )
        timestamps = [t.isoformat() for t in times]

        if PVLIB_AVAILABLE:
            profile = generate_pv_profile_pvlib(
                timestamps=timestamps,
                latitude=config.latitude,
                longitude=config.longitude,
                altitude=config.altitude,
                tilt=tilt,
                azimuth=azimuth,
                pv_type=config.pv_type,
                module_efficiency=config.module_efficiency,
                temperature_coefficient=config.temperature_coefficient,
                albedo=config.albedo,
                soiling_loss=config.soiling_loss
            )
        else:
            profile = generate_pv_profile_fallback(
                n_hours=8760,
                latitude=config.latitude,
                tilt=tilt,
                azimuth=azimuth,
                pv_type=config.pv_type,
                yield_target=config.yield_target
            )

        return {
            "success": True,
            "profile": profile.tolist(),
            "annual_yield": float(profile.sum()),
            "peak_power": float(profile.max()),
            "hours": len(profile),
            "pvlib_used": PVLIB_AVAILABLE
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/analyze", response_model=AnalysisResult)
async def analyze(request: AnalysisRequest):
    """
    Run full PV analysis across multiple capacities and find key variants.

    Uses pvlib-python for accurate solar simulation based on:
    - Actual timestamps from consumption data
    - Site location (latitude, longitude, altitude)
    - Panel configuration (tilt, azimuth)
    - Clear sky irradiance model (Ineichen)
    - Temperature effects (SAPM model)
    """
    try:
        # Get configuration
        config = request.pv_config

        # Determine panel configuration based on type
        if config.pv_type == "ground_s":
            tilt = config.tilt if config.tilt else config.latitude
            azimuth = config.azimuth if config.azimuth else 180
        elif config.pv_type == "roof_ew":
            tilt = config.tilt if config.tilt else 10
            azimuth = config.azimuth if config.azimuth else 90
        else:  # ground_ew
            tilt = config.tilt if config.tilt else 15
            azimuth = config.azimuth if config.azimuth else 90

        print(f"\n{'='*60}")
        print(f"🔆 PV Analysis using pvlib-python v{PVLIB_VERSION}")
        print(f"{'='*60}")

        # Generate timestamps if not provided
        if request.timestamps and len(request.timestamps) == len(request.consumption):
            timestamps = request.timestamps
            print(f"Using {len(timestamps)} timestamps from consumption data")
        else:
            # Generate hourly timestamps for the year
            n_hours = len(request.consumption)
            year = datetime.now().year
            times = pd.date_range(
                start=f'{year}-01-01',
                periods=n_hours,
                freq='H',
                tz='Europe/Warsaw'
            )
            timestamps = [t.isoformat() for t in times]
            print(f"Generated {len(timestamps)} hourly timestamps for year {year}")

        # Try to use PVGIS data first, fall back to clearsky if unavailable
        pvgis_data = None
        use_pvgis = config.use_pvgis if hasattr(config, 'use_pvgis') else True  # Default to PVGIS

        if use_pvgis and PVLIB_AVAILABLE:
            print("📡 Attempting to use PVGIS TMY data...")
            pvgis_data = fetch_pvgis_tmy_data(config.latitude, config.longitude)

        # Generate PV profile
        if PVLIB_AVAILABLE:
            if pvgis_data:
                print("✓ Using PVGIS TMY data for PV simulation")
                pv_profile = generate_pv_profile_pvgis(
                    pvgis_data=pvgis_data,
                    consumption_timestamps=timestamps,
                    latitude=config.latitude,
                    longitude=config.longitude,
                    altitude=config.altitude,
                    tilt=tilt,
                    azimuth=azimuth,
                    pv_type=config.pv_type,
                    temperature_coefficient=config.temperature_coefficient,
                    albedo=config.albedo,
                    soiling_loss=config.soiling_loss
                )
            else:
                print("⚠️ PVGIS unavailable, using clearsky model")
                pv_profile = generate_pv_profile_pvlib(
                    timestamps=timestamps,
                    latitude=config.latitude,
                    longitude=config.longitude,
                    altitude=config.altitude,
                    tilt=tilt,
                    azimuth=azimuth,
                    pv_type=config.pv_type,
                    module_efficiency=config.module_efficiency,
                    temperature_coefficient=config.temperature_coefficient,
                    albedo=config.albedo,
                    soiling_loss=config.soiling_loss
                )
        else:
            print("⚠️ pvlib not available, using fallback model")
            pv_profile = generate_pv_profile_fallback(
                n_hours=len(request.consumption),
                latitude=config.latitude,
                tilt=tilt,
                azimuth=azimuth,
                pv_type=config.pv_type,
                yield_target=config.yield_target
            )

        consumption = np.array(request.consumption)

        # Determine DC/AC selection mode
        dcac_mode = getattr(config, 'dcac_mode', 'manual')  # Default to manual if not set
        auto_dcac_ratio = None

        if dcac_mode == 'auto':
            # Automatic mode: analyze consumption profile once
            print(f"\n🤖 Tryb automatyczny: analiza profilu zużycia")
            auto_dcac_ratio = analyze_consumption_profile(consumption)
        else:
            # Manual mode: use tier table
            print(f"\n📋 Tryb ręczny: DC/AC ratio wg tabeli przedziałów")

        # Run simulations for each capacity
        scenarios = []
        capacity = request.capacity_min

        print(f"\n📊 Running {int((request.capacity_max - request.capacity_min) / request.capacity_step) + 1} scenarios")
        print(f"   Capacity range: {request.capacity_min} - {request.capacity_max} kWp")

        while capacity <= request.capacity_max:
            # Get DC/AC ratio for this capacity
            if dcac_mode == 'auto' and auto_dcac_ratio is not None:
                # Use automatically determined ratio for all capacities
                dcac_ratio = auto_dcac_ratio
            else:
                # Use tier-based ratio
                dcac_ratio = get_dcac_for_capacity(
                    capacity,
                    config.dcac_tiers,
                    config.dc_ac_ratio
                )

            result = simulate_pv_system(
                capacity=capacity,
                pv_profile=pv_profile,
                consumption=consumption,
                dc_ac_ratio=dcac_ratio
            )
            scenarios.append(result)
            capacity += request.capacity_step

        # Find key variants
        key_variants = {}

        for variant_name, threshold in request.thresholds.items():
            variant_scenario = find_variant(scenarios, threshold)

            if variant_scenario:
                key_variants[variant_name] = VariantResult(
                    variant=variant_name,
                    threshold=threshold,
                    capacity=variant_scenario.capacity,
                    dcac_ratio=variant_scenario.dcac_ratio,
                    production=variant_scenario.production,
                    self_consumed=variant_scenario.self_consumed,
                    exported=variant_scenario.exported,
                    auto_consumption_pct=variant_scenario.auto_consumption_pct,
                    coverage_pct=variant_scenario.coverage_pct,
                    meets_threshold=True
                )
                print(f"   Variant {variant_name} ({threshold}%): {variant_scenario.capacity:.0f} kWp, auto={variant_scenario.auto_consumption_pct:.1f}%")

        print(f"\n✅ Analysis complete: {len(scenarios)} scenarios, {len(key_variants)} variants")
        print(f"{'='*60}\n")

        return AnalysisResult(
            scenarios=scenarios,
            key_variants=key_variants,
            pv_profile=pv_profile.tolist(),
            pvlib_version=PVLIB_VERSION
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))

# ============== Main ==============
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)

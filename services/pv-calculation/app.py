"""
PV Calculation Service using pvlib-python
==========================================

This service uses pvlib-python (https://github.com/pvlib/pvlib-python)
for accurate photovoltaic system simulation.

pvlib is the industry-standard library for solar resource and PV modeling.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Optional, Tuple
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import pytz
import requests
import io
import asyncio
import json

# Global progress store for SSE
optimization_progress = {
    "active": False,
    "percent": 0,
    "step": "",
    "current_capacity": 0,
    "total_configs": 0,
    "tested_configs": 0
}

# BESS Dispatch Service URL (for PRO mode with LP/MIP solver)
# Note: bess-dispatch exposes main endpoints at root level (e.g., /sizing, /dispatch)
# Only auth/admin/audit/projects routers have /api/bess-dispatch prefix
BESS_DISPATCH_URL = "http://bess-dispatch:8031"  # Docker network name - endpoints at root level
PROFILE_ANALYSIS_URL = "http://profile-analysis:8040"  # For K-class capacity fee scenarios

# Legacy - keep for backwards compatibility but prefer BESS_DISPATCH_URL
BESS_OPTIMIZER_URL = "http://bess-optimizer:8030"  # Docker network name (deprecated)

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

# Prometheus metrics
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(title="PV Calculation Service (pvlib)", version="2.1.0")

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
    # BESS results (only populated when BESS enabled)
    bess_power_kw: Optional[float] = None
    bess_energy_kwh: Optional[float] = None
    bess_charged_kwh: Optional[float] = None
    bess_discharged_kwh: Optional[float] = None
    bess_curtailed_kwh: Optional[float] = None
    bess_grid_import_kwh: Optional[float] = None
    bess_self_consumed_direct_kwh: Optional[float] = None
    bess_self_consumed_from_bess_kwh: Optional[float] = None
    bess_cycles_equivalent: Optional[float] = None
    # Monthly BESS breakdown (NEW in v3.2)
    bess_monthly_data: Optional[List["BESSMonthlyData"]] = None
    # SOC histogram (NEW in v3.2)
    bess_soc_histogram: Optional["BESSSOCHistogram"] = None

# ============== BESS PRO Configuration (LP/MIP Optimization) ==============
class CapacityFeeConfig(BaseModel):
    """Polish capacity fee (opłata mocowa) configuration"""
    enabled: bool = False
    som_rate_pln_kw: float = 0.2194  # Monthly SOM rate in PLN/kW
    qualification_period: str = 'daily'  # 'daily' | 'monthly'
    peak_hours: List[int] = [7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]  # default peak hours

class TariffConfig(BaseModel):
    """Time-of-Use tariff configuration"""
    type: str = 'flat'  # 'flat' | 'two_zone' | 'three_zone'
    flat_rate_pln_mwh: float = 800.0
    # Two-zone (day/night)
    day_rate_pln_mwh: Optional[float] = None
    night_rate_pln_mwh: Optional[float] = None
    day_hours_start: int = 6
    day_hours_end: int = 22
    # Three-zone (peak/day/night)
    peak_rate_pln_mwh: Optional[float] = None
    peak_hours: Optional[List[int]] = None
    # Fixed charges (OSD dystrybucja, OZE, kog, jakość, mocowa, akcyza)
    # These are added on top of ToU rates for total energy cost
    other_fees_pln_mwh: float = 451.0  # Default: 451 PLN/MWh

class BESSProConfig(BaseModel):
    """BESS PRO configuration for LP/MIP optimization"""
    min_power_kw: float = 50.0
    max_power_kw: float = 10000.0
    min_energy_kwh: float = 100.0
    max_energy_kwh: float = 50000.0
    duration_min: float = 1.0
    duration_max: float = 4.0
    solver: str = 'highs'  # 'highs' | 'glpk' | 'cbc'
    objective: str = 'npv'  # 'npv' | 'payback' | 'autoconsumption'
    time_resolution: str = 'hourly'  # 'hourly' | '15min'
    typical_days: int = 0  # 0 = full year
    zero_export: bool = True
    export_penalty: float = 1000.0  # PLN/MWh

# ============== BESS Configuration Model (PRO Mode - LIGHT deprecated) ==============
class BESSConfigLite(BaseModel):
    """BESS configuration - PRO mode is default (LIGHT deprecated)"""
    enabled: bool = True
    mode: str = 'pro'  # 'pro' = LP/MIP optimization (light deprecated)
    duration: str = 'auto'  # 'auto' | '1' | '2' | '4' hours (E/P ratio) - for LIGHT mode
    # Technical parameters
    roundtrip_efficiency: float = 0.90  # 88-92% typical for Li-ion
    soc_min: float = 0.10  # Minimum SOC (protect battery)
    soc_max: float = 0.90  # Maximum SOC (protect battery)
    soc_initial: float = 0.50  # Initial SOC
    # Economic parameters (for NPV calculation in economics module)
    capex_per_kwh: float = 1500.0  # PLN/kWh (battery + BMS)
    capex_per_kw: float = 300.0  # PLN/kW (PCS/inverter)
    opex_pct_per_year: float = 1.5  # OPEX as % of CAPEX
    lifetime_years: int = 15
    degradation_pct_per_year: float = 2.0
    # Dispatch mode and topology (from scenario selection)
    dispatch_mode: str = 'pv_surplus'  # 'pv_surplus' | 'stacked' | 'load_only'
    topology: str = 'pv_load'  # 'pv_load' | 'load_only'
    # Peak shaving / demand charge parameters
    demand_charge_pln_kw_month: float = 0.0  # Monthly demand charge (PLN/kW)
    peak_limit_kw: Optional[float] = None  # Target peak limit for peak shaving
    # Capacity fee (opłata mocowa) configuration
    capacity_fee_config: Optional[CapacityFeeConfig] = None
    # Tariff configuration (for ToU arbitrage)
    tariff_config: Optional[TariffConfig] = None
    # PRO mode configuration (optional, only when mode='pro')
    pro_config: Optional[BESSProConfig] = None

class AnalysisRequest(BaseModel):
    pv_config: PVConfiguration
    consumption: List[float]
    timestamps: Optional[List[str]] = None  # ISO format timestamps
    capacity_min: float = 1000.0
    capacity_max: float = 50000.0
    capacity_step: float = 500.0
    thresholds: Dict[str, float] = {"A": 95, "B": 90, "C": 85, "D": 80}
    bess_config: Optional[BESSConfigLite] = None  # BESS LIGHT/AUTO configuration

class BaselineMetrics(BaseModel):
    """Baseline metrics without BESS for comparison"""
    production: float
    self_consumed: float
    exported: float
    auto_consumption_pct: float
    coverage_pct: float

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
    # Hourly production data (AC output with DC/AC clipping applied)
    hourly_production: Optional[List[float]] = None
    # BESS results (only populated when BESS enabled)
    bess_power_kw: Optional[float] = None
    bess_energy_kwh: Optional[float] = None
    bess_charged_kwh: Optional[float] = None
    bess_discharged_kwh: Optional[float] = None
    bess_curtailed_kwh: Optional[float] = None
    bess_grid_import_kwh: Optional[float] = None
    bess_self_consumed_direct_kwh: Optional[float] = None
    bess_self_consumed_from_bess_kwh: Optional[float] = None
    bess_cycles_equivalent: Optional[float] = None
    # Monthly BESS breakdown (NEW in v3.2)
    bess_monthly_data: Optional[List["BESSMonthlyData"]] = None
    # SOC histogram (NEW in v3.2)
    bess_soc_histogram: Optional["BESSSOCHistogram"] = None
    # Baseline comparison (without BESS) - for impact analysis
    baseline_no_bess: Optional[BaselineMetrics] = None
    # Savings breakdown from bess-dispatch (PRO mode)
    savings_breakdown: Optional["SavingsBreakdown"] = None
    # Dispatch metadata from bess-dispatch (PRO mode)
    dispatch_metadata: Optional["DispatchMetadata"] = None
    # Capacity fee K-class scenarios (v3.0 — multi-scenario K-class)
    capacity_fee_baseline_pln: Optional[float] = None       # S0: bez PV, bez BESS
    capacity_fee_with_pv_pln: Optional[float] = None        # S1: z PV
    capacity_fee_with_pv_bess_pln: Optional[float] = None   # S2: z PV + BESS
    k_class_baseline: Optional[str] = None
    k_class_with_pv: Optional[str] = None
    k_class_with_pv_bess: Optional[str] = None
    capacity_fee_savings_pv_pln: Optional[float] = None     # S0 - S1
    capacity_fee_savings_bess_pln: Optional[float] = None   # S1 - S2
    capacity_fee_savings_total_pln: Optional[float] = None  # S0 - S2

class BESSMonthlyData(BaseModel):
    """Monthly BESS performance data"""
    month: int  # 1-12
    month_name: str  # "Styczeń", "Luty", etc.
    charged_kwh: float
    discharged_kwh: float
    curtailed_kwh: float
    grid_import_kwh: float
    self_consumed_direct_kwh: float
    self_consumed_from_bess_kwh: float
    cycles_equivalent: float
    # Throughput for cycle tracking
    throughput_kwh: float  # charged + discharged

class BESSSOCHistogram(BaseModel):
    """SOC histogram data (10 bins from 0-100%)"""
    bins: List[str]  # ["0-10%", "10-20%", ..., "90-100%"]
    hours: List[int]  # Number of hours in each bin
    percentages: List[float]  # Percentage of total hours in each bin

class SavingsBreakdown(BaseModel):
    """Detailed breakdown of BESS savings from bess-dispatch"""
    energy_savings_pln: float = 0.0
    demand_charge_savings_pln: float = 0.0
    capacity_fee_savings_pln: float = 0.0
    arbitrage_savings_pln: float = 0.0
    degradation_cost_pln: float = 0.0
    net_savings_pln: float = 0.0
    source: str = "bess_dispatch_accurate"  # Always accurate from bess-dispatch

class DispatchMetadata(BaseModel):
    """Metadata about dispatch mode and topology"""
    dispatch_mode: str = "pv_surplus"
    topology: str = "pv_load"
    peak_shaving_enabled: bool = False
    peak_limit_kw: Optional[float] = None

class BESSSummary(BaseModel):
    """Summary of BESS sizing and performance from bess-dispatch PRO solver"""
    enabled: bool = False
    mode: str = 'pro'  # Always PRO - uses bess-dispatch full solver
    duration_selected: str = 'auto'
    power_kw: float = 0.0
    energy_kwh: float = 0.0
    annual_charged_kwh: float = 0.0
    annual_discharged_kwh: float = 0.0
    annual_curtailed_kwh: float = 0.0
    annual_grid_import_kwh: float = 0.0
    cycles_equivalent: float = 0.0
    capex_total: float = 0.0
    opex_annual: float = 0.0
    annual_savings_pln: float = 0.0  # Total annual savings from BESS
    npv_pln: float = 0.0  # NPV from bess-dispatch
    # Monthly breakdown (NEW in v3.2)
    monthly_data: Optional[List[BESSMonthlyData]] = None
    # Savings breakdown from bess-dispatch (PRECISE - LP/MIP solver)
    savings_breakdown: Optional[SavingsBreakdown] = None
    # Dispatch metadata
    dispatch_metadata: Optional[DispatchMetadata] = None
    # Schema version for frontend compatibility
    schema_version: str = "bess_economics_v2"

class AnalysisResult(BaseModel):
    scenarios: List[SimulationResult]
    key_variants: Dict[str, VariantResult]
    pv_profile: List[float]
    pvlib_version: Optional[str] = None
    # Date range information
    date_range_start: Optional[str] = None
    date_range_end: Optional[str] = None
    estimation_method: Optional[str] = None  # "none", "seasonal_scaling_Xm", etc.
    data_hours: Optional[int] = None
    # BESS summary (only when BESS enabled)
    bess_summary: Optional[BESSSummary] = None

# ============== Seasonality Band Optimization Models ==============
class BandConfig(BaseModel):
    """Konfiguracja pasma sezonowego"""
    band: str  # "High", "Mid", "Low"
    ac_limit_kw: float  # Limit mocy AC dla pasma [kW]
    months: List[str]  # Miesiące przypisane do pasma

class SeasonalityOptimizationRequest(BaseModel):
    """Żądanie optymalizacji z pasmami sezonowości"""
    pv_config: PVConfiguration
    consumption: List[float]
    timestamps: List[str]
    # Pasma sezonowości (z data-analysis /seasonality)
    band_powers: List[dict]  # {"band": "High", "p_recommended": 800}
    monthly_bands: List[dict]  # {"month": "2024-07", "dominant_band": "High"}
    # Zakres analizy
    capacity_min: float = 100.0
    capacity_max: float = 5000.0
    capacity_step: float = 100.0
    # Parametry finansowe (z frontend-settings)
    capex_per_kwp: float = 3500.0
    opex_per_kwp_year: float = 50.0
    energy_price_import: float = 800.0  # PLN/MWh
    energy_price_esco: float = 700.0  # PLN/MWh (cena dla klienta EaaS)
    discount_rate: float = 0.08
    project_years: int = 15
    # Tryb optymalizacji
    mode: str = "MAX_AUTOCONSUMPTION"  # lub "MAX_NPV"
    # Wybrane sezony do optymalizacji (High, Mid, Low)
    target_seasons: List[str] = ["High", "Mid"]  # Domyślnie High + Mid
    # Progi autokonsumpcji z ustawień (do filtrowania konfiguracji)
    autoconsumption_thresholds: Optional[dict] = None  # {"A": 95, "B": 90, "C": 85, "D": 80}

class SeasonalityOptimizationResult(BaseModel):
    """Wynik optymalizacji z pasmami sezonowości"""
    mode: str
    best_capacity_kwp: float
    best_dcac_ratio: float
    best_band_config: List[BandConfig]
    # Metryki CAŁOROCZNE dla najlepszej konfiguracji
    autoconsumption_pct: float
    coverage_pct: float
    annual_production_mwh: float
    annual_self_consumed_mwh: float
    annual_exported_mwh: float
    # Metryki SEZONOWE (target) dla najlepszej konfiguracji
    target_self_consumed_mwh: Optional[float] = None
    target_autoconsumption_pct: Optional[float] = None
    target_coverage_pct: Optional[float] = None
    target_npv: Optional[float] = None
    target_seasons: Optional[List[str]] = None
    # Metryki finansowe CAŁOROCZNE (dla MAX_NPV)
    npv: Optional[float] = None
    irr: Optional[float] = None
    payback_years: Optional[float] = None
    # Porównanie konfiguracji
    configurations_tested: int
    all_configurations: List[dict]  # Tabela porównawcza

# ============== Date Extraction and Validation ==============

def extract_date_range_from_timestamps(timestamps: List[str]) -> Tuple[datetime, datetime, int]:
    """
    Extract date range from consumption timestamps.

    Args:
        timestamps: List of ISO format timestamps from consumption file

    Returns:
        Tuple of (start_date, end_date, total_days)
    """
    if not timestamps or len(timestamps) < 24:
        raise ValueError("Insufficient timestamps - need at least 24 hours of data")

    # Parse timestamps
    parsed = pd.to_datetime(timestamps)
    start_date = parsed.min()
    end_date = parsed.max()

    total_days = (end_date - start_date).days + 1

    print(f"📅 Extracted date range from consumption data:")
    print(f"   Start: {start_date.strftime('%Y-%m-%d %H:%M')}")
    print(f"   End: {end_date.strftime('%Y-%m-%d %H:%M')}")
    print(f"   Total days: {total_days}")

    return start_date.to_pydatetime(), end_date.to_pydatetime(), total_days


def validate_and_adjust_date_range(
    start_date: datetime,
    end_date: datetime,
    max_days: int = 366
) -> Tuple[datetime, datetime, bool]:
    """
    Validate date range and truncate if exceeds max_days (1 year).

    Args:
        start_date: Start date from consumption file
        end_date: End date from consumption file
        max_days: Maximum allowed days (default 366 for leap year)

    Returns:
        Tuple of (adjusted_start, adjusted_end, was_truncated)
    """
    total_days = (end_date - start_date).days + 1

    if total_days <= max_days:
        return start_date, end_date, False

    # Truncate to max_days from start
    adjusted_end = start_date + timedelta(days=max_days - 1)

    print(f"⚠️ Date range exceeds {max_days} days ({total_days} days)")
    print(f"   Truncating to: {start_date.strftime('%Y-%m-%d')} - {adjusted_end.strftime('%Y-%m-%d')}")

    return start_date, adjusted_end, True


def estimate_annual_consumption(
    consumption: np.ndarray,
    timestamps: List[str],
    target_hours: int = 8760
) -> Tuple[np.ndarray, List[str], str]:
    """
    Analyze consumption data and handle partial year scenarios.

    ANALYTICAL YEAR APPROACH:
    - If data covers 365/366 consecutive days, use as-is (full analytical year)
    - If data covers less, we DON'T extend to calendar year anymore
    - Instead, we use the actual date range (analytical year concept)

    Args:
        consumption: Hourly consumption array
        timestamps: List of ISO timestamps
        target_hours: Target hours (8760 for non-leap, 8784 for leap year) - NOW IGNORED

    Returns:
        Tuple of (consumption, timestamps, estimation_method)
        Note: We no longer estimate/extend data - analytical year is used as-is
    """
    parsed = pd.to_datetime(timestamps)
    start_date = parsed.min()
    end_date = parsed.max()

    total_days = (end_date - start_date).days + 1
    total_hours = len(consumption)
    months_covered = len(set([(d.year, d.month) for d in parsed]))

    print(f"📅 Analytical year analysis:")
    print(f"   Start date: {start_date.strftime('%Y-%m-%d')}")
    print(f"   End date: {end_date.strftime('%Y-%m-%d')}")
    print(f"   Total days: {total_days}")
    print(f"   Total hours: {total_hours}")
    print(f"   Months covered: {months_covered}")

    # ANALYTICAL YEAR: Use data as-is, regardless of calendar year boundaries
    # A full analytical year is 365/366 consecutive days from ANY start date
    if total_days >= 365:
        print(f"✓ Full analytical year ({total_days} days) - using data as-is")
        return consumption, timestamps, "analytical_year_full"

    if total_days >= 335:  # ~11 months
        print(f"✓ Near-full analytical year ({total_days} days, {months_covered} months) - using data as-is")
        return consumption, timestamps, "analytical_year_partial"

    # For partial data (<11 months), we still use it as-is
    # The PV calculation will be scaled appropriately
    print(f"⚠️ Partial analytical year ({total_days} days, {months_covered} months)")
    print(f"   Using actual data without extension (analytical year approach)")

    return consumption, timestamps, f"analytical_year_{months_covered}m"


# ============== Analytical Year Support ==============

def map_tmy_to_analytical_year(
    tmy_data: dict,
    analytical_year_timestamps: List[str]
) -> dict:
    """
    Mapuje dane TMY (Typical Meteorological Year) na rok analityczny.

    Dane TMY to 8760 godzin reprezentujących typowy rok kalendarzowy (Jan 1 - Dec 31).
    Rok analityczny może zaczynać się od dowolnej daty (np. 1 lipca 2024 do 30 czerwca 2025).

    Mapowanie odbywa się przez dopasowanie miesiąc/dzień/godzina - ignorując rok.
    Np. godzina 12:00 z 15 lipca w roku analitycznym pobiera dane z godziny 12:00, 15 lipca w TMY.

    Args:
        tmy_data: Słownik z danymi TMY (ghi, dni, dhi, temp_air, wind_speed)
        analytical_year_timestamps: Lista timestampów roku analitycznego (ISO format)

    Returns:
        Słownik z danymi zmapowanymi na rok analityczny
    """
    import calendar as cal

    print(f"📅 Mapowanie TMY na rok analityczny ({len(analytical_year_timestamps)} godzin)")

    # Parse analytical year timestamps
    parsed_times = pd.to_datetime(analytical_year_timestamps)

    # TMY data is indexed by day-of-year (1-365) and hour (0-23)
    # Total: 365 * 24 = 8760 hours
    tmy_length = len(tmy_data['ghi'])

    mapped_ghi = []
    mapped_dni = []
    mapped_dhi = []
    mapped_temp = []
    mapped_wind = []

    for ts in parsed_times:
        month = ts.month
        day = ts.day
        hour = ts.hour

        # Obsługa 29 lutego w roku przestępnym:
        # TMY nie ma 29 lutego (8760h = 365 dni)
        # Jeśli rok analityczny zawiera 29 lutego, użyj danych z 28 lutego
        if month == 2 and day == 29:
            day = 28  # Fallback to Feb 28

        # Oblicz dzień roku w TMY (bez 29 lutego)
        # TMY używa standardowego roku 365 dni
        # Styczeń = dni 1-31, Luty = dni 32-59, itd.
        days_before_month = sum(cal.monthrange(2023, m)[1] for m in range(1, month))  # 2023 = rok nieprzestępny
        tmy_day_of_year = days_before_month + day

        # Indeks w tablicy TMY: (dzień-1) * 24 + godzina
        tmy_idx = (tmy_day_of_year - 1) * 24 + hour

        # Zabezpieczenie przed przekroczeniem zakresu
        tmy_idx = min(tmy_idx, tmy_length - 1)
        tmy_idx = max(tmy_idx, 0)

        mapped_ghi.append(tmy_data['ghi'][tmy_idx])
        mapped_dni.append(tmy_data['dni'][tmy_idx])
        mapped_dhi.append(tmy_data['dhi'][tmy_idx])
        mapped_temp.append(tmy_data['temp_air'][tmy_idx])

        if 'wind_speed' in tmy_data and len(tmy_data['wind_speed']) > tmy_idx:
            mapped_wind.append(tmy_data['wind_speed'][tmy_idx])
        else:
            mapped_wind.append(1.0)

    print(f"   ✓ Zmapowano {len(mapped_ghi)} godzin danych TMY")
    print(f"   Zakres dat: {parsed_times[0].strftime('%Y-%m-%d')} do {parsed_times[-1].strftime('%Y-%m-%d')}")

    return {
        'ghi': np.array(mapped_ghi),
        'dni': np.array(mapped_dni),
        'dhi': np.array(mapped_dhi),
        'temp_air': np.array(mapped_temp),
        'wind_speed': np.array(mapped_wind),
        'timestamps': analytical_year_timestamps,
        'metadata': {
            'source': 'PVGIS TMY (mapped to analytical year)',
            'analytical_year_hours': len(analytical_year_timestamps),
            'original_tmy_hours': tmy_length
        }
    }


# ============== PVGIS Integration ==============

def fetch_pvgis_tmy_data(latitude: float, longitude: float):
    """
    Fetch Typical Meteorological Year (TMY) data from PVGIS API.
    Returns hourly irradiance data for a full year.

    PVGIS: Photovoltaic Geographical Information System
    Free EU service providing solar radiation and PV performance data.
    """
    try:
        url = "https://re.jrc.ec.europa.eu/api/v5_3/tmy"
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

        # Create timestamps for TMY data (will be mapped to actual consumption period later)
        # Use generic reference - actual mapping happens in generate_pv_profile_pvgis
        timestamps = pd.date_range('2000-01-01 00:30:00', periods=len(df), freq='H', tz='UTC')

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

    # CRITICAL: Clearsky model correction factor for Poland
    # Clearsky gives ideal conditions (no clouds) which overestimates yield by ~60-70%
    # Real yield in Poland is 950-1100 kWh/kWp, clearsky gives ~1700 kWh/kWp
    # Apply cloud/weather correction factor based on latitude (higher lat = more clouds)
    # For Poland (lat ~52°): typical GHI reduction due to clouds is ~35-40%
    CLEARSKY_CORRECTION_FACTOR = 0.62  # Reduces clearsky to realistic Poland values
    print(f"   ⚠️ Using CLEARSKY model (PVGIS unavailable) - applying {CLEARSKY_CORRECTION_FACTOR:.0%} correction factor")

    power_output = power_per_kwp * system_efficiency * CLEARSKY_CORRECTION_FACTOR
    power_output = np.maximum(power_output, 0)  # No negative power

    # Calculate annual yield
    annual_yield = power_output.sum()  # kWh/kWp/year for hourly data
    print(f"   Annual yield (corrected): {annual_yield:.0f} kWh/kWp")
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
    Generate PV profile using PVGIS TMY data for analytical year.

    PVGIS provides 8760 hours of TMY data (typical calendar year Jan 1 - Dec 31).
    Analytical year may start from any date (e.g., July 1, 2024 to June 30, 2025).

    TMY data is mapped to analytical year by matching month/day/hour - ignoring year.
    This ensures correct solar irradiance for each calendar day regardless of
    which year the analytical period spans.

    Args:
        pvgis_data: PVGIS TMY data dictionary
        consumption_timestamps: Timestamps from analytical year (ISO format)
        albedo: Ground reflectance (0.2 = typical, 0.8 = snow)
        soiling_loss: Soiling loss factor (0.02 = 2% typical for Europe)

    Returns:
        Array of power output per kWp [kW/kWp] for each timestamp.
        Sum gives kWh/kWp for the analytical year period.
    """
    if not PVLIB_AVAILABLE:
        raise HTTPException(status_code=500, detail="pvlib-python not available")

    print(f"📊 Generating PV profile using PVGIS data (analytical year)")
    print(f"   Analytical year timestamps: {len(consumption_timestamps)}")
    print(f"   PVGIS TMY data points: {len(pvgis_data['ghi'])}")

    # Map TMY data to analytical year timestamps (handles any start date)
    mapped_data = map_tmy_to_analytical_year(pvgis_data, consumption_timestamps)

    ghi = mapped_data['ghi']
    dni = mapped_data['dni']
    dhi = mapped_data['dhi']
    temp_air = mapped_data['temp_air']
    wind_speed = mapped_data['wind_speed']

    # Parse consumption timestamps
    consumption_times = pd.DatetimeIndex(pd.to_datetime(consumption_timestamps))

    # Handle timezone
    if consumption_times.tz is None:
        try:
            consumption_times = consumption_times.tz_localize('Europe/Warsaw', ambiguous='infer', nonexistent='shift_forward')
        except Exception as e:
            print(f"⚠️ Timezone handling: {e}")
            consumption_times = consumption_times.tz_localize('UTC').tz_convert('Europe/Warsaw')

    # Create location
    site = location.Location(
        latitude=latitude,
        longitude=longitude,
        altitude=altitude,
        tz='Europe/Warsaw'
    )

    # Calculate solar position for analytical year timestamps
    solar_position = site.get_solarposition(consumption_times)

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

    # Calculate cell temperature using mapped wind speed data
    temp_params = temperature.TEMPERATURE_MODEL_PARAMETERS['sapm']['open_rack_glass_polymer']
    cell_temp = temperature.sapm_cell(
        poa_global,
        temp_air,
        wind_speed,  # Use mapped wind_speed from analytical year
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

# ============== Seasonality Band Optimization Functions ==============

def simulate_pv_with_seasonal_bands(
    capacity_kwp: float,
    pv_profile: np.ndarray,
    consumption: np.ndarray,
    timestamps: List[str],
    monthly_bands: List[dict],
    dc_ac_ratio: float = 1.2,
    target_seasons: List[str] = None  # Filtr sezonów do metryki optymalizacji
) -> dict:
    """
    Symulacja PV z sezonowością (bez sztucznych limitów mocy AC).
    Wersja zoptymalizowana z wektoryzacją NumPy.

    Jedyny limit AC to limit inwertera (z DC/AC ratio).
    W trybie 0-export energia jest limitowana do zużycia w danej godzinie.

    target_seasons: Jeśli podane, metryki optymalizacji (self_consumed_target)
    są liczone tylko dla godzin w wybranych sezonach.
    """
    # Produkcja DC
    production_dc = pv_profile * capacity_kwp

    # Limit AC = tylko limit inwertera (z DC/AC ratio)
    ac_capacity = capacity_kwp / dc_ac_ratio

    # Przygotuj mapę pasm dla miesięcy (do filtrowania sezonów)
    month_band_map = {item['month']: item['dominant_band'] for item in monthly_bands}

    # Parsuj timestampy
    parsed_times = pd.to_datetime(timestamps)

    # Wektoryzowana symulacja
    # Produkcja AC = min(DC, AC_capacity) - tylko limit inwertera!
    production_ac = np.minimum(production_dc, ac_capacity)

    # 0-export: nie więcej niż zużycie
    self_consumed = np.minimum(production_ac, consumption)
    exported = np.maximum(production_ac - self_consumed, 0)

    # Sumy CAŁKOWITE (dla raportowania)
    total_production = production_ac.sum()
    total_self_consumed = self_consumed.sum()
    total_exported = exported.sum()
    total_consumption = consumption.sum()

    # Metryki całkowite
    autoconsumption_pct = (total_self_consumed / total_production * 100) if total_production > 0 else 0
    coverage_pct = (total_self_consumed / total_consumption * 100) if total_consumption > 0 else 0

    # Metryki dla WYBRANYCH SEZONÓW (do optymalizacji)
    if target_seasons:
        # Stwórz maskę dla wybranych sezonów
        season_mask = np.array([
            month_band_map.get(ts.strftime('%Y-%m'), 'Mid') in target_seasons
            for ts in parsed_times
        ])

        # Policz metryki tylko dla wybranych sezonów
        target_self_consumed = self_consumed[season_mask].sum()
        target_production = production_ac[season_mask].sum()
        target_consumption = consumption[season_mask].sum()
        target_exported = exported[season_mask].sum()

        target_autoconsumption_pct = (target_self_consumed / target_production * 100) if target_production > 0 else 0
        target_coverage_pct = (target_self_consumed / target_consumption * 100) if target_consumption > 0 else 0
    else:
        # Bez filtra = całość
        target_self_consumed = total_self_consumed
        target_production = total_production
        target_exported = total_exported
        target_autoconsumption_pct = autoconsumption_pct
        target_coverage_pct = coverage_pct

    return {
        'capacity_kwp': capacity_kwp,
        'dc_ac_ratio': dc_ac_ratio,
        # Metryki CAŁKOWITE (do raportowania)
        'production_mwh': total_production / 1000,
        'self_consumed_mwh': total_self_consumed / 1000,
        'exported_mwh': total_exported / 1000,
        'autoconsumption_pct': autoconsumption_pct,
        'coverage_pct': coverage_pct,
        # Metryki dla WYBRANYCH SEZONÓW (do optymalizacji)
        'target_self_consumed_mwh': target_self_consumed / 1000,
        'target_production_mwh': target_production / 1000,
        'target_exported_mwh': target_exported / 1000,
        'target_autoconsumption_pct': target_autoconsumption_pct,
        'target_coverage_pct': target_coverage_pct,
        # Dane godzinowe
        'hourly_production': production_ac.tolist(),
        'hourly_self_consumed': self_consumed.tolist()
    }




def calculate_npv_for_config(
    simulation_result: dict,
    capex_per_kwp: float,
    opex_per_kwp_year: float,
    energy_price_esco: float,
    discount_rate: float,
    project_years: int
) -> dict:
    """
    Oblicz NPV dla konfiguracji PV (perspektywa ESCO/inwestora).

    Args:
        simulation_result: Wynik symulacji PV
        capex_per_kwp: CAPEX per kWp [PLN]
        opex_per_kwp_year: OPEX roczny per kWp [PLN]
        energy_price_esco: Cena sprzedaży energii klientowi [PLN/MWh]
        discount_rate: Stopa dyskontowa
        project_years: Okres projektu [lata]

    Returns:
        Słownik z metrykami finansowymi
    """
    capacity = simulation_result['capacity_kwp']
    annual_energy_mwh = simulation_result['self_consumed_mwh']

    # CAPEX
    capex = capacity * capex_per_kwp

    # Roczne przychody (sprzedaż energii klientowi)
    annual_revenue = annual_energy_mwh * energy_price_esco

    # Roczne koszty operacyjne
    annual_opex = capacity * opex_per_kwp_year

    # Roczny cashflow
    annual_cf = annual_revenue - annual_opex

    # NPV
    npv = -capex
    for year in range(1, project_years + 1):
        npv += annual_cf / ((1 + discount_rate) ** year)

    # Prosty payback
    if annual_cf > 0:
        payback = capex / annual_cf
    else:
        payback = float('inf')

    # IRR (przybliżony - metodą iteracyjną)
    irr = None
    try:
        cashflows = [-capex] + [annual_cf] * project_years
        # Prosta metoda bisekcji dla IRR
        low, high = -0.5, 1.0
        for _ in range(50):
            mid = (low + high) / 2
            npv_test = sum(cf / ((1 + mid) ** i) for i, cf in enumerate(cashflows))
            if npv_test > 0:
                low = mid
            else:
                high = mid
        irr = mid * 100  # %
    except:
        irr = None

    return {
        'npv': npv,
        'irr': irr,
        'payback_years': payback if payback != float('inf') else None,
        'capex': capex,
        'annual_revenue': annual_revenue,
        'annual_opex': annual_opex,
        'annual_cf': annual_cf
    }


def extrapolate_consumption_from_high_season(
    consumption: np.ndarray,
    timestamps: List[str],
    monthly_bands: List[dict],
    pv_profile: np.ndarray
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Ekstrapoluje zużycie z sezonu HIGH na cały rok.

    ULEPSZONA LOGIKA:
    1. Oblicz ŚREDNIĄ miesięcznego zużycia w miesiącach HIGH (nie medianę)
    2. Skaluj miesiące MID i LOW do poziomu średniej HIGH
    3. Miesiące HIGH pozostają bez zmian

    Średnia jest lepsza od mediany bo:
    - Uwzględnia wszystkie wartości HIGH (nie ignoruje outlierów)
    - Daje wyższe oszacowanie dla scenariusza "pełne obroty"

    Args:
        consumption: Rzeczywiste zużycie godzinowe
        timestamps: Timestampy
        monthly_bands: Mapowanie miesięcy na pasma
        pv_profile: Profil PV (do zachowania proporcji godzinowych)

    Returns:
        Tuple (ekstrapolowane_zużycie, ekstrapolowany_pv_profile)
    """
    parsed_times = pd.to_datetime(timestamps)
    month_band_map = {item['month']: item['dominant_band'] for item in monthly_bands}

    # Znajdź miesiące HIGH
    high_months = [m for m, b in month_band_map.items() if b == 'High']

    if not high_months:
        print("⚠️ Brak miesięcy HIGH - używam całego roku")
        return consumption, pv_profile

    # Oblicz zużycie miesięczne dla każdego miesiąca
    monthly_consumption = {}
    monthly_hours = {}

    for i, ts in enumerate(parsed_times):
        month_key = ts.strftime('%Y-%m')
        if month_key not in monthly_consumption:
            monthly_consumption[month_key] = 0
            monthly_hours[month_key] = 0
        monthly_consumption[month_key] += consumption[i]
        monthly_hours[month_key] += 1

    # Zużycie miesięczne tylko dla HIGH
    high_monthly_values = [
        monthly_consumption[m] for m in high_months
        if m in monthly_consumption
    ]

    if not high_monthly_values:
        print("⚠️ Brak danych zużycia dla miesięcy HIGH")
        return consumption, pv_profile

    # ŚREDNIA miesięcznego zużycia w HIGH (zamiast mediany)
    mean_high_consumption = np.mean(high_monthly_values)
    median_high_consumption = np.median(high_monthly_values)
    max_high_consumption = np.max(high_monthly_values)

    # Znajdź miesiące MID i LOW do skalowania
    mid_months = [m for m, b in month_band_map.items() if b == 'Mid']
    low_months = [m for m, b in month_band_map.items() if b == 'Low']

    print(f"📊 Ekstrapolacja zużycia z sezonu HIGH (ulepszona):")
    print(f"   Miesiące HIGH: {', '.join(high_months)} ({len(high_months)} mies.)")
    print(f"   Miesiące MID:  {', '.join(mid_months)} ({len(mid_months)} mies.) - będą skalowane")
    print(f"   Miesiące LOW:  {', '.join(low_months)} ({len(low_months)} mies.) - będą skalowane")
    print(f"   Zużycie miesięczne HIGH: {[f'{v/1000:.1f} MWh' for v in high_monthly_values]}")
    print(f"   Statystyki HIGH:")
    print(f"      Średnia: {mean_high_consumption/1000:.1f} MWh/mies. (używana do skalowania)")
    print(f"      Mediana: {median_high_consumption/1000:.1f} MWh/mies.")
    print(f"      Max:     {max_high_consumption/1000:.1f} MWh/mies.")

    # Ekstrapolacja: dla miesięcy MID i LOW, skaluj do ŚREDNIEJ HIGH
    extrapolated_consumption = consumption.copy()
    scaling_info = []

    for month_key, band in month_band_map.items():
        # Skaluj MID i LOW (nie tylko LOW jak wcześniej)
        if band in ['Mid', 'Low'] and month_key in monthly_consumption:
            current_monthly = monthly_consumption[month_key]
            if current_monthly > 0:
                scale_factor = mean_high_consumption / current_monthly
            else:
                scale_factor = 1.0

            # Skaluj godziny tego miesiąca
            for i, ts in enumerate(parsed_times):
                if ts.strftime('%Y-%m') == month_key:
                    extrapolated_consumption[i] = consumption[i] * scale_factor

            scaling_info.append({
                'month': month_key,
                'band': band,
                'original': current_monthly / 1000,
                'scaled': mean_high_consumption / 1000,
                'factor': scale_factor
            })

    # Wyświetl szczegóły skalowania
    print(f"\n   Skalowanie miesięcy MID+LOW:")
    for info in scaling_info:
        print(f"      {info['month']} ({info['band']}): {info['original']:.1f} → {info['scaled']:.1f} MWh (x{info['factor']:.2f})")

    # Podsumowanie
    original_total = consumption.sum()
    extrapolated_total = extrapolated_consumption.sum()

    print(f"\n   Zużycie oryginalne: {original_total/1000:.1f} MWh/rok")
    print(f"   Zużycie ekstrapolowane: {extrapolated_total/1000:.1f} MWh/rok")
    print(f"   Współczynnik ekstrapolacji: {extrapolated_total/original_total:.2f}x")

    return extrapolated_consumption, pv_profile


def optimize_seasonality_bands(
    pv_config: PVConfiguration,
    consumption: np.ndarray,
    timestamps: List[str],
    pv_profile: np.ndarray,
    monthly_bands: List[dict],
    capacity_min: float,
    capacity_max: float,
    capacity_step: float,
    capex_per_kwp: float,
    opex_per_kwp_year: float,
    energy_price_esco: float,
    discount_rate: float,
    project_years: int,
    mode: str = "MAX_AUTOCONSUMPTION",
    target_seasons: List[str] = None,
    autoconsumption_thresholds: dict = None  # {"A": 95, "B": 90, "C": 85, "D": 80}
) -> SeasonalityOptimizationResult:
    """
    Optymalizacja doboru mocy PV z uwzględnieniem sezonowości.

    LOGIKA DLA MAX_NPV (dwuetapowa):
    1. ESTYMACJA: Ekstrapoluj zużycie HIGH na cały rok, szukaj optymalnej mocy
    2. WERYFIKACJA: Przelicz NPV dla znalezionej mocy na RZECZYWISTYM zużyciu

    LOGIKA DLA MAX_AUTOCONSUMPTION:
    - Maksymalizuj MWh autokonsumpcji przy zachowaniu progu autokonsumpcji

    Args:
        target_seasons: Lista sezonów do optymalizacji ["High", "Mid", "Low"]
        autoconsumption_thresholds: Progi autokonsumpcji z ustawień {"A": 95, "B": 90, ...}

    Returns:
        SeasonalityOptimizationResult z najlepszą konfiguracją
    """
    global optimization_progress

    # Domyślnie High jeśli nie podano
    if target_seasons is None:
        target_seasons = ["High"]

    # Domyślne progi autokonsumpcji
    if autoconsumption_thresholds is None:
        autoconsumption_thresholds = {"A": 95, "B": 90, "C": 85, "D": 80}

    # Minimalny próg autokonsumpcji dla filtrowania (próg D)
    min_autoconsumption_pct = autoconsumption_thresholds.get("D", 80)

    print(f"\n{'='*60}")
    print(f"🎯 Optymalizacja SEZONOWA - tryb: {mode}")
    print(f"🎯 Sezony docelowe: {', '.join(target_seasons)}")
    print(f"🎯 Min. autokonsumpcja: {min_autoconsumption_pct}%")
    print(f"{'='*60}")

    # ========== KROK 1: EKSTRAPOLACJA (tylko dla MAX_NPV) ==========
    if mode == "MAX_NPV":
        print(f"\n📈 KROK 1: Ekstrapolacja zużycia HIGH na cały rok")
        extrapolated_consumption, extrapolated_pv = extrapolate_consumption_from_high_season(
            consumption, timestamps, monthly_bands, pv_profile
        )
        search_consumption = extrapolated_consumption
    else:
        search_consumption = consumption

    # ========== KROK 2: SZUKANIE OPTYMALNEJ MOCY ==========
    print(f"\n🔍 KROK 2: Szukanie optymalnej mocy")

    all_configs = []
    config_id = 0
    num_capacities = int((capacity_max - capacity_min) / capacity_step) + 1
    print(f"📊 Testowanie {num_capacities} konfiguracji mocy")

    # Initialize progress
    optimization_progress["active"] = True
    optimization_progress["total_configs"] = num_capacities
    optimization_progress["tested_configs"] = 0
    optimization_progress["percent"] = 0
    optimization_progress["step"] = "Szukanie optymalnej mocy"

    capacity = capacity_min
    progress_step = max(1, num_capacities // 20)

    while capacity <= capacity_max:
        capacity_idx = int((capacity - capacity_min) / capacity_step)
        if capacity_idx % progress_step == 0:
            progress_pct = (capacity_idx / num_capacities) * 100
            print(f"   ⏳ Postęp: {progress_pct:.0f}% ({capacity:.0f} kWp)")
            optimization_progress["percent"] = int(progress_pct)
            optimization_progress["current_capacity"] = capacity
            optimization_progress["step"] = f"Testowanie {capacity:.0f} kWp"

        dcac_ratio = get_dcac_for_capacity(capacity, pv_config.dcac_tiers, pv_config.dc_ac_ratio)

        # Symulacja na zużyciu do przeszukiwania (ekstrapolowanym lub rzeczywistym)
        sim_result = simulate_pv_with_seasonal_bands(
            capacity_kwp=capacity,
            pv_profile=pv_profile,
            consumption=search_consumption,
            timestamps=timestamps,
            monthly_bands=monthly_bands,
            dc_ac_ratio=dcac_ratio,
            target_seasons=target_seasons
        )

        # NPV dla przeszukiwania
        fin_result = calculate_npv_for_config(
            sim_result,
            capex_per_kwp,
            opex_per_kwp_year,
            energy_price_esco,
            discount_rate,
            project_years
        )

        all_configs.append({
            'id': config_id,
            'capacity_kwp': capacity,
            'dcac_ratio': dcac_ratio,
            'autoconsumption_pct': sim_result['autoconsumption_pct'],
            'coverage_pct': sim_result['coverage_pct'],
            'production_mwh': sim_result['production_mwh'],
            'self_consumed_mwh': sim_result['self_consumed_mwh'],
            'exported_mwh': sim_result['exported_mwh'],
            'target_self_consumed_mwh': sim_result['target_self_consumed_mwh'],
            'target_autoconsumption_pct': sim_result['target_autoconsumption_pct'],
            'target_coverage_pct': sim_result['target_coverage_pct'],
            'npv': fin_result['npv'],
            'irr': fin_result['irr'],
            'payback_years': fin_result['payback_years']
        })

        config_id += 1
        capacity += capacity_step

    print(f"✓ Przetestowano {len(all_configs)} konfiguracji")

    # ========== WYBÓR NAJLEPSZEJ KONFIGURACJI ==========
    target_seasons_str = ", ".join(target_seasons) if target_seasons else "wszystkie"

    if mode == "MAX_AUTOCONSUMPTION":
        # Filtruj wg autokonsumpcji całorocznej
        filtered_configs = [
            c for c in all_configs
            if c['autoconsumption_pct'] >= min_autoconsumption_pct
        ]
        if not filtered_configs:
            print(f"⚠️ Brak konfiguracji z autokonsumpcją >= {min_autoconsumption_pct}%, biorę wszystkie")
            filtered_configs = all_configs

        best = max(filtered_configs, key=lambda x: x['target_self_consumed_mwh'])
        print(f"🏆 Najlepsza autokonsumpcja w sezonie {target_seasons_str}:")
        print(f"   Moc: {best['capacity_kwp']:.0f} kWp")
        print(f"   Target MWh: {best['target_self_consumed_mwh']:.2f} MWh")
        print(f"   Auto%: {best['autoconsumption_pct']:.1f}%")
        print(f"   NPV: {best['npv']:,.0f} PLN")

    else:  # MAX_NPV
        # Szukaj max NPV na ekstrapolowanym zużyciu - BEZ filtra autokonsumpcji!
        best_extrapolated = max(all_configs, key=lambda x: x['npv'] if x.get('npv') else float('-inf'))

        print(f"\n📈 Wynik na EKSTRAPOLOWANYM zużyciu:")
        print(f"   Moc: {best_extrapolated['capacity_kwp']:.0f} kWp")
        print(f"   NPV (ekstrap.): {best_extrapolated['npv']:,.0f} PLN")
        print(f"   Auto% (ekstrap.): {best_extrapolated['autoconsumption_pct']:.1f}%")
        print(f"   Self-consumed (ekstrap.): {best_extrapolated['self_consumed_mwh']:.2f} MWh")

        # ========== KROK 3: WERYFIKACJA NA RZECZYWISTYM ZUŻYCIU ==========
        print(f"\n✅ KROK 3: Weryfikacja na RZECZYWISTYM zużyciu")

        # Symulacja z tą samą mocą, ale na rzeczywistym zużyciu
        real_sim_result = simulate_pv_with_seasonal_bands(
            capacity_kwp=best_extrapolated['capacity_kwp'],
            pv_profile=pv_profile,
            consumption=consumption,  # RZECZYWISTE zużycie!
            timestamps=timestamps,
            monthly_bands=monthly_bands,
            dc_ac_ratio=best_extrapolated['dcac_ratio'],
            target_seasons=target_seasons
        )

        real_fin_result = calculate_npv_for_config(
            real_sim_result,
            capex_per_kwp,
            opex_per_kwp_year,
            energy_price_esco,
            discount_rate,
            project_years
        )

        # Nadpisz metryki rzeczywistymi wartościami
        best = {
            'capacity_kwp': best_extrapolated['capacity_kwp'],
            'dcac_ratio': best_extrapolated['dcac_ratio'],
            'autoconsumption_pct': real_sim_result['autoconsumption_pct'],
            'coverage_pct': real_sim_result['coverage_pct'],
            'production_mwh': real_sim_result['production_mwh'],
            'self_consumed_mwh': real_sim_result['self_consumed_mwh'],
            'exported_mwh': real_sim_result['exported_mwh'],
            'target_self_consumed_mwh': real_sim_result['target_self_consumed_mwh'],
            'target_autoconsumption_pct': real_sim_result['target_autoconsumption_pct'],
            'target_coverage_pct': real_sim_result['target_coverage_pct'],
            'npv': real_fin_result['npv'],
            'irr': real_fin_result['irr'],
            'payback_years': real_fin_result['payback_years'],
            # Dodatkowe info o ekstrapolacji
            'extrapolated_npv': best_extrapolated['npv'],
            'extrapolated_self_consumed_mwh': best_extrapolated['self_consumed_mwh']
        }

        print(f"\n🏆 Wynik na RZECZYWISTYM zużyciu:")
        print(f"   Moc: {best['capacity_kwp']:.0f} kWp")
        print(f"   NPV (rzeczywiste): {best['npv']:,.0f} PLN")
        print(f"   Auto% (rzeczywiste): {best['autoconsumption_pct']:.1f}%")
        print(f"   Self-consumed (rzeczywiste): {best['self_consumed_mwh']:.2f} MWh")

    # Mark optimization as complete
    optimization_progress["percent"] = 100
    optimization_progress["step"] = "Zakończono"
    optimization_progress["active"] = False

    # Przygotuj tabelę porównawczą (top 20)
    sorted_configs = sorted(
        all_configs,
        key=lambda x: x['npv'] if x.get('npv') else float('-inf'),
        reverse=True
    )[:20]

    # Konfiguracja pasm
    month_band_map = {item['month']: item['dominant_band'] for item in monthly_bands}
    band_config = []
    for band_name in ["High", "Mid", "Low"]:
        months_for_band = [m for m, b in month_band_map.items() if b == band_name]
        if months_for_band:
            band_config.append(BandConfig(
                band=band_name,
                ac_limit_kw=best['capacity_kwp'] / best['dcac_ratio'],
                months=months_for_band
            ))

    return SeasonalityOptimizationResult(
        mode=mode,
        best_capacity_kwp=best['capacity_kwp'],
        best_dcac_ratio=best['dcac_ratio'],
        best_band_config=band_config,
        autoconsumption_pct=best['autoconsumption_pct'],
        coverage_pct=best['coverage_pct'],
        annual_production_mwh=best['production_mwh'],
        annual_self_consumed_mwh=best['self_consumed_mwh'],
        annual_exported_mwh=best['exported_mwh'],
        target_self_consumed_mwh=best['target_self_consumed_mwh'],
        target_autoconsumption_pct=best['target_autoconsumption_pct'],
        target_coverage_pct=best['target_coverage_pct'],
        target_npv=best.get('npv'),
        target_seasons=target_seasons,
        npv=best['npv'],
        irr=best['irr'],
        payback_years=best['payback_years'],
        configurations_tested=len(all_configs),
        all_configurations=sorted_configs
    )


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


def simulate_pv_system_batch(
    capacities: np.ndarray,
    dcac_ratios: np.ndarray,
    pv_profile: np.ndarray,
    consumption: np.ndarray,
) -> list:
    """
    Vectorized PV simulation for multiple capacities at once.

    Instead of N separate calls to simulate_pv_system(), this computes
    all capacities in a single NumPy operation on (8760, N) matrices.

    Args:
        capacities: Array of PV capacities [kWp], shape (N,)
        dcac_ratios: Array of DC/AC ratios, shape (N,)
        pv_profile: Hourly generation per kWp, shape (8760,)
        consumption: Hourly consumption in kW, shape (8760,)

    Returns:
        List of SimulationResult objects (same as calling simulate_pv_system N times)
    """
    n_cap = len(capacities)
    n_hours = len(pv_profile)

    # Broadcast: pv_profile (8760,1) * capacities (1,N) -> (8760, N)
    production = pv_profile[:, None] * capacities[None, :]

    # Clip to AC capacity (inverter limit per capacity)
    ac_capacities = capacities / dcac_ratios  # (N,)
    production = np.minimum(production, ac_capacities[None, :])

    # Self-consumed and exported: (8760, N)
    consumption_2d = consumption[:, None]  # (8760, 1) broadcasts to (8760, N)
    self_consumed = np.minimum(production, consumption_2d)
    exported = production - self_consumed

    # Sum along time axis -> (N,) totals
    total_production = production.sum(axis=0)
    total_consumed = self_consumed.sum(axis=0)
    total_exported = exported.sum(axis=0)
    total_consumption = consumption.sum()  # scalar

    # Percentages
    auto_pct = np.where(total_production > 0, total_consumed / total_production * 100, 0.0)
    coverage_pct = np.where(total_consumption > 0, total_consumed / total_consumption * 100, 0.0)

    # Build result list
    results = []
    for i in range(n_cap):
        results.append(SimulationResult(
            capacity=float(capacities[i]),
            dcac_ratio=float(dcac_ratios[i]),
            production=float(total_production[i]),
            self_consumed=float(total_consumed[i]),
            exported=float(total_exported[i]),
            auto_consumption_pct=float(auto_pct[i]),
            coverage_pct=float(coverage_pct[i])
        ))

    return results


def simulate_pv_system_with_bess(
    capacity: float,
    pv_profile: np.ndarray,
    consumption: np.ndarray,
    bess_power_kw: float,
    bess_energy_kwh: float,
    dc_ac_ratio: float = 1.2,
    roundtrip_efficiency: float = 0.90,
    soc_min: float = 0.10,
    soc_max: float = 0.90,
    soc_initial: float = 0.50
) -> SimulationResult:
    """
    Simulate PV system with BESS in 0-export mode (greedy dispatch).

    In 0-export mode:
    - PV surplus charges the battery (no grid export)
    - Battery discharges to cover load deficit
    - Excess PV when battery is full = curtailment
    - Remaining deficit after battery = grid import

    Args:
        capacity: PV system capacity in kWp
        pv_profile: Hourly generation per kWp (8760 values)
        consumption: Hourly consumption in kW (8760 values)
        bess_power_kw: Battery max charge/discharge power in kW
        bess_energy_kwh: Battery total capacity in kWh
        dc_ac_ratio: DC to AC capacity ratio
        roundtrip_efficiency: Round-trip efficiency (0.88-0.92 typical)
        soc_min: Minimum SOC (0.10 = 10%)
        soc_max: Maximum SOC (0.90 = 90%)
        soc_initial: Initial SOC (0.50 = 50%)

    Returns:
        SimulationResult with BESS metrics including monthly breakdown
    """
    # Polish month names
    MONTH_NAMES_PL = [
        "Styczeń", "Luty", "Marzec", "Kwiecień", "Maj", "Czerwiec",
        "Lipiec", "Sierpień", "Wrzesień", "Październik", "Listopad", "Grudzień"
    ]

    # Scale profile by capacity with inverter clipping
    ac_capacity = capacity / dc_ac_ratio
    production = np.minimum(pv_profile * capacity, ac_capacity)

    n_hours = len(production)

    # Usable energy capacity (considering SOC limits)
    usable_energy = bess_energy_kwh * (soc_max - soc_min)

    # One-way efficiency (sqrt of roundtrip)
    one_way_eff = np.sqrt(roundtrip_efficiency)

    # Initialize tracking arrays
    soc = soc_initial * bess_energy_kwh  # Current energy in battery (kWh)
    soc_min_kwh = soc_min * bess_energy_kwh
    soc_max_kwh = soc_max * bess_energy_kwh

    # Annual accumulators
    total_direct_consumed = 0.0      # PV directly consumed by load
    total_charged = 0.0              # Energy into battery (before losses)
    total_discharged = 0.0           # Energy from battery (after losses)
    total_curtailed = 0.0            # Excess PV curtailed (0-export)
    total_grid_import = 0.0          # Energy imported from grid
    total_self_from_bess = 0.0       # Load covered by battery

    # Monthly accumulators (NEW in v3.2)
    monthly_charged = [0.0] * 12
    monthly_discharged = [0.0] * 12
    monthly_curtailed = [0.0] * 12
    monthly_grid_import = [0.0] * 12
    monthly_direct_consumed = [0.0] * 12
    monthly_self_from_bess = [0.0] * 12

    # SOC histogram (10 bins: 0-10%, 10-20%, ..., 90-100%)
    soc_histogram_bins = [0] * 10  # Hours count in each bin

    # Hours per month (for standard 8760-hour year)
    # Jan(744), Feb(672), Mar(744), Apr(720), May(744), Jun(720),
    # Jul(744), Aug(744), Sep(720), Oct(744), Nov(720), Dec(744)
    hours_per_month = [744, 672, 744, 720, 744, 720, 744, 744, 720, 744, 720, 744]
    month_start_hours = [0]
    for hours in hours_per_month[:-1]:
        month_start_hours.append(month_start_hours[-1] + hours)

    def get_month_index(hour: int) -> int:
        """Get month index (0-11) for given hour (0-8759)"""
        for m in range(11, -1, -1):
            if hour >= month_start_hours[m]:
                return m
        return 0

    for h in range(n_hours):
        pv = production[h]
        load = consumption[h]
        month_idx = get_month_index(h)

        # Step 1: Direct self-consumption
        direct = min(pv, load)
        total_direct_consumed += direct
        monthly_direct_consumed[month_idx] += direct

        surplus = pv - direct      # PV surplus after direct consumption
        deficit = load - direct    # Remaining load after direct consumption

        # Step 2: Handle surplus (charge battery or curtail)
        if surplus > 0:
            # Limit by battery power and available space
            charge_power = min(surplus, bess_power_kw)
            available_space = soc_max_kwh - soc
            # Energy stored = charge_power * efficiency
            charge_energy = min(charge_power * one_way_eff, available_space)

            if charge_energy > 0:
                soc += charge_energy
                charged_power = charge_energy / one_way_eff  # Track gross input
                total_charged += charged_power
                monthly_charged[month_idx] += charged_power

            # Remaining surplus is curtailed (0-export mode)
            actually_charged_power = charge_energy / one_way_eff if charge_energy > 0 else 0
            curtailed = surplus - actually_charged_power
            total_curtailed += curtailed
            monthly_curtailed[month_idx] += curtailed

        # Step 3: Handle deficit (discharge battery or import from grid)
        if deficit > 0:
            # Limit by battery power and available energy
            discharge_power = min(deficit, bess_power_kw)
            available_energy = soc - soc_min_kwh
            # Energy delivered = discharge * efficiency
            discharge_from_soc = min(discharge_power / one_way_eff, available_energy)
            discharge_delivered = discharge_from_soc * one_way_eff

            if discharge_delivered > 0:
                soc -= discharge_from_soc
                total_discharged += discharge_delivered
                total_self_from_bess += discharge_delivered
                monthly_discharged[month_idx] += discharge_delivered
                monthly_self_from_bess[month_idx] += discharge_delivered

            # Remaining deficit = grid import
            grid_import = deficit - discharge_delivered
            total_grid_import += grid_import
            monthly_grid_import[month_idx] += grid_import

        # Track SOC in histogram (at end of hour)
        soc_pct = (soc / bess_energy_kwh) * 100 if bess_energy_kwh > 0 else 0
        bin_idx = min(int(soc_pct / 10), 9)  # 0-9 bins
        soc_histogram_bins[bin_idx] += 1

    # Calculate totals
    total_production = production.sum()
    total_consumption = consumption.sum()
    total_self_consumed = total_direct_consumed + total_self_from_bess

    # In 0-export mode, exported is always 0
    total_exported = 0.0

    # Calculate percentages
    # Auto-consumption = what % of PV production was used (not curtailed/exported)
    pv_utilized = total_direct_consumed + (total_charged * one_way_eff)  # Direct + what went to battery
    auto_consumption_pct = (pv_utilized / total_production * 100) if total_production > 0 else 0

    # Coverage = what % of load was covered by PV+BESS
    coverage_pct = (total_self_consumed / total_consumption * 100) if total_consumption > 0 else 0

    # Equivalent cycles = total energy throughput / usable capacity
    cycles_equivalent = (total_charged + total_discharged) / (2 * usable_energy) if usable_energy > 0 else 0

    # Build monthly data (NEW in v3.2)
    monthly_data = []
    for m in range(12):
        throughput = monthly_charged[m] + monthly_discharged[m]
        monthly_cycles = throughput / (2 * usable_energy) if usable_energy > 0 else 0
        monthly_data.append(BESSMonthlyData(
            month=m + 1,
            month_name=MONTH_NAMES_PL[m],
            charged_kwh=round(monthly_charged[m], 2),
            discharged_kwh=round(monthly_discharged[m], 2),
            curtailed_kwh=round(monthly_curtailed[m], 2),
            grid_import_kwh=round(monthly_grid_import[m], 2),
            self_consumed_direct_kwh=round(monthly_direct_consumed[m], 2),
            self_consumed_from_bess_kwh=round(monthly_self_from_bess[m], 2),
            cycles_equivalent=round(monthly_cycles, 2),
            throughput_kwh=round(throughput, 2)
        ))

    # Build SOC histogram (NEW in v3.2)
    soc_histogram_labels = [f"{i*10}-{(i+1)*10}%" for i in range(10)]
    total_hours = sum(soc_histogram_bins)
    soc_histogram_pcts = [
        round(h / total_hours * 100, 1) if total_hours > 0 else 0
        for h in soc_histogram_bins
    ]
    soc_histogram = BESSSOCHistogram(
        bins=soc_histogram_labels,
        hours=soc_histogram_bins,
        percentages=soc_histogram_pcts
    )

    return SimulationResult(
        capacity=capacity,
        dcac_ratio=dc_ac_ratio,
        production=total_production,
        self_consumed=total_self_consumed,
        exported=total_exported,
        auto_consumption_pct=auto_consumption_pct,
        coverage_pct=coverage_pct,
        # BESS specific fields
        bess_power_kw=bess_power_kw,
        bess_energy_kwh=bess_energy_kwh,
        bess_charged_kwh=total_charged,
        bess_discharged_kwh=total_discharged,
        bess_curtailed_kwh=total_curtailed,
        bess_grid_import_kwh=total_grid_import,
        bess_self_consumed_direct_kwh=total_direct_consumed,
        bess_self_consumed_from_bess_kwh=total_self_from_bess,
        bess_cycles_equivalent=cycles_equivalent,
        # Monthly breakdown (NEW in v3.2)
        bess_monthly_data=monthly_data,
        # SOC histogram (NEW in v3.2)
        bess_soc_histogram=soc_histogram
    )


def auto_size_bess_lite(
    pv_profile: np.ndarray,
    consumption: np.ndarray,
    capacity: float,
    dc_ac_ratio: float = 1.2,
    duration: str = 'auto',
    capex_per_kwh: float = 1500.0,
    capex_per_kw: float = 300.0,
    energy_price_plnmwh: float = 800.0,
    discount_rate: float = 0.07,
    lifetime_years: int = 15,
    roundtrip_efficiency: float = 0.90
) -> tuple:
    """
    Auto-size BESS power (kW) and energy (kWh) using iterative NPV optimization.

    Tests multiple BESS sizes and selects the one with best NPV.
    This ensures the selected size is economically optimal, not just technically feasible.

    Args:
        pv_profile: Hourly generation per kWp
        consumption: Hourly consumption in kW
        capacity: PV system capacity in kWp
        dc_ac_ratio: DC to AC ratio
        duration: 'auto' | '1' | '2' | '4' hours
        capex_per_kwh: CAPEX per kWh of storage [PLN/kWh]
        capex_per_kw: CAPEX per kW of power [PLN/kW]
        energy_price_plnmwh: Energy price [PLN/MWh]
        discount_rate: Discount rate for NPV calculation
        lifetime_years: BESS lifetime [years]
        roundtrip_efficiency: Round-trip efficiency

    Returns:
        Tuple of (bess_power_kw, bess_energy_kwh)
    """
    # Calculate PV production
    ac_capacity = capacity / dc_ac_ratio
    production = np.minimum(pv_profile * capacity, ac_capacity)

    # Calculate hourly surplus and deficit
    direct_consumed = np.minimum(production, consumption)
    surplus = production - direct_consumed
    deficit = consumption - direct_consumed

    # Filter only hours with surplus
    surplus_positive = surplus[surplus > 0]

    if len(surplus_positive) == 0:
        # No surplus at all - no battery needed
        return (0.0, 0.0)

    # Calculate annuity factor for NPV
    if discount_rate > 0:
        annuity_factor = (discount_rate * (1 + discount_rate) ** lifetime_years) / \
                         ((1 + discount_rate) ** lifetime_years - 1)
    else:
        annuity_factor = 1.0 / lifetime_years

    # Determine duration multiplier
    if duration == 'auto':
        duration_h = 2.0  # Default 2h for iteration
    else:
        try:
            duration_h = float(duration)
        except (ValueError, TypeError):
            duration_h = 2.0

    # Define power range to test (10 steps from small to large)
    # Max power based on 75th percentile of surplus (not 95th - that's too aggressive)
    p_max_candidate = np.percentile(surplus_positive, 75)
    p_max_candidate = max(p_max_candidate, 50.0)  # At least 50 kW

    # Test range from 10% to 100% of max candidate
    power_steps = np.linspace(p_max_candidate * 0.1, p_max_candidate, 10)

    best_npv = float('-inf')
    best_power = 0.0
    best_energy = 0.0

    energy_price_plnkwh = energy_price_plnmwh / 1000.0
    eta = np.sqrt(roundtrip_efficiency)  # One-way efficiency

    for p_test in power_steps:
        e_test = p_test * duration_h

        # Quick dispatch simulation
        annual_discharge = _simulate_quick_dispatch(
            surplus=surplus,
            deficit=deficit,
            power_kw=p_test,
            energy_kwh=e_test,
            eta=eta
        )

        # Calculate annual savings
        annual_savings = annual_discharge * energy_price_plnkwh

        # Calculate CAPEX
        capex = p_test * capex_per_kw + e_test * capex_per_kwh

        # Calculate annualized cost
        annual_cost = capex * annuity_factor

        # Net annual benefit
        net_annual = annual_savings - annual_cost

        # Simple NPV approximation (using annuity)
        npv = net_annual / annuity_factor if annuity_factor > 0 else net_annual * lifetime_years

        if npv > best_npv:
            best_npv = npv
            best_power = p_test
            best_energy = e_test

    # If no positive NPV found, return minimal or zero
    if best_npv <= 0:
        # Check if even minimal battery is worth it
        min_power = 50.0
        min_energy = min_power * duration_h
        min_discharge = _simulate_quick_dispatch(surplus, deficit, min_power, min_energy, eta)
        min_savings = min_discharge * energy_price_plnkwh
        min_capex = min_power * capex_per_kw + min_energy * capex_per_kwh
        min_annual_cost = min_capex * annuity_factor

        if min_savings > min_annual_cost:
            return (round(min_power, 1), round(min_energy, 1))
        else:
            # Battery doesn't pay for itself - return zero
            return (0.0, 0.0)

    # Round to reasonable values
    best_power = round(best_power, 1)
    best_energy = round(best_energy, 1)

    return (best_power, best_energy)


def _simulate_quick_dispatch(
    surplus: np.ndarray,
    deficit: np.ndarray,
    power_kw: float,
    energy_kwh: float,
    eta: float,
    soc_min: float = 0.1,
    soc_max: float = 0.9
) -> float:
    """
    Quick greedy dispatch simulation to estimate annual discharge.

    Returns:
        Annual discharge in kWh
    """
    usable_capacity = energy_kwh * (soc_max - soc_min)
    soc = usable_capacity * 0.5  # Start at 50%
    total_discharge = 0.0

    for i in range(len(surplus)):
        s = surplus[i]
        d = deficit[i]

        # Charge from surplus
        if s > 0 and soc < usable_capacity:
            charge = min(s, power_kw, (usable_capacity - soc) / eta)
            soc += charge * eta

        # Discharge to cover deficit
        if d > 0 and soc > 0:
            discharge = min(d, power_kw, soc * eta)
            soc -= discharge / eta
            total_discharge += discharge

    return total_discharge


def call_bess_pro_optimizer(
    pv_generation: np.ndarray,
    consumption: np.ndarray,
    pv_capacity_kwp: float,
    bess_config: "BESSConfigLite",
    energy_price_plnmwh: float = 800.0,
    discount_rate: float = 0.07,
    analysis_period_years: int = 25
) -> Optional[dict]:
    """
    Call the BESS PRO optimizer service for LP/MIP optimization.

    Args:
        pv_generation: Hourly PV generation [kWh]
        consumption: Hourly load [kWh]
        pv_capacity_kwp: PV capacity [kWp]
        bess_config: BESS configuration with pro_config
        energy_price_plnmwh: Energy price [PLN/MWh]
        discount_rate: Discount rate (e.g., 0.07 = 7%)
        analysis_period_years: Analysis period [years]

    Returns:
        Optimization result dict or None if failed
    """
    if not bess_config.pro_config:
        print("⚠️ BESS PRO config missing, falling back to LIGHT mode")
        return None

    pro = bess_config.pro_config

    # Build request payload
    payload = {
        "pv_generation_kwh": pv_generation.tolist(),
        "load_kwh": consumption.tolist(),
        "pv_capacity_kwp": pv_capacity_kwp,
        "min_power_kw": pro.min_power_kw,
        "max_power_kw": pro.max_power_kw,
        "min_energy_kwh": pro.min_energy_kwh,
        "max_energy_kwh": pro.max_energy_kwh,
        "duration_min_h": pro.duration_min,
        "duration_max_h": pro.duration_max,
        "roundtrip_efficiency": bess_config.roundtrip_efficiency,
        "soc_min": bess_config.soc_min,
        "soc_max": bess_config.soc_max,
        "capex_per_kwh": bess_config.capex_per_kwh,
        "capex_per_kw": bess_config.capex_per_kw,
        "opex_pct_per_year": bess_config.opex_pct_per_year,
        "lifetime_years": bess_config.lifetime_years,
        "energy_price_plnmwh": energy_price_plnmwh,
        "discount_rate": discount_rate,
        "analysis_period_years": analysis_period_years,
        "solver": pro.solver,
        "objective": pro.objective,
        "time_resolution": pro.time_resolution,
        "typical_days": pro.typical_days,
        "zero_export": pro.zero_export,
        "export_penalty_plnmwh": pro.export_penalty
    }

    try:
        print(f"🚀 Calling BESS PRO optimizer at {BESS_OPTIMIZER_URL}/optimize")
        response = requests.post(
            f"{BESS_OPTIMIZER_URL}/optimize",
            json=payload,
            timeout=300  # 5 minutes timeout for optimization
        )

        if response.status_code == 200:
            result = response.json()
            print(f"✅ BESS PRO optimization successful:")
            print(f"   Optimal: {result['optimal_power_kw']:.0f} kW / {result['optimal_energy_kwh']:.0f} kWh")
            print(f"   NPV: {result['npv_bess_pln']:.0f} PLN")
            print(f"   Solve time: {result['solve_time_s']:.1f}s")
            return result
        else:
            print(f"❌ BESS PRO optimizer error: {response.status_code}")
            print(f"   Response: {response.text[:500]}")
            return None

    except requests.exceptions.Timeout:
        print("❌ BESS PRO optimizer timeout (>5min)")
        return None
    except requests.exceptions.ConnectionError as e:
        print(f"❌ BESS PRO optimizer connection error: {e}")
        print("   Is bess-optimizer service running?")
        return None
    except Exception as e:
        print(f"❌ BESS PRO optimizer error: {e}")
        return None


def call_capacity_fee_scenarios(
    load_kwh: List[float],
    pv_kwh: Optional[List[float]] = None,
    bess_charge_from_grid_kwh: Optional[List[float]] = None,
    bess_discharge_kwh: Optional[List[float]] = None,
    som_rate_pln_kwh: float = 0.2194,
    data_start_date: Optional[str] = None,
    start_year: int = 2026,
) -> Optional[dict]:
    """
    Call profile-analysis /compute-capacity-fee-scenarios for K-class calculation.

    Returns dict with baseline, with_pv, with_pv_bess scenarios and savings,
    or None on failure.
    """
    payload = {
        "load_kwh": load_kwh,
        "som_rate_pln_kwh": som_rate_pln_kwh,
        "selected_start": 7,
        "selected_end": 22,
        "start_year": start_year,
    }
    if pv_kwh:
        payload["pv_kwh"] = pv_kwh
    if bess_charge_from_grid_kwh:
        payload["bess_charge_from_grid_kwh"] = bess_charge_from_grid_kwh
    if bess_discharge_kwh:
        payload["bess_discharge_kwh"] = bess_discharge_kwh
    if data_start_date:
        payload["data_start_date"] = data_start_date

    try:
        print(f"📊 Calling profile-analysis /compute-capacity-fee-scenarios")
        print(f"   load: {len(load_kwh)}h, pv: {len(pv_kwh) if pv_kwh else 0}h, "
              f"bess_charge: {len(bess_charge_from_grid_kwh) if bess_charge_from_grid_kwh else 0}h, "
              f"bess_discharge: {len(bess_discharge_kwh) if bess_discharge_kwh else 0}h")

        response = requests.post(
            f"{PROFILE_ANALYSIS_URL}/compute-capacity-fee-scenarios",
            json=payload,
            timeout=30,
        )
        if response.status_code == 200:
            result = response.json()
            baseline = result.get('baseline', {})
            with_pv = result.get('with_pv', {})
            with_pv_bess = result.get('with_pv_bess', {})
            print(f"   ✅ K-class: baseline={baseline.get('k_class','?')} fee={baseline.get('annual_fee_pln',0):.0f}")
            if with_pv:
                print(f"   ✅ K-class with PV: {with_pv.get('k_class','?')} fee={with_pv.get('annual_fee_pln',0):.0f}, savings={result.get('savings_pv_only_pln',0):.0f}")
            if with_pv_bess:
                print(f"   ✅ K-class with PV+BESS: {with_pv_bess.get('k_class','?')} fee={with_pv_bess.get('annual_fee_pln',0):.0f}, bess_incremental={result.get('savings_bess_incremental_pln',0):.0f}")
            return result
        else:
            print(f"   ❌ K-class error: {response.status_code} {response.text[:200]}")
            return None
    except requests.exceptions.Timeout:
        print("   ❌ K-class timeout (>30s)")
        return None
    except requests.exceptions.ConnectionError as e:
        print(f"   ❌ K-class connection error: {e}")
        return None
    except Exception as e:
        print(f"   ❌ K-class error: {e}")
        return None


def call_bess_dispatch_sizing(
    pv_generation_kw: List[float],
    load_kw: List[float],
    topology: str,  # 'pv_load' or 'load_only'
    bess_settings: dict,
    interval_minutes: int = 60
) -> Optional[dict]:
    """
    Call bess-dispatch /sizing endpoint for PRO optimization with LP/MIP solver.

    This is the ONLY way to get precise savings_breakdown.

    Args:
        pv_generation_kw: Hourly PV generation [kW] (empty for load_only)
        load_kw: Hourly load consumption [kW]
        topology: 'pv_load' (PV+BESS) or 'load_only' (BESS stand-alone)
        bess_settings: BESS settings from frontend (capex, opex, efficiency, etc.)
        interval_minutes: Data interval (60 for hourly)

    Returns:
        SizingResult dict with variants and savings_breakdown, or None if failed
    """
    # Determine dispatch mode based on topology and settings
    if topology == 'load_only':
        mode = 'load_only'
        # For load_only, we need peak_limit_kw for peak shaving
        peak_limit_kw = bess_settings.get('peak_limit_kw')
        if not peak_limit_kw:
            # Calculate reasonable peak limit from load profile
            load_array = np.array(load_kw)
            peak_limit_kw = float(np.percentile(load_array, 90))  # P90 as default target
    else:
        # Use dispatch_mode from settings if available, otherwise default to 'pv_surplus'
        mode = bess_settings.get('dispatch_mode', 'pv_surplus')
        peak_limit_kw = bess_settings.get('peak_limit_kw')
        # For stacked mode, calculate peak_limit from P95 if not provided
        if mode == 'stacked' and not peak_limit_kw:
            load_array = np.array(load_kw)
            peak_limit_kw = float(np.percentile(load_array, 95))  # P95 as default target
            print(f"   📊 Stacked mode: auto peak_limit_kw = {peak_limit_kw:.1f} kW (P95)")

    # Build request payload
    payload = {
        "pv_generation_kw": pv_generation_kw if topology == 'pv_load' else [],
        "load_kw": load_kw,
        "interval_minutes": interval_minutes,
        "mode": mode,

        # Peak shaving params (for load_only or stacked)
        "peak_limit_kw": peak_limit_kw,
        "reserve_fraction": bess_settings.get('reserve_fraction', 0.3),

        # Battery constraints from settings
        "min_power_kw": bess_settings.get('min_power_kw', 10.0),
        "max_power_kw": bess_settings.get('max_power_kw', 10000.0),
        "power_steps": bess_settings.get('power_steps', 10),

        # Duration variants
        "durations_h": bess_settings.get('durations_h', [1.0, 2.0, 4.0]),

        # Battery parameters
        "roundtrip_efficiency": bess_settings.get('roundtrip_efficiency', 0.90),
        "soc_min": bess_settings.get('soc_min', 0.10),
        "soc_max": bess_settings.get('soc_max', 0.90),

        # Degradation - supports year 1 and years 2+ separately (from Settings)
        "bess_degradation_year1_pct": bess_settings.get('bess_degradation_year1_pct', 3.0),  # Year 1 default 3%
        "annual_degradation_pct": bess_settings.get('annual_degradation_pct', 2.0),  # Years 2+ default 2%/year

        # Economics - defaults match Settings module defaults
        "capex_per_kwh": bess_settings.get('capex_per_kwh', 1500.0),  # PLN/kWh from Settings
        "capex_per_kw": bess_settings.get('capex_per_kw', 300.0),     # PLN/kW from Settings
        "opex_pct_per_year": bess_settings.get('opex_pct_per_year', 0.015),
        "discount_rate": bess_settings.get('discount_rate', 0.07),   # 7% from Settings.discountRate
        # BESS analysis horizon is capped at 10 years (battery lifetime constraint)
        "analysis_years": min(bess_settings.get('analysis_years', 15), 10),

        # Prices
        "import_price_pln_mwh": bess_settings.get('import_price_pln_mwh', 800.0),
        "export_price_pln_mwh": bess_settings.get('export_price_pln_mwh', 0.0),
        "demand_charge_pln_kw_month": bess_settings.get('demand_charge_pln_kw_month', 0.0),

        # Degradation budget (optional)
        "max_efc_per_year": bess_settings.get('max_efc_per_year'),
        "max_throughput_mwh_per_year": bess_settings.get('max_throughput_mwh_per_year'),

        # Include hourly profiles for K-class capacity fee calculation
        "include_hourly_profiles": True,
    }

    # Add ToU pricing if available
    if bess_settings.get('prices'):
        payload['prices'] = bess_settings['prices']

    # Add capacity fee configuration if available
    if bess_settings.get('capacity_fee'):
        cf = bess_settings['capacity_fee']
        # Add to prices dict (bess-dispatch expects it there)
        if 'prices' not in payload:
            payload['prices'] = {}
        payload['prices']['capacity_fee_method'] = 'polish_som'
        payload['prices']['capacity_fee_som_pln_kwh'] = cf.get('som_rate_pln_kw', 0.2194)
        print(f"   📊 Capacity fee: SOM={cf.get('som_rate_pln_kw', 0.2194)} PLN/kW/month")

    # Add arbitrage_config if ToU pricing is configured (enables price arbitrage in sizing)
    # This is CRITICAL for proper sizing with ToU tariffs - without it, sizing ignores price spreads
    if bess_settings.get('prices') and bess_settings['prices'].get('type') in ['two_zone', 'three_zone']:
        prices = bess_settings['prices']
        # Generate tariff_id that matches bess-dispatch presets (e.g., pge_c12a_2026)
        # Use simple format: operator_group_year
        tariff_id = f"pge_c12a_{2026}"  # Default to PGE C12a 2026

        day_rate = prices.get('day_rate_pln_mwh', 800) / 1000  # Convert to PLN/kWh
        night_rate = prices.get('night_rate_pln_mwh', 400) / 1000

        payload['arbitrage_config'] = {
            'enabled': True,
            'tariff_id': tariff_id,
            'strategy': 'zone_based',
            'charge_below_percentile': 30,
            'discharge_above_percentile': 70,
            'degradation_cost_pln_kwh': 0.02,  # Default degradation cost
        }
        # start_date is required when arbitrage is enabled (for ToU zone assignment)
        payload['start_date'] = bess_settings.get('start_date', '2024-01-01')
        print(f"   📊 Arbitrage enabled: tariff_id={tariff_id}, day={day_rate:.3f}/night={night_rate:.3f} PLN/kWh, start_date={payload['start_date']}")

    try:
        print(f"🚀 Calling bess-dispatch /sizing at {BESS_DISPATCH_URL}/sizing?compat=clean")
        print(f"   Mode: {mode}, Topology: {topology}, dispatch_mode from settings: {bess_settings.get('dispatch_mode', 'NOT_SET')}")
        print(f"   Load points: {len(load_kw)}, PV points: {len(pv_generation_kw)}")
        print(f"   demand_charge: {bess_settings.get('demand_charge_pln_kw_month', 0)} PLN/kW/month, peak_limit: {peak_limit_kw} kW")

        response = requests.post(
            f"{BESS_DISPATCH_URL}/sizing?compat=clean",
            json=payload,
            timeout=300  # 5 minutes timeout for optimization
        )

        if response.status_code == 200:
            result = response.json()
            print(f"✅ bess-dispatch sizing successful:")
            print(f"   Recommended: {result.get('recommended_power_kw', 0):.0f} kW / {result.get('recommended_energy_kwh', 0):.0f} kWh")
            if result.get('variants'):
                best = result['variants'][0]
                print(f"   Annual savings: {best.get('annual_savings_pln', 0):.0f} PLN")
                if best.get('savings_breakdown'):
                    sb = best['savings_breakdown']
                    print(f"   Savings breakdown: energy={sb.get('energy_savings_pln', 0):.0f}, "
                          f"demand={sb.get('demand_charge_savings_pln', 0):.0f}, "
                          f"capacity={sb.get('capacity_fee_savings_pln', 0):.0f}")
            return result
        else:
            print(f"❌ bess-dispatch sizing error: {response.status_code}")
            print(f"   Response: {response.text[:500]}")
            return None

    except requests.exceptions.Timeout:
        print("❌ bess-dispatch sizing timeout (>5min)")
        return None
    except requests.exceptions.ConnectionError as e:
        print(f"❌ bess-dispatch connection error: {e}")
        print("   Is bess-dispatch service running?")
        return None
    except Exception as e:
        print(f"❌ bess-dispatch sizing error: {e}")
        import traceback
        traceback.print_exc()
        return None


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
        "version": "2.1.0",
        "engine": "pvlib-python",
        "pvlib_available": PVLIB_AVAILABLE,
        "pvlib_version": PVLIB_VERSION,
        "features": ["pvgis_tmy", "analytical_year", "seasonality_bands"]
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "pvlib_available": PVLIB_AVAILABLE,
        "pvlib_version": PVLIB_VERSION
    }


@app.get("/optimization-progress")
async def optimization_progress_stream():
    """
    SSE endpoint for live progress updates during optimization.
    Returns Server-Sent Events with progress data.
    """
    async def event_generator():
        global optimization_progress
        last_percent = -1
        wait_count = 0
        max_wait = 100  # Max 30 seconds waiting for optimization to start

        # Wait for optimization to start (max 30 seconds)
        while not optimization_progress["active"] and wait_count < max_wait:
            await asyncio.sleep(0.3)
            wait_count += 1
            # Send waiting signal
            data = json.dumps({
                "active": False,
                "percent": 0,
                "step": "Oczekiwanie na optymalizację..."
            })
            yield f"data: {data}\n\n"

        # If optimization started, track progress
        if optimization_progress["active"]:
            while True:
                if optimization_progress["active"]:
                    if optimization_progress["percent"] != last_percent:
                        data = json.dumps({
                            "active": True,
                            "percent": optimization_progress["percent"],
                            "step": optimization_progress["step"],
                            "current_capacity": optimization_progress["current_capacity"],
                            "total_configs": optimization_progress["total_configs"],
                            "tested_configs": optimization_progress["tested_configs"]
                        })
                        yield f"data: {data}\n\n"
                        last_percent = optimization_progress["percent"]
                else:
                    # Optimization finished
                    data = json.dumps({
                        "active": False,
                        "percent": 100,
                        "step": "Zakończono"
                    })
                    yield f"data: {data}\n\n"
                    break

                await asyncio.sleep(0.2)  # Check every 200ms

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

class GenerateProfileRequest(BaseModel):
    """Request model for generate-profile endpoint with optional date range"""
    pv_config: PVConfiguration
    start_date: Optional[str] = None  # ISO format: "2024-01-01"
    end_date: Optional[str] = None  # ISO format: "2024-12-31"


@app.post("/generate-profile")
async def generate_profile(config: PVConfiguration, start_date: Optional[str] = None, end_date: Optional[str] = None):
    """
    Generate PV generation profile.

    Args:
        config: PV system configuration
        start_date: Optional start date (ISO format). If not provided, uses current year.
        end_date: Optional end date (ISO format). If not provided, uses full year from start.
    """
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

        # Generate timestamps based on provided dates or default to current year
        if start_date and end_date:
            start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            print(f"📅 Using provided date range: {start_date} to {end_date}")
        elif start_date:
            start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            end_dt = datetime(start_dt.year, 12, 31, 23, 0, 0)
            print(f"📅 Using start date with full year: {start_date} to {end_dt.strftime('%Y-%m-%d')}")
        else:
            # Default: current year (fallback for backward compatibility)
            year = datetime.now().year
            start_dt = datetime(year, 1, 1)
            end_dt = datetime(year, 12, 31, 23, 0, 0)
            print(f"📅 Using current year: {year}")

        times = pd.date_range(
            start=start_dt,
            end=end_dt,
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

        # Scale profile DOWN to match yield_target (only if target < actual)
        actual_yield = float(profile.sum())
        if config.yield_target > 0 and actual_yield > 0 and config.yield_target < actual_yield - 10:
            scale = config.yield_target / actual_yield
            profile = profile * scale
            print(f"   ⚡ Yield scaling DOWN: {actual_yield:.0f} → {config.yield_target:.0f} kWh/kWp (factor: {scale:.3f})")

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

        consumption = np.array(request.consumption)
        estimation_method = "none"

        # Process timestamps - extract from consumption data or generate
        if request.timestamps and len(request.timestamps) == len(request.consumption):
            timestamps = request.timestamps

            # Extract and validate date range from provided timestamps
            try:
                start_date, end_date, total_days = extract_date_range_from_timestamps(timestamps)

                # Validate and truncate if exceeds 1 year
                start_date, end_date, was_truncated = validate_and_adjust_date_range(start_date, end_date)

                if was_truncated:
                    # Truncate consumption data and timestamps to match
                    max_hours = 366 * 24  # Max hours for a leap year
                    timestamps = timestamps[:max_hours]
                    consumption = consumption[:max_hours]
                    print(f"   Truncated data to {len(timestamps)} hours")

                # Check if we need estimation for incomplete data (<11 months)
                parsed_times = pd.to_datetime(timestamps)
                months_covered = len(set([(d.year, d.month) for d in parsed_times]))

                if months_covered < 11 and total_days < 335:
                    print(f"📊 Incomplete data detected: {months_covered} months")
                    consumption, timestamps, estimation_method = estimate_annual_consumption(
                        consumption, timestamps
                    )

            except Exception as e:
                print(f"⚠️ Date extraction warning: {e}")
                # Continue with provided timestamps as-is

            print(f"Using {len(timestamps)} timestamps from consumption data")
        else:
            # No timestamps provided - generate based on consumption data length
            n_hours = len(request.consumption)

            # Determine if it's a leap year based on hours
            if n_hours == 8784:
                year = 2024  # Use a leap year reference
            elif n_hours == 8760:
                year = 2023  # Use a non-leap year reference
            else:
                # Partial data - use current year as reference
                year = datetime.now().year

            times = pd.date_range(
                start=f'{year}-01-01',
                periods=n_hours,
                freq='H',
                tz='Europe/Warsaw'
            )
            timestamps = [t.isoformat() for t in times]
            print(f"Generated {len(timestamps)} hourly timestamps for year {year} (no timestamps provided)")

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
                n_hours=len(consumption),
                latitude=config.latitude,
                tilt=tilt,
                azimuth=azimuth,
                pv_type=config.pv_type,
                yield_target=config.yield_target
            )

        # Scale profile DOWN to match yield_target (only if target < PVGIS yield)
        # This allows users to reduce yield to match PV SYST simulations.
        # Never scales UP — if PVGIS is already below target, soiling/physical losses are preserved.
        pvgis_yield = float(pv_profile.sum()) if hasattr(pv_profile, 'sum') else float(np.sum(pv_profile))
        yield_target = config.yield_target
        if yield_target > 0 and pvgis_yield > 0 and yield_target < pvgis_yield - 10:
            yield_scale = yield_target / pvgis_yield
            pv_profile = pv_profile * yield_scale
            print(f"   ⚡ Yield scaling DOWN: PVGIS {pvgis_yield:.0f} → target {yield_target:.0f} kWh/kWp (factor: {yield_scale:.3f})")
        else:
            print(f"   ✓ No downscaling needed: PVGIS {pvgis_yield:.0f} kWh/kWp, target {yield_target:.0f} kWh/kWp")

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

        # Check if BESS is enabled and determine mode
        bess_enabled = request.bess_config and request.bess_config.enabled
        bess_config = request.bess_config
        bess_mode = bess_config.mode if bess_config else 'off'
        bess_pro_result = None  # Will store PRO optimization result if applicable

        if bess_enabled:
            if bess_mode == 'pro':
                print(f"\n🚀 BESS PRO mode enabled (LP/MIP optimization)")
                print(f"   Solver: {bess_config.pro_config.solver if bess_config.pro_config else 'highs'}")
                print(f"   Objective: {bess_config.pro_config.objective if bess_config.pro_config else 'npv'}")
            else:
                print(f"\n🔋 BESS LIGHT mode enabled")
                print(f"   Duration: {bess_config.duration}")
            print(f"   Round-trip efficiency: {bess_config.roundtrip_efficiency:.0%}")

        # Run simulations for each capacity
        scenarios = []

        import time as _time
        _t_sweep_start = _time.time()

        # Build capacity array
        capacities_arr = np.arange(
            request.capacity_min,
            request.capacity_max + request.capacity_step * 0.5,
            request.capacity_step
        )
        n_scenarios = len(capacities_arr)
        print(f"\n📊 Running {n_scenarios} scenarios")
        print(f"   Capacity range: {request.capacity_min} - {request.capacity_max} kWp")
        print(f"   Thresholds: {request.thresholds}")
        print(f"   Consumption: sum={consumption.sum():.0f} kWh ({consumption.sum()/1000:.1f} MWh), len={len(consumption)}, min={consumption.min():.2f}, max={consumption.max():.2f}")
        print(f"   PV profile: sum={pv_profile.sum():.0f} kWh/kWp, max={pv_profile.max():.4f} kW/kWp")

        # Pre-compute DC/AC ratios for all capacities
        if dcac_mode == 'auto' and auto_dcac_ratio is not None:
            dcac_ratios_arr = np.full(n_scenarios, auto_dcac_ratio)
        else:
            dcac_ratios_arr = np.array([
                get_dcac_for_capacity(cap, config.dcac_tiers, config.dc_ac_ratio)
                for cap in capacities_arr
            ])

        if bess_enabled:
            # BESS path: sequential loop (SOC state depends on previous hour)
            for i, capacity in enumerate(capacities_arr):
                dcac_ratio = float(dcac_ratios_arr[i])

                # Main loop always uses LIGHT mode for speed
                # PRO optimization is applied only to key variants (A/B/C/D) after selection
                bess_power_kw, bess_energy_kwh = auto_size_bess_lite(
                    pv_profile=pv_profile,
                    consumption=consumption,
                    capacity=float(capacity),
                    dc_ac_ratio=dcac_ratio,
                    duration=str(bess_config.duration),
                    capex_per_kwh=bess_config.capex_per_kwh,
                    capex_per_kw=bess_config.capex_per_kw,
                    energy_price_plnmwh=request.pv_config.energy_price if hasattr(request.pv_config, 'energy_price') else 800.0,
                    discount_rate=request.pv_config.discount_rate if hasattr(request.pv_config, 'discount_rate') else 0.07,
                    lifetime_years=bess_config.lifetime_years,
                    roundtrip_efficiency=bess_config.roundtrip_efficiency
                )

                # Simulate PV+BESS in 0-export mode
                result = simulate_pv_system_with_bess(
                    capacity=float(capacity),
                    pv_profile=pv_profile,
                    consumption=consumption,
                    bess_power_kw=bess_power_kw,
                    bess_energy_kwh=bess_energy_kwh,
                    dc_ac_ratio=dcac_ratio,
                    roundtrip_efficiency=bess_config.roundtrip_efficiency,
                    soc_min=bess_config.soc_min,
                    soc_max=bess_config.soc_max,
                    soc_initial=bess_config.soc_initial
                )
                scenarios.append(result)
        else:
            # VECTORIZED path: all capacities in single NumPy operation
            scenarios = simulate_pv_system_batch(
                capacities=capacities_arr,
                dcac_ratios=dcac_ratios_arr,
                pv_profile=pv_profile,
                consumption=consumption,
            )

        _t_sweep_end = _time.time()
        print(f"   ⏱️ Capacity sweep: {_t_sweep_end - _t_sweep_start:.2f}s ({n_scenarios} scenarios, {'BESS sequential' if bess_enabled else 'vectorized'})")

        # Debug: print first, middle, and last scenario auto_consumption
        if scenarios:
            first = scenarios[0]
            last = scenarios[-1]
            mid = scenarios[len(scenarios)//2]
            print(f"\n🔍 DEBUG Scenario auto_consumption:")
            print(f"   First ({first.capacity:.0f} kWp): auto={first.auto_consumption_pct:.1f}%, prod={first.production:.0f} kWh, self={first.self_consumed:.0f} kWh, exported={first.exported:.0f} kWh")
            print(f"   Mid   ({mid.capacity:.0f} kWp): auto={mid.auto_consumption_pct:.1f}%, prod={mid.production:.0f} kWh, self={mid.self_consumed:.0f} kWh")
            print(f"   Last  ({last.capacity:.0f} kWp): auto={last.auto_consumption_pct:.1f}%, prod={last.production:.0f} kWh, self={last.self_consumed:.0f} kWh")
            # Count how many meet each threshold
            for thr_name, thr_val in request.thresholds.items():
                count = sum(1 for s in scenarios if s.auto_consumption_pct >= thr_val)
                print(f"   Threshold {thr_name} ({thr_val}%): {count}/{len(scenarios)} scenarios qualify")

        # Find key variants
        key_variants = {}

        for variant_name, threshold in request.thresholds.items():
            variant_scenario = find_variant(scenarios, threshold)

            if variant_scenario:
                # For BESS PRO mode: call bess-dispatch /sizing for full LP/MIP optimization
                bess_dispatch_result = None
                if bess_enabled and bess_mode == 'pro':
                    print(f"   🚀 bess-dispatch PRO optimization for variant {variant_name} ({variant_scenario.capacity:.0f} kWp)...")

                    # Prepare PV generation profile
                    pv_generation_kw = (pv_profile * variant_scenario.capacity / variant_scenario.dcac_ratio).tolist()

                    # Determine topology from settings
                    topology = getattr(bess_config, 'topology', 'pv_load')
                    if topology == 'load_only' or not any(pv_generation_kw):
                        topology = 'load_only'
                    else:
                        topology = 'pv_load'

                    # Build settings dict for bess-dispatch
                    # Note: opex_pct_per_year in bess_config is stored as percentage (e.g., 1.5 means 1.5%)
                    # bess-dispatch expects fraction (0.015), so divide by 100
                    opex_fraction = bess_config.opex_pct_per_year / 100.0 if bess_config.opex_pct_per_year > 0.1 else bess_config.opex_pct_per_year

                    # Debug: log incoming economic params from frontend
                    print(f"   💰 BESS Economic Params from frontend:")
                    print(f"      demand_charge_pln_kw_month: {getattr(bess_config, 'demand_charge_pln_kw_month', 0.0)}")
                    print(f"      peak_limit_kw: {getattr(bess_config, 'peak_limit_kw', None)}")
                    if bess_config.capacity_fee_config:
                        print(f"      capacity_fee_config: enabled={bess_config.capacity_fee_config.enabled}, som_rate={bess_config.capacity_fee_config.som_rate_pln_kw}")
                    else:
                        print(f"      capacity_fee_config: None (WILL USE DEFAULT!)")
                    if bess_config.tariff_config:
                        print(f"      tariff_config: type={bess_config.tariff_config.type}, day={bess_config.tariff_config.day_rate_pln_mwh}, night={bess_config.tariff_config.night_rate_pln_mwh}")
                    else:
                        print(f"      tariff_config: None (WILL USE DEFAULT!)")

                    bess_settings = {
                        'roundtrip_efficiency': bess_config.roundtrip_efficiency,
                        'soc_min': bess_config.soc_min,
                        'soc_max': bess_config.soc_max,
                        'capex_per_kwh': bess_config.capex_per_kwh,
                        'capex_per_kw': bess_config.capex_per_kw,
                        'opex_pct_per_year': opex_fraction,
                        'discount_rate': getattr(request.pv_config, 'discount_rate', 0.07),
                        'analysis_years': bess_config.lifetime_years,
                        'import_price_pln_mwh': getattr(request.pv_config, 'energy_price', 800.0),
                        'durations_h': [1.0, 2.0, 4.0],
                        # Demand charge for peak shaving savings
                        'demand_charge_pln_kw_month': getattr(bess_config, 'demand_charge_pln_kw_month', 0.0),
                        'peak_limit_kw': getattr(bess_config, 'peak_limit_kw', None),
                        # Dispatch mode from scenario
                        'dispatch_mode': getattr(bess_config, 'dispatch_mode', 'pv_surplus'),
                    }

                    # Add capacity fee configuration if enabled
                    if bess_config.capacity_fee_config and bess_config.capacity_fee_config.enabled:
                        bess_settings['capacity_fee'] = {
                            'enabled': True,
                            'som_rate_pln_kw': bess_config.capacity_fee_config.som_rate_pln_kw,
                            'qualification_period': bess_config.capacity_fee_config.qualification_period,
                            'peak_hours': bess_config.capacity_fee_config.peak_hours,
                        }
                        print(f"   📊 Capacity fee enabled: SOM={bess_config.capacity_fee_config.som_rate_pln_kw} PLN/kW/month")

                    # Add tariff configuration for ToU arbitrage
                    if bess_config.tariff_config and bess_config.tariff_config.type != 'flat':
                        tariff = bess_config.tariff_config
                        # Get fixed charges (opłaty stałe) - default 451 PLN/MWh
                        other_fees = tariff.other_fees_pln_mwh or 451.0
                        if tariff.type == 'two_zone':
                            day_rate = tariff.day_rate_pln_mwh or 800.0
                            night_rate = tariff.night_rate_pln_mwh or 400.0
                            # Calculate weighted average (same as BESS frontend: 60% day, 40% night)
                            avg_energia = day_rate * 0.6 + night_rate * 0.4
                            full_price = avg_energia + other_fees
                            bess_settings['prices'] = {
                                'type': 'two_zone',
                                'day_rate_pln_mwh': day_rate,
                                'night_rate_pln_mwh': night_rate,
                                'day_hours_start': tariff.day_hours_start,
                                'day_hours_end': tariff.day_hours_end,
                                'other_fees_pln_mwh': other_fees,  # Fixed charges on top of ToU rates
                            }
                            # Set import_price_pln_mwh to fullPrice for consistent calculations
                            bess_settings['import_price_pln_mwh'] = full_price
                            print(f"   📊 ToU tariff: day={day_rate} / night={night_rate} + other_fees={other_fees} = fullPrice={full_price} PLN/MWh")
                        elif tariff.type == 'three_zone':
                            peak_rate = tariff.peak_rate_pln_mwh or 1200.0
                            day_rate = tariff.day_rate_pln_mwh or 800.0
                            night_rate = tariff.night_rate_pln_mwh or 400.0
                            # Calculate weighted average (same as BESS frontend: 20% peak, 40% day, 40% night)
                            avg_energia = peak_rate * 0.2 + day_rate * 0.4 + night_rate * 0.4
                            full_price = avg_energia + other_fees
                            bess_settings['prices'] = {
                                'type': 'three_zone',
                                'peak_rate_pln_mwh': peak_rate,
                                'day_rate_pln_mwh': day_rate,
                                'night_rate_pln_mwh': night_rate,
                                'peak_hours': tariff.peak_hours or [7, 8, 9, 10, 11, 12, 13, 17, 18, 19, 20, 21],
                                'other_fees_pln_mwh': other_fees,  # Fixed charges on top of ToU rates
                            }
                            # Set import_price_pln_mwh to fullPrice for consistent calculations
                            bess_settings['import_price_pln_mwh'] = full_price
                            print(f"   📊 ToU tariff 3-zone: peak={peak_rate} / day={day_rate} / night={night_rate} + other_fees={other_fees} = fullPrice={full_price} PLN/MWh")

                    # Add PRO config constraints if available
                    if bess_config.pro_config:
                        bess_settings.update({
                            'min_power_kw': bess_config.pro_config.min_power_kw,
                            'max_power_kw': bess_config.pro_config.max_power_kw,
                            'min_energy_kwh': bess_config.pro_config.min_energy_kwh,
                            'max_energy_kwh': bess_config.pro_config.max_energy_kwh,
                        })

                    # Call bess-dispatch for precise sizing with savings_breakdown
                    bess_dispatch_result = call_bess_dispatch_sizing(
                        pv_generation_kw=pv_generation_kw,
                        load_kw=consumption.tolist(),
                        topology=topology,
                        bess_settings=bess_settings,
                        interval_minutes=60
                    )

                    if bess_dispatch_result and bess_dispatch_result.get('variants'):
                        # BUG FIX v7.1: Use recommended_power_kw/recommended_energy_kwh
                        # from bess-dispatch instead of variants[0] which is just the first
                        # tested variant, NOT the optimal one.
                        rec_power = bess_dispatch_result.get('recommended_power_kw', 0)
                        rec_energy = bess_dispatch_result.get('recommended_energy_kwh', 0)
                        rec_variant_name = bess_dispatch_result.get('recommended_variant')

                        # Find the recommended variant in the variants list
                        best_bess_variant = None
                        if rec_variant_name:
                            for v in bess_dispatch_result['variants']:
                                if v.get('variant') == rec_variant_name:
                                    best_bess_variant = v
                                    break
                        # Fallback: find variant closest to recommended sizing
                        if not best_bess_variant and rec_power > 0:
                            best_match = None
                            best_dist = float('inf')
                            for v in bess_dispatch_result['variants']:
                                dist = abs(v['power_kw'] - rec_power) + abs(v['energy_kwh'] - rec_energy)
                                if dist < best_dist:
                                    best_dist = dist
                                    best_match = v
                            best_bess_variant = best_match
                        # Final fallback: first variant
                        if not best_bess_variant:
                            best_bess_variant = bess_dispatch_result['variants'][0]

                        bess_power = best_bess_variant['power_kw']
                        bess_energy = best_bess_variant['energy_kwh']
                        print(f"   🎯 Recommended by bess-dispatch: {rec_power:.0f} kW / {rec_energy:.0f} kWh ({rec_variant_name})")
                        print(f"   ✅ Using variant: {bess_power:.0f} kW / {bess_energy:.0f} kWh")

                        # Re-simulate with bess-dispatch optimized sizing
                        variant_scenario = simulate_pv_system_with_bess(
                            capacity=variant_scenario.capacity,
                            pv_profile=pv_profile,
                            consumption=consumption,
                            bess_power_kw=bess_power,
                            bess_energy_kwh=bess_energy,
                            dc_ac_ratio=variant_scenario.dcac_ratio,
                            roundtrip_efficiency=bess_config.roundtrip_efficiency,
                            soc_min=bess_config.soc_min,
                            soc_max=bess_config.soc_max,
                            soc_initial=bess_config.soc_initial
                        )

                        # Store bess-dispatch result for savings_breakdown
                        variant_scenario._bess_dispatch_result = bess_dispatch_result
                        if best_bess_variant.get('savings_breakdown'):
                            sb = best_bess_variant['savings_breakdown']
                            print(f"   💰 Savings: {sb.get('net_savings_pln', 0):.0f} PLN/year")

                        # Override greedy BESS metrics with LP dispatch results
                        # The greedy simulate_pv_system_with_bess only does pv_surplus mode.
                        # For stacked/peak_shaving/arbitrage, LP dispatch data is authoritative.
                        ds = best_bess_variant.get('dispatch_summary', {})
                        if ds:
                            lp_charge = ds.get('total_charge_kwh', 0)
                            lp_discharge = ds.get('total_discharge_kwh', 0)
                            lp_grid_import = ds.get('total_grid_import_kwh')
                            lp_curtail = ds.get('total_curtailment_kwh')
                            lp_direct_pv = ds.get('total_direct_pv_kwh')
                            lp_self_consumption = ds.get('self_consumption_kwh')

                            if lp_charge > 0 or lp_discharge > 0:
                                variant_scenario.bess_charged_kwh = lp_charge
                                variant_scenario.bess_discharged_kwh = lp_discharge
                                variant_scenario.bess_self_consumed_from_bess_kwh = lp_discharge
                                if lp_grid_import is not None:
                                    variant_scenario.bess_grid_import_kwh = lp_grid_import
                                if lp_curtail is not None:
                                    variant_scenario.bess_curtailed_kwh = lp_curtail
                                if lp_direct_pv is not None:
                                    variant_scenario.bess_self_consumed_direct_kwh = lp_direct_pv

                                # Recalculate cycles
                                usable = bess_energy * (bess_config.soc_max - bess_config.soc_min)
                                if usable > 0:
                                    variant_scenario.bess_cycles_equivalent = (lp_charge + lp_discharge) / (2 * usable)

                                print(f"   📊 LP metrics override: charge={lp_charge:.0f}, discharge={lp_discharge:.0f}, "
                                      f"grid_import={lp_grid_import:.0f}, curtail={lp_curtail:.0f} kWh")

                # Calculate hourly production for this variant (AC output with clipping)
                # pv_profile is normalized per 1 kWp
                variant_pv_dc = pv_profile * variant_scenario.capacity  # DC production
                variant_ac_capacity = variant_scenario.capacity / variant_scenario.dcac_ratio  # AC limit
                variant_hourly_production = np.minimum(variant_pv_dc, variant_ac_capacity)  # AC with clipping

                variant_result = VariantResult(
                    variant=variant_name,
                    threshold=threshold,
                    capacity=variant_scenario.capacity,
                    dcac_ratio=variant_scenario.dcac_ratio,
                    production=variant_scenario.production,
                    self_consumed=variant_scenario.self_consumed,
                    exported=variant_scenario.exported,
                    auto_consumption_pct=variant_scenario.auto_consumption_pct,
                    coverage_pct=variant_scenario.coverage_pct,
                    meets_threshold=True,
                    hourly_production=variant_hourly_production.tolist()  # Include hourly data for Profile Analysis
                )

                # Add BESS fields if available
                if bess_enabled and variant_scenario.bess_power_kw is not None:
                    variant_result.bess_power_kw = variant_scenario.bess_power_kw
                    variant_result.bess_energy_kwh = variant_scenario.bess_energy_kwh
                    variant_result.bess_charged_kwh = variant_scenario.bess_charged_kwh
                    variant_result.bess_discharged_kwh = variant_scenario.bess_discharged_kwh
                    variant_result.bess_curtailed_kwh = variant_scenario.bess_curtailed_kwh
                    variant_result.bess_grid_import_kwh = variant_scenario.bess_grid_import_kwh
                    variant_result.bess_self_consumed_direct_kwh = variant_scenario.bess_self_consumed_direct_kwh
                    variant_result.bess_self_consumed_from_bess_kwh = variant_scenario.bess_self_consumed_from_bess_kwh
                    variant_result.bess_cycles_equivalent = variant_scenario.bess_cycles_equivalent
                    # Monthly breakdown (NEW in v3.2)
                    variant_result.bess_monthly_data = variant_scenario.bess_monthly_data
                    # SOC histogram (NEW in v3.2)
                    variant_result.bess_soc_histogram = variant_scenario.bess_soc_histogram

                    # Savings breakdown from bess-dispatch (PRO mode)
                    if hasattr(variant_scenario, '_bess_dispatch_result') and variant_scenario._bess_dispatch_result:
                        bess_result = variant_scenario._bess_dispatch_result
                        if bess_result.get('variants'):
                            best_variant = bess_result['variants'][0]  # Recommended variant
                            if best_variant.get('savings_breakdown'):
                                sb = best_variant['savings_breakdown']
                                variant_result.savings_breakdown = SavingsBreakdown(
                                    energy_savings_pln=sb.get('energy_savings_pln', 0.0),
                                    demand_charge_savings_pln=sb.get('demand_charge_savings_pln', 0.0),
                                    capacity_fee_savings_pln=sb.get('capacity_fee_savings_pln', 0.0),
                                    arbitrage_savings_pln=sb.get('arbitrage_savings_pln', 0.0),
                                    degradation_cost_pln=sb.get('degradation_cost_pln', 0.0),
                                    net_savings_pln=sb.get('net_savings_pln', 0.0),
                                    source="bess_dispatch_accurate"
                                )
                                print(f"      💰 Savings breakdown: {sb.get('net_savings_pln', 0):.0f} PLN/year (precise)")

                            # Dispatch metadata
                            if best_variant.get('dispatch_mode') or bess_result.get('topology'):
                                variant_result.dispatch_metadata = DispatchMetadata(
                                    dispatch_mode=best_variant.get('dispatch_mode', 'pv_surplus'),
                                    topology=bess_result.get('topology', 'pv_load'),
                                    peak_shaving_enabled=best_variant.get('peak_shaving_enabled', False),
                                    peak_limit_kw=best_variant.get('peak_limit_kw')
                                )

                    # DEBUG: Check if monthly data exists
                    monthly_count = len(variant_scenario.bess_monthly_data) if variant_scenario.bess_monthly_data else 0
                    soc_exists = "YES" if variant_scenario.bess_soc_histogram else "NO"
                    print(f"      📊 Monthly data: {monthly_count} months, SOC histogram: {soc_exists}")

                    # Compute baseline (no BESS) for comparison
                    baseline_result = simulate_pv_system(
                        capacity=variant_scenario.capacity,
                        pv_profile=pv_profile,
                        consumption=consumption,
                        dc_ac_ratio=variant_scenario.dcac_ratio
                    )
                    variant_result.baseline_no_bess = BaselineMetrics(
                        production=baseline_result.production,
                        self_consumed=baseline_result.self_consumed,
                        exported=baseline_result.exported,
                        auto_consumption_pct=baseline_result.auto_consumption_pct,
                        coverage_pct=baseline_result.coverage_pct
                    )

                # =====================================================================
                # K-class Capacity Fee Scenarios (v3.0)
                # Calculate opłata mocowa for: baseline, PV only, PV+BESS
                # =====================================================================
                try:
                    # consumption is the original load profile (hourly kWh)
                    load_list = consumption.tolist() if hasattr(consumption, 'tolist') else list(consumption)
                    pv_list = variant_hourly_production.tolist() if variant_hourly_production is not None else None

                    # Extract BESS hourly profiles from bess-dispatch response
                    bess_charge_from_grid = None
                    bess_discharge = None
                    if hasattr(variant_scenario, '_bess_dispatch_result') and variant_scenario._bess_dispatch_result:
                        bdr = variant_scenario._bess_dispatch_result
                        if bdr.get('variants'):
                            # Find recommended variant's dispatch_summary
                            rec_name = bdr.get('recommended_variant')
                            best_v = None
                            for v in bdr['variants']:
                                if v.get('variant') == rec_name:
                                    best_v = v
                                    break
                            if not best_v:
                                best_v = bdr['variants'][0]

                            # Get hourly profiles from variant-level (populated by include_hourly_profiles)
                            bess_charge_from_grid = best_v.get('hourly_charge_from_grid_kw')
                            bess_discharge = best_v.get('hourly_discharge_kw')

                            # Fallback: try dispatch_summary
                            if not bess_discharge and best_v.get('dispatch_summary'):
                                ds = best_v['dispatch_summary']
                                bess_discharge = ds.get('hourly_discharge_kw')
                                if not bess_charge_from_grid:
                                    bess_charge_from_grid = ds.get('hourly_charge_from_grid_kw')

                    # Determine start date from timestamps
                    data_start_date = None
                    start_year = 2026
                    if timestamps is not None and len(timestamps) > 0:
                        ts0 = pd.to_datetime(timestamps[0])
                        data_start_date = ts0.strftime('%Y-%m-%d')
                        start_year = ts0.year

                    kclass_result = call_capacity_fee_scenarios(
                        load_kwh=load_list,
                        pv_kwh=pv_list,
                        bess_charge_from_grid_kwh=bess_charge_from_grid,
                        bess_discharge_kwh=bess_discharge,
                        data_start_date=data_start_date,
                        start_year=start_year,
                    )

                    if kclass_result:
                        bl = kclass_result.get('baseline', {})
                        variant_result.capacity_fee_baseline_pln = bl.get('annual_fee_pln', 0)
                        variant_result.k_class_baseline = bl.get('k_class', 'K4')

                        pv_sc = kclass_result.get('with_pv')
                        if pv_sc:
                            variant_result.capacity_fee_with_pv_pln = pv_sc.get('annual_fee_pln', 0)
                            variant_result.k_class_with_pv = pv_sc.get('k_class', 'K4')

                        pv_bess_sc = kclass_result.get('with_pv_bess')
                        if pv_bess_sc:
                            variant_result.capacity_fee_with_pv_bess_pln = pv_bess_sc.get('annual_fee_pln', 0)
                            variant_result.k_class_with_pv_bess = pv_bess_sc.get('k_class', 'K4')

                        variant_result.capacity_fee_savings_pv_pln = kclass_result.get('savings_pv_only_pln', 0)
                        variant_result.capacity_fee_savings_bess_pln = kclass_result.get('savings_bess_incremental_pln', 0)
                        variant_result.capacity_fee_savings_total_pln = kclass_result.get('savings_pv_bess_pln', 0)

                        print(f"      📊 K-class: {variant_result.k_class_baseline} → {variant_result.k_class_with_pv} → {variant_result.k_class_with_pv_bess}")
                        print(f"         Savings: PV={variant_result.capacity_fee_savings_pv_pln:.0f}, BESS={variant_result.capacity_fee_savings_bess_pln:.0f}, Total={variant_result.capacity_fee_savings_total_pln:.0f} PLN")
                except Exception as e:
                    print(f"      ⚠️ K-class calculation failed: {e}")
                    import traceback
                    traceback.print_exc()

                key_variants[variant_name] = variant_result

                # Print variant info
                if bess_enabled and variant_scenario.bess_power_kw:
                    baseline_auto = variant_result.baseline_no_bess.auto_consumption_pct if variant_result.baseline_no_bess else 0
                    auto_increase = variant_scenario.auto_consumption_pct - baseline_auto
                    print(f"   Variant {variant_name} ({threshold}%): {variant_scenario.capacity:.0f} kWp + {variant_scenario.bess_power_kw:.0f}kW/{variant_scenario.bess_energy_kwh:.0f}kWh BESS")
                    print(f"      Auto-consumption: {baseline_auto:.1f}% -> {variant_scenario.auto_consumption_pct:.1f}% (+{auto_increase:.1f}%)")
                else:
                    print(f"   Variant {variant_name} ({threshold}%): {variant_scenario.capacity:.0f} kWp, auto={variant_scenario.auto_consumption_pct:.1f}%")

        # Extract date range for response
        parsed_timestamps = pd.to_datetime(timestamps)
        date_start = parsed_timestamps.min().strftime('%Y-%m-%d')
        date_end = parsed_timestamps.max().strftime('%Y-%m-%d')

        print(f"\n✅ Analysis complete: {len(scenarios)} scenarios, {len(key_variants)} variants")
        print(f"   Date range: {date_start} to {date_end}")
        print(f"   Estimation method: {estimation_method}")
        if bess_enabled:
            print(f"   BESS mode: {bess_mode.upper()}")
        print(f"{'='*60}\n")

        # Build BESS summary if enabled
        bess_summary = None
        if bess_enabled and scenarios:
            # Find best scenario (highest autoconsumption that meets threshold)
            # Use the 70% variant if available, otherwise the best scenario
            best_scenario = None
            if 'variant_70' in key_variants:
                # Find matching scenario
                target_cap = key_variants['variant_70'].capacity
                for s in scenarios:
                    if s.capacity == target_cap:
                        best_scenario = s
                        break
            if not best_scenario:
                # Use scenario with highest autoconsumption
                best_scenario = max(scenarios, key=lambda s: s.auto_consumption_pct)

            if best_scenario and best_scenario.bess_power_kw is not None:
                total_consumption = consumption.sum()

                # Get savings_breakdown from variant_70 (or best variant with bess-dispatch data)
                variant_savings_breakdown = None
                variant_dispatch_metadata = None
                variant_npv = 0.0
                variant_annual_savings = 0.0

                for vname in ['variant_70', 'variant_80', 'variant_60', 'variant_90']:
                    if vname in key_variants:
                        vr = key_variants[vname]
                        if vr.savings_breakdown:
                            variant_savings_breakdown = vr.savings_breakdown
                            variant_annual_savings = vr.savings_breakdown.net_savings_pln
                            break
                        if vr.dispatch_metadata:
                            variant_dispatch_metadata = vr.dispatch_metadata

                bess_summary = BESSSummary(
                    enabled=True,
                    mode='pro',  # Always PRO - uses bess-dispatch full solver
                    duration_selected='optimized',
                    power_kw=best_scenario.bess_power_kw,
                    energy_kwh=best_scenario.bess_energy_kwh,
                    annual_charged_kwh=best_scenario.bess_charged_kwh,
                    annual_discharged_kwh=best_scenario.bess_discharged_kwh,
                    annual_curtailed_kwh=best_scenario.bess_curtailed_kwh,
                    annual_grid_import_kwh=best_scenario.bess_grid_import_kwh,
                    cycles_equivalent=best_scenario.bess_cycles_equivalent,
                    annual_savings_pln=variant_annual_savings,
                    savings_breakdown=variant_savings_breakdown,
                    dispatch_metadata=variant_dispatch_metadata,
                    schema_version="bess_economics_v2"
                )
                print(f"   BESS Summary: {best_scenario.bess_power_kw:.0f} kW / {best_scenario.bess_energy_kwh:.0f} kWh")
                print(f"   Charged: {best_scenario.bess_charged_kwh:.0f} kWh, Discharged: {best_scenario.bess_discharged_kwh:.0f} kWh")
                print(f"   Curtailed: {best_scenario.bess_curtailed_kwh:.0f} kWh, Grid Import: {best_scenario.bess_grid_import_kwh:.0f} kWh")
                if variant_savings_breakdown:
                    print(f"   💰 Annual savings: {variant_annual_savings:.0f} PLN (precise from bess-dispatch)")

        return AnalysisResult(
            scenarios=scenarios,
            key_variants=key_variants,
            pv_profile=pv_profile.tolist(),
            pvlib_version=PVLIB_VERSION,
            date_range_start=date_start,
            date_range_end=date_end,
            estimation_method=estimation_method,
            data_hours=len(timestamps),
            bess_summary=bess_summary
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/optimize-seasonality", response_model=SeasonalityOptimizationResult)
async def optimize_seasonality(request: SeasonalityOptimizationRequest):
    """
    Optymalizacja doboru mocy PV z uwzględnieniem pasm sezonowości.

    Strategia PASMA_SEZONOWOŚĆ:
    - Wykrywa okresy wysokiego/niskiego zużycia (High/Mid/Low)
    - Dobiera moc instalacji PV i limity AC dla każdego pasma
    - Tryb MAX_AUTOCONSUMPTION: maksymalizuje autokonsumpcję przy 0-export
    - Tryb MAX_NPV: maksymalizuje NPV dla modelu EaaS

    Wymaga wcześniejszego wywołania /seasonality w data-analysis.
    """
    try:
        config = request.pv_config

        # Konfiguracja paneli
        if config.pv_type == "ground_s":
            tilt = config.tilt if config.tilt else config.latitude
            azimuth = config.azimuth if config.azimuth else 180
        elif config.pv_type == "roof_ew":
            tilt = config.tilt if config.tilt else 10
            azimuth = config.azimuth if config.azimuth else 90
        else:
            tilt = config.tilt if config.tilt else 15
            azimuth = config.azimuth if config.azimuth else 90

        print(f"\n{'='*60}")
        print(f"🌞 PASMA_SEZONOWOŚĆ Optimization")
        print(f"   Mode: {request.mode}")
        print(f"   Capacity range: {request.capacity_min} - {request.capacity_max} kWp")
        print(f"{'='*60}")

        consumption = np.array(request.consumption)
        timestamps = request.timestamps

        # Pobierz dane PVGIS TMY
        pvgis_data = None
        if PVLIB_AVAILABLE:
            pvgis_data = fetch_pvgis_tmy_data(config.latitude, config.longitude)

        # Generuj profil PV
        if PVLIB_AVAILABLE and pvgis_data:
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
        elif PVLIB_AVAILABLE:
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
            pv_profile = generate_pv_profile_fallback(
                n_hours=len(consumption),
                latitude=config.latitude,
                tilt=tilt,
                azimuth=azimuth,
                pv_type=config.pv_type,
                yield_target=config.yield_target
            )

        # Scale profile DOWN to match yield_target (only if target < actual yield)
        pvgis_yield_band = float(pv_profile.sum()) if hasattr(pv_profile, 'sum') else float(np.sum(pv_profile))
        yield_target_band = config.yield_target
        if yield_target_band > 0 and pvgis_yield_band > 0 and yield_target_band < pvgis_yield_band - 10:
            yield_scale_band = yield_target_band / pvgis_yield_band
            pv_profile = pv_profile * yield_scale_band
            print(f"   ⚡ Yield scaling DOWN: {pvgis_yield_band:.0f} → target {yield_target_band:.0f} kWh/kWp (factor: {yield_scale_band:.3f})")
        else:
            print(f"   ✓ No downscaling needed: actual {pvgis_yield_band:.0f} kWh/kWp, target {yield_target_band:.0f} kWh/kWp")

        # Uruchom optymalizację w osobnym wątku (pozwala SSE działać równolegle)
        target_seasons = request.target_seasons if request.target_seasons else ["High", "Mid"]
        autoconsumption_thresholds = request.autoconsumption_thresholds
        print(f"   Target seasons: {target_seasons}")
        print(f"   Autoconsumption thresholds: {autoconsumption_thresholds}")

        result = await asyncio.to_thread(
            optimize_seasonality_bands,
            pv_config=config,
            consumption=consumption,
            timestamps=timestamps,
            pv_profile=pv_profile,
            monthly_bands=request.monthly_bands,
            capacity_min=request.capacity_min,
            capacity_max=request.capacity_max,
            capacity_step=request.capacity_step,
            capex_per_kwp=request.capex_per_kwp,
            opex_per_kwp_year=request.opex_per_kwp_year,
            energy_price_esco=request.energy_price_esco,
            discount_rate=request.discount_rate,
            project_years=request.project_years,
            mode=request.mode,
            target_seasons=target_seasons,
            autoconsumption_thresholds=autoconsumption_thresholds
        )

        print(f"\n✅ Optimization complete")
        print(f"   Best capacity: {result.best_capacity_kwp:.0f} kWp")
        print(f"   Autoconsumption: {result.autoconsumption_pct:.1f}%")
        if result.npv:
            print(f"   NPV: {result.npv:.0f} PLN")
        print(f"{'='*60}\n")

        return result

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))


# ============== Main ==============
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)

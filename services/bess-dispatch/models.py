"""
BESS Dispatch Models
====================
Data Transfer Objects for BESS dispatch simulation and sizing.

Supports:
- 15-min and 60-min intervals
- PV-surplus (autokonsumpcja) mode
- Peak shaving mode
- STACKED mode (PV + Peak with SOC reserve)
- ToU Arbitrage integration (price-driven dispatch)
- Degradation metrics (throughput, EFC, budget)
- Time-varying prices with OSD tariffs
- Audit metadata for reproducibility

Version: 1.3.0
"""

from enum import Enum
from typing import List, Optional, Dict, Any, Union, Tuple
from pydantic import BaseModel, Field, validator, model_validator

# Engine version for audit trail
ENGINE_VERSION = "1.3.0"


class TimeResolution(str, Enum):
    """Supported time resolutions"""
    HOURLY = "hourly"           # 60-min intervals
    QUARTER_HOURLY = "15min"    # 15-min intervals


class ProfileUnit(str, Enum):
    """
    Units for input power profiles.

    All profiles should be in kW_avg (average power over interval).
    This enum enables explicit declaration and validation.
    """
    KW_AVG = "kW_avg"           # Average power over interval (standard)
    KW_PEAK = "kW_peak"         # Peak power in interval (requires conversion)
    KWH = "kWh"                 # Energy per interval (requires conversion based on dt)


class DispatchMode(str, Enum):
    """BESS dispatch modes"""
    PV_SURPLUS = "pv_surplus"           # Autokonsumpcja only
    PEAK_SHAVING = "peak_shaving"       # Peak shaving only
    STACKED = "stacked"                 # PV + Peak (dual-service)
    ARBITRAGE = "arbitrage"             # Price arbitrage only (requires time-varying prices)
    LOAD_ONLY = "load_only"             # Stand-alone BESS without PV (peak shaving focus)


class ArbitrageStrategy(str, Enum):
    """
    Arbitrage strategy for price-driven dispatch.

    Determines how charge/discharge thresholds are calculated.
    """
    PERCENTILE_THRESHOLD = "percentile"  # Charge below P25, discharge above P75
    ZONE_BASED = "zone_based"            # Charge in zone II/III, discharge in zone I
    SPREAD_THRESHOLD = "spread"          # Require minimum spread before acting


class TopologyType(str, Enum):
    """
    System topology - defines which components are present.

    Used to validate input profiles and select appropriate algorithms.
    """
    PV_LOAD = "pv_load"                 # Standard: PV + Load + BESS
    LOAD_ONLY = "load_only"             # No PV: Load + BESS only (grid arbitrage/peak shaving)


class DegradationStatus(str, Enum):
    """Degradation budget status"""
    OK = "ok"
    WARNING = "warning"
    EXCEEDED = "exceeded"


class SolverType(str, Enum):
    """Dispatch solver algorithm (v7.0.0: LP only)"""
    LP = "lp"             # Linear programming with rolling horizon


class LPSolverParams(BaseModel):
    """Configuration for LP solver"""
    forecast_hours: int = Field(
        34, ge=2, le=168,
        description="Rolling horizon forecast window [hours]. Default 34h (Galileo-proven)."
    )
    keep_hours: int = Field(
        24, ge=1, le=168,
        description="Rolling horizon keep window [hours]. Default 24h."
    )
    time_limit_seconds: float = Field(
        30.0, ge=1.0, le=300.0,
        description="Time limit per LP window solve [seconds]."
    )


# =============================================================================
# ANALYTICAL PERIOD - Time Axis Definition
# =============================================================================

class AnalyticalPeriodConfig(BaseModel):
    """
    Time axis definition for analysis.

    This is the SINGLE SOURCE OF TRUTH for time-related calculations.
    All modules must use this instead of hardcoded 8760/365 or date(year, 1, 1).

    The time axis is defined by:
    - start_datetime: When the analysis period begins
    - interval_minutes: Data resolution (15 or 60)
    - n_points: Number of data points (determines period length)

    The end_datetime is calculated as: start + (n_points - 1) * interval

    Usage:
    - ToU pricing: Use time_index derived from this for zone lookup
    - Capacity fee: Use time_index for working day determination
    - Daily metrics: Use groupby(date) on time_index, NOT hardcoded 365 days
    """
    start_datetime: str = Field(
        ...,
        description="Analysis start datetime (ISO 8601: YYYY-MM-DDTHH:MM:SS)"
    )
    interval_minutes: int = Field(
        60,
        ge=15, le=60,
        description="Time resolution: 15 or 60 minutes"
    )
    n_points: int = Field(
        ...,
        ge=1,
        description="Number of data points (determines period length)"
    )
    timezone: str = Field(
        "Europe/Warsaw",
        description="Timezone for ToU/capacity fee calculations"
    )
    clock_mode: str = Field(
        "CET_FIXED",
        description="Clock mode: CET_FIXED (ignore DST) or LOCAL_TZ (honor DST)"
    )

    # Optional: raw timestamps for irregular data or DST handling
    timestamps: Optional[List[str]] = Field(
        None,
        description="If provided, use these timestamps 1:1 instead of generating from start_datetime"
    )

    @property
    def period_hours(self) -> float:
        """Total hours in analysis period"""
        return (self.n_points * self.interval_minutes) / 60

    @property
    def period_days(self) -> float:
        """Total days in analysis period"""
        return self.period_hours / 24

    @property
    def is_full_year(self) -> bool:
        """True if period covers at least one full year (8760 hours)"""
        return self.period_hours >= 8760

    @property
    def annualization_factor(self) -> float:
        """Factor to scale period values to annual (8760 / period_hours)"""
        return 1.0 if self.is_full_year else (8760 / self.period_hours)

    @property
    def end_datetime(self) -> str:
        """Calculate end datetime from start + n_points * interval"""
        from datetime import datetime, timedelta
        start = datetime.fromisoformat(self.start_datetime)
        end = start + timedelta(minutes=(self.n_points - 1) * self.interval_minutes)
        return end.isoformat()


class PeriodInfo(BaseModel):
    """
    Period information included in responses.

    Helps UI understand whether results are for a full year or partial period,
    and whether annualization was applied.

    New fields (v0.3.3):
    - steps: number of time steps in analysis
    - step_minutes: time resolution (15 or 60)
    - timezone: timezone string (e.g., "Europe/Warsaw")
    """
    # Core period info
    period_hours: float = Field(..., description="Total hours in analysis period")
    period_days: float = Field(..., description="Total days in analysis period")
    is_full_year: bool = Field(..., description="True if period >= 8760 hours")
    annualization_factor: float = Field(
        ...,
        description="8760 / period_hours. Use to scale to annual if needed."
    )
    start_datetime: str = Field(..., description="Analysis start (ISO 8601)")
    end_datetime: str = Field(..., description="Analysis end (ISO 8601)")

    # Extended fields (v0.3.3)
    steps: Optional[int] = Field(None, description="Number of time steps")
    step_minutes: Optional[int] = Field(None, description="Time resolution in minutes (15 or 60)")
    timezone: Optional[str] = Field(None, description="Timezone (e.g., 'Europe/Warsaw')")


# =============================================================================
# Battery Parameters
# =============================================================================

class BatteryParams(BaseModel):
    """Core battery parameters"""
    power_kw: float = Field(..., gt=0, description="Nominal power [kW]")
    energy_kwh: float = Field(..., gt=0, description="Nominal capacity [kWh]")
    eta_charge: float = Field(0.9487, ge=0.7, le=1.0, description="Charging efficiency (one-way)")
    eta_discharge: float = Field(0.9487, ge=0.7, le=1.0, description="Discharging efficiency (one-way)")
    soc_min: float = Field(0.10, ge=0.0, le=0.5, description="Minimum SOC [0-1]")
    soc_max: float = Field(0.90, ge=0.5, le=1.0, description="Maximum SOC [0-1]")
    soc_initial: float = Field(0.50, ge=0.0, le=1.0, description="Initial SOC [0-1]")

    @property
    def usable_dod(self) -> float:
        """Usable depth of discharge"""
        return self.soc_max - self.soc_min

    @property
    def usable_capacity_kwh(self) -> float:
        """Usable capacity [kWh]"""
        return self.energy_kwh * self.usable_dod

    @property
    def c_rate(self) -> float:
        """C-rate (power/capacity ratio)"""
        return self.power_kw / self.energy_kwh if self.energy_kwh > 0 else 0

    @property
    def roundtrip_efficiency(self) -> float:
        """Round-trip efficiency"""
        return self.eta_charge * self.eta_discharge

    @classmethod
    def from_roundtrip(cls, power_kw: float, energy_kwh: float,
                       roundtrip_eff: float = 0.90, **kwargs) -> "BatteryParams":
        """Create from roundtrip efficiency (splits evenly)"""
        one_way = roundtrip_eff ** 0.5
        return cls(
            power_kw=power_kw,
            energy_kwh=energy_kwh,
            eta_charge=one_way,
            eta_discharge=one_way,
            **kwargs
        )


class StackedModeParams(BaseModel):
    """Parameters for STACKED (PV+Peak) mode"""
    peak_limit_kw: float = Field(..., gt=0, description="Grid import limit [kW]")
    reserve_fraction: float = Field(0.3, ge=0.0, le=0.8,
                                    description="SOC fraction reserved for peak shaving [0-1]")
    allow_reserve_breach: bool = Field(False,
                                       description="Allow using reserve in emergency (with warning)")


# =============================================================================
# STACKED DECOMPOSITION MODELS - Separate Peak Shaving & Arbitrage Components
# =============================================================================

class StackedComponentModel(BaseModel):
    """
    Single component of Stacked BESS sizing (Peak Shaving or Arbitrage).

    This model represents one "service" that the BESS provides in Stacked mode.
    The total BESS size is the SUM of all components.
    """
    name: str = Field(..., description="Component name: 'peak_shaving' or 'arbitrage'")
    power_kw: float = Field(..., ge=0, description="Required power for this service [kW]")
    energy_kwh: float = Field(..., ge=0, description="Required energy capacity for this service [kWh]")
    duration_h: float = Field(..., ge=0, description="Effective duration for this component [h]")
    capex_pln: float = Field(..., ge=0, description="CAPEX for this component [PLN]")
    annual_savings_pln: float = Field(..., description="Annual savings from this service [PLN/rok]")
    npv_pln: float = Field(..., description="NPV for this component standalone [PLN]")
    description: str = Field(..., description="Human-readable description of sizing rationale")


class StackedDecompositionModel(BaseModel):
    """
    Full decomposition of Stacked BESS into Peak Shaving and Arbitrage components.

    KEY INSIGHT: For Stacked mode, BESS should be sized as SUM of services, not MAX.
    This allows full utilization of both Peak Shaving (demand charge reduction) and
    Arbitrage (ToU spread + PV surplus shifting).

    Formula:
        Total BESS = Peak Shaving component + Arbitrage component

    Example:
        Peak Shaving: 40 kW / 80 kWh (for demand charge reduction)
        Arbitrage: 60 kW / 240 kWh (for ToU spread exploitation)
        TOTAL: 100 kW / 320 kWh
    """
    peak_shaving: StackedComponentModel = Field(
        ..., description="Peak Shaving component - sized to reduce demand charges"
    )
    arbitrage: StackedComponentModel = Field(
        ..., description="Arbitrage component - sized for ToU spread + PV surplus shifting"
    )

    # Combined totals
    total_power_kw: float = Field(..., ge=0, description="Total power = peak + arbitrage [kW]")
    total_energy_kwh: float = Field(..., ge=0, description="Total energy = peak + arbitrage [kWh]")
    total_capex_pln: float = Field(..., ge=0, description="Total CAPEX [PLN]")
    total_annual_savings_pln: float = Field(..., description="Total annual savings [PLN/rok]")
    total_npv_pln: float = Field(..., description="Combined NPV (with shared OPEX) [PLN]")

    # Sizing rationale
    sizing_rationale: str = Field(
        ...,
        description="Human-readable explanation of how BESS size was determined"
    )

    @property
    def peak_fraction(self) -> float:
        """Fraction of total power dedicated to peak shaving"""
        if self.total_power_kw > 0:
            return self.peak_shaving.power_kw / self.total_power_kw
        return 0.0

    @property
    def arbitrage_fraction(self) -> float:
        """Fraction of total power dedicated to arbitrage"""
        if self.total_power_kw > 0:
            return self.arbitrage.power_kw / self.total_power_kw
        return 0.0


class DegradationBudget(BaseModel):
    """Degradation budget constraints for battery lifecycle management.

    Supports both annual and daily limits to control battery wear.
    Daily limits are enforced in real-time during dispatch.
    Annual limits are checked post-dispatch for reporting.
    """
    # Annual limits (checked post-dispatch)
    max_efc_per_year: Optional[float] = Field(None, ge=0,
                                               description="Max equivalent full cycles per year")
    max_throughput_mwh_per_year: Optional[float] = Field(None, ge=0,
                                                          description="Max throughput MWh per year")

    # Daily limits (enforced during dispatch)
    max_cycles_per_day: Optional[float] = Field(
        None, ge=0, le=10,
        description="Max EFC cycles per day. Enforced in real-time during dispatch."
    )
    max_throughput_mwh_per_day: Optional[float] = Field(
        None, ge=0,
        description="Max throughput per day [MWh]. Enforced in real-time during dispatch."
    )

    def has_limits(self) -> bool:
        """Check if any limits are set"""
        return (
            self.max_efc_per_year is not None or
            self.max_throughput_mwh_per_year is not None or
            self.max_cycles_per_day is not None or
            self.max_throughput_mwh_per_day is not None
        )

    def has_daily_limits(self) -> bool:
        """Check if daily limits are set (enforced during dispatch)"""
        return self.max_cycles_per_day is not None or self.max_throughput_mwh_per_day is not None


# =============================================================================
# Arbitrage Configuration
# =============================================================================

class ArbitrageConfig(BaseModel):
    """
    Configuration for Time-of-Use (ToU) arbitrage dispatch.

    Arbitrage exploits price differences between tariff zones:
    - Charge from grid when price is low (below threshold)
    - Discharge when price is high (above threshold)

    IMPORTANT: For NPV calculations, capacity fee (opłata mocowa) is NOT
    included in price thresholds. It's calculated post-dispatch using
    the capacity_fee_pl module based on the actual import profile.

    Integration with STACKED mode:
    - Peak shaving has priority 1 (can use full SOC range)
    - PV surplus charging has priority 2 (always before grid charging)
    - Arbitrage grid-charge has priority 3 (only if spare charging capacity)
    - Arbitrage discharge has priority 4 (when price high and SOC > floor)
    """
    enabled: bool = Field(False, description="Enable ToU arbitrage in dispatch")

    # Grid charging control
    allow_grid_charging: bool = Field(
        True,
        description="Allow charging battery from grid for arbitrage. "
                    "If False, only PV surplus can charge battery."
    )

    # Tariff selection (must match osd_tariffs/presets keys)
    tariff_id: str = Field(
        "pge_c12a_2025",
        description="OSD tariff preset ID (from /osd-tariffs/presets)"
    )

    # Strategy
    strategy: ArbitrageStrategy = Field(
        ArbitrageStrategy.PERCENTILE_THRESHOLD,
        description="How to calculate charge/discharge thresholds"
    )

    # Percentile thresholds (for PERCENTILE_THRESHOLD strategy)
    charge_below_percentile: float = Field(
        25.0,
        ge=0,
        le=50,
        description="Charge from grid when price below this percentile [%]"
    )
    discharge_above_percentile: float = Field(
        75.0,
        ge=50,
        le=100,
        description="Discharge when price above this percentile [%]"
    )

    # Minimum spread for profitability (accounts for efficiency + degradation)
    min_spread_pln_kwh: float = Field(
        0.10,
        ge=0,
        description="Minimum price spread to act [PLN/kWh]"
    )

    # SOC floor for arbitrage discharge
    # Arbitrage cannot discharge below max(reserve_soc, arb_soc_min, soc_min)
    arbitrage_soc_min: float = Field(
        0.20,
        ge=0.0,
        le=0.5,
        description="Minimum SOC for arbitrage discharge [0-1]"
    )

    # Grid charging limits
    max_grid_charge_kw: Optional[float] = Field(
        None,
        description="Maximum power for grid charging [kW]. None = use battery power."
    )

    # Cycle limits for degradation management
    max_cycles_per_day: Optional[float] = Field(
        None,
        ge=0,
        le=10,
        description="Maximum EFC cycles per day for arbitrage. None = no limit."
    )
    max_throughput_mwh_per_day: Optional[float] = Field(
        None,
        ge=0,
        description="Maximum throughput per day [MWh]. None = no limit."
    )

    # Degradation cost for profitability calculation
    degradation_cost_pln_kwh: float = Field(
        0.05,
        ge=0,
        description="Degradation cost per kWh throughput [PLN/kWh]"
    )

    # RDN hourly prices (passed from frontend "Ceny RDN" widget)
    # When provided, these are used directly instead of looking up OSD tariff presets
    hourly_prices_pln_mwh: Optional[List[float]] = Field(
        None,
        description="Hourly RDN prices [PLN/MWh] from Ceny RDN widget (8760 values). "
                    "When provided, used directly for arbitrage dispatch."
    )

    # Price components to include in import_total (for dispatch steering)
    # NOTE: capacity_fee should be 0 here - it's calculated post-dispatch!
    capacity_fee_pln_kwh: float = Field(
        0.0,
        ge=0,
        description="Capacity fee in steering prices [PLN/kWh]. Keep 0 for accurate NPV."
    )
    other_components_pln_kwh: float = Field(
        0.0,
        ge=0,
        description="Other components (akcyza, OZE, etc.) [PLN/kWh]"
    )

    @model_validator(mode='after')
    def validate_arbitrage_config(self) -> 'ArbitrageConfig':
        """Validate arbitrage configuration consistency."""
        warnings = []

        # Warn if enabled but allow_grid_charging is False
        if self.enabled and not self.allow_grid_charging:
            warnings.append(
                "Arbitrage enabled but allow_grid_charging=False. "
                "Only PV surplus can be used for charging - limited arbitrage potential."
            )

        # Warn if spread is too small (unlikely profitable)
        min_profitable_spread = 0.05  # 50 PLN/MWh minimum
        if self.enabled and self.min_spread_pln_kwh < min_profitable_spread:
            warnings.append(
                f"min_spread_pln_kwh={self.min_spread_pln_kwh} is very low. "
                f"Consider at least {min_profitable_spread} PLN/kWh for profitability."
            )

        # Store warnings (for potential response inclusion)
        object.__setattr__(self, '_validation_warnings', warnings)
        return self


# =============================================================================
# Cable Pooling
# =============================================================================

class CablePoolingProfile(BaseModel):
    """
    Additional PV/load profile for cable pooling configuration.

    Cable pooling aggregates multiple generation and consumption profiles
    behind a single grid connection point. The BESS optimizes for the
    combined (summed) net load.
    """
    label: str = Field(..., description="Profile label (e.g., 'PV Roof East', 'EV Charger')")
    pv_kw: Optional[List[float]] = Field(
        None,
        description="Additional PV generation [kW_avg]. Same length as main profile."
    )
    load_kw: Optional[List[float]] = Field(
        None,
        description="Additional load [kW_avg]. Same length as main profile."
    )
    scale_factor: float = Field(
        1.0, ge=0, le=100,
        description="Scaling factor applied to this profile. 1.0 = as-is."
    )


# =============================================================================
# Price Configuration (future-ready for time-varying)
# =============================================================================

class PriceConfig(BaseModel):
    """
    Energy price configuration.

    Supports two pricing modes:
    1. Flat pricing (legacy): Single import/export rate
    2. ToU pricing (Opcja B): OSD tariff + OTHER fees + capacity fee separately

    When tariff_id is set, ToU pricing is used with:
    - OSD rates = energia czynna + dystrybucja (combined from preset)
    - other_fees = OZE + kog + jakość + akcyza (added on top)
    - capacity_fee = calculated separately via capacity_fee_pl module
    """
    # Legacy flat pricing (used when tariff_id is None)
    import_price_pln_mwh: float = Field(800.0, ge=0,
                                         description="Import price [PLN/MWh]")
    export_price_pln_mwh: float = Field(0.0, ge=0,
                                         description="Export price [PLN/MWh] (0 for 0-export)")

    # Demand charge (opłata za moc umowną) - for peak shaving
    demand_charge_pln_kw_month: float = Field(0.0, ge=0,
                                               description="Monthly demand charge [PLN/kW/month] based on peak import")
    demand_charge_pln_kw_year: float = Field(0.0, ge=0,
                                              description="Annual demand charge [PLN/kW/year] based on peak import")

    # === NEW: ToU Pricing (Opcja B - OSD_ALL_IN) ===

    # OSD tariff preset (e.g., "pge_c12a_2025")
    tariff_id: Optional[str] = Field(
        None,
        description="OSD tariff preset ID. If set, uses ToU pricing instead of flat."
    )

    # OTHER fees (suma opłat stałych) - added to energia czynna rates
    other_fees_pln_mwh: float = Field(
        451.0,  # Default: 200 + 10 + 7 + 10 + 219 + 5 (OSD, OZE, kog, jakość, mocowa, akcyza)
        ge=0,
        description="Suma opłat stałych [PLN/MWh]"
    )

    # Capacity fee (opłata mocowa PL) settings
    capacity_fee_method: str = Field(
        "dynamic",
        description="'dynamic' (A×SOM×ZS) or 'fixed' (simple per-MWh)"
    )
    capacity_fee_som_pln_kwh: float = Field(
        0.2194,  # 2025/2026 rate
        ge=0,
        description="SOM rate for dynamic capacity fee [PLN/kWh]"
    )
    capacity_fee_fixed_pln_mwh: Optional[float] = Field(
        None,
        ge=0,
        description="Fixed capacity fee rate [PLN/MWh] - only for 'fixed' method"
    )

    # Analysis year (for ToU zone calculation)
    analysis_year: int = Field(
        2025,
        ge=2020,
        le=2035,
        description="Year for calendar calculations (holidays, weekends)"
    )

    @property
    def is_tou_enabled(self) -> bool:
        """Check if ToU pricing is enabled (tariff_id set)"""
        return self.tariff_id is not None

    @property
    def is_time_varying(self) -> bool:
        """Check if prices are time-varying"""
        return self.is_tou_enabled

    @property
    def annual_demand_charge_pln_kw(self) -> float:
        """Get annual demand charge per kW peak (sum of monthly or annual rate)"""
        return self.demand_charge_pln_kw_month * 12 + self.demand_charge_pln_kw_year

    @property
    def other_fees_pln_kwh(self) -> float:
        """Get OTHER fees in PLN/kWh"""
        return self.other_fees_pln_mwh / 1000.0

    def get_import_price(self, timestep: int = 0) -> float:
        """Get import price for timestep (constant for flat, ToU handled separately)"""
        return self.import_price_pln_mwh

    def get_export_price(self, timestep: int = 0) -> float:
        """Get export price for timestep (constant for now)"""
        return self.export_price_pln_mwh


# =============================================================================
# Tariff Schedule Config (v2.1.0)
# =============================================================================

class TariffScheduleConfig(BaseModel):
    """
    Custom tariff schedule configuration (v2.1.0).

    Allows defining 24-hour price schedules for weekdays and weekends,
    with optional holiday overrides.

    DST-safe: Uses timezone-aware datetime conversion for correct hour mapping.
    """
    # Weekday import prices (24 values, one per hour 0-23)
    weekday_import_price_pln_per_mwh: List[float] = Field(
        ...,
        min_length=24,
        max_length=24,
        description="Import prices for weekdays [PLN/MWh]. Index 0 = hour 00:00, index 23 = hour 23:00."
    )
    # Weekend import prices (24 values, one per hour 0-23)
    weekend_import_price_pln_per_mwh: List[float] = Field(
        ...,
        min_length=24,
        max_length=24,
        description="Import prices for weekends [PLN/MWh]. Index 0 = hour 00:00, index 23 = hour 23:00."
    )
    # Weekday export prices (24 values)
    weekday_export_price_pln_per_mwh: List[float] = Field(
        default_factory=lambda: [0.0] * 24,
        min_length=24,
        max_length=24,
        description="Export prices for weekdays [PLN/MWh]. Defaults to 0."
    )
    # Weekend export prices (24 values)
    weekend_export_price_pln_per_mwh: List[float] = Field(
        default_factory=lambda: [0.0] * 24,
        min_length=24,
        max_length=24,
        description="Export prices for weekends [PLN/MWh]. Defaults to 0."
    )
    # Weekday other fees (24 values)
    weekday_other_fees_pln_per_mwh: List[float] = Field(
        default_factory=lambda: [0.0] * 24,
        min_length=24,
        max_length=24,
        description="Other fees for weekdays [PLN/MWh]."
    )
    # Weekend other fees (24 values)
    weekend_other_fees_pln_per_mwh: List[float] = Field(
        default_factory=lambda: [0.0] * 24,
        min_length=24,
        max_length=24,
        description="Other fees for weekends [PLN/MWh]."
    )
    # Holiday dates (YYYY-MM-DD format, treated as weekends)
    holiday_dates: List[str] = Field(
        default_factory=list,
        description="Holiday dates (YYYY-MM-DD) to treat as weekends."
    )
    # Timezone for DST-safe hour mapping
    timezone: str = Field(
        "Europe/Warsaw",
        description="Timezone for mapping UTC to local hour (DST-safe)."
    )


# =============================================================================
# Dispatch Request
# =============================================================================

class DispatchRequest(BaseModel):
    """Request for BESS dispatch simulation"""

    # Topology - determines which components are present (must be first for validation order)
    topology: TopologyType = Field(
        TopologyType.PV_LOAD,
        description="System topology (pv_load or load_only)"
    )

    # Time series data [kW average per interval]
    pv_generation_kw: List[float] = Field(default_factory=list,
                                           description="PV generation [kW_avg]. Can be empty for LOAD_ONLY topology.")
    load_kw: List[float] = Field(..., min_items=24,
                                  description="Load consumption [kW_avg]")

    # Analytical period - SINGLE SOURCE OF TRUTH for time axis
    # If provided, overrides interval_minutes and start_date with period config
    analytical_period: Optional[AnalyticalPeriodConfig] = Field(
        None,
        description="Time axis configuration. If provided, is the single source of truth for time calculations."
    )

    # Profile unit declaration for audit trail
    profile_unit: ProfileUnit = Field(
        ProfileUnit.KW_AVG,
        description="Unit of input profiles (must be kW_avg for dispatch)"
    )

    # Time configuration
    interval_minutes: int = Field(60, description="Interval duration (15 or 60)")

    # Battery configuration
    battery: BatteryParams

    # Dispatch mode
    mode: DispatchMode = Field(DispatchMode.PV_SURPLUS)

    # Solver selection (v1.4.0 - LP optimization)
    solver: SolverType = Field(
        SolverType.LP,
        description="Always 'lp' (v7.0.0). LP is the only dispatch algorithm."
    )
    lp_params: Optional[LPSolverParams] = Field(
        default_factory=LPSolverParams,
        description="LP solver configuration. Defaults are Galileo-proven (34h/24h)."
    )

    # Mode-specific parameters
    stacked_params: Optional[StackedModeParams] = None
    peak_limit_kw: Optional[float] = None  # For PEAK_SHAVING / LOAD_ONLY mode

    # Arbitrage configuration (optional, enables ToU arbitrage in STACKED mode)
    arbitrage_config: Optional[ArbitrageConfig] = Field(
        None,
        description="ToU arbitrage configuration. If enabled, adds arbitrage to STACKED mode."
    )

    # Start date for price lookup (required when arbitrage enabled)
    start_date: Optional[str] = Field(
        None,
        description="Start date (YYYY-MM-DD) for tariff price lookup. Required if arbitrage enabled."
    )

    # Degradation budget
    degradation_budget: Optional[DegradationBudget] = None

    # Pricing
    prices: PriceConfig = Field(default_factory=PriceConfig)

    # Cable pooling: multiple PV/load profiles behind single connection point
    cable_pooling_profiles: Optional[List["CablePoolingProfile"]] = Field(
        None,
        description="Additional PV/load profiles for cable pooling. "
                    "Profiles are summed with main pv_generation_kw/load_kw before dispatch."
    )

    # Energy flows SSoT control (new in v0.3)
    include_energy_flows_timeseries: bool = Field(
        False,
        description="Include per-timestep energy flows in response. "
                    "False = only totals_mwh (small). True = also timeseries_kwh (large)."
    )

    # Economics timeseries control (new in v1.5.0)
    include_economics_timeseries: bool = Field(
        False,
        description="Include per-timestep economics breakdown in response. "
                    "False = only totals_pln (small). True = also timeseries_pln (large)."
    )

    # Battery trace control (new in v2.2.0)
    include_battery_trace: bool = Field(
        False,
        description="Include per-timestep battery trace in response. "
                    "Shows soc_kwh, charge_kw, discharge_kw at each timestep for dispatch debugging."
    )

    # Capacity fee optimization (flatness constraint multi-solve)
    optimize_capacity_fee: bool = Field(
        False,
        description="Enable capacity fee optimization via multi-solve LP. "
                    "Runs LP multiple times with different price premiums on selected hours "
                    "to find dispatch minimizing total cost (energy + opłata mocowa)."
    )

    # Grid constraints (v0.7.0)
    grid_constraints: Optional["GridConstraints"] = Field(
        None,
        description="Grid connection constraints (max_export_kw, max_import_kw, allow_export). "
                    "Applied to both baseline and project scenarios."
    )

    @validator('interval_minutes')
    def validate_interval(cls, v):
        if v not in [15, 60]:
            raise ValueError("interval_minutes must be 15 or 60")
        return v

    @validator('pv_generation_kw', pre=True, always=True)
    def validate_pv_generation(cls, v, values):
        """Allow empty PV array for LOAD_ONLY topology"""
        if v is None:
            return []
        return v

    @validator('load_kw')
    def validate_lengths(cls, v, values):
        """Validate load vs PV lengths, accounting for topology"""
        pv = values.get('pv_generation_kw', [])
        topology = values.get('topology', TopologyType.PV_LOAD)

        if topology == TopologyType.LOAD_ONLY:
            # LOAD_ONLY: PV can be empty or all zeros
            if len(pv) > 0 and len(v) != len(pv):
                raise ValueError("If pv_generation_kw is provided, it must match load_kw length")
        else:
            # PV_LOAD: PV is required and must match load length
            if len(pv) == 0:
                raise ValueError("pv_generation_kw is required for PV_LOAD topology")
            if len(v) != len(pv):
                raise ValueError("pv_generation_kw and load_kw must have same length")
        return v

    @validator('mode')
    def validate_mode_topology(cls, v, values):
        """Validate mode is compatible with topology"""
        topology = values.get('topology', TopologyType.PV_LOAD)

        if topology == TopologyType.LOAD_ONLY:
            # LOAD_ONLY topology: only LOAD_ONLY or PEAK_SHAVING modes make sense
            if v in [DispatchMode.PV_SURPLUS, DispatchMode.STACKED]:
                raise ValueError(
                    f"Mode {v} requires PV generation. Use LOAD_ONLY or PEAK_SHAVING mode "
                    f"with LOAD_ONLY topology, or switch to PV_LOAD topology."
                )
        return v

    @validator('profile_unit')
    def validate_profile_unit(cls, v):
        if v != ProfileUnit.KW_AVG:
            raise ValueError(
                f"Dispatch requires kW_avg profiles. Got {v}. "
                "Use convert_profile_to_kw_avg() to convert."
            )
        return v

    @validator('start_date', always=True)
    def validate_start_date_for_arbitrage(cls, v, values):
        """Validate start_date is provided when arbitrage is enabled"""
        arb_config = values.get('arbitrage_config')
        if arb_config and arb_config.enabled and not v:
            raise ValueError(
                "start_date is required when arbitrage_config.enabled=True. "
                "Provide date in YYYY-MM-DD format for tariff price lookup."
            )
        return v

    @property
    def dt_hours(self) -> float:
        """Time step duration in hours"""
        return self.interval_minutes / 60.0

    @property
    def n_timesteps(self) -> int:
        """Number of timesteps"""
        return len(self.load_kw)

    @property
    def total_hours(self) -> float:
        """Total simulation duration in hours"""
        return self.n_timesteps * self.dt_hours

    @property
    def effective_pv_kw(self) -> List[float]:
        """Get PV array, creating zeros if empty (for LOAD_ONLY topology)"""
        if len(self.pv_generation_kw) == 0:
            return [0.0] * len(self.load_kw)
        return self.pv_generation_kw


# =============================================================================
# Degradation Metrics
# =============================================================================

class DegradationMetrics(BaseModel):
    """Degradation and cycling metrics"""

    # Total throughput
    throughput_charge_kwh: float = Field(0.0, description="Total energy charged [kWh]")
    throughput_discharge_kwh: float = Field(0.0, description="Total energy discharged [kWh]")
    throughput_total_mwh: float = Field(0.0, description="Total throughput [MWh]")

    # Equivalent Full Cycles
    efc_total: float = Field(0.0, description="Total equivalent full cycles")

    # Per-service breakdown (for STACKED mode)
    throughput_pv_mwh: float = Field(0.0, description="Throughput for PV shifting [MWh]")
    throughput_peak_mwh: float = Field(0.0, description="Throughput for peak shaving [MWh]")
    efc_pv: float = Field(0.0, description="EFC for PV shifting")
    efc_peak: float = Field(0.0, description="EFC for peak shaving")

    # Arbitrage metrics (for STACKED + arbitrage)
    throughput_arb_mwh: float = Field(0.0, description="Throughput for arbitrage [MWh]")
    efc_arb: float = Field(0.0, description="EFC for arbitrage")
    arb_charge_from_grid_kwh: float = Field(0.0, description="Energy charged from grid for arbitrage [kWh]")
    arb_discharge_kwh: float = Field(0.0, description="Energy discharged for arbitrage [kWh]")
    arb_cycles_count: int = Field(0, description="Number of arbitrage charge/discharge cycles")

    # Peak shaving event statistics
    peak_events_count: int = Field(0, description="Number of hours with peak shaving discharge")
    peak_events_energy_kwh: float = Field(0.0, description="Total energy discharged for peak shaving [kWh]")
    peak_max_discharge_kw: float = Field(0.0, description="Maximum discharge power for peak shaving [kW]")

    # Daily statistics (for daily limit enforcement)
    n_days: int = Field(0, description="Number of days in analysis period")
    max_daily_efc: float = Field(0.0, description="Max EFC in any single day")
    avg_daily_efc: float = Field(0.0, description="Average EFC per day")
    max_daily_throughput_mwh: float = Field(0.0, description="Max throughput in any single day [MWh]")
    avg_daily_throughput_mwh: float = Field(0.0, description="Average throughput per day [MWh]")
    days_exceeding_cycle_limit: int = Field(0, description="Days where daily cycle limit was exceeded")
    days_exceeding_throughput_limit: int = Field(0, description="Days where daily throughput limit was exceeded")

    # Charge source breakdown
    charge_from_pv_kwh: float = Field(0.0, description="Energy charged from PV surplus [kWh]")
    charge_from_grid_kwh: float = Field(0.0, description="Energy charged from grid [kWh]")
    charge_pv_pct: float = Field(0.0, description="Percentage of charge from PV [%]")

    # Budget status
    budget_status: DegradationStatus = Field(DegradationStatus.OK)
    budget_utilization_pct: float = Field(0.0, description="Budget utilization [%]")
    budget_warnings: List[str] = Field(default_factory=list)


# =============================================================================
# Dispatch Result
# =============================================================================

class HourlyDispatch(BaseModel):
    """Hourly dispatch data (for detailed analysis)"""
    timestep: int
    pv_kw: float
    load_kw: float
    direct_pv_kw: float
    charge_kw: float
    discharge_kw: float
    grid_import_kw: float
    grid_export_kw: float
    curtailment_kw: float
    soc_kwh: float
    soc_pct: float

    # For STACKED mode: service breakdown
    discharge_peak_kw: float = 0.0
    discharge_pv_kw: float = 0.0
    discharge_arb_kw: float = 0.0  # For arbitrage


class SavingsBreakdown(BaseModel):
    """
    Detailed breakdown of annual savings by source.

    Used for transparent NPV calculation and frontend display.
    Sum of all components equals net_savings_pln.

    NOTE on terminology:
    - demand_charge_savings_pln = peak shaving (opłata za moc umowną / demand charge)
    - capacity_fee_savings_pln = opłata mocowa PL (rynek mocy) - osobny moduł
    - export_revenue_pln = revenue from grid export (sprzedaż nadwyżek do sieci)
    """
    # Positive savings/revenue
    energy_savings_pln: float = Field(0.0, description="Savings from reduced grid import at flat price (volume × flat_rate)")
    arbitrage_savings_pln: float = Field(0.0, description="ADDITIONAL savings from ToU price spread (tou_total - flat_savings)")
    capacity_fee_savings_pln: float = Field(0.0, description="Savings from reduced capacity fee (opłata mocowa PL)")
    demand_charge_savings_pln: float = Field(0.0, description="Savings from peak shaving (opłata za moc / demand charge)")

    # Export revenue breakdown (SSoT)
    baseline_export_revenue_pln: float = Field(0.0, description="Export revenue WITHOUT battery (PV surplus only)")
    project_export_revenue_pln: float = Field(0.0, description="Export revenue WITH battery (reduced due to self-consumption)")
    export_revenue_savings_pln: float = Field(0.0, description="Change in export revenue = project - baseline (typically negative)")

    # DEPRECATED: Use project_export_revenue_pln instead
    # This field will be removed in v1.0. For now it equals project_export_revenue_pln.
    export_revenue_pln: float = Field(
        0.0,
        description="[DEPRECATED] Use project_export_revenue_pln instead. "
                    "This field equals project_export_revenue_pln for backward compatibility."
    )

    # Battery throughput (for degradation calculation)
    battery_throughput_mwh: float = Field(0.0, description="Total battery throughput [MWh] (discharge only)")

    # Ancillary services revenue (v2.0 — uslugi pomocnicze)
    ancillary_afrr_revenue_pln: float = Field(0.0, description="aFRR capacity + energy revenue [PLN/year]")
    ancillary_mfrr_revenue_pln: float = Field(0.0, description="mFRR capacity + energy revenue [PLN/year]")
    ancillary_fcr_revenue_pln: float = Field(0.0, description="FCR capacity revenue [PLN/year]")
    ancillary_capacity_market_pln: float = Field(0.0, description="Rynek Mocy revenue [PLN/year]")
    ancillary_aggregator_fee_pln: float = Field(0.0, description="Aggregator margin deducted [PLN/year]")
    ancillary_total_net_pln: float = Field(0.0, description="Total ancillary net revenue after aggregator [PLN/year]")

    # Negative (costs)
    degradation_cost_pln: float = Field(0.0, description="Cost of battery degradation (throughput-based)")
    unserved_load_penalty_pln: float = Field(0.0, description="Penalty for unserved load due to import cap [PLN]")

    # Net
    net_savings_pln: float = Field(0.0, description="Net annual savings = energy + demand + arbitrage + capacity_fee + export_delta + ancillary - degradation - unserved_penalty")

    def calculate_net(self) -> float:
        """
        Calculate net savings from components.

        Formula: net = energy + arbitrage + capacity_fee + demand + export_delta + ancillary_net - degradation - unserved_penalty

        Note: export_revenue_savings_pln is typically NEGATIVE (battery uses PV that would be exported)
        so adding it reduces net savings, which is correct behavior.
        """
        return (
            self.energy_savings_pln +
            self.arbitrage_savings_pln +
            self.capacity_fee_savings_pln +
            self.demand_charge_savings_pln +
            self.export_revenue_savings_pln +  # delta = project - baseline (usually negative)
            self.ancillary_total_net_pln -      # ancillary services net revenue
            abs(self.degradation_cost_pln) -
            abs(self.unserved_load_penalty_pln)
        )


# =============================================================================
# Money Ledger SSoT (v1.9.0)
# =============================================================================

class MoneyLedgerTotalsPln(BaseModel):
    """
    Cost breakdown totals for a scenario (baseline or project).

    All values in PLN. Costs are positive, revenue is positive but subtracted
    from total_cost (so higher revenue = lower total_cost).

    This is the SINGLE SOURCE OF TRUTH for cost accounting.
    """
    # Energy costs (import from grid)
    import_energy_cost_pln: float = Field(
        0.0,
        description="Cost of importing energy from grid [PLN] - includes ToU rate"
    )

    # Export revenue (positive = money earned)
    export_revenue_pln: float = Field(
        0.0,
        description="Revenue from exporting energy to grid [PLN] - positive value"
    )

    # Fees and charges
    other_fees_pln: float = Field(
        0.0,
        description="Other fees [PLN]: OZE, kogeneracja, jakość, akcyza"
    )
    capacity_fee_pln: float = Field(
        0.0,
        description="Capacity fee (opłata mocowa PL) [PLN]"
    )
    demand_charge_pln: float = Field(
        0.0,
        description="Demand charge / peak shaving fee (opłata za moc umowną) [PLN]"
    )

    # Penalties and costs
    unserved_penalty_pln: float = Field(
        0.0,
        description="Penalty for unserved load due to import constraints [PLN]"
    )
    degradation_cost_pln: float = Field(
        0.0,
        description="Battery degradation cost (throughput-based) [PLN]"
    )

    # SSoT Total
    total_cost_pln: float = Field(
        0.0,
        description="Total net cost [PLN] = import + fees + penalties - export_revenue"
    )

    def calculate_total(self) -> float:
        """
        Calculate total cost from components.

        Formula: total = import + other_fees + capacity_fee + demand_charge
                        + unserved_penalty + degradation - export_revenue
        """
        return (
            self.import_energy_cost_pln +
            self.other_fees_pln +
            self.capacity_fee_pln +
            self.demand_charge_pln +
            self.unserved_penalty_pln +
            self.degradation_cost_pln -
            self.export_revenue_pln  # Revenue reduces total cost
        )


class MoneyLedger(BaseModel):
    """
    Complete money ledger comparing baseline vs project costs (v1.9.0 SSoT).

    Provides full cost breakdown for:
    - baseline_period: Costs for the analysis period WITHOUT battery
    - project_period: Costs for the analysis period WITH battery
    - delta_period_pln: Difference (baseline - project) for period
    - baseline_annual: Annualized costs WITHOUT battery
    - project_annual: Annualized costs WITH battery
    - delta_annual_pln: Annualized difference (baseline - project)

    The delta values represent SAVINGS (positive = money saved).
    delta.total_cost_pln should match net_savings_pln (SSoT reconciliation).
    """
    # Period costs (actual analysis period)
    baseline_period: MoneyLedgerTotalsPln = Field(
        default_factory=MoneyLedgerTotalsPln,
        description="Baseline costs for the analysis period (no battery)"
    )
    project_period: MoneyLedgerTotalsPln = Field(
        default_factory=MoneyLedgerTotalsPln,
        description="Project costs for the analysis period (with battery)"
    )
    delta_period_pln: MoneyLedgerTotalsPln = Field(
        default_factory=MoneyLedgerTotalsPln,
        description="Delta (baseline - project) for period = savings per category"
    )

    # Annualized costs
    baseline_annual: MoneyLedgerTotalsPln = Field(
        default_factory=MoneyLedgerTotalsPln,
        description="Baseline costs annualized"
    )
    project_annual: MoneyLedgerTotalsPln = Field(
        default_factory=MoneyLedgerTotalsPln,
        description="Project costs annualized"
    )
    delta_annual_pln: MoneyLedgerTotalsPln = Field(
        default_factory=MoneyLedgerTotalsPln,
        description="Delta (baseline - project) annualized = annual savings per category"
    )

    # Period metadata
    is_full_year: bool = Field(
        False,
        description="True if analysis period is exactly 8760 hours (1 year)"
    )
    period_hours: int = Field(
        0,
        description="Number of hours in analysis period"
    )


# =============================================================================
# Price Timeseries SSoT (v2.0.0)
# =============================================================================

class PriceTimeseriesPlnPerMwh(BaseModel):
    """
    Per-step price timeseries in PLN/MWh (v2.0.0 SSoT).

    This is the SINGLE SOURCE OF TRUTH for what prices were used in calculations.
    All values are arrays of length 'steps' (matching period_info.steps).

    Used for:
    - Debugging: verify which prices were applied at each timestep
    - Transparency: user can see exact ToU zone mapping
    - Reproducibility: export prices + use as override for deterministic replay
    - Validation: sum(price * energy) should match MoneyLedger totals
    """
    # Core price arrays (PLN per MWh)
    import_price_pln_per_mwh: List[float] = Field(
        ...,
        description="Grid import price at each timestep [PLN/MWh]. Length = steps."
    )
    export_price_pln_per_mwh: List[float] = Field(
        ...,
        description="Grid export price at each timestep [PLN/MWh]. Length = steps."
    )
    other_fees_pln_per_mwh: List[float] = Field(
        default_factory=list,
        description="Other fees (OZE, kogeneracja, etc.) at each timestep [PLN/MWh]. Length = steps."
    )

    # Penalty rates (may be constant or time-varying)
    unserved_penalty_pln_per_kwh: List[float] = Field(
        default_factory=list,
        description="Unserved load penalty at each timestep [PLN/kWh]. Length = steps."
    )

    # Period metadata
    step_minutes: int = Field(
        ...,
        ge=15, le=60,
        description="Time resolution in minutes (15 or 60)"
    )
    steps: int = Field(
        ...,
        ge=1,
        description="Number of timesteps"
    )
    timezone: str = Field(
        "Europe/Warsaw",
        description="Timezone used for ToU zone mapping"
    )
    period_start: str = Field(
        ...,
        description="Period start (ISO 8601)"
    )
    period_end: str = Field(
        ...,
        description="Period end (ISO 8601)"
    )

    def validate_lengths(self) -> bool:
        """Validate that all arrays have correct length."""
        if len(self.import_price_pln_per_mwh) != self.steps:
            return False
        if len(self.export_price_pln_per_mwh) != self.steps:
            return False
        if self.other_fees_pln_per_mwh and len(self.other_fees_pln_per_mwh) != self.steps:
            return False
        if self.unserved_penalty_pln_per_kwh and len(self.unserved_penalty_pln_per_kwh) != self.steps:
            return False
        return True

    def has_invalid_values(self) -> bool:
        """Check for NaN or inf values in price arrays."""
        import math
        for arr in [self.import_price_pln_per_mwh, self.export_price_pln_per_mwh]:
            for v in arr:
                if math.isnan(v) or math.isinf(v):
                    return True
        return False


# =============================================================================
# Battery Trace Timeseries SSoT (v2.2.0)
# =============================================================================

class BatteryTraceTimeseries(BaseModel):
    """
    Per-step battery trace timeseries (v2.2.0 SSoT).

    This is the SINGLE SOURCE OF TRUTH for battery state and power flows
    at each timestep during dispatch simulation.

    Returned only when include_battery_trace=true to avoid payload bloat.

    Used for:
    - Debugging: verify SOC evolution and charge/discharge decisions
    - Transparency: user can see exact power flows at each timestep
    - Validation: SOC bounds and power limits invariants
    - Visualization: chart SOC and power over time
    """
    # SOC at each timestep (kWh) - length = steps
    # Convention: soc_kwh[i] = SOC at the END of timestep i
    soc_kwh: List[float] = Field(
        ...,
        description="Battery SOC at end of each timestep [kWh]. Length = steps."
    )

    # Charge/discharge power at each timestep (kW) - all >= 0
    charge_kw: List[float] = Field(
        ...,
        description="Battery charge power at each timestep [kW]. All values >= 0. Length = steps."
    )
    discharge_kw: List[float] = Field(
        ...,
        description="Battery discharge power at each timestep [kW]. All values >= 0. Length = steps."
    )

    # Source of charge power breakdown
    charge_from_pv_kw: List[float] = Field(
        ...,
        description="Charge from PV surplus at each timestep [kW]. All values >= 0. Length = steps."
    )
    charge_from_grid_kw: List[float] = Field(
        default_factory=list,
        description="Charge from grid at each timestep [kW]. All values >= 0. Only with allow_grid_charging. Length = steps."
    )

    # Destination of discharge power breakdown
    discharge_to_load_kw: List[float] = Field(
        ...,
        description="Discharge to load at each timestep [kW]. All values >= 0. Length = steps."
    )
    discharge_to_grid_kw: List[float] = Field(
        default_factory=list,
        description="Discharge to grid (export) at each timestep [kW]. All values >= 0. Length = steps."
    )

    # Metadata
    steps: int = Field(
        ...,
        ge=1,
        description="Number of timesteps"
    )
    step_minutes: int = Field(
        ...,
        ge=15, le=60,
        description="Time resolution in minutes (15 or 60)"
    )

    # Battery parameters for validation
    battery_energy_kwh: float = Field(
        ...,
        description="Battery energy capacity [kWh] for SOC bounds validation"
    )
    battery_power_kw: float = Field(
        ...,
        description="Battery power capacity [kW] for power limits validation"
    )

    def validate_lengths(self) -> bool:
        """Check all arrays have correct length."""
        if len(self.soc_kwh) != self.steps:
            return False
        if len(self.charge_kw) != self.steps:
            return False
        if len(self.discharge_kw) != self.steps:
            return False
        if len(self.charge_from_pv_kw) != self.steps:
            return False
        if len(self.discharge_to_load_kw) != self.steps:
            return False
        # Optional arrays (may be empty if feature not enabled)
        if self.charge_from_grid_kw and len(self.charge_from_grid_kw) != self.steps:
            return False
        if self.discharge_to_grid_kw and len(self.discharge_to_grid_kw) != self.steps:
            return False
        return True

    def validate_soc_bounds(self, tolerance: float = 1e-6) -> bool:
        """Check SOC stays within [0, battery_energy_kwh]."""
        for soc in self.soc_kwh:
            if soc < -tolerance:
                return False
            if soc > self.battery_energy_kwh + tolerance:
                return False
        return True

    def validate_power_non_negative(self) -> bool:
        """Check all power values are non-negative."""
        for arr in [self.charge_kw, self.discharge_kw, self.charge_from_pv_kw, self.discharge_to_load_kw]:
            if any(v < 0 for v in arr):
                return False
        if self.charge_from_grid_kw and any(v < 0 for v in self.charge_from_grid_kw):
            return False
        if self.discharge_to_grid_kw and any(v < 0 for v in self.discharge_to_grid_kw):
            return False
        return True


# =============================================================================
# Ledger Timeseries SSoT (v2.0.0)
# =============================================================================

class LedgerTimeseriesPlnPerStep(BaseModel):
    """
    Per-step cost timeseries in PLN for each timestep (v2.0.0 SSoT).

    This is the SINGLE SOURCE OF TRUTH for per-step economics.
    All values are arrays of length 'steps' (matching period_info.steps).

    Used for:
    - Debugging: see cost contributions at each timestep
    - Transparency: user can trace costs back to energy flows
    - Validation: sum of arrays should match MoneyLedger totals (invariant)
    - Visualization: chart stacked costs over time
    """
    # Cost buckets per step (PLN)
    import_cost_pln: List[float] = Field(
        ...,
        description="Grid import cost at each timestep [PLN]. Length = steps."
    )
    export_revenue_pln: List[float] = Field(
        ...,
        description="Export revenue at each timestep [PLN]. Positive = revenue. Length = steps."
    )
    other_fees_pln: List[float] = Field(
        default_factory=list,
        description="Other fees at each timestep [PLN]. Length = steps."
    )
    unserved_penalty_pln: List[float] = Field(
        default_factory=list,
        description="Unserved load penalty at each timestep [PLN]. Length = steps."
    )

    # Aggregated net cost per step
    net_cost_pln: List[float] = Field(
        default_factory=list,
        description="Net cost at each timestep [PLN] = import + fees + penalty - export. Length = steps."
    )

    # Period metadata
    step_minutes: int = Field(
        ...,
        ge=15, le=60,
        description="Time resolution in minutes (15 or 60)"
    )
    steps: int = Field(
        ...,
        ge=1,
        description="Number of timesteps"
    )

    # Sum totals (for invariant checking)
    sum_import_cost_pln: float = Field(
        0.0,
        description="Sum of import_cost_pln array [PLN]. Should match MoneyLedger."
    )
    sum_export_revenue_pln: float = Field(
        0.0,
        description="Sum of export_revenue_pln array [PLN]. Should match MoneyLedger."
    )
    sum_other_fees_pln: float = Field(
        0.0,
        description="Sum of other_fees_pln array [PLN]. Should match MoneyLedger."
    )
    sum_unserved_penalty_pln: float = Field(
        0.0,
        description="Sum of unserved_penalty_pln array [PLN]. Should match MoneyLedger."
    )
    sum_net_cost_pln: float = Field(
        0.0,
        description="Sum of net_cost_pln array [PLN]. Should match MoneyLedger.total_cost_pln."
    )

    def validate_lengths(self) -> bool:
        """Validate that all arrays have correct length."""
        if len(self.import_cost_pln) != self.steps:
            return False
        if len(self.export_revenue_pln) != self.steps:
            return False
        if self.other_fees_pln and len(self.other_fees_pln) != self.steps:
            return False
        if self.unserved_penalty_pln and len(self.unserved_penalty_pln) != self.steps:
            return False
        if self.net_cost_pln and len(self.net_cost_pln) != self.steps:
            return False
        return True

    def validate_sums(self, tolerance: float = 0.01) -> Tuple[bool, List[str]]:
        """
        Validate that sum fields match actual array sums.

        Returns:
            Tuple of (is_valid, list of error messages)
        """
        errors = []
        actual_import = sum(self.import_cost_pln)
        if abs(actual_import - self.sum_import_cost_pln) > tolerance:
            errors.append(f"import_cost sum mismatch: {actual_import:.2f} != {self.sum_import_cost_pln:.2f}")

        actual_export = sum(self.export_revenue_pln)
        if abs(actual_export - self.sum_export_revenue_pln) > tolerance:
            errors.append(f"export_revenue sum mismatch: {actual_export:.2f} != {self.sum_export_revenue_pln:.2f}")

        if self.other_fees_pln:
            actual_fees = sum(self.other_fees_pln)
            if abs(actual_fees - self.sum_other_fees_pln) > tolerance:
                errors.append(f"other_fees sum mismatch: {actual_fees:.2f} != {self.sum_other_fees_pln:.2f}")

        if self.unserved_penalty_pln:
            actual_penalty = sum(self.unserved_penalty_pln)
            if abs(actual_penalty - self.sum_unserved_penalty_pln) > tolerance:
                errors.append(f"unserved_penalty sum mismatch: {actual_penalty:.2f} != {self.sum_unserved_penalty_pln:.2f}")

        if self.net_cost_pln:
            actual_net = sum(self.net_cost_pln)
            if abs(actual_net - self.sum_net_cost_pln) > tolerance:
                errors.append(f"net_cost sum mismatch: {actual_net:.2f} != {self.sum_net_cost_pln:.2f}")

        return len(errors) == 0, errors

    def calculate_sums(self) -> None:
        """Recalculate sum fields from arrays (mutates self)."""
        self.sum_import_cost_pln = sum(self.import_cost_pln)
        self.sum_export_revenue_pln = sum(self.export_revenue_pln)
        self.sum_other_fees_pln = sum(self.other_fees_pln) if self.other_fees_pln else 0.0
        self.sum_unserved_penalty_pln = sum(self.unserved_penalty_pln) if self.unserved_penalty_pln else 0.0
        self.sum_net_cost_pln = sum(self.net_cost_pln) if self.net_cost_pln else 0.0


# =============================================================================
# Energy Flows SSoT
# =============================================================================

class EnergyFlowsTotalsMwh(BaseModel):
    """
    Total energy flows in MWh for the analysis period.

    This is the SINGLE SOURCE OF TRUTH for energy accounting.
    All values are in MWh and represent totals over the period.
    """
    grid_import_mwh: float = Field(0.0, description="Total grid import [MWh]")
    grid_export_mwh: float = Field(0.0, description="Total grid export [MWh]")
    pv_to_load_mwh: float = Field(0.0, description="PV energy directly consumed by load [MWh]")
    pv_to_batt_mwh: float = Field(0.0, description="PV energy charged to battery [MWh]")
    pv_curtail_mwh: float = Field(0.0, description="PV energy curtailed [MWh]")
    batt_to_load_mwh: float = Field(0.0, description="Battery discharge to load [MWh]")
    batt_charge_from_grid_mwh: float = Field(0.0, description="Battery charge from grid [MWh]")
    batt_losses_mwh: float = Field(0.0, description="Battery round-trip losses [MWh]")


class EnergyFlowsTimeseriesKwh(BaseModel):
    """
    Per-timestep energy flows in kWh.

    Only included in response when include_energy_flows_timeseries=True.
    Useful for debugging and detailed analysis.
    """
    grid_import_kwh: List[float] = Field(default_factory=list, description="Grid import per step [kWh]")
    grid_export_kwh: List[float] = Field(default_factory=list, description="Grid export per step [kWh]")
    pv_to_load_kwh: List[float] = Field(default_factory=list, description="PV to load per step [kWh]")
    pv_to_batt_kwh: List[float] = Field(default_factory=list, description="PV to battery per step [kWh]")
    pv_curtail_kwh: List[float] = Field(default_factory=list, description="PV curtailed per step [kWh]")
    batt_to_load_kwh: List[float] = Field(default_factory=list, description="Battery to load per step [kWh]")
    batt_charge_from_grid_kwh: List[float] = Field(default_factory=list, description="Battery charge from grid per step [kWh]")
    batt_losses_kwh: List[float] = Field(default_factory=list, description="Battery losses per step [kWh]")
    soc_kwh: List[float] = Field(default_factory=list, description="State of charge per step [kWh]")


class EnergyFlows(BaseModel):
    """
    Complete energy flows structure.

    Contains:
    - totals_mwh: Always present (small, for UI and golden tests)
    - timeseries_kwh: Only when requested via include_energy_flows_timeseries flag

    Usage invariants:
    - sum(timeseries_kwh) / 1000 ≈ totals_mwh (within floating point tolerance)
    - Load balance: load_kwh[t] ≈ pv_to_load[t] + batt_to_load[t] + grid_import[t]
    """
    totals_mwh: EnergyFlowsTotalsMwh = Field(
        default_factory=EnergyFlowsTotalsMwh,
        description="Aggregate totals in MWh (always present)"
    )
    timeseries_kwh: Optional[EnergyFlowsTimeseriesKwh] = Field(
        None,
        description="Per-timestep values in kWh (only if include_energy_flows_timeseries=True)"
    )


# =============================================================================
# Economics Breakdown (v1.5.0)
# =============================================================================

class EconomicsTotalsPln(BaseModel):
    """
    Aggregate economics totals in PLN for the analysis period.

    Always present in EconomicsBreakdown (small payload).
    These are per-period totals that sum up to the same values as savings_breakdown.
    """
    energy_cost_baseline_pln: float = Field(
        0.0, description="Total energy cost without battery [PLN]"
    )
    energy_cost_project_pln: float = Field(
        0.0, description="Total energy cost with battery [PLN]"
    )
    energy_savings_pln: float = Field(
        0.0, description="Energy cost savings = baseline - project [PLN]"
    )
    capacity_fee_baseline_pln: float = Field(
        0.0, description="Capacity fee without battery [PLN]"
    )
    capacity_fee_project_pln: float = Field(
        0.0, description="Capacity fee with battery [PLN]"
    )
    capacity_fee_savings_pln: float = Field(
        0.0, description="Capacity fee savings = baseline - project [PLN]"
    )
    demand_charge_baseline_pln: float = Field(
        0.0, description="Demand charge without battery [PLN]"
    )
    demand_charge_project_pln: float = Field(
        0.0, description="Demand charge with battery [PLN]"
    )
    demand_charge_savings_pln: float = Field(
        0.0, description="Demand charge savings = baseline - project [PLN]"
    )
    export_revenue_pln: float = Field(
        0.0, description="Revenue from grid export [PLN]"
    )
    degradation_cost_pln: float = Field(
        0.0, description="Battery degradation cost [PLN]"
    )


class EconomicsTimeseriesPln(BaseModel):
    """
    Per-timestep economics in PLN.

    Only included when include_economics_timeseries=True.
    Useful for debugging and detailed economic analysis.

    Invariants:
    - sum(energy_cost_baseline_pln) = totals.energy_cost_baseline_pln
    - sum(energy_cost_project_pln) = totals.energy_cost_project_pln
    - sum(capacity_fee_pln) = totals.capacity_fee_project_pln (if applicable)
    """
    energy_cost_baseline_pln: List[float] = Field(
        default_factory=list,
        description="Per-step energy cost without battery [PLN]"
    )
    energy_cost_project_pln: List[float] = Field(
        default_factory=list,
        description="Per-step energy cost with battery [PLN]"
    )
    export_revenue_pln: List[float] = Field(
        default_factory=list,
        description="Per-step export revenue [PLN]"
    )
    # Note: Capacity fee and demand charge are typically monthly/annual,
    # so timeseries may not be meaningful for them in hourly resolution


class EconomicsBreakdown(BaseModel):
    """
    Complete economics breakdown structure (v1.5.0).

    Contains:
    - totals_pln: Always present (aggregate values matching savings_breakdown)
    - timeseries_pln: Only when requested via include_economics_timeseries flag

    Usage invariants:
    - sum(timeseries_pln.energy_cost_baseline_pln) ≈ totals_pln.energy_cost_baseline_pln
    - totals_pln.energy_savings_pln ≈ savings_breakdown.energy_savings_pln
    """
    totals_pln: EconomicsTotalsPln = Field(
        default_factory=EconomicsTotalsPln,
        description="Aggregate totals in PLN (always present)"
    )
    timeseries_pln: Optional[EconomicsTimeseriesPln] = Field(
        None,
        description="Per-timestep values in PLN (only if include_economics_timeseries=True)"
    )


class PricesSummary(BaseModel):
    """
    Summary of prices used in simulation.

    For transparency - user can verify what assumptions were used.
    """
    import_price_pln_mwh: float = Field(description="Import price [PLN/MWh]")
    export_price_pln_mwh: float = Field(description="Export price [PLN/MWh]")
    demand_charge_pln_kw_month: float = Field(description="Monthly demand charge [PLN/kW/month]")
    demand_charge_pln_kw_year: float = Field(default=0.0, description="Annual demand charge [PLN/kW/year]")
    tariff_type: str = Field(default="flat", description="Tariff type: flat, two_zone, three_zone")
    tariff_id: Optional[str] = Field(default=None, description="OSD tariff preset ID if used")
    zone_rates: Optional[Dict[str, float]] = Field(
        default=None,
        description="Zone rates if ToU tariff [PLN/MWh], e.g. {'peak': 950, 'partial': 700, 'off_peak': 450}"
    )


class DispatchResult(BaseModel):
    """Result of BESS dispatch simulation"""

    # Configuration echo
    mode: DispatchMode
    battery_power_kw: float
    battery_energy_kwh: float
    interval_minutes: int
    n_timesteps: int

    # Energy flows [kWh]
    total_pv_kwh: float
    total_load_kwh: float
    total_direct_pv_kwh: float
    total_charge_kwh: float
    total_discharge_kwh: float
    total_grid_import_kwh: float
    total_grid_export_kwh: float
    total_curtailment_kwh: float

    # Self-consumption metrics
    self_consumption_kwh: float
    self_consumption_pct: float
    grid_independence_pct: float

    # Peak metrics (for STACKED/PEAK modes)
    original_peak_kw: float = 0.0
    new_peak_kw: float = 0.0
    peak_reduction_kw: float = 0.0
    peak_reduction_pct: float = 0.0

    # Degradation metrics
    degradation: DegradationMetrics

    # Economic results
    baseline_cost_pln: float = 0.0
    project_cost_pln: float = 0.0
    annual_savings_pln: float = 0.0

    # Detailed savings breakdown (optional, for transparency)
    savings_breakdown: Optional[SavingsBreakdown] = Field(
        None,
        description="Detailed breakdown of savings by source (energy, arbitrage, capacity fee, etc.)"
    )

    # Price summary (for transparency - what prices were used)
    # Can be PricesSummary or Dict for ToU detailed breakdown
    prices_summary: Optional[Union[PricesSummary, Dict[str, Any]]] = Field(
        None,
        description="Summary of prices used in simulation (or ToU cost breakdown)"
    )

    # Energy flows SSoT (new in v0.3)
    energy_flows: Optional[EnergyFlows] = Field(
        None,
        description="Detailed energy flows. totals_mwh always present, timeseries_kwh only on request."
    )

    # Economics breakdown SSoT (new in v1.5.0)
    economics_breakdown: Optional[EconomicsBreakdown] = Field(
        None,
        description="Detailed economics breakdown. totals_pln always present, timeseries_pln only on request."
    )

    # Hourly arrays (optional, for charts)
    hourly_charge_kw: Optional[List[float]] = None
    hourly_discharge_kw: Optional[List[float]] = None
    hourly_charge_from_grid_kw: Optional[List[float]] = None
    hourly_soc_pct: Optional[List[float]] = None
    hourly_grid_import_kw: Optional[List[float]] = None
    hourly_grid_export_kw: Optional[List[float]] = None

    # Detailed dispatch (optional)
    hourly_dispatch: Optional[List[HourlyDispatch]] = None

    # Warnings and info
    warnings: List[str] = Field(default_factory=list)
    info: Dict[str, Any] = Field(default_factory=dict)

    # Grid constraint summary (v0.7.0) - tracks cap hits
    constraint_summary: Optional["ConstraintSummary"] = Field(
        None,
        description="Summary of grid constraint impacts (export_cap_hit_steps, curtailed_kwh, etc.)"
    )

    # Debug events summary (v1.8.0) - aggregates constraint/curtail/unserved info for debugging
    debug_events: Optional["DebugEvents"] = Field(
        None,
        description="Summary of debug events (caps/curtail/unserved) for debugging and repro analysis"
    )

    # Battery trace (v2.2.0) - per-step SOC and power flows
    battery_trace: Optional["BatteryTraceTimeseries"] = Field(
        None,
        description="Per-step battery trace if include_battery_trace=True. "
                    "Shows soc_kwh, charge_kw, discharge_kw at each timestep for dispatch debugging."
    )


# =============================================================================
# Sizing Request/Result
# =============================================================================

class GridConstraints(BaseModel):
    """
    Grid connection constraints (v0.7.0).

    Defines physical limits of the grid connection that apply to both
    baseline and project scenarios. These are hard limits that cannot
    be exceeded regardless of battery operation.
    """
    max_export_kw: Optional[float] = Field(
        None,
        ge=0,
        description="Maximum grid export power [kW]. If set, excess PV is curtailed. "
                    "None = no limit (unconstrained export)."
    )
    max_import_kw: Optional[float] = Field(
        None,
        ge=0,
        description="Maximum grid import power [kW]. If set, load exceeding this + PV + battery "
                    "results in unserved load. None = no limit (unconstrained import)."
    )
    allow_export: bool = Field(
        True,
        description="Whether grid export is allowed. If False, all excess PV is curtailed "
                    "or stored in battery. Equivalent to max_export_kw=0."
    )
    unserved_load_penalty_pln_kwh: float = Field(
        0.0,
        ge=0,
        description="Penalty cost per kWh of unserved load [PLN/kWh]. "
                    "Used for economic impact calculation when import cap causes unserved load."
    )


class GridConstraintsApplied(BaseModel):
    """
    Echo of grid constraints applied in calculation (v0.7.0).

    Returned in response so user can verify what constraints were used,
    including computed effective values (e.g., max_export_kw=0 when allow_export=False).
    """
    max_export_kw: Optional[float] = Field(
        None,
        description="Effective max export [kW]. 0 if allow_export=False."
    )
    max_import_kw: Optional[float] = Field(
        None,
        description="Effective max import [kW]. None = unlimited."
    )
    allow_export: bool = Field(
        True,
        description="Whether export was allowed."
    )
    unserved_load_penalty_pln_kwh: float = Field(
        0.0,
        description="Penalty rate for unserved load [PLN/kWh]."
    )


# =============================================================================
# SIZING CONSTRAINTS CONFIG (v0.8.0)
# =============================================================================

class ConstraintsConfig(BaseModel):
    """
    User-defined constraints for BESS sizing optimization (v0.8.0).

    These are soft constraints that filter which variants are considered
    "feasible" for recommendation. Unlike grid_constraints (physical limits),
    these are economic/business constraints that affect variant selection.

    Variants violating constraints are still returned but marked as not feasible.
    """
    max_capex_pln: Optional[float] = Field(
        None,
        ge=0,
        description="Maximum allowed CAPEX [PLN]. Variants exceeding this are not feasible."
    )
    max_payback_years: Optional[float] = Field(
        None,
        ge=0,
        description="Maximum allowed payback period [years]. Variants exceeding this are not feasible."
    )
    min_npv_pln: Optional[float] = Field(
        None,
        description="Minimum required NPV [PLN]. Variants below this are not feasible. "
                    "Can be negative to allow limited losses."
    )
    min_net_savings_pln: Optional[float] = Field(
        None,
        description="Minimum required annual net savings [PLN]. "
                    "Variants below this are not feasible."
    )
    require_no_unserved_load: bool = Field(
        False,
        description="If True, variants with any unserved_load_kwh > 0 are not feasible."
    )
    max_unserved_load_kwh: Optional[float] = Field(
        None,
        ge=0,
        description="Maximum allowed unserved load [kWh]. "
                    "If set, variants exceeding this are not feasible."
    )


class ConstraintViolation(BaseModel):
    """
    Details of a single constraint violation (v0.8.0).

    Used to explain why a variant is not feasible.
    """
    code: str = Field(
        ...,
        description="Constraint code: MAX_CAPEX, MAX_PAYBACK, MIN_NPV, MIN_NET_SAVINGS, "
                    "NO_UNSERVED_LOAD, MAX_UNSERVED_LOAD"
    )
    limit: float = Field(
        ...,
        description="The constraint limit value"
    )
    actual: float = Field(
        ...,
        description="The actual value that violated the constraint"
    )
    unit: str = Field(
        ...,
        description="Unit of measurement (PLN, years, kWh)"
    )
    message: str = Field(
        ...,
        description="Human-readable violation message"
    )


class Feasibility(BaseModel):
    """
    Per-variant feasibility status (v0.8.0).

    Indicates whether a variant satisfies all user-defined constraints.
    """
    is_feasible: bool = Field(
        True,
        description="True if variant satisfies all constraints"
    )
    violations: List[ConstraintViolation] = Field(
        default_factory=list,
        description="List of constraint violations (empty if feasible)"
    )


class ConstraintsReport(BaseModel):
    """
    Summary of constraint evaluation results (v0.8.0).

    Provides overview of how many variants are feasible and which ones.
    """
    applied: bool = Field(
        False,
        description="True if constraints_config was provided in request"
    )
    feasible_count: int = Field(
        0,
        description="Number of feasible variants"
    )
    feasible_variants: List[str] = Field(
        default_factory=list,
        description="List of feasible variant names (e.g., ['small', 'medium'])"
    )
    none_feasible: bool = Field(
        False,
        description="True if no variants are feasible (recommended is fallback)"
    )


class ParetoPoint(BaseModel):
    """
    A point on the Pareto frontier for NPV vs Payback trade-off (v0.8.0).

    A variant is Pareto-optimal (non-dominated) if no other variant has:
    - Higher NPV AND lower payback simultaneously

    Variants on the frontier represent optimal trade-offs.
    """
    variant: str = Field(
        ...,
        description="Variant name (e.g., 'small', 'medium', 'large')"
    )
    npv_pln: float = Field(
        ...,
        description="Net Present Value [PLN]"
    )
    payback_years: float = Field(
        ...,
        description="Simple payback period [years]"
    )
    is_dominated: bool = Field(
        False,
        description="True if this variant is dominated by another (not on Pareto frontier)"
    )


class ConstraintSummary(BaseModel):
    """
    Summary of grid constraint impacts (v0.7.0).

    Tracks how often and how much constraints were hit during dispatch.
    """
    # Export cap (PR 2/6)
    export_cap_hit_steps: int = Field(
        0,
        description="Number of timesteps where export was capped by max_export_kw"
    )
    export_cap_curtailed_kwh: float = Field(
        0.0,
        description="Total energy curtailed due to export cap [kWh]"
    )

    # Import cap (PR 3/6) - to be added later
    import_cap_hit_steps: int = Field(
        0,
        description="Number of timesteps where import was capped by max_import_kw"
    )
    unserved_load_kwh: float = Field(
        0.0,
        description="Total energy unserved due to import cap [kWh]"
    )


class DebugEvents(BaseModel):
    """
    Debug events summary (v1.8.0).

    Aggregates key debugging information from constraint_summary and energy_flows
    into a single, easy-to-read block for debugging and repro analysis.
    """
    # Total timesteps in simulation
    steps: int = Field(0, description="Total number of timesteps in simulation")

    # Export limiting (from constraint_summary)
    export_limited_steps: int = Field(
        0, description="Steps where export was limited by max_export_kw"
    )
    export_limited_mwh: float = Field(
        0.0, description="Total export energy limited [MWh]"
    )

    # Import limiting (from constraint_summary)
    import_limited_steps: int = Field(
        0, description="Steps where import was limited by max_import_kw"
    )
    import_limited_mwh: float = Field(
        0.0, description="Total import energy limited (unserved load) [MWh]"
    )

    # PV curtailment (from energy_flows)
    pv_curtail_steps: int = Field(
        0, description="Steps where PV was curtailed"
    )
    pv_curtail_mwh: float = Field(
        0.0, description="Total PV energy curtailed [MWh]"
    )

    # Unserved load (from constraint_summary or energy_flows)
    unserved_load_steps: int = Field(
        0, description="Steps with unserved load"
    )
    unserved_load_kwh: float = Field(
        0.0, description="Total unserved load [kWh]"
    )


class SizingVariant(str, Enum):
    """Pre-defined sizing variants"""
    SMALL = "small"       # 1h duration
    MEDIUM = "medium"     # 2h duration
    LARGE = "large"       # 4h duration
    CUSTOM = "custom"     # User-defined


class SizingRequest(BaseModel):
    """Request for BESS sizing optimization"""

    # Time series data [kW_avg]
    pv_generation_kw: List[float]
    load_kw: List[float]
    interval_minutes: int = 60

    # Analytical period - SINGLE SOURCE OF TRUTH for time axis
    # If provided, overrides interval_minutes and start_date with period config
    analytical_period: Optional[AnalyticalPeriodConfig] = Field(
        None,
        description="Time axis configuration. If provided, is the single source of truth for time calculations."
    )

    # Profile unit declaration for audit trail
    profile_unit: ProfileUnit = Field(
        ProfileUnit.KW_AVG,
        description="Unit of input profiles (must be kW_avg for sizing)"
    )

    # Dispatch mode
    mode: DispatchMode = Field(DispatchMode.PV_SURPLUS)
    stacked_params: Optional[StackedModeParams] = None
    peak_limit_kw: Optional[float] = None

    # LP solver configuration (v7.0.0)
    solver: SolverType = Field(
        SolverType.LP,
        description="Always 'lp' (v7.0.0). LP is the only dispatch algorithm."
    )
    lp_params: Optional[LPSolverParams] = Field(
        default_factory=LPSolverParams,
        description="LP solver configuration. Defaults are Galileo-proven (34h/24h)."
    )

    # Arbitrage configuration (optional, enables ToU arbitrage in sizing)
    arbitrage_config: Optional[ArbitrageConfig] = Field(
        None,
        description="ToU arbitrage configuration. If enabled, sizing includes arbitrage savings in NPV."
    )

    # Start date for price lookup (required when arbitrage enabled)
    start_date: Optional[str] = Field(
        None,
        description="Start date (YYYY-MM-DD) for tariff price lookup. Required if arbitrage enabled."
    )

    # Period configuration (optional - for explicit time axis specification)
    timezone: Optional[str] = Field(
        None,
        description="Timezone (e.g., 'Europe/Warsaw'). Used for period_info in response."
    )
    period_start: Optional[str] = Field(
        None,
        description="Analysis period start (ISO 8601, e.g., '2025-01-01T00:00:00')"
    )
    period_end: Optional[str] = Field(
        None,
        description="Analysis period end (ISO 8601, e.g., '2025-12-31T23:00:00')"
    )

    # Battery constraints
    min_power_kw: float = Field(10.0, ge=0)
    max_power_kw: float = Field(10000.0, ge=0)
    power_steps: int = Field(15, ge=5, le=50, description="Number of power levels to test in grid search")

    # Duration variants
    durations_h: List[float] = Field([1.0, 2.0, 4.0], description="Duration variants [h]")

    # Battery parameters
    roundtrip_efficiency: float = Field(0.90, ge=0.7, le=1.0)
    soc_min: float = Field(0.10, ge=0.0, le=0.5)
    soc_max: float = Field(0.90, ge=0.5, le=1.0)

    # Degradation and EOL sizing
    # EOL capacity factor: target capacity at end-of-life as % of BOL (beginning-of-life)
    # Example: 0.70 means size battery so that at EOL (after analysis_years) it still has 70% of original
    # Formula: required_bol_capacity = target_eol_capacity / eol_capacity_factor
    # If 0.0 or not set, no EOL adjustment is made (legacy behavior)
    eol_capacity_factor: float = Field(
        0.0, ge=0.0, le=1.0,
        description="Target EOL capacity as fraction of BOL. 0.70 = size for 70% capacity at end of life."
    )
    annual_degradation_pct: float = Field(
        2.0, ge=0.0, le=10.0,
        description="Annual capacity degradation [%/year]. Used to calculate EOL capacity."
    )

    # Economics
    capex_per_kwh: float = Field(1500.0, ge=0, description="CAPEX [PLN/kWh]")
    capex_per_kw: float = Field(300.0, ge=0, description="CAPEX [PLN/kW]")
    opex_pct_per_year: float = Field(0.015, ge=0, le=0.1, description="OPEX as % of CAPEX")
    discount_rate: float = Field(0.07, ge=0, le=0.3)
    analysis_years: int = Field(15, ge=1, le=30)

    # House load / auxiliary consumption (HVAC, BMS, PCS standby)
    house_load_kw_per_mwh: float = Field(
        2.75,
        ge=0, le=10.0,
        description="Continuous auxiliary power draw per MWh of battery capacity [kW/MWh]. "
                    "Covers HVAC, BMS, PCS standby, SCADA. Typical LFP container: 2.5-3.0 kW/MWh."
    )

    # Pricing
    prices: PriceConfig = Field(default_factory=PriceConfig)

    # Degradation cost (general parameter)
    degradation_cost_pln_mwh: float = Field(
        50.0,
        ge=0,
        description="Degradation cost per MWh throughput [PLN/MWh]. Used for savings_breakdown."
    )

    # Degradation budget
    degradation_budget: Optional[DegradationBudget] = None

    # Grid connection limit [kW] - limits battery charging from grid
    # At each hour: grid_import <= grid_connection_kw
    # Battery can only charge from grid up to: grid_connection_kw - current_load_kw
    grid_connection_kw: Optional[float] = Field(
        None, ge=0,
        description="Grid connection capacity [kW]. Limits battery charging from grid."
    )

    # Capacity fee optimization (flatness constraint multi-solve)
    optimize_capacity_fee: bool = Field(
        False,
        description="Enable capacity fee optimization via multi-solve LP."
    )

    # Cable pooling: multiple PV/load profiles behind single connection point
    cable_pooling_profiles: Optional[List["CablePoolingProfile"]] = Field(
        None,
        description="Additional PV/load profiles for cable pooling. "
                    "Main pv_generation_kw/load_kw is always included. "
                    "Additional profiles are summed before dispatch."
    )

    # Parallel sizing
    parallel_workers: int = Field(
        1,
        ge=1, le=8,
        description="Number of parallel workers for sizing grid search. "
                    "Set >1 to parallelize across power levels."
    )

    # Include hourly BESS profiles in response (for K-class capacity fee calculation)
    include_hourly_profiles: bool = Field(
        False,
        description="Include hourly charge_from_grid_kw and discharge_kw arrays in variant response. "
                    "Required for accurate K-class capacity fee scenarios (profile-analysis integration)."
    )

    # Optimization configuration (optional)
    # Note: OptimizationConfig is defined later in file, using forward reference
    optimization: Optional["OptimizationConfig"] = Field(
        None,
        description="Optimization objective and constraints configuration"
    )

    # Energy flows SSoT control (new in v0.3)
    include_energy_flows_timeseries: bool = Field(
        False,
        description="Include per-timestep energy flows in response. "
                    "False = only totals_mwh (small). True = also timeseries_kwh (large)."
    )

    # Economics timeseries control (new in v1.5.0)
    include_economics_timeseries: bool = Field(
        False,
        description="Include per-timestep economics breakdown in response. "
                    "False = only totals_pln (small). True = also timeseries_pln (large)."
    )

    # Money ledger control (new in v1.9.0)
    include_money_ledger: bool = Field(
        False,
        description="Include MoneyLedger (baseline/project cost breakdown) in response. "
                    "Shows all cost categories for transparency and reconciliation."
    )

    # Price timeseries control (new in v2.0.0)
    include_price_timeseries: bool = Field(
        False,
        description="Include PriceTimeseries (per-step prices) in response. "
                    "Shows import/export/fees prices at each timestep for debugging and replay."
    )

    # Ledger timeseries control (new in v2.0.0 PR3)
    include_ledger_timeseries: bool = Field(
        False,
        description="Include LedgerTimeseries (per-step costs) in response. "
                    "Shows import_cost/export_revenue/fees/penalty at each timestep for charts."
    )

    # Battery trace control (new in v2.2.0 PR1)
    include_battery_trace: bool = Field(
        False,
        description="Include BatteryTraceTimeseries (per-step SOC and power flows) in response. "
                    "Shows soc_kwh, charge_kw, discharge_kw at each timestep for dispatch debugging."
    )

    # Timeseries mode controls (new in v2.5.0 PR2)
    # These take precedence over legacy boolean flags when set.
    # Backward compatibility: include_X=True with no mode → FULL (original behavior)
    battery_trace_mode: Optional[str] = Field(
        None,
        description="Mode for battery trace output: 'none', 'preview' (first N rows), or 'full'. "
                    "If set, overrides include_battery_trace flag."
    )
    ledger_timeseries_mode: Optional[str] = Field(
        None,
        description="Mode for ledger timeseries output: 'none', 'preview', or 'full'. "
                    "If set, overrides include_ledger_timeseries flag."
    )
    price_timeseries_mode: Optional[str] = Field(
        None,
        description="Mode for price timeseries output: 'none', 'preview', or 'full'. "
                    "If set, overrides include_price_timeseries flag."
    )
    timeseries_preview_rows: Optional[int] = Field(
        None,
        ge=12, le=240,
        description="Number of rows for 'preview' mode (default 48, min 12, max 240). "
                    "Applies to all timeseries in preview mode."
    )

    # Price timeseries override (new in v2.0.0 PR2)
    price_timeseries_override: Optional["PriceTimeseriesPlnPerMwh"] = Field(
        None,
        description="Explicit price timeseries to use instead of generated ToU prices. "
                    "If provided, bypasses ToU mapping and uses these prices directly. "
                    "Must match input data length (steps = len(load_kw))."
    )

    # Finance configuration (v0.5.0)
    finance_config: Optional["FinanceConfig"] = Field(
        None,
        description="Financial parameters for NPV/cashflow calculation. "
                    "If not provided, uses default values from analysis_years/discount_rate."
    )

    # Grid constraints (v0.7.0)
    grid_constraints: Optional[GridConstraints] = Field(
        None,
        description="Grid connection constraints (max_export_kw, max_import_kw, allow_export). "
                    "Applied to both baseline and project scenarios."
    )

    # Sizing constraints (v0.8.0)
    constraints_config: Optional["ConstraintsConfig"] = Field(
        None,
        description="User-defined constraints for variant selection (max_capex, max_payback, min_npv). "
                    "Variants violating constraints are marked as not feasible but still returned."
    )

    # Ancillary services (v2.0 — uslugi pomocnicze)
    ancillary_services_enabled: bool = Field(
        False,
        description="Enable ancillary services revenue in sizing economics (aFRR, mFRR, FCR, capacity market)"
    )
    ancillary_market_year: int = Field(2026, description="Market preset year for ancillary services")
    ancillary_aggregator_margin_pct: float = Field(20.0, ge=0, le=50, description="Aggregator margin [%]")
    ancillary_services_list: Optional[List[str]] = Field(
        None,
        description="List of enabled services: aFRR_up, aFRR_down, mFRR_up, peak_shaving, energy_arbitrage, fcr, capacity_market"
    )

    @property
    def effective_pv_kw(self) -> List[float]:
        """Get PV array, creating zeros if empty (for LOAD_ONLY mode)"""
        if not self.pv_generation_kw or len(self.pv_generation_kw) == 0:
            return [0.0] * len(self.load_kw)
        return self.pv_generation_kw


class SizingVariantResult(BaseModel):
    """Result for a single sizing variant"""

    # Variant identification
    variant: SizingVariant
    variant_label: str  # e.g., "Small (1h)", "Medium (2h)"
    duration_h: float

    # Optimal sizing
    power_kw: float
    energy_kwh: float
    c_rate: float

    # Economics
    capex_pln: float
    annual_opex_pln: float
    annual_savings_pln: float
    npv_pln: float
    simple_payback_years: float
    irr_pct: Optional[float] = None

    # Dispatch summary
    dispatch_summary: DispatchResult

    # Degradation
    degradation: DegradationMetrics
    degradation_status: DegradationStatus

    # Recommendation score (0-100)
    score: float = 0.0
    is_recommended: bool = False

    # Convenience aliases for frontend (expose nested fields at top level for JSON)
    # These are stored as explicit fields that get populated from dispatch_summary
    savings_breakdown: Optional[SavingsBreakdown] = Field(
        None,
        description="Alias - populated from dispatch_summary.savings_breakdown"
    )
    prices_summary: Optional[Union[PricesSummary, Dict[str, Any]]] = Field(
        None,
        description="Alias - populated from dispatch_summary.prices_summary (ToU breakdown)"
    )

    # Finance summary (v0.5.0) - key financial metrics in one place
    finance_summary: Optional["FinanceSummary"] = Field(
        None,
        description="Financial summary with CAPEX, OPEX, NPV, payback. "
                    "NPV here matches npv_pln used for scoring and top_variants_details."
    )

    # Feasibility (v0.8.0) - constraint satisfaction status
    feasibility: Optional["Feasibility"] = Field(
        None,
        description="Feasibility status based on constraints_config. "
                    "is_feasible=True if variant satisfies all constraints, with violations list."
    )
    
    # Invariants (v1.6.0) - correctness checks
    invariants: Optional[Dict[str, Any]] = Field(
        None,
        description="Invariant check results if include_invariants=True. "
                    "Contains energy_balance_ok, non_negative_ok, cost_sums_ok, annualization_ok."
    )

    # Money ledger (v1.9.0) - cost breakdown SSoT
    money_ledger: Optional["MoneyLedger"] = Field(
        None,
        description="Money ledger with baseline/project cost breakdown if include_money_ledger=True. "
                    "Provides full transparency into cost categories and reconciliation."
    )

    # Price timeseries (v2.0.0) - per-step prices SSoT
    price_timeseries: Optional["PriceTimeseriesPlnPerMwh"] = Field(
        None,
        description="Per-step price timeseries if include_price_timeseries=True. "
                    "Shows import/export/fees prices at each timestep for debugging and replay."
    )
    price_hash: Optional[str] = Field(
        None,
        description="SHA256 hash of canonical price_timeseries JSON. "
                    "Stable identifier for price set - same prices = same hash."
    )
    pricing_mode: Optional[str] = Field(
        None,
        description="Source of prices: 'generated' (from ToU/PriceConfig) or 'override' "
                    "(from price_timeseries_override). Set when include_price_timeseries=True."
    )

    # Ledger timeseries (v2.0.0 PR3) - per-step costs SSoT
    ledger_timeseries: Optional["LedgerTimeseriesPlnPerStep"] = Field(
        None,
        description="Per-step cost timeseries if include_ledger_timeseries=True. "
                    "Shows import_cost/export_revenue/fees/penalty at each timestep for charts."
    )

    # Battery trace (v2.2.0 PR1) - per-step SOC and power flows
    battery_trace: Optional["BatteryTraceTimeseries"] = Field(
        None,
        description="Per-step battery trace if include_battery_trace=True. "
                    "Shows soc_kwh, charge_kw, discharge_kw at each timestep for dispatch debugging."
    )

    # Hourly BESS profiles for K-class capacity fee calculation (v3.0)
    hourly_charge_from_grid_kw: Optional[List[float]] = Field(
        None,
        description="Hourly BESS charging from grid [kW]. Excludes PV-sourced charging. "
                    "Required for accurate K-class capacity fee scenarios."
    )
    hourly_discharge_kw: Optional[List[float]] = Field(
        None,
        description="Hourly BESS discharge [kW]. "
                    "Required for accurate K-class capacity fee scenarios."
    )

    def model_post_init(self, __context):
        """Pydantic v2: populate alias fields after init"""
        if self.dispatch_summary:
            # Use object.__setattr__ to bypass frozen model check
            if self.dispatch_summary.savings_breakdown and self.savings_breakdown is None:
                object.__setattr__(self, 'savings_breakdown', self.dispatch_summary.savings_breakdown)
            if self.dispatch_summary.prices_summary and self.prices_summary is None:
                object.__setattr__(self, 'prices_summary', self.dispatch_summary.prices_summary)


class AppliedParameters(BaseModel):
    """
    Applied parameters used in sizing calculation.

    This shows what default values were actually used, useful for:
    - Debugging: verify which defaults took effect
    - Transparency: user can see exact values used
    - Reproducibility: re-run with explicit values

    Note: Only includes parameters with defaults that affect results.
    """
    # Degradation
    degradation_cost_pln_mwh: float = Field(
        ...,
        description="Degradation cost rate used [PLN/MWh]. "
                    "Default: 50. Set to 0 to disable degradation cost."
    )
    degradation_cost_source: str = Field(
        "default",
        description="Source of degradation cost: 'default', 'request', or 'arbitrage_config'"
    )

    # Economics
    discount_rate: float = Field(..., description="Discount rate used for NPV calculation")
    analysis_years: int = Field(..., description="Analysis period in years")
    opex_pct_per_year: float = Field(..., description="OPEX as % of CAPEX per year")

    # Pricing
    import_price_pln_mwh: float = Field(..., description="Grid import price [PLN/MWh]")
    export_price_pln_mwh: float = Field(0.0, description="Grid export price [PLN/MWh]")


# =============================================================================
# FINANCE CONFIGURATION (v0.5.0)
# =============================================================================

class FinanceConfig(BaseModel):
    """
    Financial parameters for NPV/cashflow calculation.

    This provides explicit control over financial assumptions that affect
    NPV, payback, and IRR calculations. All parameters are optional with
    sensible defaults.

    Note: capex_override_pln enables deterministic tests and what-if scenarios
    without changing battery sizing assumptions.
    """
    horizon_years: int = Field(
        10,
        ge=1, le=30,
        description="Analysis horizon in years for NPV/cashflow calculation"
    )
    discount_rate: float = Field(
        0.08,
        ge=0, le=0.3,
        description="Discount rate for NPV calculation (0.08 = 8%)"
    )
    savings_escalation_rate: float = Field(
        0.0,
        ge=0, le=0.1,
        description="Annual escalation rate for savings (0.02 = 2% per year)"
    )
    opex_pln_per_year: float = Field(
        0.0,
        ge=0,
        description="Fixed annual OPEX in PLN (added to % based OPEX)"
    )
    opex_escalation_rate: float = Field(
        0.0,
        ge=0, le=0.1,
        description="Annual escalation rate for OPEX (0.02 = 2% per year)"
    )
    capex_override_pln: Optional[float] = Field(
        None,
        ge=0,
        description="Override CAPEX for deterministic tests and what-if scenarios. "
                    "If None, CAPEX is calculated from battery sizing."
    )
    include_cashflow_timeseries: bool = Field(
        False,
        description="If True, include year-by-year cashflow_timeseries in finance_summary."
    )
    discount_rate_sweep: Optional[List[float]] = Field(
        None,
        description="List of discount rates (e.g., [0.05, 0.08, 0.10, 0.12]) for sensitivity analysis. "
                    "If provided, finance_summary will include discount_rate_sensitivity array."
    )
    # Battery replacement (v0.6.0)
    replacement_year: Optional[int] = Field(
        None,
        ge=1, le=30,
        description="Year for battery replacement (e.g., 10). If None, no replacement event."
    )
    replacement_capex_pln: Optional[float] = Field(
        None,
        ge=0,
        description="Replacement cost in PLN. If None, uses original CAPEX."
    )
    # Performance degradation (v0.6.0 PR3, v1.2.0: calendar aging year 1)
    bess_degradation_year1_pct: float = Field(
        5.0,
        ge=0, le=20.0,
        description="BESS calendar degradation in year 1 [%]. Formation loss - typically higher than subsequent years. "
                    "E.g., 5.0 = 5% capacity loss in first year."
    )
    bess_degradation_pct_per_year: float = Field(
        2.0,
        ge=0, le=10.0,
        description="BESS calendar degradation [%/year] for years 2+. "
                    "E.g., 2.0 = 2% annual degradation."
    )
    pv_degradation_pct_per_year: float = Field(
        0.0,
        ge=0, le=5.0,
        description="PV output degradation [%/year]. Applied to savings as (1 - rate)^year. "
                    "E.g., 0.5 = 0.5% annual degradation."
    )
    # Throughput-based degradation (pagra-galileo SoH curve model)
    bess_degradation_model: str = Field(
        "linear",
        description="Degradation model: 'linear' (% per year) or 'throughput' (cycle-based SoH curve). "
                    "When 'throughput', uses cycles_to_eol and eol_soh_pct to build SoH curve."
    )
    cycles_to_eol: float = Field(
        6000.0,
        ge=100, le=20000,
        description="Number of full equivalent cycles to end-of-life SoH. "
                    "Typical LFP: 6000, NMC: 3000-4000."
    )
    eol_soh_pct: float = Field(
        70.0,
        ge=50, le=90,
        description="State of Health at end-of-life [%]. Typically 70% or 80%."
    )
    degradation_curve: str = Field(
        "linear",
        description="SoH curve shape: 'linear' (straight line) or 'sqrt' (fast early, slow late)."
    )
    # Seller margin
    seller_margin_pct: float = Field(
        0.0,
        ge=0, le=50.0,
        description="Seller/integrator margin [%] applied on top of CAPEX. "
                    "E.g., 15.0 = 15% margin added to equipment cost."
    )
    # Sensitivity sweeps (v0.6.0 PR4)
    energy_price_multiplier_sweep: Optional[List[float]] = Field(
        None,
        description="Energy price multipliers for sensitivity analysis (e.g., [0.8, 1.0, 1.2]). "
                    "NPV calculated at each multiplier. Results in energy_price_sensitivity."
    )
    capex_multiplier_sweep: Optional[List[float]] = Field(
        None,
        description="CAPEX multipliers for sensitivity analysis (e.g., [0.8, 1.0, 1.2]). "
                    "NPV calculated at each multiplier. Results in capex_sensitivity."
    )


class FinanceAssumptions(BaseModel):
    """
    Echo of finance parameters applied in calculation.

    Returned in response so user can verify what values were used,
    especially when using defaults.
    """
    horizon_years: int = Field(..., description="Analysis horizon used")
    discount_rate: float = Field(..., description="Discount rate used")
    savings_escalation_rate: float = Field(..., description="Savings escalation rate used")
    opex_pln_per_year: float = Field(..., description="Fixed OPEX per year used")
    opex_escalation_rate: float = Field(..., description="OPEX escalation rate used")
    capex_override_pln: Optional[float] = Field(
        None,
        description="CAPEX override if provided, None if using calculated CAPEX"
    )
    # Battery replacement (v0.6.0)
    replacement_year: Optional[int] = Field(
        None,
        description="Year for battery replacement, None if no replacement"
    )
    replacement_capex_pln: Optional[float] = Field(
        None,
        description="Replacement cost used, None if no replacement"
    )
    # Performance degradation (v0.6.0 PR3)
    bess_degradation_pct_per_year: float = Field(
        0.0,
        description="BESS capacity degradation [%/year]"
    )
    pv_degradation_pct_per_year: float = Field(
        0.0,
        description="PV output degradation [%/year]"
    )


class FinanceSummary(BaseModel):
    """
    Financial summary per variant.

    Provides key financial metrics in one place for easy UI display.
    NPV here is the same value used for scoring (when objective=npv)
    and displayed in top_variants_details.
    """
    capex_pln: float = Field(..., description="Total CAPEX for this variant [PLN]")
    opex_pln_per_year: float = Field(..., description="Annual OPEX [PLN/year]")
    horizon_years: int = Field(..., description="Analysis horizon [years]")
    discount_rate: float = Field(..., description="Discount rate used")
    npv_pln: float = Field(..., description="Net Present Value [PLN]")
    payback_years: float = Field(..., description="Simple payback period [years]")
    irr_pct: Optional[float] = Field(
        None,
        description="Internal Rate of Return [%]. Null if IRR not calculated."
    )
    # Cashflow timeseries (optional, only when include_cashflow_timeseries=True)
    cashflow_timeseries: Optional[List["CashflowYear"]] = Field(
        None,
        description="Year-by-year cashflow breakdown. Only present when include_cashflow_timeseries=True."
    )
    # Discount rate sensitivity (optional, only when discount_rate_sweep provided)
    discount_rate_sensitivity: Optional[List["DiscountRateSensitivityPoint"]] = Field(
        None,
        description="NPV at different discount rates. Only present when discount_rate_sweep provided."
    )
    # Energy price sensitivity (optional, v0.6.0 PR4)
    energy_price_sensitivity: Optional[List["MultiplierSensitivityPoint"]] = Field(
        None,
        description="NPV at different energy price multipliers. Only present when energy_price_multiplier_sweep provided."
    )
    # CAPEX sensitivity (optional, v0.6.0 PR4)
    capex_sensitivity: Optional[List["MultiplierSensitivityPoint"]] = Field(
        None,
        description="NPV at different CAPEX multipliers. Only present when capex_multiplier_sweep provided."
    )


class CashflowYear(BaseModel):
    """
    Annual cashflow data for a single year.

    Used for building cashflow tables and charts in UI.
    Year 0 represents the initial investment (negative CAPEX).
    """
    year: int = Field(..., description="Year number (0 = investment, 1-N = operating years)")
    savings_pln: float = Field(..., description="Annual savings [PLN]. 0 for year 0.")
    opex_pln: float = Field(..., description="Annual OPEX [PLN]. 0 for year 0.")
    net_cashflow_pln: float = Field(
        ...,
        description="Net cashflow = savings - opex (year > 0), or -capex (year 0)"
    )
    cumulative_cashflow_pln: float = Field(
        ...,
        description="Cumulative undiscounted cashflow up to this year"
    )
    discounted_cashflow_pln: float = Field(
        ...,
        description="Net cashflow discounted to year 0"
    )
    nominal_cashflow_pln: Optional[float] = Field(
        None,
        description="Undiscounted net cashflow = net_cashflow_pln (for IRR calculation convenience)"
    )


class DiscountRateSensitivityPoint(BaseModel):
    """
    NPV at a specific discount rate.

    Used for discount rate sensitivity charts showing how NPV varies
    with different discount rate assumptions.
    """
    discount_rate: float = Field(
        ...,
        description="Discount rate (0.05 = 5%)"
    )
    discount_rate_pct: float = Field(
        ...,
        description="Discount rate as percentage (5.0 = 5%)"
    )
    npv_pln: float = Field(
        ...,
        description="NPV at this discount rate [PLN]"
    )


class MultiplierSensitivityPoint(BaseModel):
    """
    NPV at a specific multiplier value (v0.6.0 PR4).

    Used for energy price and CAPEX sensitivity charts showing how NPV varies
    with different price/cost assumptions.
    """
    multiplier: float = Field(
        ...,
        description="Multiplier value (1.0 = 100%, 0.8 = 80%, 1.2 = 120%)"
    )
    multiplier_pct: float = Field(
        ...,
        description="Multiplier as percentage (100.0 = 100%)"
    )
    npv_pln: float = Field(
        ...,
        description="NPV at this multiplier [PLN]"
    )


class TopVariantDetail(BaseModel):
    """
    Detailed information about a top variant for UI display.

    Contains key metrics for easy comparison in a table/list view.
    """
    variant: SizingVariant = Field(..., description="Variant name (small/medium/large)")
    score: float = Field(..., description="Optimization score (higher is better)")
    npv_pln: float = Field(..., description="Net Present Value [PLN]")
    payback_years: float = Field(..., description="Simple payback period [years]")
    net_savings_pln: float = Field(..., description="Net annual savings from savings_breakdown [PLN]")


class SizingResult(BaseModel):
    """Complete sizing result with all variants"""

    # API versioning - for frontend/backend compatibility
    schema_version: str = Field(
        "1.0.0",
        description="API schema version. Bump when response structure changes."
    )
    assumptions_version: str = Field(
        "v1.0-unknown",
        description="Assumptions version (hash of docs/assumptions.yaml)."
    )

    # Input summary
    mode: DispatchMode
    total_pv_mwh: float
    total_load_mwh: float
    annual_surplus_mwh: float

    # Analytical period - SSoT for time axis (replaces hardcoded 8760)
    period_info: Optional[PeriodInfo] = Field(
        None,
        description="Time axis metadata. period_hours replaces hardcoded 8760."
    )

    # Sizing variants
    variants: List[SizingVariantResult]

    # Recommended variant
    recommended_variant: Optional[SizingVariant] = None
    recommended_power_kw: float = 0.0
    recommended_energy_kwh: float = 0.0
    recommended_reason: Optional[str] = Field(
        None,
        description="Human-readable explanation of why this variant was recommended. "
                    "Example: 'Highest NPV (45,230 PLN) among variants with payback < 8 years'"
    )

    # Structured reason fields (machine-readable, stable API)
    recommended_reason_code: Optional[str] = Field(
        None,
        description="Machine-readable code for recommendation reason. "
                    "Values: npv_max, payback_min, self_consumption_max, peak_reduction_max, "
                    "efc_utilization_max, constrained_fallback"
    )
    recommended_reason_metric: Optional[str] = Field(
        None,
        description="Metric name used for recommendation. "
                    "Values: npv_pln, payback_years, self_consumption_pct, peak_reduction_pct, efc_total"
    )
    recommended_reason_value: Optional[float] = Field(
        None,
        description="Numeric value of the recommendation metric. Example: 45230.0 for NPV"
    )
    recommended_reason_unit: Optional[str] = Field(
        None,
        description="Unit for the recommendation metric value. "
                    "Values: PLN, years, %, cycles"
    )

    # Top variants (ranked by score, best first)
    top_variants: Optional[List[SizingVariant]] = Field(
        None,
        description="Top 3 variants ranked by score (highest first). "
                    "Useful for UI to show alternatives. Example: ['medium', 'large', 'small']"
    )

    # Top variants with details (for UI comparison tables)
    top_variants_details: Optional[List[TopVariantDetail]] = Field(
        None,
        description="Top 3 variants with key metrics for easy comparison. "
                    "First element is always the recommended variant."
    )

    # Optimization objective used
    objective_used: Optional[str] = Field(
        None,
        description="Optimization objective that was used. Default is 'npv'. "
                    "Values: npv, payback, self_consumption, peak_reduction, efc_utilization"
    )

    # Pareto frontier (v0.8.0)
    pareto_frontier: Optional[List["ParetoPoint"]] = Field(
        None,
        description="Pareto frontier for NPV vs Payback trade-off. "
                    "Variants with is_dominated=False are on the frontier."
    )

    # Applied parameters - SSoT for debugging and transparency
    applied_parameters: Optional[AppliedParameters] = Field(
        None,
        description="Parameters actually used in calculation. "
                    "Shows effective defaults and sources for transparency."
    )

    # Finance assumptions (v0.5.0) - echo of finance_config values used
    finance_assumptions: Optional[FinanceAssumptions] = Field(
        None,
        description="Echo of finance parameters applied in calculation. "
                    "Shows what values were used (explicit or defaults)."
    )

    # Grid constraints applied (v0.7.0) - echo of grid constraints used
    grid_constraints_applied: Optional[GridConstraintsApplied] = Field(
        None,
        description="Echo of grid constraints applied in calculation. "
                    "Shows effective values (e.g., max_export_kw=0 when allow_export=False)."
    )

    # Constraints report (v0.8.0) - summary of constraint evaluation
    constraints_report: Optional[ConstraintsReport] = Field(
        None,
        description="Summary of constraint evaluation: how many variants are feasible, "
                    "which ones, and whether recommended is fallback due to none_feasible."
    )

    # Cache info (v0.9.0) - request hash and run_id for caching
    cache_info: Optional["CacheInfo"] = Field(
        None,
        description="Cache metadata including request_hash, run_id, and cache_status. "
                    "Enables deterministic result retrieval and debugging."
    )

    # Timeseries info (v2.5.0 PR2) - metadata about truncation
    timeseries_info: Optional[Dict[str, Any]] = Field(
        None,
        description="Timeseries throttling metadata. Shows mode, included_steps, total_steps, "
                    "and truncated flag for each timeseries type (battery_trace, ledger, price)."
    )

    # Stacked decomposition (v3.1.0) - separate Peak Shaving & Arbitrage components
    stacked_decomposition: Optional[StackedDecompositionModel] = Field(
        None,
        description="For STACKED mode: decomposition into Peak Shaving and Arbitrage components. "
                    "Shows how total BESS size = peak_shaving + arbitrage. "
                    "Enables transparent sizing rationale for dual-service BESS."
    )

    # Grid search results - ALL evaluated power x duration combinations
    grid_search_results: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="All evaluated grid points (power x duration). Each point has: "
                    "power_kw, energy_kwh, duration_h, capex_pln, annual_savings_pln, "
                    "npv_pln, npv_per_kwh, payback_years, efc_total, self_consumption_pct, "
                    "peak_reduction_pct. Sorted by npv_per_kwh descending."
    )

    # Warnings
    warnings: List[str] = Field(default_factory=list)

    # BESS Advisor response (v3.0.0) - intelligent recommendations
    advisor_response: Optional[Dict[str, Any]] = Field(
        None,
        description="BESS Advisor generated response with markdown text, "
                    "recommended SKU configuration, alternatives, and warnings. "
                    "Includes snap-to-market adjustments for real products."
    )


# =============================================================================
# Unit Conversion Utilities
# =============================================================================

def convert_profile_to_kw_avg(
    values: List[float],
    source_unit: ProfileUnit,
    interval_minutes: int,
) -> List[float]:
    """
    Convert power/energy profile to kW_avg (average power over interval).

    Parameters:
    -----------
    values : List[float]
        Input values in source_unit
    source_unit : ProfileUnit
        Unit of input values
    interval_minutes : int
        Interval duration (15 or 60)

    Returns:
    --------
    List[float] : Values converted to kW_avg

    Examples:
    ---------
    # 100 kWh over 1 hour = 100 kW_avg
    convert_profile_to_kw_avg([100], ProfileUnit.KWH, 60)  # -> [100.0]

    # 25 kWh over 15 min = 100 kW_avg
    convert_profile_to_kw_avg([25], ProfileUnit.KWH, 15)   # -> [100.0]
    """
    if source_unit == ProfileUnit.KW_AVG:
        return values  # No conversion needed

    dt_hours = interval_minutes / 60.0

    if source_unit == ProfileUnit.KWH:
        # Energy to average power: P_avg = E / dt
        return [v / dt_hours for v in values]

    if source_unit == ProfileUnit.KW_PEAK:
        # Peak power to average power
        # Without sub-interval data, assume avg = 0.8 * peak (typical for PV)
        # This is a rough approximation - better to use actual kW_avg data
        return [v * 0.8 for v in values]

    return values


class ResamplingMethod(str, Enum):
    """Methods for resampling time series data"""
    NONE = "none"                       # No resampling applied
    INTERPOLATE_LINEAR = "linear"       # Linear interpolation (for upsampling)
    REPEAT = "repeat"                   # Repeat values (for upsampling)
    AGGREGATE_SUM = "sum"               # Sum values (for downsampling energy)
    AGGREGATE_MEAN = "mean"             # Average values (for downsampling power)


def resample_hourly_to_15min(
    hourly_data: List[float],
    method: ResamplingMethod = ResamplingMethod.REPEAT,
) -> List[float]:
    """
    Resample hourly (60-min) data to 15-min intervals.

    Energy Conservation Property:
    - For power profiles (kW_avg): sum remains the same (repeat preserves avg)
    - Hourly energy = sum(hourly_kw) * 1h
    - 15min energy = sum(15min_kw) * 0.25h = sum(hourly_kw) * 4 * 0.25h = same

    Parameters:
    -----------
    hourly_data : List[float]
        Input data with 60-min resolution (length N, typically 8760)
    method : ResamplingMethod
        REPEAT: Each hourly value repeated 4 times (default, energy-conserving)
        INTERPOLATE_LINEAR: Linear interpolation between hours

    Returns:
    --------
    List[float] : Data with 15-min resolution (length 4*N, typically 35040)

    Examples:
    ---------
    # 8760 hourly -> 35040 quarter-hourly
    data_15min = resample_hourly_to_15min(data_1h)
    assert len(data_15min) == 4 * len(data_1h)

    # Energy conservation check
    energy_1h = sum(data_1h) * 1.0  # kWh
    energy_15min = sum(data_15min) * 0.25  # kWh
    assert abs(energy_1h - energy_15min) < 0.001
    """
    n = len(hourly_data)

    if method == ResamplingMethod.REPEAT:
        # Repeat each value 4 times - preserves average power
        result = []
        for v in hourly_data:
            result.extend([v, v, v, v])
        return result

    elif method == ResamplingMethod.INTERPOLATE_LINEAR:
        # Linear interpolation between hourly midpoints
        # Hour boundaries are at 0, 1, 2, ... h
        # 15-min points at 0, 0.25, 0.5, 0.75, 1.0, ...
        result = []
        for i in range(n):
            v_curr = hourly_data[i]
            v_next = hourly_data[i + 1] if i < n - 1 else hourly_data[i]

            # 4 quarter-hourly values within this hour
            for j in range(4):
                t = j / 4  # 0, 0.25, 0.5, 0.75
                result.append(v_curr * (1 - t) + v_next * t)

        return result

    else:
        # Default to repeat
        return resample_hourly_to_15min(hourly_data, ResamplingMethod.REPEAT)


def resample_15min_to_hourly(
    data_15min: List[float],
    method: ResamplingMethod = ResamplingMethod.AGGREGATE_MEAN,
) -> List[float]:
    """
    Resample 15-min data to hourly (60-min) intervals.

    Parameters:
    -----------
    data_15min : List[float]
        Input data with 15-min resolution (length 4*N)
    method : ResamplingMethod
        AGGREGATE_MEAN: Average of 4 values (for power, preserves energy)
        AGGREGATE_SUM: Sum of 4 values (for counts/events)

    Returns:
    --------
    List[float] : Data with 60-min resolution (length N)

    Energy Conservation:
    - For kW_avg profiles, use AGGREGATE_MEAN
    - Energy_1h = hourly_avg * 1.0h = mean(4 values) * 1.0h
    - Energy_15min = sum(4 values) * 0.25h = mean(4 values) * 1.0h
    """
    n = len(data_15min)
    if n % 4 != 0:
        raise ValueError(f"15-min data length must be divisible by 4, got {n}")

    n_hours = n // 4
    result = []

    for h in range(n_hours):
        chunk = data_15min[h * 4 : (h + 1) * 4]
        if method == ResamplingMethod.AGGREGATE_MEAN:
            result.append(sum(chunk) / 4)
        elif method == ResamplingMethod.AGGREGATE_SUM:
            result.append(sum(chunk))
        else:
            result.append(sum(chunk) / 4)  # Default to mean

    return result


class AuditMetadata(BaseModel):
    """
    Audit metadata for reproducibility.

    Included in DispatchResult.info to enable external verification.
    """
    engine_version: str = Field(ENGINE_VERSION, description="Dispatch engine version")
    profile_unit: ProfileUnit = Field(ProfileUnit.KW_AVG, description="Input profile unit")
    interval_minutes: int = Field(60, description="Time interval [min]")
    resampling_method: ResamplingMethod = Field(
        ResamplingMethod.NONE,
        description="Resampling method applied to input data"
    )
    source_interval_minutes: Optional[int] = Field(
        None,
        description="Original interval before resampling (if resampled)"
    )


# =============================================================================
# Optimization Objectives and Constraints
# =============================================================================

class OptimizationObjective(str, Enum):
    """
    Optimization objectives for BESS sizing (v4.5.0 - extended).

    Determines which metric is maximized/minimized during grid search.
    """
    NPV = "npv"                             # Maximize Net Present Value (default)
    IRR = "irr"                             # Maximize Internal Rate of Return
    PAYBACK = "payback"                     # Minimize Simple Payback Period
    SELF_CONSUMPTION = "self_consumption"   # Maximize self-consumption %
    SELF_CONSUMPTION_RATE = "self_consumption_rate"  # Alias for self_consumption
    PEAK_REDUCTION = "peak_reduction"       # Maximize peak reduction %
    EFC_UTILIZATION = "efc_utilization"     # Maximize EFC utilization within budget
    LCOS = "lcos"                           # Minimize Levelized Cost of Storage [PLN/MWh]
    LCOE = "lcoe"                           # Alias for LCOS (maps to lcos internally)
    RESILIENCE = "resilience"               # Minimize unserved load / maximize backup capability


class RecommendedReasonCode(str, Enum):
    """
    Machine-readable codes for recommended variant selection reason (v4.5.0 - extended).

    UI can use these codes to generate localized descriptions.
    """
    NPV_MAX = "npv_max"                         # Highest NPV selected
    IRR_MAX = "irr_max"                         # Highest IRR selected
    PAYBACK_MIN = "payback_min"                 # Shortest payback selected
    SELF_CONSUMPTION_MAX = "self_consumption_max"  # Highest self-consumption %
    PEAK_REDUCTION_MAX = "peak_reduction_max"   # Highest peak reduction %
    EFC_UTILIZATION_MAX = "efc_utilization_max" # Optimal EFC utilization
    LCOS_MIN = "lcos_min"                       # Lowest LCOS selected
    RESILIENCE_MAX = "resilience_max"           # Best resilience (min unserved load)
    NPV_NEAR_OPTIMAL_TIE_BREAK = "npv_near_optimal_tie_break"  # Near-optimal NPV with tie-breaker
    CONSTRAINED_FALLBACK = "constrained_fallback"  # Best within constraints


class ConstraintType(str, Enum):
    """Types of constraints for BESS sizing"""
    MAX_CAPEX = "max_capex"                 # Maximum CAPEX [PLN]
    MAX_PAYBACK = "max_payback"             # Maximum payback [years]
    MIN_NPV = "min_npv"                     # Minimum NPV [PLN]
    MAX_EFC = "max_efc"                     # Maximum EFC per year
    MIN_SELF_CONSUMPTION = "min_self_consumption"  # Minimum self-consumption [%]


class SizingConstraint(BaseModel):
    """Single constraint for BESS sizing optimization"""
    constraint_type: ConstraintType
    value: float = Field(..., description="Constraint value")
    hard: bool = Field(True, description="Hard constraint (reject) vs soft (penalty)")


class OptimizationConfig(BaseModel):
    """
    Configuration for multi-objective optimization.

    Allows users to specify:
    - Primary objective to optimize
    - Hard/soft constraints to satisfy
    """
    objective: OptimizationObjective = Field(
        OptimizationObjective.NPV,
        description="Primary optimization objective"
    )
    constraints: List[SizingConstraint] = Field(
        default_factory=list,
        description="List of sizing constraints"
    )
    constraint_penalty_weight: float = Field(
        0.3,
        ge=0.0,
        le=1.0,
        description="Weight for soft constraint penalties (0-1)"
    )

    def has_constraint(self, constraint_type: ConstraintType) -> bool:
        """Check if a specific constraint type is defined"""
        return any(c.constraint_type == constraint_type for c in self.constraints)

    def get_constraint(self, constraint_type: ConstraintType) -> Optional[SizingConstraint]:
        """Get constraint by type"""
        for c in self.constraints:
            if c.constraint_type == constraint_type:
                return c
        return None


# =============================================================================
# Decision Drivers v4.5.0 - Recommendation Policy + Variant Space + Profiles
# =============================================================================

class OptimizationProfile(str, Enum):
    """
    Predefined optimization profiles (v4.5.0).

    Each profile maps to a primary objective and default recommendation policy.
    """
    BALANCED = "balanced"                       # NPV with tie-breakers for self-consumption/payback
    COMMERCIAL_PEAK_SHAVING = "commercial_peak_shaving"  # Peak reduction focus
    PV_SELF_CONSUMPTION = "pv_self_consumption"  # Maximize self-consumption rate
    ARBITRAGE = "arbitrage"                     # NPV with grid charging enabled
    RESILIENCE_BACKUP = "resilience_backup"     # Minimize unserved load


class RecommendationPolicy(BaseModel):
    """
    Policy for selecting recommended variant (v4.5.0).

    Enables near-optimal selection with tie-breakers to avoid
    always picking 1h duration when NPV difference is minimal.
    """
    near_optimal_tolerance_pct: float = Field(
        5.0,
        ge=0.0,
        le=50.0,
        description="Tolerance for near-optimal variants (% from best). "
                    "E.g., 5% means variants within 5% of best NPV are considered."
    )
    tie_breakers: List[str] = Field(
        default_factory=lambda: ["self_consumption_rate", "payback_years", "peak_reduction_kw"],
        description="Ordered list of metrics for tie-breaking within near-optimal set. "
                    "Applied in order until a winner is found."
    )
    min_npv_pln: Optional[float] = Field(
        None,
        description="Minimum NPV constraint for non-NPV objectives. "
                    "Variants with NPV below this are excluded from selection."
    )

    @model_validator(mode='after')
    def validate_tie_breakers(self):
        """Validate tie-breaker metric names."""
        valid_metrics = {
            "self_consumption_rate", "payback_years", "peak_reduction_kw",
            "npv_pln", "irr_pct", "lcos_pln_per_mwh", "duration_h",
            "capex_pln", "net_savings_pln", "resilience_unserved_load_kwh"
        }
        for tb in self.tie_breakers:
            if tb not in valid_metrics:
                raise ValueError(
                    f"Invalid tie-breaker '{tb}'. "
                    f"Valid values: {sorted(valid_metrics)}"
                )
        return self


class VariantSpace(BaseModel):
    """
    Custom variant space definition (v4.5.0).

    Allows explicit specification of power x duration grid
    instead of automatic power range with fixed durations.
    """
    power_kw_candidates: List[float] = Field(
        default_factory=list,
        description="Explicit power candidates [kW]. If empty, uses min/max/steps from request."
    )
    duration_h_candidates: List[float] = Field(
        default_factory=lambda: [1.0, 2.0, 4.0],
        description="Duration candidates [hours]. Grid is power x duration."
    )
    max_variants: int = Field(
        60,
        ge=1,
        le=200,
        description="Maximum variants to evaluate (guard against explosion). "
                    "Returns 422 if grid exceeds this limit."
    )

    @model_validator(mode='after')
    def validate_variant_count(self):
        """Validate variant count is within limits."""
        if self.power_kw_candidates:
            grid_size = len(self.power_kw_candidates) * len(self.duration_h_candidates)
            if grid_size > self.max_variants:
                raise ValueError(
                    f"Variant grid size ({grid_size}) exceeds max_variants ({self.max_variants}). "
                    f"Reduce power_kw_candidates or duration_h_candidates."
                )
        return self


class DriverRecommendation(BaseModel):
    """
    Single recommendation for a specific objective/driver (v4.5.0).

    Response includes one recommendation per active driver.
    """
    objective: str = Field(..., description="Objective/driver name (e.g., 'npv', 'lcos')")
    variant: str = Field(..., description="Recommended variant name (e.g., 'medium', '2h_100kW')")
    variant_label: Optional[str] = Field(None, description="Human-readable variant label")
    reason_code: str = Field(..., description="Machine-readable reason code")
    reason_metric: str = Field(..., description="Metric used for selection")
    reason_value: float = Field(..., description="Value of the metric")
    reason_unit: str = Field(..., description="Unit of the metric (e.g., 'PLN', 'ratio', 'years')")
    is_near_optimal: bool = Field(False, description="True if selected via near-optimal tie-break")
    tie_breaker_used: Optional[str] = Field(None, description="Tie-breaker metric if near-optimal")


class DurationSweepPoint(BaseModel):
    """Single point in duration sweep analysis (v4.5.0)."""
    duration_h: float = Field(..., description="Duration [hours]")
    npv_pln: float = Field(..., description="NPV [PLN]")
    payback_years: Optional[float] = Field(None, description="Payback [years]")
    self_consumption_rate: Optional[float] = Field(None, description="Self-consumption rate [0-1]")
    lcos_pln_per_mwh: Optional[float] = Field(None, description="LCOS [PLN/MWh]")
    power_kw: Optional[float] = Field(None, description="Representative power for this duration")


class MarginalMetrics(BaseModel):
    """Marginal value metrics for capacity additions (v4.5.0)."""
    marginal_npv_pln_per_added_kwh: Optional[float] = Field(
        None,
        description="Marginal NPV per additional kWh capacity"
    )
    marginal_net_savings_pln_per_added_kwh: Optional[float] = Field(
        None,
        description="Marginal net savings per additional kWh capacity"
    )
    marginal_self_consumption_pct_per_added_kwh: Optional[float] = Field(
        None,
        description="Marginal self-consumption improvement per additional kWh"
    )


# =============================================================================
# Sensitivity Analysis (Tornado Chart)
# =============================================================================

class SensitivityParameter(str, Enum):
    """Parameters available for sensitivity analysis"""
    ENERGY_PRICE = "energy_price"           # PLN/MWh
    CAPEX_PER_KWH = "capex_per_kwh"         # PLN/kWh
    CAPEX_PER_KW = "capex_per_kw"           # PLN/kW
    DISCOUNT_RATE = "discount_rate"          # %
    ROUNDTRIP_EFFICIENCY = "efficiency"      # %
    OPEX_PCT = "opex_pct"                    # %/year


class SensitivityRange(BaseModel):
    """Range for a single sensitivity parameter"""
    parameter: SensitivityParameter
    low_pct: float = Field(-20.0, description="Low deviation from base (%)")
    high_pct: float = Field(20.0, description="High deviation from base (%)")
    base_value: Optional[float] = Field(None, description="Base value (from request if None)")


class SensitivityRequest(BaseModel):
    """Request for sensitivity analysis with fixed BESS size"""

    # Time series (required for dispatch)
    pv_generation_kw: List[float] = Field(..., min_items=24)
    load_kw: List[float] = Field(..., min_items=24)
    interval_minutes: int = Field(60)

    # Fixed BESS size (from previous sizing result)
    battery_power_kw: float = Field(..., gt=0, description="Fixed BESS power [kW]")
    battery_energy_kwh: float = Field(..., gt=0, description="Fixed BESS capacity [kWh]")

    # Battery parameters
    roundtrip_efficiency: float = Field(0.90, ge=0.7, le=1.0)
    soc_min: float = Field(0.10, ge=0.0, le=0.5)
    soc_max: float = Field(0.90, ge=0.5, le=1.0)

    # Mode
    mode: DispatchMode = Field(DispatchMode.PV_SURPLUS)
    peak_limit_kw: Optional[float] = None
    reserve_fraction: float = Field(0.3, ge=0.0, le=0.8)

    # Economic parameters (base values)
    capex_per_kwh: float = Field(1500.0, ge=0)
    capex_per_kw: float = Field(300.0, ge=0)
    opex_pct_per_year: float = Field(0.015, ge=0, le=0.1)
    discount_rate: float = Field(0.07, ge=0, le=0.3)
    analysis_years: int = Field(15, ge=1, le=30)
    import_price_pln_mwh: float = Field(800.0, ge=0)

    # Sensitivity configuration
    parameters: List[SensitivityRange] = Field(
        default_factory=lambda: [
            SensitivityRange(parameter=SensitivityParameter.ENERGY_PRICE),
            SensitivityRange(parameter=SensitivityParameter.CAPEX_PER_KWH),
            SensitivityRange(parameter=SensitivityParameter.DISCOUNT_RATE),
            SensitivityRange(parameter=SensitivityParameter.ROUNDTRIP_EFFICIENCY),
        ],
        description="Parameters to analyze (default: price, capex, discount, efficiency)"
    )


class SensitivityPoint(BaseModel):
    """Result for a single sensitivity point"""
    parameter: SensitivityParameter
    parameter_label: str
    deviation_pct: float           # e.g., -20, 0, +20
    parameter_value: float         # Actual parameter value used
    npv_pln: float
    npv_delta_pln: float           # Difference from base NPV
    npv_delta_pct: float           # Percentage change from base NPV
    payback_years: float


class SensitivityParameterResult(BaseModel):
    """Result for one parameter's sensitivity range"""
    parameter: SensitivityParameter
    parameter_label: str
    base_value: float
    unit: str

    # Low point
    low_value: float
    low_npv_pln: float
    low_npv_delta_pct: float

    # High point
    high_value: float
    high_npv_pln: float
    high_npv_delta_pct: float

    # Swing (for sorting tornado bars)
    npv_swing_pln: float           # |high_npv - low_npv|
    npv_swing_pct: float           # swing as % of base NPV


class SensitivityResult(BaseModel):
    """Complete sensitivity analysis result"""

    # Fixed BESS configuration
    battery_power_kw: float
    battery_energy_kwh: float
    duration_h: float

    # Base case economics
    base_npv_pln: float
    base_payback_years: float
    base_annual_savings_pln: float
    base_capex_pln: float

    # Parameter results (sorted by swing for tornado chart)
    parameters: List[SensitivityParameterResult]

    # All points for detailed charts
    all_points: List[SensitivityPoint]

    # Summary
    most_sensitive_parameter: str
    least_sensitive_parameter: str
    breakeven_scenarios: List[str]  # Parameters where NPV crosses zero


# =============================================================================
# Batch Sizing (v0.9.0)
# =============================================================================

class BatchItemStatus(str, Enum):
    """Status of individual batch item"""
    OK = "ok"           # Item processed successfully
    ERROR = "error"     # Item failed to process


class BatchSizingItem(BaseModel):
    """Single item in a batch sizing request"""
    item_id: str = Field(
        ...,
        description="Unique identifier for this item within the batch. "
                    "Used to correlate request items with response results."
    )
    request: Dict[str, Any] = Field(
        ...,
        description="Sizing request payload (same schema as POST /sizing)"
    )


class BatchSizingRequest(BaseModel):
    """
    Request for batch sizing - multiple sizing requests in one API call.

    Each item is processed independently. If fail_fast=True, processing stops
    on first error. Otherwise, all items are processed and errors are collected.
    """
    batch_id: Optional[str] = Field(
        None,
        description="Optional batch identifier. If None, server generates UUID."
    )
    items: List[BatchSizingItem] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="List of sizing items to process. Max 100 items per batch."
    )
    fail_fast: bool = Field(
        False,
        description="If True, stop processing on first error. "
                    "If False (default), process all items and collect errors."
    )


class BatchItemResult(BaseModel):
    """Result for a single batch item"""
    item_id: str = Field(
        ...,
        description="Item identifier (same as in request)"
    )
    status: BatchItemStatus = Field(
        ...,
        description="Processing status: ok or error"
    )
    response: Optional[Dict[str, Any]] = Field(
        None,
        description="SizingResult as dict when status=ok. None when status=error."
    )
    error: Optional[str] = Field(
        None,
        description="Error message when status=error. None when status=ok."
    )


class BatchSizingSummary(BaseModel):
    """Summary statistics for batch sizing result"""
    total_items: int = Field(..., description="Total items in batch")
    ok_count: int = Field(..., description="Successfully processed items")
    error_count: int = Field(..., description="Failed items")
    processing_time_ms: float = Field(..., description="Total processing time [ms]")


class PortfolioVariantRanking(BaseModel):
    """
    Ranking entry for a variant across the portfolio.

    Used to compare variants across multiple items/scenarios in the batch.
    """
    variant: str = Field(
        ...,
        description="Variant name (small, medium, large)"
    )
    total_npv_pln: float = Field(
        ...,
        description="Sum of NPV across all items for this variant [PLN]"
    )
    avg_npv_pln: float = Field(
        ...,
        description="Average NPV for this variant [PLN]"
    )
    avg_payback_years: float = Field(
        ...,
        description="Average payback period for this variant [years]"
    )
    feasible_count: int = Field(
        ...,
        description="Number of items where this variant is feasible"
    )
    recommended_count: int = Field(
        ...,
        description="Number of items where this variant is recommended"
    )


class PortfolioSummary(BaseModel):
    """
    Portfolio-level summary for batch sizing.

    Provides aggregated metrics across all items to help identify
    the best overall variant for a portfolio of scenarios.
    """
    # Overall metrics
    total_npv_pln: float = Field(
        ...,
        description="Sum of recommended variant NPVs across all items [PLN]"
    )
    avg_npv_pln: float = Field(
        ...,
        description="Average recommended variant NPV [PLN]"
    )
    avg_payback_years: float = Field(
        ...,
        description="Average recommended variant payback [years]"
    )

    # Portfolio-optimal variant (by total NPV)
    portfolio_optimal_variant: str = Field(
        ...,
        description="Variant with highest total NPV across portfolio"
    )

    # Ranking by variant
    variant_rankings: List[PortfolioVariantRanking] = Field(
        ...,
        description="Rankings for each variant, sorted by total_npv_pln descending"
    )


class BatchSizingResponse(BaseModel):
    """
    Response for batch sizing request.

    Contains results for each item, summary statistics, and API versioning info.
    """
    # Batch metadata
    batch_id: str = Field(
        ...,
        description="Batch identifier (from request or server-generated UUID)"
    )

    # API versioning
    schema_version: str = Field(
        "1.0.0",
        description="API schema version"
    )
    assumptions_version: str = Field(
        "v1.0-unknown",
        description="Assumptions version (hash of docs/assumptions.yaml)"
    )

    # Results
    results: List[BatchItemResult] = Field(
        ...,
        description="Results for each item in the same order as request"
    )

    # Summary
    summary: BatchSizingSummary = Field(
        ...,
        description="Summary statistics for the batch"
    )

    # Portfolio summary (v0.9.0) - aggregated metrics across items
    portfolio_summary: Optional[PortfolioSummary] = Field(
        None,
        description="Portfolio-level summary with variant rankings. "
                    "None if all items failed."
    )


# =============================================================================
# Request Hash and Caching (v0.9.0)
# =============================================================================

class CacheStatus(str, Enum):
    """Cache lookup result status"""
    HIT = "hit"          # Result retrieved from cache
    MISS = "miss"        # New computation performed
    DISABLED = "disabled"  # Caching disabled for request


class CacheInfo(BaseModel):
    """
    Cache metadata for a sizing result.

    Enables deterministic result retrieval and debugging.
    """
    request_hash: str = Field(
        ...,
        description="SHA-256 hash of canonical request JSON. "
                    "Same inputs always produce same hash."
    )
    run_id: str = Field(
        ...,
        description="Unique identifier for this computation run (UUID). "
                    "Different for each new computation, same for cache hits."
    )
    cache_status: CacheStatus = Field(
        CacheStatus.MISS,
        description="Whether result was from cache (hit) or freshly computed (miss)"
    )
    cached_at: Optional[str] = Field(
        None,
        description="ISO 8601 timestamp when result was cached. "
                    "None for cache misses."
    )
    ttl_seconds: Optional[int] = Field(
        None,
        description="Cache time-to-live in seconds. None if caching disabled."
    )


# =============================================================================
# PORTFOLIO MODELS (v2.3.0)
# =============================================================================


class PortfolioItem(BaseModel):
    """
    Input item for portfolio aggregation.

    Represents a single run to be included in the portfolio summary.
    """
    run_id: str = Field(
        ...,
        description="Unique run identifier from sizing response"
    )
    label: Optional[str] = Field(
        None,
        description="User-defined label for this run (e.g., 'Site A', 'Customer 123')"
    )
    tags: Optional[List[str]] = Field(
        None,
        description="Optional tags for grouping/filtering (e.g., ['region:north', 'type:industrial'])"
    )
    weight: Optional[float] = Field(
        None,
        ge=0.0,
        description="Optional weight for weighted aggregations. If None, uses CAPEX as weight."
    )


class PortfolioItemSummary(BaseModel):
    """
    Summary of a single run within a portfolio.

    Contains extracted KPIs and metadata from the stored run.
    """
    run_id: str = Field(..., description="Unique run identifier")
    label: Optional[str] = Field(None, description="User-defined label")
    tags: Optional[List[str]] = Field(None, description="Optional tags")

    # KPIs from recommended variant
    recommended_variant: Optional[str] = Field(
        None,
        description="Name of the recommended variant (e.g., 'bess_100kWh')"
    )
    objective_used: Optional[str] = Field(
        None,
        description="Optimization objective used (e.g., 'npv', 'payback')"
    )
    npv_pln: float = Field(
        0.0,
        description="Net Present Value in PLN from recommended variant"
    )
    payback_years: Optional[float] = Field(
        None,
        description="Simple payback period in years"
    )
    irr_pct: Optional[float] = Field(
        None,
        description="Internal Rate of Return as percentage (if available)"
    )
    net_savings_pln: float = Field(
        0.0,
        description="Annual net savings in PLN"
    )
    capex_pln: float = Field(
        0.0,
        description="Total CAPEX in PLN (from finance_summary or assumptions)"
    )

    # Metadata for compatibility checks
    assumptions_version: Optional[str] = Field(
        None,
        description="Version of assumptions used for this run"
    )
    schema_version: Optional[str] = Field(
        None,
        description="Schema version of the sizing result"
    )
    pricing_mode: Optional[str] = Field(
        None,
        description="Pricing mode used (generated/override/preset)"
    )

    # Status
    status: str = Field(
        "ok",
        description="Item status: 'ok' or 'error'"
    )
    error_message: Optional[str] = Field(
        None,
        description="Error message if status is 'error'"
    )


class PortfolioRunsSummary(BaseModel):
    """
    Aggregated summary of a portfolio of runs (v2.3.0).

    Provides total KPIs, weighted averages, and compatibility warnings.
    Different from PortfolioSummary which is for batch sizing.
    """
    # Counts
    items_total: int = Field(
        0,
        description="Total number of items in portfolio"
    )
    items_ok: int = Field(
        0,
        description="Number of items successfully aggregated"
    )
    items_error: int = Field(
        0,
        description="Number of items with errors"
    )

    # Compatibility warnings
    mixed_assumptions: bool = Field(
        False,
        description="True if items have different assumptions_version values"
    )
    assumptions_versions: List[str] = Field(
        default_factory=list,
        description="List of unique assumptions_version values found"
    )
    schema_versions: List[str] = Field(
        default_factory=list,
        description="List of unique schema_version values found"
    )
    pricing_modes: List[str] = Field(
        default_factory=list,
        description="List of unique pricing_mode values found"
    )

    # Aggregated KPIs
    total_npv_pln: float = Field(
        0.0,
        description="Sum of NPV across all OK items"
    )
    total_net_savings_pln: float = Field(
        0.0,
        description="Sum of net_savings_pln across all OK items"
    )
    total_capex_pln: float = Field(
        0.0,
        description="Sum of CAPEX across all OK items"
    )
    weighted_payback_years: Optional[float] = Field(
        None,
        description="CAPEX-weighted average payback (simple average if total_capex=0)"
    )
    avg_irr_pct: Optional[float] = Field(
        None,
        description="Simple average IRR across items with IRR values"
    )

    # Top performers
    top_items_by_npv: List[PortfolioItemSummary] = Field(
        default_factory=list,
        description="Top 5 items by NPV (descending)"
    )


class PortfolioItemError(BaseModel):
    """
    Error details for a failed portfolio item.
    """
    run_id: str = Field(..., description="Run ID that failed")
    error: str = Field(..., description="Error message")


class PortfolioRequest(BaseModel):
    """
    Request to aggregate multiple runs into a portfolio summary.
    """
    run_ids: List[str] = Field(
        ...,
        min_length=1,
        description="List of run IDs to aggregate"
    )
    labels: Optional[Dict[str, str]] = Field(
        None,
        description="Optional mapping of run_id -> label"
    )
    tags: Optional[Dict[str, List[str]]] = Field(
        None,
        description="Optional mapping of run_id -> tags list"
    )


class PortfolioResponse(BaseModel):
    """
    Response from portfolio aggregation (v2.3.0).
    """
    summary: PortfolioRunsSummary = Field(
        ...,
        description="Aggregated portfolio summary"
    )
    items: List[PortfolioItemSummary] = Field(
        default_factory=list,
        description="Summary of each item in portfolio"
    )
    errors: List[PortfolioItemError] = Field(
        default_factory=list,
        description="Errors for items that could not be processed"
    )


# Update forward references for Pydantic
SizingRequest.model_rebuild()
SizingResult.model_rebuild()

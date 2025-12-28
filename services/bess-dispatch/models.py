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
from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field, validator

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


class PeriodInfo(BaseModel):
    """
    Period information included in responses.

    Helps UI understand whether results are for a full year or partial period,
    and whether annualization was applied.
    """
    period_hours: float = Field(..., description="Total hours in analysis period")
    period_days: float = Field(..., description="Total days in analysis period")
    is_full_year: bool = Field(..., description="True if period >= 8760 hours")
    annualization_factor: float = Field(
        ...,
        description="8760 / period_hours. Use to scale to annual if needed."
    )
    start_datetime: str = Field(..., description="Analysis start (ISO 8601)")
    end_datetime: str = Field(..., description="Analysis end (ISO 8601)")


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


class DegradationBudget(BaseModel):
    """Degradation budget constraints"""
    max_efc_per_year: Optional[float] = Field(None, ge=0,
                                               description="Max equivalent full cycles per year")
    max_throughput_mwh_per_year: Optional[float] = Field(None, ge=0,
                                                          description="Max throughput MWh per year")

    def has_limits(self) -> bool:
        """Check if any limits are set"""
        return self.max_efc_per_year is not None or self.max_throughput_mwh_per_year is not None


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

    # Degradation cost for profitability calculation
    degradation_cost_pln_kwh: float = Field(
        0.05,
        ge=0,
        description="Degradation cost per kWh throughput [PLN/kWh]"
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
    """
    # Positive savings
    energy_savings_pln: float = Field(0.0, description="Savings from reduced grid import at flat price (volume × flat_rate)")
    arbitrage_savings_pln: float = Field(0.0, description="ADDITIONAL savings from ToU price spread (tou_total - flat_savings)")
    capacity_fee_savings_pln: float = Field(0.0, description="Savings from reduced capacity fee (opłata mocowa PL)")
    demand_charge_savings_pln: float = Field(0.0, description="Savings from peak shaving (opłata za moc / demand charge)")

    # Negative (costs)
    degradation_cost_pln: float = Field(0.0, description="Cost of battery degradation (throughput-based)")

    # Net
    net_savings_pln: float = Field(0.0, description="Net annual savings = energy + demand + arbitrage + capacity_fee - degradation")

    def calculate_net(self) -> float:
        """Calculate net savings from components"""
        return (
            self.energy_savings_pln +
            self.arbitrage_savings_pln +
            self.capacity_fee_savings_pln +
            self.demand_charge_savings_pln -
            abs(self.degradation_cost_pln)
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

    # Hourly arrays (optional, for charts)
    hourly_charge_kw: Optional[List[float]] = None
    hourly_discharge_kw: Optional[List[float]] = None
    hourly_soc_pct: Optional[List[float]] = None
    hourly_grid_import_kw: Optional[List[float]] = None
    hourly_grid_export_kw: Optional[List[float]] = None

    # Detailed dispatch (optional)
    hourly_dispatch: Optional[List[HourlyDispatch]] = None

    # Warnings and info
    warnings: List[str] = Field(default_factory=list)
    info: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Sizing Request/Result
# =============================================================================

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

    # Battery constraints
    min_power_kw: float = Field(10.0, ge=0)
    max_power_kw: float = Field(10000.0, ge=0)
    power_steps: int = Field(10, ge=5, le=50, description="Number of power levels to test")

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

    # Pricing
    prices: PriceConfig = Field(default_factory=PriceConfig)

    # Degradation budget
    degradation_budget: Optional[DegradationBudget] = None

    # Optimization configuration (optional)
    # Note: OptimizationConfig is defined later in file, using forward reference
    optimization: Optional["OptimizationConfig"] = Field(
        None,
        description="Optimization objective and constraints configuration"
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

    def model_post_init(self, __context):
        """Pydantic v2: populate alias fields after init"""
        if self.dispatch_summary:
            # Use object.__setattr__ to bypass frozen model check
            if self.dispatch_summary.savings_breakdown and self.savings_breakdown is None:
                object.__setattr__(self, 'savings_breakdown', self.dispatch_summary.savings_breakdown)
            if self.dispatch_summary.prices_summary and self.prices_summary is None:
                object.__setattr__(self, 'prices_summary', self.dispatch_summary.prices_summary)


class SizingResult(BaseModel):
    """Complete sizing result with all variants"""

    # Input summary
    mode: DispatchMode
    total_pv_mwh: float
    total_load_mwh: float
    annual_surplus_mwh: float

    # Sizing variants
    variants: List[SizingVariantResult]

    # Recommended variant
    recommended_variant: Optional[SizingVariant] = None
    recommended_power_kw: float = 0.0
    recommended_energy_kwh: float = 0.0

    # Pareto frontier (optional)
    pareto_points: Optional[List[Dict[str, float]]] = None

    # Warnings
    warnings: List[str] = Field(default_factory=list)


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
    Optimization objectives for BESS sizing.

    Determines which metric is maximized/minimized during grid search.
    """
    NPV = "npv"                             # Maximize Net Present Value (default)
    PAYBACK = "payback"                     # Minimize Simple Payback Period
    SELF_CONSUMPTION = "self_consumption"   # Maximize self-consumption %
    PEAK_REDUCTION = "peak_reduction"       # Maximize peak reduction %
    EFC_UTILIZATION = "efc_utilization"     # Maximize EFC utilization within budget


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


# Update forward references for Pydantic
SizingRequest.update_forward_refs()

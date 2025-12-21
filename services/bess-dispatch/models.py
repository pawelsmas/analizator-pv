"""
BESS Dispatch Models
====================
Data Transfer Objects for BESS dispatch simulation and sizing.

Supports:
- 15-min and 60-min intervals
- PV-surplus (autokonsumpcja) mode
- Peak shaving mode
- STACKED mode (PV + Peak with SOC reserve)
- Degradation metrics (throughput, EFC, budget)
- Time-varying prices (future-ready)
"""

from enum import Enum
from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field, validator


class TimeResolution(str, Enum):
    """Supported time resolutions"""
    HOURLY = "hourly"           # 60-min intervals
    QUARTER_HOURLY = "15min"    # 15-min intervals


class DispatchMode(str, Enum):
    """BESS dispatch modes"""
    PV_SURPLUS = "pv_surplus"           # Autokonsumpcja only
    PEAK_SHAVING = "peak_shaving"       # Peak shaving only
    STACKED = "stacked"                 # PV + Peak (dual-service)
    ARBITRAGE = "arbitrage"             # Price arbitrage only


class DegradationStatus(str, Enum):
    """Degradation budget status"""
    OK = "ok"
    WARNING = "warning"
    EXCEEDED = "exceeded"


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
# Price Configuration (future-ready for time-varying)
# =============================================================================

class PriceConfig(BaseModel):
    """
    Energy price configuration.
    Currently supports constant prices, but structure ready for time-varying.
    """
    import_price_pln_mwh: float = Field(800.0, ge=0,
                                         description="Import price [PLN/MWh]")
    export_price_pln_mwh: float = Field(0.0, ge=0,
                                         description="Export price [PLN/MWh] (0 for 0-export)")

    # TODO: Future support for time-varying prices
    # import_prices_pln_mwh: Optional[List[float]] = None  # Per-timestep import prices
    # export_prices_pln_mwh: Optional[List[float]] = None  # Per-timestep export prices

    @property
    def is_time_varying(self) -> bool:
        """Check if prices are time-varying (future feature)"""
        return False  # TODO: implement when arrays added

    def get_import_price(self, timestep: int = 0) -> float:
        """Get import price for timestep (constant for now)"""
        # TODO: return self.import_prices_pln_mwh[timestep] if time-varying
        return self.import_price_pln_mwh

    def get_export_price(self, timestep: int = 0) -> float:
        """Get export price for timestep (constant for now)"""
        # TODO: return self.export_prices_pln_mwh[timestep] if time-varying
        return self.export_price_pln_mwh


# =============================================================================
# Dispatch Request
# =============================================================================

class DispatchRequest(BaseModel):
    """Request for BESS dispatch simulation"""

    # Time series data [kW average per interval]
    pv_generation_kw: List[float] = Field(..., min_items=24,
                                           description="PV generation [kW]")
    load_kw: List[float] = Field(..., min_items=24,
                                  description="Load consumption [kW]")

    # Time configuration
    interval_minutes: int = Field(60, description="Interval duration (15 or 60)")

    # Battery configuration
    battery: BatteryParams

    # Dispatch mode
    mode: DispatchMode = Field(DispatchMode.PV_SURPLUS)

    # Mode-specific parameters
    stacked_params: Optional[StackedModeParams] = None
    peak_limit_kw: Optional[float] = None  # For PEAK_SHAVING mode

    # Degradation budget
    degradation_budget: Optional[DegradationBudget] = None

    # Pricing
    prices: PriceConfig = Field(default_factory=PriceConfig)

    @validator('interval_minutes')
    def validate_interval(cls, v):
        if v not in [15, 60]:
            raise ValueError("interval_minutes must be 15 or 60")
        return v

    @validator('load_kw')
    def validate_lengths(cls, v, values):
        if 'pv_generation_kw' in values and len(v) != len(values['pv_generation_kw']):
            raise ValueError("pv_generation_kw and load_kw must have same length")
        return v

    @property
    def dt_hours(self) -> float:
        """Time step duration in hours"""
        return self.interval_minutes / 60.0

    @property
    def n_timesteps(self) -> int:
        """Number of timesteps"""
        return len(self.pv_generation_kw)

    @property
    def total_hours(self) -> float:
        """Total simulation duration in hours"""
        return self.n_timesteps * self.dt_hours


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

    # Time series data
    pv_generation_kw: List[float]
    load_kw: List[float]
    interval_minutes: int = 60

    # Dispatch mode
    mode: DispatchMode = Field(DispatchMode.PV_SURPLUS)
    stacked_params: Optional[StackedModeParams] = None
    peak_limit_kw: Optional[float] = None

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

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
- Audit metadata for reproducibility

Version: 1.2.0
"""

from enum import Enum
from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field, validator

# Engine version for audit trail
ENGINE_VERSION = "1.2.0"


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
                                           description="PV generation [kW_avg]")
    load_kw: List[float] = Field(..., min_items=24,
                                  description="Load consumption [kW_avg]")

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

    @validator('profile_unit')
    def validate_profile_unit(cls, v):
        if v != ProfileUnit.KW_AVG:
            raise ValueError(
                f"Dispatch requires kW_avg profiles. Got {v}. "
                "Use convert_profile_to_kw_avg() to convert."
            )
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

    # Time series data [kW_avg]
    pv_generation_kw: List[float]
    load_kw: List[float]
    interval_minutes: int = 60

    # Profile unit declaration for audit trail
    profile_unit: ProfileUnit = Field(
        ProfileUnit.KW_AVG,
        description="Unit of input profiles (must be kW_avg for sizing)"
    )

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

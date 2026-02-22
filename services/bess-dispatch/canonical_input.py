"""
Canonical Input - Unified Input Format for Multi-Engine BESS Analysis
======================================================================

This module defines a normalized input structure that serves as the
Single Source of Truth (SSoT) for all BESS sizing/dispatch engines:

1. Layer 1: Native Engine (fast, Polish-market-specific heuristics)
2. Layer 2: REopt Adapter (NREL MILP optimizer for sizing validation)
3. Layer 3: PySAM Adapter (NREL SAM for hourly dispatch diagnostics)

The Canonical Input ensures:
- Consistent units across all engines (kW_avg, PLN/kWh)
- Time-aligned profiles with explicit datetime index
- Complete pricing with ToU zones + capacity fees
- Uniform policy flags for grid charging, export, etc.

Version: 1.0.0
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
from enum import Enum
import numpy as np

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS
# =============================================================================

class CanonicalDispatchMode(str, Enum):
    """Normalized dispatch modes across engines."""
    PV_SURPLUS = "pv_surplus"       # Self-consumption optimization
    PEAK_SHAVING = "peak_shaving"   # Demand charge reduction
    ARBITRAGE = "arbitrage"         # ToU price arbitrage
    STACKED = "stacked"             # PV surplus + peak shaving combined
    LOAD_ONLY = "load_only"         # No PV, just load + grid


class CanonicalPriceZone(str, Enum):
    """Polish ToU zones for price mapping."""
    SZCZYT = "szczyt"           # Peak (zone I)
    POZASZCZYT = "pozaszczyt"   # Off-peak (zone II)
    NOC = "noc"                 # Night (zone III, if applicable)


# =============================================================================
# CANONICAL DATA CLASSES
# =============================================================================

@dataclass
class CanonicalTimeAxis:
    """
    Time axis definition - single source of truth for all time calculations.

    All timeseries in CanonicalInput must align with this axis.
    """
    start_datetime: datetime
    interval_minutes: int  # 15 or 60
    n_points: int
    timezone: str = "Europe/Warsaw"

    @property
    def dt_hours(self) -> float:
        """Time step in hours."""
        return self.interval_minutes / 60.0

    @property
    def end_datetime(self) -> datetime:
        """Calculate end datetime."""
        return self.start_datetime + timedelta(minutes=(self.n_points - 1) * self.interval_minutes)

    @property
    def period_hours(self) -> float:
        """Total hours in analysis period."""
        return self.n_points * self.dt_hours

    @property
    def period_days(self) -> float:
        """Total days in analysis period."""
        return self.period_hours / 24.0

    @property
    def is_full_year(self) -> bool:
        """True if period covers at least one full year."""
        return self.period_hours >= 8760

    @property
    def annualization_factor(self) -> float:
        """Factor to scale period values to annual."""
        return 1.0 if self.is_full_year else (8760 / self.period_hours)

    def generate_timestamps(self) -> List[datetime]:
        """Generate list of timestamps for this axis."""
        return [
            self.start_datetime + timedelta(minutes=i * self.interval_minutes)
            for i in range(self.n_points)
        ]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "start_datetime": self.start_datetime.isoformat(),
            "end_datetime": self.end_datetime.isoformat(),
            "interval_minutes": self.interval_minutes,
            "n_points": self.n_points,
            "timezone": self.timezone,
            "dt_hours": self.dt_hours,
            "period_hours": self.period_hours,
            "period_days": self.period_days,
            "is_full_year": self.is_full_year,
            "annualization_factor": self.annualization_factor,
        }


@dataclass
class CanonicalPricing:
    """
    Normalized pricing structure.

    All prices in PLN/kWh, time-aligned with CanonicalTimeAxis.
    """
    # Core price timeseries (PLN/kWh)
    price_import: np.ndarray      # Cost to buy from grid (energy + distribution)
    price_export: np.ndarray      # Revenue from selling to grid (may be 0)

    # ToU zone mapping (optional, for analysis)
    tou_zones: Optional[np.ndarray] = None  # Zone per timestep (1=peak, 2=off-peak, 3=night)

    # Capacity fee info (Polish: opłata mocowa)
    capacity_fee_pln_per_kwh: float = 0.0           # Rate for capacity fee calculation
    capacity_fee_hours: Optional[np.ndarray] = None  # Boolean mask for capacity fee hours

    # Demand charges (for peak shaving value)
    demand_charge_pln_per_kw: float = 0.0           # Monthly demand charge rate
    billing_period_days: int = 30                    # Days per billing period

    # Price statistics (computed)
    price_spread_pln: float = 0.0                   # Max - min price spread
    avg_price_import: float = 0.0
    avg_price_export: float = 0.0

    def __post_init__(self):
        """Compute derived statistics."""
        if len(self.price_import) > 0:
            self.price_spread_pln = float(np.max(self.price_import) - np.min(self.price_import))
            self.avg_price_import = float(np.mean(self.price_import))
        if len(self.price_export) > 0:
            self.avg_price_export = float(np.mean(self.price_export))

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary (without full arrays)."""
        return {
            "n_points": len(self.price_import),
            "capacity_fee_pln_per_kwh": self.capacity_fee_pln_per_kwh,
            "demand_charge_pln_per_kw": self.demand_charge_pln_per_kw,
            "billing_period_days": self.billing_period_days,
            "price_spread_pln": self.price_spread_pln,
            "avg_price_import": self.avg_price_import,
            "avg_price_export": self.avg_price_export,
            "has_tou_zones": self.tou_zones is not None,
            "has_capacity_fee_hours": self.capacity_fee_hours is not None,
        }


@dataclass
class CanonicalBattery:
    """
    Normalized battery parameters.

    All units explicit and consistent.
    """
    power_kw: float               # Nominal power [kW]
    energy_kwh: float             # Nominal capacity [kWh]
    eta_charge: float = 0.9487    # One-way charging efficiency
    eta_discharge: float = 0.9487 # One-way discharging efficiency
    soc_min: float = 0.10         # Minimum SOC [0-1]
    soc_max: float = 0.90         # Maximum SOC [0-1]
    soc_initial: float = 0.50     # Initial SOC [0-1]

    # Degradation limits
    max_cycles_per_year: Optional[float] = None
    max_cycles_per_day: Optional[float] = None

    @property
    def usable_capacity_kwh(self) -> float:
        """Usable capacity considering SOC limits."""
        return self.energy_kwh * (self.soc_max - self.soc_min)

    @property
    def c_rate(self) -> float:
        """C-rate (power/energy ratio)."""
        return self.power_kw / self.energy_kwh if self.energy_kwh > 0 else 0

    @property
    def roundtrip_efficiency(self) -> float:
        """Round-trip efficiency."""
        return self.eta_charge * self.eta_discharge

    @property
    def duration_hours(self) -> float:
        """Duration at full power."""
        return self.energy_kwh / self.power_kw if self.power_kw > 0 else 0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "power_kw": self.power_kw,
            "energy_kwh": self.energy_kwh,
            "eta_charge": self.eta_charge,
            "eta_discharge": self.eta_discharge,
            "soc_min": self.soc_min,
            "soc_max": self.soc_max,
            "soc_initial": self.soc_initial,
            "usable_capacity_kwh": self.usable_capacity_kwh,
            "c_rate": self.c_rate,
            "roundtrip_efficiency": self.roundtrip_efficiency,
            "duration_hours": self.duration_hours,
            "max_cycles_per_year": self.max_cycles_per_year,
            "max_cycles_per_day": self.max_cycles_per_day,
        }


@dataclass
class CanonicalPolicies:
    """
    Operational policies and constraints.

    Controls what the BESS is allowed to do.
    """
    # Charging policies
    allow_grid_charging: bool = True        # Can charge from grid (for arbitrage)
    allow_pv_charging: bool = True          # Can charge from PV

    # Export policies
    allow_grid_export: bool = False         # Can export to grid (sell)
    max_export_kw: Optional[float] = None   # Export power limit

    # Peak shaving
    peak_limit_kw: Optional[float] = None   # Target grid import limit
    reserve_fraction: float = 0.3           # SOC reserved for peak shaving

    # Arbitrage
    arbitrage_enabled: bool = False
    arbitrage_strategy: str = "zone_based"  # percentile, zone_based, spread
    charge_threshold_pln: Optional[float] = None   # Charge when price below this
    discharge_threshold_pln: Optional[float] = None # Discharge when price above this
    min_spread_pln: float = 0.0             # Minimum spread for arbitrage

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "allow_grid_charging": self.allow_grid_charging,
            "allow_pv_charging": self.allow_pv_charging,
            "allow_grid_export": self.allow_grid_export,
            "max_export_kw": self.max_export_kw,
            "peak_limit_kw": self.peak_limit_kw,
            "reserve_fraction": self.reserve_fraction,
            "arbitrage_enabled": self.arbitrage_enabled,
            "arbitrage_strategy": self.arbitrage_strategy,
            "charge_threshold_pln": self.charge_threshold_pln,
            "discharge_threshold_pln": self.discharge_threshold_pln,
            "min_spread_pln": self.min_spread_pln,
        }


@dataclass
class CanonicalEconomics:
    """
    Economic parameters for NPV/IRR calculations.
    """
    # CAPEX
    capex_per_kwh: float = 1500.0           # PLN per kWh
    capex_per_kw: float = 300.0             # PLN per kW
    capex_fixed: float = 0.0                # Fixed installation cost

    # OPEX
    opex_pct_per_year: float = 0.02         # Annual OPEX as % of CAPEX

    # Financing
    discount_rate: float = 0.08             # Nominal discount rate
    inflation_rate: float = 0.025           # Annual inflation
    analysis_years: int = 15                # Project lifetime

    # Replacement
    battery_lifetime_years: int = 10        # Years before replacement
    replacement_cost_factor: float = 0.5    # Replacement cost as fraction of initial

    def calculate_capex(self, power_kw: float, energy_kwh: float) -> float:
        """Calculate total CAPEX for given system size."""
        return (
            self.capex_per_kwh * energy_kwh +
            self.capex_per_kw * power_kw +
            self.capex_fixed
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "capex_per_kwh": self.capex_per_kwh,
            "capex_per_kw": self.capex_per_kw,
            "capex_fixed": self.capex_fixed,
            "opex_pct_per_year": self.opex_pct_per_year,
            "discount_rate": self.discount_rate,
            "inflation_rate": self.inflation_rate,
            "analysis_years": self.analysis_years,
            "battery_lifetime_years": self.battery_lifetime_years,
            "replacement_cost_factor": self.replacement_cost_factor,
        }


# =============================================================================
# MAIN CANONICAL INPUT CLASS
# =============================================================================

@dataclass
class CanonicalInput:
    """
    Unified input format for all BESS sizing/dispatch engines.

    This is the Single Source of Truth that normalizes data from various
    frontend/API formats into a consistent structure that all engines can use.

    Key principles:
    1. All timeseries are numpy arrays aligned with time_axis
    2. All power values are in kW_avg (average over interval)
    3. All prices are in PLN/kWh (including distribution fees)
    4. Policies explicitly declare what BESS can/cannot do
    5. Complete economic assumptions for NPV calculation

    Example usage:
    >>> from canonical_input import CanonicalInput, normalize_sizing_request
    >>> canonical = normalize_sizing_request(sizing_request)
    >>> # Now pass to any engine adapter
    >>> reopt_result = reopt_adapter.run_sizing(canonical)
    >>> pysam_result = pysam_adapter.run_dispatch(canonical, battery_params)
    """
    # Required fields
    time_axis: CanonicalTimeAxis

    # Power profiles [kW_avg], aligned with time_axis
    pv_kw: np.ndarray              # PV generation (can be zeros if no PV)
    load_kw: np.ndarray            # Facility load (consumption)

    # Pricing
    pricing: CanonicalPricing

    # Battery (optional for sizing - will be swept)
    battery: Optional[CanonicalBattery] = None

    # Policies and constraints
    policies: CanonicalPolicies = field(default_factory=CanonicalPolicies)

    # Economics
    economics: CanonicalEconomics = field(default_factory=CanonicalEconomics)

    # Dispatch mode
    mode: CanonicalDispatchMode = CanonicalDispatchMode.PV_SURPLUS

    # Metadata
    source_format: str = "unknown"  # e.g., "sizing_request", "dispatch_request"
    normalization_version: str = "1.0.0"
    project_id: Optional[str] = None

    def __post_init__(self):
        """Validate array lengths match time axis."""
        n = self.time_axis.n_points
        if len(self.pv_kw) != n:
            raise ValueError(f"pv_kw length {len(self.pv_kw)} != time_axis.n_points {n}")
        if len(self.load_kw) != n:
            raise ValueError(f"load_kw length {len(self.load_kw)} != time_axis.n_points {n}")
        if len(self.pricing.price_import) != n:
            raise ValueError(f"price_import length {len(self.pricing.price_import)} != time_axis.n_points {n}")
        if len(self.pricing.price_export) != n:
            raise ValueError(f"price_export length {len(self.pricing.price_export)} != time_axis.n_points {n}")

    @property
    def net_load_kw(self) -> np.ndarray:
        """Net load = Load - PV (positive = importing, negative = exporting)."""
        return self.load_kw - self.pv_kw

    @property
    def pv_surplus_kw(self) -> np.ndarray:
        """PV surplus = max(0, PV - Load)."""
        return np.maximum(0, self.pv_kw - self.load_kw)

    @property
    def grid_import_no_bess_kw(self) -> np.ndarray:
        """Grid import without BESS = max(0, Load - PV)."""
        return np.maximum(0, self.load_kw - self.pv_kw)

    @property
    def annual_load_kwh(self) -> float:
        """Total annual load (annualized if period < 1 year)."""
        return float(np.sum(self.load_kw) * self.time_axis.dt_hours * self.time_axis.annualization_factor)

    @property
    def annual_pv_kwh(self) -> float:
        """Total annual PV generation (annualized if period < 1 year)."""
        return float(np.sum(self.pv_kw) * self.time_axis.dt_hours * self.time_axis.annualization_factor)

    @property
    def peak_load_kw(self) -> float:
        """Peak load value."""
        return float(np.max(self.load_kw))

    @property
    def peak_net_load_kw(self) -> float:
        """Peak net load (max grid import without BESS)."""
        return float(np.max(self.net_load_kw))

    def compute_baseline_cost(self) -> float:
        """
        Calculate annual energy cost without BESS.

        This is the reference point for savings calculation.
        """
        dt = self.time_axis.dt_hours

        # Energy import cost
        import_kwh = self.grid_import_no_bess_kw * dt
        import_cost = np.sum(import_kwh * self.pricing.price_import)

        # Export revenue (negative cost)
        export_kwh = self.pv_surplus_kw * dt
        export_revenue = np.sum(export_kwh * self.pricing.price_export)

        # Demand charges (based on peak import)
        peak_kw = self.peak_net_load_kw
        n_billing_periods = self.time_axis.period_days / self.pricing.billing_period_days
        demand_cost = peak_kw * self.pricing.demand_charge_pln_per_kw * n_billing_periods

        # Capacity fee
        if self.pricing.capacity_fee_hours is not None:
            # Sum import during capacity fee hours
            cf_import_kwh = np.sum(
                import_kwh * self.pricing.capacity_fee_hours
            )
            capacity_cost = cf_import_kwh * self.pricing.capacity_fee_pln_per_kwh
        else:
            capacity_cost = 0.0

        total = import_cost - export_revenue + demand_cost + capacity_cost

        # Annualize
        return float(total * self.time_axis.annualization_factor)

    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics for logging/debugging."""
        return {
            "time_axis": self.time_axis.to_dict(),
            "mode": self.mode.value,
            "n_points": self.time_axis.n_points,
            "annual_load_kwh": round(self.annual_load_kwh, 1),
            "annual_pv_kwh": round(self.annual_pv_kwh, 1),
            "peak_load_kw": round(self.peak_load_kw, 1),
            "peak_net_load_kw": round(self.peak_net_load_kw, 1),
            "pv_to_load_ratio": round(self.annual_pv_kwh / self.annual_load_kwh, 2) if self.annual_load_kwh > 0 else 0,
            "pricing_summary": self.pricing.to_dict(),
            "policies_summary": self.policies.to_dict(),
            "economics_summary": self.economics.to_dict(),
            "battery_defined": self.battery is not None,
            "baseline_cost_pln": round(self.compute_baseline_cost(), 2),
            "source_format": self.source_format,
            "normalization_version": self.normalization_version,
        }

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary (excluding large arrays)."""
        result = self.get_summary()
        if self.battery:
            result["battery"] = self.battery.to_dict()
        return result


# =============================================================================
# NORMALIZATION FUNCTIONS
# =============================================================================

def normalize_sizing_request(
    request: Any,  # SizingRequest from models.py
    pv_profile: List[float],
    load_profile: List[float],
    price_import: Optional[List[float]] = None,
    price_export: Optional[List[float]] = None,
) -> CanonicalInput:
    """
    Normalize a SizingRequest into CanonicalInput format.

    This bridges the gap between the API request format and the
    unified engine input format.

    Args:
        request: SizingRequest from API
        pv_profile: PV generation profile [kW_avg]
        load_profile: Load consumption profile [kW_avg]
        price_import: Import prices [PLN/kWh] (optional, uses request.prices)
        price_export: Export prices [PLN/kWh] (optional)

    Returns:
        CanonicalInput ready for any engine
    """
    from models import DispatchMode, ArbitrageStrategy

    # Determine time axis
    n_points = len(load_profile)

    # Handle analytical period
    if hasattr(request, 'analytical_period') and request.analytical_period:
        ap = request.analytical_period
        start_dt = datetime.fromisoformat(ap.start_datetime)
        interval_min = ap.interval_minutes
        timezone = ap.timezone
    else:
        # Default: assume hourly data starting Jan 1 of current year
        start_dt = datetime(datetime.now().year, 1, 1)
        interval_min = 60 if n_points <= 8760 else 15
        timezone = "Europe/Warsaw"

    time_axis = CanonicalTimeAxis(
        start_datetime=start_dt,
        interval_minutes=interval_min,
        n_points=n_points,
        timezone=timezone,
    )

    # Convert profiles to numpy
    pv_kw = np.array(pv_profile, dtype=np.float64)
    load_kw = np.array(load_profile, dtype=np.float64)

    # Handle pricing
    if price_import is not None:
        p_import = np.array(price_import, dtype=np.float64)
    elif hasattr(request, 'prices') and request.prices:
        # Use flat rate from price config
        flat_rate = request.prices.buy_rate_pln_kwh or 0.7
        p_import = np.full(n_points, flat_rate, dtype=np.float64)
    else:
        p_import = np.full(n_points, 0.7, dtype=np.float64)  # Default

    if price_export is not None:
        p_export = np.array(price_export, dtype=np.float64)
    elif hasattr(request, 'prices') and request.prices:
        sell_rate = request.prices.sell_rate_pln_kwh or 0.0
        p_export = np.full(n_points, sell_rate, dtype=np.float64)
    else:
        p_export = np.zeros(n_points, dtype=np.float64)

    # Build pricing object
    pricing = CanonicalPricing(
        price_import=p_import,
        price_export=p_export,
        capacity_fee_pln_per_kwh=0.0,  # Will be filled from tariff config
        demand_charge_pln_per_kw=0.0,
    )

    # Map dispatch mode
    mode_map = {
        DispatchMode.PV_SURPLUS: CanonicalDispatchMode.PV_SURPLUS,
        DispatchMode.PEAK_SHAVING: CanonicalDispatchMode.PEAK_SHAVING,
        DispatchMode.STACKED: CanonicalDispatchMode.STACKED,
        DispatchMode.ARBITRAGE: CanonicalDispatchMode.ARBITRAGE,
        DispatchMode.LOAD_ONLY: CanonicalDispatchMode.LOAD_ONLY,
    }
    mode = mode_map.get(request.mode, CanonicalDispatchMode.PV_SURPLUS)

    # Build policies
    policies = CanonicalPolicies()

    # Handle stacked mode params
    if hasattr(request, 'stacked_params') and request.stacked_params:
        policies.peak_limit_kw = request.stacked_params.peak_limit_kw
        policies.reserve_fraction = request.stacked_params.reserve_fraction

    # Handle arbitrage config
    if hasattr(request, 'arbitrage_config') and request.arbitrage_config:
        arb = request.arbitrage_config
        policies.arbitrage_enabled = True
        policies.allow_grid_charging = arb.allow_grid_charging if hasattr(arb, 'allow_grid_charging') else True

        strategy_map = {
            ArbitrageStrategy.PERCENTILE_THRESHOLD: "percentile",
            ArbitrageStrategy.ZONE_BASED: "zone_based",
            ArbitrageStrategy.SPREAD_THRESHOLD: "spread",
        }
        policies.arbitrage_strategy = strategy_map.get(arb.strategy, "zone_based")

    # Build economics
    economics = CanonicalEconomics()
    if hasattr(request, 'finance') and request.finance:
        fin = request.finance
        if hasattr(fin, 'capex_per_kwh') and fin.capex_per_kwh:
            economics.capex_per_kwh = fin.capex_per_kwh
        if hasattr(fin, 'capex_per_kw') and fin.capex_per_kw:
            economics.capex_per_kw = fin.capex_per_kw
        if hasattr(fin, 'discount_rate') and fin.discount_rate:
            economics.discount_rate = fin.discount_rate
        if hasattr(fin, 'analysis_years') and fin.analysis_years:
            economics.analysis_years = fin.analysis_years

    return CanonicalInput(
        time_axis=time_axis,
        pv_kw=pv_kw,
        load_kw=load_kw,
        pricing=pricing,
        battery=None,  # Sizing will sweep battery parameters
        policies=policies,
        economics=economics,
        mode=mode,
        source_format="sizing_request",
    )


def normalize_dispatch_request(
    request: Any,  # DispatchRequest from models.py
    pv_profile: List[float],
    load_profile: List[float],
    price_import: Optional[List[float]] = None,
    price_export: Optional[List[float]] = None,
) -> CanonicalInput:
    """
    Normalize a DispatchRequest into CanonicalInput format.

    Similar to normalize_sizing_request but includes battery parameters.
    """
    from models import DispatchMode

    # Get base canonical input
    # Create a minimal sizing-like request for reuse
    canonical = normalize_sizing_request(
        request=request,
        pv_profile=pv_profile,
        load_profile=load_profile,
        price_import=price_import,
        price_export=price_export,
    )

    # Add battery from dispatch request
    if hasattr(request, 'battery') and request.battery:
        bat = request.battery
        canonical.battery = CanonicalBattery(
            power_kw=bat.power_kw,
            energy_kwh=bat.energy_kwh,
            eta_charge=bat.eta_charge,
            eta_discharge=bat.eta_discharge,
            soc_min=bat.soc_min,
            soc_max=bat.soc_max,
            soc_initial=bat.soc_initial,
        )

    canonical.source_format = "dispatch_request"
    return canonical


# =============================================================================
# VALIDATION AND QUALITY CHECKS
# =============================================================================

@dataclass
class ValidationResult:
    """Result of canonical input validation."""
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    quality_score: float  # 0-1, 1 = perfect

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "quality_score": self.quality_score,
        }


def validate_canonical_input(inp: CanonicalInput) -> ValidationResult:
    """
    Validate a CanonicalInput for completeness and consistency.

    Returns validation result with errors, warnings, and quality score.
    """
    errors = []
    warnings = []
    quality_score = 1.0

    n = inp.time_axis.n_points

    # Check array lengths
    if len(inp.pv_kw) != n:
        errors.append(f"pv_kw length mismatch: {len(inp.pv_kw)} vs {n}")
    if len(inp.load_kw) != n:
        errors.append(f"load_kw length mismatch: {len(inp.load_kw)} vs {n}")
    if len(inp.pricing.price_import) != n:
        errors.append(f"price_import length mismatch: {len(inp.pricing.price_import)} vs {n}")

    # Check for negative values
    if np.any(inp.pv_kw < 0):
        errors.append("pv_kw contains negative values")
    if np.any(inp.load_kw < 0):
        errors.append("load_kw contains negative values")
    if np.any(inp.pricing.price_import < 0):
        warnings.append("price_import contains negative values")

    # Check for NaN/Inf
    if np.any(~np.isfinite(inp.pv_kw)):
        errors.append("pv_kw contains NaN or Inf")
    if np.any(~np.isfinite(inp.load_kw)):
        errors.append("load_kw contains NaN or Inf")

    # Check time axis
    if inp.time_axis.interval_minutes not in [15, 60]:
        warnings.append(f"Non-standard interval: {inp.time_axis.interval_minutes} min")
        quality_score -= 0.1

    # Check period length
    if not inp.time_axis.is_full_year:
        warnings.append(f"Period is less than full year: {inp.time_axis.period_days:.1f} days")
        quality_score -= 0.1

    # Check pricing quality
    if inp.pricing.price_spread_pln < 0.05:
        warnings.append("Low price spread - arbitrage may not be valuable")
        quality_score -= 0.05

    # Check load characteristics
    if inp.peak_load_kw <= 0:
        errors.append("Peak load is zero or negative")

    # Check PV presence if not load-only mode
    if inp.mode != CanonicalDispatchMode.LOAD_ONLY:
        if np.sum(inp.pv_kw) == 0:
            warnings.append("No PV generation - consider LOAD_ONLY mode")
            quality_score -= 0.1

    # Check policies consistency
    if inp.policies.arbitrage_enabled and inp.mode not in [
        CanonicalDispatchMode.ARBITRAGE,
        CanonicalDispatchMode.STACKED
    ]:
        warnings.append("Arbitrage enabled but mode is not ARBITRAGE or STACKED")

    # Determine validity
    is_valid = len(errors) == 0

    # Clamp quality score
    quality_score = max(0.0, min(1.0, quality_score))

    return ValidationResult(
        is_valid=is_valid,
        errors=errors,
        warnings=warnings,
        quality_score=quality_score,
    )


# =============================================================================
# EXPORT FOR EXTERNAL ENGINES
# =============================================================================

def to_reopt_format(inp: CanonicalInput) -> Dict[str, Any]:
    """
    Convert CanonicalInput to REopt API format.

    REopt uses slightly different field names and structure.
    This is a stub - full implementation in reopt_adapter.py
    """
    return {
        "Site": {
            "latitude": 52.0,  # Default Poland
            "longitude": 21.0,
        },
        "ElectricLoad": {
            "loads_kw": inp.load_kw.tolist(),
        },
        "PV": {
            "production_factor_series": (inp.pv_kw / inp.peak_load_kw).tolist() if inp.peak_load_kw > 0 else None,
        },
        "ElectricTariff": {
            "urdb_rate_name": "custom",
            "energy_rate_structure": "custom",
        },
        "ElectricStorage": {
            "min_kw": 0,
            "max_kw": 1000,  # Will be constrained by sizing
            "min_kwh": 0,
            "max_kwh": 4000,
        },
        "_canonical_version": inp.normalization_version,
    }


def to_pysam_format(inp: CanonicalInput, battery: CanonicalBattery) -> Dict[str, Any]:
    """
    Convert CanonicalInput to PySAM BatteryStateful format.

    PySAM requires specific parameter naming for its battery model.
    This is a stub - full implementation in pysam_adapter.py
    """
    return {
        "system_capacity": battery.energy_kwh,
        "batt_power": battery.power_kw,
        "batt_simple_chemistry": 1,  # LFP
        "analysis_period": inp.economics.analysis_years,
        "load": inp.load_kw.tolist(),
        "gen": inp.pv_kw.tolist(),
        "_canonical_version": inp.normalization_version,
    }

"""
Economics Helper - Unified cost calculation for BESS dispatch.

Implements the MVP pricing stack (Opcja B - OSD_ALL_IN):
- ToU rates from OSD presets = energia czynna + dystrybucja (combined)
- OTHER fees = OZE + kogeneracja + jakość + akcyza (per kWh, flat)
- Capacity fee PL = osobno, dynamicznie (A × SOM × ZS) lub fixed

Key principles:
- All prices in PLN/kWh NETTO (not MWh)
- CET-fixed time handling (Polish "czas zimowy")
- Single source of truth: OSD compiler for zone schedules
- Capacity fee calculated post-dispatch, not in price series

Version: 1.0.0
"""

from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Any, TYPE_CHECKING
import numpy as np
from pydantic import BaseModel, Field

# Import AnalyticalPeriodConfig only for type checking to avoid circular imports
if TYPE_CHECKING:
    from models import AnalyticalPeriodConfig

# Internal imports
from common.time_utils import CET_FIXED_OFFSET, ClockMode
from common.calendar_pl import get_day_type, DayType
from price_engine import (
    ToUPriceProvider,
    ToUPriceConfig,
    PriceBundle,
    PriceComponent,
    FlatPriceProvider,
)
from osd_tariffs.presets import get_preset_by_id, list_presets, ALL_PRESETS
from osd_tariffs.presets.templates import (
    create_c11_template,
    create_c12a_template,
    create_c12b_template,
)
from osd_tariffs.models import OsdTariff, ZoneId
from capacity_fee_pl.calculator import (
    compute_capacity_fee,
    compute_capacity_fee_savings,
    build_selected_hours_mask,
)
from capacity_fee_pl.models import CapacityFeeConfig, CapacityFeeResult


# =============================================================================
# Configuration
# =============================================================================

# Default OTHER fees (PLN/MWh) - suma opłat stałych (OSD, OZE, kog, jakość, mocowa, akcyza)
# These are added on top of energia czynna rates
DEFAULT_OTHER_FEES_PLN_MWH = 451.0  # 200 + 10 + 7 + 10 + 219 + 5

# Default SOM rate for capacity fee (2025/2026)
DEFAULT_SOM_PLN_KWH = 0.2194


class PricingConfig(BaseModel):
    """
    Configuration for energy cost calculations.

    Implements Opcja B (OSD_ALL_IN):
    - tariff_id: Preset OSD tariff (energia + dystrybucja combined)
    - other_fees_pln_mwh: OTHER opłaty (OZE, kog, jakość, akcyza)
    - capacity_fee_*: Opłata mocowa PL settings
    """
    # Tariff selection
    tariff_id: Optional[str] = Field(
        None,
        description="OSD preset ID (e.g., 'pge_c12a_2025'). If None, uses flat pricing."
    )

    # Fallback flat rates (when tariff_id is None)
    flat_import_pln_mwh: float = Field(
        750.0,
        description="Flat import rate [PLN/MWh] if no tariff selected"
    )
    flat_export_pln_mwh: float = Field(
        0.0,
        description="Flat export rate [PLN/MWh] - typically 0 for 0-export"
    )

    # OTHER fees (per kWh, added on top of OSD rates)
    other_fees_pln_mwh: float = Field(
        DEFAULT_OTHER_FEES_PLN_MWH,
        description="OTHER fees [PLN/MWh]: OZE + kog + jakość + akcyza"
    )

    # Capacity fee settings
    capacity_fee_method: str = Field(
        "dynamic",
        description="'dynamic' (A×SOM×ZS) or 'fixed' (simple per-MWh)"
    )
    capacity_fee_som_pln_kwh: float = Field(
        DEFAULT_SOM_PLN_KWH,
        description="SOM rate for dynamic method [PLN/kWh]"
    )
    capacity_fee_fixed_pln_mwh: Optional[float] = Field(
        None,
        description="Fixed capacity fee rate [PLN/MWh] for fixed method"
    )

    # Analysis year (for time_index generation)
    analysis_year: int = Field(
        2025,
        description="Year for calendar calculations (weekends, holidays)"
    )

    # Export policy
    export_policy: str = Field(
        "zero_export",
        description="'zero_export' (eksport=0, curtailment) or 'export_allowed'"
    )

    @property
    def other_fees_pln_kwh(self) -> float:
        """Convert OTHER fees to PLN/kWh."""
        return self.other_fees_pln_mwh / 1000.0


class CostBreakdown(BaseModel):
    """Detailed breakdown of energy costs."""
    # ToU costs (energia + dystrybucja from OSD)
    tou_cost_pln: float = Field(0.0, description="ToU energy+distribution cost")

    # OTHER fees
    other_fees_pln: float = Field(0.0, description="OTHER fees (OZE, kog, jakość, akcyza)")

    # Capacity fee
    capacity_fee_pln: float = Field(0.0, description="Opłata mocowa PL")
    capacity_fee_method: str = Field("none", description="Method used")
    capacity_fee_details: Dict[str, Any] = Field(default_factory=dict)

    # Totals
    total_cost_pln: float = Field(0.0, description="Total energy cost")

    # Energy metrics
    total_import_kwh: float = Field(0.0)
    total_export_kwh: float = Field(0.0)

    # Tariff info
    tariff_id: Optional[str] = None
    tariff_source: str = "unknown"

    def calculate_total(self) -> float:
        """Calculate total cost from components."""
        return self.tou_cost_pln + self.other_fees_pln + self.capacity_fee_pln


# =============================================================================
# Time Index Builder (CET-fixed)
# =============================================================================

def build_time_index_cet_fixed(
    start_date: date,
    n_timesteps: int,
    interval_minutes: int = 60
) -> List[datetime]:
    """
    Build time_index in CET-fixed mode (UTC+1 year-round).

    This is required for:
    - Correct zone assignments (Polish tariffs use "czas zimowy")
    - Capacity fee calculations (workday detection)

    Args:
        start_date: Start date (e.g., date(2025, 1, 1))
        n_timesteps: Number of timesteps (e.g., 8760 for yearly hourly)
        interval_minutes: Time resolution (15 or 60)

    Returns:
        List of datetime objects in CET-fixed timezone
    """
    result = []
    dt = datetime(
        start_date.year, start_date.month, start_date.day,
        0, 0, 0, tzinfo=CET_FIXED_OFFSET
    )
    delta = timedelta(minutes=interval_minutes)

    for _ in range(n_timesteps):
        result.append(dt)
        dt += delta

    return result


def build_time_index_from_period(
    analytical_period: "AnalyticalPeriodConfig",
) -> List[datetime]:
    """
    Build time_index from AnalyticalPeriodConfig - SINGLE SOURCE OF TRUTH.

    This function should be used instead of build_time_index_cet_fixed when
    analytical_period is available, as it respects the exact start_datetime
    and n_points from the data file.

    Args:
        analytical_period: AnalyticalPeriodConfig from request

    Returns:
        List of datetime objects in CET-fixed timezone (or raw timestamps if provided)

    Example:
        # Data file has 4380 points starting from 2024-10-01
        period = AnalyticalPeriodConfig(
            start_datetime="2024-10-01T00:00:00",
            interval_minutes=60,
            n_points=4380
        )
        time_index = build_time_index_from_period(period)
        # Returns list of 4380 datetimes from Oct 1 2024 00:00 to Mar 31 2025 23:00
    """
    # Priority 1: If raw timestamps are provided, use them directly
    if analytical_period.timestamps:
        return [
            datetime.fromisoformat(ts.replace('Z', '+00:00'))
            for ts in analytical_period.timestamps
        ]

    # Priority 2: Build from start_datetime + interval + n_points
    start_dt = datetime.fromisoformat(analytical_period.start_datetime)

    # If no timezone, assume CET-fixed (Polish "czas zimowy")
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=CET_FIXED_OFFSET)

    result = []
    delta = timedelta(minutes=analytical_period.interval_minutes)
    dt = start_dt

    for _ in range(analytical_period.n_points):
        result.append(dt)
        dt += delta

    return result


def get_time_index_for_request(
    analytical_period: Optional["AnalyticalPeriodConfig"],
    n_timesteps: int,
    interval_minutes: int,
    fallback_year: int = 2025,
) -> List[datetime]:
    """
    Get time_index using best available source - prioritizes analytical_period.

    This is the recommended entry point for getting time_index.
    It will:
    1. Use analytical_period if provided (PREFERRED)
    2. Fall back to building from fallback_year + Jan 1 (with warning)

    Args:
        analytical_period: AnalyticalPeriodConfig from request (if available)
        n_timesteps: Number of timesteps (used for validation/fallback)
        interval_minutes: Time resolution (used for fallback)
        fallback_year: Year to use if no analytical_period provided

    Returns:
        List of datetime objects
    """
    if analytical_period is not None:
        time_index = build_time_index_from_period(analytical_period)

        # Validate length matches
        if len(time_index) != n_timesteps:
            import logging
            logging.warning(
                f"⚠️ Time index length mismatch: analytical_period has {len(time_index)} points, "
                f"but data has {n_timesteps} points. Using analytical_period length."
            )

        return time_index

    # Fallback: use legacy method with warning
    import logging
    logging.warning(
        f"⚠️ No analytical_period provided - using fallback {fallback_year}-01-01. "
        "This may cause incorrect ToU zone assignments for non-January data."
    )

    return build_time_index_cet_fixed(
        date(fallback_year, 1, 1),
        n_timesteps,
        interval_minutes
    )


def get_analysis_dates(
    analysis_year: int,
    n_timesteps: int,
    interval_minutes: int
) -> Tuple[date, date]:
    """
    Calculate start and end dates for analysis.

    Args:
        analysis_year: Year of analysis
        n_timesteps: Number of timesteps
        interval_minutes: Time resolution

    Returns:
        Tuple of (start_date, end_date)
    """
    start_date = date(analysis_year, 1, 1)

    # Calculate total hours
    total_hours = (n_timesteps * interval_minutes) / 60
    total_days = int(np.ceil(total_hours / 24))

    end_date = start_date + timedelta(days=total_days - 1)

    return start_date, end_date


# =============================================================================
# ToU Cost Calculator
# =============================================================================

def calculate_tou_cost(
    grid_import_kw: np.ndarray,
    config: PricingConfig,
    interval_minutes: int = 60,
    analytical_period: Optional["AnalyticalPeriodConfig"] = None,
) -> Tuple[float, PriceBundle]:
    """
    Calculate ToU energy cost (energia + dystrybucja from OSD).

    Uses ToUPriceProvider with OSD preset, or falls back to flat pricing.
    Does NOT include capacity fee (calculated separately).

    Args:
        grid_import_kw: Grid import profile [kW]
        config: Pricing configuration
        interval_minutes: Time resolution (15 or 60)
        analytical_period: Time axis config (PREFERRED - uses actual start date)

    Returns:
        Tuple of (cost_pln, price_bundle)
    """
    n_timesteps = len(grid_import_kw)
    dt_hours = interval_minutes / 60

    # Use analytical_period if available for accurate date range
    if analytical_period is not None:
        start_dt = datetime.fromisoformat(analytical_period.start_datetime)
        start_date = start_dt.date()
        # Calculate end date from period config
        total_hours = (analytical_period.n_points * analytical_period.interval_minutes) / 60
        total_days = int(np.ceil(total_hours / 24))
        end_date = start_date + timedelta(days=total_days - 1)
    else:
        start_date, end_date = get_analysis_dates(
            config.analysis_year, n_timesteps, interval_minutes
        )

    # Get tariff or use flat
    if config.tariff_id:
        osd_tariff = get_preset_by_id(config.tariff_id)
        if osd_tariff is None:
            raise ValueError(f"Unknown tariff preset: {config.tariff_id}")

        # Create provider with OTHER fees, but NO capacity fee
        tou_config = ToUPriceConfig(
            osd_tariff=osd_tariff,
            capacity_fee_pln_kwh=0.0,  # Capacity fee calculated separately!
            other_components_pln_kwh=config.other_fees_pln_kwh,
            export_rate_pln_kwh=config.flat_export_pln_mwh / 1000.0,
        )
        provider = ToUPriceProvider(tou_config)
    else:
        # Flat pricing fallback
        provider = FlatPriceProvider(
            import_price_pln_kwh=config.flat_import_pln_mwh / 1000.0 + config.other_fees_pln_kwh,
            export_price_pln_kwh=config.flat_export_pln_mwh / 1000.0,
        )

    # Get price series
    price_bundle = provider.get_series(start_date, end_date, interval_minutes)

    # Ensure we have enough prices
    price_array = price_bundle.get_import_array()
    if len(price_array) < n_timesteps:
        # Extend with last value if needed
        extension = [price_array[-1]] * (n_timesteps - len(price_array))
        price_array = np.concatenate([price_array, extension])
    price_array = price_array[:n_timesteps]

    # Calculate cost
    import_kwh = grid_import_kw * dt_hours
    tou_cost = float(np.sum(import_kwh * price_array))

    return tou_cost, price_bundle


# =============================================================================
# Capacity Fee Calculator
# =============================================================================

def calculate_capacity_fee(
    grid_import_kw: np.ndarray,
    config: PricingConfig,
    interval_minutes: int = 60,
    analytical_period: Optional["AnalyticalPeriodConfig"] = None,
) -> Tuple[float, Dict[str, Any]]:
    """
    Calculate Polish capacity market fee (opłata mocowa PL).

    Supports two methods:
    - 'dynamic': A × SOM × ZS (accurate, based on K-class)
    - 'fixed': Simple per-MWh rate (approximation)

    Args:
        grid_import_kw: Grid import profile [kW]
        config: Pricing configuration
        interval_minutes: Time resolution
        analytical_period: Time axis config (PREFERRED - uses actual start date)

    Returns:
        Tuple of (fee_pln, details_dict)
    """
    n_timesteps = len(grid_import_kw)
    dt_hours = interval_minutes / 60

    # IMPORTANT: Convert kW to kWh for capacity fee calculation
    grid_import_kwh = grid_import_kw * dt_hours

    if config.capacity_fee_method == 'fixed' and config.capacity_fee_fixed_pln_mwh is not None:
        # Fixed method: simple per-MWh calculation
        total_import_mwh = float(np.sum(grid_import_kwh)) / 1000.0
        fee_pln = total_import_mwh * config.capacity_fee_fixed_pln_mwh

        return fee_pln, {
            'method': 'fixed',
            'fixed_rate_pln_mwh': config.capacity_fee_fixed_pln_mwh,
            'total_import_mwh': total_import_mwh,
        }

    # Dynamic method: A × SOM × ZS
    # Use analytical_period if available, otherwise fall back to analysis_year + Jan 1
    time_index = get_time_index_for_request(
        analytical_period=analytical_period,
        n_timesteps=n_timesteps,
        interval_minutes=interval_minutes,
        fallback_year=config.analysis_year,
    )

    cap_config = CapacityFeeConfig(
        year=config.analysis_year,
        som_pln_per_kwh=config.capacity_fee_som_pln_kwh,
    )

    result = compute_capacity_fee(grid_import_kwh, time_index, cap_config)

    return result.total_fee_pln, {
        'method': 'dynamic',
        'som_pln_kwh': config.capacity_fee_som_pln_kwh,
        'k_histogram': result.k_histogram,
        'avg_delta_s': result.avg_delta_s,
        'workdays_count': result.workdays_count,
        'total_zs_kwh': result.total_zs_kwh,
    }


# =============================================================================
# Complete Cost Calculator
# =============================================================================

def calculate_total_energy_cost(
    grid_import_kw: np.ndarray,
    grid_export_kw: Optional[np.ndarray],
    config: PricingConfig,
    interval_minutes: int = 60,
    analytical_period: Optional["AnalyticalPeriodConfig"] = None,
) -> CostBreakdown:
    """
    Calculate complete energy cost with full breakdown.

    Implements Opcja B (OSD_ALL_IN):
    1. ToU cost (energia + dystrybucja from OSD preset)
    2. OTHER fees (already included in ToU via provider config)
    3. Capacity fee PL (calculated separately)

    Args:
        grid_import_kw: Grid import profile [kW]
        grid_export_kw: Grid export profile [kW] (or None for 0-export)
        config: Pricing configuration
        interval_minutes: Time resolution
        analytical_period: Time axis config (PREFERRED - uses actual start date)

    Returns:
        CostBreakdown with all components
    """
    n_timesteps = len(grid_import_kw)
    dt_hours = interval_minutes / 60

    # 1. Calculate ToU cost (includes OTHER fees via provider config)
    tou_cost, price_bundle = calculate_tou_cost(
        grid_import_kw, config, interval_minutes, analytical_period
    )

    # 2. Calculate capacity fee separately
    cap_fee, cap_details = calculate_capacity_fee(
        grid_import_kw, config, interval_minutes, analytical_period
    )

    # 3. Calculate export revenue (if any)
    export_kwh = 0.0
    if grid_export_kw is not None and config.export_policy == 'export_allowed':
        export_kwh = float(np.sum(grid_export_kw * dt_hours))
        # Export revenue would reduce cost - but typically 0 in our model

    # 4. Build breakdown
    import_kwh = float(np.sum(grid_import_kw * dt_hours))

    # Note: ToU cost from provider already includes OTHER fees
    # We need to separate them for transparency
    other_fees_total = import_kwh * config.other_fees_pln_kwh
    tou_only = tou_cost - other_fees_total

    breakdown = CostBreakdown(
        tou_cost_pln=tou_only,
        other_fees_pln=other_fees_total,
        capacity_fee_pln=cap_fee,
        capacity_fee_method=config.capacity_fee_method,
        capacity_fee_details=cap_details,
        total_cost_pln=tou_cost + cap_fee,  # tou_cost includes other_fees
        total_import_kwh=import_kwh,
        total_export_kwh=export_kwh,
        tariff_id=config.tariff_id,
        tariff_source=price_bundle.source if hasattr(price_bundle, 'source') else "flat",
    )

    return breakdown


# =============================================================================
# Savings Calculator (Baseline vs Project)
# =============================================================================

def calculate_savings(
    baseline_import_kw: np.ndarray,
    project_import_kw: np.ndarray,
    config: PricingConfig,
    interval_minutes: int = 60,
    analytical_period: Optional["AnalyticalPeriodConfig"] = None,
) -> Dict[str, Any]:
    """
    Calculate savings between baseline (PV-only) and project (PV+BESS).

    Both scenarios use the same pricing configuration to ensure
    fair comparison.

    Args:
        baseline_import_kw: Grid import without BESS [kW]
        project_import_kw: Grid import with BESS [kW]
        config: Pricing configuration (same for both)
        interval_minutes: Time resolution
        analytical_period: Time axis config (PREFERRED - uses actual start date)

    Returns:
        Dict with savings breakdown
    """
    # Calculate costs for both scenarios
    baseline_cost = calculate_total_energy_cost(
        baseline_import_kw, None, config, interval_minutes, analytical_period
    )
    project_cost = calculate_total_energy_cost(
        project_import_kw, None, config, interval_minutes, analytical_period
    )

    # Calculate savings
    tou_savings = baseline_cost.tou_cost_pln - project_cost.tou_cost_pln
    other_savings = baseline_cost.other_fees_pln - project_cost.other_fees_pln
    capacity_savings = baseline_cost.capacity_fee_pln - project_cost.capacity_fee_pln
    total_savings = baseline_cost.total_cost_pln - project_cost.total_cost_pln

    return {
        'baseline': {
            'tou_cost_pln': baseline_cost.tou_cost_pln,
            'other_fees_pln': baseline_cost.other_fees_pln,
            'capacity_fee_pln': baseline_cost.capacity_fee_pln,
            'total_cost_pln': baseline_cost.total_cost_pln,
            'total_import_kwh': baseline_cost.total_import_kwh,
        },
        'project': {
            'tou_cost_pln': project_cost.tou_cost_pln,
            'other_fees_pln': project_cost.other_fees_pln,
            'capacity_fee_pln': project_cost.capacity_fee_pln,
            'total_cost_pln': project_cost.total_cost_pln,
            'total_import_kwh': project_cost.total_import_kwh,
        },
        'savings': {
            'tou_savings_pln': tou_savings,
            'other_savings_pln': other_savings,
            'capacity_fee_savings_pln': capacity_savings,
            'total_savings_pln': total_savings,
            'import_reduction_kwh': baseline_cost.total_import_kwh - project_cost.total_import_kwh,
        },
        'config': {
            'tariff_id': config.tariff_id,
            'analysis_year': config.analysis_year,
            'capacity_fee_method': config.capacity_fee_method,
        }
    }


# =============================================================================
# Available Tariffs Query
# =============================================================================

def get_available_tariffs() -> List[Dict[str, Any]]:
    """
    Get list of available OSD tariff presets.

    Returns:
        List of tariff info dicts
    """
    presets = list_presets()
    return [
        {
            'id': p.id,
            'name': p.name,
            'osd': p.osd,
            'group': p.group,
            'zones_count': p.zones_count,
            'zones': p.zones,
        }
        for p in presets
    ]


def create_custom_tariff(
    group: str,
    rates: Dict[str, float],
    osd: str = "Custom",
    valid_from: Optional[date] = None,
) -> OsdTariff:
    """
    Create a custom tariff with user-defined rates.

    Args:
        group: Tariff group ('C11', 'C12a', 'C12b')
        rates: Zone rates in PLN/kWh:
            - C11: {'flat': 0.75}
            - C12a: {'peak': 0.85, 'offpeak': 0.55}
            - C12b: {'peak': 0.95, 'day': 0.75, 'night': 0.45}
        osd: OSD name
        valid_from: Start date (default: Jan 1 current year)

    Returns:
        OsdTariff object
    """
    if valid_from is None:
        valid_from = date.today().replace(month=1, day=1)

    if group == 'C11':
        return create_c11_template(
            osd=osd,
            rate=rates.get('flat', 0.75),
            valid_from=valid_from,
        )
    elif group == 'C12a':
        return create_c12a_template(
            osd=osd,
            rate_peak=rates.get('peak', 0.85),
            rate_offpeak=rates.get('offpeak', 0.55),
            valid_from=valid_from,
        )
    elif group == 'C12b':
        return create_c12b_template(
            osd=osd,
            rate_peak=rates.get('peak', 0.95),
            rate_day=rates.get('day', 0.75),
            rate_night=rates.get('night', 0.45),
            valid_from=valid_from,
        )
    else:
        raise ValueError(f"Unknown tariff group: {group}. Supported: C11, C12a, C12b")

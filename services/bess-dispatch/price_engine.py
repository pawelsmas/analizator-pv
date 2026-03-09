"""
Price Engine - Unified price signal provider for BESS dispatch.

Thin MVP v1.0:
- PriceBundle: import_total[t] + export_total[t] + breakdown[t]
- ToUPriceProvider: Converts OSD tariff definitions to price series
- FlatPriceProvider: Legacy adapter for constant prices

Architecture principles:
- Single interface: get_series(start, end, resolution) -> PriceBundle
- All prices in PLN/kWh NETTO (not MWh!)
- Breakdown components for transparency and debugging
- Provider abstraction enables ToU, RDN, hybrid sources

Future extensions (not in MVP):
- RDNPriceProvider: 15-min day-ahead market prices
- HybridPriceProvider: Composite of multiple sources
- Forecast confidence intervals

Version: 1.0.0
"""

from datetime import date, datetime, timedelta
from enum import Enum
from typing import List, Optional, Dict, Any, Protocol, Union
from pydantic import BaseModel, Field, field_validator
import numpy as np

# Import existing tariff infrastructure
from osd_tariffs.models import OsdTariff, ZoneId, TariffComponent, ChargeBasis, TimeDependency
from osd_tariffs.compiler import TariffCompiler


# =============================================================================
# Price Bundle - Core output type
# =============================================================================

class PriceComponent(str, Enum):
    """
    Components that make up the total energy price.

    Polish tariff structure breakdown:
    - OSD_VARIABLE: Składnik zmienny OSD (distribution variable)
    - OSD_FIXED: Składnik stały OSD (distribution fixed - not time-varying)
    - ENERGY: Energia czynna (active energy from sprzedawca)
    - CAPACITY_FEE: Opłata mocowa (capacity market fee)
    - RDN: Cena z Rynku Dnia Następnego (day-ahead market)
    """
    OSD_VARIABLE = "osd_variable"
    OSD_FIXED = "osd_fixed"
    ENERGY = "energy"
    CAPACITY_FEE = "capacity_fee"
    RDN = "rdn"
    OTHER = "other"


class PriceBreakdown(BaseModel):
    """
    Breakdown of price components for a single timestep.

    All values in PLN/kWh NETTO.
    """
    components: Dict[PriceComponent, float] = Field(
        default_factory=dict,
        description="Component -> rate mapping [PLN/kWh]"
    )
    zone_id: Optional[ZoneId] = Field(
        None,
        description="Tariff zone for this timestep (if zone-based)"
    )

    @property
    def total(self) -> float:
        """Sum of all components"""
        return sum(self.components.values())

    def get(self, component: PriceComponent, default: float = 0.0) -> float:
        """Get component value with default"""
        return self.components.get(component, default)


class PriceBundle(BaseModel):
    """
    Complete price signal for dispatch optimization.

    Contains:
    - import_total: Total import price per timestep [PLN/kWh]
    - export_total: Total export price per timestep [PLN/kWh]
    - breakdown: Component-level breakdown for each timestep
    - metadata: Source info, validity, confidence

    All arrays are aligned: len(import_total) == len(export_total) == len(breakdown)
    """
    # Core price series [PLN/kWh]
    import_total: List[float] = Field(..., description="Total import price [PLN/kWh] per timestep")
    export_total: List[float] = Field(..., description="Total export price [PLN/kWh] per timestep")

    # Detailed breakdown per timestep
    breakdown: List[PriceBreakdown] = Field(
        default_factory=list,
        description="Component breakdown per timestep"
    )

    # Metadata
    source: str = Field("unknown", description="Price source identifier")
    start_date: Optional[date] = Field(None, description="First date in series")
    end_date: Optional[date] = Field(None, description="Last date in series")
    resolution_minutes: int = Field(60, description="Time resolution (15 or 60)")
    currency: str = Field("PLN", description="Currency code")
    unit: str = Field("PLN/kWh", description="Price unit")

    @field_validator('import_total', 'export_total')
    @classmethod
    def validate_non_negative(cls, v: List[float]) -> List[float]:
        """Prices must be non-negative"""
        if any(p < 0 for p in v):
            raise ValueError("Prices cannot be negative")
        return v

    @property
    def n_timesteps(self) -> int:
        """Number of timesteps in bundle"""
        return len(self.import_total)

    @property
    def has_breakdown(self) -> bool:
        """Check if detailed breakdown is available"""
        return len(self.breakdown) == self.n_timesteps

    def get_import_array(self) -> np.ndarray:
        """Get import prices as numpy array"""
        return np.array(self.import_total)

    def get_export_array(self) -> np.ndarray:
        """Get export prices as numpy array"""
        return np.array(self.export_total)

    def get_spread_array(self) -> np.ndarray:
        """Get price spread (import - export) for arbitrage potential"""
        return self.get_import_array() - self.get_export_array()

    def get_zones(self) -> Optional[List[ZoneId]]:
        """Get zone IDs if breakdown available"""
        if not self.has_breakdown:
            return None
        return [b.zone_id for b in self.breakdown]

    @classmethod
    def from_constant(
        cls,
        import_price_pln_kwh: float,
        export_price_pln_kwh: float,
        n_timesteps: int,
        source: str = "constant"
    ) -> "PriceBundle":
        """
        Create bundle with constant prices.

        Adapter for legacy flat pricing.
        """
        return cls(
            import_total=[import_price_pln_kwh] * n_timesteps,
            export_total=[export_price_pln_kwh] * n_timesteps,
            breakdown=[
                PriceBreakdown(components={PriceComponent.ENERGY: import_price_pln_kwh})
                for _ in range(n_timesteps)
            ],
            source=source,
            resolution_minutes=60,
        )


# =============================================================================
# Price Provider Protocol
# =============================================================================

class PriceProvider(Protocol):
    """
    Protocol for price providers.

    All providers must implement get_series() with consistent interface.
    """

    def get_series(
        self,
        start_date: date,
        end_date: date,
        resolution_minutes: int = 60
    ) -> PriceBundle:
        """
        Get price series for date range.

        Args:
            start_date: First date (inclusive)
            end_date: Last date (inclusive)
            resolution_minutes: Time resolution (15 or 60)

        Returns:
            PriceBundle with import/export prices and breakdown
        """
        ...


# =============================================================================
# ToU Price Provider (MVP)
# =============================================================================

class ToUPriceConfig(BaseModel):
    """
    Configuration for ToU (Time-of-Use) price provider.

    Polish electricity price structure:
    - Tariff rates (from OSD tariff): combined energia czynna + dystrybucja
    - Capacity fee (opłata mocowa): flat per kWh
    - Other components: akcyza, kogeneracja, OZE

    NOTE: The OSD tariff rates from presets typically include BOTH the
    sprzedawca energy rate AND the OSD distribution rate combined.
    This is how Polish tariffs are usually quoted (total per zone).

    If you have separate OSD and sprzedawca rates, sum them when
    creating the tariff preset.
    """
    # OSD tariff definition (provides zone schedule + combined rates)
    osd_tariff: OsdTariff = Field(..., description="OSD tariff with zone schedule and combined rates")

    # Capacity fee (opłata mocowa) - optional, added on top
    capacity_fee_pln_kwh: float = Field(
        0.0,
        ge=0,
        description="Capacity market fee [PLN/kWh] - flat component"
    )

    # Other fixed components (akcyza, kogeneracja, OZE)
    other_components_pln_kwh: float = Field(
        0.0,
        ge=0,
        description="Other fixed charges [PLN/kWh]"
    )

    # Export pricing
    export_rate_pln_kwh: float = Field(
        0.0,
        ge=0,
        description="Export rate [PLN/kWh] - typically 0 for prosumers post-2024"
    )

    # Fallback rate when tariff has no data for a day
    default_rate_pln_kwh: float = Field(
        0.65,
        ge=0,
        description="Default rate if no tariff data [PLN/kWh]"
    )


class ToUPriceProvider:
    """
    Time-of-Use price provider using OSD tariff definitions.

    Compiles OSD tariff schedules into hourly price series.
    The tariff rates are treated as the base energy rate per zone,
    with optional capacity fee and other components added on top.

    Usage:
        config = ToUPriceConfig(
            osd_tariff=PGE_C12A_2025,  # Has rates: I=0.85, II=0.55 PLN/kWh
            capacity_fee_pln_kwh=0.12,  # Added on top
        )
        provider = ToUPriceProvider(config)
        prices = provider.get_series(date(2025, 1, 1), date(2025, 12, 31))
    """

    def __init__(self, config: ToUPriceConfig):
        self.config = config
        self.compiler = TariffCompiler(config.osd_tariff)

    def get_series(
        self,
        start_date: date,
        end_date: date,
        resolution_minutes: int = 60
    ) -> PriceBundle:
        """
        Generate price series for date range.

        Currently supports hourly resolution only.
        15-min resolution will repeat hourly values (TODO: proper 15-min support).
        """
        if resolution_minutes not in [15, 60]:
            raise ValueError(f"Resolution must be 15 or 60, got {resolution_minutes}")

        # Compile tariff for date range
        compiled_range = self.compiler.compile_range(start_date, end_date)

        import_prices: List[float] = []
        export_prices: List[float] = []
        breakdowns: List[PriceBreakdown] = []

        current_date = start_date
        while current_date <= end_date:
            compiled_day = compiled_range.get(current_date)

            if compiled_day is None:
                # No tariff data - use defaults
                for hour in range(24):
                    self._append_default_hour(import_prices, export_prices, breakdowns)
            else:
                for hour in range(24):
                    zone_id = compiled_day.hourly_zones[hour]
                    base_rate = compiled_day.hourly_rates[hour]  # Combined rate from tariff

                    # Build breakdown
                    components = {
                        PriceComponent.ENERGY: base_rate,  # Base tariff rate
                    }

                    if self.config.capacity_fee_pln_kwh > 0:
                        components[PriceComponent.CAPACITY_FEE] = self.config.capacity_fee_pln_kwh

                    if self.config.other_components_pln_kwh > 0:
                        components[PriceComponent.OTHER] = self.config.other_components_pln_kwh

                    breakdown = PriceBreakdown(
                        components=components,
                        zone_id=zone_id
                    )

                    total_import = breakdown.total

                    import_prices.append(total_import)
                    export_prices.append(self.config.export_rate_pln_kwh)
                    breakdowns.append(breakdown)

            current_date += timedelta(days=1)

        # Handle 15-min resolution by repeating hourly values
        if resolution_minutes == 15:
            import_prices = self._expand_to_15min(import_prices)
            export_prices = self._expand_to_15min(export_prices)
            breakdowns = self._expand_breakdowns_to_15min(breakdowns)

        return PriceBundle(
            import_total=import_prices,
            export_total=export_prices,
            breakdown=breakdowns,
            source=f"tou:{self.config.osd_tariff.id}",
            start_date=start_date,
            end_date=end_date,
            resolution_minutes=resolution_minutes,
        )

    def _append_default_hour(
        self,
        import_prices: List[float],
        export_prices: List[float],
        breakdowns: List[PriceBreakdown]
    ):
        """Append default prices for an hour with no tariff data"""
        default_rate = self.config.default_rate_pln_kwh
        total = default_rate + self.config.capacity_fee_pln_kwh + self.config.other_components_pln_kwh
        import_prices.append(total)
        export_prices.append(self.config.export_rate_pln_kwh)
        breakdowns.append(PriceBreakdown(
            components={PriceComponent.ENERGY: default_rate},
            zone_id=ZoneId.FLAT
        ))

    def _expand_to_15min(self, hourly: List[float]) -> List[float]:
        """Expand hourly values to 15-min (4x each hour)"""
        result = []
        for val in hourly:
            result.extend([val] * 4)
        return result

    def _expand_breakdowns_to_15min(
        self,
        hourly: List[PriceBreakdown]
    ) -> List[PriceBreakdown]:
        """Expand hourly breakdowns to 15-min"""
        result = []
        for bd in hourly:
            result.extend([bd] * 4)
        return result

    def get_zone_summary(self, start_date: date, end_date: date) -> Dict[str, Any]:
        """
        Get summary statistics by zone.

        Useful for UI display and debugging.
        """
        bundle = self.get_series(start_date, end_date, 60)

        zone_stats: Dict[ZoneId, Dict[str, Any]] = {}

        for i, breakdown in enumerate(bundle.breakdown):
            zone = breakdown.zone_id or ZoneId.FLAT
            if zone not in zone_stats:
                zone_stats[zone] = {
                    "hours": 0,
                    "total_import_price": 0.0,
                    "min_price": float('inf'),
                    "max_price": 0.0,
                }

            price = bundle.import_total[i]
            stats = zone_stats[zone]
            stats["hours"] += 1
            stats["total_import_price"] += price
            stats["min_price"] = min(stats["min_price"], price)
            stats["max_price"] = max(stats["max_price"], price)

        # Calculate averages
        for zone, stats in zone_stats.items():
            if stats["hours"] > 0:
                stats["avg_price"] = stats["total_import_price"] / stats["hours"]
            else:
                stats["avg_price"] = 0.0

            if stats["min_price"] == float('inf'):
                stats["min_price"] = 0.0

        return {
            "zones": {z.value: s for z, s in zone_stats.items()},
            "total_hours": len(bundle.import_total),
            "source": bundle.source,
        }


# =============================================================================
# Flat Price Provider (Legacy Adapter)
# =============================================================================

class FlatPriceProvider:
    """
    Flat price provider for constant prices.

    Adapter for legacy PriceConfig compatibility.
    """

    def __init__(
        self,
        import_price_pln_kwh: float,
        export_price_pln_kwh: float = 0.0
    ):
        """
        Initialize with constant prices.

        Note: Accepts PLN/kWh (not MWh like old PriceConfig).
        """
        self.import_price = import_price_pln_kwh
        self.export_price = export_price_pln_kwh

    @classmethod
    def from_legacy_config(cls, legacy_prices: Any) -> "FlatPriceProvider":
        """
        Create from legacy PriceConfig.

        Handles PLN/MWh to PLN/kWh conversion.
        """
        # Legacy uses PLN/MWh, we use PLN/kWh
        import_kwh = legacy_prices.import_price_pln_mwh / 1000.0
        export_kwh = legacy_prices.export_price_pln_mwh / 1000.0
        return cls(import_kwh, export_kwh)

    def get_series(
        self,
        start_date: date,
        end_date: date,
        resolution_minutes: int = 60
    ) -> PriceBundle:
        """Generate constant price series"""
        n_days = (end_date - start_date).days + 1
        hours_per_day = 24

        if resolution_minutes == 15:
            n_timesteps = n_days * hours_per_day * 4
        else:
            n_timesteps = n_days * hours_per_day

        return PriceBundle.from_constant(
            import_price_pln_kwh=self.import_price,
            export_price_pln_kwh=self.export_price,
            n_timesteps=n_timesteps,
            source="flat"
        )


# =============================================================================
# RDN Price Provider (Day-Ahead Market)
# =============================================================================

class RDNPriceConfig(BaseModel):
    """Configuration for RDN (day-ahead market) price provider."""
    add_other_fees_pln_kwh: float = Field(
        0.0,
        description="Other fees to add on top of RDN price [PLN/kWh]"
    )
    add_osd_variable_pln_kwh: float = Field(
        0.0,
        description="OSD variable fee to add on top of RDN price [PLN/kWh]"
    )
    export_price_pln_kwh: float = Field(
        0.0,
        description="Export price [PLN/kWh]. 0 = zero-export."
    )
    seller_margin_pct: float = Field(
        0.0,
        description="Seller margin [%] on RDN price."
    )


class RDNPriceProvider:
    """
    RDN (Rynek Dnia Następnego) price provider.

    Fetches day-ahead market prices from PSE API or uses cached data.
    Falls back to synthetic prices if API is unavailable.
    """

    def __init__(self, config: Optional[RDNPriceConfig] = None):
        self.config = config or RDNPriceConfig()

    def get_series(
        self,
        start_date: date,
        end_date: date,
        resolution_minutes: int = 60
    ) -> PriceBundle:
        """
        Get RDN price series for date range.

        Tries to fetch from PSE API, falls back to synthetic prices.
        """
        try:
            from rdn_prices import fetch_rdn_prices, rdn_to_price_array
            rdn_data = fetch_rdn_prices(start_date, end_date)

            n_days = (end_date - start_date).days + 1
            n_timesteps = n_days * 24 * (4 if resolution_minutes == 15 else 1)

            # Build time_index for conversion
            from economics_helper import build_time_index_cet_fixed
            time_index = build_time_index_cet_fixed(start_date, n_timesteps, resolution_minutes)

            rdn_prices_kwh = rdn_to_price_array(rdn_data, time_index, resolution_minutes)

            # Apply margin
            if self.config.seller_margin_pct > 0:
                rdn_prices_kwh *= (1 + self.config.seller_margin_pct / 100.0)

            # Add fees
            import_total = (
                rdn_prices_kwh +
                self.config.add_other_fees_pln_kwh +
                self.config.add_osd_variable_pln_kwh
            )
            export_total = np.full(n_timesteps, self.config.export_price_pln_kwh)

            return PriceBundle(
                import_total=import_total.tolist(),
                export_total=export_total.tolist(),
                breakdown=[],
                source="rdn_pse",
                steps=n_timesteps,
                start_date=str(start_date),
                resolution_minutes=resolution_minutes,
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"RDN fetch failed: {e}, using synthetic prices")
            return self._synthetic_fallback(start_date, end_date, resolution_minutes)

    def _synthetic_fallback(self, start_date: date, end_date: date, resolution_minutes: int) -> PriceBundle:
        """Generate synthetic RDN-like prices as fallback."""
        n_days = (end_date - start_date).days + 1
        steps_per_day = 24 * (4 if resolution_minutes == 15 else 1)
        n_timesteps = n_days * steps_per_day

        # Typical Polish RDN profile (PLN/MWh → PLN/kWh)
        hourly_profile_pln_mwh = [
            280, 265, 255, 250, 252, 275,  # 0-5h (night)
            310, 360, 400, 420, 415, 390,  # 6-11h (morning ramp)
            370, 350, 340, 355, 380, 430,  # 12-17h (afternoon)
            470, 450, 410, 370, 330, 300,  # 18-23h (evening peak)
        ]

        prices = []
        for day in range(n_days):
            for h in range(24):
                base = hourly_profile_pln_mwh[h] / 1000.0  # PLN/kWh
                if resolution_minutes == 15:
                    prices.extend([base] * 4)
                else:
                    prices.append(base)

        import_arr = np.array(prices[:n_timesteps])
        if self.config.seller_margin_pct > 0:
            import_arr *= (1 + self.config.seller_margin_pct / 100.0)

        import_arr += self.config.add_other_fees_pln_kwh + self.config.add_osd_variable_pln_kwh
        export_arr = np.full(n_timesteps, self.config.export_price_pln_kwh)

        return PriceBundle(
            import_total=import_arr.tolist(),
            export_total=export_arr.tolist(),
            breakdown=[],
            source="rdn_synthetic",
            steps=n_timesteps,
            start_date=str(start_date),
            resolution_minutes=resolution_minutes,
        )


# =============================================================================
# Hybrid Monthly Price Provider (OSD + RDN per month)
# =============================================================================

class HybridMonthlyPriceProvider:
    """
    Hybrid price provider that stitches OSD tariff and RDN spot prices
    on a per-month basis.

    Example: Q1+Q4 use fixed OSD tariff, Q2+Q3 use RDN spot prices.

    Args:
        tou_provider: ToUPriceProvider for OSD months
        rdn_prices_pln_kwh: numpy array of RDN hourly prices [PLN/kWh]
        monthly_sources: dict mapping month number (1-12) to 'osd' or 'rdn'
        start_date: first date of the analysis period
    """

    def __init__(
        self,
        tou_provider: ToUPriceProvider,
        rdn_prices_pln_kwh: np.ndarray,
        monthly_sources: Dict[int, str],
        start_date: date,
    ):
        self.tou_provider = tou_provider
        self.rdn_prices = rdn_prices_pln_kwh
        self.monthly_sources = monthly_sources
        self.start_date = start_date

    def get_series(
        self,
        start_date: date,
        end_date: date,
        resolution_minutes: int = 60
    ) -> PriceBundle:
        """
        Build stitched price series: OSD for OSD-months, RDN for RDN-months.
        """
        # Get full OSD price series as baseline
        tou_bundle = self.tou_provider.get_series(start_date, end_date, resolution_minutes)
        tou_prices = np.array(tou_bundle.import_total)

        n_days = (end_date - start_date).days + 1
        steps_per_day = 24 * (4 if resolution_minutes == 15 else 1)
        n_timesteps = n_days * steps_per_day

        # Ensure arrays match
        if len(tou_prices) < n_timesteps:
            tou_prices = np.pad(tou_prices, (0, n_timesteps - len(tou_prices)),
                                'edge')

        rdn = self.rdn_prices
        if len(rdn) < n_timesteps:
            repeats = (n_timesteps + len(rdn) - 1) // len(rdn)
            rdn = np.tile(rdn, repeats)[:n_timesteps]
        else:
            rdn = rdn[:n_timesteps]

        # Build result: pick source per timestep based on month
        result = np.copy(tou_prices)
        step = 0
        current_date = start_date
        delta_day = timedelta(days=1)

        for _ in range(n_days):
            month = current_date.month
            source = self.monthly_sources.get(month, 'osd')
            if source == 'rdn':
                end_step = min(step + steps_per_day, n_timesteps)
                result[step:end_step] = rdn[step:end_step]
            step += steps_per_day
            current_date += delta_day

        # Build source label
        rdn_months = [m for m, s in self.monthly_sources.items() if s == 'rdn']
        osd_months = [m for m, s in self.monthly_sources.items() if s != 'rdn']
        source_label = f"hybrid_monthly(RDN:{rdn_months},OSD:{osd_months})"

        export_total = tou_bundle.export_total
        if len(export_total) < n_timesteps:
            export_total = export_total + [0.0] * (n_timesteps - len(export_total))

        return PriceBundle(
            import_total=result[:n_timesteps].tolist(),
            export_total=export_total[:n_timesteps],
            breakdown=[],
            source=source_label,
            start_date=start_date,
            end_date=end_date,
            resolution_minutes=resolution_minutes,
        )


# =============================================================================
# Economic Dispatch Config (for dispatch_economic)
# =============================================================================

class ArbitrageStrategy(str, Enum):
    """
    Arbitrage strategy for price-driven dispatch.

    PERCENTILE_THRESHOLD: Charge below P25, discharge above P75
    ZONE_BASED: Charge in zone III, discharge in zone I
    SPREAD_THRESHOLD: Charge/discharge when spread > threshold
    """
    PERCENTILE_THRESHOLD = "percentile"
    ZONE_BASED = "zone_based"
    SPREAD_THRESHOLD = "spread"


class EconomicDispatchConfig(BaseModel):
    """
    Configuration for economic (price-driven) dispatch.

    Used by dispatch_economic() to make charge/discharge decisions
    based on price signals rather than just PV/load patterns.
    """
    # Arbitrage settings
    strategy: ArbitrageStrategy = Field(
        ArbitrageStrategy.PERCENTILE_THRESHOLD,
        description="Arbitrage decision strategy"
    )

    # Percentile thresholds (for PERCENTILE_THRESHOLD strategy)
    charge_below_percentile: float = Field(
        25.0,
        ge=0,
        le=50,
        description="Charge when price below this percentile [%]"
    )
    discharge_above_percentile: float = Field(
        75.0,
        ge=50,
        le=100,
        description="Discharge when price above this percentile [%]"
    )

    # Spread threshold (for SPREAD_THRESHOLD strategy)
    min_spread_pln_kwh: float = Field(
        0.10,
        ge=0,
        description="Minimum price spread to trigger arbitrage [PLN/kWh]"
    )

    # Zone-based settings (for ZONE_BASED strategy)
    charge_zones: List[ZoneId] = Field(
        default_factory=lambda: [ZoneId.III],
        description="Zones allowed for grid charging"
    )
    discharge_zones: List[ZoneId] = Field(
        default_factory=lambda: [ZoneId.I],
        description="Zones preferred for discharge"
    )

    # Degradation cost
    degradation_cost_pln_kwh: float = Field(
        0.05,
        ge=0,
        description="Cost of battery degradation per kWh throughput [PLN/kWh]"
    )

    # Reserve SOC for peak shaving (hybrid mode)
    reserve_soc_fraction: float = Field(
        0.0,
        ge=0,
        le=0.8,
        description="SOC fraction reserved for peak shaving [0-1]"
    )

    # Grid charging constraints
    allow_grid_charging: bool = Field(
        True,
        description="Allow charging from grid (not just PV)"
    )
    max_grid_charge_kw: Optional[float] = Field(
        None,
        description="Max power for grid charging [kW] - None = battery limit"
    )


class EconomicDispatchConstraints(BaseModel):
    """
    Constraints for economic dispatch optimization.

    Hard limits that must not be violated.
    """
    # Grid constraints
    max_grid_import_kw: Optional[float] = Field(
        None,
        description="Maximum grid import power [kW]"
    )
    max_grid_export_kw: Optional[float] = Field(
        None,
        description="Maximum grid export power [kW]"
    )

    # Peak shaving target (optional - for hybrid modes)
    peak_limit_kw: Optional[float] = Field(
        None,
        description="Grid import limit for peak shaving [kW]"
    )

    # Time-of-use restrictions
    no_discharge_hours: List[int] = Field(
        default_factory=list,
        description="Hours when discharge is forbidden (e.g., [22, 23, 0, 1, 2, 3, 4, 5])"
    )
    no_charge_hours: List[int] = Field(
        default_factory=list,
        description="Hours when grid charging is forbidden"
    )


# =============================================================================
# Utility Functions
# =============================================================================

def calculate_arbitrage_thresholds(
    prices: PriceBundle,
    config: EconomicDispatchConfig
) -> Dict[str, float]:
    """
    Calculate price thresholds for arbitrage decisions.

    Returns dict with:
    - charge_threshold: Price below which to charge
    - discharge_threshold: Price above which to discharge
    - spread_required: Minimum spread after degradation cost
    """
    import_array = prices.get_import_array()

    if config.strategy == ArbitrageStrategy.PERCENTILE_THRESHOLD:
        charge_threshold = float(np.percentile(import_array, config.charge_below_percentile))
        discharge_threshold = float(np.percentile(import_array, config.discharge_above_percentile))
    elif config.strategy == ArbitrageStrategy.SPREAD_THRESHOLD:
        median_price = float(np.median(import_array))
        charge_threshold = median_price - config.min_spread_pln_kwh / 2
        discharge_threshold = median_price + config.min_spread_pln_kwh / 2
    else:
        # ZONE_BASED - use zone-based logic in dispatch
        charge_threshold = float(np.percentile(import_array, 33))
        discharge_threshold = float(np.percentile(import_array, 67))

    # Spread required considering roundtrip efficiency and degradation
    # spread_required = 2 * degradation_cost + (1 - roundtrip_eff) * avg_price
    avg_price = float(np.mean(import_array))
    spread_required = 2 * config.degradation_cost_pln_kwh + 0.10 * avg_price  # Assume 90% RTE

    return {
        "charge_threshold": charge_threshold,
        "discharge_threshold": discharge_threshold,
        "spread_required": spread_required,
        "price_min": float(np.min(import_array)),
        "price_max": float(np.max(import_array)),
        "price_mean": avg_price,
        "price_spread": float(np.max(import_array) - np.min(import_array)),
    }


def estimate_arbitrage_potential(
    prices: PriceBundle,
    battery_kwh: float,
    roundtrip_efficiency: float = 0.90,
    degradation_cost_pln_kwh: float = 0.05
) -> Dict[str, float]:
    """
    Estimate theoretical arbitrage potential for given prices and battery.

    Simple estimation based on daily price spreads.
    """
    import_array = prices.get_import_array()

    # Daily analysis (assuming hourly resolution)
    hours_per_day = 24
    n_days = len(import_array) // hours_per_day

    total_arbitrage_value = 0.0

    for day in range(n_days):
        start = day * hours_per_day
        end = start + hours_per_day
        day_prices = import_array[start:end]

        min_price = np.min(day_prices)
        max_price = np.max(day_prices)
        spread = max_price - min_price

        # Value per cycle = spread * capacity * RTE - degradation
        cycle_value = (
            spread * battery_kwh * roundtrip_efficiency
            - 2 * battery_kwh * degradation_cost_pln_kwh
        )

        if cycle_value > 0:
            total_arbitrage_value += cycle_value

    # Calculate annualization factor based on actual data period
    # If data is less than a year, scale up; if more, scale down
    annualization_factor = 365.0 / max(n_days, 1) if n_days < 365 else 1.0

    return {
        "total_potential_pln": total_arbitrage_value,
        "daily_avg_pln": total_arbitrage_value / max(n_days, 1),
        "annual_estimate_pln": total_arbitrage_value * annualization_factor,
        "period_days": n_days,
        "annualization_factor": annualization_factor,
        "n_profitable_days": sum(
            1 for day in range(n_days)
            if (np.max(import_array[day*24:(day+1)*24]) -
                np.min(import_array[day*24:(day+1)*24])) * battery_kwh * roundtrip_efficiency
                > 2 * battery_kwh * degradation_cost_pln_kwh
        ),
    }

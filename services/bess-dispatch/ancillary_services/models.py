"""
Data models for ancillary services and battery virtualization.

Covers:
- Service type definitions (aFRR, mFRR, FCR, capacity market)
- Battery slice configuration (virtual partitioning)
- Revenue results per service
- Polish market parameters (PSE/URE)
"""

from enum import Enum
from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel, Field


class AncillaryServiceType(str, Enum):
    """Supported ancillary service types for Polish market."""
    # Frequency services
    AFRR_UP = "aFRR_up"         # Automatic FRR upward (discharge)
    AFRR_DOWN = "aFRR_down"     # Automatic FRR downward (charge)
    MFRR_UP = "mFRR_up"         # Manual FRR upward (discharge)
    MFRR_DOWN = "mFRR_down"     # Manual FRR downward (charge)
    FCR = "fcr"                 # Frequency Containment Reserve (symmetric)

    # Market services
    CAPACITY_MARKET = "capacity_market"   # Rynek Mocy
    ENERGY_ARBITRAGE = "energy_arbitrage" # RDN/TGE price spreads

    # Behind-the-meter services
    PEAK_SHAVING = "peak_shaving"
    PV_SURPLUS = "pv_surplus"


# Service characteristics
SERVICE_PROPERTIES = {
    AncillaryServiceType.AFRR_UP: {
        "direction": "discharge",
        "activation_time_s": 300,      # 5 min full activation
        "min_duration_min": 15,        # 15-min product
        "symmetric": False,
        "capacity_reservation": True,  # Must reserve capacity
        "platform": "PICASSO",
    },
    AncillaryServiceType.AFRR_DOWN: {
        "direction": "charge",
        "activation_time_s": 300,
        "min_duration_min": 15,
        "symmetric": False,
        "capacity_reservation": True,
        "platform": "PICASSO",
    },
    AncillaryServiceType.MFRR_UP: {
        "direction": "discharge",
        "activation_time_s": 750,      # 12.5 min
        "min_duration_min": 15,
        "symmetric": False,
        "capacity_reservation": True,
        "platform": "MARI",
    },
    AncillaryServiceType.MFRR_DOWN: {
        "direction": "charge",
        "activation_time_s": 750,
        "min_duration_min": 15,
        "symmetric": False,
        "capacity_reservation": True,
        "platform": "MARI",
    },
    AncillaryServiceType.FCR: {
        "direction": "symmetric",
        "activation_time_s": 30,       # 30s full activation
        "min_duration_min": 15,        # 15-min blocks
        "symmetric": True,
        "capacity_reservation": True,
        "platform": "FCR_cooperation",
    },
    AncillaryServiceType.CAPACITY_MARKET: {
        "direction": "discharge",
        "activation_time_s": 0,        # Availability-based
        "min_duration_min": 0,
        "symmetric": False,
        "capacity_reservation": True,
        "platform": "PSE_RM",
    },
    AncillaryServiceType.ENERGY_ARBITRAGE: {
        "direction": "both",
        "activation_time_s": 0,
        "min_duration_min": 60,
        "symmetric": False,
        "capacity_reservation": False,
        "platform": "RDN/TGE",
    },
    AncillaryServiceType.PEAK_SHAVING: {
        "direction": "discharge",
        "activation_time_s": 0,
        "min_duration_min": 0,
        "symmetric": False,
        "capacity_reservation": True,  # Reserve SoC
        "platform": "behind_meter",
    },
    AncillaryServiceType.PV_SURPLUS: {
        "direction": "charge",
        "activation_time_s": 0,
        "min_duration_min": 0,
        "symmetric": False,
        "capacity_reservation": False,
        "platform": "behind_meter",
    },
}


class AncillaryServiceConfig(BaseModel):
    """Configuration for a single ancillary service."""
    service_type: AncillaryServiceType
    enabled: bool = True

    # Capacity allocation
    power_kw: float = Field(0.0, ge=0, description="Power allocated to this service [kW]")
    energy_kwh: float = Field(0.0, ge=0, description="Energy allocated to this service [kWh]")

    # Revenue parameters
    capacity_price_pln_mw_h: float = Field(
        0.0, ge=0,
        description="Capacity payment [PLN/MW/h] for availability"
    )
    energy_price_pln_mwh: float = Field(
        0.0, ge=0,
        description="Energy payment [PLN/MWh] for activation"
    )

    # Activation parameters
    expected_activation_hours_per_year: float = Field(
        0.0, ge=0,
        description="Expected activation hours per year"
    )
    expected_activations_per_year: int = Field(
        0, ge=0,
        description="Expected number of activations (test + real)"
    )

    # Aggregator margin
    aggregator_margin_pct: float = Field(
        20.0, ge=0, le=100,
        description="Aggregator margin deducted from revenue [%]"
    )

    # Availability constraint
    min_availability_pct: float = Field(
        95.0, ge=0, le=100,
        description="Minimum availability requirement [%]"
    )

    # Price timeseries (optional, for hourly optimization)
    hourly_prices_pln_mw: Optional[List[float]] = Field(
        None,
        description="Hourly capacity prices [PLN/MW] for time-varying optimization"
    )


class BatterySlice(BaseModel):
    """
    Virtual partition of a physical battery for a specific service.

    Each slice has its own SoC bounds and power limits,
    but shares the physical hardware.
    """
    service_type: AncillaryServiceType
    label: str = ""

    # Capacity allocation (subset of physical battery)
    power_kw: float = Field(..., ge=0, description="Max power for this slice [kW]")
    energy_kwh: float = Field(..., ge=0, description="Energy capacity for this slice [kWh]")

    # SoC bounds within this slice
    soc_min_pct: float = Field(10.0, ge=0, le=100)
    soc_max_pct: float = Field(90.0, ge=0, le=100)

    # Priority (lower = higher priority, used for conflict resolution)
    priority: int = Field(5, ge=1, le=10)

    # Time windows (hours of day when this service is active)
    active_hours: Optional[List[int]] = Field(
        None,
        description="Hours when this slice is active (None = always)"
    )

    # Current state
    soc_kwh: float = Field(0.0, ge=0, description="Current SoC [kWh]")

    @property
    def usable_energy_kwh(self) -> float:
        """Usable energy between SoC bounds."""
        return self.energy_kwh * (self.soc_max_pct - self.soc_min_pct) / 100.0

    @property
    def available_charge_kwh(self) -> float:
        """Available charge headroom."""
        max_soc = self.energy_kwh * self.soc_max_pct / 100.0
        return max(0, max_soc - self.soc_kwh)

    @property
    def available_discharge_kwh(self) -> float:
        """Available discharge energy."""
        min_soc = self.energy_kwh * self.soc_min_pct / 100.0
        return max(0, self.soc_kwh - min_soc)


class BatteryVirtualizationConfig(BaseModel):
    """
    Configuration for virtualizing a physical battery into service slices.

    The sum of all slice capacities must not exceed the physical battery.
    Slices can overlap in time (co-optimization resolves conflicts).
    """
    # Physical battery limits
    total_power_kw: float = Field(..., gt=0)
    total_energy_kwh: float = Field(..., gt=0)
    roundtrip_efficiency: float = Field(0.90, ge=0.7, le=1.0)

    # Service slices
    slices: List[BatterySlice] = Field(default_factory=list)

    # Optimization mode
    allow_dynamic_reallocation: bool = Field(
        True,
        description="Allow optimizer to shift capacity between slices dynamically"
    )

    # Conflict resolution
    priority_mode: str = Field(
        "strict",
        description="How to handle slice conflicts: 'strict' (by priority) or 'proportional'"
    )

    def validate_allocation(self) -> List[str]:
        """Check that slices don't over-allocate physical battery."""
        warnings = []
        total_power = sum(s.power_kw for s in self.slices)
        total_energy = sum(s.energy_kwh for s in self.slices)

        if total_power > self.total_power_kw * 1.01:
            warnings.append(
                f"Over-allocated power: {total_power:.0f} kW > {self.total_power_kw:.0f} kW physical. "
                f"Dynamic reallocation will manage conflicts."
            )
        if total_energy > self.total_energy_kwh * 1.01:
            warnings.append(
                f"Over-allocated energy: {total_energy:.0f} kWh > {self.total_energy_kwh:.0f} kWh physical. "
                f"Dynamic reallocation will manage conflicts."
            )
        return warnings

    def get_slice(self, service_type: AncillaryServiceType) -> Optional[BatterySlice]:
        """Get slice for a specific service type."""
        for s in self.slices:
            if s.service_type == service_type:
                return s
        return None


# ── Polish Market Presets ────────────────────────────────────────

class PolishMarketPreset(BaseModel):
    """Polish ancillary services market parameters."""
    year: int = 2026

    # aFRR prices (PLN/MW/h) - capacity payment for availability
    afrr_up_capacity_pln_mw_h: float = Field(
        181.0, description="aFRR upward capacity price [PLN/MW/h] (2025 avg)"
    )
    afrr_down_capacity_pln_mw_h: float = Field(
        120.0, description="aFRR downward capacity price [PLN/MW/h]"
    )

    # mFRR prices
    mfrr_up_capacity_pln_mw_h: float = Field(
        95.0, description="mFRR upward capacity price [PLN/MW/h]"
    )
    mfrr_down_capacity_pln_mw_h: float = Field(
        60.0, description="mFRR downward capacity price [PLN/MW/h]"
    )

    # FCR
    fcr_capacity_pln_mw_h: float = Field(
        45.0, description="FCR capacity price [PLN/MW/h]"
    )

    # Capacity Market (Rynek Mocy)
    capacity_market_pln_mw_year: float = Field(
        264900.0, description="Capacity market payment [PLN/MW/year]"
    )
    kwd: float = Field(
        0.133, description="KWD - availability penalty coefficient"
    )

    # Energy prices (for activation)
    afrr_energy_pln_mwh: float = Field(
        400.0, description="aFRR energy activation price [PLN/MWh]"
    )
    mfrr_energy_pln_mwh: float = Field(
        500.0, description="mFRR energy activation price [PLN/MWh]"
    )

    # Expected activations
    afrr_activation_hours_year: float = Field(
        500.0, description="Expected aFRR activation hours/year"
    )
    mfrr_activations_year: int = Field(
        8, description="Expected mFRR activations/year (test + real)"
    )
    capacity_market_test_activations: int = Field(
        4, description="Capacity market test call-ups/year"
    )
    capacity_market_real_activations: int = Field(
        4, description="Capacity market real call-ups/year"
    )

    # Aggregator
    aggregator_margin_pct: float = Field(20.0, description="Aggregator margin [%]")


POLISH_MARKET_PRESETS: Dict[int, PolishMarketPreset] = {
    2025: PolishMarketPreset(
        year=2025,
        afrr_up_capacity_pln_mw_h=181.0,
        afrr_down_capacity_pln_mw_h=120.0,
        capacity_market_pln_mw_year=264900.0,
    ),
    2026: PolishMarketPreset(
        year=2026,
        afrr_up_capacity_pln_mw_h=200.0,
        afrr_down_capacity_pln_mw_h=130.0,
        capacity_market_pln_mw_year=280000.0,
    ),
}


# ── Revenue Results ──────────────────────────────────────────────

class ServiceRevenueDetail(BaseModel):
    """Revenue breakdown for a single service."""
    service_type: AncillaryServiceType
    enabled: bool = True

    # Capacity revenue
    capacity_revenue_pln: float = Field(0.0, description="Revenue from capacity availability [PLN/year]")
    availability_hours: float = Field(0.0, description="Hours of availability provided")

    # Energy/activation revenue
    energy_revenue_pln: float = Field(0.0, description="Revenue from energy activations [PLN/year]")
    activation_count: int = Field(0, description="Number of activations")
    activation_energy_mwh: float = Field(0.0, description="Total energy activated [MWh]")

    # Costs
    aggregator_fee_pln: float = Field(0.0, description="Aggregator margin deducted [PLN]")
    degradation_cost_pln: float = Field(0.0, description="Battery degradation cost [PLN]")
    efficiency_loss_pln: float = Field(0.0, description="Roundtrip efficiency loss cost [PLN]")

    # Net
    gross_revenue_pln: float = Field(0.0, description="Gross revenue before deductions [PLN/year]")
    net_revenue_pln: float = Field(0.0, description="Net revenue after all deductions [PLN/year]")

    # Battery usage
    efc_contribution: float = Field(0.0, description="EFC cycles consumed by this service")
    throughput_mwh: float = Field(0.0, description="Total throughput for this service [MWh]")

    # Allocation
    power_allocated_kw: float = Field(0.0)
    energy_allocated_kwh: float = Field(0.0)


class AncillaryRevenueResult(BaseModel):
    """Complete ancillary services revenue calculation."""
    services: List[ServiceRevenueDetail] = Field(default_factory=list)

    total_gross_revenue_pln: float = Field(0.0)
    total_net_revenue_pln: float = Field(0.0)
    total_aggregator_fees_pln: float = Field(0.0)
    total_degradation_cost_pln: float = Field(0.0)
    total_efc: float = Field(0.0)
    total_throughput_mwh: float = Field(0.0)

    market_preset: Optional[PolishMarketPreset] = None


class StackedRevenueResult(BaseModel):
    """Combined result: behind-the-meter + ancillary services."""
    # Behind-the-meter (existing dispatch)
    btm_savings_pln: float = Field(0.0, description="Peak shaving + PV surplus + arbitrage savings")
    btm_efc: float = Field(0.0)

    # Ancillary services (new)
    ancillary_revenue: AncillaryRevenueResult = Field(default_factory=AncillaryRevenueResult)

    # Total stacked
    total_annual_revenue_pln: float = Field(0.0, description="BTM savings + ancillary revenue")
    total_efc: float = Field(0.0, description="Total EFC from all services")

    # Allocation summary
    allocation_summary: Dict[str, Dict[str, float]] = Field(
        default_factory=dict,
        description="Per-service allocation: {service: {power_kw, energy_kwh, revenue_pln}}"
    )

    # Warnings
    warnings: List[str] = Field(default_factory=list)

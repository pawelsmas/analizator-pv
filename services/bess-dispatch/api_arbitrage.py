"""
ToU Arbitrage API Endpoints
===========================

FastAPI router for Time-of-Use tariff arbitrage dispatch.

Endpoints:
- POST /arbitrage/dispatch - Run arbitrage dispatch simulation
- GET /arbitrage/tariffs - List available tariff presets
- POST /arbitrage/prices - Preview price series for date range

Version: 1.0.0
"""

import time
from datetime import date, datetime
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from models import (
    DispatchResult,
    BatteryParams,
    PriceConfig,
)
from dispatch_arbitrage import run_arbitrage_with_price_bundle
from price_engine import (
    ToUPriceProvider,
    ToUPriceConfig,
    EconomicDispatchConfig,
    ArbitrageStrategy,
    PriceBundle,
    calculate_arbitrage_thresholds,
    estimate_arbitrage_potential,
)
from osd_tariffs.models import ZoneId, OsdTariff
from osd_tariffs.presets import list_presets
from osd_tariffs.presets.templates import ALL_PRESETS


def get_tariff_by_id(preset_id: str) -> Optional[OsdTariff]:
    """Get a preset tariff by ID (matches tariff.id, not dict key)."""
    # First try direct key lookup
    if preset_id in ALL_PRESETS:
        return ALL_PRESETS[preset_id]
    # Then search by tariff.id
    for tariff in ALL_PRESETS.values():
        if tariff.id == preset_id:
            return tariff
    return None


router = APIRouter(prefix="/arbitrage", tags=["arbitrage"])


# =============================================================================
# Request/Response Models
# =============================================================================

class ArbitrageDispatchRequest(BaseModel):
    """Request for ToU arbitrage dispatch simulation"""

    # Load profile
    load_kw: List[float] = Field(..., min_length=24, description="Load consumption [kW] per hour")
    start_date: str = Field(..., description="Start date (YYYY-MM-DD) for price lookup")

    # Battery configuration
    battery_power_kw: float = Field(..., gt=0, description="Battery power [kW]")
    battery_energy_kwh: float = Field(..., gt=0, description="Battery capacity [kWh]")
    roundtrip_efficiency: float = Field(0.90, ge=0.7, le=1.0)
    soc_min: float = Field(0.10, ge=0.0, le=0.5)
    soc_max: float = Field(0.90, ge=0.5, le=1.0)
    soc_initial: float = Field(0.50, ge=0.0, le=1.0)

    # Tariff configuration
    tariff_id: str = Field(
        "pge_dystrybucja_c12a_2025",
        description="OSD tariff preset ID (from /arbitrage/tariffs)"
    )
    capacity_fee_pln_kwh: float = Field(
        0.12,
        ge=0,
        description="Capacity market fee [PLN/kWh]"
    )
    other_components_pln_kwh: float = Field(
        0.0,
        ge=0,
        description="Other charges (akcyza, OZE, etc.) [PLN/kWh]"
    )

    # Arbitrage strategy
    strategy: str = Field(
        "percentile",
        description="Arbitrage strategy: percentile, zone_based, spread"
    )
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

    # Optional peak shaving constraint (hybrid mode)
    peak_limit_kw: Optional[float] = Field(
        None,
        description="Grid import limit for hybrid peak+arbitrage mode [kW]"
    )

    # Demand charge for economics
    demand_charge_pln_kw_month: float = Field(
        0.0,
        ge=0,
        description="Monthly demand charge [PLN/kW/month]"
    )

    # Options
    return_hourly: bool = Field(True, description="Include hourly arrays in response")


class ArbitrageDispatchResponse(BaseModel):
    """Enhanced response with arbitrage-specific metrics"""
    dispatch: DispatchResult
    price_summary: Dict[str, Any]
    arbitrage_analysis: Dict[str, Any]
    compute_time_ms: float


class TariffListResponse(BaseModel):
    """List of available tariff presets"""
    tariffs: List[Dict[str, Any]]


class PricePreviewRequest(BaseModel):
    """Request for price preview"""
    tariff_id: str = Field(..., description="OSD tariff preset ID")
    start_date: str = Field(..., description="Start date (YYYY-MM-DD)")
    end_date: str = Field(..., description="End date (YYYY-MM-DD)")
    capacity_fee_pln_kwh: float = Field(0.0, ge=0)
    other_components_pln_kwh: float = Field(0.0, ge=0)


class PricePreviewResponse(BaseModel):
    """Price preview response"""
    tariff_id: str
    start_date: str
    end_date: str
    n_hours: int
    zone_summary: Dict[str, Any]
    sample_prices: List[Dict[str, Any]]
    arbitrage_potential: Dict[str, Any]


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/tariffs", response_model=TariffListResponse)
async def get_available_tariffs():
    """
    List available OSD tariff presets.

    Returns tariff IDs, names, groups, and zone information.
    """
    try:
        presets = list_presets()
        tariffs = []

        for preset in presets:
            tariffs.append({
                "id": preset.id,
                "name": preset.name,
                "osd": preset.osd,
                "group": preset.group,
                "zones": list(preset.zones),
                "zones_count": preset.zones_count,
                "has_seasonality": preset.has_seasonality,
            })

        return TariffListResponse(tariffs=tariffs)

    except Exception as e:
        raise HTTPException(500, f"Error listing tariffs: {str(e)}")


@router.post("/prices/preview", response_model=PricePreviewResponse)
async def preview_prices(request: PricePreviewRequest):
    """
    Preview price series for a date range.

    Shows zone distribution, sample prices, and estimated arbitrage potential.
    """
    try:
        # Parse dates
        start = datetime.strptime(request.start_date, "%Y-%m-%d").date()
        end = datetime.strptime(request.end_date, "%Y-%m-%d").date()

        if end < start:
            raise HTTPException(400, "end_date must be >= start_date")

        # Get tariff
        tariff = get_tariff_by_id(request.tariff_id)
        if tariff is None:
            raise HTTPException(404, f"Tariff not found: {request.tariff_id}")

        # Create provider
        config = ToUPriceConfig(
            osd_tariff=tariff,
            capacity_fee_pln_kwh=request.capacity_fee_pln_kwh,
            other_components_pln_kwh=request.other_components_pln_kwh,
        )
        provider = ToUPriceProvider(config)

        # Get prices
        prices = provider.get_series(start, end, 60)

        # Zone summary
        zone_summary = provider.get_zone_summary(start, end)

        # Sample prices (first 48 hours)
        sample_prices = []
        for i in range(min(48, prices.n_timesteps)):
            bd = prices.breakdown[i]
            sample_prices.append({
                "hour": i,
                "zone": bd.zone_id.value if bd.zone_id else "FLAT",
                "import_total": round(prices.import_total[i], 4),
                "breakdown": {k.value: round(v, 4) for k, v in bd.components.items()},
            })

        # Estimate arbitrage potential for 100 kWh battery
        potential = estimate_arbitrage_potential(
            prices,
            battery_kwh=100,
            roundtrip_efficiency=0.90,
            degradation_cost_pln_kwh=0.05
        )

        return PricePreviewResponse(
            tariff_id=request.tariff_id,
            start_date=request.start_date,
            end_date=request.end_date,
            n_hours=prices.n_timesteps,
            zone_summary=zone_summary,
            sample_prices=sample_prices,
            arbitrage_potential={
                "battery_kwh": 100,
                "total_potential_pln": round(potential["total_potential_pln"], 2),
                "daily_avg_pln": round(potential["daily_avg_pln"], 2),
                "annual_estimate_pln": round(potential["annual_estimate_pln"], 0),
                "n_profitable_days": potential["n_profitable_days"],
            },
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(400, f"Invalid request: {str(e)}")
    except Exception as e:
        raise HTTPException(500, f"Price preview error: {str(e)}")


@router.post("/dispatch", response_model=ArbitrageDispatchResponse)
async def run_arbitrage_dispatch(request: ArbitrageDispatchRequest):
    """
    Run ToU arbitrage dispatch simulation.

    Uses time-varying prices from OSD tariff to optimize battery charge/discharge:
    - Charges when price is low (below percentile threshold)
    - Discharges when price is high (above percentile threshold)
    - Optionally enforces peak_limit_kw for hybrid peak+arbitrage mode

    Returns:
    - Full dispatch result with energy flows
    - Price summary (zone distribution, thresholds)
    - Arbitrage analysis (savings, spread, efficiency)
    """
    start_time = time.time()

    try:
        # Parse start date
        start_date = datetime.strptime(request.start_date, "%Y-%m-%d").date()

        # Calculate end date from load length
        n_hours = len(request.load_kw)
        n_days = (n_hours + 23) // 24
        end_date = start_date + __import__('datetime').timedelta(days=n_days - 1)

        # Get tariff
        tariff = get_tariff_by_id(request.tariff_id)
        if tariff is None:
            raise HTTPException(404, f"Tariff not found: {request.tariff_id}")

        # Create price provider
        price_config = ToUPriceConfig(
            osd_tariff=tariff,
            capacity_fee_pln_kwh=request.capacity_fee_pln_kwh,
            other_components_pln_kwh=request.other_components_pln_kwh,
        )
        provider = ToUPriceProvider(price_config)

        # Get price bundle
        prices = provider.get_series(start_date, end_date, 60)

        # Truncate/pad prices to match load length
        if prices.n_timesteps < n_hours:
            raise HTTPException(
                400,
                f"Price data too short ({prices.n_timesteps}h) for load ({n_hours}h)"
            )
        elif prices.n_timesteps > n_hours:
            # Truncate prices
            prices = PriceBundle(
                import_total=prices.import_total[:n_hours],
                export_total=prices.export_total[:n_hours],
                breakdown=prices.breakdown[:n_hours],
                source=prices.source,
                start_date=prices.start_date,
                end_date=prices.end_date,
                resolution_minutes=prices.resolution_minutes,
            )

        # Create battery
        battery = BatteryParams.from_roundtrip(
            power_kw=request.battery_power_kw,
            energy_kwh=request.battery_energy_kwh,
            roundtrip_eff=request.roundtrip_efficiency,
            soc_min=request.soc_min,
            soc_max=request.soc_max,
            soc_initial=request.soc_initial,
        )

        # Create arbitrage config
        strategy_map = {
            "percentile": ArbitrageStrategy.PERCENTILE_THRESHOLD,
            "zone_based": ArbitrageStrategy.ZONE_BASED,
            "spread": ArbitrageStrategy.SPREAD_THRESHOLD,
        }
        strategy = strategy_map.get(request.strategy, ArbitrageStrategy.PERCENTILE_THRESHOLD)

        arb_config = EconomicDispatchConfig(
            strategy=strategy,
            charge_below_percentile=request.charge_below_percentile,
            discharge_above_percentile=request.discharge_above_percentile,
        )

        # Legacy prices for demand charge
        legacy_prices = PriceConfig(
            import_price_pln_mwh=800.0,  # Not used for energy cost
            demand_charge_pln_kw_month=request.demand_charge_pln_kw_month,
        )

        # Run dispatch
        result = run_arbitrage_with_price_bundle(
            load_kw=request.load_kw,
            battery=battery,
            price_bundle=prices,
            config=arb_config,
            peak_limit_kw=request.peak_limit_kw,
            legacy_prices=legacy_prices,
        )

        # Remove hourly arrays if not requested
        if not request.return_hourly:
            result.hourly_charge_kw = None
            result.hourly_discharge_kw = None
            result.hourly_soc_pct = None
            result.hourly_grid_import_kw = None
            result.hourly_grid_export_kw = None

        # Calculate thresholds for response
        thresholds = calculate_arbitrage_thresholds(prices, arb_config)

        # Zone summary
        zone_summary = provider.get_zone_summary(start_date, end_date)

        # Build response
        compute_time = (time.time() - start_time) * 1000

        return ArbitrageDispatchResponse(
            dispatch=result,
            price_summary={
                "tariff_id": request.tariff_id,
                "n_hours": n_hours,
                "zones": zone_summary.get("zones", {}),
                "thresholds": {
                    "charge_below": round(thresholds["charge_threshold"], 4),
                    "discharge_above": round(thresholds["discharge_threshold"], 4),
                    "price_min": round(thresholds["price_min"], 4),
                    "price_max": round(thresholds["price_max"], 4),
                    "price_mean": round(thresholds["price_mean"], 4),
                    "spread": round(thresholds["price_spread"], 4),
                },
            },
            arbitrage_analysis={
                "mode": "hybrid" if request.peak_limit_kw else "pure_arbitrage",
                "peak_limit_kw": request.peak_limit_kw,
                "energy_savings_pln": round(result.info.get("arbitrage", {}).get("energy_savings", 0), 2),
                "demand_savings_pln": round(result.info.get("arbitrage", {}).get("demand_savings_pln", 0), 2) if request.peak_limit_kw else 0,
                "avg_charge_price": round(result.info.get("arbitrage", {}).get("avg_charge_price", 0), 4),
                "avg_discharge_price": round(result.info.get("arbitrage", {}).get("avg_discharge_price", 0), 4),
                "realized_spread": round(result.info.get("arbitrage", {}).get("spread", 0), 4),
            },
            compute_time_ms=round(compute_time, 1),
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(400, f"Invalid request: {str(e)}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Arbitrage dispatch error: {str(e)}")

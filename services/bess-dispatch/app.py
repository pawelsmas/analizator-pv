"""
BESS Dispatch Service
=====================
FastAPI service for BESS dispatch simulation and sizing.

Endpoints:
- POST /dispatch - Run dispatch simulation
- POST /sizing - Run sizing optimization with S/M/L variants
- POST /sizing/quick - Quick sizing for PV-surplus mode
- GET /health - Health check
- GET /info - Service info and capabilities

Port: 8031
"""

import io
import time
from typing import List, Optional, Dict, Any, Union
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel, Field

from observability.http_metrics import (
    HTTP_REQUESTS_TOTAL,
    HTTP_REQUEST_DURATION_SECONDS,
    SERVICE_NAME,
)

from models import (
    DispatchRequest,
    DispatchResult,
    DispatchMode,
    SizingRequest,
    SizingResult,
    BatteryParams,
    StackedModeParams,
    DegradationBudget,
    PriceConfig,
    TimeResolution,
    TopologyType,
    SensitivityRequest,
    SensitivityResult,
    SensitivityParameter,
    SensitivityRange,
    OptimizationConfig,
    OptimizationObjective,
    SizingConstraint,
    ConstraintType,
    ArbitrageConfig,
    ArbitrageStrategy,
)
from dispatch_engine import run_dispatch
from sizing_runner import run_sizing, run_quick_sizing
from sensitivity_runner import run_sensitivity_analysis
from common.logging_structured import (
    log_dispatch_request,
    log_dispatch_response,
    record_dispatch_metrics,
)


# =============================================================================
# Application Setup
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler"""
    print("BESS Dispatch Service starting...")
    yield
    print("BESS Dispatch Service shutting down...")


app = FastAPI(
    title="BESS Dispatch Service",
    description="Battery Energy Storage System dispatch simulation and sizing",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Prometheus HTTP metrics middleware
@app.middleware("http")
async def prometheus_http_middleware(request: Request, call_next):
    """Record HTTP metrics for all requests."""
    start = time.perf_counter()
    status = "500"
    endpoint = "unknown"

    try:
        response = await call_next(request)
        status = str(response.status_code)

        # Use route template path for low cardinality
        route = request.scope.get("route")
        if route and getattr(route, "path", None):
            endpoint = route.path
        else:
            endpoint = request.url.path

        return response
    except Exception:
        status = "500"
        raise
    finally:
        duration = time.perf_counter() - start
        method = request.method

        HTTP_REQUEST_DURATION_SECONDS.labels(
            service=SERVICE_NAME,
            endpoint=endpoint,
            method=method,
        ).observe(duration)

        HTTP_REQUESTS_TOTAL.labels(
            service=SERVICE_NAME,
            endpoint=endpoint,
            method=method,
            status=status,
        ).inc()


# Include arbitrage router
from api_arbitrage import router as arbitrage_router
app.include_router(arbitrage_router)


# =============================================================================
# Health and Info Endpoints
# =============================================================================

class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class ServiceInfo(BaseModel):
    name: str
    version: str
    description: str
    dispatch_modes: List[str]
    supported_intervals: List[int]
    sizing_variants: List[str]
    features: List[str]


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        status="healthy",
        service="bess-dispatch",
        version="1.0.0"
    )


@app.get("/metrics")
def metrics_root():
    """Prometheus metrics endpoint"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/info", response_model=ServiceInfo)
async def service_info():
    """Service information and capabilities"""
    return ServiceInfo(
        name="BESS Dispatch Service",
        version="1.3.0",
        description="Time-based dispatch simulation with degradation tracking and ToU arbitrage",
        dispatch_modes=[m.value for m in DispatchMode],
        supported_intervals=[15, 60],
        sizing_variants=["small (1h)", "medium (2h)", "large (4h)"],
        features=[
            "PV-surplus (autokonsumpcja) dispatch",
            "Peak shaving dispatch",
            "STACKED mode (PV + Peak with SOC reserve)",
            "LOAD_ONLY mode (stand-alone BESS without PV)",
            "ToU Arbitrage (STACKED + price-driven charging/discharging)",
            "Topology support (pv_load, load_only)",
            "Throughput and EFC tracking",
            "Per-service degradation breakdown",
            "Degradation budget monitoring",
            "S/M/L sizing variants",
            "NPV-based optimization with arbitrage savings",
            "Capacity fee (opłata mocowa) post-dispatch calculation",
            "Sensitivity analysis (tornado chart)",
            "OSD tariff presets (C11, C12a, C12b, C21, C22a, C22b)",
        ]
    )


# =============================================================================
# Dispatch Endpoint
# =============================================================================

class ArbitrageConfigAPI(BaseModel):
    """API model for ToU arbitrage configuration"""
    enabled: bool = Field(True, description="Enable ToU arbitrage")
    tariff_id: str = Field("pge_c12a_2025", description="OSD tariff preset ID")
    strategy: str = Field("percentile", description="Strategy: percentile, zone_based, spread")
    charge_below_percentile: float = Field(25.0, ge=0, le=50)
    discharge_above_percentile: float = Field(75.0, ge=50, le=100)
    min_spread_pln_kwh: float = Field(0.10, ge=0)
    arbitrage_soc_min: float = Field(0.20, ge=0.0, le=0.5)
    max_grid_charge_kw: Optional[float] = None
    degradation_cost_pln_kwh: float = Field(0.05, ge=0)
    capacity_fee_pln_kwh: float = Field(0.0, ge=0)
    other_components_pln_kwh: float = Field(0.0, ge=0)


class DispatchRequestAPI(BaseModel):
    """API request for dispatch simulation"""
    pv_generation_kw: Optional[List[float]] = Field(
        None,
        description="PV generation [kW]. Can be omitted for LOAD_ONLY topology."
    )
    load_kw: List[float] = Field(..., description="Load consumption [kW]")
    interval_minutes: int = Field(60, description="Interval duration (15 or 60)")

    # Topology - determines system configuration
    topology: TopologyType = Field(
        TopologyType.PV_LOAD,
        description="System topology: pv_load (standard) or load_only (no PV)"
    )

    # Battery
    battery_power_kw: float = Field(..., gt=0)
    battery_energy_kwh: float = Field(..., gt=0)
    roundtrip_efficiency: float = Field(0.90, ge=0.7, le=1.0)
    soc_min: float = Field(0.10, ge=0.0, le=0.5)
    soc_max: float = Field(0.90, ge=0.5, le=1.0)
    soc_initial: float = Field(0.50, ge=0.0, le=1.0)

    # Mode
    mode: DispatchMode = Field(DispatchMode.PV_SURPLUS)

    # Peak shaving / STACKED / LOAD_ONLY params
    peak_limit_kw: Optional[float] = None
    reserve_fraction: float = Field(0.3, ge=0.0, le=0.8)

    # Arbitrage configuration (optional)
    arbitrage_config: Optional[ArbitrageConfigAPI] = Field(
        None,
        description="ToU arbitrage configuration. If enabled with STACKED mode, adds arbitrage dispatch."
    )
    start_date: Optional[str] = Field(
        None,
        description="Start date (YYYY-MM-DD) for tariff price lookup. Required if arbitrage enabled."
    )

    # Degradation budget (annual limits)
    max_efc_per_year: Optional[float] = None
    max_throughput_mwh_per_year: Optional[float] = None

    # Degradation budget (daily limits)
    max_cycles_per_day: Optional[float] = Field(
        None, ge=0, le=10,
        description="Max EFC cycles per day."
    )
    max_throughput_mwh_per_day: Optional[float] = Field(
        None, ge=0,
        description="Max throughput per day [MWh]."
    )

    # Prices
    import_price_pln_mwh: float = Field(800.0, ge=0)
    export_price_pln_mwh: float = Field(0.0, ge=0)
    demand_charge_pln_kw_month: float = Field(0.0, ge=0, description="Monthly demand charge [PLN/kW/month]")
    demand_charge_pln_kw_year: float = Field(0.0, ge=0, description="Annual demand charge [PLN/kW/year]")

    # Options
    return_hourly: bool = Field(True, description="Include hourly arrays")


@app.post("/dispatch", response_model=DispatchResult)
async def run_dispatch_simulation(request: DispatchRequestAPI):
    """
    Run BESS dispatch simulation.

    Modes:
    - pv_surplus: Maximize self-consumption from PV
    - peak_shaving: Reduce grid import peaks
    - stacked: Dual-service with SOC reserve for peak shaving
    - load_only: Stand-alone BESS without PV (peak shaving from grid)

    Topologies:
    - pv_load: Standard system with PV + Load + BESS
    - load_only: No PV, only Load + BESS (for peak shaving/arbitrage)

    Arbitrage (optional):
    - Enable with arbitrage_config + start_date
    - Works with STACKED mode for dual-service + ToU arbitrage
    - Priority: Peak Shaving > PV Charging > Arbitrage Grid Charge > Arbitrage Discharge

    Returns detailed energy flows, degradation metrics, and economics.
    """
    start_time = time.time()

    try:
        # Validate topology/mode compatibility
        if request.topology == TopologyType.LOAD_ONLY:
            if request.mode in [DispatchMode.PV_SURPLUS, DispatchMode.STACKED]:
                raise HTTPException(
                    400,
                    f"Mode {request.mode} requires PV. Use LOAD_ONLY or PEAK_SHAVING mode "
                    f"with LOAD_ONLY topology."
                )
            if request.mode == DispatchMode.LOAD_ONLY and not request.peak_limit_kw:
                raise HTTPException(400, "peak_limit_kw required for LOAD_ONLY mode")

        # Validate arbitrage requirements
        if request.arbitrage_config and request.arbitrage_config.enabled:
            if not request.start_date:
                raise HTTPException(
                    400,
                    "start_date is required when arbitrage_config.enabled=True"
                )
            if request.mode != DispatchMode.STACKED:
                raise HTTPException(
                    400,
                    "Arbitrage requires STACKED mode. Set mode='stacked' with peak_limit_kw."
                )

        # Build internal request
        battery = BatteryParams.from_roundtrip(
            power_kw=request.battery_power_kw,
            energy_kwh=request.battery_energy_kwh,
            roundtrip_eff=request.roundtrip_efficiency,
            soc_min=request.soc_min,
            soc_max=request.soc_max,
            soc_initial=request.soc_initial,
        )

        stacked_params = None
        if request.mode == DispatchMode.STACKED:
            if not request.peak_limit_kw:
                raise HTTPException(400, "peak_limit_kw required for STACKED mode")
            stacked_params = StackedModeParams(
                peak_limit_kw=request.peak_limit_kw,
                reserve_fraction=request.reserve_fraction,
            )

        budget = None
        if (request.max_efc_per_year or request.max_throughput_mwh_per_year or
            request.max_cycles_per_day or request.max_throughput_mwh_per_day):
            budget = DegradationBudget(
                max_efc_per_year=request.max_efc_per_year,
                max_throughput_mwh_per_year=request.max_throughput_mwh_per_year,
                max_cycles_per_day=request.max_cycles_per_day,
                max_throughput_mwh_per_day=request.max_throughput_mwh_per_day,
            )

        prices = PriceConfig(
            import_price_pln_mwh=request.import_price_pln_mwh,
            export_price_pln_mwh=request.export_price_pln_mwh,
            demand_charge_pln_kw_month=request.demand_charge_pln_kw_month,
            demand_charge_pln_kw_year=request.demand_charge_pln_kw_year,
        )

        # Build ArbitrageConfig if provided
        arb_config = None
        if request.arbitrage_config and request.arbitrage_config.enabled:
            strategy_map = {
                "percentile": ArbitrageStrategy.PERCENTILE_THRESHOLD,
                "zone_based": ArbitrageStrategy.ZONE_BASED,
                "spread": ArbitrageStrategy.SPREAD_THRESHOLD,
            }
            arb_config = ArbitrageConfig(
                enabled=True,
                tariff_id=request.arbitrage_config.tariff_id,
                strategy=strategy_map.get(
                    request.arbitrage_config.strategy,
                    ArbitrageStrategy.PERCENTILE_THRESHOLD
                ),
                charge_below_percentile=request.arbitrage_config.charge_below_percentile,
                discharge_above_percentile=request.arbitrage_config.discharge_above_percentile,
                min_spread_pln_kwh=request.arbitrage_config.min_spread_pln_kwh,
                arbitrage_soc_min=request.arbitrage_config.arbitrage_soc_min,
                max_grid_charge_kw=request.arbitrage_config.max_grid_charge_kw,
                degradation_cost_pln_kwh=request.arbitrage_config.degradation_cost_pln_kwh,
                capacity_fee_pln_kwh=request.arbitrage_config.capacity_fee_pln_kwh,
                other_components_pln_kwh=request.arbitrage_config.other_components_pln_kwh,
            )

        # Handle PV generation - empty list for LOAD_ONLY topology
        pv_generation = request.pv_generation_kw or []

        internal_request = DispatchRequest(
            pv_generation_kw=pv_generation,
            load_kw=request.load_kw,
            interval_minutes=request.interval_minutes,
            topology=request.topology,
            battery=battery,
            mode=request.mode,
            stacked_params=stacked_params,
            peak_limit_kw=request.peak_limit_kw,
            degradation_budget=budget,
            prices=prices,
            arbitrage_config=arb_config,
            start_date=request.start_date,
        )

        # Fetch import prices if arbitrage enabled
        import_prices_array = None
        if arb_config and arb_config.enabled and request.start_date:
            from datetime import datetime, timedelta
            from price_engine import ToUPriceProvider, ToUPriceConfig
            from osd_tariffs.presets.templates import ALL_PRESETS

            # Get tariff
            tariff = ALL_PRESETS.get(arb_config.tariff_id)
            if tariff is None:
                for t in ALL_PRESETS.values():
                    if t.id == arb_config.tariff_id:
                        tariff = t
                        break
            if tariff is None:
                raise HTTPException(404, f"Tariff not found: {arb_config.tariff_id}")

            # Parse dates
            start_date = datetime.strptime(request.start_date, "%Y-%m-%d").date()
            n_hours = len(request.load_kw)
            n_days = (n_hours + 23) // 24
            end_date = start_date + timedelta(days=n_days - 1)

            # Create price provider (capacity_fee = 0 for steering)
            price_config = ToUPriceConfig(
                osd_tariff=tariff,
                capacity_fee_pln_kwh=0.0,
                other_components_pln_kwh=arb_config.other_components_pln_kwh,
            )
            provider = ToUPriceProvider(price_config)
            price_bundle = provider.get_series(start_date, end_date, request.interval_minutes)

            # Extract import prices and trim/pad to match load length
            import_prices_array = np.array(price_bundle.import_total[:n_hours])
            if len(import_prices_array) < n_hours:
                pad_value = import_prices_array[-1] if len(import_prices_array) > 0 else 0.65
                import_prices_array = np.pad(
                    import_prices_array,
                    (0, n_hours - len(import_prices_array)),
                    'constant',
                    constant_values=pad_value
                )

        # Structured log: dispatch request
        n_hours = len(request.load_kw)
        dt_hours = request.interval_minutes / 60.0
        arbitrage_on = bool(request.arbitrage_config and request.arbitrage_config.enabled)

        log_dispatch_request(
            mode=request.mode.value,
            period_hours=n_hours * dt_hours,
            arbitrage_enabled=arbitrage_on,
            battery_power_kw=request.battery_power_kw,
            battery_energy_kwh=request.battery_energy_kwh,
        )

        # Run dispatch
        result = run_dispatch(internal_request, import_prices=import_prices_array)

        # Remove hourly arrays if not requested
        if not request.return_hourly:
            result.hourly_charge_kw = None
            result.hourly_discharge_kw = None
            result.hourly_soc_pct = None
            result.hourly_grid_import_kw = None
            result.hourly_grid_export_kw = None

        # Add timing info
        compute_time_ms = (time.time() - start_time) * 1000
        result.info["compute_time_ms"] = compute_time_ms

        # Structured log: dispatch response
        log_dispatch_response(
            annual_savings_pln=result.annual_savings_pln,
            self_consumption_pct=result.self_consumption_pct,
            efc_total=result.degradation.efc_total,
            compute_time_ms=compute_time_ms,
        )

        # Record Prometheus metrics (if available)
        record_dispatch_metrics(mode=request.mode.value)

        return result

    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Dispatch error: {str(e)}")


# =============================================================================
# Sizing Endpoint
# =============================================================================

class SizingRequestAPI(BaseModel):
    """API request for BESS sizing optimization"""
    pv_generation_kw: List[float] = Field(..., description="PV generation [kW]")
    load_kw: List[float] = Field(..., description="Load consumption [kW]")
    interval_minutes: int = Field(60)

    # Mode
    mode: DispatchMode = Field(DispatchMode.PV_SURPLUS)

    # Peak shaving / STACKED params
    peak_limit_kw: Optional[float] = None
    reserve_fraction: float = Field(0.3, ge=0.0, le=0.8)

    # Arbitrage configuration (optional) - for STACKED mode
    arbitrage_config: Optional[ArbitrageConfigAPI] = Field(
        None,
        description="ToU arbitrage configuration. Sizing will include arbitrage savings in NPV."
    )
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
    power_steps: int = Field(10, ge=5, le=50)

    # Duration variants
    durations_h: List[float] = Field([1.0, 2.0, 4.0])

    # Battery parameters
    roundtrip_efficiency: float = Field(0.90, ge=0.7, le=1.0)
    soc_min: float = Field(0.10, ge=0.0, le=0.5)
    soc_max: float = Field(0.90, ge=0.5, le=1.0)

    # EOL (End-of-Life) Degradation Sizing
    # If eol_capacity_factor > 0, battery will be oversized so EOL capacity meets this target
    # Example: 0.70 = size so that at end of life (after analysis_years) battery has 70% of BOL capacity
    eol_capacity_factor: float = Field(0.0, ge=0.0, le=1.0, description="Target EOL capacity factor (0=no adjustment)")
    annual_degradation_pct: float = Field(2.0, ge=0.0, le=10.0, description="Annual degradation [%/year]")

    # Economics
    capex_per_kwh: float = Field(1500.0, ge=0)
    capex_per_kw: float = Field(300.0, ge=0)
    opex_pct_per_year: float = Field(0.015, ge=0, le=0.1)
    discount_rate: float = Field(0.07, ge=0, le=0.3)
    analysis_years: int = Field(15, ge=1, le=30)

    # Prices (legacy flat pricing)
    import_price_pln_mwh: float = Field(800.0, ge=0)
    export_price_pln_mwh: float = Field(0.0, ge=0)
    demand_charge_pln_kw_month: float = Field(0.0, ge=0, description="Monthly demand charge [PLN/kW/month]")
    demand_charge_pln_kw_year: float = Field(0.0, ge=0, description="Annual demand charge [PLN/kW/year]")

    # ToU Pricing (Opcja B - OSD_ALL_IN)
    # Optional dict that enables ToU pricing when present
    prices: Optional[dict] = Field(
        None,
        description="ToU pricing config: {tariff_id, other_fees_pln_mwh, capacity_fee_method, analysis_year}"
    )

    # Degradation cost (general parameter - not just for arbitrage)
    degradation_cost_pln_mwh: float = Field(
        50.0,
        ge=0,
        description="Degradation cost per MWh throughput [PLN/MWh]. Used to calculate degradation_cost_pln in savings_breakdown."
    )

    # Degradation budget (annual limits - checked post-dispatch)
    max_efc_per_year: Optional[float] = None
    max_throughput_mwh_per_year: Optional[float] = None

    # Degradation budget (daily limits - triggers warnings when exceeded)
    max_cycles_per_day: Optional[float] = Field(
        None, ge=0, le=10,
        description="Max EFC cycles per day. Triggers warning when exceeded."
    )
    max_throughput_mwh_per_day: Optional[float] = Field(
        None, ge=0,
        description="Max throughput per day [MWh]. Triggers warning when exceeded."
    )

    # OR full degradation_budget object (takes precedence if provided)
    degradation_budget: Optional[Dict[str, Any]] = Field(
        None,
        description="Full DegradationBudget config: {max_efc_per_year, max_throughput_mwh_per_year, max_cycles_per_day, max_throughput_mwh_per_day}. Takes precedence over individual fields."
    )

    # Optimization configuration (objective + constraints)
    optimization: Optional[Dict[str, Any]] = Field(
        None,
        description="Optimization config: {objective, constraints, constraint_penalty_weight}"
    )

    # Energy flows timeseries (optional - off by default to reduce response size)
    include_energy_flows_timeseries: bool = Field(
        False,
        description="If True, include per-timestep energy flows in response. Default: False to keep response small."
    )


@app.post("/sizing", response_model=SizingResult)
async def run_sizing_optimization(request: SizingRequestAPI):
    """
    Run BESS sizing optimization.

    Tests multiple duration variants (default: 1h, 2h, 4h) and finds
    optimal power for each using NPV-based grid search.

    Arbitrage (optional):
    - Enable with arbitrage_config + start_date
    - Sizing includes arbitrage savings in NPV calculation
    - Capacity fee savings calculated post-dispatch

    Returns:
    - S/M/L variant results with economics (including arbitrage savings breakdown)
    - Degradation metrics per variant
    - Recommended variant based on score
    """
    start_time = time.time()

    try:
        # Validate arbitrage requirements
        if request.arbitrage_config and request.arbitrage_config.enabled:
            if not request.start_date:
                raise HTTPException(
                    400,
                    "start_date is required when arbitrage_config.enabled=True"
                )
            if request.mode != DispatchMode.STACKED:
                raise HTTPException(
                    400,
                    "Arbitrage sizing requires STACKED mode. Set mode='stacked' with peak_limit_kw."
                )

        stacked_params = None
        if request.mode == DispatchMode.STACKED:
            if not request.peak_limit_kw:
                raise HTTPException(400, "peak_limit_kw required for STACKED mode")
            stacked_params = StackedModeParams(
                peak_limit_kw=request.peak_limit_kw,
                reserve_fraction=request.reserve_fraction,
            )

        # Build DegradationBudget from request
        budget = None
        if request.degradation_budget:
            # Full budget object takes precedence
            budget = DegradationBudget(**request.degradation_budget)
        elif (request.max_efc_per_year or request.max_throughput_mwh_per_year or
              request.max_cycles_per_day or request.max_throughput_mwh_per_day):
            # Individual fields
            budget = DegradationBudget(
                max_efc_per_year=request.max_efc_per_year,
                max_throughput_mwh_per_year=request.max_throughput_mwh_per_year,
                max_cycles_per_day=request.max_cycles_per_day,
                max_throughput_mwh_per_day=request.max_throughput_mwh_per_day,
            )

        # Build PriceConfig from request
        # Check for ToU pricing: tariff_id OR type='two_zone'/'three_zone'
        prices_dict = request.prices or {}
        is_tou = (
            prices_dict.get('tariff_id') or
            prices_dict.get('type') in ('two_zone', 'three_zone')
        )

        if is_tou:
            # Calculate weighted average import price for ToU if no tariff_id preset
            if not prices_dict.get('tariff_id'):
                # Build tariff_id from type for presets lookup, or use custom rates
                tou_type = prices_dict.get('type', 'two_zone')
                if tou_type == 'two_zone':
                    day_rate = prices_dict.get('day_rate_pln_mwh', 800.0)
                    night_rate = prices_dict.get('night_rate_pln_mwh', 400.0)
                    # Weighted average: 60% day, 40% night
                    avg_rate = day_rate * 0.6 + night_rate * 0.4
                elif tou_type == 'three_zone':
                    peak_rate = prices_dict.get('peak_rate_pln_mwh', 1200.0)
                    day_rate = prices_dict.get('day_rate_pln_mwh', 800.0)
                    night_rate = prices_dict.get('night_rate_pln_mwh', 400.0)
                    # Weighted average: 20% peak, 40% day, 40% night
                    avg_rate = peak_rate * 0.2 + day_rate * 0.4 + night_rate * 0.4
                else:
                    avg_rate = request.import_price_pln_mwh

                # Use custom ToU rates - calculate full price = energia czynna + opłaty stałe
                other_fees = prices_dict.get('other_fees_pln_mwh', 451.0)
                full_import_price = avg_rate + other_fees

                prices = PriceConfig(
                    import_price_pln_mwh=full_import_price,
                    export_price_pln_mwh=request.export_price_pln_mwh,
                    demand_charge_pln_kw_month=request.demand_charge_pln_kw_month,
                    demand_charge_pln_kw_year=request.demand_charge_pln_kw_year,
                    other_fees_pln_mwh=other_fees,
                    capacity_fee_method=prices_dict.get('capacity_fee_method', 'dynamic'),
                    capacity_fee_som_pln_kwh=prices_dict.get('capacity_fee_som_pln_kwh', 0.2194),
                    analysis_year=prices_dict.get('analysis_year', 2025),
                )
            else:
                # Use tariff preset
                prices = PriceConfig(
                    import_price_pln_mwh=request.import_price_pln_mwh,
                    export_price_pln_mwh=request.export_price_pln_mwh,
                    demand_charge_pln_kw_month=request.demand_charge_pln_kw_month,
                    demand_charge_pln_kw_year=request.demand_charge_pln_kw_year,
                    tariff_id=prices_dict.get('tariff_id'),
                    other_fees_pln_mwh=prices_dict.get('other_fees_pln_mwh', 451.0),
                    capacity_fee_method=prices_dict.get('capacity_fee_method', 'dynamic'),
                    capacity_fee_som_pln_kwh=prices_dict.get('capacity_fee_som_pln_kwh', 0.2194),
                    capacity_fee_fixed_pln_mwh=prices_dict.get('capacity_fee_fixed_pln_mwh'),
                    analysis_year=prices_dict.get('analysis_year', 2025),
                )
        else:
            # Legacy flat pricing - still include other_fees if provided
            other_fees = prices_dict.get('other_fees_pln_mwh', 451.0)
            prices = PriceConfig(
                import_price_pln_mwh=request.import_price_pln_mwh + other_fees,
                export_price_pln_mwh=request.export_price_pln_mwh,
                demand_charge_pln_kw_month=request.demand_charge_pln_kw_month,
                demand_charge_pln_kw_year=request.demand_charge_pln_kw_year,
                other_fees_pln_mwh=other_fees,
            )

        # Build ArbitrageConfig for sizing
        arb_config = None
        if request.arbitrage_config and request.arbitrage_config.enabled:
            strategy_map = {
                "percentile": ArbitrageStrategy.PERCENTILE_THRESHOLD,
                "zone_based": ArbitrageStrategy.ZONE_BASED,
                "spread": ArbitrageStrategy.SPREAD_THRESHOLD,
            }
            arb_config = ArbitrageConfig(
                enabled=True,
                tariff_id=request.arbitrage_config.tariff_id,
                strategy=strategy_map.get(
                    request.arbitrage_config.strategy,
                    ArbitrageStrategy.PERCENTILE_THRESHOLD
                ),
                charge_below_percentile=request.arbitrage_config.charge_below_percentile,
                discharge_above_percentile=request.arbitrage_config.discharge_above_percentile,
                min_spread_pln_kwh=request.arbitrage_config.min_spread_pln_kwh,
                arbitrage_soc_min=request.arbitrage_config.arbitrage_soc_min,
                max_grid_charge_kw=request.arbitrage_config.max_grid_charge_kw,
                degradation_cost_pln_kwh=request.arbitrage_config.degradation_cost_pln_kwh,
                capacity_fee_pln_kwh=0.0,  # Always 0 for sizing - post-dispatch calculation
                other_components_pln_kwh=request.arbitrage_config.other_components_pln_kwh,
            )

        # Parse optimization config from frontend
        optimization_config = None
        if request.optimization:
            opt_dict = request.optimization
            constraints_list = []
            if opt_dict.get("constraints"):
                for c in opt_dict["constraints"]:
                    constraints_list.append(SizingConstraint(
                        constraint_type=ConstraintType(c.get("constraint_type", "max_capex")),
                        value=c.get("value", 0),
                        hard=c.get("hard", True),
                    ))
            optimization_config = OptimizationConfig(
                objective=OptimizationObjective(opt_dict.get("objective", "npv")),
                constraints=constraints_list,
                constraint_penalty_weight=opt_dict.get("constraint_penalty_weight", 0.3),
            )

        internal_request = SizingRequest(
            pv_generation_kw=request.pv_generation_kw,
            load_kw=request.load_kw,
            interval_minutes=request.interval_minutes,
            mode=request.mode,
            stacked_params=stacked_params,
            peak_limit_kw=request.peak_limit_kw,
            arbitrage_config=arb_config,
            start_date=request.start_date,
            # Period configuration (v0.3.3)
            timezone=request.timezone,
            period_start=request.period_start,
            period_end=request.period_end,
            # Battery sizing
            min_power_kw=request.min_power_kw,
            max_power_kw=request.max_power_kw,
            power_steps=request.power_steps,
            durations_h=request.durations_h,
            roundtrip_efficiency=request.roundtrip_efficiency,
            soc_min=request.soc_min,
            soc_max=request.soc_max,
            # EOL degradation sizing
            eol_capacity_factor=request.eol_capacity_factor,
            annual_degradation_pct=request.annual_degradation_pct,
            # Economics
            capex_per_kwh=request.capex_per_kwh,
            capex_per_kw=request.capex_per_kw,
            opex_pct_per_year=request.opex_pct_per_year,
            discount_rate=request.discount_rate,
            analysis_years=request.analysis_years,
            prices=prices,
            # Degradation
            degradation_cost_pln_mwh=request.degradation_cost_pln_mwh,
            degradation_budget=budget,
            optimization=optimization_config,
            include_energy_flows_timeseries=request.include_energy_flows_timeseries,
        )

        result = run_sizing(internal_request)

        return result

    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Sizing error: {str(e)}")


# =============================================================================
# Quick Sizing Endpoint
# =============================================================================

class QuickSizingRequest(BaseModel):
    """Simplified request for quick PV-surplus sizing"""
    pv_generation_kw: List[float]
    load_kw: List[float]
    interval_minutes: int = 60
    duration_h: float = 2.0
    roundtrip_efficiency: float = 0.90
    capex_per_kwh: float = 1500.0
    capex_per_kw: float = 300.0
    import_price_pln_mwh: float = 800.0


class QuickSizingResult(BaseModel):
    """Quick sizing result"""
    power_kw: float
    energy_kwh: float
    duration_h: float
    annual_savings_pln: float
    capex_pln: float


@app.post("/sizing/quick", response_model=QuickSizingResult)
async def quick_sizing(request: QuickSizingRequest):
    """
    Quick BESS sizing for PV-surplus mode.

    Simplified endpoint for fast sizing estimation.
    """
    try:
        pv = np.array(request.pv_generation_kw)
        load = np.array(request.load_kw)
        dt_hours = request.interval_minutes / 60.0

        power, energy, savings = run_quick_sizing(
            pv, load, dt_hours,
            duration_h=request.duration_h,
            roundtrip_eff=request.roundtrip_efficiency,
            capex_per_kwh=request.capex_per_kwh,
            capex_per_kw=request.capex_per_kw,
            import_price_pln_mwh=request.import_price_pln_mwh,
        )

        capex = energy * request.capex_per_kwh + power * request.capex_per_kw

        return QuickSizingResult(
            power_kw=power,
            energy_kwh=energy,
            duration_h=request.duration_h,
            annual_savings_pln=savings,
            capex_pln=capex,
        )

    except Exception as e:
        raise HTTPException(500, f"Quick sizing error: {str(e)}")


# =============================================================================
# Sensitivity Analysis Endpoint
# =============================================================================

class SensitivityRequestAPI(BaseModel):
    """API request for tornado sensitivity analysis"""
    pv_generation_kw: List[float] = Field(..., description="PV generation [kW]")
    load_kw: List[float] = Field(..., description="Load consumption [kW]")
    interval_minutes: int = Field(60)

    # Fixed BESS configuration
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

    # Sensitivity parameters (optional, defaults to standard set)
    parameters: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="Custom sensitivity parameters. If None, uses defaults."
    )


@app.post("/sensitivity", response_model=SensitivityResult)
async def run_sensitivity(request: SensitivityRequestAPI):
    """
    Run tornado-style sensitivity analysis for a fixed BESS configuration.

    Varies each parameter independently (default ±20%) and measures
    impact on NPV. Results are sorted by sensitivity for tornado chart.

    Default parameters analyzed:
    - energy_price: Cena energii [PLN/MWh]
    - capex_per_kwh: CAPEX/kWh [PLN/kWh]
    - discount_rate: Stopa dyskontowa [%]
    - efficiency: Sprawność [%]

    Returns sensitivity results sorted by NPV swing (most sensitive first).
    """
    start_time = time.time()

    try:
        # Build internal request
        sens_params = []
        if request.parameters:
            for p in request.parameters:
                sens_params.append(SensitivityRange(
                    parameter=SensitivityParameter(p.get("parameter", "energy_price")),
                    low_pct=p.get("low_pct", -20.0),
                    high_pct=p.get("high_pct", 20.0),
                ))
        else:
            # Default parameters
            sens_params = [
                SensitivityRange(parameter=SensitivityParameter.ENERGY_PRICE),
                SensitivityRange(parameter=SensitivityParameter.CAPEX_PER_KWH),
                SensitivityRange(parameter=SensitivityParameter.DISCOUNT_RATE),
                SensitivityRange(parameter=SensitivityParameter.ROUNDTRIP_EFFICIENCY),
            ]

        internal_request = SensitivityRequest(
            pv_generation_kw=request.pv_generation_kw,
            load_kw=request.load_kw,
            interval_minutes=request.interval_minutes,
            battery_power_kw=request.battery_power_kw,
            battery_energy_kwh=request.battery_energy_kwh,
            roundtrip_efficiency=request.roundtrip_efficiency,
            soc_min=request.soc_min,
            soc_max=request.soc_max,
            mode=request.mode,
            peak_limit_kw=request.peak_limit_kw,
            reserve_fraction=request.reserve_fraction,
            capex_per_kwh=request.capex_per_kwh,
            capex_per_kw=request.capex_per_kw,
            opex_pct_per_year=request.opex_pct_per_year,
            discount_rate=request.discount_rate,
            analysis_years=request.analysis_years,
            import_price_pln_mwh=request.import_price_pln_mwh,
            parameters=sens_params,
        )

        result = run_sensitivity_analysis(internal_request)

        return result

    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Sensitivity analysis error: {str(e)}")


# =============================================================================
# Capacity Fee PL (Opłata Mocowa) Endpoints
# =============================================================================

from capacity_fee_pl import (
    compute_capacity_fee,
    compute_capacity_fee_savings,
    CapacityFeeConfig,
    CapacityFeeResult,
    CapacityFeeSavings,
    get_preset_for_year,
    QualificationPeriod,
)


class CapacityFeeRequestAPI(BaseModel):
    """API request for capacity fee calculation"""
    grid_import_kwh: List[float] = Field(
        ...,
        description="Hourly grid import [kWh]. Length must match time_index."
    )
    time_index: List[str] = Field(
        ...,
        description="ISO timestamps for each interval (YYYY-MM-DDTHH:MM:SS)"
    )
    year: int = Field(2026, ge=2020, le=2035, description="Year for SOM rate and rules")
    som_pln_per_kwh: Optional[float] = Field(
        None,
        description="Override SOM rate [PLN/kWh]. If None, uses preset for year."
    )
    selected_windows_by_quarter: Optional[Dict[str, List[int]]] = Field(
        None,
        description="Override selected hours per quarter. Format: {'Q1': [7, 22], ...}"
    )


class CapacityFeeSavingsRequestAPI(BaseModel):
    """API request for capacity fee savings comparison"""
    grid_import_before_kwh: List[float] = Field(
        ...,
        description="Grid import BEFORE BESS [kWh]"
    )
    grid_import_after_kwh: List[float] = Field(
        ...,
        description="Grid import AFTER BESS [kWh]"
    )
    time_index: List[str] = Field(
        ...,
        description="ISO timestamps for each interval"
    )
    year: int = Field(2026, ge=2020, le=2035)
    som_pln_per_kwh: Optional[float] = None


@app.post("/capacity-fee", response_model=CapacityFeeResult)
async def calculate_capacity_fee(request: CapacityFeeRequestAPI):
    """
    Calculate Polish Capacity Market Fee (Opłata Mocowa).

    Based on Ustawa o rynku mocy and URE regulations.

    Formula: WOM = A × SOM × ZS
    - A = K-class coefficient (0.17/0.50/0.83/1.00)
    - SOM = capacity fee rate [PLN/kWh]
    - ZS = energy consumed in selected hours [kWh]

    Selected hours: 7:00-22:00 on workdays (2026 default).
    Fee applies only to workdays (Mon-Fri, excluding Polish holidays).

    K-class classification based on Δs:
    - K1: Δs < 5%     → A = 0.17 (83% discount)
    - K2: Δs ∈ [5%, 10%)  → A = 0.50 (50% discount)
    - K3: Δs ∈ [10%, 15%) → A = 0.83 (17% discount)
    - K4: Δs ≥ 15%    → A = 1.00 (no discount)
    """
    import pandas as pd

    try:
        # Parse timestamps
        time_index = pd.to_datetime(request.time_index)
        grid_import = np.array(request.grid_import_kwh)

        if len(grid_import) != len(time_index):
            raise HTTPException(
                400,
                f"Length mismatch: grid_import_kwh ({len(grid_import)}) vs time_index ({len(time_index)})"
            )

        # Build config
        config = get_preset_for_year(request.year)
        if request.som_pln_per_kwh is not None:
            config.som_pln_per_kwh = request.som_pln_per_kwh
        if request.selected_windows_by_quarter:
            config.selected_windows_by_quarter = {
                k: tuple(v) for k, v in request.selected_windows_by_quarter.items()
            }

        # Calculate
        result = compute_capacity_fee(grid_import, time_index, config)

        return result

    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Capacity fee calculation error: {str(e)}")


@app.post("/capacity-fee/savings", response_model=CapacityFeeSavings)
async def calculate_capacity_fee_savings(request: CapacityFeeSavingsRequestAPI):
    """
    Compare capacity fee before and after BESS.

    Returns savings and K-class shift analysis.
    """
    import pandas as pd

    try:
        time_index = pd.to_datetime(request.time_index)
        before = np.array(request.grid_import_before_kwh)
        after = np.array(request.grid_import_after_kwh)

        if len(before) != len(time_index) or len(after) != len(time_index):
            raise HTTPException(400, "Length mismatch between arrays and time_index")

        config = get_preset_for_year(request.year)
        if request.som_pln_per_kwh is not None:
            config.som_pln_per_kwh = request.som_pln_per_kwh

        result = compute_capacity_fee_savings(before, after, time_index, config)

        return result

    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Capacity fee savings error: {str(e)}")


@app.get("/capacity-fee/presets/{year}")
async def get_capacity_fee_preset(year: int):
    """
    Get capacity fee configuration preset for a given year.

    Returns SOM rate, qualification period, and selected hours windows.
    """
    try:
        config = get_preset_for_year(year)
        return {
            "year": config.year,
            "som_pln_per_kwh": config.som_pln_per_kwh,
            "qualification_period": config.qualification_period.value,
            "selected_windows_by_quarter": config.selected_windows_by_quarter,
            "notes": {
                "som_source": "URE 58/2025" if year == 2026 else "Estimate",
                "daily_qualification": year >= 2025,
            }
        }
    except Exception as e:
        raise HTTPException(500, f"Error getting preset: {str(e)}")


# =============================================================================
# OSD Tariffs Endpoints
# =============================================================================

from datetime import date as date_type
from osd_tariffs import (
    OsdTariff,
    OsdTariffRequest,
    OsdTariffResponse,
    ZoneId,
    ChargeBasis,
    TimeDependency,
    Segment,
    ScheduleBlock,
    TariffComponent,
    CompiledTariffHour,
    validate_tariff,
    TariffValidationError,
    TariffCompiler,
    compile_tariff_for_date,
)
from osd_tariffs.models import TariffPreview
from osd_tariffs.presets import list_presets, get_preset_by_id


class OsdTariffValidateRequest(BaseModel):
    """Request to validate an OSD tariff definition"""
    tariff: Dict[str, Any] = Field(..., description="Tariff definition")
    check_date: Optional[str] = Field(None, description="Date to check validity (YYYY-MM-DD)")
    strict: bool = Field(True, description="Strict validation mode")


class OsdTariffValidateResponse(BaseModel):
    """Validation result"""
    valid: bool
    tariff_id: str
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class OsdTariffCompileRequest(BaseModel):
    """Request to compile a tariff for specific dates"""
    tariff: Dict[str, Any] = Field(..., description="Tariff definition")
    target_date: str = Field(..., description="Target date (YYYY-MM-DD)")


class OsdTariffCompileResponse(BaseModel):
    """Compiled tariff for a day"""
    date: str
    day_type: str
    hours: List[Dict[str, Any]]  # List of {hour, zone_id, rate, day_type}


@app.post("/osd-tariffs/validate", response_model=OsdTariffValidateResponse)
async def validate_osd_tariff(request: OsdTariffValidateRequest):
    """
    Validate an OSD tariff definition.

    Checks:
    - Segment minute values (0-1439/1-1440)
    - 1440-minute coverage per day type
    - Overlap detection
    - Component completeness
    - Schedule date ranges

    Returns validation result with errors and warnings.
    """
    try:
        # Parse tariff from dict
        tariff = OsdTariff(**request.tariff)

        # Parse check date if provided
        check_date = None
        if request.check_date:
            check_date = date_type.fromisoformat(request.check_date)

        # Validate
        is_valid, errors, warnings = validate_tariff(
            tariff,
            strict=request.strict,
            check_date=check_date,
        )

        return OsdTariffValidateResponse(
            valid=is_valid,
            tariff_id=tariff.id,
            errors=errors,
            warnings=warnings,
        )

    except Exception as e:
        return OsdTariffValidateResponse(
            valid=False,
            tariff_id=request.tariff.get("id", "unknown"),
            errors=[str(e)],
            warnings=[],
        )


@app.post("/osd-tariffs/compile", response_model=OsdTariffCompileResponse)
async def compile_osd_tariff(request: OsdTariffCompileRequest):
    """
    Compile a tariff for a specific date.

    Returns 24 hourly zone assignments and rates.
    Uses CET_FIXED clock mode (Polish winter time) by default.
    """
    try:
        tariff = OsdTariff(**request.tariff)
        target_date = date_type.fromisoformat(request.target_date)

        compiler = TariffCompiler(tariff)
        compiled = compiler.compile_day(target_date)

        if compiled is None:
            raise HTTPException(404, f"No active schedule for date {target_date}")

        hours_data = []
        for hour in range(24):
            hours_data.append({
                "hour": hour,
                "zone_id": compiled.hourly_zones[hour].value,
                "rate": compiled.hourly_rates[hour],
                "day_type": compiled.day_type.value,
            })

        return OsdTariffCompileResponse(
            date=target_date.isoformat(),
            day_type=compiled.day_type.value,
            hours=hours_data,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Compile error: {str(e)}")


@app.get("/osd-tariffs/presets", response_model=List[Dict[str, Any]])
async def get_osd_tariff_presets():
    """
    List available OSD tariff presets.

    Returns preset metadata including OSD, group, zones, and validity.
    """
    presets = list_presets()
    return [
        {
            "id": p.id,
            "name": p.name,
            "osd": p.osd,
            "group": p.group,
            "zones_count": p.zones_count,
            "zones": p.zones,
            "has_seasonality": p.has_seasonality,
            "valid_from": p.valid_from.isoformat(),
            "valid_to": p.valid_to.isoformat() if p.valid_to else None,
        }
        for p in presets
    ]


@app.get("/osd-tariffs/presets/{preset_id}")
async def get_osd_tariff_preset(preset_id: str):
    """
    Get a specific OSD tariff preset by ID.

    Returns full tariff definition with schedule blocks and components.
    """
    tariff = get_preset_by_id(preset_id)
    if tariff is None:
        raise HTTPException(404, f"Preset not found: {preset_id}")

    # Convert to dict for JSON response
    return tariff.model_dump(mode="json")


@app.post("/osd-tariffs/compile-range")
async def compile_osd_tariff_range(
    request: Dict[str, Any]
):
    """
    Compile a tariff for a date range.

    Request body:
    - tariff: Tariff definition
    - start_date: Start date (YYYY-MM-DD)
    - end_date: End date (YYYY-MM-DD)

    Returns compiled data for each day in range.
    """
    try:
        tariff = OsdTariff(**request["tariff"])
        start_date = date_type.fromisoformat(request["start_date"])
        end_date = date_type.fromisoformat(request["end_date"])

        if (end_date - start_date).days > 366:
            raise HTTPException(400, "Date range cannot exceed 366 days")

        compiler = TariffCompiler(tariff)
        compiled_range = compiler.compile_range(start_date, end_date)

        result = []
        for d, compiled in compiled_range.items():
            result.append({
                "date": d.isoformat(),
                "day_type": compiled.day_type.value,
                "hourly_rates": compiled.hourly_rates,
                "hourly_zones": [z.value for z in compiled.hourly_zones],
            })

        return {
            "tariff_id": tariff.id,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "days_count": len(result),
            "days": result,
        }

    except HTTPException:
        raise
    except KeyError as e:
        raise HTTPException(400, f"Missing field: {e}")
    except Exception as e:
        raise HTTPException(500, f"Compile range error: {str(e)}")


# =============================================================================
# Excel Export Endpoint
# =============================================================================

from fastapi.responses import StreamingResponse
from datetime import date as date_type
from excel_export import (
    generate_economics_excel,
    ToUConfig,
    FixedChargesConfig,
)


class ExcelExportRequest(BaseModel):
    """Request for Excel export of BESS economics analysis."""
    # Energy data (kW profiles)
    baseline_import_kw: List[float] = Field(
        ..., description="Grid import without BESS [kW]"
    )
    project_import_kw: List[float] = Field(
        ..., description="Grid import with BESS [kW]"
    )

    # BESS configuration
    bess_power_kw: float = Field(..., gt=0, description="BESS power rating [kW]")
    bess_energy_kwh: float = Field(..., gt=0, description="BESS energy capacity [kWh]")

    # Time configuration
    start_date: str = Field("2025-01-01", description="Start date (YYYY-MM-DD)")
    interval_minutes: int = Field(60, description="Interval duration (15 or 60)")

    # ToU tariff configuration
    tariff_type: str = Field("two_zone", description="Tariff type: flat, two_zone, three_zone")
    flat_rate: float = Field(750.0, ge=0, description="Flat rate [PLN/MWh]")
    day_rate: float = Field(850.0, ge=0, description="Day rate [PLN/MWh] (two_zone)")
    night_rate: float = Field(450.0, ge=0, description="Night rate [PLN/MWh] (two_zone)")
    peak_rate: float = Field(950.0, ge=0, description="Peak rate [PLN/MWh] (three_zone)")
    partial_rate: float = Field(700.0, ge=0, description="Partial rate [PLN/MWh] (three_zone)")
    off_peak_rate: float = Field(400.0, ge=0, description="Off-peak rate [PLN/MWh] (three_zone)")

    # ToU time windows
    weekday_day_start: int = Field(6, ge=0, le=23)
    weekday_day_end: int = Field(22, ge=0, le=24)
    weekend_day_start: int = Field(6, ge=0, le=23)
    weekend_day_end: int = Field(13, ge=0, le=24)
    peak1_start: int = Field(7, ge=0, le=23)
    peak1_end: int = Field(13, ge=0, le=24)
    peak2_start: int = Field(17, ge=0, le=23)
    peak2_end: int = Field(21, ge=0, le=24)

    # Fixed charges [PLN/MWh]
    distribution: float = Field(200.0, ge=0, description="Dystrybucja [PLN/MWh]")
    quality_fee: float = Field(10.0, ge=0, description="Opłata jakościowa [PLN/MWh]")
    oze_fee: float = Field(7.0, ge=0, description="Opłata OZE [PLN/MWh]")
    cogeneration_fee: float = Field(10.0, ge=0, description="Opłata kogeneracyjna [PLN/MWh]")
    excise_tax: float = Field(5.0, ge=0, description="Akcyza [PLN/MWh]")
    capacity_fee_som: float = Field(0.2194, ge=0, description="SOM rate [PLN/kWh]")

    # OSD_ALL_IN mode: if True, ToU rates already include distribution (no double counting)
    is_osd_all_in: bool = Field(False, description="If True, ToU rates include distribution")

    # Report configuration
    project_name: str = Field("Analiza BESS", description="Report title")


@app.post("/sizing-export-excel")
async def export_sizing_to_excel(request: ExcelExportRequest):
    """
    Export detailed BESS economics analysis to Excel.

    Generates comprehensive Excel file with:
    - Summary sheet with annual totals
    - Hourly breakdown with:
      - For each hour: energia czynna (per ToU zone), dystrybucja, jakość, OZE, kog, akcyza, mocowa
      - Baseline (PV only) vs Project (PV+BESS) comparison
      - Savings per hour
    - Daily summary
    - Monthly summary

    Capacity fee (opłata mocowa) is applied only during:
    - Workdays (Mon-Fri, excluding Polish holidays)
    - Hours 7:00-21:59 (7-22)

    Returns Excel file as download.
    """
    try:
        # Parse start date
        start_date = date_type.fromisoformat(request.start_date)

        # Convert to numpy arrays
        baseline = np.array(request.baseline_import_kw)
        project = np.array(request.project_import_kw)

        if len(baseline) != len(project):
            raise HTTPException(
                400,
                f"Length mismatch: baseline ({len(baseline)}) vs project ({len(project)})"
            )

        # Build ToU config
        tou_config = ToUConfig(
            tariff_type=request.tariff_type,
            flat_rate=request.flat_rate,
            day_rate=request.day_rate,
            night_rate=request.night_rate,
            peak_rate=request.peak_rate,
            partial_rate=request.partial_rate,
            off_peak_rate=request.off_peak_rate,
            weekday_day_start=request.weekday_day_start,
            weekday_day_end=request.weekday_day_end,
            weekend_day_start=request.weekend_day_start,
            weekend_day_end=request.weekend_day_end,
            peak1_start=request.peak1_start,
            peak1_end=request.peak1_end,
            peak2_start=request.peak2_start,
            peak2_end=request.peak2_end,
        )

        # Build fixed charges config
        fixed_config = FixedChargesConfig(
            distribution=request.distribution,
            quality_fee=request.quality_fee,
            oze_fee=request.oze_fee,
            cogeneration_fee=request.cogeneration_fee,
            excise_tax=request.excise_tax,
            capacity_fee_som=request.capacity_fee_som,
            is_osd_all_in=request.is_osd_all_in,
        )

        # Generate Excel
        excel_bytes = generate_economics_excel(
            baseline_import_kw=baseline,
            project_import_kw=project,
            tou_config=tou_config,
            fixed_config=fixed_config,
            start_date=start_date,
            bess_power_kw=request.bess_power_kw,
            bess_energy_kwh=request.bess_energy_kwh,
            interval_minutes=request.interval_minutes,
            project_name=request.project_name,
        )

        # Create filename
        filename = f"BESS_Economics_{start_date.year}_{request.bess_power_kw}kW_{request.bess_energy_kwh}kWh.xlsx"

        return StreamingResponse(
            io.BytesIO(excel_bytes),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Excel export error: {str(e)}")


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8031)

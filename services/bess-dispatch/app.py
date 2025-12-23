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

import time
from typing import List, Optional, Dict, Any, Union
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

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
)
from dispatch_engine import run_dispatch
from sizing_runner import run_sizing, run_quick_sizing
from sensitivity_runner import run_sensitivity_analysis


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


@app.get("/info", response_model=ServiceInfo)
async def service_info():
    """Service information and capabilities"""
    return ServiceInfo(
        name="BESS Dispatch Service",
        version="1.1.0",
        description="Time-based dispatch simulation with degradation tracking",
        dispatch_modes=[m.value for m in DispatchMode],
        supported_intervals=[15, 60],
        sizing_variants=["small (1h)", "medium (2h)", "large (4h)"],
        features=[
            "PV-surplus (autokonsumpcja) dispatch",
            "Peak shaving dispatch",
            "STACKED mode (PV + Peak with SOC reserve)",
            "LOAD_ONLY mode (stand-alone BESS without PV)",
            "Topology support (pv_load, load_only)",
            "Throughput and EFC tracking",
            "Per-service degradation breakdown",
            "Degradation budget monitoring",
            "S/M/L sizing variants",
            "NPV-based optimization",
            "Sensitivity analysis (tornado chart)",
            "Future-ready for time-varying prices",
        ]
    )


# =============================================================================
# Dispatch Endpoint
# =============================================================================

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

    # Degradation budget
    max_efc_per_year: Optional[float] = None
    max_throughput_mwh_per_year: Optional[float] = None

    # Prices
    import_price_pln_mwh: float = Field(800.0, ge=0)
    export_price_pln_mwh: float = Field(0.0, ge=0)

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
        if request.max_efc_per_year or request.max_throughput_mwh_per_year:
            budget = DegradationBudget(
                max_efc_per_year=request.max_efc_per_year,
                max_throughput_mwh_per_year=request.max_throughput_mwh_per_year,
            )

        prices = PriceConfig(
            import_price_pln_mwh=request.import_price_pln_mwh,
            export_price_pln_mwh=request.export_price_pln_mwh,
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
        )

        # Run dispatch
        result = run_dispatch(internal_request)

        # Remove hourly arrays if not requested
        if not request.return_hourly:
            result.hourly_charge_kw = None
            result.hourly_discharge_kw = None
            result.hourly_soc_pct = None
            result.hourly_grid_import_kw = None
            result.hourly_grid_export_kw = None

        # Add timing info
        result.info["compute_time_ms"] = (time.time() - start_time) * 1000

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

    # Economics
    capex_per_kwh: float = Field(1500.0, ge=0)
    capex_per_kw: float = Field(300.0, ge=0)
    opex_pct_per_year: float = Field(0.015, ge=0, le=0.1)
    discount_rate: float = Field(0.07, ge=0, le=0.3)
    analysis_years: int = Field(15, ge=1, le=30)

    # Prices
    import_price_pln_mwh: float = Field(800.0, ge=0)
    export_price_pln_mwh: float = Field(0.0, ge=0)

    # Degradation budget
    max_efc_per_year: Optional[float] = None
    max_throughput_mwh_per_year: Optional[float] = None


@app.post("/sizing", response_model=SizingResult)
async def run_sizing_optimization(request: SizingRequestAPI):
    """
    Run BESS sizing optimization.

    Tests multiple duration variants (default: 1h, 2h, 4h) and finds
    optimal power for each using NPV-based grid search.

    Returns:
    - S/M/L variant results with economics
    - Degradation metrics per variant
    - Recommended variant based on score
    """
    start_time = time.time()

    try:
        stacked_params = None
        if request.mode == DispatchMode.STACKED:
            if not request.peak_limit_kw:
                raise HTTPException(400, "peak_limit_kw required for STACKED mode")
            stacked_params = StackedModeParams(
                peak_limit_kw=request.peak_limit_kw,
                reserve_fraction=request.reserve_fraction,
            )

        budget = None
        if request.max_efc_per_year or request.max_throughput_mwh_per_year:
            budget = DegradationBudget(
                max_efc_per_year=request.max_efc_per_year,
                max_throughput_mwh_per_year=request.max_throughput_mwh_per_year,
            )

        prices = PriceConfig(
            import_price_pln_mwh=request.import_price_pln_mwh,
            export_price_pln_mwh=request.export_price_pln_mwh,
        )

        internal_request = SizingRequest(
            pv_generation_kw=request.pv_generation_kw,
            load_kw=request.load_kw,
            interval_minutes=request.interval_minutes,
            mode=request.mode,
            stacked_params=stacked_params,
            peak_limit_kw=request.peak_limit_kw,
            min_power_kw=request.min_power_kw,
            max_power_kw=request.max_power_kw,
            power_steps=request.power_steps,
            durations_h=request.durations_h,
            roundtrip_efficiency=request.roundtrip_efficiency,
            soc_min=request.soc_min,
            soc_max=request.soc_max,
            capex_per_kwh=request.capex_per_kwh,
            capex_per_kw=request.capex_per_kw,
            opex_pct_per_year=request.opex_pct_per_year,
            discount_rate=request.discount_rate,
            analysis_years=request.analysis_years,
            prices=prices,
            degradation_budget=budget,
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
# Main
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8031)

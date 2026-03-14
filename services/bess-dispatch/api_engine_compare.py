"""
Engine Comparison API Router
============================

Provides endpoints for multi-engine BESS analysis:
- /advisor/compare - Run sizing/dispatch comparison across engines
- /advisor/engines - List available engines and their status

Version: 1.0.0
"""

import logging
import time
from datetime import datetime
from typing import List, Optional, Dict, Any
import numpy as np

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from canonical_input import (
    CanonicalInput,
    CanonicalBattery,
    CanonicalTimeAxis,
    CanonicalPricing,
    CanonicalPolicies,
    CanonicalEconomics,
    CanonicalDispatchMode,
    validate_canonical_input,
)
from engine_adapters import (
    NativeAdapter,
    REoptAdapter,
    PySAMAdapter,
    EngineComparator,
    ComparisonResult,
    ConfidenceLevel,
)
from engine_adapters.base import EngineType

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/bess-dispatch/advisor",
    tags=["advisor"],
)


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

class EngineInfo(BaseModel):
    """Information about a single engine."""
    engine_type: str
    engine_version: str
    is_available: bool
    description: str


class EnginesResponse(BaseModel):
    """Response listing available engines."""
    engines: List[EngineInfo]
    default_engine: str = "native"


class CompareRequest(BaseModel):
    """Request for multi-engine comparison."""
    # Required timeseries
    pv_kw: List[float] = Field(..., description="PV generation [kW_avg]")
    load_kw: List[float] = Field(..., description="Load consumption [kW_avg]")

    # Time axis
    start_datetime: Optional[str] = Field(None, description="ISO 8601 start datetime")
    interval_minutes: int = Field(60, description="Time interval (15 or 60)")

    # Pricing
    price_import: Optional[List[float]] = Field(None, description="Import prices [PLN/kWh]")
    price_export: Optional[List[float]] = Field(None, description="Export prices [PLN/kWh]")
    flat_rate_import: float = Field(0.7, description="Flat import rate if price_import not provided")
    flat_rate_export: float = Field(0.0, description="Flat export rate if price_export not provided")

    # Mode
    mode: str = Field("pv_surplus", description="Dispatch mode: pv_surplus, peak_shaving, stacked, arbitrage")

    # Policies
    peak_limit_kw: Optional[float] = Field(None, description="Peak limit for stacked/peak_shaving mode")
    reserve_fraction: float = Field(0.3, description="SOC reserve for peak shaving")
    allow_grid_charging: bool = Field(True, description="Allow charging from grid")
    arbitrage_enabled: bool = Field(False, description="Enable arbitrage strategy")
    arbitrage_strategy: str = Field("zone_based", description="Arbitrage strategy")

    # Economics
    capex_per_kwh: float = Field(1500.0, description="CAPEX per kWh [PLN]")
    capex_per_kw: float = Field(300.0, description="CAPEX per kW [PLN]")
    discount_rate: float = Field(0.10, description="Discount rate")
    analysis_years: int = Field(15, description="Analysis period")

    # Battery (optional - for dispatch comparison)
    battery_power_kw: Optional[float] = Field(None, description="Fixed battery power for dispatch")
    battery_energy_kwh: Optional[float] = Field(None, description="Fixed battery energy for dispatch")

    # Engines to use
    engines: Optional[List[str]] = Field(
        None,
        description="Engines to use: native, reopt, pysam. Default: all available"
    )

    # Comparison mode
    comparison_mode: str = Field(
        "sizing",
        description="Comparison mode: sizing, dispatch, or full"
    )


class CompareResponse(BaseModel):
    """Response from multi-engine comparison."""
    # Metadata
    comparison_timestamp: str
    comparison_mode: str
    engines_used: List[str]
    engines_available: Dict[str, bool]

    # Confidence
    confidence_level: str
    confidence_score: float

    # Recommended sizing (consensus)
    recommended: Dict[str, Any]

    # Per-engine results summary
    sizing_comparison: Optional[Dict[str, Any]] = None
    dispatch_comparison: Optional[Dict[str, Any]] = None

    # Computation times
    computation_times_ms: Dict[str, float]

    # Issues and diagnostics
    issues: List[Dict[str, Any]]
    n_issues_error: int
    n_issues_warning: int

    # Validation
    input_validation: Dict[str, Any]


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/engines", response_model=EnginesResponse)
async def list_engines():
    """
    List available BESS calculation engines.

    Returns information about each engine:
    - native: Fast Polish-market-specific heuristic engine
    - reopt: NREL REopt MILP optimizer (requires API key)
    - pysam: NREL PySAM dispatch simulator (requires package)
    """
    native = NativeAdapter()
    reopt = REoptAdapter()
    pysam = PySAMAdapter()

    engines = [
        EngineInfo(
            engine_type="native",
            engine_version=native.engine_version,
            is_available=native.is_available(),
            description="Fast Polish-market heuristic engine with OSD tariff support"
        ),
        EngineInfo(
            engine_type="reopt",
            engine_version=reopt.engine_version,
            is_available=reopt.is_available(),
            description="NREL REopt MILP optimizer - golden reference for sizing"
        ),
        EngineInfo(
            engine_type="pysam",
            engine_version=pysam.engine_version,
            is_available=pysam.is_available(),
            description="NREL PySAM battery dispatch - reference for SOC validation"
        ),
    ]

    return EnginesResponse(
        engines=engines,
        default_engine="native"
    )


@router.post("/compare", response_model=CompareResponse)
async def run_comparison(request: CompareRequest):
    """
    Run multi-engine BESS analysis comparison.

    Executes sizing/dispatch across multiple engines and generates:
    - Confidence score based on engine agreement
    - Difference report highlighting discrepancies
    - Recommended values (weighted consensus)
    - Diagnostic issues for debugging

    Calculation modes:
    - standard: Native engine only (fastest)
    - verified: Native + REopt (MILP validation)
    - diagnostic: All engines (full comparison)
    """
    start_time = time.time()

    try:
        # Build canonical input
        canonical = _build_canonical_input(request)

        # Validate input
        validation = validate_canonical_input(canonical)

        if not validation.is_valid:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid input: {', '.join(validation.errors)}"
            )

        # Set up comparator with requested engines
        comparator = EngineComparator()
        comparator.add_engine(NativeAdapter())
        comparator.add_engine(REoptAdapter())
        comparator.add_engine(PySAMAdapter())

        # Determine which engines to use
        engines_to_use = None
        if request.engines:
            engine_map = {
                "native": EngineType.NATIVE,
                "reopt": EngineType.REOPT,
                "pysam": EngineType.PYSAM,
            }
            engines_to_use = [
                engine_map[e] for e in request.engines
                if e in engine_map
            ]

        # Run comparison based on mode
        if request.comparison_mode == "sizing":
            result = comparator.run_sizing_comparison(canonical, engines_to_use)
        elif request.comparison_mode == "dispatch":
            if not request.battery_power_kw or not request.battery_energy_kwh:
                raise HTTPException(
                    status_code=400,
                    detail="Dispatch comparison requires battery_power_kw and battery_energy_kwh"
                )
            battery = CanonicalBattery(
                power_kw=request.battery_power_kw,
                energy_kwh=request.battery_energy_kwh,
            )
            result = comparator.run_dispatch_comparison(canonical, battery, engines_to_use)
        elif request.comparison_mode == "full":
            result = comparator.run_full_comparison(canonical, engines_to_use)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid comparison_mode: {request.comparison_mode}"
            )

        # Build response
        result_dict = result.to_dict()

        return CompareResponse(
            comparison_timestamp=result.comparison_timestamp,
            comparison_mode=request.comparison_mode,
            engines_used=result.engines_used,
            engines_available=result.engines_available,
            confidence_level=result.confidence_level.value,
            confidence_score=result.confidence_score,
            recommended={
                "power_kw": round(result.recommended_power_kw, 1),
                "energy_kwh": round(result.recommended_energy_kwh, 1),
                "npv_pln": round(result.recommended_npv_pln, 0),
                "duration_h": round(
                    result.recommended_energy_kwh / result.recommended_power_kw, 1
                ) if result.recommended_power_kw > 0 else 0,
            },
            sizing_comparison=result_dict.get("sizing"),
            dispatch_comparison=result_dict.get("dispatch"),
            computation_times_ms=result_dict.get("computation_times_ms", {}),
            issues=result_dict.get("issues", []),
            n_issues_error=result_dict.get("n_issues_error", 0),
            n_issues_warning=result_dict.get("n_issues_warning", 0),
            input_validation=validation.to_dict(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Comparison failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Comparison error: {str(e)}"
        )


def _build_canonical_input(request: CompareRequest) -> CanonicalInput:
    """Build CanonicalInput from CompareRequest."""
    n = len(request.load_kw)

    # Validate array lengths
    if len(request.pv_kw) != n:
        raise HTTPException(
            status_code=400,
            detail=f"pv_kw length ({len(request.pv_kw)}) must match load_kw length ({n})"
        )

    # Time axis
    if request.start_datetime:
        start_dt = datetime.fromisoformat(request.start_datetime)
    else:
        start_dt = datetime(datetime.now().year, 1, 1)

    time_axis = CanonicalTimeAxis(
        start_datetime=start_dt,
        interval_minutes=request.interval_minutes,
        n_points=n,
    )

    # Pricing
    if request.price_import:
        if len(request.price_import) != n:
            raise HTTPException(
                status_code=400,
                detail=f"price_import length ({len(request.price_import)}) must match load_kw length ({n})"
            )
        p_import = np.array(request.price_import, dtype=np.float64)
    else:
        p_import = np.full(n, request.flat_rate_import, dtype=np.float64)

    if request.price_export:
        if len(request.price_export) != n:
            raise HTTPException(
                status_code=400,
                detail=f"price_export length ({len(request.price_export)}) must match load_kw length ({n})"
            )
        p_export = np.array(request.price_export, dtype=np.float64)
    else:
        p_export = np.full(n, request.flat_rate_export, dtype=np.float64)

    pricing = CanonicalPricing(
        price_import=p_import,
        price_export=p_export,
    )

    # Mode
    mode_map = {
        "pv_surplus": CanonicalDispatchMode.PV_SURPLUS,
        "peak_shaving": CanonicalDispatchMode.PEAK_SHAVING,
        "stacked": CanonicalDispatchMode.STACKED,
        "arbitrage": CanonicalDispatchMode.ARBITRAGE,
        "load_only": CanonicalDispatchMode.LOAD_ONLY,
    }
    mode = mode_map.get(request.mode, CanonicalDispatchMode.PV_SURPLUS)

    # Policies
    policies = CanonicalPolicies(
        allow_grid_charging=request.allow_grid_charging,
        peak_limit_kw=request.peak_limit_kw,
        reserve_fraction=request.reserve_fraction,
        arbitrage_enabled=request.arbitrage_enabled,
        arbitrage_strategy=request.arbitrage_strategy,
    )

    # Economics
    economics = CanonicalEconomics(
        capex_per_kwh=request.capex_per_kwh,
        capex_per_kw=request.capex_per_kw,
        discount_rate=request.discount_rate,
        analysis_years=request.analysis_years,
    )

    # Battery (optional)
    battery = None
    if request.battery_power_kw and request.battery_energy_kwh:
        battery = CanonicalBattery(
            power_kw=request.battery_power_kw,
            energy_kwh=request.battery_energy_kwh,
        )

    return CanonicalInput(
        time_axis=time_axis,
        pv_kw=np.array(request.pv_kw, dtype=np.float64),
        load_kw=np.array(request.load_kw, dtype=np.float64),
        pricing=pricing,
        battery=battery,
        policies=policies,
        economics=economics,
        mode=mode,
        source_format="compare_request",
    )

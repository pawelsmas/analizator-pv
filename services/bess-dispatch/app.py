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
import json
import os
import time
import uuid
from typing import List, Optional, Dict, Any, Union
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel, Field, model_validator

from observability.http_metrics import (
    HTTP_REQUESTS_TOTAL,
    HTTP_REQUEST_DURATION_SECONDS,
    SERVICE_NAME,
)

from limits_config import (
    MAX_STEPS,
    MAX_REQUEST_BYTES,
    MAX_VARIANTS,
    MAX_DURATIONS,
    MAX_TRACE_STEPS,
    TimeseriesMode,
    ErrorCode,
    get_limits_info,
)
from middleware.request_size_limit import RequestSizeLimitMiddleware
from timeseries_throttle import (
    resolve_timeseries_mode,
    validate_preview_rows,
    check_full_timeseries_limit,
    truncate_timeseries_array,
    truncate_timeseries_dict,
    get_timeseries_info,
)

from observability.batch_metrics import (
    record_batch_request,
    record_portfolio_summary,
)

from observability.runstore_metrics import (
    record_runstore_save,
    record_runstore_get,
    record_runstore_list,
    record_runstore_prune,
    record_runstore_compare,
    record_runstore_export,
)

from observability.jobs_metrics import (
    record_job_created,
    record_job_idempotency_hit,
    record_job_status_transition,
    record_job_completed,
    record_job_cancelled,
    record_job_get,
    record_job_list,
    record_job_cancel,
    # v1.2.0 retention/prune/vacuum metrics
    record_jobs_prune,
    record_jobs_vacuum,
    record_jobs_stats,
    record_jobs_retention_config,
    # v1.2.0 SSE streaming metrics
    record_sse_connection,
    record_sse_event,
    record_sse_connection_duration,
    # v1.2.0 job export metrics
    record_job_export,
)

from observability.metadata_metrics import (
    # v1.3.0 run metadata metrics
    record_run_metadata_patch,
    record_run_metadata_patch_error,
    record_run_list_tag_filter,
    record_run_list_search,
    record_run_list_sort,
    # v1.3.0 job metadata metrics
    record_job_metadata_patch,
    record_job_metadata_patch_error,
)

from observability.repro_metrics import (
    # v1.8.0 repro bundle and debug events metrics
    record_repro_run_download,
    record_repro_job_download,
    record_debug_events,
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
    FinanceConfig,
    # v0.7.0 Grid Constraints
    GridConstraints,
    # v0.8.0 Sizing Constraints
    ConstraintsConfig,
    # v0.9.0 Batch Sizing
    BatchSizingRequest,
    BatchSizingResponse,
    BatchSizingItem,
    BatchItemResult,
    BatchItemStatus,
    BatchSizingSummary,
    PortfolioSummary,
    PortfolioVariantRanking,
    # v0.9.0 Caching
    CacheInfo,
    CacheStatus,
)
from cache_helper import (
    compute_request_hash,
    generate_run_id,
    get_cache_entry,
    set_cache_entry,
    build_cache_info,
    clear_cache,
    get_cache_stats,
    DEFAULT_CACHE_TTL_SECONDS,
)
from invariants_helper import (
    compute_invariants,
    validate_invariants_strict,
    InvariantViolationError,
    STRICT_INVARIANTS,
)
from validate_pack import (
    list_packs as list_pack_names,
    load_pack,
    load_scenario_files,
    run_validate_pack,
    SCENARIOS_ROOT,
    PACKS_DIR,
)
from observability.invariant_metrics import (
    record_invariant_result,
    record_strict_invariants_status,
    record_strict_invariants_violation,
)
from observability.validation_pack_metrics import (
    record_pack_validation_request,
    record_pack_validation_result,
    record_scenario_validation,
    record_pack_validation_duration,
)
from observability.pricing_metrics import (
    record_tariff_presets_list,
    record_pricing_preview,
    record_tariff_preset_usage,
    record_tariff_schedule_usage,
    record_pricing_preview_steps,
    record_pricing_preview_duration,
    check_price_anomalies,
)
from run_store import (
    save_run,
    get_run,
    list_runs,
    prune_runs,
    update_run_metadata,
    validate_tags,
    validate_label,
    validate_notes,
    RUN_STORE_ENABLED,
    RUN_STORE_RETENTION_DAYS,
)
from job_store import (
    JobStore,
    get_job_store,
    create_job,
    get_job,
    list_jobs,
    cancel_job,
    is_cancelled,
    save_result,
    mark_running,
    update_progress,
    prune_old_jobs,
    vacuum_jobs_db,
    get_jobs_db_stats,
    update_job_metadata,
    JOB_STORE_ENABLED,
    JOBS_MAX_ITEMS,
    JOBS_INLINE_WAIT_MAX_SECONDS,
)
from job_processor import process_job
from dispatch_engine import run_dispatch
from sizing_runner import run_sizing, run_quick_sizing
from sensitivity_runner import run_sensitivity_analysis
from validation_kpis import (
    KpiSnapshot,
    ToleranceConfig,
    KpiDiff,
    extract_kpis_from_sizing_response,
    compute_kpi_diffs,
    kpi_snapshot_to_dict,
)
from common.logging_structured import (
    log_dispatch_request,
    log_dispatch_response,
    record_dispatch_metrics,
)
from common.versioning import get_full_version_info


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

# Rate Limiting Middleware (v3.2.0)
from rate_limit import RateLimitMiddleware
app.add_middleware(RateLimitMiddleware)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request size limit middleware (v2.5.0)
app.add_middleware(RequestSizeLimitMiddleware, max_bytes=MAX_REQUEST_BYTES)

# GZip compression middleware (v2.5.0 PR4)
# Compresses responses > minimum_size bytes when client accepts gzip
from starlette.middleware.gzip import GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=1000)  # Compress responses > 1KB


# Performance metrics imports (v2.5.0 PR6)
from observability.perf_metrics import (
    track_request_duration,
    track_request_size,
    track_response_size,
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

        # Track performance metrics (v2.5.0 PR6)
        track_request_duration(endpoint, method, duration)


# Deprecation tracking middleware (v2.7.0)
from deprecations_usage import (
    add_warnings_to_response,
    clear_request_deprecations,
    get_deprecation_headers,
    has_deprecations_used,
)

# Compat mode for response shaping (v2.7.0)
from compat_mode import parse_compat_mode, apply_compat_mode, CompatMode


@app.middleware("http")
async def deprecation_tracking_middleware(request: Request, call_next):
    """
    Track deprecated field usage and add deprecation headers (v2.7.0).

    Clears deprecation tracking at start of request.
    Adds Deprecation/Link/Sunset headers if deprecated fields were used.
    """
    # Clear any previous request's deprecations
    clear_request_deprecations()

    # Process the request
    response = await call_next(request)

    # Add deprecation headers if any deprecated fields were used
    if has_deprecations_used():
        headers = get_deprecation_headers()
        for name, value in headers.items():
            response.headers[name] = value

    return response


# Include arbitrage router
from api_arbitrage import router as arbitrage_router
app.include_router(arbitrage_router)

# Include auth router (v3.0.0)
from auth_router import router as auth_router
app.include_router(auth_router, prefix="/api/bess-dispatch")

# Include admin router (v3.0.0 PR3)
from admin_router import router as admin_router
app.include_router(admin_router, prefix="/api/bess-dispatch")

# Include audit router (v3.0.0 PR4)
from audit_router import router as audit_router
app.include_router(audit_router, prefix="/api/bess-dispatch")

# Include projects router (v3.7.0)
from projects_router import router as projects_router
app.include_router(projects_router, prefix="/api/bess-dispatch")


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
            "Request hash + run_id for deterministic caching (v0.9.0)",
            "Batch sizing endpoint (v0.9.0)",
        ]
    )


# =============================================================================
# Version Endpoint (v1.8.0)
# =============================================================================

class VersionResponse(BaseModel):
    """Service version information."""
    service: str = Field(..., description="Service name")
    git_sha: str = Field(..., description="Git commit SHA")
    build_time_utc: str = Field(..., description="Build timestamp (UTC)")
    schema_version: str = Field(..., description="API schema version")
    assumptions_version: str = Field(..., description="Assumptions file version hash")


@app.get("/api/bess-dispatch/version", response_model=VersionResponse)
async def get_version():
    """
    Get service version information.

    Returns git SHA, build time, schema version, and assumptions version.
    Useful for debugging and ensuring frontend/backend compatibility.
    """
    return VersionResponse(**get_full_version_info())


# =============================================================================
# Cache Management Endpoints (v0.9.0)
# =============================================================================

class CacheStatsResponse(BaseModel):
    """Cache statistics"""
    entries: int = Field(..., description="Current number of cache entries")
    max_entries: int = Field(..., description="Maximum cache entries allowed")


@app.get("/cache/stats", response_model=CacheStatsResponse)
async def cache_stats():
    """Get cache statistics."""
    stats = get_cache_stats()
    return CacheStatsResponse(**stats)


@app.delete("/cache")
async def cache_clear():
    """
    Clear all cache entries.

    Returns the number of entries cleared.
    """
    count = clear_cache()
    return {"cleared": count}


# =============================================================================
# Limits Endpoint (v2.5.0)
# =============================================================================

@app.get("/api/bess-dispatch/limits")
async def get_limits():
    """
    Get current request limits configuration.

    Returns MAX_REQUEST_BYTES, MAX_STEPS, and other configured limits.
    Useful for clients to check limits before sending large requests.
    """
    return get_limits_info()


# =============================================================================
# Deprecations Endpoint (v2.6.0)
# =============================================================================

class DeprecationItem(BaseModel):
    """A deprecated field or feature."""
    field: str = Field(..., description="Name of the deprecated field")
    location: str = Field(..., description="Location of the field in the API")
    status: str = Field(..., description="Deprecation status (deprecated, removed)")
    since: str = Field(..., description="Version when deprecation was announced")
    remove_in: str = Field(..., description="Version when field will be removed")
    replacement: str = Field(..., description="Replacement field or approach")
    notes: str = Field(..., description="Additional notes about the deprecation")


class DeprecationsResponse(BaseModel):
    """Response for deprecations endpoint."""
    version: str = Field(..., description="Deprecations registry version")
    last_updated: str = Field(..., description="Date of last update")
    items: List[DeprecationItem] = Field(..., description="List of deprecations")


def _load_deprecations() -> dict:
    """Load deprecations from SSoT file."""
    import json
    from pathlib import Path

    # Try multiple paths for the deprecations file
    possible_paths = [
        Path(__file__).parent.parent.parent / "docs" / "api" / "deprecations.json",
        Path("docs/api/deprecations.json"),
        Path("/app/docs/api/deprecations.json"),
    ]

    for path in possible_paths:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)

    # Return empty registry if file not found
    return {
        "version": "1.0.0",
        "last_updated": "unknown",
        "items": []
    }


@app.get("/api/bess-dispatch/deprecations", response_model=DeprecationsResponse)
async def get_deprecations():
    """
    Get list of deprecated API fields and features.

    Returns a registry of deprecated fields with information about:
    - When deprecation was announced (since)
    - When the field will be removed (remove_in)
    - What to use instead (replacement)

    This helps API consumers plan migrations before breaking changes.
    """
    return _load_deprecations()


# =============================================================================
# Run Store Endpoints (v1.0.0)
# =============================================================================


class PruneRunsRequest(BaseModel):
    """Request model for pruning old runs."""
    retention_days: Optional[int] = Field(
        None,
        ge=1,
        le=365,
        description="Days to keep. If None, uses RUN_STORE_RETENTION_DAYS env var."
    )


class PruneRunsResponse(BaseModel):
    """Response model for prune operation."""
    deleted: int = Field(..., description="Number of runs deleted")
    retention_days: int = Field(..., description="Retention days used")


class RetentionConfigResponse(BaseModel):
    """Response model for retention configuration."""
    retention_days: int = Field(..., description="Current retention days setting")
    run_store_enabled: bool = Field(..., description="Whether run store is enabled")


class PatchRunMetadataRequest(BaseModel):
    """Request model for updating run metadata (v1.3.0)."""
    label: Optional[str] = Field(
        None,
        max_length=80,
        description="Label for the run (max 80 chars)"
    )
    tags: Optional[List[str]] = Field(
        None,
        max_length=20,
        description="Tags list (max 20 tags, each 1-32 chars [a-zA-Z0-9_-])"
    )
    notes: Optional[str] = Field(
        None,
        max_length=2000,
        description="Notes for the run (max 2000 chars)"
    )


class PatchRunMetadataResponse(BaseModel):
    """Response model for PATCH run metadata (v1.3.0)."""
    run_id: str = Field(..., description="Run identifier")
    label: Optional[str] = Field(None, description="Updated label")
    tags: Optional[List[str]] = Field(None, description="Updated tags")
    notes: Optional[str] = Field(None, description="Updated notes")
    updated_at: str = Field(..., description="ISO 8601 timestamp of update")


@app.get("/runs/retention")
async def get_retention_config():
    """
    Get current retention configuration.

    Returns the retention days setting and whether run store is enabled.
    """
    return RetentionConfigResponse(
        retention_days=RUN_STORE_RETENTION_DAYS,
        run_store_enabled=RUN_STORE_ENABLED,
    )


@app.post("/runs:prune")
async def prune_old_runs(request: PruneRunsRequest):
    """
    Prune runs older than retention period.

    If retention_days is not provided, uses RUN_STORE_RETENTION_DAYS env var.
    Returns the number of runs deleted.
    Returns 503 if run store is disabled.
    """
    if not RUN_STORE_ENABLED:
        raise HTTPException(503, "Run store is disabled")

    retention = request.retention_days or RUN_STORE_RETENTION_DAYS
    deleted = prune_runs(retention)
    record_runstore_prune(deleted=deleted, retention_days=retention)
    return PruneRunsResponse(
        deleted=deleted,
        retention_days=retention,
    )


@app.get("/runs/{run_id}")
async def get_run_by_id(run_id: str):
    """
    Get stored run by run_id.

    Returns the full run record including request and response payloads.
    Returns 404 if run_id not found.
    Returns 503 if run store is disabled.
    """
    if not RUN_STORE_ENABLED:
        raise HTTPException(503, "Run store is disabled")

    stored = get_run(run_id)
    if stored is None:
        record_runstore_get(found=False)
        raise HTTPException(404, f"Run {run_id} not found")
    record_runstore_get(found=True)
    return stored


@app.patch("/runs/{run_id}")
async def patch_run_metadata(run_id: str, request: PatchRunMetadataRequest):
    """
    Update metadata for a run (v1.3.0).

    Allows updating label, tags, and notes fields.
    Returns 404 if run_id not found.
    Returns 422 if validation fails.
    Returns 503 if run store is disabled.
    """
    if not RUN_STORE_ENABLED:
        raise HTTPException(503, "Run store is disabled")

    # Validate tags more strictly (Pydantic only validates list length)
    try:
        validate_tags(request.tags)
        validate_label(request.label)
        validate_notes(request.notes)
    except ValueError as e:
        raise HTTPException(422, str(e))

    try:
        updated = update_run_metadata(
            run_id=run_id,
            label=request.label,
            tags=request.tags,
            notes=request.notes,
        )
    except ValueError as e:
        raise HTTPException(422, str(e))

    if not updated:
        record_run_metadata_patch_error("not_found")
        raise HTTPException(404, f"Run {run_id} not found")

    # Fetch updated run to get the updated_at timestamp
    stored = get_run(run_id)
    if stored is None:
        raise HTTPException(500, "Run updated but not found on re-fetch")

    # Record metrics for successful PATCH
    record_run_metadata_patch(
        has_label=request.label is not None,
        has_tags=request.tags is not None,
        has_notes=request.notes is not None,
        tags_count=len(request.tags) if request.tags else 0,
        notes_length=len(request.notes) if request.notes else 0,
    )

    return PatchRunMetadataResponse(
        run_id=run_id,
        label=stored.get("label"),
        tags=stored.get("tags"),
        notes=stored.get("notes"),
        updated_at=stored.get("updated_at") or "",
    )


@app.get("/runs")
async def list_runs_endpoint(
    limit: int = Query(20, ge=1, le=100, description="Max results per page"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    request_hash: Optional[str] = Query(None, description="Filter by request_hash"),
    endpoint: Optional[str] = Query(None, description="Filter by endpoint (e.g., 'sizing')"),
    tag: Optional[str] = Query(None, description="Filter by tag (exact match in tags array)"),
    q: Optional[str] = Query(None, description="Free-text search in label and notes"),
    sort: Optional[str] = Query(
        None,
        description="Sort order: created_at_asc, created_at_desc (default), updated_at_desc",
        regex="^(created_at_asc|created_at_desc|updated_at_desc)$",
    ),
):
    """
    List stored runs with optional filtering, search, and sorting (v1.3.0).

    Returns items list with metadata (without full request/response blobs).
    Supports filtering by request_hash, endpoint, tag, and free-text search.
    Supports sorting by created_at or updated_at.
    Returns 503 if run store is disabled.
    """
    if not RUN_STORE_ENABLED:
        raise HTTPException(503, "Run store is disabled")

    result = list_runs(
        limit=limit,
        offset=offset,
        request_hash=request_hash,
        endpoint=endpoint,
        tag=tag,
        q=q,
        sort=sort,
    )
    has_filters = any([request_hash, endpoint, tag, q])
    record_runstore_list(has_filters=has_filters, results_count=len(result.get("items", [])))

    # Record v1.3.0 metadata filter metrics
    if tag:
        record_run_list_tag_filter()
    if q:
        record_run_list_search()
    if sort:
        record_run_list_sort(sort_order=sort)

    return result


class CompareRunsRequest(BaseModel):
    """Request model for comparing two runs."""
    run_id_a: str = Field(..., description="First run ID (baseline)")
    run_id_b: str = Field(..., description="Second run ID (comparison)")


class CompareFieldDelta(BaseModel):
    """Delta between two field values."""
    field: str = Field(..., description="Field path (e.g., 'npv_pln')")
    a: Optional[float] = Field(None, description="Value in run A")
    b: Optional[float] = Field(None, description="Value in run B")
    delta: Optional[float] = Field(None, description="b - a")
    pct_change: Optional[float] = Field(None, description="Percent change from a to b")


class CompareRunsResponse(BaseModel):
    """Response model for run comparison."""
    run_id_a: str
    run_id_b: str
    same_request_hash: bool = Field(..., description="Whether runs have same request")
    recommended_variant_a: Optional[str] = None
    recommended_variant_b: Optional[str] = None
    variant_changed: bool = False
    key_deltas: List[CompareFieldDelta] = Field(default_factory=list)


def _safe_delta(a: Optional[float], b: Optional[float]) -> Optional[float]:
    """Calculate delta, returning None if either value is None."""
    if a is None or b is None:
        return None
    return b - a


def _safe_pct_change(a: Optional[float], b: Optional[float]) -> Optional[float]:
    """Calculate percent change, returning None if base is 0 or None."""
    if a is None or b is None or a == 0:
        return None
    return ((b - a) / abs(a)) * 100.0


def _extract_numeric(response: Dict, path: str) -> Optional[float]:
    """Extract numeric value from response by path."""
    try:
        parts = path.split(".")
        val = response
        for part in parts:
            if isinstance(val, dict):
                val = val.get(part)
            else:
                return None
        if isinstance(val, (int, float)):
            return float(val)
        return None
    except (KeyError, TypeError):
        return None


@app.post("/runs:compare")
async def compare_runs(request: CompareRunsRequest):
    """
    Compare two runs and compute deltas for key metrics.

    Returns comparison of recommended variant and key economic metrics.
    Useful for A/B testing or tracking changes across runs.
    Returns 404 if either run_id not found.
    Returns 503 if run store is disabled.
    """
    if not RUN_STORE_ENABLED:
        raise HTTPException(503, "Run store is disabled")

    run_a = get_run(request.run_id_a)
    run_b = get_run(request.run_id_b)

    if run_a is None:
        raise HTTPException(404, f"Run {request.run_id_a} not found")
    if run_b is None:
        raise HTTPException(404, f"Run {request.run_id_b} not found")

    # Extract response data
    resp_a = run_a.get("response", {})
    resp_b = run_b.get("response", {})

    # Same request hash?
    same_hash = run_a.get("request_hash") == run_b.get("request_hash")

    # Get recommended variants
    rec_a = resp_a.get("recommended_variant")
    rec_b = resp_b.get("recommended_variant")
    variant_changed = rec_a != rec_b

    # Key metrics to compare
    key_paths = [
        "recommended_variant_npv_pln",  # From top_variants_details
        "recommended_variant_payback_years",
    ]

    # Extract from top_variants_details (first element is recommended)
    tvd_a = resp_a.get("top_variants_details", [])
    tvd_b = resp_b.get("top_variants_details", [])

    npv_a = tvd_a[0].get("npv_pln") if len(tvd_a) > 0 else None
    npv_b = tvd_b[0].get("npv_pln") if len(tvd_b) > 0 else None
    payback_a = tvd_a[0].get("payback_years") if len(tvd_a) > 0 else None
    payback_b = tvd_b[0].get("payback_years") if len(tvd_b) > 0 else None

    key_deltas = [
        CompareFieldDelta(
            field="recommended_npv_pln",
            a=npv_a,
            b=npv_b,
            delta=_safe_delta(npv_a, npv_b),
            pct_change=_safe_pct_change(npv_a, npv_b),
        ),
        CompareFieldDelta(
            field="recommended_payback_years",
            a=payback_a,
            b=payback_b,
            delta=_safe_delta(payback_a, payback_b),
            pct_change=_safe_pct_change(payback_a, payback_b),
        ),
    ]

    record_runstore_compare(variant_changed=variant_changed)

    return CompareRunsResponse(
        run_id_a=request.run_id_a,
        run_id_b=request.run_id_b,
        same_request_hash=same_hash,
        recommended_variant_a=rec_a,
        recommended_variant_b=rec_b,
        variant_changed=variant_changed,
        key_deltas=key_deltas,
    )


@app.get("/runs/{run_id}/export/json")
async def export_run_json(run_id: str):
    """
    Export run as downloadable JSON file.

    Returns the full run record as a JSON file attachment.
    Filename: run_{run_id}.json

    Returns 404 if run_id not found.
    Returns 503 if run store is disabled.
    """
    if not RUN_STORE_ENABLED:
        raise HTTPException(503, "Run store is disabled")

    stored = get_run(run_id)
    if stored is None:
        raise HTTPException(404, f"Run {run_id} not found")

    import json
    content = json.dumps(stored, indent=2, ensure_ascii=False, default=str)

    record_runstore_export(format_type="json")

    return Response(
        content=content,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="run_{run_id}.json"'
        }
    )


def _flatten_dict(d: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    """Flatten nested dict for CSV export."""
    items = {}
    for k, v in d.items():
        new_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            items.update(_flatten_dict(v, new_key))
        elif isinstance(v, list):
            # For lists, store as JSON string
            import json
            items[new_key] = json.dumps(v, default=str)
        else:
            items[new_key] = v
    return items


@app.get("/runs/{run_id}/export/csv")
async def export_run_csv(run_id: str):
    """
    Export run as downloadable CSV file.

    Returns run metadata and key metrics as CSV.
    Filename: run_{run_id}.csv

    CSV contains:
    - Run metadata (run_id, request_hash, created_at, endpoint, status, cache_hit)
    - Key metrics from recommended variant (npv_pln, payback_years, net_savings_pln)

    Returns 404 if run_id not found.
    Returns 503 if run store is disabled.
    """
    if not RUN_STORE_ENABLED:
        raise HTTPException(503, "Run store is disabled")

    stored = get_run(run_id)
    if stored is None:
        raise HTTPException(404, f"Run {run_id} not found")

    import csv

    # Build CSV data
    rows = []

    # Row 1: Metadata
    metadata = {
        "run_id": stored.get("run_id"),
        "request_hash": stored.get("request_hash"),
        "created_at": stored.get("created_at"),
        "endpoint": stored.get("endpoint"),
        "status": stored.get("status"),
        "cache_hit": stored.get("cache_hit"),
        "schema_version": stored.get("schema_version"),
        "assumptions_version": stored.get("assumptions_version"),
        "compute_time_ms": stored.get("compute_time_ms"),
    }

    # Extract key metrics from response
    response = stored.get("response", {})
    rec_variant = response.get("recommended_variant")
    metadata["recommended_variant"] = rec_variant

    # Get top_variants_details for recommended variant metrics
    tvd = response.get("top_variants_details", [])
    if len(tvd) > 0:
        rec = tvd[0]
        metadata["npv_pln"] = rec.get("npv_pln")
        metadata["payback_years"] = rec.get("payback_years")
        metadata["net_savings_pln"] = rec.get("net_savings_pln")
        metadata["score"] = rec.get("score")

    # Get period_info
    period_info = response.get("period_info", {})
    metadata["period_hours"] = period_info.get("period_hours")
    metadata["period_days"] = period_info.get("period_days")

    # Build CSV
    output = io.StringIO()
    writer = csv.writer(output)

    # Write headers and values
    writer.writerow(list(metadata.keys()))
    writer.writerow(list(metadata.values()))

    csv_content = output.getvalue()

    record_runstore_export(format_type="csv")

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="run_{run_id}.csv"'
        }
    )


@app.get("/runs/{run_id}/repro.zip")
async def export_run_repro_bundle(run_id: str):
    """
    Export run as reproducibility bundle (v1.8.0).

    Returns a ZIP archive containing:
    - request.json: The original sizing request
    - response.json: The full sizing response
    - debug_events.json: Extracted debug events from recommended variant

    Filename: repro_{run_id}.zip

    Returns 404 if run_id not found.
    Returns 503 if run store is disabled.
    """
    if not RUN_STORE_ENABLED:
        raise HTTPException(503, "Run store is disabled")

    stored = get_run(run_id)
    if stored is None:
        record_repro_run_download(success=False)
        raise HTTPException(404, f"Run {run_id} not found")

    import zipfile
    import io as zip_io

    # Extract components
    request_data = stored.get("request", {})
    response_data = stored.get("response", {})

    # Extract debug_events from recommended variant
    debug_events = None
    variants = response_data.get("variants", [])
    recommended = next((v for v in variants if v.get("is_recommended")), None)
    if recommended:
        dispatch_summary = recommended.get("dispatch_summary", {})
        debug_events = dispatch_summary.get("debug_events")

    # Create ZIP in memory
    zip_buffer = zip_io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # request.json
        zf.writestr(
            "request.json",
            json.dumps(request_data, indent=2, ensure_ascii=False, default=str)
        )
        # response.json
        zf.writestr(
            "response.json",
            json.dumps(response_data, indent=2, ensure_ascii=False, default=str)
        )
        # debug_events.json (if available)
        if debug_events:
            zf.writestr(
                "debug_events.json",
                json.dumps(debug_events, indent=2, ensure_ascii=False, default=str)
            )
        # metadata.json with run info
        metadata = {
            "run_id": run_id,
            "request_hash": stored.get("request_hash"),
            "created_at": stored.get("created_at"),
            "endpoint": stored.get("endpoint"),
            "version": "1.8.0",
        }
        zf.writestr(
            "metadata.json",
            json.dumps(metadata, indent=2, ensure_ascii=False, default=str)
        )

    zip_content = zip_buffer.getvalue()

    record_runstore_export(format_type="repro_zip")
    record_repro_run_download(success=True)

    return Response(
        content=zip_content,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="repro_{run_id}.zip"'
        }
    )


# =============================================================================
# Run Report Endpoints (v2.4.0)
# =============================================================================

@app.get("/api/bess-dispatch/runs/{run_id}/report.zip")
async def get_run_report_zip(
    run_id: str,
    profile: str = Query("client", description="Report profile: client or engineering"),
    report_title: Optional[str] = Query(None, max_length=120, description="Custom report title"),
    client_name: Optional[str] = Query(None, max_length=120, description="Client name"),
    site_name: Optional[str] = Query(None, max_length=120, description="Site name"),
    prepared_by: Optional[str] = Query(None, max_length=120, description="Prepared by"),
    prepared_for: Optional[str] = Query(None, max_length=120, description="Prepared for"),
    notes: Optional[str] = Query(None, max_length=2000, description="Notes"),
    max_table_rows: int = Query(48, ge=12, le=240, description="Max table rows"),
):
    """
    Get run report as ZIP bundle (v2.4.0).

    Returns a deterministic ZIP archive containing:
    - report.json: ReportData extracted from run (SSoT)
    - request.json: Original sizing request
    - response_meta.json: Run metadata (run_id, schema_version, etc.)
    - README.md: Repro instructions and bundle documentation
    - WARNINGS.txt: Extraction warnings (if any)

    Query parameters allow customizing report options:
    - profile: 'client' (executive summary) or 'engineering' (detailed)
    - branding: report_title, client_name, site_name, prepared_by, prepared_for
    - notes: Custom notes to include
    - max_table_rows: Maximum rows in preview tables (12-240)

    Returns 404 if run_id not found.
    Returns 503 if run store is disabled.
    """
    if not RUN_STORE_ENABLED:
        raise HTTPException(503, "Run store is disabled")

    stored = get_run(run_id)
    if stored is None:
        raise HTTPException(404, f"Run {run_id} not found")

    # Import report modules
    from report_models import ReportOptions, ReportProfile, ReportBranding
    from report_zip_helper import build_run_report_zip
    from report_cache import (
        compute_report_cache_key, get_cached_report, set_cached_report, CacheHeader
    )

    # Import metrics
    import time
    from observability.report_metrics import (
        track_report_request, track_report_error, track_report_branding,
        track_report_generation
    )

    start_time = time.time()

    # Compute cache key (v2.5.0 PR3)
    cache_key = compute_report_cache_key(
        run_id=run_id,
        format="zip",
        profile=profile,
        report_title=report_title,
        client_name=client_name,
        site_name=site_name,
        prepared_by=prepared_by,
        prepared_for=prepared_for,
        notes=notes,
        max_table_rows=max_table_rows,
    )

    # Check cache
    cached_content, cache_header = get_cached_report(cache_key, "zip")
    if cached_content is not None:
        # Cache hit - return immediately with X-Cache header
        return Response(
            content=cached_content,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="report_{run_id}.zip"',
                "X-Cache": cache_header,
            }
        )

    # Cache miss - build report
    # Build options from query params
    branding = None
    if any([report_title, client_name, site_name, prepared_by, prepared_for]):
        branding = ReportBranding(
            report_title=report_title,
            client_name=client_name,
            site_name=site_name,
            prepared_by=prepared_by,
            prepared_for=prepared_for,
        )

    try:
        report_profile = ReportProfile(profile)
    except ValueError:
        report_profile = ReportProfile.CLIENT

    options = ReportOptions(
        profile=report_profile,
        branding=branding,
        notes=notes,
        max_table_rows=max_table_rows,
    )

    # Track request metrics
    track_report_request("zip", report_profile.value)
    track_report_branding(
        client_name=client_name,
        site_name=site_name,
        report_title=report_title,
        notes=notes
    )

    # Build report ZIP
    zip_content = build_run_report_zip(stored, options)

    # Cache the result (v2.5.0 PR3)
    set_cached_report(cache_key, "zip", zip_content)

    # Track generation metrics
    duration = time.time() - start_time
    track_report_generation("zip", duration, len(zip_content))

    return Response(
        content=zip_content,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="report_{run_id}.zip"',
            "X-Cache": CacheHeader.MISS,
        }
    )


@app.get("/api/bess-dispatch/runs/{run_id}/report.pdf")
async def get_run_report_pdf(
    run_id: str,
    profile: str = Query("client", description="Report profile: client or engineering"),
    report_title: Optional[str] = Query(None, max_length=120, description="Custom report title"),
    client_name: Optional[str] = Query(None, max_length=120, description="Client name"),
    site_name: Optional[str] = Query(None, max_length=120, description="Site name"),
    prepared_by: Optional[str] = Query(None, max_length=120, description="Prepared by"),
    prepared_for: Optional[str] = Query(None, max_length=120, description="Prepared for"),
    notes: Optional[str] = Query(None, max_length=2000, description="Notes"),
    max_table_rows: int = Query(48, ge=12, le=240, description="Max table rows"),
):
    """
    Get run report as PDF (v2.4.0).

    Returns a PDF report with:
    - Header with branding and run info
    - Executive summary with KPIs
    - Annual cost breakdown (MoneyLedger)
    - Energy flows and constraints
    - Engineering details (if profile=engineering)
    - Warnings

    Returns 404 if run_id not found.
    Returns 503 if run store is disabled.
    """
    if not RUN_STORE_ENABLED:
        raise HTTPException(503, "Run store is disabled")

    stored = get_run(run_id)
    if stored is None:
        raise HTTPException(404, f"Run {run_id} not found")

    # Import report modules
    import time
    from report_models import ReportOptions, ReportProfile, ReportBranding
    from report_data import build_report_data_from_run
    from report_pdf import render_pdf
    from report_cache import (
        compute_report_cache_key, get_cached_report, set_cached_report, CacheHeader
    )
    from observability.report_metrics import (
        track_report_request, track_report_branding, track_report_generation
    )

    start_time = time.time()

    # Compute cache key (v2.5.0 PR3)
    cache_key = compute_report_cache_key(
        run_id=run_id,
        format="pdf",
        profile=profile,
        report_title=report_title,
        client_name=client_name,
        site_name=site_name,
        prepared_by=prepared_by,
        prepared_for=prepared_for,
        notes=notes,
        max_table_rows=max_table_rows,
    )

    # Check cache
    cached_content, cache_header = get_cached_report(cache_key, "pdf")
    if cached_content is not None:
        # Cache hit - return immediately with X-Cache header
        return Response(
            content=cached_content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="report_{run_id}.pdf"',
                "X-Cache": cache_header,
            }
        )

    # Cache miss - build report
    # Build options from query params
    branding = None
    if any([report_title, client_name, site_name, prepared_by, prepared_for]):
        branding = ReportBranding(
            report_title=report_title,
            client_name=client_name,
            site_name=site_name,
            prepared_by=prepared_by,
            prepared_for=prepared_for,
        )

    try:
        report_profile = ReportProfile(profile)
    except ValueError:
        report_profile = ReportProfile.CLIENT

    options = ReportOptions(
        profile=report_profile,
        branding=branding,
        notes=notes,
        max_table_rows=max_table_rows,
    )

    # Track request metrics
    track_report_request("pdf", report_profile.value)
    track_report_branding(
        client_name=client_name,
        site_name=site_name,
        report_title=report_title,
        notes=notes
    )

    # Build report data and render PDF
    report_data = build_report_data_from_run(stored, options)
    pdf_content = render_pdf(report_data)

    # Cache the result (v2.5.0 PR3)
    set_cached_report(cache_key, "pdf", pdf_content)

    # Track generation metrics
    duration = time.time() - start_time
    track_report_generation("pdf", duration, len(pdf_content))

    return Response(
        content=pdf_content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="report_{run_id}.pdf"',
            "X-Cache": CacheHeader.MISS,
        }
    )


@app.get("/api/bess-dispatch/runs/{run_id}/report.xlsx")
async def get_run_report_xlsx(
    run_id: str,
    profile: str = Query("client", description="Report profile: client or engineering"),
    report_title: Optional[str] = Query(None, max_length=120, description="Custom report title"),
    client_name: Optional[str] = Query(None, max_length=120, description="Client name"),
    site_name: Optional[str] = Query(None, max_length=120, description="Site name"),
    prepared_by: Optional[str] = Query(None, max_length=120, description="Prepared by"),
    prepared_for: Optional[str] = Query(None, max_length=120, description="Prepared for"),
    notes: Optional[str] = Query(None, max_length=2000, description="Notes"),
    max_table_rows: int = Query(48, ge=12, le=240, description="Max table rows"),
):
    """
    Get run report as XLSX (v2.4.0).

    Returns an Excel workbook with worksheets:
    - Summary: Overview with KPIs
    - Ledger: Annual costs breakdown
    - Flows: Energy flows summary
    - Constraints: Grid constraints
    - Engineering (if profile=engineering): Cycles, invariants, debug events
    - Warnings (if any)

    Returns 404 if run_id not found.
    Returns 503 if run store is disabled.
    """
    if not RUN_STORE_ENABLED:
        raise HTTPException(503, "Run store is disabled")

    stored = get_run(run_id)
    if stored is None:
        raise HTTPException(404, f"Run {run_id} not found")

    # Import report modules
    import time
    from report_models import ReportOptions, ReportProfile, ReportBranding
    from report_data import build_report_data_from_run
    from report_xlsx import render_xlsx
    from report_cache import (
        compute_report_cache_key, get_cached_report, set_cached_report, CacheHeader
    )
    from observability.report_metrics import (
        track_report_request, track_report_branding, track_report_generation
    )

    start_time = time.time()

    # Compute cache key (v2.5.0 PR3)
    cache_key = compute_report_cache_key(
        run_id=run_id,
        format="xlsx",
        profile=profile,
        report_title=report_title,
        client_name=client_name,
        site_name=site_name,
        prepared_by=prepared_by,
        prepared_for=prepared_for,
        notes=notes,
        max_table_rows=max_table_rows,
    )

    # Check cache
    cached_content, cache_header = get_cached_report(cache_key, "xlsx")
    if cached_content is not None:
        # Cache hit - return immediately with X-Cache header
        return Response(
            content=cached_content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="report_{run_id}.xlsx"',
                "X-Cache": cache_header,
            }
        )

    # Cache miss - build report
    # Build options from query params
    branding = None
    if any([report_title, client_name, site_name, prepared_by, prepared_for]):
        branding = ReportBranding(
            report_title=report_title,
            client_name=client_name,
            site_name=site_name,
            prepared_by=prepared_by,
            prepared_for=prepared_for,
        )

    try:
        report_profile = ReportProfile(profile)
    except ValueError:
        report_profile = ReportProfile.CLIENT

    options = ReportOptions(
        profile=report_profile,
        branding=branding,
        notes=notes,
        max_table_rows=max_table_rows,
    )

    # Track request metrics
    track_report_request("xlsx", report_profile.value)
    track_report_branding(
        client_name=client_name,
        site_name=site_name,
        report_title=report_title,
        notes=notes
    )

    # Build report data and render XLSX
    report_data = build_report_data_from_run(stored, options)
    xlsx_content = render_xlsx(report_data)

    # Cache the result (v2.5.0 PR3)
    set_cached_report(cache_key, "xlsx", xlsx_content)

    # Track generation metrics
    duration = time.time() - start_time
    track_report_generation("xlsx", duration, len(xlsx_content))

    return Response(
        content=xlsx_content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="report_{run_id}.xlsx"',
            "X-Cache": CacheHeader.MISS,
        }
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

    # Economics timeseries (v1.5.0 - optional, off by default)
    include_economics_timeseries: bool = Field(
        False,
        description="If True, include per-timestep economics breakdown in response. Default: False to keep response small."
    )

    # Finance configuration (v0.5.0) - explicit financial parameters
    finance_config: Optional[Dict[str, Any]] = Field(
        None,
        description="Finance config: {horizon_years, discount_rate, savings_escalation_rate, opex_pln_per_year, opex_escalation_rate, capex_override_pln}. Overrides analysis_years/discount_rate when provided."
    )

    # Grid constraints (v0.7.0) - physical grid connection limits
    grid_constraints: Optional[Dict[str, Any]] = Field(
        None,
        description="Grid constraints: {max_export_kw, max_import_kw, allow_export}. "
                    "Applied to both baseline and project scenarios."
    )

    # Sizing constraints (v0.8.0) - user-defined constraints for variant selection
    constraints_config: Optional[Dict[str, Any]] = Field(
        None,
        description="Sizing constraints: {max_capex_pln, max_payback_years, min_npv_pln, min_net_savings_pln, "
                    "require_no_unserved_load, max_unserved_load_kwh}. "
                    "Variants violating constraints are marked as not feasible."
    )
    
    # Invariants (v1.6.0) - optional correctness checks
    include_invariants: bool = Field(
        False,
        description="If True, include invariants check results in each variant. Default: False."
    )

    # Battery trace (v2.2.0) - optional per-timestep battery data
    include_battery_trace: bool = Field(
        False,
        description="If True, include per-timestep battery trace (SOC, charge/discharge). Default: False."
    )

    # Price timeseries (v2.0.0) - optional per-timestep pricing
    include_price_timeseries: bool = Field(
        False,
        description="If True, include per-timestep price arrays in response. Default: False."
    )

    # Ledger timeseries (v2.0.0) - optional per-timestep costs
    include_ledger_timeseries: bool = Field(
        False,
        description="If True, include per-timestep cost ledger in response. Default: False."
    )

    @model_validator(mode='after')
    def validate_optimization_objective(self):
        """Validate optimization.objective is a valid enum value."""
        if self.optimization is not None and 'objective' in self.optimization:
            objective = self.optimization['objective']
            valid_objectives = {e.value for e in OptimizationObjective}
            if objective not in valid_objectives:
                raise ValueError(
                    f"Invalid objective '{objective}'. "
                    f"Valid values: {sorted(valid_objectives)}"
                )
        return self


@app.post("/sizing")
async def run_sizing_optimization(
    request: SizingRequestAPI,
    compat: Optional[str] = Query(
        None,
        description="Compatibility mode: 'clean' (default) omits deprecated fields, 'legacy' includes them"
    ),
):
    """
    Run BESS sizing optimization.

    Tests multiple duration variants (default: 1h, 2h, 4h) and finds
    optimal power for each using NPV-based grid search.

    Arbitrage (optional):
    - Enable with arbitrage_config + start_date
    - Sizing includes arbitrage savings in NPV calculation
    - Capacity fee savings calculated post-dispatch

    Query params:
    - compat: 'clean' (default) or 'legacy' for deprecated fields

    Returns:
    - S/M/L variant results with economics (including arbitrage savings breakdown)
    - Degradation metrics per variant
    - Recommended variant based on score
    """
    start_time = time.time()

    try:
        # Validate step limits (v2.5.0)
        n_steps = len(request.load_kw)
        if n_steps > MAX_STEPS:
            return Response(
                content=json.dumps({
                    "error_code": ErrorCode.STEPS_LIMIT_EXCEEDED,
                    "detail": f"Number of steps ({n_steps}) exceeds maximum allowed ({MAX_STEPS})",
                    "max_steps": MAX_STEPS,
                    "steps": n_steps,
                }),
                status_code=422,
                media_type="application/json",
            )

        # Resolve timeseries modes (v2.5.0 PR2)
        # Mode params override include_* flags for backward compatibility
        # v2.7.0: Track deprecated include_* flag usage
        battery_trace_mode = resolve_timeseries_mode(
            include_flag=request.include_battery_trace,
            mode_param=getattr(request, 'battery_trace_mode', None),
            deprecated_field_name="include_battery_trace",
        )
        ledger_timeseries_mode = resolve_timeseries_mode(
            include_flag=request.include_ledger_timeseries,
            mode_param=getattr(request, 'ledger_timeseries_mode', None),
            deprecated_field_name="include_ledger_timeseries",
        )
        price_timeseries_mode = resolve_timeseries_mode(
            include_flag=request.include_price_timeseries,
            mode_param=getattr(request, 'price_timeseries_mode', None),
            deprecated_field_name="include_price_timeseries",
        )
        preview_rows = validate_preview_rows(
            getattr(request, 'timeseries_preview_rows', None)
        )

        # Validate full timeseries mode limits (v2.5.0 PR2)
        # Any FULL mode with steps > MAX_TRACE_STEPS must be rejected
        if battery_trace_mode == TimeseriesMode.FULL:
            is_ok, error = check_full_timeseries_limit(n_steps)
            if not is_ok:
                return Response(
                    content=json.dumps(error),
                    status_code=422,
                    media_type="application/json",
                )
        if ledger_timeseries_mode == TimeseriesMode.FULL:
            is_ok, error = check_full_timeseries_limit(n_steps)
            if not is_ok:
                return Response(
                    content=json.dumps(error),
                    status_code=422,
                    media_type="application/json",
                )
        if price_timeseries_mode == TimeseriesMode.FULL:
            is_ok, error = check_full_timeseries_limit(n_steps)
            if not is_ok:
                return Response(
                    content=json.dumps(error),
                    status_code=422,
                    media_type="application/json",
                )

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

        # Parse finance_config (v0.5.0, v0.6.0: replacement + degradation + sweeps)
        finance_config = None
        if request.finance_config:
            fc_dict = request.finance_config
            finance_config = FinanceConfig(
                horizon_years=fc_dict.get("horizon_years", 10),
                discount_rate=fc_dict.get("discount_rate", 0.08),
                savings_escalation_rate=fc_dict.get("savings_escalation_rate", 0.0),
                opex_pln_per_year=fc_dict.get("opex_pln_per_year", 0.0),
                opex_escalation_rate=fc_dict.get("opex_escalation_rate", 0.0),
                capex_override_pln=fc_dict.get("capex_override_pln"),
                include_cashflow_timeseries=fc_dict.get("include_cashflow_timeseries", False),
                discount_rate_sweep=fc_dict.get("discount_rate_sweep"),
                # v0.6.0: Battery replacement
                replacement_year=fc_dict.get("replacement_year"),
                replacement_capex_pln=fc_dict.get("replacement_capex_pln"),
                # v0.6.0 PR3: Performance degradation
                bess_degradation_pct_per_year=fc_dict.get("bess_degradation_pct_per_year", 0.0),
                pv_degradation_pct_per_year=fc_dict.get("pv_degradation_pct_per_year", 0.0),
                # v0.6.0 PR4: Sensitivity sweeps
                energy_price_multiplier_sweep=fc_dict.get("energy_price_multiplier_sweep"),
                capex_multiplier_sweep=fc_dict.get("capex_multiplier_sweep"),
            )

        # Parse grid_constraints (v0.7.0)
        grid_constraints = None
        if request.grid_constraints:
            gc_dict = request.grid_constraints
            grid_constraints = GridConstraints(
                max_export_kw=gc_dict.get("max_export_kw"),
                max_import_kw=gc_dict.get("max_import_kw"),
                allow_export=gc_dict.get("allow_export", True),
                unserved_load_penalty_pln_kwh=gc_dict.get("unserved_load_penalty_pln_kwh", 0.0),
            )

        # Parse constraints_config (v0.8.0)
        constraints_config = None
        if request.constraints_config:
            cc_dict = request.constraints_config
            constraints_config = ConstraintsConfig(
                max_capex_pln=cc_dict.get("max_capex_pln"),
                max_payback_years=cc_dict.get("max_payback_years"),
                min_npv_pln=cc_dict.get("min_npv_pln"),
                min_net_savings_pln=cc_dict.get("min_net_savings_pln"),
                require_no_unserved_load=cc_dict.get("require_no_unserved_load", False),
                max_unserved_load_kwh=cc_dict.get("max_unserved_load_kwh"),
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
            include_economics_timeseries=request.include_economics_timeseries,
            # Finance (v0.5.0)
            finance_config=finance_config,
            # Grid constraints (v0.7.0)
            grid_constraints=grid_constraints,
            # Sizing constraints (v0.8.0)
            constraints_config=constraints_config,
        )

        # v0.9.0: Caching - compute request hash
        # Convert request to dict for hash computation
        request_dict = request.model_dump(mode="json")
        request_hash = compute_request_hash(request_dict)

        # Check cache (unless disabled via query param - future feature)
        cache_entry = get_cache_entry(request_hash)
        if cache_entry:
            # Cache hit - return cached result with updated cache_info
            result_dict, original_run_id, cached_at = cache_entry
            # v1.0.0: Generate new run_id for this request (audit trail)
            new_run_id = generate_run_id()
            cache_info = build_cache_info(
                request_hash=request_hash,
                run_id=new_run_id,
                cache_status=CacheStatus.HIT,
                cached_at=cached_at,
            )
            result_dict["cache_info"] = cache_info.model_dump(mode="json")

            # v1.0.0: Save cache hit to RunStore for audit trail
            compute_time_ms = int((time.time() - start_time) * 1000)
            save_run(
                run_id=new_run_id,
                request_hash=request_hash,
                endpoint="sizing",
                status="ok",
                cache_hit=True,
                schema_version=result_dict.get("schema_version"),
                assumptions_version=result_dict.get("assumptions_version"),
                compute_time_ms=compute_time_ms,
                request=request_dict,
                response=result_dict,
            )
            record_runstore_save(endpoint="sizing", cache_hit=True)

            return result_dict

        # Cache miss - run computation
        run_id = generate_run_id()
        result = run_sizing(internal_request)

        
        # v1.6.0: Add invariants to variants if requested
        if request.include_invariants:
            # Record STRICT_INVARIANTS mode status
            record_strict_invariants_status(STRICT_INVARIANTS)
            for variant in result.variants:
                variant_dict = variant.model_dump(mode="json")
                invariants_result = compute_invariants(variant_dict)
                object.__setattr__(variant, 'invariants', invariants_result)
                # Record invariant metrics for observability
                record_invariant_result(invariants_result)
                # Strict mode validation
                if STRICT_INVARIANTS and not invariants_result.get("all_passed", True):
                    record_strict_invariants_violation()
                    raise InvariantViolationError(
                        f"Invariant violation in variant {variant.variant}",
                        failed_invariants=[k for k, v in invariants_result.items() if k.endswith("_ok") and not v],
                        invariants=invariants_result,
                    )
        # Apply timeseries truncation based on mode (v2.5.0 PR2)
        # Only truncate if mode is PREVIEW (NONE doesn't include, FULL keeps all)
        if battery_trace_mode == TimeseriesMode.PREVIEW:
            for variant in result.variants:
                if variant.dispatch_summary and variant.dispatch_summary.battery_trace:
                    trace = variant.dispatch_summary.battery_trace
                    truncated = truncate_timeseries_dict(
                        trace.model_dump(mode="json"),
                        battery_trace_mode,
                        preview_rows,
                    )
                    # Update the trace object
                    for key, val in truncated.items():
                        setattr(trace, key, val)
        if ledger_timeseries_mode == TimeseriesMode.PREVIEW:
            for variant in result.variants:
                if variant.dispatch_summary and variant.dispatch_summary.ledger_timeseries:
                    ledger = variant.dispatch_summary.ledger_timeseries
                    truncated = truncate_timeseries_dict(
                        ledger.model_dump(mode="json"),
                        ledger_timeseries_mode,
                        preview_rows,
                    )
                    for key, val in truncated.items():
                        setattr(ledger, key, val)
        if price_timeseries_mode == TimeseriesMode.PREVIEW:
            for variant in result.variants:
                if variant.dispatch_summary and variant.dispatch_summary.price_timeseries:
                    prices = variant.dispatch_summary.price_timeseries
                    truncated = truncate_timeseries_dict(
                        prices.model_dump(mode="json"),
                        price_timeseries_mode,
                        preview_rows,
                    )
                    for key, val in truncated.items():
                        setattr(prices, key, val)

        # Build timeseries_info metadata (v2.5.0 PR2)
        timeseries_info = {
            "battery_trace": get_timeseries_info(battery_trace_mode, n_steps, preview_rows),
            "ledger_timeseries": get_timeseries_info(ledger_timeseries_mode, n_steps, preview_rows),
            "price_timeseries": get_timeseries_info(price_timeseries_mode, n_steps, preview_rows),
        }
        result.timeseries_info = timeseries_info

        # Add cache_info to result
        cache_info = build_cache_info(
            request_hash=request_hash,
            run_id=run_id,
            cache_status=CacheStatus.MISS,
        )
        result.cache_info = cache_info

        # Store in cache
        result_dict = result.model_dump(mode="json")
        set_cache_entry(request_hash, result_dict, run_id)

        # v1.0.0: Save run to RunStore for audit trail
        compute_time_ms = int((time.time() - start_time) * 1000)
        save_run(
            run_id=run_id,
            request_hash=request_hash,
            endpoint="sizing",
            status="ok",
            cache_hit=False,
            schema_version=result_dict.get("schema_version"),
            assumptions_version=result_dict.get("assumptions_version"),
            compute_time_ms=compute_time_ms,
            request=request_dict,
            response=result_dict,
        )
        record_runstore_save(endpoint="sizing", cache_hit=False)

        # Apply compat mode (v2.7.0, v2.8.0: default=clean)
        compat_mode = parse_compat_mode(compat)
        result_dict = result.model_dump(mode="json")
        # Always apply compat mode to ensure clean/legacy is enforced
        result_dict = apply_compat_mode(result_dict, compat_mode)
        # Add deprecation warnings if any deprecated fields were used (v2.7.0 PR3)
        result_dict = add_warnings_to_response(result_dict)
        return result_dict

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
# Batch Sizing Endpoint (v0.9.0)
# =============================================================================

def _process_single_sizing_item(item_request: Dict[str, Any]) -> SizingResult:
    """
    Process a single sizing request from batch.

    This is a synchronous helper that reuses the same logic as the /sizing endpoint.
    Raises exceptions on error (caller handles wrapping to BatchItemResult).
    """
    # Parse the request dict into SizingRequestAPI model
    api_request = SizingRequestAPI(**item_request)

    # Validate arbitrage requirements
    if api_request.arbitrage_config and api_request.arbitrage_config.enabled:
        if not api_request.start_date:
            raise ValueError("start_date is required when arbitrage_config.enabled=True")
        if api_request.mode != DispatchMode.STACKED:
            raise ValueError("Arbitrage sizing requires STACKED mode")

    stacked_params = None
    if api_request.mode == DispatchMode.STACKED:
        if not api_request.peak_limit_kw:
            raise ValueError("peak_limit_kw required for STACKED mode")
        stacked_params = StackedModeParams(
            peak_limit_kw=api_request.peak_limit_kw,
            reserve_fraction=api_request.reserve_fraction,
        )

    # Build DegradationBudget from request
    budget = None
    if api_request.degradation_budget:
        budget = DegradationBudget(**api_request.degradation_budget)
    elif (api_request.max_efc_per_year or api_request.max_throughput_mwh_per_year or
          api_request.max_cycles_per_day or api_request.max_throughput_mwh_per_day):
        budget = DegradationBudget(
            max_efc_per_year=api_request.max_efc_per_year,
            max_throughput_mwh_per_year=api_request.max_throughput_mwh_per_year,
            max_cycles_per_day=api_request.max_cycles_per_day,
            max_throughput_mwh_per_day=api_request.max_throughput_mwh_per_day,
        )

    # Build PriceConfig from request
    prices_dict = api_request.prices or {}
    is_tou = (
        prices_dict.get('tariff_id') or
        prices_dict.get('type') in ('two_zone', 'three_zone')
    )

    if is_tou:
        if not prices_dict.get('tariff_id'):
            tou_type = prices_dict.get('type', 'two_zone')
            if tou_type == 'two_zone':
                day_rate = prices_dict.get('day_rate_pln_mwh', 800.0)
                night_rate = prices_dict.get('night_rate_pln_mwh', 400.0)
                avg_rate = day_rate * 0.6 + night_rate * 0.4
            elif tou_type == 'three_zone':
                peak_rate = prices_dict.get('peak_rate_pln_mwh', 1200.0)
                day_rate = prices_dict.get('day_rate_pln_mwh', 800.0)
                night_rate = prices_dict.get('night_rate_pln_mwh', 400.0)
                avg_rate = peak_rate * 0.2 + day_rate * 0.4 + night_rate * 0.4
            else:
                avg_rate = api_request.import_price_pln_mwh

            other_fees = prices_dict.get('other_fees_pln_mwh', 451.0)
            full_import_price = avg_rate + other_fees

            prices = PriceConfig(
                import_price_pln_mwh=full_import_price,
                export_price_pln_mwh=api_request.export_price_pln_mwh,
                demand_charge_pln_kw_month=api_request.demand_charge_pln_kw_month,
                demand_charge_pln_kw_year=api_request.demand_charge_pln_kw_year,
                other_fees_pln_mwh=other_fees,
                capacity_fee_method=prices_dict.get('capacity_fee_method', 'dynamic'),
                capacity_fee_som_pln_kwh=prices_dict.get('capacity_fee_som_pln_kwh', 0.2194),
                analysis_year=prices_dict.get('analysis_year', 2025),
            )
        else:
            prices = PriceConfig(
                import_price_pln_mwh=api_request.import_price_pln_mwh,
                export_price_pln_mwh=api_request.export_price_pln_mwh,
                demand_charge_pln_kw_month=api_request.demand_charge_pln_kw_month,
                demand_charge_pln_kw_year=api_request.demand_charge_pln_kw_year,
                tariff_id=prices_dict.get('tariff_id'),
                other_fees_pln_mwh=prices_dict.get('other_fees_pln_mwh', 451.0),
                capacity_fee_method=prices_dict.get('capacity_fee_method', 'dynamic'),
                capacity_fee_som_pln_kwh=prices_dict.get('capacity_fee_som_pln_kwh', 0.2194),
                capacity_fee_fixed_pln_mwh=prices_dict.get('capacity_fee_fixed_pln_mwh'),
                analysis_year=prices_dict.get('analysis_year', 2025),
            )
    else:
        other_fees = prices_dict.get('other_fees_pln_mwh', 451.0)
        prices = PriceConfig(
            import_price_pln_mwh=api_request.import_price_pln_mwh + other_fees,
            export_price_pln_mwh=api_request.export_price_pln_mwh,
            demand_charge_pln_kw_month=api_request.demand_charge_pln_kw_month,
            demand_charge_pln_kw_year=api_request.demand_charge_pln_kw_year,
            other_fees_pln_mwh=other_fees,
        )

    # Build ArbitrageConfig for sizing
    arb_config = None
    if api_request.arbitrage_config and api_request.arbitrage_config.enabled:
        strategy_map = {
            "percentile": ArbitrageStrategy.PERCENTILE_THRESHOLD,
            "zone_based": ArbitrageStrategy.ZONE_BASED,
            "spread": ArbitrageStrategy.SPREAD_THRESHOLD,
        }
        arb_config = ArbitrageConfig(
            enabled=True,
            tariff_id=api_request.arbitrage_config.tariff_id,
            strategy=strategy_map.get(
                api_request.arbitrage_config.strategy,
                ArbitrageStrategy.PERCENTILE_THRESHOLD
            ),
            charge_below_percentile=api_request.arbitrage_config.charge_below_percentile,
            discharge_above_percentile=api_request.arbitrage_config.discharge_above_percentile,
            min_spread_pln_kwh=api_request.arbitrage_config.min_spread_pln_kwh,
            arbitrage_soc_min=api_request.arbitrage_config.arbitrage_soc_min,
            max_grid_charge_kw=api_request.arbitrage_config.max_grid_charge_kw,
            degradation_cost_pln_kwh=api_request.arbitrage_config.degradation_cost_pln_kwh,
            capacity_fee_pln_kwh=0.0,
            other_components_pln_kwh=api_request.arbitrage_config.other_components_pln_kwh,
        )

    # Parse optimization config
    optimization_config = None
    if api_request.optimization:
        opt_dict = api_request.optimization
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

    # Parse finance_config
    finance_config = None
    if api_request.finance_config:
        fc_dict = api_request.finance_config
        finance_config = FinanceConfig(
            horizon_years=fc_dict.get("horizon_years", 10),
            discount_rate=fc_dict.get("discount_rate", 0.08),
            savings_escalation_rate=fc_dict.get("savings_escalation_rate", 0.0),
            opex_pln_per_year=fc_dict.get("opex_pln_per_year", 0.0),
            opex_escalation_rate=fc_dict.get("opex_escalation_rate", 0.0),
            capex_override_pln=fc_dict.get("capex_override_pln"),
            include_cashflow_timeseries=fc_dict.get("include_cashflow_timeseries", False),
            discount_rate_sweep=fc_dict.get("discount_rate_sweep"),
            replacement_year=fc_dict.get("replacement_year"),
            replacement_capex_pln=fc_dict.get("replacement_capex_pln"),
            bess_degradation_pct_per_year=fc_dict.get("bess_degradation_pct_per_year", 0.0),
            pv_degradation_pct_per_year=fc_dict.get("pv_degradation_pct_per_year", 0.0),
            energy_price_multiplier_sweep=fc_dict.get("energy_price_multiplier_sweep"),
            capex_multiplier_sweep=fc_dict.get("capex_multiplier_sweep"),
        )

    # Parse grid_constraints
    grid_constraints = None
    if api_request.grid_constraints:
        gc_dict = api_request.grid_constraints
        grid_constraints = GridConstraints(
            max_export_kw=gc_dict.get("max_export_kw"),
            max_import_kw=gc_dict.get("max_import_kw"),
            allow_export=gc_dict.get("allow_export", True),
            unserved_load_penalty_pln_kwh=gc_dict.get("unserved_load_penalty_pln_kwh", 0.0),
        )

    # Parse constraints_config
    constraints_config = None
    if api_request.constraints_config:
        cc_dict = api_request.constraints_config
        constraints_config = ConstraintsConfig(
            max_capex_pln=cc_dict.get("max_capex_pln"),
            max_payback_years=cc_dict.get("max_payback_years"),
            min_npv_pln=cc_dict.get("min_npv_pln"),
            min_net_savings_pln=cc_dict.get("min_net_savings_pln"),
            require_no_unserved_load=cc_dict.get("require_no_unserved_load", False),
            max_unserved_load_kwh=cc_dict.get("max_unserved_load_kwh"),
        )

    internal_request = SizingRequest(
        pv_generation_kw=api_request.pv_generation_kw,
        load_kw=api_request.load_kw,
        interval_minutes=api_request.interval_minutes,
        mode=api_request.mode,
        stacked_params=stacked_params,
        peak_limit_kw=api_request.peak_limit_kw,
        arbitrage_config=arb_config,
        start_date=api_request.start_date,
        timezone=api_request.timezone,
        period_start=api_request.period_start,
        period_end=api_request.period_end,
        min_power_kw=api_request.min_power_kw,
        max_power_kw=api_request.max_power_kw,
        power_steps=api_request.power_steps,
        durations_h=api_request.durations_h,
        roundtrip_efficiency=api_request.roundtrip_efficiency,
        soc_min=api_request.soc_min,
        soc_max=api_request.soc_max,
        eol_capacity_factor=api_request.eol_capacity_factor,
        annual_degradation_pct=api_request.annual_degradation_pct,
        capex_per_kwh=api_request.capex_per_kwh,
        capex_per_kw=api_request.capex_per_kw,
        opex_pct_per_year=api_request.opex_pct_per_year,
        discount_rate=api_request.discount_rate,
        analysis_years=api_request.analysis_years,
        prices=prices,
        degradation_cost_pln_mwh=api_request.degradation_cost_pln_mwh,
        degradation_budget=budget,
        optimization=optimization_config,
        include_energy_flows_timeseries=api_request.include_energy_flows_timeseries,
        include_economics_timeseries=api_request.include_economics_timeseries,
        finance_config=finance_config,
        grid_constraints=grid_constraints,
        constraints_config=constraints_config,
    )

    return run_sizing(internal_request)


def _build_portfolio_summary(
    results: List[BatchItemResult]
) -> Optional[PortfolioSummary]:
    """
    Build portfolio summary from batch results.

    Aggregates metrics across all successful items to identify
    the best overall variant for the portfolio.

    Returns None if no successful results.
    """
    from collections import defaultdict

    # Filter successful results
    ok_results = [r for r in results if r.status == BatchItemStatus.OK and r.response]
    if not ok_results:
        return None

    # Collect variant data across all items
    # variant_name -> list of (npv, payback, is_feasible, is_recommended)
    variant_data: Dict[str, List[Dict]] = defaultdict(list)
    recommended_npv_sum = 0.0
    recommended_payback_sum = 0.0
    recommended_count = 0

    for result in ok_results:
        resp = result.response
        recommended_variant = resp.get("recommended_variant", "")

        # Get recommended variant data for overall metrics
        for v in resp.get("variants", []):
            variant_name = v.get("variant", "")
            npv = v.get("npv_pln", 0.0)
            payback = v.get("simple_payback_years", float("inf"))
            is_recommended = (variant_name == recommended_variant)

            # Check feasibility
            feasibility = v.get("feasibility", {})
            is_feasible = feasibility.get("is_feasible", True) if feasibility else True

            variant_data[variant_name].append({
                "npv": npv,
                "payback": payback,
                "is_feasible": is_feasible,
                "is_recommended": is_recommended,
            })

            if is_recommended:
                recommended_npv_sum += npv
                recommended_payback_sum += payback
                recommended_count += 1

    # Build variant rankings
    variant_rankings = []
    for variant_name, data_list in variant_data.items():
        total_npv = sum(d["npv"] for d in data_list)
        avg_npv = total_npv / len(data_list) if data_list else 0.0

        payback_values = [d["payback"] for d in data_list if d["payback"] < float("inf")]
        avg_payback = sum(payback_values) / len(payback_values) if payback_values else float("inf")

        feasible_count = sum(1 for d in data_list if d["is_feasible"])
        rec_count = sum(1 for d in data_list if d["is_recommended"])

        variant_rankings.append(PortfolioVariantRanking(
            variant=variant_name,
            total_npv_pln=total_npv,
            avg_npv_pln=avg_npv,
            avg_payback_years=avg_payback if avg_payback < float("inf") else 0.0,
            feasible_count=feasible_count,
            recommended_count=rec_count,
        ))

    # Sort by total NPV descending
    variant_rankings.sort(key=lambda x: x.total_npv_pln, reverse=True)

    # Portfolio optimal is the variant with highest total NPV
    portfolio_optimal = variant_rankings[0].variant if variant_rankings else ""

    # Overall metrics from recommended variants
    overall_avg_npv = recommended_npv_sum / recommended_count if recommended_count > 0 else 0.0
    overall_avg_payback = recommended_payback_sum / recommended_count if recommended_count > 0 else 0.0

    return PortfolioSummary(
        total_npv_pln=recommended_npv_sum,
        avg_npv_pln=overall_avg_npv,
        avg_payback_years=overall_avg_payback,
        portfolio_optimal_variant=portfolio_optimal,
        variant_rankings=variant_rankings,
    )


@app.post("/sizing:batch", response_model=BatchSizingResponse)
async def run_batch_sizing(request: BatchSizingRequest):
    """
    Run batch BESS sizing optimization.

    Process multiple sizing requests in a single API call. Each item is processed
    independently with per-item error isolation.

    Features:
    - batch_id: Unique identifier for the batch (server-generated if not provided)
    - fail_fast: If True, stop on first error; otherwise process all items
    - Per-item status: ok/error with response/error message

    Use cases:
    - Compare multiple scenarios with different parameters
    - Process portfolio of sites
    - Parameter sweeps for sensitivity analysis

    Returns results for each item in the same order as the request, plus summary.
    """
    start_time = time.time()

    # Generate batch_id if not provided
    batch_id = request.batch_id or str(uuid.uuid4())

    results: List[BatchItemResult] = []
    ok_count = 0
    error_count = 0

    for item in request.items:
        try:
            # Process single item
            sizing_result = _process_single_sizing_item(item.request)

            # Convert to dict for response
            result_dict = sizing_result.model_dump(mode="json")

            results.append(BatchItemResult(
                item_id=item.item_id,
                status=BatchItemStatus.OK,
                response=result_dict,
                error=None,
            ))
            ok_count += 1

        except Exception as e:
            error_msg = str(e)
            results.append(BatchItemResult(
                item_id=item.item_id,
                status=BatchItemStatus.ERROR,
                response=None,
                error=error_msg,
            ))
            error_count += 1

            # Stop on first error if fail_fast
            if request.fail_fast:
                break

    processing_time_ms = (time.time() - start_time) * 1000

    # Get schema/assumptions versions from first successful result or use defaults
    schema_version = "1.0.0"
    assumptions_version = "v1.0-unknown"
    for r in results:
        if r.status == BatchItemStatus.OK and r.response:
            schema_version = r.response.get("schema_version", schema_version)
            assumptions_version = r.response.get("assumptions_version", assumptions_version)
            break

    # Build portfolio summary from successful results
    portfolio_summary = _build_portfolio_summary(results)

    # Record batch metrics
    record_batch_request(
        total_items=len(request.items),
        ok_count=ok_count,
        error_count=error_count,
        processing_time_ms=processing_time_ms,
    )

    # Record portfolio metrics if available
    if portfolio_summary:
        record_portfolio_summary(
            optimal_variant=portfolio_summary.portfolio_optimal_variant,
            total_npv_pln=portfolio_summary.total_npv_pln,
            avg_payback_years=portfolio_summary.avg_payback_years,
        )

    return BatchSizingResponse(
        batch_id=batch_id,
        schema_version=schema_version,
        assumptions_version=assumptions_version,
        results=results,
        summary=BatchSizingSummary(
            total_items=len(request.items),
            ok_count=ok_count,
            error_count=error_count,
            processing_time_ms=processing_time_ms,
        ),
        portfolio_summary=portfolio_summary,
    )


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
# Jobs API (v1.1.0)
# =============================================================================

class JobSizingBatchItem(BaseModel):
    """Single item in a job sizing batch request."""
    item_id: str = Field(..., description="Client-provided item identifier")
    request: Dict[str, Any] = Field(..., description="Standard sizing request payload")


class CreateJobRequest(BaseModel):
    """Request to create a sizing batch job."""
    batch_id: Optional[str] = Field(None, description="Optional batch identifier")
    idempotency_key: Optional[str] = Field(None, description="Optional key for duplicate detection")
    fail_fast: bool = Field(False, description="Stop on first error")
    wait: bool = Field(False, description="Wait for job completion (inline processing)")
    items: List[JobSizingBatchItem] = Field(..., description="List of sizing requests")


class JobStatusResponse(BaseModel):
    """Response for job status."""
    job_id: str = Field(..., description="Job identifier")
    status: str = Field(..., description="Job status (pending, running, done, failed, cancelled)")
    created_at: str = Field(..., description="Job creation timestamp")
    items_total: int = Field(..., description="Total number of items")
    items_done: int = Field(..., description="Number of completed items")
    error_count: int = Field(..., description="Number of items with errors")
    batch_id: Optional[str] = Field(None, description="Batch identifier")
    message: Optional[str] = Field(None, description="Status message")


class JobDetailResponse(BaseModel):
    """Response for job detail including result."""
    job_id: str = Field(..., description="Job identifier")
    status: str = Field(..., description="Job status")
    created_at: str = Field(..., description="Job creation timestamp")
    updated_at: str = Field(..., description="Last update timestamp")
    items_total: int = Field(..., description="Total number of items")
    items_done: int = Field(..., description="Number of completed items")
    error_count: int = Field(..., description="Number of items with errors")
    batch_id: Optional[str] = Field(None, description="Batch identifier")
    message: Optional[str] = Field(None, description="Status message")
    result: Optional[Dict[str, Any]] = Field(None, description="Job result (only for done/failed/cancelled)")
    request: Optional[Dict[str, Any]] = Field(None, description="Original request (only for done/failed/cancelled)")
    # v1.3.0 metadata fields
    label: Optional[str] = Field(None, description="Job label (v1.3.0)")
    tags: Optional[List[str]] = Field(None, description="Job tags (v1.3.0)")
    notes: Optional[str] = Field(None, description="Job notes (v1.3.0)")


class JobListResponse(BaseModel):
    """Response for job list."""
    items: List[Dict[str, Any]] = Field(..., description="List of jobs")
    total: int = Field(..., description="Total number of matching jobs")
    limit: int = Field(..., description="Results per page")
    offset: int = Field(..., description="Pagination offset")


class CancelJobResponse(BaseModel):
    """Response for job cancellation."""
    cancelled: bool = Field(..., description="Whether cancellation succeeded")
    status: str = Field(..., description="Current job status")


class PatchJobMetadataRequest(BaseModel):
    """Request model for updating job metadata (v1.3.0)."""
    label: Optional[str] = Field(
        None,
        max_length=80,
        description="Label for the job (max 80 chars)"
    )
    tags: Optional[List[str]] = Field(
        None,
        max_length=20,
        description="Tags list (max 20 tags, each 1-32 chars [a-zA-Z0-9_-])"
    )
    notes: Optional[str] = Field(
        None,
        max_length=2000,
        description="Notes for the job (max 2000 chars)"
    )


class PatchJobMetadataResponse(BaseModel):
    """Response model for PATCH job metadata (v1.3.0)."""
    job_id: str = Field(..., description="Job identifier")
    label: Optional[str] = Field(None, description="Updated label")
    tags: Optional[List[str]] = Field(None, description="Updated tags")
    notes: Optional[str] = Field(None, description="Updated notes")
    updated_at: str = Field(..., description="ISO 8601 timestamp of update")


def _process_sizing_item_for_job(request: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process a single sizing item for a job.

    This wraps _process_single_sizing_item to convert Pydantic model to dict.
    """
    sizing_result = _process_single_sizing_item(request)
    return sizing_result.model_dump(mode="json")


def _process_job_inline(job_id: str, items: List[JobSizingBatchItem], fail_fast: bool) -> Dict[str, Any]:
    """
    Process a job inline (for wait=true mode).

    Uses shared process_job function from job_processor module.
    """
    # Convert items to dict format expected by process_job
    items_dict = [{"item_id": item.item_id, "request": item.request} for item in items]

    return process_job(
        job_id=job_id,
        items=items_dict,
        fail_fast=fail_fast,
        process_item_fn=_process_sizing_item_for_job,
    )


@app.post("/api/bess-dispatch/jobs/sizing-batch", response_model=JobStatusResponse)
async def create_sizing_batch_job(request: CreateJobRequest):
    """
    Create an async sizing batch job.

    Features:
    - idempotency_key: Returns existing job if key already exists
    - wait=true: Process inline and return completed job
    - wait=false: Return immediately with pending job (requires worker for processing)
    - fail_fast: Stop on first error

    Items limit: Max 100 items per batch (configurable via JOBS_MAX_ITEMS).
    """
    if not JOB_STORE_ENABLED:
        raise HTTPException(503, "Job store is disabled")

    # Validate items count
    if len(request.items) > JOBS_MAX_ITEMS:
        raise HTTPException(422, f"Too many items: {len(request.items)} > {JOBS_MAX_ITEMS}")

    if len(request.items) == 0:
        raise HTTPException(422, "At least one item is required")

    # Build request payload for storage
    job_request = {
        "batch_id": request.batch_id,
        "fail_fast": request.fail_fast,
        "items": [{"item_id": item.item_id, "request": item.request} for item in request.items],
    }

    # Create job (idempotency handled by JobStore)
    job_id = create_job(
        type="sizing_batch",
        request=job_request,
        batch_id=request.batch_id,
        idempotency_key=request.idempotency_key,
    )

    # Get job to check if it already existed
    job = get_job(job_id)

    # If job already done (idempotency hit), return it
    if job["status"] in ("done", "failed", "cancelled"):
        record_job_idempotency_hit()
        return JobStatusResponse(
            job_id=job["job_id"],
            status=job["status"],
            created_at=job["created_at"],
            items_total=job["items_total"],
            items_done=job["items_done"],
            error_count=job["error_count"],
            batch_id=job.get("batch_id"),
            message=job.get("message"),
        )

    # Record job creation metrics
    wait_mode = "sync" if request.wait else "async"
    record_job_created(wait_mode=wait_mode, items_count=len(request.items))

    # If wait=true, process inline
    if request.wait:
        # Mark running
        mark_running(job_id)

        # Process items
        result = _process_job_inline(job_id, request.items, request.fail_fast)

        # Check if cancelled during processing
        if is_cancelled(job_id):
            record_job_cancelled()
            return JobStatusResponse(
                job_id=job_id,
                status="cancelled",
                created_at=job["created_at"],
                items_total=len(request.items),
                items_done=result["summary"]["ok_count"] + result["summary"]["error_count"],
                error_count=result["summary"]["error_count"],
                batch_id=request.batch_id,
                message="Job cancelled during processing",
            )

        # Save result
        final_status = "done" if result["summary"]["error_count"] == 0 else "done"
        save_result(job_id, result, status=final_status)

        # Record completion metrics
        processing_time_ms = result["summary"]["processing_time_ms"]
        record_job_completed(
            final_status=final_status,
            duration_seconds=processing_time_ms / 1000.0,
            ok_count=result["summary"]["ok_count"],
            error_count=result["summary"]["error_count"],
        )

        # Get updated job
        job = get_job(job_id)
        return JobStatusResponse(
            job_id=job["job_id"],
            status=job["status"],
            created_at=job["created_at"],
            items_total=job["items_total"],
            items_done=job["items_done"],
            error_count=job["error_count"],
            batch_id=job.get("batch_id"),
            message=job.get("message"),
        )

    # Return pending job (worker will process later)
    return JobStatusResponse(
        job_id=job_id,
        status="pending",
        created_at=job["created_at"],
        items_total=len(request.items),
        items_done=0,
        error_count=0,
        batch_id=request.batch_id,
        message=None,
    )


# -----------------------------------------------------------------------------

class JobRetentionConfig(BaseModel):
    """Response for job retention configuration."""
    retention_days: int = Field(..., description="Default retention days")
    job_store_enabled: bool = Field(..., description="Whether job store is enabled")


class PruneJobsRequest(BaseModel):
    """Request for pruning old jobs."""
    retention_days: Optional[int] = Field(
        None,
        ge=1,
        le=365,
        description="Days to retain (1-365). Uses JOB_STORE_RETENTION_DAYS if not provided."
    )


class PruneJobsResponse(BaseModel):
    """Response for job pruning."""
    deleted: int = Field(..., description="Number of jobs deleted")
    retention_days: int = Field(..., description="Retention days used")


class VacuumJobsResponse(BaseModel):
    """Response for database vacuum."""
    size_before_bytes: int = Field(..., description="Database size before vacuum")
    size_after_bytes: int = Field(..., description="Database size after vacuum")
    freed_bytes: int = Field(..., description="Bytes freed by vacuum")


class JobStoreStatsResponse(BaseModel):
    """Response for job store statistics."""
    total_jobs: int = Field(..., description="Total number of jobs")
    size_bytes: int = Field(..., description="Database size in bytes")
    by_status: Dict[str, int] = Field(..., description="Job count by status")
    by_type: Dict[str, int] = Field(..., description="Job count by type")
    oldest_job: Optional[str] = Field(None, description="Oldest job timestamp")
    newest_job: Optional[str] = Field(None, description="Newest job timestamp")
    job_store_enabled: bool = Field(..., description="Whether job store is enabled")


# Environment variable for job retention
JOB_STORE_RETENTION_DAYS = int(os.environ.get("JOB_STORE_RETENTION_DAYS", "14"))


@app.get("/api/bess-dispatch/jobs/retention", response_model=JobRetentionConfig)
async def get_job_retention_config():
    """
    Get current job retention configuration.

    Returns the retention days setting and whether job store is enabled.
    """
    record_jobs_retention_config()
    return JobRetentionConfig(
        retention_days=JOB_STORE_RETENTION_DAYS,
        job_store_enabled=JOB_STORE_ENABLED,
    )


@app.post("/api/bess-dispatch/jobs:prune", response_model=PruneJobsResponse)
async def prune_jobs_endpoint(request: PruneJobsRequest):
    """
    Prune jobs older than retention period.

    If retention_days is not provided, uses JOB_STORE_RETENTION_DAYS env var (default 14).
    """
    if not JOB_STORE_ENABLED:
        raise HTTPException(503, "Job store is disabled")

    retention = request.retention_days or JOB_STORE_RETENTION_DAYS
    deleted = prune_old_jobs(retention)

    # Record metrics
    record_jobs_prune(deleted_count=deleted, retention_days=retention)

    return PruneJobsResponse(
        deleted=deleted,
        retention_days=retention,
    )


@app.post("/api/bess-dispatch/jobs:vacuum", response_model=VacuumJobsResponse)
async def vacuum_jobs_endpoint():
    """
    Vacuum the job store database to reclaim space.

    This is useful after pruning a large number of jobs.
    """
    if not JOB_STORE_ENABLED:
        raise HTTPException(503, "Job store is disabled")

    result = vacuum_jobs_db()

    # Record metrics
    record_jobs_vacuum(freed_bytes=result["freed_bytes"])

    return VacuumJobsResponse(
        size_before_bytes=result["size_before_bytes"],
        size_after_bytes=result["size_after_bytes"],
        freed_bytes=result["freed_bytes"],
    )


@app.get("/api/bess-dispatch/jobs/stats", response_model=JobStoreStatsResponse)
async def get_job_store_stats():
    """
    Get job store statistics.

    Returns total jobs, size, and breakdown by status and type.
    """
    # Record metrics
    record_jobs_stats()

    if not JOB_STORE_ENABLED:
        return JobStoreStatsResponse(
            total_jobs=0,
            size_bytes=0,
            by_status={},
            by_type={},
            oldest_job=None,
            newest_job=None,
            job_store_enabled=False,
        )

    stats = get_jobs_db_stats()

    return JobStoreStatsResponse(
        total_jobs=stats["total_jobs"],
        size_bytes=stats["size_bytes"],
        by_status=stats["by_status"],
        by_type=stats["by_type"],
        oldest_job=stats["oldest_job"],
        newest_job=stats["newest_job"],
        job_store_enabled=True,
    )


@app.get("/api/bess-dispatch/jobs/{job_id}", response_model=JobDetailResponse)
async def get_job_detail(job_id: str):
    """
    Get job status and result.

    Returns full result/request only for completed jobs (done, failed, cancelled).
    """
    if not JOB_STORE_ENABLED:
        raise HTTPException(503, "Job store is disabled")

    job = get_job(job_id)
    if not job:
        record_job_get(found=False)
        raise HTTPException(404, f"Job not found: {job_id}")

    record_job_get(found=True)
    return JobDetailResponse(
        job_id=job["job_id"],
        status=job["status"],
        created_at=job["created_at"],
        updated_at=job["updated_at"],
        items_total=job["items_total"],
        items_done=job["items_done"],
        error_count=job["error_count"],
        batch_id=job.get("batch_id"),
        message=job.get("message"),
        result=job.get("result"),
        request=job.get("request"),
        # v1.3.0 metadata fields
        label=job.get("label"),
        tags=job.get("tags"),
        notes=job.get("notes"),
    )


@app.patch("/api/bess-dispatch/jobs/{job_id}", response_model=PatchJobMetadataResponse)
async def patch_job_metadata(job_id: str, request: PatchJobMetadataRequest):
    """
    Update metadata for a job (v1.3.0).

    Allows updating label, tags, and notes fields.
    Returns 404 if job_id not found.
    Returns 422 if validation fails.
    Returns 503 if job store is disabled.
    """
    if not JOB_STORE_ENABLED:
        raise HTTPException(503, "Job store is disabled")

    # Validate tags more strictly (Pydantic only validates list length)
    try:
        validate_tags(request.tags)
        validate_label(request.label)
        validate_notes(request.notes)
    except ValueError as e:
        raise HTTPException(422, str(e))

    try:
        updated = update_job_metadata(
            job_id=job_id,
            label=request.label,
            tags=request.tags,
            notes=request.notes,
        )
    except ValueError as e:
        raise HTTPException(422, str(e))

    if not updated:
        record_job_metadata_patch_error("not_found")
        raise HTTPException(404, f"Job {job_id} not found")

    # Fetch updated job to get the updated_at timestamp
    job = get_job(job_id)
    if job is None:
        raise HTTPException(500, "Job updated but not found on re-fetch")

    # Record metrics for successful PATCH
    record_job_metadata_patch(
        has_label=request.label is not None,
        has_tags=request.tags is not None,
        has_notes=request.notes is not None,
        tags_count=len(request.tags) if request.tags else 0,
        notes_length=len(request.notes) if request.notes else 0,
    )

    return PatchJobMetadataResponse(
        job_id=job_id,
        label=job.get("label"),
        tags=job.get("tags"),
        notes=job.get("notes"),
        updated_at=job.get("updated_at") or "",
    )


# -----------------------------------------------------------------------------
# Job Export Endpoints (v1.2.0)
# -----------------------------------------------------------------------------

from job_export_helper import (
    export_job_to_json,
    export_job_to_csv,
    export_job_to_zip,
)


@app.get("/api/bess-dispatch/jobs/{job_id}/export/json")
async def export_job_json(job_id: str, enriched: bool = Query(True)):
    """
    Export job results to JSON format.

    Args:
        job_id: Job identifier
        enriched: Include enriched item data with request_summary (default: true)

    Returns:
        JSON file download
    """
    if not JOB_STORE_ENABLED:
        raise HTTPException(503, "Job store is disabled")

    job = get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job not found: {job_id}")

    if job["status"] not in ("done", "failed", "cancelled"):
        raise HTTPException(400, f"Job not complete: status={job['status']}")

    json_content = export_job_to_json(job, enriched=enriched)
    batch_id = job.get("batch_id", "batch")
    filename = f"{batch_id}_{job_id[:8]}_results.json"

    # Record metrics
    record_job_export(format="json")

    return Response(
        content=json_content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/bess-dispatch/jobs/{job_id}/export/csv")
async def export_job_csv(job_id: str):
    """
    Export job results to CSV format.

    Flattens key metrics for spreadsheet analysis.

    Args:
        job_id: Job identifier

    Returns:
        CSV file download
    """
    if not JOB_STORE_ENABLED:
        raise HTTPException(503, "Job store is disabled")

    job = get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job not found: {job_id}")

    if job["status"] not in ("done", "failed", "cancelled"):
        raise HTTPException(400, f"Job not complete: status={job['status']}")

    csv_content = export_job_to_csv(job)
    batch_id = job.get("batch_id", "batch")
    filename = f"{batch_id}_{job_id[:8]}_summary.csv"

    # Record metrics
    record_job_export(format="csv")

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/bess-dispatch/jobs/{job_id}/export/zip")
async def export_job_zip(job_id: str):
    """
    Export job results to ZIP archive containing JSON and CSV.

    Args:
        job_id: Job identifier

    Returns:
        ZIP file download
    """
    if not JOB_STORE_ENABLED:
        raise HTTPException(503, "Job store is disabled")

    job = get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job not found: {job_id}")

    if job["status"] not in ("done", "failed", "cancelled"):
        raise HTTPException(400, f"Job not complete: status={job['status']}")

    zip_content = export_job_to_zip(job)
    batch_id = job.get("batch_id", "batch")
    filename = f"{batch_id}_{job_id[:8]}_export.zip"

    # Record metrics
    record_job_export(format="zip")

    return Response(
        content=zip_content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/bess-dispatch/jobs/{job_id}/repro.zip")
async def export_job_repro_bundle(job_id: str):
    """
    Export job results as reproducibility bundle (v1.8.0).

    Returns a ZIP archive containing for each item in the batch:
    - items/{index}/request.json: The original sizing request
    - items/{index}/response.json: The full sizing response
    - items/{index}/debug_events.json: Extracted debug events

    Plus metadata:
    - metadata.json: Job metadata and summary

    Filename: repro_{job_id}.zip

    Returns 404 if job_id not found.
    Returns 400 if job not complete.
    Returns 503 if job store is disabled.
    """
    if not JOB_STORE_ENABLED:
        raise HTTPException(503, "Job store is disabled")

    job = get_job(job_id)
    if not job:
        record_repro_job_download(success=False)
        raise HTTPException(404, f"Job not found: {job_id}")

    if job["status"] not in ("done", "failed", "cancelled"):
        raise HTTPException(400, f"Job not complete: status={job['status']}")

    import zipfile
    import io as zip_io

    # Create ZIP in memory
    zip_buffer = zip_io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # Get results from job (stored under 'results' not 'items')
        result = job.get("result", {})
        results = result.get("results", [])

        for idx, item in enumerate(results):
            prefix = f"items/{idx:04d}"
            item_id = item.get("item_id", f"item_{idx}")

            # response.json (response is stored directly)
            response_data = item.get("response", {})
            zf.writestr(
                f"{prefix}/response.json",
                json.dumps(response_data, indent=2, ensure_ascii=False, default=str)
            )

            # request.json (extract from response.cache_info or use item_id as placeholder)
            # Note: The original request is not stored in the results, so we extract what we can
            request_data = {"item_id": item_id, "status": item.get("status")}
            zf.writestr(
                f"{prefix}/request.json",
                json.dumps(request_data, indent=2, ensure_ascii=False, default=str)
            )

            # debug_events.json (if available)
            debug_events = None
            variants = response_data.get("variants", [])
            recommended = next((v for v in variants if v.get("is_recommended")), None)
            if recommended:
                dispatch_summary = recommended.get("dispatch_summary", {})
                debug_events = dispatch_summary.get("debug_events")

            if debug_events:
                zf.writestr(
                    f"{prefix}/debug_events.json",
                    json.dumps(debug_events, indent=2, ensure_ascii=False, default=str)
                )

        # metadata.json with job info
        metadata = {
            "job_id": job_id,
            "batch_id": job.get("batch_id"),
            "created_at": job.get("created_at"),
            "status": job.get("status"),
            "items_total": job.get("items_total", 0),
            "items_done": job.get("items_done", 0),
            "error_count": job.get("error_count", 0),
            "version": "1.8.0",
        }
        zf.writestr(
            "metadata.json",
            json.dumps(metadata, indent=2, ensure_ascii=False, default=str)
        )

    zip_content = zip_buffer.getvalue()

    record_job_export(format="repro_zip")
    record_repro_job_download(success=True)

    return Response(
        content=zip_content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="repro_{job_id[:8]}.zip"'},
    )


# -----------------------------------------------------------------------------
# Job SSE Progress Streaming (v1.2.0)
# -----------------------------------------------------------------------------

import asyncio
from starlette.responses import StreamingResponse as StarletteStreamingResponse


async def _job_progress_generator(job_id: str, poll_interval: float = 0.5, timeout: float = 600.0):
    """
    Generator that yields SSE events for job progress.

    Event types:
    - status: Job status update (pending/running/done/failed/cancelled)
    - progress: Progress update with items_done, items_total, error_count
    - done: Job completed with final result summary
    - error: Job failed with error message
    - cancelled: Job was cancelled
    - timeout: Stream timed out waiting for job completion
    """
    start_time = time.time()
    last_items_done = -1
    last_status = None

    while True:
        # Check timeout
        elapsed = time.time() - start_time
        if elapsed > timeout:
            yield f"event: timeout\ndata: {json.dumps({'message': 'Stream timed out', 'elapsed_seconds': elapsed})}\n\n"
            break

        # Get current job state
        job = get_job(job_id)
        if not job:
            yield f"event: error\ndata: {json.dumps({'message': 'Job not found'})}\n\n"
            break

        current_status = job["status"]
        items_done = job.get("items_done", 0)
        items_total = job.get("items_total", 0)
        error_count = job.get("error_count", 0)

        # Send status change event
        if current_status != last_status:
            yield f"event: status\ndata: {json.dumps({'status': current_status, 'items_done': items_done, 'items_total': items_total})}\n\n"
            last_status = current_status

        # Send progress update (only if items_done changed)
        if items_done != last_items_done and current_status == "running":
            progress_pct = (items_done / items_total * 100) if items_total > 0 else 0
            yield f"event: progress\ndata: {json.dumps({'items_done': items_done, 'items_total': items_total, 'error_count': error_count, 'progress_pct': round(progress_pct, 1)})}\n\n"
            last_items_done = items_done

        # Check for terminal states
        if current_status == "done":
            # Send final done event with summary
            result = job.get("result", {})
            summary = result.get("summary", {})
            yield f"event: done\ndata: {json.dumps({'items_done': items_done, 'items_total': items_total, 'error_count': error_count, 'processing_time_ms': summary.get('processing_time_ms', 0)})}\n\n"
            break

        if current_status == "failed":
            yield f"event: error\ndata: {json.dumps({'message': job.get('message', 'Job failed'), 'error_count': error_count})}\n\n"
            break

        if current_status == "cancelled":
            yield f"event: cancelled\ndata: {json.dumps({'message': 'Job was cancelled', 'items_done': items_done})}\n\n"
            break

        # Wait before next poll
        await asyncio.sleep(poll_interval)


@app.get("/api/bess-dispatch/jobs/{job_id}/events")
async def stream_job_events(
    job_id: str,
    poll_interval: float = Query(0.5, ge=0.1, le=5.0, description="Poll interval in seconds"),
    timeout: float = Query(600.0, ge=1.0, le=3600.0, description="Stream timeout in seconds"),
):
    """
    Stream job progress events using Server-Sent Events (SSE).

    Event types:
    - status: Job status changed (pending/running/done/failed/cancelled)
    - progress: Item processing progress (items_done, items_total, progress_pct)
    - done: Job completed successfully
    - error: Job failed with error
    - cancelled: Job was cancelled
    - timeout: Stream timed out

    Example usage with JavaScript EventSource:
    ```javascript
    const eventSource = new EventSource('/api/bess-dispatch/jobs/{job_id}/events');
    eventSource.addEventListener('progress', (e) => console.log(JSON.parse(e.data)));
    eventSource.addEventListener('done', (e) => { console.log('Done!'); eventSource.close(); });
    ```
    """
    if not JOB_STORE_ENABLED:
        raise HTTPException(503, "Job store is disabled")

    # Verify job exists
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job not found: {job_id}")

    # Record SSE connection metric
    record_sse_connection(job_status=job["status"])

    # If job is already complete, return single event
    if job["status"] in ("done", "failed", "cancelled"):
        async def single_event():
            status = job["status"]
            if status == "done":
                result = job.get("result", {})
                summary = result.get("summary", {})
                record_sse_event(event_type="done")
                yield f"event: done\ndata: {json.dumps({'items_done': job['items_done'], 'items_total': job['items_total'], 'error_count': job['error_count'], 'processing_time_ms': summary.get('processing_time_ms', 0)})}\n\n"
            elif status == "failed":
                record_sse_event(event_type="error")
                yield f"event: error\ndata: {json.dumps({'message': job.get('message', 'Job failed'), 'error_count': job['error_count']})}\n\n"
            else:
                record_sse_event(event_type="cancelled")
                yield f"event: cancelled\ndata: {json.dumps({'message': 'Job was cancelled', 'items_done': job['items_done']})}\n\n"

        return StarletteStreamingResponse(
            single_event(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            },
        )

    # Stream progress events
    return StarletteStreamingResponse(
        _job_progress_generator(job_id, poll_interval=poll_interval, timeout=timeout),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@app.get("/api/bess-dispatch/jobs", response_model=JobListResponse)
async def list_sizing_jobs(
    limit: int = Query(20, ge=1, le=100, description="Results per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    status: Optional[str] = Query(None, description="Filter by status"),
    type: Optional[str] = Query(None, description="Filter by job type"),
):
    """
    List jobs with pagination and filtering.

    Supports filtering by:
    - status: pending, running, done, failed, cancelled
    - type: sizing_batch
    """
    if not JOB_STORE_ENABLED:
        raise HTTPException(503, "Job store is disabled")

    result = list_jobs(limit=limit, offset=offset, status=status, type=type)

    # Record metrics
    has_filters = status is not None or type is not None
    record_job_list(has_filters=has_filters, results_count=len(result["items"]))

    return JobListResponse(
        items=result["items"],
        total=result["total"],
        limit=result["limit"],
        offset=result["offset"],
    )


@app.delete("/api/bess-dispatch/jobs/{job_id}", response_model=CancelJobResponse)
async def cancel_job_endpoint(job_id: str):
    """
    Cancel a pending or running job.

    Only pending or running jobs can be cancelled.
    Returns cancelled=true if successfully cancelled, false otherwise.
    """
    if not JOB_STORE_ENABLED:
        raise HTTPException(503, "Job store is disabled")

    job = get_job(job_id)
    if not job:
        record_job_cancel(result="not_found")
        raise HTTPException(404, f"Job not found: {job_id}")

    # Check if job is already completed
    if job["status"] in ("done", "failed", "cancelled"):
        record_job_cancel(result="already_done")
        return CancelJobResponse(
            cancelled=False,
            status=job["status"],
        )

    cancelled = cancel_job(job_id)

    # Record metrics
    if cancelled:
        record_job_cancel(result="cancelled")
        record_job_cancelled()
    else:
        record_job_cancel(result="already_done")

    # Get updated status
    updated_job = get_job(job_id)
    return CancelJobResponse(
        cancelled=cancelled,
        status=updated_job["status"] if updated_job else job["status"],
    )


# -----------------------------------------------------------------------------
# Job Retention/Pruning/Vacuum Endpoints (v1.2.0)
# =============================================================================


# =============================================================================
# Validation Endpoints (v1.4.0)
# =============================================================================


class ValidateSizingRequest(BaseModel):
    """Request for /validate/sizing endpoint."""
    request: Dict[str, Any] = Field(..., description="Sizing request payload")
    expected_kpis: Dict[str, float] = Field(..., description="Expected KPI values")
    tolerances: Optional[Dict[str, Any]] = Field(
        None,
        description="Tolerance configuration (default_abs, default_rel, per_field_abs, per_field_rel)"
    )
    scenario_id: Optional[str] = Field(None, description="Optional scenario ID for tracking")


class TopMismatch(BaseModel):
    """A single top mismatch entry (v1.8.0)."""
    field: str = Field(..., description="Field name that mismatched")
    expected: Any = Field(..., description="Expected value")
    actual: Any = Field(..., description="Actual value")
    abs_diff: float = Field(..., description="Absolute difference")
    rel_diff_pct: Optional[float] = Field(None, description="Relative difference as percentage")


class CostBucket(BaseModel):
    """A cost bucket for top cost breakdown (v2.0.0)."""
    category: str = Field(..., description="Cost category (import/export/fees/penalty)")
    sum_pln: float = Field(..., description="Sum of costs in this category [PLN]")
    pct_of_total: float = Field(..., description="Percentage of total costs")


class PricingDebug(BaseModel):
    """Pricing debug info for /validate response (v2.0.0 PR4)."""
    pricing_mode: Optional[str] = Field(
        None,
        description="Source of prices: 'generated' or 'override'"
    )
    price_hash: Optional[str] = Field(
        None,
        description="SHA256 hash of price timeseries (if include_price_timeseries=True)"
    )
    top_cost_buckets: List[CostBucket] = Field(
        default_factory=list,
        description="Top cost buckets from ledger_timeseries sums"
    )


class ValidateSizingResponse(BaseModel):
    """Response from /validate/sizing endpoint."""
    passed: bool = Field(..., description="True if all KPIs pass within tolerances")
    run_id: str = Field(..., description="Run ID of the sizing calculation")
    scenario_id: Optional[str] = Field(None, description="Echoed scenario ID")
    actual_kpis: Dict[str, Any] = Field(..., description="Extracted KPI values from sizing response")
    diffs: List[Dict[str, Any]] = Field(..., description="Per-field comparison results")
    failed_fields: List[str] = Field(..., description="List of fields that failed validation")
    passed_fields: List[str] = Field(..., description="List of fields that passed validation")
    # v1.8.0: Top mismatches and debug summary for drilldown
    top_mismatches: List[TopMismatch] = Field(
        default_factory=list,
        description="Top 5 mismatches sorted by abs_diff descending (v1.8.0)"
    )
    debug_summary: Optional[Dict[str, Any]] = Field(
        None,
        description="Debug events summary from sizing response (v1.8.0)"
    )
    # v2.0.0 PR4: Pricing debug info
    pricing_debug: Optional[PricingDebug] = Field(
        None,
        description="Pricing debug info (mode/hash/top buckets) for transparency (v2.0.0)"
    )


@app.post("/validate/sizing", response_model=ValidateSizingResponse)
async def validate_sizing(body: ValidateSizingRequest):
    """
    Run sizing and validate results against expected KPIs.

    This endpoint:
    1. Runs sizing with the provided request payload
    2. Extracts KPIs from the recommended variant
    3. Compares actual vs expected with tolerances
    4. Returns pass/fail status with detailed diffs

    Tolerance formula: abs_diff <= max(abs_tol, abs(expected) * rel_tol)

    Default tolerances:
    - default_abs: 1.0
    - default_rel: 0.001 (0.1%)
    """
    start_time = time.time()

    # Build tolerances config
    tol_dict = body.tolerances or {}
    tolerances = ToleranceConfig(
        default_abs=tol_dict.get("default_abs", 1.0),
        default_rel=tol_dict.get("default_rel", 0.001),
        per_field_abs=tol_dict.get("per_field_abs", {}),
        per_field_rel=tol_dict.get("per_field_rel", {}),
    )

    # Parse and run sizing
    # v2.0.0: Auto-enable price/ledger timeseries for pricing_debug in response
    request_dict = dict(body.request)
    request_dict["include_price_timeseries"] = True
    request_dict["include_ledger_timeseries"] = True
    try:
        sizing_req = SizingRequestAPI(**request_dict)
    except Exception as e:
        from observability import record_validation_error
        record_validation_error("422")
        raise HTTPException(422, f"Invalid sizing request: {e}")

    # Run sizing (reuse existing endpoint logic)
    sizing_response = await run_sizing_optimization(sizing_req)

    # Convert to dict if it's a Pydantic model (can be SizingResult or dict from cache)
    if hasattr(sizing_response, 'model_dump'):
        response_dict = sizing_response.model_dump(mode="json")
    else:
        response_dict = sizing_response

    # Extract actual KPIs
    actual_kpis = extract_kpis_from_sizing_response(response_dict)
    actual_kpis_dict = kpi_snapshot_to_dict(actual_kpis)

    # Add recommended_variant to actual_kpis for completeness
    actual_kpis_full = actual_kpis.model_dump()

    # Compute diffs
    diffs = compute_kpi_diffs(body.expected_kpis, actual_kpis_dict, tolerances)

    # Determine pass/fail
    failed_fields = [d.field for d in diffs if not d.pass_]
    passed_fields = [d.field for d in diffs if d.pass_]
    passed = len(failed_fields) == 0

    # Record validation metrics (v1.4.0)
    from observability import (
        record_validation_request,
        record_validation_result,
        record_validation_duration,
        record_validation_tolerance,
    )
    record_validation_request(body.scenario_id or "unknown")
    record_validation_result(
        scenario_id=body.scenario_id or "unknown",
        passed=passed,
        num_kpis=len(diffs),
        num_failed=len(failed_fields),
    )
    record_validation_duration(time.time() - start_time)
    record_validation_tolerance(tolerances.default_rel, tolerances.default_abs)

    # v1.5.0: Record per-field mismatch metrics
    from observability import record_field_diffs
    diffs_for_metrics = [{"field": d.field, "pass": d.pass_} for d in diffs]
    record_field_diffs(body.scenario_id or "unknown", diffs_for_metrics)

    # Get run_id from cache_info
    run_id = response_dict.get("cache_info", {}).get("run_id", "unknown")

    # Convert diffs to dicts with "pass" key (not "pass_")
    diffs_as_dicts = []
    for d in diffs:
        d_dict = d.model_dump(by_alias=True)
        diffs_as_dicts.append(d_dict)

    # v1.8.0: Compute top_mismatches (top 5 failed fields by abs_diff)
    failed_diffs = [d for d in diffs if not d.pass_]
    # Sort by abs_diff descending
    failed_diffs_sorted = sorted(failed_diffs, key=lambda x: x.abs_diff, reverse=True)
    top_mismatches = []
    for d in failed_diffs_sorted[:5]:
        rel_diff_pct = None
        if d.expected is not None and d.expected != 0:
            rel_diff_pct = (d.abs_diff / abs(d.expected)) * 100
        top_mismatches.append(TopMismatch(
            field=d.field,
            expected=d.expected,
            actual=d.actual,
            abs_diff=d.abs_diff,
            rel_diff_pct=rel_diff_pct,
        ))

    # v1.8.0: Extract debug_summary from recommended variant
    debug_summary = None
    variants = response_dict.get("variants", [])
    recommended = next((v for v in variants if v.get("is_recommended")), None)
    if recommended:
        dispatch_summary = recommended.get("dispatch_summary", {})
        debug_summary = dispatch_summary.get("debug_events")

    # v2.0.0 PR4: Extract pricing_debug from recommended variant
    pricing_debug = None
    if recommended:
        pricing_mode = recommended.get("pricing_mode")
        price_hash = recommended.get("price_hash")
        ledger_ts = recommended.get("ledger_timeseries")

        # Build top_cost_buckets from ledger_timeseries sums
        top_cost_buckets = []
        if ledger_ts:
            # Collect cost categories
            buckets_raw = [
                ("import", ledger_ts.get("sum_import_cost_pln", 0)),
                ("export_revenue", ledger_ts.get("sum_export_revenue_pln", 0)),
                ("other_fees", ledger_ts.get("sum_other_fees_pln", 0)),
                ("unserved_penalty", ledger_ts.get("sum_unserved_penalty_pln", 0)),
            ]

            # Calculate total (absolute sum for percentage calculation)
            total_abs = sum(abs(v) for _, v in buckets_raw if v != 0)

            # Sort by absolute value descending
            buckets_sorted = sorted(buckets_raw, key=lambda x: abs(x[1]), reverse=True)

            for category, sum_pln in buckets_sorted:
                if sum_pln != 0:
                    pct = (abs(sum_pln) / total_abs * 100) if total_abs > 0 else 0
                    top_cost_buckets.append(CostBucket(
                        category=category,
                        sum_pln=sum_pln,
                        pct_of_total=round(pct, 2),
                    ))

        # Only include pricing_debug if we have data
        if pricing_mode or price_hash or top_cost_buckets:
            pricing_debug = PricingDebug(
                pricing_mode=pricing_mode,
                price_hash=price_hash,
                top_cost_buckets=top_cost_buckets,
            )

    return ValidateSizingResponse(
        passed=passed,
        run_id=run_id,
        scenario_id=body.scenario_id,
        actual_kpis=actual_kpis_full,
        diffs=diffs_as_dicts,
        failed_fields=failed_fields,
        passed_fields=passed_fields,
        top_mismatches=top_mismatches,
        debug_summary=debug_summary,
        pricing_debug=pricing_debug,
    )


# =============================================================================
# Validation Packs API (v1.7.0)
# =============================================================================

class PackListResponse(BaseModel):
    """Response for GET /validation/packs"""
    packs: List[str] = Field(..., description="List of available pack names")


class CreateValidatePackJobRequest(BaseModel):
    """Request for POST /jobs/validate-pack"""
    pack: str = Field(..., description="Pack name to validate")
    idempotency_key: Optional[str] = Field(None, description="Idempotency key")
    wait: bool = Field(False, description="Process inline if true")
    strict: bool = Field(True, description="Fail on any validation errors")


class ValidatePackJobResponse(BaseModel):
    """Response for validate-pack job"""
    job_id: str
    type: str = "validate_pack"
    pack: str
    status: str
    items_total: int
    items_done: int = 0
    error_count: int = 0
    result: Optional[Dict[str, Any]] = None
    message: Optional[str] = None


@app.get("/api/bess-dispatch/validation/packs", response_model=PackListResponse)
async def get_validation_packs():
    """List available scenario packs."""
    packs = list_pack_names(PACKS_DIR)
    return PackListResponse(packs=packs)


def _validate_one_scenario_for_pack(
    request: Dict[str, Any],
    expected_kpis: Dict[str, Any],
    tolerances: Dict[str, Any],
) -> Dict[str, Any]:
    """Validate single scenario for pack validation."""
    from sizing_runner import run_sizing

    tol_config = ToleranceConfig(
        default_abs=tolerances.get("default_abs", 1.0),
        default_rel=tolerances.get("default_rel", 0.001),
        per_field_abs=tolerances.get("per_field_abs", {}),
        per_field_rel=tolerances.get("per_field_rel", {}),
    )

    try:
        sizing_req = SizingRequestAPI(**request)
        internal_req = build_internal_sizing_request(sizing_req)
        sizing_result = run_sizing(internal_req)
        response_dict = sizing_result.model_dump(mode="json")
    except Exception as e:
        return {"passed": False, "error": str(e), "diffs": []}

    run_id = response_dict.get("cache_info", {}).get("run_id")
    request_hash = response_dict.get("cache_info", {}).get("request_hash")

    actual_kpis = extract_kpis_from_sizing_response(response_dict)
    actual_kpis_dict = kpi_snapshot_to_dict(actual_kpis)

    diffs = compute_kpi_diffs(expected_kpis, actual_kpis_dict, tol_config)
    failed_fields = [d.field for d in diffs if not d.pass_]
    passed = len(failed_fields) == 0

    diffs_as_dicts = [
        {"field": d.field, "expected": d.expected, "actual": d.actual,
         "abs_diff": d.abs_diff, "rel_diff": d.rel_diff,
         "tolerance_abs": d.tolerance_abs, "tolerance_rel": d.tolerance_rel,
         "pass": d.pass_}
        for d in diffs
    ]

    return {"passed": passed, "diffs": diffs_as_dicts, "run_id": run_id, "request_hash": request_hash}


@app.post("/api/bess-dispatch/jobs/validate-pack", response_model=ValidatePackJobResponse)
async def create_validate_pack_job(request: CreateValidatePackJobRequest):
    """Create a validate-pack job."""
    if not JOB_STORE_ENABLED:
        raise HTTPException(503, "Job store is disabled")

    packs = list_pack_names(PACKS_DIR)
    if request.pack not in packs:
        raise HTTPException(404, f"Pack not found: {request.pack}")

    try:
        scenarios = load_pack(request.pack, PACKS_DIR)
    except Exception as e:
        raise HTTPException(422, f"Failed to load pack: {e}")

    job_request = {"pack": request.pack, "strict": request.strict, "scenarios": scenarios}

    job_id = create_job(
        type="validate_pack",
        request=job_request,
        idempotency_key=request.idempotency_key,
    )

    job = get_job(job_id)

    if job["status"] in ("done", "failed", "cancelled"):
        return ValidatePackJobResponse(
            job_id=job["job_id"], pack=request.pack, status=job["status"],
            items_total=job["items_total"], items_done=job["items_done"],
            error_count=job["error_count"], result=job.get("result"),
            message=job.get("message"),
        )

    if request.wait:
        mark_running(job_id)
        import time
        start_time = time.time()
        record_pack_validation_request(request.pack)
        try:
            result = run_validate_pack(
                pack_name=request.pack,
                validate_one_fn=_validate_one_scenario_for_pack,
                scenarios_root=SCENARIOS_ROOT,
                packs_dir=PACKS_DIR,
            )
            all_passed = result.get("pass", False)
            summary = result.get("summary", {})
            error_count = summary.get("fail", 0)
            save_result(job_id, result=result, status="done",
                       message=None if all_passed else f"{error_count} scenario(s) failed")
            update_progress(job_id, items_done=len(scenarios), error_count=error_count)

            # Record metrics (v1.7.0)
            duration = time.time() - start_time
            record_pack_validation_duration(request.pack, duration)
            record_pack_validation_result(request.pack, all_passed, summary)
            for scenario in result.get("scenarios", []):
                record_scenario_validation(
                    pack=request.pack,
                    scenario=scenario.get("name", "unknown"),
                    passed=scenario.get("pass", False),
                    error=bool(scenario.get("error")),
                    mismatch_count=scenario.get("mismatch_count", 0),
                )

            return ValidatePackJobResponse(
                job_id=job_id, pack=request.pack, status="done",
                items_total=len(scenarios), items_done=len(scenarios),
                error_count=error_count, result=result,
                message=None if all_passed else f"{error_count} scenario(s) failed",
            )
        except Exception as e:
            save_result(job_id, result={"pack": request.pack, "pass": False, "error": str(e)},
                       status="failed", message=str(e))
            return ValidatePackJobResponse(
                job_id=job_id, pack=request.pack, status="failed",
                items_total=len(scenarios), items_done=0, error_count=0, message=str(e),
            )

    return ValidatePackJobResponse(
        job_id=job_id, pack=request.pack, status="pending",
        items_total=len(scenarios), items_done=0, error_count=0,
    )


# =============================================================================
# Validate-Pack Exports (v1.7.0)
# =============================================================================

from validate_pack_export_helper import (
    export_validate_pack_to_csv,
    export_validate_pack_diffs_to_csv,
    export_validate_pack_to_json,
    export_validate_pack_to_zip,
)


@app.get("/api/bess-dispatch/jobs/{job_id}/validate-pack/export/csv")
async def export_validate_pack_csv(job_id: str):
    """
    Export validate-pack results to CSV format.

    Returns a summary CSV with one row per scenario.

    Args:
        job_id: Job identifier (must be a validate_pack job)

    Returns:
        CSV file download
    """
    if not JOB_STORE_ENABLED:
        raise HTTPException(503, "Job store is disabled")

    job = get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job not found: {job_id}")

    if job.get("type") != "validate_pack":
        raise HTTPException(400, f"Job is not a validate-pack job: type={job.get('type')}")

    if job["status"] not in ("done", "failed", "cancelled"):
        raise HTTPException(400, f"Job not complete: status={job['status']}")

    result = job.get("result", {})
    csv_content = export_validate_pack_to_csv(result)
    pack_name = result.get("pack", "pack")
    filename = f"validate_{pack_name}_{job_id[:8]}_summary.csv"

    record_job_export(format="csv")

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/bess-dispatch/jobs/{job_id}/validate-pack/export/diffs")
async def export_validate_pack_diffs(job_id: str):
    """
    Export validate-pack diffs to CSV format.

    Returns a detailed CSV with one row per field diff.

    Args:
        job_id: Job identifier (must be a validate_pack job)

    Returns:
        CSV file download
    """
    if not JOB_STORE_ENABLED:
        raise HTTPException(503, "Job store is disabled")

    job = get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job not found: {job_id}")

    if job.get("type") != "validate_pack":
        raise HTTPException(400, f"Job is not a validate-pack job: type={job.get('type')}")

    if job["status"] not in ("done", "failed", "cancelled"):
        raise HTTPException(400, f"Job not complete: status={job['status']}")

    result = job.get("result", {})
    csv_content = export_validate_pack_diffs_to_csv(result)
    pack_name = result.get("pack", "pack")
    filename = f"validate_{pack_name}_{job_id[:8]}_diffs.csv"

    record_job_export(format="csv")

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/bess-dispatch/jobs/{job_id}/validate-pack/export/json")
async def export_validate_pack_json(job_id: str):
    """
    Export validate-pack results to JSON format.

    Args:
        job_id: Job identifier (must be a validate_pack job)

    Returns:
        JSON file download
    """
    if not JOB_STORE_ENABLED:
        raise HTTPException(503, "Job store is disabled")

    job = get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job not found: {job_id}")

    if job.get("type") != "validate_pack":
        raise HTTPException(400, f"Job is not a validate-pack job: type={job.get('type')}")

    if job["status"] not in ("done", "failed", "cancelled"):
        raise HTTPException(400, f"Job not complete: status={job['status']}")

    result = job.get("result", {})
    json_content = export_validate_pack_to_json(result, job_id)
    pack_name = result.get("pack", "pack")
    filename = f"validate_{pack_name}_{job_id[:8]}_result.json"

    record_job_export(format="json")

    return Response(
        content=json_content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/bess-dispatch/jobs/{job_id}/validate-pack/export/zip")
async def export_validate_pack_zip(job_id: str):
    """
    Export validate-pack results to ZIP archive.

    Contains summary.csv, diffs.csv, result.json, and metadata.json.

    Args:
        job_id: Job identifier (must be a validate_pack job)

    Returns:
        ZIP file download
    """
    if not JOB_STORE_ENABLED:
        raise HTTPException(503, "Job store is disabled")

    job = get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job not found: {job_id}")

    if job.get("type") != "validate_pack":
        raise HTTPException(400, f"Job is not a validate-pack job: type={job.get('type')}")

    if job["status"] not in ("done", "failed", "cancelled"):
        raise HTTPException(400, f"Job not complete: status={job['status']}")

    result = job.get("result", {})
    zip_content = export_validate_pack_to_zip(result, job_id)
    pack_name = result.get("pack", "pack")
    filename = f"validate_{pack_name}_{job_id[:8]}.zip"

    record_job_export(format="zip")

    return Response(
        content=zip_content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# =============================================================================
# Pricing Preview (v2.1.0)
# =============================================================================

from price_timeseries_helper import generate_price_timeseries, compute_price_hash
from models import PriceTimeseriesPlnPerMwh
from tariff_presets_helper import (
    list_presets,
    get_preset,
    generate_price_timeseries_from_preset,
)


# =============================================================================
# Tariff Presets (v2.1.0)
# =============================================================================

class TariffPresetInfo(BaseModel):
    """Tariff preset summary."""
    id: str = Field(..., description="Preset identifier")
    label: str = Field(..., description="Human-readable label")


class TariffPresetsResponse(BaseModel):
    """Response from GET /tariffs endpoint."""
    presets: List[TariffPresetInfo] = Field(
        ...,
        description="List of available tariff presets"
    )


@app.get("/api/bess-dispatch/tariffs", response_model=TariffPresetsResponse)
async def get_tariffs():
    """
    List available tariff presets.

    Returns list of preset IDs and labels for UI dropdown.
    """
    # Record metrics
    record_tariff_presets_list()

    presets = list_presets()
    return TariffPresetsResponse(
        presets=[TariffPresetInfo(id=p["id"], label=p["label"]) for p in presets]
    )


class PricingPreviewRequest(BaseModel):
    """Request for pricing preview (no dispatch, just price generation)."""
    interval_minutes: int = Field(
        60,
        ge=15, le=60,
        description="Time resolution in minutes (15 or 60)"
    )
    timezone: str = Field(
        "Europe/Warsaw",
        description="Timezone for ToU zone mapping"
    )
    period_start: str = Field(
        ...,
        description="Period start (ISO 8601: YYYY-MM-DDTHH:MM:SS)"
    )
    period_end: str = Field(
        ...,
        description="Period end (ISO 8601: YYYY-MM-DDTHH:MM:SS)"
    )
    pricing_config: Optional[PriceConfig] = Field(
        None,
        description="Pricing configuration (required if tariff_preset/tariff_schedule not provided)"
    )
    tariff_preset: Optional[str] = Field(
        None,
        description="Tariff preset ID (e.g., 'pl_flat_2026'). If provided, pricing_mode='preset'"
    )
    tariff_schedule: Optional[Dict[str, Any]] = Field(
        None,
        description="Custom tariff schedule with weekday/weekend 24h arrays. If provided, pricing_mode='schedule'"
    )


class PricingPreviewPeriodInfo(BaseModel):
    """Period info for pricing preview response."""
    period_start: str
    period_end: str
    steps: int
    step_minutes: int
    timezone: str
    period_hours: float
    period_days: float


class PricingPreviewResponse(BaseModel):
    """Response from pricing preview endpoint."""
    pricing_mode: str = Field(
        ...,
        description="Pricing mode: 'generated', 'override', 'schedule', or 'preset'"
    )
    price_hash: str = Field(
        ...,
        description="SHA256 hash of price timeseries (64-char hex)"
    )
    price_timeseries: PriceTimeseriesPlnPerMwh = Field(
        ...,
        description="Generated price timeseries"
    )
    period_info: PricingPreviewPeriodInfo = Field(
        ...,
        description="Period information"
    )


@app.post("/api/bess-dispatch/pricing/preview", response_model=PricingPreviewResponse)
async def pricing_preview(request: PricingPreviewRequest):
    """
    Generate pricing preview without running dispatch.

    Returns price_timeseries with the same logic as sizing endpoint,
    but without running the actual dispatch/economics calculations.

    Supports multiple pricing modes:
    - 'generated': From pricing_config (default)
    - 'preset': From tariff_preset (e.g., 'pl_flat_2026')

    Useful for:
    - Previewing what prices will be used before running sizing
    - Verifying ToU zone mapping
    - Exporting prices for offline analysis
    """
    import time
    from datetime import datetime, timedelta

    from models import TariffScheduleConfig
    from tariff_schedule_helper import generate_price_timeseries_from_schedule

    start_time = time.time()

    try:
        # Validate that at least one pricing source is provided
        if not request.tariff_preset and not request.pricing_config and not request.tariff_schedule:
            raise HTTPException(400, "Either tariff_preset, tariff_schedule, or pricing_config must be provided")

        # Parse period dates
        try:
            start_dt = datetime.fromisoformat(request.period_start.replace('Z', '+00:00'))
        except ValueError:
            start_dt = datetime.fromisoformat(request.period_start)

        try:
            end_dt = datetime.fromisoformat(request.period_end.replace('Z', '+00:00'))
        except ValueError:
            end_dt = datetime.fromisoformat(request.period_end)

        # Calculate number of steps
        period_minutes = (end_dt - start_dt).total_seconds() / 60
        n_steps = int(period_minutes / request.interval_minutes) + 1

        if n_steps < 1:
            raise HTTPException(400, "Period must be positive")
        if n_steps > 35136:  # Max ~4 years at 15-min resolution
            raise HTTPException(400, f"Too many steps: {n_steps} (max 35136)")

        # Determine pricing mode and generate timeseries
        # Priority: tariff_schedule > tariff_preset > pricing_config
        if request.tariff_schedule:
            # Use custom tariff schedule
            schedule = TariffScheduleConfig(**request.tariff_schedule)
            price_timeseries = generate_price_timeseries_from_schedule(
                schedule=schedule,
                n_steps=n_steps,
                step_minutes=request.interval_minutes,
                start_datetime=request.period_start,
                timezone=request.timezone,
            )
            pricing_mode = "schedule"
            # Record schedule metrics
            has_holidays = bool(request.tariff_schedule.get("holiday_dates"))
            record_tariff_schedule_usage(has_holidays)
        elif request.tariff_preset:
            # Use tariff preset
            price_timeseries = generate_price_timeseries_from_preset(
                preset_id=request.tariff_preset,
                n_steps=n_steps,
                step_minutes=request.interval_minutes,
                start_datetime=request.period_start,
                timezone=request.timezone,
            )
            if not price_timeseries:
                raise HTTPException(404, f"Tariff preset not found: {request.tariff_preset}")
            pricing_mode = "preset"
            # Record preset metrics
            record_tariff_preset_usage(request.tariff_preset)
        else:
            # Use pricing_config (generated mode)
            price_timeseries = generate_price_timeseries(
                prices=request.pricing_config,
                n_steps=n_steps,
                step_minutes=request.interval_minutes,
                start_datetime=request.period_start,
                timezone=request.timezone,
            )
            pricing_mode = "generated"

        # Compute deterministic price hash
        price_hash = compute_price_hash(price_timeseries)

        # Build period info
        period_hours = n_steps * request.interval_minutes / 60
        period_info = PricingPreviewPeriodInfo(
            period_start=request.period_start,
            period_end=request.period_end,
            steps=n_steps,
            step_minutes=request.interval_minutes,
            timezone=request.timezone,
            period_hours=period_hours,
            period_days=period_hours / 24,
        )

        # Record metrics
        record_pricing_preview(pricing_mode)
        record_pricing_preview_steps(n_steps)
        record_pricing_preview_duration(time.time() - start_time)

        # Check for price anomalies
        check_price_anomalies(price_timeseries.import_price_pln_per_mwh)

        return PricingPreviewResponse(
            pricing_mode=pricing_mode,
            price_hash=price_hash,
            price_timeseries=price_timeseries,
            period_info=period_info,
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(400, f"Invalid request: {str(e)}")
    except Exception as e:
        raise HTTPException(500, f"Pricing preview error: {str(e)}")


# =============================================================================
# Portfolio Aggregation (v2.3.0)
# =============================================================================

from models import (
    PortfolioRequest,
    PortfolioResponse,
    PortfolioRunsSummary,
    PortfolioItemSummary,
    PortfolioItemError,
)
from portfolio_api import compute_portfolio_summary


@app.post("/api/bess-dispatch/portfolio/summary", response_model=PortfolioResponse)
async def portfolio_summary(request: PortfolioRequest):
    """
    Aggregate multiple runs into a portfolio summary.

    Takes a list of run_ids and returns aggregated KPIs:
    - Total NPV, savings, CAPEX across all runs
    - CAPEX-weighted average payback
    - Mixed assumptions warning
    - Top 5 items by NPV

    Args:
        request: PortfolioRequest with run_ids, optional labels/tags

    Returns:
        PortfolioResponse with summary, items, and errors
    """
    # v2.3.0: Record portfolio metrics
    from observability.portfolio_metrics import (
        record_portfolio_summary_request,
        record_portfolio_summary_result,
        record_portfolio_summary_error,
    )

    record_portfolio_summary_request(source="api")

    try:
        response = compute_portfolio_summary(
            run_ids=request.run_ids,
            labels=request.labels,
            tags=request.tags,
            get_run_fn=get_run,
        )

        # Record result metrics
        record_portfolio_summary_result(
            source="api",
            items_total=response.summary.items_total,
            items_ok=response.summary.items_ok,
            items_error=response.summary.items_error,
            total_npv_pln=response.summary.total_npv_pln,
            total_capex_pln=response.summary.total_capex_pln,
            mixed_assumptions=response.summary.mixed_assumptions,
        )

        return response

    except HTTPException:
        record_portfolio_summary_error(source="api", error_type="validation")
        raise
    except Exception as e:
        record_portfolio_summary_error(source="api", error_type="processing")
        raise HTTPException(500, f"Portfolio summary error: {str(e)}")


# -----------------------------------------------------------------------------
# Portfolio Exports (v2.3.0 PR4)
# -----------------------------------------------------------------------------

from portfolio_export_helper import (
    export_portfolio_to_csv,
    export_portfolio_to_zip,
    export_portfolio_summary_to_json,
)


@app.get("/api/bess-dispatch/jobs/{job_id}/portfolio/export/csv")
async def export_job_portfolio_csv(job_id: str):
    """
    Export job portfolio items to CSV format.

    Returns a CSV with one row per portfolio item showing KPIs.

    Args:
        job_id: Job identifier

    Returns:
        CSV file with portfolio items
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")

    result = job.get("result")
    if not result:
        raise HTTPException(404, f"Job {job_id} has no result")

    portfolio_summary = result.get("portfolio_summary")
    portfolio_items = result.get("portfolio_items")

    if not portfolio_summary or portfolio_items is None:
        raise HTTPException(404, f"Job {job_id} has no portfolio data")

    csv_content = export_portfolio_to_csv(
        portfolio_summary=portfolio_summary,
        portfolio_items=portfolio_items,
    )

    batch_id = job.get("batch_id", "batch")
    filename = f"{batch_id}_{job_id[:8]}_portfolio.csv"

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/bess-dispatch/jobs/{job_id}/portfolio/export/zip")
async def export_job_portfolio_zip(job_id: str):
    """
    Export job portfolio to ZIP archive containing JSON and CSV.

    Args:
        job_id: Job identifier

    Returns:
        ZIP file with portfolio.json, items.csv, summary.csv
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")

    result = job.get("result")
    if not result:
        raise HTTPException(404, f"Job {job_id} has no result")

    portfolio_summary = result.get("portfolio_summary")
    portfolio_items = result.get("portfolio_items")

    if not portfolio_summary or portfolio_items is None:
        raise HTTPException(404, f"Job {job_id} has no portfolio data")

    zip_content = export_portfolio_to_zip(
        portfolio_summary=portfolio_summary,
        portfolio_items=portfolio_items,
        source_id=job_id,
        source_type="job",
    )

    batch_id = job.get("batch_id", "batch")
    filename = f"{batch_id}_{job_id[:8]}_portfolio.zip"

    return Response(
        content=zip_content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/bess-dispatch/portfolio/summary/export/csv")
async def export_portfolio_summary_csv(request: PortfolioRequest):
    """
    Compute portfolio summary and export to CSV.

    Aggregates run_ids and returns CSV with portfolio items.

    Args:
        request: PortfolioRequest with run_ids

    Returns:
        CSV file with portfolio items
    """
    from observability.portfolio_metrics import record_portfolio_export_request
    record_portfolio_export_request(source="api", format="csv")

    try:
        response = compute_portfolio_summary(
            run_ids=request.run_ids,
            labels=request.labels,
            tags=request.tags,
            get_run_fn=get_run,
        )

        csv_content = export_portfolio_to_csv(
            portfolio_summary=response.summary.model_dump(),
            portfolio_items=[item.model_dump() for item in response.items],
        )

        filename = f"portfolio_{len(request.run_ids)}items.csv"

        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Portfolio export error: {str(e)}")


@app.post("/api/bess-dispatch/portfolio/summary/export/zip")
async def export_portfolio_summary_zip(request: PortfolioRequest):
    """
    Compute portfolio summary and export to ZIP.

    Aggregates run_ids and returns ZIP with portfolio.json, items.csv, summary.csv.

    Args:
        request: PortfolioRequest with run_ids

    Returns:
        ZIP file with portfolio data
    """
    from observability.portfolio_metrics import record_portfolio_export_request
    record_portfolio_export_request(source="api", format="zip")

    try:
        response = compute_portfolio_summary(
            run_ids=request.run_ids,
            labels=request.labels,
            tags=request.tags,
            get_run_fn=get_run,
        )

        zip_content = export_portfolio_to_zip(
            portfolio_summary=response.summary.model_dump(),
            portfolio_items=[item.model_dump() for item in response.items],
            source_id=None,
            source_type="portfolio",
        )

        filename = f"portfolio_{len(request.run_ids)}items.zip"

        return Response(
            content=zip_content,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Portfolio export error: {str(e)}")


# =============================================================================
# Portfolio Report Endpoint (v2.4.0)
# =============================================================================

class PortfolioReportRequest(BaseModel):
    """Request for portfolio report generation."""
    run_ids: List[str] = Field(..., min_length=1, description="List of run_ids to include")
    labels: Optional[Dict[str, str]] = Field(None, description="Optional labels: run_id -> label")
    tags: Optional[Dict[str, List[str]]] = Field(None, description="Optional tags: run_id -> [tags]")
    options: Optional[Dict[str, Any]] = Field(None, description="Report options (profile, branding, notes)")


@app.post("/api/bess-dispatch/portfolio/report.zip")
async def get_portfolio_report_zip(request: PortfolioReportRequest):
    """
    Generate portfolio report as ZIP bundle (v2.4.0).

    Returns a ZIP archive containing:
    - portfolio_summary.json: Aggregated portfolio summary
    - portfolio_items.csv: Items as CSV
    - portfolio_items.xlsx: Items as Excel
    - README.md: Documentation and repro instructions
    - WARNINGS.txt: Warnings (if any, e.g., mixed assumptions)

    Args:
        request: PortfolioReportRequest with run_ids and optional options

    Returns:
        ZIP file attachment
    """
    from report_models import ReportOptions, ReportProfile, ReportBranding
    from portfolio_report_helper import build_portfolio_report_zip
    from observability.portfolio_metrics import record_portfolio_export_request
    from observability.report_metrics import (
        track_portfolio_report_request, track_portfolio_report_error
    )
    record_portfolio_export_request(source="api", format="zip")
    track_portfolio_report_request(len(request.run_ids))

    try:
        # Compute portfolio summary
        response = compute_portfolio_summary(
            run_ids=request.run_ids,
            labels=request.labels,
            tags=request.tags,
            get_run_fn=get_run,
        )

        # Build options from request
        options = None
        if request.options:
            opts = request.options
            branding = None
            branding_opts = opts.get("branding", {})
            if branding_opts:
                branding = ReportBranding(
                    report_title=branding_opts.get("report_title"),
                    client_name=branding_opts.get("client_name"),
                    site_name=branding_opts.get("site_name"),
                    prepared_by=branding_opts.get("prepared_by"),
                    prepared_for=branding_opts.get("prepared_for"),
                )

            profile = ReportProfile.CLIENT
            if opts.get("profile") == "engineering":
                profile = ReportProfile.ENGINEERING

            options = ReportOptions(
                profile=profile,
                branding=branding,
                notes=opts.get("notes"),
                max_table_rows=opts.get("max_table_rows", 48),
            )

        # Build report ZIP
        zip_content = build_portfolio_report_zip(
            portfolio_summary=response.summary.model_dump(),
            portfolio_items=[item.model_dump() for item in response.items],
            options=options,
            source_type="api",
        )

        filename = f"portfolio_report_{len(request.run_ids)}items.zip"

        return Response(
            content=zip_content,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    except HTTPException:
        track_portfolio_report_error("validation")
        raise
    except Exception as e:
        track_portfolio_report_error("generation")
        raise HTTPException(500, f"Portfolio report error: {str(e)}")


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8031)

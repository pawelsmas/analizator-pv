"""
Structured JSON logging for observability.

Provides structured log helpers for SSoT traceability:
- assumptions_version: Hash of assumptions.yaml
- schema_version: API schema version
- period_info: Time axis metadata
- objective/mode: Optimization settings
- arbitrage_enabled: ToU arbitrage flag

Usage:
    from common.logging_structured import log_sizing_request, log_sizing_response

    log_sizing_request(request)
    result = run_sizing(request)
    log_sizing_response(result, request)

Log format: JSON lines, parseable by ELK/Loki/CloudWatch.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

# Get module-specific logger
logger = logging.getLogger("bess.structured")


def _json_log(level: str, event: str, **data: Any) -> None:
    """
    Emit structured JSON log entry.

    Format: {"ts": "...", "level": "...", "event": "...", ...data}
    """
    entry = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "level": level,
        "event": event,
        **data,
    }

    # Log as JSON string
    log_line = json.dumps(entry, default=str, ensure_ascii=False)

    if level == "INFO":
        logger.info(log_line)
    elif level == "WARNING":
        logger.warning(log_line)
    elif level == "ERROR":
        logger.error(log_line)
    elif level == "DEBUG":
        logger.debug(log_line)
    else:
        logger.info(log_line)


def log_sizing_request(
    mode: str,
    period_hours: float,
    arbitrage_enabled: bool,
    objective: str = "npv",
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Log structured entry for sizing request.

    Args:
        mode: Dispatch mode (pv_surplus, stacked, peak_shaving, load_only)
        period_hours: Analysis period length in hours
        arbitrage_enabled: Whether ToU arbitrage is enabled
        objective: Optimization objective (npv, payback, etc.)
        extra: Additional context fields
    """
    data = {
        "mode": mode,
        "period_hours": period_hours,
        "arbitrage_enabled": arbitrage_enabled,
        "objective": objective,
    }
    if extra:
        data.update(extra)

    _json_log("INFO", "sizing_request", **data)


def log_sizing_response(
    schema_version: str,
    assumptions_version: str,
    period_hours: float,
    is_full_year: bool,
    mode: str,
    arbitrage_enabled: bool,
    recommended_variant: Optional[str] = None,
    recommended_npv: Optional[float] = None,
    num_variants: int = 0,
    compute_time_ms: Optional[float] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Log structured entry for sizing response.

    This is the main observability entry for SSoT traceability.

    Args:
        schema_version: API schema version (e.g., "1.0.0")
        assumptions_version: Assumptions hash (e.g., "v1.0-abc12345")
        period_hours: Analysis period length in hours
        is_full_year: Whether period >= 8760 hours
        mode: Dispatch mode
        arbitrage_enabled: Whether ToU arbitrage was used
        recommended_variant: Recommended variant label (S/M/L)
        recommended_npv: NPV of recommended variant [PLN]
        num_variants: Number of variants computed
        compute_time_ms: Total computation time [ms]
        extra: Additional context fields
    """
    data = {
        "schema_version": schema_version,
        "assumptions_version": assumptions_version,
        "period_hours": period_hours,
        "is_full_year": is_full_year,
        "mode": mode,
        "arbitrage_enabled": arbitrage_enabled,
        "recommended_variant": recommended_variant,
        "recommended_npv_pln": recommended_npv,
        "num_variants": num_variants,
    }
    if compute_time_ms is not None:
        data["compute_time_ms"] = round(compute_time_ms, 2)
    if extra:
        data.update(extra)

    _json_log("INFO", "sizing_response", **data)


def log_dispatch_request(
    mode: str,
    period_hours: float,
    arbitrage_enabled: bool,
    battery_power_kw: float,
    battery_energy_kwh: float,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Log structured entry for dispatch request."""
    data = {
        "mode": mode,
        "period_hours": period_hours,
        "arbitrage_enabled": arbitrage_enabled,
        "battery_power_kw": battery_power_kw,
        "battery_energy_kwh": battery_energy_kwh,
    }
    if extra:
        data.update(extra)

    _json_log("INFO", "dispatch_request", **data)


def log_dispatch_response(
    annual_savings_pln: float,
    self_consumption_pct: float,
    efc_total: float,
    compute_time_ms: Optional[float] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Log structured entry for dispatch response."""
    data = {
        "annual_savings_pln": round(annual_savings_pln, 2),
        "self_consumption_pct": round(self_consumption_pct, 2),
        "efc_total": round(efc_total, 2),
    }
    if compute_time_ms is not None:
        data["compute_time_ms"] = round(compute_time_ms, 2)
    if extra:
        data.update(extra)

    _json_log("INFO", "dispatch_response", **data)


def log_error(
    event: str,
    error: str,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Log structured error entry."""
    data = {"error": error}
    if extra:
        data.update(extra)

    _json_log("ERROR", event, **data)


def log_warning(
    event: str,
    message: str,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Log structured warning entry."""
    data = {"message": message}
    if extra:
        data.update(extra)

    _json_log("WARNING", event, **data)


# =============================================================================
# Prometheus Metrics (optional)
# =============================================================================

try:
    from prometheus_client import Counter, Histogram

    SIZING_REQUESTS = Counter(
        "bess_sizing_requests_total",
        "Total number of sizing requests",
        ["mode", "arbitrage_enabled"],
    )

    SIZING_DURATION = Histogram(
        "bess_sizing_duration_seconds",
        "Sizing computation duration in seconds",
        ["mode"],
        buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
    )

    DISPATCH_REQUESTS = Counter(
        "bess_dispatch_requests_total",
        "Total number of dispatch requests",
        ["mode"],
    )

    PROMETHEUS_AVAILABLE = True

except ImportError:
    PROMETHEUS_AVAILABLE = False
    SIZING_REQUESTS = None
    SIZING_DURATION = None
    DISPATCH_REQUESTS = None


def record_sizing_metrics(
    mode: str,
    arbitrage_enabled: bool,
    duration_seconds: float,
) -> None:
    """
    Record Prometheus metrics for sizing request.

    No-op if prometheus_client not installed.
    """
    if not PROMETHEUS_AVAILABLE:
        return

    SIZING_REQUESTS.labels(
        mode=mode,
        arbitrage_enabled=str(arbitrage_enabled).lower(),
    ).inc()

    SIZING_DURATION.labels(mode=mode).observe(duration_seconds)


def record_dispatch_metrics(mode: str) -> None:
    """Record Prometheus metrics for dispatch request."""
    if not PROMETHEUS_AVAILABLE:
        return

    DISPATCH_REQUESTS.labels(mode=mode).inc()

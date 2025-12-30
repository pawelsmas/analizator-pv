"""
Prometheus metrics for scenario validation operations (v1.4.0).

Tracks:
- POST /validate/sizing requests
- Validation results (passed/failed)
- KPI diff counts and tolerances
- Validation duration
"""

from prometheus_client import Counter, Histogram


# -----------------------------------------------------------------------------
# Counters - Validation Requests
# -----------------------------------------------------------------------------

VALIDATION_REQUESTS_TOTAL = Counter(
    "bess_validation_requests_total",
    "Total POST /validate/sizing requests",
    ["scenario_id"],
)

VALIDATION_PASSED_TOTAL = Counter(
    "bess_validation_passed_total",
    "Total validations that passed",
    ["scenario_id"],
)

VALIDATION_FAILED_TOTAL = Counter(
    "bess_validation_failed_total",
    "Total validations that failed",
    ["scenario_id"],
)


# -----------------------------------------------------------------------------
# Counters - Validation Errors
# -----------------------------------------------------------------------------

VALIDATION_ERRORS_TOTAL = Counter(
    "bess_validation_errors_total",
    "Total validation errors (422/500)",
    ["error_type"],
)


# -----------------------------------------------------------------------------
# Histograms
# -----------------------------------------------------------------------------

VALIDATION_KPIS_COUNT = Histogram(
    "bess_validation_kpis_count",
    "Number of KPIs checked per validation",
    buckets=[1, 2, 3, 5, 10, 15, 20, 30],
)

VALIDATION_DIFFS_FAILED_COUNT = Histogram(
    "bess_validation_diffs_failed_count",
    "Number of failed KPI diffs per validation",
    buckets=[0, 1, 2, 3, 5, 10],
)

VALIDATION_DURATION_SECONDS = Histogram(
    "bess_validation_duration_seconds",
    "Time taken to process validation request",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

VALIDATION_TOLERANCE_REL = Histogram(
    "bess_validation_tolerance_rel",
    "Relative tolerance used in validation",
    buckets=[0.01, 0.02, 0.05, 0.10, 0.15, 0.20],
)

VALIDATION_TOLERANCE_ABS = Histogram(
    "bess_validation_tolerance_abs",
    "Absolute tolerance used in validation",
    buckets=[1, 10, 50, 100, 500, 1000, 5000],
)


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

def record_validation_request(scenario_id: str):
    """Record a validation request for a scenario."""
    VALIDATION_REQUESTS_TOTAL.labels(scenario_id=scenario_id or "unknown").inc()


def record_validation_result(scenario_id: str, passed: bool, num_kpis: int, num_failed: int):
    """Record validation result (passed/failed) with KPI counts."""
    if passed:
        VALIDATION_PASSED_TOTAL.labels(scenario_id=scenario_id or "unknown").inc()
    else:
        VALIDATION_FAILED_TOTAL.labels(scenario_id=scenario_id or "unknown").inc()

    VALIDATION_KPIS_COUNT.observe(num_kpis)
    VALIDATION_DIFFS_FAILED_COUNT.observe(num_failed)


def record_validation_error(error_type: str):
    """Record a validation error (422/500)."""
    VALIDATION_ERRORS_TOTAL.labels(error_type=error_type).inc()


def record_validation_duration(duration_seconds: float):
    """Record validation processing duration."""
    VALIDATION_DURATION_SECONDS.observe(duration_seconds)


def record_validation_tolerance(rel_tol: float, abs_tol: float):
    """Record tolerance values used in validation."""
    VALIDATION_TOLERANCE_REL.observe(rel_tol)
    VALIDATION_TOLERANCE_ABS.observe(abs_tol)

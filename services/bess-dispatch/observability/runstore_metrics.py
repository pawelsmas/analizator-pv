"""
Prometheus metrics for RunStore operations (v1.0.0).

Tracks:
- Run saves (cache hit vs miss)
- Run retrievals
- Prune operations
- Compare operations
- Export operations
"""

from prometheus_client import Counter, Histogram

# Service name for metric labels
SERVICE_NAME = "bess-dispatch"


# -----------------------------------------------------------------------------
# Counters
# -----------------------------------------------------------------------------

RUNSTORE_SAVES_TOTAL = Counter(
    "bess_runstore_saves_total",
    "Total runs saved to run store",
    ["endpoint", "cache_hit"],
)

RUNSTORE_GETS_TOTAL = Counter(
    "bess_runstore_gets_total",
    "Total runs retrieved from run store",
    ["found"],
)

RUNSTORE_LIST_REQUESTS_TOTAL = Counter(
    "bess_runstore_list_requests_total",
    "Total list/search requests to run store",
    ["has_filters"],
)

RUNSTORE_PRUNE_TOTAL = Counter(
    "bess_runstore_prune_total",
    "Total prune operations executed",
)

RUNSTORE_COMPARE_TOTAL = Counter(
    "bess_runstore_compare_total",
    "Total compare operations executed",
    ["variant_changed"],
)

RUNSTORE_EXPORT_TOTAL = Counter(
    "bess_runstore_export_total",
    "Total export operations executed",
    ["format"],
)


# -----------------------------------------------------------------------------
# Histograms
# -----------------------------------------------------------------------------

RUNSTORE_DELETED_COUNT = Histogram(
    "bess_runstore_deleted_count",
    "Number of runs deleted per prune operation",
    buckets=[0, 1, 5, 10, 50, 100, 500, 1000, 5000],
)

RUNSTORE_LIST_RESULTS_COUNT = Histogram(
    "bess_runstore_list_results_count",
    "Number of results returned per list request",
    buckets=[0, 1, 5, 10, 20, 50, 100],
)

RUNSTORE_RETENTION_DAYS = Histogram(
    "bess_runstore_retention_days",
    "Retention days used in prune operations",
    buckets=[1, 7, 14, 30, 60, 90, 180, 365],
)


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

def record_runstore_save(endpoint: str, cache_hit: bool) -> None:
    """Record a run save operation."""
    RUNSTORE_SAVES_TOTAL.labels(
        endpoint=endpoint,
        cache_hit="true" if cache_hit else "false",
    ).inc()


def record_runstore_get(found: bool) -> None:
    """Record a run get operation."""
    RUNSTORE_GETS_TOTAL.labels(
        found="true" if found else "false",
    ).inc()


def record_runstore_list(has_filters: bool, results_count: int) -> None:
    """Record a list/search request."""
    RUNSTORE_LIST_REQUESTS_TOTAL.labels(
        has_filters="true" if has_filters else "false",
    ).inc()
    RUNSTORE_LIST_RESULTS_COUNT.observe(results_count)


def record_runstore_prune(deleted: int, retention_days: int) -> None:
    """Record a prune operation."""
    RUNSTORE_PRUNE_TOTAL.inc()
    RUNSTORE_DELETED_COUNT.observe(deleted)
    RUNSTORE_RETENTION_DAYS.observe(retention_days)


def record_runstore_compare(variant_changed: bool) -> None:
    """Record a compare operation."""
    RUNSTORE_COMPARE_TOTAL.labels(
        variant_changed="true" if variant_changed else "false",
    ).inc()


def record_runstore_export(format_type: str) -> None:
    """Record an export operation."""
    RUNSTORE_EXPORT_TOTAL.labels(
        format=format_type,
    ).inc()

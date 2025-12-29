"""
Batch sizing metrics for Prometheus instrumentation (v0.9.0).

Provides:
- Counters for batch requests
- Histograms for batch size and processing time
- Counters for portfolio summary

Label cardinality rules:
- No high-cardinality labels (batch_id excluded)
"""

from prometheus_client import Counter, Histogram


# ============================================
# BATCH SIZING METRICS
# ============================================

BATCH_REQUESTS = Counter(
    "bess_batch_sizing_requests_total",
    "Total batch sizing requests",
)

BATCH_ITEMS_COUNT = Histogram(
    "bess_batch_items_count",
    "Number of items per batch request",
    buckets=(1, 2, 3, 5, 10, 20, 50, 100),
)

BATCH_OK_COUNT = Histogram(
    "bess_batch_ok_count",
    "Number of successful items per batch",
    buckets=(0, 1, 2, 3, 5, 10, 20, 50, 100),
)

BATCH_ERROR_COUNT = Histogram(
    "bess_batch_error_count",
    "Number of failed items per batch",
    buckets=(0, 1, 2, 3, 5, 10, 20),
)

BATCH_PROCESSING_TIME_MS = Histogram(
    "bess_batch_processing_time_ms",
    "Total batch processing time in milliseconds",
    buckets=(10, 50, 100, 200, 500, 1000, 2000, 5000, 10000),
)


# ============================================
# PORTFOLIO SUMMARY METRICS
# ============================================

PORTFOLIO_SUMMARY_REQUESTS = Counter(
    "bess_portfolio_summary_requests_total",
    "Total batch requests with portfolio_summary",
)

PORTFOLIO_OPTIMAL_VARIANT = Counter(
    "bess_portfolio_optimal_variant_total",
    "Count of portfolio optimal variant selections",
    ["variant"],
)

PORTFOLIO_TOTAL_NPV_KPLN = Histogram(
    "bess_portfolio_total_npv_kpln",
    "Portfolio total NPV in thousands PLN",
    buckets=(-1000, -500, -200, -100, -50, 0, 50, 100, 200, 500, 1000),
)

PORTFOLIO_AVG_PAYBACK_YEARS = Histogram(
    "bess_portfolio_avg_payback_years",
    "Portfolio average payback in years",
    buckets=(0, 1, 2, 3, 5, 7, 10, 15, 20, 50, 100),
)


# ============================================
# HELPER FUNCTIONS
# ============================================

def record_batch_request(total_items: int, ok_count: int, error_count: int, processing_time_ms: float):
    """Record batch request metrics."""
    BATCH_REQUESTS.inc()
    BATCH_ITEMS_COUNT.observe(total_items)
    BATCH_OK_COUNT.observe(ok_count)
    BATCH_ERROR_COUNT.observe(error_count)
    BATCH_PROCESSING_TIME_MS.observe(processing_time_ms)


def record_portfolio_summary(
    optimal_variant: str,
    total_npv_pln: float,
    avg_payback_years: float,
):
    """Record portfolio summary metrics."""
    PORTFOLIO_SUMMARY_REQUESTS.inc()
    PORTFOLIO_OPTIMAL_VARIANT.labels(variant=optimal_variant).inc()
    PORTFOLIO_TOTAL_NPV_KPLN.observe(total_npv_pln / 1000.0)  # Convert to kPLN
    PORTFOLIO_AVG_PAYBACK_YEARS.observe(avg_payback_years)

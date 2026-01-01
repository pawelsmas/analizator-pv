"""
Prometheus metrics for portfolio operations (v2.3.0).

Tracks:
- Portfolio summary requests (total, by source)
- Portfolio export requests (CSV, ZIP)
- Items aggregated per request
- Mixed assumptions detection
- Total NPV aggregated

These metrics enable monitoring of portfolio usage patterns
and alerting on anomalies.
"""

from prometheus_client import Counter, Gauge, Histogram


# -----------------------------------------------------------------------------
# Counters - Portfolio Summary Requests
# -----------------------------------------------------------------------------

PORTFOLIO_SUMMARY_REQUESTS_TOTAL = Counter(
    "bess_portfolio_summary_requests_total",
    "Total portfolio summary requests",
    ["source"],  # "api" or "job"
)

PORTFOLIO_SUMMARY_ERRORS_TOTAL = Counter(
    "bess_portfolio_summary_errors_total",
    "Total portfolio summary errors",
    ["source", "error_type"],  # error_type: "validation", "processing", "not_found"
)


# -----------------------------------------------------------------------------
# Counters - Portfolio Exports
# -----------------------------------------------------------------------------

PORTFOLIO_EXPORT_REQUESTS_TOTAL = Counter(
    "bess_portfolio_export_requests_total",
    "Total portfolio export requests",
    ["source", "format"],  # source: "api" or "job", format: "csv" or "zip"
)


# -----------------------------------------------------------------------------
# Counters - Items Aggregation
# -----------------------------------------------------------------------------

PORTFOLIO_ITEMS_TOTAL = Counter(
    "bess_portfolio_items_total",
    "Total items aggregated in portfolio requests",
    ["status"],  # "ok" or "error"
)

PORTFOLIO_MIXED_ASSUMPTIONS_TOTAL = Counter(
    "bess_portfolio_mixed_assumptions_total",
    "Total portfolio requests with mixed assumptions",
    ["source"],
)


# -----------------------------------------------------------------------------
# Histograms - Request Characteristics
# -----------------------------------------------------------------------------

PORTFOLIO_ITEMS_PER_REQUEST = Histogram(
    "bess_portfolio_items_per_request",
    "Number of items per portfolio request",
    buckets=[1, 2, 5, 10, 20, 50, 100],
)

PORTFOLIO_TOTAL_NPV_PLN = Histogram(
    "bess_portfolio_total_npv_pln",
    "Total NPV in PLN per portfolio request",
    buckets=[0, 10000, 50000, 100000, 500000, 1000000, 5000000, 10000000],
)

PORTFOLIO_TOTAL_CAPEX_PLN = Histogram(
    "bess_portfolio_total_capex_pln",
    "Total CAPEX in PLN per portfolio request",
    buckets=[0, 10000, 50000, 100000, 500000, 1000000, 5000000, 10000000],
)


# -----------------------------------------------------------------------------
# Gauges - Last Request State
# -----------------------------------------------------------------------------

PORTFOLIO_LAST_ITEMS_TOTAL = Gauge(
    "bess_portfolio_last_items_total",
    "Total items in last portfolio request",
)

PORTFOLIO_LAST_ITEMS_OK = Gauge(
    "bess_portfolio_last_items_ok",
    "OK items in last portfolio request",
)

PORTFOLIO_LAST_ITEMS_ERROR = Gauge(
    "bess_portfolio_last_items_error",
    "Error items in last portfolio request",
)

PORTFOLIO_LAST_TOTAL_NPV_PLN = Gauge(
    "bess_portfolio_last_total_npv_pln",
    "Total NPV in PLN for last portfolio request",
)


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

def record_portfolio_summary_request(source: str):
    """
    Record a portfolio summary request.

    Args:
        source: Request source ("api" or "job")
    """
    PORTFOLIO_SUMMARY_REQUESTS_TOTAL.labels(source=source).inc()


def record_portfolio_summary_error(source: str, error_type: str):
    """
    Record a portfolio summary error.

    Args:
        source: Request source ("api" or "job")
        error_type: Type of error ("validation", "processing", "not_found")
    """
    PORTFOLIO_SUMMARY_ERRORS_TOTAL.labels(source=source, error_type=error_type).inc()


def record_portfolio_export_request(source: str, format: str):
    """
    Record a portfolio export request.

    Args:
        source: Request source ("api" or "job")
        format: Export format ("csv" or "zip")
    """
    PORTFOLIO_EXPORT_REQUESTS_TOTAL.labels(source=source, format=format).inc()


def record_portfolio_summary_result(
    source: str,
    items_total: int,
    items_ok: int,
    items_error: int,
    total_npv_pln: float,
    total_capex_pln: float,
    mixed_assumptions: bool,
):
    """
    Record portfolio summary result.

    Args:
        source: Request source ("api" or "job")
        items_total: Total items aggregated
        items_ok: Items with status OK
        items_error: Items with errors
        total_npv_pln: Total NPV across items
        total_capex_pln: Total CAPEX across items
        mixed_assumptions: Whether assumptions versions are mixed
    """
    # Record item counts
    PORTFOLIO_ITEMS_TOTAL.labels(status="ok").inc(items_ok)
    PORTFOLIO_ITEMS_TOTAL.labels(status="error").inc(items_error)

    # Record histograms
    PORTFOLIO_ITEMS_PER_REQUEST.observe(items_total)
    PORTFOLIO_TOTAL_NPV_PLN.observe(abs(total_npv_pln))
    PORTFOLIO_TOTAL_CAPEX_PLN.observe(total_capex_pln)

    # Record mixed assumptions
    if mixed_assumptions:
        PORTFOLIO_MIXED_ASSUMPTIONS_TOTAL.labels(source=source).inc()

    # Update gauges
    PORTFOLIO_LAST_ITEMS_TOTAL.set(items_total)
    PORTFOLIO_LAST_ITEMS_OK.set(items_ok)
    PORTFOLIO_LAST_ITEMS_ERROR.set(items_error)
    PORTFOLIO_LAST_TOTAL_NPV_PLN.set(total_npv_pln)

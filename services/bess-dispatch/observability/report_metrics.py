"""
Prometheus metrics for report generation (v2.4.0).

Tracks:
- Report requests by format (PDF, XLSX, ZIP)
- Report profile usage (client vs engineering)
- Report generation duration
- Report size in bytes
- Portfolio report requests
- Report errors by type

These metrics enable monitoring of report generation patterns
and alerting on anomalies.
"""

from prometheus_client import Counter, Gauge, Histogram


# -----------------------------------------------------------------------------
# Counters - Run Report Requests
# -----------------------------------------------------------------------------

REPORT_REQUESTS_TOTAL = Counter(
    "bess_report_requests_total",
    "Total report download requests",
    ["format"],  # "pdf", "xlsx", "zip"
)

REPORT_PROFILE_REQUESTS_TOTAL = Counter(
    "bess_report_profile_requests_total",
    "Total report requests by profile",
    ["profile"],  # "client", "engineering"
)

REPORT_ERRORS_TOTAL = Counter(
    "bess_report_errors_total",
    "Total report generation errors",
    ["format", "error_type"],  # error_type: "not_found", "generation", "validation"
)


# -----------------------------------------------------------------------------
# Counters - Portfolio Report Requests
# -----------------------------------------------------------------------------

PORTFOLIO_REPORT_REQUESTS_TOTAL = Counter(
    "bess_portfolio_report_requests_total",
    "Total portfolio report requests",
)

PORTFOLIO_REPORT_ERRORS_TOTAL = Counter(
    "bess_portfolio_report_errors_total",
    "Total portfolio report errors",
    ["error_type"],  # "validation", "generation", "empty_portfolio"
)


# -----------------------------------------------------------------------------
# Counters - Branding Usage
# -----------------------------------------------------------------------------

REPORT_BRANDING_USAGE_TOTAL = Counter(
    "bess_report_branding_usage_total",
    "Total reports with custom branding fields",
    ["field"],  # "client_name", "site_name", "report_title", "notes"
)


# -----------------------------------------------------------------------------
# Histograms - Report Generation Performance
# -----------------------------------------------------------------------------

REPORT_GENERATION_DURATION_SECONDS = Histogram(
    "bess_report_generation_duration_seconds",
    "Report generation duration in seconds",
    ["format"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

REPORT_SIZE_BYTES = Histogram(
    "bess_report_size_bytes",
    "Report file size in bytes",
    ["format"],
    buckets=[1000, 10000, 50000, 100000, 500000, 1000000, 5000000],
)

PORTFOLIO_REPORT_ITEMS_COUNT = Histogram(
    "bess_portfolio_report_items_count",
    "Number of items in portfolio report",
    buckets=[1, 2, 5, 10, 20, 50, 100],
)


# -----------------------------------------------------------------------------
# Gauges - Last Report State
# -----------------------------------------------------------------------------

REPORT_LAST_GENERATION_TIMESTAMP = Gauge(
    "bess_report_last_generation_timestamp",
    "Timestamp of last report generation",
    ["format"],
)

REPORT_LAST_SIZE_BYTES = Gauge(
    "bess_report_last_size_bytes",
    "Size of last generated report in bytes",
    ["format"],
)


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

def track_report_request(format: str, profile: str = "client"):
    """Track a report request with format and profile."""
    REPORT_REQUESTS_TOTAL.labels(format=format).inc()
    REPORT_PROFILE_REQUESTS_TOTAL.labels(profile=profile).inc()


def track_report_error(format: str, error_type: str):
    """Track a report generation error."""
    REPORT_ERRORS_TOTAL.labels(format=format, error_type=error_type).inc()


def track_report_branding(client_name: str = None, site_name: str = None,
                          report_title: str = None, notes: str = None):
    """Track branding field usage."""
    if client_name:
        REPORT_BRANDING_USAGE_TOTAL.labels(field="client_name").inc()
    if site_name:
        REPORT_BRANDING_USAGE_TOTAL.labels(field="site_name").inc()
    if report_title:
        REPORT_BRANDING_USAGE_TOTAL.labels(field="report_title").inc()
    if notes:
        REPORT_BRANDING_USAGE_TOTAL.labels(field="notes").inc()


def track_report_generation(format: str, duration_seconds: float, size_bytes: int):
    """Track report generation metrics."""
    import time
    REPORT_GENERATION_DURATION_SECONDS.labels(format=format).observe(duration_seconds)
    REPORT_SIZE_BYTES.labels(format=format).observe(size_bytes)
    REPORT_LAST_GENERATION_TIMESTAMP.labels(format=format).set(time.time())
    REPORT_LAST_SIZE_BYTES.labels(format=format).set(size_bytes)


def track_portfolio_report_request(items_count: int):
    """Track a portfolio report request."""
    PORTFOLIO_REPORT_REQUESTS_TOTAL.inc()
    PORTFOLIO_REPORT_ITEMS_COUNT.observe(items_count)


def track_portfolio_report_error(error_type: str):
    """Track a portfolio report error."""
    PORTFOLIO_REPORT_ERRORS_TOTAL.labels(error_type=error_type).inc()

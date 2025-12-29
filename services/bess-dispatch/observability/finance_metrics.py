"""
Finance metrics for Prometheus instrumentation (v0.5.0).

Provides:
- bess_finance_cashflow_requests_total: Counter for cashflow timeseries requests
- bess_finance_sensitivity_requests_total: Counter for discount rate sensitivity requests
- bess_finance_sensitivity_points: Histogram for number of sensitivity points
- bess_finance_npv_pln: Histogram for NPV distribution

Label cardinality rules:
- mode: stacked, pv_surplus, peak_shaving, load_only
- horizon_years: 10, 15, 20, etc.
"""

from prometheus_client import Counter, Histogram

SERVICE_NAME = "bess-dispatch"

# Cashflow timeseries requests
FINANCE_CASHFLOW_REQUESTS = Counter(
    "bess_finance_cashflow_requests_total",
    "Total requests that include cashflow_timeseries",
    ["mode", "horizon_years"],
)

# Discount rate sensitivity requests
FINANCE_SENSITIVITY_REQUESTS = Counter(
    "bess_finance_sensitivity_requests_total",
    "Total requests that include discount_rate_sensitivity",
    ["mode"],
)

# Number of sensitivity points per request (useful for cardinality analysis)
FINANCE_SENSITIVITY_POINTS = Histogram(
    "bess_finance_sensitivity_points",
    "Number of discount rate sensitivity points per request",
    ["mode"],
    buckets=[1, 2, 3, 5, 7, 10, 15, 20],
)

# NPV distribution (in thousands PLN for better bucket resolution)
FINANCE_NPV_KPLN = Histogram(
    "bess_finance_npv_kpln",
    "NPV distribution in thousands PLN",
    ["mode", "variant"],
    buckets=[-500, -200, -100, -50, -20, -10, 0, 10, 20, 50, 100, 200, 500, 1000],
)

# IRR distribution (percentage)
FINANCE_IRR_PCT = Histogram(
    "bess_finance_irr_pct",
    "IRR distribution in percent",
    ["mode", "variant"],
    buckets=[-20, -10, -5, 0, 5, 10, 15, 20, 25, 30, 40, 50],
)


def record_finance_cashflow_metrics(mode: str, horizon_years: int) -> None:
    """Record metrics for cashflow timeseries request."""
    FINANCE_CASHFLOW_REQUESTS.labels(
        mode=mode,
        horizon_years=str(horizon_years),
    ).inc()


def record_finance_sensitivity_metrics(mode: str, num_points: int) -> None:
    """Record metrics for discount rate sensitivity request."""
    FINANCE_SENSITIVITY_REQUESTS.labels(mode=mode).inc()
    FINANCE_SENSITIVITY_POINTS.labels(mode=mode).observe(num_points)


def record_finance_npv_metrics(mode: str, variant: str, npv_pln: float) -> None:
    """Record NPV metric for a variant."""
    npv_kpln = npv_pln / 1000.0  # Convert to thousands
    FINANCE_NPV_KPLN.labels(mode=mode, variant=variant).observe(npv_kpln)


def record_finance_irr_metrics(mode: str, variant: str, irr_pct: float) -> None:
    """Record IRR metric for a variant."""
    if irr_pct is not None:
        FINANCE_IRR_PCT.labels(mode=mode, variant=variant).observe(irr_pct)

"""
Finance metrics for Prometheus instrumentation (v0.5.0, v0.6.0).

Provides:
- bess_finance_cashflow_requests_total: Counter for cashflow timeseries requests
- bess_finance_sensitivity_requests_total: Counter for discount rate sensitivity requests
- bess_finance_sensitivity_points: Histogram for number of sensitivity points
- bess_finance_npv_pln: Histogram for NPV distribution
- bess_finance_replacement_requests_total: Counter for battery replacement config (v0.6.0)
- bess_finance_degradation_requests_total: Counter for degradation config (v0.6.0)
- bess_finance_energy_price_sensitivity_total: Counter for energy price sweeps (v0.6.0)
- bess_finance_capex_sensitivity_total: Counter for CAPEX sweeps (v0.6.0)

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


# =============================================================================
# v0.6.0 Lifecycle Metrics
# =============================================================================

# Battery replacement requests
FINANCE_REPLACEMENT_REQUESTS = Counter(
    "bess_finance_replacement_requests_total",
    "Total requests that include battery replacement configuration",
    ["mode", "replacement_year"],
)

# Degradation requests (BESS or PV)
FINANCE_DEGRADATION_REQUESTS = Counter(
    "bess_finance_degradation_requests_total",
    "Total requests that include performance degradation configuration",
    ["mode", "degradation_type"],  # bess, pv, both
)

# Energy price sensitivity requests
FINANCE_ENERGY_PRICE_SENSITIVITY = Counter(
    "bess_finance_energy_price_sensitivity_total",
    "Total requests that include energy price sensitivity sweep",
    ["mode"],
)

# CAPEX sensitivity requests
FINANCE_CAPEX_SENSITIVITY = Counter(
    "bess_finance_capex_sensitivity_total",
    "Total requests that include CAPEX sensitivity sweep",
    ["mode"],
)

# Replacement year distribution (histogram)
FINANCE_REPLACEMENT_YEAR = Histogram(
    "bess_finance_replacement_year",
    "Battery replacement year distribution",
    ["mode"],
    buckets=[5, 7, 8, 9, 10, 11, 12, 15, 20],
)

# Degradation rate histograms
FINANCE_BESS_DEGRADATION_RATE = Histogram(
    "bess_finance_bess_degradation_rate_pct",
    "BESS capacity degradation rate distribution [%/year]",
    ["mode"],
    buckets=[0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0],
)

FINANCE_PV_DEGRADATION_RATE = Histogram(
    "bess_finance_pv_degradation_rate_pct",
    "PV output degradation rate distribution [%/year]",
    ["mode"],
    buckets=[0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0],
)


def record_replacement_metrics(mode: str, replacement_year: int) -> None:
    """Record metrics for battery replacement configuration."""
    FINANCE_REPLACEMENT_REQUESTS.labels(
        mode=mode,
        replacement_year=str(replacement_year),
    ).inc()
    FINANCE_REPLACEMENT_YEAR.labels(mode=mode).observe(replacement_year)


def record_degradation_metrics(
    mode: str,
    bess_degradation_pct: float,
    pv_degradation_pct: float,
) -> None:
    """Record metrics for performance degradation configuration."""
    # Determine degradation type
    has_bess = bess_degradation_pct > 0
    has_pv = pv_degradation_pct > 0

    if has_bess and has_pv:
        degradation_type = "both"
    elif has_bess:
        degradation_type = "bess"
    elif has_pv:
        degradation_type = "pv"
    else:
        return  # No degradation configured, skip

    FINANCE_DEGRADATION_REQUESTS.labels(
        mode=mode,
        degradation_type=degradation_type,
    ).inc()

    if has_bess:
        FINANCE_BESS_DEGRADATION_RATE.labels(mode=mode).observe(bess_degradation_pct)
    if has_pv:
        FINANCE_PV_DEGRADATION_RATE.labels(mode=mode).observe(pv_degradation_pct)


def record_energy_price_sensitivity_metrics(mode: str, num_points: int) -> None:
    """Record metrics for energy price sensitivity sweep."""
    FINANCE_ENERGY_PRICE_SENSITIVITY.labels(mode=mode).inc()


def record_capex_sensitivity_metrics(mode: str, num_points: int) -> None:
    """Record metrics for CAPEX sensitivity sweep."""
    FINANCE_CAPEX_SENSITIVITY.labels(mode=mode).inc()

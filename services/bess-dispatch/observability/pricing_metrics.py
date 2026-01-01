"""
Prometheus metrics for Pricing Engine (v2.0.0).

Tracks:
- Price timeseries requests (with/without flag)
- Pricing mode distribution (generated vs override)
- Ledger timeseries requests
- Cost bucket distributions
"""

from prometheus_client import Counter, Histogram


# -----------------------------------------------------------------------------
# Counters - Pricing Requests
# -----------------------------------------------------------------------------

PRICING_REQUESTS_TOTAL = Counter(
    "bess_pricing_requests_total",
    "Total sizing requests with pricing tracking",
    ["include_price_timeseries", "include_ledger_timeseries"],
)

PRICING_MODE_TOTAL = Counter(
    "bess_pricing_mode_total",
    "Pricing mode distribution",
    ["mode"],  # "generated" or "override"
)

PRICE_OVERRIDE_REQUESTS_TOTAL = Counter(
    "bess_price_override_requests_total",
    "Total requests using price_timeseries_override",
)


# -----------------------------------------------------------------------------
# Histograms - Price Values
# -----------------------------------------------------------------------------

PRICE_IMPORT_PLN_MWH = Histogram(
    "bess_price_import_pln_mwh",
    "Average import price per request [PLN/MWh]",
    buckets=[0, 200, 400, 600, 800, 1000, 1200, 1500, 2000, 3000],
)

PRICE_EXPORT_PLN_MWH = Histogram(
    "bess_price_export_pln_mwh",
    "Average export price per request [PLN/MWh]",
    buckets=[0, 100, 200, 300, 400, 500, 600, 800, 1000],
)


# -----------------------------------------------------------------------------
# Histograms - Ledger Costs
# -----------------------------------------------------------------------------

LEDGER_IMPORT_COST_PLN = Histogram(
    "bess_ledger_import_cost_pln",
    "Total import cost from ledger timeseries [PLN]",
    buckets=[0, 10, 50, 100, 500, 1000, 5000, 10000, 50000],
)

LEDGER_EXPORT_REVENUE_PLN = Histogram(
    "bess_ledger_export_revenue_pln",
    "Total export revenue from ledger timeseries [PLN]",
    buckets=[0, 10, 50, 100, 500, 1000, 5000, 10000, 50000],
)

LEDGER_NET_COST_PLN = Histogram(
    "bess_ledger_net_cost_pln",
    "Total net cost from ledger timeseries [PLN]",
    buckets=[-10000, -5000, -1000, -500, -100, 0, 100, 500, 1000, 5000, 10000],
)


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

def record_pricing_request(
    include_price_timeseries: bool,
    include_ledger_timeseries: bool,
) -> None:
    """
    Record a sizing request with pricing flags.

    Args:
        include_price_timeseries: Whether price_timeseries was requested
        include_ledger_timeseries: Whether ledger_timeseries was requested
    """
    PRICING_REQUESTS_TOTAL.labels(
        include_price_timeseries="true" if include_price_timeseries else "false",
        include_ledger_timeseries="true" if include_ledger_timeseries else "false",
    ).inc()


def record_pricing_mode(mode: str) -> None:
    """
    Record the pricing mode used.

    Args:
        mode: "generated" or "override"
    """
    PRICING_MODE_TOTAL.labels(mode=mode).inc()


def record_price_override_request() -> None:
    """Record that price_timeseries_override was used."""
    PRICE_OVERRIDE_REQUESTS_TOTAL.inc()


def record_price_values(avg_import_pln_mwh: float, avg_export_pln_mwh: float) -> None:
    """
    Record average price values for the request.

    Args:
        avg_import_pln_mwh: Average import price [PLN/MWh]
        avg_export_pln_mwh: Average export price [PLN/MWh]
    """
    PRICE_IMPORT_PLN_MWH.observe(avg_import_pln_mwh)
    PRICE_EXPORT_PLN_MWH.observe(avg_export_pln_mwh)


def record_ledger_costs(
    import_cost_pln: float,
    export_revenue_pln: float,
    net_cost_pln: float,
) -> None:
    """
    Record ledger cost totals.

    Args:
        import_cost_pln: Total import cost [PLN]
        export_revenue_pln: Total export revenue [PLN]
        net_cost_pln: Total net cost [PLN]
    """
    LEDGER_IMPORT_COST_PLN.observe(import_cost_pln)
    LEDGER_EXPORT_REVENUE_PLN.observe(export_revenue_pln)
    LEDGER_NET_COST_PLN.observe(net_cost_pln)

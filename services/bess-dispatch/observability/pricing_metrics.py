"""
Prometheus metrics for Pricing Engine (v2.0.0 + v2.1.0).

Tracks:
- Price timeseries requests (with/without flag)
- Pricing mode distribution (generated vs override vs preset vs schedule)
- Ledger timeseries requests
- Cost bucket distributions
- v2.1.0: Tariff presets usage, pricing preview requests, schedule usage
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


# =============================================================================
# v2.1.0: Tariff Presets + Pricing Preview Metrics
# =============================================================================

# -----------------------------------------------------------------------------
# Counters - Tariff & Preview Requests
# -----------------------------------------------------------------------------

TARIFF_PRESETS_LIST_TOTAL = Counter(
    "bess_tariff_presets_list_total",
    "Total GET /tariffs requests",
)

PRICING_PREVIEW_REQUESTS_TOTAL = Counter(
    "bess_pricing_preview_requests_total",
    "Total POST /pricing/preview requests",
    ["pricing_mode"],  # "generated", "preset", "schedule", "override"
)

TARIFF_PRESET_USAGE_TOTAL = Counter(
    "bess_tariff_preset_usage_total",
    "Tariff preset usage by preset ID",
    ["preset_id"],  # e.g., "pl_flat_2026", "pl_tou_simple_2026"
)

TARIFF_SCHEDULE_USAGE_TOTAL = Counter(
    "bess_tariff_schedule_usage_total",
    "Custom tariff schedule usage",
    ["has_holidays"],  # "true" or "false"
)


# -----------------------------------------------------------------------------
# Histograms - Preview Response Metrics
# -----------------------------------------------------------------------------

PRICING_PREVIEW_STEPS = Histogram(
    "bess_pricing_preview_steps",
    "Number of steps in pricing preview response",
    buckets=[24, 48, 96, 168, 336, 672, 744, 1440, 2880, 8760],
)

PRICING_PREVIEW_DURATION_SECONDS = Histogram(
    "bess_pricing_preview_duration_seconds",
    "Pricing preview request duration [seconds]",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
)


# -----------------------------------------------------------------------------
# Gauges - Price Anomaly Detection
# -----------------------------------------------------------------------------

PRICE_ANOMALY_DETECTED = Counter(
    "bess_price_anomaly_detected_total",
    "Price anomaly detections",
    ["anomaly_type"],  # "zero_import", "negative_price", "extreme_variance"
)


# -----------------------------------------------------------------------------
# Helper Functions - v2.1.0
# -----------------------------------------------------------------------------

def record_tariff_presets_list() -> None:
    """Record a GET /tariffs request."""
    TARIFF_PRESETS_LIST_TOTAL.inc()


def record_pricing_preview(pricing_mode: str) -> None:
    """
    Record a POST /pricing/preview request.

    Args:
        pricing_mode: "generated", "preset", "schedule", or "override"
    """
    PRICING_PREVIEW_REQUESTS_TOTAL.labels(pricing_mode=pricing_mode).inc()


def record_tariff_preset_usage(preset_id: str) -> None:
    """
    Record usage of a specific tariff preset.

    Args:
        preset_id: The preset ID (e.g., "pl_flat_2026")
    """
    TARIFF_PRESET_USAGE_TOTAL.labels(preset_id=preset_id).inc()


def record_tariff_schedule_usage(has_holidays: bool) -> None:
    """
    Record usage of a custom tariff schedule.

    Args:
        has_holidays: Whether the schedule includes holiday dates
    """
    TARIFF_SCHEDULE_USAGE_TOTAL.labels(
        has_holidays="true" if has_holidays else "false"
    ).inc()


def record_pricing_preview_steps(n_steps: int) -> None:
    """
    Record the number of steps in a pricing preview response.

    Args:
        n_steps: Number of timesteps in the response
    """
    PRICING_PREVIEW_STEPS.observe(n_steps)


def record_pricing_preview_duration(duration_seconds: float) -> None:
    """
    Record the duration of a pricing preview request.

    Args:
        duration_seconds: Request duration in seconds
    """
    PRICING_PREVIEW_DURATION_SECONDS.observe(duration_seconds)


def record_price_anomaly(anomaly_type: str) -> None:
    """
    Record a detected price anomaly.

    Args:
        anomaly_type: Type of anomaly detected:
            - "zero_import": All import prices are zero
            - "negative_price": Negative prices detected
            - "extreme_variance": Price variance exceeds threshold
    """
    PRICE_ANOMALY_DETECTED.labels(anomaly_type=anomaly_type).inc()


def check_price_anomalies(import_prices: list) -> list:
    """
    Check for price anomalies and record any found.

    Args:
        import_prices: List of import prices

    Returns:
        List of detected anomaly types
    """
    anomalies = []

    if not import_prices:
        return anomalies

    # Check for all-zero prices
    if all(p == 0 for p in import_prices):
        record_price_anomaly("zero_import")
        anomalies.append("zero_import")

    # Check for negative prices
    if any(p < 0 for p in import_prices):
        record_price_anomaly("negative_price")
        anomalies.append("negative_price")

    # Check for extreme variance (coefficient of variation > 100%)
    if len(import_prices) > 1:
        avg = sum(import_prices) / len(import_prices)
        if avg > 0:
            variance = sum((p - avg) ** 2 for p in import_prices) / len(import_prices)
            std_dev = variance ** 0.5
            cv = std_dev / avg
            if cv > 1.0:  # CV > 100%
                record_price_anomaly("extreme_variance")
                anomalies.append("extreme_variance")

    return anomalies

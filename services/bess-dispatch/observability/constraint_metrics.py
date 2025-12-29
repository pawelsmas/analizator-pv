"""
Grid constraint metrics for Prometheus instrumentation (v0.7.0).

Provides:
- Counters for requests with grid constraints
- Histograms for constraint impact (curtailed kWh, unserved kWh)
- Counters for constraint violations

Label cardinality rules:
- mode: Dispatch mode (stacked, pv_surplus, peak_shaving, load_only)
- constraint_type: export_cap, import_cap, no_export
"""

from prometheus_client import Counter, Histogram


# Counters
GRID_CONSTRAINT_REQUESTS = Counter(
    "bess_grid_constraint_requests_total",
    "Total sizing requests with grid constraints",
    ["mode"],
)

EXPORT_CAP_HIT = Counter(
    "bess_export_cap_hit_total",
    "Total requests where export cap was hit",
    ["mode"],
)

IMPORT_CAP_HIT = Counter(
    "bess_import_cap_hit_total",
    "Total requests where import cap was hit",
    ["mode"],
)

UNSERVED_LOAD_OCCURRED = Counter(
    "bess_unserved_load_occurred_total",
    "Total requests with unserved load (import cap exceeded)",
    ["mode"],
)

# Histograms
EXPORT_CAP_CURTAILED_KWH = Histogram(
    "bess_export_cap_curtailed_kwh",
    "Energy curtailed due to export cap [kWh]",
    ["mode"],
    buckets=(0, 10, 50, 100, 500, 1000, 5000, 10000, 50000),
)

UNSERVED_LOAD_KWH = Histogram(
    "bess_unserved_load_kwh",
    "Unserved load due to import cap [kWh]",
    ["mode"],
    buckets=(0, 1, 5, 10, 50, 100, 500, 1000, 5000),
)

UNSERVED_LOAD_PENALTY_PLN = Histogram(
    "bess_unserved_load_penalty_pln",
    "Unserved load penalty [PLN]",
    ["mode"],
    buckets=(0, 10, 50, 100, 500, 1000, 5000, 10000, 50000),
)

EXPORT_CAP_HIT_STEPS = Histogram(
    "bess_export_cap_hit_steps",
    "Number of time steps where export cap was hit",
    ["mode"],
    buckets=(0, 10, 50, 100, 500, 1000, 2000, 4000, 8760),
)

IMPORT_CAP_HIT_STEPS = Histogram(
    "bess_import_cap_hit_steps",
    "Number of time steps where import cap was hit",
    ["mode"],
    buckets=(0, 10, 50, 100, 500, 1000, 2000, 4000, 8760),
)


def record_grid_constraint_request(mode: str):
    """Record that a request with grid constraints was processed."""
    GRID_CONSTRAINT_REQUESTS.labels(mode=mode).inc()


def record_export_cap_metrics(
    mode: str,
    hit_steps: int,
    curtailed_kwh: float,
):
    """Record export cap metrics."""
    if hit_steps > 0:
        EXPORT_CAP_HIT.labels(mode=mode).inc()
        EXPORT_CAP_HIT_STEPS.labels(mode=mode).observe(hit_steps)
        EXPORT_CAP_CURTAILED_KWH.labels(mode=mode).observe(curtailed_kwh)


def record_import_cap_metrics(
    mode: str,
    hit_steps: int,
    unserved_kwh: float,
    penalty_pln: float,
):
    """Record import cap and unserved load metrics."""
    if hit_steps > 0:
        IMPORT_CAP_HIT.labels(mode=mode).inc()
        IMPORT_CAP_HIT_STEPS.labels(mode=mode).observe(hit_steps)

    if unserved_kwh > 0:
        UNSERVED_LOAD_OCCURRED.labels(mode=mode).inc()
        UNSERVED_LOAD_KWH.labels(mode=mode).observe(unserved_kwh)
        UNSERVED_LOAD_PENALTY_PLN.labels(mode=mode).observe(penalty_pln)

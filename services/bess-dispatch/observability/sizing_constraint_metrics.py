"""
Sizing constraint and Pareto metrics for Prometheus instrumentation (v0.8.0).

Provides:
- Counters for sizing constraint requests
- Histograms for constraint feasibility
- Counters for Pareto frontier analysis

Label cardinality rules:
- mode: Dispatch mode (stacked, pv_surplus, peak_shaving, load_only)
- feasibility: feasible, infeasible
"""

from prometheus_client import Counter, Histogram, Gauge


# ============================================
# SIZING CONSTRAINTS METRICS
# ============================================

SIZING_CONSTRAINTS_REQUESTS = Counter(
    "bess_sizing_constraints_requests_total",
    "Total sizing requests with constraints_config",
    ["mode"],
)

SIZING_CONSTRAINTS_FEASIBLE = Counter(
    "bess_sizing_constraints_feasible_total",
    "Total requests with at least one feasible variant",
    ["mode"],
)

SIZING_CONSTRAINTS_NONE_FEASIBLE = Counter(
    "bess_sizing_constraints_none_feasible_total",
    "Total requests where no variant is feasible",
    ["mode"],
)

SIZING_FEASIBLE_VARIANTS_COUNT = Histogram(
    "bess_sizing_feasible_variants_count",
    "Number of feasible variants per request",
    ["mode"],
    buckets=(0, 1, 2, 3, 4, 5, 10, 20),
)

# Constraint type counters
SIZING_CONSTRAINT_MAX_CAPEX = Counter(
    "bess_sizing_constraint_max_capex_total",
    "Total requests with max_capex constraint",
    ["mode"],
)

SIZING_CONSTRAINT_MAX_PAYBACK = Counter(
    "bess_sizing_constraint_max_payback_total",
    "Total requests with max_payback constraint",
    ["mode"],
)

SIZING_CONSTRAINT_MIN_NPV = Counter(
    "bess_sizing_constraint_min_npv_total",
    "Total requests with min_npv constraint",
    ["mode"],
)


# ============================================
# PARETO FRONTIER METRICS
# ============================================

PARETO_FRONTIER_REQUESTS = Counter(
    "bess_pareto_frontier_requests_total",
    "Total sizing requests with Pareto frontier calculated",
    ["mode"],
)

PARETO_FRONTIER_SIZE = Histogram(
    "bess_pareto_frontier_size",
    "Number of non-dominated variants on Pareto frontier",
    ["mode"],
    buckets=(0, 1, 2, 3, 4, 5),
)

PARETO_DOMINATED_COUNT = Histogram(
    "bess_pareto_dominated_count",
    "Number of dominated variants",
    ["mode"],
    buckets=(0, 1, 2, 3, 4, 5),
)


# ============================================
# HELPER FUNCTIONS
# ============================================

def record_sizing_constraints_request(
    mode: str,
    has_max_capex: bool = False,
    has_max_payback: bool = False,
    has_min_npv: bool = False,
):
    """Record that a sizing request with constraints_config was processed."""
    SIZING_CONSTRAINTS_REQUESTS.labels(mode=mode).inc()

    if has_max_capex:
        SIZING_CONSTRAINT_MAX_CAPEX.labels(mode=mode).inc()
    if has_max_payback:
        SIZING_CONSTRAINT_MAX_PAYBACK.labels(mode=mode).inc()
    if has_min_npv:
        SIZING_CONSTRAINT_MIN_NPV.labels(mode=mode).inc()


def record_sizing_feasibility(
    mode: str,
    feasible_count: int,
    total_variants: int,
):
    """Record feasibility results from constraints_report."""
    SIZING_FEASIBLE_VARIANTS_COUNT.labels(mode=mode).observe(feasible_count)

    if feasible_count > 0:
        SIZING_CONSTRAINTS_FEASIBLE.labels(mode=mode).inc()
    else:
        SIZING_CONSTRAINTS_NONE_FEASIBLE.labels(mode=mode).inc()


def record_pareto_frontier(
    mode: str,
    frontier_size: int,
    dominated_count: int,
):
    """Record Pareto frontier metrics."""
    PARETO_FRONTIER_REQUESTS.labels(mode=mode).inc()
    PARETO_FRONTIER_SIZE.labels(mode=mode).observe(frontier_size)
    PARETO_DOMINATED_COUNT.labels(mode=mode).observe(dominated_count)

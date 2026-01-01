"""
Prometheus metrics for dispatch trace and cycle accounting (v2.2.0).

Tracks:
- Dispatch invariant checks (SOC bounds, power limits, no-simultaneous)
- Cycle accounting (EFC, daily cycles, cycle limit enforcement)
- Battery trace requests and generation
- Dispatch invariant violations

These metrics enable monitoring of dispatch correctness
and alerting on invariant/cycle limit violations.
"""

from prometheus_client import Counter, Gauge, Histogram


# -----------------------------------------------------------------------------
# Counters - Battery Trace Requests
# -----------------------------------------------------------------------------

BATTERY_TRACE_REQUESTS_TOTAL = Counter(
    "bess_battery_trace_requests_total",
    "Total requests with include_battery_trace=true",
)

BATTERY_TRACE_GENERATED_TOTAL = Counter(
    "bess_battery_trace_generated_total",
    "Total battery traces successfully generated",
)


# -----------------------------------------------------------------------------
# Counters - Dispatch Invariant Checks
# -----------------------------------------------------------------------------

DISPATCH_INVARIANT_CHECKS_TOTAL = Counter(
    "bess_dispatch_invariant_checks_total",
    "Total dispatch invariant checks performed",
    ["check_type"],  # soc_bounds, power_limits, no_simultaneous, energy_balance
)

DISPATCH_INVARIANT_PASSED_TOTAL = Counter(
    "bess_dispatch_invariant_passed_total",
    "Total dispatch invariant checks that passed",
    ["check_type"],
)

DISPATCH_INVARIANT_FAILED_TOTAL = Counter(
    "bess_dispatch_invariant_failed_total",
    "Total dispatch invariant checks that failed",
    ["check_type"],
)

DISPATCH_INVARIANT_ALL_OK_TOTAL = Counter(
    "bess_dispatch_invariant_all_ok_total",
    "Total dispatch runs where all invariants passed",
)

DISPATCH_INVARIANT_VIOLATIONS_TOTAL = Counter(
    "bess_dispatch_invariant_violations_total",
    "Total dispatch invariant violations detected",
    ["invariant_type"],  # soc_min, soc_max, power_charge, power_discharge, simultaneous
)


# -----------------------------------------------------------------------------
# Counters - Cycle Limit Enforcement
# -----------------------------------------------------------------------------

CYCLE_LIMIT_REQUESTS_TOTAL = Counter(
    "bess_cycle_limit_requests_total",
    "Total requests with max_cycles_per_day specified",
)

CYCLE_LIMIT_CLAMP_EVENTS_TOTAL = Counter(
    "bess_cycle_limit_clamp_events_total",
    "Total timesteps where discharge was clamped due to cycle limit",
)

CYCLE_LIMIT_DAYS_EXCEEDED_TOTAL = Counter(
    "bess_cycle_limit_days_exceeded_total",
    "Total days where cycle limit was exceeded (before clamping)",
)


# -----------------------------------------------------------------------------
# Gauges - Cycle Accounting
# -----------------------------------------------------------------------------

CYCLE_EFC_TOTAL = Gauge(
    "bess_cycle_efc_total",
    "Total Equivalent Full Cycles in current dispatch",
)

CYCLE_DAILY_MAX = Gauge(
    "bess_cycle_daily_max_efc",
    "Maximum daily EFC in current dispatch",
)

CYCLE_DAILY_AVG = Gauge(
    "bess_cycle_daily_avg_efc",
    "Average daily EFC in current dispatch",
)

CYCLE_THROUGHPUT_MWH = Gauge(
    "bess_cycle_throughput_mwh",
    "Total battery throughput in current dispatch (MWh)",
)


# -----------------------------------------------------------------------------
# Histograms - Dispatch Invariant Magnitudes
# -----------------------------------------------------------------------------

DISPATCH_SOC_MIN_VIOLATION_KWH = Histogram(
    "bess_dispatch_soc_min_violation_kwh",
    "Magnitude of SOC below zero violations (kWh)",
    buckets=[0.0, 0.1, 1.0, 5.0, 10.0, 50.0, 100.0],
)

DISPATCH_SOC_MAX_VIOLATION_KWH = Histogram(
    "bess_dispatch_soc_max_violation_kwh",
    "Magnitude of SOC above capacity violations (kWh)",
    buckets=[0.0, 0.1, 1.0, 5.0, 10.0, 50.0, 100.0],
)

DISPATCH_POWER_VIOLATION_KW = Histogram(
    "bess_dispatch_power_violation_kw",
    "Magnitude of power limit violations (kW)",
    buckets=[0.0, 0.1, 1.0, 5.0, 10.0, 50.0, 100.0],
)


# -----------------------------------------------------------------------------
# Histograms - Cycle Accounting
# -----------------------------------------------------------------------------

CYCLE_EFC_PER_DAY_HISTOGRAM = Histogram(
    "bess_cycle_efc_per_day",
    "Distribution of daily EFC values",
    buckets=[0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0],
)

CYCLE_EFC_TOTAL_HISTOGRAM = Histogram(
    "bess_cycle_efc_total_histogram",
    "Distribution of total EFC per dispatch",
    buckets=[0.0, 10.0, 50.0, 100.0, 200.0, 365.0, 500.0, 730.0, 1000.0],
)


# -----------------------------------------------------------------------------
# Helper Functions - Battery Trace
# -----------------------------------------------------------------------------

def record_battery_trace_request():
    """Record a request with include_battery_trace=true."""
    BATTERY_TRACE_REQUESTS_TOTAL.inc()


def record_battery_trace_generated():
    """Record a battery trace successfully generated."""
    BATTERY_TRACE_GENERATED_TOTAL.inc()


# -----------------------------------------------------------------------------
# Helper Functions - Dispatch Invariants
# -----------------------------------------------------------------------------

def record_dispatch_invariant_check(check_type: str, passed: bool):
    """
    Record a dispatch invariant check result.

    Args:
        check_type: Type of check (soc_bounds, power_limits, no_simultaneous, energy_balance)
        passed: Whether the check passed
    """
    DISPATCH_INVARIANT_CHECKS_TOTAL.labels(check_type=check_type).inc()

    if passed:
        DISPATCH_INVARIANT_PASSED_TOTAL.labels(check_type=check_type).inc()
    else:
        DISPATCH_INVARIANT_FAILED_TOTAL.labels(check_type=check_type).inc()


def record_dispatch_invariant_result(result: dict):
    """
    Record dispatch invariant results from InvariantCheckResult.to_dict().

    Args:
        result: Dict with check results from InvariantCheckResult.to_dict()
    """
    all_ok = result.get("all_ok", True)

    if all_ok:
        DISPATCH_INVARIANT_ALL_OK_TOTAL.inc()

    # Record individual checks
    record_dispatch_invariant_check("soc_bounds", result.get("soc_bounds_ok", True))
    record_dispatch_invariant_check("power_limits", result.get("power_limits_ok", True))
    record_dispatch_invariant_check("no_simultaneous", result.get("no_simultaneous_ok", True))
    record_dispatch_invariant_check("energy_balance", result.get("energy_balance_ok", True))

    # Record violations by type
    violations = result.get("violations", [])
    for v in violations:
        invariant_type = v.get("invariant", "unknown")
        DISPATCH_INVARIANT_VIOLATIONS_TOTAL.labels(invariant_type=invariant_type).inc()


def record_dispatch_invariant_violation(invariant_type: str, magnitude: float):
    """
    Record a dispatch invariant violation with magnitude.

    Args:
        invariant_type: Type of violation (soc_min, soc_max, power_charge, power_discharge)
        magnitude: Magnitude of the violation
    """
    DISPATCH_INVARIANT_VIOLATIONS_TOTAL.labels(invariant_type=invariant_type).inc()

    if invariant_type == "soc_min":
        DISPATCH_SOC_MIN_VIOLATION_KWH.observe(abs(magnitude))
    elif invariant_type == "soc_max":
        DISPATCH_SOC_MAX_VIOLATION_KWH.observe(abs(magnitude))
    elif invariant_type in ("power_charge", "power_discharge"):
        DISPATCH_POWER_VIOLATION_KW.observe(abs(magnitude))


# -----------------------------------------------------------------------------
# Helper Functions - Cycle Accounting
# -----------------------------------------------------------------------------

def record_cycle_limit_request():
    """Record a request with max_cycles_per_day specified."""
    CYCLE_LIMIT_REQUESTS_TOTAL.inc()


def record_cycle_limit_clamp():
    """Record a timestep where discharge was clamped due to cycle limit."""
    CYCLE_LIMIT_CLAMP_EVENTS_TOTAL.inc()


def record_cycle_limit_day_exceeded():
    """Record a day where cycle limit was exceeded."""
    CYCLE_LIMIT_DAYS_EXCEEDED_TOTAL.inc()


def record_cycle_summary(summary: dict):
    """
    Record cycle accounting summary.

    Args:
        summary: CycleSummary as dict with efc_total, cycles_per_day, etc.
    """
    # Update gauges
    efc_total = summary.get("efc_total", 0.0)
    CYCLE_EFC_TOTAL.set(efc_total)
    CYCLE_EFC_TOTAL_HISTOGRAM.observe(efc_total)

    max_daily = summary.get("max_daily_efc", 0.0)
    CYCLE_DAILY_MAX.set(max_daily)

    avg_daily = summary.get("avg_daily_efc", 0.0)
    CYCLE_DAILY_AVG.set(avg_daily)

    throughput_kwh = summary.get("total_throughput_kwh", 0.0)
    CYCLE_THROUGHPUT_MWH.set(throughput_kwh / 1000.0)

    # Record per-day histogram
    cycles_per_day = summary.get("cycles_per_day", [])
    for daily_efc in cycles_per_day:
        CYCLE_EFC_PER_DAY_HISTOGRAM.observe(daily_efc)

    # Record days exceeding limit
    days_exceeded = summary.get("days_exceeding_limit", 0)
    for _ in range(days_exceeded):
        record_cycle_limit_day_exceeded()

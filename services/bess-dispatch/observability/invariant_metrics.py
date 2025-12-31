"""
Prometheus metrics for invariant checks (v1.6.0).

Tracks:
- Invariant check results (passed/failed per check type)
- Invariant violation details (max error values)
- STRICT_INVARIANTS mode failures

These metrics enable monitoring of calculation correctness
and alerting on invariant violations.
"""

from prometheus_client import Counter, Gauge, Histogram


# -----------------------------------------------------------------------------
# Counters - Invariant Checks
# -----------------------------------------------------------------------------

INVARIANT_CHECKS_TOTAL = Counter(
    "bess_invariant_checks_total",
    "Total invariant checks performed",
    ["check_type"],  # energy_balance, non_negative, cost_sums, annualization
)

INVARIANT_PASSED_TOTAL = Counter(
    "bess_invariant_passed_total",
    "Total invariant checks that passed",
    ["check_type"],
)

INVARIANT_FAILED_TOTAL = Counter(
    "bess_invariant_failed_total",
    "Total invariant checks that failed",
    ["check_type"],
)

INVARIANT_ALL_PASSED_TOTAL = Counter(
    "bess_invariant_all_passed_total",
    "Total variants where all invariants passed",
)

INVARIANT_ANY_FAILED_TOTAL = Counter(
    "bess_invariant_any_failed_total",
    "Total variants where at least one invariant failed",
)


# -----------------------------------------------------------------------------
# Counters - STRICT_INVARIANTS mode
# -----------------------------------------------------------------------------

STRICT_INVARIANTS_ENABLED = Gauge(
    "bess_strict_invariants_enabled",
    "Whether STRICT_INVARIANTS mode is enabled (1=enabled, 0=disabled)",
)

STRICT_INVARIANTS_VIOLATIONS_TOTAL = Counter(
    "bess_strict_invariants_violations_total",
    "Total InvariantViolationError exceptions raised in STRICT mode",
)


# -----------------------------------------------------------------------------
# Histograms - Error Magnitudes
# -----------------------------------------------------------------------------

INVARIANT_ENERGY_BALANCE_ERROR = Histogram(
    "bess_invariant_energy_balance_error_mwh",
    "Maximum absolute error in energy balance (MWh)",
    buckets=[0.0, 0.0001, 0.001, 0.01, 0.1, 1.0, 10.0],
)

INVARIANT_COST_SUMS_ERROR = Histogram(
    "bess_invariant_cost_sums_error_pln",
    "Maximum absolute error in cost sums (PLN)",
    buckets=[0.0, 0.01, 0.1, 1.0, 10.0, 100.0, 1000.0],
)

INVARIANT_ANNUALIZATION_ERROR = Histogram(
    "bess_invariant_annualization_error_pln",
    "Maximum absolute error in annualization (PLN)",
    buckets=[0.0, 0.01, 0.1, 1.0, 10.0, 100.0, 1000.0],
)


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

def record_invariant_check(check_type: str, passed: bool, max_error: float = 0.0):
    """
    Record an invariant check result.

    Args:
        check_type: Type of invariant (energy_balance, non_negative, cost_sums, annualization)
        passed: Whether the check passed
        max_error: Maximum absolute error found (optional)
    """
    INVARIANT_CHECKS_TOTAL.labels(check_type=check_type).inc()

    if passed:
        INVARIANT_PASSED_TOTAL.labels(check_type=check_type).inc()
    else:
        INVARIANT_FAILED_TOTAL.labels(check_type=check_type).inc()

    # Record error magnitude histograms
    if check_type == "energy_balance":
        INVARIANT_ENERGY_BALANCE_ERROR.observe(max_error)
    elif check_type == "cost_sums":
        INVARIANT_COST_SUMS_ERROR.observe(max_error)
    elif check_type == "annualization":
        INVARIANT_ANNUALIZATION_ERROR.observe(max_error)


def record_invariant_result(invariants: dict):
    """
    Record invariant results from a variant.

    Args:
        invariants: Dict with check results (e.g., {'energy_balance_ok': True, ...})
    """
    all_passed = invariants.get("all_passed", True)

    if all_passed:
        INVARIANT_ALL_PASSED_TOTAL.inc()
    else:
        INVARIANT_ANY_FAILED_TOTAL.inc()

    # Record individual checks
    check_types = [
        ("energy_balance", "energy_balance_ok", "energy_balance_max_abs_error"),
        ("non_negative", "non_negative_ok", None),
        ("cost_sums", "cost_sums_ok", "cost_sums_max_abs_error"),
        ("annualization", "annualization_ok", "annualization_max_abs_error"),
    ]

    for check_type, ok_key, error_key in check_types:
        if ok_key in invariants:
            passed = invariants.get(ok_key, True)
            max_error = invariants.get(error_key, 0.0) if error_key else 0.0
            record_invariant_check(check_type, passed, max_error)


def record_strict_invariants_status(enabled: bool):
    """Record whether STRICT_INVARIANTS mode is enabled."""
    STRICT_INVARIANTS_ENABLED.set(1 if enabled else 0)


def record_strict_invariants_violation():
    """Record a STRICT_INVARIANTS violation (InvariantViolationError raised)."""
    STRICT_INVARIANTS_VIOLATIONS_TOTAL.inc()

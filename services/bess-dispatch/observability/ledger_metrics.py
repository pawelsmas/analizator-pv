"""
Prometheus metrics for MoneyLedger reconciliation (v1.9.0).

Tracks:
- Ledger reconciliation checks (passed/failed)
- Reconciliation error magnitudes
- Ledger requests (with/without money_ledger)
"""

from prometheus_client import Counter, Histogram


# -----------------------------------------------------------------------------
# Counters - Reconciliation
# -----------------------------------------------------------------------------

LEDGER_RECONCILIATION_TOTAL = Counter(
    "bess_ledger_reconciliation_total",
    "Total ledger reconciliation checks",
    ["status"],  # "passed" or "failed"
)

LEDGER_REQUESTS_TOTAL = Counter(
    "bess_ledger_requests_total",
    "Total sizing requests with ledger tracking",
    ["include_money_ledger"],  # "true" or "false"
)


# -----------------------------------------------------------------------------
# Histograms - Reconciliation Errors
# -----------------------------------------------------------------------------

LEDGER_RECONCILIATION_ERROR_PLN = Histogram(
    "bess_ledger_reconciliation_error_pln",
    "Ledger reconciliation error magnitude (abs diff in PLN)",
    buckets=[0, 0.01, 0.1, 1.0, 10.0, 100.0, 1000.0],
)


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

def record_ledger_reconciliation(passed: bool, error_pln: float = 0.0) -> None:
    """
    Record a ledger reconciliation check.

    Args:
        passed: Whether reconciliation passed
        error_pln: Absolute error in PLN between net_savings and ledger delta
    """
    LEDGER_RECONCILIATION_TOTAL.labels(
        status="passed" if passed else "failed"
    ).inc()

    LEDGER_RECONCILIATION_ERROR_PLN.observe(abs(error_pln))


def record_ledger_request(include_money_ledger: bool) -> None:
    """
    Record a sizing request with ledger tracking.

    Args:
        include_money_ledger: Whether money_ledger was requested
    """
    LEDGER_REQUESTS_TOTAL.labels(
        include_money_ledger="true" if include_money_ledger else "false"
    ).inc()

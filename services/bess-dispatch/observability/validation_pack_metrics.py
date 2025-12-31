"""
Prometheus metrics for validate-pack operations (v1.7.0).

Tracks:
- Pack validation requests (total, pass, fail)
- Scenario validation results per pack
- Field mismatch counts
- Validation job duration

These metrics enable monitoring of baseline health validation
and alerting on validation failures.
"""

from prometheus_client import Counter, Gauge, Histogram


# -----------------------------------------------------------------------------
# Counters - Pack Validation Requests
# -----------------------------------------------------------------------------

VALIDATION_PACK_REQUESTS_TOTAL = Counter(
    "bess_validation_pack_requests_total",
    "Total validate-pack requests",
    ["pack"],  # pack name
)

VALIDATION_PACK_PASSED_TOTAL = Counter(
    "bess_validation_pack_passed_total",
    "Total validate-pack requests where all scenarios passed",
    ["pack"],
)

VALIDATION_PACK_FAILED_TOTAL = Counter(
    "bess_validation_pack_failed_total",
    "Total validate-pack requests with at least one scenario failure",
    ["pack"],
)


# -----------------------------------------------------------------------------
# Counters - Scenario Validation Results
# -----------------------------------------------------------------------------

VALIDATION_SCENARIO_TOTAL = Counter(
    "bess_validation_scenario_total",
    "Total scenario validations",
    ["pack", "scenario"],
)

VALIDATION_SCENARIO_PASSED = Counter(
    "bess_validation_scenario_passed_total",
    "Total scenario validations that passed",
    ["pack", "scenario"],
)

VALIDATION_SCENARIO_FAILED = Counter(
    "bess_validation_scenario_failed_total",
    "Total scenario validations that failed",
    ["pack", "scenario"],
)

VALIDATION_SCENARIO_ERROR = Counter(
    "bess_validation_scenario_error_total",
    "Total scenario validations with errors (not mismatches)",
    ["pack", "scenario"],
)


# -----------------------------------------------------------------------------
# Gauges - Current State
# -----------------------------------------------------------------------------

VALIDATION_LAST_PACK_PASSED = Gauge(
    "bess_validation_last_pack_passed",
    "Whether last validation of pack passed (1=pass, 0=fail)",
    ["pack"],
)

VALIDATION_LAST_SCENARIOS_TOTAL = Gauge(
    "bess_validation_last_scenarios_total",
    "Total scenarios in last pack validation",
    ["pack"],
)

VALIDATION_LAST_SCENARIOS_PASSED = Gauge(
    "bess_validation_last_scenarios_passed",
    "Passed scenarios in last pack validation",
    ["pack"],
)

VALIDATION_LAST_SCENARIOS_FAILED = Gauge(
    "bess_validation_last_scenarios_failed",
    "Failed scenarios in last pack validation",
    ["pack"],
)


# -----------------------------------------------------------------------------
# Histograms - Field Mismatches
# -----------------------------------------------------------------------------

VALIDATION_FIELD_MISMATCH_COUNT = Histogram(
    "bess_validation_field_mismatch_count",
    "Number of field mismatches per scenario",
    ["pack"],
    buckets=[0, 1, 2, 5, 10, 20, 50],
)


# -----------------------------------------------------------------------------
# Histograms - Duration
# -----------------------------------------------------------------------------

VALIDATION_PACK_DURATION_SECONDS = Histogram(
    "bess_validation_pack_duration_seconds",
    "Duration of validate-pack job",
    ["pack"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0],
)


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

def record_pack_validation_request(pack: str):
    """Record a validate-pack request."""
    VALIDATION_PACK_REQUESTS_TOTAL.labels(pack=pack).inc()


def record_pack_validation_result(pack: str, passed: bool, summary: dict):
    """
    Record validate-pack result.

    Args:
        pack: Pack name
        passed: Whether all scenarios passed
        summary: Summary dict with total/pass/fail counts
    """
    if passed:
        VALIDATION_PACK_PASSED_TOTAL.labels(pack=pack).inc()
    else:
        VALIDATION_PACK_FAILED_TOTAL.labels(pack=pack).inc()

    # Update last state gauges
    VALIDATION_LAST_PACK_PASSED.labels(pack=pack).set(1 if passed else 0)
    VALIDATION_LAST_SCENARIOS_TOTAL.labels(pack=pack).set(summary.get("total", 0))
    VALIDATION_LAST_SCENARIOS_PASSED.labels(pack=pack).set(summary.get("pass", 0))
    VALIDATION_LAST_SCENARIOS_FAILED.labels(pack=pack).set(summary.get("fail", 0))


def record_scenario_validation(pack: str, scenario: str, passed: bool, error: bool, mismatch_count: int):
    """
    Record scenario validation result.

    Args:
        pack: Pack name
        scenario: Scenario name
        passed: Whether scenario passed
        error: Whether there was an error (not mismatch)
        mismatch_count: Number of field mismatches
    """
    VALIDATION_SCENARIO_TOTAL.labels(pack=pack, scenario=scenario).inc()

    if passed:
        VALIDATION_SCENARIO_PASSED.labels(pack=pack, scenario=scenario).inc()
    else:
        VALIDATION_SCENARIO_FAILED.labels(pack=pack, scenario=scenario).inc()

    if error:
        VALIDATION_SCENARIO_ERROR.labels(pack=pack, scenario=scenario).inc()

    # Record mismatch count histogram
    VALIDATION_FIELD_MISMATCH_COUNT.labels(pack=pack).observe(mismatch_count)


def record_pack_validation_duration(pack: str, duration_seconds: float):
    """Record validate-pack job duration."""
    VALIDATION_PACK_DURATION_SECONDS.labels(pack=pack).observe(duration_seconds)

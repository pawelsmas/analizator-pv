"""
Driver Observability Metrics (v4.5.0).

Prometheus metrics for tracking objective/profile usage and duration distribution.
"""

from prometheus_client import Counter, Histogram

# Objective usage counter
OBJECTIVE_USAGE_TOTAL = Counter(
    'bess_objective_usage_total',
    'Number of requests by optimization objective',
    ['objective']
)

# Profile usage counter
PROFILE_USAGE_TOTAL = Counter(
    'bess_profile_usage_total',
    'Number of requests by optimization profile',
    ['profile']
)

# Duration distribution histogram
RECOMMENDED_DURATION_HISTOGRAM = Histogram(
    'bess_recommended_duration_hours',
    'Distribution of recommended battery duration',
    buckets=[0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0]
)

# Near-optimal selection counter
NEAR_OPTIMAL_SELECTION_TOTAL = Counter(
    'bess_near_optimal_selection_total',
    'Number of times near-optimal tie-breaker was used',
    ['tie_breaker']
)

# Tie-breaker effectiveness
TIE_BREAKER_USED_TOTAL = Counter(
    'bess_tie_breaker_used_total',
    'Which tie-breaker was decisive',
    ['tie_breaker', 'objective']
)


def record_objective_usage(objective: str):
    """Record objective usage."""
    OBJECTIVE_USAGE_TOTAL.labels(objective=objective).inc()


def record_profile_usage(profile: str):
    """Record profile usage."""
    PROFILE_USAGE_TOTAL.labels(profile=profile).inc()


def record_recommended_duration(duration_h: float):
    """Record recommended duration."""
    RECOMMENDED_DURATION_HISTOGRAM.observe(duration_h)


def record_near_optimal_selection(tie_breaker: str):
    """Record near-optimal tie-breaker usage."""
    NEAR_OPTIMAL_SELECTION_TOTAL.labels(tie_breaker=tie_breaker).inc()


def record_tie_breaker_decision(tie_breaker: str, objective: str):
    """Record which tie-breaker was decisive."""
    TIE_BREAKER_USED_TOTAL.labels(tie_breaker=tie_breaker, objective=objective).inc()

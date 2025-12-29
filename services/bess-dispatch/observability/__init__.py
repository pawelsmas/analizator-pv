"""
Observability module for bess-dispatch service.

Contains HTTP metrics and finance metrics instrumentation for Prometheus.
"""

from .http_metrics import (
    HTTP_REQUESTS_TOTAL,
    HTTP_REQUEST_DURATION_SECONDS,
    SERVICE_NAME,
)

from .finance_metrics import (
    FINANCE_CASHFLOW_REQUESTS,
    FINANCE_SENSITIVITY_REQUESTS,
    FINANCE_SENSITIVITY_POINTS,
    FINANCE_NPV_KPLN,
    FINANCE_IRR_PCT,
    record_finance_cashflow_metrics,
    record_finance_sensitivity_metrics,
    record_finance_npv_metrics,
    record_finance_irr_metrics,
)

__all__ = [
    # HTTP metrics
    "HTTP_REQUESTS_TOTAL",
    "HTTP_REQUEST_DURATION_SECONDS",
    "SERVICE_NAME",
    # Finance metrics
    "FINANCE_CASHFLOW_REQUESTS",
    "FINANCE_SENSITIVITY_REQUESTS",
    "FINANCE_SENSITIVITY_POINTS",
    "FINANCE_NPV_KPLN",
    "FINANCE_IRR_PCT",
    "record_finance_cashflow_metrics",
    "record_finance_sensitivity_metrics",
    "record_finance_npv_metrics",
    "record_finance_irr_metrics",
]

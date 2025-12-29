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
    # v0.6.0 lifecycle metrics
    FINANCE_REPLACEMENT_REQUESTS,
    FINANCE_DEGRADATION_REQUESTS,
    FINANCE_ENERGY_PRICE_SENSITIVITY,
    FINANCE_CAPEX_SENSITIVITY,
    FINANCE_REPLACEMENT_YEAR,
    FINANCE_BESS_DEGRADATION_RATE,
    FINANCE_PV_DEGRADATION_RATE,
    record_replacement_metrics,
    record_degradation_metrics,
    record_energy_price_sensitivity_metrics,
    record_capex_sensitivity_metrics,
)

__all__ = [
    # HTTP metrics
    "HTTP_REQUESTS_TOTAL",
    "HTTP_REQUEST_DURATION_SECONDS",
    "SERVICE_NAME",
    # Finance metrics (v0.5.0)
    "FINANCE_CASHFLOW_REQUESTS",
    "FINANCE_SENSITIVITY_REQUESTS",
    "FINANCE_SENSITIVITY_POINTS",
    "FINANCE_NPV_KPLN",
    "FINANCE_IRR_PCT",
    "record_finance_cashflow_metrics",
    "record_finance_sensitivity_metrics",
    "record_finance_npv_metrics",
    "record_finance_irr_metrics",
    # Lifecycle metrics (v0.6.0)
    "FINANCE_REPLACEMENT_REQUESTS",
    "FINANCE_DEGRADATION_REQUESTS",
    "FINANCE_ENERGY_PRICE_SENSITIVITY",
    "FINANCE_CAPEX_SENSITIVITY",
    "FINANCE_REPLACEMENT_YEAR",
    "FINANCE_BESS_DEGRADATION_RATE",
    "FINANCE_PV_DEGRADATION_RATE",
    "record_replacement_metrics",
    "record_degradation_metrics",
    "record_energy_price_sensitivity_metrics",
    "record_capex_sensitivity_metrics",
]

"""
Observability module for bess-dispatch service.

Contains HTTP metrics, finance metrics, and constraint metrics for Prometheus.
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

from .constraint_metrics import (
    # v0.7.0 grid constraint metrics
    GRID_CONSTRAINT_REQUESTS,
    EXPORT_CAP_HIT,
    IMPORT_CAP_HIT,
    UNSERVED_LOAD_OCCURRED,
    EXPORT_CAP_CURTAILED_KWH,
    UNSERVED_LOAD_KWH,
    UNSERVED_LOAD_PENALTY_PLN,
    EXPORT_CAP_HIT_STEPS,
    IMPORT_CAP_HIT_STEPS,
    record_grid_constraint_request,
    record_export_cap_metrics,
    record_import_cap_metrics,
)

from .sizing_constraint_metrics import (
    # v0.8.0 sizing constraint metrics
    SIZING_CONSTRAINTS_REQUESTS,
    SIZING_CONSTRAINTS_FEASIBLE,
    SIZING_CONSTRAINTS_NONE_FEASIBLE,
    SIZING_FEASIBLE_VARIANTS_COUNT,
    SIZING_CONSTRAINT_MAX_CAPEX,
    SIZING_CONSTRAINT_MAX_PAYBACK,
    SIZING_CONSTRAINT_MIN_NPV,
    # v0.8.0 Pareto frontier metrics
    PARETO_FRONTIER_REQUESTS,
    PARETO_FRONTIER_SIZE,
    PARETO_DOMINATED_COUNT,
    # Helper functions
    record_sizing_constraints_request,
    record_sizing_feasibility,
    record_pareto_frontier,
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
    # Grid constraint metrics (v0.7.0)
    "GRID_CONSTRAINT_REQUESTS",
    "EXPORT_CAP_HIT",
    "IMPORT_CAP_HIT",
    "UNSERVED_LOAD_OCCURRED",
    "EXPORT_CAP_CURTAILED_KWH",
    "UNSERVED_LOAD_KWH",
    "UNSERVED_LOAD_PENALTY_PLN",
    "EXPORT_CAP_HIT_STEPS",
    "IMPORT_CAP_HIT_STEPS",
    "record_grid_constraint_request",
    "record_export_cap_metrics",
    "record_import_cap_metrics",
    # Sizing constraint metrics (v0.8.0)
    "SIZING_CONSTRAINTS_REQUESTS",
    "SIZING_CONSTRAINTS_FEASIBLE",
    "SIZING_CONSTRAINTS_NONE_FEASIBLE",
    "SIZING_FEASIBLE_VARIANTS_COUNT",
    "SIZING_CONSTRAINT_MAX_CAPEX",
    "SIZING_CONSTRAINT_MAX_PAYBACK",
    "SIZING_CONSTRAINT_MIN_NPV",
    "record_sizing_constraints_request",
    "record_sizing_feasibility",
    # Pareto frontier metrics (v0.8.0)
    "PARETO_FRONTIER_REQUESTS",
    "PARETO_FRONTIER_SIZE",
    "PARETO_DOMINATED_COUNT",
    "record_pareto_frontier",
]

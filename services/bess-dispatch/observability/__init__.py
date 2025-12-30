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

from .batch_metrics import (
    # v0.9.0 batch sizing metrics
    BATCH_REQUESTS,
    BATCH_ITEMS_COUNT,
    BATCH_OK_COUNT,
    BATCH_ERROR_COUNT,
    BATCH_PROCESSING_TIME_MS,
    # v0.9.0 portfolio summary metrics
    PORTFOLIO_SUMMARY_REQUESTS,
    PORTFOLIO_OPTIMAL_VARIANT,
    PORTFOLIO_TOTAL_NPV_KPLN,
    PORTFOLIO_AVG_PAYBACK_YEARS,
    # Helper functions
    record_batch_request,
    record_portfolio_summary,
)

from .runstore_metrics import (
    # v1.0.0 run store metrics
    RUNSTORE_SAVES_TOTAL,
    RUNSTORE_GETS_TOTAL,
    RUNSTORE_LIST_REQUESTS_TOTAL,
    RUNSTORE_PRUNE_TOTAL,
    RUNSTORE_COMPARE_TOTAL,
    RUNSTORE_EXPORT_TOTAL,
    RUNSTORE_DELETED_COUNT,
    RUNSTORE_LIST_RESULTS_COUNT,
    RUNSTORE_RETENTION_DAYS,
    # Helper functions
    record_runstore_save,
    record_runstore_get,
    record_runstore_list,
    record_runstore_prune,
    record_runstore_compare,
    record_runstore_export,
)

from .jobs_metrics import (
    # v1.1.0 async jobs metrics
    JOBS_CREATED_TOTAL,
    JOBS_IDEMPOTENCY_HIT_TOTAL,
    JOBS_ITEMS_COUNT,
    JOBS_STATUS_TRANSITIONS,
    JOBS_COMPLETED_TOTAL,
    JOBS_CANCELLED_TOTAL,
    JOBS_DURATION_SECONDS,
    JOBS_WAIT_TIME_SECONDS,
    JOBS_PROCESSING_TIME_SECONDS,
    JOBS_OK_ITEMS_COUNT,
    JOBS_ERROR_ITEMS_COUNT,
    JOBS_GET_TOTAL,
    JOBS_LIST_TOTAL,
    JOBS_LIST_RESULTS_COUNT,
    JOBS_CANCEL_TOTAL,
    # Helper functions
    record_job_created,
    record_job_idempotency_hit,
    record_job_status_transition,
    record_job_completed,
    record_job_cancelled,
    record_job_wait_time,
    record_job_processing_time,
    record_job_get,
    record_job_list,
    record_job_cancel,
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
    # Batch sizing metrics (v0.9.0)
    "BATCH_REQUESTS",
    "BATCH_ITEMS_COUNT",
    "BATCH_OK_COUNT",
    "BATCH_ERROR_COUNT",
    "BATCH_PROCESSING_TIME_MS",
    "record_batch_request",
    # Portfolio summary metrics (v0.9.0)
    "PORTFOLIO_SUMMARY_REQUESTS",
    "PORTFOLIO_OPTIMAL_VARIANT",
    "PORTFOLIO_TOTAL_NPV_KPLN",
    "PORTFOLIO_AVG_PAYBACK_YEARS",
    "record_portfolio_summary",
    # Run store metrics (v1.0.0)
    "RUNSTORE_SAVES_TOTAL",
    "RUNSTORE_GETS_TOTAL",
    "RUNSTORE_LIST_REQUESTS_TOTAL",
    "RUNSTORE_PRUNE_TOTAL",
    "RUNSTORE_COMPARE_TOTAL",
    "RUNSTORE_EXPORT_TOTAL",
    "RUNSTORE_DELETED_COUNT",
    "RUNSTORE_LIST_RESULTS_COUNT",
    "RUNSTORE_RETENTION_DAYS",
    "record_runstore_save",
    "record_runstore_get",
    "record_runstore_list",
    "record_runstore_prune",
    "record_runstore_compare",
    "record_runstore_export",
    # Async jobs metrics (v1.1.0)
    "JOBS_CREATED_TOTAL",
    "JOBS_IDEMPOTENCY_HIT_TOTAL",
    "JOBS_ITEMS_COUNT",
    "JOBS_STATUS_TRANSITIONS",
    "JOBS_COMPLETED_TOTAL",
    "JOBS_CANCELLED_TOTAL",
    "JOBS_DURATION_SECONDS",
    "JOBS_WAIT_TIME_SECONDS",
    "JOBS_PROCESSING_TIME_SECONDS",
    "JOBS_OK_ITEMS_COUNT",
    "JOBS_ERROR_ITEMS_COUNT",
    "JOBS_GET_TOTAL",
    "JOBS_LIST_TOTAL",
    "JOBS_LIST_RESULTS_COUNT",
    "JOBS_CANCEL_TOTAL",
    "record_job_created",
    "record_job_idempotency_hit",
    "record_job_status_transition",
    "record_job_completed",
    "record_job_cancelled",
    "record_job_wait_time",
    "record_job_processing_time",
    "record_job_get",
    "record_job_list",
    "record_job_cancel",
]

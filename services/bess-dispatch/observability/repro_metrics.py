"""
Prometheus metrics for repro bundle and debug events (v1.8.0).

Tracks:
- Repro bundle downloads (run and job)
- Debug events (constraint caps, curtailment, unserved load)
"""

from typing import Union
from prometheus_client import Counter, Histogram


# -----------------------------------------------------------------------------
# Counters - Repro Bundle Downloads
# -----------------------------------------------------------------------------

REPRO_RUN_DOWNLOADS_TOTAL = Counter(
    "bess_repro_run_downloads_total",
    "Total repro.zip downloads for individual runs",
    ["status"],  # "success" or "not_found"
)

REPRO_JOB_DOWNLOADS_TOTAL = Counter(
    "bess_repro_job_downloads_total",
    "Total repro.zip downloads for batch jobs",
    ["status"],  # "success" or "not_found"
)


# -----------------------------------------------------------------------------
# Counters - Debug Events
# -----------------------------------------------------------------------------

DEBUG_EVENTS_EXPORT_LIMITED_TOTAL = Counter(
    "bess_debug_events_export_limited_total",
    "Total runs with export limited steps (grid capacity constraint)",
)

DEBUG_EVENTS_IMPORT_LIMITED_TOTAL = Counter(
    "bess_debug_events_import_limited_total",
    "Total runs with import limited steps (grid capacity constraint)",
)

DEBUG_EVENTS_PV_CURTAIL_TOTAL = Counter(
    "bess_debug_events_pv_curtail_total",
    "Total runs with PV curtailment",
)

DEBUG_EVENTS_UNSERVED_LOAD_TOTAL = Counter(
    "bess_debug_events_unserved_load_total",
    "Total runs with unserved load (critical issue)",
)


# -----------------------------------------------------------------------------
# Histograms - Debug Events Magnitude
# -----------------------------------------------------------------------------

DEBUG_EVENTS_EXPORT_LIMITED_MWH = Histogram(
    "bess_debug_events_export_limited_mwh",
    "Export limited energy per run (MWh)",
    buckets=[0, 0.01, 0.1, 0.5, 1.0, 5.0, 10.0, 50.0, 100.0],
)

DEBUG_EVENTS_IMPORT_LIMITED_MWH = Histogram(
    "bess_debug_events_import_limited_mwh",
    "Import limited energy per run (MWh)",
    buckets=[0, 0.01, 0.1, 0.5, 1.0, 5.0, 10.0, 50.0, 100.0],
)

DEBUG_EVENTS_PV_CURTAIL_MWH = Histogram(
    "bess_debug_events_pv_curtail_mwh",
    "PV curtailment per run (MWh)",
    buckets=[0, 0.01, 0.1, 0.5, 1.0, 5.0, 10.0, 50.0, 100.0],
)

DEBUG_EVENTS_UNSERVED_LOAD_KWH = Histogram(
    "bess_debug_events_unserved_load_kwh",
    "Unserved load per run (kWh) - critical if > 0",
    buckets=[0, 0.1, 1, 10, 50, 100, 500, 1000],
)


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

def record_repro_run_download(success: bool) -> None:
    """Record a repro.zip download for an individual run."""
    REPRO_RUN_DOWNLOADS_TOTAL.labels(
        status="success" if success else "not_found"
    ).inc()


def record_repro_job_download(success: bool) -> None:
    """Record a repro.zip download for a batch job."""
    REPRO_JOB_DOWNLOADS_TOTAL.labels(
        status="success" if success else "not_found"
    ).inc()


def record_debug_events(debug_events: Union[dict, object]) -> None:
    """
    Record debug events metrics from a run.

    Args:
        debug_events: DebugEvents object or dict with debug event counts and magnitudes
    """
    if not debug_events:
        return

    # Handle both dict and object access
    def get_val(obj, key, default=0):
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    # Export limited
    export_limited_steps = get_val(debug_events, "export_limited_steps", 0)
    export_limited_mwh = get_val(debug_events, "export_limited_mwh", 0.0)
    if export_limited_steps > 0:
        DEBUG_EVENTS_EXPORT_LIMITED_TOTAL.inc()
    DEBUG_EVENTS_EXPORT_LIMITED_MWH.observe(export_limited_mwh)

    # Import limited
    import_limited_steps = get_val(debug_events, "import_limited_steps", 0)
    import_limited_mwh = get_val(debug_events, "import_limited_mwh", 0.0)
    if import_limited_steps > 0:
        DEBUG_EVENTS_IMPORT_LIMITED_TOTAL.inc()
    DEBUG_EVENTS_IMPORT_LIMITED_MWH.observe(import_limited_mwh)

    # PV curtailment
    pv_curtail_steps = get_val(debug_events, "pv_curtail_steps", 0)
    pv_curtail_mwh = get_val(debug_events, "pv_curtail_mwh", 0.0)
    if pv_curtail_steps > 0:
        DEBUG_EVENTS_PV_CURTAIL_TOTAL.inc()
    DEBUG_EVENTS_PV_CURTAIL_MWH.observe(pv_curtail_mwh)

    # Unserved load (critical)
    unserved_load_steps = get_val(debug_events, "unserved_load_steps", 0)
    unserved_load_kwh = get_val(debug_events, "unserved_load_kwh", 0.0)
    if unserved_load_steps > 0:
        DEBUG_EVENTS_UNSERVED_LOAD_TOTAL.inc()
    DEBUG_EVENTS_UNSERVED_LOAD_KWH.observe(unserved_load_kwh)

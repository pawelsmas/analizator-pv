"""
Debug Events Helper (v1.8.0).

Creates DebugEvents summary from dispatch result data.
Aggregates constraint_summary and energy_flows into easy-to-read debug info.
"""

from typing import Optional
from models import DebugEvents, ConstraintSummary, EnergyFlows


def compute_debug_events(
    n_timesteps: int,
    constraint_summary: Optional[ConstraintSummary] = None,
    energy_flows: Optional[EnergyFlows] = None,
    pv_curtail_kwh_arr: Optional[list] = None,
) -> DebugEvents:
    """
    Compute debug events from dispatch result components.

    Args:
        n_timesteps: Total number of timesteps in simulation
        constraint_summary: Grid constraint summary (export/import cap hits)
        energy_flows: Energy flows with totals and timeseries
        pv_curtail_kwh_arr: PV curtailment per step (for counting steps)

    Returns:
        DebugEvents with aggregated debug info
    """
    debug = DebugEvents(steps=n_timesteps)

    # Export limiting (from constraint_summary)
    if constraint_summary:
        debug.export_limited_steps = constraint_summary.export_cap_hit_steps
        debug.export_limited_mwh = constraint_summary.export_cap_curtailed_kwh / 1000.0

        debug.import_limited_steps = constraint_summary.import_cap_hit_steps
        debug.unserved_load_kwh = constraint_summary.unserved_load_kwh
        debug.unserved_load_steps = constraint_summary.import_cap_hit_steps
        debug.import_limited_mwh = constraint_summary.unserved_load_kwh / 1000.0

    # PV curtailment (from energy_flows or direct array)
    if energy_flows and energy_flows.totals_mwh:
        debug.pv_curtail_mwh = energy_flows.totals_mwh.pv_curtail_mwh

        # Count steps from timeseries if available
        if energy_flows.timeseries_kwh and energy_flows.timeseries_kwh.pv_curtail_kwh:
            debug.pv_curtail_steps = sum(
                1 for kwh in energy_flows.timeseries_kwh.pv_curtail_kwh if kwh > 0
            )
    elif pv_curtail_kwh_arr:
        debug.pv_curtail_mwh = sum(pv_curtail_kwh_arr) / 1000.0
        debug.pv_curtail_steps = sum(1 for kwh in pv_curtail_kwh_arr if kwh > 0)

    return debug


def merge_debug_events(
    result_dict: dict,
    n_timesteps: int,
) -> DebugEvents:
    """
    Extract debug events from a result dictionary.

    Args:
        result_dict: Dispatch result as dict (with constraint_summary, energy_flows)
        n_timesteps: Total timesteps

    Returns:
        DebugEvents
    """
    debug = DebugEvents(steps=n_timesteps)

    # From constraint_summary
    cs = result_dict.get("constraint_summary")
    if cs:
        debug.export_limited_steps = cs.get("export_cap_hit_steps", 0)
        debug.export_limited_mwh = cs.get("export_cap_curtailed_kwh", 0) / 1000.0
        debug.import_limited_steps = cs.get("import_cap_hit_steps", 0)
        debug.import_limited_mwh = cs.get("unserved_load_kwh", 0) / 1000.0
        debug.unserved_load_kwh = cs.get("unserved_load_kwh", 0)
        debug.unserved_load_steps = cs.get("import_cap_hit_steps", 0)

    # From energy_flows
    ef = result_dict.get("energy_flows")
    if ef:
        totals = ef.get("totals_mwh")
        if totals:
            debug.pv_curtail_mwh = totals.get("pv_curtail_mwh", 0)

        ts = ef.get("timeseries_kwh")
        if ts and ts.get("pv_curtail_kwh"):
            debug.pv_curtail_steps = sum(
                1 for kwh in ts["pv_curtail_kwh"] if kwh > 0
            )

    return debug

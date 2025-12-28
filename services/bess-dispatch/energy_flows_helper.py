"""
Energy Flows SSoT Helper
========================
Helper functions for creating EnergyFlows objects.

The EnergyFlows structure is the Single Source of Truth for energy accounting.
"""

import numpy as np
from typing import Optional

from models import (
    EnergyFlows,
    EnergyFlowsTotalsMwh,
    EnergyFlowsTimeseriesKwh,
)


def create_energy_flows(
    grid_import_kwh: np.ndarray,
    grid_export_kwh: np.ndarray,
    pv_to_load_kwh: np.ndarray,
    pv_to_batt_kwh: np.ndarray,
    pv_curtail_kwh: np.ndarray,
    batt_to_load_kwh: np.ndarray,
    batt_charge_from_grid_kwh: np.ndarray,
    batt_losses_kwh: np.ndarray,
    soc_kwh: np.ndarray,
    include_timeseries: bool = False,
) -> EnergyFlows:
    """
    Create EnergyFlows object from per-timestep arrays.

    Args:
        grid_import_kwh: Grid import energy per step [kWh]
        grid_export_kwh: Grid export energy per step [kWh]
        pv_to_load_kwh: PV direct to load per step [kWh]
        pv_to_batt_kwh: PV to battery per step [kWh]
        pv_curtail_kwh: PV curtailed per step [kWh]
        batt_to_load_kwh: Battery to load per step [kWh]
        batt_charge_from_grid_kwh: Battery charge from grid per step [kWh]
        batt_losses_kwh: Battery losses per step [kWh]
        soc_kwh: State of charge per step [kWh]
        include_timeseries: If True, include per-timestep arrays in response

    Returns:
        EnergyFlows with totals_mwh (always) and timeseries_kwh (if requested)
    """
    # Calculate totals (kWh -> MWh)
    totals = EnergyFlowsTotalsMwh(
        grid_import_mwh=float(np.sum(grid_import_kwh)) / 1000.0,
        grid_export_mwh=float(np.sum(grid_export_kwh)) / 1000.0,
        pv_to_load_mwh=float(np.sum(pv_to_load_kwh)) / 1000.0,
        pv_to_batt_mwh=float(np.sum(pv_to_batt_kwh)) / 1000.0,
        pv_curtail_mwh=float(np.sum(pv_curtail_kwh)) / 1000.0,
        batt_to_load_mwh=float(np.sum(batt_to_load_kwh)) / 1000.0,
        batt_charge_from_grid_mwh=float(np.sum(batt_charge_from_grid_kwh)) / 1000.0,
        batt_losses_mwh=float(np.sum(batt_losses_kwh)) / 1000.0,
    )

    timeseries = None
    if include_timeseries:
        timeseries = EnergyFlowsTimeseriesKwh(
            grid_import_kwh=grid_import_kwh.tolist(),
            grid_export_kwh=grid_export_kwh.tolist(),
            pv_to_load_kwh=pv_to_load_kwh.tolist(),
            pv_to_batt_kwh=pv_to_batt_kwh.tolist(),
            pv_curtail_kwh=pv_curtail_kwh.tolist(),
            batt_to_load_kwh=batt_to_load_kwh.tolist(),
            batt_charge_from_grid_kwh=batt_charge_from_grid_kwh.tolist(),
            batt_losses_kwh=batt_losses_kwh.tolist(),
            soc_kwh=soc_kwh.tolist(),
        )

    return EnergyFlows(totals_mwh=totals, timeseries_kwh=timeseries)

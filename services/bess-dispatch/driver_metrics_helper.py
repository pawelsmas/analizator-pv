"""
Driver Metrics Helper (v4.5.0).

Computes key metrics for decision drivers optimization.

This module is the SINGLE SOURCE OF TRUTH for:
- Self-consumption rate calculation
- LCOS (Levelized Cost of Storage) calculation
- Resilience score calculation

These metrics enable intelligent variant selection beyond just NPV.
"""

import logging
from typing import Optional, Dict, Any, Union
import math

logger = logging.getLogger(__name__)


def compute_self_consumption_rate(
    self_consumption_kwh: float,
    total_pv_kwh: float,
) -> float:
    """
    Compute self-consumption rate as ratio [0-1].

    Self-consumption rate = PV energy consumed locally / Total PV generation

    Args:
        self_consumption_kwh: Total PV energy consumed locally (direct + via battery) [kWh]
        total_pv_kwh: Total PV generation [kWh]

    Returns:
        Self-consumption rate [0-1]. Returns 0.0 if no PV generation.
    """
    if total_pv_kwh <= 0:
        return 0.0

    rate = self_consumption_kwh / total_pv_kwh
    # Clamp to [0, 1] to handle floating point errors
    return max(0.0, min(1.0, rate))


def compute_self_consumption_rate_from_dispatch(
    dispatch_result: Union[Dict[str, Any], Any],
) -> float:
    """
    Compute self-consumption rate from dispatch result.

    Args:
        dispatch_result: DispatchResult model or dict with self_consumption_kwh and total_pv_kwh

    Returns:
        Self-consumption rate [0-1]
    """
    if isinstance(dispatch_result, dict):
        self_consumption_kwh = dispatch_result.get("self_consumption_kwh", 0.0)
        total_pv_kwh = dispatch_result.get("total_pv_kwh", 0.0)
    else:
        self_consumption_kwh = getattr(dispatch_result, "self_consumption_kwh", 0.0)
        total_pv_kwh = getattr(dispatch_result, "total_pv_kwh", 0.0)

    return compute_self_consumption_rate(self_consumption_kwh, total_pv_kwh)


def compute_lcos_pln_per_mwh(
    capex_pln: float,
    annual_opex_pln: float,
    annual_throughput_mwh: float,
    discount_rate: float = 0.08,
    lifetime_years: int = 15,
) -> Optional[float]:
    """
    Compute Levelized Cost of Storage (LCOS) in PLN/MWh.

    LCOS = (NPV of all costs) / (NPV of all throughput)

    This is the average cost per MWh of energy stored and discharged
    over the battery's lifetime, accounting for time value of money.

    Formula:
        LCOS = (CAPEX + Σ(OPEX_t / (1+r)^t)) / Σ(Throughput_t / (1+r)^t)

    Args:
        capex_pln: Initial capital expenditure [PLN]
        annual_opex_pln: Annual operating expenditure [PLN/year]
        annual_throughput_mwh: Annual energy throughput (discharge) [MWh/year]
        discount_rate: Discount rate for NPV calculation [0-1]
        lifetime_years: Battery lifetime [years]

    Returns:
        LCOS [PLN/MWh] or None if throughput is zero.
    """
    if annual_throughput_mwh <= 0:
        logger.warning("Cannot compute LCOS: zero throughput")
        return None

    if lifetime_years <= 0:
        logger.warning("Cannot compute LCOS: invalid lifetime")
        return None

    # NPV of costs: CAPEX + sum of discounted OPEX
    npv_costs = capex_pln
    for year in range(1, lifetime_years + 1):
        discount_factor = 1 / ((1 + discount_rate) ** year)
        npv_costs += annual_opex_pln * discount_factor

    # NPV of throughput: sum of discounted annual throughput
    npv_throughput = 0.0
    for year in range(1, lifetime_years + 1):
        discount_factor = 1 / ((1 + discount_rate) ** year)
        npv_throughput += annual_throughput_mwh * discount_factor

    if npv_throughput <= 0:
        return None

    lcos = npv_costs / npv_throughput

    logger.debug(
        f"LCOS calculation: CAPEX={capex_pln:.0f}, OPEX={annual_opex_pln:.0f}/yr, "
        f"Throughput={annual_throughput_mwh:.2f}MWh/yr, "
        f"Rate={discount_rate:.1%}, Life={lifetime_years}yr -> LCOS={lcos:.2f} PLN/MWh"
    )

    return lcos


def compute_lcos_from_sizing_result(
    capex_pln: float,
    annual_opex_pln: float,
    total_discharge_kwh: float,
    discount_rate: float = 0.08,
    lifetime_years: int = 15,
) -> Optional[float]:
    """
    Compute LCOS from sizing result parameters.

    Convenience wrapper that converts kWh to MWh.

    Args:
        capex_pln: Initial capital expenditure [PLN]
        annual_opex_pln: Annual operating expenditure [PLN/year]
        total_discharge_kwh: Annual discharge energy [kWh/year]
        discount_rate: Discount rate for NPV calculation [0-1]
        lifetime_years: Battery lifetime [years]

    Returns:
        LCOS [PLN/MWh] or None if throughput is zero.
    """
    annual_throughput_mwh = total_discharge_kwh / 1000.0

    return compute_lcos_pln_per_mwh(
        capex_pln=capex_pln,
        annual_opex_pln=annual_opex_pln,
        annual_throughput_mwh=annual_throughput_mwh,
        discount_rate=discount_rate,
        lifetime_years=lifetime_years,
    )


def compute_resilience_score(
    unserved_load_kwh: float,
    total_load_kwh: float,
) -> float:
    """
    Compute resilience score as ratio [0-1].

    Resilience score = 1 - (unserved load / total load)

    A score of 1.0 means all load was served (no outages).
    A score of 0.0 means no load was served.

    Args:
        unserved_load_kwh: Total unserved load due to constraints [kWh]
        total_load_kwh: Total load demand [kWh]

    Returns:
        Resilience score [0-1]. Returns 1.0 if no load (edge case).
    """
    if total_load_kwh <= 0:
        return 1.0  # No load to serve = fully resilient

    if unserved_load_kwh <= 0:
        return 1.0  # All load served

    served_ratio = 1.0 - (unserved_load_kwh / total_load_kwh)
    # Clamp to [0, 1]
    return max(0.0, min(1.0, served_ratio))


def compute_resilience_score_from_dispatch(
    dispatch_result: Union[Dict[str, Any], Any],
    constraint_summary: Optional[Union[Dict[str, Any], Any]] = None,
) -> float:
    """
    Compute resilience score from dispatch result.

    Args:
        dispatch_result: DispatchResult model or dict with total_load_kwh
        constraint_summary: ConstraintSummary model or dict with unserved_load_kwh

    Returns:
        Resilience score [0-1]
    """
    # Get total load
    if isinstance(dispatch_result, dict):
        total_load_kwh = dispatch_result.get("total_load_kwh", 0.0)
    else:
        total_load_kwh = getattr(dispatch_result, "total_load_kwh", 0.0)

    # Get unserved load from constraint summary
    unserved_load_kwh = 0.0
    if constraint_summary is not None:
        if isinstance(constraint_summary, dict):
            unserved_load_kwh = constraint_summary.get("unserved_load_kwh", 0.0)
        else:
            unserved_load_kwh = getattr(constraint_summary, "unserved_load_kwh", 0.0)

    return compute_resilience_score(unserved_load_kwh, total_load_kwh)


def compute_all_driver_metrics(
    dispatch_result: Union[Dict[str, Any], Any],
    constraint_summary: Optional[Union[Dict[str, Any], Any]] = None,
    capex_pln: float = 0.0,
    annual_opex_pln: float = 0.0,
    discount_rate: float = 0.08,
    lifetime_years: int = 15,
) -> Dict[str, Optional[float]]:
    """
    Compute all driver metrics from dispatch result.

    Convenience function to get all metrics in one call.

    Args:
        dispatch_result: DispatchResult model or dict
        constraint_summary: ConstraintSummary model or dict (optional)
        capex_pln: Initial capital expenditure [PLN]
        annual_opex_pln: Annual operating expenditure [PLN/year]
        discount_rate: Discount rate for NPV calculation [0-1]
        lifetime_years: Battery lifetime [years]

    Returns:
        Dict with keys:
        - self_consumption_rate: [0-1]
        - lcos_pln_per_mwh: PLN/MWh or None
        - resilience_score: [0-1]
    """
    # Get discharge for LCOS
    if isinstance(dispatch_result, dict):
        total_discharge_kwh = dispatch_result.get("total_discharge_kwh", 0.0)
    else:
        total_discharge_kwh = getattr(dispatch_result, "total_discharge_kwh", 0.0)

    return {
        "self_consumption_rate": compute_self_consumption_rate_from_dispatch(
            dispatch_result
        ),
        "lcos_pln_per_mwh": compute_lcos_from_sizing_result(
            capex_pln=capex_pln,
            annual_opex_pln=annual_opex_pln,
            total_discharge_kwh=total_discharge_kwh,
            discount_rate=discount_rate,
            lifetime_years=lifetime_years,
        ),
        "resilience_score": compute_resilience_score_from_dispatch(
            dispatch_result,
            constraint_summary,
        ),
    }

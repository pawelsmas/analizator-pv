"""
Duration Sweep Helper (v4.5.0).

Computes duration sweep analysis and marginal metrics.
"""

import logging
from typing import List, Dict, Any, Optional
from models import DurationSweepPoint, MarginalMetrics

logger = logging.getLogger(__name__)


def compute_duration_sweep(
    variants_by_duration: Dict[float, Dict[str, Any]],
) -> List[DurationSweepPoint]:
    """
    Compute duration sweep from variants grouped by duration.

    Args:
        variants_by_duration: {duration_h: {npv_pln, payback_years, self_consumption_rate, lcos, power_kw}}

    Returns:
        List of DurationSweepPoint sorted by duration
    """
    points = []
    for duration_h, metrics in sorted(variants_by_duration.items()):
        points.append(DurationSweepPoint(
            duration_h=duration_h,
            npv_pln=metrics.get("npv_pln", 0.0),
            payback_years=metrics.get("payback_years"),
            self_consumption_rate=metrics.get("self_consumption_rate"),
            lcos_pln_per_mwh=metrics.get("lcos_pln_per_mwh"),
            power_kw=metrics.get("power_kw"),
        ))
    return points


def compute_marginal_metrics(
    sweep_points: List[DurationSweepPoint],
) -> Optional[MarginalMetrics]:
    """
    Compute marginal value metrics from duration sweep.

    Calculates how much additional value each kWh of capacity adds.
    """
    if len(sweep_points) < 2:
        return None

    # Sort by duration
    sorted_points = sorted(sweep_points, key=lambda p: p.duration_h)

    # Calculate marginals between consecutive points
    marginal_npvs = []
    marginal_sc = []

    for i in range(1, len(sorted_points)):
        prev = sorted_points[i - 1]
        curr = sorted_points[i]

        # Assume same power, so energy diff = power * duration_diff
        if curr.power_kw and prev.power_kw:
            power = (curr.power_kw + prev.power_kw) / 2
            energy_diff = power * (curr.duration_h - prev.duration_h)

            if energy_diff > 0:
                npv_diff = curr.npv_pln - prev.npv_pln
                marginal_npvs.append(npv_diff / energy_diff)

                if curr.self_consumption_rate and prev.self_consumption_rate:
                    sc_diff = curr.self_consumption_rate - prev.self_consumption_rate
                    marginal_sc.append(sc_diff / energy_diff)

    return MarginalMetrics(
        marginal_npv_pln_per_added_kwh=sum(marginal_npvs) / len(marginal_npvs) if marginal_npvs else None,
        marginal_self_consumption_pct_per_added_kwh=sum(marginal_sc) / len(marginal_sc) if marginal_sc else None,
    )


def build_duration_sweep_response(
    variants: List[Dict[str, Any]],
    include_marginal: bool = True,
) -> Dict[str, Any]:
    """
    Build complete duration sweep response.

    Args:
        variants: List of variant dicts with duration_h, npv_pln, etc.
        include_marginal: Whether to compute marginal metrics

    Returns:
        Dict with duration_sweep and marginal_metrics
    """
    # Group best variant per duration
    by_duration = {}
    for v in variants:
        d = v.get("duration_h", 1.0)
        if d not in by_duration or v.get("npv_pln", 0) > by_duration[d].get("npv_pln", 0):
            by_duration[d] = v

    sweep = compute_duration_sweep(by_duration)

    response = {
        "duration_sweep": [
            {
                "duration_h": p.duration_h,
                "npv_pln": p.npv_pln,
                "payback_years": p.payback_years,
                "self_consumption_rate": p.self_consumption_rate,
                "lcos_pln_per_mwh": p.lcos_pln_per_mwh,
            }
            for p in sweep
        ],
    }

    if include_marginal:
        marginal = compute_marginal_metrics(sweep)
        if marginal:
            response["marginal_metrics"] = {
                "marginal_npv_pln_per_added_kwh": marginal.marginal_npv_pln_per_added_kwh,
                "marginal_self_consumption_pct_per_added_kwh": marginal.marginal_self_consumption_pct_per_added_kwh,
            }

    return response

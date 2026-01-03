"""
Recommendations Builder (v4.5.0).

Builds structured recommendations per driver/objective.

This module is the SINGLE SOURCE OF TRUTH for:
- Building DriverRecommendation objects for each objective
- Generating structured reason descriptions
- Collecting all recommendations for response

The output recommendations[] array enables UI to show
"Recommended by: NPV, Self-consumption, LCOS" per variant.
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from models import (
    DriverRecommendation,
    OptimizationObjective,
    RecommendedReasonCode,
    RecommendationPolicy,
)
from scoring_policy_helper import ScoredVariant, select_with_policy

logger = logging.getLogger(__name__)


# Objective to reason code mapping
OBJECTIVE_REASON_CODES = {
    "npv": RecommendedReasonCode.NPV_MAX,
    "irr": RecommendedReasonCode.IRR_MAX,
    "payback": RecommendedReasonCode.PAYBACK_MIN,
    "self_consumption": RecommendedReasonCode.SELF_CONSUMPTION_MAX,
    "self_consumption_rate": RecommendedReasonCode.SELF_CONSUMPTION_MAX,
    "peak_reduction": RecommendedReasonCode.PEAK_REDUCTION_MAX,
    "efc_utilization": RecommendedReasonCode.EFC_UTILIZATION_MAX,
    "lcos": RecommendedReasonCode.LCOS_MIN,
    "lcoe": RecommendedReasonCode.LCOS_MIN,
    "resilience": RecommendedReasonCode.RESILIENCE_MAX,
}

# Metric names for each objective
OBJECTIVE_METRICS = {
    "npv": ("npv_pln", "PLN"),
    "irr": ("irr_pct", "%"),
    "payback": ("payback_years", "years"),
    "self_consumption": ("self_consumption_rate", "ratio"),
    "self_consumption_rate": ("self_consumption_rate", "ratio"),
    "peak_reduction": ("peak_reduction_kw", "kW"),
    "lcos": ("lcos_pln_per_mwh", "PLN/MWh"),
    "lcoe": ("lcos_pln_per_mwh", "PLN/MWh"),
    "resilience": ("resilience_score", "ratio"),
}


def get_metric_value_from_variant(
    variant: ScoredVariant,
    metric_name: str,
) -> Optional[float]:
    """Get metric value from ScoredVariant."""
    return getattr(variant, metric_name, None)


def build_recommendation_for_objective(
    winner: ScoredVariant,
    objective: str,
    selection_meta: Dict[str, Any],
) -> DriverRecommendation:
    """
    Build a DriverRecommendation for a specific objective.

    Args:
        winner: The winning variant for this objective
        objective: Objective name (npv, lcos, etc.)
        selection_meta: Metadata from select_with_policy

    Returns:
        DriverRecommendation object
    """
    # Get metric info
    metric_name, unit = OBJECTIVE_METRICS.get(objective, ("npv_pln", "PLN"))
    metric_value = get_metric_value_from_variant(winner, metric_name)

    # Determine reason code
    is_near_optimal = selection_meta.get("is_near_optimal", False)
    if is_near_optimal:
        reason_code = RecommendedReasonCode.NPV_NEAR_OPTIMAL_TIE_BREAK.value
    else:
        reason_code = OBJECTIVE_REASON_CODES.get(
            objective, RecommendedReasonCode.NPV_MAX
        ).value

    return DriverRecommendation(
        objective=objective,
        variant=winner.variant_id,
        variant_label=f"{winner.power_kw:.0f}kW/{winner.duration_h}h",
        reason_code=reason_code,
        reason_metric=metric_name,
        reason_value=metric_value or 0.0,
        reason_unit=unit,
        is_near_optimal=is_near_optimal,
        tie_breaker_used=selection_meta.get("tie_breaker_used"),
    )


def build_recommendations_for_all_objectives(
    variants: List[ScoredVariant],
    objectives: List[str] = None,
    policy: Optional[RecommendationPolicy] = None,
) -> List[DriverRecommendation]:
    """
    Build recommendations for all specified objectives.

    Args:
        variants: List of scored variants
        objectives: List of objectives to evaluate (default: all)
        policy: RecommendationPolicy for tie-breaking

    Returns:
        List of DriverRecommendation, one per objective
    """
    if not variants:
        return []

    if objectives is None:
        # Default objectives
        objectives = ["npv", "self_consumption", "payback", "lcos", "resilience"]

    if policy is None:
        policy = RecommendationPolicy()

    recommendations = []

    for objective in objectives:
        winner, meta = select_with_policy(
            variants=variants,
            primary_objective=objective,
            tolerance_pct=policy.near_optimal_tolerance_pct,
            tie_breakers=policy.tie_breakers,
            min_npv_pln=policy.min_npv_pln,
        )

        if winner:
            rec = build_recommendation_for_objective(winner, objective, meta)
            recommendations.append(rec)
            logger.debug(
                f"Recommendation for {objective}: {winner.variant_id} "
                f"({rec.reason_code}, near_optimal={rec.is_near_optimal})"
            )

    return recommendations


def group_recommendations_by_variant(
    recommendations: List[DriverRecommendation],
) -> Dict[str, List[str]]:
    """
    Group recommendations by variant ID.

    Returns dict mapping variant_id -> list of objectives that recommend it.

    Example:
        {"medium_2h": ["npv", "self_consumption"], "small_1h": ["payback"]}
    """
    grouped = {}
    for rec in recommendations:
        if rec.variant not in grouped:
            grouped[rec.variant] = []
        grouped[rec.variant].append(rec.objective)
    return grouped


def get_consensus_variant(
    recommendations: List[DriverRecommendation],
) -> Optional[str]:
    """
    Find variant recommended by most objectives.

    Returns variant_id or None if no recommendations.
    """
    if not recommendations:
        return None

    grouped = group_recommendations_by_variant(recommendations)

    # Sort by count descending
    sorted_variants = sorted(
        grouped.items(),
        key=lambda x: len(x[1]),
        reverse=True
    )

    return sorted_variants[0][0] if sorted_variants else None


def build_recommendation_summary(
    recommendations: List[DriverRecommendation],
) -> Dict[str, Any]:
    """
    Build summary of all recommendations.

    Returns dict with:
    - total_objectives: Number of objectives evaluated
    - recommendations_by_variant: {variant_id: [objectives]}
    - consensus_variant: Most recommended variant
    - unique_variants: Number of distinct recommended variants
    """
    grouped = group_recommendations_by_variant(recommendations)

    return {
        "total_objectives": len(recommendations),
        "recommendations_by_variant": grouped,
        "consensus_variant": get_consensus_variant(recommendations),
        "unique_variants": len(grouped),
    }


@dataclass
class RecommendationsResponse:
    """Full recommendations response for sizing result."""
    recommendations: List[DriverRecommendation]
    summary: Dict[str, Any]
    policy_used: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "recommendations": [
                {
                    "objective": r.objective,
                    "variant": r.variant,
                    "variant_label": r.variant_label,
                    "reason_code": r.reason_code,
                    "reason_metric": r.reason_metric,
                    "reason_value": r.reason_value,
                    "reason_unit": r.reason_unit,
                    "is_near_optimal": r.is_near_optimal,
                    "tie_breaker_used": r.tie_breaker_used,
                }
                for r in self.recommendations
            ],
            "summary": self.summary,
            "policy_used": self.policy_used,
        }


def build_full_recommendations_response(
    variants: List[ScoredVariant],
    objectives: List[str] = None,
    policy: Optional[RecommendationPolicy] = None,
) -> RecommendationsResponse:
    """
    Build complete recommendations response.

    Args:
        variants: List of scored variants
        objectives: List of objectives to evaluate
        policy: RecommendationPolicy for tie-breaking

    Returns:
        RecommendationsResponse with recommendations, summary, and policy
    """
    if policy is None:
        policy = RecommendationPolicy()

    recommendations = build_recommendations_for_all_objectives(
        variants=variants,
        objectives=objectives,
        policy=policy,
    )

    summary = build_recommendation_summary(recommendations)

    policy_dict = {
        "near_optimal_tolerance_pct": policy.near_optimal_tolerance_pct,
        "tie_breakers": policy.tie_breakers,
        "min_npv_pln": policy.min_npv_pln,
    }

    return RecommendationsResponse(
        recommendations=recommendations,
        summary=summary,
        policy_used=policy_dict,
    )

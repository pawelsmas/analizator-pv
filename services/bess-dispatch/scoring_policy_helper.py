"""
Scoring Policy Helper (v4.5.0).

Implements objective scoring and near-optimal NPV tie-breaker policy.

This module is the SINGLE SOURCE OF TRUTH for:
- Scoring variants by different objectives
- Finding near-optimal variants within tolerance
- Applying tie-breaker rules to select best variant

The tie-breaker policy solves the "always 1h" problem by allowing
selection of higher-duration variants when NPV difference is minimal.
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ScoredVariant:
    """A variant with its scores for different objectives."""
    variant_id: str
    power_kw: float
    duration_h: float
    energy_kwh: float

    # Core metrics
    npv_pln: float
    irr_pct: Optional[float]
    payback_years: Optional[float]
    capex_pln: float

    # Driver metrics
    self_consumption_rate: float  # [0-1]
    peak_reduction_kw: float
    lcos_pln_per_mwh: Optional[float]
    resilience_score: float  # [0-1]

    # Computed scores (normalized 0-100)
    scores: Dict[str, float] = None

    def __post_init__(self):
        if self.scores is None:
            self.scores = {}


# Objectives where higher is better
MAXIMIZE_OBJECTIVES = {
    "npv", "irr", "self_consumption", "self_consumption_rate",
    "peak_reduction", "efc_utilization", "resilience"
}

# Objectives where lower is better
MINIMIZE_OBJECTIVES = {
    "payback", "lcos", "lcoe"
}

# Tie-breaker metrics: direction (True = higher is better)
TIE_BREAKER_DIRECTIONS = {
    "self_consumption_rate": True,
    "payback_years": False,  # Lower is better
    "peak_reduction_kw": True,
    "npv_pln": True,
    "irr_pct": True,
    "lcos_pln_per_mwh": False,  # Lower is better
    "duration_h": True,  # Prefer longer duration as tie-breaker
    "capex_pln": False,  # Lower is better
    "net_savings_pln": True,
    "resilience_unserved_load_kwh": False,  # Lower is better
}


def get_metric_value(variant: ScoredVariant, metric: str) -> Optional[float]:
    """
    Get metric value from a scored variant.

    Args:
        variant: ScoredVariant instance
        metric: Metric name (e.g., "self_consumption_rate", "npv_pln")

    Returns:
        Metric value or None if not available
    """
    # Map metric names to attributes
    metric_map = {
        "self_consumption_rate": "self_consumption_rate",
        "payback_years": "payback_years",
        "peak_reduction_kw": "peak_reduction_kw",
        "npv_pln": "npv_pln",
        "irr_pct": "irr_pct",
        "lcos_pln_per_mwh": "lcos_pln_per_mwh",
        "duration_h": "duration_h",
        "capex_pln": "capex_pln",
        "resilience_score": "resilience_score",
        "resilience_unserved_load_kwh": None,  # Computed from score
    }

    attr = metric_map.get(metric)
    if attr is None:
        return None

    return getattr(variant, attr, None)


def score_by_objective(
    variants: List[ScoredVariant],
    objective: str,
) -> List[ScoredVariant]:
    """
    Score variants by a specific objective (0-100 scale).

    Higher score = better for the objective.

    Args:
        variants: List of ScoredVariant to score
        objective: Objective name (npv, irr, payback, lcos, etc.)

    Returns:
        Same variants with scores[objective] populated
    """
    if not variants:
        return variants

    # Determine which metric to use
    metric_map = {
        "npv": "npv_pln",
        "irr": "irr_pct",
        "payback": "payback_years",
        "self_consumption": "self_consumption_rate",
        "self_consumption_rate": "self_consumption_rate",
        "peak_reduction": "peak_reduction_kw",
        "lcos": "lcos_pln_per_mwh",
        "lcoe": "lcos_pln_per_mwh",
        "resilience": "resilience_score",
    }

    metric = metric_map.get(objective)
    if not metric:
        logger.warning(f"Unknown objective: {objective}")
        return variants

    # Get values (filter None)
    values = []
    for v in variants:
        val = getattr(v, metric, None)
        if val is not None:
            values.append(val)

    if not values:
        return variants

    min_val = min(values)
    max_val = max(values)
    range_val = max_val - min_val if max_val != min_val else 1.0

    # Score: normalize to 0-100
    is_minimize = objective in MINIMIZE_OBJECTIVES

    for v in variants:
        val = getattr(v, metric, None)
        if val is None:
            v.scores[objective] = 0.0
            continue

        if is_minimize:
            # Lower is better: invert score
            normalized = 1.0 - (val - min_val) / range_val
        else:
            # Higher is better
            normalized = (val - min_val) / range_val

        v.scores[objective] = normalized * 100.0

    return variants


def find_best_by_objective(
    variants: List[ScoredVariant],
    objective: str,
) -> Optional[ScoredVariant]:
    """
    Find the best variant for a specific objective.

    Args:
        variants: List of ScoredVariant (should be scored already)
        objective: Objective name

    Returns:
        Best variant or None if empty
    """
    if not variants:
        return None

    # Ensure scored
    variants = score_by_objective(variants, objective)

    return max(variants, key=lambda v: v.scores.get(objective, 0.0))


def find_near_optimal_variants(
    variants: List[ScoredVariant],
    primary_objective: str,
    tolerance_pct: float = 5.0,
) -> List[ScoredVariant]:
    """
    Find variants within tolerance of the best.

    Args:
        variants: List of ScoredVariant
        primary_objective: Primary objective for near-optimal calculation
        tolerance_pct: Tolerance percentage (e.g., 5% from best)

    Returns:
        List of near-optimal variants
    """
    if not variants:
        return []

    # Score by primary objective
    variants = score_by_objective(variants, primary_objective)

    # Find best score
    best_score = max(v.scores.get(primary_objective, 0.0) for v in variants)

    if best_score <= 0:
        return variants  # All equally bad

    # Threshold: within tolerance_pct of best
    threshold = best_score * (1 - tolerance_pct / 100.0)

    near_optimal = [
        v for v in variants
        if v.scores.get(primary_objective, 0.0) >= threshold
    ]

    logger.debug(
        f"Near-optimal: {len(near_optimal)}/{len(variants)} variants "
        f"within {tolerance_pct}% of best {primary_objective}"
    )

    return near_optimal


def apply_tie_breaker(
    variants: List[ScoredVariant],
    tie_breaker: str,
) -> Optional[ScoredVariant]:
    """
    Apply a single tie-breaker to select from variants.

    Args:
        variants: List of near-optimal variants
        tie_breaker: Tie-breaker metric name

    Returns:
        Winner variant or None
    """
    if not variants:
        return None

    if len(variants) == 1:
        return variants[0]

    # Get direction
    higher_is_better = TIE_BREAKER_DIRECTIONS.get(tie_breaker, True)

    # Filter variants with valid tie-breaker value
    valid_variants = []
    for v in variants:
        val = get_metric_value(v, tie_breaker)
        if val is not None:
            valid_variants.append((v, val))

    if not valid_variants:
        return variants[0]  # Fallback to first

    # Sort by tie-breaker
    if higher_is_better:
        valid_variants.sort(key=lambda x: x[1], reverse=True)
    else:
        valid_variants.sort(key=lambda x: x[1])

    winner = valid_variants[0][0]
    winner_val = valid_variants[0][1]

    logger.debug(
        f"Tie-breaker '{tie_breaker}' selected {winner.variant_id} "
        f"(value={winner_val:.2f})"
    )

    return winner


def select_with_policy(
    variants: List[ScoredVariant],
    primary_objective: str = "npv",
    tolerance_pct: float = 5.0,
    tie_breakers: List[str] = None,
    min_npv_pln: Optional[float] = None,
) -> Tuple[Optional[ScoredVariant], Dict[str, Any]]:
    """
    Select best variant using recommendation policy.

    Process:
    1. Filter by min_npv_pln if specified
    2. Find near-optimal variants within tolerance
    3. Apply tie-breakers in order
    4. Return winner with selection metadata

    Args:
        variants: List of ScoredVariant
        primary_objective: Primary optimization objective
        tolerance_pct: Near-optimal tolerance (%)
        tie_breakers: Ordered list of tie-breaker metrics
        min_npv_pln: Minimum NPV constraint

    Returns:
        Tuple of (winner variant, selection metadata dict)
    """
    if tie_breakers is None:
        tie_breakers = ["self_consumption_rate", "payback_years", "peak_reduction_kw"]

    metadata = {
        "primary_objective": primary_objective,
        "tolerance_pct": tolerance_pct,
        "tie_breakers": tie_breakers,
        "total_variants": len(variants),
        "filtered_by_min_npv": 0,
        "near_optimal_count": 0,
        "is_near_optimal": False,
        "tie_breaker_used": None,
        "reason_code": None,
    }

    if not variants:
        return None, metadata

    # Step 1: Filter by min_npv_pln
    if min_npv_pln is not None:
        filtered = [v for v in variants if v.npv_pln >= min_npv_pln]
        metadata["filtered_by_min_npv"] = len(variants) - len(filtered)
        variants = filtered

        if not variants:
            logger.warning(f"All variants filtered by min_npv_pln={min_npv_pln}")
            return None, metadata

    # Step 2: Score and find near-optimal
    variants = score_by_objective(variants, primary_objective)
    near_optimal = find_near_optimal_variants(
        variants, primary_objective, tolerance_pct
    )
    metadata["near_optimal_count"] = len(near_optimal)

    # Step 3: If only one near-optimal, that's the winner
    if len(near_optimal) == 1:
        winner = near_optimal[0]
        metadata["is_near_optimal"] = False  # It's THE optimal
        metadata["reason_code"] = f"{primary_objective}_max" if primary_objective in MAXIMIZE_OBJECTIVES else f"{primary_objective}_min"
        return winner, metadata

    # Step 4: Apply tie-breakers
    candidates = near_optimal
    for tb in tie_breakers:
        if len(candidates) == 1:
            break

        winner = apply_tie_breaker(candidates, tb)
        if winner:
            # Check if this tie-breaker resolved it
            winner_val = get_metric_value(winner, tb)
            others = [v for v in candidates if v != winner]

            if others:
                # Check if winner is actually better
                other_val = get_metric_value(others[0], tb)
                if other_val is not None and winner_val is not None:
                    higher_better = TIE_BREAKER_DIRECTIONS.get(tb, True)
                    if (higher_better and winner_val > other_val) or \
                       (not higher_better and winner_val < other_val):
                        metadata["is_near_optimal"] = True
                        metadata["tie_breaker_used"] = tb
                        metadata["reason_code"] = "npv_near_optimal_tie_break"
                        return winner, metadata

            candidates = [winner]

    # Final selection
    winner = candidates[0] if candidates else near_optimal[0]
    metadata["is_near_optimal"] = len(near_optimal) > 1

    if metadata["is_near_optimal"]:
        metadata["reason_code"] = "npv_near_optimal_tie_break"
        if tie_breakers:
            metadata["tie_breaker_used"] = tie_breakers[0]
    else:
        metadata["reason_code"] = f"{primary_objective}_max" if primary_objective in MAXIMIZE_OBJECTIVES else f"{primary_objective}_min"

    return winner, metadata


def rank_variants_by_objective(
    variants: List[ScoredVariant],
    objective: str,
    top_n: int = 3,
) -> List[Tuple[ScoredVariant, int]]:
    """
    Rank variants by objective and return top N with ranks.

    Args:
        variants: List of ScoredVariant
        objective: Objective to rank by
        top_n: Number of top variants to return

    Returns:
        List of (variant, rank) tuples (rank starts at 1)
    """
    if not variants:
        return []

    variants = score_by_objective(variants, objective)
    sorted_variants = sorted(
        variants,
        key=lambda v: v.scores.get(objective, 0.0),
        reverse=True
    )

    return [(v, i + 1) for i, v in enumerate(sorted_variants[:top_n])]

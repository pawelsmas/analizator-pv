"""
Determinism helpers for reproducible variant selection.

Provides deterministic tie-breaking when multiple variants have equal scores:
1. Higher npv_pln wins
2. If NPV equal: lower capex_pln wins
3. If CAPEX equal: alphabetically by variant name

v1.6.0: Added for determinism and correctness freeze.
"""

from typing import Any, Callable, List, Optional, Tuple

# Tolerance for score comparison (scores within this range are considered equal)
SCORE_EPSILON = 1e-9


def variant_sort_key(
    variant: Any,
    score_getter: Callable[[Any], float],
    npv_getter: Callable[[Any], float],
    capex_getter: Callable[[Any], float],
    name_getter: Callable[[Any], str],
) -> Tuple[float, float, float, str]:
    """
    Create a deterministic sort key for variant selection.

    Sort order (all descending except name):
    1. score (higher is better)
    2. npv_pln (higher is better) - tie-breaker #1
    3. -capex_pln (lower is better) - tie-breaker #2
    4. variant name (alphabetically) - tie-breaker #3

    Args:
        variant: The variant object
        score_getter: Function to get score from variant
        npv_getter: Function to get NPV from variant
        capex_getter: Function to get CAPEX from variant
        name_getter: Function to get variant name from variant

    Returns:
        Tuple for sorting: (score, npv, -capex, name)
        Use with reverse=True for max selection
    """
    score = score_getter(variant)
    npv = npv_getter(variant)
    capex = capex_getter(variant)
    name = name_getter(variant)

    # Return tuple for deterministic sorting:
    # - score descending (negate for min-first sort)
    # - npv descending (negate for min-first sort)
    # - capex ascending (keep as-is for min-first sort)
    # - name ascending (alphabetically)
    return (-score, -npv, capex, name)


def select_best_variant_deterministic(
    variants: List[Any],
    score_getter: Callable[[Any], float],
    npv_getter: Callable[[Any], float],
    capex_getter: Callable[[Any], float],
    name_getter: Callable[[Any], str],
    filter_fn: Optional[Callable[[Any], bool]] = None,
) -> Optional[int]:
    """
    Select the best variant index using deterministic tie-breaking.

    When scores are equal (within SCORE_EPSILON), applies tie-breakers:
    1. Higher NPV wins
    2. If NPV equal: lower CAPEX wins
    3. If CAPEX equal: alphabetically by variant name

    Args:
        variants: List of variant objects
        score_getter: Function to get score from variant
        npv_getter: Function to get NPV from variant
        capex_getter: Function to get CAPEX from variant
        name_getter: Function to get variant name from variant
        filter_fn: Optional filter function (only consider variants where this returns True)

    Returns:
        Index of the best variant, or None if no variants match filter
    """
    if not variants:
        return None

    # Build list of (index, variant) pairs that pass the filter
    candidates = []
    for idx, v in enumerate(variants):
        if filter_fn is None or filter_fn(v):
            candidates.append((idx, v))

    if not candidates:
        return None

    # Sort using deterministic key (min-first, so best is first)
    candidates.sort(
        key=lambda iv: variant_sort_key(
            iv[1], score_getter, npv_getter, capex_getter, name_getter
        )
    )

    # Return index of best variant
    return candidates[0][0]


def scores_are_equal(score_a: float, score_b: float, epsilon: float = SCORE_EPSILON) -> bool:
    """
    Check if two scores are effectively equal within tolerance.

    Args:
        score_a: First score
        score_b: Second score
        epsilon: Tolerance for equality comparison

    Returns:
        True if scores are within epsilon of each other
    """
    return abs(score_a - score_b) < epsilon

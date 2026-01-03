"""
Variant Space Helper (v4.5.0).

Generates power x duration grid for BESS sizing optimization.

This module is the SINGLE SOURCE OF TRUTH for:
- Converting VariantSpace config to concrete power x duration pairs
- Computing grid size and validating against limits
- Generating variant names/labels for the grid

The variant space allows explicit specification of the sizing search space,
enabling smarter recommendations by evaluating more duration options.
"""

import logging
from typing import List, Tuple, Optional, Dict, Any
import numpy as np

from models import VariantSpace, SizingVariant

logger = logging.getLogger(__name__)


# Default durations if not specified
DEFAULT_DURATIONS_H = [1.0, 2.0, 4.0]

# Duration to variant enum mapping (for standard durations)
DURATION_TO_VARIANT = {
    1.0: SizingVariant.SMALL,
    2.0: SizingVariant.MEDIUM,
    4.0: SizingVariant.LARGE,
}

# Variant labels for each duration
DURATION_LABELS = {
    1.0: ("small", "Small (1h)"),
    2.0: ("medium", "Medium (2h)"),
    4.0: ("large", "Large (4h)"),
}


def compute_grid_size(
    power_candidates: List[float],
    duration_candidates: List[float],
) -> int:
    """
    Compute the total number of variants in the grid.

    Args:
        power_candidates: List of power values [kW]
        duration_candidates: List of duration values [hours]

    Returns:
        Total number of variants (power x duration)
    """
    return len(power_candidates) * len(duration_candidates)


def validate_grid_size(
    power_candidates: List[float],
    duration_candidates: List[float],
    max_variants: int = 60,
) -> Tuple[bool, Optional[str]]:
    """
    Validate that grid size is within limits.

    Args:
        power_candidates: List of power values [kW]
        duration_candidates: List of duration values [hours]
        max_variants: Maximum allowed variants

    Returns:
        Tuple of (is_valid, error_message)
    """
    grid_size = compute_grid_size(power_candidates, duration_candidates)

    if grid_size > max_variants:
        return False, (
            f"Variant grid size ({grid_size}) exceeds max_variants ({max_variants}). "
            f"Reduce power_kw_candidates ({len(power_candidates)}) or "
            f"duration_h_candidates ({len(duration_candidates)})."
        )

    if grid_size == 0:
        return False, "Variant grid is empty. Need at least one power and one duration."

    return True, None


def generate_power_candidates(
    p_min: float,
    p_max: float,
    power_steps: int = 10,
) -> List[float]:
    """
    Generate power candidates for grid search.

    Args:
        p_min: Minimum power [kW]
        p_max: Maximum power [kW]
        power_steps: Number of steps

    Returns:
        List of power values [kW]
    """
    if p_min >= p_max:
        return [p_min]

    if power_steps <= 1:
        return [p_min, p_max]

    return list(np.linspace(p_min, p_max, power_steps))


def get_variant_name(power_kw: float, duration_h: float) -> str:
    """
    Generate a variant name for a power x duration combination.

    Args:
        power_kw: Power [kW]
        duration_h: Duration [hours]

    Returns:
        Variant name (e.g., "100kW_2h")
    """
    return f"{int(power_kw)}kW_{duration_h}h"


def get_variant_label(power_kw: float, duration_h: float) -> str:
    """
    Generate a human-readable label for a variant.

    Uses standard labels for 1h/2h/4h, custom format for others.

    Args:
        power_kw: Power [kW]
        duration_h: Duration [hours]

    Returns:
        Human-readable label (e.g., "Medium (2h) 100kW")
    """
    if duration_h in DURATION_LABELS:
        _, base_label = DURATION_LABELS[duration_h]
        return f"{base_label} {int(power_kw)}kW"

    # Custom duration format
    return f"Custom ({duration_h}h) {int(power_kw)}kW"


def get_variant_enum(duration_h: float) -> SizingVariant:
    """
    Map duration to SizingVariant enum.

    Args:
        duration_h: Duration [hours]

    Returns:
        SizingVariant enum value
    """
    if duration_h in DURATION_TO_VARIANT:
        return DURATION_TO_VARIANT[duration_h]

    # For non-standard durations, pick closest
    if duration_h <= 1.5:
        return SizingVariant.SMALL
    elif duration_h <= 3.0:
        return SizingVariant.MEDIUM
    else:
        return SizingVariant.LARGE


def generate_variant_space(
    variant_space_config: Optional[VariantSpace] = None,
    p_min: float = None,
    p_max: float = None,
    power_steps: int = 10,
    default_durations: List[float] = None,
) -> Tuple[List[Tuple[float, float]], List[str], Dict[str, Any]]:
    """
    Generate the complete variant space (power x duration grid).

    If variant_space_config is provided, uses its explicit power/duration lists.
    Otherwise, generates power candidates from p_min/p_max/steps.

    Args:
        variant_space_config: Optional explicit VariantSpace configuration
        p_min: Minimum power for auto-generation [kW]
        p_max: Maximum power for auto-generation [kW]
        power_steps: Number of power steps for auto-generation
        default_durations: Default durations if none specified

    Returns:
        Tuple of:
        - List of (power_kw, duration_h) pairs
        - List of variant names
        - Metadata dict with grid_size, durations, etc.

    Raises:
        ValueError: If grid size exceeds max_variants
    """
    if default_durations is None:
        default_durations = DEFAULT_DURATIONS_H

    # Determine power candidates
    if variant_space_config and variant_space_config.power_kw_candidates:
        power_candidates = sorted(variant_space_config.power_kw_candidates)
    elif p_min is not None and p_max is not None:
        power_candidates = generate_power_candidates(p_min, p_max, power_steps)
    else:
        raise ValueError("Must provide either power_kw_candidates or p_min/p_max")

    # Determine duration candidates
    if variant_space_config:
        duration_candidates = sorted(variant_space_config.duration_h_candidates)
        max_variants = variant_space_config.max_variants
    else:
        duration_candidates = sorted(default_durations)
        max_variants = 60  # Default limit

    # Validate grid size
    is_valid, error_msg = validate_grid_size(
        power_candidates, duration_candidates, max_variants
    )
    if not is_valid:
        raise ValueError(error_msg)

    # Generate grid
    variants = []
    variant_names = []

    for duration_h in duration_candidates:
        for power_kw in power_candidates:
            variants.append((power_kw, duration_h))
            variant_names.append(get_variant_name(power_kw, duration_h))

    # Metadata
    metadata = {
        "grid_size": len(variants),
        "power_count": len(power_candidates),
        "duration_count": len(duration_candidates),
        "power_range_kw": (min(power_candidates), max(power_candidates)),
        "durations_h": duration_candidates,
        "max_variants": max_variants,
        "is_explicit_power": bool(
            variant_space_config and variant_space_config.power_kw_candidates
        ),
    }

    logger.info(
        f"Generated variant space: {metadata['grid_size']} variants "
        f"({metadata['power_count']} powers x {metadata['duration_count']} durations)"
    )

    return variants, variant_names, metadata


def get_variant_info_for_result(
    power_kw: float,
    duration_h: float,
) -> Dict[str, Any]:
    """
    Get variant metadata for including in sizing result.

    Args:
        power_kw: Power [kW]
        duration_h: Duration [hours]

    Returns:
        Dict with variant, variant_label, duration_h
    """
    return {
        "variant": get_variant_enum(duration_h).value,
        "variant_label": get_variant_label(power_kw, duration_h),
        "variant_name": get_variant_name(power_kw, duration_h),
        "duration_h": duration_h,
    }


def filter_variants_by_constraint(
    variants: List[Tuple[float, float]],
    max_capex_pln: Optional[float] = None,
    capex_per_kwh: float = 2000.0,
) -> List[Tuple[float, float]]:
    """
    Filter variants by CAPEX constraint.

    Args:
        variants: List of (power_kw, duration_h) pairs
        max_capex_pln: Maximum CAPEX constraint [PLN]
        capex_per_kwh: CAPEX per kWh [PLN/kWh]

    Returns:
        Filtered list of variants
    """
    if max_capex_pln is None:
        return variants

    filtered = []
    for power_kw, duration_h in variants:
        energy_kwh = power_kw * duration_h
        estimated_capex = energy_kwh * capex_per_kwh

        if estimated_capex <= max_capex_pln:
            filtered.append((power_kw, duration_h))

    logger.info(
        f"Filtered variants by CAPEX: {len(filtered)}/{len(variants)} "
        f"(max_capex={max_capex_pln:.0f} PLN)"
    )

    return filtered

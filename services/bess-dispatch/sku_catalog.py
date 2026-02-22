"""
SKU Catalog - Snap-to-Market for BESS Products
===============================================

Hardcoded catalog of available BESS products (PCS and battery modules).
Provides snap_to_sku() function to map continuous optimization results
to real market products.

Version: 1.0.0
"""

import math
from typing import List, Tuple, Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum


class Manufacturer(str, Enum):
    """Supported manufacturers (for future expansion)"""
    GENERIC = "generic"
    # Add specific manufacturers as needed


@dataclass
class PCSProduct:
    """Power Conditioning System (inverter) product"""
    power_kw: float
    model_name: str
    manufacturer: Manufacturer = Manufacturer.GENERIC
    min_battery_kwh: Optional[float] = None  # Min compatible battery size
    max_battery_kwh: Optional[float] = None  # Max compatible battery size
    max_c_rate: float = 1.0  # Maximum C-rate supported


@dataclass
class BatteryModule:
    """Battery module product"""
    energy_kwh: float
    model_name: str
    manufacturer: Manufacturer = Manufacturer.GENERIC
    max_c_rate: float = 1.0  # Maximum discharge C-rate


@dataclass
class SnappedSKU:
    """Result of snap-to-SKU operation"""
    # Snapped values
    power_kw: float
    energy_kwh: float
    duration_h: float
    c_rate: float

    # Product details
    pcs_model: str
    battery_config: str  # e.g., "2x 51.2 kWh"
    n_battery_modules: int

    # Original vs snapped delta
    original_power_kw: float
    original_energy_kwh: float
    power_delta_pct: float  # Positive = snapped up
    energy_delta_pct: float

    # Economics impact
    capex_delta_pln: float  # Additional CAPEX due to snapping

    # Warnings
    warnings: List[str]


# =============================================================================
# HARDCODED SKU CATALOG
# =============================================================================

# Available PCS (Power Conditioning System) power ratings [kW]
# Standard commercial and industrial sizes
PCS_POWER_STEPS_KW: List[float] = [
    25.0,   # Small commercial
    30.0,   # Small commercial
    50.0,   # Medium commercial
    60.0,   # Medium commercial
    100.0,  # Large commercial
    125.0,  # Large commercial
    150.0,  # Industrial
    200.0,  # Industrial
    250.0,  # Industrial
    300.0,  # Large industrial
    500.0,  # Utility-scale
    630.0,  # Utility-scale
    1000.0, # Utility-scale base unit
    # For larger systems, we use multiples of the base unit (1000 kW)
    # Dynamically generated in snap_power_to_sku for utility-scale
]

# Base unit for utility-scale systems (MW-class)
UTILITY_SCALE_BASE_KW: float = 1000.0  # 1 MW base unit for large systems

# Battery module base size [kWh]
BATTERY_MODULE_KWH: float = 51.2  # Standard LFP module

# Alternative smaller module for small systems
BATTERY_MODULE_SMALL_KWH: float = 25.6  # Half-size module

# C-rate limits
DEFAULT_MAX_C_RATE: float = 1.0   # Standard: can discharge full capacity in 1h
DEFAULT_MIN_C_RATE: float = 0.25  # Minimum practical: 4h duration

# Default economics for delta calculation
DEFAULT_CAPEX_PER_KWH: float = 1500.0
DEFAULT_CAPEX_PER_KW: float = 300.0


# =============================================================================
# SNAP-TO-SKU FUNCTIONS
# =============================================================================

def snap_power_to_sku(
    power_kw: float,
    direction: str = "up",
) -> Tuple[float, str]:
    """
    Snap power to nearest available PCS rating.

    For utility-scale systems (>1000 kW), uses multiples of UTILITY_SCALE_BASE_KW.
    This allows scaling to any MW-class system (e.g., 63 MW = 63x 1MW units).

    Args:
        power_kw: Desired power [kW]
        direction: "up" (default, conservative), "down", or "nearest"

    Returns:
        Tuple of (snapped_power_kw, pcs_model_name)
    """
    if power_kw <= 0:
        return PCS_POWER_STEPS_KW[0], f"PCS-{PCS_POWER_STEPS_KW[0]:.0f}kW"

    max_standard = max(PCS_POWER_STEPS_KW)  # 1000 kW

    # For utility-scale systems (>1000 kW), use multiples of base unit
    if power_kw > max_standard:
        if direction == "up":
            n_units = math.ceil(power_kw / UTILITY_SCALE_BASE_KW)
        elif direction == "down":
            n_units = max(1, math.floor(power_kw / UTILITY_SCALE_BASE_KW))
        else:  # nearest
            n_units = max(1, round(power_kw / UTILITY_SCALE_BASE_KW))

        snapped = n_units * UTILITY_SCALE_BASE_KW

        # Format model name for utility-scale
        if snapped >= 1000:
            mw_value = snapped / 1000
            if mw_value == int(mw_value):
                model_name = f"PCS-{int(mw_value)}MW ({n_units}x1MW)"
            else:
                model_name = f"PCS-{mw_value:.1f}MW ({n_units}x1MW)"
        else:
            model_name = f"PCS-{snapped:.0f}kW"

        return snapped, model_name

    # Standard sizes (<=1000 kW)
    if direction == "up":
        # Find smallest PCS >= requested power
        candidates = [p for p in PCS_POWER_STEPS_KW if p >= power_kw]
        if candidates:
            snapped = min(candidates)
        else:
            snapped = max_standard

    elif direction == "down":
        # Find largest PCS <= requested power
        candidates = [p for p in PCS_POWER_STEPS_KW if p <= power_kw]
        if candidates:
            snapped = max(candidates)
        else:
            snapped = PCS_POWER_STEPS_KW[0]

    else:  # nearest
        snapped = min(PCS_POWER_STEPS_KW, key=lambda p: abs(p - power_kw))

    model_name = f"PCS-{snapped:.0f}kW"
    return snapped, model_name


# Utility-scale battery module (container-based)
UTILITY_SCALE_BATTERY_MODULE_KWH: float = 1000.0  # 1 MWh container module


def snap_energy_to_sku(
    energy_kwh: float,
    module_size: float = BATTERY_MODULE_KWH,
    direction: str = "up",
) -> Tuple[float, int, str]:
    """
    Snap energy to nearest multiple of battery module size.

    For utility-scale systems (>10 MWh), automatically uses 1 MWh container modules.

    Args:
        energy_kwh: Desired energy [kWh]
        module_size: Battery module size [kWh] (default 51.2)
        direction: "up" (default, conservative), "down", or "nearest"

    Returns:
        Tuple of (snapped_energy_kwh, n_modules, config_string)
    """
    if energy_kwh <= 0:
        return module_size, 1, f"1x {module_size:.1f} kWh"

    # For utility-scale (>10 MWh), use 1 MWh container modules
    UTILITY_THRESHOLD_KWH = 10000.0  # 10 MWh
    if energy_kwh > UTILITY_THRESHOLD_KWH:
        module_size = UTILITY_SCALE_BATTERY_MODULE_KWH  # 1 MWh

        if direction == "up":
            n_modules = math.ceil(energy_kwh / module_size)
        elif direction == "down":
            n_modules = max(1, math.floor(energy_kwh / module_size))
        else:  # nearest
            n_modules = max(1, round(energy_kwh / module_size))

        snapped = n_modules * module_size

        # Format for utility-scale (MWh)
        mwh_value = snapped / 1000
        if mwh_value == int(mwh_value):
            config = f"{n_modules}x 1MWh ({int(mwh_value)} MWh total)"
        else:
            config = f"{n_modules}x 1MWh ({mwh_value:.1f} MWh total)"

        return snapped, n_modules, config

    # Standard sizing for commercial/industrial (<10 MWh)
    if direction == "up":
        n_modules = math.ceil(energy_kwh / module_size)
    elif direction == "down":
        n_modules = max(1, math.floor(energy_kwh / module_size))
    else:  # nearest
        n_modules = max(1, round(energy_kwh / module_size))

    snapped = n_modules * module_size
    config = f"{n_modules}x {module_size:.1f} kWh"

    return snapped, n_modules, config


def validate_c_rate(
    power_kw: float,
    energy_kwh: float,
    max_c_rate: float = DEFAULT_MAX_C_RATE,
    min_c_rate: float = DEFAULT_MIN_C_RATE,
) -> Tuple[bool, List[str]]:
    """
    Validate C-rate is within acceptable range.

    Args:
        power_kw: System power [kW]
        energy_kwh: System energy [kWh]
        max_c_rate: Maximum allowed C-rate (default 1.0)
        min_c_rate: Minimum practical C-rate (default 0.25)

    Returns:
        Tuple of (is_valid, list_of_warnings)
    """
    warnings = []

    if energy_kwh <= 0:
        return False, ["Energy must be positive"]

    c_rate = power_kw / energy_kwh

    if c_rate > max_c_rate:
        warnings.append(
            f"C-rate ({c_rate:.2f}) exceeds max ({max_c_rate}). "
            f"Consider adding battery modules or reducing PCS power."
        )
        return False, warnings

    if c_rate < min_c_rate:
        warnings.append(
            f"C-rate ({c_rate:.2f}) is very low - duration {1/c_rate:.1f}h. "
            f"Battery may be oversized for the PCS."
        )

    return True, warnings


def snap_to_sku(
    power_kw: float,
    energy_kwh: float,
    capex_per_kwh: float = DEFAULT_CAPEX_PER_KWH,
    capex_per_kw: float = DEFAULT_CAPEX_PER_KW,
    snap_direction: str = "up",
    enforce_c_rate: bool = True,
) -> SnappedSKU:
    """
    Snap continuous optimization result to real market SKU.

    This is the main function for snap-to-market logic.

    Args:
        power_kw: Optimized power [kW]
        energy_kwh: Optimized energy [kWh]
        capex_per_kwh: CAPEX per kWh for delta calculation
        capex_per_kw: CAPEX per kW for delta calculation
        snap_direction: "up" (conservative), "down", or "nearest"
        enforce_c_rate: If True, add modules to satisfy max C-rate

    Returns:
        SnappedSKU with all details

    Example:
        >>> result = snap_to_sku(25.6, 51.2)
        >>> result.power_kw
        30.0
        >>> result.energy_kwh
        51.2
        >>> result.pcs_model
        'PCS-30kW'
    """
    warnings = []

    # Step 1: Snap power to available PCS
    snapped_power, pcs_model = snap_power_to_sku(power_kw, snap_direction)

    # Step 2: Snap energy to module multiples
    # snap_energy_to_sku automatically selects appropriate module size:
    # - Standard modules (51.2 kWh) for <10 MWh systems
    # - Container modules (1 MWh) for utility-scale >10 MWh systems
    # The module_size parameter is just a hint for small systems
    module_size = BATTERY_MODULE_KWH if energy_kwh >= 40 else BATTERY_MODULE_SMALL_KWH
    snapped_energy, n_modules, battery_config = snap_energy_to_sku(
        energy_kwh, module_size, snap_direction
    )

    # Step 3: Validate and adjust for C-rate
    if enforce_c_rate:
        is_valid, c_rate_warnings = validate_c_rate(snapped_power, snapped_energy)
        warnings.extend(c_rate_warnings)

        # If C-rate too high, add battery modules
        if not is_valid:
            min_energy_for_c_rate = snapped_power / DEFAULT_MAX_C_RATE
            snapped_energy, n_modules, battery_config = snap_energy_to_sku(
                min_energy_for_c_rate, module_size, "up"
            )
            # Format warning message appropriately for system size
            if snapped_energy >= 10000:
                warnings.append(
                    f"Energy increased to {snapped_energy/1000:.1f} MWh to satisfy C-rate limit."
                )
            else:
                warnings.append(
                    f"Energy increased to {snapped_energy:.1f} kWh to satisfy C-rate limit."
                )

    # Step 4: Calculate derived values
    duration_h = snapped_energy / snapped_power if snapped_power > 0 else 0
    c_rate = snapped_power / snapped_energy if snapped_energy > 0 else 0

    # Step 5: Calculate deltas
    power_delta_pct = ((snapped_power - power_kw) / power_kw * 100) if power_kw > 0 else 0
    energy_delta_pct = ((snapped_energy - energy_kwh) / energy_kwh * 100) if energy_kwh > 0 else 0

    # CAPEX delta
    original_capex = energy_kwh * capex_per_kwh + power_kw * capex_per_kw
    snapped_capex = snapped_energy * capex_per_kwh + snapped_power * capex_per_kw
    capex_delta = snapped_capex - original_capex

    return SnappedSKU(
        power_kw=snapped_power,
        energy_kwh=snapped_energy,
        duration_h=duration_h,
        c_rate=c_rate,
        pcs_model=pcs_model,
        battery_config=battery_config,
        n_battery_modules=n_modules,
        original_power_kw=power_kw,
        original_energy_kwh=energy_kwh,
        power_delta_pct=power_delta_pct,
        energy_delta_pct=energy_delta_pct,
        capex_delta_pln=capex_delta,
        warnings=warnings,
    )


def get_alternative_skus(
    power_kw: float,
    energy_kwh: float,
    n_alternatives: int = 3,
    capex_per_kwh: float = DEFAULT_CAPEX_PER_KWH,
    capex_per_kw: float = DEFAULT_CAPEX_PER_KW,
) -> List[SnappedSKU]:
    """
    Get alternative SKU configurations around the optimal point.

    Useful for showing user options: "recommended" + "budget" + "premium".

    Args:
        power_kw: Optimal power [kW]
        energy_kwh: Optimal energy [kWh]
        n_alternatives: Number of alternatives to return
        capex_per_kwh: For CAPEX calculation
        capex_per_kw: For CAPEX calculation

    Returns:
        List of SnappedSKU sorted by CAPEX (lowest first)
    """
    alternatives = []

    # Find PCS options around the target
    target_idx = 0
    for i, p in enumerate(PCS_POWER_STEPS_KW):
        if p >= power_kw:
            target_idx = i
            break

    # Get range of PCS options
    start_idx = max(0, target_idx - 1)
    end_idx = min(len(PCS_POWER_STEPS_KW), target_idx + 2)

    for pcs_power in PCS_POWER_STEPS_KW[start_idx:end_idx]:
        # For each PCS, find matching energy (preserve duration)
        target_duration = energy_kwh / power_kw if power_kw > 0 else 2.0
        target_energy = pcs_power * target_duration

        sku = snap_to_sku(
            pcs_power,
            target_energy,
            capex_per_kwh,
            capex_per_kw,
            snap_direction="nearest",
        )
        alternatives.append(sku)

    # Sort by CAPEX and return requested number
    alternatives.sort(key=lambda s: s.power_kw * capex_per_kw + s.energy_kwh * capex_per_kwh)

    return alternatives[:n_alternatives]


def format_sku_for_display(sku: SnappedSKU) -> Dict[str, Any]:
    """
    Format SnappedSKU for JSON/UI display.

    Returns:
        Dictionary suitable for JSON serialization
    """
    return {
        "power_kw": sku.power_kw,
        "energy_kwh": sku.energy_kwh,
        "duration_h": round(sku.duration_h, 1),
        "c_rate": round(sku.c_rate, 2),
        "pcs_model": sku.pcs_model,
        "battery_config": sku.battery_config,
        "n_battery_modules": sku.n_battery_modules,
        "snapping_delta": {
            "original_power_kw": round(sku.original_power_kw, 1),
            "original_energy_kwh": round(sku.original_energy_kwh, 1),
            "power_delta_pct": round(sku.power_delta_pct, 1),
            "energy_delta_pct": round(sku.energy_delta_pct, 1),
            "capex_delta_pln": round(sku.capex_delta_pln, 0),
        },
        "warnings": sku.warnings,
    }


# =============================================================================
# CATALOG INFO
# =============================================================================

def get_catalog_info() -> Dict[str, Any]:
    """
    Get catalog metadata for UI/documentation.

    Returns:
        Dictionary with catalog details
    """
    return {
        "version": "1.0.0",
        "pcs_options": {
            "available_kw": PCS_POWER_STEPS_KW,
            "min_kw": min(PCS_POWER_STEPS_KW),
            "max_kw": max(PCS_POWER_STEPS_KW),
        },
        "battery_modules": {
            "standard_kwh": BATTERY_MODULE_KWH,
            "small_kwh": BATTERY_MODULE_SMALL_KWH,
            "description": "LFP (Lithium Iron Phosphate)",
        },
        "c_rate_limits": {
            "max": DEFAULT_MAX_C_RATE,
            "min": DEFAULT_MIN_C_RATE,
        },
        "snap_policy": "Snap UP to nearest available SKU (conservative)",
    }

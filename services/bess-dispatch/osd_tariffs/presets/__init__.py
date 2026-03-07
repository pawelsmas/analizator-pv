"""
Preset OSD tariff templates for Polish distribution operators.

Contains ready-to-use tariff definitions for common tariff groups:
- C11: Single-zone (flat) tariff
- C12a, G12: Two-zone tariff (peak/off-peak)
- C12b: Three-zone tariff (day/peak/night)

5 OSD operators × 4 tariff groups × 3 years (2024-2026) = 60 presets.
Operators: PGE, Tauron, Energa, Enea, Stoen.
"""

from .templates import (
    # Template factories
    create_c11_template,
    create_c12a_template,
    create_c12b_template,
    create_c22_template,
    create_g12_template,
    # All presets registry
    ALL_PRESETS,
    TARIFF_ALIASES,
    get_preset_by_id,
    list_presets,
)

__all__ = [
    "create_c11_template",
    "create_c12a_template",
    "create_c12b_template",
    "create_c22_template",
    "create_g12_template",
    "ALL_PRESETS",
    "TARIFF_ALIASES",
    "get_preset_by_id",
    "list_presets",
]

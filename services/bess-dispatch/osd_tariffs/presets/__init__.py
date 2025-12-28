"""
Preset OSD tariff templates for Polish distribution operators.

Contains ready-to-use tariff definitions for common tariff groups:
- C11: Single-zone (flat) tariff
- C12a, G12: Two-zone tariff (peak/off-peak)
- C12b, C22: Three-zone tariff (day/peak/night)
- C24: Four-zone tariff (rare, complex)

Each template provides structure only - rates must be filled from
actual OSD tariff sheets (cenniki).
"""

from .templates import (
    # Template factories
    create_c11_template,
    create_c12a_template,
    create_c12b_template,
    create_c22_template,
    create_g12_template,
    # Pre-built examples
    PGE_C12A_2025,
    TAURON_C12A_2025,
    ENERGA_G12_2025,
    # All presets
    ALL_PRESETS,
    get_preset_by_id,
    list_presets,
)

__all__ = [
    "create_c11_template",
    "create_c12a_template",
    "create_c12b_template",
    "create_c22_template",
    "create_g12_template",
    "PGE_C12A_2025",
    "TAURON_C12A_2025",
    "ENERGA_G12_2025",
    "ALL_PRESETS",
    "get_preset_by_id",
    "list_presets",
]

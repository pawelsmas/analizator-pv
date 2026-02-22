"""
OSD Tariff templates for Polish distribution operators.

These templates provide the TIME STRUCTURE of tariffs - when each zone
is active. Rates (ceny) must be filled from actual OSD tariff sheets.

Common Polish tariff structures:

C11 - Flat (single zone)
    - No time differentiation
    - Same rate 24/7

C12a / G12 - Two zones (szczyt/pozaszczyt)
    - Szczyt (peak): 6:00-13:00, 15:00-22:00 (workdays)
    - Pozaszczyt (off-peak): all other times
    - Note: G12 is same structure as C12a but for households

C12b - Three zones (dzień/szczyt/noc)
    - Szczyt (peak): 7:00-13:00, 16:00-21:00 (workdays)
    - Dzień (day): 6:00-7:00, 13:00-16:00, 21:00-22:00 (workdays)
    - Noc (night): 22:00-6:00 (all days)
    - Weekend: all night zone

C22 - Three zones with complex schedule
    - Similar to C12b but with more variations
    - May have seasonal differences

Times are in CET (czas zimowy / winter time).
"""

from datetime import date
from typing import List, Dict, Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from common.calendar_pl import DayType
from common.time_utils import ClockMode, minute_of_day

from ..models import (
    OsdTariff,
    ScheduleBlock,
    Segment,
    ZoneId,
    TariffComponent,
    ChargeBasis,
    TimeDependency,
    TariffPreview,
)


# =============================================================================
# Helper functions
# =============================================================================

def _create_segment(
    zone: ZoneId,
    start_hour: int,
    end_hour: int,
    day_types: List[DayType],
    start_minute: int = 0,
    end_minute: int = 0,
) -> Segment:
    """
    Create a segment with hour-based times.

    Args:
        zone: Zone ID
        start_hour: Start hour (0-23)
        end_hour: End hour (0-24, 24 = midnight next day)
        day_types: List of day types
        start_minute: Start minute within hour (default 0)
        end_minute: End minute within hour (default 0)
    """
    start = minute_of_day(start_hour, start_minute)

    # Handle end_hour = 24 (midnight)
    if end_hour == 24:
        end = 1440
    elif end_hour == 0 and end_minute == 0:
        end = 1440  # midnight = 1440
    else:
        end = minute_of_day(end_hour, end_minute)

    return Segment(
        zone_id=zone,
        start_minute=start,
        end_minute=end,
        day_types=day_types,
    )


# =============================================================================
# C11 - Flat tariff (single zone)
# =============================================================================

def create_c11_template(
    osd: str,
    rate: float = 0.0,
    valid_from: date = date(2025, 1, 1),
) -> OsdTariff:
    """
    Create a C11 (flat/single-zone) tariff template.

    C11 is the simplest tariff - same rate 24/7.
    """
    return OsdTariff(
        id=f"{osd.lower().replace(' ', '_')}_c11_{valid_from.year}",
        name=f"{osd} C11 {valid_from.year}",
        osd=osd,
        group="C11",
        voltage_level="nn",
        clock_mode=ClockMode.CET_FIXED,
        schedule_blocks=[
            ScheduleBlock(
                name="Całoroczny",
                valid_from=valid_from,
                valid_to=None,
                segments=[
                    _create_segment(
                        ZoneId.FLAT, 0, 24,
                        [DayType.WORKDAY, DayType.SATURDAY, DayType.SUNDAY, DayType.HOLIDAY]
                    ),
                ],
            ),
        ],
        components=[
            TariffComponent(
                name="Energia czynna",
                charge_basis=ChargeBasis.ENERGY,
                time_dependency=TimeDependency.FLAT,
                rates={ZoneId.FLAT: rate},
                unit="PLN/kWh",
            ),
        ],
    )


# =============================================================================
# C12a / G12 - Two-zone tariff (szczyt/pozaszczyt)
# =============================================================================

def create_c12a_template(
    osd: str,
    rate_peak: float = 0.0,
    rate_offpeak: float = 0.0,
    valid_from: date = date(2025, 1, 1),
) -> OsdTariff:
    """
    Create a C12a (two-zone) tariff template.

    Standard C12a zones:
    - Szczyt (I): 6:00-13:00, 15:00-22:00 (workdays)
    - Pozaszczyt (II): all other times

    All times are CET (winter time).
    """
    return OsdTariff(
        id=f"{osd.lower().replace(' ', '_')}_c12a_{valid_from.year}",
        name=f"{osd} C12a {valid_from.year}",
        osd=osd,
        group="C12a",
        voltage_level="nn",
        clock_mode=ClockMode.CET_FIXED,
        schedule_blocks=[
            ScheduleBlock(
                name="Całoroczny",
                valid_from=valid_from,
                valid_to=None,
                segments=[
                    # Workday peak: 6:00-13:00
                    _create_segment(ZoneId.I, 6, 13, [DayType.WORKDAY]),
                    # Workday peak: 15:00-22:00
                    _create_segment(ZoneId.I, 15, 22, [DayType.WORKDAY]),
                    # Workday off-peak: 0:00-6:00
                    _create_segment(ZoneId.II, 0, 6, [DayType.WORKDAY]),
                    # Workday off-peak: 13:00-15:00
                    _create_segment(ZoneId.II, 13, 15, [DayType.WORKDAY]),
                    # Workday off-peak: 22:00-24:00
                    _create_segment(ZoneId.II, 22, 24, [DayType.WORKDAY]),
                    # Weekend/holiday: all off-peak
                    _create_segment(
                        ZoneId.II, 0, 24,
                        [DayType.SATURDAY, DayType.SUNDAY, DayType.HOLIDAY]
                    ),
                ],
            ),
        ],
        components=[
            TariffComponent(
                name="Energia czynna",
                charge_basis=ChargeBasis.ENERGY,
                time_dependency=TimeDependency.ZONE_BASED,
                rates={
                    ZoneId.I: rate_peak,
                    ZoneId.II: rate_offpeak,
                },
                unit="PLN/kWh",
            ),
        ],
    )


def create_g12_template(
    osd: str,
    rate_peak: float = 0.0,
    rate_offpeak: float = 0.0,
    valid_from: date = date(2025, 1, 1),
) -> OsdTariff:
    """
    Create a G12 (household two-zone) tariff template.

    G12 has same structure as C12a but for households.
    """
    tariff = create_c12a_template(osd, rate_peak, rate_offpeak, valid_from)

    # Update metadata for G12
    return OsdTariff(
        id=f"{osd.lower().replace(' ', '_')}_g12_{valid_from.year}",
        name=f"{osd} G12 {valid_from.year}",
        osd=tariff.osd,
        group="G12",
        voltage_level="nn",
        clock_mode=tariff.clock_mode,
        schedule_blocks=tariff.schedule_blocks,
        components=tariff.components,
    )


# =============================================================================
# C12b - Three-zone tariff (szczyt/dzień/noc)
# =============================================================================

def create_c12b_template(
    osd: str,
    rate_peak: float = 0.0,
    rate_day: float = 0.0,
    rate_night: float = 0.0,
    valid_from: date = date(2025, 1, 1),
) -> OsdTariff:
    """
    Create a C12b (three-zone) tariff template.

    Standard C12b zones:
    - Szczyt (I): 7:00-13:00, 16:00-21:00 (workdays)
    - Dzień (II): 6:00-7:00, 13:00-16:00, 21:00-22:00 (workdays)
    - Noc (III): 22:00-6:00 (all days), + all weekend

    All times are CET (winter time).
    """
    return OsdTariff(
        id=f"{osd.lower().replace(' ', '_')}_c12b_{valid_from.year}",
        name=f"{osd} C12b {valid_from.year}",
        osd=osd,
        group="C12b",
        voltage_level="nn",
        clock_mode=ClockMode.CET_FIXED,
        schedule_blocks=[
            ScheduleBlock(
                name="Całoroczny",
                valid_from=valid_from,
                valid_to=None,
                segments=[
                    # === WORKDAY ===
                    # Night zone 0:00-6:00
                    _create_segment(ZoneId.III, 0, 6, [DayType.WORKDAY]),
                    # Day zone 6:00-7:00
                    _create_segment(ZoneId.II, 6, 7, [DayType.WORKDAY]),
                    # Peak zone 7:00-13:00
                    _create_segment(ZoneId.I, 7, 13, [DayType.WORKDAY]),
                    # Day zone 13:00-16:00
                    _create_segment(ZoneId.II, 13, 16, [DayType.WORKDAY]),
                    # Peak zone 16:00-21:00
                    _create_segment(ZoneId.I, 16, 21, [DayType.WORKDAY]),
                    # Day zone 21:00-22:00
                    _create_segment(ZoneId.II, 21, 22, [DayType.WORKDAY]),
                    # Night zone 22:00-24:00
                    _create_segment(ZoneId.III, 22, 24, [DayType.WORKDAY]),

                    # === WEEKEND & HOLIDAY ===
                    # All night zone
                    _create_segment(
                        ZoneId.III, 0, 24,
                        [DayType.SATURDAY, DayType.SUNDAY, DayType.HOLIDAY]
                    ),
                ],
            ),
        ],
        components=[
            TariffComponent(
                name="Energia czynna",
                charge_basis=ChargeBasis.ENERGY,
                time_dependency=TimeDependency.ZONE_BASED,
                rates={
                    ZoneId.I: rate_peak,
                    ZoneId.II: rate_day,
                    ZoneId.III: rate_night,
                },
                unit="PLN/kWh",
            ),
        ],
    )


# =============================================================================
# C22 - Business three-zone with potential seasonality
# =============================================================================

def create_c22_template(
    osd: str,
    rate_peak: float = 0.0,
    rate_day: float = 0.0,
    rate_night: float = 0.0,
    valid_from: date = date(2025, 1, 1),
    has_seasonality: bool = False,
) -> OsdTariff:
    """
    Create a C22 (business three-zone) tariff template.

    C22 is similar to C12b but for business customers.
    Some C22 tariffs have seasonal variations (winter/summer).

    Standard C22 zones (year-round):
    - Szczyt (I): 7:00-13:00, 17:00-21:00 (workdays)
    - Dzień (II): 6:00-7:00, 13:00-17:00, 21:00-22:00 (workdays)
    - Noc (III): 22:00-6:00 (all days), + all weekend

    Note: Some OSDs have different peak hours (e.g., 16:00-21:00 vs 17:00-21:00).
    Check actual tariff sheets.
    """
    if has_seasonality:
        # Winter: October - March (different peak hours possible)
        # Summer: April - September
        schedule_blocks = [
            ScheduleBlock(
                name="Zimowy (X-III)",
                valid_from=date(valid_from.year, 10, 1),
                valid_to=date(valid_from.year + 1, 3, 31),
                segments=[
                    # Workday structure
                    _create_segment(ZoneId.III, 0, 6, [DayType.WORKDAY]),
                    _create_segment(ZoneId.II, 6, 7, [DayType.WORKDAY]),
                    _create_segment(ZoneId.I, 7, 13, [DayType.WORKDAY]),
                    _create_segment(ZoneId.II, 13, 16, [DayType.WORKDAY]),
                    _create_segment(ZoneId.I, 16, 21, [DayType.WORKDAY]),  # Winter: earlier peak
                    _create_segment(ZoneId.II, 21, 22, [DayType.WORKDAY]),
                    _create_segment(ZoneId.III, 22, 24, [DayType.WORKDAY]),
                    # Weekend
                    _create_segment(
                        ZoneId.III, 0, 24,
                        [DayType.SATURDAY, DayType.SUNDAY, DayType.HOLIDAY]
                    ),
                ],
            ),
            ScheduleBlock(
                name="Letni (IV-IX)",
                valid_from=date(valid_from.year, 4, 1),
                valid_to=date(valid_from.year, 9, 30),
                segments=[
                    # Workday structure - summer has later afternoon peak
                    _create_segment(ZoneId.III, 0, 6, [DayType.WORKDAY]),
                    _create_segment(ZoneId.II, 6, 7, [DayType.WORKDAY]),
                    _create_segment(ZoneId.I, 7, 13, [DayType.WORKDAY]),
                    _create_segment(ZoneId.II, 13, 17, [DayType.WORKDAY]),  # Summer: longer day
                    _create_segment(ZoneId.I, 17, 21, [DayType.WORKDAY]),
                    _create_segment(ZoneId.II, 21, 22, [DayType.WORKDAY]),
                    _create_segment(ZoneId.III, 22, 24, [DayType.WORKDAY]),
                    # Weekend
                    _create_segment(
                        ZoneId.III, 0, 24,
                        [DayType.SATURDAY, DayType.SUNDAY, DayType.HOLIDAY]
                    ),
                ],
            ),
        ]
    else:
        # Year-round schedule
        schedule_blocks = [
            ScheduleBlock(
                name="Całoroczny",
                valid_from=valid_from,
                valid_to=None,
                segments=[
                    _create_segment(ZoneId.III, 0, 6, [DayType.WORKDAY]),
                    _create_segment(ZoneId.II, 6, 7, [DayType.WORKDAY]),
                    _create_segment(ZoneId.I, 7, 13, [DayType.WORKDAY]),
                    _create_segment(ZoneId.II, 13, 17, [DayType.WORKDAY]),
                    _create_segment(ZoneId.I, 17, 21, [DayType.WORKDAY]),
                    _create_segment(ZoneId.II, 21, 22, [DayType.WORKDAY]),
                    _create_segment(ZoneId.III, 22, 24, [DayType.WORKDAY]),
                    _create_segment(
                        ZoneId.III, 0, 24,
                        [DayType.SATURDAY, DayType.SUNDAY, DayType.HOLIDAY]
                    ),
                ],
            ),
        ]

    return OsdTariff(
        id=f"{osd.lower().replace(' ', '_')}_c22_{valid_from.year}",
        name=f"{osd} C22 {valid_from.year}",
        osd=osd,
        group="C22",
        voltage_level="nn",
        clock_mode=ClockMode.CET_FIXED,
        schedule_blocks=schedule_blocks,
        components=[
            TariffComponent(
                name="Energia czynna",
                charge_basis=ChargeBasis.ENERGY,
                time_dependency=TimeDependency.ZONE_BASED,
                rates={
                    ZoneId.I: rate_peak,
                    ZoneId.II: rate_day,
                    ZoneId.III: rate_night,
                },
                unit="PLN/kWh",
            ),
        ],
    )


# =============================================================================
# Pre-built examples with typical Polish OSD rates (2025)
# =============================================================================

# PGE Dystrybucja C12a 2025 (przykładowe stawki)
PGE_C12A_2025 = create_c12a_template(
    osd="PGE Dystrybucja",
    rate_peak=0.85,      # Szczyt (PLN/kWh netto)
    rate_offpeak=0.55,   # Pozaszczyt (PLN/kWh netto)
    valid_from=date(2025, 1, 1),
)

# Tauron Dystrybucja C12a 2025 (przykładowe stawki)
TAURON_C12A_2025 = create_c12a_template(
    osd="Tauron Dystrybucja",
    rate_peak=0.82,
    rate_offpeak=0.52,
    valid_from=date(2025, 1, 1),
)

# Energa-Operator G12 2025 (przykładowe stawki dla gospodarstw)
ENERGA_G12_2025 = create_g12_template(
    osd="Energa-Operator",
    rate_peak=0.78,
    rate_offpeak=0.48,
    valid_from=date(2025, 1, 1),
)

# =============================================================================
# 2026 Tariffs (aktualizacja stawek na 2026)
# =============================================================================

# PGE Dystrybucja C12a 2026
PGE_C12A_2026 = create_c12a_template(
    osd="PGE Dystrybucja",
    rate_peak=0.75,      # Szczyt (PLN/kWh) - zaktualizowane stawki
    rate_offpeak=0.45,   # Pozaszczyt (PLN/kWh) - spread 300 PLN/MWh
    valid_from=date(2026, 1, 1),
)

# PGE Dystrybucja C12b 2026 (trzy strefy)
PGE_C12B_2026 = create_c12a_template(  # TODO: use create_c12b_template when available
    osd="PGE Dystrybucja",
    rate_peak=0.85,      # Szczyt
    rate_offpeak=0.40,   # Noc - najniższa strefa
    valid_from=date(2026, 1, 1),
)

# Tauron Dystrybucja C12a 2026
TAURON_C12A_2026 = create_c12a_template(
    osd="Tauron Dystrybucja",
    rate_peak=0.72,
    rate_offpeak=0.42,
    valid_from=date(2026, 1, 1),
)

# Energa-Operator C12a 2026
ENERGA_C12A_2026 = create_c12a_template(
    osd="Energa-Operator",
    rate_peak=0.70,
    rate_offpeak=0.40,
    valid_from=date(2026, 1, 1),
)


# =============================================================================
# Preset registry
# =============================================================================

ALL_PRESETS: Dict[str, OsdTariff] = {
    # 2025
    "pge_c12a_2025": PGE_C12A_2025,
    "tauron_c12a_2025": TAURON_C12A_2025,
    "energa_g12_2025": ENERGA_G12_2025,
    # 2026
    "pge_c12a_2026": PGE_C12A_2026,
    "pge_c12b_2026": PGE_C12B_2026,
    "tauron_c12a_2026": TAURON_C12A_2026,
    "energa_c12a_2026": ENERGA_C12A_2026,
}


# Aliases for common tariff names
TARIFF_ALIASES = {"C12a": "pge_c12a_2025", "c12a": "pge_c12a_2025", "G12": "energa_g12_2025"}

def get_preset_by_id(preset_id: str) -> Optional[OsdTariff]:
    """Get a preset tariff by ID."""
    if preset_id in ALL_PRESETS: return ALL_PRESETS[preset_id]
    if preset_id in TARIFF_ALIASES: return ALL_PRESETS.get(TARIFF_ALIASES[preset_id])
    return None


def list_presets() -> List[TariffPreview]:
    """List all available preset tariffs."""
    previews = []

    for tariff in ALL_PRESETS.values():
        zones = tariff.get_zones_used()
        first_block = tariff.schedule_blocks[0] if tariff.schedule_blocks else None

        previews.append(TariffPreview(
            id=tariff.id,
            name=tariff.name,
            osd=tariff.osd,
            group=tariff.group,
            zones_count=len(zones),
            zones=[z.value for z in zones],
            has_seasonality=len(tariff.schedule_blocks) > 1,
            valid_from=first_block.valid_from if first_block else date(2025, 1, 1),
            valid_to=first_block.valid_to if first_block else None,
        ))

    return previews

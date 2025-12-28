"""
OSD Tariffs Engine for Polish Distribution System Operators.

This module provides comprehensive support for Polish OSD tariff structures:
- Multi-zone tariffs (I/II/III/IV zones)
- Multiple segments per zone per day
- Day type handling (workday/saturday/sunday/holiday)
- Seasonality via ScheduleBlocks with date ranges
- Clock mode handling (CET_FIXED for "czas zimowy")
- Tariff components with different charge bases

Supported tariff groups:
- C11 (flat, single zone)
- C12a, G12 (two zones: szczyt/pozaszczyt)
- C12b, C22 (three zones: dzień/szczyt/noc)
- C24 (four zones, complex)
"""

from .models import (
    ZoneId,
    ChargeBasis,
    TimeDependency,
    Segment,
    ScheduleBlock,
    TariffComponent,
    OsdTariff,
    OsdTariffRequest,
    OsdTariffResponse,
    CompiledTariffHour,
)

from .validators import (
    validate_schedule_coverage,
    validate_segment_overlap,
    validate_tariff,
    TariffValidationError,
)

from .compiler import (
    TariffCompiler,
    compile_tariff_for_date,
    compile_tariff_for_range,
)

__all__ = [
    # Models
    "ZoneId",
    "ChargeBasis",
    "TimeDependency",
    "Segment",
    "ScheduleBlock",
    "TariffComponent",
    "OsdTariff",
    "OsdTariffRequest",
    "OsdTariffResponse",
    "CompiledTariffHour",
    # Validators
    "validate_schedule_coverage",
    "validate_segment_overlap",
    "validate_tariff",
    "TariffValidationError",
    # Compiler
    "TariffCompiler",
    "compile_tariff_for_date",
    "compile_tariff_for_range",
]

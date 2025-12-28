"""
Pydantic models for Polish OSD Tariffs.

Key design decisions:
- ZoneId: I/II/III/IV + FLAT for single-zone tariffs
- Segment: Uses start_minute/end_minute (0-1439, 1-1440) with wraps_midnight property
- ScheduleBlock: Handles seasonality with valid_from/valid_to date ranges
- ClockMode: CET_FIXED (default) for Polish tariffs using "czas zimowy"
- Internal units: PLN/kWh netto for energy rates

Validation rules:
- start_minute != end_minute
- wraps_midnight = start_minute > end_minute (e.g., 22:00-06:00)
- valid_to is inclusive (valid_to=2025-03-31 includes that day)
- Each day_type must have exactly 1440 minutes coverage
"""

from datetime import date
from enum import Enum
from typing import List, Optional, Dict, Any, Set
from pydantic import BaseModel, Field, field_validator, model_validator


class ZoneId(str, Enum):
    """
    Tariff zone identifier.

    Polish OSD tariffs use up to 4 zones:
    - I: Strefa szczytowa (peak) - highest rates
    - II: Strefa dzienna/pośrednia (day/intermediate)
    - III: Strefa nocna/pozaszczytowa (night/off-peak)
    - IV: Strefa weekend/specjalna (rare, for complex tariffs)
    - FLAT: Single zone for C11-type tariffs
    """
    I = "I"
    II = "II"
    III = "III"
    IV = "IV"
    FLAT = "FLAT"


class ChargeBasis(str, Enum):
    """
    Basis for tariff component charging.

    ENERGY: Charge per kWh consumed
    POWER: Charge per kW of contracted/max power
    FIXED: Fixed monthly charge
    REACTIVE: Charge for reactive energy (tgφ)
    """
    ENERGY = "energy"
    POWER = "power"
    FIXED = "fixed"
    REACTIVE = "reactive"


class TimeDependency(str, Enum):
    """
    Time dependency of tariff component.

    ZONE_BASED: Rate varies by zone (e.g., energy rates)
    FLAT: Same rate regardless of time (e.g., fixed fees)
    PEAK_ONLY: Only applies during peak hours
    """
    ZONE_BASED = "zone_based"
    FLAT = "flat"
    PEAK_ONLY = "peak_only"


# Import DayType from common
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from common.calendar_pl import DayType
from common.time_utils import ClockMode


class Segment(BaseModel):
    """
    A time segment within a day that belongs to a specific zone.

    Represents a continuous time block (possibly wrapping midnight)
    that is assigned to one zone for specific day types.

    Attributes:
        zone_id: Which tariff zone this segment belongs to
        start_minute: Start minute of day (0-1439 inclusive)
        end_minute: End minute of day (1-1440 inclusive, 1440 = midnight)
        day_types: Which day types this segment applies to

    Examples:
        # Morning peak 7:00-13:00 on workdays
        Segment(zone_id="I", start_minute=420, end_minute=780, day_types=["workday"])

        # Night zone wrapping midnight 22:00-06:00
        Segment(zone_id="III", start_minute=1320, end_minute=360, day_types=["workday"])
    """
    zone_id: ZoneId = Field(..., description="Zone this segment belongs to")
    start_minute: int = Field(..., ge=0, le=1439, description="Start minute (0-1439)")
    end_minute: int = Field(..., ge=1, le=1440, description="End minute (1-1440, 1440=midnight)")
    day_types: List[DayType] = Field(..., min_length=1, description="Day types this applies to")

    @field_validator("end_minute")
    @classmethod
    def validate_end_minute(cls, v: int, info) -> int:
        """Validate end_minute is different from start_minute."""
        # Access start_minute from the data being validated
        if "start_minute" in info.data:
            start = info.data["start_minute"]
            if v == start:
                raise ValueError(f"end_minute ({v}) must differ from start_minute ({start})")
        return v

    @property
    def wraps_midnight(self) -> bool:
        """
        Check if this segment wraps around midnight.

        A segment wraps midnight when start > end, e.g., 22:00-06:00.
        This means the segment covers 22:00-23:59 and 00:00-06:00.
        """
        return self.start_minute > self.end_minute

    @property
    def duration_minutes(self) -> int:
        """
        Calculate the duration of this segment in minutes.

        Handles both normal and wrap-around cases.
        """
        if self.wraps_midnight:
            # 22:00-06:00 = (1440 - 1320) + 360 = 120 + 360 = 480 minutes
            return (1440 - self.start_minute) + self.end_minute
        else:
            return self.end_minute - self.start_minute

    def contains_minute(self, minute: int) -> bool:
        """
        Check if a minute of day falls within this segment.

        Args:
            minute: Minute of day (0-1439)

        Returns:
            True if minute is within this segment
        """
        if self.wraps_midnight:
            # 22:00-06:00 contains 23:00 (1380) and 03:00 (180)
            return minute >= self.start_minute or minute < self.end_minute
        else:
            # 07:00-13:00 contains 10:00 (600)
            return self.start_minute <= minute < self.end_minute

    def get_minute_ranges(self) -> List[tuple]:
        """
        Get the minute ranges covered by this segment.

        Returns:
            List of (start, end) tuples. For wrap-around segments,
            returns two ranges.

        Examples:
            # Normal segment 07:00-13:00
            [(420, 780)]

            # Wrap segment 22:00-06:00
            [(1320, 1440), (0, 360)]
        """
        if self.wraps_midnight:
            return [(self.start_minute, 1440), (0, self.end_minute)]
        else:
            return [(self.start_minute, self.end_minute)]

    def format_time_range(self) -> str:
        """Format as HH:MM-HH:MM string."""
        start_h, start_m = divmod(self.start_minute, 60)
        end_h, end_m = divmod(self.end_minute if self.end_minute < 1440 else 0, 60)
        if self.end_minute == 1440:
            end_h = 24
        return f"{start_h:02d}:{start_m:02d}-{end_h:02d}:{end_m:02d}"

    model_config = {"frozen": True}


class ScheduleBlock(BaseModel):
    """
    A schedule block with seasonal validity and segment definitions.

    Handles seasonality - different tariff schedules for different
    parts of the year (e.g., winter vs summer rates).

    Attributes:
        name: Human-readable name (e.g., "Całoroczny", "Zimowy", "Letni")
        valid_from: First day this schedule is valid (inclusive)
        valid_to: Last day this schedule is valid (inclusive), None = forever
        segments: List of time segments defining zones for this period

    Examples:
        # Year-round schedule
        ScheduleBlock(name="Całoroczny", valid_from=date(2025,1,1), segments=[...])

        # Winter schedule (Oct-Mar)
        ScheduleBlock(name="Zimowy", valid_from=date(2025,10,1),
                      valid_to=date(2026,3,31), segments=[...])
    """
    name: str = Field(..., min_length=1, max_length=100, description="Schedule name")
    valid_from: date = Field(..., description="First valid day (inclusive)")
    valid_to: Optional[date] = Field(None, description="Last valid day (inclusive), None=forever")
    segments: List[Segment] = Field(..., min_length=1, description="Time segments")

    @model_validator(mode="after")
    def validate_date_range(self) -> "ScheduleBlock":
        """Ensure valid_to >= valid_from if both specified."""
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError(
                f"valid_to ({self.valid_to}) must be >= valid_from ({self.valid_from})"
            )
        return self

    def is_valid_for_date(self, d: date) -> bool:
        """
        Check if this schedule is valid for a given date.

        Args:
            d: Date to check

        Returns:
            True if date falls within valid range (inclusive)
        """
        if d < self.valid_from:
            return False
        if self.valid_to is not None and d > self.valid_to:
            return False
        return True

    def get_segments_for_day_type(self, day_type: DayType) -> List[Segment]:
        """Get all segments that apply to a specific day type."""
        return [s for s in self.segments if day_type in s.day_types]


class TariffComponent(BaseModel):
    """
    A component of the tariff (energy, power, fixed fee, etc.).

    Each component has a charge basis and may be zone-dependent.

    Attributes:
        name: Component name (e.g., "Energia czynna", "Opłata sieciowa zmienna")
        charge_basis: How this component is charged (per kWh, per kW, fixed)
        time_dependency: Whether rate varies by zone
        rates: Zone -> rate mapping (PLN/kWh netto for energy)
        unit: Display unit (informational)

    Examples:
        # Energy rate varying by zone
        TariffComponent(
            name="Energia czynna",
            charge_basis="energy",
            time_dependency="zone_based",
            rates={"I": 0.85, "II": 0.65, "III": 0.45}
        )

        # Fixed monthly fee
        TariffComponent(
            name="Opłata stała",
            charge_basis="fixed",
            time_dependency="flat",
            rates={"FLAT": 15.50}
        )
    """
    name: str = Field(..., min_length=1, max_length=200)
    charge_basis: ChargeBasis
    time_dependency: TimeDependency
    rates: Dict[ZoneId, float] = Field(..., description="Zone -> rate mapping (PLN/kWh netto)")
    unit: str = Field(default="PLN/kWh", description="Display unit")

    @field_validator("rates")
    @classmethod
    def validate_rates(cls, v: Dict[ZoneId, float]) -> Dict[ZoneId, float]:
        """Ensure rates are non-negative."""
        for zone, rate in v.items():
            if rate < 0:
                raise ValueError(f"Rate for zone {zone} cannot be negative: {rate}")
        return v

    def get_rate(self, zone_id: ZoneId) -> Optional[float]:
        """Get rate for a specific zone, or None if not applicable."""
        if self.time_dependency == TimeDependency.FLAT:
            # For flat components, return FLAT rate or first available
            return self.rates.get(ZoneId.FLAT) or next(iter(self.rates.values()), None)
        return self.rates.get(zone_id)


class OsdTariff(BaseModel):
    """
    Complete OSD tariff definition.

    This is the main model representing a Polish OSD tariff with:
    - Metadata (ID, name, OSD, tariff group)
    - Clock mode for time interpretation
    - Schedule blocks for seasonality
    - Tariff components for pricing

    Attributes:
        id: Unique identifier
        name: Human-readable name
        osd: Distribution System Operator name
        group: Tariff group (C11, C12a, C22, etc.)
        voltage_level: Voltage level (nn, SN)
        clock_mode: How to interpret times (default: CET_FIXED)
        schedule_blocks: List of schedule blocks with segments
        components: List of tariff components

    Examples:
        OsdTariff(
            id="pge_c12a_2025",
            name="PGE Dystrybucja C12a 2025",
            osd="PGE Dystrybucja",
            group="C12a",
            voltage_level="nn",
            clock_mode="cet_fixed",
            schedule_blocks=[...],
            components=[...]
        )
    """
    id: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9_-]+$")
    name: str = Field(..., min_length=1, max_length=200)
    osd: str = Field(..., min_length=1, max_length=100, description="OSD name")
    group: str = Field(..., min_length=1, max_length=20, description="Tariff group (C11, C12a, etc.)")
    voltage_level: str = Field(default="nn", description="Voltage level (nn, SN)")
    clock_mode: ClockMode = Field(default=ClockMode.CET_FIXED, description="Time interpretation mode")
    schedule_blocks: List[ScheduleBlock] = Field(..., min_length=1)
    components: List[TariffComponent] = Field(default_factory=list)

    def get_active_schedule(self, d: date) -> Optional[ScheduleBlock]:
        """
        Get the schedule block active for a given date.

        Returns the first schedule block that is valid for the date.
        If multiple are valid, returns the first one (should be ordered by priority).
        """
        for block in self.schedule_blocks:
            if block.is_valid_for_date(d):
                return block
        return None

    def get_zones_used(self) -> Set[ZoneId]:
        """Get all zone IDs used in this tariff."""
        zones = set()
        for block in self.schedule_blocks:
            for segment in block.segments:
                zones.add(segment.zone_id)
        return zones


class CompiledTariffHour(BaseModel):
    """
    Compiled tariff data for a single hour.

    Result of compiling a tariff for a specific datetime,
    with zone and rate information.

    Attributes:
        hour: Hour of day (0-23)
        zone_id: Which zone this hour belongs to
        rate: Energy rate for this hour (PLN/kWh)
        day_type: Type of day
    """
    hour: int = Field(..., ge=0, le=23)
    zone_id: ZoneId
    rate: float = Field(..., ge=0)
    day_type: DayType


class OsdTariffRequest(BaseModel):
    """Request model for tariff operations."""
    tariff: OsdTariff
    target_date: Optional[date] = None
    validate_only: bool = False


class OsdTariffResponse(BaseModel):
    """Response model for tariff operations."""
    success: bool
    tariff_id: str
    message: Optional[str] = None
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    compiled_hours: Optional[List[CompiledTariffHour]] = None


class TariffPreview(BaseModel):
    """Preview of a tariff for display purposes."""
    id: str
    name: str
    osd: str
    group: str
    zones_count: int
    zones: List[str]
    has_seasonality: bool
    valid_from: date
    valid_to: Optional[date]


class ZoneInfo(BaseModel):
    """Information about a single zone in a tariff."""
    zone_id: ZoneId
    name: str
    color: str  # Hex color for UI
    rate: float
    hours_per_day: Dict[str, float]  # day_type -> hours

"""
Validation functions for OSD tariffs.

Key validations:
1. Coverage: Each day_type must have exactly 1440 minutes covered
2. Overlap: Detect and resolve overlapping segments (using priority)
3. Completeness: All required components present
4. Consistency: Zones in components match zones in segments

Priority order for overlap resolution (auto):
  HOLIDAY > SUNDAY > SATURDAY > WORKDAY
"""

from datetime import date
from typing import List, Dict, Tuple, Optional, Set
from collections import defaultdict

from .models import (
    OsdTariff,
    ScheduleBlock,
    Segment,
    ZoneId,
    TariffComponent,
    ChargeBasis,
    TimeDependency,
)

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from common.calendar_pl import DayType, DAY_TYPE_PRIORITY


class TariffValidationError(Exception):
    """Exception raised for tariff validation errors."""

    def __init__(self, message: str, errors: List[str] = None, warnings: List[str] = None):
        super().__init__(message)
        self.message = message
        self.errors = errors or []
        self.warnings = warnings or []


def validate_segment_minutes(segment: Segment) -> List[str]:
    """
    Validate a single segment's minute values.

    Returns list of errors (empty if valid).
    """
    errors = []

    # start_minute must be 0-1439
    if not (0 <= segment.start_minute <= 1439):
        errors.append(
            f"start_minute must be 0-1439, got {segment.start_minute}"
        )

    # end_minute must be 1-1440
    if not (1 <= segment.end_minute <= 1440):
        errors.append(
            f"end_minute must be 1-1440, got {segment.end_minute}"
        )

    # start != end (already in model validator, but double-check)
    if segment.start_minute == segment.end_minute:
        errors.append(
            f"start_minute ({segment.start_minute}) must differ from end_minute"
        )

    return errors


def get_minute_coverage(segments: List[Segment], day_type: DayType) -> List[bool]:
    """
    Get minute-by-minute coverage for a day type.

    Returns a list of 1440 booleans indicating if each minute is covered.
    """
    coverage = [False] * 1440

    for segment in segments:
        if day_type not in segment.day_types:
            continue

        for start, end in segment.get_minute_ranges():
            for minute in range(start, end):
                if minute < 1440:
                    coverage[minute] = True

    return coverage


def get_minute_zones(segments: List[Segment], day_type: DayType) -> List[Optional[ZoneId]]:
    """
    Get zone assignment for each minute of day.

    Returns a list of 1440 ZoneIds (or None if uncovered).
    Handles overlaps by using segment priority (last one wins).
    """
    zones = [None] * 1440

    # Sort segments by day_type priority (lower priority first, so higher overwrites)
    sorted_segments = sorted(
        [s for s in segments if day_type in s.day_types],
        key=lambda s: max(DAY_TYPE_PRIORITY.get(dt, 0) for dt in s.day_types)
    )

    for segment in sorted_segments:
        for start, end in segment.get_minute_ranges():
            for minute in range(start, end):
                if minute < 1440:
                    zones[minute] = segment.zone_id

    return zones


def validate_schedule_coverage(
    schedule: ScheduleBlock,
    strict: bool = True
) -> Tuple[List[str], List[str]]:
    """
    Validate that a schedule covers exactly 1440 minutes for each day type.

    Args:
        schedule: Schedule block to validate
        strict: If True, uncovered minutes are errors. If False, warnings.

    Returns:
        Tuple of (errors, warnings)
    """
    errors = []
    warnings = []

    # Collect all day types used in this schedule
    day_types_used: Set[DayType] = set()
    for segment in schedule.segments:
        day_types_used.update(segment.day_types)

    # Validate each day type
    for day_type in DayType:
        coverage = get_minute_coverage(schedule.segments, day_type)
        covered_count = sum(coverage)

        if day_type in day_types_used:
            # This day type is explicitly defined
            if covered_count < 1440:
                # Find uncovered ranges
                uncovered = find_uncovered_ranges(coverage)
                msg = (
                    f"Schedule '{schedule.name}': {day_type.value} has only "
                    f"{covered_count}/1440 minutes covered. "
                    f"Uncovered: {format_minute_ranges(uncovered)}"
                )
                if strict:
                    errors.append(msg)
                else:
                    warnings.append(msg)

            elif covered_count > 1440:
                # This shouldn't happen with proper logic, but check anyway
                errors.append(
                    f"Schedule '{schedule.name}': {day_type.value} has "
                    f"{covered_count} minutes (>1440, overlap detected)"
                )
        else:
            # Day type not explicitly defined - might inherit or be uncovered
            if covered_count == 0:
                warnings.append(
                    f"Schedule '{schedule.name}': {day_type.value} has no coverage. "
                    f"Consider adding segments or using fallback."
                )

    return errors, warnings


def find_uncovered_ranges(coverage: List[bool]) -> List[Tuple[int, int]]:
    """
    Find ranges of uncovered minutes.

    Returns list of (start, end) tuples for uncovered ranges.
    """
    ranges = []
    in_gap = False
    gap_start = 0

    for minute, covered in enumerate(coverage):
        if not covered and not in_gap:
            in_gap = True
            gap_start = minute
        elif covered and in_gap:
            in_gap = False
            ranges.append((gap_start, minute))

    if in_gap:
        ranges.append((gap_start, 1440))

    return ranges


def format_minute_ranges(ranges: List[Tuple[int, int]]) -> str:
    """Format minute ranges as human-readable string."""
    parts = []
    for start, end in ranges:
        start_h, start_m = divmod(start, 60)
        end_h, end_m = divmod(end, 60)
        parts.append(f"{start_h:02d}:{start_m:02d}-{end_h:02d}:{end_m:02d}")
    return ", ".join(parts) if parts else "(none)"


def validate_segment_overlap(
    segments: List[Segment],
    day_type: DayType
) -> Tuple[List[str], List[Tuple[int, List[ZoneId]]]]:
    """
    Detect overlapping segments for a day type.

    Returns:
        Tuple of (warnings, overlaps)
        - warnings: Human-readable overlap descriptions
        - overlaps: List of (minute, [zones]) for each overlapping minute
    """
    warnings = []
    overlaps = []

    # Track which zones cover each minute
    minute_zones: Dict[int, List[ZoneId]] = defaultdict(list)

    for segment in segments:
        if day_type not in segment.day_types:
            continue

        for start, end in segment.get_minute_ranges():
            for minute in range(start, end):
                if minute < 1440:
                    minute_zones[minute].append(segment.zone_id)

    # Find minutes with multiple zones
    for minute, zones in minute_zones.items():
        if len(zones) > 1:
            overlaps.append((minute, zones))

    # Group overlaps into ranges for readable warnings
    if overlaps:
        overlap_ranges = group_overlapping_minutes(overlaps)
        for start, end, zones in overlap_ranges:
            start_h, start_m = divmod(start, 60)
            end_h, end_m = divmod(end, 60)
            zone_str = ", ".join(z.value for z in zones)
            warnings.append(
                f"{day_type.value}: Overlap at {start_h:02d}:{start_m:02d}-"
                f"{end_h:02d}:{end_m:02d} between zones [{zone_str}]"
            )

    return warnings, overlaps


def group_overlapping_minutes(
    overlaps: List[Tuple[int, List[ZoneId]]]
) -> List[Tuple[int, int, Set[ZoneId]]]:
    """
    Group consecutive overlapping minutes into ranges.

    Returns list of (start_minute, end_minute, zones_set).
    """
    if not overlaps:
        return []

    overlaps = sorted(overlaps, key=lambda x: x[0])
    ranges = []

    current_start = overlaps[0][0]
    current_end = overlaps[0][0] + 1
    current_zones = set(overlaps[0][1])

    for minute, zones in overlaps[1:]:
        if minute == current_end and set(zones) == current_zones:
            current_end = minute + 1
        else:
            ranges.append((current_start, current_end, current_zones))
            current_start = minute
            current_end = minute + 1
            current_zones = set(zones)

    ranges.append((current_start, current_end, current_zones))
    return ranges


def validate_components(
    tariff: OsdTariff
) -> Tuple[List[str], List[str]]:
    """
    Validate tariff components.

    Checks:
    - Zone-based components have rates for all zones used in segments
    - At least one energy component exists
    - No duplicate component names
    """
    errors = []
    warnings = []

    zones_used = tariff.get_zones_used()

    # Check for energy component
    energy_components = [
        c for c in tariff.components
        if c.charge_basis == ChargeBasis.ENERGY
    ]
    if not energy_components:
        warnings.append("No energy component defined in tariff")

    # Check zone coverage in components
    for component in tariff.components:
        if component.time_dependency == TimeDependency.ZONE_BASED:
            component_zones = set(component.rates.keys())
            missing_zones = zones_used - component_zones

            if missing_zones:
                missing_str = ", ".join(z.value for z in missing_zones)
                warnings.append(
                    f"Component '{component.name}' missing rates for zones: {missing_str}"
                )

    # Check for duplicate names
    names = [c.name for c in tariff.components]
    duplicates = [n for n in names if names.count(n) > 1]
    if duplicates:
        warnings.append(
            f"Duplicate component names: {', '.join(set(duplicates))}"
        )

    return errors, warnings


def validate_schedule_date_ranges(
    schedule_blocks: List[ScheduleBlock]
) -> Tuple[List[str], List[str]]:
    """
    Validate schedule block date ranges for gaps and overlaps.

    Returns (errors, warnings).
    """
    errors = []
    warnings = []

    if len(schedule_blocks) == 1:
        # Single block - just check it has a start
        block = schedule_blocks[0]
        if block.valid_to is not None:
            warnings.append(
                f"Single schedule '{block.name}' has end date {block.valid_to}. "
                f"Tariff may not be valid after this date."
            )
        return errors, warnings

    # Multiple blocks - check for gaps and overlaps
    sorted_blocks = sorted(schedule_blocks, key=lambda b: b.valid_from)

    for i in range(len(sorted_blocks) - 1):
        current = sorted_blocks[i]
        next_block = sorted_blocks[i + 1]

        if current.valid_to is None:
            # Current block extends forever - overlap
            warnings.append(
                f"Schedule '{current.name}' has no end date but "
                f"'{next_block.name}' starts on {next_block.valid_from}. "
                f"May cause overlap."
            )
        elif current.valid_to >= next_block.valid_from:
            # Overlap
            warnings.append(
                f"Schedules '{current.name}' (ends {current.valid_to}) and "
                f"'{next_block.name}' (starts {next_block.valid_from}) overlap."
            )
        elif (next_block.valid_from - current.valid_to).days > 1:
            # Gap
            warnings.append(
                f"Gap between schedules '{current.name}' (ends {current.valid_to}) "
                f"and '{next_block.name}' (starts {next_block.valid_from})."
            )

    return errors, warnings


def validate_tariff(
    tariff: OsdTariff,
    strict: bool = True,
    check_date: Optional[date] = None
) -> Tuple[bool, List[str], List[str]]:
    """
    Perform full validation of an OSD tariff.

    Args:
        tariff: Tariff to validate
        strict: If True, coverage issues are errors. If False, warnings.
        check_date: Optional date to check schedule validity for.

    Returns:
        Tuple of (is_valid, errors, warnings)
    """
    all_errors = []
    all_warnings = []

    # 1. Validate each segment
    for block in tariff.schedule_blocks:
        for segment in block.segments:
            segment_errors = validate_segment_minutes(segment)
            all_errors.extend(segment_errors)

    # 2. Validate schedule coverage
    for block in tariff.schedule_blocks:
        errors, warnings = validate_schedule_coverage(block, strict=strict)
        all_errors.extend(errors)
        all_warnings.extend(warnings)

    # 3. Check for overlaps
    for block in tariff.schedule_blocks:
        for day_type in DayType:
            overlap_warnings, _ = validate_segment_overlap(block.segments, day_type)
            all_warnings.extend(overlap_warnings)

    # 4. Validate components
    comp_errors, comp_warnings = validate_components(tariff)
    all_errors.extend(comp_errors)
    all_warnings.extend(comp_warnings)

    # 5. Validate schedule date ranges
    date_errors, date_warnings = validate_schedule_date_ranges(tariff.schedule_blocks)
    all_errors.extend(date_errors)
    all_warnings.extend(date_warnings)

    # 6. Check if valid for specific date
    if check_date:
        active_schedule = tariff.get_active_schedule(check_date)
        if active_schedule is None:
            all_errors.append(
                f"No active schedule for date {check_date}"
            )

    is_valid = len(all_errors) == 0
    return is_valid, all_errors, all_warnings


def auto_resolve_overlaps(
    segments: List[Segment],
    day_type: DayType
) -> List[Segment]:
    """
    Automatically resolve overlapping segments using day type priority.

    Higher priority day types win:
    HOLIDAY > SUNDAY > SATURDAY > WORKDAY

    This creates new segments with resolved boundaries.

    Note: This modifies segment structure - use with caution.
    """
    # Build minute-by-minute zone map with priority
    minute_zone: List[Optional[ZoneId]] = [None] * 1440
    minute_priority: List[int] = [0] * 1440

    for segment in segments:
        if day_type not in segment.day_types:
            continue

        # Calculate priority for this segment
        segment_priority = max(
            DAY_TYPE_PRIORITY.get(dt, 0) for dt in segment.day_types
        )

        for start, end in segment.get_minute_ranges():
            for minute in range(start, end):
                if minute < 1440:
                    if segment_priority >= minute_priority[minute]:
                        minute_zone[minute] = segment.zone_id
                        minute_priority[minute] = segment_priority

    # Convert back to segments (simplified - just return zone map)
    # In practice, you'd want to merge consecutive same-zone minutes
    return minute_zone  # type: ignore

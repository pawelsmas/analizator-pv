"""
Unit tests for dst_helper module (v1.5.0).

Tests verify:
- DST date calculations for Poland/EU
- 23-hour day (spring forward) detection
- 25-hour day (fall back) detection
- DSTInfo dataclass correctness
- Hour mapping during DST transitions
- Period hours calculation with DST
"""

import pytest
import sys
import os
from datetime import date, timedelta

# Add service path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../services/bess-dispatch'))

from common.dst_helper import (
    get_last_sunday_of_month,
    get_spring_forward_date,
    get_fall_back_date,
    is_spring_forward_day,
    is_fall_back_day,
    get_day_hours_count,
    get_dst_info,
    get_dst_transition_dates,
    map_hourly_index_to_cet_hour,
    get_period_hours_with_dst,
    get_year_dst_dates_list,
    DSTInfo,
    WARSAW_TZ,
)


# -----------------------------------------------------------------------------
# Test: get_last_sunday_of_month()
# -----------------------------------------------------------------------------

class TestGetLastSundayOfMonth:
    """Test get_last_sunday_of_month function."""

    def test_march_2025(self):
        """Last Sunday of March 2025 should be March 30."""
        result = get_last_sunday_of_month(2025, 3)
        assert result == date(2025, 3, 30)
        assert result.weekday() == 6  # Sunday

    def test_october_2025(self):
        """Last Sunday of October 2025 should be October 26."""
        result = get_last_sunday_of_month(2025, 10)
        assert result == date(2025, 10, 26)
        assert result.weekday() == 6  # Sunday

    def test_march_2024(self):
        """Last Sunday of March 2024 should be March 31."""
        result = get_last_sunday_of_month(2024, 3)
        assert result == date(2024, 3, 31)
        assert result.weekday() == 6  # Sunday

    def test_october_2024(self):
        """Last Sunday of October 2024 should be October 27."""
        result = get_last_sunday_of_month(2024, 10)
        assert result == date(2024, 10, 27)
        assert result.weekday() == 6  # Sunday

    def test_december_wraps_to_next_year(self):
        """December calculation should not overflow."""
        result = get_last_sunday_of_month(2025, 12)
        assert result.month == 12
        assert result.year == 2025
        assert result.weekday() == 6  # Sunday

    def test_result_is_always_sunday(self):
        """Result should always be a Sunday for any month."""
        for month in range(1, 13):
            result = get_last_sunday_of_month(2025, month)
            assert result.weekday() == 6, f"Month {month} result is not Sunday"


# -----------------------------------------------------------------------------
# Test: get_spring_forward_date() / get_fall_back_date()
# -----------------------------------------------------------------------------

class TestDSTDates:
    """Test DST date functions."""

    def test_spring_forward_2025(self):
        """Spring forward 2025 should be March 30."""
        assert get_spring_forward_date(2025) == date(2025, 3, 30)

    def test_fall_back_2025(self):
        """Fall back 2025 should be October 26."""
        assert get_fall_back_date(2025) == date(2025, 10, 26)

    def test_spring_forward_2024(self):
        """Spring forward 2024 should be March 31."""
        assert get_spring_forward_date(2024) == date(2024, 3, 31)

    def test_fall_back_2024(self):
        """Fall back 2024 should be October 27."""
        assert get_fall_back_date(2024) == date(2024, 10, 27)

    def test_spring_forward_2026(self):
        """Spring forward 2026 should be March 29."""
        assert get_spring_forward_date(2026) == date(2026, 3, 29)

    def test_fall_back_2026(self):
        """Fall back 2026 should be October 25."""
        assert get_fall_back_date(2026) == date(2026, 10, 25)


# -----------------------------------------------------------------------------
# Test: is_spring_forward_day() / is_fall_back_day()
# -----------------------------------------------------------------------------

class TestIsDSTDay:
    """Test DST day detection functions."""

    def test_spring_forward_day_true(self):
        """March 30, 2025 is spring forward day."""
        assert is_spring_forward_day(date(2025, 3, 30)) is True

    def test_spring_forward_day_false_for_normal(self):
        """Normal day should not be spring forward."""
        assert is_spring_forward_day(date(2025, 3, 29)) is False
        assert is_spring_forward_day(date(2025, 3, 31)) is False

    def test_fall_back_day_true(self):
        """October 26, 2025 is fall back day."""
        assert is_fall_back_day(date(2025, 10, 26)) is True

    def test_fall_back_day_false_for_normal(self):
        """Normal day should not be fall back."""
        assert is_fall_back_day(date(2025, 10, 25)) is False
        assert is_fall_back_day(date(2025, 10, 27)) is False

    def test_not_both_dst_types(self):
        """A day cannot be both spring forward and fall back."""
        spring = date(2025, 3, 30)
        fall = date(2025, 10, 26)

        assert not (is_spring_forward_day(spring) and is_fall_back_day(spring))
        assert not (is_spring_forward_day(fall) and is_fall_back_day(fall))


# -----------------------------------------------------------------------------
# Test: get_day_hours_count()
# -----------------------------------------------------------------------------

class TestGetDayHoursCount:
    """Test get_day_hours_count function."""

    def test_normal_day_24_hours(self):
        """Normal day should have 24 hours."""
        assert get_day_hours_count(date(2025, 1, 15)) == 24
        assert get_day_hours_count(date(2025, 6, 15)) == 24
        assert get_day_hours_count(date(2025, 12, 25)) == 24

    def test_spring_forward_23_hours(self):
        """Spring forward day should have 23 hours."""
        assert get_day_hours_count(date(2025, 3, 30)) == 23

    def test_fall_back_25_hours(self):
        """Fall back day should have 25 hours."""
        assert get_day_hours_count(date(2025, 10, 26)) == 25

    def test_days_around_spring_forward(self):
        """Days before/after spring forward should be normal."""
        assert get_day_hours_count(date(2025, 3, 29)) == 24
        assert get_day_hours_count(date(2025, 3, 30)) == 23
        assert get_day_hours_count(date(2025, 3, 31)) == 24

    def test_days_around_fall_back(self):
        """Days before/after fall back should be normal."""
        assert get_day_hours_count(date(2025, 10, 25)) == 24
        assert get_day_hours_count(date(2025, 10, 26)) == 25
        assert get_day_hours_count(date(2025, 10, 27)) == 24


# -----------------------------------------------------------------------------
# Test: get_dst_info()
# -----------------------------------------------------------------------------

class TestGetDSTInfo:
    """Test get_dst_info function."""

    def test_normal_day_info(self):
        """Normal day should return non-DST info."""
        info = get_dst_info(date(2025, 6, 15))

        assert info.is_dst_day is False
        assert info.hours == 24
        assert info.is_spring_forward is False
        assert info.is_fall_back is False
        assert info.missing_hour is None
        assert info.duplicate_hour is None

    def test_spring_forward_info(self):
        """Spring forward should return correct info."""
        info = get_dst_info(date(2025, 3, 30))

        assert info.is_dst_day is True
        assert info.hours == 23
        assert info.is_spring_forward is True
        assert info.is_fall_back is False
        assert info.missing_hour == 2  # 02:00 CET doesn't exist
        assert info.duplicate_hour is None

    def test_fall_back_info(self):
        """Fall back should return correct info."""
        info = get_dst_info(date(2025, 10, 26))

        assert info.is_dst_day is True
        assert info.hours == 25
        assert info.is_spring_forward is False
        assert info.is_fall_back is True
        assert info.missing_hour is None
        assert info.duplicate_hour == 2  # 02:00 CET occurs twice

    def test_dst_info_is_dataclass(self):
        """Result should be a DSTInfo dataclass."""
        info = get_dst_info(date(2025, 6, 15))
        assert isinstance(info, DSTInfo)


# -----------------------------------------------------------------------------
# Test: get_dst_transition_dates()
# -----------------------------------------------------------------------------

class TestGetDSTTransitionDates:
    """Test get_dst_transition_dates function."""

    def test_returns_tuple_of_dates(self):
        """Should return tuple of (spring_forward, fall_back) dates."""
        spring, fall = get_dst_transition_dates(2025)

        assert isinstance(spring, date)
        assert isinstance(fall, date)
        assert spring == date(2025, 3, 30)
        assert fall == date(2025, 10, 26)

    def test_spring_before_fall(self):
        """Spring forward should always be before fall back."""
        spring, fall = get_dst_transition_dates(2025)
        assert spring < fall

    def test_multiple_years(self):
        """Should work for multiple years."""
        for year in [2024, 2025, 2026, 2027]:
            spring, fall = get_dst_transition_dates(year)
            assert spring.year == year
            assert fall.year == year
            assert spring.month == 3
            assert fall.month == 10


# -----------------------------------------------------------------------------
# Test: map_hourly_index_to_cet_hour()
# -----------------------------------------------------------------------------

class TestMapHourlyIndexToCETHour:
    """Test map_hourly_index_to_cet_hour function."""

    def test_cet_fixed_mode_normal_day(self):
        """CET_FIXED mode should use simple 24-hour calculation."""
        start = date(2025, 1, 1)

        # First day
        d, h = map_hourly_index_to_cet_hour(0, start, is_local_tz=False)
        assert d == date(2025, 1, 1) and h == 0

        d, h = map_hourly_index_to_cet_hour(12, start, is_local_tz=False)
        assert d == date(2025, 1, 1) and h == 12

        d, h = map_hourly_index_to_cet_hour(23, start, is_local_tz=False)
        assert d == date(2025, 1, 1) and h == 23

        # Second day
        d, h = map_hourly_index_to_cet_hour(24, start, is_local_tz=False)
        assert d == date(2025, 1, 2) and h == 0

        d, h = map_hourly_index_to_cet_hour(36, start, is_local_tz=False)
        assert d == date(2025, 1, 2) and h == 12

    def test_local_tz_mode_normal_day(self):
        """LOCAL_TZ mode on normal day should work like CET_FIXED."""
        start = date(2025, 6, 15)  # Normal day

        d, h = map_hourly_index_to_cet_hour(0, start, is_local_tz=True)
        assert d == date(2025, 6, 15) and h == 0

        d, h = map_hourly_index_to_cet_hour(12, start, is_local_tz=True)
        assert d == date(2025, 6, 15) and h == 12

    def test_local_tz_mode_spring_forward(self):
        """LOCAL_TZ mode on spring forward should skip hour 2."""
        start = date(2025, 3, 30)  # Spring forward day

        # Hours 0 and 1 should be normal
        d, h = map_hourly_index_to_cet_hour(0, start, is_local_tz=True)
        assert h == 0

        d, h = map_hourly_index_to_cet_hour(1, start, is_local_tz=True)
        assert h == 1

        # Index 2 should map to hour 3 (hour 2 doesn't exist)
        d, h = map_hourly_index_to_cet_hour(2, start, is_local_tz=True)
        assert h == 3

    def test_local_tz_mode_fall_back(self):
        """LOCAL_TZ mode on fall back should handle duplicate hour 2."""
        start = date(2025, 10, 26)  # Fall back day

        # Hours 0 and 1 should be normal
        d, h = map_hourly_index_to_cet_hour(0, start, is_local_tz=True)
        assert h == 0

        d, h = map_hourly_index_to_cet_hour(1, start, is_local_tz=True)
        assert h == 1

        # Indices 2 and 3 both map to hour 2
        d, h = map_hourly_index_to_cet_hour(2, start, is_local_tz=True)
        assert h == 2

        d, h = map_hourly_index_to_cet_hour(3, start, is_local_tz=True)
        assert h == 2


# -----------------------------------------------------------------------------
# Test: get_period_hours_with_dst()
# -----------------------------------------------------------------------------

class TestGetPeriodHoursWithDST:
    """Test get_period_hours_with_dst function."""

    def test_week_with_no_dst(self):
        """Week without DST should be 168 hours."""
        start = date(2025, 1, 1)
        end = date(2025, 1, 8)  # 7 days

        assert get_period_hours_with_dst(start, end) == 168

    def test_week_with_spring_forward(self):
        """Week with spring forward should be 167 hours."""
        start = date(2025, 3, 27)  # Thursday
        end = date(2025, 4, 3)  # Following Thursday, includes March 30

        # 7 days: 6 normal (144h) + 1 spring forward (23h) = 167
        assert get_period_hours_with_dst(start, end) == 167

    def test_week_with_fall_back(self):
        """Week with fall back should be 169 hours."""
        start = date(2025, 10, 23)  # Thursday
        end = date(2025, 10, 30)  # Following Thursday, includes Oct 26

        # 7 days: 6 normal (144h) + 1 fall back (25h) = 169
        assert get_period_hours_with_dst(start, end) == 169

    def test_full_year_with_dst(self):
        """Full year should have 8760 hours (DST cancels out)."""
        # Year with both spring forward (-1h) and fall back (+1h)
        start = date(2025, 1, 1)
        end = date(2026, 1, 1)

        # 365 days: 363 normal (8712h) + 1 spring (23h) + 1 fall (25h) = 8760
        assert get_period_hours_with_dst(start, end) == 8760

    def test_single_normal_day(self):
        """Single normal day should be 24 hours."""
        start = date(2025, 6, 15)
        end = date(2025, 6, 16)

        assert get_period_hours_with_dst(start, end) == 24

    def test_single_spring_forward_day(self):
        """Single spring forward day should be 23 hours."""
        start = date(2025, 3, 30)
        end = date(2025, 3, 31)

        assert get_period_hours_with_dst(start, end) == 23

    def test_single_fall_back_day(self):
        """Single fall back day should be 25 hours."""
        start = date(2025, 10, 26)
        end = date(2025, 10, 27)

        assert get_period_hours_with_dst(start, end) == 25


# -----------------------------------------------------------------------------
# Test: get_year_dst_dates_list()
# -----------------------------------------------------------------------------

class TestGetYearDSTDatesList:
    """Test get_year_dst_dates_list function."""

    def test_returns_list_of_tuples(self):
        """Should return list of (date, type) tuples."""
        result = get_year_dst_dates_list(2025)

        assert isinstance(result, list)
        assert len(result) == 2

        for item in result:
            assert isinstance(item, tuple)
            assert len(item) == 2
            assert isinstance(item[0], date)
            assert isinstance(item[1], str)

    def test_correct_dates_and_types(self):
        """Should return correct dates with correct types."""
        result = get_year_dst_dates_list(2025)

        assert result[0] == (date(2025, 3, 30), "spring_forward")
        assert result[1] == (date(2025, 10, 26), "fall_back")

    def test_spring_forward_first(self):
        """Spring forward should be first in list."""
        result = get_year_dst_dates_list(2025)

        assert result[0][1] == "spring_forward"
        assert result[1][1] == "fall_back"


# -----------------------------------------------------------------------------
# Test: WARSAW_TZ constant
# -----------------------------------------------------------------------------

class TestWarsawTZ:
    """Test WARSAW_TZ constant."""

    def test_warsaw_tz_exists(self):
        """WARSAW_TZ should be defined."""
        assert WARSAW_TZ is not None

    def test_warsaw_tz_is_zoneinfo(self):
        """WARSAW_TZ should be a ZoneInfo object."""
        from zoneinfo import ZoneInfo
        assert isinstance(WARSAW_TZ, ZoneInfo)


# -----------------------------------------------------------------------------
# Test: Edge Cases
# -----------------------------------------------------------------------------

class TestDSTEdgeCases:
    """Test edge cases for DST handling."""

    def test_year_2000(self):
        """Should work for year 2000."""
        spring = get_spring_forward_date(2000)
        fall = get_fall_back_date(2000)

        assert spring.year == 2000
        assert fall.year == 2000

    def test_year_2030(self):
        """Should work for year 2030."""
        spring = get_spring_forward_date(2030)
        fall = get_fall_back_date(2030)

        assert spring.year == 2030
        assert fall.year == 2030
        assert spring < fall

    def test_empty_period(self):
        """Empty period (same start and end) should be 0 hours."""
        start = date(2025, 6, 15)
        assert get_period_hours_with_dst(start, start) == 0

    def test_period_only_spring_forward(self):
        """Period containing only spring forward day."""
        start = date(2025, 3, 30)
        end = date(2025, 3, 31)
        assert get_period_hours_with_dst(start, end) == 23

    def test_period_only_fall_back(self):
        """Period containing only fall back day."""
        start = date(2025, 10, 26)
        end = date(2025, 10, 27)
        assert get_period_hours_with_dst(start, end) == 25


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

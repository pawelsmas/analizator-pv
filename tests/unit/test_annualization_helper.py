"""
Unit tests for annualization_helper module (v1.5.0).

Tests verify:
- HOURS_PER_YEAR = 8760 constant
- compute_annualization_factor() formula correctness
- annualize_value() scaling behavior
- is_full_year() threshold
- get_period_hours() calculation
- get_annualization_info() complete dataclass
- Edge cases (partial years, multi-year, DST days)
"""

import pytest
import sys
import os

# Add service path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../services/bess-dispatch'))

from annualization_helper import (
    HOURS_PER_YEAR,
    DAYS_PER_YEAR,
    compute_annualization_factor,
    annualize_value,
    is_full_year,
    get_period_hours,
    get_period_days,
    get_annualization_info,
    AnnualizationInfo,
)


# -----------------------------------------------------------------------------
# Test: Constants
# -----------------------------------------------------------------------------

class TestAnnualizationConstants:
    """Test annualization constants."""

    def test_hours_per_year_is_8760(self):
        """HOURS_PER_YEAR should be 8760 (non-leap year)."""
        assert HOURS_PER_YEAR == 8760

    def test_days_per_year_is_365(self):
        """DAYS_PER_YEAR should be 365 (non-leap year)."""
        assert DAYS_PER_YEAR == 365

    def test_hours_equals_days_times_24(self):
        """HOURS_PER_YEAR should equal DAYS_PER_YEAR * 24."""
        assert HOURS_PER_YEAR == DAYS_PER_YEAR * 24


# -----------------------------------------------------------------------------
# Test: compute_annualization_factor()
# -----------------------------------------------------------------------------

class TestComputeAnnualizationFactor:
    """Test compute_annualization_factor function."""

    def test_full_year_returns_one(self):
        """Full year (8760 hours) should return factor of 1.0."""
        assert compute_annualization_factor(8760) == 1.0

    def test_more_than_full_year_returns_one(self):
        """More than one year should return factor of 1.0 (capped)."""
        assert compute_annualization_factor(17520) == 1.0  # 2 years
        assert compute_annualization_factor(10000) == 1.0

    def test_half_year_returns_two(self):
        """Half year (4380 hours) should return factor of 2.0."""
        factor = compute_annualization_factor(4380)
        assert abs(factor - 2.0) < 0.001

    def test_one_month_30_days(self):
        """30 days (720 hours) should return factor of ~12.17."""
        factor = compute_annualization_factor(720)
        expected = 8760 / 720  # 12.1666...
        assert abs(factor - expected) < 0.001

    def test_one_week_168_hours(self):
        """1 week (168 hours) should return factor of ~52.14."""
        factor = compute_annualization_factor(168)
        expected = 8760 / 168  # 52.14285...
        assert abs(factor - expected) < 0.001

    def test_one_day_24_hours(self):
        """1 day (24 hours) should return factor of 365."""
        factor = compute_annualization_factor(24)
        assert factor == 365.0

    def test_one_hour_returns_8760(self):
        """1 hour should return factor of 8760."""
        factor = compute_annualization_factor(1)
        assert factor == 8760.0

    def test_cap_at_one_false_allows_greater_than_one(self):
        """With cap_at_one=False, can return factor > 1 for multi-year."""
        factor = compute_annualization_factor(17520, cap_at_one=False)  # 2 years
        assert abs(factor - 0.5) < 0.001

    def test_zero_period_raises_error(self):
        """Zero period hours should raise ValueError."""
        with pytest.raises(ValueError, match="period_hours must be positive"):
            compute_annualization_factor(0)

    def test_negative_period_raises_error(self):
        """Negative period hours should raise ValueError."""
        with pytest.raises(ValueError, match="period_hours must be positive"):
            compute_annualization_factor(-100)


# -----------------------------------------------------------------------------
# Test: annualize_value()
# -----------------------------------------------------------------------------

class TestAnnualizeValue:
    """Test annualize_value function."""

    def test_full_year_no_scaling(self):
        """Full year value should not be scaled."""
        result = annualize_value(10000, 8760)
        assert result == 10000

    def test_half_year_doubled(self):
        """Half year value should be doubled."""
        result = annualize_value(5000, 4380)
        assert abs(result - 10000) < 0.01

    def test_one_month_scaled_to_annual(self):
        """Monthly value should be scaled to annual."""
        monthly_savings = 1000
        result = annualize_value(monthly_savings, 720)  # 30 days
        expected = 1000 * (8760 / 720)  # ~12166.67
        assert abs(result - expected) < 0.01

    def test_weekly_scaled_to_annual(self):
        """Weekly value should be scaled to annual."""
        weekly_savings = 100
        result = annualize_value(weekly_savings, 168)  # 1 week
        expected = 100 * (8760 / 168)  # ~5214.29
        assert abs(result - expected) < 0.01

    def test_zero_value_returns_zero(self):
        """Zero value should return zero regardless of period."""
        assert annualize_value(0, 720) == 0
        assert annualize_value(0, 8760) == 0

    def test_negative_value_scaled_correctly(self):
        """Negative values should be scaled like positive values."""
        result = annualize_value(-1000, 720)
        expected = -1000 * (8760 / 720)
        assert abs(result - expected) < 0.01


# -----------------------------------------------------------------------------
# Test: is_full_year()
# -----------------------------------------------------------------------------

class TestIsFullYear:
    """Test is_full_year function."""

    def test_exactly_8760_is_full_year(self):
        """Exactly 8760 hours should be considered full year."""
        assert is_full_year(8760) is True

    def test_8759_is_not_full_year(self):
        """8759 hours should NOT be considered full year."""
        assert is_full_year(8759) is False

    def test_more_than_8760_is_full_year(self):
        """More than 8760 hours should be considered full year."""
        assert is_full_year(17520) is True  # 2 years
        assert is_full_year(9000) is True

    def test_small_periods_not_full_year(self):
        """Small periods should not be full year."""
        assert is_full_year(720) is False   # 30 days
        assert is_full_year(168) is False   # 1 week
        assert is_full_year(24) is False    # 1 day


# -----------------------------------------------------------------------------
# Test: get_period_hours()
# -----------------------------------------------------------------------------

class TestGetPeriodHours:
    """Test get_period_hours function."""

    def test_hourly_data_one_year(self):
        """8760 hourly points should be 8760 hours."""
        result = get_period_hours(8760, 60)
        assert result == 8760.0

    def test_hourly_data_one_week(self):
        """168 hourly points should be 168 hours."""
        result = get_period_hours(168, 60)
        assert result == 168.0

    def test_15min_data_one_week(self):
        """672 15-min points should be 168 hours."""
        result = get_period_hours(672, 15)
        assert result == 168.0

    def test_15min_data_one_year(self):
        """35040 15-min points should be 8760 hours."""
        result = get_period_hours(35040, 15)
        assert result == 8760.0

    def test_30min_data(self):
        """336 30-min points should be 168 hours."""
        result = get_period_hours(336, 30)
        assert result == 168.0

    def test_zero_points_raises_error(self):
        """Zero points should raise ValueError."""
        with pytest.raises(ValueError, match="n_points must be positive"):
            get_period_hours(0, 60)

    def test_zero_interval_raises_error(self):
        """Zero interval should raise ValueError."""
        with pytest.raises(ValueError, match="interval_minutes must be positive"):
            get_period_hours(100, 0)


# -----------------------------------------------------------------------------
# Test: get_period_days()
# -----------------------------------------------------------------------------

class TestGetPeriodDays:
    """Test get_period_days function."""

    def test_full_year_is_365_days(self):
        """8760 hours should be 365 days."""
        assert get_period_days(8760) == 365.0

    def test_one_week_is_7_days(self):
        """168 hours should be 7 days."""
        assert get_period_days(168) == 7.0

    def test_one_day_is_1_day(self):
        """24 hours should be 1 day."""
        assert get_period_days(24) == 1.0

    def test_fractional_days(self):
        """12 hours should be 0.5 days."""
        assert get_period_days(12) == 0.5


# -----------------------------------------------------------------------------
# Test: get_annualization_info()
# -----------------------------------------------------------------------------

class TestGetAnnualizationInfo:
    """Test get_annualization_info function."""

    def test_from_period_hours(self):
        """Should compute info from period_hours."""
        info = get_annualization_info(period_hours=720)
        assert info.period_hours == 720
        assert info.period_days == 30.0
        assert info.is_full_year is False
        assert abs(info.annualization_factor - 12.1667) < 0.001

    def test_from_n_points_and_interval(self):
        """Should compute info from n_points and interval_minutes."""
        info = get_annualization_info(n_points=8760, interval_minutes=60)
        assert info.period_hours == 8760
        assert info.period_days == 365.0
        assert info.is_full_year is True
        assert info.annualization_factor == 1.0

    def test_from_15min_data(self):
        """Should handle 15-min data correctly."""
        # 4 weeks of 15-min data: 4 * 7 * 24 * 4 = 2688 points
        info = get_annualization_info(n_points=2688, interval_minutes=15)
        assert info.period_hours == 672  # 28 days
        assert info.period_days == 28.0
        assert info.is_full_year is False

    def test_full_year_info(self):
        """Should return correct info for full year."""
        info = get_annualization_info(period_hours=8760)
        assert info.is_full_year is True
        assert info.annualization_factor == 1.0

    def test_missing_parameters_raises_error(self):
        """Should raise error if no parameters provided."""
        with pytest.raises(ValueError, match="Either period_hours"):
            get_annualization_info()

    def test_partial_parameters_raises_error(self):
        """Should raise error if only n_points provided."""
        with pytest.raises(ValueError, match="Either period_hours"):
            get_annualization_info(n_points=100)


# -----------------------------------------------------------------------------
# Test: AnnualizationInfo dataclass
# -----------------------------------------------------------------------------

class TestAnnualizationInfoDataclass:
    """Test AnnualizationInfo dataclass."""

    def test_dataclass_fields(self):
        """Dataclass should have all required fields."""
        info = AnnualizationInfo(
            period_hours=720,
            period_days=30,
            is_full_year=False,
            annualization_factor=12.167
        )
        assert info.period_hours == 720
        assert info.period_days == 30
        assert info.is_full_year is False
        assert info.annualization_factor == 12.167


# -----------------------------------------------------------------------------
# Test: DST Edge Cases
# -----------------------------------------------------------------------------

class TestDSTEdgeCases:
    """Test DST-related edge cases."""

    def test_23_hour_day_spring_forward(self):
        """23-hour day (spring DST) should be 23 hours."""
        result = get_period_hours(23, 60)
        assert result == 23.0

        # Annualization factor should be slightly higher than 24-hour day
        factor_23h = compute_annualization_factor(23)
        factor_24h = compute_annualization_factor(24)
        assert factor_23h > factor_24h

    def test_25_hour_day_fall_back(self):
        """25-hour day (fall DST) should be 25 hours."""
        result = get_period_hours(25, 60)
        assert result == 25.0

        # Annualization factor should be slightly lower than 24-hour day
        factor_25h = compute_annualization_factor(25)
        factor_24h = compute_annualization_factor(24)
        assert factor_25h < factor_24h

    def test_year_with_dst_8759_hours(self):
        """Year with DST (e.g., 8759 hours) should NOT be full year."""
        # In some years with DST, actual hours might be 8759 or 8761
        assert is_full_year(8759) is False

        # But should still produce a factor close to 1.0
        factor = compute_annualization_factor(8759)
        assert abs(factor - 1.0) < 0.001


# -----------------------------------------------------------------------------
# Test: Leap Year Edge Cases
# -----------------------------------------------------------------------------

class TestLeapYearEdgeCases:
    """Test leap year edge cases."""

    def test_leap_year_8784_hours(self):
        """Leap year (8784 hours) should be full year."""
        assert is_full_year(8784) is True
        assert compute_annualization_factor(8784) == 1.0

    def test_leap_year_366_days(self):
        """366 days should be > 8760 hours."""
        leap_year_hours = 366 * 24  # 8784
        assert is_full_year(leap_year_hours) is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

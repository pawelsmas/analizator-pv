"""
Unit tests for quota reset timing.

Tests verify:
- Reset time is at midnight UTC
- Seconds until reset is calculated correctly
- Reset time format is ISO 8601
"""

import os
import sys
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))

from quota_engine import get_next_reset_time, get_seconds_until_reset


# -----------------------------------------------------------------------------
# get_next_reset_time tests
# -----------------------------------------------------------------------------

class TestGetNextResetTime:
    """Tests for get_next_reset_time function."""

    def test_returns_iso8601_format(self):
        """Should return valid ISO 8601 string."""
        reset_time = get_next_reset_time()

        # Should be parseable
        parsed = datetime.fromisoformat(reset_time.replace("Z", "+00:00"))
        assert parsed is not None

    def test_reset_is_at_midnight(self):
        """Reset time should be at 00:00:00."""
        reset_time = get_next_reset_time()
        parsed = datetime.fromisoformat(reset_time.replace("Z", "+00:00"))

        assert parsed.hour == 0
        assert parsed.minute == 0
        assert parsed.second == 0
        assert parsed.microsecond == 0

    def test_reset_is_utc(self):
        """Reset time should be in UTC timezone."""
        reset_time = get_next_reset_time()
        parsed = datetime.fromisoformat(reset_time.replace("Z", "+00:00"))

        assert parsed.tzinfo is not None
        # UTC offset should be 0
        assert parsed.utcoffset() == timedelta(0)

    def test_reset_is_tomorrow(self):
        """Reset time should be tomorrow, not today."""
        reset_time = get_next_reset_time()
        parsed = datetime.fromisoformat(reset_time.replace("Z", "+00:00"))

        now = datetime.now(timezone.utc)

        # Reset should be after now
        assert parsed > now

        # Reset should be at most 24 hours from now
        assert (parsed - now).total_seconds() <= 86400

    @patch('quota_engine.datetime')
    def test_reset_just_before_midnight(self, mock_datetime):
        """At 23:59:59 UTC, reset should be in ~1 second."""
        mock_now = datetime(2024, 6, 15, 23, 59, 59, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        reset_time = get_next_reset_time()
        parsed = datetime.fromisoformat(reset_time.replace("Z", "+00:00"))

        # Should be 2024-06-16 00:00:00 UTC
        assert parsed.year == 2024
        assert parsed.month == 6
        assert parsed.day == 16
        assert parsed.hour == 0

    @patch('quota_engine.datetime')
    def test_reset_just_after_midnight(self, mock_datetime):
        """At 00:00:01 UTC, reset should be in ~24 hours."""
        mock_now = datetime(2024, 6, 15, 0, 0, 1, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        reset_time = get_next_reset_time()
        parsed = datetime.fromisoformat(reset_time.replace("Z", "+00:00"))

        # Should be 2024-06-16 00:00:00 UTC (tomorrow)
        assert parsed.year == 2024
        assert parsed.month == 6
        assert parsed.day == 16


# -----------------------------------------------------------------------------
# get_seconds_until_reset tests
# -----------------------------------------------------------------------------

class TestGetSecondsUntilReset:
    """Tests for get_seconds_until_reset function."""

    def test_returns_positive_integer(self):
        """Should return positive integer."""
        seconds = get_seconds_until_reset()

        assert isinstance(seconds, int)
        assert seconds > 0

    def test_max_seconds_is_24_hours(self):
        """Should be at most 86400 seconds (24 hours)."""
        seconds = get_seconds_until_reset()

        assert seconds <= 86400

    def test_min_seconds_is_1(self):
        """Should be at least 1 second."""
        seconds = get_seconds_until_reset()

        assert seconds >= 1

    @patch('quota_engine.datetime')
    def test_seconds_just_before_midnight(self, mock_datetime):
        """At 23:59:59, should return ~1 second."""
        mock_now = datetime(2024, 6, 15, 23, 59, 59, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        seconds = get_seconds_until_reset()

        # Should be 1 second
        assert seconds == 1

    @patch('quota_engine.datetime')
    def test_seconds_just_after_midnight(self, mock_datetime):
        """At 00:00:01, should return ~86399 seconds."""
        mock_now = datetime(2024, 6, 15, 0, 0, 1, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        seconds = get_seconds_until_reset()

        # Should be 86399 seconds (24h - 1s)
        assert seconds == 86399

    @patch('quota_engine.datetime')
    def test_seconds_at_noon(self, mock_datetime):
        """At noon, should return ~12 hours."""
        mock_now = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        seconds = get_seconds_until_reset()

        # Should be 43200 seconds (12 hours)
        assert seconds == 43200


# -----------------------------------------------------------------------------
# Integration tests
# -----------------------------------------------------------------------------

class TestResetTimeIntegration:
    """Integration tests for reset time calculations."""

    def test_seconds_matches_reset_time(self):
        """Seconds until reset should match reset_at timestamp."""
        reset_time = get_next_reset_time()
        seconds = get_seconds_until_reset()

        parsed = datetime.fromisoformat(reset_time.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)

        expected_seconds = int((parsed - now).total_seconds())

        # Allow 1 second tolerance due to test execution time
        assert abs(seconds - expected_seconds) <= 1

    def test_reset_time_consistent_across_calls(self):
        """Multiple calls should return consistent values."""
        reset1 = get_next_reset_time()
        reset2 = get_next_reset_time()

        # Should be the same (within the same second)
        assert reset1 == reset2

    def test_seconds_decreases_over_time(self):
        """Seconds until reset should decrease (or stay same) over time."""
        seconds1 = get_seconds_until_reset()

        import time
        time.sleep(0.1)

        seconds2 = get_seconds_until_reset()

        # Should decrease or stay same (due to integer truncation)
        assert seconds2 <= seconds1

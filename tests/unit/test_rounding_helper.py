"""
Unit tests for rounding_helper module.

v1.6.0: Tests rounding policy for deterministic output.
"""

import sys
from pathlib import Path

# Add services/bess-dispatch to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))

from rounding_helper import (
    round_pln,
    round_mwh,
    round_kwh,
    round_kw,
    round_pct,
)


class TestRoundPln:
    """Tests for round_pln (2 decimal places for currency)."""

    def test_rounds_to_two_decimals(self):
        assert round_pln(123.456) == 123.46
        assert round_pln(123.454) == 123.45

    def test_handles_integers(self):
        assert round_pln(100) == 100.0
        assert isinstance(round_pln(100), float)

    def test_handles_negative(self):
        assert round_pln(-99.999) == -100.0
        assert round_pln(-99.994) == -99.99

    def test_zero(self):
        assert round_pln(0) == 0.0

    def test_large_values(self):
        assert round_pln(1_000_000.999) == 1_000_001.0


class TestRoundMwh:
    """Tests for round_mwh (3 decimal places for MWh)."""

    def test_rounds_to_three_decimals(self):
        assert round_mwh(1.2345) == 1.234
        assert round_mwh(1.2346) == 1.235

    def test_handles_integers(self):
        assert round_mwh(5) == 5.0
        assert isinstance(round_mwh(5), float)

    def test_handles_negative(self):
        assert round_mwh(-0.9999) == -1.0

    def test_zero(self):
        assert round_mwh(0) == 0.0

    def test_small_values(self):
        assert round_mwh(0.0001) == 0.0
        assert round_mwh(0.0005) == 0.001


class TestRoundKwh:
    """Tests for round_kwh (1 decimal place for kWh)."""

    def test_rounds_to_one_decimal(self):
        # Note: Python uses banker's rounding (round half to even)
        # 123.45 rounds to 123.4 (4 is even), 123.55 rounds to 123.6 (6 is even)
        assert round_kwh(123.44) == 123.4
        assert round_kwh(123.46) == 123.5

    def test_handles_integers(self):
        assert round_kwh(1000) == 1000.0
        assert isinstance(round_kwh(1000), float)

    def test_zero(self):
        assert round_kwh(0) == 0.0


class TestRoundKw:
    """Tests for round_kw (1 decimal place for kW)."""

    def test_rounds_to_one_decimal(self):
        assert round_kw(500.456) == 500.5
        assert round_kw(500.449) == 500.4

    def test_handles_integers(self):
        assert round_kw(100) == 100.0
        assert isinstance(round_kw(100), float)

    def test_zero(self):
        assert round_kw(0) == 0.0


class TestRoundPct:
    """Tests for round_pct (2 decimal places for percentages)."""

    def test_rounds_to_two_decimals(self):
        # Note: Python uses banker's rounding (round half to even)
        # 12.345 rounds to 12.34 (4 is even)
        assert round_pct(12.344) == 12.34
        assert round_pct(12.346) == 12.35

    def test_handles_integers(self):
        assert round_pct(50) == 50.0
        assert isinstance(round_pct(50), float)

    def test_negative_percentages(self):
        # -5.555 with banker's rounding goes to -5.56 (6 is even)
        assert round_pct(-5.556) == -5.56

    def test_zero(self):
        assert round_pct(0) == 0.0

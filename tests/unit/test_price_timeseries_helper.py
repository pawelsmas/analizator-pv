"""
Unit tests for price_timeseries_helper.py (v2.0.0).

Tests verify:
- Price timeseries generation from PriceConfig
- Deterministic price_hash computation
- Validation of price timeseries
"""

import pytest
import sys
import os

# Add service path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch')))

from price_timeseries_helper import (
    compute_price_hash,
    generate_price_timeseries,
    validate_price_timeseries,
)
from models import PriceConfig, PriceTimeseriesPlnPerMwh


class TestComputePriceHash:
    """Tests for compute_price_hash function."""

    def test_hash_is_deterministic(self):
        """Same price timeseries produces same hash."""
        ts = PriceTimeseriesPlnPerMwh(
            import_price_pln_per_mwh=[800.0, 800.0, 800.0],
            export_price_pln_per_mwh=[400.0, 400.0, 400.0],
            step_minutes=60,
            steps=3,
            timezone="Europe/Warsaw",
            period_start="2025-01-01T00:00:00",
            period_end="2025-01-01T02:00:00",
        )

        hash1 = compute_price_hash(ts)
        hash2 = compute_price_hash(ts)

        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex digest

    def test_different_prices_different_hash(self):
        """Different prices produce different hash."""
        ts1 = PriceTimeseriesPlnPerMwh(
            import_price_pln_per_mwh=[800.0, 800.0, 800.0],
            export_price_pln_per_mwh=[400.0, 400.0, 400.0],
            step_minutes=60,
            steps=3,
            timezone="Europe/Warsaw",
            period_start="2025-01-01T00:00:00",
            period_end="2025-01-01T02:00:00",
        )
        ts2 = PriceTimeseriesPlnPerMwh(
            import_price_pln_per_mwh=[900.0, 900.0, 900.0],  # Different price
            export_price_pln_per_mwh=[400.0, 400.0, 400.0],
            step_minutes=60,
            steps=3,
            timezone="Europe/Warsaw",
            period_start="2025-01-01T00:00:00",
            period_end="2025-01-01T02:00:00",
        )

        assert compute_price_hash(ts1) != compute_price_hash(ts2)

    def test_hash_is_64_char_hex(self):
        """Hash is valid SHA256 hex string."""
        ts = PriceTimeseriesPlnPerMwh(
            import_price_pln_per_mwh=[800.0],
            export_price_pln_per_mwh=[400.0],
            step_minutes=60,
            steps=1,
            timezone="Europe/Warsaw",
            period_start="2025-01-01T00:00:00",
            period_end="2025-01-01T00:00:00",
        )

        hash_val = compute_price_hash(ts)
        assert len(hash_val) == 64
        assert all(c in '0123456789abcdef' for c in hash_val)

    def test_rounding_stability(self):
        """Small floating point differences round to same hash."""
        ts1 = PriceTimeseriesPlnPerMwh(
            import_price_pln_per_mwh=[800.0000001],
            export_price_pln_per_mwh=[400.0],
            step_minutes=60,
            steps=1,
            timezone="Europe/Warsaw",
            period_start="2025-01-01T00:00:00",
            period_end="2025-01-01T00:00:00",
        )
        ts2 = PriceTimeseriesPlnPerMwh(
            import_price_pln_per_mwh=[800.0000002],  # Different by 1e-7
            export_price_pln_per_mwh=[400.0],
            step_minutes=60,
            steps=1,
            timezone="Europe/Warsaw",
            period_start="2025-01-01T00:00:00",
            period_end="2025-01-01T00:00:00",
        )

        # Should round to same value at 6 decimal places
        assert compute_price_hash(ts1) == compute_price_hash(ts2)


class TestGeneratePriceTimeseries:
    """Tests for generate_price_timeseries function."""

    def test_generate_flat_prices(self):
        """Generate flat price timeseries from PriceConfig."""
        prices = PriceConfig(
            import_price_pln_mwh=800.0,  # Already in PLN/MWh
            export_price_pln_mwh=400.0,
        )

        ts = generate_price_timeseries(
            prices=prices,
            n_steps=24,
            step_minutes=60,
            start_datetime="2025-01-01T00:00:00",
            timezone="Europe/Warsaw",
        )

        assert ts.steps == 24
        assert len(ts.import_price_pln_per_mwh) == 24
        assert len(ts.export_price_pln_per_mwh) == 24
        assert ts.import_price_pln_per_mwh[0] == 800.0
        assert ts.export_price_pln_per_mwh[0] == 400.0

    def test_generate_15min_resolution(self):
        """Generate with 15-minute resolution."""
        prices = PriceConfig(
            import_price_pln_mwh=800.0,
            export_price_pln_mwh=400.0,
        )

        ts = generate_price_timeseries(
            prices=prices,
            n_steps=96,  # 24 hours * 4
            step_minutes=15,
            start_datetime="2025-01-01T00:00:00",
        )

        assert ts.steps == 96
        assert ts.step_minutes == 15
        assert len(ts.import_price_pln_per_mwh) == 96

    def test_period_end_calculated(self):
        """Period end is correctly calculated from steps."""
        prices = PriceConfig(
            import_price_pln_mwh=800.0,
            export_price_pln_mwh=400.0,
        )

        ts = generate_price_timeseries(
            prices=prices,
            n_steps=24,
            step_minutes=60,
            start_datetime="2025-01-01T00:00:00",
        )

        assert ts.period_start == "2025-01-01T00:00:00"
        assert ts.period_end == "2025-01-01T23:00:00"

    def test_unserved_penalty_included(self):
        """Unserved penalty is included in timeseries."""
        prices = PriceConfig(
            import_price_pln_mwh=800.0,
            export_price_pln_mwh=400.0,
        )

        ts = generate_price_timeseries(
            prices=prices,
            n_steps=24,
            step_minutes=60,
            start_datetime="2025-01-01T00:00:00",
            unserved_penalty_pln_kwh=15.0,
        )

        assert len(ts.unserved_penalty_pln_per_kwh) == 24
        assert ts.unserved_penalty_pln_per_kwh[0] == 15.0


class TestValidatePriceTimeseries:
    """Tests for validate_price_timeseries function."""

    def test_valid_timeseries(self):
        """Valid timeseries passes validation."""
        ts = PriceTimeseriesPlnPerMwh(
            import_price_pln_per_mwh=[800.0, 800.0, 800.0],
            export_price_pln_per_mwh=[400.0, 400.0, 400.0],
            step_minutes=60,
            steps=3,
            timezone="Europe/Warsaw",
            period_start="2025-01-01T00:00:00",
            period_end="2025-01-01T02:00:00",
        )

        is_valid, errors = validate_price_timeseries(ts, expected_steps=3)
        assert is_valid
        assert len(errors) == 0

    def test_steps_mismatch(self):
        """Detect steps mismatch."""
        ts = PriceTimeseriesPlnPerMwh(
            import_price_pln_per_mwh=[800.0, 800.0, 800.0],
            export_price_pln_per_mwh=[400.0, 400.0, 400.0],
            step_minutes=60,
            steps=3,
            timezone="Europe/Warsaw",
            period_start="2025-01-01T00:00:00",
            period_end="2025-01-01T02:00:00",
        )

        is_valid, errors = validate_price_timeseries(ts, expected_steps=24)
        assert not is_valid
        assert any("mismatch" in e for e in errors)

    def test_negative_import_price(self):
        """Detect negative import prices."""
        ts = PriceTimeseriesPlnPerMwh(
            import_price_pln_per_mwh=[800.0, -100.0, 800.0],  # Negative
            export_price_pln_per_mwh=[400.0, 400.0, 400.0],
            step_minutes=60,
            steps=3,
            timezone="Europe/Warsaw",
            period_start="2025-01-01T00:00:00",
            period_end="2025-01-01T02:00:00",
        )

        is_valid, errors = validate_price_timeseries(ts, expected_steps=3)
        assert not is_valid
        assert any("Negative" in e for e in errors)


class TestPriceTimeseriesModel:
    """Tests for PriceTimeseriesPlnPerMwh model."""

    def test_validate_lengths_pass(self):
        """Lengths match steps."""
        ts = PriceTimeseriesPlnPerMwh(
            import_price_pln_per_mwh=[800.0, 800.0],
            export_price_pln_per_mwh=[400.0, 400.0],
            step_minutes=60,
            steps=2,
            timezone="Europe/Warsaw",
            period_start="2025-01-01T00:00:00",
            period_end="2025-01-01T01:00:00",
        )

        assert ts.validate_lengths()

    def test_validate_lengths_fail(self):
        """Lengths don't match steps."""
        ts = PriceTimeseriesPlnPerMwh(
            import_price_pln_per_mwh=[800.0, 800.0, 800.0],  # 3 elements
            export_price_pln_per_mwh=[400.0, 400.0],  # 2 elements
            step_minutes=60,
            steps=3,
            timezone="Europe/Warsaw",
            period_start="2025-01-01T00:00:00",
            period_end="2025-01-01T02:00:00",
        )

        assert not ts.validate_lengths()

    def test_has_invalid_values_nan(self):
        """Detect NaN values."""
        import math
        ts = PriceTimeseriesPlnPerMwh(
            import_price_pln_per_mwh=[800.0, float('nan')],
            export_price_pln_per_mwh=[400.0, 400.0],
            step_minutes=60,
            steps=2,
            timezone="Europe/Warsaw",
            period_start="2025-01-01T00:00:00",
            period_end="2025-01-01T01:00:00",
        )

        assert ts.has_invalid_values()

    def test_has_invalid_values_inf(self):
        """Detect inf values."""
        ts = PriceTimeseriesPlnPerMwh(
            import_price_pln_per_mwh=[800.0, float('inf')],
            export_price_pln_per_mwh=[400.0, 400.0],
            step_minutes=60,
            steps=2,
            timezone="Europe/Warsaw",
            period_start="2025-01-01T00:00:00",
            period_end="2025-01-01T01:00:00",
        )

        assert ts.has_invalid_values()

    def test_no_invalid_values(self):
        """Clean values pass."""
        ts = PriceTimeseriesPlnPerMwh(
            import_price_pln_per_mwh=[800.0, 900.0],
            export_price_pln_per_mwh=[400.0, 400.0],
            step_minutes=60,
            steps=2,
            timezone="Europe/Warsaw",
            period_start="2025-01-01T00:00:00",
            period_end="2025-01-01T01:00:00",
        )

        assert not ts.has_invalid_values()

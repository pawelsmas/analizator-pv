"""
Unit tests for cycle_accounting_helper (v2.2.0 PR2).

Tests verify:
- EFC calculation
- Throughput calculation
- Daily cycle tracking
- Cycle limit enforcement
- CycleAccountingTracker class
"""

import pytest
import numpy as np
import sys
import os

# Add service path for imports
service_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "services", "bess-dispatch")
)
if service_path not in sys.path:
    sys.path.insert(0, service_path)

from cycle_accounting_helper import (
    compute_efc,
    compute_throughput_mwh,
    get_day_index,
    compute_cycles_per_day,
    compute_cycle_summary,
    compute_remaining_discharge_headroom,
    clamp_discharge_for_cycle_limit,
    CycleAccountingTracker,
)


class TestComputeEfc:
    """Tests for EFC calculation."""

    def test_basic_efc(self):
        """Verify basic EFC calculation."""
        # 100 kWh discharged from 100 kWh capacity = 1 EFC
        efc = compute_efc(100.0, 100.0)
        assert efc == pytest.approx(1.0)

    def test_fractional_efc(self):
        """Verify fractional EFC calculation."""
        # 50 kWh discharged from 100 kWh capacity = 0.5 EFC
        efc = compute_efc(50.0, 100.0)
        assert efc == pytest.approx(0.5)

    def test_multiple_cycles(self):
        """Verify multiple cycles calculation."""
        # 250 kWh discharged from 100 kWh capacity = 2.5 EFC
        efc = compute_efc(250.0, 100.0)
        assert efc == pytest.approx(2.5)

    def test_zero_discharge(self):
        """Verify zero discharge returns zero EFC."""
        efc = compute_efc(0.0, 100.0)
        assert efc == 0.0

    def test_zero_capacity_returns_zero(self):
        """Verify zero capacity returns zero EFC (not infinity)."""
        efc = compute_efc(100.0, 0.0)
        assert efc == 0.0


class TestComputeThroughputMwh:
    """Tests for throughput calculation."""

    def test_basic_throughput(self):
        """Verify basic throughput calculation."""
        # 100 kWh charge + 100 kWh discharge = 0.2 MWh
        throughput = compute_throughput_mwh(100.0, 100.0)
        assert throughput == pytest.approx(0.2)

    def test_asymmetric_throughput(self):
        """Verify asymmetric throughput calculation."""
        # 150 kWh charge + 100 kWh discharge = 0.25 MWh
        throughput = compute_throughput_mwh(150.0, 100.0)
        assert throughput == pytest.approx(0.25)

    def test_zero_throughput(self):
        """Verify zero throughput."""
        throughput = compute_throughput_mwh(0.0, 0.0)
        assert throughput == 0.0


class TestGetDayIndex:
    """Tests for day index calculation."""

    def test_first_day_hourly(self):
        """Verify first day for hourly steps."""
        # Steps 0-23 should be day 0
        for step in range(24):
            assert get_day_index(step, 60) == 0

    def test_second_day_hourly(self):
        """Verify second day for hourly steps."""
        # Steps 24-47 should be day 1
        for step in range(24, 48):
            assert get_day_index(step, 60) == 1

    def test_first_day_15min(self):
        """Verify first day for 15-min steps."""
        # Steps 0-95 should be day 0 (96 steps = 24 hours)
        for step in range(96):
            assert get_day_index(step, 15) == 0

    def test_second_day_15min(self):
        """Verify second day for 15-min steps."""
        # Steps 96-191 should be day 1
        for step in range(96, 192):
            assert get_day_index(step, 15) == 1


class TestComputeCyclesPerDay:
    """Tests for daily cycle calculation."""

    def test_single_day(self):
        """Verify single day cycle calculation."""
        # 24 hours of 10 kW discharge = 240 kWh
        # With 100 kWh usable capacity = 2.4 EFC
        discharge_kw = np.full(24, 10.0)
        cycles = compute_cycles_per_day(discharge_kw, 60, 100.0)

        assert len(cycles) == 1
        assert cycles[0] == pytest.approx(2.4)

    def test_two_days(self):
        """Verify two-day cycle calculation."""
        # 48 hours of 10 kW discharge
        discharge_kw = np.full(48, 10.0)
        cycles = compute_cycles_per_day(discharge_kw, 60, 100.0)

        assert len(cycles) == 2
        assert cycles[0] == pytest.approx(2.4)
        assert cycles[1] == pytest.approx(2.4)

    def test_varying_discharge(self):
        """Verify varying discharge calculation."""
        # Day 1: 10 kW for 24h = 240 kWh = 2.4 EFC
        # Day 2: 5 kW for 24h = 120 kWh = 1.2 EFC
        discharge_kw = np.concatenate([np.full(24, 10.0), np.full(24, 5.0)])
        cycles = compute_cycles_per_day(discharge_kw, 60, 100.0)

        assert len(cycles) == 2
        assert cycles[0] == pytest.approx(2.4)
        assert cycles[1] == pytest.approx(1.2)

    def test_empty_array(self):
        """Verify empty array returns empty list."""
        cycles = compute_cycles_per_day(np.array([]), 60, 100.0)
        assert cycles == []


class TestComputeCycleSummary:
    """Tests for cycle summary calculation."""

    def test_basic_summary(self):
        """Verify basic summary calculation."""
        charge_kw = np.full(24, 10.0)
        discharge_kw = np.full(24, 10.0)

        summary = compute_cycle_summary(charge_kw, discharge_kw, 60, 100.0)

        assert summary.total_charge_kwh == pytest.approx(240.0)
        assert summary.total_discharge_kwh == pytest.approx(240.0)
        assert summary.total_throughput_kwh == pytest.approx(480.0)
        assert summary.efc_total == pytest.approx(2.4)
        assert len(summary.cycles_per_day) == 1
        assert summary.max_daily_efc == pytest.approx(2.4)
        assert summary.avg_daily_efc == pytest.approx(2.4)

    def test_summary_with_limit(self):
        """Verify summary with cycle limit counts exceeded days."""
        discharge_kw = np.concatenate([np.full(24, 20.0), np.full(24, 5.0)])
        charge_kw = np.full(48, 10.0)

        summary = compute_cycle_summary(
            charge_kw, discharge_kw, 60, 100.0, max_cycles_per_day=2.0
        )

        # Day 1: 20 kW * 24h = 480 kWh = 4.8 EFC (exceeds 2.0)
        # Day 2: 5 kW * 24h = 120 kWh = 1.2 EFC (OK)
        assert summary.days_exceeding_limit == 1


class TestComputeRemainingDischargeHeadroom:
    """Tests for remaining discharge headroom calculation."""

    def test_full_headroom(self):
        """Verify full headroom when no discharge yet."""
        # 2 EFC/day limit, 100 kWh capacity = 200 kWh/day allowed
        remaining = compute_remaining_discharge_headroom(0.0, 100.0, 2.0)
        assert remaining == pytest.approx(200.0)

    def test_partial_headroom(self):
        """Verify partial headroom after some discharge."""
        # Already discharged 100 kWh, limit is 200 kWh
        remaining = compute_remaining_discharge_headroom(100.0, 100.0, 2.0)
        assert remaining == pytest.approx(100.0)

    def test_no_headroom(self):
        """Verify zero headroom when limit reached."""
        # Already discharged 200 kWh, limit is 200 kWh
        remaining = compute_remaining_discharge_headroom(200.0, 100.0, 2.0)
        assert remaining == pytest.approx(0.0)

    def test_over_limit_returns_zero(self):
        """Verify zero headroom when over limit."""
        # Already discharged 250 kWh, limit is 200 kWh
        remaining = compute_remaining_discharge_headroom(250.0, 100.0, 2.0)
        assert remaining == pytest.approx(0.0)


class TestClampDischargeForCycleLimit:
    """Tests for discharge clamping."""

    def test_no_clamping_needed(self):
        """Verify no clamping when under limit."""
        # 2 EFC/day limit, 100 kWh capacity = 200 kWh/day
        # Want 10 kW for 1 hour = 10 kWh
        clamped_kw, actual_kwh = clamp_discharge_for_cycle_limit(
            10.0, 0.0, 100.0, 2.0, 1.0
        )
        assert clamped_kw == pytest.approx(10.0)
        assert actual_kwh == pytest.approx(10.0)

    def test_clamping_at_limit(self):
        """Verify clamping when approaching limit."""
        # Already discharged 190 kWh, limit is 200 kWh
        # Want 20 kW for 1 hour = 20 kWh, but only 10 kWh remaining
        clamped_kw, actual_kwh = clamp_discharge_for_cycle_limit(
            20.0, 190.0, 100.0, 2.0, 1.0
        )
        assert clamped_kw == pytest.approx(10.0)
        assert actual_kwh == pytest.approx(10.0)

    def test_no_discharge_at_limit(self):
        """Verify no discharge when limit reached."""
        # Already discharged 200 kWh, limit is 200 kWh
        clamped_kw, actual_kwh = clamp_discharge_for_cycle_limit(
            20.0, 200.0, 100.0, 2.0, 1.0
        )
        assert clamped_kw == pytest.approx(0.0)
        assert actual_kwh == pytest.approx(0.0)

    def test_zero_desired_discharge(self):
        """Verify zero desired discharge returns zero."""
        clamped_kw, actual_kwh = clamp_discharge_for_cycle_limit(
            0.0, 0.0, 100.0, 2.0, 1.0
        )
        assert clamped_kw == 0.0
        assert actual_kwh == 0.0


class TestCycleAccountingTracker:
    """Tests for CycleAccountingTracker class."""

    def test_no_limit(self):
        """Verify tracker works without limit."""
        tracker = CycleAccountingTracker(100.0, None, 60)

        # Process 24 hours
        for t in range(24):
            discharge_kw, clamped = tracker.process_step(t, 10.0, 1.0, 5.0)
            assert discharge_kw == pytest.approx(10.0)
            assert clamped is False

        summary = tracker.finalize()
        assert summary.total_discharge_kwh == pytest.approx(240.0)

    def test_with_limit(self):
        """Verify tracker enforces limit."""
        # 1 EFC/day limit, 100 kWh capacity = 100 kWh/day
        tracker = CycleAccountingTracker(100.0, 1.0, 60)

        total_discharge = 0.0
        clamped_count = 0

        # Try to discharge 10 kW for 24 hours = 240 kWh (but limit is 100 kWh)
        for t in range(24):
            discharge_kw, clamped = tracker.process_step(t, 10.0, 1.0)
            total_discharge += discharge_kw
            if clamped:
                clamped_count += 1

        # Should be clamped to 100 kWh for the day
        assert total_discharge == pytest.approx(100.0)
        assert clamped_count > 0

    def test_day_boundary(self):
        """Verify tracker resets at day boundary."""
        # 1 EFC/day limit
        tracker = CycleAccountingTracker(100.0, 1.0, 60)

        # Day 1: discharge 100 kWh (hit limit)
        for t in range(10):
            tracker.process_step(t, 10.0, 1.0)

        # At step 10, should be at limit (100 kWh)
        _, clamped = tracker.process_step(10, 10.0, 1.0)
        assert clamped is True

        # Day 2: step 24 should reset limit
        _, clamped = tracker.process_step(24, 10.0, 1.0)
        assert clamped is False

    def test_finalize_summary(self):
        """Verify finalize returns correct summary."""
        tracker = CycleAccountingTracker(100.0, 2.0, 60)

        # Process 48 hours (2 days)
        for t in range(48):
            tracker.process_step(t, 5.0, 1.0, 5.0)

        summary = tracker.finalize()

        assert len(summary.cycles_per_day) == 2
        assert summary.total_discharge_kwh == pytest.approx(240.0)  # 5 kW * 48h
        assert summary.efc_total == pytest.approx(2.4)


class TestCycleAccountingIntegration:
    """Integration tests for cycle accounting."""

    def test_week_simulation(self):
        """Verify week-long simulation with varying discharge."""
        tracker = CycleAccountingTracker(100.0, 2.0, 60)

        # 7 days of varying discharge
        discharge_pattern = [10.0, 8.0, 12.0, 6.0, 15.0, 5.0, 7.0]  # kW per day

        for day in range(7):
            for hour in range(24):
                step = day * 24 + hour
                tracker.process_step(step, discharge_pattern[day], 1.0)

        summary = tracker.finalize()

        assert len(summary.cycles_per_day) == 7
        # Day with 15 kW should be clamped to limit
        assert summary.cycles_per_day[4] <= 2.0  # Max 2 EFC/day

    def test_15min_intervals(self):
        """Verify 15-minute interval tracking."""
        tracker = CycleAccountingTracker(100.0, 1.0, 15)

        # 1 day = 96 steps at 15-min intervals
        for t in range(96):
            tracker.process_step(t, 10.0, 0.25)

        summary = tracker.finalize()

        assert len(summary.cycles_per_day) == 1
        # 10 kW * 24h = 240 kWh, but limited to 100 kWh (1 EFC)
        assert summary.total_discharge_kwh == pytest.approx(100.0)

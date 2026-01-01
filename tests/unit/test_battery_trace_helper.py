"""
Unit tests for battery_trace_helper (v2.2.0 PR1).

Tests verify:
- create_battery_trace function
- create_battery_trace_from_dispatch_result function
- validate_battery_trace function
- BatteryTraceTimeseries model validation methods
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

from models import BatteryTraceTimeseries
from battery_trace_helper import (
    create_battery_trace,
    create_battery_trace_from_dispatch_result,
    validate_battery_trace,
)


class TestCreateBatteryTrace:
    """Tests for create_battery_trace function."""

    def test_basic_creation(self):
        """Verify basic trace creation with numpy arrays."""
        n = 24
        soc_kwh = np.linspace(20, 30, n)
        charge_kw = np.full(n, 10.0)
        discharge_kw = np.full(n, 5.0)
        charge_from_pv_kw = np.full(n, 10.0)
        charge_from_grid_kw = np.zeros(n)
        discharge_to_load_kw = np.full(n, 5.0)
        discharge_to_grid_kw = np.zeros(n)

        trace = create_battery_trace(
            soc_kwh=soc_kwh,
            charge_kw=charge_kw,
            discharge_kw=discharge_kw,
            charge_from_pv_kw=charge_from_pv_kw,
            charge_from_grid_kw=charge_from_grid_kw,
            discharge_to_load_kw=discharge_to_load_kw,
            discharge_to_grid_kw=discharge_to_grid_kw,
            step_minutes=60,
            battery_energy_kwh=40.0,
            battery_power_kw=20.0,
        )

        assert trace.steps == n
        assert trace.step_minutes == 60
        assert trace.battery_energy_kwh == 40.0
        assert trace.battery_power_kw == 20.0
        assert len(trace.soc_kwh) == n
        assert len(trace.charge_kw) == n

    def test_none_grid_charge(self):
        """Verify None charge_from_grid_kw creates zeros."""
        n = 24
        trace = create_battery_trace(
            soc_kwh=np.full(n, 20.0),
            charge_kw=np.full(n, 10.0),
            discharge_kw=np.zeros(n),
            charge_from_pv_kw=np.full(n, 10.0),
            charge_from_grid_kw=None,
            discharge_to_load_kw=np.zeros(n),
            discharge_to_grid_kw=None,
            step_minutes=60,
            battery_energy_kwh=40.0,
            battery_power_kw=20.0,
        )

        assert all(v == 0 for v in trace.charge_from_grid_kw)
        assert all(v == 0 for v in trace.discharge_to_grid_kw)


class TestCreateBatteryTraceFromDispatchResult:
    """Tests for create_battery_trace_from_dispatch_result function."""

    def test_soc_array_slicing(self):
        """Verify SOC array is correctly sliced (n+1 -> n)."""
        n = 24
        # SOC array from dispatch has n+1 values
        soc_array = np.linspace(20, 30, n + 1)
        charge_array = np.full(n, 10.0)
        discharge_array = np.full(n, 5.0)

        trace = create_battery_trace_from_dispatch_result(
            soc_array=soc_array,
            charge_array=charge_array,
            discharge_array=discharge_array,
            charge_from_pv_array=charge_array,
            charge_from_grid_array=None,
            discharge_to_load_array=discharge_array,
            discharge_to_grid_array=None,
            interval_minutes=60,
            battery_energy_kwh=40.0,
            battery_power_kw=20.0,
        )

        # Should use soc[1:n+1], which has n elements
        assert len(trace.soc_kwh) == n
        assert trace.steps == n
        # First SOC value should be soc_array[1], not soc_array[0]
        assert trace.soc_kwh[0] == pytest.approx(soc_array[1])


class TestValidateBatteryTrace:
    """Tests for validate_battery_trace function."""

    def get_valid_trace(self, n: int = 24) -> BatteryTraceTimeseries:
        """Create a valid battery trace for testing."""
        return BatteryTraceTimeseries(
            soc_kwh=[20.0] * n,
            charge_kw=[10.0] * n,
            discharge_kw=[5.0] * n,
            charge_from_pv_kw=[10.0] * n,
            charge_from_grid_kw=[0.0] * n,
            discharge_to_load_kw=[5.0] * n,
            discharge_to_grid_kw=[0.0] * n,
            steps=n,
            step_minutes=60,
            battery_energy_kwh=40.0,
            battery_power_kw=20.0,
        )

    def test_valid_trace_passes(self):
        """Verify valid trace passes all checks."""
        trace = self.get_valid_trace()
        result = validate_battery_trace(trace)

        assert result["all_ok"] is True
        assert result["lengths_ok"] is True
        assert result["soc_bounds_ok"] is True
        assert result["power_non_negative_ok"] is True
        assert result["charge_split_ok"] is True
        assert result["discharge_split_ok"] is True
        assert len(result["errors"]) == 0

    def test_soc_bounds_violation(self):
        """Verify SOC bounds violation is detected."""
        trace = BatteryTraceTimeseries(
            soc_kwh=[50.0] * 24,  # Exceeds battery_energy_kwh=40
            charge_kw=[10.0] * 24,
            discharge_kw=[5.0] * 24,
            charge_from_pv_kw=[10.0] * 24,
            charge_from_grid_kw=[0.0] * 24,
            discharge_to_load_kw=[5.0] * 24,
            discharge_to_grid_kw=[0.0] * 24,
            steps=24,
            step_minutes=60,
            battery_energy_kwh=40.0,
            battery_power_kw=20.0,
        )
        result = validate_battery_trace(trace)

        assert result["all_ok"] is False
        assert result["soc_bounds_ok"] is False

    def test_negative_soc_violation(self):
        """Verify negative SOC is detected."""
        trace = BatteryTraceTimeseries(
            soc_kwh=[-5.0] * 24,  # Negative SOC
            charge_kw=[10.0] * 24,
            discharge_kw=[5.0] * 24,
            charge_from_pv_kw=[10.0] * 24,
            charge_from_grid_kw=[0.0] * 24,
            discharge_to_load_kw=[5.0] * 24,
            discharge_to_grid_kw=[0.0] * 24,
            steps=24,
            step_minutes=60,
            battery_energy_kwh=40.0,
            battery_power_kw=20.0,
        )
        result = validate_battery_trace(trace)

        assert result["all_ok"] is False
        assert result["soc_bounds_ok"] is False

    def test_charge_split_mismatch(self):
        """Verify charge split mismatch is detected."""
        trace = BatteryTraceTimeseries(
            soc_kwh=[20.0] * 24,
            charge_kw=[15.0] * 24,  # Total charge
            discharge_kw=[5.0] * 24,
            charge_from_pv_kw=[5.0] * 24,  # Only 5
            charge_from_grid_kw=[5.0] * 24,  # Only 5, sum=10 != 15
            discharge_to_load_kw=[5.0] * 24,
            discharge_to_grid_kw=[0.0] * 24,
            steps=24,
            step_minutes=60,
            battery_energy_kwh=40.0,
            battery_power_kw=20.0,
        )
        result = validate_battery_trace(trace)

        assert result["all_ok"] is False
        assert result["charge_split_ok"] is False

    def test_discharge_split_mismatch(self):
        """Verify discharge split mismatch is detected."""
        trace = BatteryTraceTimeseries(
            soc_kwh=[20.0] * 24,
            charge_kw=[10.0] * 24,
            discharge_kw=[15.0] * 24,  # Total discharge
            charge_from_pv_kw=[10.0] * 24,
            charge_from_grid_kw=[0.0] * 24,
            discharge_to_load_kw=[5.0] * 24,  # Only 5
            discharge_to_grid_kw=[5.0] * 24,  # Only 5, sum=10 != 15
            steps=24,
            step_minutes=60,
            battery_energy_kwh=40.0,
            battery_power_kw=20.0,
        )
        result = validate_battery_trace(trace)

        assert result["all_ok"] is False
        assert result["discharge_split_ok"] is False


class TestBatteryTraceTimeseriesModel:
    """Tests for BatteryTraceTimeseries model methods."""

    def test_validate_lengths_ok(self):
        """Verify validate_lengths returns True for correct lengths."""
        trace = BatteryTraceTimeseries(
            soc_kwh=[20.0] * 24,
            charge_kw=[10.0] * 24,
            discharge_kw=[5.0] * 24,
            charge_from_pv_kw=[10.0] * 24,
            charge_from_grid_kw=[0.0] * 24,
            discharge_to_load_kw=[5.0] * 24,
            discharge_to_grid_kw=[0.0] * 24,
            steps=24,
            step_minutes=60,
            battery_energy_kwh=40.0,
            battery_power_kw=20.0,
        )
        assert trace.validate_lengths() is True

    def test_validate_lengths_fail(self):
        """Verify validate_lengths returns False for incorrect lengths."""
        trace = BatteryTraceTimeseries(
            soc_kwh=[20.0] * 23,  # Wrong length
            charge_kw=[10.0] * 24,
            discharge_kw=[5.0] * 24,
            charge_from_pv_kw=[10.0] * 24,
            charge_from_grid_kw=[0.0] * 24,
            discharge_to_load_kw=[5.0] * 24,
            discharge_to_grid_kw=[0.0] * 24,
            steps=24,
            step_minutes=60,
            battery_energy_kwh=40.0,
            battery_power_kw=20.0,
        )
        assert trace.validate_lengths() is False

    def test_validate_soc_bounds_ok(self):
        """Verify validate_soc_bounds returns True for valid SOC."""
        trace = BatteryTraceTimeseries(
            soc_kwh=[20.0] * 24,
            charge_kw=[10.0] * 24,
            discharge_kw=[5.0] * 24,
            charge_from_pv_kw=[10.0] * 24,
            charge_from_grid_kw=[0.0] * 24,
            discharge_to_load_kw=[5.0] * 24,
            discharge_to_grid_kw=[0.0] * 24,
            steps=24,
            step_minutes=60,
            battery_energy_kwh=40.0,
            battery_power_kw=20.0,
        )
        assert trace.validate_soc_bounds() is True

    def test_validate_power_non_negative_ok(self):
        """Verify validate_power_non_negative returns True for positive power."""
        trace = BatteryTraceTimeseries(
            soc_kwh=[20.0] * 24,
            charge_kw=[10.0] * 24,
            discharge_kw=[5.0] * 24,
            charge_from_pv_kw=[10.0] * 24,
            charge_from_grid_kw=[0.0] * 24,
            discharge_to_load_kw=[5.0] * 24,
            discharge_to_grid_kw=[0.0] * 24,
            steps=24,
            step_minutes=60,
            battery_energy_kwh=40.0,
            battery_power_kw=20.0,
        )
        assert trace.validate_power_non_negative() is True

    def test_validate_power_non_negative_fail(self):
        """Verify validate_power_non_negative returns False for negative power."""
        trace = BatteryTraceTimeseries(
            soc_kwh=[20.0] * 24,
            charge_kw=[-10.0] * 24,  # Negative charge
            discharge_kw=[5.0] * 24,
            charge_from_pv_kw=[10.0] * 24,
            charge_from_grid_kw=[0.0] * 24,
            discharge_to_load_kw=[5.0] * 24,
            discharge_to_grid_kw=[0.0] * 24,
            steps=24,
            step_minutes=60,
            battery_energy_kwh=40.0,
            battery_power_kw=20.0,
        )
        assert trace.validate_power_non_negative() is False


class TestBatteryTraceEdgeCases:
    """Tests for edge cases in battery trace."""

    def test_single_step(self):
        """Verify handling of single step arrays."""
        trace = create_battery_trace(
            soc_kwh=np.array([20.0]),
            charge_kw=np.array([10.0]),
            discharge_kw=np.array([5.0]),
            charge_from_pv_kw=np.array([10.0]),
            charge_from_grid_kw=None,
            discharge_to_load_kw=np.array([5.0]),
            discharge_to_grid_kw=None,
            step_minutes=15,
            battery_energy_kwh=40.0,
            battery_power_kw=20.0,
        )
        assert trace.steps == 1
        assert trace.step_minutes == 15

    def test_list_inputs(self):
        """Verify handling of list inputs (not numpy arrays)."""
        n = 24
        trace = create_battery_trace(
            soc_kwh=[20.0] * n,
            charge_kw=[10.0] * n,
            discharge_kw=[5.0] * n,
            charge_from_pv_kw=[10.0] * n,
            charge_from_grid_kw=[0.0] * n,
            discharge_to_load_kw=[5.0] * n,
            discharge_to_grid_kw=[0.0] * n,
            step_minutes=60,
            battery_energy_kwh=40.0,
            battery_power_kw=20.0,
        )
        assert trace.steps == n
        assert isinstance(trace.soc_kwh, list)

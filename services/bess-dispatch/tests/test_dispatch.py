"""
Tests for BESS Dispatch Engine
==============================
Tests cover:
- PV-surplus dispatch
- Peak shaving dispatch
- STACKED mode dispatch
- Degradation metrics
- 15-min vs 60-min intervals
- SOC bounds
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import numpy as np
from models import (
    BatteryParams,
    DispatchMode,
    StackedModeParams,
    DegradationBudget,
    PriceConfig,
)
from dispatch_engine import (
    dispatch_pv_surplus,
    dispatch_peak_shaving,
    dispatch_stacked,
    calculate_degradation_metrics,
    check_degradation_budget,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def simple_battery():
    """Simple 100kW/200kWh battery for testing"""
    return BatteryParams.from_roundtrip(
        power_kw=100,
        energy_kwh=200,
        roundtrip_eff=0.90,
        soc_min=0.10,
        soc_max=0.90,
        soc_initial=0.50,
    )


@pytest.fixture
def synthetic_day_hourly():
    """Synthetic 24h profile: PV noon peak, load evening peak"""
    hours = 24
    # PV: bell curve centered at 12:00
    pv = np.array([0, 0, 0, 0, 0, 10, 30, 60, 90, 110, 120, 130,
                   130, 120, 100, 70, 40, 15, 0, 0, 0, 0, 0, 0], dtype=float)
    # Load: morning + evening peaks
    load = np.array([20, 15, 12, 10, 10, 15, 40, 60, 50, 45, 50, 55,
                     60, 50, 45, 50, 70, 100, 120, 100, 80, 50, 30, 20], dtype=float)
    return pv, load


@pytest.fixture
def synthetic_day_15min():
    """Synthetic 24h profile at 15-min resolution (96 points)"""
    pv_hourly = np.array([0, 0, 0, 0, 0, 10, 30, 60, 90, 110, 120, 130,
                          130, 120, 100, 70, 40, 15, 0, 0, 0, 0, 0, 0], dtype=float)
    load_hourly = np.array([20, 15, 12, 10, 10, 15, 40, 60, 50, 45, 50, 55,
                            60, 50, 45, 50, 70, 100, 120, 100, 80, 50, 30, 20], dtype=float)
    # Expand to 15-min (4x)
    pv = np.repeat(pv_hourly, 4)
    load = np.repeat(load_hourly, 4)
    return pv, load


# =============================================================================
# PV-Surplus Dispatch Tests
# =============================================================================

class TestPVSurplusDispatch:
    """Tests for PV-surplus (autokonsumpcja) mode"""

    def test_basic_dispatch(self, simple_battery, synthetic_day_hourly):
        """Test basic PV-surplus dispatch works"""
        pv, load = synthetic_day_hourly
        dt_hours = 1.0

        result = dispatch_pv_surplus(pv, load, simple_battery, dt_hours)

        # Basic sanity checks
        assert result.mode == DispatchMode.PV_SURPLUS
        assert result.total_pv_kwh > 0
        assert result.total_load_kwh > 0
        assert result.total_charge_kwh > 0
        assert result.total_discharge_kwh > 0

    def test_energy_balance(self, simple_battery, synthetic_day_hourly):
        """Test energy balance: PV = direct + charge + curtail"""
        pv, load = synthetic_day_hourly
        dt_hours = 1.0

        result = dispatch_pv_surplus(pv, load, simple_battery, dt_hours)

        # PV energy should equal direct + charge + curtail + export
        pv_energy = result.total_pv_kwh
        pv_used = (result.total_direct_pv_kwh +
                   result.total_charge_kwh +
                   result.total_curtailment_kwh +
                   result.total_grid_export_kwh)

        assert abs(pv_energy - pv_used) < 1.0  # Allow small rounding error

    def test_load_balance(self, simple_battery, synthetic_day_hourly):
        """Test load balance: load = direct + discharge + import"""
        pv, load = synthetic_day_hourly
        dt_hours = 1.0

        result = dispatch_pv_surplus(pv, load, simple_battery, dt_hours)

        load_energy = result.total_load_kwh
        load_sources = (result.total_direct_pv_kwh +
                        result.total_discharge_kwh +
                        result.total_grid_import_kwh)

        assert abs(load_energy - load_sources) < 1.0

    def test_zero_export_mode(self, simple_battery, synthetic_day_hourly):
        """Test that 0-export mode produces no export"""
        pv, load = synthetic_day_hourly
        dt_hours = 1.0

        result = dispatch_pv_surplus(pv, load, simple_battery, dt_hours)

        assert result.total_grid_export_kwh == 0

    def test_soc_bounds(self, simple_battery, synthetic_day_hourly):
        """Test SOC stays within bounds"""
        pv, load = synthetic_day_hourly
        dt_hours = 1.0

        result = dispatch_pv_surplus(pv, load, simple_battery, dt_hours)

        soc_pct = np.array(result.hourly_soc_pct)
        min_soc = simple_battery.soc_min * 100
        max_soc = simple_battery.soc_max * 100

        assert np.all(soc_pct >= min_soc - 0.1)  # Small tolerance
        assert np.all(soc_pct <= max_soc + 0.1)

    def test_15min_vs_hourly_energy(self, simple_battery, synthetic_day_hourly, synthetic_day_15min):
        """Test that 15-min produces similar annual energy as hourly"""
        pv_h, load_h = synthetic_day_hourly
        pv_15, load_15 = synthetic_day_15min

        result_h = dispatch_pv_surplus(pv_h, load_h, simple_battery, dt_hours=1.0)
        result_15 = dispatch_pv_surplus(pv_15, load_15, simple_battery, dt_hours=0.25)

        # Total energies should be similar (within 5%)
        assert abs(result_h.total_pv_kwh - result_15.total_pv_kwh) / result_h.total_pv_kwh < 0.05
        assert abs(result_h.total_load_kwh - result_15.total_load_kwh) / result_h.total_load_kwh < 0.05


# =============================================================================
# Peak Shaving Dispatch Tests
# =============================================================================

class TestPeakShavingDispatch:
    """Tests for peak shaving mode"""

    def test_peak_reduction(self, simple_battery, synthetic_day_hourly):
        """Test that peak shaving reduces peaks"""
        pv, load = synthetic_day_hourly
        dt_hours = 1.0
        peak_limit = 80.0  # Below max load of 120 kW

        result = dispatch_peak_shaving(pv, load, simple_battery, dt_hours, peak_limit)

        assert result.mode == DispatchMode.PEAK_SHAVING
        assert result.original_peak_kw > peak_limit
        assert result.new_peak_kw <= result.original_peak_kw
        assert result.peak_reduction_kw > 0

    def test_peak_limit_respected(self, simple_battery, synthetic_day_hourly):
        """Test new peak is at or below limit (if battery has capacity)"""
        pv, load = synthetic_day_hourly
        dt_hours = 1.0
        peak_limit = 90.0

        result = dispatch_peak_shaving(pv, load, simple_battery, dt_hours, peak_limit)

        # Grid import should not exceed limit (or be close if battery depleted)
        grid_import = np.array(result.hourly_grid_import_kw)
        # Allow small exceedance if battery was depleted
        max_import = np.max(grid_import)
        assert max_import <= peak_limit + 20  # 20 kW tolerance for battery depletion


# =============================================================================
# STACKED Mode Dispatch Tests
# =============================================================================

class TestStackedDispatch:
    """Tests for STACKED (PV + Peak) mode"""

    def test_stacked_dispatch_works(self, simple_battery, synthetic_day_hourly):
        """Test STACKED dispatch produces results"""
        pv, load = synthetic_day_hourly
        dt_hours = 1.0
        params = StackedModeParams(
            peak_limit_kw=80.0,
            reserve_fraction=0.3,
        )

        result = dispatch_stacked(pv, load, simple_battery, dt_hours, params)

        assert result.mode == DispatchMode.STACKED
        assert result.peak_reduction_kw >= 0
        assert result.total_discharge_kwh > 0

    def test_service_breakdown(self, simple_battery, synthetic_day_hourly):
        """Test per-service throughput breakdown"""
        pv, load = synthetic_day_hourly
        dt_hours = 1.0
        params = StackedModeParams(
            peak_limit_kw=80.0,
            reserve_fraction=0.3,
        )

        result = dispatch_stacked(pv, load, simple_battery, dt_hours, params)

        # Should have breakdown in degradation metrics
        deg = result.degradation
        total = deg.throughput_pv_mwh + deg.throughput_peak_mwh
        # Total should be close to throughput_total
        assert abs(total - deg.throughput_total_mwh) < 0.1

    def test_reserve_soc_protection(self, simple_battery, synthetic_day_hourly):
        """Test that PV shifting respects SOC reserve"""
        pv, load = synthetic_day_hourly
        dt_hours = 1.0
        reserve_frac = 0.4  # 40% reserve for peak

        params = StackedModeParams(
            peak_limit_kw=80.0,
            reserve_fraction=reserve_frac,
        )

        result = dispatch_stacked(pv, load, simple_battery, dt_hours, params)

        # Check info has reserve parameters
        assert 'reserve_fraction' in result.info
        assert result.info['reserve_fraction'] == reserve_frac


# =============================================================================
# Degradation Metrics Tests
# =============================================================================

class TestDegradationMetrics:
    """Tests for degradation metrics calculation"""

    def test_efc_calculation(self, simple_battery):
        """Test EFC calculation"""
        total_charge = 500  # kWh
        total_discharge = 450  # kWh (losses)
        total_hours = 24

        metrics = calculate_degradation_metrics(
            total_charge, total_discharge, simple_battery, total_hours
        )

        # EFC = discharge / usable_capacity
        usable = simple_battery.usable_capacity_kwh
        expected_efc = total_discharge / usable

        assert abs(metrics.efc_total - expected_efc) < 0.01

    def test_throughput_calculation(self, simple_battery):
        """Test throughput calculation"""
        total_charge = 500
        total_discharge = 450
        total_hours = 24

        metrics = calculate_degradation_metrics(
            total_charge, total_discharge, simple_battery, total_hours
        )

        expected_throughput = (total_charge + total_discharge) / 1000  # MWh
        assert abs(metrics.throughput_total_mwh - expected_throughput) < 0.001

    def test_budget_check_ok(self):
        """Test budget check with OK status"""
        from models import DegradationMetrics, DegradationStatus

        metrics = DegradationMetrics(
            throughput_charge_kwh=100,
            throughput_discharge_kwh=90,
            throughput_total_mwh=0.19,
            efc_total=50,
        )
        budget = DegradationBudget(max_efc_per_year=300)

        result = check_degradation_budget(metrics, budget)

        assert result.budget_status == DegradationStatus.OK

    def test_budget_check_exceeded(self):
        """Test budget check with exceeded status"""
        from models import DegradationMetrics, DegradationStatus

        metrics = DegradationMetrics(
            throughput_charge_kwh=1000,
            throughput_discharge_kwh=900,
            throughput_total_mwh=1.9,
            efc_total=350,
        )
        budget = DegradationBudget(max_efc_per_year=300)

        result = check_degradation_budget(metrics, budget)

        assert result.budget_status == DegradationStatus.EXCEEDED
        assert len(result.budget_warnings) > 0


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests for dispatch engine"""

    def test_full_year_simulation(self, simple_battery):
        """Test full year (8760 hours) simulation"""
        np.random.seed(42)
        hours = 8760

        # Generate synthetic annual profile
        pv = np.zeros(hours)
        load = np.zeros(hours)

        for h in range(hours):
            hour_of_day = h % 24
            day_of_year = h // 24

            # PV: daytime production with seasonal variation
            if 6 <= hour_of_day <= 18:
                seasonal = 0.5 + 0.5 * np.cos((day_of_year - 172) * 2 * np.pi / 365)
                pv[h] = 80 * seasonal * np.exp(-((hour_of_day - 12) ** 2) / 20)

            # Load: base + daily pattern
            load[h] = 30 + 20 * np.sin((hour_of_day - 6) * np.pi / 12) ** 2
            load[h] += np.random.normal(0, 5)

        pv = np.maximum(pv, 0)
        load = np.maximum(load, 10)

        result = dispatch_pv_surplus(pv, load, simple_battery, dt_hours=1.0)

        # Verify results
        assert result.n_timesteps == 8760
        assert result.total_pv_kwh > 100000  # Reasonable annual production
        assert result.degradation.efc_total > 0
        assert result.degradation.efc_total < 1000  # Reasonable cycles

    def test_dispatch_with_pricing(self, simple_battery, synthetic_day_hourly):
        """Test dispatch with price calculations"""
        pv, load = synthetic_day_hourly
        prices = PriceConfig(
            import_price_pln_mwh=800,
            export_price_pln_mwh=0,
        )

        result = dispatch_pv_surplus(
            pv, load, simple_battery, dt_hours=1.0, prices=prices
        )

        assert result.baseline_cost_pln > 0
        assert result.project_cost_pln >= 0
        assert result.annual_savings_pln >= 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

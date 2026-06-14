"""
Tests for LP Dispatch Engine
=============================
Tests cover:
- LP solver basic operation
- SoC bounds enforcement
- C-rate limits
- Zero-export constraint (PV_SURPLUS mode)
- Peak shaving constraint
- Rolling horizon continuity
- LP vs greedy savings comparison
- Full year performance
- DispatchResult format compatibility
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import numpy as np
from models import (
    BatteryParams,
    DispatchMode,
    PriceConfig,
    LPSolverParams,
    SolverType,
)
from lp_dispatch import (
    dispatch_lp,
    solve_lp_window,
    lp_dispatch_rolling,
    resolve_price_arrays,
    _build_difference_matrix,
    _build_power_constraints,
    _build_cost_constraints,
    _build_mode_constraints,
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
def small_battery():
    """Small 10kW/20kWh battery for fast tests"""
    return BatteryParams.from_roundtrip(
        power_kw=10,
        energy_kwh=20,
        roundtrip_eff=0.90,
        soc_min=0.10,
        soc_max=0.90,
        soc_initial=0.50,
    )


@pytest.fixture
def synthetic_day_hourly():
    """Synthetic 24h profile: PV noon peak, load evening peak"""
    pv = np.array([0, 0, 0, 0, 0, 10, 30, 60, 90, 110, 120, 130,
                   130, 120, 100, 70, 40, 15, 0, 0, 0, 0, 0, 0], dtype=float)
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
    pv = np.repeat(pv_hourly, 4)
    load = np.repeat(load_hourly, 4)
    return pv, load


@pytest.fixture
def flat_prices():
    """Flat pricing: 800 PLN/MWh import, 0 export"""
    return PriceConfig(
        import_price_pln_mwh=800.0,
        export_price_pln_mwh=0.0,
    )


# =============================================================================
# Constraint Shape Tests
# =============================================================================

class TestConstraintShapes:
    """Test that constraint matrices have correct dimensions."""

    def test_difference_matrix_shape(self):
        n = 24
        A = _build_difference_matrix(n, dt_hours=1.0)
        assert A.shape == (n, n)

    def test_difference_matrix_first_row(self):
        n = 10
        A = _build_difference_matrix(n, dt_hours=1.0)
        # First row: SoC[0] / dt = SoC[0] (since no SoC[-1])
        assert A[0, 0] == 1.0
        assert np.sum(np.abs(A[0, 1:])) == 0.0

    def test_difference_matrix_later_rows(self):
        n = 10
        dt = 0.25  # 15-min
        A = _build_difference_matrix(n, dt)
        # Row 3: (SoC[3] - SoC[2]) / dt
        assert A[3, 3] == pytest.approx(1.0 / dt)
        assert A[3, 2] == pytest.approx(-1.0 / dt)

    def test_power_constraints_shape(self, simple_battery, synthetic_day_hourly):
        pv, load = synthetic_day_hourly
        n = len(pv)
        A, b, n_rows = _build_power_constraints(
            n, 1.0, 0.5, simple_battery, pv, load, DispatchMode.PV_SURPLUS
        )
        assert n_rows == 2 * n
        assert A.shape == (2 * n, 2 * n)  # 2n rows, 2n cols (SoC + t_aux)
        assert b.shape == (2 * n,)

    def test_cost_constraints_shape(self, simple_battery, synthetic_day_hourly, flat_prices):
        pv, load = synthetic_day_hourly
        n = len(pv)
        buy, sell = resolve_price_arrays(flat_prices, n)
        A, b, n_rows = _build_cost_constraints(
            n, 1.0, 0.5, simple_battery, buy, sell, pv, load
        )
        assert n_rows == 4 * n  # 4 pieces per timestep
        assert A.shape == (4 * n, 2 * n)
        assert b.shape == (4 * n,)

    def test_mode_constraints_return_empty(self, simple_battery, synthetic_day_hourly):
        """Mode constraints are now handled via power bounds, so return 0 rows."""
        pv, load = synthetic_day_hourly
        n = len(pv)
        A, b, n_rows = _build_mode_constraints(
            n, 1.0, 0.5, simple_battery, pv, load, DispatchMode.PV_SURPLUS
        )
        assert n_rows == 0  # Zero-export handled by cost function

        A, b, n_rows = _build_mode_constraints(
            n, 1.0, 0.5, simple_battery, pv, load, DispatchMode.PEAK_SHAVING, peak_limit_kw=80.0
        )
        assert n_rows == 0  # Peak handled by power bounds

        A, b, n_rows = _build_mode_constraints(
            n, 1.0, 0.5, simple_battery, pv, load, DispatchMode.STACKED, peak_limit_kw=80.0
        )
        assert n_rows == 0  # Both handled elsewhere


# =============================================================================
# SoC Bounds Tests
# =============================================================================

class TestSoCBounds:
    """SoC must stay within [soc_min, soc_max]."""

    def test_soc_within_bounds_pv_surplus(self, simple_battery, synthetic_day_hourly, flat_prices):
        pv, load = synthetic_day_hourly
        result = dispatch_lp(pv, load, simple_battery, 1.0, flat_prices,
                             mode=DispatchMode.PV_SURPLUS)
        assert result is not None
        soc_arr = np.array(result.hourly_soc_pct) / 100.0  # Convert to fraction
        assert np.all(soc_arr >= simple_battery.soc_min - 1e-6)
        assert np.all(soc_arr <= simple_battery.soc_max + 1e-6)

    def test_soc_within_bounds_peak_shaving(self, simple_battery, synthetic_day_hourly, flat_prices):
        pv, load = synthetic_day_hourly
        result = dispatch_lp(pv, load, simple_battery, 1.0, flat_prices,
                             mode=DispatchMode.PEAK_SHAVING, peak_limit_kw=80.0)
        assert result is not None
        soc_arr = np.array(result.hourly_soc_pct) / 100.0
        assert np.all(soc_arr >= simple_battery.soc_min - 1e-6)
        assert np.all(soc_arr <= simple_battery.soc_max + 1e-6)


# =============================================================================
# C-rate Limit Tests
# =============================================================================

class TestCrateLimits:
    """Battery power must not exceed power_kw."""

    def test_charge_within_power_limit(self, simple_battery, synthetic_day_hourly, flat_prices):
        pv, load = synthetic_day_hourly
        result = dispatch_lp(pv, load, simple_battery, 1.0, flat_prices,
                             mode=DispatchMode.PV_SURPLUS)
        assert result is not None
        charge = np.array(result.hourly_charge_kw)
        # Allow small numerical tolerance
        assert np.all(charge <= simple_battery.power_kw + 1.0)

    def test_discharge_within_power_limit(self, simple_battery, synthetic_day_hourly, flat_prices):
        pv, load = synthetic_day_hourly
        result = dispatch_lp(pv, load, simple_battery, 1.0, flat_prices,
                             mode=DispatchMode.PV_SURPLUS)
        assert result is not None
        discharge = np.array(result.hourly_discharge_kw)
        assert np.all(discharge <= simple_battery.power_kw + 1.0)


# =============================================================================
# Zero-Export Tests (PV_SURPLUS)
# =============================================================================

class TestZeroExport:
    """In PV_SURPLUS mode, grid export should be zero or very small."""

    def test_no_grid_export_pv_surplus(self, simple_battery, synthetic_day_hourly, flat_prices):
        pv, load = synthetic_day_hourly
        result = dispatch_lp(pv, load, simple_battery, 1.0, flat_prices,
                             mode=DispatchMode.PV_SURPLUS)
        assert result is not None
        # Grid export should be zero (or negligible due to numerical precision)
        assert result.total_grid_export_kwh < 1.0  # < 1 kWh tolerance


# =============================================================================
# Peak Shaving Tests
# =============================================================================

class TestPeakShaving:
    """In PEAK_SHAVING mode, grid import should respect peak_limit."""

    def test_peak_limit_respected(self, simple_battery, synthetic_day_hourly, flat_prices):
        pv, load = synthetic_day_hourly
        peak_limit = 80.0
        result = dispatch_lp(pv, load, simple_battery, 1.0, flat_prices,
                             mode=DispatchMode.PEAK_SHAVING, peak_limit_kw=peak_limit)
        assert result is not None
        grid_import = np.array(result.hourly_grid_import_kw)
        # Allow small tolerance for LP numerical precision
        assert np.all(grid_import <= peak_limit + 2.0)

    def test_peak_reduction(self, simple_battery, synthetic_day_hourly, flat_prices):
        pv, load = synthetic_day_hourly
        peak_limit = 80.0
        result = dispatch_lp(pv, load, simple_battery, 1.0, flat_prices,
                             mode=DispatchMode.PEAK_SHAVING, peak_limit_kw=peak_limit)
        assert result is not None
        assert result.new_peak_kw <= result.original_peak_kw


# =============================================================================
# Rolling Horizon Tests
# =============================================================================

class TestRollingHorizon:
    """Rolling horizon should produce continuous SoC across windows."""

    def test_rolling_horizon_continuity(self, simple_battery, flat_prices):
        """SoC should be continuous across rolling horizon windows."""
        # 48h profile (2 days) to force at least 2 windows
        n = 48
        pv = np.tile([0, 0, 0, 0, 0, 10, 30, 60, 90, 110, 120, 130,
                      130, 120, 100, 70, 40, 15, 0, 0, 0, 0, 0, 0], 2).astype(float)
        load = np.tile([20, 15, 12, 10, 10, 15, 40, 60, 50, 45, 50, 55,
                        60, 50, 45, 50, 70, 100, 120, 100, 80, 50, 30, 20], 2).astype(float)

        buy, sell = resolve_price_arrays(flat_prices, n)

        # Use small window to force multiple solves
        config = LPSolverParams(forecast_hours=12, keep_hours=8)
        soc = lp_dispatch_rolling(
            pv, load, simple_battery, 1.0, buy, sell,
            DispatchMode.PV_SURPLUS, lp_config=config
        )
        assert soc is not None
        assert len(soc) == n
        # SoC should be within bounds
        assert np.all(soc >= simple_battery.soc_min - 1e-6)
        assert np.all(soc <= simple_battery.soc_max + 1e-6)

    def test_rolling_covers_full_horizon(self, simple_battery, flat_prices):
        """Rolling horizon should produce results for all timesteps."""
        n = 72  # 3 days
        pv = np.tile([0, 0, 0, 0, 0, 10, 30, 60, 90, 110, 120, 130,
                      130, 120, 100, 70, 40, 15, 0, 0, 0, 0, 0, 0], 3).astype(float)
        load = np.tile([20, 15, 12, 10, 10, 15, 40, 60, 50, 45, 50, 55,
                        60, 50, 45, 50, 70, 100, 120, 100, 80, 50, 30, 20], 3).astype(float)

        result = dispatch_lp(pv, load, simple_battery, 1.0, flat_prices,
                             mode=DispatchMode.PV_SURPLUS)
        assert result is not None
        assert result.n_timesteps == n
        assert len(result.hourly_charge_kw) == n
        assert len(result.hourly_soc_pct) == n


# =============================================================================
# LP vs Greedy Comparison
# =============================================================================

class TestLPvsGreedy:
    """LP should produce savings >= greedy (it's optimal)."""

    def test_lp_savings_ge_greedy_pv_surplus(self, simple_battery, synthetic_day_hourly, flat_prices):
        from dispatch_engine import dispatch_pv_surplus

        pv, load = synthetic_day_hourly
        greedy_result = dispatch_pv_surplus(pv, load, simple_battery, 1.0, flat_prices)
        lp_result = dispatch_lp(pv, load, simple_battery, 1.0, flat_prices,
                                mode=DispatchMode.PV_SURPLUS)

        assert lp_result is not None
        # LP should have equal or lower project cost
        assert lp_result.project_cost_pln <= greedy_result.project_cost_pln + 1.0  # 1 PLN tolerance

    def test_lp_savings_ge_greedy_peak_shaving(self, simple_battery, synthetic_day_hourly, flat_prices):
        from dispatch_engine import dispatch_peak_shaving

        pv, load = synthetic_day_hourly
        peak_limit = 80.0
        greedy_result = dispatch_peak_shaving(pv, load, simple_battery, 1.0,
                                              peak_limit, flat_prices)
        lp_result = dispatch_lp(pv, load, simple_battery, 1.0, flat_prices,
                                mode=DispatchMode.PEAK_SHAVING, peak_limit_kw=peak_limit)

        assert lp_result is not None
        # LP should produce equal or better peak reduction
        assert lp_result.new_peak_kw <= greedy_result.new_peak_kw + 1.0


# =============================================================================
# DispatchResult Format Tests
# =============================================================================

class TestDispatchResultFormat:
    """LP result should have the same structure as greedy result."""

    def test_result_has_required_fields(self, simple_battery, synthetic_day_hourly, flat_prices):
        pv, load = synthetic_day_hourly
        result = dispatch_lp(pv, load, simple_battery, 1.0, flat_prices,
                             mode=DispatchMode.PV_SURPLUS)
        assert result is not None

        # Check required fields
        assert result.mode == DispatchMode.PV_SURPLUS
        assert result.battery_power_kw == simple_battery.power_kw
        assert result.battery_energy_kwh == simple_battery.energy_kwh
        assert result.interval_minutes == 60
        assert result.n_timesteps == 24
        assert result.total_pv_kwh > 0
        assert result.total_load_kwh > 0
        assert result.degradation is not None
        assert result.savings_breakdown is not None
        assert result.energy_flows is not None

    def test_result_has_hourly_arrays(self, simple_battery, synthetic_day_hourly, flat_prices):
        pv, load = synthetic_day_hourly
        result = dispatch_lp(pv, load, simple_battery, 1.0, flat_prices,
                             mode=DispatchMode.PV_SURPLUS)
        assert result is not None
        assert result.hourly_charge_kw is not None
        assert result.hourly_discharge_kw is not None
        assert result.hourly_soc_pct is not None
        assert result.hourly_grid_import_kw is not None
        assert result.hourly_grid_export_kw is not None
        assert len(result.hourly_charge_kw) == 24

    def test_result_info_has_solver_tag(self, simple_battery, synthetic_day_hourly, flat_prices):
        pv, load = synthetic_day_hourly
        result = dispatch_lp(pv, load, simple_battery, 1.0, flat_prices,
                             mode=DispatchMode.PV_SURPLUS)
        assert result is not None
        assert result.info.get("solver") == "lp"

    def test_energy_balance(self, simple_battery, synthetic_day_hourly, flat_prices):
        """Energy balance check: supply side should roughly match demand side."""
        pv, load = synthetic_day_hourly
        result = dispatch_lp(pv, load, simple_battery, 1.0, flat_prices,
                             mode=DispatchMode.PV_SURPLUS)
        assert result is not None

        # Energy balance:
        # PV + import = load + export + curtailment + battery_losses + delta_SOC
        supply = result.total_pv_kwh + result.total_grid_import_kwh
        demand = (result.total_load_kwh + result.total_grid_export_kwh
                  + result.total_curtailment_kwh)
        # Difference = battery losses + SOC change (can be significant)
        battery_throughput = result.total_charge_kwh + result.total_discharge_kwh
        max_losses = battery_throughput * 0.15  # Max 15% throughput loss
        soc_change = simple_battery.energy_kwh  # Max possible SOC change
        tolerance = max_losses + soc_change
        assert abs(supply - demand) < tolerance


# =============================================================================
# 15-min Resolution Tests
# =============================================================================

class TestQuarterHourly:
    """Tests with 15-min resolution."""

    def test_15min_pv_surplus(self, simple_battery, synthetic_day_15min, flat_prices):
        pv, load = synthetic_day_15min
        result = dispatch_lp(pv, load, simple_battery, 0.25, flat_prices,
                             mode=DispatchMode.PV_SURPLUS)
        assert result is not None
        assert result.n_timesteps == 96
        assert result.interval_minutes == 15

    def test_15min_soc_bounds(self, simple_battery, synthetic_day_15min, flat_prices):
        pv, load = synthetic_day_15min
        result = dispatch_lp(pv, load, simple_battery, 0.25, flat_prices,
                             mode=DispatchMode.PV_SURPLUS)
        assert result is not None
        soc = np.array(result.hourly_soc_pct) / 100.0
        assert np.all(soc >= simple_battery.soc_min - 1e-6)
        assert np.all(soc <= simple_battery.soc_max + 1e-6)


# =============================================================================
# Edge Cases
# =============================================================================

class TestEdgeCases:
    """Edge case handling."""

    def test_no_pv(self, simple_battery, flat_prices):
        """Load-only scenario: no PV generation, with variable load."""
        n = 24
        pv = np.zeros(n)
        # Variable load with peaks - battery can charge during low load
        load = np.array([30, 25, 20, 15, 15, 20, 40, 60, 80, 100, 90, 85,
                         80, 70, 65, 75, 95, 120, 110, 90, 70, 50, 35, 30], dtype=float)
        result = dispatch_lp(pv, load, simple_battery, 1.0, flat_prices,
                             mode=DispatchMode.PEAK_SHAVING, peak_limit_kw=80.0)
        assert result is not None
        assert result.total_pv_kwh == 0.0

    def test_no_load(self, simple_battery, flat_prices):
        """No load scenario: all PV is surplus."""
        n = 24
        pv = np.array([0, 0, 0, 0, 0, 10, 30, 60, 90, 110, 120, 130,
                       130, 120, 100, 70, 40, 15, 0, 0, 0, 0, 0, 0], dtype=float)
        load = np.zeros(n)
        result = dispatch_lp(pv, load, simple_battery, 1.0, flat_prices,
                             mode=DispatchMode.PV_SURPLUS)
        assert result is not None
        assert result.total_load_kwh == 0.0

    def test_very_small_battery(self, flat_prices, synthetic_day_hourly):
        """Very small battery relative to load."""
        pv, load = synthetic_day_hourly
        tiny_batt = BatteryParams.from_roundtrip(
            power_kw=1, energy_kwh=2, roundtrip_eff=0.90
        )
        result = dispatch_lp(pv, load, tiny_batt, 1.0, flat_prices,
                             mode=DispatchMode.PV_SURPLUS)
        assert result is not None


# =============================================================================
# Price Arrays Tests
# =============================================================================

class TestPriceResolution:
    """Test price array resolution."""

    def test_flat_prices(self, flat_prices):
        buy, sell = resolve_price_arrays(flat_prices, 24)
        assert len(buy) == 24
        assert len(sell) == 24
        assert np.all(buy == 0.8)  # 800 PLN/MWh = 0.8 PLN/kWh
        assert np.all(sell >= 1e-6)  # Minimum floor

    def test_none_prices_default(self):
        buy, sell = resolve_price_arrays(None, 24)
        assert len(buy) == 24
        assert len(sell) == 24


# =============================================================================
# Performance Tests
# =============================================================================

class TestPerformance:
    """Performance benchmarks."""

    def test_full_year_hourly(self, simple_battery, flat_prices):
        """Full year (8760h) should complete in reasonable time."""
        n = 8760
        # Repeat daily pattern
        pv_day = np.array([0, 0, 0, 0, 0, 10, 30, 60, 90, 110, 120, 130,
                           130, 120, 100, 70, 40, 15, 0, 0, 0, 0, 0, 0], dtype=float)
        load_day = np.array([20, 15, 12, 10, 10, 15, 40, 60, 50, 45, 50, 55,
                             60, 50, 45, 50, 70, 100, 120, 100, 80, 50, 30, 20], dtype=float)
        pv = np.tile(pv_day, 365)
        load = np.tile(load_day, 365)

        result = dispatch_lp(pv, load, simple_battery, 1.0, flat_prices,
                             mode=DispatchMode.PV_SURPLUS)
        assert result is not None
        assert result.n_timesteps == 8760
        # LP should find meaningful savings
        assert result.annual_savings_pln > 0

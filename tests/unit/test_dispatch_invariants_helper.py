"""
Unit tests for dispatch_invariants_helper (v2.2.0 PR3).

Tests verify:
- SOC bounds checking
- Power limits checking
- No-simultaneous charge/discharge checking
- Energy balance checking
- STRICT_INVARIANTS mode
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

from dispatch_invariants_helper import (
    check_soc_bounds,
    check_power_limits,
    check_no_simultaneous,
    check_energy_balance,
    check_dispatch_invariants,
    is_strict_mode,
    DispatchInvariantViolationError,
    InvariantCheckResult,
)


class TestCheckSocBounds:
    """Tests for SOC bounds checking."""

    def test_valid_soc_no_violations(self):
        """Verify valid SOC has no violations."""
        soc = np.array([20.0, 25.0, 30.0, 25.0, 20.0])
        violations = check_soc_bounds(soc, energy_kwh=40.0)
        assert len(violations) == 0

    def test_soc_below_zero(self):
        """Verify SOC below zero is detected."""
        soc = np.array([20.0, 10.0, -5.0, 0.0])
        violations = check_soc_bounds(soc, energy_kwh=40.0)
        assert len(violations) == 1
        assert violations[0].invariant == "soc_min"
        assert violations[0].step == 2

    def test_soc_above_capacity(self):
        """Verify SOC above capacity is detected."""
        soc = np.array([20.0, 30.0, 45.0, 35.0])
        violations = check_soc_bounds(soc, energy_kwh=40.0)
        assert len(violations) == 1
        assert violations[0].invariant == "soc_max"
        assert violations[0].step == 2

    def test_soc_at_bounds(self):
        """Verify SOC at bounds is OK."""
        soc = np.array([0.0, 40.0, 20.0])
        violations = check_soc_bounds(soc, energy_kwh=40.0)
        assert len(violations) == 0

    def test_soc_tolerance(self):
        """Verify tolerance is applied."""
        soc = np.array([0.0, -1e-7, 40.0 + 1e-7])  # Within tolerance
        violations = check_soc_bounds(soc, energy_kwh=40.0, tolerance=1e-6)
        assert len(violations) == 0


class TestCheckPowerLimits:
    """Tests for power limits checking."""

    def test_valid_power_no_violations(self):
        """Verify valid power has no violations."""
        charge = np.array([10.0, 15.0, 20.0, 10.0])
        discharge = np.array([5.0, 10.0, 15.0, 20.0])
        violations = check_power_limits(charge, discharge, power_kw=20.0)
        assert len(violations) == 0

    def test_charge_exceeds_limit(self):
        """Verify charge exceeding limit is detected."""
        charge = np.array([10.0, 25.0, 15.0])
        discharge = np.array([5.0, 0.0, 5.0])
        violations = check_power_limits(charge, discharge, power_kw=20.0)
        assert len(violations) == 1
        assert violations[0].invariant == "power_charge"
        assert violations[0].step == 1

    def test_discharge_exceeds_limit(self):
        """Verify discharge exceeding limit is detected."""
        charge = np.array([10.0, 0.0, 15.0])
        discharge = np.array([5.0, 30.0, 5.0])
        violations = check_power_limits(charge, discharge, power_kw=20.0)
        assert len(violations) == 1
        assert violations[0].invariant == "power_discharge"
        assert violations[0].step == 1

    def test_power_at_limit(self):
        """Verify power at limit is OK."""
        charge = np.array([20.0, 0.0])
        discharge = np.array([0.0, 20.0])
        violations = check_power_limits(charge, discharge, power_kw=20.0)
        assert len(violations) == 0


class TestCheckNoSimultaneous:
    """Tests for no-simultaneous charge/discharge checking."""

    def test_no_simultaneous_violations(self):
        """Verify valid dispatch has no simultaneous violations."""
        charge = np.array([10.0, 0.0, 15.0, 0.0])
        discharge = np.array([0.0, 10.0, 0.0, 15.0])
        violations = check_no_simultaneous(charge, discharge)
        assert len(violations) == 0

    def test_simultaneous_detected(self):
        """Verify simultaneous charge/discharge is detected."""
        charge = np.array([10.0, 5.0, 15.0])
        discharge = np.array([0.0, 8.0, 0.0])
        violations = check_no_simultaneous(charge, discharge)
        assert len(violations) == 1
        assert violations[0].invariant == "simultaneous"
        assert violations[0].step == 1

    def test_zero_values_ok(self):
        """Verify zero values are OK (not simultaneous)."""
        charge = np.array([0.0, 0.0, 0.0])
        discharge = np.array([0.0, 0.0, 0.0])
        violations = check_no_simultaneous(charge, discharge)
        assert len(violations) == 0

    def test_tolerance_applied(self):
        """Verify tolerance is applied."""
        charge = np.array([10.0, 1e-8])
        discharge = np.array([0.0, 1e-8])
        violations = check_no_simultaneous(charge, discharge, tolerance=1e-6)
        assert len(violations) == 0


class TestCheckEnergyBalance:
    """Tests for energy balance checking."""

    def test_perfect_balance(self):
        """Verify perfect energy balance has no violations."""
        # SOC: 20 -> 30 -> 25 (charge 10 kWh, discharge 5 kWh at eta=1.0)
        soc = np.array([20.0, 30.0, 25.0])
        charge = np.array([10.0, 0.0])  # 10 kW * 1h = 10 kWh
        discharge = np.array([0.0, 5.0])  # 5 kW * 1h = 5 kWh

        violations = check_energy_balance(
            soc, charge, discharge,
            dt_hours=1.0, eta_charge=1.0, eta_discharge=1.0
        )
        assert len(violations) == 0

    def test_balance_with_efficiency(self):
        """Verify balance with efficiency losses."""
        # 10 kW charge at 95% efficiency = 9.5 kWh added
        soc = np.array([20.0, 29.5])
        charge = np.array([10.0])
        discharge = np.array([0.0])

        violations = check_energy_balance(
            soc, charge, discharge,
            dt_hours=1.0, eta_charge=0.95, eta_discharge=0.95
        )
        assert len(violations) == 0

    def test_imbalance_detected(self):
        """Verify imbalance is detected."""
        # SOC jumps from 20 to 40 with only 5 kW charge (should be ~5 kWh, not 20)
        soc = np.array([20.0, 40.0])
        charge = np.array([5.0])
        discharge = np.array([0.0])

        violations = check_energy_balance(
            soc, charge, discharge,
            dt_hours=1.0, eta_charge=1.0, eta_discharge=1.0
        )
        # Should detect imbalance > tolerance
        assert len(violations) == 1
        assert violations[0].invariant == "energy_balance"


class TestCheckDispatchInvariants:
    """Tests for combined invariant checking."""

    def test_all_ok(self):
        """Verify all-OK dispatch passes (errors only, not warnings)."""
        # SOC within bounds, power within limits, no simultaneous
        soc = np.array([20.0, 25.0, 20.0, 25.0])
        charge = np.array([10.0, 0.0, 10.0])
        discharge = np.array([0.0, 10.0, 0.0])

        result = check_dispatch_invariants(
            soc, charge, discharge,
            energy_kwh=40.0, power_kw=20.0
        )

        # all_ok only considers errors, not warnings (energy_balance is warning)
        assert result.all_ok is True
        assert result.soc_min_violations == 0
        assert result.soc_max_violations == 0
        assert result.power_charge_violations == 0
        assert result.power_discharge_violations == 0
        assert result.simultaneous_violations == 0

    def test_multiple_violations(self):
        """Verify multiple violations are collected."""
        # SOC violation + simultaneous violation
        soc = np.array([-5.0, 10.0])  # Below zero
        charge = np.array([5.0])
        discharge = np.array([5.0])  # Simultaneous

        result = check_dispatch_invariants(
            soc, charge, discharge,
            energy_kwh=40.0, power_kw=20.0
        )

        assert result.all_ok is False
        assert result.soc_min_violations >= 1
        assert result.simultaneous_violations >= 1

    def test_to_dict_conversion(self):
        """Verify to_dict() works correctly."""
        soc = np.array([20.0, 25.0])
        charge = np.array([10.0])
        discharge = np.array([0.0])

        result = check_dispatch_invariants(
            soc, charge, discharge,
            energy_kwh=40.0, power_kw=20.0
        )

        d = result.to_dict()
        assert "all_ok" in d
        assert "soc_bounds_ok" in d
        assert "power_limits_ok" in d
        assert "no_simultaneous_ok" in d
        assert "violations_count" in d


class TestStrictMode:
    """Tests for STRICT_INVARIANTS mode."""

    def test_is_strict_mode_default(self):
        """Verify default mode is not strict."""
        # Clear env var if set
        os.environ.pop("STRICT_INVARIANTS", None)
        assert is_strict_mode() is False

    def test_is_strict_mode_true(self):
        """Verify strict mode when env var is true."""
        os.environ["STRICT_INVARIANTS"] = "true"
        try:
            assert is_strict_mode() is True
        finally:
            os.environ.pop("STRICT_INVARIANTS", None)

    def test_strict_mode_raises_on_violation(self):
        """Verify strict mode raises exception on violation."""
        os.environ["STRICT_INVARIANTS"] = "true"
        try:
            soc = np.array([-5.0, 10.0])  # Violation
            charge = np.array([10.0])
            discharge = np.array([0.0])

            with pytest.raises(DispatchInvariantViolationError) as exc_info:
                check_dispatch_invariants(
                    soc, charge, discharge,
                    energy_kwh=40.0, power_kw=20.0
                )

            assert exc_info.value.result.all_ok is False
        finally:
            os.environ.pop("STRICT_INVARIANTS", None)

    def test_non_strict_mode_returns_result(self):
        """Verify non-strict mode returns result even with violations."""
        os.environ.pop("STRICT_INVARIANTS", None)

        soc = np.array([-5.0, 10.0])  # Violation
        charge = np.array([10.0])
        discharge = np.array([0.0])

        result = check_dispatch_invariants(
            soc, charge, discharge,
            energy_kwh=40.0, power_kw=20.0
        )

        assert result.all_ok is False
        assert len(result.violations) > 0


class TestInvariantViolationDetails:
    """Tests for violation detail accuracy."""

    def test_violation_step_correct(self):
        """Verify violation step is correctly identified."""
        soc = np.array([20.0, 25.0, -5.0, 30.0])  # Violation at step 2
        violations = check_soc_bounds(soc, energy_kwh=40.0)
        assert len(violations) == 1
        assert violations[0].step == 2

    def test_violation_value_correct(self):
        """Verify violation value is correctly reported."""
        soc = np.array([20.0, -7.5])  # -7.5 kWh
        violations = check_soc_bounds(soc, energy_kwh=40.0)
        assert len(violations) == 1
        assert violations[0].actual_value == pytest.approx(-7.5)

    def test_multiple_violations_all_captured(self):
        """Verify all violations are captured."""
        soc = np.array([-5.0, -10.0, -3.0])  # 3 violations
        violations = check_soc_bounds(soc, energy_kwh=40.0)
        assert len(violations) == 3

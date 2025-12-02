"""
Unit tests for IRR solver

Tests cover:
1. Classical investment cash flows - should match numpy_financial.irr
2. No root cases (all positive or all negative cash flows)
3. High inflation scenarios
4. Edge cases
"""
import pytest
from app import calculate_irr_robust, IRRResult, _npv_at_rate

# Try to import numpy_financial for comparison tests
try:
    import numpy_financial as npf
    HAS_NPF = True
except ImportError:
    HAS_NPF = False
    print("Warning: numpy_financial not installed, skipping comparison tests")


class TestIRRSolver:
    """Test cases for the robust IRR solver"""

    def test_classical_investment(self):
        """
        Test 1: Classical investment case
        Cash flows: -100, 30, 30, 30, 30, 130 (investment + 5 years)
        Expected IRR should be around 27.44%
        """
        cash_flows = [-100, 30, 30, 30, 30, 130]
        result = calculate_irr_robust(cash_flows)

        assert result.status == "converged"
        assert result.value is not None
        # IRR should be approximately 27.44%
        assert abs(result.value - 0.2744) < 0.01

        if HAS_NPF:
            npf_irr = npf.irr(cash_flows)
            assert abs(result.value - npf_irr) < 0.001, \
                f"IRR mismatch: our={result.value:.6f}, numpy={npf_irr:.6f}"

    def test_simple_payback(self):
        """
        Test 2: Simple payback case
        Cash flows: -1000, 200, 200, 200, 200, 200 (5 years)
        Expected IRR should be around 0%
        """
        cash_flows = [-1000, 200, 200, 200, 200, 200]
        result = calculate_irr_robust(cash_flows)

        assert result.status == "converged"
        assert result.value is not None
        # This should result in IRR close to 0%
        assert result.value < 0.01

    def test_no_root_all_positive(self):
        """
        Test 3: No root case - all positive cash flows
        Should return no_root status
        """
        cash_flows = [100, 200, 300, 400]
        result = calculate_irr_robust(cash_flows)

        assert result.status == "no_root"
        assert result.value is None
        assert result.message is not None

    def test_no_root_all_negative(self):
        """
        Test 4: No root case - all negative cash flows
        Should return no_root status
        """
        cash_flows = [-100, -200, -300, -400]
        result = calculate_irr_robust(cash_flows)

        assert result.status == "no_root"
        assert result.value is None

    def test_pv_installation_typical(self):
        """
        Test 5: Typical PV installation scenario
        Cash flows: -3,500,000 PLN initial, ~700,000 PLN/year for 25 years
        Expected IRR around 18-20%
        """
        # 1 MWp installation at 3500 PLN/kWp
        initial_investment = -3500000  # -3.5 mln PLN
        annual_cash_flow = 700000  # 700k PLN (savings - OPEX)

        # Generate 25-year cash flows
        cash_flows = [initial_investment]
        for year in range(1, 26):
            # Apply 0.5% degradation
            degradation = (1 - 0.005) ** year
            cash_flows.append(annual_cash_flow * degradation)

        result = calculate_irr_robust(cash_flows)

        assert result.status == "converged"
        assert result.value is not None
        # IRR should be positive and reasonable for PV investment
        assert result.value > 0.10  # > 10%
        assert result.value < 0.30  # < 30%

    def test_high_inflation_scenario(self):
        """
        Test 6: High inflation scenario (nominal cash flows)
        Cash flows increase with 5% inflation
        """
        initial_investment = -1000000
        base_annual = 150000
        inflation_rate = 0.05

        cash_flows = [initial_investment]
        for year in range(1, 26):
            inflation_factor = (1 + inflation_rate) ** year
            cash_flows.append(base_annual * inflation_factor)

        result = calculate_irr_robust(cash_flows, irr_mode="nominal")

        assert result.status == "converged"
        assert result.value is not None
        assert result.mode == "nominal"
        # With inflation, nominal IRR should be higher than real
        assert result.value > 0.15

    def test_irr_mode_parameter(self):
        """
        Test 7: IRR mode parameter is correctly passed through
        """
        cash_flows = [-100, 30, 30, 30, 30, 30]

        result_real = calculate_irr_robust(cash_flows, irr_mode="real")
        result_nominal = calculate_irr_robust(cash_flows, irr_mode="nominal")

        assert result_real.mode == "real"
        assert result_nominal.mode == "nominal"
        # The IRR value should be the same (mode is just for labeling)
        assert abs(result_real.value - result_nominal.value) < 0.0001

    def test_convergence_iterations(self):
        """
        Test 8: Check that iterations count is reasonable
        """
        cash_flows = [-100, 30, 30, 30, 30, 30]
        result = calculate_irr_robust(cash_flows)

        assert result.status == "converged"
        assert result.iterations > 0
        assert result.iterations < 50  # Should converge quickly

    def test_edge_case_two_cash_flows(self):
        """
        Test 9: Minimum valid case - 2 cash flows
        """
        cash_flows = [-100, 150]
        result = calculate_irr_robust(cash_flows)

        assert result.status == "converged"
        assert result.value is not None
        # IRR should be 50%
        assert abs(result.value - 0.50) < 0.01

    def test_edge_case_one_cash_flow(self):
        """
        Test 10: Invalid case - only 1 cash flow
        """
        cash_flows = [-100]
        result = calculate_irr_robust(cash_flows)

        assert result.status == "invalid_cashflows"
        assert result.value is None

    def test_npv_helper_function(self):
        """
        Test 11: NPV helper function
        """
        cash_flows = [-100, 50, 50, 50]
        rate = 0.10  # 10%

        npv = _npv_at_rate(cash_flows, rate)

        # Manual calculation: -100 + 50/1.1 + 50/1.21 + 50/1.331
        expected_npv = -100 + 50/1.1 + 50/1.21 + 50/1.331
        assert abs(npv - expected_npv) < 0.01

    def test_zero_initial_investment(self):
        """
        Test 12: Zero initial investment with future costs
        """
        cash_flows = [0, -100, 50, 50, 50, 50]
        result = calculate_irr_robust(cash_flows)

        # Should still find a valid IRR
        assert result.status == "converged"
        assert result.value is not None


class TestIRRComparison:
    """Comparison tests with numpy_financial (if available)"""

    @pytest.mark.skipif(not HAS_NPF, reason="numpy_financial not installed")
    def test_comparison_simple(self):
        """Compare with numpy_financial for simple case"""
        cash_flows = [-100, 30, 30, 30, 30, 30]

        our_result = calculate_irr_robust(cash_flows)
        npf_irr = npf.irr(cash_flows)

        assert abs(our_result.value - npf_irr) < 0.0001

    @pytest.mark.skipif(not HAS_NPF, reason="numpy_financial not installed")
    def test_comparison_pv_realistic(self):
        """Compare with numpy_financial for realistic PV case"""
        # 5 MWp installation
        initial = -17500000  # 5000 kWp * 3500 PLN/kWp
        annual = 3500000  # ~700 PLN/kWp savings

        cash_flows = [initial]
        for year in range(1, 26):
            degradation = (1 - 0.005) ** year
            cash_flows.append(annual * degradation)

        our_result = calculate_irr_robust(cash_flows)
        npf_irr = npf.irr(cash_flows)

        assert abs(our_result.value - npf_irr) < 0.001


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""
Unit tests for driver metrics helper (v4.5.0 PR3).

Tests:
- Self-consumption rate calculation
- LCOS calculation
- Resilience score calculation
- Combined metrics computation
"""

import sys
from pathlib import Path
import pytest

# Add services/bess-dispatch to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))


class TestSelfConsumptionRate:
    """Tests for self_consumption_rate calculation."""

    def test_basic_calculation(self):
        """Basic self-consumption rate calculation."""
        from driver_metrics_helper import compute_self_consumption_rate

        # 80 kWh consumed out of 100 kWh generated
        rate = compute_self_consumption_rate(
            self_consumption_kwh=80.0,
            total_pv_kwh=100.0
        )
        assert rate == 0.8

    def test_full_self_consumption(self):
        """100% self-consumption."""
        from driver_metrics_helper import compute_self_consumption_rate

        rate = compute_self_consumption_rate(
            self_consumption_kwh=100.0,
            total_pv_kwh=100.0
        )
        assert rate == 1.0

    def test_zero_pv_returns_zero(self):
        """Zero PV generation returns 0 rate."""
        from driver_metrics_helper import compute_self_consumption_rate

        rate = compute_self_consumption_rate(
            self_consumption_kwh=50.0,
            total_pv_kwh=0.0
        )
        assert rate == 0.0

    def test_clamped_to_one(self):
        """Rate is clamped to max 1.0."""
        from driver_metrics_helper import compute_self_consumption_rate

        # Edge case: consumption > generation (shouldn't happen but handle gracefully)
        rate = compute_self_consumption_rate(
            self_consumption_kwh=120.0,
            total_pv_kwh=100.0
        )
        assert rate == 1.0

    def test_from_dispatch_dict(self):
        """Compute from dispatch result dict."""
        from driver_metrics_helper import compute_self_consumption_rate_from_dispatch

        dispatch = {
            "self_consumption_kwh": 750.0,
            "total_pv_kwh": 1000.0
        }
        rate = compute_self_consumption_rate_from_dispatch(dispatch)
        assert rate == 0.75


class TestLCOSCalculation:
    """Tests for LCOS calculation."""

    def test_basic_lcos(self):
        """Basic LCOS calculation."""
        from driver_metrics_helper import compute_lcos_pln_per_mwh

        # CAPEX: 100k PLN, OPEX: 5k PLN/yr, 50 MWh/yr throughput
        lcos = compute_lcos_pln_per_mwh(
            capex_pln=100000.0,
            annual_opex_pln=5000.0,
            annual_throughput_mwh=50.0,
            discount_rate=0.08,
            lifetime_years=15
        )

        assert lcos is not None
        # LCOS should be positive and reasonable
        assert 200 < lcos < 1000  # PLN/MWh

    def test_zero_throughput_returns_none(self):
        """Zero throughput returns None."""
        from driver_metrics_helper import compute_lcos_pln_per_mwh

        lcos = compute_lcos_pln_per_mwh(
            capex_pln=100000.0,
            annual_opex_pln=5000.0,
            annual_throughput_mwh=0.0,
            discount_rate=0.08,
            lifetime_years=15
        )
        assert lcos is None

    def test_higher_capex_higher_lcos(self):
        """Higher CAPEX leads to higher LCOS."""
        from driver_metrics_helper import compute_lcos_pln_per_mwh

        lcos_low = compute_lcos_pln_per_mwh(
            capex_pln=50000.0,
            annual_opex_pln=5000.0,
            annual_throughput_mwh=50.0,
            discount_rate=0.08,
            lifetime_years=15
        )

        lcos_high = compute_lcos_pln_per_mwh(
            capex_pln=150000.0,
            annual_opex_pln=5000.0,
            annual_throughput_mwh=50.0,
            discount_rate=0.08,
            lifetime_years=15
        )

        assert lcos_high > lcos_low

    def test_higher_throughput_lower_lcos(self):
        """Higher throughput leads to lower LCOS."""
        from driver_metrics_helper import compute_lcos_pln_per_mwh

        lcos_low_throughput = compute_lcos_pln_per_mwh(
            capex_pln=100000.0,
            annual_opex_pln=5000.0,
            annual_throughput_mwh=25.0,
            discount_rate=0.08,
            lifetime_years=15
        )

        lcos_high_throughput = compute_lcos_pln_per_mwh(
            capex_pln=100000.0,
            annual_opex_pln=5000.0,
            annual_throughput_mwh=100.0,
            discount_rate=0.08,
            lifetime_years=15
        )

        assert lcos_high_throughput < lcos_low_throughput

    def test_from_sizing_result_kwh(self):
        """Compute from sizing result with kWh throughput."""
        from driver_metrics_helper import compute_lcos_from_sizing_result

        # 50000 kWh/yr = 50 MWh/yr
        lcos = compute_lcos_from_sizing_result(
            capex_pln=100000.0,
            annual_opex_pln=5000.0,
            total_discharge_kwh=50000.0,  # kWh
            discount_rate=0.08,
            lifetime_years=15
        )

        assert lcos is not None
        assert 200 < lcos < 1000

    def test_invalid_lifetime_returns_none(self):
        """Invalid lifetime returns None."""
        from driver_metrics_helper import compute_lcos_pln_per_mwh

        lcos = compute_lcos_pln_per_mwh(
            capex_pln=100000.0,
            annual_opex_pln=5000.0,
            annual_throughput_mwh=50.0,
            discount_rate=0.08,
            lifetime_years=0
        )
        assert lcos is None


class TestResilienceScore:
    """Tests for resilience score calculation."""

    def test_full_resilience(self):
        """All load served = score 1.0."""
        from driver_metrics_helper import compute_resilience_score

        score = compute_resilience_score(
            unserved_load_kwh=0.0,
            total_load_kwh=1000.0
        )
        assert score == 1.0

    def test_partial_resilience(self):
        """Some load unserved."""
        from driver_metrics_helper import compute_resilience_score

        # 100 kWh unserved out of 1000 kWh total
        score = compute_resilience_score(
            unserved_load_kwh=100.0,
            total_load_kwh=1000.0
        )
        assert score == 0.9

    def test_no_load_full_resilience(self):
        """No load to serve = full resilience."""
        from driver_metrics_helper import compute_resilience_score

        score = compute_resilience_score(
            unserved_load_kwh=0.0,
            total_load_kwh=0.0
        )
        assert score == 1.0

    def test_all_load_unserved(self):
        """All load unserved = score 0.0."""
        from driver_metrics_helper import compute_resilience_score

        score = compute_resilience_score(
            unserved_load_kwh=1000.0,
            total_load_kwh=1000.0
        )
        assert score == 0.0

    def test_clamped_to_zero(self):
        """Score clamped to 0 if unserved > total."""
        from driver_metrics_helper import compute_resilience_score

        score = compute_resilience_score(
            unserved_load_kwh=1500.0,
            total_load_kwh=1000.0
        )
        assert score == 0.0

    def test_from_dispatch_dict(self):
        """Compute from dispatch result dict."""
        from driver_metrics_helper import compute_resilience_score_from_dispatch

        dispatch = {"total_load_kwh": 1000.0}
        constraints = {"unserved_load_kwh": 50.0}

        score = compute_resilience_score_from_dispatch(dispatch, constraints)
        assert score == 0.95

    def test_from_dispatch_no_constraints(self):
        """No constraint summary = full resilience."""
        from driver_metrics_helper import compute_resilience_score_from_dispatch

        dispatch = {"total_load_kwh": 1000.0}

        score = compute_resilience_score_from_dispatch(dispatch, None)
        assert score == 1.0


class TestComputeAllDriverMetrics:
    """Tests for combined metrics computation."""

    def test_computes_all_metrics(self):
        """All metrics are computed."""
        from driver_metrics_helper import compute_all_driver_metrics

        dispatch = {
            "self_consumption_kwh": 800.0,
            "total_pv_kwh": 1000.0,
            "total_load_kwh": 2000.0,
            "total_discharge_kwh": 50000.0,  # 50 MWh/yr
        }
        constraints = {"unserved_load_kwh": 100.0}

        metrics = compute_all_driver_metrics(
            dispatch_result=dispatch,
            constraint_summary=constraints,
            capex_pln=100000.0,
            annual_opex_pln=5000.0,
            discount_rate=0.08,
            lifetime_years=15,
        )

        assert "self_consumption_rate" in metrics
        assert "lcos_pln_per_mwh" in metrics
        assert "resilience_score" in metrics

        assert metrics["self_consumption_rate"] == 0.8
        assert metrics["lcos_pln_per_mwh"] is not None
        assert metrics["resilience_score"] == 0.95

    def test_handles_missing_constraint_summary(self):
        """Works without constraint summary."""
        from driver_metrics_helper import compute_all_driver_metrics

        dispatch = {
            "self_consumption_kwh": 800.0,
            "total_pv_kwh": 1000.0,
            "total_load_kwh": 2000.0,
            "total_discharge_kwh": 50000.0,
        }

        metrics = compute_all_driver_metrics(
            dispatch_result=dispatch,
            constraint_summary=None,
            capex_pln=100000.0,
            annual_opex_pln=5000.0,
        )

        assert metrics["resilience_score"] == 1.0  # No unserved load

    def test_handles_zero_throughput(self):
        """LCOS is None when no throughput."""
        from driver_metrics_helper import compute_all_driver_metrics

        dispatch = {
            "self_consumption_kwh": 0.0,
            "total_pv_kwh": 0.0,
            "total_load_kwh": 1000.0,
            "total_discharge_kwh": 0.0,
        }

        metrics = compute_all_driver_metrics(
            dispatch_result=dispatch,
            capex_pln=100000.0,
            annual_opex_pln=5000.0,
        )

        assert metrics["lcos_pln_per_mwh"] is None

"""
Contract tests for cashflow_timeseries feature.

These tests verify the v0.5.0 PR2 cashflow timeseries feature:
1. cashflow_timeseries is absent by default
2. cashflow_timeseries is present when include_cashflow_timeseries=True
3. NPV consistency: sum of discounted_cashflow equals npv_pln
"""
import pytest
import requests


class TestCashflowTimeseriesPresence:
    """Test that cashflow_timeseries is correctly returned based on flag."""

    def test_cashflow_timeseries_absent_by_default(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """cashflow_timeseries should be null when flag not set."""
        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=minimal_sizing_request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        variants = data.get("variants", [])
        for v in variants:
            fs = v.get("finance_summary")
            if fs:
                assert fs.get("cashflow_timeseries") is None, (
                    f"Variant {v.get('variant')}: cashflow_timeseries should be null by default"
                )

    def test_cashflow_timeseries_present_when_requested(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """cashflow_timeseries should be present when include_cashflow_timeseries=True."""
        request = {
            **minimal_sizing_request,
            "finance_config": {
                "include_cashflow_timeseries": True,
            },
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        variants = data.get("variants", [])
        assert len(variants) > 0, "Should have at least one variant"

        for v in variants:
            fs = v.get("finance_summary")
            assert fs is not None, f"Variant {v.get('variant')} should have finance_summary"
            assert fs.get("cashflow_timeseries") is not None, (
                f"Variant {v.get('variant')}: cashflow_timeseries should be present"
            )
            assert isinstance(fs["cashflow_timeseries"], list), (
                f"Variant {v.get('variant')}: cashflow_timeseries should be a list"
            )


class TestCashflowTimeseriesStructure:
    """Test cashflow_timeseries structure."""

    def test_cashflow_year_has_required_fields(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """Each CashflowYear should have all required fields."""
        request = {
            **minimal_sizing_request,
            "finance_config": {
                "include_cashflow_timeseries": True,
            },
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        variants = data.get("variants", [])
        required_fields = [
            "year",
            "savings_pln",
            "opex_pln",
            "net_cashflow_pln",
            "cumulative_cashflow_pln",
            "discounted_cashflow_pln",
        ]

        for v in variants:
            fs = v.get("finance_summary", {})
            cashflow_ts = fs.get("cashflow_timeseries", [])

            for cf_year in cashflow_ts:
                for field in required_fields:
                    assert field in cf_year, (
                        f"CashflowYear for variant {v.get('variant')} "
                        f"should have {field}"
                    )

    def test_cashflow_starts_at_year_zero(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """Cashflow timeseries should start at year 0 (investment)."""
        request = {
            **minimal_sizing_request,
            "finance_config": {
                "include_cashflow_timeseries": True,
            },
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        variants = data.get("variants", [])
        for v in variants:
            fs = v.get("finance_summary", {})
            cashflow_ts = fs.get("cashflow_timeseries", [])

            assert len(cashflow_ts) > 0, f"Variant {v.get('variant')} should have cashflow data"
            assert cashflow_ts[0]["year"] == 0, (
                f"Variant {v.get('variant')}: First year should be 0 (investment)"
            )

    def test_year_zero_is_negative_capex(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """Year 0 net_cashflow should be negative CAPEX."""
        request = {
            **minimal_sizing_request,
            "finance_config": {
                "include_cashflow_timeseries": True,
            },
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        variants = data.get("variants", [])
        for v in variants:
            fs = v.get("finance_summary", {})
            cashflow_ts = fs.get("cashflow_timeseries", [])
            capex = fs.get("capex_pln", 0)

            year_0 = cashflow_ts[0]
            assert abs(year_0["net_cashflow_pln"] + capex) < 1.0, (
                f"Variant {v.get('variant')}: Year 0 net_cashflow should be -CAPEX "
                f"(got {year_0['net_cashflow_pln']}, expected -{capex})"
            )
            assert year_0["savings_pln"] == 0, (
                f"Variant {v.get('variant')}: Year 0 savings should be 0"
            )
            assert year_0["opex_pln"] == 0, (
                f"Variant {v.get('variant')}: Year 0 opex should be 0"
            )


class TestCashflowNPVConsistency:
    """Test NPV consistency with cashflow timeseries."""

    def test_npv_equals_sum_of_discounted_cashflows(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """
        NPV in finance_summary should equal sum of discounted_cashflow_pln.

        This is the key contract invariant that ensures NPV calculation consistency.
        """
        request = {
            **minimal_sizing_request,
            "finance_config": {
                "include_cashflow_timeseries": True,
            },
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        variants = data.get("variants", [])
        for v in variants:
            fs = v.get("finance_summary", {})
            npv_pln = fs.get("npv_pln", 0)
            cashflow_ts = fs.get("cashflow_timeseries", [])

            # Sum all discounted cashflows
            sum_discounted = sum(cf["discounted_cashflow_pln"] for cf in cashflow_ts)

            # Allow 1% tolerance for floating point
            tolerance = max(abs(npv_pln) * 0.01, 1.0)
            diff = abs(npv_pln - sum_discounted)

            assert diff < tolerance, (
                f"Variant {v.get('variant')}: NPV ({npv_pln:.2f}) should equal "
                f"sum of discounted cashflows ({sum_discounted:.2f}). Diff: {diff:.2f}"
            )

    def test_cumulative_cashflow_is_running_total(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """Cumulative cashflow should be running total of net_cashflow."""
        request = {
            **minimal_sizing_request,
            "finance_config": {
                "include_cashflow_timeseries": True,
            },
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        variants = data.get("variants", [])
        for v in variants:
            fs = v.get("finance_summary", {})
            cashflow_ts = fs.get("cashflow_timeseries", [])

            running_total = 0.0
            for cf_year in cashflow_ts:
                running_total += cf_year["net_cashflow_pln"]
                diff = abs(cf_year["cumulative_cashflow_pln"] - running_total)
                assert diff < 1.0, (
                    f"Variant {v.get('variant')}, Year {cf_year['year']}: "
                    f"cumulative_cashflow ({cf_year['cumulative_cashflow_pln']:.2f}) "
                    f"should equal running total ({running_total:.2f})"
                )


class TestCashflowHorizonConsistency:
    """Test cashflow horizon matches finance_config."""

    def test_cashflow_length_matches_horizon(
        self,
        wait_for_services,
        bess_dispatch_url,
        minimal_sizing_request,
    ):
        """Cashflow timeseries length should be horizon_years + 1 (includes year 0)."""
        horizon = 10
        request = {
            **minimal_sizing_request,
            "finance_config": {
                "horizon_years": horizon,
                "include_cashflow_timeseries": True,
            },
        }

        response = requests.post(
            f"{bess_dispatch_url}/sizing",
            json=request,
            timeout=120,
        )

        assert response.status_code == 200
        data = response.json()

        variants = data.get("variants", [])
        for v in variants:
            fs = v.get("finance_summary", {})
            cashflow_ts = fs.get("cashflow_timeseries", [])
            expected_length = horizon + 1  # year 0 through horizon

            assert len(cashflow_ts) == expected_length, (
                f"Variant {v.get('variant')}: cashflow_timeseries length should be "
                f"{expected_length}, got {len(cashflow_ts)}"
            )

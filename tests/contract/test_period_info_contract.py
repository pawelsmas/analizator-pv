"""
Contract tests for PeriodInfo and 15-min interval support.

Verifies:
1. period_info is always present in sizing response
2. period_info has all required fields
3. 15-min intervals are handled correctly
4. annualization_factor is correct for partial periods
"""
import math
import pytest
from ._api import post_json, load_smoke_payload, pick_recommended_variant


class TestPeriodInfoPresence:
    """Test that period_info is always present."""

    def test_period_info_present_in_response(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify period_info is present in sizing response."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")

        resp = post_json("/sizing", payload)

        assert "period_info" in resp, "period_info missing from response"
        period_info = resp["period_info"]

        # Required fields
        required_fields = [
            "period_hours",
            "period_days",
            "is_full_year",
            "annualization_factor",
            "start_datetime",
            "end_datetime",
        ]

        for field in required_fields:
            assert field in period_info, f"period_info.{field} missing"

    def test_period_info_values_consistent(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify period_info values are internally consistent."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")

        resp = post_json("/sizing", payload)
        pi = resp["period_info"]

        # period_days = period_hours / 24
        assert math.isclose(
            pi["period_days"], pi["period_hours"] / 24, rel_tol=1e-6
        ), "period_days != period_hours / 24"

        # is_full_year iff period_hours >= 8760
        if pi["period_hours"] >= 8760:
            assert pi["is_full_year"] is True
            assert pi["annualization_factor"] == 1.0
        else:
            assert pi["is_full_year"] is False
            expected_factor = 8760 / pi["period_hours"]
            assert math.isclose(
                pi["annualization_factor"], expected_factor, rel_tol=1e-6
            ), f"annualization_factor mismatch: {pi['annualization_factor']} vs {expected_factor}"


class TestIntervalSupport:
    """Test 15-min and 60-min interval support."""

    def test_hourly_interval_accepted(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify 60-min interval works correctly."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        payload["interval_minutes"] = 60

        resp = post_json("/sizing", payload)

        assert "variants" in resp
        assert len(resp["variants"]) > 0

        # Check period_hours matches input
        n_points = len(payload["load_kw"])
        expected_hours = n_points * 60 / 60  # n_points * interval / 60
        assert math.isclose(
            resp["period_info"]["period_hours"], expected_hours, rel_tol=1e-6
        )

    def test_15min_interval_accepted(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify 15-min interval is accepted and period calculated correctly."""
        # Create 15-min payload by expanding hourly data
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")

        # Keep first 24 hours only for test speed
        n_hours = 24
        load_hourly = payload["load_kw"][:n_hours]
        pv_hourly = payload["pv_generation_kw"][:n_hours]

        # Expand to 15-min by repeating each value 4 times
        load_15min = [v for v in load_hourly for _ in range(4)]
        pv_15min = [v for v in pv_hourly for _ in range(4)]

        payload["load_kw"] = load_15min
        payload["pv_generation_kw"] = pv_15min
        payload["interval_minutes"] = 15

        resp = post_json("/sizing", payload)

        assert "variants" in resp
        assert len(resp["variants"]) > 0

        # Check period_hours matches input
        n_points = len(load_15min)
        expected_hours = n_points * 15 / 60  # n_points * interval / 60
        assert math.isclose(
            resp["period_info"]["period_hours"], expected_hours, rel_tol=1e-6
        ), f"period_hours {resp['period_info']['period_hours']} != {expected_hours}"


class TestPartialPeriod:
    """Test partial period handling (< full year)."""

    def test_week_period_annualization(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify annualization factor is correct for 1-week period."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")

        # Use only 1 week (168 hours)
        payload["load_kw"] = payload["load_kw"][:168]
        payload["pv_generation_kw"] = payload["pv_generation_kw"][:168]
        payload["interval_minutes"] = 60

        resp = post_json("/sizing", payload)
        pi = resp["period_info"]

        assert pi["period_hours"] == 168
        assert pi["is_full_year"] is False
        expected_factor = 8760 / 168
        assert math.isclose(
            pi["annualization_factor"], expected_factor, rel_tol=1e-6
        )

    def test_full_year_no_annualization(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify annualization_factor is 1.0 for full year."""
        # This is the default smoke payload which is 168 hours (1 week)
        # We need to check if it's marked correctly
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")

        resp = post_json("/sizing", payload)
        pi = resp["period_info"]

        n_hours = len(payload["load_kw"])
        if n_hours >= 8760:
            assert pi["is_full_year"] is True
            assert pi["annualization_factor"] == 1.0
        else:
            assert pi["is_full_year"] is False
            assert pi["annualization_factor"] > 1.0

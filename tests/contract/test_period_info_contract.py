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

        # Required fields (core)
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

    def test_period_info_extended_fields_present(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify extended period_info fields (v0.3.3) are present."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")

        resp = post_json("/sizing", payload)
        pi = resp["period_info"]

        # Extended fields (v0.3.3) - may be None but should be present
        assert "steps" in pi, "period_info.steps missing"
        assert "step_minutes" in pi, "period_info.step_minutes missing"
        assert "timezone" in pi, "period_info.timezone missing"

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


class TestStepsAndStepMinutes:
    """Test steps and step_minutes consistency (v0.3.3)."""

    def test_steps_equals_n_points(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify steps equals len(load_kw)."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")

        resp = post_json("/sizing", payload)
        pi = resp["period_info"]

        n_points = len(payload["load_kw"])
        assert pi["steps"] == n_points, f"steps {pi['steps']} != n_points {n_points}"

    def test_step_minutes_equals_interval(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify step_minutes equals interval_minutes from request."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        payload["interval_minutes"] = 60

        resp = post_json("/sizing", payload)
        pi = resp["period_info"]

        assert pi["step_minutes"] == 60, f"step_minutes {pi['step_minutes']} != 60"

    def test_period_hours_equals_steps_times_interval(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify period_hours = steps * step_minutes / 60."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        payload["interval_minutes"] = 60

        resp = post_json("/sizing", payload)
        pi = resp["period_info"]

        expected_hours = pi["steps"] * pi["step_minutes"] / 60.0
        assert math.isclose(
            pi["period_hours"], expected_hours, rel_tol=1e-6
        ), f"period_hours {pi['period_hours']} != steps * step_minutes / 60 = {expected_hours}"

    def test_15min_interval_step_minutes(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify step_minutes=15 when interval_minutes=15."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")

        # Keep first 24 hours, expand to 15-min
        n_hours = 24
        load_hourly = payload["load_kw"][:n_hours]
        pv_hourly = payload["pv_generation_kw"][:n_hours]

        load_15min = [v for v in load_hourly for _ in range(4)]
        pv_15min = [v for v in pv_hourly for _ in range(4)]

        payload["load_kw"] = load_15min
        payload["pv_generation_kw"] = pv_15min
        payload["interval_minutes"] = 15

        resp = post_json("/sizing", payload)
        pi = resp["period_info"]

        assert pi["step_minutes"] == 15, f"step_minutes {pi['step_minutes']} != 15"
        assert pi["steps"] == len(load_15min), f"steps {pi['steps']} != {len(load_15min)}"


class TestExplicitPeriodStartEnd:
    """Test explicit period_start/period_end from request (v0.3.3)."""

    def test_explicit_period_start_end_respected(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify explicit period_start/period_end from request are used."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")

        # Set explicit period_start/period_end
        payload["period_start"] = "2025-06-01T00:00:00"
        payload["period_end"] = "2025-06-08T00:00:00"

        resp = post_json("/sizing", payload)
        pi = resp["period_info"]

        assert pi["start_datetime"] == "2025-06-01T00:00:00", \
            f"start_datetime {pi['start_datetime']} != 2025-06-01T00:00:00"
        assert pi["end_datetime"] == "2025-06-08T00:00:00", \
            f"end_datetime {pi['end_datetime']} != 2025-06-08T00:00:00"

    def test_explicit_timezone_respected(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify explicit timezone from request is returned."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")

        # Set explicit timezone
        payload["timezone"] = "Europe/Warsaw"

        resp = post_json("/sizing", payload)
        pi = resp["period_info"]

        assert pi["timezone"] == "Europe/Warsaw", \
            f"timezone {pi['timezone']} != Europe/Warsaw"

    def test_default_timezone_none(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify timezone is None when not provided."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")

        # Ensure no timezone in payload
        payload.pop("timezone", None)

        resp = post_json("/sizing", payload)
        pi = resp["period_info"]

        # timezone should be None (or null in JSON)
        assert pi.get("timezone") is None, f"timezone should be None, got {pi.get('timezone')}"


class Test15MinEquivalence:
    """Test 15-min vs 60-min equivalence (same energy, similar results)."""

    def test_15min_vs_60min_similar_npv(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify 15-min and 60-min produce similar NPV for same energy."""
        # Run 60-min
        payload_60 = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        n_hours = 24
        load_hourly = payload_60["load_kw"][:n_hours]
        pv_hourly = payload_60["pv_generation_kw"][:n_hours]

        payload_60["load_kw"] = load_hourly
        payload_60["pv_generation_kw"] = pv_hourly
        payload_60["interval_minutes"] = 60

        resp_60 = post_json("/sizing", payload_60)

        # Run 15-min (expanded from same hourly data)
        payload_15 = load_smoke_payload("sizing_stacked_no_arbitrage.json")
        load_15min = [v for v in load_hourly for _ in range(4)]
        pv_15min = [v for v in pv_hourly for _ in range(4)]

        payload_15["load_kw"] = load_15min
        payload_15["pv_generation_kw"] = pv_15min
        payload_15["interval_minutes"] = 15

        resp_15 = post_json("/sizing", payload_15)

        # Same period_hours
        assert math.isclose(
            resp_60["period_info"]["period_hours"],
            resp_15["period_info"]["period_hours"],
            rel_tol=1e-6
        ), "period_hours should be same for 60-min and 15-min"

        # NPV should be similar (not exact due to dispatch differences)
        recommended_60 = pick_recommended_variant(resp_60)
        recommended_15 = pick_recommended_variant(resp_15)

        if recommended_60 and recommended_15:
            npv_60 = recommended_60["npv_pln"]
            npv_15 = recommended_15["npv_pln"]

            # Allow 10% tolerance due to dispatch granularity differences
            assert math.isclose(npv_60, npv_15, rel_tol=0.10), \
                f"NPV 60-min {npv_60} vs 15-min {npv_15} differ by >10%"

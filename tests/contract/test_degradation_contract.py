"""
Contract tests for degradation metrics and daily cycle limits.

Verifies:
1. Daily statistics are present in degradation metrics
2. max_daily_efc and avg_daily_efc are computed correctly
3. days_exceeding_cycle_limit is tracked
4. DegradationBudget.max_cycles_per_day triggers warnings
"""
import pytest
from ._api import post_json, load_smoke_payload, pick_recommended_variant


class TestDailyDegradationMetrics:
    """Test daily degradation metrics in sizing response."""

    def test_daily_statistics_present(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify daily statistics are present in degradation metrics."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")

        resp = post_json("/sizing", payload)

        recommended = pick_recommended_variant(resp)
        assert recommended is not None, "No recommended variant"

        # Check dispatch_summary has degradation
        ds = recommended.get("dispatch_summary", {})
        deg = ds.get("degradation", {})

        # Daily statistics should be present
        assert "n_days" in deg, "n_days missing from degradation"
        assert "max_daily_efc" in deg, "max_daily_efc missing from degradation"
        assert "avg_daily_efc" in deg, "avg_daily_efc missing from degradation"
        assert "max_daily_throughput_mwh" in deg, "max_daily_throughput_mwh missing"
        assert "avg_daily_throughput_mwh" in deg, "avg_daily_throughput_mwh missing"

    def test_n_days_positive(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify n_days is positive for multi-day analysis."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")

        resp = post_json("/sizing", payload)

        recommended = pick_recommended_variant(resp)
        ds = recommended.get("dispatch_summary", {})
        deg = ds.get("degradation", {})

        # n_days should be > 0 for multi-day analysis
        n_hours = len(payload["load_kw"])
        expected_days = n_hours // 24

        if expected_days > 0:
            assert deg["n_days"] >= expected_days, (
                f"n_days {deg['n_days']} < expected {expected_days}"
            )

    def test_daily_efc_reasonable(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify daily EFC values are reasonable (not exceeding physics)."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")

        resp = post_json("/sizing", payload)

        recommended = pick_recommended_variant(resp)
        ds = recommended.get("dispatch_summary", {})
        deg = ds.get("degradation", {})

        # Max daily EFC should be reasonable (typically < 2-3 for normal operation)
        # In extreme cases it could be higher, but >10 is unrealistic
        max_efc = deg.get("max_daily_efc", 0)
        assert max_efc <= 10, f"max_daily_efc {max_efc} unreasonably high"

        # Average should be <= max
        avg_efc = deg.get("avg_daily_efc", 0)
        if max_efc > 0:
            assert avg_efc <= max_efc + 0.001, (
                f"avg_daily_efc {avg_efc} > max_daily_efc {max_efc}"
            )

    def test_efc_total_equals_days_times_avg(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify total EFC ≈ n_days × avg_daily_efc."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")

        resp = post_json("/sizing", payload)

        recommended = pick_recommended_variant(resp)
        ds = recommended.get("dispatch_summary", {})
        deg = ds.get("degradation", {})

        n_days = deg.get("n_days", 0)
        avg_efc = deg.get("avg_daily_efc", 0)
        efc_total = deg.get("efc_total", 0)

        if n_days > 0 and efc_total > 0:
            calculated = n_days * avg_efc
            # Allow 20% tolerance due to partial days and rounding
            tolerance = max(0.2 * efc_total, 0.1)
            assert abs(efc_total - calculated) < tolerance, (
                f"efc_total {efc_total} != n_days {n_days} × avg {avg_efc} = {calculated}"
            )


class TestDegradationBudgetDailyLimits:
    """Test daily cycle limits in degradation budget."""

    def test_max_cycles_per_day_accepted_in_request(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify degradation_budget.max_cycles_per_day is accepted."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")

        # Add degradation budget with daily limit
        payload["degradation_budget"] = {
            "max_cycles_per_day": 1.5,
            "max_efc_per_year": 500,
        }

        resp = post_json("/sizing", payload)

        # Should return valid response
        assert "variants" in resp
        assert len(resp["variants"]) > 0

    def test_daily_limit_warning_triggered(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify warning is generated when daily limit is exceeded."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")

        # Set very low daily limit to trigger warning
        payload["degradation_budget"] = {
            "max_cycles_per_day": 0.1,  # Very low limit
        }

        resp = post_json("/sizing", payload)

        recommended = pick_recommended_variant(resp)
        ds = recommended.get("dispatch_summary", {})
        deg = ds.get("degradation", {})

        # Should have warning about daily limit
        warnings = deg.get("budget_warnings", [])
        has_daily_warning = any(
            "DAILY" in w.upper() or "daily" in w.lower()
            for w in warnings
        )

        max_daily = deg.get("max_daily_efc", 0)
        if max_daily > 0.1:
            assert has_daily_warning, (
                f"Expected DAILY warning for max_daily_efc={max_daily} > limit=0.1, "
                f"but got warnings: {warnings}"
            )


class TestBatteryThroughputAndDegradationCost:
    """Test battery_throughput_mwh and degradation_cost_pln in savings_breakdown."""

    def test_battery_throughput_present(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify battery_throughput_mwh is present in savings_breakdown."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")

        resp = post_json("/sizing", payload)

        recommended = pick_recommended_variant(resp)
        sb = recommended.get("savings_breakdown", {})

        assert "battery_throughput_mwh" in sb, "battery_throughput_mwh missing"
        assert sb["battery_throughput_mwh"] >= 0, "battery_throughput_mwh should be >= 0"

    def test_degradation_cost_calculated_with_rate(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify degradation_cost_pln is calculated when degradation_cost_pln_mwh is set."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")

        # Set explicit degradation cost rate
        payload["degradation_cost_pln_mwh"] = 100.0  # 100 PLN/MWh

        resp = post_json("/sizing", payload)

        recommended = pick_recommended_variant(resp)
        sb = recommended.get("savings_breakdown", {})

        throughput = sb.get("battery_throughput_mwh", 0)
        deg_cost = sb.get("degradation_cost_pln", 0)

        # If there's throughput, there should be degradation cost
        if throughput > 0:
            expected_cost = throughput * 100.0  # rate * throughput
            assert abs(deg_cost - expected_cost) < 1.0, (
                f"degradation_cost_pln {deg_cost} != throughput {throughput} * 100 = {expected_cost}"
            )

    def test_zero_degradation_rate_zero_cost(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify degradation_cost_pln is 0 when degradation_cost_pln_mwh is 0."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")

        # Set zero degradation cost rate
        payload["degradation_cost_pln_mwh"] = 0.0

        resp = post_json("/sizing", payload)

        recommended = pick_recommended_variant(resp)
        sb = recommended.get("savings_breakdown", {})

        deg_cost = sb.get("degradation_cost_pln", 0)
        assert deg_cost == 0, f"degradation_cost_pln should be 0, got {deg_cost}"


class TestDaysExceedingLimits:
    """Test days_exceeding_cycle_limit tracking."""

    def test_days_exceeding_fields_present(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify days_exceeding fields are in response."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")

        resp = post_json("/sizing", payload)

        recommended = pick_recommended_variant(resp)
        ds = recommended.get("dispatch_summary", {})
        deg = ds.get("degradation", {})

        assert "days_exceeding_cycle_limit" in deg, (
            "days_exceeding_cycle_limit missing"
        )
        assert "days_exceeding_throughput_limit" in deg, (
            "days_exceeding_throughput_limit missing"
        )

    def test_days_exceeding_non_negative(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify days_exceeding values are non-negative."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")

        resp = post_json("/sizing", payload)

        recommended = pick_recommended_variant(resp)
        ds = recommended.get("dispatch_summary", {})
        deg = ds.get("degradation", {})

        assert deg.get("days_exceeding_cycle_limit", 0) >= 0
        assert deg.get("days_exceeding_throughput_limit", 0) >= 0

    def test_days_exceeding_not_more_than_n_days(
        self, wait_for_services, bess_dispatch_url
    ):
        """Verify days_exceeding <= n_days."""
        payload = load_smoke_payload("sizing_stacked_no_arbitrage.json")

        # Set low limit to trigger exceeding
        payload["degradation_budget"] = {
            "max_cycles_per_day": 0.1,
        }

        resp = post_json("/sizing", payload)

        recommended = pick_recommended_variant(resp)
        ds = recommended.get("dispatch_summary", {})
        deg = ds.get("degradation", {})

        n_days = deg.get("n_days", 0)
        exceeding = deg.get("days_exceeding_cycle_limit", 0)

        assert exceeding <= n_days, (
            f"days_exceeding_cycle_limit {exceeding} > n_days {n_days}"
        )

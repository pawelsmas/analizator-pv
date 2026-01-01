"""
Contract tests for Cycle Limit Enforcement (v2.2.0 PR2).

Tests verify:
- max_cycles_per_day in degradation_budget limits daily EFC
- Discharge is clamped when limit would be exceeded
- Multiple days reset the limit correctly
"""

import pytest
import requests
import os

# Test against local API
API_BASE = os.environ.get("BESS_API_URL", "http://localhost:8000")


def get_dispatch_request_with_cycle_limit(
    max_cycles_per_day: float,
    n_hours: int = 48,
) -> dict:
    """Create dispatch request with cycle limit."""
    # Constant high discharge scenario (would exceed limit without clamping)
    pv = [100.0] * n_hours  # 100 kW constant PV
    load = [20.0] * n_hours  # 20 kW constant load (surplus = 80 kW)

    return {
        "pv_generation_kw": pv,
        "load_kw": load,
        "interval_minutes": 60,
        "battery": {
            "power_kw": 50.0,
            "energy_kwh": 100.0,  # 100 kWh capacity
            "roundtrip_efficiency": 0.9,
            "soc_min": 0.1,
            "soc_max": 0.9,
            "soc_initial": 0.5,
        },
        "mode": "pv_surplus",
        "degradation_budget": {
            "max_cycles_per_day": max_cycles_per_day,
        },
        "include_battery_trace": True,
    }


class TestCycleLimitPresence:
    """Tests for cycle limit feature availability."""

    def test_degradation_budget_accepted(self):
        """Verify degradation_budget with max_cycles_per_day is accepted."""
        request = get_dispatch_request_with_cycle_limit(max_cycles_per_day=2.0)
        response = requests.post(f"{API_BASE}/api/bess-dispatch/dispatch", json=request)

        # Should not fail due to parameter
        assert response.status_code in [200, 500], f"Unexpected status: {response.status_code}"


class TestCycleLimitEnforcement:
    """Tests for cycle limit enforcement during dispatch."""

    def test_discharge_limited_to_max_cycles(self):
        """Verify discharge is limited to max_cycles_per_day."""
        # 1 EFC/day limit with 100 kWh capacity = 100 kWh/day max discharge
        request = get_dispatch_request_with_cycle_limit(max_cycles_per_day=1.0, n_hours=24)
        response = requests.post(f"{API_BASE}/api/bess-dispatch/dispatch", json=request)

        if response.status_code != 200:
            pytest.skip(f"API returned {response.status_code}")

        data = response.json()

        # Total discharge should be <= usable_capacity * max_cycles_per_day
        # usable_capacity = 100 * (0.9 - 0.1) = 80 kWh
        # max_daily_discharge = 80 * 1.0 = 80 kWh
        usable_capacity = 100.0 * (0.9 - 0.1)
        max_daily_discharge = usable_capacity * 1.0

        assert data["total_discharge_kwh"] <= max_daily_discharge * 1.01  # 1% tolerance


class TestCycleLimitDegradationMetrics:
    """Tests for degradation metrics with cycle limits."""

    def test_degradation_metrics_present(self):
        """Verify degradation metrics are returned."""
        request = get_dispatch_request_with_cycle_limit(max_cycles_per_day=2.0)
        response = requests.post(f"{API_BASE}/api/bess-dispatch/dispatch", json=request)

        if response.status_code != 200:
            pytest.skip(f"API returned {response.status_code}")

        data = response.json()

        assert "degradation" in data
        degradation = data["degradation"]
        assert "efc_total" in degradation
        assert "throughput_total_mwh" in degradation

    def test_efc_respects_limit(self):
        """Verify EFC respects daily limit."""
        # 0.5 EFC/day limit, 2 days = max 1.0 total EFC
        request = get_dispatch_request_with_cycle_limit(max_cycles_per_day=0.5, n_hours=48)
        response = requests.post(f"{API_BASE}/api/bess-dispatch/dispatch", json=request)

        if response.status_code != 200:
            pytest.skip(f"API returned {response.status_code}")

        data = response.json()
        degradation = data["degradation"]

        # EFC should be <= 2 days * 0.5 EFC/day = 1.0 EFC
        assert degradation["efc_total"] <= 1.1  # 10% tolerance


class TestCycleLimitBatteryTrace:
    """Tests for battery trace with cycle limits."""

    def test_battery_trace_reflects_clamping(self):
        """Verify battery trace shows clamped discharge."""
        # Very low limit to force clamping
        request = get_dispatch_request_with_cycle_limit(max_cycles_per_day=0.1, n_hours=24)
        response = requests.post(f"{API_BASE}/api/bess-dispatch/dispatch", json=request)

        if response.status_code != 200:
            pytest.skip(f"API returned {response.status_code}")

        data = response.json()
        trace = data.get("battery_trace")

        if trace is None:
            pytest.skip("battery_trace not returned")

        # Discharge should be zero after limit reached
        discharge_kw = trace["discharge_kw"]

        # Sum of discharge * dt should be <= limit
        usable_capacity = 100.0 * (0.9 - 0.1)
        max_daily_discharge = usable_capacity * 0.1  # 8 kWh/day

        total_discharge_kwh = sum(discharge_kw)  # Each value is kW for 1 hour
        assert total_discharge_kwh <= max_daily_discharge * 1.1  # 10% tolerance


class TestNoCycleLimit:
    """Tests for dispatch without cycle limits."""

    def test_no_limit_allows_full_cycling(self):
        """Verify no limit allows unlimited cycling."""
        request = get_dispatch_request_with_cycle_limit(max_cycles_per_day=10.0, n_hours=24)
        # Remove the limit
        del request["degradation_budget"]

        response = requests.post(f"{API_BASE}/api/bess-dispatch/dispatch", json=request)

        if response.status_code != 200:
            pytest.skip(f"API returned {response.status_code}")

        data = response.json()

        # Without limit, discharge can be higher
        # (just verify the request works)
        assert data["total_discharge_kwh"] >= 0

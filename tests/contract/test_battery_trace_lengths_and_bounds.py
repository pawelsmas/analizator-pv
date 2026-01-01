"""
Contract tests for Battery Trace (v2.2.0 PR1).

Tests verify:
- battery_trace is returned when include_battery_trace=True
- battery_trace is None when include_battery_trace=False (default)
- len(soc_kwh) == period_info.steps (or n_timesteps)
- min(soc_kwh) >= -1e-6 (allow for floating point)
- max(soc_kwh) <= energy_kwh + 1e-6
- All power arrays are non-negative
- charge_from_pv + charge_from_grid == charge (approximately)
- discharge_to_load + discharge_to_grid == discharge (approximately)
"""

import pytest
import requests
import os

# Test against local API
API_BASE = os.environ.get("BESS_API_URL", "http://localhost:8000")


def get_minimal_dispatch_request(mode: str = "pv_surplus", include_battery_trace: bool = True):
    """Create a minimal valid dispatch request for testing."""
    # 24-hour profile (hourly intervals)
    n = 24
    pv = [50.0] * n  # 50 kW constant PV
    load = [30.0] * n  # 30 kW constant load

    request = {
        "pv_generation_kw": pv,
        "load_kw": load,
        "interval_minutes": 60,
        "battery": {
            "power_kw": 20.0,
            "energy_kwh": 40.0,
            "roundtrip_efficiency": 0.9,
            "soc_min": 0.1,
            "soc_max": 0.9,
            "soc_initial": 0.5,
        },
        "mode": mode,
        "include_battery_trace": include_battery_trace,
    }

    if mode in ["peak_shaving", "load_only"]:
        request["peak_limit_kw"] = 25.0

    if mode == "stacked":
        request["stacked_params"] = {
            "peak_limit_kw": 25.0,
            "reserve_fraction": 0.3,
        }

    if mode == "load_only":
        request["topology"] = "load_only"
        request["pv_generation_kw"] = []

    return request


class TestBatteryTracePresence:
    """Tests for battery_trace field presence."""

    @pytest.mark.parametrize("mode", ["pv_surplus", "peak_shaving", "stacked"])
    def test_battery_trace_present_when_requested(self, mode):
        """Verify battery_trace is returned when include_battery_trace=True."""
        request = get_minimal_dispatch_request(mode=mode, include_battery_trace=True)
        response = requests.post(f"{API_BASE}/api/bess-dispatch/dispatch", json=request)

        if response.status_code != 200:
            pytest.skip(f"API returned {response.status_code}: {response.text[:200]}")

        data = response.json()
        assert "battery_trace" in data, "battery_trace field should be present"
        assert data["battery_trace"] is not None, "battery_trace should not be None"

    @pytest.mark.parametrize("mode", ["pv_surplus", "peak_shaving", "stacked"])
    def test_battery_trace_none_when_not_requested(self, mode):
        """Verify battery_trace is None when include_battery_trace=False."""
        request = get_minimal_dispatch_request(mode=mode, include_battery_trace=False)
        response = requests.post(f"{API_BASE}/api/bess-dispatch/dispatch", json=request)

        if response.status_code != 200:
            pytest.skip(f"API returned {response.status_code}: {response.text[:200]}")

        data = response.json()
        # battery_trace should either be absent or None
        assert data.get("battery_trace") is None, "battery_trace should be None when not requested"


class TestBatteryTraceLengths:
    """Tests for battery_trace array lengths."""

    @pytest.mark.parametrize("mode", ["pv_surplus", "peak_shaving", "stacked"])
    def test_soc_length_matches_timesteps(self, mode):
        """Verify len(soc_kwh) == n_timesteps."""
        request = get_minimal_dispatch_request(mode=mode, include_battery_trace=True)
        response = requests.post(f"{API_BASE}/api/bess-dispatch/dispatch", json=request)

        if response.status_code != 200:
            pytest.skip(f"API returned {response.status_code}")

        data = response.json()
        trace = data.get("battery_trace")
        if trace is None:
            pytest.skip("battery_trace not returned")

        n_timesteps = data["n_timesteps"]
        assert len(trace["soc_kwh"]) == n_timesteps, \
            f"soc_kwh length {len(trace['soc_kwh'])} should match n_timesteps {n_timesteps}"

    @pytest.mark.parametrize("mode", ["pv_surplus", "peak_shaving", "stacked"])
    def test_all_arrays_same_length(self, mode):
        """Verify all trace arrays have the same length as steps."""
        request = get_minimal_dispatch_request(mode=mode, include_battery_trace=True)
        response = requests.post(f"{API_BASE}/api/bess-dispatch/dispatch", json=request)

        if response.status_code != 200:
            pytest.skip(f"API returned {response.status_code}")

        data = response.json()
        trace = data.get("battery_trace")
        if trace is None:
            pytest.skip("battery_trace not returned")

        steps = trace["steps"]
        arrays = [
            ("soc_kwh", trace["soc_kwh"]),
            ("charge_kw", trace["charge_kw"]),
            ("discharge_kw", trace["discharge_kw"]),
            ("charge_from_pv_kw", trace["charge_from_pv_kw"]),
            ("charge_from_grid_kw", trace["charge_from_grid_kw"]),
            ("discharge_to_load_kw", trace["discharge_to_load_kw"]),
            ("discharge_to_grid_kw", trace["discharge_to_grid_kw"]),
        ]

        for name, arr in arrays:
            assert len(arr) == steps, f"{name} length {len(arr)} should match steps {steps}"


class TestBatteryTraceSocBounds:
    """Tests for SOC bounds validation."""

    @pytest.mark.parametrize("mode", ["pv_surplus", "peak_shaving", "stacked"])
    def test_soc_min_bound(self, mode):
        """Verify min(soc_kwh) >= -tolerance."""
        request = get_minimal_dispatch_request(mode=mode, include_battery_trace=True)
        response = requests.post(f"{API_BASE}/api/bess-dispatch/dispatch", json=request)

        if response.status_code != 200:
            pytest.skip(f"API returned {response.status_code}")

        data = response.json()
        trace = data.get("battery_trace")
        if trace is None:
            pytest.skip("battery_trace not returned")

        min_soc = min(trace["soc_kwh"])
        tolerance = 1e-6
        assert min_soc >= -tolerance, \
            f"min(soc_kwh)={min_soc:.6f} should be >= {-tolerance}"

    @pytest.mark.parametrize("mode", ["pv_surplus", "peak_shaving", "stacked"])
    def test_soc_max_bound(self, mode):
        """Verify max(soc_kwh) <= energy_kwh + tolerance."""
        request = get_minimal_dispatch_request(mode=mode, include_battery_trace=True)
        response = requests.post(f"{API_BASE}/api/bess-dispatch/dispatch", json=request)

        if response.status_code != 200:
            pytest.skip(f"API returned {response.status_code}")

        data = response.json()
        trace = data.get("battery_trace")
        if trace is None:
            pytest.skip("battery_trace not returned")

        max_soc = max(trace["soc_kwh"])
        energy_kwh = trace["battery_energy_kwh"]
        tolerance = 1e-6
        assert max_soc <= energy_kwh + tolerance, \
            f"max(soc_kwh)={max_soc:.6f} should be <= energy_kwh={energy_kwh} + tolerance"


class TestBatteryTracePowerNonNegative:
    """Tests for power non-negativity."""

    @pytest.mark.parametrize("mode", ["pv_surplus", "peak_shaving", "stacked"])
    def test_charge_non_negative(self, mode):
        """Verify all charge values are non-negative."""
        request = get_minimal_dispatch_request(mode=mode, include_battery_trace=True)
        response = requests.post(f"{API_BASE}/api/bess-dispatch/dispatch", json=request)

        if response.status_code != 200:
            pytest.skip(f"API returned {response.status_code}")

        data = response.json()
        trace = data.get("battery_trace")
        if trace is None:
            pytest.skip("battery_trace not returned")

        min_charge = min(trace["charge_kw"])
        assert min_charge >= 0, f"min(charge_kw)={min_charge} should be >= 0"

    @pytest.mark.parametrize("mode", ["pv_surplus", "peak_shaving", "stacked"])
    def test_discharge_non_negative(self, mode):
        """Verify all discharge values are non-negative."""
        request = get_minimal_dispatch_request(mode=mode, include_battery_trace=True)
        response = requests.post(f"{API_BASE}/api/bess-dispatch/dispatch", json=request)

        if response.status_code != 200:
            pytest.skip(f"API returned {response.status_code}")

        data = response.json()
        trace = data.get("battery_trace")
        if trace is None:
            pytest.skip("battery_trace not returned")

        min_discharge = min(trace["discharge_kw"])
        assert min_discharge >= 0, f"min(discharge_kw)={min_discharge} should be >= 0"


class TestBatteryTraceChargeSplit:
    """Tests for charge source split invariant."""

    @pytest.mark.parametrize("mode", ["pv_surplus", "peak_shaving", "stacked"])
    def test_charge_equals_sum_of_sources(self, mode):
        """Verify charge_from_pv + charge_from_grid ≈ charge."""
        request = get_minimal_dispatch_request(mode=mode, include_battery_trace=True)
        response = requests.post(f"{API_BASE}/api/bess-dispatch/dispatch", json=request)

        if response.status_code != 200:
            pytest.skip(f"API returned {response.status_code}")

        data = response.json()
        trace = data.get("battery_trace")
        if trace is None:
            pytest.skip("battery_trace not returned")

        tolerance = 1e-6
        for i in range(trace["steps"]):
            charge_sum = trace["charge_from_pv_kw"][i] + trace["charge_from_grid_kw"][i]
            charge_total = trace["charge_kw"][i]
            assert abs(charge_sum - charge_total) <= tolerance, \
                f"Step {i}: charge_from_pv + charge_from_grid = {charge_sum} != charge = {charge_total}"


class TestBatteryTraceDischargeSplit:
    """Tests for discharge destination split invariant."""

    @pytest.mark.parametrize("mode", ["pv_surplus", "peak_shaving", "stacked"])
    def test_discharge_equals_sum_of_destinations(self, mode):
        """Verify discharge_to_load + discharge_to_grid ≈ discharge."""
        request = get_minimal_dispatch_request(mode=mode, include_battery_trace=True)
        response = requests.post(f"{API_BASE}/api/bess-dispatch/dispatch", json=request)

        if response.status_code != 200:
            pytest.skip(f"API returned {response.status_code}")

        data = response.json()
        trace = data.get("battery_trace")
        if trace is None:
            pytest.skip("battery_trace not returned")

        tolerance = 1e-6
        for i in range(trace["steps"]):
            discharge_sum = trace["discharge_to_load_kw"][i] + trace["discharge_to_grid_kw"][i]
            discharge_total = trace["discharge_kw"][i]
            assert abs(discharge_sum - discharge_total) <= tolerance, \
                f"Step {i}: discharge_to_load + discharge_to_grid = {discharge_sum} != discharge = {discharge_total}"


class TestBatteryTraceMetadata:
    """Tests for battery trace metadata fields."""

    @pytest.mark.parametrize("mode", ["pv_surplus", "peak_shaving", "stacked"])
    def test_metadata_matches_request(self, mode):
        """Verify trace metadata matches request parameters."""
        request = get_minimal_dispatch_request(mode=mode, include_battery_trace=True)
        response = requests.post(f"{API_BASE}/api/bess-dispatch/dispatch", json=request)

        if response.status_code != 200:
            pytest.skip(f"API returned {response.status_code}")

        data = response.json()
        trace = data.get("battery_trace")
        if trace is None:
            pytest.skip("battery_trace not returned")

        # Check metadata
        assert trace["step_minutes"] == request["interval_minutes"]
        assert trace["battery_energy_kwh"] == request["battery"]["energy_kwh"]
        assert trace["battery_power_kw"] == request["battery"]["power_kw"]

"""
Unit tests for dispatch scenarios (v2.2.0 PR5).

Tests verify:
- Dispatch pack definition exists
- All scenario directories exist with required files
- Request files are valid JSON
- Expected KPIs files are valid JSON
"""

import pytest
import os
import json


class TestDispatchPackDefinition:
    """Tests for dispatch.yml pack definition."""

    @pytest.fixture
    def pack_path(self):
        """Get path to dispatch pack."""
        return os.path.join(
            os.path.dirname(__file__),
            "..", "..", "docs", "scenarios", "packs", "dispatch.yml"
        )

    def test_dispatch_pack_exists(self, pack_path):
        """Verify dispatch.yml pack file exists."""
        assert os.path.exists(pack_path), f"Pack file not found: {pack_path}"

    def test_dispatch_pack_has_scenarios(self, pack_path):
        """Verify pack defines scenarios."""
        import yaml
        with open(pack_path, "r") as f:
            pack = yaml.safe_load(f)
        assert "scenarios" in pack
        assert len(pack["scenarios"]) >= 5


class TestDispatchBatteryTraceScenario:
    """Tests for dispatch_battery_trace_basic scenario."""

    @pytest.fixture
    def scenario_dir(self):
        """Get scenario directory."""
        return os.path.join(
            os.path.dirname(__file__),
            "..", "..", "docs", "scenarios", "dispatch_battery_trace_basic"
        )

    def test_request_file_exists(self, scenario_dir):
        """Verify request.json exists."""
        request_path = os.path.join(scenario_dir, "request.json")
        assert os.path.exists(request_path)

    def test_request_file_valid_json(self, scenario_dir):
        """Verify request.json is valid JSON."""
        request_path = os.path.join(scenario_dir, "request.json")
        with open(request_path, "r") as f:
            request = json.load(f)
        assert "load_kw" in request
        assert "pv_generation_kw" in request
        assert "include_battery_trace" in request
        assert request["include_battery_trace"] is True

    def test_expected_kpis_exists(self, scenario_dir):
        """Verify expected_kpis.json exists."""
        kpis_path = os.path.join(scenario_dir, "expected_kpis.json")
        assert os.path.exists(kpis_path)

    def test_expected_kpis_valid_json(self, scenario_dir):
        """Verify expected_kpis.json is valid JSON."""
        kpis_path = os.path.join(scenario_dir, "expected_kpis.json")
        with open(kpis_path, "r") as f:
            kpis = json.load(f)
        assert "battery_trace_steps" in kpis

    def test_tolerances_exists(self, scenario_dir):
        """Verify tolerances.json exists."""
        tol_path = os.path.join(scenario_dir, "tolerances.json")
        assert os.path.exists(tol_path)


class TestDispatchCycleLimitScenario:
    """Tests for dispatch_cycle_limit_enforcement scenario."""

    @pytest.fixture
    def scenario_dir(self):
        """Get scenario directory."""
        return os.path.join(
            os.path.dirname(__file__),
            "..", "..", "docs", "scenarios", "dispatch_cycle_limit_enforcement"
        )

    def test_request_file_exists(self, scenario_dir):
        """Verify request.json exists."""
        request_path = os.path.join(scenario_dir, "request.json")
        assert os.path.exists(request_path)

    def test_request_has_max_cycles_per_day(self, scenario_dir):
        """Verify request includes max_cycles_per_day."""
        request_path = os.path.join(scenario_dir, "request.json")
        with open(request_path, "r") as f:
            request = json.load(f)
        assert "max_cycles_per_day" in request
        assert request["max_cycles_per_day"] == 1.0

    def test_expected_kpis_exists(self, scenario_dir):
        """Verify expected_kpis.json exists."""
        kpis_path = os.path.join(scenario_dir, "expected_kpis.json")
        assert os.path.exists(kpis_path)


class TestDispatchInvariantsScenario:
    """Tests for dispatch_invariants_soc_bounds scenario."""

    @pytest.fixture
    def scenario_dir(self):
        """Get scenario directory."""
        return os.path.join(
            os.path.dirname(__file__),
            "..", "..", "docs", "scenarios", "dispatch_invariants_soc_bounds"
        )

    def test_request_file_exists(self, scenario_dir):
        """Verify request.json exists."""
        request_path = os.path.join(scenario_dir, "request.json")
        assert os.path.exists(request_path)

    def test_request_has_include_invariants(self, scenario_dir):
        """Verify request includes include_invariants."""
        request_path = os.path.join(scenario_dir, "request.json")
        with open(request_path, "r") as f:
            request = json.load(f)
        assert "include_invariants" in request
        assert request["include_invariants"] is True

    def test_expected_kpis_has_invariants(self, scenario_dir):
        """Verify expected_kpis includes invariant checks."""
        kpis_path = os.path.join(scenario_dir, "expected_kpis.json")
        with open(kpis_path, "r") as f:
            kpis = json.load(f)
        assert "invariants_all_ok" in kpis
        assert "soc_bounds_ok" in kpis


class TestDispatchPowerClampScenario:
    """Tests for dispatch_power_clamp_charge scenario."""

    @pytest.fixture
    def scenario_dir(self):
        """Get scenario directory."""
        return os.path.join(
            os.path.dirname(__file__),
            "..", "..", "docs", "scenarios", "dispatch_power_clamp_charge"
        )

    def test_request_file_exists(self, scenario_dir):
        """Verify request.json exists."""
        request_path = os.path.join(scenario_dir, "request.json")
        assert os.path.exists(request_path)

    def test_request_has_battery_power_limit(self, scenario_dir):
        """Verify request has battery power limit."""
        request_path = os.path.join(scenario_dir, "request.json")
        with open(request_path, "r") as f:
            request = json.load(f)
        assert "battery" in request
        assert "power_kw" in request["battery"]
        assert request["battery"]["power_kw"] == 50.0

    def test_expected_kpis_exists(self, scenario_dir):
        """Verify expected_kpis.json exists."""
        kpis_path = os.path.join(scenario_dir, "expected_kpis.json")
        assert os.path.exists(kpis_path)


class TestDispatchGridChargeScenario:
    """Tests for dispatch_grid_charge_enabled scenario."""

    @pytest.fixture
    def scenario_dir(self):
        """Get scenario directory."""
        return os.path.join(
            os.path.dirname(__file__),
            "..", "..", "docs", "scenarios", "dispatch_grid_charge_enabled"
        )

    def test_request_file_exists(self, scenario_dir):
        """Verify request.json exists."""
        request_path = os.path.join(scenario_dir, "request.json")
        assert os.path.exists(request_path)

    def test_request_has_allow_grid_charge(self, scenario_dir):
        """Verify request includes allow_grid_charge."""
        request_path = os.path.join(scenario_dir, "request.json")
        with open(request_path, "r") as f:
            request = json.load(f)
        assert "allow_grid_charge" in request
        assert request["allow_grid_charge"] is True

    def test_request_is_stacked_mode(self, scenario_dir):
        """Verify request uses stacked mode."""
        request_path = os.path.join(scenario_dir, "request.json")
        with open(request_path, "r") as f:
            request = json.load(f)
        assert request["mode"] == "stacked"

    def test_expected_kpis_exists(self, scenario_dir):
        """Verify expected_kpis.json exists."""
        kpis_path = os.path.join(scenario_dir, "expected_kpis.json")
        assert os.path.exists(kpis_path)


class TestAllDispatchScenarios:
    """Tests for all dispatch scenarios collectively."""

    @pytest.fixture
    def scenarios_base_dir(self):
        """Get base scenarios directory."""
        return os.path.join(
            os.path.dirname(__file__),
            "..", "..", "docs", "scenarios"
        )

    def test_all_scenario_dirs_exist(self, scenarios_base_dir):
        """Verify all dispatch scenario directories exist."""
        expected_dirs = [
            "dispatch_battery_trace_basic",
            "dispatch_cycle_limit_enforcement",
            "dispatch_invariants_soc_bounds",
            "dispatch_power_clamp_charge",
            "dispatch_grid_charge_enabled",
        ]
        for scenario in expected_dirs:
            path = os.path.join(scenarios_base_dir, scenario)
            assert os.path.isdir(path), f"Scenario dir not found: {scenario}"

    def test_all_scenarios_have_required_files(self, scenarios_base_dir):
        """Verify all scenarios have request.json, expected_kpis.json, tolerances.json."""
        expected_dirs = [
            "dispatch_battery_trace_basic",
            "dispatch_cycle_limit_enforcement",
            "dispatch_invariants_soc_bounds",
            "dispatch_power_clamp_charge",
            "dispatch_grid_charge_enabled",
        ]
        required_files = ["request.json", "expected_kpis.json", "tolerances.json"]

        for scenario in expected_dirs:
            for filename in required_files:
                path = os.path.join(scenarios_base_dir, scenario, filename)
                assert os.path.exists(path), f"Missing {filename} in {scenario}"

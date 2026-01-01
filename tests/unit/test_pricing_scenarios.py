"""
Unit tests for Pricing scenarios pack structure (v2.1.0 PR5).

Tests verify:
- Pricing pack YAML structure
- Scenario JSON file structure
- Expected fields presence
- Request/expected field validation
"""

import json
import os
import pytest
import yaml


SCENARIOS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "docs", "scenarios"
)
PACKS_DIR = os.path.join(SCENARIOS_DIR, "packs")


class TestPricingPackStructure:
    """Tests for pricing.yml pack file."""

    def test_pricing_pack_exists(self):
        """Verify pricing.yml pack file exists."""
        pack_path = os.path.join(PACKS_DIR, "pricing.yml")
        assert os.path.exists(pack_path), "pricing.yml pack file should exist"

    def test_pricing_pack_has_name(self):
        """Verify pricing pack has name field."""
        pack_path = os.path.join(PACKS_DIR, "pricing.yml")
        with open(pack_path, "r") as f:
            data = yaml.safe_load(f)
        assert "name" in data
        assert data["name"] == "pricing"

    def test_pricing_pack_has_scenarios(self):
        """Verify pricing pack has scenarios list."""
        pack_path = os.path.join(PACKS_DIR, "pricing.yml")
        with open(pack_path, "r") as f:
            data = yaml.safe_load(f)
        assert "scenarios" in data
        assert isinstance(data["scenarios"], list)
        assert len(data["scenarios"]) >= 5

    def test_pricing_pack_scenario_ids(self):
        """Verify pricing pack contains expected scenario IDs."""
        pack_path = os.path.join(PACKS_DIR, "pricing.yml")
        with open(pack_path, "r") as f:
            data = yaml.safe_load(f)
        scenarios = data["scenarios"]
        assert "pricing_preset_flat" in scenarios
        assert "pricing_preset_tou" in scenarios
        assert "pricing_schedule_weekday" in scenarios


class TestPricingScenarioFiles:
    """Tests for individual pricing scenario JSON files."""

    @pytest.fixture
    def scenario_ids(self):
        """Get list of pricing scenario IDs from pack."""
        pack_path = os.path.join(PACKS_DIR, "pricing.yml")
        with open(pack_path, "r") as f:
            data = yaml.safe_load(f)
        return data["scenarios"]

    def test_all_scenario_files_exist(self, scenario_ids):
        """Verify all scenario JSON files exist."""
        for scenario_id in scenario_ids:
            path = os.path.join(SCENARIOS_DIR, f"{scenario_id}.json")
            assert os.path.exists(path), f"Scenario file {scenario_id}.json should exist"

    def test_scenario_files_valid_json(self, scenario_ids):
        """Verify all scenario files are valid JSON."""
        for scenario_id in scenario_ids:
            path = os.path.join(SCENARIOS_DIR, f"{scenario_id}.json")
            with open(path, "r") as f:
                data = json.load(f)
            assert isinstance(data, dict)


class TestPresetFlatScenario:
    """Tests for pricing_preset_flat scenario."""

    @pytest.fixture
    def scenario(self):
        """Load pricing_preset_flat scenario."""
        path = os.path.join(SCENARIOS_DIR, "pricing_preset_flat.json")
        with open(path, "r") as f:
            return json.load(f)

    def test_has_scenario_id(self, scenario):
        """Verify scenario has scenario_id field."""
        assert "scenario_id" in scenario
        assert scenario["scenario_id"] == "pricing_preset_flat"

    def test_has_endpoint(self, scenario):
        """Verify scenario has endpoint field."""
        assert "endpoint" in scenario
        assert scenario["endpoint"] == "/api/bess-dispatch/pricing/preview"

    def test_has_method(self, scenario):
        """Verify scenario has method field."""
        assert "method" in scenario
        assert scenario["method"] == "POST"

    def test_has_request(self, scenario):
        """Verify scenario has request field."""
        assert "request" in scenario
        assert "tariff_preset" in scenario["request"]
        assert scenario["request"]["tariff_preset"] == "pl_flat_2026"

    def test_has_expected(self, scenario):
        """Verify scenario has expected field."""
        assert "expected" in scenario
        assert "pricing_mode" in scenario["expected"]
        assert scenario["expected"]["pricing_mode"] == "preset"


class TestPresetTouScenario:
    """Tests for pricing_preset_tou scenario."""

    @pytest.fixture
    def scenario(self):
        """Load pricing_preset_tou scenario."""
        path = os.path.join(SCENARIOS_DIR, "pricing_preset_tou.json")
        with open(path, "r") as f:
            return json.load(f)

    def test_uses_tou_preset(self, scenario):
        """Verify scenario uses ToU preset."""
        assert scenario["request"]["tariff_preset"] == "pl_tou_simple_2026"

    def test_expects_varying_prices(self, scenario):
        """Verify scenario expects varying prices."""
        assert scenario["expected"]["price_timeseries"]["has_varying_prices"] is True


class TestScheduleWeekdayScenario:
    """Tests for pricing_schedule_weekday scenario."""

    @pytest.fixture
    def scenario(self):
        """Load pricing_schedule_weekday scenario."""
        path = os.path.join(SCENARIOS_DIR, "pricing_schedule_weekday.json")
        with open(path, "r") as f:
            return json.load(f)

    def test_has_tariff_schedule(self, scenario):
        """Verify scenario has tariff_schedule in request."""
        assert "tariff_schedule" in scenario["request"]

    def test_schedule_has_24_hour_arrays(self, scenario):
        """Verify schedule has 24-hour price arrays."""
        schedule = scenario["request"]["tariff_schedule"]
        assert len(schedule["weekday_import_price_pln_per_mwh"]) == 24
        assert len(schedule["weekend_import_price_pln_per_mwh"]) == 24

    def test_expects_schedule_mode(self, scenario):
        """Verify scenario expects schedule pricing mode."""
        assert scenario["expected"]["pricing_mode"] == "schedule"


class TestScheduleHolidayScenario:
    """Tests for pricing_schedule_holiday scenario."""

    @pytest.fixture
    def scenario(self):
        """Load pricing_schedule_holiday scenario."""
        path = os.path.join(SCENARIOS_DIR, "pricing_schedule_holiday.json")
        with open(path, "r") as f:
            return json.load(f)

    def test_has_holiday_dates(self, scenario):
        """Verify scenario has holiday_dates in tariff_schedule."""
        schedule = scenario["request"]["tariff_schedule"]
        assert "holiday_dates" in schedule
        assert len(schedule["holiday_dates"]) > 0

    def test_holiday_date_format(self, scenario):
        """Verify holiday dates are in YYYY-MM-DD format."""
        schedule = scenario["request"]["tariff_schedule"]
        for date in schedule["holiday_dates"]:
            # Should be YYYY-MM-DD format
            assert len(date) == 10
            assert date[4] == "-"
            assert date[7] == "-"

    def test_expects_weekend_prices_on_holiday(self, scenario):
        """Verify scenario expects weekend prices on holiday."""
        expected = scenario["expected"]["price_timeseries"]
        assert expected["holiday_uses_weekend_prices"] is True


class TestDstSpringForwardScenario:
    """Tests for pricing_dst_spring_forward scenario."""

    @pytest.fixture
    def scenario(self):
        """Load pricing_dst_spring_forward scenario."""
        path = os.path.join(SCENARIOS_DIR, "pricing_dst_spring_forward.json")
        with open(path, "r") as f:
            return json.load(f)

    def test_uses_dst_date(self, scenario):
        """Verify scenario uses DST spring forward date."""
        assert "2025-03-30" in scenario["request"]["period_start"]

    def test_expects_no_exception(self, scenario):
        """Verify scenario expects no exception during DST."""
        expected = scenario["expected"]["price_timeseries"]
        assert expected["no_exception"] is True


class TestDstFallBackScenario:
    """Tests for pricing_dst_fall_back scenario."""

    @pytest.fixture
    def scenario(self):
        """Load pricing_dst_fall_back scenario."""
        path = os.path.join(SCENARIOS_DIR, "pricing_dst_fall_back.json")
        with open(path, "r") as f:
            return json.load(f)

    def test_uses_dst_date(self, scenario):
        """Verify scenario uses DST fall back date."""
        assert "2025-10-26" in scenario["request"]["period_start"]

    def test_expects_array_length_matches(self, scenario):
        """Verify scenario expects array length to match steps."""
        expected = scenario["expected"]["price_timeseries"]
        assert expected["array_length_matches_steps"] is True


class TestScenarioTolerances:
    """Tests for scenario tolerance configuration."""

    def test_all_scenarios_have_tolerances(self):
        """Verify all pricing scenarios have tolerances field."""
        pack_path = os.path.join(PACKS_DIR, "pricing.yml")
        with open(pack_path, "r") as f:
            data = yaml.safe_load(f)

        for scenario_id in data["scenarios"]:
            path = os.path.join(SCENARIOS_DIR, f"{scenario_id}.json")
            with open(path, "r") as f:
                scenario = json.load(f)
            assert "tolerances" in scenario, f"{scenario_id} should have tolerances"

    def test_tolerance_values_reasonable(self):
        """Verify tolerance values are within reasonable range."""
        pack_path = os.path.join(PACKS_DIR, "pricing.yml")
        with open(pack_path, "r") as f:
            data = yaml.safe_load(f)

        for scenario_id in data["scenarios"]:
            path = os.path.join(SCENARIOS_DIR, f"{scenario_id}.json")
            with open(path, "r") as f:
                scenario = json.load(f)

            tolerances = scenario["tolerances"]
            if "default_rel" in tolerances:
                assert 0 < tolerances["default_rel"] <= 0.1, \
                    f"{scenario_id} default_rel should be between 0 and 0.1"

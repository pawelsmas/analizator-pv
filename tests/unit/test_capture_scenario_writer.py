"""
Unit tests for capture_scenario.py writer functions.

Tests:
- write_scenario_folder() creates correct files
- extract_kpis_from_response() extracts expected fields
- Default tolerances are applied correctly
"""

import json
import os
import sys
import tempfile
from pathlib import Path

# Add scripts directory to path for importing
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from capture_scenario import (
    DEFAULT_TOLERANCES,
    extract_kpis_from_response,
    write_scenario_folder,
)


# -----------------------------------------------------------------------------
# Test: write_scenario_folder
# -----------------------------------------------------------------------------

class TestWriteScenarioFolder:
    """Tests for write_scenario_folder function."""

    def test_creates_folder_with_correct_name(self):
        """Scenario folder should be created with the given name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            name = "test_scenario"
            request = {"mode": "STACKED"}
            expected_kpis = {"npv_pln": 50000.0}

            result = write_scenario_folder(output_dir, name, request, expected_kpis)

            assert result.exists()
            assert result.name == name

    def test_creates_request_json(self):
        """request.json should contain the original request."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            request = {"mode": "STACKED", "load_kw": [1.0, 2.0, 3.0]}
            expected_kpis = {"npv_pln": 50000.0}

            scenario_dir = write_scenario_folder(output_dir, "test", request, expected_kpis)

            request_path = scenario_dir / "request.json"
            assert request_path.exists()

            with open(request_path) as f:
                saved_request = json.load(f)

            assert saved_request == request

    def test_creates_expected_kpis_json(self):
        """expected_kpis.json should contain the extracted KPIs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            request = {"mode": "STACKED"}
            expected_kpis = {
                "npv_pln": 50000.0,
                "payback_years": 5.2,
                "net_savings_pln": 8500.0,
            }

            scenario_dir = write_scenario_folder(output_dir, "test", request, expected_kpis)

            kpis_path = scenario_dir / "expected_kpis.json"
            assert kpis_path.exists()

            with open(kpis_path) as f:
                saved_kpis = json.load(f)

            assert saved_kpis == expected_kpis

    def test_creates_tolerances_json_with_defaults(self):
        """tolerances.json should contain default tolerances when not specified."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            request = {"mode": "STACKED"}
            expected_kpis = {"npv_pln": 50000.0}

            scenario_dir = write_scenario_folder(output_dir, "test", request, expected_kpis)

            tolerances_path = scenario_dir / "tolerances.json"
            assert tolerances_path.exists()

            with open(tolerances_path) as f:
                saved_tolerances = json.load(f)

            assert saved_tolerances["default_abs"] == DEFAULT_TOLERANCES["default_abs"]
            assert saved_tolerances["default_rel"] == DEFAULT_TOLERANCES["default_rel"]

    def test_creates_tolerances_json_with_custom(self):
        """tolerances.json should contain custom tolerances when specified."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            request = {"mode": "STACKED"}
            expected_kpis = {"npv_pln": 50000.0}
            custom_tolerances = {
                "default_abs": 10.0,
                "default_rel": 0.05,
            }

            scenario_dir = write_scenario_folder(
                output_dir, "test", request, expected_kpis, tolerances=custom_tolerances
            )

            tolerances_path = scenario_dir / "tolerances.json"
            with open(tolerances_path) as f:
                saved_tolerances = json.load(f)

            assert saved_tolerances["default_abs"] == 10.0
            assert saved_tolerances["default_rel"] == 0.05

    def test_creates_combined_scenario_json(self):
        """scenario.json should contain combined format for compatibility."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            request = {"mode": "STACKED"}
            expected_kpis = {
                "recommended_variant": "medium",  # String, should be excluded from numeric KPIs
                "npv_pln": 50000.0,
                "payback_years": 5.2,
            }

            scenario_dir = write_scenario_folder(output_dir, "my_scenario", request, expected_kpis)

            scenario_path = scenario_dir / "scenario.json"
            assert scenario_path.exists()

            with open(scenario_path) as f:
                saved_scenario = json.load(f)

            assert saved_scenario["scenario_id"] == "my_scenario"
            assert saved_scenario["request_file"] == "docs/scenarios/my_scenario/request.json"
            # Only numeric KPIs should be in combined format
            assert "npv_pln" in saved_scenario["expected_kpis"]
            assert "payback_years" in saved_scenario["expected_kpis"]
            # String values should be excluded
            assert "recommended_variant" not in saved_scenario["expected_kpis"]

    def test_creates_nested_directories(self):
        """Should create parent directories if they don't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "nested" / "path"
            request = {"mode": "STACKED"}
            expected_kpis = {"npv_pln": 50000.0}

            scenario_dir = write_scenario_folder(output_dir, "test", request, expected_kpis)

            assert scenario_dir.exists()
            assert (scenario_dir / "request.json").exists()

    def test_description_in_combined_scenario(self):
        """Description should be included in combined scenario.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            request = {"mode": "STACKED"}
            expected_kpis = {"npv_pln": 50000.0}

            scenario_dir = write_scenario_folder(
                output_dir, "test", request, expected_kpis,
                description="My custom description"
            )

            with open(scenario_dir / "scenario.json") as f:
                saved_scenario = json.load(f)

            assert saved_scenario["description"] == "My custom description"


# -----------------------------------------------------------------------------
# Test: extract_kpis_from_response
# -----------------------------------------------------------------------------

class TestExtractKpisFromResponse:
    """Tests for extract_kpis_from_response function."""

    def test_extracts_recommended_variant(self):
        """Should extract recommended_variant from response."""
        response = {
            "recommended_variant": "medium",
            "variants": [
                {"variant": "medium", "npv_pln": 50000.0}
            ],
        }

        kpis = extract_kpis_from_response(response)

        assert kpis["recommended_variant"] == "medium"

    def test_extracts_npv_from_finance_summary(self):
        """Should extract npv_pln from finance_summary."""
        response = {
            "recommended_variant": "medium",
            "variants": [
                {
                    "variant": "medium",
                    "finance_summary": {"npv_pln": 50000.0, "payback_years": 5.2},
                }
            ],
        }

        kpis = extract_kpis_from_response(response)

        assert kpis["npv_pln"] == 50000.0
        assert kpis["payback_years"] == 5.2

    def test_extracts_savings_breakdown(self):
        """Should extract savings breakdown components."""
        response = {
            "recommended_variant": "medium",
            "variants": [
                {
                    "variant": "medium",
                    "savings_breakdown": {
                        "net_savings_pln": 8500.0,
                        "energy_savings_pln": 10000.0,
                        "degradation_cost_pln": 1500.0,
                    },
                }
            ],
        }

        kpis = extract_kpis_from_response(response)

        assert kpis["net_savings_pln"] == 8500.0
        assert kpis["energy_savings_pln"] == 10000.0
        assert kpis["degradation_cost_pln"] == 1500.0

    def test_extracts_energy_flows(self):
        """Should extract energy flow totals from dispatch_summary."""
        response = {
            "recommended_variant": "medium",
            "variants": [
                {
                    "variant": "medium",
                    "dispatch_summary": {
                        "energy_flows": {
                            "totals_mwh": {
                                "grid_import_mwh": 100.0,
                                "grid_export_mwh": 20.0,
                                "pv_curtail_mwh": 5.0,
                            }
                        }
                    },
                }
            ],
        }

        kpis = extract_kpis_from_response(response)

        assert kpis["grid_import_mwh"] == 100.0
        assert kpis["grid_export_mwh"] == 20.0
        assert kpis["pv_curtail_mwh"] == 5.0

    def test_extracts_unserved_load_from_constraint_summary(self):
        """Should extract unserved_load_kwh from constraint_summary."""
        response = {
            "recommended_variant": "medium",
            "variants": [
                {
                    "variant": "medium",
                    "dispatch_summary": {
                        "constraint_summary": {
                            "unserved_load_kwh": 150.0,
                        }
                    },
                }
            ],
        }

        kpis = extract_kpis_from_response(response)

        assert kpis["unserved_load_kwh"] == 150.0

    def test_handles_missing_recommended_variant(self):
        """Should fall back to first variant if recommended not found."""
        response = {
            "recommended_variant": "unknown",
            "variants": [
                {
                    "variant": "small",
                    "npv_pln": 30000.0,
                }
            ],
        }

        kpis = extract_kpis_from_response(response)

        # Should use first variant
        assert "npv_pln" in kpis

    def test_handles_empty_response(self):
        """Should return minimal KPIs for empty response."""
        response = {
            "variants": [],
        }

        kpis = extract_kpis_from_response(response)

        assert kpis["recommended_variant"] == "unknown"

    def test_extracts_objective_used(self):
        """Should extract objective_used if present."""
        response = {
            "recommended_variant": "medium",
            "objective_used": "npv",
            "variants": [
                {"variant": "medium", "npv_pln": 50000.0}
            ],
        }

        kpis = extract_kpis_from_response(response)

        assert kpis["objective_used"] == "npv"


# -----------------------------------------------------------------------------
# Test: Default tolerances
# -----------------------------------------------------------------------------

class TestDefaultTolerances:
    """Tests for default tolerance values."""

    def test_default_abs_is_reasonable(self):
        """Default absolute tolerance should be 1.0 PLN."""
        assert DEFAULT_TOLERANCES["default_abs"] == 1.0

    def test_default_rel_is_reasonable(self):
        """Default relative tolerance should be 1% (0.01)."""
        assert DEFAULT_TOLERANCES["default_rel"] == 0.01

    def test_payback_has_special_tolerance(self):
        """Payback years should have per-field absolute tolerance."""
        assert "payback_years" in DEFAULT_TOLERANCES["per_field_abs"]
        assert DEFAULT_TOLERANCES["per_field_abs"]["payback_years"] == 0.05

    def test_irr_has_special_tolerance(self):
        """IRR should have per-field absolute tolerance."""
        assert "irr_pct" in DEFAULT_TOLERANCES["per_field_abs"]
        assert DEFAULT_TOLERANCES["per_field_abs"]["irr_pct"] == 0.5

    def test_throughput_has_special_tolerance(self):
        """Battery throughput should have per-field absolute tolerance."""
        assert "battery_throughput_mwh" in DEFAULT_TOLERANCES["per_field_abs"]
        assert DEFAULT_TOLERANCES["per_field_abs"]["battery_throughput_mwh"] == 0.001

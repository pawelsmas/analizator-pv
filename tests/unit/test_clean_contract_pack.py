"""
Unit tests for clean contract pack (v2.8.0 PR6).

Tests verify:
- Clean contract pack exists and is valid
- Pack configuration is correct
- Deprecated fields are properly specified
"""

import pytest
import yaml
from pathlib import Path


# Path to scenario packs
PACKS_PATH = Path(__file__).parent.parent.parent / "docs" / "scenarios" / "packs"


class TestCleanContractPackExists:
    """Tests for clean contract pack existence."""

    def test_pack_file_exists(self):
        """clean_contract.yml should exist."""
        pack_file = PACKS_PATH / "clean_contract.yml"
        assert pack_file.exists()

    def test_pack_is_valid_yaml(self):
        """clean_contract.yml should be valid YAML."""
        pack_file = PACKS_PATH / "clean_contract.yml"
        with open(pack_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)


class TestCleanContractPackConfig:
    """Tests for clean contract pack configuration."""

    def test_has_name(self):
        """Pack should have a name."""
        pack_file = PACKS_PATH / "clean_contract.yml"
        with open(pack_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert "name" in data
        assert data["name"] == "clean_contract"

    def test_has_version(self):
        """Pack should have a version."""
        pack_file = PACKS_PATH / "clean_contract.yml"
        with open(pack_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert "version" in data
        assert data["version"] == "2.8.0"

    def test_has_scenarios(self):
        """Pack should have scenarios."""
        pack_file = PACKS_PATH / "clean_contract.yml"
        with open(pack_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert "scenarios" in data
        assert len(data["scenarios"]) >= 1


class TestCleanContractPackValidation:
    """Tests for clean contract pack validation rules."""

    def test_has_validation_section(self):
        """Pack should have validation section."""
        pack_file = PACKS_PATH / "clean_contract.yml"
        with open(pack_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert "validation" in data

    def test_specifies_deprecated_fields(self):
        """Pack should specify deprecated response fields."""
        pack_file = PACKS_PATH / "clean_contract.yml"
        with open(pack_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        validation = data.get("validation", {})
        assert "deprecated_response_fields" in validation
        assert len(validation["deprecated_response_fields"]) >= 1

    def test_export_revenue_pln_is_deprecated(self):
        """export_revenue_pln should be in deprecated fields."""
        pack_file = PACKS_PATH / "clean_contract.yml"
        with open(pack_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        deprecated = data["validation"]["deprecated_response_fields"]
        assert "export_revenue_pln" in deprecated

    def test_specifies_required_clean_fields(self):
        """Pack should specify required clean fields."""
        pack_file = PACKS_PATH / "clean_contract.yml"
        with open(pack_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        validation = data.get("validation", {})
        assert "required_clean_fields" in validation
        assert len(validation["required_clean_fields"]) >= 1

    def test_export_savings_pln_is_required(self):
        """export_savings_pln should be in required clean fields."""
        pack_file = PACKS_PATH / "clean_contract.yml"
        with open(pack_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        required = data["validation"]["required_clean_fields"]
        assert "export_savings_pln" in required


class TestCleanContractPackScenarios:
    """Tests for clean contract pack scenarios."""

    def test_includes_baseline_scenarios(self):
        """Pack should include baseline scenarios."""
        pack_file = PACKS_PATH / "clean_contract.yml"
        with open(pack_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        scenarios = data["scenarios"]
        # Get scenario names (handle both string and dict format)
        scenario_names = []
        for s in scenarios:
            if isinstance(s, str):
                scenario_names.append(s)
            elif isinstance(s, dict):
                scenario_names.extend(s.keys())
        assert "baseline_stacked_no_arb" in scenario_names


class TestAllPacksValid:
    """Tests that all scenario packs are valid."""

    def test_baseline_pack_exists(self):
        """baseline.yml should exist."""
        assert (PACKS_PATH / "baseline.yml").exists()

    def test_clean_contract_pack_exists(self):
        """clean_contract.yml should exist."""
        assert (PACKS_PATH / "clean_contract.yml").exists()

    def test_all_packs_valid_yaml(self):
        """All .yml files in packs directory should be valid YAML."""
        for pack_file in PACKS_PATH.glob("*.yml"):
            with open(pack_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            assert isinstance(data, dict), f"{pack_file.name} is not a valid pack"
            assert "name" in data, f"{pack_file.name} missing 'name'"

"""
Unit tests for scenario updates check script (v2.6.0 PR2).

Tests verify:
- Protected file detection rules
- Approval file detection
- Different file types correctly categorized
"""

import sys

import pytest

sys.path.insert(0, "scripts")

from check_scenario_updates import (
    is_scenario_request_file,
    is_scenario_tolerances_file,
    is_pack_file,
    detect_protected_files,
    has_approval_update,
)


class TestIsScenarioRequestFile:
    """Tests for is_scenario_request_file function."""

    def test_scenario_request_json_is_protected(self):
        """request.json in scenarios dir should be protected."""
        assert is_scenario_request_file("docs/scenarios/basic/request.json") is True

    def test_nested_scenario_request_json_is_protected(self):
        """Nested request.json should be protected."""
        assert is_scenario_request_file("docs/scenarios/pv_surplus/basic/request.json") is True

    def test_request_json_outside_scenarios_not_protected(self):
        """request.json outside scenarios should not be protected."""
        assert is_scenario_request_file("src/request.json") is False
        assert is_scenario_request_file("tests/request.json") is False

    def test_other_json_not_protected(self):
        """Other JSON files should not be protected as request files."""
        assert is_scenario_request_file("docs/scenarios/basic/expected_kpis.json") is False
        assert is_scenario_request_file("docs/scenarios/basic/response.json") is False


class TestIsScenarioTolerancesFile:
    """Tests for is_scenario_tolerances_file function."""

    def test_tolerances_json_is_protected(self):
        """tolerances.json in scenarios dir should be protected."""
        assert is_scenario_tolerances_file("docs/scenarios/basic/tolerances.json") is True

    def test_nested_tolerances_json_is_protected(self):
        """Nested tolerances.json should be protected."""
        assert is_scenario_tolerances_file("docs/scenarios/pv_surplus/basic/tolerances.json") is True

    def test_tolerances_outside_scenarios_not_protected(self):
        """tolerances.json outside scenarios should not be protected."""
        assert is_scenario_tolerances_file("src/tolerances.json") is False

    def test_other_json_not_protected(self):
        """Other JSON files should not be protected as tolerances files."""
        assert is_scenario_tolerances_file("docs/scenarios/basic/request.json") is False


class TestIsPackFile:
    """Tests for is_pack_file function."""

    def test_pack_yml_is_protected(self):
        """Pack YAML files should be protected."""
        assert is_pack_file("docs/scenarios/packs/baseline.yml") is True
        assert is_pack_file("docs/scenarios/packs/pricing.yml") is True

    def test_pack_yaml_not_protected(self):
        """.yaml extension should not match (only .yml)."""
        assert is_pack_file("docs/scenarios/packs/baseline.yaml") is False

    def test_yml_outside_packs_not_protected(self):
        """YAML outside packs dir should not be protected."""
        assert is_pack_file("docs/scenarios/basic/config.yml") is False
        assert is_pack_file(".github/workflows/tests.yml") is False


class TestDetectProtectedFiles:
    """Tests for detect_protected_files function."""

    def test_empty_list_returns_empty(self):
        """Empty file list should return empty."""
        assert detect_protected_files([]) == []

    def test_filters_protected_files(self):
        """Should filter to only protected files."""
        files = [
            "docs/scenarios/basic/request.json",
            "docs/scenarios/basic/expected_kpis.json",
            "src/main.py",
            "docs/scenarios/packs/baseline.yml",
            "README.md",
        ]
        protected = detect_protected_files(files)
        assert len(protected) == 2
        assert "docs/scenarios/basic/request.json" in protected
        assert "docs/scenarios/packs/baseline.yml" in protected

    def test_includes_tolerances(self):
        """Should include tolerances.json files."""
        files = [
            "docs/scenarios/basic/tolerances.json",
        ]
        protected = detect_protected_files(files)
        assert len(protected) == 1

    def test_no_protected_files(self):
        """Should return empty if no protected files."""
        files = [
            "src/main.py",
            "tests/test_foo.py",
            "README.md",
        ]
        assert detect_protected_files(files) == []


class TestHasApprovalUpdate:
    """Tests for has_approval_update function."""

    def test_approval_md_is_detected(self):
        """APPROVAL.md in correct location should be detected."""
        files = [
            "docs/scenario_updates/APPROVAL.md",
            "src/main.py",
        ]
        assert has_approval_update(files) is True

    def test_no_approval_file(self):
        """Should return False if no approval file."""
        files = [
            "src/main.py",
            "docs/scenarios/basic/request.json",
        ]
        assert has_approval_update(files) is False

    def test_wrong_approval_file_not_detected(self):
        """Wrong APPROVAL.md location should not be detected."""
        files = [
            "docs/expected_updates/APPROVAL.md",  # Wrong dir
        ]
        assert has_approval_update(files) is False


class TestIntegration:
    """Integration tests for the check script."""

    def test_protected_without_approval_detected(self):
        """Protected files without approval should be detected."""
        files = [
            "docs/scenarios/basic/request.json",
        ]
        protected = detect_protected_files(files)
        has_approval = has_approval_update(files)

        assert len(protected) > 0
        assert has_approval is False

    def test_protected_with_approval_ok(self):
        """Protected files with approval should be OK."""
        files = [
            "docs/scenarios/basic/request.json",
            "docs/scenario_updates/APPROVAL.md",
        ]
        protected = detect_protected_files(files)
        has_approval = has_approval_update(files)

        assert len(protected) > 0
        assert has_approval is True

    def test_no_protected_files_ok(self):
        """No protected files should be OK regardless of approval."""
        files = [
            "src/main.py",
            "tests/test_foo.py",
        ]
        protected = detect_protected_files(files)

        assert len(protected) == 0

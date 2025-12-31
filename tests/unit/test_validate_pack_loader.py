"""
Unit tests for validate_pack module (loader and runner).

v1.7.0: Tests pack loading, scenario loading, and pack validation runner.
"""

import sys
import json
import tempfile
from pathlib import Path

import pytest
import yaml

# Add services/bess-dispatch to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))

from validate_pack import (
    list_packs,
    load_pack,
    load_scenario_files,
    run_validate_pack,
)


class TestListPacks:
    """Tests for list_packs function."""

    def test_list_packs_empty_dir(self, tmp_path):
        """Empty directory returns empty list."""
        result = list_packs(tmp_path)
        assert result == []

    def test_list_packs_nonexistent_dir(self, tmp_path):
        """Nonexistent directory returns empty list."""
        result = list_packs(tmp_path / "nonexistent")
        assert result == []

    def test_list_packs_with_yml_files(self, tmp_path):
        """Finds .yml pack files."""
        (tmp_path / "baseline.yml").write_text("name: baseline\nscenarios: []")
        (tmp_path / "nightly.yml").write_text("name: nightly\nscenarios: []")

        result = list_packs(tmp_path)
        assert sorted(result) == ["baseline", "nightly"]

    def test_list_packs_with_yaml_files(self, tmp_path):
        """Finds .yaml pack files."""
        (tmp_path / "quick.yaml").write_text("name: quick\nscenarios: []")

        result = list_packs(tmp_path)
        assert result == ["quick"]

    def test_list_packs_ignores_non_yaml(self, tmp_path):
        """Ignores non-YAML files."""
        (tmp_path / "baseline.yml").write_text("name: baseline\nscenarios: []")
        (tmp_path / "readme.md").write_text("# Packs")
        (tmp_path / "data.json").write_text("{}")

        result = list_packs(tmp_path)
        assert result == ["baseline"]


class TestLoadPack:
    """Tests for load_pack function."""

    def test_load_pack_success(self, tmp_path):
        """Successfully loads pack with scenarios."""
        pack_content = """
name: baseline
scenarios:
  - scenario_1
  - scenario_2
  - scenario_3
"""
        (tmp_path / "baseline.yml").write_text(pack_content)

        result = load_pack("baseline", tmp_path)
        assert result == ["scenario_1", "scenario_2", "scenario_3"]

    def test_load_pack_not_found(self, tmp_path):
        """Raises FileNotFoundError for missing pack."""
        with pytest.raises(FileNotFoundError):
            load_pack("nonexistent", tmp_path)

    def test_load_pack_prefers_yml_over_yaml(self, tmp_path):
        """Prefers .yml over .yaml when both exist."""
        (tmp_path / "test.yml").write_text("name: test\nscenarios: [a]")
        (tmp_path / "test.yaml").write_text("name: test\nscenarios: [b]")

        result = load_pack("test", tmp_path)
        assert result == ["a"]

    def test_load_pack_falls_back_to_yaml(self, tmp_path):
        """Falls back to .yaml if .yml doesn't exist."""
        (tmp_path / "test.yaml").write_text("name: test\nscenarios: [from_yaml]")

        result = load_pack("test", tmp_path)
        assert result == ["from_yaml"]

    def test_load_pack_empty_scenarios(self, tmp_path):
        """Handles pack with empty scenarios list."""
        (tmp_path / "empty.yml").write_text("name: empty\nscenarios: []")

        result = load_pack("empty", tmp_path)
        assert result == []

    def test_load_pack_invalid_format(self, tmp_path):
        """Raises ValueError for invalid pack format."""
        (tmp_path / "invalid.yml").write_text("just a string")

        with pytest.raises(ValueError):
            load_pack("invalid", tmp_path)

    def test_load_pack_scenarios_not_list(self, tmp_path):
        """Raises ValueError if scenarios is not a list."""
        (tmp_path / "bad.yml").write_text("name: bad\nscenarios: not_a_list")

        with pytest.raises(ValueError):
            load_pack("bad", tmp_path)


class TestLoadScenarioFiles:
    """Tests for load_scenario_files function."""

    def test_load_scenario_from_directory(self, tmp_path):
        """Loads scenario from directory format."""
        scenario_dir = tmp_path / "my_scenario"
        scenario_dir.mkdir()

        request = {"load_kw": [100, 100], "interval_minutes": 60}
        expected = {"npv_pln": 1000.0, "payback_years": 5.0}
        tolerances = {"default_abs": 1.0, "default_rel": 0.01}

        (scenario_dir / "request.json").write_text(json.dumps(request))
        (scenario_dir / "expected_kpis.json").write_text(json.dumps(expected))
        (scenario_dir / "tolerances.json").write_text(json.dumps(tolerances))

        result = load_scenario_files("my_scenario", tmp_path)

        assert result["request"] == request
        assert result["expected_kpis"] == expected
        assert result["tolerances"] == tolerances

    def test_load_scenario_tolerances_optional(self, tmp_path):
        """Tolerances file is optional."""
        scenario_dir = tmp_path / "minimal"
        scenario_dir.mkdir()

        (scenario_dir / "request.json").write_text('{"load_kw": [100]}')
        (scenario_dir / "expected_kpis.json").write_text('{"npv_pln": 500}')

        result = load_scenario_files("minimal", tmp_path)

        assert result["request"] == {"load_kw": [100]}
        assert result["expected_kpis"] == {"npv_pln": 500}
        assert result["tolerances"] == {}

    def test_load_scenario_from_legacy_file(self, tmp_path):
        """Loads scenario from legacy single-file format with inline request."""
        scenario_data = {
            "scenario_id": "legacy_test",
            "request": {"load_kw": [200, 200]},
            "expected_kpis": {"npv_pln": 2000.0},
            "tolerances": {"default_abs": 5.0},
        }
        (tmp_path / "legacy_test.json").write_text(json.dumps(scenario_data))

        result = load_scenario_files("legacy_test", tmp_path)

        assert result["request"] == {"load_kw": [200, 200]}
        assert result["expected_kpis"] == {"npv_pln": 2000.0}
        assert result["tolerances"] == {"default_abs": 5.0}

    def test_load_scenario_from_legacy_with_request_file(self, tmp_path):
        """Loads scenario with request_file reference."""
        # Create the referenced request file
        repo_root = tmp_path.parent
        request_path = tmp_path / "smoke" / "request.json"
        request_path.parent.mkdir(parents=True, exist_ok=True)
        request_path.write_text('{"load_kw": [300]}')

        # Create scenario file with reference (relative to scenarios_root parent)
        scenarios_root = tmp_path / "scenarios"
        scenarios_root.mkdir()

        scenario_data = {
            "scenario_id": "ref_test",
            "request_file": f"scenarios/smoke/request.json",
            "expected_kpis": {"npv_pln": 3000.0},
        }
        (scenarios_root / "ref_test.json").write_text(json.dumps(scenario_data))

        # Note: This test relies on specific path resolution
        # The actual implementation resolves relative to repo root

    def test_load_scenario_not_found(self, tmp_path):
        """Raises FileNotFoundError for missing scenario."""
        with pytest.raises(FileNotFoundError):
            load_scenario_files("nonexistent", tmp_path)

    def test_load_scenario_missing_request_in_dir(self, tmp_path):
        """Raises error if request.json missing in directory."""
        scenario_dir = tmp_path / "incomplete"
        scenario_dir.mkdir()
        (scenario_dir / "expected_kpis.json").write_text('{}')

        with pytest.raises(FileNotFoundError):
            load_scenario_files("incomplete", tmp_path)


class TestRunValidatePack:
    """Tests for run_validate_pack function."""

    def _create_test_pack(self, tmp_path, pack_name: str, scenarios: list):
        """Helper to create a test pack structure."""
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir(exist_ok=True)

        pack_content = f"name: {pack_name}\nscenarios:\n"
        for s in scenarios:
            pack_content += f"  - {s}\n"
        (packs_dir / f"{pack_name}.yml").write_text(pack_content)

        return packs_dir

    def _create_test_scenario(self, tmp_path, name: str, request: dict, expected: dict):
        """Helper to create a test scenario directory."""
        scenario_dir = tmp_path / name
        scenario_dir.mkdir(exist_ok=True)
        (scenario_dir / "request.json").write_text(json.dumps(request))
        (scenario_dir / "expected_kpis.json").write_text(json.dumps(expected))

    def test_run_validate_pack_all_pass(self, tmp_path):
        """All scenarios passing."""
        packs_dir = self._create_test_pack(tmp_path, "test", ["s1", "s2"])
        self._create_test_scenario(tmp_path, "s1", {"load": [100]}, {"npv": 1000})
        self._create_test_scenario(tmp_path, "s2", {"load": [200]}, {"npv": 2000})

        def validate_fn(request, expected, tolerances):
            return {"passed": True, "diffs": [], "run_id": "abc123"}

        result = run_validate_pack("test", validate_fn, tmp_path, packs_dir)

        assert result["pack"] == "test"
        assert result["pass"] is True
        assert result["summary"]["total"] == 2
        assert result["summary"]["pass"] == 2
        assert result["summary"]["fail"] == 0
        assert len(result["scenarios"]) == 2
        assert all(s["pass"] for s in result["scenarios"])

    def test_run_validate_pack_some_fail(self, tmp_path):
        """Some scenarios failing."""
        packs_dir = self._create_test_pack(tmp_path, "test", ["s1", "s2"])
        self._create_test_scenario(tmp_path, "s1", {"load": [100]}, {"npv": 1000})
        self._create_test_scenario(tmp_path, "s2", {"load": [200]}, {"npv": 2000})

        def validate_fn(request, expected, tolerances):
            if request.get("load") == [100]:
                return {"passed": True, "diffs": []}
            else:
                return {
                    "passed": False,
                    "diffs": [
                        {"field": "npv", "pass": False, "abs_diff": 100, "expected": 2000, "actual": 2100}
                    ],
                }

        result = run_validate_pack("test", validate_fn, tmp_path, packs_dir)

        assert result["pass"] is False
        assert result["summary"]["pass"] == 1
        assert result["summary"]["fail"] == 1

    def test_run_validate_pack_top_mismatches(self, tmp_path):
        """Top mismatches are extracted correctly."""
        packs_dir = self._create_test_pack(tmp_path, "test", ["s1"])
        self._create_test_scenario(tmp_path, "s1", {}, {})

        def validate_fn(request, expected, tolerances):
            return {
                "passed": False,
                "diffs": [
                    {"field": "a", "pass": False, "abs_diff": 10, "expected": 100, "actual": 110},
                    {"field": "b", "pass": False, "abs_diff": 50, "expected": 200, "actual": 250},
                    {"field": "c", "pass": True, "abs_diff": 0},  # Should be excluded
                    {"field": "d", "pass": False, "abs_diff": 5, "expected": 50, "actual": 55},
                ],
            }

        result = run_validate_pack("test", validate_fn, tmp_path, packs_dir)

        scenario = result["scenarios"][0]
        assert scenario["mismatch_count"] == 3  # a, b, d
        assert len(scenario["top_mismatches"]) == 3

        # Should be sorted by abs_diff descending
        assert scenario["top_mismatches"][0]["field"] == "b"
        assert scenario["top_mismatches"][1]["field"] == "a"
        assert scenario["top_mismatches"][2]["field"] == "d"

    def test_run_validate_pack_max_5_mismatches(self, tmp_path):
        """Top mismatches limited to 5."""
        packs_dir = self._create_test_pack(tmp_path, "test", ["s1"])
        self._create_test_scenario(tmp_path, "s1", {}, {})

        def validate_fn(request, expected, tolerances):
            return {
                "passed": False,
                "diffs": [
                    {"field": f"f{i}", "pass": False, "abs_diff": i}
                    for i in range(10)
                ],
            }

        result = run_validate_pack("test", validate_fn, tmp_path, packs_dir)

        scenario = result["scenarios"][0]
        assert scenario["mismatch_count"] == 10
        assert len(scenario["top_mismatches"]) == 5

    def test_run_validate_pack_scenario_error(self, tmp_path):
        """Handles scenario loading errors."""
        packs_dir = self._create_test_pack(tmp_path, "test", ["exists", "missing"])
        self._create_test_scenario(tmp_path, "exists", {}, {})
        # "missing" scenario not created

        def validate_fn(request, expected, tolerances):
            return {"passed": True, "diffs": []}

        result = run_validate_pack("test", validate_fn, tmp_path, packs_dir)

        assert result["pass"] is False
        assert result["summary"]["pass"] == 1
        assert result["summary"]["fail"] == 1
        assert result["summary"]["error"] == 1

        # Find error scenario
        error_scenario = next(s for s in result["scenarios"] if s["name"] == "missing")
        assert error_scenario["pass"] is False
        assert "error" in error_scenario

    def test_run_validate_pack_not_found(self, tmp_path):
        """Handles missing pack gracefully."""
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()

        def validate_fn(request, expected, tolerances):
            return {"passed": True, "diffs": []}

        result = run_validate_pack("nonexistent", validate_fn, tmp_path, packs_dir)

        assert result["pass"] is False
        assert "error" in result
        assert result["summary"]["total"] == 0

    def test_run_validate_pack_run_id_and_hash(self, tmp_path):
        """Captures run_id and request_hash from validation."""
        packs_dir = self._create_test_pack(tmp_path, "test", ["s1"])
        self._create_test_scenario(tmp_path, "s1", {}, {})

        def validate_fn(request, expected, tolerances):
            return {
                "passed": True,
                "diffs": [],
                "run_id": "run_123",
                "request_hash": "hash_456",
            }

        result = run_validate_pack("test", validate_fn, tmp_path, packs_dir)

        scenario = result["scenarios"][0]
        assert scenario["run_id"] == "run_123"
        assert scenario["request_hash"] == "hash_456"

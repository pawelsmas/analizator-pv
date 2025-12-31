"""
Unit tests for scenario pack parser.

Tests the YAML pack loading and scenario ID extraction without requiring
the API or actual scenario files.
"""

import sys
import tempfile
from pathlib import Path

import pytest

# Add scripts to path for import
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from validate_scenarios import load_pack, parse_pack_scenarios


class TestLoadPack:
    """Tests for load_pack function."""

    def test_load_pack_valid_yaml(self, tmp_path: Path):
        """Test loading a valid pack YAML file."""
        pack_file = tmp_path / "test_pack.yml"
        pack_file.write_text("""
name: test_pack
scenarios:
  - scenario_a
  - scenario_b
  - scenario_c
""")
        result = load_pack(pack_file)
        assert result["name"] == "test_pack"
        assert result["scenarios"] == ["scenario_a", "scenario_b", "scenario_c"]

    def test_load_pack_with_comments(self, tmp_path: Path):
        """Test loading pack with YAML comments."""
        pack_file = tmp_path / "commented.yml"
        pack_file.write_text("""
# This is a baseline pack
name: baseline
# Core scenarios for release validation
scenarios:
  - core_1  # Critical path
  - core_2
""")
        result = load_pack(pack_file)
        assert result["name"] == "baseline"
        assert len(result["scenarios"]) == 2

    def test_load_pack_empty_scenarios(self, tmp_path: Path):
        """Test loading pack with empty scenarios list."""
        pack_file = tmp_path / "empty.yml"
        pack_file.write_text("""
name: empty_pack
scenarios: []
""")
        result = load_pack(pack_file)
        assert result["name"] == "empty_pack"
        assert result["scenarios"] == []

    def test_load_pack_file_not_found(self, tmp_path: Path):
        """Test error when pack file doesn't exist."""
        missing_file = tmp_path / "missing.yml"
        with pytest.raises(FileNotFoundError):
            load_pack(missing_file)


class TestParsePackScenarios:
    """Tests for parse_pack_scenarios function."""

    def test_parse_scenarios_list(self):
        """Test extracting scenarios from pack data."""
        pack_data = {
            "name": "test",
            "scenarios": ["s1", "s2", "s3"]
        }
        result = parse_pack_scenarios(pack_data)
        assert result == ["s1", "s2", "s3"]

    def test_parse_preserves_order(self):
        """Test that scenario order is preserved."""
        pack_data = {
            "name": "ordered",
            "scenarios": ["z_last", "a_first", "m_middle"]
        }
        result = parse_pack_scenarios(pack_data)
        assert result == ["z_last", "a_first", "m_middle"]

    def test_parse_missing_scenarios_key(self):
        """Test handling of missing scenarios key."""
        pack_data = {"name": "no_scenarios"}
        result = parse_pack_scenarios(pack_data)
        assert result == []

    def test_parse_none_scenarios(self):
        """Test handling of None scenarios value."""
        pack_data = {"name": "null", "scenarios": None}
        result = parse_pack_scenarios(pack_data)
        # get() returns None, which should be handled
        assert result is None or result == []


class TestBaselinePackFormat:
    """Integration test for the actual baseline.yml format."""

    def test_baseline_pack_structure(self):
        """Test that baseline.yml can be loaded and has expected structure."""
        baseline_path = Path(__file__).parent.parent.parent / "docs" / "scenarios" / "packs" / "baseline.yml"

        if not baseline_path.exists():
            pytest.skip("baseline.yml not found")

        pack_data = load_pack(baseline_path)

        # Must have a name
        assert "name" in pack_data
        assert pack_data["name"] == "baseline"

        # Must have scenarios list
        assert "scenarios" in pack_data
        assert isinstance(pack_data["scenarios"], list)

        # Scenarios must be non-empty strings
        for scenario_id in pack_data["scenarios"]:
            assert isinstance(scenario_id, str)
            assert len(scenario_id) > 0

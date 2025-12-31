"""
Unit tests for validate_pack ledger_diffs functionality (v1.9.0).

Tests verify:
- compute_ledger_diffs produces correct category-level diffs
- ScenarioResult includes ledger_diffs field
- Empty ledger_diffs when no money_ledger present
"""

import pytest
import sys
import os

# Add services/bess-dispatch to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "bess-dispatch"))

from validate_pack import (
    compute_ledger_diffs,
    ScenarioResult,
    LedgerCategoryDiff,
    _scenario_result_to_dict,
)


class TestComputeLedgerDiffs:
    """Tests for compute_ledger_diffs function."""

    def test_returns_empty_list_when_expected_is_none(self):
        """Should return empty list when expected_ledger is None."""
        actual = {"delta_annual_pln": {"total_cost_pln": 1000.0}}
        result = compute_ledger_diffs(None, actual)
        assert result == []

    def test_returns_empty_list_when_actual_is_none(self):
        """Should return empty list when actual_ledger is None."""
        expected = {"delta_annual_pln": {"total_cost_pln": 1000.0}}
        result = compute_ledger_diffs(expected, None)
        assert result == []

    def test_returns_empty_list_when_both_none(self):
        """Should return empty list when both are None."""
        result = compute_ledger_diffs(None, None)
        assert result == []

    def test_returns_empty_list_when_no_differences(self):
        """Should return empty list when values match (within tolerance)."""
        expected = {
            "baseline_annual": {"total_cost_pln": 1000.0},
            "project_annual": {"total_cost_pln": 500.0},
            "delta_annual_pln": {"total_cost_pln": 500.0},
        }
        actual = {
            "baseline_annual": {"total_cost_pln": 1000.0},
            "project_annual": {"total_cost_pln": 500.0},
            "delta_annual_pln": {"total_cost_pln": 500.0},
        }
        result = compute_ledger_diffs(expected, actual)
        assert result == []

    def test_returns_diffs_when_values_differ(self):
        """Should return diffs when values differ beyond tolerance."""
        expected = {
            "baseline_annual": {"total_cost_pln": 1000.0},
            "project_annual": {"total_cost_pln": 500.0},
            "delta_annual_pln": {"total_cost_pln": 500.0},
        }
        actual = {
            "baseline_annual": {"total_cost_pln": 1000.0},
            "project_annual": {"total_cost_pln": 600.0},
            "delta_annual_pln": {"total_cost_pln": 400.0},  # Diff = 100
        }
        result = compute_ledger_diffs(expected, actual)

        assert len(result) == 1
        assert result[0]["category"] == "total_cost_pln"
        assert result[0]["delta_expected"] == 500.0
        assert result[0]["delta_actual"] == 400.0
        assert result[0]["diff_pln"] == 100.0

    def test_includes_all_diff_categories(self):
        """Should include all categories with differences."""
        expected = {
            "baseline_annual": {
                "import_energy_cost_pln": 800.0,
                "export_revenue_pln": 100.0,
            },
            "project_annual": {
                "import_energy_cost_pln": 400.0,
                "export_revenue_pln": 200.0,
            },
            "delta_annual_pln": {
                "import_energy_cost_pln": 400.0,
                "export_revenue_pln": 100.0,
            },
        }
        actual = {
            "baseline_annual": {
                "import_energy_cost_pln": 800.0,
                "export_revenue_pln": 100.0,
            },
            "project_annual": {
                "import_energy_cost_pln": 300.0,  # Different
                "export_revenue_pln": 250.0,  # Different
            },
            "delta_annual_pln": {
                "import_energy_cost_pln": 500.0,  # Diff = -100
                "export_revenue_pln": 150.0,  # Diff = -50
            },
        }
        result = compute_ledger_diffs(expected, actual)

        assert len(result) == 2
        categories = [d["category"] for d in result]
        assert "import_energy_cost_pln" in categories
        assert "export_revenue_pln" in categories

    def test_sorted_by_absolute_diff(self):
        """Should sort diffs by absolute difference (largest first)."""
        expected = {
            "delta_annual_pln": {
                "import_energy_cost_pln": 100.0,
                "export_revenue_pln": 200.0,
            },
        }
        actual = {
            "delta_annual_pln": {
                "import_energy_cost_pln": 50.0,   # Diff = 50
                "export_revenue_pln": 0.0,  # Diff = 200
            },
        }
        result = compute_ledger_diffs(expected, actual)

        # export_revenue_pln has larger diff, should be first
        assert result[0]["category"] == "export_revenue_pln"
        assert result[1]["category"] == "import_energy_cost_pln"


class TestScenarioResultWithLedgerDiffs:
    """Tests for ScenarioResult with ledger_diffs."""

    def test_scenario_result_has_ledger_diffs_field(self):
        """ScenarioResult should have ledger_diffs field."""
        result = ScenarioResult(
            name="test",
            passed=True,
            ledger_diffs=[{"category": "total_cost_pln", "diff_pln": 100}],
        )
        assert result.ledger_diffs == [{"category": "total_cost_pln", "diff_pln": 100}]

    def test_scenario_result_default_empty_ledger_diffs(self):
        """ScenarioResult should default to empty ledger_diffs."""
        result = ScenarioResult(
            name="test",
            passed=True,
        )
        assert result.ledger_diffs == []

    def test_scenario_result_to_dict_includes_ledger_diffs(self):
        """_scenario_result_to_dict should include ledger_diffs when present."""
        result = ScenarioResult(
            name="test",
            passed=True,
            ledger_diffs=[{"category": "total_cost_pln", "diff_pln": 100}],
        )
        d = _scenario_result_to_dict(result)
        assert "ledger_diffs" in d
        assert d["ledger_diffs"] == [{"category": "total_cost_pln", "diff_pln": 100}]

    def test_scenario_result_to_dict_omits_empty_ledger_diffs(self):
        """_scenario_result_to_dict should omit ledger_diffs when empty."""
        result = ScenarioResult(
            name="test",
            passed=True,
        )
        d = _scenario_result_to_dict(result)
        assert "ledger_diffs" not in d


class TestLedgerCategoryDiff:
    """Tests for LedgerCategoryDiff dataclass."""

    def test_ledger_category_diff_fields(self):
        """LedgerCategoryDiff should have all required fields."""
        diff = LedgerCategoryDiff(
            category="total_cost_pln",
            baseline_expected=1000.0,
            baseline_actual=1000.0,
            project_expected=500.0,
            project_actual=600.0,
            delta_expected=500.0,
            delta_actual=400.0,
            diff_pln=100.0,
        )
        assert diff.category == "total_cost_pln"
        assert diff.baseline_expected == 1000.0
        assert diff.baseline_actual == 1000.0
        assert diff.project_expected == 500.0
        assert diff.project_actual == 600.0
        assert diff.delta_expected == 500.0
        assert diff.delta_actual == 400.0
        assert diff.diff_pln == 100.0

"""
Unit tests for KPI diff engine (v1.4.0).

Tests:
- ToleranceConfig defaults and overrides
- compute_kpi_diffs() pass/fail logic
- extract_kpis_from_sizing_response() extraction
- kpi_snapshot_to_dict() conversion
"""

import sys
import os

import pytest

# Add services to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "bess-dispatch"))

from validation_kpis import (
    KpiSnapshot,
    ToleranceConfig,
    KpiDiff,
    compute_kpi_diffs,
    extract_kpis_from_sizing_response,
    kpi_snapshot_to_dict,
)


# -----------------------------------------------------------------------------
# ToleranceConfig Tests
# -----------------------------------------------------------------------------

class TestToleranceConfig:
    """Test ToleranceConfig model."""

    def test_default_values(self):
        """Test default tolerance values."""
        config = ToleranceConfig()
        assert config.default_abs == 1.0
        assert config.default_rel == 0.001
        assert config.per_field_abs == {}
        assert config.per_field_rel == {}

    def test_custom_values(self):
        """Test custom tolerance values."""
        config = ToleranceConfig(
            default_abs=0.5,
            default_rel=0.01,
            per_field_abs={"payback_years": 0.05},
            per_field_rel={"npv_pln": 0.005},
        )
        assert config.default_abs == 0.5
        assert config.default_rel == 0.01
        assert config.per_field_abs["payback_years"] == 0.05
        assert config.per_field_rel["npv_pln"] == 0.005


# -----------------------------------------------------------------------------
# compute_kpi_diffs() Tests
# -----------------------------------------------------------------------------

class TestComputeKpiDiffs:
    """Test compute_kpi_diffs function."""

    def test_kpi_diff_passes_within_absolute_tolerance(self):
        """Test that diff passes when within absolute tolerance."""
        expected = {"npv_pln": 1000.0}
        actual = {"npv_pln": 1000.4}
        tolerances = ToleranceConfig(default_abs=1.0, default_rel=0.0)

        diffs = compute_kpi_diffs(expected, actual, tolerances)

        assert len(diffs) == 1
        d = diffs[0]
        assert d.field == "npv_pln"
        assert d.expected == 1000.0
        assert d.actual == 1000.4
        assert d.abs_diff == pytest.approx(0.4)
        assert d.pass_ is True

    def test_kpi_diff_fails_outside_absolute_tolerance(self):
        """Test that diff fails when outside absolute tolerance."""
        expected = {"npv_pln": 1000.0}
        actual = {"npv_pln": 1002.0}
        tolerances = ToleranceConfig(default_abs=1.0, default_rel=0.0)

        diffs = compute_kpi_diffs(expected, actual, tolerances)

        assert len(diffs) == 1
        assert diffs[0].pass_ is False
        assert diffs[0].abs_diff == 2.0

    def test_kpi_diff_passes_within_relative_tolerance(self):
        """Test that diff passes when within relative tolerance."""
        expected = {"npv_pln": 10000.0}
        actual = {"npv_pln": 10005.0}  # 0.05% difference
        tolerances = ToleranceConfig(default_abs=0.0, default_rel=0.001)  # 0.1% tolerance

        diffs = compute_kpi_diffs(expected, actual, tolerances)

        assert diffs[0].pass_ is True

    def test_kpi_diff_fails_outside_relative_tolerance(self):
        """Test that diff fails when outside relative tolerance."""
        expected = {"npv_pln": 10000.0}
        actual = {"npv_pln": 10020.0}  # 0.2% difference
        tolerances = ToleranceConfig(default_abs=0.0, default_rel=0.001)  # 0.1% tolerance

        diffs = compute_kpi_diffs(expected, actual, tolerances)

        assert diffs[0].pass_ is False

    def test_effective_tolerance_is_max_of_abs_and_rel(self):
        """Test that effective tolerance is max(abs_tol, |expected| * rel_tol)."""
        # For npv_pln=1000, rel_tol=0.01 gives 10, abs_tol=5
        # Effective tolerance should be 10 (rel wins)
        expected = {"npv_pln": 1000.0}
        actual = {"npv_pln": 1008.0}  # diff = 8
        tolerances = ToleranceConfig(default_abs=5.0, default_rel=0.01)

        diffs = compute_kpi_diffs(expected, actual, tolerances)

        # 8 <= max(5, 1000*0.01) = max(5, 10) = 10 -> pass
        assert diffs[0].pass_ is True

    def test_per_field_tolerance_overrides_default(self):
        """Test that per-field tolerance overrides default."""
        expected = {"npv_pln": 1000.0, "payback_years": 5.0}
        actual = {"npv_pln": 1002.0, "payback_years": 5.1}
        tolerances = ToleranceConfig(
            default_abs=1.0,
            default_rel=0.0,
            per_field_abs={"payback_years": 0.2},  # Override for payback
        )

        diffs = compute_kpi_diffs(expected, actual, tolerances)

        # npv_pln: diff=2, tol=1 -> fail
        npv_diff = next(d for d in diffs if d.field == "npv_pln")
        assert npv_diff.pass_ is False

        # payback_years: diff=0.1, tol=0.2 -> pass
        payback_diff = next(d for d in diffs if d.field == "payback_years")
        assert payback_diff.pass_ is True

    def test_rel_diff_is_none_when_expected_is_zero(self):
        """Test that rel_diff is None when expected is zero."""
        expected = {"npv_pln": 0.0}
        actual = {"npv_pln": 5.0}
        tolerances = ToleranceConfig(default_abs=10.0, default_rel=0.0)

        diffs = compute_kpi_diffs(expected, actual, tolerances)

        assert diffs[0].rel_diff is None

    def test_multiple_fields(self):
        """Test diff computation for multiple fields."""
        expected = {
            "npv_pln": 1000.0,
            "payback_years": 5.0,
            "net_savings_pln": 200.0,
        }
        actual = {
            "npv_pln": 1000.5,
            "payback_years": 5.1,
            "net_savings_pln": 195.0,
        }
        tolerances = ToleranceConfig(default_abs=1.0, default_rel=0.0)

        diffs = compute_kpi_diffs(expected, actual, tolerances)

        assert len(diffs) == 3

    def test_missing_field_in_actual_defaults_to_zero(self):
        """Test that missing field in actual defaults to 0."""
        expected = {"npv_pln": 100.0}
        actual = {}  # npv_pln missing
        tolerances = ToleranceConfig(default_abs=1.0, default_rel=0.0)

        diffs = compute_kpi_diffs(expected, actual, tolerances)

        assert diffs[0].actual == 0.0
        assert diffs[0].abs_diff == 100.0

    def test_skips_non_numeric_fields(self):
        """Test that non-numeric fields are skipped."""
        expected = {"npv_pln": 1000.0, "recommended_variant": "medium"}
        actual = {"npv_pln": 1000.0, "recommended_variant": "large"}
        tolerances = ToleranceConfig()

        diffs = compute_kpi_diffs(expected, actual, tolerances)

        # Only npv_pln should be in diffs
        assert len(diffs) == 1
        assert diffs[0].field == "npv_pln"


# -----------------------------------------------------------------------------
# extract_kpis_from_sizing_response() Tests
# -----------------------------------------------------------------------------

class TestExtractKpisFromSizingResponse:
    """Test extract_kpis_from_sizing_response function."""

    def test_extracts_recommended_variant(self):
        """Test extraction of recommended variant name."""
        resp = {
            "recommended_variant": "medium",
            "variants": [
                {"variant": "medium", "npv_pln": 1000.0, "simple_payback_years": 5.0}
            ],
        }
        kpis = extract_kpis_from_sizing_response(resp)

        assert kpis.recommended_variant == "medium"

    def test_extracts_finance_summary(self):
        """Test extraction of finance_summary values."""
        resp = {
            "recommended_variant": "medium",
            "variants": [
                {
                    "variant": "medium",
                    "finance_summary": {
                        "npv_pln": 12345.0,
                        "payback_years": 4.5,
                        "irr_pct": 15.2,
                    },
                }
            ],
        }
        kpis = extract_kpis_from_sizing_response(resp)

        assert kpis.npv_pln == 12345.0
        assert kpis.payback_years == 4.5
        assert kpis.irr_pct == 15.2

    def test_extracts_savings_breakdown(self):
        """Test extraction of savings_breakdown values."""
        resp = {
            "recommended_variant": "medium",
            "variants": [
                {
                    "variant": "medium",
                    "npv_pln": 1000.0,
                    "simple_payback_years": 5.0,
                    "savings_breakdown": {
                        "net_savings_pln": 500.0,
                        "energy_savings_pln": 300.0,
                        "capacity_fee_savings_pln": 100.0,
                        "demand_charge_savings_pln": 50.0,
                        "arbitrage_savings_pln": 25.0,
                        "export_revenue_savings_pln": -10.0,
                        "degradation_cost_pln": 15.0,
                        "battery_throughput_mwh": 1.5,
                    },
                }
            ],
        }
        kpis = extract_kpis_from_sizing_response(resp)

        assert kpis.net_savings_pln == 500.0
        assert kpis.energy_savings_pln == 300.0
        assert kpis.capacity_fee_savings_pln == 100.0
        assert kpis.demand_charge_savings_pln == 50.0
        assert kpis.arbitrage_savings_pln == 25.0
        assert kpis.export_revenue_savings_pln == -10.0
        assert kpis.degradation_cost_pln == 15.0
        assert kpis.battery_throughput_mwh == 1.5

    def test_extracts_energy_flows(self):
        """Test extraction of energy flow totals."""
        resp = {
            "recommended_variant": "medium",
            "variants": [
                {
                    "variant": "medium",
                    "npv_pln": 1000.0,
                    "simple_payback_years": 5.0,
                    "dispatch_summary": {
                        "energy_flows": {
                            "totals_mwh": {
                                "grid_import_mwh": 10.5,
                                "grid_export_mwh": 2.3,
                                "pv_curtail_mwh": 0.5,
                            }
                        }
                    },
                }
            ],
        }
        kpis = extract_kpis_from_sizing_response(resp)

        assert kpis.grid_import_mwh == 10.5
        assert kpis.grid_export_mwh == 2.3
        assert kpis.pv_curtail_mwh == 0.5

    def test_extracts_unserved_load(self):
        """Test extraction of unserved load from constraint_summary."""
        resp = {
            "recommended_variant": "medium",
            "variants": [
                {
                    "variant": "medium",
                    "npv_pln": 1000.0,
                    "simple_payback_years": 5.0,
                    "dispatch_summary": {
                        "constraint_summary": {
                            "unserved_load_kwh": 100.5,
                        }
                    },
                }
            ],
        }
        kpis = extract_kpis_from_sizing_response(resp)

        assert kpis.unserved_load_kwh == 100.5

    def test_extracts_objective_used(self):
        """Test extraction of objective_used."""
        resp = {
            "recommended_variant": "medium",
            "objective_used": "payback",
            "variants": [
                {"variant": "medium", "npv_pln": 1000.0, "simple_payback_years": 5.0}
            ],
        }
        kpis = extract_kpis_from_sizing_response(resp)

        assert kpis.objective_used == "payback"

    def test_handles_empty_response(self):
        """Test handling of empty response."""
        kpis = extract_kpis_from_sizing_response({})

        assert kpis.recommended_variant == "unknown"
        assert kpis.npv_pln == 0.0

    def test_handles_missing_variant(self):
        """Test handling when recommended variant is not in variants list."""
        resp = {
            "recommended_variant": "large",
            "variants": [
                {"variant": "medium", "npv_pln": 500.0, "simple_payback_years": 6.0}
            ],
        }
        kpis = extract_kpis_from_sizing_response(resp)

        # Falls back to first variant
        assert kpis.recommended_variant == "medium"
        assert kpis.npv_pln == 500.0


# -----------------------------------------------------------------------------
# kpi_snapshot_to_dict() Tests
# -----------------------------------------------------------------------------

class TestKpiSnapshotToDict:
    """Test kpi_snapshot_to_dict function."""

    def test_converts_to_dict(self):
        """Test conversion to dict."""
        snapshot = KpiSnapshot(
            recommended_variant="medium",
            objective_used="npv",
            net_savings_pln=100.0,
            npv_pln=1000.0,
            payback_years=5.0,
            irr_pct=12.0,
        )
        d = kpi_snapshot_to_dict(snapshot)

        assert "net_savings_pln" in d
        assert "npv_pln" in d
        assert d["net_savings_pln"] == 100.0
        assert d["npv_pln"] == 1000.0

    def test_excludes_non_numeric_fields(self):
        """Test that non-numeric fields are excluded."""
        snapshot = KpiSnapshot(
            recommended_variant="medium",
            objective_used="npv",
            net_savings_pln=100.0,
            npv_pln=1000.0,
            payback_years=5.0,
        )
        d = kpi_snapshot_to_dict(snapshot)

        assert "recommended_variant" not in d
        assert "objective_used" not in d

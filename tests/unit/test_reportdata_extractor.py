"""
Unit tests for report_data extractor (v2.4.0 PR1).

Tests verify:
- ReportMeta extraction (run_id, schema_version, assumptions_version, etc.)
- ReportRecommended extraction (net_savings_pln, NPV, payback)
- ReportMoneyLedgerAnnual extraction (baseline/project/delta totals)
- Engineering profile includes dispatch_summary
- Warnings generated for missing fields
"""

import pytest
import sys

sys.path.insert(0, "services/bess-dispatch")


def _minimal_run_record():
    """Create a minimal valid run record for testing."""
    return {
        "run_id": "test-run-001",
        "created_at": "2026-01-01T10:00:00Z",
        "schema_version": "1.3.0",
        "assumptions_version": "v1.0.0-abc123",
        "request": {
            "load_kw": [100] * 24,
            "pv_generation_kw": [50] * 24,
            "mode": "pv_surplus",
            "grid_constraints": {
                "max_import_kw": 500.0,
                "max_export_kw": 200.0,
            },
        },
        "response": {
            "meta": {
                "run_id": "test-run-001",
                "git_sha": "abc123def456",
                "build_time_utc": "2026-01-01T08:00:00Z",
            },
            "period_info": {
                "period_hours": 8760.0,
                "period_days": 365.0,
                "is_full_year": True,
                "start_datetime": "2026-01-01T00:00:00",
                "end_datetime": "2026-12-31T23:00:00",
                "steps": 8760,
                "step_minutes": 60,
                "timezone": "Europe/Warsaw",
            },
            "pricing_debug": {
                "pricing_mode": "generated",
                "price_hash": "abc123def456789",
            },
            "objective_used": "npv",
            "recommended": {
                "variant_name": "bess_100kWh",
                "name": "bess_100kWh",
                "recommendation_reason": "Highest NPV",
                "finance_summary": {
                    "npv_pln": 150000.0,
                    "payback_years": 4.5,
                    "irr_pct": 18.5,
                    "net_savings_pln": 35000.0,
                    "capex_pln": 180000.0,
                },
                "totals": {
                    "grid_import_mwh": 500.0,
                    "grid_export_mwh": 120.0,
                    "pv_curtail_mwh": 5.0,
                    "unserved_load_kwh": 0.0,
                },
                "money_ledger": {
                    "baseline_annual": {
                        "import_energy_cost_pln": 400000.0,
                        "export_revenue_pln": 10000.0,
                        "capacity_fee_pln": 50000.0,
                        "demand_charge_pln": 20000.0,
                        "total_cost_pln": 460000.0,
                    },
                    "project_annual": {
                        "import_energy_cost_pln": 350000.0,
                        "export_revenue_pln": 25000.0,
                        "capacity_fee_pln": 45000.0,
                        "demand_charge_pln": 15000.0,
                        "unserved_penalty_pln": 0.0,
                        "total_cost_pln": 385000.0,
                    },
                    "delta_annual_pln": {
                        "import_energy_cost_pln": 50000.0,
                        "export_revenue_pln": 15000.0,
                        "capacity_fee_pln": 5000.0,
                        "demand_charge_pln": 5000.0,
                        "total_cost_pln": 75000.0,
                    },
                },
                "debug_events": {
                    "steps": 8760,
                    "export_limited_steps": 120,
                    "export_limited_mwh": 15.5,
                    "import_limited_steps": 0,
                    "import_limited_mwh": 0.0,
                    "pv_curtail_mwh": 5.0,
                    "unserved_load_kwh": 0.0,
                },
                "dispatch_summary": {
                    "cycle_summary": {
                        "efc_total": 250.0,
                        "avg_daily_efc": 0.68,
                        "max_daily_efc": 1.2,
                        "total_throughput_kwh": 25000.0,
                        "cycle_limit_hit": False,
                    },
                },
                "invariants": {
                    "all_ok": True,
                    "soc_bounds_ok": True,
                    "power_limits_ok": True,
                    "no_simultaneous_ok": True,
                    "energy_balance_ok": True,
                },
            },
        },
    }


# =============================================================================
# TestReportMetaExtraction
# =============================================================================

class TestReportMetaExtraction:
    """Tests for ReportMeta extraction."""

    def test_meta_run_id_extracted(self):
        """run_id should be extracted from run record."""
        from report_data import build_report_data_from_run

        run_record = _minimal_run_record()
        report_data = build_report_data_from_run(run_record)

        assert report_data.meta.run_id == "test-run-001"

    def test_meta_created_at_extracted(self):
        """created_at should be extracted from run record."""
        from report_data import build_report_data_from_run

        run_record = _minimal_run_record()
        report_data = build_report_data_from_run(run_record)

        assert report_data.meta.created_at == "2026-01-01T10:00:00Z"

    def test_meta_schema_version_extracted(self):
        """schema_version should be extracted from run record."""
        from report_data import build_report_data_from_run

        run_record = _minimal_run_record()
        report_data = build_report_data_from_run(run_record)

        assert report_data.meta.schema_version == "1.3.0"

    def test_meta_assumptions_version_extracted(self):
        """assumptions_version should be extracted from run record."""
        from report_data import build_report_data_from_run

        run_record = _minimal_run_record()
        report_data = build_report_data_from_run(run_record)

        assert report_data.meta.assumptions_version == "v1.0.0-abc123"

    def test_meta_git_sha_extracted(self):
        """git_sha should be extracted from response meta."""
        from report_data import build_report_data_from_run

        run_record = _minimal_run_record()
        report_data = build_report_data_from_run(run_record)

        assert report_data.meta.git_sha == "abc123def456"

    def test_meta_pricing_mode_extracted(self):
        """pricing_mode should be extracted from pricing_debug."""
        from report_data import build_report_data_from_run

        run_record = _minimal_run_record()
        report_data = build_report_data_from_run(run_record)

        assert report_data.meta.pricing_mode == "generated"

    def test_meta_period_info_extracted(self):
        """Period info should be extracted."""
        from report_data import build_report_data_from_run

        run_record = _minimal_run_record()
        report_data = build_report_data_from_run(run_record)

        assert report_data.meta.period_hours == 8760.0
        assert report_data.meta.is_full_year is True
        assert report_data.meta.steps == 8760
        assert report_data.meta.step_minutes == 60


# =============================================================================
# TestReportRecommendedExtraction
# =============================================================================

class TestReportRecommendedExtraction:
    """Tests for ReportRecommended extraction."""

    def test_recommended_variant_name_extracted(self):
        """recommended_variant should be extracted."""
        from report_data import build_report_data_from_run

        run_record = _minimal_run_record()
        report_data = build_report_data_from_run(run_record)

        assert report_data.recommended.recommended_variant == "bess_100kWh"

    def test_recommended_net_savings_extracted(self):
        """net_savings_pln should be extracted from finance_summary."""
        from report_data import build_report_data_from_run

        run_record = _minimal_run_record()
        report_data = build_report_data_from_run(run_record)

        assert report_data.recommended.net_savings_pln == 35000.0

    def test_recommended_npv_extracted(self):
        """npv_pln should be extracted from finance_summary."""
        from report_data import build_report_data_from_run

        run_record = _minimal_run_record()
        report_data = build_report_data_from_run(run_record)

        assert report_data.recommended.npv_pln == 150000.0

    def test_recommended_payback_extracted(self):
        """payback_years should be extracted from finance_summary."""
        from report_data import build_report_data_from_run

        run_record = _minimal_run_record()
        report_data = build_report_data_from_run(run_record)

        assert report_data.recommended.payback_years == 4.5

    def test_recommended_irr_extracted(self):
        """irr_pct should be extracted from finance_summary."""
        from report_data import build_report_data_from_run

        run_record = _minimal_run_record()
        report_data = build_report_data_from_run(run_record)

        assert report_data.recommended.irr_pct == 18.5

    def test_recommended_objective_used_extracted(self):
        """objective_used should be extracted from response."""
        from report_data import build_report_data_from_run

        run_record = _minimal_run_record()
        report_data = build_report_data_from_run(run_record)

        assert report_data.recommended.objective_used == "npv"


# =============================================================================
# TestReportMoneyLedgerExtraction
# =============================================================================

class TestReportMoneyLedgerExtraction:
    """Tests for ReportMoneyLedgerAnnual extraction."""

    def test_money_ledger_baseline_total_extracted(self):
        """Baseline total_cost_pln should be extracted."""
        from report_data import build_report_data_from_run

        run_record = _minimal_run_record()
        report_data = build_report_data_from_run(run_record)

        assert report_data.money_ledger_annual.baseline.total_cost_pln == 460000.0

    def test_money_ledger_project_total_extracted(self):
        """Project total_cost_pln should be extracted."""
        from report_data import build_report_data_from_run

        run_record = _minimal_run_record()
        report_data = build_report_data_from_run(run_record)

        assert report_data.money_ledger_annual.project.total_cost_pln == 385000.0

    def test_money_ledger_delta_total_extracted(self):
        """Delta total_cost_pln should be extracted."""
        from report_data import build_report_data_from_run

        run_record = _minimal_run_record()
        report_data = build_report_data_from_run(run_record)

        assert report_data.money_ledger_annual.delta.total_cost_pln == 75000.0

    def test_money_ledger_import_costs_extracted(self):
        """Import energy costs should be extracted for all buckets."""
        from report_data import build_report_data_from_run

        run_record = _minimal_run_record()
        report_data = build_report_data_from_run(run_record)

        assert report_data.money_ledger_annual.baseline.import_energy_cost_pln == 400000.0
        assert report_data.money_ledger_annual.project.import_energy_cost_pln == 350000.0
        assert report_data.money_ledger_annual.delta.import_energy_cost_pln == 50000.0

    def test_money_ledger_export_revenue_extracted(self):
        """Export revenue should be extracted for all buckets."""
        from report_data import build_report_data_from_run

        run_record = _minimal_run_record()
        report_data = build_report_data_from_run(run_record)

        assert report_data.money_ledger_annual.baseline.export_revenue_pln == 10000.0
        assert report_data.money_ledger_annual.project.export_revenue_pln == 25000.0
        assert report_data.money_ledger_annual.delta.export_revenue_pln == 15000.0


# =============================================================================
# TestReportFlowsExtraction
# =============================================================================

class TestReportFlowsExtraction:
    """Tests for ReportFlowsAnnual extraction."""

    def test_flows_grid_import_extracted(self):
        """grid_import_mwh should be extracted."""
        from report_data import build_report_data_from_run

        run_record = _minimal_run_record()
        report_data = build_report_data_from_run(run_record)

        assert report_data.flows_annual.grid_import_mwh == 500.0

    def test_flows_grid_export_extracted(self):
        """grid_export_mwh should be extracted."""
        from report_data import build_report_data_from_run

        run_record = _minimal_run_record()
        report_data = build_report_data_from_run(run_record)

        assert report_data.flows_annual.grid_export_mwh == 120.0

    def test_flows_pv_curtail_extracted(self):
        """pv_curtail_mwh should be extracted."""
        from report_data import build_report_data_from_run

        run_record = _minimal_run_record()
        report_data = build_report_data_from_run(run_record)

        assert report_data.flows_annual.pv_curtail_mwh == 5.0


# =============================================================================
# TestReportConstraintsExtraction
# =============================================================================

class TestReportConstraintsExtraction:
    """Tests for ReportConstraints extraction."""

    def test_constraints_max_import_extracted(self):
        """max_import_kw should be extracted from request."""
        from report_data import build_report_data_from_run

        run_record = _minimal_run_record()
        report_data = build_report_data_from_run(run_record)

        assert report_data.constraints.max_import_kw == 500.0

    def test_constraints_max_export_extracted(self):
        """max_export_kw should be extracted from request."""
        from report_data import build_report_data_from_run

        run_record = _minimal_run_record()
        report_data = build_report_data_from_run(run_record)

        assert report_data.constraints.max_export_kw == 200.0

    def test_constraints_export_limited_steps_extracted(self):
        """export_limited_steps should be extracted from debug_events."""
        from report_data import build_report_data_from_run

        run_record = _minimal_run_record()
        report_data = build_report_data_from_run(run_record)

        assert report_data.constraints.export_limited_steps == 120


# =============================================================================
# TestEngineeringProfile
# =============================================================================

class TestEngineeringProfile:
    """Tests for engineering profile with dispatch_summary."""

    def test_engineering_profile_includes_dispatch_summary(self):
        """Engineering profile should include dispatch_summary."""
        from report_data import build_report_data_from_run
        from report_models import ReportOptions, ReportProfile

        run_record = _minimal_run_record()
        options = ReportOptions(profile=ReportProfile.ENGINEERING)
        report_data = build_report_data_from_run(run_record, options)

        assert report_data.dispatch_summary is not None

    def test_engineering_profile_cycle_summary_extracted(self):
        """Cycle summary should be extracted for engineering profile."""
        from report_data import build_report_data_from_run
        from report_models import ReportOptions, ReportProfile

        run_record = _minimal_run_record()
        options = ReportOptions(profile=ReportProfile.ENGINEERING)
        report_data = build_report_data_from_run(run_record, options)

        assert report_data.dispatch_summary.cycle_summary is not None
        assert report_data.dispatch_summary.cycle_summary.efc_total == 250.0

    def test_engineering_profile_invariants_extracted(self):
        """Invariants should be extracted for engineering profile."""
        from report_data import build_report_data_from_run
        from report_models import ReportOptions, ReportProfile

        run_record = _minimal_run_record()
        options = ReportOptions(profile=ReportProfile.ENGINEERING)
        report_data = build_report_data_from_run(run_record, options)

        assert report_data.dispatch_summary.invariants is not None
        assert report_data.dispatch_summary.invariants.all_ok is True

    def test_engineering_profile_debug_events_extracted(self):
        """Debug events should be extracted for engineering profile."""
        from report_data import build_report_data_from_run
        from report_models import ReportOptions, ReportProfile

        run_record = _minimal_run_record()
        options = ReportOptions(profile=ReportProfile.ENGINEERING)
        report_data = build_report_data_from_run(run_record, options)

        assert report_data.dispatch_summary.debug_events is not None
        assert report_data.dispatch_summary.debug_events.steps == 8760

    def test_client_profile_no_dispatch_summary(self):
        """Client profile should NOT include dispatch_summary."""
        from report_data import build_report_data_from_run
        from report_models import ReportOptions, ReportProfile

        run_record = _minimal_run_record()
        options = ReportOptions(profile=ReportProfile.CLIENT)
        report_data = build_report_data_from_run(run_record, options)

        assert report_data.dispatch_summary is None


# =============================================================================
# TestWarningsGeneration
# =============================================================================

class TestWarningsGeneration:
    """Tests for warnings generated on missing fields."""

    def test_missing_git_sha_generates_warning(self):
        """Missing git_sha should generate warning."""
        from report_data import build_report_data_from_run

        run_record = _minimal_run_record()
        del run_record["response"]["meta"]["git_sha"]
        report_data = build_report_data_from_run(run_record)

        assert any("git_sha" in w for w in report_data.warnings)

    def test_missing_pricing_mode_generates_warning(self):
        """Missing pricing_mode should generate warning."""
        from report_data import build_report_data_from_run

        run_record = _minimal_run_record()
        del run_record["response"]["pricing_debug"]
        report_data = build_report_data_from_run(run_record)

        assert any("pricing_mode" in w for w in report_data.warnings)

    def test_missing_money_ledger_generates_warning(self):
        """Missing money_ledger should generate warning."""
        from report_data import build_report_data_from_run

        run_record = _minimal_run_record()
        del run_record["response"]["recommended"]["money_ledger"]
        report_data = build_report_data_from_run(run_record)

        assert any("money_ledger" in w for w in report_data.warnings)

    def test_missing_recommended_generates_warning(self):
        """Missing recommended should generate warning."""
        from report_data import build_report_data_from_run

        run_record = _minimal_run_record()
        del run_record["response"]["recommended"]
        report_data = build_report_data_from_run(run_record)

        assert any("recommended" in w.lower() for w in report_data.warnings)


# =============================================================================
# TestReportOptions
# =============================================================================

class TestReportOptions:
    """Tests for ReportOptions model."""

    def test_report_options_default_profile_is_client(self):
        """Default profile should be client."""
        from report_models import ReportOptions, ReportProfile

        options = ReportOptions()
        assert options.profile == ReportProfile.CLIENT

    def test_report_options_default_max_table_rows_is_48(self):
        """Default max_table_rows should be 48."""
        from report_models import ReportOptions

        options = ReportOptions()
        assert options.max_table_rows == 48

    def test_report_options_branding_optional(self):
        """Branding should be optional."""
        from report_models import ReportOptions

        options = ReportOptions()
        assert options.branding is None

    def test_report_options_notes_optional(self):
        """Notes should be optional."""
        from report_models import ReportOptions

        options = ReportOptions()
        assert options.notes is None

    def test_report_branding_fields(self):
        """ReportBranding should accept all fields."""
        from report_models import ReportBranding

        branding = ReportBranding(
            report_title="BESS Analysis Report",
            client_name="ACME Corp",
            site_name="Factory A",
            prepared_by="Engineer X",
            prepared_for="CEO Y",
        )

        assert branding.report_title == "BESS Analysis Report"
        assert branding.client_name == "ACME Corp"
        assert branding.site_name == "Factory A"
        assert branding.prepared_by == "Engineer X"
        assert branding.prepared_for == "CEO Y"

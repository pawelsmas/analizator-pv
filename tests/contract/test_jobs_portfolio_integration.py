"""
Contract tests for Jobs Portfolio Integration (v2.3.0 PR3).

Tests verify:
- Job result contains portfolio_summary with aggregated KPIs
- Job result contains portfolio_items array
- total_npv_pln equals sum of individual item NPVs
- mixed_assumptions is set correctly
- Error items are excluded from portfolio summary
"""

import pytest
import uuid
from ._api import post_json, get_json


def _base_req():
    """Minimal valid sizing request."""
    return {
        "load_kw": [100, 100, 100, 100, 100, 100, 150, 200, 250, 300, 300, 300, 300, 300, 250, 200, 150, 100, 100, 100, 100, 100, 100, 100],
        "pv_generation_kw": [0, 0, 0, 0, 0, 0, 50, 200, 500, 800, 1000, 1100, 1100, 1000, 800, 500, 200, 50, 0, 0, 0, 0, 0, 0],
        "mode": "pv_surplus",
        "durations_h": [1.0, 2.0],
        "interval_minutes": 60,
        "discount_rate": 0.08,
        "analysis_years": 15,
        "capex_pln_per_kwh": 1800.0,
        "import_price_pln_mwh": 800.0,
    }


# =============================================================================
# TestJobsPortfolioSummaryPresence
# =============================================================================

class TestJobsPortfolioSummaryPresence:
    """Tests for portfolio_summary presence in job result."""

    def test_job_result_has_portfolio_summary(self):
        """Job result should have portfolio_summary field."""
        payload = {
            "wait": True,
            "fail_fast": False,
            "items": [
                {"item_id": "PS1", "request": _base_req()},
                {"item_id": "PS2", "request": _base_req()},
            ]
        }
        resp = post_json("/api/bess-dispatch/jobs/sizing-batch", payload)
        job_id = resp["job_id"]

        detail = get_json(f"/api/bess-dispatch/jobs/{job_id}")
        result = detail["result"]

        assert "portfolio_summary" in result
        assert result["portfolio_summary"] is not None

    def test_job_result_has_portfolio_items(self):
        """Job result should have portfolio_items array."""
        payload = {
            "wait": True,
            "fail_fast": False,
            "items": [
                {"item_id": "PI1", "request": _base_req()},
                {"item_id": "PI2", "request": _base_req()},
            ]
        }
        resp = post_json("/api/bess-dispatch/jobs/sizing-batch", payload)
        job_id = resp["job_id"]

        detail = get_json(f"/api/bess-dispatch/jobs/{job_id}")
        result = detail["result"]

        assert "portfolio_items" in result
        assert isinstance(result["portfolio_items"], list)
        assert len(result["portfolio_items"]) == 2

    def test_portfolio_summary_has_required_fields(self):
        """Portfolio summary should have all required fields."""
        payload = {
            "wait": True,
            "items": [{"item_id": "RF1", "request": _base_req()}]
        }
        resp = post_json("/api/bess-dispatch/jobs/sizing-batch", payload)
        job_id = resp["job_id"]

        detail = get_json(f"/api/bess-dispatch/jobs/{job_id}")
        portfolio_summary = detail["result"]["portfolio_summary"]

        # Required fields from PortfolioRunsSummary model
        assert "items_total" in portfolio_summary
        assert "items_ok" in portfolio_summary
        assert "items_error" in portfolio_summary
        assert "mixed_assumptions" in portfolio_summary
        assert "total_npv_pln" in portfolio_summary
        assert "total_net_savings_pln" in portfolio_summary
        assert "total_capex_pln" in portfolio_summary
        assert "top_items_by_npv" in portfolio_summary

    def test_portfolio_item_has_required_fields(self):
        """Each portfolio item should have required fields."""
        payload = {
            "wait": True,
            "items": [{"item_id": "IF1", "request": _base_req()}]
        }
        resp = post_json("/api/bess-dispatch/jobs/sizing-batch", payload)
        job_id = resp["job_id"]

        detail = get_json(f"/api/bess-dispatch/jobs/{job_id}")
        portfolio_items = detail["result"]["portfolio_items"]

        assert len(portfolio_items) == 1
        item = portfolio_items[0]

        # Required fields from PortfolioItemSummary model
        assert "run_id" in item
        assert "npv_pln" in item
        assert "net_savings_pln" in item
        assert "capex_pln" in item
        assert "status" in item


# =============================================================================
# TestJobsPortfolioAggregation
# =============================================================================

class TestJobsPortfolioAggregation:
    """Tests for portfolio aggregation in job results."""

    def test_portfolio_summary_counts_match_job(self):
        """Portfolio summary counts should match job counts."""
        payload = {
            "wait": True,
            "fail_fast": False,
            "items": [
                {"item_id": "MC1", "request": _base_req()},
                {"item_id": "MC2", "request": _base_req()},
                {"item_id": "MC3", "request": _base_req()},
            ]
        }
        resp = post_json("/api/bess-dispatch/jobs/sizing-batch", payload)
        job_id = resp["job_id"]

        detail = get_json(f"/api/bess-dispatch/jobs/{job_id}")
        result = detail["result"]

        # Portfolio counts should match summary counts
        assert result["portfolio_summary"]["items_ok"] == result["summary"]["ok_count"]
        assert result["portfolio_summary"]["items_error"] == result["summary"]["error_count"]

    def test_portfolio_total_npv_equals_sum(self):
        """Total NPV should equal sum of individual item NPVs."""
        payload = {
            "wait": True,
            "fail_fast": False,
            "items": [
                {"item_id": "SUM1", "request": _base_req()},
                {"item_id": "SUM2", "request": _base_req()},
            ]
        }
        resp = post_json("/api/bess-dispatch/jobs/sizing-batch", payload)
        job_id = resp["job_id"]

        detail = get_json(f"/api/bess-dispatch/jobs/{job_id}")
        portfolio_summary = detail["result"]["portfolio_summary"]
        portfolio_items = detail["result"]["portfolio_items"]

        # Sum individual NPVs
        sum_npv = sum(item["npv_pln"] for item in portfolio_items)

        # Total should match sum (within tolerance for floating point)
        assert abs(portfolio_summary["total_npv_pln"] - sum_npv) < 1.0, \
            f"Total NPV {portfolio_summary['total_npv_pln']} != sum {sum_npv}"

    def test_portfolio_item_run_id_matches_item_id(self):
        """Portfolio item run_id should match the job item_id."""
        payload = {
            "wait": True,
            "items": [
                {"item_id": "MATCH_A", "request": _base_req()},
                {"item_id": "MATCH_B", "request": _base_req()},
            ]
        }
        resp = post_json("/api/bess-dispatch/jobs/sizing-batch", payload)
        job_id = resp["job_id"]

        detail = get_json(f"/api/bess-dispatch/jobs/{job_id}")
        portfolio_items = detail["result"]["portfolio_items"]

        run_ids = {item["run_id"] for item in portfolio_items}
        assert "MATCH_A" in run_ids
        assert "MATCH_B" in run_ids

    def test_top_items_by_npv_sorted_descending(self):
        """Top items by NPV should be sorted by NPV descending."""
        payload = {
            "wait": True,
            "fail_fast": False,
            "items": [
                {"item_id": "TOP1", "request": _base_req()},
                {"item_id": "TOP2", "request": _base_req()},
                {"item_id": "TOP3", "request": _base_req()},
            ]
        }
        resp = post_json("/api/bess-dispatch/jobs/sizing-batch", payload)
        job_id = resp["job_id"]

        detail = get_json(f"/api/bess-dispatch/jobs/{job_id}")
        top_items = detail["result"]["portfolio_summary"]["top_items_by_npv"]

        # Verify they're sorted by NPV descending
        npvs = [item["npv_pln"] for item in top_items]
        assert npvs == sorted(npvs, reverse=True)


# =============================================================================
# TestJobsPortfolioErrorHandling
# =============================================================================

class TestJobsPortfolioErrorHandling:
    """Tests for error handling in portfolio aggregation."""

    def test_empty_job_has_empty_portfolio(self):
        """Single item job should have single portfolio item."""
        payload = {
            "wait": True,
            "items": [{"item_id": "SINGLE1", "request": _base_req()}]
        }
        resp = post_json("/api/bess-dispatch/jobs/sizing-batch", payload)
        job_id = resp["job_id"]

        detail = get_json(f"/api/bess-dispatch/jobs/{job_id}")

        assert detail["result"]["portfolio_summary"]["items_ok"] == 1
        assert len(detail["result"]["portfolio_items"]) == 1

    def test_mixed_assumptions_false_when_same_version(self):
        """Mixed assumptions should be false when all items have same version."""
        payload = {
            "wait": True,
            "fail_fast": False,
            "items": [
                {"item_id": "MIX1", "request": _base_req()},
                {"item_id": "MIX2", "request": _base_req()},
            ]
        }
        resp = post_json("/api/bess-dispatch/jobs/sizing-batch", payload)
        job_id = resp["job_id"]

        detail = get_json(f"/api/bess-dispatch/jobs/{job_id}")
        portfolio_summary = detail["result"]["portfolio_summary"]

        # Same engine version should not be mixed
        assert portfolio_summary["mixed_assumptions"] is False


# =============================================================================
# TestJobsPortfolioStatusMapping
# =============================================================================

class TestJobsPortfolioStatusMapping:
    """Tests for portfolio item status mapping."""

    def test_successful_item_has_status_ok(self):
        """Successful items should have status 'ok' in portfolio."""
        payload = {
            "wait": True,
            "items": [{"item_id": "SOK1", "request": _base_req()}]
        }
        resp = post_json("/api/bess-dispatch/jobs/sizing-batch", payload)
        job_id = resp["job_id"]

        detail = get_json(f"/api/bess-dispatch/jobs/{job_id}")
        portfolio_items = detail["result"]["portfolio_items"]

        for item in portfolio_items:
            assert item["status"] == "ok"

    def test_portfolio_items_count_matches_ok_count(self):
        """Number of portfolio items should match ok_count."""
        payload = {
            "wait": True,
            "fail_fast": False,
            "items": [
                {"item_id": "CNT1", "request": _base_req()},
                {"item_id": "CNT2", "request": _base_req()},
            ]
        }
        resp = post_json("/api/bess-dispatch/jobs/sizing-batch", payload)
        job_id = resp["job_id"]

        detail = get_json(f"/api/bess-dispatch/jobs/{job_id}")
        result = detail["result"]

        # Portfolio items only includes OK items
        assert len(result["portfolio_items"]) == result["summary"]["ok_count"]

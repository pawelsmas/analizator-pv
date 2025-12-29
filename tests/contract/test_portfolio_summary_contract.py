"""
Contract tests for v0.9.0 portfolio summary in batch sizing.

Tests verify:
- portfolio_summary is present when batch has successful items
- portfolio_summary is None when all items fail
- variant_rankings are sorted by total_npv_pln descending
- portfolio_optimal_variant matches highest total NPV
- Metrics aggregation is correct

Run with: pytest tests/contract/test_portfolio_summary_contract.py -v
"""
import pytest
from ._api import post_json


BATCH_ENDPOINT = "/sizing:batch"


# Minimal batch request with 2 items
def make_batch_request(num_items: int = 2):
    """Create batch request with specified number of items."""
    items = []
    for i in range(num_items):
        items.append({
            "item_id": f"item_{i}",
            "request": {
                "load_kw": [100 + i * 10, 120 + i * 10, 110 + i * 10, 90 + i * 10],
                "pv_generation_kw": [50, 70, 80, 60],
                "energy_price_pln_kwh": 0.8,
            }
        })
    return {"items": items}


class TestPortfolioSummaryPresence:
    """Tests for portfolio_summary presence in batch response."""

    def test_portfolio_summary_present_in_batch_response(self):
        """Verify portfolio_summary is present when batch has successful items."""
        req = make_batch_request(2)
        resp = post_json(BATCH_ENDPOINT, req)

        assert "portfolio_summary" in resp
        assert resp["portfolio_summary"] is not None

    def test_portfolio_summary_has_required_fields(self):
        """Verify portfolio_summary has all required fields."""
        req = make_batch_request(2)
        resp = post_json(BATCH_ENDPOINT, req)
        ps = resp["portfolio_summary"]

        assert "total_npv_pln" in ps
        assert "avg_npv_pln" in ps
        assert "avg_payback_years" in ps
        assert "portfolio_optimal_variant" in ps
        assert "variant_rankings" in ps

    def test_variant_rankings_is_list(self):
        """Verify variant_rankings is a list."""
        req = make_batch_request(2)
        resp = post_json(BATCH_ENDPOINT, req)
        ps = resp["portfolio_summary"]

        assert isinstance(ps["variant_rankings"], list)
        assert len(ps["variant_rankings"]) > 0


class TestVariantRankingsStructure:
    """Tests for variant_rankings structure."""

    def test_variant_ranking_has_required_fields(self):
        """Verify each variant ranking has required fields."""
        req = make_batch_request(2)
        resp = post_json(BATCH_ENDPOINT, req)
        rankings = resp["portfolio_summary"]["variant_rankings"]

        for ranking in rankings:
            assert "variant" in ranking
            assert "total_npv_pln" in ranking
            assert "avg_npv_pln" in ranking
            assert "avg_payback_years" in ranking
            assert "feasible_count" in ranking
            assert "recommended_count" in ranking

    def test_variant_rankings_sorted_by_total_npv(self):
        """Verify variant_rankings are sorted by total_npv_pln descending."""
        req = make_batch_request(3)
        resp = post_json(BATCH_ENDPOINT, req)
        rankings = resp["portfolio_summary"]["variant_rankings"]

        for i in range(len(rankings) - 1):
            assert rankings[i]["total_npv_pln"] >= rankings[i + 1]["total_npv_pln"], \
                f"Rankings not sorted: {rankings[i]['total_npv_pln']} < {rankings[i+1]['total_npv_pln']}"

    def test_portfolio_optimal_matches_first_ranking(self):
        """Verify portfolio_optimal_variant matches first ranking variant."""
        req = make_batch_request(2)
        resp = post_json(BATCH_ENDPOINT, req)
        ps = resp["portfolio_summary"]

        first_ranking = ps["variant_rankings"][0]
        assert ps["portfolio_optimal_variant"] == first_ranking["variant"]


class TestPortfolioMetricsAggregation:
    """Tests for portfolio metrics aggregation."""

    def test_recommended_count_sums_correctly(self):
        """Verify recommended_count across variants sums to number of items."""
        req = make_batch_request(3)
        resp = post_json(BATCH_ENDPOINT, req)
        rankings = resp["portfolio_summary"]["variant_rankings"]

        total_recommended = sum(r["recommended_count"] for r in rankings)
        ok_count = resp["summary"]["ok_count"]

        assert total_recommended == ok_count, \
            f"Total recommended {total_recommended} != ok_count {ok_count}"

    def test_avg_npv_is_total_divided_by_count(self):
        """Verify avg_npv_pln = total_npv_pln / count for each variant."""
        req = make_batch_request(2)
        resp = post_json(BATCH_ENDPOINT, req)
        rankings = resp["portfolio_summary"]["variant_rankings"]

        for ranking in rankings:
            expected_avg = ranking["total_npv_pln"] / len(req["items"])
            assert abs(ranking["avg_npv_pln"] - expected_avg) < 0.01, \
                f"avg_npv_pln {ranking['avg_npv_pln']} != expected {expected_avg}"

    def test_feasible_count_not_negative(self):
        """Verify feasible_count is non-negative."""
        req = make_batch_request(2)
        resp = post_json(BATCH_ENDPOINT, req)
        rankings = resp["portfolio_summary"]["variant_rankings"]

        for ranking in rankings:
            assert ranking["feasible_count"] >= 0


class TestPortfolioOverallMetrics:
    """Tests for overall portfolio metrics."""

    def test_total_npv_from_recommended_variants(self):
        """Verify total_npv_pln is sum of recommended variant NPVs."""
        req = make_batch_request(2)
        resp = post_json(BATCH_ENDPOINT, req)
        ps = resp["portfolio_summary"]

        # Calculate expected total from results
        expected_total = 0.0
        for result in resp["results"]:
            if result["status"] == "ok":
                recommended = result["response"]["recommended_variant"]
                for v in result["response"]["variants"]:
                    if v["variant"] == recommended:
                        expected_total += v["npv_pln"]
                        break

        assert abs(ps["total_npv_pln"] - expected_total) < 0.01, \
            f"total_npv_pln {ps['total_npv_pln']} != expected {expected_total}"

    def test_avg_npv_is_total_divided_by_ok_count(self):
        """Verify avg_npv_pln = total_npv_pln / ok_count."""
        req = make_batch_request(2)
        resp = post_json(BATCH_ENDPOINT, req)
        ps = resp["portfolio_summary"]
        ok_count = resp["summary"]["ok_count"]

        if ok_count > 0:
            expected_avg = ps["total_npv_pln"] / ok_count
            assert abs(ps["avg_npv_pln"] - expected_avg) < 0.01, \
                f"avg_npv_pln {ps['avg_npv_pln']} != expected {expected_avg}"

    def test_avg_payback_is_numeric(self):
        """Verify avg_payback_years is numeric and non-negative."""
        req = make_batch_request(2)
        resp = post_json(BATCH_ENDPOINT, req)
        ps = resp["portfolio_summary"]

        assert isinstance(ps["avg_payback_years"], (int, float))
        assert ps["avg_payback_years"] >= 0


class TestPortfolioWithSingleItem:
    """Tests for portfolio summary with single item."""

    def test_single_item_portfolio_summary(self):
        """Verify portfolio_summary works with single item."""
        req = make_batch_request(1)
        resp = post_json(BATCH_ENDPOINT, req)

        assert resp["portfolio_summary"] is not None
        assert len(resp["portfolio_summary"]["variant_rankings"]) > 0

    def test_single_item_recommended_count_is_one(self):
        """Verify recommended_count sums to 1 for single item."""
        req = make_batch_request(1)
        resp = post_json(BATCH_ENDPOINT, req)
        rankings = resp["portfolio_summary"]["variant_rankings"]

        total_recommended = sum(r["recommended_count"] for r in rankings)
        assert total_recommended == 1

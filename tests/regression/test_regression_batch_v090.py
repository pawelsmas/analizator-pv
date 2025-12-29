"""
Regression tests for v0.9.0 batch sizing API.

Tests verify:
- Batch response structure is consistent
- Portfolio summary calculations are correct
- Batch ID is present
- Summary totals are consistent

Scenarios:
1. Batch with 3 items - basic batch response
2. Batch with portfolio summary verification

Tolerance: 5% for economic values
"""
import pytest
import math


# Tolerance for floating point comparisons
ECONOMIC_TOLERANCE = 0.05  # 5% for NPV, savings


def relative_diff(actual: float, expected: float) -> float:
    """Calculate relative difference, handling zero expected."""
    if abs(expected) < 1e-9:
        return abs(actual)
    return abs(actual - expected) / abs(expected)


class TestRegressionBatchResponseStructure:
    """Regression tests for batch response structure."""

    GOLDEN_FILE = "scenario_batch_v090.json"

    def test_batch_response_has_results_array(self, load_golden):
        """Verify batch response has results array."""
        golden = load_golden(self.GOLDEN_FILE)

        assert "results" in golden
        assert isinstance(golden["results"], list)
        assert len(golden["results"]) > 0

    def test_batch_response_has_batch_id(self, load_golden):
        """Verify batch response has batch_id."""
        golden = load_golden(self.GOLDEN_FILE)

        assert "batch_id" in golden
        assert golden["batch_id"] is not None
        assert len(golden["batch_id"]) > 0

    def test_batch_response_has_summary(self, load_golden):
        """Verify batch response has summary section."""
        golden = load_golden(self.GOLDEN_FILE)

        assert "summary" in golden
        summary = golden["summary"]
        assert "total_items" in summary
        assert "ok_count" in summary
        assert "error_count" in summary
        assert "processing_time_ms" in summary

    def test_batch_response_has_portfolio_summary(self, load_golden):
        """Verify batch response has portfolio_summary."""
        golden = load_golden(self.GOLDEN_FILE)

        assert "portfolio_summary" in golden
        assert golden["portfolio_summary"] is not None

    def test_each_result_has_item_id(self, load_golden):
        """Verify each result has item_id."""
        golden = load_golden(self.GOLDEN_FILE)

        for result in golden["results"]:
            assert "item_id" in result
            assert result["item_id"] is not None

    def test_each_result_has_status(self, load_golden):
        """Verify each result has status (ok or error)."""
        golden = load_golden(self.GOLDEN_FILE)

        for result in golden["results"]:
            assert "status" in result
            assert result["status"] in ["ok", "error"]


class TestRegressionPortfolioSummary:
    """Regression tests for portfolio_summary calculations."""

    GOLDEN_FILE = "scenario_batch_v090.json"

    def test_portfolio_summary_has_required_fields(self, load_golden):
        """Verify portfolio_summary has all required fields."""
        golden = load_golden(self.GOLDEN_FILE)
        ps = golden["portfolio_summary"]

        assert "total_npv_pln" in ps
        assert "avg_npv_pln" in ps
        assert "avg_payback_years" in ps
        assert "portfolio_optimal_variant" in ps
        assert "variant_rankings" in ps

    def test_variant_rankings_sorted_by_total_npv(self, load_golden):
        """Verify variant_rankings are sorted by total_npv_pln descending."""
        golden = load_golden(self.GOLDEN_FILE)
        rankings = golden["portfolio_summary"]["variant_rankings"]

        for i in range(len(rankings) - 1):
            assert rankings[i]["total_npv_pln"] >= rankings[i + 1]["total_npv_pln"], (
                f"Rankings not sorted: {rankings[i]['total_npv_pln']} < "
                f"{rankings[i + 1]['total_npv_pln']}"
            )

    def test_portfolio_optimal_matches_first_ranking(self, load_golden):
        """Verify portfolio_optimal_variant matches first ranking."""
        golden = load_golden(self.GOLDEN_FILE)
        ps = golden["portfolio_summary"]

        first_ranking = ps["variant_rankings"][0]
        assert ps["portfolio_optimal_variant"] == first_ranking["variant"]

    def test_total_npv_from_recommended_variants(self, load_golden):
        """Verify total_npv_pln is sum of recommended variant NPVs."""
        golden = load_golden(self.GOLDEN_FILE)
        ps = golden["portfolio_summary"]

        # Calculate expected total from results
        expected_total = 0.0
        for result in golden["results"]:
            if result["status"] == "ok":
                response = result["response"]
                recommended = response["recommended_variant"]
                for v in response["variants"]:
                    if v["variant"] == recommended:
                        expected_total += v["npv_pln"]
                        break

        assert math.isclose(ps["total_npv_pln"], expected_total, abs_tol=1.0), (
            f"total_npv_pln {ps['total_npv_pln']:.2f} != expected {expected_total:.2f}"
        )

    def test_recommended_count_sums_to_ok_count(self, load_golden):
        """Verify recommended_count across variants sums to ok_count."""
        golden = load_golden(self.GOLDEN_FILE)
        rankings = golden["portfolio_summary"]["variant_rankings"]
        ok_count = golden["summary"]["ok_count"]

        total_recommended = sum(r["recommended_count"] for r in rankings)

        assert total_recommended == ok_count, (
            f"Total recommended {total_recommended} != ok_count {ok_count}"
        )


class TestRegressionBatchItemContent:
    """Regression tests for batch item response content."""

    GOLDEN_FILE = "scenario_batch_v090.json"

    def test_ok_results_have_response(self, load_golden):
        """Verify ok results have response object."""
        golden = load_golden(self.GOLDEN_FILE)

        for result in golden["results"]:
            if result["status"] == "ok":
                assert "response" in result
                assert result["response"] is not None

    def test_response_has_variants(self, load_golden):
        """Verify response has variants array."""
        golden = load_golden(self.GOLDEN_FILE)

        for result in golden["results"]:
            if result["status"] == "ok":
                response = result["response"]
                assert "variants" in response
                assert len(response["variants"]) > 0

    def test_response_has_recommended_variant(self, load_golden):
        """Verify response has recommended_variant."""
        golden = load_golden(self.GOLDEN_FILE)

        for result in golden["results"]:
            if result["status"] == "ok":
                response = result["response"]
                assert "recommended_variant" in response
                assert response["recommended_variant"] in ["small", "medium", "large"]


class TestRegressionSummaryTotals:
    """Regression tests for batch summary totals."""

    GOLDEN_FILE = "scenario_batch_v090.json"

    def test_total_items_matches_results_length(self, load_golden):
        """Verify total_items matches results array length."""
        golden = load_golden(self.GOLDEN_FILE)

        assert golden["summary"]["total_items"] == len(golden["results"])

    def test_ok_plus_error_equals_total(self, load_golden):
        """Verify ok_count + error_count = total_items."""
        golden = load_golden(self.GOLDEN_FILE)
        summary = golden["summary"]

        assert summary["ok_count"] + summary["error_count"] == summary["total_items"]

    def test_ok_count_matches_ok_results(self, load_golden):
        """Verify ok_count matches actual ok results."""
        golden = load_golden(self.GOLDEN_FILE)

        actual_ok = sum(1 for r in golden["results"] if r["status"] == "ok")
        assert golden["summary"]["ok_count"] == actual_ok

    def test_processing_time_is_positive(self, load_golden):
        """Verify processing_time_ms is positive."""
        golden = load_golden(self.GOLDEN_FILE)

        assert golden["summary"]["processing_time_ms"] > 0

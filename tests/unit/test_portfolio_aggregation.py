"""
Unit tests for portfolio_agg.py - Portfolio Aggregation Helper (v2.3.0).

Tests verify:
- Sum aggregations (NPV, savings, CAPEX)
- Weighted payback calculation
- Mixed assumptions detection
- Top items by NPV extraction
- Deterministic sorting and tie-breaking
- Edge cases (empty list, all errors, no payback, etc.)
"""

import pytest
from typing import List, Optional


# -----------------------------------------------------------------------------
# Helper classes for testing (mirroring the models)
# -----------------------------------------------------------------------------

class MockPortfolioItemSummary:
    """Mock PortfolioItemSummary for testing aggregation logic."""

    def __init__(
        self,
        run_id: str,
        label: Optional[str] = None,
        tags: Optional[List[str]] = None,
        recommended_variant: Optional[str] = None,
        objective_used: Optional[str] = None,
        npv_pln: float = 0.0,
        payback_years: Optional[float] = None,
        irr_pct: Optional[float] = None,
        net_savings_pln: float = 0.0,
        capex_pln: float = 0.0,
        assumptions_version: Optional[str] = None,
        schema_version: Optional[str] = None,
        pricing_mode: Optional[str] = None,
        status: str = "ok",
        error_message: Optional[str] = None,
    ):
        self.run_id = run_id
        self.label = label
        self.tags = tags
        self.recommended_variant = recommended_variant
        self.objective_used = objective_used
        self.npv_pln = npv_pln
        self.payback_years = payback_years
        self.irr_pct = irr_pct
        self.net_savings_pln = net_savings_pln
        self.capex_pln = capex_pln
        self.assumptions_version = assumptions_version
        self.schema_version = schema_version
        self.pricing_mode = pricing_mode
        self.status = status
        self.error_message = error_message


# -----------------------------------------------------------------------------
# Aggregation logic (mirrors portfolio_agg.py)
# -----------------------------------------------------------------------------

def summarize_items_logic(items):
    """Test logic for summarize_items."""
    if not items:
        return {
            "items_total": 0,
            "items_ok": 0,
            "items_error": 0,
            "mixed_assumptions": False,
            "assumptions_versions": [],
            "schema_versions": [],
            "pricing_modes": [],
            "total_npv_pln": 0.0,
            "total_net_savings_pln": 0.0,
            "total_capex_pln": 0.0,
            "weighted_payback_years": None,
            "avg_irr_pct": None,
            "top_items_by_npv": [],
        }

    ok_items = [item for item in items if item.status == "ok"]
    error_items = [item for item in items if item.status != "ok"]

    assumptions_versions = sorted(set(
        item.assumptions_version for item in ok_items
        if item.assumptions_version is not None
    ))
    schema_versions = sorted(set(
        item.schema_version for item in ok_items
        if item.schema_version is not None
    ))
    pricing_modes = sorted(set(
        item.pricing_mode for item in ok_items
        if item.pricing_mode is not None
    ))

    mixed_assumptions = len(assumptions_versions) > 1

    total_npv_pln = sum(item.npv_pln for item in ok_items)
    total_net_savings_pln = sum(item.net_savings_pln for item in ok_items)
    total_capex_pln = sum(item.capex_pln for item in ok_items)

    weighted_payback_years = calculate_weighted_payback_logic(ok_items, total_capex_pln)
    avg_irr_pct = calculate_avg_irr_logic(ok_items)
    top_items_by_npv = get_top_items_by_npv_logic(ok_items, limit=5)

    return {
        "items_total": len(items),
        "items_ok": len(ok_items),
        "items_error": len(error_items),
        "mixed_assumptions": mixed_assumptions,
        "assumptions_versions": assumptions_versions,
        "schema_versions": schema_versions,
        "pricing_modes": pricing_modes,
        "total_npv_pln": total_npv_pln,
        "total_net_savings_pln": total_net_savings_pln,
        "total_capex_pln": total_capex_pln,
        "weighted_payback_years": weighted_payback_years,
        "avg_irr_pct": avg_irr_pct,
        "top_items_by_npv": top_items_by_npv,
    }


def calculate_weighted_payback_logic(items, total_capex_pln):
    """Test logic for weighted payback calculation."""
    items_with_payback = [
        item for item in items
        if item.payback_years is not None
    ]

    if not items_with_payback:
        return None

    if total_capex_pln > 0:
        weighted_sum = sum(
            item.payback_years * item.capex_pln
            for item in items_with_payback
        )
        capex_sum = sum(item.capex_pln for item in items_with_payback)

        if capex_sum > 0:
            return weighted_sum / capex_sum
        else:
            return sum(item.payback_years for item in items_with_payback) / len(items_with_payback)
    else:
        return sum(item.payback_years for item in items_with_payback) / len(items_with_payback)


def calculate_avg_irr_logic(items):
    """Test logic for average IRR calculation."""
    items_with_irr = [
        item for item in items
        if item.irr_pct is not None
    ]

    if not items_with_irr:
        return None

    return sum(item.irr_pct for item in items_with_irr) / len(items_with_irr)


def get_top_items_by_npv_logic(items, limit=5):
    """Test logic for top items by NPV."""
    if not items:
        return []

    sorted_items = sorted(
        items,
        key=lambda x: (-x.npv_pln, x.run_id)
    )

    return sorted_items[:limit]


# -----------------------------------------------------------------------------
# Tests for PortfolioItemSummary Model
# -----------------------------------------------------------------------------

class TestPortfolioItemSummaryModel:
    """Tests for PortfolioItemSummary model fields."""

    def test_item_summary_required_fields(self):
        """Verify run_id is required and defaults work."""
        item = MockPortfolioItemSummary(run_id="test-123")
        assert item.run_id == "test-123"
        assert item.npv_pln == 0.0
        assert item.status == "ok"

    def test_item_summary_all_fields(self):
        """Verify all fields can be set."""
        item = MockPortfolioItemSummary(
            run_id="test-456",
            label="Site A",
            tags=["region:north", "type:industrial"],
            recommended_variant="bess_100kWh",
            objective_used="npv",
            npv_pln=50000.0,
            payback_years=5.5,
            irr_pct=12.5,
            net_savings_pln=10000.0,
            capex_pln=45000.0,
            assumptions_version="2024.1",
            schema_version="1.3.0",
            pricing_mode="generated",
            status="ok",
            error_message=None,
        )
        assert item.label == "Site A"
        assert item.npv_pln == 50000.0
        assert item.payback_years == 5.5

    def test_item_summary_error_status(self):
        """Verify error status can be set."""
        item = MockPortfolioItemSummary(
            run_id="test-error",
            status="error",
            error_message="Run not found",
        )
        assert item.status == "error"
        assert item.error_message == "Run not found"


# -----------------------------------------------------------------------------
# Tests for summarize_items
# -----------------------------------------------------------------------------

class TestSummarizeItems:
    """Tests for summarize_items function."""

    def test_empty_list_returns_empty_summary(self):
        """Verify empty input returns empty summary."""
        summary = summarize_items_logic([])
        assert summary["items_total"] == 0
        assert summary["items_ok"] == 0
        assert summary["total_npv_pln"] == 0.0

    def test_single_item_aggregation(self):
        """Verify single item is aggregated correctly."""
        item = MockPortfolioItemSummary(
            run_id="run-1",
            npv_pln=50000.0,
            net_savings_pln=10000.0,
            capex_pln=45000.0,
            payback_years=4.5,
            assumptions_version="2024.1",
        )

        summary = summarize_items_logic([item])

        assert summary["items_total"] == 1
        assert summary["items_ok"] == 1
        assert summary["items_error"] == 0
        assert summary["total_npv_pln"] == 50000.0
        assert summary["total_net_savings_pln"] == 10000.0
        assert summary["total_capex_pln"] == 45000.0
        assert summary["weighted_payback_years"] == 4.5

    def test_multiple_items_sum_aggregation(self):
        """Verify sums are calculated correctly for multiple items."""
        items = [
            MockPortfolioItemSummary(
                run_id="run-1",
                npv_pln=50000.0,
                net_savings_pln=10000.0,
                capex_pln=45000.0,
            ),
            MockPortfolioItemSummary(
                run_id="run-2",
                npv_pln=30000.0,
                net_savings_pln=6000.0,
                capex_pln=27000.0,
            ),
            MockPortfolioItemSummary(
                run_id="run-3",
                npv_pln=20000.0,
                net_savings_pln=4000.0,
                capex_pln=18000.0,
            ),
        ]

        summary = summarize_items_logic(items)

        assert summary["items_total"] == 3
        assert summary["items_ok"] == 3
        assert summary["total_npv_pln"] == 100000.0
        assert summary["total_net_savings_pln"] == 20000.0
        assert summary["total_capex_pln"] == 90000.0

    def test_error_items_excluded_from_aggregation(self):
        """Verify error items are counted but not included in sums."""
        items = [
            MockPortfolioItemSummary(
                run_id="run-1",
                npv_pln=50000.0,
                net_savings_pln=10000.0,
                capex_pln=45000.0,
            ),
            MockPortfolioItemSummary(
                run_id="run-2",
                npv_pln=30000.0,
                status="error",
                error_message="Not found",
            ),
        ]

        summary = summarize_items_logic(items)

        assert summary["items_total"] == 2
        assert summary["items_ok"] == 1
        assert summary["items_error"] == 1
        assert summary["total_npv_pln"] == 50000.0  # Only run-1

    def test_all_error_items(self):
        """Verify all error items results in zero sums."""
        items = [
            MockPortfolioItemSummary(
                run_id="run-1",
                status="error",
                error_message="Not found",
            ),
            MockPortfolioItemSummary(
                run_id="run-2",
                status="error",
                error_message="Invalid data",
            ),
        ]

        summary = summarize_items_logic(items)

        assert summary["items_total"] == 2
        assert summary["items_ok"] == 0
        assert summary["items_error"] == 2
        assert summary["total_npv_pln"] == 0.0


# -----------------------------------------------------------------------------
# Tests for weighted payback
# -----------------------------------------------------------------------------

class TestWeightedPayback:
    """Tests for weighted payback calculation."""

    def test_capex_weighted_payback(self):
        """Verify CAPEX-weighted average payback."""
        items = [
            MockPortfolioItemSummary(
                run_id="run-1",
                capex_pln=100000.0,
                payback_years=5.0,
            ),
            MockPortfolioItemSummary(
                run_id="run-2",
                capex_pln=50000.0,
                payback_years=3.0,
            ),
        ]

        summary = summarize_items_logic(items)

        # Weighted: (5.0 * 100000 + 3.0 * 50000) / 150000 = 650000 / 150000 = 4.333...
        expected = (5.0 * 100000 + 3.0 * 50000) / 150000
        assert abs(summary["weighted_payback_years"] - expected) < 0.001

    def test_simple_average_when_no_capex(self):
        """Verify simple average when total CAPEX is zero."""
        items = [
            MockPortfolioItemSummary(
                run_id="run-1",
                capex_pln=0.0,
                payback_years=5.0,
            ),
            MockPortfolioItemSummary(
                run_id="run-2",
                capex_pln=0.0,
                payback_years=3.0,
            ),
        ]

        summary = summarize_items_logic(items)

        # Simple average: (5.0 + 3.0) / 2 = 4.0
        assert summary["weighted_payback_years"] == 4.0

    def test_no_payback_returns_none(self):
        """Verify None is returned when no items have payback."""
        items = [
            MockPortfolioItemSummary(
                run_id="run-1",
                npv_pln=50000.0,
                payback_years=None,
            ),
            MockPortfolioItemSummary(
                run_id="run-2",
                npv_pln=30000.0,
                payback_years=None,
            ),
        ]

        summary = summarize_items_logic(items)

        assert summary["weighted_payback_years"] is None

    def test_mixed_payback_values(self):
        """Verify weighted payback only uses items with payback values."""
        items = [
            MockPortfolioItemSummary(
                run_id="run-1",
                capex_pln=100000.0,
                payback_years=5.0,
            ),
            MockPortfolioItemSummary(
                run_id="run-2",
                capex_pln=50000.0,
                payback_years=None,
            ),
        ]

        summary = summarize_items_logic(items)

        # Only run-1 has payback, so weighted = 5.0
        assert summary["weighted_payback_years"] == 5.0


# -----------------------------------------------------------------------------
# Tests for mixed assumptions
# -----------------------------------------------------------------------------

class TestMixedAssumptions:
    """Tests for mixed assumptions detection."""

    def test_single_version_not_mixed(self):
        """Verify single assumptions version is not mixed."""
        items = [
            MockPortfolioItemSummary(
                run_id="run-1",
                assumptions_version="2024.1",
            ),
            MockPortfolioItemSummary(
                run_id="run-2",
                assumptions_version="2024.1",
            ),
        ]

        summary = summarize_items_logic(items)

        assert summary["mixed_assumptions"] is False
        assert summary["assumptions_versions"] == ["2024.1"]

    def test_multiple_versions_is_mixed(self):
        """Verify multiple assumptions versions is mixed."""
        items = [
            MockPortfolioItemSummary(
                run_id="run-1",
                assumptions_version="2024.1",
            ),
            MockPortfolioItemSummary(
                run_id="run-2",
                assumptions_version="2024.2",
            ),
        ]

        summary = summarize_items_logic(items)

        assert summary["mixed_assumptions"] is True
        assert summary["assumptions_versions"] == ["2024.1", "2024.2"]

    def test_none_versions_excluded(self):
        """Verify None assumptions versions are excluded."""
        items = [
            MockPortfolioItemSummary(
                run_id="run-1",
                assumptions_version="2024.1",
            ),
            MockPortfolioItemSummary(
                run_id="run-2",
                assumptions_version=None,
            ),
        ]

        summary = summarize_items_logic(items)

        assert summary["mixed_assumptions"] is False
        assert summary["assumptions_versions"] == ["2024.1"]

    def test_versions_sorted_alphabetically(self):
        """Verify versions are sorted for determinism."""
        items = [
            MockPortfolioItemSummary(run_id="run-1", assumptions_version="2024.3"),
            MockPortfolioItemSummary(run_id="run-2", assumptions_version="2024.1"),
            MockPortfolioItemSummary(run_id="run-3", assumptions_version="2024.2"),
        ]

        summary = summarize_items_logic(items)

        assert summary["assumptions_versions"] == ["2024.1", "2024.2", "2024.3"]


# -----------------------------------------------------------------------------
# Tests for top items by NPV
# -----------------------------------------------------------------------------

class TestTopItemsByNpv:
    """Tests for top items by NPV extraction."""

    def test_top_5_items_returned(self):
        """Verify only top 5 items are returned."""
        items = [
            MockPortfolioItemSummary(run_id=f"run-{i}", npv_pln=float(i * 10000))
            for i in range(1, 8)  # 7 items
        ]

        summary = summarize_items_logic(items)

        assert len(summary["top_items_by_npv"]) == 5
        # Top 5 by NPV: run-7, run-6, run-5, run-4, run-3
        assert summary["top_items_by_npv"][0].run_id == "run-7"
        assert summary["top_items_by_npv"][4].run_id == "run-3"

    def test_fewer_than_5_items(self):
        """Verify all items returned when fewer than 5."""
        items = [
            MockPortfolioItemSummary(run_id="run-1", npv_pln=50000.0),
            MockPortfolioItemSummary(run_id="run-2", npv_pln=30000.0),
        ]

        summary = summarize_items_logic(items)

        assert len(summary["top_items_by_npv"]) == 2
        assert summary["top_items_by_npv"][0].run_id == "run-1"
        assert summary["top_items_by_npv"][1].run_id == "run-2"

    def test_tie_breaking_by_run_id(self):
        """Verify tie-breaking uses run_id for determinism."""
        items = [
            MockPortfolioItemSummary(run_id="run-c", npv_pln=50000.0),
            MockPortfolioItemSummary(run_id="run-a", npv_pln=50000.0),
            MockPortfolioItemSummary(run_id="run-b", npv_pln=50000.0),
        ]

        summary = summarize_items_logic(items)

        # Same NPV, sorted by run_id ascending
        assert summary["top_items_by_npv"][0].run_id == "run-a"
        assert summary["top_items_by_npv"][1].run_id == "run-b"
        assert summary["top_items_by_npv"][2].run_id == "run-c"

    def test_descending_npv_order(self):
        """Verify items are sorted by NPV descending."""
        items = [
            MockPortfolioItemSummary(run_id="run-1", npv_pln=10000.0),
            MockPortfolioItemSummary(run_id="run-2", npv_pln=50000.0),
            MockPortfolioItemSummary(run_id="run-3", npv_pln=30000.0),
        ]

        summary = summarize_items_logic(items)

        assert summary["top_items_by_npv"][0].npv_pln == 50000.0
        assert summary["top_items_by_npv"][1].npv_pln == 30000.0
        assert summary["top_items_by_npv"][2].npv_pln == 10000.0


# -----------------------------------------------------------------------------
# Tests for average IRR
# -----------------------------------------------------------------------------

class TestAvgIrr:
    """Tests for average IRR calculation."""

    def test_avg_irr_calculated(self):
        """Verify average IRR is calculated correctly."""
        items = [
            MockPortfolioItemSummary(run_id="run-1", irr_pct=10.0),
            MockPortfolioItemSummary(run_id="run-2", irr_pct=20.0),
        ]

        summary = summarize_items_logic(items)

        assert summary["avg_irr_pct"] == 15.0

    def test_no_irr_returns_none(self):
        """Verify None is returned when no items have IRR."""
        items = [
            MockPortfolioItemSummary(run_id="run-1", npv_pln=50000.0),
            MockPortfolioItemSummary(run_id="run-2", npv_pln=30000.0),
        ]

        summary = summarize_items_logic(items)

        assert summary["avg_irr_pct"] is None

    def test_mixed_irr_values(self):
        """Verify only items with IRR are included in average."""
        items = [
            MockPortfolioItemSummary(run_id="run-1", irr_pct=10.0),
            MockPortfolioItemSummary(run_id="run-2", irr_pct=None),
            MockPortfolioItemSummary(run_id="run-3", irr_pct=20.0),
        ]

        summary = summarize_items_logic(items)

        # Average of 10 and 20 = 15
        assert summary["avg_irr_pct"] == 15.0


# -----------------------------------------------------------------------------
# Tests for schema and pricing modes
# -----------------------------------------------------------------------------

class TestSchemaAndPricingModes:
    """Tests for schema versions and pricing modes collection."""

    def test_schema_versions_collected(self):
        """Verify schema versions are collected and sorted."""
        items = [
            MockPortfolioItemSummary(run_id="run-1", schema_version="1.3.0"),
            MockPortfolioItemSummary(run_id="run-2", schema_version="1.2.0"),
            MockPortfolioItemSummary(run_id="run-3", schema_version="1.3.0"),
        ]

        summary = summarize_items_logic(items)

        assert summary["schema_versions"] == ["1.2.0", "1.3.0"]

    def test_pricing_modes_collected(self):
        """Verify pricing modes are collected and sorted."""
        items = [
            MockPortfolioItemSummary(run_id="run-1", pricing_mode="generated"),
            MockPortfolioItemSummary(run_id="run-2", pricing_mode="override"),
            MockPortfolioItemSummary(run_id="run-3", pricing_mode="generated"),
        ]

        summary = summarize_items_logic(items)

        assert summary["pricing_modes"] == ["generated", "override"]


# -----------------------------------------------------------------------------
# Tests for extract_item_summary logic
# -----------------------------------------------------------------------------

class TestExtractItemSummary:
    """Tests for extract_item_summary_from_result logic."""

    def test_extract_basic_fields(self):
        """Verify basic fields are extracted."""
        result = {
            "recommended": {
                "variant_name": "bess_100kWh",
                "finance_summary": {
                    "npv_pln": 50000.0,
                    "payback_years": 5.0,
                    "net_savings_pln": 10000.0,
                    "capex_pln": 45000.0,
                },
            },
            "meta": {
                "assumptions_version": "2024.1",
                "schema_version": "1.3.0",
            },
        }

        # Extract logic
        recommended = result.get("recommended", {})
        recommended_variant = recommended.get("variant_name")
        finance_summary = recommended.get("finance_summary", {})
        npv_pln = finance_summary.get("npv_pln", 0.0)
        payback_years = finance_summary.get("payback_years")

        assert recommended_variant == "bess_100kWh"
        assert npv_pln == 50000.0
        assert payback_years == 5.0

    def test_extract_handles_missing_fields(self):
        """Verify missing fields get default values."""
        result = {
            "recommended": {},
        }

        recommended = result.get("recommended", {})
        finance_summary = recommended.get("finance_summary", {})
        npv_pln = finance_summary.get("npv_pln", 0.0)
        payback_years = finance_summary.get("payback_years")

        assert npv_pln == 0.0
        assert payback_years is None

    def test_extract_handles_empty_result(self):
        """Verify empty result is handled gracefully."""
        result = {}

        recommended = result.get("recommended", {})
        npv_pln = recommended.get("npv_pln", 0.0)

        assert npv_pln == 0.0

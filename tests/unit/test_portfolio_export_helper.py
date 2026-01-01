"""
Unit tests for portfolio_export_helper (v2.3.0 PR4).

Tests verify:
- CSV export format and content
- ZIP export structure and files
- Summary-only CSV export
"""

import pytest
import json
import zipfile
import io


# Mock data for testing
def _mock_portfolio_summary():
    """Create a mock portfolio summary dict."""
    return {
        "items_total": 3,
        "items_ok": 2,
        "items_error": 1,
        "mixed_assumptions": False,
        "assumptions_versions": ["v1.0.0"],
        "schema_versions": ["1.0"],
        "pricing_modes": ["generated"],
        "total_npv_pln": 150000.0,
        "total_net_savings_pln": 50000.0,
        "total_capex_pln": 100000.0,
        "weighted_payback_years": 2.5,
        "avg_irr_pct": 15.5,
        "top_items_by_npv": [],
    }


def _mock_portfolio_items():
    """Create mock portfolio items list."""
    return [
        {
            "run_id": "run-001",
            "label": "Site A",
            "status": "ok",
            "recommended_variant": "medium",
            "objective_used": "npv",
            "npv_pln": 80000.0,
            "payback_years": 2.0,
            "irr_pct": 18.0,
            "net_savings_pln": 30000.0,
            "capex_pln": 60000.0,
            "assumptions_version": "v1.0.0",
            "schema_version": "1.0",
            "pricing_mode": "generated",
            "tags": ["region:north", "type:industrial"],
            "error_message": None,
        },
        {
            "run_id": "run-002",
            "label": "Site B",
            "status": "ok",
            "recommended_variant": "large",
            "objective_used": "npv",
            "npv_pln": 70000.0,
            "payback_years": 3.0,
            "irr_pct": 13.0,
            "net_savings_pln": 20000.0,
            "capex_pln": 40000.0,
            "assumptions_version": "v1.0.0",
            "schema_version": "1.0",
            "pricing_mode": "generated",
            "tags": ["region:south"],
            "error_message": None,
        },
    ]


# =============================================================================
# TestExportPortfolioCsv
# =============================================================================

class TestExportPortfolioCsv:
    """Tests for export_portfolio_to_csv function."""

    def test_csv_export_returns_string(self):
        """CSV export should return a string."""
        import sys
        sys.path.insert(0, "services/bess-dispatch")
        from portfolio_export_helper import export_portfolio_to_csv

        result = export_portfolio_to_csv(
            portfolio_summary=_mock_portfolio_summary(),
            portfolio_items=_mock_portfolio_items(),
        )

        assert isinstance(result, str)

    def test_csv_export_has_header_row(self):
        """CSV export should have header row."""
        import sys
        sys.path.insert(0, "services/bess-dispatch")
        from portfolio_export_helper import export_portfolio_to_csv

        result = export_portfolio_to_csv(
            portfolio_summary=_mock_portfolio_summary(),
            portfolio_items=_mock_portfolio_items(),
        )

        lines = result.strip().split("\n")
        header = lines[0].lower()
        assert "run_id" in header
        assert "npv_pln" in header
        assert "status" in header

    def test_csv_export_has_data_rows(self):
        """CSV export should have data rows for each item."""
        import sys
        sys.path.insert(0, "services/bess-dispatch")
        from portfolio_export_helper import export_portfolio_to_csv

        result = export_portfolio_to_csv(
            portfolio_summary=_mock_portfolio_summary(),
            portfolio_items=_mock_portfolio_items(),
        )

        lines = result.strip().split("\n")
        # Header + 2 items
        assert len(lines) == 3

    def test_csv_export_contains_run_ids(self):
        """CSV export should contain run_ids."""
        import sys
        sys.path.insert(0, "services/bess-dispatch")
        from portfolio_export_helper import export_portfolio_to_csv

        result = export_portfolio_to_csv(
            portfolio_summary=_mock_portfolio_summary(),
            portfolio_items=_mock_portfolio_items(),
        )

        assert "run-001" in result
        assert "run-002" in result

    def test_csv_export_contains_labels(self):
        """CSV export should contain labels."""
        import sys
        sys.path.insert(0, "services/bess-dispatch")
        from portfolio_export_helper import export_portfolio_to_csv

        result = export_portfolio_to_csv(
            portfolio_summary=_mock_portfolio_summary(),
            portfolio_items=_mock_portfolio_items(),
        )

        assert "Site A" in result
        assert "Site B" in result

    def test_csv_export_empty_items_has_header_only(self):
        """CSV export with empty items should have header only."""
        import sys
        sys.path.insert(0, "services/bess-dispatch")
        from portfolio_export_helper import export_portfolio_to_csv

        result = export_portfolio_to_csv(
            portfolio_summary=_mock_portfolio_summary(),
            portfolio_items=[],
        )

        lines = result.strip().split("\n")
        assert len(lines) == 1  # Header only

    def test_csv_export_tags_joined(self):
        """CSV export should join tags with comma."""
        import sys
        sys.path.insert(0, "services/bess-dispatch")
        from portfolio_export_helper import export_portfolio_to_csv

        result = export_portfolio_to_csv(
            portfolio_summary=_mock_portfolio_summary(),
            portfolio_items=_mock_portfolio_items(),
        )

        # Tags should be comma-separated within the cell
        assert "region:north" in result


# =============================================================================
# TestExportPortfolioZip
# =============================================================================

class TestExportPortfolioZip:
    """Tests for export_portfolio_to_zip function."""

    def test_zip_export_returns_bytes(self):
        """ZIP export should return bytes."""
        import sys
        sys.path.insert(0, "services/bess-dispatch")
        from portfolio_export_helper import export_portfolio_to_zip

        result = export_portfolio_to_zip(
            portfolio_summary=_mock_portfolio_summary(),
            portfolio_items=_mock_portfolio_items(),
            source_id="test-123",
            source_type="job",
        )

        assert isinstance(result, bytes)

    def test_zip_export_is_valid_zipfile(self):
        """ZIP export should be a valid zip file."""
        import sys
        sys.path.insert(0, "services/bess-dispatch")
        from portfolio_export_helper import export_portfolio_to_zip

        result = export_portfolio_to_zip(
            portfolio_summary=_mock_portfolio_summary(),
            portfolio_items=_mock_portfolio_items(),
            source_id="test-123",
            source_type="job",
        )

        zip_buffer = io.BytesIO(result)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            names = zf.namelist()
            assert len(names) >= 3

    def test_zip_export_contains_portfolio_json(self):
        """ZIP export should contain portfolio JSON file."""
        import sys
        sys.path.insert(0, "services/bess-dispatch")
        from portfolio_export_helper import export_portfolio_to_zip

        result = export_portfolio_to_zip(
            portfolio_summary=_mock_portfolio_summary(),
            portfolio_items=_mock_portfolio_items(),
            source_id="test-123",
            source_type="job",
        )

        zip_buffer = io.BytesIO(result)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            names = zf.namelist()
            assert any("portfolio.json" in name for name in names)

    def test_zip_export_contains_items_csv(self):
        """ZIP export should contain items CSV file."""
        import sys
        sys.path.insert(0, "services/bess-dispatch")
        from portfolio_export_helper import export_portfolio_to_zip

        result = export_portfolio_to_zip(
            portfolio_summary=_mock_portfolio_summary(),
            portfolio_items=_mock_portfolio_items(),
            source_id="test-123",
            source_type="job",
        )

        zip_buffer = io.BytesIO(result)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            names = zf.namelist()
            assert any("items.csv" in name for name in names)

    def test_zip_export_contains_summary_csv(self):
        """ZIP export should contain summary CSV file."""
        import sys
        sys.path.insert(0, "services/bess-dispatch")
        from portfolio_export_helper import export_portfolio_to_zip

        result = export_portfolio_to_zip(
            portfolio_summary=_mock_portfolio_summary(),
            portfolio_items=_mock_portfolio_items(),
            source_id="test-123",
            source_type="job",
        )

        zip_buffer = io.BytesIO(result)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            names = zf.namelist()
            assert any("summary.csv" in name for name in names)

    def test_zip_export_contains_metadata(self):
        """ZIP export should contain metadata.json."""
        import sys
        sys.path.insert(0, "services/bess-dispatch")
        from portfolio_export_helper import export_portfolio_to_zip

        result = export_portfolio_to_zip(
            portfolio_summary=_mock_portfolio_summary(),
            portfolio_items=_mock_portfolio_items(),
            source_id="test-123",
            source_type="job",
        )

        zip_buffer = io.BytesIO(result)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            assert "metadata.json" in zf.namelist()

    def test_zip_export_metadata_has_source_info(self):
        """ZIP metadata should have source info."""
        import sys
        sys.path.insert(0, "services/bess-dispatch")
        from portfolio_export_helper import export_portfolio_to_zip

        result = export_portfolio_to_zip(
            portfolio_summary=_mock_portfolio_summary(),
            portfolio_items=_mock_portfolio_items(),
            source_id="test-123",
            source_type="job",
        )

        zip_buffer = io.BytesIO(result)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            metadata = json.loads(zf.read("metadata.json"))
            assert metadata["source_id"] == "test-123"
            assert metadata["source_type"] == "job"

    def test_zip_export_portfolio_json_valid(self):
        """ZIP portfolio.json should be valid JSON."""
        import sys
        sys.path.insert(0, "services/bess-dispatch")
        from portfolio_export_helper import export_portfolio_to_zip

        result = export_portfolio_to_zip(
            portfolio_summary=_mock_portfolio_summary(),
            portfolio_items=_mock_portfolio_items(),
            source_id="test-123",
            source_type="job",
        )

        zip_buffer = io.BytesIO(result)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            for name in zf.namelist():
                if "portfolio.json" in name:
                    content = zf.read(name)
                    data = json.loads(content)
                    assert "summary" in data
                    assert "items" in data


# =============================================================================
# TestExportSummaryOnlyCsv
# =============================================================================

class TestExportSummaryOnlyCsv:
    """Tests for export_summary_only_csv function."""

    def test_summary_csv_returns_string(self):
        """Summary CSV should return a string."""
        import sys
        sys.path.insert(0, "services/bess-dispatch")
        from portfolio_export_helper import export_summary_only_csv

        result = export_summary_only_csv(_mock_portfolio_summary())

        assert isinstance(result, str)

    def test_summary_csv_has_metric_value_columns(self):
        """Summary CSV should have metric and value columns."""
        import sys
        sys.path.insert(0, "services/bess-dispatch")
        from portfolio_export_helper import export_summary_only_csv

        result = export_summary_only_csv(_mock_portfolio_summary())

        lines = result.strip().split("\n")
        header = lines[0].lower()
        assert "metric" in header
        assert "value" in header

    def test_summary_csv_contains_totals(self):
        """Summary CSV should contain total values."""
        import sys
        sys.path.insert(0, "services/bess-dispatch")
        from portfolio_export_helper import export_summary_only_csv

        result = export_summary_only_csv(_mock_portfolio_summary())

        assert "total_npv_pln" in result
        assert "150000" in result

    def test_summary_csv_contains_counts(self):
        """Summary CSV should contain item counts."""
        import sys
        sys.path.insert(0, "services/bess-dispatch")
        from portfolio_export_helper import export_summary_only_csv

        result = export_summary_only_csv(_mock_portfolio_summary())

        assert "items_total" in result
        assert "items_ok" in result
        assert "items_error" in result


# =============================================================================
# TestExportPortfolioSummaryJson
# =============================================================================

class TestExportPortfolioSummaryJson:
    """Tests for export_portfolio_summary_to_json function."""

    def test_json_export_returns_string(self):
        """JSON export should return a string."""
        import sys
        sys.path.insert(0, "services/bess-dispatch")
        from portfolio_export_helper import export_portfolio_summary_to_json

        result = export_portfolio_summary_to_json(
            portfolio_summary=_mock_portfolio_summary(),
            portfolio_items=_mock_portfolio_items(),
            source_id="test-123",
            source_type="job",
        )

        assert isinstance(result, str)

    def test_json_export_is_valid_json(self):
        """JSON export should be valid JSON."""
        import sys
        sys.path.insert(0, "services/bess-dispatch")
        from portfolio_export_helper import export_portfolio_summary_to_json

        result = export_portfolio_summary_to_json(
            portfolio_summary=_mock_portfolio_summary(),
            portfolio_items=_mock_portfolio_items(),
            source_id="test-123",
            source_type="job",
        )

        data = json.loads(result)
        assert "summary" in data
        assert "items" in data

    def test_json_export_has_source_info(self):
        """JSON export should have source info."""
        import sys
        sys.path.insert(0, "services/bess-dispatch")
        from portfolio_export_helper import export_portfolio_summary_to_json

        result = export_portfolio_summary_to_json(
            portfolio_summary=_mock_portfolio_summary(),
            portfolio_items=_mock_portfolio_items(),
            source_id="test-123",
            source_type="job",
        )

        data = json.loads(result)
        assert data["source_id"] == "test-123"
        assert data["source_type"] == "job"

    def test_json_export_has_exported_at(self):
        """JSON export should have exported_at timestamp."""
        import sys
        sys.path.insert(0, "services/bess-dispatch")
        from portfolio_export_helper import export_portfolio_summary_to_json

        result = export_portfolio_summary_to_json(
            portfolio_summary=_mock_portfolio_summary(),
            portfolio_items=_mock_portfolio_items(),
        )

        data = json.loads(result)
        assert "exported_at" in data

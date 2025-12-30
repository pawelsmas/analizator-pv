"""
Unit tests for v1.2.0 job export functionality.

Tests verify:
- Per-item enrichment with request_summary
- JSON export with enriched items
- CSV export with flat metrics
- ZIP export with combined formats
"""
import json
import os
import sys
import zipfile
import io

import pytest

# Add services directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "bess-dispatch"))

from job_export_helper import (
    enrich_item_result,
    build_enriched_results,
    export_job_to_json,
    export_job_to_csv,
    export_job_to_zip,
)


# Sample test data
SAMPLE_ITEM_RESULT = {
    "item_id": "scenario_A",
    "status": "ok",
    "response": {
        "recommended_variant": "medium",
        "variants": [
            {
                "variant": "small",
                "npv_pln": 10000.0,
                "simple_payback_years": 8.5,
                "power_kw": 50,
                "energy_kwh": 100,
                "capex_pln": 85000.0,
                "savings_breakdown": {"net_savings_pln": 10000.0},
            },
            {
                "variant": "medium",
                "npv_pln": 25000.0,
                "simple_payback_years": 6.2,
                "power_kw": 100,
                "energy_kwh": 200,
                "capex_pln": 155000.0,
                "savings_breakdown": {"net_savings_pln": 25000.0},
            },
            {
                "variant": "large",
                "npv_pln": 15000.0,
                "simple_payback_years": 9.1,
                "power_kw": 150,
                "energy_kwh": 300,
                "capex_pln": 225000.0,
                "savings_breakdown": {"net_savings_pln": 15000.0},
            },
        ],
    },
}

SAMPLE_ITEM_REQUEST = {
    "item_id": "scenario_A",
    "request": {
        "mode": "stacked",
        "load_kw": [50, 60, 70, 80, 90, 100] * 4,
        "pv_generation_kw": [0, 0, 0, 5, 20, 40] * 4,
        "energy_price_pln_kwh": 0.8,
        "peak_limit_kw": 80,
    },
}

SAMPLE_JOB = {
    "job_id": "test-job-123",
    "batch_id": "test-batch",
    "status": "done",
    "created_at": "2025-12-30T10:00:00Z",
    "updated_at": "2025-12-30T10:01:00Z",
    "items_total": 2,
    "items_done": 2,
    "error_count": 0,
    "request": {
        "items": [
            SAMPLE_ITEM_REQUEST,
            {
                "item_id": "scenario_B",
                "request": {
                    "mode": "peak_shaving",
                    "load_kw": [100, 120, 140],
                    "pv_generation_kw": [0, 0, 0],
                    "energy_price_pln_kwh": 0.9,
                    "peak_limit_kw": 100,
                },
            },
        ],
    },
    "result": {
        "results": [
            SAMPLE_ITEM_RESULT,
            {
                "item_id": "scenario_B",
                "status": "error",
                "error": "Invalid load profile",
            },
        ],
        "summary": {
            "total_items": 2,
            "ok_count": 1,
            "error_count": 1,
            "processing_time_ms": 150,
        },
        "portfolio_summary": {
            "total_npv_pln": 25000.0,
            "avg_npv_pln": 25000.0,
            "portfolio_optimal_variant": "medium",
        },
    },
}


class TestEnrichItemResult:
    """Test per-item enrichment."""

    def test_enriches_ok_item_with_request_summary(self):
        """Verify request_summary is added from item_request."""
        enriched = enrich_item_result(SAMPLE_ITEM_RESULT, SAMPLE_ITEM_REQUEST)

        assert "request_summary" in enriched
        summary = enriched["request_summary"]
        assert summary["mode"] == "stacked"
        assert summary["load_points"] == 24
        assert summary["pv_points"] == 24
        assert summary["energy_price_pln_kwh"] == 0.8
        assert summary["peak_limit_kw"] == 80

    def test_enriches_ok_item_with_recommended_metrics(self):
        """Verify recommended variant metrics are extracted."""
        enriched = enrich_item_result(SAMPLE_ITEM_RESULT, SAMPLE_ITEM_REQUEST)

        assert enriched["recommended_npv_pln"] == 25000.0
        assert enriched["recommended_payback_years"] == 6.2
        assert enriched["recommended_power_kw"] == 100
        assert enriched["recommended_energy_kwh"] == 200
        assert enriched["recommended_capex_pln"] == 155000.0
        assert enriched["recommended_net_savings_pln"] == 25000.0

    def test_error_item_has_request_summary_but_no_metrics(self):
        """Verify error items still get request_summary but no metrics."""
        error_result = {
            "item_id": "scenario_B",
            "status": "error",
            "error": "Invalid input",
        }
        error_request = {
            "item_id": "scenario_B",
            "request": {
                "mode": "peak_shaving",
                "load_kw": [100, 120],
                "pv_generation_kw": [0, 0],
            },
        }

        enriched = enrich_item_result(error_result, error_request)

        assert "request_summary" in enriched
        assert enriched["request_summary"]["mode"] == "peak_shaving"
        assert enriched.get("recommended_npv_pln") is None

    def test_missing_request_handled_gracefully(self):
        """Verify missing request doesn't crash."""
        enriched = enrich_item_result(SAMPLE_ITEM_RESULT, {})

        assert enriched["item_id"] == "scenario_A"
        assert enriched["status"] == "ok"


class TestBuildEnrichedResults:
    """Test building enriched results list from job data."""

    def test_builds_enriched_list(self):
        """Verify all items are enriched."""
        enriched_items = build_enriched_results(SAMPLE_JOB)

        assert len(enriched_items) == 2
        assert enriched_items[0]["item_id"] == "scenario_A"
        assert enriched_items[1]["item_id"] == "scenario_B"

    def test_matches_request_to_result_by_item_id(self):
        """Verify request is matched to result by item_id."""
        enriched_items = build_enriched_results(SAMPLE_JOB)

        # First item should have stacked mode from request
        assert enriched_items[0]["request_summary"]["mode"] == "stacked"
        # Second item should have peak_shaving mode
        assert enriched_items[1]["request_summary"]["mode"] == "peak_shaving"

    def test_handles_empty_results(self):
        """Verify empty results handled gracefully."""
        empty_job = {"result": {"results": []}, "request": {"items": []}}
        enriched_items = build_enriched_results(empty_job)

        assert len(enriched_items) == 0


class TestExportJobToJSON:
    """Test JSON export functionality."""

    def test_json_has_required_fields(self):
        """Verify JSON export has all required fields."""
        json_str = export_job_to_json(SAMPLE_JOB)
        data = json.loads(json_str)

        assert data["job_id"] == "test-job-123"
        assert data["batch_id"] == "test-batch"
        assert data["status"] == "done"
        assert data["items_total"] == 2
        assert data["items_done"] == 2
        assert data["error_count"] == 0
        assert "exported_at" in data

    def test_json_has_enriched_items_by_default(self):
        """Verify items are enriched by default."""
        json_str = export_job_to_json(SAMPLE_JOB, enriched=True)
        data = json.loads(json_str)

        assert "items" in data
        assert len(data["items"]) == 2
        assert "request_summary" in data["items"][0]

    def test_json_has_raw_items_when_not_enriched(self):
        """Verify raw items when enriched=False."""
        json_str = export_job_to_json(SAMPLE_JOB, enriched=False)
        data = json.loads(json_str)

        assert "items" in data
        # Raw items don't have request_summary
        assert "request_summary" not in data["items"][0]

    def test_json_includes_summary_and_portfolio(self):
        """Verify summary and portfolio_summary are included."""
        json_str = export_job_to_json(SAMPLE_JOB)
        data = json.loads(json_str)

        assert "summary" in data
        assert data["summary"]["total_items"] == 2
        assert "portfolio_summary" in data
        assert data["portfolio_summary"]["portfolio_optimal_variant"] == "medium"


class TestExportJobToCSV:
    """Test CSV export functionality."""

    def test_csv_has_header_row(self):
        """Verify CSV has correct header row."""
        csv_str = export_job_to_csv(SAMPLE_JOB)
        lines = csv_str.strip().split("\n")

        assert len(lines) >= 1
        header = lines[0]
        assert "item_id" in header
        assert "status" in header
        assert "recommended_variant" in header
        assert "recommended_npv_pln" in header

    def test_csv_has_data_rows(self):
        """Verify CSV has data rows for each item."""
        csv_str = export_job_to_csv(SAMPLE_JOB)
        lines = csv_str.strip().split("\n")

        # Header + 2 data rows
        assert len(lines) == 3

    def test_csv_ok_item_has_metrics(self):
        """Verify ok item has metrics in CSV."""
        csv_str = export_job_to_csv(SAMPLE_JOB)

        assert "scenario_A" in csv_str
        assert "ok" in csv_str
        assert "medium" in csv_str  # recommended_variant
        assert "25000" in csv_str  # npv_pln

    def test_csv_error_item_has_error(self):
        """Verify error item has error message."""
        csv_str = export_job_to_csv(SAMPLE_JOB)

        assert "scenario_B" in csv_str
        assert "error" in csv_str
        assert "Invalid load profile" in csv_str

    def test_csv_empty_job_has_header_only(self):
        """Verify empty job returns header only."""
        empty_job = {"result": {"results": []}, "request": {"items": []}}
        csv_str = export_job_to_csv(empty_job)

        assert "item_id,status,error" in csv_str


class TestExportJobToZIP:
    """Test ZIP export functionality."""

    def test_zip_contains_json_file(self):
        """Verify ZIP contains JSON file."""
        zip_bytes = export_job_to_zip(SAMPLE_JOB)

        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            names = zf.namelist()
            json_files = [n for n in names if n.endswith(".json") and n != "metadata.json"]
            assert len(json_files) >= 1

    def test_zip_contains_csv_file(self):
        """Verify ZIP contains CSV file."""
        zip_bytes = export_job_to_zip(SAMPLE_JOB)

        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            names = zf.namelist()
            csv_files = [n for n in names if n.endswith(".csv")]
            assert len(csv_files) >= 1

    def test_zip_contains_metadata(self):
        """Verify ZIP contains metadata.json."""
        zip_bytes = export_job_to_zip(SAMPLE_JOB)

        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            assert "metadata.json" in zf.namelist()

            metadata = json.loads(zf.read("metadata.json"))
            assert metadata["job_id"] == "test-job-123"
            assert "exported_at" in metadata
            assert "files" in metadata

    def test_zip_json_is_valid(self):
        """Verify JSON file in ZIP is valid JSON."""
        zip_bytes = export_job_to_zip(SAMPLE_JOB)

        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            json_files = [n for n in zf.namelist() if n.endswith("_results.json")]
            assert len(json_files) == 1

            content = zf.read(json_files[0])
            data = json.loads(content)
            assert data["job_id"] == "test-job-123"

    def test_zip_csv_is_valid(self):
        """Verify CSV file in ZIP has data."""
        zip_bytes = export_job_to_zip(SAMPLE_JOB)

        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            csv_files = [n for n in zf.namelist() if n.endswith("_summary.csv")]
            assert len(csv_files) == 1

            content = zf.read(csv_files[0]).decode("utf-8")
            assert "item_id" in content
            assert "scenario_A" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

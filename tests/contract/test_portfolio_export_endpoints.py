"""
Contract tests for Portfolio Export endpoints (v2.3.0 PR4).

Tests verify:
- GET /api/bess-dispatch/jobs/{job_id}/portfolio/export/csv
- GET /api/bess-dispatch/jobs/{job_id}/portfolio/export/zip
- POST /api/bess-dispatch/portfolio/summary/export/csv
- POST /api/bess-dispatch/portfolio/summary/export/zip
"""

import pytest
import uuid
import zipfile
import io
from ._api import post_json, get_json, DEFAULT_BASE_URL
import requests


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


def _create_sizing_batch_job():
    """Create a sizing batch job and wait for completion."""
    payload = {
        "wait": True,
        "fail_fast": False,
        "items": [
            {"item_id": "EXP_A", "request": _base_req()},
            {"item_id": "EXP_B", "request": _base_req()},
        ]
    }
    resp = post_json("/api/bess-dispatch/jobs/sizing-batch", payload)
    return resp["job_id"]


def _create_sizing_run():
    """Create a sizing run and return run_id."""
    request = _base_req()
    resp = post_json("/sizing", request)
    return resp.get("meta", {}).get("run_id") or resp.get("cache_info", {}).get("run_id")


# =============================================================================
# TestJobPortfolioExportCsv
# =============================================================================

class TestJobPortfolioExportCsv:
    """Tests for GET /api/bess-dispatch/jobs/{job_id}/portfolio/export/csv."""

    def test_export_csv_returns_200(self):
        """Export CSV should return 200."""
        job_id = _create_sizing_batch_job()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/jobs/{job_id}/portfolio/export/csv"
        resp = requests.get(url)

        assert resp.status_code == 200

    def test_export_csv_content_type(self):
        """Export CSV should have text/csv content type."""
        job_id = _create_sizing_batch_job()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/jobs/{job_id}/portfolio/export/csv"
        resp = requests.get(url)

        assert "text/csv" in resp.headers.get("Content-Type", "")

    def test_export_csv_has_content_disposition(self):
        """Export CSV should have Content-Disposition header."""
        job_id = _create_sizing_batch_job()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/jobs/{job_id}/portfolio/export/csv"
        resp = requests.get(url)

        assert "Content-Disposition" in resp.headers
        assert "attachment" in resp.headers["Content-Disposition"]
        assert ".csv" in resp.headers["Content-Disposition"]

    def test_export_csv_has_header_row(self):
        """Export CSV should have header row with column names."""
        job_id = _create_sizing_batch_job()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/jobs/{job_id}/portfolio/export/csv"
        resp = requests.get(url)

        lines = resp.text.strip().split("\n")
        assert len(lines) >= 1
        header = lines[0].lower()
        assert "run_id" in header
        assert "npv_pln" in header
        assert "status" in header

    def test_export_csv_has_data_rows(self):
        """Export CSV should have data rows for each item."""
        job_id = _create_sizing_batch_job()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/jobs/{job_id}/portfolio/export/csv"
        resp = requests.get(url)

        lines = resp.text.strip().split("\n")
        # Header + 2 items
        assert len(lines) >= 3

    def test_export_csv_404_for_missing_job(self):
        """Export CSV should return 404 for missing job."""
        fake_id = str(uuid.uuid4())
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/jobs/{fake_id}/portfolio/export/csv"
        resp = requests.get(url)

        assert resp.status_code == 404


# =============================================================================
# TestJobPortfolioExportZip
# =============================================================================

class TestJobPortfolioExportZip:
    """Tests for GET /api/bess-dispatch/jobs/{job_id}/portfolio/export/zip."""

    def test_export_zip_returns_200(self):
        """Export ZIP should return 200."""
        job_id = _create_sizing_batch_job()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/jobs/{job_id}/portfolio/export/zip"
        resp = requests.get(url)

        assert resp.status_code == 200

    def test_export_zip_content_type(self):
        """Export ZIP should have application/zip content type."""
        job_id = _create_sizing_batch_job()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/jobs/{job_id}/portfolio/export/zip"
        resp = requests.get(url)

        assert "application/zip" in resp.headers.get("Content-Type", "")

    def test_export_zip_is_valid_zipfile(self):
        """Export ZIP should be a valid zip file."""
        job_id = _create_sizing_batch_job()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/jobs/{job_id}/portfolio/export/zip"
        resp = requests.get(url)

        zip_buffer = io.BytesIO(resp.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            names = zf.namelist()
            assert len(names) >= 3  # portfolio.json, items.csv, summary.csv, metadata.json

    def test_export_zip_contains_json_file(self):
        """Export ZIP should contain JSON file."""
        job_id = _create_sizing_batch_job()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/jobs/{job_id}/portfolio/export/zip"
        resp = requests.get(url)

        zip_buffer = io.BytesIO(resp.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            names = zf.namelist()
            assert any("portfolio.json" in name for name in names)

    def test_export_zip_contains_csv_file(self):
        """Export ZIP should contain CSV file."""
        job_id = _create_sizing_batch_job()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/jobs/{job_id}/portfolio/export/zip"
        resp = requests.get(url)

        zip_buffer = io.BytesIO(resp.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            names = zf.namelist()
            assert any("items.csv" in name for name in names)

    def test_export_zip_contains_metadata(self):
        """Export ZIP should contain metadata.json."""
        job_id = _create_sizing_batch_job()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/jobs/{job_id}/portfolio/export/zip"
        resp = requests.get(url)

        zip_buffer = io.BytesIO(resp.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            names = zf.namelist()
            assert "metadata.json" in names


# =============================================================================
# TestPortfolioSummaryExportCsv
# =============================================================================

class TestPortfolioSummaryExportCsv:
    """Tests for POST /api/bess-dispatch/portfolio/summary/export/csv."""

    def test_export_csv_returns_200(self):
        """Portfolio summary export CSV should return 200."""
        run_id_1 = _create_sizing_run()
        run_id_2 = _create_sizing_run()

        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/portfolio/summary/export/csv"
        resp = requests.post(url, json={"run_ids": [run_id_1, run_id_2]})

        assert resp.status_code == 200

    def test_export_csv_content_type(self):
        """Portfolio summary export CSV should have text/csv content type."""
        run_id_1 = _create_sizing_run()
        run_id_2 = _create_sizing_run()

        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/portfolio/summary/export/csv"
        resp = requests.post(url, json={"run_ids": [run_id_1, run_id_2]})

        assert "text/csv" in resp.headers.get("Content-Type", "")

    def test_export_csv_has_data_rows(self):
        """Portfolio summary export CSV should have data rows."""
        run_id_1 = _create_sizing_run()
        run_id_2 = _create_sizing_run()

        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/portfolio/summary/export/csv"
        resp = requests.post(url, json={"run_ids": [run_id_1, run_id_2]})

        lines = resp.text.strip().split("\n")
        # Header + 2 items
        assert len(lines) >= 3


# =============================================================================
# TestPortfolioSummaryExportZip
# =============================================================================

class TestPortfolioSummaryExportZip:
    """Tests for POST /api/bess-dispatch/portfolio/summary/export/zip."""

    def test_export_zip_returns_200(self):
        """Portfolio summary export ZIP should return 200."""
        run_id_1 = _create_sizing_run()
        run_id_2 = _create_sizing_run()

        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/portfolio/summary/export/zip"
        resp = requests.post(url, json={"run_ids": [run_id_1, run_id_2]})

        assert resp.status_code == 200

    def test_export_zip_content_type(self):
        """Portfolio summary export ZIP should have application/zip content type."""
        run_id_1 = _create_sizing_run()
        run_id_2 = _create_sizing_run()

        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/portfolio/summary/export/zip"
        resp = requests.post(url, json={"run_ids": [run_id_1, run_id_2]})

        assert "application/zip" in resp.headers.get("Content-Type", "")

    def test_export_zip_is_valid_zipfile(self):
        """Portfolio summary export ZIP should be a valid zip file."""
        run_id_1 = _create_sizing_run()
        run_id_2 = _create_sizing_run()

        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/portfolio/summary/export/zip"
        resp = requests.post(url, json={"run_ids": [run_id_1, run_id_2]})

        zip_buffer = io.BytesIO(resp.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            names = zf.namelist()
            assert len(names) >= 3

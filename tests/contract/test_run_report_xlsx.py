"""
Contract tests for Run Report XLSX endpoint (v2.4.0 PR3).

Tests verify:
- GET /api/bess-dispatch/runs/{run_id}/report.xlsx returns 200
- Response is a valid XLSX (ZIP with PK magic bytes)
"""

import pytest
import uuid
from ._api import post_json, DEFAULT_BASE_URL
import requests


def _base_req():
    """Minimal valid sizing request."""
    return {
        "load_kw": [100] * 24,
        "pv_generation_kw": [0, 0, 0, 0, 0, 0, 50, 200, 500, 800, 1000, 1100, 1100, 1000, 800, 500, 200, 50, 0, 0, 0, 0, 0, 0],
        "mode": "pv_surplus",
        "durations_h": [1.0, 2.0],
        "interval_minutes": 60,
        "discount_rate": 0.08,
        "analysis_years": 15,
        "capex_pln_per_kwh": 1800.0,
        "import_price_pln_mwh": 800.0,
    }


def _create_sizing_run():
    """Create a sizing run and return run_id."""
    request = _base_req()
    resp = post_json("/sizing", request)
    return resp.get("meta", {}).get("run_id") or resp.get("cache_info", {}).get("run_id")


class TestRunReportXlsxBasic:
    """Basic tests for /runs/{run_id}/report.xlsx endpoint."""

    def test_report_xlsx_returns_200(self):
        """Report XLSX should return 200."""
        run_id = _create_sizing_run()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/runs/{run_id}/report.xlsx"
        resp = requests.get(url)

        assert resp.status_code == 200

    def test_report_xlsx_content_type(self):
        """Report XLSX should have Excel content type."""
        run_id = _create_sizing_run()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/runs/{run_id}/report.xlsx"
        resp = requests.get(url)

        content_type = resp.headers.get("Content-Type", "")
        assert "spreadsheet" in content_type or "xlsx" in content_type or "application/vnd" in content_type

    def test_report_xlsx_has_content_disposition(self):
        """Report XLSX should have Content-Disposition header."""
        run_id = _create_sizing_run()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/runs/{run_id}/report.xlsx"
        resp = requests.get(url)

        assert "Content-Disposition" in resp.headers
        assert "attachment" in resp.headers["Content-Disposition"]
        assert ".xlsx" in resp.headers["Content-Disposition"]

    def test_report_xlsx_is_valid_zip(self):
        """Report XLSX should be a valid ZIP file (starts with PK magic bytes)."""
        run_id = _create_sizing_run()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/runs/{run_id}/report.xlsx"
        resp = requests.get(url)

        # XLSX files are ZIP archives, starting with PK magic bytes
        assert resp.content[:4] == b"PK\x03\x04"

    def test_report_xlsx_with_engineering_profile(self):
        """Report XLSX with engineering profile should return 200."""
        run_id = _create_sizing_run()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/runs/{run_id}/report.xlsx?profile=engineering"
        resp = requests.get(url)

        assert resp.status_code == 200
        assert resp.content[:4] == b"PK\x03\x04"

    def test_report_xlsx_404_for_missing_run(self):
        """Report XLSX should return 404 for missing run."""
        fake_id = str(uuid.uuid4())
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/runs/{fake_id}/report.xlsx"
        resp = requests.get(url)

        assert resp.status_code == 404

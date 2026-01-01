"""
Contract tests for Run Report PDF endpoint (v2.4.0 PR3).

Tests verify:
- GET /api/bess-dispatch/runs/{run_id}/report.pdf returns 200
- Response is a valid PDF (starts with %PDF-)
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


class TestRunReportPdfBasic:
    """Basic tests for /runs/{run_id}/report.pdf endpoint."""

    def test_report_pdf_returns_200(self):
        """Report PDF should return 200."""
        run_id = _create_sizing_run()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/runs/{run_id}/report.pdf"
        resp = requests.get(url)

        assert resp.status_code == 200

    def test_report_pdf_content_type(self):
        """Report PDF should have application/pdf content type."""
        run_id = _create_sizing_run()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/runs/{run_id}/report.pdf"
        resp = requests.get(url)

        assert "application/pdf" in resp.headers.get("Content-Type", "")

    def test_report_pdf_has_content_disposition(self):
        """Report PDF should have Content-Disposition header."""
        run_id = _create_sizing_run()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/runs/{run_id}/report.pdf"
        resp = requests.get(url)

        assert "Content-Disposition" in resp.headers
        assert "attachment" in resp.headers["Content-Disposition"]
        assert ".pdf" in resp.headers["Content-Disposition"]

    def test_report_pdf_is_valid_pdf(self):
        """Report PDF should start with %PDF- magic bytes."""
        run_id = _create_sizing_run()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/runs/{run_id}/report.pdf"
        resp = requests.get(url)

        # PDF files start with %PDF-
        assert resp.content[:5] == b"%PDF-"

    def test_report_pdf_with_engineering_profile(self):
        """Report PDF with engineering profile should return 200."""
        run_id = _create_sizing_run()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/runs/{run_id}/report.pdf?profile=engineering"
        resp = requests.get(url)

        assert resp.status_code == 200
        assert resp.content[:5] == b"%PDF-"

    def test_report_pdf_404_for_missing_run(self):
        """Report PDF should return 404 for missing run."""
        fake_id = str(uuid.uuid4())
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/runs/{fake_id}/report.pdf"
        resp = requests.get(url)

        assert resp.status_code == 404

"""
Contract tests for Run Report ZIP endpoint (v2.4.0 PR2).

Tests verify:
- GET /api/bess-dispatch/runs/{run_id}/report.zip returns 200
- ZIP file contains expected files
- report.json has meta.run_id and recommended.net_savings_pln
- response_meta.json has run metadata
- README.md is present
"""

import pytest
import zipfile
import io
import json
from ._api import post_json, get_json, DEFAULT_BASE_URL
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


# =============================================================================
# TestRunReportZipBasic
# =============================================================================

class TestRunReportZipBasic:
    """Basic tests for /runs/{run_id}/report.zip endpoint."""

    def test_report_zip_returns_200(self):
        """Report ZIP should return 200."""
        run_id = _create_sizing_run()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/runs/{run_id}/report.zip"
        resp = requests.get(url)

        assert resp.status_code == 200

    def test_report_zip_content_type(self):
        """Report ZIP should have application/zip content type."""
        run_id = _create_sizing_run()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/runs/{run_id}/report.zip"
        resp = requests.get(url)

        assert "application/zip" in resp.headers.get("Content-Type", "")

    def test_report_zip_has_content_disposition(self):
        """Report ZIP should have Content-Disposition header."""
        run_id = _create_sizing_run()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/runs/{run_id}/report.zip"
        resp = requests.get(url)

        assert "Content-Disposition" in resp.headers
        assert "attachment" in resp.headers["Content-Disposition"]
        assert "report_" in resp.headers["Content-Disposition"]
        assert ".zip" in resp.headers["Content-Disposition"]

    def test_report_zip_is_valid_zipfile(self):
        """Report ZIP should be a valid zip file."""
        run_id = _create_sizing_run()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/runs/{run_id}/report.zip"
        resp = requests.get(url)

        zip_buffer = io.BytesIO(resp.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            names = zf.namelist()
            assert len(names) >= 4


# =============================================================================
# TestRunReportZipContents
# =============================================================================

class TestRunReportZipContents:
    """Tests for report ZIP file contents."""

    def test_report_zip_contains_report_json(self):
        """Report ZIP should contain report.json."""
        run_id = _create_sizing_run()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/runs/{run_id}/report.zip"
        resp = requests.get(url)

        zip_buffer = io.BytesIO(resp.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            names = zf.namelist()
            assert "report.json" in names

    def test_report_zip_contains_request_json(self):
        """Report ZIP should contain request.json."""
        run_id = _create_sizing_run()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/runs/{run_id}/report.zip"
        resp = requests.get(url)

        zip_buffer = io.BytesIO(resp.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            names = zf.namelist()
            assert "request.json" in names

    def test_report_zip_contains_response_meta_json(self):
        """Report ZIP should contain response_meta.json."""
        run_id = _create_sizing_run()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/runs/{run_id}/report.zip"
        resp = requests.get(url)

        zip_buffer = io.BytesIO(resp.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            names = zf.namelist()
            assert "response_meta.json" in names

    def test_report_zip_contains_readme(self):
        """Report ZIP should contain README.md."""
        run_id = _create_sizing_run()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/runs/{run_id}/report.zip"
        resp = requests.get(url)

        zip_buffer = io.BytesIO(resp.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            names = zf.namelist()
            assert "README.md" in names


# =============================================================================
# TestRunReportJsonContents
# =============================================================================

class TestRunReportJsonContents:
    """Tests for report.json content."""

    def test_report_json_has_meta_run_id(self):
        """report.json should have meta.run_id."""
        run_id = _create_sizing_run()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/runs/{run_id}/report.zip"
        resp = requests.get(url)

        zip_buffer = io.BytesIO(resp.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            content = zf.read("report.json").decode("utf-8")
            data = json.loads(content)

            assert "meta" in data
            assert "run_id" in data["meta"]
            assert data["meta"]["run_id"] == run_id

    def test_report_json_has_recommended(self):
        """report.json should have recommended section."""
        run_id = _create_sizing_run()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/runs/{run_id}/report.zip"
        resp = requests.get(url)

        zip_buffer = io.BytesIO(resp.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            content = zf.read("report.json").decode("utf-8")
            data = json.loads(content)

            assert "recommended" in data

    def test_report_json_has_money_ledger_annual(self):
        """report.json should have money_ledger_annual."""
        run_id = _create_sizing_run()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/runs/{run_id}/report.zip"
        resp = requests.get(url)

        zip_buffer = io.BytesIO(resp.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            content = zf.read("report.json").decode("utf-8")
            data = json.loads(content)

            assert "money_ledger_annual" in data

    def test_response_meta_json_has_run_id(self):
        """response_meta.json should have run_id."""
        run_id = _create_sizing_run()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/runs/{run_id}/report.zip"
        resp = requests.get(url)

        zip_buffer = io.BytesIO(resp.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            content = zf.read("response_meta.json").decode("utf-8")
            data = json.loads(content)

            assert data["run_id"] == run_id


# =============================================================================
# TestRunReportZipOptions
# =============================================================================

class TestRunReportZipOptions:
    """Tests for report ZIP with options."""

    def test_report_zip_with_engineering_profile(self):
        """Report ZIP with engineering profile should return 200."""
        run_id = _create_sizing_run()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/runs/{run_id}/report.zip?profile=engineering"
        resp = requests.get(url)

        assert resp.status_code == 200

    def test_report_zip_with_branding(self):
        """Report ZIP with branding should include branding in README."""
        run_id = _create_sizing_run()
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/runs/{run_id}/report.zip?client_name=ACME%20Corp&site_name=Factory%20A"
        resp = requests.get(url)

        zip_buffer = io.BytesIO(resp.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            readme = zf.read("README.md").decode("utf-8")
            assert "ACME Corp" in readme
            assert "Factory A" in readme


# =============================================================================
# TestRunReportZipErrors
# =============================================================================

class TestRunReportZipErrors:
    """Tests for error cases."""

    def test_report_zip_404_for_missing_run(self):
        """Report ZIP should return 404 for missing run."""
        import uuid
        fake_id = str(uuid.uuid4())
        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/runs/{fake_id}/report.zip"
        resp = requests.get(url)

        assert resp.status_code == 404

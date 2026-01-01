"""
Contract tests for Portfolio Report ZIP endpoint (v2.4.0 PR4).

Tests verify:
- POST /api/bess-dispatch/portfolio/report.zip returns 200
- ZIP file contains expected files (summary.json, items.csv)
"""

import pytest
import zipfile
import io
import json
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


class TestPortfolioReportZipBasic:
    """Basic tests for /portfolio/report.zip endpoint."""

    def test_portfolio_report_zip_returns_200(self):
        """Portfolio report ZIP should return 200."""
        run_id_1 = _create_sizing_run()
        run_id_2 = _create_sizing_run()

        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/portfolio/report.zip"
        resp = requests.post(url, json={"run_ids": [run_id_1, run_id_2]})

        assert resp.status_code == 200

    def test_portfolio_report_zip_content_type(self):
        """Portfolio report ZIP should have application/zip content type."""
        run_id_1 = _create_sizing_run()
        run_id_2 = _create_sizing_run()

        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/portfolio/report.zip"
        resp = requests.post(url, json={"run_ids": [run_id_1, run_id_2]})

        assert "application/zip" in resp.headers.get("Content-Type", "")

    def test_portfolio_report_zip_is_valid_zipfile(self):
        """Portfolio report ZIP should be a valid zip file."""
        run_id_1 = _create_sizing_run()
        run_id_2 = _create_sizing_run()

        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/portfolio/report.zip"
        resp = requests.post(url, json={"run_ids": [run_id_1, run_id_2]})

        zip_buffer = io.BytesIO(resp.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            names = zf.namelist()
            assert len(names) >= 3


class TestPortfolioReportZipContents:
    """Tests for portfolio report ZIP file contents."""

    def test_portfolio_report_zip_contains_summary_json(self):
        """Portfolio report ZIP should contain portfolio_summary.json."""
        run_id_1 = _create_sizing_run()
        run_id_2 = _create_sizing_run()

        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/portfolio/report.zip"
        resp = requests.post(url, json={"run_ids": [run_id_1, run_id_2]})

        zip_buffer = io.BytesIO(resp.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            names = zf.namelist()
            assert "portfolio_summary.json" in names

    def test_portfolio_report_zip_contains_items_csv(self):
        """Portfolio report ZIP should contain portfolio_items.csv."""
        run_id_1 = _create_sizing_run()
        run_id_2 = _create_sizing_run()

        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/portfolio/report.zip"
        resp = requests.post(url, json={"run_ids": [run_id_1, run_id_2]})

        zip_buffer = io.BytesIO(resp.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            names = zf.namelist()
            assert "portfolio_items.csv" in names

    def test_portfolio_report_zip_contains_readme(self):
        """Portfolio report ZIP should contain README.md."""
        run_id_1 = _create_sizing_run()
        run_id_2 = _create_sizing_run()

        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/portfolio/report.zip"
        resp = requests.post(url, json={"run_ids": [run_id_1, run_id_2]})

        zip_buffer = io.BytesIO(resp.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            names = zf.namelist()
            assert "README.md" in names

    def test_portfolio_report_summary_json_valid(self):
        """portfolio_summary.json should be valid JSON with expected fields."""
        run_id_1 = _create_sizing_run()
        run_id_2 = _create_sizing_run()

        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/portfolio/report.zip"
        resp = requests.post(url, json={"run_ids": [run_id_1, run_id_2]})

        zip_buffer = io.BytesIO(resp.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            content = zf.read("portfolio_summary.json").decode("utf-8")
            data = json.loads(content)

            assert "items_total" in data
            assert "items_ok" in data
            assert "total_npv_pln" in data

    def test_portfolio_report_items_csv_has_header(self):
        """portfolio_items.csv should have header row."""
        run_id_1 = _create_sizing_run()
        run_id_2 = _create_sizing_run()

        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/portfolio/report.zip"
        resp = requests.post(url, json={"run_ids": [run_id_1, run_id_2]})

        zip_buffer = io.BytesIO(resp.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            content = zf.read("portfolio_items.csv").decode("utf-8")
            lines = content.strip().split("\n")

            assert len(lines) >= 1
            header = lines[0].lower()
            assert "run_id" in header
            assert "npv_pln" in header


class TestPortfolioReportZipWithOptions:
    """Tests for portfolio report ZIP with options."""

    def test_portfolio_report_with_branding(self):
        """Portfolio report with branding should return 200."""
        run_id_1 = _create_sizing_run()
        run_id_2 = _create_sizing_run()

        url = f"{DEFAULT_BASE_URL}/api/bess-dispatch/portfolio/report.zip"
        resp = requests.post(url, json={
            "run_ids": [run_id_1, run_id_2],
            "options": {
                "profile": "client",
                "branding": {
                    "client_name": "ACME Corp",
                    "report_title": "Portfolio Analysis",
                },
            },
        })

        assert resp.status_code == 200

        zip_buffer = io.BytesIO(resp.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            readme = zf.read("README.md").decode("utf-8")
            assert "ACME Corp" in readme
            assert "Portfolio Analysis" in readme

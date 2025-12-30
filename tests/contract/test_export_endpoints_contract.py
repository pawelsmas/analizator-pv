"""
Contract tests for v1.0.0 Export endpoints.

Tests verify:
- GET /runs/{run_id}/export/json returns downloadable JSON
- GET /runs/{run_id}/export/csv returns downloadable CSV
- Content-Disposition headers are correct
- 404 for nonexistent runs

Run with: pytest tests/contract/test_export_endpoints_contract.py -v
"""
import pytest
import requests
import json
import csv
import io
from ._api import post_json


SIZING_ENDPOINT = "/sizing"
BASE_URL = "http://localhost:8031"


def make_sizing_request():
    """Create minimal sizing request."""
    return {
        "load_kw": [100, 120, 110, 90],
        "pv_generation_kw": [50, 70, 80, 60],
        "energy_price_pln_kwh": 0.8,
    }


class TestExportJsonEndpoint:
    """Tests for GET /runs/{run_id}/export/json endpoint."""

    def test_export_json_returns_200(self):
        """Verify export/json returns 200 status."""
        req = make_sizing_request()
        resp = post_json(SIZING_ENDPOINT, req)
        run_id = resp["cache_info"]["run_id"]

        r = requests.get(f"{BASE_URL}/runs/{run_id}/export/json")
        assert r.status_code == 200

    def test_export_json_content_type(self):
        """Verify export/json returns application/json content type."""
        req = make_sizing_request()
        resp = post_json(SIZING_ENDPOINT, req)
        run_id = resp["cache_info"]["run_id"]

        r = requests.get(f"{BASE_URL}/runs/{run_id}/export/json")
        assert "application/json" in r.headers.get("Content-Type", "")

    def test_export_json_has_content_disposition(self):
        """Verify export/json has Content-Disposition header."""
        req = make_sizing_request()
        resp = post_json(SIZING_ENDPOINT, req)
        run_id = resp["cache_info"]["run_id"]

        r = requests.get(f"{BASE_URL}/runs/{run_id}/export/json")
        cd = r.headers.get("Content-Disposition", "")
        assert "attachment" in cd
        assert f"run_{run_id}.json" in cd

    def test_export_json_is_valid_json(self):
        """Verify export/json content is valid JSON."""
        req = make_sizing_request()
        resp = post_json(SIZING_ENDPOINT, req)
        run_id = resp["cache_info"]["run_id"]

        r = requests.get(f"{BASE_URL}/runs/{run_id}/export/json")
        data = r.json()
        assert isinstance(data, dict)

    def test_export_json_contains_run_id(self):
        """Verify exported JSON contains run_id."""
        req = make_sizing_request()
        resp = post_json(SIZING_ENDPOINT, req)
        run_id = resp["cache_info"]["run_id"]

        r = requests.get(f"{BASE_URL}/runs/{run_id}/export/json")
        data = r.json()
        assert data["run_id"] == run_id

    def test_export_json_contains_response(self):
        """Verify exported JSON contains response payload."""
        req = make_sizing_request()
        resp = post_json(SIZING_ENDPOINT, req)
        run_id = resp["cache_info"]["run_id"]

        r = requests.get(f"{BASE_URL}/runs/{run_id}/export/json")
        data = r.json()
        assert "response" in data
        assert "variants" in data["response"]

    def test_export_json_nonexistent_returns_404(self):
        """Verify export/json returns 404 for nonexistent run_id."""
        fake_run_id = "00000000-0000-0000-0000-000000000000"
        r = requests.get(f"{BASE_URL}/runs/{fake_run_id}/export/json")
        assert r.status_code == 404


class TestExportCsvEndpoint:
    """Tests for GET /runs/{run_id}/export/csv endpoint."""

    def test_export_csv_returns_200(self):
        """Verify export/csv returns 200 status."""
        req = make_sizing_request()
        resp = post_json(SIZING_ENDPOINT, req)
        run_id = resp["cache_info"]["run_id"]

        r = requests.get(f"{BASE_URL}/runs/{run_id}/export/csv")
        assert r.status_code == 200

    def test_export_csv_content_type(self):
        """Verify export/csv returns text/csv content type."""
        req = make_sizing_request()
        resp = post_json(SIZING_ENDPOINT, req)
        run_id = resp["cache_info"]["run_id"]

        r = requests.get(f"{BASE_URL}/runs/{run_id}/export/csv")
        assert "text/csv" in r.headers.get("Content-Type", "")

    def test_export_csv_has_content_disposition(self):
        """Verify export/csv has Content-Disposition header."""
        req = make_sizing_request()
        resp = post_json(SIZING_ENDPOINT, req)
        run_id = resp["cache_info"]["run_id"]

        r = requests.get(f"{BASE_URL}/runs/{run_id}/export/csv")
        cd = r.headers.get("Content-Disposition", "")
        assert "attachment" in cd
        assert f"run_{run_id}.csv" in cd

    def test_export_csv_is_valid_csv(self):
        """Verify export/csv content is valid CSV."""
        req = make_sizing_request()
        resp = post_json(SIZING_ENDPOINT, req)
        run_id = resp["cache_info"]["run_id"]

        r = requests.get(f"{BASE_URL}/runs/{run_id}/export/csv")
        reader = csv.reader(io.StringIO(r.text))
        rows = list(reader)
        assert len(rows) >= 2  # Header + at least one data row

    def test_export_csv_has_header_row(self):
        """Verify CSV has header row with expected columns."""
        req = make_sizing_request()
        resp = post_json(SIZING_ENDPOINT, req)
        run_id = resp["cache_info"]["run_id"]

        r = requests.get(f"{BASE_URL}/runs/{run_id}/export/csv")
        reader = csv.reader(io.StringIO(r.text))
        rows = list(reader)
        headers = rows[0]

        expected_headers = ["run_id", "request_hash", "created_at", "endpoint", "status"]
        for h in expected_headers:
            assert h in headers

    def test_export_csv_has_metrics_columns(self):
        """Verify CSV has key metrics columns."""
        req = make_sizing_request()
        resp = post_json(SIZING_ENDPOINT, req)
        run_id = resp["cache_info"]["run_id"]

        r = requests.get(f"{BASE_URL}/runs/{run_id}/export/csv")
        reader = csv.reader(io.StringIO(r.text))
        rows = list(reader)
        headers = rows[0]

        # Should have recommended variant and metrics
        assert "recommended_variant" in headers
        assert "npv_pln" in headers
        assert "payback_years" in headers

    def test_export_csv_run_id_matches(self):
        """Verify CSV data contains correct run_id."""
        req = make_sizing_request()
        resp = post_json(SIZING_ENDPOINT, req)
        run_id = resp["cache_info"]["run_id"]

        r = requests.get(f"{BASE_URL}/runs/{run_id}/export/csv")
        reader = csv.DictReader(io.StringIO(r.text))
        rows = list(reader)

        assert len(rows) == 1
        assert rows[0]["run_id"] == run_id

    def test_export_csv_nonexistent_returns_404(self):
        """Verify export/csv returns 404 for nonexistent run_id."""
        fake_run_id = "00000000-0000-0000-0000-000000000000"
        r = requests.get(f"{BASE_URL}/runs/{fake_run_id}/export/csv")
        assert r.status_code == 404

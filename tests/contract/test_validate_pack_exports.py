"""
Contract tests for validate-pack export endpoints (v1.7.0).

Tests:
- CSV export returns valid CSV with expected columns
- Diffs export returns valid CSV with diff details
- JSON export returns valid JSON structure
- ZIP export returns valid ZIP with expected files
"""

import csv
import io
import json
import zipfile
import pytest
import requests

BASE_URL = "http://localhost:8031"


@pytest.fixture(scope="module")
def validate_pack_job_id():
    """Create a validate-pack job for testing exports."""
    response = requests.post(
        f"{BASE_URL}/api/bess-dispatch/jobs/validate-pack",
        json={"pack": "baseline", "wait": True},
        timeout=120,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "done"
    return data["job_id"]


class TestValidatePackExportCSV:
    """Contract tests for CSV export endpoint."""

    def test_export_csv_returns_200(self, validate_pack_job_id):
        """GET /jobs/{job_id}/validate-pack/export/csv returns 200."""
        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/jobs/{validate_pack_job_id}/validate-pack/export/csv"
        )
        assert response.status_code == 200

    def test_export_csv_content_type(self, validate_pack_job_id):
        """CSV export returns text/csv content type."""
        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/jobs/{validate_pack_job_id}/validate-pack/export/csv"
        )
        assert "text/csv" in response.headers.get("Content-Type", "")

    def test_export_csv_has_expected_columns(self, validate_pack_job_id):
        """CSV has expected columns: scenario, pass, mismatch_count, error, failed_fields."""
        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/jobs/{validate_pack_job_id}/validate-pack/export/csv"
        )
        reader = csv.reader(io.StringIO(response.text))
        headers = next(reader)
        expected_columns = ["scenario", "pass", "mismatch_count", "error", "failed_fields"]
        assert headers == expected_columns

    def test_export_csv_has_content_disposition(self, validate_pack_job_id):
        """CSV export has Content-Disposition header."""
        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/jobs/{validate_pack_job_id}/validate-pack/export/csv"
        )
        assert "Content-Disposition" in response.headers
        assert "attachment" in response.headers["Content-Disposition"]
        assert ".csv" in response.headers["Content-Disposition"]


class TestValidatePackExportDiffs:
    """Contract tests for diffs CSV export endpoint."""

    def test_export_diffs_returns_200(self, validate_pack_job_id):
        """GET /jobs/{job_id}/validate-pack/export/diffs returns 200."""
        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/jobs/{validate_pack_job_id}/validate-pack/export/diffs"
        )
        assert response.status_code == 200

    def test_export_diffs_content_type(self, validate_pack_job_id):
        """Diffs export returns text/csv content type."""
        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/jobs/{validate_pack_job_id}/validate-pack/export/diffs"
        )
        assert "text/csv" in response.headers.get("Content-Type", "")

    def test_export_diffs_has_expected_columns(self, validate_pack_job_id):
        """Diffs CSV has expected columns for diff details."""
        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/jobs/{validate_pack_job_id}/validate-pack/export/diffs"
        )
        reader = csv.reader(io.StringIO(response.text))
        headers = next(reader)
        expected_columns = [
            "scenario", "field", "expected", "actual",
            "abs_diff", "rel_diff", "tolerance_abs", "tolerance_rel", "pass"
        ]
        assert headers == expected_columns


class TestValidatePackExportJSON:
    """Contract tests for JSON export endpoint."""

    def test_export_json_returns_200(self, validate_pack_job_id):
        """GET /jobs/{job_id}/validate-pack/export/json returns 200."""
        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/jobs/{validate_pack_job_id}/validate-pack/export/json"
        )
        assert response.status_code == 200

    def test_export_json_content_type(self, validate_pack_job_id):
        """JSON export returns application/json content type."""
        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/jobs/{validate_pack_job_id}/validate-pack/export/json"
        )
        assert "application/json" in response.headers.get("Content-Type", "")

    def test_export_json_has_expected_fields(self, validate_pack_job_id):
        """JSON export has expected top-level fields."""
        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/jobs/{validate_pack_job_id}/validate-pack/export/json"
        )
        data = response.json()
        assert "job_id" in data
        assert "pack" in data
        assert "pass" in data
        assert "summary" in data
        assert "scenarios" in data
        assert "exported_at" in data

    def test_export_json_job_id_matches(self, validate_pack_job_id):
        """JSON export job_id matches request."""
        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/jobs/{validate_pack_job_id}/validate-pack/export/json"
        )
        data = response.json()
        assert data["job_id"] == validate_pack_job_id


class TestValidatePackExportZIP:
    """Contract tests for ZIP export endpoint."""

    def test_export_zip_returns_200(self, validate_pack_job_id):
        """GET /jobs/{job_id}/validate-pack/export/zip returns 200."""
        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/jobs/{validate_pack_job_id}/validate-pack/export/zip"
        )
        assert response.status_code == 200

    def test_export_zip_content_type(self, validate_pack_job_id):
        """ZIP export returns application/zip content type."""
        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/jobs/{validate_pack_job_id}/validate-pack/export/zip"
        )
        assert "application/zip" in response.headers.get("Content-Type", "")

    def test_export_zip_is_valid(self, validate_pack_job_id):
        """ZIP export is a valid ZIP file."""
        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/jobs/{validate_pack_job_id}/validate-pack/export/zip"
        )
        zip_buffer = io.BytesIO(response.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            assert len(zf.namelist()) > 0

    def test_export_zip_contains_expected_files(self, validate_pack_job_id):
        """ZIP contains summary.csv, diffs.csv, result.json, metadata.json."""
        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/jobs/{validate_pack_job_id}/validate-pack/export/zip"
        )
        zip_buffer = io.BytesIO(response.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            filenames = zf.namelist()
            # Check for expected file patterns
            assert any("summary.csv" in f for f in filenames)
            assert any("diffs.csv" in f for f in filenames)
            assert any("result.json" in f for f in filenames)
            assert "metadata.json" in filenames

    def test_export_zip_metadata_is_valid_json(self, validate_pack_job_id):
        """ZIP metadata.json is valid JSON with expected fields."""
        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/jobs/{validate_pack_job_id}/validate-pack/export/zip"
        )
        zip_buffer = io.BytesIO(response.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            with zf.open("metadata.json") as f:
                metadata = json.load(f)
                assert "job_id" in metadata
                assert "pack" in metadata
                assert "exported_at" in metadata
                assert "files" in metadata


class TestValidatePackExportErrors:
    """Contract tests for export error handling."""

    def test_export_invalid_job_returns_404(self):
        """Export with invalid job_id returns 404."""
        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/jobs/invalid-job-id/validate-pack/export/csv"
        )
        assert response.status_code == 404

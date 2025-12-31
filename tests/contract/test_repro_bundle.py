"""
Contract tests for repro bundle endpoints (v1.8.0).

Tests verify:
- GET /runs/{run_id}/repro.zip returns valid ZIP
- ZIP contains request.json, response.json, debug_events.json, metadata.json
- GET /api/bess-dispatch/jobs/{job_id}/repro.zip returns valid ZIP
- ZIP contains items with request.json, response.json, debug_events.json
"""
import pytest
import requests
import zipfile
import io
import json

BASE_URL = "http://localhost:8031"


def create_sizing_request():
    """Create a sizing request to generate a run."""
    n_hours = 24
    request = {
        "pv_generation_kw": [50.0] * n_hours,
        "load_kw": [30.0] * n_hours,
        "interval_minutes": 60,
        "battery_power_kw": 50.0,
        "battery_energy_kwh": 100.0,
        "mode": "pv_surplus",
        "prices": {
            "import_price_pln_kwh": 0.8,
            "export_price_pln_kwh": 0.4,
        },
    }
    response = requests.post(f"{BASE_URL}/sizing", json=request, timeout=60)
    assert response.status_code == 200, f"Sizing failed: {response.text}"
    return response.json()


def get_run_id():
    """Get a run_id by creating a sizing request."""
    sizing_result = create_sizing_request()
    cache_info = sizing_result.get("cache_info", {})
    run_id = cache_info.get("run_id")
    assert run_id is not None, "run_id not found in sizing response"
    return run_id


class TestRunReproBundleEndpoint:
    """Contract tests for /runs/{run_id}/repro.zip endpoint."""

    def test_repro_zip_returns_200(self):
        """Verify repro.zip endpoint returns 200."""
        run_id = get_run_id()
        response = requests.get(f"{BASE_URL}/runs/{run_id}/repro.zip", timeout=30)
        assert response.status_code == 200

    def test_repro_zip_content_type(self):
        """Verify repro.zip returns application/zip content type."""
        run_id = get_run_id()
        response = requests.get(f"{BASE_URL}/runs/{run_id}/repro.zip", timeout=30)
        assert "application/zip" in response.headers.get("content-type", "")

    def test_repro_zip_is_valid_zipfile(self):
        """Verify repro.zip returns a valid ZIP file."""
        run_id = get_run_id()
        response = requests.get(f"{BASE_URL}/runs/{run_id}/repro.zip", timeout=30)
        zip_buffer = io.BytesIO(response.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            assert len(zf.namelist()) > 0

    def test_repro_zip_contains_request_json(self):
        """Verify repro.zip contains request.json."""
        run_id = get_run_id()
        response = requests.get(f"{BASE_URL}/runs/{run_id}/repro.zip", timeout=30)
        zip_buffer = io.BytesIO(response.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            assert "request.json" in zf.namelist()
            content = json.loads(zf.read("request.json"))
            assert isinstance(content, dict)

    def test_repro_zip_contains_response_json(self):
        """Verify repro.zip contains response.json."""
        run_id = get_run_id()
        response = requests.get(f"{BASE_URL}/runs/{run_id}/repro.zip", timeout=30)
        zip_buffer = io.BytesIO(response.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            assert "response.json" in zf.namelist()
            content = json.loads(zf.read("response.json"))
            assert isinstance(content, dict)
            assert "variants" in content

    def test_repro_zip_contains_debug_events_json(self):
        """Verify repro.zip contains debug_events.json."""
        run_id = get_run_id()
        response = requests.get(f"{BASE_URL}/runs/{run_id}/repro.zip", timeout=30)
        zip_buffer = io.BytesIO(response.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            assert "debug_events.json" in zf.namelist()
            content = json.loads(zf.read("debug_events.json"))
            assert "steps" in content
            assert "export_limited_steps" in content

    def test_repro_zip_contains_metadata_json(self):
        """Verify repro.zip contains metadata.json."""
        run_id = get_run_id()
        response = requests.get(f"{BASE_URL}/runs/{run_id}/repro.zip", timeout=30)
        zip_buffer = io.BytesIO(response.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            assert "metadata.json" in zf.namelist()
            content = json.loads(zf.read("metadata.json"))
            assert content.get("run_id") == run_id
            assert content.get("version") == "1.8.0"

    def test_repro_zip_404_for_unknown_run(self):
        """Verify repro.zip returns 404 for unknown run_id."""
        response = requests.get(f"{BASE_URL}/runs/unknown-run-id/repro.zip", timeout=30)
        assert response.status_code == 404

    def test_repro_zip_filename(self):
        """Verify repro.zip has correct filename in Content-Disposition."""
        run_id = get_run_id()
        response = requests.get(f"{BASE_URL}/runs/{run_id}/repro.zip", timeout=30)
        content_disposition = response.headers.get("Content-Disposition", "")
        assert f"repro_{run_id}.zip" in content_disposition


class TestJobReproBundleEndpoint:
    """Contract tests for /api/bess-dispatch/jobs/{job_id}/repro.zip endpoint."""

    @pytest.fixture
    def batch_job_id(self):
        """Create a batch job and return job_id."""
        n_hours = 24
        sizing_request = {
            "pv_generation_kw": [50.0] * n_hours,
            "load_kw": [30.0] * n_hours,
            "interval_minutes": 60,
            "battery_power_kw": 50.0,
            "battery_energy_kwh": 100.0,
            "mode": "pv_surplus",
            "prices": {"import_price_pln_kwh": 0.8, "export_price_pln_kwh": 0.4},
        }
        batch_request = {
            "items": [
                {
                    "item_id": "test-item-001",
                    "request": sizing_request,
                }
            ],
            "wait": True,
        }
        response = requests.post(
            f"{BASE_URL}/api/bess-dispatch/jobs/sizing-batch",
            json=batch_request,
            timeout=60,
        )
        assert response.status_code == 200, f"Batch job failed: {response.text}"
        data = response.json()
        return data.get("job_id")

    def test_job_repro_zip_returns_200(self, batch_job_id):
        """Verify job repro.zip endpoint returns 200."""
        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/jobs/{batch_job_id}/repro.zip",
            timeout=30,
        )
        assert response.status_code == 200

    def test_job_repro_zip_content_type(self, batch_job_id):
        """Verify job repro.zip returns application/zip content type."""
        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/jobs/{batch_job_id}/repro.zip",
            timeout=30,
        )
        assert "application/zip" in response.headers.get("content-type", "")

    def test_job_repro_zip_is_valid_zipfile(self, batch_job_id):
        """Verify job repro.zip returns a valid ZIP file."""
        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/jobs/{batch_job_id}/repro.zip",
            timeout=30,
        )
        zip_buffer = io.BytesIO(response.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            assert len(zf.namelist()) > 0

    def test_job_repro_zip_contains_metadata_json(self, batch_job_id):
        """Verify job repro.zip contains metadata.json."""
        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/jobs/{batch_job_id}/repro.zip",
            timeout=30,
        )
        zip_buffer = io.BytesIO(response.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            assert "metadata.json" in zf.namelist()
            content = json.loads(zf.read("metadata.json"))
            assert content.get("job_id") == batch_job_id
            assert content.get("version") == "1.8.0"

    def test_job_repro_zip_contains_item_request(self, batch_job_id):
        """Verify job repro.zip contains items with request.json."""
        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/jobs/{batch_job_id}/repro.zip",
            timeout=30,
        )
        zip_buffer = io.BytesIO(response.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            # Should have items/0000/request.json
            assert "items/0000/request.json" in zf.namelist()
            content = json.loads(zf.read("items/0000/request.json"))
            assert isinstance(content, dict)

    def test_job_repro_zip_contains_item_response(self, batch_job_id):
        """Verify job repro.zip contains items with response.json."""
        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/jobs/{batch_job_id}/repro.zip",
            timeout=30,
        )
        zip_buffer = io.BytesIO(response.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            assert "items/0000/response.json" in zf.namelist()
            content = json.loads(zf.read("items/0000/response.json"))
            assert isinstance(content, dict)
            assert "variants" in content

    def test_job_repro_zip_contains_item_debug_events(self, batch_job_id):
        """Verify job repro.zip contains items with debug_events.json."""
        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/jobs/{batch_job_id}/repro.zip",
            timeout=30,
        )
        zip_buffer = io.BytesIO(response.content)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            assert "items/0000/debug_events.json" in zf.namelist()
            content = json.loads(zf.read("items/0000/debug_events.json"))
            assert "steps" in content

    def test_job_repro_zip_404_for_unknown_job(self):
        """Verify job repro.zip returns 404 for unknown job_id."""
        response = requests.get(
            f"{BASE_URL}/api/bess-dispatch/jobs/unknown-job-id/repro.zip",
            timeout=30,
        )
        assert response.status_code == 404

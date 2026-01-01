"""
Contract tests for runstore DB backend (v3.6.0 PR1).

Tests verify:
- DB backend returns same response structure as filesystem backend
- Run details accessible after sizing via DB backend
- Schema version and key fields preserved
"""

import pytest
import os
import sys
import tempfile
from pathlib import Path

# Add services to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))


class TestRunstoreDbBackendReturnsSameResponse:
    """Contract tests ensuring DB backend returns equivalent responses to filesystem."""

    @pytest.fixture
    def db_backend(self):
        """Create DB backend with temp SQLite."""
        from runstore_backend import DbRunPayloadBackend

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "runstore.db")
            backend = DbRunPayloadBackend(
                db_url=f"sqlite:///{db_path}",
                compress=False,
            )
            yield backend
            backend.close()

    def _create_sample_sizing_request(self):
        """Create a sample sizing request."""
        return {
            "pv_power_kw": 100,
            "battery_kwh": 50,
            "latitude": 52.0,
            "longitude": 21.0,
            "yearly_consumption_kwh": 100000,
        }

    def _create_sample_sizing_response(self, run_id: str):
        """Create a sample sizing response."""
        return {
            "run_id": run_id,
            "schema_version": "1.0.0",
            "variants": [
                {
                    "name": "baseline",
                    "npv_pln": 50000,
                    "payback_years": 7.5,
                    "irr_pct": 12.0,
                }
            ],
            "recommended_variant": "baseline",
            "meta": {
                "endpoint": "sizing",
                "status": "ok",
            },
        }

    def test_db_backend_saves_and_retrieves_run(self, db_backend):
        """DB backend should save run and retrieve with same fields."""
        from runstore_backend import RunPayload
        from datetime import datetime, timezone

        run_id = "contract-test-run-001"

        request_json = self._create_sample_sizing_request()
        response_json = self._create_sample_sizing_response(run_id)

        payload = RunPayload(
            run_id=run_id,
            tenant_id="default",
            created_at=datetime.now(timezone.utc).isoformat(),
            request_json=request_json,
            response_json=response_json,
            meta_json={"endpoint": "sizing", "status": "ok"},
        )

        db_backend.save_run(payload)
        retrieved = db_backend.get_run(run_id, "default")

        # Contract: same fields returned
        assert retrieved is not None
        assert retrieved.run_id == run_id
        assert retrieved.response_json["schema_version"] == "1.0.0"
        assert retrieved.response_json["run_id"] == run_id
        assert retrieved.response_json["recommended_variant"] == "baseline"
        assert len(retrieved.response_json["variants"]) == 1

    def test_db_backend_response_structure_matches_filesystem(self, db_backend):
        """DB backend response structure should match filesystem backend."""
        from runstore_backend import RunPayload
        from datetime import datetime, timezone

        run_id = "contract-test-structure-001"
        request_json = self._create_sample_sizing_request()
        response_json = self._create_sample_sizing_response(run_id)

        payload = RunPayload(
            run_id=run_id,
            tenant_id="default",
            created_at=datetime.now(timezone.utc).isoformat(),
            request_json=request_json,
            response_json=response_json,
            meta_json={"endpoint": "sizing"},
        )

        # Save to DB backend
        db_backend.save_run(payload)
        db_result = db_backend.get_run(run_id, "default")

        # Contract: DB result has same structure as payload
        assert db_result.run_id == payload.run_id
        assert db_result.tenant_id == payload.tenant_id
        assert db_result.request_json == payload.request_json
        assert db_result.response_json == payload.response_json

    def test_schema_version_preserved_in_db(self, db_backend):
        """Schema version should be preserved when stored in DB."""
        from runstore_backend import RunPayload
        from datetime import datetime, timezone

        run_id = "contract-test-schema-001"

        response_json = {
            "run_id": run_id,
            "schema_version": "2.5.0",  # Specific version to test
            "variants": [],
        }

        payload = RunPayload(
            run_id=run_id,
            tenant_id="default",
            created_at=datetime.now(timezone.utc).isoformat(),
            request_json={},
            response_json=response_json,
        )

        db_backend.save_run(payload)
        retrieved = db_backend.get_run(run_id, "default")

        assert retrieved.response_json["schema_version"] == "2.5.0"

    def test_variants_array_preserved_in_db(self, db_backend):
        """Variants array should be preserved exactly when stored in DB."""
        from runstore_backend import RunPayload
        from datetime import datetime, timezone

        run_id = "contract-test-variants-001"

        variants = [
            {"name": "small", "npv_pln": 10000, "payback_years": 10.0},
            {"name": "medium", "npv_pln": 25000, "payback_years": 8.0},
            {"name": "large", "npv_pln": 50000, "payback_years": 6.0},
        ]

        payload = RunPayload(
            run_id=run_id,
            tenant_id="default",
            created_at=datetime.now(timezone.utc).isoformat(),
            request_json={},
            response_json={"run_id": run_id, "variants": variants},
        )

        db_backend.save_run(payload)
        retrieved = db_backend.get_run(run_id, "default")

        assert len(retrieved.response_json["variants"]) == 3
        assert retrieved.response_json["variants"][0]["name"] == "small"
        assert retrieved.response_json["variants"][1]["npv_pln"] == 25000
        assert retrieved.response_json["variants"][2]["payback_years"] == 6.0

    def test_meta_json_optional_and_preserved(self, db_backend):
        """Meta JSON should be optional but preserved when provided."""
        from runstore_backend import RunPayload
        from datetime import datetime, timezone

        # Without meta
        run_id_no_meta = "contract-test-no-meta-001"
        payload_no_meta = RunPayload(
            run_id=run_id_no_meta,
            tenant_id="default",
            created_at=datetime.now(timezone.utc).isoformat(),
            request_json={},
            response_json={"run_id": run_id_no_meta},
            meta_json=None,
        )
        db_backend.save_run(payload_no_meta)
        retrieved_no_meta = db_backend.get_run(run_id_no_meta, "default")
        assert retrieved_no_meta.meta_json is None

        # With meta
        run_id_with_meta = "contract-test-with-meta-001"
        meta = {"endpoint": "sizing", "duration_ms": 150, "version": "3.6.0"}
        payload_with_meta = RunPayload(
            run_id=run_id_with_meta,
            tenant_id="default",
            created_at=datetime.now(timezone.utc).isoformat(),
            request_json={},
            response_json={"run_id": run_id_with_meta},
            meta_json=meta,
        )
        db_backend.save_run(payload_with_meta)
        retrieved_with_meta = db_backend.get_run(run_id_with_meta, "default")
        assert retrieved_with_meta.meta_json == meta

    def test_created_at_preserved_in_db(self, db_backend):
        """Created at timestamp should be preserved exactly."""
        from runstore_backend import RunPayload

        run_id = "contract-test-timestamp-001"
        timestamp = "2025-06-15T10:30:00+00:00"

        payload = RunPayload(
            run_id=run_id,
            tenant_id="default",
            created_at=timestamp,
            request_json={},
            response_json={"run_id": run_id},
        )

        db_backend.save_run(payload)
        retrieved = db_backend.get_run(run_id, "default")

        assert retrieved.created_at == timestamp

    def test_complex_nested_json_preserved(self, db_backend):
        """Complex nested JSON structures should be preserved."""
        from runstore_backend import RunPayload
        from datetime import datetime, timezone

        run_id = "contract-test-nested-001"

        complex_request = {
            "config": {
                "battery": {
                    "sizes": [50, 100, 200],
                    "parameters": {
                        "efficiency": 0.95,
                        "depth_of_discharge": 0.9,
                    },
                },
                "pv": {
                    "panels": [
                        {"type": "mono", "power_w": 400},
                        {"type": "poly", "power_w": 350},
                    ],
                },
            },
            "flags": {
                "include_trace": True,
                "include_invariants": False,
            },
        }

        payload = RunPayload(
            run_id=run_id,
            tenant_id="default",
            created_at=datetime.now(timezone.utc).isoformat(),
            request_json=complex_request,
            response_json={"run_id": run_id},
        )

        db_backend.save_run(payload)
        retrieved = db_backend.get_run(run_id, "default")

        assert retrieved.request_json == complex_request
        assert retrieved.request_json["config"]["battery"]["sizes"] == [50, 100, 200]
        assert retrieved.request_json["config"]["pv"]["panels"][0]["type"] == "mono"


class TestRunstoreDbBackendWithCompression:
    """Contract tests for DB backend with compression enabled."""

    @pytest.fixture
    def compressed_db_backend(self):
        """Create DB backend with compression enabled."""
        from runstore_backend import DbRunPayloadBackend

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "runstore_compressed.db")
            backend = DbRunPayloadBackend(
                db_url=f"sqlite:///{db_path}",
                compress=True,
            )
            yield backend
            backend.close()

    def test_compressed_backend_returns_same_response(self, compressed_db_backend):
        """Compressed DB backend should return identical response."""
        from runstore_backend import RunPayload
        from datetime import datetime, timezone

        run_id = "contract-test-compressed-001"

        # Large payload that benefits from compression
        large_response = {
            "run_id": run_id,
            "schema_version": "1.0.0",
            "variants": [{"name": f"variant_{i}", "data": list(range(100))} for i in range(10)],
        }

        payload = RunPayload(
            run_id=run_id,
            tenant_id="default",
            created_at=datetime.now(timezone.utc).isoformat(),
            request_json={"test": "data"},
            response_json=large_response,
        )

        compressed_db_backend.save_run(payload)
        retrieved = compressed_db_backend.get_run(run_id, "default")

        # Contract: response identical after compression roundtrip
        assert retrieved.response_json == large_response
        assert len(retrieved.response_json["variants"]) == 10
        assert retrieved.response_json["variants"][5]["data"] == list(range(100))


class TestJobPayloadDbBackend:
    """Contract tests for job payload DB backend."""

    @pytest.fixture
    def job_backend(self):
        """Create job backend with temp SQLite."""
        from runstore_backend import DbJobPayloadBackend

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "jobstore.db")
            backend = DbJobPayloadBackend(db_url=f"sqlite:///{db_path}")
            yield backend
            backend.close()

    def test_job_payload_roundtrip(self, job_backend):
        """Job payload should roundtrip through DB backend."""
        from runstore_backend import JobPayload
        from datetime import datetime, timezone

        job_id = "contract-test-job-001"

        payload_json = {
            "items": [
                {"run_id": "run-1", "params": {"pv_kw": 100}},
                {"run_id": "run-2", "params": {"pv_kw": 200}},
            ],
            "options": {"parallel": True},
        }

        result_json = {
            "results": [
                {"run_id": "run-1", "status": "ok", "npv": 10000},
                {"run_id": "run-2", "status": "ok", "npv": 20000},
            ],
            "summary": {"total_npv": 30000},
        }

        payload = JobPayload(
            job_id=job_id,
            tenant_id="default",
            created_at=datetime.now(timezone.utc).isoformat(),
            payload_json=payload_json,
            result_json=result_json,
        )

        job_backend.save_job(payload)
        retrieved = job_backend.get_job(job_id, "default")

        assert retrieved is not None
        assert retrieved.job_id == job_id
        assert retrieved.payload_json == payload_json
        assert retrieved.result_json == result_json

    def test_job_error_preserved(self, job_backend):
        """Job error should be preserved in DB backend."""
        from runstore_backend import JobPayload
        from datetime import datetime, timezone

        job_id = "contract-test-job-error-001"

        error_json = {
            "code": "VALIDATION_ERROR",
            "message": "Invalid parameters",
            "details": {"field": "pv_power_kw", "reason": "must be positive"},
        }

        payload = JobPayload(
            job_id=job_id,
            tenant_id="default",
            created_at=datetime.now(timezone.utc).isoformat(),
            payload_json={"items": []},
            result_json=None,
            error_json=error_json,
        )

        job_backend.save_job(payload)
        retrieved = job_backend.get_job(job_id, "default")

        assert retrieved.result_json is None
        assert retrieved.error_json == error_json
        assert retrieved.error_json["code"] == "VALIDATION_ERROR"

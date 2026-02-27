"""
Unit tests for runstore_backend DB roundtrip (v3.6.0 PR1).

Tests verify:
- DbRunPayloadBackend save and get
- DbJobPayloadBackend save and get
- Compression handling
- Tenant isolation
- Upsert behavior
"""

import pytest
import sys
import os
import tempfile
from pathlib import Path
from datetime import datetime, timezone

# Add services to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))


class TestDbRunPayloadBackendRoundtrip:
    """Tests for DbRunPayloadBackend save/get roundtrip."""

    @pytest.fixture
    def db_backend(self):
        """Create test backend with temp SQLite and cleanup after."""
        from runstore_backend import DbRunPayloadBackend

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            backend = DbRunPayloadBackend(
                db_url=f"sqlite:///{db_path}",
                compress=False,
            )
            yield backend
            backend.close()

    @pytest.fixture
    def compressed_db_backend(self):
        """Create test backend with compression enabled."""
        from runstore_backend import DbRunPayloadBackend

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            backend = DbRunPayloadBackend(
                db_url=f"sqlite:///{db_path}",
                compress=True,
            )
            yield backend
            backend.close()

    def test_save_and_get_basic(self, db_backend):
        """Should save and retrieve run payload."""
        from runstore_backend import RunPayload

        payload = RunPayload(
            run_id="run-123",
            tenant_id="tenant-1",
            created_at=datetime.now(timezone.utc).isoformat(),
            request_json={"pv_power_kw": 100, "battery_kwh": 50},
            response_json={"run_id": "run-123", "variants": []},
            meta_json={"endpoint": "sizing", "status": "ok"},
        )

        db_backend.save_run(payload)
        retrieved = db_backend.get_run("run-123", "tenant-1")

        assert retrieved is not None
        assert retrieved.run_id == "run-123"
        assert retrieved.tenant_id == "tenant-1"
        assert retrieved.request_json["pv_power_kw"] == 100
        assert retrieved.response_json["run_id"] == "run-123"
        assert retrieved.meta_json["endpoint"] == "sizing"

    def test_save_and_get_with_compression(self, compressed_db_backend):
        """Should handle compressed payloads."""
        from runstore_backend import RunPayload

        # Large payload to benefit from compression
        large_data = {"values": list(range(1000))}

        payload = RunPayload(
            run_id="run-compressed",
            tenant_id="default",
            created_at=datetime.now(timezone.utc).isoformat(),
            request_json=large_data,
            response_json={"result": "ok"},
        )

        compressed_db_backend.save_run(payload)
        retrieved = compressed_db_backend.get_run("run-compressed", "default")

        assert retrieved is not None
        assert retrieved.request_json["values"] == list(range(1000))

    def test_tenant_isolation(self, db_backend):
        """Should not return runs from other tenants."""
        from runstore_backend import RunPayload

        # Save run for tenant-1
        payload = RunPayload(
            run_id="run-isolated",
            tenant_id="tenant-1",
            created_at=datetime.now(timezone.utc).isoformat(),
            request_json={"data": "secret"},
            response_json={"result": "ok"},
        )
        db_backend.save_run(payload)

        # Try to get from tenant-2
        result = db_backend.get_run("run-isolated", "tenant-2")
        assert result is None

        # Get from tenant-1 should work
        result = db_backend.get_run("run-isolated", "tenant-1")
        assert result is not None

    def test_upsert_updates_existing(self, db_backend):
        """Should update existing run on save (upsert)."""
        from runstore_backend import RunPayload

        # Save initial
        payload1 = RunPayload(
            run_id="run-upsert",
            tenant_id="default",
            created_at=datetime.now(timezone.utc).isoformat(),
            request_json={"version": 1},
            response_json={"status": "initial"},
        )
        db_backend.save_run(payload1)

        # Update with same run_id
        payload2 = RunPayload(
            run_id="run-upsert",
            tenant_id="default",
            created_at=datetime.now(timezone.utc).isoformat(),
            request_json={"version": 2},
            response_json={"status": "updated"},
        )
        db_backend.save_run(payload2)

        # Should get updated version
        retrieved = db_backend.get_run("run-upsert", "default")
        assert retrieved.request_json["version"] == 2
        assert retrieved.response_json["status"] == "updated"

    def test_delete_run(self, db_backend):
        """Should delete run payload."""
        from runstore_backend import RunPayload

        payload = RunPayload(
            run_id="run-delete",
            tenant_id="default",
            created_at=datetime.now(timezone.utc).isoformat(),
            request_json={},
            response_json={},
        )
        db_backend.save_run(payload)

        # Delete
        result = db_backend.delete_run("run-delete", "default")
        assert result is True

        # Should not exist anymore
        assert db_backend.get_run("run-delete", "default") is None

    def test_delete_runs_before(self, db_backend):
        """Should delete runs created before cutoff."""
        from runstore_backend import RunPayload

        # Save old run
        old_payload = RunPayload(
            run_id="run-old",
            tenant_id="default",
            created_at="2020-01-01T00:00:00Z",
            request_json={},
            response_json={},
        )
        db_backend.save_run(old_payload)

        # Save new run
        new_payload = RunPayload(
            run_id="run-new",
            tenant_id="default",
            created_at="2025-01-01T00:00:00Z",
            request_json={},
            response_json={},
        )
        db_backend.save_run(new_payload)

        # Delete runs before 2024
        deleted = db_backend.delete_runs_before("2024-01-01T00:00:00Z")
        assert deleted == 1

        # Old should be gone, new should remain
        assert db_backend.get_run("run-old", "default") is None
        assert db_backend.get_run("run-new", "default") is not None


class TestDbJobPayloadBackendRoundtrip:
    """Tests for DbJobPayloadBackend save/get roundtrip."""

    @pytest.fixture
    def job_backend(self):
        """Create test backend with temp SQLite."""
        from runstore_backend import DbJobPayloadBackend

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            backend = DbJobPayloadBackend(db_url=f"sqlite:///{db_path}")
            yield backend
            backend.close()

    def test_save_and_get_job(self, job_backend):
        """Should save and retrieve job payload."""
        from runstore_backend import JobPayload

        payload = JobPayload(
            job_id="job-123",
            tenant_id="default",
            created_at=datetime.now(timezone.utc).isoformat(),
            payload_json={"items": [{"id": 1}, {"id": 2}]},
            result_json={"results": ["ok", "ok"]},
        )

        job_backend.save_job(payload)
        retrieved = job_backend.get_job("job-123", "default")

        assert retrieved is not None
        assert retrieved.job_id == "job-123"
        assert len(retrieved.payload_json["items"]) == 2
        assert retrieved.result_json["results"] == ["ok", "ok"]

    def test_job_with_error(self, job_backend):
        """Should handle job with error."""
        from runstore_backend import JobPayload

        payload = JobPayload(
            job_id="job-error",
            tenant_id="default",
            created_at=datetime.now(timezone.utc).isoformat(),
            payload_json={"items": []},
            result_json=None,
            error_json={"message": "Something went wrong", "code": "ERR001"},
        )

        job_backend.save_job(payload)
        retrieved = job_backend.get_job("job-error", "default")

        assert retrieved is not None
        assert retrieved.result_json is None
        assert retrieved.error_json["message"] == "Something went wrong"


class TestBackendFactory:
    """Tests for backend factory functions."""

    def test_get_run_payload_backend_default(self):
        """Should return filesystem backend by default."""
        from runstore_backend import (
            get_run_payload_backend,
            reset_backends,
            FilesystemRunPayloadBackend,
        )

        reset_backends()

        # Default should be filesystem
        backend = get_run_payload_backend()
        assert isinstance(backend, FilesystemRunPayloadBackend)

    def test_backend_caching(self):
        """Should cache backend instance."""
        from runstore_backend import get_run_payload_backend, reset_backends

        reset_backends()

        backend1 = get_run_payload_backend()
        backend2 = get_run_payload_backend()

        assert backend1 is backend2


class TestBackendAvailability:
    """Tests for backend availability checks."""

    def test_db_backend_unavailable_without_url(self):
        """DB backend should be unavailable without URL."""
        from runstore_backend import DbRunPayloadBackend

        backend = DbRunPayloadBackend(db_url="")
        assert backend.is_available() is False

    def test_db_backend_available_with_sqlite(self):
        """DB backend should be available with valid SQLite URL."""
        from runstore_backend import DbRunPayloadBackend

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            backend = DbRunPayloadBackend(db_url=f"sqlite:///{db_path}")
            try:
                assert backend.is_available() is True
            finally:
                backend.close()

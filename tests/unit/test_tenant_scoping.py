"""
Unit tests for tenant scoping (v3.0.0 PR2).

Tests verify:
- RunStore tenant isolation
- JobStore tenant isolation
- Cross-tenant access returns None (not 403)
"""

import pytest
import sys
import tempfile
from pathlib import Path


# Add services to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))


class TestRunStoreTenantScoping:
    """Tests for RunStore tenant isolation."""

    def test_save_with_tenant_id(self):
        """Runs should be saved with tenant_id."""
        from run_store import RunStore

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        store = RunStore(db_path)
        store.save(
            run_id="run-1",
            request_hash="hash123",
            endpoint="sizing",
            status="ok",
            cache_hit=False,
            schema_version="1.0.0",
            assumptions_version="abc",
            compute_time_ms=100,
            request={"test": True},
            response={"result": "ok"},
            tenant_id="tenant_a",
        )

        run = store.get("run-1")
        assert run is not None
        assert run["tenant_id"] == "tenant_a"

    def test_get_with_tenant_scoping(self):
        """get() with tenant_id should only return matching runs."""
        from run_store import RunStore

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        store = RunStore(db_path)
        store.save(
            run_id="run-2",
            request_hash="hash123",
            endpoint="sizing",
            status="ok",
            cache_hit=False,
            schema_version="1.0.0",
            assumptions_version="abc",
            compute_time_ms=100,
            request={"test": True},
            response={"result": "ok"},
            tenant_id="tenant_a",
        )

        # Same tenant - should return run
        run = store.get("run-2", tenant_id="tenant_a")
        assert run is not None

        # Different tenant - should return None
        run = store.get("run-2", tenant_id="tenant_b")
        assert run is None

        # No tenant filter - should return run
        run = store.get("run-2")
        assert run is not None

    def test_list_with_tenant_scoping(self):
        """list() with tenant_id should only return matching runs."""
        from run_store import RunStore

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        store = RunStore(db_path)

        # Create runs for different tenants
        for i, tenant in enumerate(["tenant_a", "tenant_a", "tenant_b"]):
            store.save(
                run_id=f"run-{i}",
                request_hash=f"hash{i}",
                endpoint="sizing",
                status="ok",
                cache_hit=False,
                schema_version="1.0.0",
                assumptions_version="abc",
                compute_time_ms=100,
                request={"test": True},
                response={"result": "ok"},
                tenant_id=tenant,
            )

        # List tenant_a runs
        result = store.list(tenant_id="tenant_a")
        assert result["total"] == 2

        # List tenant_b runs
        result = store.list(tenant_id="tenant_b")
        assert result["total"] == 1

        # List all runs (no filter)
        result = store.list()
        assert result["total"] == 3

    def test_update_metadata_with_tenant_scoping(self):
        """update_metadata() with tenant_id should only update matching runs."""
        from run_store import RunStore

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        store = RunStore(db_path)
        store.save(
            run_id="run-3",
            request_hash="hash123",
            endpoint="sizing",
            status="ok",
            cache_hit=False,
            schema_version="1.0.0",
            assumptions_version="abc",
            compute_time_ms=100,
            request={"test": True},
            response={"result": "ok"},
            tenant_id="tenant_a",
        )

        # Same tenant - should update
        updated = store.update_metadata("run-3", label="My Run", tenant_id="tenant_a")
        assert updated is True

        # Different tenant - should not find/update
        updated = store.update_metadata("run-3", label="Other", tenant_id="tenant_b")
        assert updated is False

        # Verify original label
        run = store.get("run-3")
        assert run["label"] == "My Run"


class TestJobStoreTenantScoping:
    """Tests for JobStore tenant isolation."""

    def test_create_job_with_tenant_id(self):
        """Jobs should be created with tenant_id."""
        from job_store import JobStore

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        store = JobStore(db_path)
        job_id = store.create_job(
            type="sizing_batch",
            request={"items": []},
            tenant_id="tenant_a",
        )

        job = store.get_job(job_id)
        assert job is not None
        assert job["tenant_id"] == "tenant_a"

    def test_get_job_with_tenant_scoping(self):
        """get_job() with tenant_id should only return matching jobs."""
        from job_store import JobStore

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        store = JobStore(db_path)
        job_id = store.create_job(
            type="sizing_batch",
            request={"items": []},
            tenant_id="tenant_a",
        )

        # Same tenant - should return job
        job = store.get_job(job_id, tenant_id="tenant_a")
        assert job is not None

        # Different tenant - should return None
        job = store.get_job(job_id, tenant_id="tenant_b")
        assert job is None

        # No tenant filter - should return job
        job = store.get_job(job_id)
        assert job is not None

    def test_list_jobs_with_tenant_scoping(self):
        """list_jobs() with tenant_id should only return matching jobs."""
        from job_store import JobStore

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        store = JobStore(db_path)

        # Create jobs for different tenants
        for tenant in ["tenant_a", "tenant_a", "tenant_b"]:
            store.create_job(
                type="sizing_batch",
                request={"items": []},
                tenant_id=tenant,
            )

        # List tenant_a jobs
        result = store.list_jobs(tenant_id="tenant_a")
        assert result["total"] == 2

        # List tenant_b jobs
        result = store.list_jobs(tenant_id="tenant_b")
        assert result["total"] == 1

        # List all jobs (no filter)
        result = store.list_jobs()
        assert result["total"] == 3

    def test_idempotency_key_scoped_by_tenant(self):
        """Idempotency key should be scoped by tenant."""
        from job_store import JobStore

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        store = JobStore(db_path)

        # Create job with idempotency key for tenant_a
        job_id_1 = store.create_job(
            type="sizing_batch",
            request={"items": []},
            idempotency_key="same-key",
            tenant_id="tenant_a",
        )

        # Same key for same tenant - should return existing job
        job_id_2 = store.create_job(
            type="sizing_batch",
            request={"items": []},
            idempotency_key="same-key",
            tenant_id="tenant_a",
        )
        assert job_id_1 == job_id_2

        # Same key for different tenant - should create new job
        job_id_3 = store.create_job(
            type="sizing_batch",
            request={"items": []},
            idempotency_key="same-key",
            tenant_id="tenant_b",
        )
        assert job_id_3 != job_id_1


class TestDefaultTenantMigration:
    """Tests for default tenant migration."""

    def test_run_store_default_tenant(self):
        """Runs without explicit tenant should get 'default' tenant."""
        from run_store import RunStore

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        store = RunStore(db_path)
        store.save(
            run_id="run-default",
            request_hash="hash123",
            endpoint="sizing",
            status="ok",
            cache_hit=False,
            schema_version="1.0.0",
            assumptions_version="abc",
            compute_time_ms=100,
            request={"test": True},
            response={"result": "ok"},
            # No tenant_id - should default to 'default'
        )

        run = store.get("run-default")
        assert run["tenant_id"] == "default"

    def test_job_store_default_tenant(self):
        """Jobs without explicit tenant should get 'default' tenant."""
        from job_store import JobStore

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        store = JobStore(db_path)
        job_id = store.create_job(
            type="sizing_batch",
            request={"items": []},
            # No tenant_id - should default to 'default'
        )

        job = store.get_job(job_id)
        assert job["tenant_id"] == "default"

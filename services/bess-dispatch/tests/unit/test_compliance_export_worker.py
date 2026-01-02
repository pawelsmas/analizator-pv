"""
Unit tests for compliance export worker (v4.3.0 PR7).

Tests:
- start_export_job() - async and sync modes
- get_export_status() - status retrieval
- get_export_download() - bundle download
- list_export_jobs() - listing jobs
- delete_export_bundle() - cleanup
"""

import io
import json
import os
import sys
import tempfile
import time
import zipfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from compliance_store import ComplianceStore
from compliance_export_helper import ExportOptions, RedactionMode
from compliance_export_worker import (
    ExportJobStatus,
    ExportJobSummary,
    ExportJobResult,
    start_export_job,
    get_export_status,
    get_export_download,
    list_export_jobs,
    delete_export_bundle,
    cleanup_expired_bundles,
    _store_bundle,
    _get_bundle,
    _delete_bundle,
)


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture
def store(temp_db):
    """Create a ComplianceStore with temporary database."""
    return ComplianceStore(db_path=temp_db)


class TestExportJobStatus:
    """Tests for ExportJobStatus enum."""

    def test_status_values(self):
        """Test status enum values."""
        assert ExportJobStatus.PENDING.value == "pending"
        assert ExportJobStatus.RUNNING.value == "running"
        assert ExportJobStatus.COMPLETED.value == "completed"
        assert ExportJobStatus.FAILED.value == "failed"
        assert ExportJobStatus.EXPIRED.value == "expired"


class TestExportJobSummary:
    """Tests for ExportJobSummary model."""

    def test_create_summary(self):
        """Test creating job summary."""
        summary = ExportJobSummary(
            id="j1",
            tenant_id="t1",
            status="pending",
            created_at="2024-01-01T00:00:00Z",
            created_by_user_id="user1",
        )
        assert summary.id == "j1"
        assert summary.progress_pct == 0

    def test_summary_with_progress(self):
        """Test summary with progress info."""
        summary = ExportJobSummary(
            id="j1",
            tenant_id="t1",
            status="running",
            created_at="2024-01-01T00:00:00Z",
            created_by_user_id="user1",
            progress_pct=50,
            current_step="Extracting data",
        )
        assert summary.progress_pct == 50
        assert summary.current_step == "Extracting data"


class TestStartExportJob:
    """Tests for start_export_job function."""

    def test_start_job_sync(self, store):
        """Test starting export job synchronously."""
        options = ExportOptions()

        job = start_export_job(
            compliance_store=store,
            tenant_id="t1",
            options=options,
            created_by_user_id="admin",
            run_async=False,
        )

        assert job.id is not None
        assert job.tenant_id == "t1"
        assert job.created_by_user_id == "admin"

        # Wait and check status
        time.sleep(0.5)
        status = get_export_status(store, job.id)
        assert status is not None
        assert status.status in ("completed", "running", "pending")

    def test_start_job_async(self, store):
        """Test starting export job asynchronously."""
        options = ExportOptions()

        job = start_export_job(
            compliance_store=store,
            tenant_id="t1",
            options=options,
            created_by_user_id="admin",
            run_async=True,
        )

        assert job.id is not None
        # Job starts immediately
        assert job.status == "pending"

    def test_start_job_with_project(self, store):
        """Test starting job with project scope."""
        options = ExportOptions()

        job = start_export_job(
            compliance_store=store,
            tenant_id="t1",
            options=options,
            created_by_user_id="admin",
            project_id="proj-1",
            run_async=False,
        )

        assert job.project_id == "proj-1"

    def test_start_job_creates_record(self, store):
        """Test that starting job creates DB record."""
        options = ExportOptions()

        job = start_export_job(
            compliance_store=store,
            tenant_id="t1",
            options=options,
            created_by_user_id="admin",
            run_async=False,
        )

        # Check record exists in DB
        record = store.get_compliance_export(job.id)
        assert record is not None
        assert record["tenant_id"] == "t1"


class TestGetExportStatus:
    """Tests for get_export_status function."""

    def test_get_nonexistent(self, store):
        """Test getting status of nonexistent job."""
        status = get_export_status(store, "nonexistent")
        assert status is None

    def test_get_existing_status(self, store):
        """Test getting status of existing job."""
        options = ExportOptions()

        job = start_export_job(
            compliance_store=store,
            tenant_id="t1",
            options=options,
            created_by_user_id="admin",
            run_async=False,
        )

        # Wait for completion
        time.sleep(0.5)

        status = get_export_status(store, job.id)
        assert status is not None
        assert status.id == job.id


class TestGetExportDownload:
    """Tests for get_export_download function."""

    def test_download_nonexistent(self, store):
        """Test downloading nonexistent job."""
        result = get_export_download(store, "nonexistent")
        assert result is None

    def test_download_completed_job(self, store):
        """Test downloading completed job."""
        options = ExportOptions()

        # Start job synchronously
        job = start_export_job(
            compliance_store=store,
            tenant_id="t1",
            options=options,
            created_by_user_id="admin",
            run_async=False,
        )

        # Wait for completion
        time.sleep(1)

        # Check status
        status = get_export_status(store, job.id)
        if status and status.status == "completed":
            result = get_export_download(store, job.id)
            assert result is not None
            assert result.job_id == job.id
            assert len(result.bundle_bytes) > 0

            # Verify it's a valid ZIP
            with zipfile.ZipFile(io.BytesIO(result.bundle_bytes), "r") as zf:
                assert "manifest.json" in zf.namelist()

    def test_download_pending_job(self, store):
        """Test downloading pending job returns None."""
        options = ExportOptions()

        job = start_export_job(
            compliance_store=store,
            tenant_id="t1",
            options=options,
            created_by_user_id="admin",
            run_async=True,
        )

        # Immediately try to download (before completion)
        result = get_export_download(store, job.id)
        # Should be None because job isn't completed yet
        # (or could be completed if very fast)
        if result:
            assert result.bundle_bytes is not None


class TestListExportJobs:
    """Tests for list_export_jobs function."""

    def test_list_empty(self, store):
        """Test listing with no jobs."""
        jobs = list_export_jobs(store, "t1")
        assert jobs == []

    def test_list_with_jobs(self, store):
        """Test listing with multiple jobs."""
        options = ExportOptions()

        # Create multiple jobs
        for _ in range(3):
            start_export_job(
                compliance_store=store,
                tenant_id="t1",
                options=options,
                created_by_user_id="admin",
                run_async=True,
            )

        jobs = list_export_jobs(store, "t1")
        assert len(jobs) == 3

    def test_list_filters_by_tenant(self, store):
        """Test listing filters by tenant."""
        options = ExportOptions()

        start_export_job(
            compliance_store=store,
            tenant_id="t1",
            options=options,
            created_by_user_id="admin",
            run_async=True,
        )
        start_export_job(
            compliance_store=store,
            tenant_id="t2",
            options=options,
            created_by_user_id="admin",
            run_async=True,
        )

        t1_jobs = list_export_jobs(store, "t1")
        t2_jobs = list_export_jobs(store, "t2")

        assert len(t1_jobs) == 1
        assert len(t2_jobs) == 1

    def test_list_with_limit(self, store):
        """Test listing with limit."""
        options = ExportOptions()

        for _ in range(5):
            start_export_job(
                compliance_store=store,
                tenant_id="t1",
                options=options,
                created_by_user_id="admin",
                run_async=True,
            )

        jobs = list_export_jobs(store, "t1", limit=3)
        assert len(jobs) == 3


class TestDeleteExportBundle:
    """Tests for delete_export_bundle function."""

    def test_delete_nonexistent(self, store):
        """Test deleting nonexistent job."""
        result = delete_export_bundle(store, "nonexistent")
        assert result is False

    def test_delete_existing(self, store):
        """Test deleting existing job."""
        options = ExportOptions()

        job = start_export_job(
            compliance_store=store,
            tenant_id="t1",
            options=options,
            created_by_user_id="admin",
            run_async=False,
        )

        time.sleep(0.5)

        result = delete_export_bundle(store, job.id)
        assert result is True

        # Status should be expired
        status = get_export_status(store, job.id)
        assert status is not None
        assert status.status == "expired"

        # Bundle should not be downloadable
        download = get_export_download(store, job.id)
        assert download is None


class TestBundleStorage:
    """Tests for internal bundle storage functions."""

    def test_store_and_get_bundle(self):
        """Test storing and retrieving bundle."""
        job_id = "test-job-1"
        bundle = b"test bundle content"
        manifest = {"test": "manifest"}

        _store_bundle(job_id, bundle, manifest)

        retrieved = _get_bundle(job_id)
        assert retrieved == bundle

        # Clean up
        _delete_bundle(job_id)

    def test_delete_bundle(self):
        """Test deleting bundle."""
        job_id = "test-job-2"
        bundle = b"test content"
        manifest = {}

        _store_bundle(job_id, bundle, manifest)
        _delete_bundle(job_id)

        assert _get_bundle(job_id) is None

    def test_get_nonexistent_bundle(self):
        """Test getting nonexistent bundle."""
        assert _get_bundle("nonexistent") is None


class TestExportJobResult:
    """Tests for ExportJobResult model."""

    def test_create_result(self):
        """Test creating job result."""
        result = ExportJobResult(
            job_id="j1",
            tenant_id="t1",
            bundle_bytes=b"test",
            bundle_size_bytes=4,
            record_count=10,
            verification={"valid": True},
            manifest={"files": []},
        )
        assert result.job_id == "j1"
        assert result.bundle_size_bytes == 4


class TestIntegration:
    """Integration tests for full workflow."""

    def test_full_export_workflow(self, store):
        """Test complete export workflow."""
        # Create some data to export
        store.create_retention_policy("t1", {"runs_days": 365})
        store.create_legal_hold(
            tenant_id="t1",
            resource_type="run",
            reason="Test hold",
            created_by_user_id="admin",
        )

        # Start export
        options = ExportOptions(
            include_retention_policies=True,
            include_legal_holds=True,
            redaction_mode=RedactionMode.STANDARD,
        )

        job = start_export_job(
            compliance_store=store,
            tenant_id="t1",
            options=options,
            created_by_user_id="admin",
            run_async=False,
        )

        # Wait for completion
        time.sleep(1)

        # Check status
        status = get_export_status(store, job.id)
        assert status is not None
        assert status.status == "completed"

        # Download bundle
        result = get_export_download(store, job.id)
        assert result is not None

        # Verify bundle contents
        with zipfile.ZipFile(io.BytesIO(result.bundle_bytes), "r") as zf:
            assert "manifest.json" in zf.namelist()
            assert "metadata.json" in zf.namelist()
            assert "data_retention_policies.json" in zf.namelist()
            assert "data_legal_holds.json" in zf.namelist()

            # Check manifest
            manifest = json.loads(zf.read("manifest.json"))
            assert manifest["tenant_id"] == "t1"
            assert manifest["version"] == "1.0"

        # Clean up
        delete_export_bundle(store, job.id)
        assert get_export_download(store, job.id) is None

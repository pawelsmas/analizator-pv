"""
Contract tests for Report Jobs (v3.4.0 PR3).

Tests:
- job_handlers module imports and handlers
- job_artifacts module for artifact storage
- report_run and report_portfolio job execution
- artifacts endpoints on jobs router
"""

import pytest
import os
import sys
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add service to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))


class TestJobArtifactsImports:
    """Tests for job_artifacts module imports."""

    def test_import_job_artifacts(self):
        """job_artifacts should be importable."""
        import job_artifacts
        assert job_artifacts is not None

    def test_import_artifact_info(self):
        """ArtifactInfo model should be importable."""
        from job_artifacts import ArtifactInfo
        assert ArtifactInfo is not None

    def test_import_save_artifact(self):
        """save_artifact should be importable."""
        from job_artifacts import save_artifact
        assert callable(save_artifact)

    def test_import_get_artifact(self):
        """get_artifact should be importable."""
        from job_artifacts import get_artifact
        assert callable(get_artifact)

    def test_import_list_artifacts(self):
        """list_artifacts should be importable."""
        from job_artifacts import list_artifacts
        assert callable(list_artifacts)

    def test_import_delete_artifacts(self):
        """delete_artifacts should be importable."""
        from job_artifacts import delete_artifacts
        assert callable(delete_artifacts)


class TestArtifactInfoModel:
    """Tests for ArtifactInfo model."""

    def test_artifact_info_fields(self):
        """ArtifactInfo should have required fields."""
        from job_artifacts import ArtifactInfo

        info = ArtifactInfo(
            name="report.pdf",
            content_type="application/pdf",
            size_bytes=12345,
            created_at="2024-01-01T00:00:00Z",
        )

        assert info.name == "report.pdf"
        assert info.content_type == "application/pdf"
        assert info.size_bytes == 12345


class TestArtifactStorage:
    """Tests for artifact storage operations."""

    def test_save_and_get_artifact(self):
        """save_artifact and get_artifact should work together."""
        from job_artifacts import save_artifact, get_artifact, delete_artifacts

        # Use temp directory
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('job_artifacts.ARTIFACTS_DIR', Path(tmpdir)):
                job_id = "test-job-123"
                content = b"Hello, World!"

                # Save artifact
                info = save_artifact(job_id, "test.txt", content, "text/plain")

                assert info.name == "test.txt"
                assert info.content_type == "text/plain"
                assert info.size_bytes == len(content)

                # Get artifact
                result = get_artifact(job_id, "test.txt")
                assert result is not None
                retrieved_content, content_type = result
                assert retrieved_content == content
                assert content_type == "text/plain"

                # Cleanup
                delete_artifacts(job_id)

    def test_list_artifacts(self):
        """list_artifacts should return all artifacts for a job."""
        from job_artifacts import save_artifact, list_artifacts, delete_artifacts

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('job_artifacts.ARTIFACTS_DIR', Path(tmpdir)):
                job_id = "test-job-456"

                # Save multiple artifacts
                save_artifact(job_id, "report.pdf", b"PDF content", "application/pdf")
                save_artifact(job_id, "report.xlsx", b"XLSX content", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

                # List artifacts
                artifacts = list_artifacts(job_id)

                assert len(artifacts) == 2
                names = [a.name for a in artifacts]
                assert "report.pdf" in names
                assert "report.xlsx" in names

                # Cleanup
                delete_artifacts(job_id)

    def test_get_nonexistent_artifact(self):
        """get_artifact should return None for nonexistent artifacts."""
        from job_artifacts import get_artifact

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('job_artifacts.ARTIFACTS_DIR', Path(tmpdir)):
                result = get_artifact("nonexistent-job", "missing.pdf")
                assert result is None

    def test_list_empty_artifacts(self):
        """list_artifacts should return empty list for jobs without artifacts."""
        from job_artifacts import list_artifacts

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('job_artifacts.ARTIFACTS_DIR', Path(tmpdir)):
                artifacts = list_artifacts("nonexistent-job")
                assert artifacts == []


class TestJobHandlersImports:
    """Tests for job_handlers module imports."""

    def test_import_job_handlers(self):
        """job_handlers should be importable."""
        import job_handlers
        assert job_handlers is not None

    def test_import_execute_job(self):
        """execute_job should be importable."""
        from job_handlers import execute_job
        assert callable(execute_job)

    def test_import_handler_registry(self):
        """JOB_HANDLERS registry should be importable."""
        from job_handlers import JOB_HANDLERS
        assert isinstance(JOB_HANDLERS, dict)

    def test_handler_registry_has_report_run(self):
        """JOB_HANDLERS should have report_run handler."""
        from job_handlers import JOB_HANDLERS
        assert "report_run" in JOB_HANDLERS

    def test_handler_registry_has_report_portfolio(self):
        """JOB_HANDLERS should have report_portfolio handler."""
        from job_handlers import JOB_HANDLERS
        assert "report_portfolio" in JOB_HANDLERS

    def test_handler_registry_has_sizing_batch(self):
        """JOB_HANDLERS should have sizing_batch handler."""
        from job_handlers import JOB_HANDLERS
        assert "sizing_batch" in JOB_HANDLERS

    def test_handler_registry_has_validate_pack(self):
        """JOB_HANDLERS should have validate_pack handler."""
        from job_handlers import JOB_HANDLERS
        assert "validate_pack" in JOB_HANDLERS


class TestReportRunHandler:
    """Tests for report_run handler."""

    def test_handle_report_run_exists(self):
        """handle_report_run should be callable."""
        from job_handlers import handle_report_run
        assert callable(handle_report_run)

    def test_handle_report_run_missing_run_id(self):
        """handle_report_run should return error if run_id missing."""
        from job_handlers import handle_report_run
        from db_models import JobQueue

        job = MagicMock(spec=JobQueue)
        job.id = "test-job"
        job.payload_json = "{}"

        result = handle_report_run(job, {})

        assert result["success"] is False
        assert result["error_code"] == "MISSING_RUN_ID"


class TestReportPortfolioHandler:
    """Tests for report_portfolio handler."""

    def test_handle_report_portfolio_exists(self):
        """handle_report_portfolio should be callable."""
        from job_handlers import handle_report_portfolio
        assert callable(handle_report_portfolio)

    def test_handle_report_portfolio_missing_run_ids(self):
        """handle_report_portfolio should return error if run_ids missing."""
        from job_handlers import handle_report_portfolio
        from db_models import JobQueue

        job = MagicMock(spec=JobQueue)
        job.id = "test-job"
        job.payload_json = "{}"

        result = handle_report_portfolio(job, {})

        assert result["success"] is False
        assert result["error_code"] == "MISSING_RUN_IDS"


class TestSizingBatchHandler:
    """Tests for sizing_batch handler (stub)."""

    def test_handle_sizing_batch_not_implemented(self):
        """sizing_batch should return NOT_IMPLEMENTED."""
        from job_handlers import handle_sizing_batch
        from db_models import JobQueue

        job = MagicMock(spec=JobQueue)
        job.id = "test-job"

        result = handle_sizing_batch(job, {})

        assert result["success"] is False
        assert result["error_code"] == "NOT_IMPLEMENTED"


class TestValidatePackHandler:
    """Tests for validate_pack handler (stub)."""

    def test_handle_validate_pack_not_implemented(self):
        """validate_pack should return NOT_IMPLEMENTED."""
        from job_handlers import handle_validate_pack
        from db_models import JobQueue

        job = MagicMock(spec=JobQueue)
        job.id = "test-job"

        result = handle_validate_pack(job, {})

        assert result["success"] is False
        assert result["error_code"] == "NOT_IMPLEMENTED"


class TestExecuteJobDispatch:
    """Tests for execute_job dispatch to handlers."""

    def test_execute_job_unknown_kind(self):
        """execute_job should return error for unknown job kind."""
        from job_handlers import execute_job
        from db_models import JobQueue

        job = MagicMock(spec=JobQueue)
        job.id = "test-job"
        job.kind = "unknown_kind"
        job.payload_json = "{}"

        result = execute_job(job)

        assert result["success"] is False
        assert result["error_code"] == "UNKNOWN_JOB_KIND"

    def test_execute_job_invalid_payload(self):
        """execute_job should return error for invalid payload JSON."""
        from job_handlers import execute_job
        from db_models import JobQueue

        job = MagicMock(spec=JobQueue)
        job.id = "test-job"
        job.kind = "report_run"
        job.payload_json = "{invalid json"

        result = execute_job(job)

        assert result["success"] is False
        assert result["error_code"] == "INVALID_PAYLOAD"


class TestArtifactsEndpoints:
    """Tests for artifacts endpoints on jobs router."""

    def test_list_job_artifacts_exists(self):
        """list_job_artifacts endpoint should exist."""
        from jobs_router import list_job_artifacts
        assert callable(list_job_artifacts)

    def test_download_artifact_exists(self):
        """download_artifact endpoint should exist."""
        from jobs_router import download_artifact
        assert callable(download_artifact)

    def test_artifact_list_response_model(self):
        """ArtifactListResponse should have correct fields."""
        from jobs_router import ArtifactListResponse
        from job_artifacts import ArtifactInfo

        resp = ArtifactListResponse(
            job_id="test-123",
            artifacts=[
                ArtifactInfo(
                    name="report.pdf",
                    content_type="application/pdf",
                    size_bytes=1000,
                    created_at="2024-01-01T00:00:00Z",
                )
            ],
        )

        assert resp.job_id == "test-123"
        assert len(resp.artifacts) == 1
        assert resp.artifacts[0].name == "report.pdf"


class TestWorkerHandlerIntegration:
    """Tests for worker using job_handlers."""

    def test_worker_execute_job_uses_handlers(self):
        """Worker execute_job should delegate to job_handlers."""
        from worker.worker import execute_job
        from db_models import JobQueue

        job = MagicMock(spec=JobQueue)
        job.id = "test-job"
        job.kind = "unknown_kind"
        job.payload_json = "{}"

        # Should call job_handlers.execute_job
        result = execute_job(job)

        assert result["success"] is False
        assert result["error_code"] == "UNKNOWN_JOB_KIND"

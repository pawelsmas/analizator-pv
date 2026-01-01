"""
Unit tests for RunIndex and JobIndex models (v3.3.0 PR4).

Tests SQLAlchemy ORM models for runs and jobs indexing.
"""

import pytest
import os
import sys
import json
import zlib
from datetime import datetime, timezone

# Add service to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))


class TestRunIndexModel:
    """Tests for RunIndex ORM model."""

    def test_run_index_import(self):
        """RunIndex should be importable."""
        from db_models import RunIndex
        assert RunIndex is not None

    def test_run_index_tablename(self):
        """RunIndex should have correct table name."""
        from db_models import RunIndex
        assert RunIndex.__tablename__ == "run_index"

    def test_run_index_columns(self):
        """RunIndex should have all required columns."""
        from db_models import RunIndex

        columns = {c.name for c in RunIndex.__table__.columns}

        # Core columns
        assert "run_id" in columns
        assert "tenant_id" in columns
        assert "request_hash" in columns
        assert "created_at" in columns
        assert "endpoint" in columns
        assert "status" in columns
        assert "cache_hit" in columns
        assert "schema_version" in columns
        assert "assumptions_version" in columns
        assert "compute_time_ms" in columns

        # Metadata columns
        assert "label" in columns
        assert "tags_json" in columns
        assert "notes" in columns
        assert "updated_at" in columns

        # Blob columns
        assert "request_blob" in columns
        assert "response_blob" in columns

    def test_run_index_to_dict_basic(self):
        """RunIndex.to_dict should return correct dict."""
        from db_models import RunIndex

        now = datetime.now(timezone.utc)
        run = RunIndex(
            run_id="test-run-123",
            tenant_id="tenant-1",
            request_hash="abc123",
            created_at=now,
            endpoint="sizing",
            status="ok",
            cache_hit=False,
        )
        result = run.to_dict()

        assert result["run_id"] == "test-run-123"
        assert result["tenant_id"] == "tenant-1"
        assert result["request_hash"] == "abc123"
        assert result["endpoint"] == "sizing"
        assert result["status"] == "ok"
        assert result["cache_hit"] == False

    def test_run_index_to_dict_with_tags(self):
        """RunIndex.to_dict should parse tags from JSON."""
        from db_models import RunIndex

        run = RunIndex(
            run_id="test-run-123",
            tenant_id="tenant-1",
            request_hash="abc123",
            created_at=datetime.now(timezone.utc),
            endpoint="sizing",
            status="ok",
            cache_hit=False,
            tags_json='["tag1", "tag2", "tag3"]',
        )
        result = run.to_dict()

        assert result["tags"] == ["tag1", "tag2", "tag3"]

    def test_run_index_to_dict_with_blobs(self):
        """RunIndex.to_dict should decompress blobs when requested."""
        from db_models import RunIndex

        request = {"key": "value"}
        response = {"result": "success"}
        request_blob = zlib.compress(json.dumps(request).encode("utf-8"))
        response_blob = zlib.compress(json.dumps(response).encode("utf-8"))

        run = RunIndex(
            run_id="test-run-123",
            tenant_id="tenant-1",
            request_hash="abc123",
            created_at=datetime.now(timezone.utc),
            endpoint="sizing",
            status="ok",
            cache_hit=False,
            request_blob=request_blob,
            response_blob=response_blob,
        )

        # Without blobs
        result_no_blobs = run.to_dict(include_blobs=False)
        assert "request" not in result_no_blobs
        assert "response" not in result_no_blobs

        # With blobs
        result_with_blobs = run.to_dict(include_blobs=True)
        assert result_with_blobs["request"] == request
        assert result_with_blobs["response"] == response


class TestJobIndexModel:
    """Tests for JobIndex ORM model."""

    def test_job_index_import(self):
        """JobIndex should be importable."""
        from db_models import JobIndex
        assert JobIndex is not None

    def test_job_index_tablename(self):
        """JobIndex should have correct table name."""
        from db_models import JobIndex
        assert JobIndex.__tablename__ == "job_index"

    def test_job_index_columns(self):
        """JobIndex should have all required columns."""
        from db_models import JobIndex

        columns = {c.name for c in JobIndex.__table__.columns}

        # Core columns
        assert "job_id" in columns
        assert "tenant_id" in columns
        assert "created_at" in columns
        assert "updated_at" in columns
        assert "type" in columns
        assert "status" in columns
        assert "batch_id" in columns
        assert "idempotency_key" in columns
        assert "items_total" in columns
        assert "items_done" in columns
        assert "error_count" in columns
        assert "request_hash" in columns
        assert "message" in columns

        # Leasing columns
        assert "lease_owner" in columns
        assert "lease_expires_at" in columns
        assert "attempts" in columns
        assert "max_attempts" in columns
        assert "started_at" in columns
        assert "finished_at" in columns
        assert "last_error" in columns

        # Metadata columns
        assert "label" in columns
        assert "tags_json" in columns
        assert "notes" in columns

        # Blob columns
        assert "request_blob" in columns
        assert "result_blob" in columns

    def test_job_index_to_dict_basic(self):
        """JobIndex.to_dict should return correct dict."""
        from db_models import JobIndex

        now = datetime.now(timezone.utc)
        job = JobIndex(
            job_id="test-job-123",
            tenant_id="tenant-1",
            created_at=now,
            updated_at=now,
            type="sizing_batch",
            status="pending",
            items_total=10,
            items_done=0,
            error_count=0,
            request_hash="abc123",
        )
        result = job.to_dict()

        assert result["job_id"] == "test-job-123"
        assert result["tenant_id"] == "tenant-1"
        assert result["type"] == "sizing_batch"
        assert result["status"] == "pending"
        assert result["items_total"] == 10
        assert result["items_done"] == 0
        assert result["error_count"] == 0

    def test_job_index_to_dict_with_leasing(self):
        """JobIndex.to_dict should include leasing info."""
        from db_models import JobIndex

        now = datetime.now(timezone.utc)
        job = JobIndex(
            job_id="test-job-123",
            tenant_id="tenant-1",
            created_at=now,
            updated_at=now,
            type="sizing_batch",
            status="running",
            items_total=10,
            items_done=5,
            error_count=0,
            request_hash="abc123",
            lease_owner="worker-1",
            lease_expires_at=now,
            attempts=1,
            max_attempts=3,
            started_at=now,
        )
        result = job.to_dict()

        assert result["lease_owner"] == "worker-1"
        assert result["attempts"] == 1
        assert result["max_attempts"] == 3
        assert result["started_at"] is not None

    def test_job_index_to_dict_with_blobs(self):
        """JobIndex.to_dict should decompress blobs when requested."""
        from db_models import JobIndex

        request = {"items": [1, 2, 3]}
        result_data = {"results": ["a", "b", "c"]}
        request_blob = zlib.compress(json.dumps(request).encode("utf-8"))
        result_blob = zlib.compress(json.dumps(result_data).encode("utf-8"))

        now = datetime.now(timezone.utc)
        job = JobIndex(
            job_id="test-job-123",
            tenant_id="tenant-1",
            created_at=now,
            updated_at=now,
            type="sizing_batch",
            status="done",
            items_total=3,
            items_done=3,
            error_count=0,
            request_hash="abc123",
            request_blob=request_blob,
            result_blob=result_blob,
        )

        # Without blobs
        result_no_blobs = job.to_dict(include_blobs=False)
        assert "request" not in result_no_blobs
        assert "result" not in result_no_blobs

        # With blobs
        result_with_blobs = job.to_dict(include_blobs=True)
        assert result_with_blobs["request"] == request
        assert result_with_blobs["result"] == result_data


class TestIndexMetadata:
    """Tests for index table metadata and constraints."""

    def test_run_index_has_indexes(self):
        """RunIndex should have proper indexes defined."""
        from db_models import RunIndex

        index_names = {idx.name for idx in RunIndex.__table__.indexes}

        assert "idx_run_index_tenant" in index_names
        assert "idx_run_index_created_at" in index_names
        assert "idx_run_index_request_hash" in index_names
        assert "idx_run_index_endpoint" in index_names
        assert "idx_run_index_status" in index_names
        assert "idx_run_index_tenant_created" in index_names

    def test_job_index_has_indexes(self):
        """JobIndex should have proper indexes defined."""
        from db_models import JobIndex

        index_names = {idx.name for idx in JobIndex.__table__.indexes}

        assert "idx_job_index_tenant" in index_names
        assert "idx_job_index_created_at" in index_names
        assert "idx_job_index_status" in index_names
        assert "idx_job_index_type" in index_names
        assert "idx_job_index_idempotency_key" in index_names
        assert "idx_job_index_lease_expires" in index_names
        assert "idx_job_index_tenant_status" in index_names

"""
Unit tests for webhook events SSoT (v4.1.0).

Tests verify:
- Event ID generation
- Canonical payload structure
- Dedup key generation
- Event emission to outbox
"""

import os
import sys
import tempfile
import pytest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))

from webhook_events import (
    EventType,
    WebhookEventEmitter,
    generate_event_id,
    generate_dedup_key,
    JobSucceededPayload,
    JobFailedPayload,
    ReportGeneratedPayload,
    ShareAccessedPayload,
    QuotaExceededPayload,
    RunCreatedPayload,
)
from webhook_store import WebhookStore


# -------------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------------

@pytest.fixture
def temp_db():
    """Create a temporary database file."""
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def store(temp_db):
    """Create a WebhookStore instance."""
    return WebhookStore(db_path=temp_db)


@pytest.fixture
def emitter(store):
    """Create a WebhookEventEmitter instance."""
    return WebhookEventEmitter(store)


@pytest.fixture
def webhook(store):
    """Create a test webhook subscribed to all events."""
    webhook, _ = store.create_webhook(
        tenant_id="test-tenant",
        name="Test Webhook",
        url="https://example.com/hook",
        events=["job.succeeded", "job.failed", "report.generated",
                "share.accessed", "quota.exceeded", "run.created"],
        project_id="project-1",
    )
    return webhook


# -------------------------------------------------------------------------
# Test: Event ID Generation
# -------------------------------------------------------------------------

class TestEventIdGeneration:
    """Tests for event ID generation."""

    def test_event_id_format(self):
        """Should generate event ID in correct format."""
        event_id = generate_event_id(
            "job.succeeded", "tenant-1", "project-1", "job-123"
        )

        assert event_id.startswith("evt_job_")
        parts = event_id.split("_")
        assert len(parts) == 4
        assert parts[0] == "evt"
        assert parts[1] == "job"
        # parts[2] is timestamp
        assert len(parts[3]) == 8  # Hash suffix

    def test_event_id_unique_for_different_jobs(self):
        """Should generate different IDs for different jobs."""
        id1 = generate_event_id("job.succeeded", "tenant-1", "project-1", "job-1")
        id2 = generate_event_id("job.succeeded", "tenant-1", "project-1", "job-2")

        # Hash suffix should differ
        assert id1.split("_")[-1] != id2.split("_")[-1]

    def test_event_id_for_different_types(self):
        """Should include event type prefix."""
        job_id = generate_event_id("job.succeeded", "t", "p", "j")
        report_id = generate_event_id("report.generated", "t", "p", "r")
        share_id = generate_event_id("share.accessed", "t", "p", "s")

        assert "_job_" in job_id
        assert "_rep_" in report_id
        assert "_sha_" in share_id


# -------------------------------------------------------------------------
# Test: Dedup Key Generation
# -------------------------------------------------------------------------

class TestDedupKeyGeneration:
    """Tests for dedup key generation."""

    def test_dedup_key_format(self):
        """Should generate dedup key in correct format."""
        key = generate_dedup_key(
            "quota.exceeded", "tenant-1", "project-1", "jobs_per_day:2024-01-01"
        )

        assert key == "quota.exceeded:jobs_per_day:2024-01-01:project-1"

    def test_dedup_key_uses_tenant_when_no_project(self):
        """Should use tenant_id when project_id is None."""
        key = generate_dedup_key(
            "quota.exceeded", "tenant-1", None, "jobs_per_day:2024-01-01"
        )

        assert key == "quota.exceeded:jobs_per_day:2024-01-01:tenant-1"


# -------------------------------------------------------------------------
# Test: Payload Models
# -------------------------------------------------------------------------

class TestPayloadModels:
    """Tests for event payload models."""

    def test_job_succeeded_payload(self):
        """Should create job succeeded payload."""
        payload = JobSucceededPayload(
            event_id="evt_job_123_abcdef12",
            event_type="job.succeeded",
            timestamp="2024-01-01T12:00:00Z",
            tenant_id="tenant-1",
            project_id="project-1",
            job_id="job-123",
            job_type="sizing",
            run_id="run-456",
            duration_ms=5000,
            summary={"npv_pln": 100000, "capex_pln": 50000},
        )

        data = payload.to_dict()
        assert data["event_type"] == "job.succeeded"
        assert data["job_id"] == "job-123"
        assert data["job_type"] == "sizing"
        assert data["summary"]["npv_pln"] == 100000

    def test_job_failed_payload(self):
        """Should create job failed payload."""
        payload = JobFailedPayload(
            event_id="evt_job_123_abcdef12",
            event_type="job.failed",
            timestamp="2024-01-01T12:00:00Z",
            tenant_id="tenant-1",
            project_id="project-1",
            job_id="job-123",
            job_type="validation",
            run_id=None,
            error_code="SOLVER_ERROR",
            error_message="Infeasible solution",
            duration_ms=1000,
        )

        data = payload.to_dict()
        assert data["error_code"] == "SOLVER_ERROR"
        assert "run_id" not in data  # None values excluded

    def test_quota_exceeded_payload(self):
        """Should create quota exceeded payload."""
        payload = QuotaExceededPayload(
            event_id="evt_quo_123_abcdef12",
            event_type="quota.exceeded",
            timestamp="2024-01-01T12:00:00Z",
            tenant_id="tenant-1",
            project_id="project-1",
            quota_name="jobs_per_day",
            quota_limit=100,
            current_usage=101,
            period="daily",
            reset_at="2024-01-02T00:00:00Z",
        )

        data = payload.to_dict()
        assert data["quota_name"] == "jobs_per_day"
        assert data["quota_limit"] == 100
        assert data["current_usage"] == 101


# -------------------------------------------------------------------------
# Test: Event Emission
# -------------------------------------------------------------------------

class TestEventEmission:
    """Tests for event emission to outbox."""

    def test_emit_job_succeeded(self, emitter, webhook, store):
        """Should emit job.succeeded event to outbox."""
        event_id = emitter.emit_job_succeeded(
            tenant_id="test-tenant",
            project_id="project-1",
            job_id="job-123",
            job_type="sizing",
            run_id="run-456",
            duration_ms=5000,
            summary={"npv_pln": 100000},
        )

        assert event_id.startswith("evt_job_")

        # Verify in outbox
        depth = store.get_outbox_depth("queued")
        assert depth == 1

    def test_emit_job_failed(self, emitter, webhook, store):
        """Should emit job.failed event to outbox."""
        event_id = emitter.emit_job_failed(
            tenant_id="test-tenant",
            project_id="project-1",
            job_id="job-123",
            job_type="sizing",
            run_id=None,
            error_code="TIMEOUT",
            error_message="Job timed out",
        )

        assert event_id.startswith("evt_job_")
        assert store.get_outbox_depth("queued") == 1

    def test_emit_report_generated(self, emitter, webhook, store):
        """Should emit report.generated event."""
        event_id = emitter.emit_report_generated(
            tenant_id="test-tenant",
            project_id="project-1",
            report_id="report-123",
            run_id="run-456",
            format="pdf",
            size_bytes=1024000,
        )

        assert event_id.startswith("evt_rep_")
        assert store.get_outbox_depth("queued") == 1

    def test_emit_share_accessed(self, emitter, webhook, store):
        """Should emit share.accessed event."""
        event_id = emitter.emit_share_accessed(
            tenant_id="test-tenant",
            project_id="project-1",
            share_id="share-123",
            run_id="run-456",
            access_type="view",
        )

        assert event_id.startswith("evt_sha_")
        assert store.get_outbox_depth("queued") == 1

    def test_emit_quota_exceeded(self, emitter, webhook, store):
        """Should emit quota.exceeded event with dedup."""
        event_id = emitter.emit_quota_exceeded(
            tenant_id="test-tenant",
            project_id="project-1",
            quota_name="jobs_per_day",
            quota_limit=100,
            current_usage=101,
            period="daily",
            reset_at="2024-01-02T00:00:00Z",
        )

        assert event_id is not None
        assert event_id.startswith("evt_quo_")
        assert store.get_outbox_depth("queued") == 1

    def test_emit_quota_exceeded_deduped(self, emitter, webhook, store):
        """Should deduplicate quota.exceeded events."""
        # First emission
        event_id1 = emitter.emit_quota_exceeded(
            tenant_id="test-tenant",
            project_id="project-1",
            quota_name="jobs_per_day",
            quota_limit=100,
            current_usage=101,
            period="daily",
            reset_at="2024-01-02T00:00:00Z",
        )

        # Second emission should be deduplicated
        event_id2 = emitter.emit_quota_exceeded(
            tenant_id="test-tenant",
            project_id="project-1",
            quota_name="jobs_per_day",
            quota_limit=100,
            current_usage=102,
            period="daily",
            reset_at="2024-01-02T00:00:00Z",
        )

        assert event_id1 is not None
        assert event_id2 is None  # Deduplicated
        assert store.get_outbox_depth("queued") == 1  # Only one entry

    def test_emit_run_created(self, emitter, webhook, store):
        """Should emit run.created event."""
        event_id = emitter.emit_run_created(
            tenant_id="test-tenant",
            project_id="project-1",
            run_id="run-123",
            name="Test Run",
            created_by_user_id="user-456",
            scenario_count=5,
        )

        assert event_id.startswith("evt_run_")
        assert store.get_outbox_depth("queued") == 1


# -------------------------------------------------------------------------
# Test: No Matching Webhooks
# -------------------------------------------------------------------------

class TestNoMatchingWebhooks:
    """Tests for events with no matching webhooks."""

    def test_emit_when_no_webhooks(self, emitter, store):
        """Should not fail when no webhooks match."""
        event_id = emitter.emit_job_succeeded(
            tenant_id="test-tenant",
            project_id="project-1",
            job_id="job-123",
            job_type="sizing",
            run_id="run-456",
            duration_ms=5000,
            summary={},
        )

        # Event ID still generated
        assert event_id.startswith("evt_job_")
        # But no outbox entries
        assert store.get_outbox_depth("queued") == 0

    def test_emit_when_webhook_disabled(self, store, emitter):
        """Should not enqueue for disabled webhooks."""
        # Create disabled webhook
        webhook, _ = store.create_webhook(
            tenant_id="test-tenant",
            name="Disabled Webhook",
            url="https://example.com/hook",
            events=["job.succeeded"],
            project_id="project-1",
            enabled=False,
        )

        event_id = emitter.emit_job_succeeded(
            tenant_id="test-tenant",
            project_id="project-1",
            job_id="job-123",
            job_type="sizing",
            run_id="run-456",
            duration_ms=5000,
            summary={},
        )

        assert event_id.startswith("evt_job_")
        assert store.get_outbox_depth("queued") == 0


# -------------------------------------------------------------------------
# Test: Multiple Webhooks
# -------------------------------------------------------------------------

class TestMultipleWebhooks:
    """Tests for events with multiple matching webhooks."""

    def test_emit_to_multiple_webhooks(self, store, emitter):
        """Should enqueue for all matching webhooks."""
        # Create 3 webhooks
        for i in range(3):
            store.create_webhook(
                tenant_id="test-tenant",
                name=f"Webhook {i}",
                url=f"https://example.com/hook{i}",
                events=["job.succeeded"],
                project_id="project-1",
            )

        emitter.emit_job_succeeded(
            tenant_id="test-tenant",
            project_id="project-1",
            job_id="job-123",
            job_type="sizing",
            run_id="run-456",
            duration_ms=5000,
            summary={},
        )

        # Should have 3 outbox entries
        assert store.get_outbox_depth("queued") == 3

    def test_emit_respects_event_subscription(self, store, emitter):
        """Should only enqueue for webhooks subscribed to the event."""
        # Webhook 1: job.succeeded
        store.create_webhook(
            tenant_id="test-tenant",
            name="Webhook 1",
            url="https://example.com/hook1",
            events=["job.succeeded"],
            project_id="project-1",
        )

        # Webhook 2: job.failed only
        store.create_webhook(
            tenant_id="test-tenant",
            name="Webhook 2",
            url="https://example.com/hook2",
            events=["job.failed"],
            project_id="project-1",
        )

        emitter.emit_job_succeeded(
            tenant_id="test-tenant",
            project_id="project-1",
            job_id="job-123",
            job_type="sizing",
            run_id="run-456",
            duration_ms=5000,
            summary={},
        )

        # Only webhook 1 should receive
        assert store.get_outbox_depth("queued") == 1

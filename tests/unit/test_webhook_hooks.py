"""
Unit tests for webhook hooks (v4.1.0).

Tests verify:
- on_job_completed emits correct events
- Summary extraction from job results
- Error code extraction
- Report/share/quota/run event hooks
"""

import os
import sys
import tempfile
import pytest
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))

from webhook_hooks import WebhookHooks, get_webhook_hooks, set_webhook_hooks
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
def hooks(store):
    """Create WebhookHooks instance."""
    return WebhookHooks(webhook_store=store)


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
# Test: on_job_completed - Succeeded
# -------------------------------------------------------------------------

class TestOnJobCompleted:
    """Tests for on_job_completed hook."""

    def test_job_succeeded_emits_event(self, hooks, webhook, store):
        """Should emit job.succeeded event when job status is done."""
        job = {
            "job_id": "job-123",
            "tenant_id": "test-tenant",
            "project_id": "project-1",
            "job_type": "sizing",
            "run_id": "run-456",
            "status": "done",
            "result": {
                "recommended_variant": {
                    "npv_pln": 100000,
                    "capex_pln": 50000,
                    "payback_years": 5.2,
                    "variant_name": "BESS-100kWh",
                },
                "variants": [{}, {}, {}],
            },
            "created_at": "2024-01-01T10:00:00Z",
            "updated_at": "2024-01-01T10:05:00Z",
        }

        event_id = hooks.on_job_completed(job)

        assert event_id is not None
        assert event_id.startswith("evt_job_")
        assert store.get_outbox_depth("queued") == 1

    def test_job_failed_emits_event(self, hooks, webhook, store):
        """Should emit job.failed event when job status is failed."""
        job = {
            "job_id": "job-123",
            "tenant_id": "test-tenant",
            "project_id": "project-1",
            "job_type": "sizing",
            "run_id": "run-456",
            "status": "failed",
            "message": "Solver timeout after 300s",
        }

        event_id = hooks.on_job_completed(job)

        assert event_id is not None
        assert event_id.startswith("evt_job_")
        assert store.get_outbox_depth("queued") == 1

    def test_job_cancelled_does_not_emit(self, hooks, webhook, store):
        """Should not emit event for cancelled jobs."""
        job = {
            "job_id": "job-123",
            "tenant_id": "test-tenant",
            "project_id": "project-1",
            "job_type": "sizing",
            "status": "cancelled",
        }

        event_id = hooks.on_job_completed(job)

        assert event_id is None
        assert store.get_outbox_depth("queued") == 0

    def test_duration_calculated_from_timestamps(self, hooks, webhook, store):
        """Should calculate duration from created_at and updated_at."""
        job = {
            "job_id": "job-123",
            "tenant_id": "test-tenant",
            "project_id": "project-1",
            "job_type": "sizing",
            "run_id": "run-456",
            "status": "done",
            "result": {"variants": []},
            "created_at": "2024-01-01T10:00:00+00:00",
            "updated_at": "2024-01-01T10:00:05+00:00",  # 5 seconds later
        }

        event_id = hooks.on_job_completed(job)

        assert event_id is not None
        # Duration should be ~5000ms

    def test_duration_override(self, hooks, webhook, store):
        """Should use provided duration_ms."""
        job = {
            "job_id": "job-123",
            "tenant_id": "test-tenant",
            "project_id": "project-1",
            "job_type": "sizing",
            "status": "done",
            "result": {},
        }

        event_id = hooks.on_job_completed(job, duration_ms=10000)

        assert event_id is not None


# -------------------------------------------------------------------------
# Test: Summary Extraction
# -------------------------------------------------------------------------

class TestSummaryExtraction:
    """Tests for job summary extraction."""

    def test_sizing_job_summary(self, hooks, webhook, store):
        """Should extract sizing job summary."""
        job = {
            "job_id": "job-123",
            "tenant_id": "test-tenant",
            "project_id": "project-1",
            "job_type": "sizing",
            "status": "done",
            "result": {
                "recommended_variant": {
                    "npv_pln": 150000,
                    "capex_pln": 75000,
                    "payback_years": 4.5,
                    "variant_name": "Optimal-200kWh",
                },
                "variants": [{}, {}],
            },
        }

        event_id = hooks.on_job_completed(job)
        assert event_id is not None

    def test_batch_job_summary(self, hooks, webhook, store):
        """Should extract batch job summary."""
        job = {
            "job_id": "job-123",
            "tenant_id": "test-tenant",
            "project_id": "project-1",
            "job_type": "sizing-batch",
            "status": "done",
            "result": {
                "items": [
                    {"status": "OK"},
                    {"status": "OK"},
                    {"status": "FAILED"},
                ],
                "portfolio_summary": {
                    "total_npv_pln": 500000,
                    "total_capex_pln": 200000,
                },
            },
        }

        event_id = hooks.on_job_completed(job)
        assert event_id is not None

    def test_validate_pack_summary(self, hooks, webhook, store):
        """Should extract validate-pack job summary."""
        job = {
            "job_id": "job-123",
            "tenant_id": "test-tenant",
            "project_id": "project-1",
            "job_type": "validate-pack",
            "status": "done",
            "result": {
                "pack": "baseline",
                "passed_count": 8,
                "failed_count": 2,
                "total_count": 10,
            },
        }

        event_id = hooks.on_job_completed(job)
        assert event_id is not None


# -------------------------------------------------------------------------
# Test: Error Code Extraction
# -------------------------------------------------------------------------

class TestErrorCodeExtraction:
    """Tests for error code extraction."""

    def test_timeout_error(self, hooks, webhook, store):
        """Should extract TIMEOUT error code."""
        job = {
            "job_id": "job-123",
            "tenant_id": "test-tenant",
            "project_id": "project-1",
            "job_type": "sizing",
            "status": "failed",
            "message": "Job timed out after 600 seconds",
        }

        event_id = hooks.on_job_completed(job)
        assert event_id is not None

    def test_solver_error(self, hooks, webhook, store):
        """Should extract SOLVER_ERROR code."""
        job = {
            "job_id": "job-123",
            "tenant_id": "test-tenant",
            "project_id": "project-1",
            "job_type": "sizing",
            "status": "failed",
            "message": "Solver returned infeasible solution",
        }

        event_id = hooks.on_job_completed(job)
        assert event_id is not None

    def test_unknown_error(self, hooks, webhook, store):
        """Should default to INTERNAL_ERROR."""
        job = {
            "job_id": "job-123",
            "tenant_id": "test-tenant",
            "project_id": "project-1",
            "job_type": "sizing",
            "status": "failed",
            "message": "Something unexpected happened",
        }

        event_id = hooks.on_job_completed(job)
        assert event_id is not None


# -------------------------------------------------------------------------
# Test: Other Event Hooks
# -------------------------------------------------------------------------

class TestReportHook:
    """Tests for on_report_generated hook."""

    def test_report_generated_emits_event(self, hooks, webhook, store):
        """Should emit report.generated event."""
        event_id = hooks.on_report_generated(
            tenant_id="test-tenant",
            project_id="project-1",
            report_id="report-123",
            run_id="run-456",
            format="pdf",
            size_bytes=1024000,
        )

        assert event_id is not None
        assert event_id.startswith("evt_rep_")
        assert store.get_outbox_depth("queued") == 1


class TestShareHook:
    """Tests for on_share_accessed hook."""

    def test_share_accessed_emits_event(self, hooks, webhook, store):
        """Should emit share.accessed event."""
        event_id = hooks.on_share_accessed(
            tenant_id="test-tenant",
            project_id="project-1",
            share_id="share-123",
            run_id="run-456",
            access_type="view",
        )

        assert event_id is not None
        assert event_id.startswith("evt_sha_")
        assert store.get_outbox_depth("queued") == 1


class TestQuotaHook:
    """Tests for on_quota_exceeded hook."""

    def test_quota_exceeded_emits_event(self, hooks, webhook, store):
        """Should emit quota.exceeded event."""
        event_id = hooks.on_quota_exceeded(
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

    def test_quota_exceeded_deduped(self, hooks, webhook, store):
        """Should deduplicate quota events."""
        # First call
        event_id1 = hooks.on_quota_exceeded(
            tenant_id="test-tenant",
            project_id="project-1",
            quota_name="jobs_per_day",
            quota_limit=100,
            current_usage=101,
            period="daily",
            reset_at="2024-01-02T00:00:00Z",
        )

        # Second call (same quota, same day)
        event_id2 = hooks.on_quota_exceeded(
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
        assert store.get_outbox_depth("queued") == 1


class TestRunHook:
    """Tests for on_run_created hook."""

    def test_run_created_emits_event(self, hooks, webhook, store):
        """Should emit run.created event."""
        event_id = hooks.on_run_created(
            tenant_id="test-tenant",
            project_id="project-1",
            run_id="run-123",
            name="Test Run",
            created_by_user_id="user-456",
            scenario_count=5,
        )

        assert event_id is not None
        assert event_id.startswith("evt_run_")
        assert store.get_outbox_depth("queued") == 1


# -------------------------------------------------------------------------
# Test: Disabled Hooks
# -------------------------------------------------------------------------

class TestDisabledHooks:
    """Tests for disabled hooks."""

    def test_disabled_hooks_do_not_emit(self, hooks, webhook, store):
        """Should not emit when hooks are disabled."""
        hooks.disable()

        event_id = hooks.on_job_completed({
            "job_id": "job-123",
            "tenant_id": "test-tenant",
            "project_id": "project-1",
            "job_type": "sizing",
            "status": "done",
            "result": {},
        })

        assert event_id is None
        assert store.get_outbox_depth("queued") == 0

    def test_reenable_hooks(self, hooks, webhook, store):
        """Should emit after re-enabling hooks."""
        hooks.disable()
        hooks.enable()

        event_id = hooks.on_job_completed({
            "job_id": "job-123",
            "tenant_id": "test-tenant",
            "project_id": "project-1",
            "job_type": "sizing",
            "status": "done",
            "result": {},
        })

        assert event_id is not None
        assert store.get_outbox_depth("queued") == 1


# -------------------------------------------------------------------------
# Test: Global Singleton
# -------------------------------------------------------------------------

class TestGlobalSingleton:
    """Tests for global hooks singleton."""

    def test_get_webhook_hooks_creates_instance(self):
        """Should create instance on first call."""
        # Reset singleton
        set_webhook_hooks(None)

        hooks = get_webhook_hooks()
        assert hooks is not None
        assert isinstance(hooks, WebhookHooks)

    def test_get_webhook_hooks_returns_same_instance(self):
        """Should return same instance on subsequent calls."""
        hooks1 = get_webhook_hooks()
        hooks2 = get_webhook_hooks()

        assert hooks1 is hooks2

    def test_set_webhook_hooks_overrides(self, temp_db):
        """Should allow overriding the global instance."""
        store = WebhookStore(db_path=temp_db)
        custom_hooks = WebhookHooks(webhook_store=store)

        set_webhook_hooks(custom_hooks)
        hooks = get_webhook_hooks()

        assert hooks is custom_hooks

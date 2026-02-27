"""
Unit tests for webhook dedup key unique behavior.

Tests verify:
- Dedup key prevents duplicate entries
- Same dedup key for different webhooks is allowed
- Null dedup keys don't conflict
"""

import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))

from webhook_store import WebhookStore


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
    """Create a WebhookStore instance with temp database."""
    return WebhookStore(db_path=temp_db)


@pytest.fixture
def webhook(store):
    """Create a test webhook."""
    webhook, _ = store.create_webhook(
        tenant_id="tenant-1",
        name="Test Webhook",
        url="https://example.com/hook",
        events=["quota.exceeded"],
    )
    return webhook


class TestDedupKeyUniqueness:
    """Tests for dedup key uniqueness."""

    def test_same_dedup_key_rejected(self, store, webhook):
        """Should reject second entry with same dedup key for same webhook."""
        entry1 = store.enqueue_event(
            webhook_id=webhook.id,
            tenant_id="tenant-1",
            project_id="project-1",
            event_name="quota.exceeded",
            event_id="event-1",
            payload={"quota": "jobs_per_day"},
            dedup_key="quota:jobs_per_day:2024-01-01:project-1",
        )
        assert entry1 is not None

        # Second entry with same dedup key should be rejected
        entry2 = store.enqueue_event(
            webhook_id=webhook.id,
            tenant_id="tenant-1",
            project_id="project-1",
            event_name="quota.exceeded",
            event_id="event-2",
            payload={"quota": "jobs_per_day"},
            dedup_key="quota:jobs_per_day:2024-01-01:project-1",
        )
        assert entry2 is None

    def test_different_dedup_keys_allowed(self, store, webhook):
        """Should allow entries with different dedup keys."""
        entry1 = store.enqueue_event(
            webhook_id=webhook.id,
            tenant_id="tenant-1",
            project_id="project-1",
            event_name="quota.exceeded",
            event_id="event-1",
            payload={"quota": "jobs_per_day"},
            dedup_key="quota:jobs_per_day:2024-01-01:project-1",
        )
        assert entry1 is not None

        entry2 = store.enqueue_event(
            webhook_id=webhook.id,
            tenant_id="tenant-1",
            project_id="project-1",
            event_name="quota.exceeded",
            event_id="event-2",
            payload={"quota": "jobs_per_day"},
            dedup_key="quota:jobs_per_day:2024-01-02:project-1",  # Different date
        )
        assert entry2 is not None

    def test_same_dedup_key_different_webhooks_allowed(self, store):
        """Should allow same dedup key for different webhooks."""
        webhook1, _ = store.create_webhook(
            tenant_id="tenant-1",
            name="Webhook 1",
            url="https://example.com/hook1",
            events=["quota.exceeded"],
        )
        webhook2, _ = store.create_webhook(
            tenant_id="tenant-1",
            name="Webhook 2",
            url="https://example.com/hook2",
            events=["quota.exceeded"],
        )

        dedup_key = "quota:jobs_per_day:2024-01-01:project-1"

        entry1 = store.enqueue_event(
            webhook_id=webhook1.id,
            tenant_id="tenant-1",
            project_id="project-1",
            event_name="quota.exceeded",
            event_id="event-1",
            payload={"quota": "jobs_per_day"},
            dedup_key=dedup_key,
        )
        assert entry1 is not None

        entry2 = store.enqueue_event(
            webhook_id=webhook2.id,
            tenant_id="tenant-1",
            project_id="project-1",
            event_name="quota.exceeded",
            event_id="event-2",
            payload={"quota": "jobs_per_day"},
            dedup_key=dedup_key,
        )
        assert entry2 is not None

    def test_null_dedup_keys_dont_conflict(self, store, webhook):
        """Should allow multiple entries with null dedup key."""
        entry1 = store.enqueue_event(
            webhook_id=webhook.id,
            tenant_id="tenant-1",
            project_id="project-1",
            event_name="job.succeeded",
            event_id="event-1",
            payload={"job_id": "job-1"},
            dedup_key=None,
        )
        assert entry1 is not None

        entry2 = store.enqueue_event(
            webhook_id=webhook.id,
            tenant_id="tenant-1",
            project_id="project-1",
            event_name="job.succeeded",
            event_id="event-2",
            payload={"job_id": "job-2"},
            dedup_key=None,
        )
        assert entry2 is not None

        entry3 = store.enqueue_event(
            webhook_id=webhook.id,
            tenant_id="tenant-1",
            project_id="project-1",
            event_name="job.succeeded",
            event_id="event-3",
            payload={"job_id": "job-3"},
            # No dedup_key at all
        )
        assert entry3 is not None

        # Should have 3 entries
        depth = store.get_outbox_depth("queued")
        assert depth == 3


class TestDedupKeyFormats:
    """Tests for dedup key format patterns."""

    def test_quota_exceeded_dedup_key_pattern(self, store, webhook):
        """Test quota exceeded dedup pattern: quota:<name>:<date>:<project>."""
        patterns = [
            "quota:jobs_per_day:2024-01-01:project-1",
            "quota:reports_per_day:2024-01-01:project-1",
            "quota:storage_mb:2024-01-01:project-2",
        ]

        for i, pattern in enumerate(patterns):
            entry = store.enqueue_event(
                webhook_id=webhook.id,
                tenant_id="tenant-1",
                project_id="project-1",
                event_name="quota.exceeded",
                event_id=f"event-{i}",
                payload={"quota": "test"},
                dedup_key=pattern,
            )
            assert entry is not None

    def test_empty_string_dedup_key_treated_as_unique(self, store, webhook):
        """Empty string should be treated as a unique dedup key."""
        entry1 = store.enqueue_event(
            webhook_id=webhook.id,
            tenant_id="tenant-1",
            project_id="project-1",
            event_name="job.succeeded",
            event_id="event-1",
            payload={"job_id": "job-1"},
            dedup_key="",
        )
        assert entry1 is not None

        # Second entry with same empty string should be rejected
        entry2 = store.enqueue_event(
            webhook_id=webhook.id,
            tenant_id="tenant-1",
            project_id="project-1",
            event_name="job.succeeded",
            event_id="event-2",
            payload={"job_id": "job-2"},
            dedup_key="",
        )
        assert entry2 is None


class TestDedupWithStatusTransitions:
    """Tests for dedup behavior across status transitions."""

    def test_dedup_blocks_even_after_succeeded(self, store, webhook):
        """Dedup should still block after first entry succeeded."""
        dedup_key = "unique-event-123"

        # First entry
        entry1 = store.enqueue_event(
            webhook_id=webhook.id,
            tenant_id="tenant-1",
            project_id="project-1",
            event_name="job.succeeded",
            event_id="event-1",
            payload={"job_id": "job-1"},
            dedup_key=dedup_key,
        )
        assert entry1 is not None

        # Process it
        claimed = store.claim_outbox_entry("worker-1")
        store.mark_outbox_succeeded(claimed.id)

        # Second entry with same dedup key should still be blocked
        entry2 = store.enqueue_event(
            webhook_id=webhook.id,
            tenant_id="tenant-1",
            project_id="project-1",
            event_name="job.succeeded",
            event_id="event-2",
            payload={"job_id": "job-2"},
            dedup_key=dedup_key,
        )
        assert entry2 is None

    def test_dedup_blocks_even_after_dead(self, store, webhook):
        """Dedup should still block after first entry went to dead letter."""
        dedup_key = "unique-event-456"

        # First entry with max_attempts=1
        entry1 = store.enqueue_event(
            webhook_id=webhook.id,
            tenant_id="tenant-1",
            project_id="project-1",
            event_name="job.succeeded",
            event_id="event-1",
            payload={"job_id": "job-1"},
            dedup_key=dedup_key,
            max_attempts=1,
        )
        assert entry1 is not None

        # Fail it to dead letter
        claimed = store.claim_outbox_entry("worker-1")
        store.mark_outbox_failed(claimed.id)

        # Second entry with same dedup key should still be blocked
        entry2 = store.enqueue_event(
            webhook_id=webhook.id,
            tenant_id="tenant-1",
            project_id="project-1",
            event_name="job.succeeded",
            event_id="event-2",
            payload={"job_id": "job-2"},
            dedup_key=dedup_key,
        )
        assert entry2 is None


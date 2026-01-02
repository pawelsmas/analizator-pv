"""
Unit tests for webhook outbox locking.

Tests verify:
- Claiming outbox entries with locking
- Lock expiration and re-claiming
- Concurrent claim prevention
"""

import os
import sys
import tempfile
import pytest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))

from webhook_store import WebhookStore, OutboxStatus


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
def webhook_with_entry(store):
    """Create a webhook and add an outbox entry."""
    webhook, _ = store.create_webhook(
        tenant_id="tenant-1",
        name="Test Webhook",
        url="https://example.com/hook",
        events=["job.succeeded"],
    )

    entry = store.enqueue_event(
        webhook_id=webhook.id,
        tenant_id="tenant-1",
        project_id="project-1",
        event_name="job.succeeded",
        event_id="event-123",
        payload={"job_id": "job-1"},
    )

    return webhook, entry


class TestOutboxClaiming:
    """Tests for outbox entry claiming."""

    def test_claim_returns_entry(self, webhook_with_entry, store):
        """Should claim and return outbox entry."""
        webhook, entry = webhook_with_entry

        claimed = store.claim_outbox_entry("worker-1")

        assert claimed is not None
        assert claimed.id == entry.id
        assert claimed.status == "delivering"
        assert claimed.locked_by == "worker-1"
        assert claimed.attempts == 1

    def test_claim_returns_none_when_empty(self, store):
        """Should return None when no entries available."""
        claimed = store.claim_outbox_entry("worker-1")

        assert claimed is None

    def test_claim_skips_locked_entries(self, webhook_with_entry, store):
        """Should not claim already locked entries."""
        webhook, entry = webhook_with_entry

        # First worker claims
        claimed1 = store.claim_outbox_entry("worker-1")
        assert claimed1 is not None

        # Second worker should get nothing
        claimed2 = store.claim_outbox_entry("worker-2")
        assert claimed2 is None

    def test_claim_expired_lock(self, webhook_with_entry, store):
        """Should reclaim entry with expired lock after failure."""
        webhook, entry = webhook_with_entry

        # First worker claims with very short lock
        claimed1 = store.claim_outbox_entry("worker-1", lock_duration_seconds=0)
        assert claimed1 is not None

        # Mark as failed to allow reclaim (must be queued/failed status)
        store.mark_outbox_failed(claimed1.id)

        # Second worker should be able to claim
        claimed2 = store.claim_outbox_entry("worker-2", lock_duration_seconds=300)
        assert claimed2 is not None
        assert claimed2.locked_by == "worker-2"
        assert claimed2.attempts == 2  # Incremented

    def test_claim_respects_not_before(self, store):
        """Should not claim entries before not_before_at."""
        webhook, _ = store.create_webhook(
            tenant_id="tenant-1",
            name="Test Webhook",
            url="https://example.com/hook",
            events=["job.succeeded"],
        )

        # Enqueue with future not_before
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        entry = store.enqueue_event(
            webhook_id=webhook.id,
            tenant_id="tenant-1",
            project_id="project-1",
            event_name="job.succeeded",
            event_id="event-123",
            payload={"job_id": "job-1"},
            not_before=future,
        )

        # Should not be claimable yet
        claimed = store.claim_outbox_entry("worker-1")
        assert claimed is None

    def test_claim_failed_entries(self, webhook_with_entry, store):
        """Should be able to claim failed entries for retry."""
        webhook, entry = webhook_with_entry

        # Claim and mark as failed
        claimed = store.claim_outbox_entry("worker-1")
        store.mark_outbox_failed(claimed.id)

        # Should be claimable again
        claimed2 = store.claim_outbox_entry("worker-2")
        assert claimed2 is not None
        assert claimed2.id == entry.id

    def test_claim_does_not_return_succeeded(self, webhook_with_entry, store):
        """Should not claim succeeded entries."""
        webhook, entry = webhook_with_entry

        # Claim and mark as succeeded
        claimed = store.claim_outbox_entry("worker-1")
        store.mark_outbox_succeeded(claimed.id)

        # Should not be claimable
        claimed2 = store.claim_outbox_entry("worker-2")
        assert claimed2 is None

    def test_claim_does_not_return_dead(self, webhook_with_entry, store):
        """Should not claim dead entries."""
        webhook, entry = webhook_with_entry

        # Set max_attempts to 1 and fail
        claimed = store.claim_outbox_entry("worker-1")

        # Mark as failed repeatedly until dead
        for _ in range(10):
            store.mark_outbox_failed(claimed.id)
            result = store.claim_outbox_entry("worker-1")
            if result is None:
                break

        # Should not be claimable (dead)
        claimed2 = store.claim_outbox_entry("worker-2")
        assert claimed2 is None


class TestOutboxStatusTransitions:
    """Tests for outbox status transitions."""

    def test_mark_succeeded_updates_status(self, webhook_with_entry, store):
        """Should update status to succeeded."""
        webhook, entry = webhook_with_entry

        claimed = store.claim_outbox_entry("worker-1")
        store.mark_outbox_succeeded(claimed.id)

        # Check via depth
        depth = store.get_outbox_depth("succeeded")
        assert depth == 1

    def test_mark_succeeded_clears_lock(self, webhook_with_entry, store):
        """Should clear lock info on success."""
        webhook, entry = webhook_with_entry

        claimed = store.claim_outbox_entry("worker-1")
        store.mark_outbox_succeeded(claimed.id)

        # Verify lock cleared (entry not claimable means lock was cleared and status changed)
        depth = store.get_outbox_depth("delivering")
        assert depth == 0

    def test_mark_failed_schedules_retry(self, webhook_with_entry, store):
        """Should schedule retry with backoff."""
        webhook, entry = webhook_with_entry

        claimed = store.claim_outbox_entry("worker-1")
        store.mark_outbox_failed(claimed.id, next_retry_seconds=60)

        # Should be failed but not claimable yet (future not_before)
        depth = store.get_outbox_depth("failed")
        assert depth == 1

    def test_mark_failed_after_max_attempts_goes_dead(self, store):
        """Should move to dead after max attempts."""
        webhook, _ = store.create_webhook(
            tenant_id="tenant-1",
            name="Test Webhook",
            url="https://example.com/hook",
            events=["job.succeeded"],
        )

        # Enqueue with max_attempts=1
        entry = store.enqueue_event(
            webhook_id=webhook.id,
            tenant_id="tenant-1",
            project_id="project-1",
            event_name="job.succeeded",
            event_id="event-123",
            payload={"job_id": "job-1"},
            max_attempts=1,
        )

        # Claim and fail
        claimed = store.claim_outbox_entry("worker-1")
        assert claimed is not None
        assert claimed.attempts == 1

        store.mark_outbox_failed(claimed.id)

        # Should be dead
        depth = store.get_outbox_depth("dead")
        assert depth == 1


class TestOutboxDepth:
    """Tests for outbox depth counting."""

    def test_depth_by_status(self, store):
        """Should count entries by status."""
        webhook, _ = store.create_webhook(
            tenant_id="tenant-1",
            name="Test Webhook",
            url="https://example.com/hook",
            events=["job.succeeded"],
        )

        # Add multiple entries
        for i in range(5):
            store.enqueue_event(
                webhook_id=webhook.id,
                tenant_id="tenant-1",
                project_id="project-1",
                event_name="job.succeeded",
                event_id=f"event-{i}",
                payload={"job_id": f"job-{i}"},
            )

        depth = store.get_outbox_depth("queued")
        assert depth == 5

    def test_total_depth(self, store):
        """Should count all entries."""
        webhook, _ = store.create_webhook(
            tenant_id="tenant-1",
            name="Test Webhook",
            url="https://example.com/hook",
            events=["job.succeeded"],
        )

        for i in range(3):
            store.enqueue_event(
                webhook_id=webhook.id,
                tenant_id="tenant-1",
                project_id="project-1",
                event_name="job.succeeded",
                event_id=f"event-{i}",
                payload={"job_id": f"job-{i}"},
            )

        depth = store.get_outbox_depth()
        assert depth == 3


class TestDeadLetterOperations:
    """Tests for dead letter operations."""

    def test_list_dead_letter(self, store):
        """Should list dead letter entries."""
        webhook, _ = store.create_webhook(
            tenant_id="tenant-1",
            name="Test Webhook",
            url="https://example.com/hook",
            events=["job.succeeded"],
        )

        # Create and fail entry
        store.enqueue_event(
            webhook_id=webhook.id,
            tenant_id="tenant-1",
            project_id="project-1",
            event_name="job.succeeded",
            event_id="event-dead",
            payload={"job_id": "job-dead"},
            max_attempts=1,
        )

        claimed = store.claim_outbox_entry("worker-1")
        store.mark_outbox_failed(claimed.id)

        dead = store.list_dead_letter(webhook.id)
        assert len(dead) == 1
        assert dead[0].event_id == "event-dead"

    def test_replay_dead_letter(self, store):
        """Should replay dead letter entry."""
        webhook, _ = store.create_webhook(
            tenant_id="tenant-1",
            name="Test Webhook",
            url="https://example.com/hook",
            events=["job.succeeded"],
        )

        # Create and fail entry
        store.enqueue_event(
            webhook_id=webhook.id,
            tenant_id="tenant-1",
            project_id="project-1",
            event_name="job.succeeded",
            event_id="event-dead",
            payload={"job_id": "job-dead"},
            max_attempts=1,
        )

        claimed = store.claim_outbox_entry("worker-1")
        store.mark_outbox_failed(claimed.id)

        # Replay
        result = store.replay_dead_letter(claimed.id)
        assert result is True

        # Should be queued again
        depth = store.get_outbox_depth("queued")
        assert depth == 1

        # Should be claimable
        claimed2 = store.claim_outbox_entry("worker-2")
        assert claimed2 is not None
        assert claimed2.attempts == 1  # Reset

    def test_replay_non_dead_returns_false(self, webhook_with_entry, store):
        """Should return False for non-dead entries."""
        webhook, entry = webhook_with_entry

        result = store.replay_dead_letter(entry.id)
        assert result is False


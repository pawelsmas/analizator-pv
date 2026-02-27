"""
Unit tests for webhook dispatcher (v4.1.0).

Tests verify:
- Backoff calculation
- Signature computation
- Delivery success/failure handling
- Outbox processing
- Worker coordination
"""

import os
import sys
import tempfile
import pytest
from unittest.mock import patch, MagicMock
import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))

from webhook_dispatcher import (
    WebhookDispatcher,
    calculate_backoff,
    compute_signature,
    DEFAULT_BASE_BACKOFF_SECONDS,
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
def dispatcher(store):
    """Create WebhookDispatcher instance."""
    return WebhookDispatcher(
        webhook_store=store,
        worker_id="test-worker",
        timeout_seconds=5,
    )


@pytest.fixture
def webhook_with_entry(store):
    """Create a webhook and enqueue an event."""
    webhook, secret = store.create_webhook(
        tenant_id="test-tenant",
        name="Test Webhook",
        url="https://example.com/hook",
        events=["job.succeeded"],
        project_id="project-1",
    )

    entry = store.enqueue_event(
        webhook_id=webhook.id,
        tenant_id="test-tenant",
        project_id="project-1",
        event_name="job.succeeded",
        event_id="event-123",
        payload={"job_id": "job-1", "status": "done"},
    )

    return webhook, entry, secret


# -------------------------------------------------------------------------
# Test: Backoff Calculation
# -------------------------------------------------------------------------

class TestBackoffCalculation:
    """Tests for exponential backoff calculation."""

    def test_backoff_attempt_1(self):
        """First attempt: 60 seconds."""
        assert calculate_backoff(1) == 60

    def test_backoff_attempt_2(self):
        """Second attempt: 120 seconds."""
        assert calculate_backoff(2) == 120

    def test_backoff_attempt_3(self):
        """Third attempt: 240 seconds."""
        assert calculate_backoff(3) == 240

    def test_backoff_attempt_5(self):
        """Fifth attempt: 960 seconds."""
        assert calculate_backoff(5) == 960

    def test_backoff_max_1_hour(self):
        """Backoff capped at 1 hour."""
        assert calculate_backoff(10) == 3600

    def test_custom_base(self):
        """Custom base backoff."""
        assert calculate_backoff(1, base_seconds=30) == 30
        assert calculate_backoff(2, base_seconds=30) == 60


# -------------------------------------------------------------------------
# Test: Signature Computation
# -------------------------------------------------------------------------

class TestSignatureComputation:
    """Tests for HMAC signature computation."""

    def test_signature_format(self):
        """Should return v1=<hex> format."""
        sig = compute_signature("secret", 1704067200, '{"test": "data"}')

        assert sig.startswith("v1=")
        assert len(sig) == 3 + 64  # "v1=" + 64 hex chars

    def test_signature_deterministic(self):
        """Same inputs should produce same signature."""
        sig1 = compute_signature("secret", 1704067200, '{"test": "data"}')
        sig2 = compute_signature("secret", 1704067200, '{"test": "data"}')

        assert sig1 == sig2

    def test_signature_differs_with_different_secret(self):
        """Different secrets produce different signatures."""
        sig1 = compute_signature("secret1", 1704067200, '{"test": "data"}')
        sig2 = compute_signature("secret2", 1704067200, '{"test": "data"}')

        assert sig1 != sig2

    def test_signature_differs_with_different_timestamp(self):
        """Different timestamps produce different signatures."""
        sig1 = compute_signature("secret", 1704067200, '{"test": "data"}')
        sig2 = compute_signature("secret", 1704067201, '{"test": "data"}')

        assert sig1 != sig2

    def test_signature_differs_with_different_body(self):
        """Different bodies produce different signatures."""
        sig1 = compute_signature("secret", 1704067200, '{"test": "data1"}')
        sig2 = compute_signature("secret", 1704067200, '{"test": "data2"}')

        assert sig1 != sig2


# -------------------------------------------------------------------------
# Test: Dispatcher Processing
# -------------------------------------------------------------------------

class TestDispatcherProcessing:
    """Tests for dispatcher outbox processing."""

    def test_process_one_returns_false_when_empty(self, dispatcher):
        """Should return False when no entries to process."""
        result = dispatcher.process_one()
        assert result is False

    @patch("webhook_dispatcher.httpx.Client")
    def test_process_one_success(self, mock_client_class, dispatcher, webhook_with_entry, store):
        """Should process entry and mark as succeeded on 200."""
        webhook, entry, _ = webhook_with_entry

        # Mock successful response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "OK"

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = dispatcher.process_one()

        assert result is True
        assert store.get_outbox_depth("succeeded") == 1
        assert store.get_outbox_depth("queued") == 0

    @patch("webhook_dispatcher.httpx.Client")
    def test_process_one_server_error_retries(self, mock_client_class, dispatcher, webhook_with_entry, store):
        """Should mark as failed and schedule retry on 500."""
        webhook, entry, _ = webhook_with_entry

        # Mock server error
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        result = dispatcher.process_one()

        assert result is True
        assert store.get_outbox_depth("failed") == 1

    @patch("webhook_dispatcher.httpx.Client")
    def test_process_one_timeout_retries(self, mock_client_class, dispatcher, webhook_with_entry, store):
        """Should retry on timeout."""
        webhook, entry, _ = webhook_with_entry

        # Mock timeout
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = httpx.TimeoutException("Timeout")
        mock_client_class.return_value = mock_client

        result = dispatcher.process_one()

        assert result is True
        assert store.get_outbox_depth("failed") == 1

    @patch("webhook_dispatcher.httpx.Client")
    def test_process_one_connection_error_retries(self, mock_client_class, dispatcher, webhook_with_entry, store):
        """Should retry on connection error."""
        webhook, entry, _ = webhook_with_entry

        # Mock connection error
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")
        mock_client_class.return_value = mock_client

        result = dispatcher.process_one()

        assert result is True
        assert store.get_outbox_depth("failed") == 1

    def test_process_one_missing_webhook_marks_dead(self, dispatcher, store):
        """Should mark as dead if webhook not found."""
        # Create entry with non-existent webhook
        entry = store.enqueue_event(
            webhook_id="non-existent-webhook-id",
            tenant_id="test-tenant",
            project_id="project-1",
            event_name="job.succeeded",
            event_id="event-123",
            payload={"test": "data"},
        )
        assert entry is not None

        result = dispatcher.process_one()

        assert result is True
        # Entry should be failed (webhook not found)
        assert store.get_outbox_depth("queued") == 0

    @patch("webhook_dispatcher.httpx.Client")
    def test_process_one_logs_delivery(self, mock_client_class, dispatcher, webhook_with_entry, store):
        """Should log delivery attempt."""
        webhook, entry, _ = webhook_with_entry

        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "OK"

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        dispatcher.process_one()

        # Check delivery log
        logs = store.list_deliveries(webhook.id, limit=10)
        assert len(logs) == 1
        assert logs[0].status_code == 200
        assert logs[0].attempt == 1


# -------------------------------------------------------------------------
# Test: Worker ID
# -------------------------------------------------------------------------

class TestWorkerId:
    """Tests for worker ID generation."""

    def test_custom_worker_id(self, store):
        """Should use provided worker ID."""
        dispatcher = WebhookDispatcher(
            webhook_store=store,
            worker_id="my-custom-worker",
        )
        assert dispatcher.worker_id == "my-custom-worker"

    def test_auto_generated_worker_id(self, store):
        """Should auto-generate worker ID if not provided."""
        dispatcher = WebhookDispatcher(webhook_store=store)
        assert dispatcher.worker_id.startswith("worker-")


# -------------------------------------------------------------------------
# Test: Dispatcher Run Loop
# -------------------------------------------------------------------------

class TestDispatcherRunLoop:
    """Tests for dispatcher run loop."""

    def test_run_with_max_iterations(self, dispatcher):
        """Should stop after max iterations."""
        # No entries, will just poll
        dispatcher.run(max_iterations=3)
        # Should complete without hanging

    def test_stop(self, dispatcher):
        """Should stop when stop() is called."""
        dispatcher.stop()
        assert dispatcher._running is False

    @patch("webhook_dispatcher.httpx.Client")
    def test_run_processes_multiple(self, mock_client_class, dispatcher, store):
        """Should process multiple entries."""
        # Create webhook
        webhook, _ = store.create_webhook(
            tenant_id="test-tenant",
            name="Test",
            url="https://example.com/hook",
            events=["job.succeeded"],
        )

        # Create 3 entries
        for i in range(3):
            store.enqueue_event(
                webhook_id=webhook.id,
                tenant_id="test-tenant",
                project_id=None,
                event_name="job.succeeded",
                event_id=f"event-{i}",
                payload={"i": i},
            )

        # Mock success
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "OK"

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        # Run with enough iterations to process all
        dispatcher.run(max_iterations=5)

        assert store.get_outbox_depth("succeeded") == 3


# -------------------------------------------------------------------------
# Test: Disabled Webhook
# -------------------------------------------------------------------------

class TestDisabledWebhook:
    """Tests for disabled webhook handling."""

    def test_disabled_webhook_marked_failed(self, dispatcher, store):
        """Should mark entry as failed for disabled webhook."""
        # Create disabled webhook
        webhook, _ = store.create_webhook(
            tenant_id="test-tenant",
            name="Disabled",
            url="https://example.com/hook",
            events=["job.succeeded"],
            enabled=False,
        )

        # Create entry
        store.enqueue_event(
            webhook_id=webhook.id,
            tenant_id="test-tenant",
            project_id=None,
            event_name="job.succeeded",
            event_id="event-1",
            payload={"test": True},
        )

        result = dispatcher.process_one()

        assert result is True
        assert store.get_outbox_depth("queued") == 0

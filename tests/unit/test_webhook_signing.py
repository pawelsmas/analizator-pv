"""
Unit tests for webhook signing (v4.1.0).

Tests verify:
- Signature computation
- Signature verification
- Timestamp validation
- Secret storage
- Signed webhook store
"""

import os
import sys
import tempfile
import time
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))

from webhook_signing import (
    compute_signature,
    verify_signature,
    parse_signature_header,
    SecretStorage,
    SigningService,
    SignedWebhookStore,
    SIGNATURE_VERSION,
    MAX_TIMESTAMP_AGE_SECONDS,
)


# -------------------------------------------------------------------------
# Test: Signature Computation
# -------------------------------------------------------------------------

class TestSignatureComputation:
    """Tests for compute_signature function."""

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

    def test_signature_changes_with_secret(self):
        """Different secrets produce different signatures."""
        sig1 = compute_signature("secret1", 1704067200, '{"test": "data"}')
        sig2 = compute_signature("secret2", 1704067200, '{"test": "data"}')

        assert sig1 != sig2

    def test_signature_changes_with_timestamp(self):
        """Different timestamps produce different signatures."""
        sig1 = compute_signature("secret", 1704067200, '{"test": "data"}')
        sig2 = compute_signature("secret", 1704067201, '{"test": "data"}')

        assert sig1 != sig2

    def test_signature_changes_with_body(self):
        """Different bodies produce different signatures."""
        sig1 = compute_signature("secret", 1704067200, '{"test": "data1"}')
        sig2 = compute_signature("secret", 1704067200, '{"test": "data2"}')

        assert sig1 != sig2


# -------------------------------------------------------------------------
# Test: Signature Verification
# -------------------------------------------------------------------------

class TestSignatureVerification:
    """Tests for verify_signature function."""

    def test_verify_valid_signature(self):
        """Should verify valid signature."""
        secret = "test-secret"
        timestamp = int(time.time())
        body = '{"event": "test"}'

        signature = compute_signature(secret, timestamp, body)
        is_valid, error = verify_signature(secret, timestamp, body, signature)

        assert is_valid is True
        assert error is None

    def test_verify_invalid_signature(self):
        """Should reject invalid signature."""
        secret = "test-secret"
        timestamp = int(time.time())
        body = '{"event": "test"}'

        is_valid, error = verify_signature(
            secret, timestamp, body, "v1=invalid_hex"
        )

        assert is_valid is False
        assert "mismatch" in error.lower()

    def test_verify_wrong_secret(self):
        """Should reject signature with wrong secret."""
        timestamp = int(time.time())
        body = '{"event": "test"}'

        # Sign with one secret
        signature = compute_signature("secret1", timestamp, body)

        # Verify with different secret
        is_valid, error = verify_signature("secret2", timestamp, body, signature)

        assert is_valid is False
        assert "mismatch" in error.lower()

    def test_verify_expired_timestamp(self):
        """Should reject old timestamps."""
        secret = "test-secret"
        old_timestamp = int(time.time()) - 600  # 10 minutes ago
        body = '{"event": "test"}'

        signature = compute_signature(secret, old_timestamp, body)
        is_valid, error = verify_signature(
            secret, old_timestamp, body, signature, max_age_seconds=300
        )

        assert is_valid is False
        assert "old" in error.lower()

    def test_verify_future_timestamp(self):
        """Should reject future timestamps (clock skew)."""
        secret = "test-secret"
        future_timestamp = int(time.time()) + 600  # 10 minutes in future
        body = '{"event": "test"}'

        signature = compute_signature(secret, future_timestamp, body)
        is_valid, error = verify_signature(
            secret, future_timestamp, body, signature, max_age_seconds=300
        )

        assert is_valid is False
        assert "old" in error.lower()

    def test_verify_unsupported_version(self):
        """Should reject unsupported signature versions."""
        secret = "test-secret"
        timestamp = int(time.time())
        body = '{"event": "test"}'

        is_valid, error = verify_signature(
            secret, timestamp, body, "v2=somesignature"
        )

        assert is_valid is False
        assert "version" in error.lower()


# -------------------------------------------------------------------------
# Test: Signature Header Parsing
# -------------------------------------------------------------------------

class TestSignatureHeaderParsing:
    """Tests for parse_signature_header function."""

    def test_parse_single_signature(self):
        """Should parse single signature."""
        header = "v1=abc123def456"
        result = parse_signature_header(header)

        assert result == {"v1": "abc123def456"}

    def test_parse_multiple_signatures(self):
        """Should parse multiple signatures."""
        header = "v1=abc123,v2=def456"
        result = parse_signature_header(header)

        assert result == {"v1": "abc123", "v2": "def456"}

    def test_parse_with_spaces(self):
        """Should handle spaces."""
        header = "v1=abc123, v2=def456"
        result = parse_signature_header(header)

        assert result == {"v1": "abc123", "v2": "def456"}


# -------------------------------------------------------------------------
# Test: Secret Storage
# -------------------------------------------------------------------------

class TestSecretStorage:
    """Tests for SecretStorage class."""

    def test_store_and_retrieve(self):
        """Should store and retrieve secret."""
        storage = SecretStorage()

        storage.store_secret("webhook-1", "secret-123")
        result = storage.get_secret("webhook-1")

        assert result == "secret-123"

    def test_get_nonexistent(self):
        """Should return None for nonexistent webhook."""
        storage = SecretStorage()

        result = storage.get_secret("nonexistent")

        assert result is None

    def test_delete_secret(self):
        """Should delete secret."""
        storage = SecretStorage()
        storage.store_secret("webhook-1", "secret-123")

        storage.delete_secret("webhook-1")
        result = storage.get_secret("webhook-1")

        assert result is None

    def test_has_secret(self):
        """Should check if secret exists."""
        storage = SecretStorage()
        storage.store_secret("webhook-1", "secret-123")

        assert storage.has_secret("webhook-1") is True
        assert storage.has_secret("webhook-2") is False

    def test_overwrite_secret(self):
        """Should overwrite existing secret."""
        storage = SecretStorage()

        storage.store_secret("webhook-1", "secret-old")
        storage.store_secret("webhook-1", "secret-new")

        assert storage.get_secret("webhook-1") == "secret-new"


# -------------------------------------------------------------------------
# Test: Signing Service
# -------------------------------------------------------------------------

class TestSigningService:
    """Tests for SigningService class."""

    @pytest.fixture
    def storage(self):
        """Create secret storage with test secret."""
        storage = SecretStorage()
        storage.store_secret("webhook-123", "test-secret")
        return storage

    @pytest.fixture
    def service(self, storage):
        """Create signing service."""
        return SigningService(secret_storage=storage)

    def test_sign_returns_headers(self, service):
        """Should return signed headers."""
        headers = service.sign("webhook-123", '{"event": "test"}')

        assert "Content-Type" in headers
        assert "X-Webhook-Timestamp" in headers
        assert "X-Webhook-Signature" in headers
        assert "X-Webhook-Id" in headers

    def test_sign_includes_event_info(self, service):
        """Should include event ID and type if provided."""
        headers = service.sign(
            "webhook-123",
            '{"event": "test"}',
            event_id="evt-456",
            event_type="job.succeeded",
        )

        assert headers["X-Webhook-Event-Id"] == "evt-456"
        assert headers["X-Webhook-Event-Type"] == "job.succeeded"

    def test_sign_without_secret(self):
        """Should omit signature when no secret."""
        storage = SecretStorage()  # Empty
        service = SigningService(secret_storage=storage)

        headers = service.sign("webhook-no-secret", '{"event": "test"}')

        assert "X-Webhook-Signature" not in headers

    def test_verify_incoming(self, service, storage):
        """Should verify incoming signature."""
        timestamp = int(time.time())
        body = '{"event": "test"}'
        signature = compute_signature("test-secret", timestamp, body)

        is_valid, error = service.verify_incoming(
            "webhook-123", timestamp, body, signature
        )

        assert is_valid is True
        assert error is None


# -------------------------------------------------------------------------
# Test: Signed Webhook Store
# -------------------------------------------------------------------------

class TestSignedWebhookStore:
    """Tests for SignedWebhookStore class."""

    @pytest.fixture
    def temp_db(self):
        """Create temporary database."""
        fd, path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        yield path
        if os.path.exists(path):
            os.remove(path)

    @pytest.fixture
    def storage(self):
        """Create secret storage."""
        return SecretStorage()

    @pytest.fixture
    def store(self, temp_db, storage):
        """Create signed webhook store."""
        return SignedWebhookStore(db_path=temp_db, secret_storage=storage)

    def test_create_webhook_stores_secret(self, store, storage):
        """Should store secret on webhook creation."""
        webhook, secret = store.create_webhook(
            tenant_id="tenant-1",
            name="Test",
            url="https://example.com/hook",
            events=["job.succeeded"],
        )

        stored_secret = storage.get_secret(webhook.id)
        assert stored_secret == secret

    def test_rotate_secret_updates_storage(self, store, storage):
        """Should update storage on rotation."""
        webhook, original_secret = store.create_webhook(
            tenant_id="tenant-1",
            name="Test",
            url="https://example.com/hook",
            events=["job.succeeded"],
        )

        new_secret, new_version = store.rotate_secret(webhook.id)

        stored_secret = storage.get_secret(webhook.id)
        assert stored_secret == new_secret
        assert stored_secret != original_secret

    def test_delete_webhook_removes_secret(self, store, storage):
        """Should remove secret on deletion."""
        webhook, _ = store.create_webhook(
            tenant_id="tenant-1",
            name="Test",
            url="https://example.com/hook",
            events=["job.succeeded"],
        )

        store.delete_webhook(webhook.id)

        assert storage.has_secret(webhook.id) is False


# -------------------------------------------------------------------------
# Test: End-to-End Signing
# -------------------------------------------------------------------------

class TestEndToEndSigning:
    """End-to-end tests for signing flow."""

    @pytest.fixture
    def temp_db(self):
        """Create temporary database."""
        fd, path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        yield path
        if os.path.exists(path):
            os.remove(path)

    def test_full_signing_flow(self, temp_db):
        """Test complete signing and verification flow."""
        storage = SecretStorage()
        store = SignedWebhookStore(db_path=temp_db, secret_storage=storage)
        service = SigningService(webhook_store=store, secret_storage=storage)

        # Create webhook
        webhook, _ = store.create_webhook(
            tenant_id="tenant-1",
            name="Test",
            url="https://example.com/hook",
            events=["job.succeeded"],
        )

        # Sign payload
        body = '{"event_type": "job.succeeded", "job_id": "123"}'
        headers = service.sign(webhook.id, body)

        # Extract signature components
        timestamp = int(headers["X-Webhook-Timestamp"])
        signature = headers["X-Webhook-Signature"]

        # Verify
        is_valid, error = service.verify_incoming(
            webhook.id, timestamp, body, signature
        )

        assert is_valid is True
        assert error is None

    def test_rotation_maintains_signing(self, temp_db):
        """Test that signing works after secret rotation."""
        storage = SecretStorage()
        store = SignedWebhookStore(db_path=temp_db, secret_storage=storage)
        service = SigningService(webhook_store=store, secret_storage=storage)

        # Create webhook
        webhook, _ = store.create_webhook(
            tenant_id="tenant-1",
            name="Test",
            url="https://example.com/hook",
            events=["job.succeeded"],
        )

        # Rotate secret
        store.rotate_secret(webhook.id)

        # Sign with new secret
        body = '{"event_type": "job.succeeded"}'
        headers = service.sign(webhook.id, body)

        # Verify
        timestamp = int(headers["X-Webhook-Timestamp"])
        signature = headers["X-Webhook-Signature"]

        is_valid, error = service.verify_incoming(
            webhook.id, timestamp, body, signature
        )

        assert is_valid is True

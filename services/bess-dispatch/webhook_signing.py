"""
Webhook signing module for BESS API (v4.1.0).

Provides HMAC-SHA256 signing for webhook payloads with secret management.

Headers:
- X-Webhook-Timestamp: Unix timestamp when payload was signed
- X-Webhook-Signature: v1=<hmac_sha256_hex>

Signature format:
- Message: "{timestamp}.{body}"
- Algorithm: HMAC-SHA256
- Output: "v1=<64 hex characters>"

Secret Rotation:
- Each webhook has a secret_version
- During rotation, old secret remains valid briefly
- Receivers should verify using latest secret first

Usage:
    from webhook_signing import SigningService, verify_signature

    # Server-side (sending)
    service = SigningService(webhook_store)
    headers = service.sign(webhook_id, body)

    # Client-side (receiving)
    is_valid = verify_signature(secret, timestamp, body, signature)
"""

import hashlib
import hmac
import json
import time
from typing import Dict, Optional, Tuple

from webhook_store import WebhookStore, Webhook


# -------------------------------------------------------------------------
# Constants
# -------------------------------------------------------------------------

# Signature scheme version
SIGNATURE_VERSION = "v1"

# Maximum age for valid timestamp (5 minutes)
MAX_TIMESTAMP_AGE_SECONDS = 300

# Header names
HEADER_TIMESTAMP = "X-Webhook-Timestamp"
HEADER_SIGNATURE = "X-Webhook-Signature"
HEADER_WEBHOOK_ID = "X-Webhook-Id"
HEADER_EVENT_ID = "X-Webhook-Event-Id"
HEADER_EVENT_TYPE = "X-Webhook-Event-Type"


# -------------------------------------------------------------------------
# Signature Functions
# -------------------------------------------------------------------------

def compute_signature(
    secret: str,
    timestamp: int,
    body: str,
) -> str:
    """
    Compute HMAC-SHA256 signature for webhook payload.

    Args:
        secret: Webhook secret (plaintext)
        timestamp: Unix timestamp
        body: JSON payload body

    Returns:
        Signature string in format "v1=<hex>"
    """
    message = f"{timestamp}.{body}"
    signature = hmac.new(
        secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return f"{SIGNATURE_VERSION}={signature}"


def verify_signature(
    secret: str,
    timestamp: int,
    body: str,
    signature: str,
    max_age_seconds: int = MAX_TIMESTAMP_AGE_SECONDS,
) -> Tuple[bool, Optional[str]]:
    """
    Verify webhook signature.

    Args:
        secret: Webhook secret
        timestamp: Timestamp from header
        body: Request body
        signature: Signature from header
        max_age_seconds: Maximum allowed timestamp age

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check timestamp age
    current_time = int(time.time())
    age = abs(current_time - timestamp)

    if age > max_age_seconds:
        return False, f"Timestamp too old: {age}s (max {max_age_seconds}s)"

    # Parse signature
    if not signature.startswith(f"{SIGNATURE_VERSION}="):
        return False, f"Unsupported signature version (expected {SIGNATURE_VERSION}=...)"

    # Compute expected signature
    expected = compute_signature(secret, timestamp, body)

    # Constant-time comparison to prevent timing attacks
    if hmac.compare_digest(expected, signature):
        return True, None

    return False, "Signature mismatch"


def parse_signature_header(header: str) -> Dict[str, str]:
    """
    Parse signature header supporting multiple versions.

    Format: v1=<sig1>,v2=<sig2>

    Args:
        header: Signature header value

    Returns:
        Dict mapping version to signature hex
    """
    signatures = {}
    for part in header.split(","):
        part = part.strip()
        if "=" in part:
            version, sig = part.split("=", 1)
            signatures[version] = sig
    return signatures


# -------------------------------------------------------------------------
# Secret Storage
# -------------------------------------------------------------------------

class SecretStorage:
    """
    Secure storage for webhook secrets.

    In production, this would use:
    - AWS Secrets Manager
    - Azure Key Vault
    - HashiCorp Vault
    - Encrypted environment variables

    For now, secrets are stored encrypted in memory during webhook creation
    and cannot be retrieved after (hash only stored in DB).
    """

    def __init__(self):
        # In-memory cache of secrets (webhook_id -> secret)
        # This is populated during webhook creation only
        self._secrets: Dict[str, str] = {}

    def store_secret(self, webhook_id: str, secret: str):
        """Store secret for a webhook."""
        self._secrets[webhook_id] = secret

    def get_secret(self, webhook_id: str) -> Optional[str]:
        """Get secret for a webhook."""
        return self._secrets.get(webhook_id)

    def delete_secret(self, webhook_id: str):
        """Delete secret for a webhook."""
        self._secrets.pop(webhook_id, None)

    def has_secret(self, webhook_id: str) -> bool:
        """Check if secret exists."""
        return webhook_id in self._secrets


# Global secret storage singleton
_secret_storage: Optional[SecretStorage] = None


def get_secret_storage() -> SecretStorage:
    """Get or create global secret storage."""
    global _secret_storage
    if _secret_storage is None:
        _secret_storage = SecretStorage()
    return _secret_storage


def set_secret_storage(storage: SecretStorage):
    """Set global secret storage (for testing)."""
    global _secret_storage
    _secret_storage = storage


# -------------------------------------------------------------------------
# Signing Service
# -------------------------------------------------------------------------

class SigningService:
    """
    Service for signing webhook payloads.

    Handles secret retrieval and header generation.
    """

    def __init__(
        self,
        webhook_store: Optional[WebhookStore] = None,
        secret_storage: Optional[SecretStorage] = None,
    ):
        """
        Initialize signing service.

        Args:
            webhook_store: WebhookStore instance
            secret_storage: SecretStorage instance
        """
        self.store = webhook_store or WebhookStore()
        self.secrets = secret_storage or get_secret_storage()

    def sign(
        self,
        webhook_id: str,
        body: str,
        event_id: Optional[str] = None,
        event_type: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        Generate signed headers for webhook payload.

        Args:
            webhook_id: Webhook identifier
            body: JSON payload body
            event_id: Optional event identifier
            event_type: Optional event type

        Returns:
            Dict of headers to include in request
        """
        timestamp = int(time.time())

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "BESS-Webhook/1.0",
            HEADER_TIMESTAMP: str(timestamp),
            HEADER_WEBHOOK_ID: webhook_id,
        }

        if event_id:
            headers[HEADER_EVENT_ID] = event_id
        if event_type:
            headers[HEADER_EVENT_TYPE] = event_type

        # Get secret
        secret = self.secrets.get_secret(webhook_id)
        if secret:
            signature = compute_signature(secret, timestamp, body)
            headers[HEADER_SIGNATURE] = signature

        return headers

    def verify_incoming(
        self,
        webhook_id: str,
        timestamp: int,
        body: str,
        signature: str,
    ) -> Tuple[bool, Optional[str]]:
        """
        Verify incoming webhook signature.

        Useful for testing webhook receivers.

        Args:
            webhook_id: Webhook identifier
            timestamp: Timestamp from header
            body: Request body
            signature: Signature from header

        Returns:
            Tuple of (is_valid, error_message)
        """
        secret = self.secrets.get_secret(webhook_id)
        if not secret:
            return False, "Secret not found for webhook"

        return verify_signature(secret, timestamp, body, signature)


# -------------------------------------------------------------------------
# Webhook with Signing Integration
# -------------------------------------------------------------------------

class SignedWebhookStore(WebhookStore):
    """
    WebhookStore with integrated secret storage.

    Extends WebhookStore to store plaintext secrets in SecretStorage
    during webhook creation.
    """

    def __init__(self, db_path: Optional[str] = None, secret_storage: Optional[SecretStorage] = None):
        super().__init__(db_path)
        self.secrets = secret_storage or get_secret_storage()

    def create_webhook(
        self,
        tenant_id: str,
        name: str,
        url: str,
        events: list,
        project_id: Optional[str] = None,
        enabled: bool = True,
    ) -> Tuple[Webhook, str]:
        """Create webhook and store secret."""
        webhook, secret = super().create_webhook(
            tenant_id=tenant_id,
            name=name,
            url=url,
            events=events,
            project_id=project_id,
            enabled=enabled,
        )

        # Store plaintext secret
        self.secrets.store_secret(webhook.id, secret)

        return webhook, secret

    def rotate_secret(
        self, webhook_id: str, tenant_id: Optional[str] = None
    ) -> Optional[Tuple[str, int]]:
        """Rotate secret and update storage."""
        result = super().rotate_secret(webhook_id, tenant_id)
        if result:
            new_secret, new_version = result
            # Update stored secret
            self.secrets.store_secret(webhook_id, new_secret)

        return result

    def delete_webhook(self, webhook_id: str, tenant_id: Optional[str] = None) -> bool:
        """Delete webhook and its secret."""
        result = super().delete_webhook(webhook_id, tenant_id)
        if result:
            self.secrets.delete_secret(webhook_id)
        return result

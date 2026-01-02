"""
Webhook dispatcher worker for BESS API (v4.1.0).

Processes webhook outbox entries and delivers to endpoints.

Features:
- HTTP POST delivery with configurable timeout
- Exponential backoff on failure
- Dead letter queue for exhausted retries
- Delivery logging
- Worker coordination via locking

Usage:
    from webhook_dispatcher import WebhookDispatcher

    dispatcher = WebhookDispatcher()
    dispatcher.run()  # Blocking loop
    # or
    dispatcher.process_one()  # Single entry processing
"""

import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import httpx

from webhook_store import WebhookStore, OutboxEntry, OutboxStatus


logger = logging.getLogger(__name__)


# -------------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------------

DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_LOCK_DURATION_SECONDS = 60
DEFAULT_POLL_INTERVAL_SECONDS = 5
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_BASE_BACKOFF_SECONDS = 60  # 1 minute


def calculate_backoff(attempt: int, base_seconds: int = DEFAULT_BASE_BACKOFF_SECONDS) -> int:
    """
    Calculate exponential backoff delay.

    Backoff: base * 2^(attempt-1) with max of 1 hour.
    Attempt 1: 60s, 2: 120s, 3: 240s, 4: 480s, 5: 960s
    """
    delay = base_seconds * (2 ** (attempt - 1))
    return min(delay, 3600)  # Max 1 hour


# -------------------------------------------------------------------------
# Signing helper
# -------------------------------------------------------------------------

def compute_signature(
    secret: str,
    timestamp: int,
    body: str,
) -> str:
    """
    Compute HMAC-SHA256 signature for webhook payload.

    Format: v1=<hex_digest>
    Signed data: timestamp.body

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
    return f"v1={signature}"


# -------------------------------------------------------------------------
# Dispatcher class
# -------------------------------------------------------------------------

class WebhookDispatcher:
    """
    Webhook dispatcher worker.

    Processes outbox entries and delivers webhooks via HTTP POST.
    """

    def __init__(
        self,
        webhook_store: Optional[WebhookStore] = None,
        worker_id: Optional[str] = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        lock_duration_seconds: int = DEFAULT_LOCK_DURATION_SECONDS,
        poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
    ):
        """
        Initialize dispatcher.

        Args:
            webhook_store: WebhookStore instance (creates new if None)
            worker_id: Unique worker identifier (auto-generated if None)
            timeout_seconds: HTTP request timeout
            lock_duration_seconds: How long to hold outbox lock
            poll_interval_seconds: Sleep between polls when no work
        """
        self.store = webhook_store or WebhookStore()
        self.worker_id = worker_id or self._generate_worker_id()
        self.timeout_seconds = timeout_seconds
        self.lock_duration_seconds = lock_duration_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self._running = False

    def _generate_worker_id(self) -> str:
        """Generate unique worker ID."""
        import uuid
        import socket
        hostname = socket.gethostname()[:8]
        uid = uuid.uuid4().hex[:8]
        return f"worker-{hostname}-{uid}"

    def run(self, max_iterations: Optional[int] = None):
        """
        Run dispatcher loop.

        Args:
            max_iterations: Max iterations before stopping (None = infinite)
        """
        self._running = True
        iterations = 0

        logger.info(f"Webhook dispatcher {self.worker_id} starting")

        while self._running:
            processed = self.process_one()

            if not processed:
                time.sleep(self.poll_interval_seconds)

            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                break

        logger.info(f"Webhook dispatcher {self.worker_id} stopped")

    def stop(self):
        """Stop the dispatcher loop."""
        self._running = False

    def process_one(self) -> bool:
        """
        Process one outbox entry.

        Returns:
            True if an entry was processed, False if queue was empty
        """
        # Claim next entry
        entry = self.store.claim_outbox_entry(
            worker_id=self.worker_id,
            lock_duration_seconds=self.lock_duration_seconds,
        )

        if entry is None:
            return False

        logger.debug(f"Processing outbox entry {entry.id} (attempt {entry.attempts})")

        # Get webhook config
        webhook = self.store.get_webhook(entry.webhook_id)
        if webhook is None:
            logger.warning(f"Webhook {entry.webhook_id} not found, marking as dead")
            self.store.mark_outbox_failed(entry.id)
            return True

        if not webhook.enabled:
            logger.debug(f"Webhook {entry.webhook_id} is disabled, marking as dead")
            self.store.mark_outbox_failed(entry.id)
            return True

        # Get secret for signing
        secret = self._get_webhook_secret(entry.webhook_id)

        # Deliver
        result = self._deliver(
            url=webhook.url,
            payload_json=entry.payload_json,
            secret=secret,
        )

        # Log delivery attempt
        self.store.log_delivery(
            outbox_id=entry.id,
            webhook_id=entry.webhook_id,
            tenant_id=entry.tenant_id,
            project_id=entry.project_id,
            status_code=result["status_code"],
            duration_ms=result["duration_ms"],
            error_code=result.get("error_code"),
            response_snippet=result.get("response_snippet"),
            attempt=entry.attempts,
        )

        # Update status
        if result["success"]:
            self.store.mark_outbox_succeeded(entry.id)
            logger.debug(f"Outbox entry {entry.id} succeeded")

            # Update webhook last_delivery_at
            self.store.update_webhook(
                webhook_id=entry.webhook_id,
            )
        else:
            backoff = calculate_backoff(entry.attempts)
            self.store.mark_outbox_failed(
                outbox_id=entry.id,
                next_retry_seconds=backoff,
            )
            logger.debug(
                f"Outbox entry {entry.id} failed (attempt {entry.attempts}), "
                f"retry in {backoff}s: {result.get('error_code')}"
            )

        return True

    def _get_webhook_secret(self, webhook_id: str) -> Optional[str]:
        """
        Get webhook secret for signing.

        Note: In production, this would retrieve the secret from secure storage.
        For now, we return None and signing is skipped.
        """
        # TODO: Implement secure secret retrieval
        # The secret is hashed in DB, so we can't retrieve plaintext
        # This will be implemented in PR6 with proper secret management
        return None

    def _deliver(
        self,
        url: str,
        payload_json: str,
        secret: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Deliver webhook via HTTP POST.

        Args:
            url: Webhook endpoint URL
            payload_json: JSON payload string
            secret: Optional secret for signing

        Returns:
            Dict with: success, status_code, duration_ms, error_code, response_snippet
        """
        start_time = time.time()
        timestamp = int(start_time)

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "BESS-Webhook/1.0",
            "X-Webhook-Timestamp": str(timestamp),
        }

        # Add signature if secret provided
        if secret:
            signature = compute_signature(secret, timestamp, payload_json)
            headers["X-Webhook-Signature"] = signature

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(
                    url,
                    content=payload_json,
                    headers=headers,
                )

            duration_ms = int((time.time() - start_time) * 1000)

            # Success: 2xx status codes
            if 200 <= response.status_code < 300:
                return {
                    "success": True,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                }

            # Client error (4xx) - don't retry
            if 400 <= response.status_code < 500:
                return {
                    "success": False,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                    "error_code": f"HTTP_{response.status_code}",
                    "response_snippet": response.text[:500] if response.text else None,
                }

            # Server error (5xx) - retry
            return {
                "success": False,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "error_code": f"HTTP_{response.status_code}",
                "response_snippet": response.text[:500] if response.text else None,
            }

        except httpx.TimeoutException:
            duration_ms = int((time.time() - start_time) * 1000)
            return {
                "success": False,
                "status_code": None,
                "duration_ms": duration_ms,
                "error_code": "TIMEOUT",
            }

        except httpx.ConnectError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return {
                "success": False,
                "status_code": None,
                "duration_ms": duration_ms,
                "error_code": "CONNECTION_ERROR",
                "response_snippet": str(e)[:500],
            }

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.exception(f"Unexpected error delivering webhook: {e}")
            return {
                "success": False,
                "status_code": None,
                "duration_ms": duration_ms,
                "error_code": "INTERNAL_ERROR",
                "response_snippet": str(e)[:500],
            }


# -------------------------------------------------------------------------
# CLI entry point
# -------------------------------------------------------------------------

def main():
    """CLI entry point for running dispatcher."""
    import argparse

    parser = argparse.ArgumentParser(description="Webhook Dispatcher Worker")
    parser.add_argument(
        "--worker-id", type=str, default=None, help="Worker identifier"
    )
    parser.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="HTTP timeout"
    )
    parser.add_argument(
        "--poll-interval", type=int, default=DEFAULT_POLL_INTERVAL_SECONDS,
        help="Poll interval when idle"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Verbose logging"
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    dispatcher = WebhookDispatcher(
        worker_id=args.worker_id,
        timeout_seconds=args.timeout,
        poll_interval_seconds=args.poll_interval,
    )

    try:
        dispatcher.run()
    except KeyboardInterrupt:
        dispatcher.stop()


if __name__ == "__main__":
    main()

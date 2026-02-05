"""
Idempotency-Key support for BESS API (v3.9.0).

Provides idempotent POST request handling to prevent duplicate operations:
- Jobs creation (POST /jobs/*)
- Share creation (POST /shares)
- Invite creation (POST /invites)

The Idempotency-Key header allows clients to safely retry requests without
creating duplicate resources.

## Behavior

1. Client sends `Idempotency-Key: <unique-key>` header with POST request
2. Server checks if key exists in cache:
   - If exists with completed response: return cached response (200/201)
   - If exists with in-progress marker: return 409 Conflict
   - If not exists: proceed with request, cache result
3. Cache entries expire after IDEMPOTENCY_TTL_SECONDS (default: 86400 = 24h)

## Error Codes

- 409 Conflict: Key is currently being processed (concurrent request)
- 422 Unprocessable Entity: Invalid Idempotency-Key format

## Headers

Response includes:
- `X-Idempotency-Key-Status: hit` (cached response)
- `X-Idempotency-Key-Status: miss` (new request)
- `X-Idempotency-Key-Status: conflict` (concurrent request)

Environment Variables:
- IDEMPOTENCY_TTL_SECONDS: Cache TTL (default: 86400)
- IDEMPOTENCY_KEY_MAX_LENGTH: Max key length (default: 256)
- IDEMPOTENCY_ENABLED: Enable/disable feature (default: true)
"""

import hashlib
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from prometheus_client import Counter, Histogram


# -------------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------------

IDEMPOTENCY_ENABLED = os.getenv("IDEMPOTENCY_ENABLED", "true").lower() in ("true", "1", "yes")
IDEMPOTENCY_TTL_SECONDS = int(os.getenv("IDEMPOTENCY_TTL_SECONDS", "86400"))  # 24 hours
IDEMPOTENCY_KEY_MAX_LENGTH = int(os.getenv("IDEMPOTENCY_KEY_MAX_LENGTH", "256"))
IDEMPOTENCY_DB_PATH = os.getenv("IDEMPOTENCY_DB_PATH", "/data/idempotency.sqlite")

# Valid key pattern: alphanumeric, dashes, underscores, colons
KEY_PATTERN = re.compile(r"^[a-zA-Z0-9_\-:]+$")


# -------------------------------------------------------------------------
# Prometheus Metrics
# -------------------------------------------------------------------------

IDEMPOTENCY_REQUESTS_TOTAL = Counter(
    "bess_idempotency_requests_total",
    "Total requests with Idempotency-Key header",
    ["endpoint", "status"],  # status: hit, miss, conflict, invalid
)

IDEMPOTENCY_CACHE_SIZE = Counter(
    "bess_idempotency_cache_entries_total",
    "Total idempotency cache entries created",
)

IDEMPOTENCY_CACHE_HITS = Counter(
    "bess_idempotency_cache_hits_total",
    "Total cache hits (returned cached response)",
    ["endpoint"],
)

IDEMPOTENCY_CONFLICTS = Counter(
    "bess_idempotency_conflicts_total",
    "Total 409 Conflict responses (concurrent requests)",
    ["endpoint"],
)


# -------------------------------------------------------------------------
# Status Enum
# -------------------------------------------------------------------------

class IdempotencyStatus(str, Enum):
    """Status of idempotency check."""
    HIT = "hit"  # Cached response found
    MISS = "miss"  # New request, proceed
    CONFLICT = "conflict"  # Request in progress
    INVALID = "invalid"  # Invalid key format


class IdempotencyState(str, Enum):
    """State of cached entry."""
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


# -------------------------------------------------------------------------
# Exceptions
# -------------------------------------------------------------------------

class IdempotencyKeyError(Exception):
    """Base exception for idempotency errors."""
    pass


class IdempotencyKeyInvalid(IdempotencyKeyError):
    """Raised when Idempotency-Key format is invalid."""

    def __init__(self, key: str, reason: str):
        self.key = key
        self.reason = reason
        super().__init__(f"Invalid Idempotency-Key: {reason}")


class IdempotencyConflict(IdempotencyKeyError):
    """Raised when request with same key is already in progress."""

    def __init__(self, key: str):
        self.key = key
        super().__init__(f"Request with Idempotency-Key '{key}' is already in progress")


# -------------------------------------------------------------------------
# Idempotency Store
# -------------------------------------------------------------------------

class IdempotencyStore:
    """
    SQLite-backed store for idempotency keys.

    Table schema:
    - key_hash: TEXT PRIMARY KEY (SHA-256 of key + endpoint + tenant)
    - key_value: TEXT (original key for debugging)
    - endpoint: TEXT
    - tenant_id: TEXT
    - state: TEXT (in_progress, completed)
    - request_hash: TEXT (hash of request body for validation)
    - response_blob: BLOB (cached response, null if in_progress)
    - status_code: INTEGER (HTTP status code)
    - created_at: TEXT ISO 8601
    - completed_at: TEXT ISO 8601 (null if in_progress)
    - expires_at: TEXT ISO 8601
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or IDEMPOTENCY_DB_PATH
        self._ensure_db()

    def _ensure_db(self) -> None:
        """Create database and tables if they don't exist."""
        db_dir = Path(self.db_path).parent
        if not db_dir.exists():
            db_dir.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS idempotency_keys (
                    key_hash TEXT PRIMARY KEY,
                    key_value TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    response_blob BLOB,
                    status_code INTEGER,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    expires_at TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_idempotency_expires
                ON idempotency_keys(expires_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_idempotency_tenant
                ON idempotency_keys(tenant_id)
            """)
            conn.commit()
        finally:
            conn.close()

    def _compute_key_hash(self, key: str, endpoint: str, tenant_id: str) -> str:
        """Compute unique hash for key scoped to endpoint and tenant."""
        combined = f"{tenant_id}:{endpoint}:{key}"
        return hashlib.sha256(combined.encode()).hexdigest()

    def _compute_request_hash(self, request_body: Dict[str, Any]) -> str:
        """Compute hash of request body for validation."""
        # Sort keys for deterministic hash
        body_str = json.dumps(request_body, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(body_str.encode()).hexdigest()[:16]

    def check_and_lock(
        self,
        key: str,
        endpoint: str,
        tenant_id: str,
        request_body: Dict[str, Any],
    ) -> Tuple[IdempotencyStatus, Optional[Dict[str, Any]], Optional[int]]:
        """
        Check if key exists and lock for processing if not.

        Args:
            key: Idempotency key from header
            endpoint: API endpoint being called
            tenant_id: Tenant making the request
            request_body: Request body for validation

        Returns:
            Tuple of (status, cached_response, status_code)
            - HIT: (HIT, response_dict, status_code)
            - MISS: (MISS, None, None) - caller should proceed
            - CONFLICT: (CONFLICT, None, None) - request in progress

        Note: Expired entries are cleaned up automatically.
        """
        key_hash = self._compute_key_hash(key, endpoint, tenant_id)
        request_hash = self._compute_request_hash(request_body)
        now = datetime.now(timezone.utc).isoformat()
        expires_at = datetime.fromtimestamp(
            time.time() + IDEMPOTENCY_TTL_SECONDS, timezone.utc
        ).isoformat()

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Clean up expired entries
            cursor.execute("DELETE FROM idempotency_keys WHERE expires_at < ?", (now,))

            # Check for existing entry
            cursor.execute(
                "SELECT state, response_blob, status_code, request_hash FROM idempotency_keys WHERE key_hash = ?",
                (key_hash,)
            )
            row = cursor.fetchone()

            if row is not None:
                state, response_blob, status_code, stored_request_hash = row

                # Verify request body matches (optional: could return 422 if different)
                # For now, we ignore request body differences (key uniqueness is enough)

                if state == IdempotencyState.COMPLETED.value:
                    # Return cached response
                    response = json.loads(response_blob) if response_blob else {}
                    conn.commit()
                    return IdempotencyStatus.HIT, response, status_code

                elif state == IdempotencyState.IN_PROGRESS.value:
                    # Request is being processed concurrently
                    conn.commit()
                    return IdempotencyStatus.CONFLICT, None, None

            # No existing entry - create in_progress marker
            cursor.execute("""
                INSERT INTO idempotency_keys
                (key_hash, key_value, endpoint, tenant_id, state, request_hash, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                key_hash, key, endpoint, tenant_id,
                IdempotencyState.IN_PROGRESS.value, request_hash, now, expires_at
            ))
            conn.commit()
            IDEMPOTENCY_CACHE_SIZE.inc()
            return IdempotencyStatus.MISS, None, None

        finally:
            conn.close()

    def complete(
        self,
        key: str,
        endpoint: str,
        tenant_id: str,
        response: Dict[str, Any],
        status_code: int,
    ) -> None:
        """
        Mark request as completed and cache response.

        Args:
            key: Idempotency key
            endpoint: API endpoint
            tenant_id: Tenant ID
            response: Response to cache
            status_code: HTTP status code
        """
        key_hash = self._compute_key_hash(key, endpoint, tenant_id)
        now = datetime.now(timezone.utc).isoformat()
        response_blob = json.dumps(response, separators=(",", ":"))

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE idempotency_keys
                SET state = ?, response_blob = ?, status_code = ?, completed_at = ?
                WHERE key_hash = ?
            """, (
                IdempotencyState.COMPLETED.value, response_blob, status_code, now, key_hash
            ))
            conn.commit()
        finally:
            conn.close()

    def release(self, key: str, endpoint: str, tenant_id: str) -> None:
        """
        Release lock without caching (e.g., on error).

        This removes the in_progress marker, allowing retry with same key.

        Args:
            key: Idempotency key
            endpoint: API endpoint
            tenant_id: Tenant ID
        """
        key_hash = self._compute_key_hash(key, endpoint, tenant_id)

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            # Only delete if still in_progress (don't delete completed entries)
            cursor.execute(
                "DELETE FROM idempotency_keys WHERE key_hash = ? AND state = ?",
                (key_hash, IdempotencyState.IN_PROGRESS.value)
            )
            conn.commit()
        finally:
            conn.close()

    def prune_expired(self) -> int:
        """
        Delete expired entries.

        Returns:
            Number of entries deleted
        """
        now = datetime.now(timezone.utc).isoformat()

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM idempotency_keys WHERE expires_at < ?", (now,))
            deleted = cursor.rowcount
            conn.commit()
            return deleted
        finally:
            conn.close()


# -------------------------------------------------------------------------
# Global Store
# -------------------------------------------------------------------------

_store: Optional[IdempotencyStore] = None


def get_idempotency_store() -> IdempotencyStore:
    """Get or create the global IdempotencyStore instance."""
    global _store
    if _store is None:
        _store = IdempotencyStore()
    return _store


# -------------------------------------------------------------------------
# Validation Functions
# -------------------------------------------------------------------------

def validate_idempotency_key(key: str) -> None:
    """
    Validate idempotency key format.

    Args:
        key: The idempotency key to validate

    Raises:
        IdempotencyKeyInvalid: If key is invalid
    """
    if not key:
        raise IdempotencyKeyInvalid(key, "Key cannot be empty")

    if len(key) > IDEMPOTENCY_KEY_MAX_LENGTH:
        raise IdempotencyKeyInvalid(
            key, f"Key exceeds maximum length of {IDEMPOTENCY_KEY_MAX_LENGTH}"
        )

    if not KEY_PATTERN.match(key):
        raise IdempotencyKeyInvalid(
            key, "Key must contain only alphanumeric characters, dashes, underscores, and colons"
        )


def is_idempotency_enabled() -> bool:
    """Check if idempotency feature is enabled."""
    return IDEMPOTENCY_ENABLED


# -------------------------------------------------------------------------
# High-Level API
# -------------------------------------------------------------------------

def check_idempotency(
    key: Optional[str],
    endpoint: str,
    tenant_id: str,
    request_body: Dict[str, Any],
) -> Tuple[IdempotencyStatus, Optional[Dict[str, Any]], Optional[int]]:
    """
    Check idempotency for a request.

    Args:
        key: Idempotency-Key header value (or None if not provided)
        endpoint: API endpoint (e.g., "jobs.sizing-batch")
        tenant_id: Tenant ID from auth context
        request_body: Request body dict

    Returns:
        Tuple of (status, cached_response, status_code)

    Raises:
        IdempotencyKeyInvalid: If key format is invalid
        IdempotencyConflict: If request with same key is in progress
    """
    if not is_idempotency_enabled():
        return IdempotencyStatus.MISS, None, None

    if key is None:
        # No key provided, proceed normally
        return IdempotencyStatus.MISS, None, None

    # Validate key format
    validate_idempotency_key(key)

    # Check store
    store = get_idempotency_store()
    status, response, status_code = store.check_and_lock(
        key, endpoint, tenant_id, request_body
    )

    # Record metrics
    IDEMPOTENCY_REQUESTS_TOTAL.labels(endpoint=endpoint, status=status.value).inc()

    if status == IdempotencyStatus.HIT:
        IDEMPOTENCY_CACHE_HITS.labels(endpoint=endpoint).inc()

    if status == IdempotencyStatus.CONFLICT:
        IDEMPOTENCY_CONFLICTS.labels(endpoint=endpoint).inc()
        raise IdempotencyConflict(key)

    return status, response, status_code


def complete_idempotency(
    key: str,
    endpoint: str,
    tenant_id: str,
    response: Dict[str, Any],
    status_code: int,
) -> None:
    """
    Mark idempotent request as completed.

    Args:
        key: Idempotency-Key header value
        endpoint: API endpoint
        tenant_id: Tenant ID
        response: Response to cache
        status_code: HTTP status code
    """
    if not is_idempotency_enabled():
        return

    store = get_idempotency_store()
    store.complete(key, endpoint, tenant_id, response, status_code)


def release_idempotency(
    key: str,
    endpoint: str,
    tenant_id: str,
) -> None:
    """
    Release idempotency lock on error.

    Args:
        key: Idempotency-Key header value
        endpoint: API endpoint
        tenant_id: Tenant ID
    """
    if not is_idempotency_enabled():
        return

    store = get_idempotency_store()
    store.release(key, endpoint, tenant_id)

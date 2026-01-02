"""
Webhook store - SQLite-backed storage for webhooks, outbox, and deliveries (v4.1.0).

Tables:
- webhooks(id, tenant_id, project_id, name, url, events_json, secret_hash, secret_version, enabled, created_at, updated_at, last_delivery_at)
- webhook_outbox(id, tenant_id, project_id, webhook_id, event_name, event_id, payload_json, dedup_key, not_before_at, attempts, max_attempts, status, locked_by, locked_until)
- webhook_deliveries(id, tenant_id, project_id, webhook_id, outbox_id, ts_utc, status_code, duration_ms, error_code, response_snippet, attempt)
"""

import hashlib
import json
import secrets
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from auth_config import AUTH_DB_PATH


# Webhook secret pepper
WEBHOOK_SECRET_PEPPER = "bess_webhook_v1"


class OutboxStatus(Enum):
    """Outbox entry status."""
    QUEUED = "queued"
    DELIVERING = "delivering"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEAD = "dead"


@dataclass
class Webhook:
    """Webhook configuration."""
    id: str
    tenant_id: str
    project_id: Optional[str]  # None = tenant-wide webhook
    name: str
    url: str
    events: List[str]
    secret_hash: str
    secret_version: int
    enabled: bool
    created_at: str
    updated_at: str
    last_delivery_at: Optional[str] = None


@dataclass
class OutboxEntry:
    """Webhook outbox entry."""
    id: str
    tenant_id: str
    project_id: Optional[str]
    webhook_id: str
    event_name: str
    event_id: str
    payload_json: str
    dedup_key: Optional[str]
    not_before_at: str
    attempts: int
    max_attempts: int
    status: str
    locked_by: Optional[str] = None
    locked_until: Optional[str] = None


@dataclass
class DeliveryLog:
    """Webhook delivery log entry."""
    id: str
    tenant_id: str
    project_id: Optional[str]
    webhook_id: str
    outbox_id: str
    ts_utc: str
    status_code: Optional[int]
    duration_ms: int
    error_code: Optional[str]
    response_snippet: Optional[str]
    attempt: int


def hash_webhook_secret(secret: str) -> str:
    """Hash a webhook secret using SHA-256 with pepper."""
    salted = f"{WEBHOOK_SECRET_PEPPER}:{secret}"
    return hashlib.sha256(salted.encode()).hexdigest()


def generate_webhook_secret() -> str:
    """Generate a new webhook secret (plaintext, shown once)."""
    return f"whsec_{secrets.token_urlsafe(32)}"


class WebhookStore:
    """SQLite-backed webhook storage."""

    def __init__(self, db_path: str = AUTH_DB_PATH):
        """Initialize webhook store with database path."""
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Get database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Initialize database tables."""
        conn = self._get_conn()
        try:
            conn.executescript("""
                -- Webhooks table
                CREATE TABLE IF NOT EXISTS webhooks (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    project_id TEXT,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL,
                    events_json TEXT NOT NULL,
                    secret_hash TEXT NOT NULL,
                    secret_version INTEGER NOT NULL DEFAULT 1,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_delivery_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_webhooks_tenant ON webhooks(tenant_id);
                CREATE INDEX IF NOT EXISTS idx_webhooks_project ON webhooks(project_id);
                CREATE INDEX IF NOT EXISTS idx_webhooks_tenant_enabled ON webhooks(tenant_id, enabled);

                -- Webhook outbox table
                CREATE TABLE IF NOT EXISTS webhook_outbox (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    project_id TEXT,
                    webhook_id TEXT NOT NULL,
                    event_name TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    dedup_key TEXT,
                    not_before_at TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 10,
                    status TEXT NOT NULL DEFAULT 'queued',
                    locked_by TEXT,
                    locked_until TEXT,
                    FOREIGN KEY (webhook_id) REFERENCES webhooks(id)
                );
                CREATE INDEX IF NOT EXISTS idx_outbox_tenant_status ON webhook_outbox(tenant_id, status);
                CREATE INDEX IF NOT EXISTS idx_outbox_webhook_status ON webhook_outbox(webhook_id, status);
                CREATE INDEX IF NOT EXISTS idx_outbox_not_before ON webhook_outbox(not_before_at);
                CREATE INDEX IF NOT EXISTS idx_outbox_locked_until ON webhook_outbox(locked_until);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_outbox_dedup ON webhook_outbox(webhook_id, dedup_key) WHERE dedup_key IS NOT NULL;

                -- Webhook deliveries table
                CREATE TABLE IF NOT EXISTS webhook_deliveries (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    project_id TEXT,
                    webhook_id TEXT NOT NULL,
                    outbox_id TEXT NOT NULL,
                    ts_utc TEXT NOT NULL,
                    status_code INTEGER,
                    duration_ms INTEGER NOT NULL,
                    error_code TEXT,
                    response_snippet TEXT,
                    attempt INTEGER NOT NULL,
                    FOREIGN KEY (webhook_id) REFERENCES webhooks(id),
                    FOREIGN KEY (outbox_id) REFERENCES webhook_outbox(id)
                );
                CREATE INDEX IF NOT EXISTS idx_deliveries_webhook_ts ON webhook_deliveries(webhook_id, ts_utc);
                CREATE INDEX IF NOT EXISTS idx_deliveries_outbox ON webhook_deliveries(outbox_id);
            """)
            conn.commit()
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Webhook CRUD
    # -------------------------------------------------------------------------

    def create_webhook(
        self,
        tenant_id: str,
        name: str,
        url: str,
        events: List[str],
        project_id: Optional[str] = None,
        enabled: bool = True,
    ) -> tuple[Webhook, str]:
        """Create a new webhook. Returns (webhook, secret_plaintext)."""
        webhook_id = str(uuid.uuid4())
        secret_plaintext = generate_webhook_secret()
        secret_hash = hash_webhook_secret(secret_plaintext)
        now = datetime.now(timezone.utc).isoformat()

        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT INTO webhooks
                (id, tenant_id, project_id, name, url, events_json, secret_hash, secret_version, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (webhook_id, tenant_id, project_id, name, url, json.dumps(events), secret_hash, 1 if enabled else 0, now, now),
            )
            conn.commit()
        finally:
            conn.close()

        webhook = Webhook(
            id=webhook_id,
            tenant_id=tenant_id,
            project_id=project_id,
            name=name,
            url=url,
            events=events,
            secret_hash=secret_hash,
            secret_version=1,
            enabled=enabled,
            created_at=now,
            updated_at=now,
        )
        return webhook, secret_plaintext

    def get_webhook(self, webhook_id: str, tenant_id: Optional[str] = None) -> Optional[Webhook]:
        """Get webhook by ID, optionally scoped to tenant."""
        conn = self._get_conn()
        try:
            if tenant_id:
                row = conn.execute(
                    "SELECT * FROM webhooks WHERE id = ? AND tenant_id = ?",
                    (webhook_id, tenant_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM webhooks WHERE id = ?",
                    (webhook_id,),
                ).fetchone()
            if not row:
                return None
            return self._row_to_webhook(row)
        finally:
            conn.close()

    def list_webhooks(
        self,
        tenant_id: str,
        project_id: Optional[str] = None,
        include_tenant_wide: bool = True,
    ) -> List[Webhook]:
        """List webhooks for tenant, optionally filtered by project."""
        conn = self._get_conn()
        try:
            if project_id and include_tenant_wide:
                # Project-specific + tenant-wide webhooks
                rows = conn.execute(
                    """
                    SELECT * FROM webhooks
                    WHERE tenant_id = ? AND (project_id = ? OR project_id IS NULL)
                    ORDER BY created_at DESC
                    """,
                    (tenant_id, project_id),
                ).fetchall()
            elif project_id:
                # Project-specific only
                rows = conn.execute(
                    "SELECT * FROM webhooks WHERE tenant_id = ? AND project_id = ? ORDER BY created_at DESC",
                    (tenant_id, project_id),
                ).fetchall()
            else:
                # All webhooks for tenant
                rows = conn.execute(
                    "SELECT * FROM webhooks WHERE tenant_id = ? ORDER BY created_at DESC",
                    (tenant_id,),
                ).fetchall()
            return [self._row_to_webhook(row) for row in rows]
        finally:
            conn.close()

    def update_webhook(
        self,
        webhook_id: str,
        tenant_id: Optional[str] = None,
        name: Optional[str] = None,
        url: Optional[str] = None,
        events: Optional[List[str]] = None,
        enabled: Optional[bool] = None,
    ) -> Optional[Webhook]:
        """Update webhook fields."""
        webhook = self.get_webhook(webhook_id, tenant_id)
        if not webhook:
            return None

        updates = []
        params = []

        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if url is not None:
            updates.append("url = ?")
            params.append(url)
        if events is not None:
            updates.append("events_json = ?")
            params.append(json.dumps(events))
        if enabled is not None:
            updates.append("enabled = ?")
            params.append(1 if enabled else 0)

        if not updates:
            return webhook

        updates.append("updated_at = ?")
        params.append(datetime.now(timezone.utc).isoformat())
        params.append(webhook_id)

        conn = self._get_conn()
        try:
            conn.execute(
                f"UPDATE webhooks SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            conn.commit()
        finally:
            conn.close()

        return self.get_webhook(webhook_id)

    def delete_webhook(self, webhook_id: str, tenant_id: Optional[str] = None) -> bool:
        """Delete webhook by ID, optionally scoped to tenant."""
        conn = self._get_conn()
        try:
            if tenant_id:
                cursor = conn.execute(
                    "DELETE FROM webhooks WHERE id = ? AND tenant_id = ?",
                    (webhook_id, tenant_id),
                )
            else:
                cursor = conn.execute("DELETE FROM webhooks WHERE id = ?", (webhook_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def rotate_secret(
        self, webhook_id: str, tenant_id: Optional[str] = None
    ) -> Optional[tuple[str, int]]:
        """Rotate webhook secret. Returns (new_secret, new_version) tuple."""
        webhook = self.get_webhook(webhook_id, tenant_id)
        if not webhook:
            return None

        secret_plaintext = generate_webhook_secret()
        secret_hash = hash_webhook_secret(secret_plaintext)
        now = datetime.now(timezone.utc).isoformat()
        new_version = webhook.secret_version + 1

        conn = self._get_conn()
        try:
            conn.execute(
                """
                UPDATE webhooks
                SET secret_hash = ?, secret_version = ?, updated_at = ?
                WHERE id = ?
                """,
                (secret_hash, new_version, now, webhook_id),
            )
            conn.commit()
        finally:
            conn.close()

        return (secret_plaintext, new_version)

    # -------------------------------------------------------------------------
    # Outbox operations
    # -------------------------------------------------------------------------

    def enqueue_event(
        self,
        webhook_id: str,
        tenant_id: str,
        project_id: Optional[str],
        event_name: str,
        event_id: str,
        payload: dict,
        dedup_key: Optional[str] = None,
        not_before: Optional[datetime] = None,
        max_attempts: int = 10,
    ) -> Optional[OutboxEntry]:
        """Add event to outbox. Returns None if dedup_key already exists."""
        outbox_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        not_before_at = (not_before or now).isoformat()

        conn = self._get_conn()
        try:
            try:
                conn.execute(
                    """
                    INSERT INTO webhook_outbox
                    (id, tenant_id, project_id, webhook_id, event_name, event_id, payload_json, dedup_key, not_before_at, max_attempts, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued')
                    """,
                    (outbox_id, tenant_id, project_id, webhook_id, event_name, event_id, json.dumps(payload), dedup_key, not_before_at, max_attempts),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                # Dedup key conflict
                return None
        finally:
            conn.close()

        return OutboxEntry(
            id=outbox_id,
            tenant_id=tenant_id,
            project_id=project_id,
            webhook_id=webhook_id,
            event_name=event_name,
            event_id=event_id,
            payload_json=json.dumps(payload),
            dedup_key=dedup_key,
            not_before_at=not_before_at,
            attempts=0,
            max_attempts=max_attempts,
            status="queued",
        )

    def claim_outbox_entry(self, worker_id: str, lock_duration_seconds: int = 300) -> Optional[OutboxEntry]:
        """Claim an outbox entry for processing. Returns None if none available."""
        now = datetime.now(timezone.utc)
        lock_until = (now + timedelta(seconds=lock_duration_seconds)).isoformat()

        conn = self._get_conn()
        try:
            # Find an unlocked, ready entry
            row = conn.execute(
                """
                SELECT * FROM webhook_outbox
                WHERE status IN ('queued', 'failed')
                  AND not_before_at <= ?
                  AND (locked_until IS NULL OR locked_until < ?)
                ORDER BY not_before_at ASC
                LIMIT 1
                """,
                (now.isoformat(), now.isoformat()),
            ).fetchone()

            if not row:
                return None

            outbox_id = row["id"]

            # Try to claim it
            cursor = conn.execute(
                """
                UPDATE webhook_outbox
                SET status = 'delivering', locked_by = ?, locked_until = ?, attempts = attempts + 1
                WHERE id = ? AND (locked_until IS NULL OR locked_until < ?)
                """,
                (worker_id, lock_until, outbox_id, now.isoformat()),
            )
            conn.commit()

            if cursor.rowcount == 0:
                # Someone else claimed it
                return None

            # Return updated entry
            row = conn.execute("SELECT * FROM webhook_outbox WHERE id = ?", (outbox_id,)).fetchone()
            return self._row_to_outbox(row)
        finally:
            conn.close()

    def mark_outbox_succeeded(self, outbox_id: str):
        """Mark outbox entry as succeeded."""
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE webhook_outbox SET status = 'succeeded', locked_by = NULL, locked_until = NULL WHERE id = ?",
                (outbox_id,),
            )
            # Update webhook last_delivery_at
            row = conn.execute("SELECT webhook_id FROM webhook_outbox WHERE id = ?", (outbox_id,)).fetchone()
            if row:
                conn.execute(
                    "UPDATE webhooks SET last_delivery_at = ? WHERE id = ?",
                    (now, row["webhook_id"]),
                )
            conn.commit()
        finally:
            conn.close()

    def mark_outbox_failed(self, outbox_id: str, next_retry_seconds: Optional[int] = None):
        """Mark outbox entry as failed. Optionally schedule retry."""
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM webhook_outbox WHERE id = ?", (outbox_id,)).fetchone()
            if not row:
                return

            attempts = row["attempts"]
            max_attempts = row["max_attempts"]

            if attempts >= max_attempts:
                # Move to dead letter
                conn.execute(
                    "UPDATE webhook_outbox SET status = 'dead', locked_by = NULL, locked_until = NULL WHERE id = ?",
                    (outbox_id,),
                )
            else:
                # Schedule retry
                if next_retry_seconds:
                    not_before = datetime.now(timezone.utc) + timedelta(seconds=next_retry_seconds)
                    conn.execute(
                        "UPDATE webhook_outbox SET status = 'failed', locked_by = NULL, locked_until = NULL, not_before_at = ? WHERE id = ?",
                        (not_before.isoformat(), outbox_id),
                    )
                else:
                    conn.execute(
                        "UPDATE webhook_outbox SET status = 'failed', locked_by = NULL, locked_until = NULL WHERE id = ?",
                        (outbox_id,),
                    )
            conn.commit()
        finally:
            conn.close()

    def get_outbox_depth(self, status: Optional[str] = None) -> int:
        """Get count of outbox entries by status."""
        conn = self._get_conn()
        try:
            if status:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM webhook_outbox WHERE status = ?",
                    (status,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) as cnt FROM webhook_outbox").fetchone()
            return row["cnt"]
        finally:
            conn.close()

    def list_dead_letter(self, webhook_id: str, limit: int = 100) -> List[OutboxEntry]:
        """List dead letter entries for a webhook."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """
                SELECT * FROM webhook_outbox
                WHERE webhook_id = ? AND status = 'dead'
                ORDER BY not_before_at DESC
                LIMIT ?
                """,
                (webhook_id, limit),
            ).fetchall()
            return [self._row_to_outbox(row) for row in rows]
        finally:
            conn.close()

    def replay_dead_letter(self, outbox_id: str) -> bool:
        """Replay a dead letter entry."""
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """
                UPDATE webhook_outbox
                SET status = 'queued', attempts = 0, not_before_at = ?, locked_by = NULL, locked_until = NULL
                WHERE id = ? AND status = 'dead'
                """,
                (now, outbox_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Delivery logging
    # -------------------------------------------------------------------------

    def log_delivery(
        self,
        webhook_id: str,
        outbox_id: str,
        tenant_id: str,
        project_id: Optional[str],
        status_code: Optional[int],
        duration_ms: int,
        attempt: int,
        error_code: Optional[str] = None,
        response_snippet: Optional[str] = None,
    ) -> DeliveryLog:
        """Log a webhook delivery attempt."""
        delivery_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        # Truncate response snippet
        if response_snippet and len(response_snippet) > 512:
            response_snippet = response_snippet[:512]

        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT INTO webhook_deliveries
                (id, tenant_id, project_id, webhook_id, outbox_id, ts_utc, status_code, duration_ms, error_code, response_snippet, attempt)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (delivery_id, tenant_id, project_id, webhook_id, outbox_id, now, status_code, duration_ms, error_code, response_snippet, attempt),
            )
            conn.commit()
        finally:
            conn.close()

        return DeliveryLog(
            id=delivery_id,
            tenant_id=tenant_id,
            project_id=project_id,
            webhook_id=webhook_id,
            outbox_id=outbox_id,
            ts_utc=now,
            status_code=status_code,
            duration_ms=duration_ms,
            error_code=error_code,
            response_snippet=response_snippet,
            attempt=attempt,
        )

    def list_deliveries(
        self,
        webhook_id: str,
        from_ts: Optional[str] = None,
        to_ts: Optional[str] = None,
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> List[DeliveryLog]:
        """List delivery logs for a webhook."""
        conn = self._get_conn()
        try:
            query = "SELECT * FROM webhook_deliveries WHERE webhook_id = ?"
            params: List[Any] = [webhook_id]

            if from_ts:
                query += " AND ts_utc >= ?"
                params.append(from_ts)
            if to_ts:
                query += " AND ts_utc <= ?"
                params.append(to_ts)
            if cursor:
                query += " AND id < ?"
                params.append(cursor)

            query += " ORDER BY ts_utc DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            return [self._row_to_delivery(row) for row in rows]
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _row_to_webhook(self, row: sqlite3.Row) -> Webhook:
        """Convert database row to Webhook."""
        return Webhook(
            id=row["id"],
            tenant_id=row["tenant_id"],
            project_id=row["project_id"],
            name=row["name"],
            url=row["url"],
            events=json.loads(row["events_json"]),
            secret_hash=row["secret_hash"],
            secret_version=row["secret_version"],
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_delivery_at=row["last_delivery_at"],
        )

    def _row_to_outbox(self, row: sqlite3.Row) -> OutboxEntry:
        """Convert database row to OutboxEntry."""
        return OutboxEntry(
            id=row["id"],
            tenant_id=row["tenant_id"],
            project_id=row["project_id"],
            webhook_id=row["webhook_id"],
            event_name=row["event_name"],
            event_id=row["event_id"],
            payload_json=row["payload_json"],
            dedup_key=row["dedup_key"],
            not_before_at=row["not_before_at"],
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            status=row["status"],
            locked_by=row["locked_by"],
            locked_until=row["locked_until"],
        )

    def _row_to_delivery(self, row: sqlite3.Row) -> DeliveryLog:
        """Convert database row to DeliveryLog."""
        return DeliveryLog(
            id=row["id"],
            tenant_id=row["tenant_id"],
            project_id=row["project_id"],
            webhook_id=row["webhook_id"],
            outbox_id=row["outbox_id"],
            ts_utc=row["ts_utc"],
            status_code=row["status_code"],
            duration_ms=row["duration_ms"],
            error_code=row["error_code"],
            response_snippet=row["response_snippet"],
            attempt=row["attempt"],
        )

    def get_webhooks_for_event(
        self,
        tenant_id: str,
        project_id: Optional[str],
        event_name: str,
    ) -> List[Webhook]:
        """Get all enabled webhooks subscribed to an event."""
        conn = self._get_conn()
        try:
            # Get project-specific and tenant-wide webhooks
            if project_id:
                rows = conn.execute(
                    """
                    SELECT * FROM webhooks
                    WHERE tenant_id = ? AND (project_id = ? OR project_id IS NULL) AND enabled = 1
                    """,
                    (tenant_id, project_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM webhooks WHERE tenant_id = ? AND project_id IS NULL AND enabled = 1",
                    (tenant_id,),
                ).fetchall()

            # Filter by event subscription
            result = []
            for row in rows:
                webhook = self._row_to_webhook(row)
                if event_name in webhook.events or "*" in webhook.events:
                    result.append(webhook)
            return result
        finally:
            conn.close()

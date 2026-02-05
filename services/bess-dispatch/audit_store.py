"""
Audit log store - SQLite-backed audit trail (v3.0.0 PR4, v3.2.0 tamper-evident chain).

Provides:
- Audit log entry creation for security-relevant events
- Query/filter audit logs by tenant, action, actor
- Export to CSV/JSON
- Tamper-evident hash chain for integrity verification (v3.2.0)

Actions logged:
- login_success, login_failure
- api_key_created, api_key_revoked
- sizing_run, batch_job_created
- export_downloaded
"""

import csv
import hashlib
import io
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from prometheus_client import Counter, Gauge


# Configuration
AUDIT_STORE_PATH = os.getenv("AUDIT_STORE_PATH", "/data/audit.sqlite")
AUDIT_STORE_ENABLED = os.getenv("AUDIT_STORE_ENABLED", "true").lower() in ("true", "1", "yes")
AUDIT_STORE_RETENTION_DAYS = int(os.getenv("AUDIT_STORE_RETENTION_DAYS", "90"))

# Chain secret for HMAC (should be set in production)
AUDIT_CHAIN_SECRET = os.getenv("AUDIT_CHAIN_SECRET", "bess-audit-chain-v1")


# Prometheus metrics for audit chain (v3.2.0)
AUDIT_ENTRIES_TOTAL = Counter(
    "bess_audit_entries_total",
    "Total audit log entries created",
    ["action"]
)
AUDIT_CHAIN_VERIFIED_TOTAL = Counter(
    "bess_audit_chain_verified_total",
    "Total chain verification runs",
    ["result"]  # valid, tampered, empty
)
AUDIT_CHAIN_BREAKS_TOTAL = Counter(
    "bess_audit_chain_breaks_total",
    "Total chain breaks detected"
)


class AuditStore:
    """SQLite-backed audit log store."""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize AuditStore."""
        self.db_path = db_path or AUDIT_STORE_PATH
        self._ensure_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Get database connection."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_db(self) -> None:
        """Create database and tables."""
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        conn = self._get_conn()
        try:
            # v3.2.0: Added prev_hash, entry_hash for tamper-evident chain
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor_id TEXT,
                    actor_email TEXT,
                    actor_role TEXT,
                    auth_method TEXT,
                    resource_type TEXT,
                    resource_id TEXT,
                    details_json TEXT,
                    ip_address TEXT,
                    user_agent TEXT,
                    prev_hash TEXT,
                    entry_hash TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_tenant_id ON audit_log(tenant_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_log(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_actor_id ON audit_log(actor_id)")

            # Migration: add new columns if they don't exist (v3.2.0)
            try:
                conn.execute("ALTER TABLE audit_log ADD COLUMN prev_hash TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
            try:
                conn.execute("ALTER TABLE audit_log ADD COLUMN entry_hash TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists

            conn.commit()
        finally:
            conn.close()

    def _compute_entry_hash(
        self,
        entry_id: str,
        tenant_id: str,
        created_at: str,
        action: str,
        actor_id: Optional[str],
        actor_email: Optional[str],
        resource_type: Optional[str],
        resource_id: Optional[str],
        details_json: Optional[str],
        prev_hash: Optional[str],
    ) -> str:
        """Compute SHA-256 hash for an entry (tamper-evident chain)."""
        # Create canonical string representation
        data = f"{entry_id}|{tenant_id}|{created_at}|{action}|{actor_id or ''}|{actor_email or ''}|{resource_type or ''}|{resource_id or ''}|{details_json or ''}|{prev_hash or 'GENESIS'}"
        # HMAC with chain secret for added security
        return hashlib.sha256(f"{AUDIT_CHAIN_SECRET}:{data}".encode()).hexdigest()

    def _get_last_hash(self) -> Optional[str]:
        """Get the entry_hash of the most recent entry."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT entry_hash FROM audit_log ORDER BY created_at DESC, id DESC LIMIT 1"
            )
            row = cursor.fetchone()
            return row["entry_hash"] if row else None
        finally:
            conn.close()

    def _now_iso(self) -> str:
        """Get current UTC timestamp."""
        return datetime.now(timezone.utc).isoformat()

    def log(
        self,
        tenant_id: str,
        action: str,
        actor_id: Optional[str] = None,
        actor_email: Optional[str] = None,
        actor_role: Optional[str] = None,
        auth_method: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> str:
        """
        Log an audit event with tamper-evident hash chain.

        Args:
            tenant_id: Tenant identifier
            action: Action type (e.g., 'login_success', 'api_key_created')
            actor_id: User or API key ID
            actor_email: User email
            actor_role: Actor's role
            auth_method: 'jwt', 'api_key', 'disabled'
            resource_type: Type of resource affected (e.g., 'run', 'job', 'api_key')
            resource_id: ID of resource affected
            details: Additional event details
            ip_address: Client IP address
            user_agent: Client user agent

        Returns:
            Audit log entry ID
        """
        entry_id = str(uuid.uuid4())
        created_at = self._now_iso()
        details_json = json.dumps(details) if details else None

        # Get previous hash for chain (v3.2.0)
        prev_hash = self._get_last_hash()

        # Compute entry hash
        entry_hash = self._compute_entry_hash(
            entry_id=entry_id,
            tenant_id=tenant_id,
            created_at=created_at,
            action=action,
            actor_id=actor_id,
            actor_email=actor_email,
            resource_type=resource_type,
            resource_id=resource_id,
            details_json=details_json,
            prev_hash=prev_hash,
        )

        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT INTO audit_log (
                    id, tenant_id, created_at, action, actor_id, actor_email,
                    actor_role, auth_method, resource_type, resource_id,
                    details_json, ip_address, user_agent, prev_hash, entry_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id, tenant_id, created_at, action, actor_id, actor_email,
                    actor_role, auth_method, resource_type, resource_id,
                    details_json, ip_address, user_agent, prev_hash, entry_hash,
                ),
            )
            conn.commit()
            AUDIT_ENTRIES_TOTAL.labels(action=action).inc()
            return entry_id
        finally:
            conn.close()

    def query(
        self,
        tenant_id: str,
        action: Optional[str] = None,
        actor_id: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        Query audit log entries.

        Args:
            tenant_id: Tenant identifier (required for tenant isolation)
            action: Filter by action type
            actor_id: Filter by actor
            resource_type: Filter by resource type
            resource_id: Filter by resource ID
            from_date: Start date (ISO format)
            to_date: End date (ISO format)
            limit: Max results
            offset: Pagination offset

        Returns:
            Dict with items, total, limit, offset
        """
        conn = self._get_conn()
        try:
            conditions = ["tenant_id = ?"]
            params: List[Any] = [tenant_id]

            if action:
                conditions.append("action = ?")
                params.append(action)
            if actor_id:
                conditions.append("actor_id = ?")
                params.append(actor_id)
            if resource_type:
                conditions.append("resource_type = ?")
                params.append(resource_type)
            if resource_id:
                conditions.append("resource_id = ?")
                params.append(resource_id)
            if from_date:
                conditions.append("created_at >= ?")
                params.append(from_date)
            if to_date:
                conditions.append("created_at <= ?")
                params.append(to_date)

            where_clause = " AND ".join(conditions)

            # Count total
            cursor = conn.execute(
                f"SELECT COUNT(*) as cnt FROM audit_log WHERE {where_clause}",
                params,
            )
            total = cursor.fetchone()["cnt"]

            # Get items
            cursor = conn.execute(
                f"""
                SELECT * FROM audit_log
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                params + [limit, offset],
            )

            items = []
            for row in cursor.fetchall():
                item = dict(row)
                # Parse details JSON
                if item.get("details_json"):
                    try:
                        item["details"] = json.loads(item["details_json"])
                    except json.JSONDecodeError:
                        item["details"] = None
                del item["details_json"]
                items.append(item)

            return {
                "items": items,
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        finally:
            conn.close()

    def export_csv(
        self,
        tenant_id: str,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> str:
        """
        Export audit log to CSV format.

        Args:
            tenant_id: Tenant identifier
            from_date: Start date (ISO format)
            to_date: End date (ISO format)

        Returns:
            CSV string
        """
        result = self.query(
            tenant_id=tenant_id,
            from_date=from_date,
            to_date=to_date,
            limit=10000,  # Max export
        )

        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "id", "tenant_id", "created_at", "action", "actor_id",
                "actor_email", "actor_role", "auth_method", "resource_type",
                "resource_id", "details", "ip_address", "user_agent",
            ],
        )
        writer.writeheader()

        for item in result["items"]:
            # Convert details back to JSON string for CSV
            if item.get("details"):
                item["details"] = json.dumps(item["details"])
            writer.writerow(item)

        return output.getvalue()

    def export_json(
        self,
        tenant_id: str,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> str:
        """
        Export audit log to JSON format.

        Args:
            tenant_id: Tenant identifier
            from_date: Start date (ISO format)
            to_date: End date (ISO format)

        Returns:
            JSON string
        """
        result = self.query(
            tenant_id=tenant_id,
            from_date=from_date,
            to_date=to_date,
            limit=10000,
        )

        return json.dumps(result, indent=2)

    def prune(self, retention_days: Optional[int] = None) -> int:
        """
        Delete audit entries older than retention period.

        Args:
            retention_days: Days to keep (defaults to AUDIT_STORE_RETENTION_DAYS)

        Returns:
            Number of entries deleted
        """
        from datetime import timedelta

        if retention_days is None:
            retention_days = AUDIT_STORE_RETENTION_DAYS

        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        cutoff_str = cutoff.isoformat()

        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "DELETE FROM audit_log WHERE created_at < ?",
                (cutoff_str,),
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    def verify_chain(self, limit: int = 10000) -> Dict[str, Any]:
        """
        Verify the integrity of the audit chain (v3.2.0).

        Checks that each entry's prev_hash matches the previous entry's entry_hash.

        Args:
            limit: Maximum entries to verify

        Returns:
            Dict with:
                - valid: bool - True if chain is intact
                - entries_checked: int - Number of entries verified
                - first_break_at: Optional[str] - ID of first broken entry
                - first_break_reason: Optional[str] - Reason for break
        """
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """
                SELECT id, tenant_id, created_at, action, actor_id, actor_email,
                       resource_type, resource_id, details_json, prev_hash, entry_hash
                FROM audit_log
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                (limit,)
            )

            entries = cursor.fetchall()
            if not entries:
                AUDIT_CHAIN_VERIFIED_TOTAL.labels(result="empty").inc()
                return {
                    "valid": True,
                    "entries_checked": 0,
                    "first_break_at": None,
                    "first_break_reason": None,
                }

            prev_hash = None
            entries_checked = 0

            for row in entries:
                entry_id = row["id"]
                stored_prev_hash = row["prev_hash"]
                stored_entry_hash = row["entry_hash"]

                # Check prev_hash linkage
                if entries_checked == 0:
                    # First entry should have prev_hash = None
                    if stored_prev_hash is not None:
                        # Legacy entry without chain - skip check
                        pass
                else:
                    # Subsequent entries should link to previous
                    if stored_prev_hash != prev_hash:
                        AUDIT_CHAIN_VERIFIED_TOTAL.labels(result="tampered").inc()
                        AUDIT_CHAIN_BREAKS_TOTAL.inc()
                        return {
                            "valid": False,
                            "entries_checked": entries_checked,
                            "first_break_at": entry_id,
                            "first_break_reason": "prev_hash mismatch",
                        }

                # Verify entry_hash is correct (if it exists)
                if stored_entry_hash:
                    expected_hash = self._compute_entry_hash(
                        entry_id=entry_id,
                        tenant_id=row["tenant_id"],
                        created_at=row["created_at"],
                        action=row["action"],
                        actor_id=row["actor_id"],
                        actor_email=row["actor_email"],
                        resource_type=row["resource_type"],
                        resource_id=row["resource_id"],
                        details_json=row["details_json"],
                        prev_hash=stored_prev_hash,
                    )
                    if stored_entry_hash != expected_hash:
                        AUDIT_CHAIN_VERIFIED_TOTAL.labels(result="tampered").inc()
                        AUDIT_CHAIN_BREAKS_TOTAL.inc()
                        return {
                            "valid": False,
                            "entries_checked": entries_checked,
                            "first_break_at": entry_id,
                            "first_break_reason": "entry_hash mismatch (data tampered)",
                        }

                prev_hash = stored_entry_hash
                entries_checked += 1

            AUDIT_CHAIN_VERIFIED_TOTAL.labels(result="valid").inc()
            return {
                "valid": True,
                "entries_checked": entries_checked,
                "first_break_at": None,
                "first_break_reason": None,
            }
        finally:
            conn.close()

    def get_chain_stats(self) -> Dict[str, Any]:
        """Get statistics about the audit chain."""
        conn = self._get_conn()
        try:
            cursor = conn.execute("SELECT COUNT(*) as total FROM audit_log")
            total = cursor.fetchone()["total"]

            cursor = conn.execute(
                "SELECT COUNT(*) as with_hash FROM audit_log WHERE entry_hash IS NOT NULL"
            )
            with_hash = cursor.fetchone()["with_hash"]

            cursor = conn.execute(
                "SELECT MIN(created_at) as first, MAX(created_at) as last FROM audit_log"
            )
            row = cursor.fetchone()

            return {
                "total_entries": total,
                "entries_with_hash": with_hash,
                "first_entry_at": row["first"],
                "last_entry_at": row["last"],
            }
        finally:
            conn.close()


# Global instance
_audit_store: Optional[AuditStore] = None


def get_audit_store() -> AuditStore:
    """Get or create global AuditStore instance."""
    global _audit_store
    if _audit_store is None:
        _audit_store = AuditStore()
    return _audit_store


def log_audit(
    tenant_id: str,
    action: str,
    actor_id: Optional[str] = None,
    actor_email: Optional[str] = None,
    actor_role: Optional[str] = None,
    auth_method: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Optional[str]:
    """
    Log an audit event using the global store.

    No-op if AUDIT_STORE_ENABLED is False.
    """
    if not AUDIT_STORE_ENABLED:
        return None
    return get_audit_store().log(
        tenant_id=tenant_id,
        action=action,
        actor_id=actor_id,
        actor_email=actor_email,
        actor_role=actor_role,
        auth_method=auth_method,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip_address=ip_address,
        user_agent=user_agent,
    )

"""
Audit log store - SQLite-backed audit trail (v3.0.0 PR4).

Provides:
- Audit log entry creation for security-relevant events
- Query/filter audit logs by tenant, action, actor
- Export to CSV/JSON

Actions logged:
- login_success, login_failure
- api_key_created, api_key_revoked
- sizing_run, batch_job_created
- export_downloaded
"""

import csv
import io
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# Configuration
AUDIT_STORE_PATH = os.getenv("AUDIT_STORE_PATH", "/data/audit.sqlite")
AUDIT_STORE_ENABLED = os.getenv("AUDIT_STORE_ENABLED", "true").lower() in ("true", "1", "yes")
AUDIT_STORE_RETENTION_DAYS = int(os.getenv("AUDIT_STORE_RETENTION_DAYS", "90"))


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
                    user_agent TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_tenant_id ON audit_log(tenant_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_log(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_actor_id ON audit_log(actor_id)")
            conn.commit()
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
        Log an audit event.

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

        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT INTO audit_log (
                    id, tenant_id, created_at, action, actor_id, actor_email,
                    actor_role, auth_method, resource_type, resource_id,
                    details_json, ip_address, user_agent
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id, tenant_id, created_at, action, actor_id, actor_email,
                    actor_role, auth_method, resource_type, resource_id,
                    details_json, ip_address, user_agent,
                ),
            )
            conn.commit()
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

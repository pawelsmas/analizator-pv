"""
SQLAlchemy-based Audit Repository (v3.3.0 PR3).

Provides database operations for audit logging with PostgreSQL support.
"""

import csv
import hashlib
import io
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, desc

from db_config import DB_QUERY_DURATION
from db_models import AuditLog
from db_session import get_db_session


# Configuration
AUDIT_STORE_ENABLED = os.getenv("AUDIT_STORE_ENABLED", "true").lower() in ("true", "1", "yes")
AUDIT_STORE_RETENTION_DAYS = int(os.getenv("AUDIT_STORE_RETENTION_DAYS", "90"))


def compute_entry_hash(entry: Dict[str, Any], prev_hash: Optional[str] = None) -> str:
    """
    Compute SHA-256 hash for audit chain integrity (v3.2.0).

    Args:
        entry: Audit entry dict
        prev_hash: Hash of previous entry (or None for first)

    Returns:
        64-char hex hash
    """
    content = json.dumps({
        "id": entry.get("id"),
        "tenant_id": entry.get("tenant_id"),
        "created_at": entry.get("created_at"),
        "action": entry.get("action"),
        "actor_id": entry.get("actor_id"),
        "resource_type": entry.get("resource_type"),
        "resource_id": entry.get("resource_id"),
        "prev_hash": prev_hash or "",
    }, sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()


class AuditRepo:
    """SQLAlchemy-based audit log repository."""

    def __init__(self):
        """Initialize AuditRepo."""
        pass

    def _now_iso(self) -> str:
        """Get current UTC timestamp."""
        return datetime.now(timezone.utc).isoformat()

    def _get_last_entry_hash(self, tenant_id: str) -> Optional[str]:
        """Get hash of last audit entry for chain integrity."""
        with get_db_session() as db:
            last = db.query(AuditLog).filter(
                AuditLog.tenant_id == tenant_id
            ).order_by(desc(AuditLog.created_at)).first()
            return last.entry_hash if last else None

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

        Returns:
            Audit log entry ID
        """
        with DB_QUERY_DURATION.labels(repo="audit", op="log").time():
            entry_id = str(uuid.uuid4())
            created_at = datetime.now(timezone.utc)
            details_json = json.dumps(details) if details else None

            with get_db_session() as db:
                # Get prev hash for chain integrity
                prev_hash = self._get_last_entry_hash(tenant_id)

                # Compute entry hash
                entry_dict = {
                    "id": entry_id,
                    "tenant_id": tenant_id,
                    "created_at": created_at.isoformat(),
                    "action": action,
                    "actor_id": actor_id,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                }
                entry_hash = compute_entry_hash(entry_dict, prev_hash)

                audit_log = AuditLog(
                    id=entry_id,
                    tenant_id=tenant_id,
                    created_at=created_at,
                    action=action,
                    actor_id=actor_id,
                    actor_email=actor_email,
                    actor_role=actor_role,
                    auth_method=auth_method,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    details_json=details_json,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    prev_hash=prev_hash,
                    entry_hash=entry_hash,
                )
                db.add(audit_log)
                db.commit()
                return entry_id

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

        Returns:
            Dict with items, total, limit, offset
        """
        with DB_QUERY_DURATION.labels(repo="audit", op="query").time():
            with get_db_session() as db:
                query = db.query(AuditLog).filter(AuditLog.tenant_id == tenant_id)

                if action:
                    query = query.filter(AuditLog.action == action)
                if actor_id:
                    query = query.filter(AuditLog.actor_id == actor_id)
                if resource_type:
                    query = query.filter(AuditLog.resource_type == resource_type)
                if resource_id:
                    query = query.filter(AuditLog.resource_id == resource_id)
                if from_date:
                    from_dt = datetime.fromisoformat(from_date.replace("Z", "+00:00"))
                    query = query.filter(AuditLog.created_at >= from_dt)
                if to_date:
                    to_dt = datetime.fromisoformat(to_date.replace("Z", "+00:00"))
                    query = query.filter(AuditLog.created_at <= to_dt)

                total = query.count()

                items = query.order_by(desc(AuditLog.created_at)).offset(offset).limit(limit).all()

                return {
                    "items": [item.to_dict() for item in items],
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                }

    def export_csv(
        self,
        tenant_id: str,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> str:
        """Export audit log to CSV format."""
        result = self.query(
            tenant_id=tenant_id,
            from_date=from_date,
            to_date=to_date,
            limit=10000,
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
        """Export audit log to JSON format."""
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

        Returns:
            Number of entries deleted
        """
        with DB_QUERY_DURATION.labels(repo="audit", op="prune").time():
            if retention_days is None:
                retention_days = AUDIT_STORE_RETENTION_DAYS

            cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

            with get_db_session() as db:
                count = db.query(AuditLog).filter(
                    AuditLog.created_at < cutoff
                ).delete(synchronize_session=False)
                db.commit()
                return count

    def verify_chain_integrity(self, tenant_id: str, limit: int = 1000) -> Dict[str, Any]:
        """
        Verify audit chain integrity (v3.2.0).

        Returns:
            Dict with is_valid, entries_checked, first_invalid_id, error
        """
        with DB_QUERY_DURATION.labels(repo="audit", op="verify_chain").time():
            with get_db_session() as db:
                entries = db.query(AuditLog).filter(
                    AuditLog.tenant_id == tenant_id
                ).order_by(AuditLog.created_at).limit(limit).all()

                if not entries:
                    return {
                        "is_valid": True,
                        "entries_checked": 0,
                        "first_invalid_id": None,
                        "error": None,
                    }

                prev_hash = None
                for entry in entries:
                    entry_dict = {
                        "id": entry.id,
                        "tenant_id": entry.tenant_id,
                        "created_at": entry.created_at.isoformat() if entry.created_at else None,
                        "action": entry.action,
                        "actor_id": entry.actor_id,
                        "resource_type": entry.resource_type,
                        "resource_id": entry.resource_id,
                    }
                    expected_hash = compute_entry_hash(entry_dict, prev_hash)

                    if entry.entry_hash != expected_hash:
                        return {
                            "is_valid": False,
                            "entries_checked": entries.index(entry) + 1,
                            "first_invalid_id": entry.id,
                            "error": "Hash mismatch",
                        }

                    if entry.prev_hash != prev_hash:
                        return {
                            "is_valid": False,
                            "entries_checked": entries.index(entry) + 1,
                            "first_invalid_id": entry.id,
                            "error": "Chain break - prev_hash mismatch",
                        }

                    prev_hash = entry.entry_hash

                return {
                    "is_valid": True,
                    "entries_checked": len(entries),
                    "first_invalid_id": None,
                    "error": None,
                }


# Global instance
_audit_repo: Optional[AuditRepo] = None


def get_audit_repo() -> AuditRepo:
    """Get or create global AuditRepo instance."""
    global _audit_repo
    if _audit_repo is None:
        _audit_repo = AuditRepo()
    return _audit_repo


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
    return get_audit_repo().log(
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

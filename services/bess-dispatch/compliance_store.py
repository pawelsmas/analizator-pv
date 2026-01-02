"""
Compliance store - SQLite-backed storage for retention policies, legal holds,
purge runs, and compliance exports (v4.3.0).

Tables:
- retention_policies(id, tenant_id, project_id, policy_json, enabled, created_at, updated_at)
- legal_holds(id, tenant_id, project_id, resource_type, resource_id, reason, created_by_user_id,
              created_at, expires_at, released_at)
- purge_runs(id, tenant_id, project_id, mode, started_at, finished_at, summary_json, error_code, error_detail)
- compliance_exports(id, tenant_id, project_id, requested_by_user_id, scope, options_json,
                     status, job_id, artifact_name, created_at, finished_at)

Usage:
    from compliance_store import ComplianceStore
    store = ComplianceStore()
    store.create_retention_policy(tenant_id, project_id=None, policy_json={...})
"""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from auth_config import AUTH_DB_PATH


class ResourceType(Enum):
    """Resource types that can be placed under legal hold."""
    PROJECT = "project"
    RUN = "run"
    JOB = "job"
    ALL = "all"


class PurgeMode(Enum):
    """Purge execution modes."""
    DRY_RUN = "dry_run"
    EXECUTE = "execute"


class ExportScope(Enum):
    """Compliance export scope."""
    TENANT = "tenant"
    PROJECT = "project"


class ExportStatus(Enum):
    """Compliance export job status."""
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ComplianceStore:
    """
    SQLite-backed storage for compliance and retention data.

    Thread-safe via WAL mode and connection-per-call pattern.
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize compliance store.

        Args:
            db_path: Path to SQLite database (default: AUTH_DB_PATH)
        """
        self.db_path = db_path or AUTH_DB_PATH
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Get a database connection with WAL mode."""
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        """Initialize database tables."""
        conn = self._get_conn()
        try:
            # Retention policies table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS retention_policies (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    project_id TEXT,
                    policy_json TEXT NOT NULL,
                    enabled INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(tenant_id, project_id)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_retention_policies_tenant
                ON retention_policies(tenant_id)
            """)
            # Unique partial index for tenant-level policies (project_id IS NULL)
            # SQLite treats NULL as unique from other NULLs, so we need this
            conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_retention_policies_tenant_null
                ON retention_policies(tenant_id) WHERE project_id IS NULL
            """)

            # Legal holds table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS legal_holds (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    project_id TEXT,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT,
                    reason TEXT NOT NULL,
                    created_by_user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    released_at TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_legal_holds_tenant_project
                ON legal_holds(tenant_id, project_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_legal_holds_resource
                ON legal_holds(tenant_id, resource_type, resource_id)
            """)

            # Purge runs table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS purge_runs (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    project_id TEXT,
                    mode TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    summary_json TEXT,
                    error_code TEXT,
                    error_detail TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_purge_runs_tenant
                ON purge_runs(tenant_id, started_at)
            """)

            # Compliance exports table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS compliance_exports (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    project_id TEXT,
                    requested_by_user_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    job_id TEXT,
                    artifact_name TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    progress_pct INTEGER DEFAULT 0,
                    current_step TEXT,
                    bundle_size_bytes INTEGER,
                    record_count INTEGER,
                    manifest_json TEXT,
                    error TEXT,
                    error_detail TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_compliance_exports_tenant
                ON compliance_exports(tenant_id, created_at)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_compliance_exports_tenant_project
                ON compliance_exports(tenant_id, project_id, created_at)
            """)

            conn.commit()
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Retention Policies
    # -------------------------------------------------------------------------

    def create_retention_policy(
        self,
        tenant_id: str,
        policy_json: Dict[str, Any],
        project_id: Optional[str] = None,
        enabled: bool = True,
    ) -> Dict[str, Any]:
        """
        Create a retention policy for tenant or project.

        Args:
            tenant_id: Tenant ID
            policy_json: Policy configuration (days per category)
            project_id: Optional project ID for project-level override
            enabled: Whether policy is active

        Returns:
            Created policy record

        Raises:
            sqlite3.IntegrityError: If policy already exists for tenant/project
        """
        conn = self._get_conn()
        try:
            policy_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()

            conn.execute("""
                INSERT INTO retention_policies
                (id, tenant_id, project_id, policy_json, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (policy_id, tenant_id, project_id, json.dumps(policy_json),
                  1 if enabled else 0, now, now))
            conn.commit()

            return {
                "id": policy_id,
                "tenant_id": tenant_id,
                "project_id": project_id,
                "policy_json": policy_json,
                "enabled": enabled,
                "created_at": now,
                "updated_at": now,
            }
        finally:
            conn.close()

    def get_retention_policy(
        self,
        tenant_id: str,
        project_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Get retention policy for tenant or project.

        Args:
            tenant_id: Tenant ID
            project_id: Optional project ID (None for tenant default)

        Returns:
            Policy record or None if not found
        """
        conn = self._get_conn()
        try:
            if project_id:
                row = conn.execute("""
                    SELECT * FROM retention_policies
                    WHERE tenant_id = ? AND project_id = ?
                """, (tenant_id, project_id)).fetchone()
            else:
                row = conn.execute("""
                    SELECT * FROM retention_policies
                    WHERE tenant_id = ? AND project_id IS NULL
                """, (tenant_id,)).fetchone()

            if not row:
                return None

            return {
                "id": row["id"],
                "tenant_id": row["tenant_id"],
                "project_id": row["project_id"],
                "policy_json": json.loads(row["policy_json"]),
                "enabled": bool(row["enabled"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        finally:
            conn.close()

    def update_retention_policy(
        self,
        tenant_id: str,
        policy_json: Optional[Dict[str, Any]] = None,
        enabled: Optional[bool] = None,
        project_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Update retention policy.

        Args:
            tenant_id: Tenant ID
            policy_json: New policy configuration (optional)
            enabled: New enabled state (optional)
            project_id: Optional project ID

        Returns:
            Updated policy or None if not found
        """
        conn = self._get_conn()
        try:
            now = datetime.now(timezone.utc).isoformat()

            updates = ["updated_at = ?"]
            params = [now]

            if policy_json is not None:
                updates.append("policy_json = ?")
                params.append(json.dumps(policy_json))

            if enabled is not None:
                updates.append("enabled = ?")
                params.append(1 if enabled else 0)

            params.append(tenant_id)

            if project_id:
                where = "tenant_id = ? AND project_id = ?"
                params.append(project_id)
            else:
                where = "tenant_id = ? AND project_id IS NULL"

            conn.execute(f"""
                UPDATE retention_policies
                SET {', '.join(updates)}
                WHERE {where}
            """, params)
            conn.commit()

            return self.get_retention_policy(tenant_id, project_id)
        finally:
            conn.close()

    def delete_retention_policy(
        self,
        tenant_id: str,
        project_id: Optional[str] = None,
    ) -> bool:
        """
        Delete retention policy.

        Returns:
            True if deleted, False if not found
        """
        conn = self._get_conn()
        try:
            if project_id:
                result = conn.execute("""
                    DELETE FROM retention_policies
                    WHERE tenant_id = ? AND project_id = ?
                """, (tenant_id, project_id))
            else:
                result = conn.execute("""
                    DELETE FROM retention_policies
                    WHERE tenant_id = ? AND project_id IS NULL
                """, (tenant_id,))
            conn.commit()
            return result.rowcount > 0
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Legal Holds
    # -------------------------------------------------------------------------

    def create_legal_hold(
        self,
        tenant_id: str,
        resource_type: str,
        reason: str,
        created_by_user_id: str,
        project_id: Optional[str] = None,
        resource_id: Optional[str] = None,
        expires_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a legal hold.

        Args:
            tenant_id: Tenant ID
            resource_type: Type of resource (project/run/job/all)
            reason: Reason for the hold
            created_by_user_id: User who created the hold
            project_id: Optional project ID
            resource_id: Optional specific resource ID
            expires_at: Optional expiry datetime ISO string

        Returns:
            Created legal hold record
        """
        conn = self._get_conn()
        try:
            hold_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()

            conn.execute("""
                INSERT INTO legal_holds
                (id, tenant_id, project_id, resource_type, resource_id, reason,
                 created_by_user_id, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (hold_id, tenant_id, project_id, resource_type, resource_id,
                  reason, created_by_user_id, now, expires_at))
            conn.commit()

            return {
                "id": hold_id,
                "tenant_id": tenant_id,
                "project_id": project_id,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "reason": reason,
                "created_by_user_id": created_by_user_id,
                "created_at": now,
                "expires_at": expires_at,
                "released_at": None,
            }
        finally:
            conn.close()

    def get_legal_hold(self, hold_id: str) -> Optional[Dict[str, Any]]:
        """Get a legal hold by ID."""
        conn = self._get_conn()
        try:
            row = conn.execute("""
                SELECT * FROM legal_holds WHERE id = ?
            """, (hold_id,)).fetchone()

            if not row:
                return None

            return dict(row)
        finally:
            conn.close()

    def list_legal_holds(
        self,
        tenant_id: str,
        project_id: Optional[str] = None,
        active_only: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        List legal holds for tenant/project.

        Args:
            tenant_id: Tenant ID
            project_id: Optional project ID filter
            active_only: If True, only return non-released, non-expired holds

        Returns:
            List of legal hold records
        """
        conn = self._get_conn()
        try:
            now = datetime.now(timezone.utc).isoformat()

            query = "SELECT * FROM legal_holds WHERE tenant_id = ?"
            params: List[Any] = [tenant_id]

            if project_id:
                query += " AND (project_id = ? OR project_id IS NULL)"
                params.append(project_id)

            if active_only:
                query += " AND released_at IS NULL"
                query += " AND (expires_at IS NULL OR expires_at > ?)"
                params.append(now)

            query += " ORDER BY created_at DESC"

            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def release_legal_hold(self, hold_id: str) -> Optional[Dict[str, Any]]:
        """
        Release a legal hold.

        Returns:
            Updated hold record or None if not found
        """
        conn = self._get_conn()
        try:
            now = datetime.now(timezone.utc).isoformat()

            conn.execute("""
                UPDATE legal_holds
                SET released_at = ?
                WHERE id = ? AND released_at IS NULL
            """, (now, hold_id))
            conn.commit()

            return self.get_legal_hold(hold_id)
        finally:
            conn.close()

    def is_resource_held(
        self,
        tenant_id: str,
        resource_type: str,
        resource_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> bool:
        """
        Check if a resource is under active legal hold.

        Checks:
        - Direct holds on the resource
        - Holds on the parent project
        - Tenant-wide "all" holds

        Returns:
            True if any active hold applies
        """
        conn = self._get_conn()
        try:
            now = datetime.now(timezone.utc).isoformat()

            # Check for any applicable active hold
            query = """
                SELECT COUNT(*) as count FROM legal_holds
                WHERE tenant_id = ?
                AND released_at IS NULL
                AND (expires_at IS NULL OR expires_at > ?)
                AND (
                    -- Exact resource match
                    (resource_type = ? AND resource_id = ?)
                    -- Project-level hold
                    OR (resource_type = 'project' AND resource_id = ?)
                    -- Project scope hold (any resource in project)
                    OR (project_id = ? AND resource_type = ?)
                    -- Tenant-wide hold
                    OR resource_type = 'all'
                )
            """
            params = [
                tenant_id, now,
                resource_type, resource_id,
                project_id,
                project_id, resource_type,
            ]

            row = conn.execute(query, params).fetchone()
            return row["count"] > 0
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Purge Runs
    # -------------------------------------------------------------------------

    def create_purge_run(
        self,
        tenant_id: str,
        mode: str,
        project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a purge run record.

        Args:
            tenant_id: Tenant ID
            mode: "dry_run" or "execute"
            project_id: Optional project scope

        Returns:
            Created purge run record
        """
        conn = self._get_conn()
        try:
            run_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()

            conn.execute("""
                INSERT INTO purge_runs
                (id, tenant_id, project_id, mode, started_at)
                VALUES (?, ?, ?, ?, ?)
            """, (run_id, tenant_id, project_id, mode, now))
            conn.commit()

            return {
                "id": run_id,
                "tenant_id": tenant_id,
                "project_id": project_id,
                "mode": mode,
                "started_at": now,
                "finished_at": None,
                "summary_json": None,
                "error_code": None,
                "error_detail": None,
            }
        finally:
            conn.close()

    def finish_purge_run(
        self,
        run_id: str,
        summary: Dict[str, Any],
        error_code: Optional[str] = None,
        error_detail: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Complete a purge run with summary.

        Args:
            run_id: Purge run ID
            summary: Summary of what was deleted/skipped
            error_code: Optional error code if failed
            error_detail: Optional error details

        Returns:
            Updated purge run record
        """
        conn = self._get_conn()
        try:
            now = datetime.now(timezone.utc).isoformat()

            conn.execute("""
                UPDATE purge_runs
                SET finished_at = ?, summary_json = ?, error_code = ?, error_detail = ?
                WHERE id = ?
            """, (now, json.dumps(summary), error_code, error_detail, run_id))
            conn.commit()

            return self.get_purge_run(run_id)
        finally:
            conn.close()

    def get_purge_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Get a purge run by ID."""
        conn = self._get_conn()
        try:
            row = conn.execute("""
                SELECT * FROM purge_runs WHERE id = ?
            """, (run_id,)).fetchone()

            if not row:
                return None

            result = dict(row)
            if result["summary_json"]:
                result["summary_json"] = json.loads(result["summary_json"])
            return result
        finally:
            conn.close()

    def list_purge_runs(
        self,
        tenant_id: str,
        project_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List purge runs for tenant/project."""
        conn = self._get_conn()
        try:
            if project_id:
                rows = conn.execute("""
                    SELECT * FROM purge_runs
                    WHERE tenant_id = ? AND project_id = ?
                    ORDER BY started_at DESC
                    LIMIT ?
                """, (tenant_id, project_id, limit)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM purge_runs
                    WHERE tenant_id = ?
                    ORDER BY started_at DESC
                    LIMIT ?
                """, (tenant_id, limit)).fetchall()

            results = []
            for row in rows:
                result = dict(row)
                if result["summary_json"]:
                    result["summary_json"] = json.loads(result["summary_json"])
                results.append(result)
            return results
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Compliance Exports
    # -------------------------------------------------------------------------

    def create_compliance_export(
        self,
        tenant_id: str,
        created_by_user_id: str,
        options: Dict[str, Any],
        project_id: Optional[str] = None,
        scope: Optional[str] = None,
        job_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a compliance export request.

        Args:
            tenant_id: Tenant ID
            created_by_user_id: User requesting the export
            options: Export options (what to include)
            project_id: Optional project scope
            scope: "tenant" or "project" (auto-detected if not provided)
            job_id: Optional job ID if using job queue

        Returns:
            Created export record
        """
        conn = self._get_conn()
        try:
            export_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            actual_scope = scope or ("project" if project_id else "tenant")

            conn.execute("""
                INSERT INTO compliance_exports
                (id, tenant_id, project_id, requested_by_user_id, scope, options_json,
                 status, job_id, created_at, progress_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (export_id, tenant_id, project_id, created_by_user_id, actual_scope,
                  json.dumps(options), "pending", job_id, now, 0))
            conn.commit()

            return {
                "id": export_id,
                "tenant_id": tenant_id,
                "project_id": project_id,
                "created_by_user_id": created_by_user_id,
                "scope": actual_scope,
                "options": options,
                "status": "pending",
                "job_id": job_id,
                "created_at": now,
                "started_at": None,
                "finished_at": None,
                "progress_pct": 0,
                "current_step": None,
            }
        finally:
            conn.close()

    def update_compliance_export_status(
        self,
        export_id: str,
        status: str,
        artifact_name: Optional[str] = None,
        finished: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        Update compliance export status.

        Args:
            export_id: Export ID
            status: New status
            artifact_name: Artifact filename if completed
            finished: Whether to set finished_at

        Returns:
            Updated export record
        """
        conn = self._get_conn()
        try:
            updates = ["status = ?"]
            params: List[Any] = [status]

            if artifact_name:
                updates.append("artifact_name = ?")
                params.append(artifact_name)

            if finished:
                updates.append("finished_at = ?")
                params.append(datetime.now(timezone.utc).isoformat())

            params.append(export_id)

            conn.execute(f"""
                UPDATE compliance_exports
                SET {', '.join(updates)}
                WHERE id = ?
            """, params)
            conn.commit()

            return self.get_compliance_export(export_id)
        finally:
            conn.close()

    def get_compliance_export(self, export_id: str) -> Optional[Dict[str, Any]]:
        """Get a compliance export by ID."""
        conn = self._get_conn()
        try:
            row = conn.execute("""
                SELECT * FROM compliance_exports WHERE id = ?
            """, (export_id,)).fetchone()

            if not row:
                return None

            result = dict(row)
            # Parse JSON fields
            if result.get("options_json"):
                result["options"] = json.loads(result["options_json"])
            else:
                result["options"] = {}
            if result.get("manifest_json"):
                result["manifest"] = json.loads(result["manifest_json"])
            else:
                result["manifest"] = None
            # Map created_by field for compatibility
            if "requested_by_user_id" in result:
                result["created_by_user_id"] = result["requested_by_user_id"]
            return result
        finally:
            conn.close()

    def list_compliance_exports(
        self,
        tenant_id: str,
        project_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List compliance exports for tenant/project."""
        conn = self._get_conn()
        try:
            if project_id:
                rows = conn.execute("""
                    SELECT * FROM compliance_exports
                    WHERE tenant_id = ? AND project_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (tenant_id, project_id, limit)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM compliance_exports
                    WHERE tenant_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (tenant_id, limit)).fetchall()

            results = []
            for row in rows:
                result = dict(row)
                if result.get("options_json"):
                    result["options"] = json.loads(result["options_json"])
                else:
                    result["options"] = {}
                if result.get("manifest_json"):
                    result["manifest"] = json.loads(result["manifest_json"])
                if "requested_by_user_id" in result:
                    result["created_by_user_id"] = result["requested_by_user_id"]
                results.append(result)
            return results
        finally:
            conn.close()

    def update_compliance_export(
        self,
        export_id: str,
        status: Optional[str] = None,
        started_at: Optional[str] = None,
        finished_at: Optional[str] = None,
        progress_pct: Optional[int] = None,
        current_step: Optional[str] = None,
        bundle_size_bytes: Optional[int] = None,
        record_count: Optional[int] = None,
        manifest: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        error_detail: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Update compliance export with flexible fields.

        Args:
            export_id: Export ID
            status: New status
            started_at: Start timestamp
            finished_at: Finish timestamp
            progress_pct: Progress percentage (0-100)
            current_step: Current processing step
            bundle_size_bytes: Size of generated bundle
            record_count: Number of records exported
            manifest: Export manifest
            error: Error message if failed
            error_detail: Detailed error info

        Returns:
            Updated export record
        """
        conn = self._get_conn()
        try:
            # Build dynamic update
            updates = []
            params: List[Any] = []

            if status is not None:
                updates.append("status = ?")
                params.append(status)
            if started_at is not None:
                updates.append("started_at = ?")
                params.append(started_at)
            if finished_at is not None:
                updates.append("finished_at = ?")
                params.append(finished_at)
            if progress_pct is not None:
                updates.append("progress_pct = ?")
                params.append(progress_pct)
            if current_step is not None:
                updates.append("current_step = ?")
                params.append(current_step)
            if bundle_size_bytes is not None:
                updates.append("bundle_size_bytes = ?")
                params.append(bundle_size_bytes)
            if record_count is not None:
                updates.append("record_count = ?")
                params.append(record_count)
            if manifest is not None:
                updates.append("manifest_json = ?")
                params.append(json.dumps(manifest))
            if error is not None:
                updates.append("error = ?")
                params.append(error)
            if error_detail is not None:
                updates.append("error_detail = ?")
                params.append(error_detail)

            if not updates:
                return self.get_compliance_export(export_id)

            params.append(export_id)

            conn.execute(f"""
                UPDATE compliance_exports
                SET {', '.join(updates)}
                WHERE id = ?
            """, params)
            conn.commit()

            return self.get_compliance_export(export_id)
        finally:
            conn.close()


# Global instance
_compliance_store: Optional[ComplianceStore] = None


def get_compliance_store() -> ComplianceStore:
    """Get or create the global ComplianceStore instance."""
    global _compliance_store
    if _compliance_store is None:
        _compliance_store = ComplianceStore()
    return _compliance_store


def reset_compliance_store() -> None:
    """Reset the global ComplianceStore instance (for testing)."""
    global _compliance_store
    _compliance_store = None

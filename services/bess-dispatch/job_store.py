"""
SQLite-backed JobStore for async batch sizing jobs (v1.2.0).

Provides:
- Persistent job storage with compressed request/result blobs
- Progress tracking (items_done, error_count)
- Status management (pending, running, done, failed, cancelled)
- Idempotency key support for duplicate detection
- Multi-worker safe job leasing with heartbeat/reclaim
- Atomic claim with lease expiration for fault tolerance
"""

import hashlib
import json
import os
import socket
import sqlite3
import uuid
import zlib
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


# -----------------------------------------------------------------------------
# Configuration (from environment)
# -----------------------------------------------------------------------------

JOB_STORE_ENABLED = os.getenv("JOB_STORE_ENABLED", "true").lower() in ("true", "1", "yes")
JOB_STORE_PATH = os.getenv("JOB_STORE_PATH", "/data/jobs.sqlite")
JOB_STORE_RETENTION_DAYS = int(os.getenv("JOB_STORE_RETENTION_DAYS", "14"))
JOBS_MAX_ITEMS = int(os.getenv("JOBS_MAX_ITEMS", "100"))
JOBS_INLINE_WAIT_MAX_SECONDS = int(os.getenv("JOBS_INLINE_WAIT_MAX_SECONDS", "60"))
JOBS_LEASE_SECONDS = int(os.getenv("JOBS_LEASE_SECONDS", "30"))
WORKER_ID = os.getenv("WORKER_ID", socket.gethostname())


# -----------------------------------------------------------------------------
# JobStore Class
# -----------------------------------------------------------------------------

class JobStore:
    """SQLite-backed store for async jobs with multi-worker lease support."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        worker_id: Optional[str] = None,
        lease_seconds: Optional[int] = None,
    ):
        """Initialize JobStore with SQLite database.

        Args:
            db_path: Path to SQLite database file
            worker_id: Unique identifier for this worker (default: WORKER_ID env or hostname)
            lease_seconds: Lease duration in seconds (default: JOBS_LEASE_SECONDS env or 30)
        """
        self.db_path = db_path or JOB_STORE_PATH
        self.worker_id = worker_id or WORKER_ID
        self.lease_seconds = lease_seconds or JOBS_LEASE_SECONDS
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Get database connection."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initialize database schema with v1.2.0 leasing columns."""
        # Ensure directory exists
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        conn = self._get_conn()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    batch_id TEXT,
                    idempotency_key TEXT UNIQUE,
                    items_total INTEGER NOT NULL DEFAULT 0,
                    items_done INTEGER NOT NULL DEFAULT 0,
                    error_count INTEGER NOT NULL DEFAULT 0,
                    request_hash TEXT NOT NULL,
                    request_blob BLOB NOT NULL,
                    result_blob BLOB,
                    message TEXT,
                    -- v1.2.0 leasing columns
                    lease_owner TEXT,
                    lease_expires_at TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    started_at TEXT,
                    finished_at TEXT,
                    last_error TEXT
                )
            """)

            # Migration: add columns for existing databases (BEFORE creating indexes on new columns)
            self._migrate_add_leasing_columns(conn)

            # Create indexes (including on new columns, after migration)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_type ON jobs(type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_idempotency_key ON jobs(idempotency_key)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_lease_expires_at ON jobs(lease_expires_at)")

            conn.commit()
        finally:
            conn.close()

    def _migrate_add_leasing_columns(self, conn: sqlite3.Connection) -> None:
        """Add v1.2.0 leasing columns to existing tables (migration)."""
        # Get existing columns
        cursor = conn.execute("PRAGMA table_info(jobs)")
        existing_columns = {row["name"] for row in cursor.fetchall()}

        # Add missing columns
        migrations = [
            ("lease_owner", "TEXT"),
            ("lease_expires_at", "TEXT"),
            ("attempts", "INTEGER NOT NULL DEFAULT 0"),
            ("max_attempts", "INTEGER NOT NULL DEFAULT 3"),
            ("started_at", "TEXT"),
            ("finished_at", "TEXT"),
            ("last_error", "TEXT"),
        ]

        for col_name, col_def in migrations:
            if col_name not in existing_columns:
                try:
                    conn.execute(f"ALTER TABLE jobs ADD COLUMN {col_name} {col_def}")
                except sqlite3.OperationalError:
                    pass  # Column might already exist

    def _compute_request_hash(self, request: Dict[str, Any]) -> str:
        """Compute deterministic SHA-256 hash of request."""
        canonical = json.dumps(request, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _compress(self, data: Dict[str, Any]) -> bytes:
        """Compress JSON data with zlib."""
        return zlib.compress(json.dumps(data).encode("utf-8"))

    def _decompress(self, blob: bytes) -> Dict[str, Any]:
        """Decompress zlib blob to JSON."""
        return json.loads(zlib.decompress(blob).decode("utf-8"))

    def _now_iso(self) -> str:
        """Get current UTC timestamp in ISO format."""
        return datetime.now(timezone.utc).isoformat()

    def _row_to_dict(self, row: sqlite3.Row, include_blobs: bool = False) -> Dict[str, Any]:
        """Convert SQLite row to dictionary."""
        d = dict(row)
        if include_blobs:
            if d.get("request_blob"):
                d["request"] = self._decompress(d["request_blob"])
            if d.get("result_blob"):
                d["result"] = self._decompress(d["result_blob"])
        # Remove blob fields from output
        d.pop("request_blob", None)
        d.pop("result_blob", None)
        return d

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def create_job(
        self,
        type: str,
        request: Dict[str, Any],
        batch_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> str:
        """
        Create a new job.

        Args:
            type: Job type (e.g., "sizing_batch")
            request: Full request payload
            batch_id: Optional batch identifier
            idempotency_key: Optional key for duplicate detection

        Returns:
            job_id of created or existing job (if idempotency_key matches)
        """
        conn = self._get_conn()
        try:
            # Check for existing job with same idempotency_key
            if idempotency_key:
                cursor = conn.execute(
                    "SELECT job_id FROM jobs WHERE idempotency_key = ?",
                    (idempotency_key,)
                )
                existing = cursor.fetchone()
                if existing:
                    return existing["job_id"]

            job_id = str(uuid.uuid4())
            now = self._now_iso()
            request_hash = self._compute_request_hash(request)
            request_blob = self._compress(request)

            # Count items
            items = request.get("items", [])
            items_total = len(items) if isinstance(items, list) else 0

            conn.execute(
                """
                INSERT INTO jobs (
                    job_id, created_at, updated_at, type, status,
                    batch_id, idempotency_key, items_total, items_done,
                    error_count, request_hash, request_blob
                ) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, 0, 0, ?, ?)
                """,
                (
                    job_id, now, now, type, batch_id, idempotency_key,
                    items_total, request_hash, request_blob
                )
            )
            conn.commit()
            return job_id
        finally:
            conn.close()

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Get job by ID.

        Args:
            job_id: Job identifier

        Returns:
            Job dictionary with request/result if status in (done, failed, cancelled)
        """
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?",
                (job_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None

            # Include blobs only for completed states
            include_blobs = row["status"] in ("done", "failed", "cancelled")
            return self._row_to_dict(row, include_blobs=include_blobs)
        finally:
            conn.close()

    def list_jobs(
        self,
        limit: int = 20,
        offset: int = 0,
        status: Optional[str] = None,
        type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        List jobs with pagination and optional filtering.

        Args:
            limit: Max results (1-100)
            offset: Pagination offset
            status: Filter by status
            type: Filter by job type

        Returns:
            Dict with items, total, limit, offset
        """
        conn = self._get_conn()
        try:
            # Build query
            conditions = []
            params = []

            if status:
                conditions.append("status = ?")
                params.append(status)
            if type:
                conditions.append("type = ?")
                params.append(type)

            where_clause = " AND ".join(conditions) if conditions else "1=1"

            # Count total
            count_cursor = conn.execute(
                f"SELECT COUNT(*) as cnt FROM jobs WHERE {where_clause}",
                params
            )
            total = count_cursor.fetchone()["cnt"]

            # Get items
            query_params = params + [limit, offset]
            cursor = conn.execute(
                f"""
                SELECT job_id, created_at, updated_at, type, status,
                       batch_id, idempotency_key, items_total, items_done,
                       error_count, request_hash, message
                FROM jobs
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                query_params
            )

            items = [dict(row) for row in cursor.fetchall()]

            return {
                "items": items,
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        finally:
            conn.close()

    def mark_running(self, job_id: str) -> bool:
        """
        Mark job as running.

        Args:
            job_id: Job identifier

        Returns:
            True if updated, False if job not found or not pending
        """
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """
                UPDATE jobs
                SET status = 'running', updated_at = ?
                WHERE job_id = ? AND status = 'pending'
                """,
                (self._now_iso(), job_id)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def update_progress(
        self,
        job_id: str,
        items_done: int,
        error_count: int,
    ) -> bool:
        """
        Update job progress.

        Args:
            job_id: Job identifier
            items_done: Number of items completed
            error_count: Number of items with errors

        Returns:
            True if updated
        """
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """
                UPDATE jobs
                SET items_done = ?, error_count = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (items_done, error_count, self._now_iso(), job_id)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def save_result(
        self,
        job_id: str,
        result: Dict[str, Any],
        status: str = "done",
        message: Optional[str] = None,
    ) -> bool:
        """
        Save job result and update status.

        Args:
            job_id: Job identifier
            result: Result dictionary
            status: Final status (done, failed)
            message: Optional message

        Returns:
            True if updated
        """
        conn = self._get_conn()
        try:
            result_blob = self._compress(result) if result else None
            cursor = conn.execute(
                """
                UPDATE jobs
                SET status = ?, result_blob = ?, message = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (status, result_blob, message, self._now_iso(), job_id)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def cancel(self, job_id: str) -> bool:
        """
        Cancel a pending or running job.

        Args:
            job_id: Job identifier

        Returns:
            True if cancelled successfully
        """
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """
                UPDATE jobs
                SET status = 'cancelled', updated_at = ?
                WHERE job_id = ? AND status IN ('pending', 'running')
                """,
                (self._now_iso(), job_id)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def is_cancelled(self, job_id: str) -> bool:
        """
        Check if job is cancelled.

        Args:
            job_id: Job identifier

        Returns:
            True if job status is cancelled
        """
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT status FROM jobs WHERE job_id = ?",
                (job_id,)
            )
            row = cursor.fetchone()
            return row is not None and row["status"] == "cancelled"
        finally:
            conn.close()

    def claim_next_job(self, type: str = "sizing_batch") -> Optional[str]:
        """
        Atomically claim the next available job for processing.

        Claims either:
        1. A pending job that hasn't exceeded max_attempts
        2. A running job with expired lease that hasn't exceeded max_attempts

        Args:
            type: Job type to claim

        Returns:
            job_id if claimed, None if no available jobs
        """
        conn = self._get_conn()
        try:
            now = self._now_iso()
            lease_expires = (
                datetime.now(timezone.utc) + timedelta(seconds=self.lease_seconds)
            ).isoformat()

            # Try to claim a pending job first
            cursor = conn.execute(
                """
                UPDATE jobs
                SET status = 'running',
                    lease_owner = ?,
                    lease_expires_at = ?,
                    attempts = attempts + 1,
                    started_at = COALESCE(started_at, ?),
                    updated_at = ?
                WHERE job_id = (
                    SELECT job_id FROM jobs
                    WHERE type = ?
                      AND status = 'pending'
                      AND attempts < max_attempts
                    ORDER BY created_at ASC
                    LIMIT 1
                )
                RETURNING job_id
                """,
                (self.worker_id, lease_expires, now, now, type)
            )
            row = cursor.fetchone()
            if row:
                conn.commit()
                return row["job_id"]

            # Try to reclaim a running job with expired lease
            cursor = conn.execute(
                """
                UPDATE jobs
                SET lease_owner = ?,
                    lease_expires_at = ?,
                    attempts = attempts + 1,
                    updated_at = ?
                WHERE job_id = (
                    SELECT job_id FROM jobs
                    WHERE type = ?
                      AND status = 'running'
                      AND lease_expires_at < ?
                      AND attempts < max_attempts
                    ORDER BY lease_expires_at ASC
                    LIMIT 1
                )
                RETURNING job_id
                """,
                (self.worker_id, lease_expires, now, type, now)
            )
            row = cursor.fetchone()
            if row:
                conn.commit()
                return row["job_id"]

            conn.commit()
            return None
        finally:
            conn.close()

    def claim_next_pending_job(self, type: str = "sizing_batch") -> Optional[str]:
        """
        Legacy method - use claim_next_job() instead.

        Kept for backward compatibility.
        """
        return self.claim_next_job(type)

    def renew_lease(self, job_id: str) -> bool:
        """
        Renew the lease on a running job (heartbeat).

        Args:
            job_id: Job identifier

        Returns:
            True if lease renewed, False if job not found or not owned by this worker
        """
        conn = self._get_conn()
        try:
            now = self._now_iso()
            lease_expires = (
                datetime.now(timezone.utc) + timedelta(seconds=self.lease_seconds)
            ).isoformat()

            cursor = conn.execute(
                """
                UPDATE jobs
                SET lease_expires_at = ?, updated_at = ?
                WHERE job_id = ?
                  AND status = 'running'
                  AND lease_owner = ?
                """,
                (lease_expires, now, job_id, self.worker_id)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def mark_done(self, job_id: str, result: Dict[str, Any]) -> bool:
        """
        Mark job as done with result.

        Args:
            job_id: Job identifier
            result: Result dictionary

        Returns:
            True if updated
        """
        conn = self._get_conn()
        try:
            now = self._now_iso()
            result_blob = self._compress(result) if result else None

            cursor = conn.execute(
                """
                UPDATE jobs
                SET status = 'done',
                    result_blob = ?,
                    finished_at = ?,
                    updated_at = ?,
                    lease_owner = NULL,
                    lease_expires_at = NULL
                WHERE job_id = ?
                """,
                (result_blob, now, now, job_id)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def mark_failed(self, job_id: str, last_error: str) -> bool:
        """
        Mark job as failed with error message.

        Args:
            job_id: Job identifier
            last_error: Error message

        Returns:
            True if updated
        """
        conn = self._get_conn()
        try:
            now = self._now_iso()

            cursor = conn.execute(
                """
                UPDATE jobs
                SET status = 'failed',
                    last_error = ?,
                    finished_at = ?,
                    updated_at = ?,
                    lease_owner = NULL,
                    lease_expires_at = NULL
                WHERE job_id = ?
                """,
                (last_error, now, now, job_id)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def mark_cancelled(self, job_id: str) -> bool:
        """
        Mark job as cancelled.

        Args:
            job_id: Job identifier

        Returns:
            True if updated
        """
        conn = self._get_conn()
        try:
            now = self._now_iso()

            cursor = conn.execute(
                """
                UPDATE jobs
                SET status = 'cancelled',
                    finished_at = ?,
                    updated_at = ?,
                    lease_owner = NULL,
                    lease_expires_at = NULL
                WHERE job_id = ? AND status IN ('pending', 'running')
                """,
                (now, now, job_id)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def force_set_lease_expired(self, job_id: str) -> bool:
        """
        Force-expire lease for testing purposes.

        This is a test helper method to simulate lease expiration.

        Args:
            job_id: Job identifier

        Returns:
            True if updated
        """
        conn = self._get_conn()
        try:
            expired_time = (
                datetime.now(timezone.utc) - timedelta(seconds=1)
            ).isoformat()

            cursor = conn.execute(
                """
                UPDATE jobs
                SET lease_expires_at = ?
                WHERE job_id = ?
                """,
                (expired_time, job_id)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def prune_old_jobs(self, retention_days: int) -> int:
        """
        Delete jobs older than retention period.

        Args:
            retention_days: Number of days to keep

        Returns:
            Number of deleted jobs
        """
        conn = self._get_conn()
        try:
            from datetime import timedelta
            cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
            cutoff_str = cutoff.isoformat()

            cursor = conn.execute(
                "DELETE FROM jobs WHERE created_at < ?",
                (cutoff_str,)
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    def count_by_status(self) -> Dict[str, int]:
        """
        Count jobs by status.

        Returns:
            Dict mapping status to count
        """
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM jobs GROUP BY status"
            )
            return {row["status"]: row["cnt"] for row in cursor.fetchall()}
        finally:
            conn.close()


# -----------------------------------------------------------------------------
# Global instance (lazy initialization)
# -----------------------------------------------------------------------------

_job_store: Optional[JobStore] = None


def get_job_store() -> JobStore:
    """Get or create global JobStore instance."""
    global _job_store
    if _job_store is None:
        _job_store = JobStore()
    return _job_store


# -----------------------------------------------------------------------------
# Convenience functions
# -----------------------------------------------------------------------------

def create_job(
    type: str,
    request: Dict[str, Any],
    batch_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> str:
    """Create a new job."""
    return get_job_store().create_job(type, request, batch_id, idempotency_key)


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Get job by ID."""
    return get_job_store().get_job(job_id)


def list_jobs(
    limit: int = 20,
    offset: int = 0,
    status: Optional[str] = None,
    type: Optional[str] = None,
) -> Dict[str, Any]:
    """List jobs with pagination."""
    return get_job_store().list_jobs(limit, offset, status, type)


def mark_running(job_id: str) -> bool:
    """Mark job as running."""
    return get_job_store().mark_running(job_id)


def update_progress(job_id: str, items_done: int, error_count: int) -> bool:
    """Update job progress."""
    return get_job_store().update_progress(job_id, items_done, error_count)


def save_result(
    job_id: str,
    result: Dict[str, Any],
    status: str = "done",
    message: Optional[str] = None,
) -> bool:
    """Save job result."""
    return get_job_store().save_result(job_id, result, status, message)


def cancel_job(job_id: str) -> bool:
    """Cancel a job."""
    return get_job_store().cancel(job_id)


def is_cancelled(job_id: str) -> bool:
    """Check if job is cancelled."""
    return get_job_store().is_cancelled(job_id)


def claim_next_pending_job(type: str = "sizing_batch") -> Optional[str]:
    """Claim next pending job (legacy, use claim_next_job)."""
    return get_job_store().claim_next_pending_job(type)


def claim_next_job(type: str = "sizing_batch") -> Optional[str]:
    """Claim next available job with lease."""
    return get_job_store().claim_next_job(type)


def renew_lease(job_id: str) -> bool:
    """Renew lease on a running job."""
    return get_job_store().renew_lease(job_id)


def mark_done(job_id: str, result: Dict[str, Any]) -> bool:
    """Mark job as done with result."""
    return get_job_store().mark_done(job_id, result)


def mark_failed(job_id: str, last_error: str) -> bool:
    """Mark job as failed with error."""
    return get_job_store().mark_failed(job_id, last_error)


def mark_cancelled(job_id: str) -> bool:
    """Mark job as cancelled."""
    return get_job_store().mark_cancelled(job_id)


def prune_old_jobs(retention_days: int) -> int:
    """Prune old jobs."""
    return get_job_store().prune_old_jobs(retention_days)

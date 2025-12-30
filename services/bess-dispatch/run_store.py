"""
RunStore - SQLite-backed persistence for sizing runs (v1.0.0)
=============================================================

Provides audit trail and run registry for sizing operations:
- Auto-save sizing runs with request/response blobs (zlib-compressed)
- GET run by run_id
- List/search runs by request_hash, created_at, endpoint
- Retention pruning (configurable via RUN_STORE_RETENTION_DAYS)

Environment Variables:
- RUN_STORE_PATH: Path to SQLite database (default: /data/runs.sqlite)
- RUN_STORE_ENABLED: Enable/disable run store (default: true)
- RUN_STORE_RETENTION_DAYS: Days to keep runs (default: 30)
"""

import json
import os
import sqlite3
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# Configuration from environment
RUN_STORE_PATH = os.getenv("RUN_STORE_PATH", "/data/runs.sqlite")
RUN_STORE_ENABLED = os.getenv("RUN_STORE_ENABLED", "true").lower() in ("true", "1", "yes")
RUN_STORE_RETENTION_DAYS = int(os.getenv("RUN_STORE_RETENTION_DAYS", "30"))


def _compress_json(data: Dict[str, Any]) -> bytes:
    """Compress dict to zlib-compressed JSON bytes."""
    json_str = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    return zlib.compress(json_str.encode("utf-8"))


def _decompress_json(data: bytes) -> Dict[str, Any]:
    """Decompress zlib-compressed JSON bytes to dict."""
    json_str = zlib.decompress(data).decode("utf-8")
    return json.loads(json_str)


class RunStore:
    """
    SQLite-backed run store for audit trail.

    Table schema:
    - run_id: TEXT PRIMARY KEY
    - request_hash: TEXT (indexed)
    - created_at: TEXT ISO 8601 (indexed)
    - endpoint: TEXT (e.g., "sizing", "dispatch", "batch.sizing")
    - status: TEXT ("ok" or "error")
    - cache_hit: INTEGER (0/1)
    - schema_version: TEXT
    - assumptions_version: TEXT
    - compute_time_ms: INTEGER
    - request_blob: BLOB (zlib-compressed JSON)
    - response_blob: BLOB (zlib-compressed JSON)
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize RunStore.

        Args:
            db_path: Path to SQLite database. Defaults to RUN_STORE_PATH env var.
        """
        self.db_path = db_path or RUN_STORE_PATH
        self._ensure_db()

    def _ensure_db(self):
        """Create database and tables if they don't exist."""
        # Ensure directory exists
        db_dir = Path(self.db_path).parent
        if not db_dir.exists():
            db_dir.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    request_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    status TEXT NOT NULL,
                    cache_hit INTEGER NOT NULL DEFAULT 0,
                    schema_version TEXT,
                    assumptions_version TEXT,
                    compute_time_ms INTEGER,
                    request_blob BLOB NOT NULL,
                    response_blob BLOB NOT NULL
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_runs_request_hash
                ON runs(request_hash)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_runs_created_at
                ON runs(created_at DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_runs_endpoint
                ON runs(endpoint)
            """)
            conn.commit()
        finally:
            conn.close()

    def save(
        self,
        run_id: str,
        request_hash: str,
        endpoint: str,
        status: str,
        cache_hit: bool,
        schema_version: Optional[str],
        assumptions_version: Optional[str],
        compute_time_ms: int,
        request: Dict[str, Any],
        response: Dict[str, Any],
        created_at: Optional[str] = None,
    ) -> None:
        """
        Save a run to the store.

        Args:
            run_id: Unique run identifier (UUID)
            request_hash: SHA-256 hash of request
            endpoint: API endpoint (e.g., "sizing")
            status: "ok" or "error"
            cache_hit: Whether this was a cache hit
            schema_version: API schema version
            assumptions_version: Assumptions hash
            compute_time_ms: Computation time in milliseconds
            request: Request payload dict
            response: Response payload dict
            created_at: ISO 8601 timestamp (defaults to now)
        """
        if created_at is None:
            created_at = datetime.now(timezone.utc).isoformat()

        request_blob = _compress_json(request)
        response_blob = _compress_json(response)

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO runs (
                    run_id, request_hash, created_at, endpoint, status,
                    cache_hit, schema_version, assumptions_version,
                    compute_time_ms, request_blob, response_blob
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run_id, request_hash, created_at, endpoint, status,
                1 if cache_hit else 0, schema_version, assumptions_version,
                compute_time_ms, request_blob, response_blob,
            ))
            conn.commit()
        finally:
            conn.close()

    def get(self, run_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a run by run_id.

        Args:
            run_id: Run identifier

        Returns:
            Dict with run details including decompressed request/response,
            or None if not found
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT run_id, request_hash, created_at, endpoint, status,
                       cache_hit, schema_version, assumptions_version,
                       compute_time_ms, request_blob, response_blob
                FROM runs WHERE run_id = ?
            """, (run_id,))
            row = cursor.fetchone()
            if row is None:
                return None

            return {
                "run_id": row[0],
                "request_hash": row[1],
                "created_at": row[2],
                "endpoint": row[3],
                "status": row[4],
                "cache_hit": bool(row[5]),
                "schema_version": row[6],
                "assumptions_version": row[7],
                "compute_time_ms": row[8],
                "request": _decompress_json(row[9]),
                "response": _decompress_json(row[10]),
            }
        finally:
            conn.close()

    def list(
        self,
        limit: int = 20,
        offset: int = 0,
        request_hash: Optional[str] = None,
        endpoint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        List runs with optional filtering.

        Args:
            limit: Max results to return (default 20)
            offset: Offset for pagination (default 0)
            request_hash: Filter by request hash
            endpoint: Filter by endpoint

        Returns:
            Dict with items list and pagination info
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Build WHERE clause
            conditions = []
            params: List[Any] = []
            if request_hash:
                conditions.append("request_hash = ?")
                params.append(request_hash)
            if endpoint:
                conditions.append("endpoint = ?")
                params.append(endpoint)

            where_clause = ""
            if conditions:
                where_clause = "WHERE " + " AND ".join(conditions)

            # Get total count
            cursor.execute(f"SELECT COUNT(*) FROM runs {where_clause}", params)
            total = cursor.fetchone()[0]

            # Get items (without blobs for efficiency)
            query = f"""
                SELECT run_id, request_hash, created_at, endpoint, status, cache_hit
                FROM runs {where_clause}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """
            cursor.execute(query, params + [limit, offset])

            items = []
            for row in cursor.fetchall():
                items.append({
                    "run_id": row[0],
                    "request_hash": row[1],
                    "created_at": row[2],
                    "endpoint": row[3],
                    "status": row[4],
                    "cache_hit": bool(row[5]),
                })

            return {
                "items": items,
                "limit": limit,
                "offset": offset,
                "total": total,
            }
        finally:
            conn.close()

    def prune(self, retention_days: Optional[int] = None) -> int:
        """
        Delete runs older than retention period.

        Args:
            retention_days: Days to keep (defaults to RUN_STORE_RETENTION_DAYS)

        Returns:
            Number of runs deleted
        """
        if retention_days is None:
            retention_days = RUN_STORE_RETENTION_DAYS

        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        cutoff_str = cutoff.isoformat()

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM runs WHERE created_at < ?",
                (cutoff_str,)
            )
            deleted = cursor.rowcount
            conn.commit()
            return deleted
        finally:
            conn.close()

    def count(self) -> int:
        """Get total number of runs in store."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM runs")
            return cursor.fetchone()[0]
        finally:
            conn.close()

    def _insert_raw(
        self,
        run_id: str,
        request_hash: str,
        created_at: str,
        endpoint: str,
        status: str,
        cache_hit: bool,
        schema_version: Optional[str],
        assumptions_version: Optional[str],
        compute_time_ms: int,
        request: Dict[str, Any],
        response: Dict[str, Any],
    ) -> None:
        """
        Insert run with explicit created_at (for testing).

        Same as save() but created_at is required.
        """
        self.save(
            run_id=run_id,
            request_hash=request_hash,
            endpoint=endpoint,
            status=status,
            cache_hit=cache_hit,
            schema_version=schema_version,
            assumptions_version=assumptions_version,
            compute_time_ms=compute_time_ms,
            request=request,
            response=response,
            created_at=created_at,
        )


# Global instance (lazy initialization)
_run_store: Optional[RunStore] = None


def get_run_store() -> RunStore:
    """Get or create the global RunStore instance."""
    global _run_store
    if _run_store is None:
        _run_store = RunStore()
    return _run_store


def save_run(
    run_id: str,
    request_hash: str,
    endpoint: str,
    status: str,
    cache_hit: bool,
    schema_version: Optional[str],
    assumptions_version: Optional[str],
    compute_time_ms: int,
    request: Dict[str, Any],
    response: Dict[str, Any],
) -> None:
    """
    Save a run using the global store.

    No-op if RUN_STORE_ENABLED is False.
    """
    if not RUN_STORE_ENABLED:
        return
    get_run_store().save(
        run_id=run_id,
        request_hash=request_hash,
        endpoint=endpoint,
        status=status,
        cache_hit=cache_hit,
        schema_version=schema_version,
        assumptions_version=assumptions_version,
        compute_time_ms=compute_time_ms,
        request=request,
        response=response,
    )


def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    """Get a run by run_id using the global store."""
    if not RUN_STORE_ENABLED:
        return None
    return get_run_store().get(run_id)


def list_runs(
    limit: int = 20,
    offset: int = 0,
    request_hash: Optional[str] = None,
    endpoint: Optional[str] = None,
) -> Dict[str, Any]:
    """List runs using the global store."""
    if not RUN_STORE_ENABLED:
        return {"items": [], "limit": limit, "offset": offset, "total": 0}
    return get_run_store().list(
        limit=limit,
        offset=offset,
        request_hash=request_hash,
        endpoint=endpoint,
    )


def prune_runs(retention_days: Optional[int] = None) -> int:
    """Prune old runs using the global store."""
    if not RUN_STORE_ENABLED:
        return 0
    return get_run_store().prune(retention_days)

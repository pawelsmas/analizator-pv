"""
RunStore - SQLite-backed persistence for sizing runs (v1.3.0)
=============================================================

Provides audit trail and run registry for sizing operations:
- Auto-save sizing runs with request/response blobs (zlib-compressed)
- GET run by run_id
- List/search runs by request_hash, created_at, endpoint
- Retention pruning (configurable via RUN_STORE_RETENTION_DAYS)
- Metadata updates: label, tags, notes (v1.3.0)

Environment Variables:
- RUN_STORE_PATH: Path to SQLite database (default: /data/runs.sqlite)
- RUN_STORE_ENABLED: Enable/disable run store (default: true)
- RUN_STORE_RETENTION_DAYS: Days to keep runs (default: 30)
"""

import json
import os
import re
import sqlite3
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# =============================================================================
# Validation constants for metadata (v1.3.0)
# =============================================================================
MAX_TAGS = 20
MAX_TAG_LENGTH = 32
TAG_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
MAX_LABEL_LENGTH = 80
MAX_NOTES_LENGTH = 2000


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


def validate_tags(tags: Optional[List[str]]) -> None:
    """
    Validate tags list for metadata.

    Args:
        tags: List of tag strings

    Raises:
        ValueError: If validation fails
    """
    if tags is None:
        return
    if not isinstance(tags, list):
        raise ValueError("tags must be a list")
    if len(tags) > MAX_TAGS:
        raise ValueError(f"Maximum {MAX_TAGS} tags allowed, got {len(tags)}")
    for tag in tags:
        if not isinstance(tag, str):
            raise ValueError(f"Tag must be a string, got {type(tag).__name__}")
        if not tag or len(tag) > MAX_TAG_LENGTH:
            raise ValueError(f"Tag must be 1-{MAX_TAG_LENGTH} chars, got {len(tag)}")
        if not TAG_PATTERN.match(tag):
            raise ValueError(f"Tag '{tag}' contains invalid characters. Only [a-zA-Z0-9_-] allowed")


def validate_label(label: Optional[str]) -> None:
    """
    Validate label string for metadata.

    Args:
        label: Label string

    Raises:
        ValueError: If validation fails
    """
    if label is None:
        return
    if not isinstance(label, str):
        raise ValueError(f"label must be a string, got {type(label).__name__}")
    if len(label) > MAX_LABEL_LENGTH:
        raise ValueError(f"label must be max {MAX_LABEL_LENGTH} chars, got {len(label)}")


def validate_notes(notes: Optional[str]) -> None:
    """
    Validate notes string for metadata.

    Args:
        notes: Notes string

    Raises:
        ValueError: If validation fails
    """
    if notes is None:
        return
    if not isinstance(notes, str):
        raise ValueError(f"notes must be a string, got {type(notes).__name__}")
    if len(notes) > MAX_NOTES_LENGTH:
        raise ValueError(f"notes must be max {MAX_NOTES_LENGTH} chars, got {len(notes)}")


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
    - label: TEXT (v1.3.0 - optional label for run)
    - tags_json: TEXT (v1.3.0 - JSON array of tags)
    - notes: TEXT (v1.3.0 - optional notes)
    - updated_at: TEXT (v1.3.0 - last metadata update timestamp)
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize RunStore.

        Args:
            db_path: Path to SQLite database. Defaults to RUN_STORE_PATH env var.
        """
        self.db_path = db_path or RUN_STORE_PATH
        self._ensure_db()
        self._migrate_add_metadata_columns()

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

    def _migrate_add_metadata_columns(self):
        """Add v1.3.0 metadata columns if they don't exist."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            # Check existing columns
            cursor.execute("PRAGMA table_info(runs)")
            existing_columns = {row[1] for row in cursor.fetchall()}

            # Add missing columns
            if "label" not in existing_columns:
                cursor.execute("ALTER TABLE runs ADD COLUMN label TEXT")
            if "tags_json" not in existing_columns:
                cursor.execute("ALTER TABLE runs ADD COLUMN tags_json TEXT")
            if "notes" not in existing_columns:
                cursor.execute("ALTER TABLE runs ADD COLUMN notes TEXT")
            if "updated_at" not in existing_columns:
                cursor.execute("ALTER TABLE runs ADD COLUMN updated_at TEXT")
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
                       compute_time_ms, request_blob, response_blob,
                       label, tags_json, notes, updated_at
                FROM runs WHERE run_id = ?
            """, (run_id,))
            row = cursor.fetchone()
            if row is None:
                return None

            # Parse tags from JSON
            tags = None
            if row[12]:
                try:
                    tags = json.loads(row[12])
                except json.JSONDecodeError:
                    tags = None

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
                "label": row[11],
                "tags": tags,
                "notes": row[13],
                "updated_at": row[14],
            }
        finally:
            conn.close()

    def list(
        self,
        limit: int = 20,
        offset: int = 0,
        request_hash: Optional[str] = None,
        endpoint: Optional[str] = None,
        tag: Optional[str] = None,
        q: Optional[str] = None,
        sort: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        List runs with optional filtering and sorting (v1.3.0).

        Args:
            limit: Max results to return (default 20)
            offset: Offset for pagination (default 0)
            request_hash: Filter by request hash
            endpoint: Filter by endpoint
            tag: Filter by tag (exact match in tags_json array)
            q: Free-text search in label and notes
            sort: Sort order (created_at_asc, created_at_desc, updated_at_desc)

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
            if tag:
                # Search for tag in JSON array using LIKE pattern
                # This matches "tag" as a complete item in the JSON array
                conditions.append("(tags_json LIKE ? OR tags_json LIKE ? OR tags_json LIKE ? OR tags_json LIKE ?)")
                params.append(f'["{tag}"]')  # Only tag: ["tag"]
                params.append(f'["{tag}",%')  # First tag: ["tag", ...]
                params.append(f'%,"{tag}"]')  # Last tag: [..., "tag"]
                params.append(f'%,"{tag}",%')  # Middle tag: [..., "tag", ...]
            if q:
                # Free-text search in label and notes (case-insensitive)
                conditions.append("(LOWER(label) LIKE ? OR LOWER(notes) LIKE ?)")
                search_pattern = f"%{q.lower()}%"
                params.append(search_pattern)
                params.append(search_pattern)

            where_clause = ""
            if conditions:
                where_clause = "WHERE " + " AND ".join(conditions)

            # Determine sort order
            sort_mapping = {
                "created_at_asc": "created_at ASC",
                "created_at_desc": "created_at DESC",
                "updated_at_desc": "updated_at DESC",
            }
            order_by = sort_mapping.get(sort, "created_at DESC")  # Default: newest first

            # Get total count
            cursor.execute(f"SELECT COUNT(*) FROM runs {where_clause}", params)
            total = cursor.fetchone()[0]

            # Get items (without blobs for efficiency, include metadata)
            query = f"""
                SELECT run_id, request_hash, created_at, endpoint, status, cache_hit,
                       label, tags_json, notes, updated_at
                FROM runs {where_clause}
                ORDER BY {order_by}
                LIMIT ? OFFSET ?
            """
            cursor.execute(query, params + [limit, offset])

            items = []
            for row in cursor.fetchall():
                # Parse tags from JSON
                tags = None
                if row[7]:
                    try:
                        tags = json.loads(row[7])
                    except json.JSONDecodeError:
                        tags = None

                items.append({
                    "run_id": row[0],
                    "request_hash": row[1],
                    "created_at": row[2],
                    "endpoint": row[3],
                    "status": row[4],
                    "cache_hit": bool(row[5]),
                    "label": row[6],
                    "tags": tags,
                    "notes": row[8],
                    "updated_at": row[9],
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

    def update_metadata(
        self,
        run_id: str,
        label: Optional[str] = None,
        tags: Optional[List[str]] = None,
        notes: Optional[str] = None,
    ) -> bool:
        """
        Update metadata fields for a run (v1.3.0).

        Args:
            run_id: Run identifier
            label: New label (max 80 chars). Pass None to not update.
            tags: New tags list (max 20 tags, each 1-32 chars [a-zA-Z0-9_-]).
                  Pass None to not update, pass empty list to clear.
            notes: New notes (max 2000 chars). Pass None to not update.

        Returns:
            True if run was found and updated, False if run_id not found.

        Raises:
            ValueError: If validation fails
        """
        # Validate inputs
        validate_label(label)
        validate_tags(tags)
        validate_notes(notes)

        # Build UPDATE statement dynamically
        set_parts = []
        params: List[Any] = []

        if label is not None:
            set_parts.append("label = ?")
            params.append(label if label else None)  # Empty string -> NULL
        if tags is not None:
            set_parts.append("tags_json = ?")
            params.append(json.dumps(tags) if tags else None)  # Empty list -> NULL
        if notes is not None:
            set_parts.append("notes = ?")
            params.append(notes if notes else None)  # Empty string -> NULL

        if not set_parts:
            # Nothing to update
            return self.get(run_id) is not None

        # Always update updated_at
        set_parts.append("updated_at = ?")
        params.append(datetime.now(timezone.utc).isoformat())

        params.append(run_id)  # For WHERE clause

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE runs SET {', '.join(set_parts)} WHERE run_id = ?",
                params
            )
            conn.commit()
            return cursor.rowcount > 0
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
    tag: Optional[str] = None,
    q: Optional[str] = None,
    sort: Optional[str] = None,
) -> Dict[str, Any]:
    """List runs using the global store (v1.3.0).

    Args:
        limit: Max results to return (default 20)
        offset: Offset for pagination (default 0)
        request_hash: Filter by request hash
        endpoint: Filter by endpoint
        tag: Filter by tag (exact match)
        q: Free-text search in label and notes
        sort: Sort order (created_at_asc, created_at_desc, updated_at_desc)
    """
    if not RUN_STORE_ENABLED:
        return {"items": [], "limit": limit, "offset": offset, "total": 0}
    return get_run_store().list(
        limit=limit,
        offset=offset,
        request_hash=request_hash,
        endpoint=endpoint,
        tag=tag,
        q=q,
        sort=sort,
    )


def prune_runs(retention_days: Optional[int] = None) -> int:
    """Prune old runs using the global store."""
    if not RUN_STORE_ENABLED:
        return 0
    return get_run_store().prune(retention_days)


def update_run_metadata(
    run_id: str,
    label: Optional[str] = None,
    tags: Optional[List[str]] = None,
    notes: Optional[str] = None,
) -> bool:
    """
    Update metadata for a run using the global store.

    Args:
        run_id: Run identifier
        label: New label (max 80 chars)
        tags: New tags list (max 20, each 1-32 chars [a-zA-Z0-9_-])
        notes: New notes (max 2000 chars)

    Returns:
        True if run was found and updated, False if not found

    Raises:
        ValueError: If validation fails
        RuntimeError: If run store is disabled
    """
    if not RUN_STORE_ENABLED:
        raise RuntimeError("Run store is disabled")
    return get_run_store().update_metadata(
        run_id=run_id,
        label=label,
        tags=tags,
        notes=notes,
    )

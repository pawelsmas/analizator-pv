"""
RunStore Backend Abstraction (v3.6.0).

Provides pluggable backends for run/job payload storage:
- filesystem: SQLite-based storage (default, single replica)
- db: PostgreSQL/SQLite JSONB storage (HA, multi-replica)

Configuration:
- RUNSTORE_BACKEND: filesystem|db (default: filesystem)
- RUNSTORE_DB_URL: Database URL for db backend
- RUNSTORE_DB_COMPRESS: Compress payloads in DB (default: false)

For true HA (multi-replica without shared disk), use db backend.
"""

import json
import os
import zlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

RUNSTORE_BACKEND = os.getenv("RUNSTORE_BACKEND", "filesystem").lower()
RUNSTORE_DB_URL = os.getenv("RUNSTORE_DB_URL", os.getenv("DATABASE_URL", ""))
RUNSTORE_DB_COMPRESS = os.getenv("RUNSTORE_DB_COMPRESS", "false").lower() in ("true", "1", "yes")

# JobStore uses same backend configuration
JOBSTORE_BACKEND = os.getenv("JOBSTORE_BACKEND", RUNSTORE_BACKEND).lower()


# -----------------------------------------------------------------------------
# Data Models
# -----------------------------------------------------------------------------

@dataclass
class RunPayload:
    """Run payload data for storage."""
    run_id: str
    tenant_id: str
    created_at: str
    request_json: Dict[str, Any]
    response_json: Dict[str, Any]
    meta_json: Optional[Dict[str, Any]] = None


@dataclass
class JobPayload:
    """Job payload data for storage."""
    job_id: str
    tenant_id: str
    created_at: str
    payload_json: Dict[str, Any]
    result_json: Optional[Dict[str, Any]] = None
    error_json: Optional[Dict[str, Any]] = None


# -----------------------------------------------------------------------------
# Backend Interface
# -----------------------------------------------------------------------------

class RunPayloadBackend(ABC):
    """Abstract base class for run payload storage backends."""

    @abstractmethod
    def save_run(self, payload: RunPayload) -> None:
        """
        Save or update run payload (upsert).

        Args:
            payload: RunPayload to save
        """
        pass

    @abstractmethod
    def get_run(self, run_id: str, tenant_id: str) -> Optional[RunPayload]:
        """
        Get run payload by ID, scoped to tenant.

        Args:
            run_id: Run identifier
            tenant_id: Tenant identifier

        Returns:
            RunPayload or None if not found
        """
        pass

    @abstractmethod
    def delete_run(self, run_id: str, tenant_id: str) -> bool:
        """
        Delete run payload.

        Args:
            run_id: Run identifier
            tenant_id: Tenant identifier

        Returns:
            True if deleted, False if not found
        """
        pass

    @abstractmethod
    def delete_runs_before(self, cutoff_date: str, tenant_id: Optional[str] = None) -> int:
        """
        Delete runs created before cutoff date.

        Args:
            cutoff_date: ISO 8601 date string
            tenant_id: Optional tenant filter

        Returns:
            Number of runs deleted
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if backend is available."""
        pass


class JobPayloadBackend(ABC):
    """Abstract base class for job payload storage backends."""

    @abstractmethod
    def save_job(self, payload: JobPayload) -> None:
        """Save or update job payload (upsert)."""
        pass

    @abstractmethod
    def get_job(self, job_id: str, tenant_id: str) -> Optional[JobPayload]:
        """Get job payload by ID, scoped to tenant."""
        pass

    @abstractmethod
    def delete_job(self, job_id: str, tenant_id: str) -> bool:
        """Delete job payload."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if backend is available."""
        pass


# -----------------------------------------------------------------------------
# Filesystem Backend (wraps existing SQLite stores)
# -----------------------------------------------------------------------------

class FilesystemRunPayloadBackend(RunPayloadBackend):
    """
    Filesystem backend using existing SQLite RunStore.

    This is a wrapper that delegates to the existing run_store module.
    Suitable for single-replica deployments.
    """

    def __init__(self):
        self._store = None

    def _get_store(self):
        """Lazy load existing RunStore."""
        if self._store is None:
            from run_store import RunStore
            self._store = RunStore()
        return self._store

    def save_run(self, payload: RunPayload) -> None:
        """Save run using existing RunStore (data already saved by RunStore.save)."""
        # The existing RunStore.save() handles this during sizing
        # This method is for backfill/migration scenarios
        pass

    def get_run(self, run_id: str, tenant_id: str) -> Optional[RunPayload]:
        """Get run from existing RunStore."""
        store = self._get_store()
        run = store.get(run_id, tenant_id=tenant_id)
        if not run:
            return None

        return RunPayload(
            run_id=run["run_id"],
            tenant_id=run.get("tenant_id", "default"),
            created_at=run["created_at"],
            request_json=run.get("request", {}),
            response_json=run.get("response", {}),
            meta_json={
                "endpoint": run.get("endpoint"),
                "status": run.get("status"),
                "cache_hit": run.get("cache_hit"),
                "schema_version": run.get("schema_version"),
                "assumptions_version": run.get("assumptions_version"),
                "compute_time_ms": run.get("compute_time_ms"),
                "label": run.get("label"),
                "tags": run.get("tags"),
                "notes": run.get("notes"),
            }
        )

    def delete_run(self, run_id: str, tenant_id: str) -> bool:
        """Delete run from existing RunStore."""
        store = self._get_store()
        return store.delete(run_id, tenant_id=tenant_id)

    def delete_runs_before(self, cutoff_date: str, tenant_id: Optional[str] = None) -> int:
        """Delete old runs using existing pruning."""
        store = self._get_store()
        # Calculate days from cutoff
        from datetime import datetime, timezone
        cutoff = datetime.fromisoformat(cutoff_date.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        days = (now - cutoff).days
        if days <= 0:
            return 0
        return store.prune_old(days)

    def is_available(self) -> bool:
        """Check if filesystem store is available."""
        try:
            self._get_store()
            return True
        except Exception:
            return False


class FilesystemJobPayloadBackend(JobPayloadBackend):
    """
    Filesystem backend using existing SQLite JobStore.

    Wrapper for existing job_store module.
    """

    def __init__(self):
        self._store = None

    def _get_store(self):
        """Lazy load existing JobStore."""
        if self._store is None:
            from job_store import JobStore
            self._store = JobStore()
        return self._store

    def save_job(self, payload: JobPayload) -> None:
        """Save job - handled by JobStore during job creation."""
        pass

    def get_job(self, job_id: str, tenant_id: str) -> Optional[JobPayload]:
        """Get job from existing JobStore."""
        store = self._get_store()
        job = store.get_job(job_id, tenant_id=tenant_id)
        if not job:
            return None

        return JobPayload(
            job_id=job["job_id"],
            tenant_id=job.get("tenant_id", "default"),
            created_at=job["created_at"],
            payload_json=job.get("request", {}),
            result_json=job.get("result"),
            error_json={"message": job.get("message")} if job.get("message") else None,
        )

    def delete_job(self, job_id: str, tenant_id: str) -> bool:
        """Delete job from existing JobStore."""
        # JobStore doesn't have per-job delete, only prune
        return False

    def is_available(self) -> bool:
        """Check if filesystem store is available."""
        try:
            self._get_store()
            return True
        except Exception:
            return False


# -----------------------------------------------------------------------------
# Database Backend (PostgreSQL/SQLite with JSONB)
# -----------------------------------------------------------------------------

class DbRunPayloadBackend(RunPayloadBackend):
    """
    Database backend for run payloads using SQLAlchemy.

    Stores request/response as JSONB (Postgres) or TEXT JSON (SQLite).
    Supports optional zlib compression.
    """

    def __init__(self, db_url: str = None, compress: bool = None):
        self.db_url = db_url or RUNSTORE_DB_URL
        self.compress = compress if compress is not None else RUNSTORE_DB_COMPRESS
        self._engine = None
        self._session_factory = None

    def _get_engine(self):
        """Get or create SQLAlchemy engine."""
        if self._engine is None:
            from sqlalchemy import create_engine
            from sqlalchemy.pool import StaticPool

            is_sqlite = self.db_url.startswith("sqlite")
            if is_sqlite:
                # SQLite: use StaticPool for test compatibility
                self._engine = create_engine(
                    self.db_url,
                    connect_args={"check_same_thread": False},
                    poolclass=StaticPool,
                )
            else:
                # PostgreSQL: use connection pooling
                self._engine = create_engine(
                    self.db_url,
                    pool_pre_ping=True,
                    pool_size=5,
                    max_overflow=10,
                )
        return self._engine

    def close(self):
        """Close database connections."""
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
            self._session_factory = None

    def _get_session(self):
        """Get a new session."""
        if self._session_factory is None:
            from sqlalchemy.orm import sessionmaker
            self._session_factory = sessionmaker(bind=self._get_engine())
        return self._session_factory()

    def _ensure_table(self):
        """Create runs_payload table if not exists."""
        from sqlalchemy import text

        engine = self._get_engine()
        is_postgres = 'postgresql' in self.db_url.lower()

        # Use JSONB for Postgres, TEXT for SQLite
        json_type = "JSONB" if is_postgres else "TEXT"

        create_sql = f"""
            CREATE TABLE IF NOT EXISTS runs_payload (
                run_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                created_at TEXT NOT NULL,
                request_json {json_type} NOT NULL,
                response_json {json_type} NOT NULL,
                meta_json {json_type}
            )
        """

        with engine.connect() as conn:
            conn.execute(text(create_sql))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_runs_payload_tenant_created
                ON runs_payload(tenant_id, created_at)
            """))
            conn.execute(text("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_payload_tenant_run
                ON runs_payload(tenant_id, run_id)
            """))
            conn.commit()

    def _encode_json(self, data: Dict[str, Any]) -> str:
        """Encode JSON, optionally with compression."""
        json_str = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        if self.compress:
            import base64
            compressed = zlib.compress(json_str.encode("utf-8"))
            return "COMPRESSED:" + base64.b64encode(compressed).decode("ascii")
        return json_str

    def _decode_json(self, data: str) -> Dict[str, Any]:
        """Decode JSON, handling compression if present."""
        if isinstance(data, dict):
            return data  # Already decoded (JSONB)
        if data.startswith("COMPRESSED:"):
            import base64
            compressed = base64.b64decode(data[11:])
            json_str = zlib.decompress(compressed).decode("utf-8")
            return json.loads(json_str)
        return json.loads(data)

    def save_run(self, payload: RunPayload) -> None:
        """Save or update run payload (upsert)."""
        from sqlalchemy import text

        self._ensure_table()
        engine = self._get_engine()
        is_postgres = 'postgresql' in self.db_url.lower()

        request_json = self._encode_json(payload.request_json)
        response_json = self._encode_json(payload.response_json)
        meta_json = self._encode_json(payload.meta_json) if payload.meta_json else None

        if is_postgres:
            # PostgreSQL upsert with ON CONFLICT
            upsert_sql = """
                INSERT INTO runs_payload (run_id, tenant_id, created_at, request_json, response_json, meta_json)
                VALUES (:run_id, :tenant_id, :created_at, :request_json::jsonb, :response_json::jsonb, :meta_json::jsonb)
                ON CONFLICT (run_id) DO UPDATE SET
                    request_json = EXCLUDED.request_json,
                    response_json = EXCLUDED.response_json,
                    meta_json = EXCLUDED.meta_json
            """
        else:
            # SQLite upsert with INSERT OR REPLACE
            upsert_sql = """
                INSERT OR REPLACE INTO runs_payload (run_id, tenant_id, created_at, request_json, response_json, meta_json)
                VALUES (:run_id, :tenant_id, :created_at, :request_json, :response_json, :meta_json)
            """

        with engine.connect() as conn:
            conn.execute(text(upsert_sql), {
                "run_id": payload.run_id,
                "tenant_id": payload.tenant_id,
                "created_at": payload.created_at,
                "request_json": request_json,
                "response_json": response_json,
                "meta_json": meta_json,
            })
            conn.commit()

    def get_run(self, run_id: str, tenant_id: str) -> Optional[RunPayload]:
        """Get run payload by ID, scoped to tenant."""
        from sqlalchemy import text

        self._ensure_table()
        engine = self._get_engine()

        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT run_id, tenant_id, created_at, request_json, response_json, meta_json
                FROM runs_payload
                WHERE run_id = :run_id AND tenant_id = :tenant_id
            """), {"run_id": run_id, "tenant_id": tenant_id})

            row = result.fetchone()
            if not row:
                return None

            return RunPayload(
                run_id=row[0],
                tenant_id=row[1],
                created_at=row[2],
                request_json=self._decode_json(row[3]),
                response_json=self._decode_json(row[4]),
                meta_json=self._decode_json(row[5]) if row[5] else None,
            )

    def delete_run(self, run_id: str, tenant_id: str) -> bool:
        """Delete run payload."""
        from sqlalchemy import text

        self._ensure_table()
        engine = self._get_engine()

        with engine.connect() as conn:
            result = conn.execute(text("""
                DELETE FROM runs_payload
                WHERE run_id = :run_id AND tenant_id = :tenant_id
            """), {"run_id": run_id, "tenant_id": tenant_id})
            conn.commit()
            return result.rowcount > 0

    def delete_runs_before(self, cutoff_date: str, tenant_id: Optional[str] = None) -> int:
        """Delete runs created before cutoff date."""
        from sqlalchemy import text

        self._ensure_table()
        engine = self._get_engine()

        if tenant_id:
            sql = """
                DELETE FROM runs_payload
                WHERE created_at < :cutoff AND tenant_id = :tenant_id
            """
            params = {"cutoff": cutoff_date, "tenant_id": tenant_id}
        else:
            sql = "DELETE FROM runs_payload WHERE created_at < :cutoff"
            params = {"cutoff": cutoff_date}

        with engine.connect() as conn:
            result = conn.execute(text(sql), params)
            conn.commit()
            return result.rowcount

    def is_available(self) -> bool:
        """Check if database is available."""
        if not self.db_url:
            return False
        try:
            from sqlalchemy import text
            engine = self._get_engine()
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False


class DbJobPayloadBackend(JobPayloadBackend):
    """
    Database backend for job payloads using SQLAlchemy.

    Similar structure to DbRunPayloadBackend.
    """

    def __init__(self, db_url: str = None, compress: bool = None):
        self.db_url = db_url or RUNSTORE_DB_URL
        self.compress = compress if compress is not None else RUNSTORE_DB_COMPRESS
        self._engine = None

    def _get_engine(self):
        """Get or create SQLAlchemy engine."""
        if self._engine is None:
            from sqlalchemy import create_engine
            from sqlalchemy.pool import StaticPool

            is_sqlite = self.db_url.startswith("sqlite")
            if is_sqlite:
                # SQLite: use StaticPool for test compatibility
                self._engine = create_engine(
                    self.db_url,
                    connect_args={"check_same_thread": False},
                    poolclass=StaticPool,
                )
            else:
                # PostgreSQL: use connection pooling
                self._engine = create_engine(
                    self.db_url,
                    pool_pre_ping=True,
                    pool_size=5,
                    max_overflow=10,
                )
        return self._engine

    def close(self):
        """Close database connections."""
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None

    def _ensure_table(self):
        """Create jobs_payload table if not exists."""
        from sqlalchemy import text

        engine = self._get_engine()
        is_postgres = 'postgresql' in self.db_url.lower()
        json_type = "JSONB" if is_postgres else "TEXT"

        create_sql = f"""
            CREATE TABLE IF NOT EXISTS jobs_payload (
                job_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                created_at TEXT NOT NULL,
                payload_json {json_type} NOT NULL,
                result_json {json_type},
                error_json {json_type}
            )
        """

        with engine.connect() as conn:
            conn.execute(text(create_sql))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_jobs_payload_tenant_created
                ON jobs_payload(tenant_id, created_at)
            """))
            conn.commit()

    def _encode_json(self, data: Dict[str, Any]) -> str:
        """Encode JSON, optionally with compression."""
        if data is None:
            return None
        json_str = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        if self.compress:
            import base64
            compressed = zlib.compress(json_str.encode("utf-8"))
            return "COMPRESSED:" + base64.b64encode(compressed).decode("ascii")
        return json_str

    def _decode_json(self, data: str) -> Optional[Dict[str, Any]]:
        """Decode JSON, handling compression if present."""
        if data is None:
            return None
        if isinstance(data, dict):
            return data
        if data.startswith("COMPRESSED:"):
            import base64
            compressed = base64.b64decode(data[11:])
            json_str = zlib.decompress(compressed).decode("utf-8")
            return json.loads(json_str)
        return json.loads(data)

    def save_job(self, payload: JobPayload) -> None:
        """Save or update job payload (upsert)."""
        from sqlalchemy import text

        self._ensure_table()
        engine = self._get_engine()
        is_postgres = 'postgresql' in self.db_url.lower()

        payload_json = self._encode_json(payload.payload_json)
        result_json = self._encode_json(payload.result_json)
        error_json = self._encode_json(payload.error_json)

        if is_postgres:
            upsert_sql = """
                INSERT INTO jobs_payload (job_id, tenant_id, created_at, payload_json, result_json, error_json)
                VALUES (:job_id, :tenant_id, :created_at, :payload_json::jsonb, :result_json::jsonb, :error_json::jsonb)
                ON CONFLICT (job_id) DO UPDATE SET
                    payload_json = EXCLUDED.payload_json,
                    result_json = EXCLUDED.result_json,
                    error_json = EXCLUDED.error_json
            """
        else:
            upsert_sql = """
                INSERT OR REPLACE INTO jobs_payload (job_id, tenant_id, created_at, payload_json, result_json, error_json)
                VALUES (:job_id, :tenant_id, :created_at, :payload_json, :result_json, :error_json)
            """

        with engine.connect() as conn:
            conn.execute(text(upsert_sql), {
                "job_id": payload.job_id,
                "tenant_id": payload.tenant_id,
                "created_at": payload.created_at,
                "payload_json": payload_json,
                "result_json": result_json,
                "error_json": error_json,
            })
            conn.commit()

    def get_job(self, job_id: str, tenant_id: str) -> Optional[JobPayload]:
        """Get job payload by ID, scoped to tenant."""
        from sqlalchemy import text

        self._ensure_table()
        engine = self._get_engine()

        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT job_id, tenant_id, created_at, payload_json, result_json, error_json
                FROM jobs_payload
                WHERE job_id = :job_id AND tenant_id = :tenant_id
            """), {"job_id": job_id, "tenant_id": tenant_id})

            row = result.fetchone()
            if not row:
                return None

            return JobPayload(
                job_id=row[0],
                tenant_id=row[1],
                created_at=row[2],
                payload_json=self._decode_json(row[3]),
                result_json=self._decode_json(row[4]),
                error_json=self._decode_json(row[5]),
            )

    def delete_job(self, job_id: str, tenant_id: str) -> bool:
        """Delete job payload."""
        from sqlalchemy import text

        self._ensure_table()
        engine = self._get_engine()

        with engine.connect() as conn:
            result = conn.execute(text("""
                DELETE FROM jobs_payload
                WHERE job_id = :job_id AND tenant_id = :tenant_id
            """), {"job_id": job_id, "tenant_id": tenant_id})
            conn.commit()
            return result.rowcount > 0

    def is_available(self) -> bool:
        """Check if database is available."""
        if not self.db_url:
            return False
        try:
            from sqlalchemy import text
            engine = self._get_engine()
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False


# -----------------------------------------------------------------------------
# Backend Factory
# -----------------------------------------------------------------------------

_run_backend_instance: Optional[RunPayloadBackend] = None
_job_backend_instance: Optional[JobPayloadBackend] = None


def get_run_payload_backend() -> RunPayloadBackend:
    """
    Get or create run payload backend based on configuration.

    Returns:
        RunPayloadBackend instance
    """
    global _run_backend_instance

    if _run_backend_instance is not None:
        return _run_backend_instance

    if RUNSTORE_BACKEND == "db":
        db_backend = DbRunPayloadBackend()
        if db_backend.is_available():
            _run_backend_instance = db_backend
        else:
            import logging
            logging.getLogger("runstore").warning(
                "Database unavailable for runstore, falling back to filesystem"
            )
            _run_backend_instance = FilesystemRunPayloadBackend()
    else:
        _run_backend_instance = FilesystemRunPayloadBackend()

    return _run_backend_instance


def get_job_payload_backend() -> JobPayloadBackend:
    """
    Get or create job payload backend based on configuration.

    Returns:
        JobPayloadBackend instance
    """
    global _job_backend_instance

    if _job_backend_instance is not None:
        return _job_backend_instance

    if JOBSTORE_BACKEND == "db":
        db_backend = DbJobPayloadBackend()
        if db_backend.is_available():
            _job_backend_instance = db_backend
        else:
            import logging
            logging.getLogger("jobstore").warning(
                "Database unavailable for jobstore, falling back to filesystem"
            )
            _job_backend_instance = FilesystemJobPayloadBackend()
    else:
        _job_backend_instance = FilesystemJobPayloadBackend()

    return _job_backend_instance


def reset_backends():
    """Reset backend instances (for testing)."""
    global _run_backend_instance, _job_backend_instance
    _run_backend_instance = None
    _job_backend_instance = None

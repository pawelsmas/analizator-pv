"""
Database configuration module (v3.3.0).

Supports both SQLite (default for dev) and PostgreSQL (production).

Environment variables:
- DB_BACKEND: 'sqlite' or 'postgres' (default: sqlite)
- DATABASE_URL: PostgreSQL connection URL (required if DB_BACKEND=postgres)
- DB_MIGRATIONS_REQUIRED: 'true' or 'false' (default: true in postgres mode)
- SQLITE_DB_PATH: Path to SQLite database (default: /data/bess.sqlite)
"""
import os
import time
from typing import Optional
from enum import Enum

from prometheus_client import Counter, Histogram, Gauge


class DBBackend(str, Enum):
    """Supported database backends."""
    SQLITE = "sqlite"
    POSTGRES = "postgres"


# Configuration from environment
DB_BACKEND = DBBackend(os.getenv("DB_BACKEND", "sqlite").lower())
DATABASE_URL = os.getenv("DATABASE_URL", "")
SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", "/data/bess.sqlite")
DB_MIGRATIONS_REQUIRED = os.getenv("DB_MIGRATIONS_REQUIRED", "true").lower() == "true"


# Prometheus metrics for DB (v3.3.0)
DB_QUERY_DURATION = Histogram(
    "bess_db_query_duration_seconds",
    "Database query duration in seconds",
    ["repo", "op"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5]
)
DB_ERRORS_TOTAL = Counter(
    "bess_db_errors_total",
    "Total database errors",
    ["code"]
)
DB_CONNECTIONS_OPEN = Gauge(
    "bess_db_connections_open",
    "Number of open database connections"
)
DB_MIGRATIONS_PENDING = Gauge(
    "bess_db_migrations_pending",
    "Whether there are pending migrations (1=yes, 0=no)"
)


def get_database_url() -> str:
    """
    Get the database URL for SQLAlchemy.

    Returns:
        Connection URL string
    """
    if DB_BACKEND == DBBackend.POSTGRES:
        if not DATABASE_URL:
            raise ValueError("DATABASE_URL must be set when DB_BACKEND=postgres")
        return DATABASE_URL
    else:
        # SQLite
        return f"sqlite:///{SQLITE_DB_PATH}"


def get_sync_database_url() -> str:
    """
    Get synchronous database URL (for sync operations).

    Converts async URLs to sync if needed.
    """
    url = get_database_url()
    # Convert postgresql+psycopg to postgresql+psycopg (sync driver)
    if url.startswith("postgresql+asyncpg"):
        url = url.replace("postgresql+asyncpg", "postgresql+psycopg")
    return url


def check_db_connection() -> dict:
    """
    Check database connectivity.

    Returns:
        Dict with: ok (bool), db_backend (str), latency_ms (int), error (str|None)
    """
    start = time.time()

    try:
        if DB_BACKEND == DBBackend.SQLITE:
            import sqlite3
            conn = sqlite3.connect(SQLITE_DB_PATH, timeout=5.0)
            conn.execute("SELECT 1")
            conn.close()
        else:
            import psycopg
            # Parse URL for psycopg
            conn = psycopg.connect(DATABASE_URL, connect_timeout=5)
            conn.execute("SELECT 1")
            conn.close()

        latency_ms = int((time.time() - start) * 1000)
        return {
            "ok": True,
            "db_backend": DB_BACKEND.value,
            "latency_ms": latency_ms,
            "error": None,
        }
    except Exception as e:
        latency_ms = int((time.time() - start) * 1000)
        DB_ERRORS_TOTAL.labels(code="connection_error").inc()
        return {
            "ok": False,
            "db_backend": DB_BACKEND.value,
            "latency_ms": latency_ms,
            "error": str(e),
        }


def is_postgres() -> bool:
    """Check if PostgreSQL backend is configured."""
    return DB_BACKEND == DBBackend.POSTGRES


def is_sqlite() -> bool:
    """Check if SQLite backend is configured."""
    return DB_BACKEND == DBBackend.SQLITE


def migrations_required() -> bool:
    """Check if migrations are required (mainly for postgres)."""
    return DB_MIGRATIONS_REQUIRED and is_postgres()

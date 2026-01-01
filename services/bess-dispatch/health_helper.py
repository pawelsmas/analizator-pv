"""
Health check helper module (v3.5.0).

Provides:
- Liveness check: Process is alive (always 200)
- Readiness check: All dependencies are healthy (DB, Redis, S3)

Dependency checks are optional and configurable via environment variables:
- JOB_STORE_ENABLED: Enable DB check (default: true)
- REDIS_ENABLED: Enable Redis check (default: false)
- S3_ENABLED: Enable S3/MinIO check (default: false)
"""

import os
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

# Configuration from environment
JOB_STORE_ENABLED = os.getenv("JOB_STORE_ENABLED", "true").lower() in ("true", "1", "yes")
JOB_STORE_PATH = os.getenv("JOB_STORE_PATH", "/data/jobs.sqlite")
REDIS_ENABLED = os.getenv("REDIS_ENABLED", "false").lower() in ("true", "1", "yes")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
S3_ENABLED = os.getenv("S3_ENABLED", "false").lower() in ("true", "1", "yes")
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "")
S3_BUCKET = os.getenv("S3_BUCKET", "bess-artifacts")


@dataclass
class HealthStatus:
    """Health status result."""
    healthy: bool
    service: str = "bess-dispatch"
    checks: Dict[str, Dict] = field(default_factory=dict)
    message: Optional[str] = None


def check_liveness() -> HealthStatus:
    """
    Liveness check - always returns healthy if process is alive.

    Used by Kubernetes livenessProbe to detect stuck/dead processes.
    """
    return HealthStatus(
        healthy=True,
        message="Process is alive",
    )


def check_db() -> Dict:
    """
    Check SQLite database connectivity.

    Returns:
        Dict with status, latency_ms, and optional error
    """
    if not JOB_STORE_ENABLED:
        return {"status": "disabled", "latency_ms": 0}

    try:
        import sqlite3
        start = time.time()

        # Check if DB file exists (for new installs, file may not exist yet)
        db_dir = os.path.dirname(JOB_STORE_PATH)
        if db_dir and not os.path.exists(db_dir):
            # Directory doesn't exist, DB not initialized yet
            return {"status": "not_initialized", "latency_ms": 0}

        # Try to connect and execute a simple query
        conn = sqlite3.connect(JOB_STORE_PATH, timeout=5.0)
        try:
            cursor = conn.execute("SELECT 1")
            cursor.fetchone()
            latency_ms = (time.time() - start) * 1000
            return {"status": "ok", "latency_ms": round(latency_ms, 2)}
        finally:
            conn.close()

    except Exception as e:
        return {"status": "error", "latency_ms": 0, "error": str(e)}


def check_redis() -> Dict:
    """
    Check Redis connectivity.

    Returns:
        Dict with status, latency_ms, and optional error
    """
    if not REDIS_ENABLED:
        return {"status": "disabled", "latency_ms": 0}

    try:
        import redis
        start = time.time()

        client = redis.from_url(REDIS_URL, socket_timeout=5.0, socket_connect_timeout=5.0)
        client.ping()
        latency_ms = (time.time() - start) * 1000
        return {"status": "ok", "latency_ms": round(latency_ms, 2)}

    except ImportError:
        return {"status": "not_installed", "latency_ms": 0, "error": "redis package not installed"}
    except Exception as e:
        return {"status": "error", "latency_ms": 0, "error": str(e)}


def check_s3() -> Dict:
    """
    Check S3/MinIO connectivity.

    Returns:
        Dict with status, latency_ms, and optional error
    """
    if not S3_ENABLED:
        return {"status": "disabled", "latency_ms": 0}

    if not S3_ENDPOINT:
        return {"status": "not_configured", "latency_ms": 0, "error": "S3_ENDPOINT not set"}

    try:
        import boto3
        from botocore.config import Config
        from botocore.exceptions import ClientError

        start = time.time()

        # Configure S3 client
        config = Config(
            connect_timeout=5,
            read_timeout=5,
            retries={'max_attempts': 1}
        )

        s3_client = boto3.client(
            's3',
            endpoint_url=S3_ENDPOINT,
            aws_access_key_id=os.getenv("S3_ACCESS_KEY", ""),
            aws_secret_access_key=os.getenv("S3_SECRET_KEY", ""),
            config=config,
        )

        # Try to head bucket (lightweight check)
        try:
            s3_client.head_bucket(Bucket=S3_BUCKET)
        except ClientError as e:
            # 404 means bucket doesn't exist, but S3 is reachable
            if e.response.get('Error', {}).get('Code') == '404':
                latency_ms = (time.time() - start) * 1000
                return {"status": "ok", "latency_ms": round(latency_ms, 2), "note": "bucket not found"}
            raise

        latency_ms = (time.time() - start) * 1000
        return {"status": "ok", "latency_ms": round(latency_ms, 2)}

    except ImportError:
        return {"status": "not_installed", "latency_ms": 0, "error": "boto3 package not installed"}
    except Exception as e:
        return {"status": "error", "latency_ms": 0, "error": str(e)}


def check_readiness() -> HealthStatus:
    """
    Readiness check - returns healthy only if all enabled dependencies are healthy.

    Used by Kubernetes readinessProbe to determine if pod should receive traffic.

    Checks:
    - DB (SQLite) if JOB_STORE_ENABLED=true
    - Redis if REDIS_ENABLED=true
    - S3/MinIO if S3_ENABLED=true
    """
    checks = {}
    all_healthy = True
    failed_deps = []

    # Check DB
    db_check = check_db()
    checks["db"] = db_check
    if db_check["status"] not in ("ok", "disabled", "not_initialized"):
        all_healthy = False
        failed_deps.append("db")

    # Check Redis
    redis_check = check_redis()
    checks["redis"] = redis_check
    if redis_check["status"] not in ("ok", "disabled", "not_installed"):
        all_healthy = False
        failed_deps.append("redis")

    # Check S3
    s3_check = check_s3()
    checks["s3"] = s3_check
    if s3_check["status"] not in ("ok", "disabled", "not_installed", "not_configured"):
        all_healthy = False
        failed_deps.append("s3")

    if all_healthy:
        message = "All dependencies healthy"
    else:
        message = f"Dependencies unhealthy: {', '.join(failed_deps)}"

    return HealthStatus(
        healthy=all_healthy,
        checks=checks,
        message=message,
    )

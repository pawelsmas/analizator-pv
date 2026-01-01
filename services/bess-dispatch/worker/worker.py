"""
Worker process for distributed job processing (v3.4.0 PR1).

This module implements the worker that claims and executes jobs from
the job_queue table.

Environment variables:
- WORKER_POLL_SECONDS: How often to poll for new jobs (default: 1)
- WORKER_ID: Unique identifier for this worker (default: hostname)
- WORKER_CONCURRENCY: Number of concurrent jobs (default: 1, reserved for future)
- WORKER_LOCK_TIMEOUT_SECONDS: How long a lock is held (default: 300)
- JOB_RETRY_BACKOFF_SECONDS: Backoff before retry (default: 5)

Usage:
    python -m services.bess_dispatch.worker
"""

import json
import logging
import os
import signal
import socket
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import text
from sqlalchemy.orm import Session

from db_config import DB_BACKEND, DBBackend, get_database_url
from db_models import JobQueue
from db_session import get_db_session


# Configuration from environment
WORKER_POLL_SECONDS = int(os.getenv("WORKER_POLL_SECONDS", "1"))
WORKER_ID = os.getenv("WORKER_ID", socket.gethostname())
WORKER_CONCURRENCY = int(os.getenv("WORKER_CONCURRENCY", "1"))
WORKER_LOCK_TIMEOUT_SECONDS = int(os.getenv("WORKER_LOCK_TIMEOUT_SECONDS", "300"))
JOB_RETRY_BACKOFF_SECONDS = int(os.getenv("JOB_RETRY_BACKOFF_SECONDS", "5"))

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("worker")

# Graceful shutdown flag
_shutdown_requested = False


def _signal_handler(signum, frame):
    """Handle shutdown signals."""
    global _shutdown_requested
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    _shutdown_requested = True


def claim_next_job(session: Session, worker_id: str, now: datetime) -> Optional[JobQueue]:
    """
    Claim the next available job from the queue.

    Uses database-level locking to ensure only one worker can claim a job:
    - PostgreSQL: FOR UPDATE SKIP LOCKED
    - SQLite: Optimistic locking via UPDATE WHERE

    Args:
        session: SQLAlchemy session
        worker_id: Unique identifier for this worker
        now: Current timestamp

    Returns:
        The claimed JobQueue record, or None if no jobs available
    """
    lock_until = now + timedelta(seconds=WORKER_LOCK_TIMEOUT_SECONDS)

    if DB_BACKEND == DBBackend.POSTGRES:
        # PostgreSQL: Use FOR UPDATE SKIP LOCKED for efficient locking
        # This prevents workers from blocking each other
        job = session.execute(
            text("""
                SELECT id FROM job_queue
                WHERE status = 'queued'
                  AND (locked_until IS NULL OR locked_until < :now)
                ORDER BY created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            """),
            {"now": now}
        ).fetchone()

        if job:
            job_id = job[0]
            # Update the job to claim it
            session.execute(
                text("""
                    UPDATE job_queue
                    SET status = 'running',
                        locked_by = :worker_id,
                        locked_until = :lock_until,
                        started_at = :now,
                        attempts = attempts + 1
                    WHERE id = :job_id
                """),
                {
                    "worker_id": worker_id,
                    "lock_until": lock_until,
                    "now": now,
                    "job_id": job_id,
                }
            )
            session.commit()
            return session.query(JobQueue).filter(JobQueue.id == job_id).first()
    else:
        # SQLite: Optimistic locking via UPDATE WHERE
        # First, try to claim a job atomically
        result = session.execute(
            text("""
                UPDATE job_queue
                SET status = 'running',
                    locked_by = :worker_id,
                    locked_until = :lock_until,
                    started_at = :now,
                    attempts = attempts + 1
                WHERE id = (
                    SELECT id FROM job_queue
                    WHERE status = 'queued'
                      AND (locked_until IS NULL OR locked_until < :now)
                    ORDER BY created_at ASC
                    LIMIT 1
                )
                  AND status = 'queued'
                  AND (locked_until IS NULL OR locked_until < :now)
            """),
            {
                "worker_id": worker_id,
                "lock_until": lock_until,
                "now": now,
            }
        )

        if result.rowcount > 0:
            session.commit()
            # Fetch the claimed job
            return session.query(JobQueue).filter(
                JobQueue.locked_by == worker_id,
                JobQueue.status == "running",
            ).order_by(JobQueue.started_at.desc()).first()

    return None


def execute_job(job: JobQueue) -> Dict[str, Any]:
    """
    Execute a job based on its kind.

    This is a stub implementation that will be extended in PR2/PR3
    to handle actual job kinds.

    Args:
        job: The JobQueue record to execute

    Returns:
        Dict with keys:
        - success: bool
        - result: Optional dict to store in result_json
        - error_code: Optional error code
        - error_detail: Optional error message
    """
    kind = job.kind
    logger.info(f"Executing job {job.id} of kind '{kind}'")

    # Parse payload
    payload = {}
    if job.payload_json:
        try:
            payload = json.loads(job.payload_json)
        except json.JSONDecodeError:
            return {
                "success": False,
                "result": None,
                "error_code": "INVALID_PAYLOAD",
                "error_detail": "Failed to parse payload JSON",
            }

    # Stub: Unknown job kind -> fail
    # Actual implementations will be added in PR3
    return {
        "success": False,
        "result": None,
        "error_code": "UNKNOWN_JOB_KIND",
        "error_detail": f"Unknown job kind: {kind}. Job execution not yet implemented.",
    }


def complete_job(session: Session, job: JobQueue, execution_result: Dict[str, Any], now: datetime):
    """
    Mark a job as completed (succeeded or failed).

    Args:
        session: SQLAlchemy session
        job: The JobQueue record
        execution_result: Result from execute_job()
        now: Current timestamp
    """
    if execution_result["success"]:
        job.status = "succeeded"
        job.result_json = json.dumps(execution_result.get("result")) if execution_result.get("result") else None
        job.error_code = None
        job.error_detail = None
    else:
        # Check if we should retry
        if job.attempts < job.max_attempts:
            # Return to queue for retry with backoff
            job.status = "queued"
            job.locked_by = None
            job.locked_until = now + timedelta(seconds=JOB_RETRY_BACKOFF_SECONDS)
            logger.info(f"Job {job.id} failed, will retry (attempt {job.attempts}/{job.max_attempts})")
        else:
            # Max attempts reached, mark as failed
            job.status = "failed"
            job.error_code = execution_result.get("error_code", "EXECUTION_FAILED")
            job.error_detail = execution_result.get("error_detail", "Job execution failed")
            logger.warning(f"Job {job.id} failed permanently after {job.attempts} attempts")

    job.finished_at = now
    session.commit()


def process_one_job(session: Session, worker_id: str) -> bool:
    """
    Attempt to claim and process one job.

    Args:
        session: SQLAlchemy session
        worker_id: Unique identifier for this worker

    Returns:
        True if a job was processed, False if no jobs available
    """
    now = datetime.now(timezone.utc)

    # Try to claim a job
    job = claim_next_job(session, worker_id, now)
    if not job:
        return False

    logger.info(f"Claimed job {job.id} (kind={job.kind}, attempt={job.attempts})")

    try:
        # Execute the job
        result = execute_job(job)

        # Complete the job
        complete_job(session, job, result, datetime.now(timezone.utc))

        if result["success"]:
            logger.info(f"Job {job.id} completed successfully")
        else:
            logger.info(f"Job {job.id} execution returned: {result.get('error_code')}")

    except Exception as e:
        logger.exception(f"Error executing job {job.id}: {e}")
        complete_job(session, job, {
            "success": False,
            "error_code": "EXECUTION_EXCEPTION",
            "error_detail": str(e),
        }, datetime.now(timezone.utc))

    return True


def run_loop():
    """
    Main worker loop.

    Continuously polls for jobs and processes them until shutdown is requested.
    """
    global _shutdown_requested

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    logger.info(f"Worker {WORKER_ID} starting...")
    logger.info(f"Poll interval: {WORKER_POLL_SECONDS}s, Lock timeout: {WORKER_LOCK_TIMEOUT_SECONDS}s")
    logger.info(f"Database backend: {DB_BACKEND.value}")

    jobs_processed = 0

    while not _shutdown_requested:
        try:
            with get_db_session() as session:
                if process_one_job(session, WORKER_ID):
                    jobs_processed += 1
                else:
                    # No jobs available, wait before polling again
                    time.sleep(WORKER_POLL_SECONDS)

        except Exception as e:
            logger.exception(f"Error in worker loop: {e}")
            time.sleep(WORKER_POLL_SECONDS)

    logger.info(f"Worker {WORKER_ID} shutting down. Processed {jobs_processed} jobs.")


def main():
    """Entry point for worker process."""
    run_loop()


if __name__ == "__main__":
    main()

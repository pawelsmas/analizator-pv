#!/usr/bin/env python3
"""
Backfill RunStore from filesystem to database (v3.6.0).

Migrates run payloads from SQLite filesystem store to PostgreSQL/SQLite DB store.
Idempotent - can be run multiple times safely (upsert).

Usage:
    python scripts/db/backfill_runstore_db.py --tenant default
    python scripts/db/backfill_runstore_db.py --tenant tenant-123 --dry-run
    python scripts/db/backfill_runstore_db.py --all-tenants

Environment:
    RUNSTORE_DB_URL: Target database URL (required)
    RUN_STORE_PATH: Source SQLite path (default: /data/runs.sqlite)
"""

import argparse
import logging
import os
import sys
from datetime import datetime

# Add services to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "bess-dispatch"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("backfill")


def get_source_runs(tenant_id: str = None, limit: int = None):
    """
    Get runs from filesystem SQLite store.

    Args:
        tenant_id: Filter by tenant (None = all tenants)
        limit: Max runs to fetch

    Yields:
        Dict with run data
    """
    from run_store import RunStore

    store = RunStore()

    # Use list method to get runs
    result = store.list(
        limit=limit or 10000,
        offset=0,
        tenant_id=tenant_id,
    )

    for run_summary in result["items"]:
        # Get full run details
        run = store.get(run_summary["run_id"], tenant_id=tenant_id)
        if run:
            yield run


def backfill_runs(tenant_id: str = None, dry_run: bool = False, batch_size: int = 100):
    """
    Backfill runs from filesystem to database.

    Args:
        tenant_id: Specific tenant to migrate (None = all)
        dry_run: If True, don't actually write
        batch_size: Number of runs per batch

    Returns:
        Dict with statistics
    """
    from runstore_backend import (
        DbRunPayloadBackend,
        RunPayload,
        RUNSTORE_DB_URL,
    )

    if not RUNSTORE_DB_URL:
        logger.error("RUNSTORE_DB_URL not set")
        return {"error": "RUNSTORE_DB_URL required"}

    db_backend = DbRunPayloadBackend()

    if not db_backend.is_available():
        logger.error("Database not available")
        return {"error": "Database not available"}

    stats = {
        "total_processed": 0,
        "migrated": 0,
        "skipped": 0,
        "errors": 0,
        "start_time": datetime.utcnow().isoformat(),
    }

    logger.info(f"Starting backfill (tenant={tenant_id or 'all'}, dry_run={dry_run})")

    batch = []

    for run in get_source_runs(tenant_id=tenant_id):
        stats["total_processed"] += 1

        try:
            payload = RunPayload(
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

            if not dry_run:
                db_backend.save_run(payload)

            stats["migrated"] += 1

            if stats["migrated"] % 100 == 0:
                logger.info(f"Progress: {stats['migrated']} runs migrated")

        except Exception as e:
            logger.error(f"Error migrating run {run.get('run_id')}: {e}")
            stats["errors"] += 1

    stats["end_time"] = datetime.utcnow().isoformat()

    logger.info(f"Backfill complete: {stats}")

    return stats


def backfill_jobs(tenant_id: str = None, dry_run: bool = False):
    """
    Backfill jobs from filesystem to database.

    Args:
        tenant_id: Specific tenant to migrate
        dry_run: If True, don't actually write

    Returns:
        Dict with statistics
    """
    from runstore_backend import (
        DbJobPayloadBackend,
        JobPayload,
        RUNSTORE_DB_URL,
    )
    from job_store import JobStore

    if not RUNSTORE_DB_URL:
        logger.error("RUNSTORE_DB_URL not set")
        return {"error": "RUNSTORE_DB_URL required"}

    db_backend = DbJobPayloadBackend()

    if not db_backend.is_available():
        logger.error("Database not available")
        return {"error": "Database not available"}

    stats = {
        "total_processed": 0,
        "migrated": 0,
        "errors": 0,
        "start_time": datetime.utcnow().isoformat(),
    }

    logger.info(f"Starting job backfill (tenant={tenant_id or 'all'}, dry_run={dry_run})")

    fs_store = JobStore()
    result = fs_store.list_jobs(limit=10000, tenant_id=tenant_id)

    for job_summary in result["items"]:
        stats["total_processed"] += 1

        try:
            job = fs_store.get_job(job_summary["job_id"], tenant_id=tenant_id)
            if not job:
                continue

            payload = JobPayload(
                job_id=job["job_id"],
                tenant_id=job.get("tenant_id", "default"),
                created_at=job["created_at"],
                payload_json=job.get("request", {}),
                result_json=job.get("result"),
                error_json={"message": job.get("message")} if job.get("message") else None,
            )

            if not dry_run:
                db_backend.save_job(payload)

            stats["migrated"] += 1

        except Exception as e:
            logger.error(f"Error migrating job {job_summary.get('job_id')}: {e}")
            stats["errors"] += 1

    stats["end_time"] = datetime.utcnow().isoformat()

    logger.info(f"Job backfill complete: {stats}")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Backfill RunStore from filesystem to database")
    parser.add_argument("--tenant", type=str, help="Specific tenant to migrate")
    parser.add_argument("--all-tenants", action="store_true", help="Migrate all tenants")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually write to DB")
    parser.add_argument("--include-jobs", action="store_true", help="Also migrate jobs")
    parser.add_argument("--batch-size", type=int, default=100, help="Batch size")

    args = parser.parse_args()

    if not args.tenant and not args.all_tenants:
        parser.error("Either --tenant or --all-tenants required")

    tenant_id = None if args.all_tenants else args.tenant

    # Backfill runs
    run_stats = backfill_runs(
        tenant_id=tenant_id,
        dry_run=args.dry_run,
        batch_size=args.batch_size,
    )

    print("\n=== Run Backfill Results ===")
    for key, value in run_stats.items():
        print(f"  {key}: {value}")

    # Optionally backfill jobs
    if args.include_jobs:
        job_stats = backfill_jobs(
            tenant_id=tenant_id,
            dry_run=args.dry_run,
        )

        print("\n=== Job Backfill Results ===")
        for key, value in job_stats.items():
            print(f"  {key}: {value}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Backfill runs and jobs from SQLite to PostgreSQL (v3.3.0 PR4).

This script migrates existing run and job data from the SQLite stores
to the PostgreSQL run_index and job_index tables.

Usage:
    python scripts/db/backfill_runs_jobs.py [--dry-run] [--batch-size 100]

Environment:
    - DATABASE_URL: PostgreSQL connection URL (required)
    - RUN_STORE_PATH: Path to runs SQLite database (default: /data/runs.sqlite)
    - JOB_STORE_PATH: Path to jobs SQLite database (default: /data/jobs.sqlite)
"""

import argparse
import json
import os
import sqlite3
import sys
import zlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Add services to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db_models import RunIndex, JobIndex


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Backfill runs and jobs from SQLite to PostgreSQL'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=100,
        help='Number of records to process per batch (default: 100)'
    )
    parser.add_argument(
        '--runs-only',
        action='store_true',
        help='Only backfill runs'
    )
    parser.add_argument(
        '--jobs-only',
        action='store_true',
        help='Only backfill jobs'
    )
    parser.add_argument(
        '--skip-existing',
        action='store_true',
        default=True,
        help='Skip records that already exist in PostgreSQL (default: True)'
    )
    return parser.parse_args()


def get_pg_session():
    """Get PostgreSQL session."""
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        raise ValueError("DATABASE_URL environment variable is required")

    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)
    return Session()


def get_sqlite_runs(db_path: str, batch_size: int, offset: int) -> List[Dict[str, Any]]:
    """Get batch of runs from SQLite."""
    if not os.path.exists(db_path):
        return []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute("""
            SELECT run_id, tenant_id, request_hash, created_at, endpoint, status,
                   cache_hit, schema_version, assumptions_version, compute_time_ms,
                   request_blob, response_blob, label, tags_json, notes, updated_at
            FROM runs
            ORDER BY created_at
            LIMIT ? OFFSET ?
        """, (batch_size, offset))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_sqlite_jobs(db_path: str, batch_size: int, offset: int) -> List[Dict[str, Any]]:
    """Get batch of jobs from SQLite."""
    if not os.path.exists(db_path):
        return []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute("""
            SELECT job_id, tenant_id, created_at, updated_at, type, status,
                   batch_id, idempotency_key, items_total, items_done, error_count,
                   request_hash, request_blob, result_blob, message,
                   lease_owner, lease_expires_at, attempts, max_attempts,
                   started_at, finished_at, last_error, label, tags_json, notes
            FROM jobs
            ORDER BY created_at
            LIMIT ? OFFSET ?
        """, (batch_size, offset))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def count_sqlite_runs(db_path: str) -> int:
    """Count runs in SQLite."""
    if not os.path.exists(db_path):
        return 0

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute("SELECT COUNT(*) FROM runs")
        return cursor.fetchone()[0]
    finally:
        conn.close()


def count_sqlite_jobs(db_path: str) -> int:
    """Count jobs in SQLite."""
    if not os.path.exists(db_path):
        return 0

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute("SELECT COUNT(*) FROM jobs")
        return cursor.fetchone()[0]
    finally:
        conn.close()


def parse_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """Parse ISO datetime string to datetime object."""
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
    except Exception:
        return None


def backfill_runs(session, runs_path: str, batch_size: int, dry_run: bool, skip_existing: bool) -> Dict[str, int]:
    """Backfill runs from SQLite to PostgreSQL."""
    total = count_sqlite_runs(runs_path)
    if total == 0:
        print(f"  No runs found in {runs_path}")
        return {"total": 0, "inserted": 0, "skipped": 0, "errors": 0}

    print(f"  Found {total} runs in SQLite")

    inserted = 0
    skipped = 0
    errors = 0
    offset = 0

    while offset < total:
        batch = get_sqlite_runs(runs_path, batch_size, offset)
        if not batch:
            break

        for row in batch:
            try:
                run_id = row['run_id']

                # Check if exists
                if skip_existing:
                    existing = session.query(RunIndex).filter(RunIndex.run_id == run_id).first()
                    if existing:
                        skipped += 1
                        continue

                if dry_run:
                    print(f"    [DRY-RUN] Would insert run {run_id}")
                    inserted += 1
                    continue

                # Create RunIndex record
                run_index = RunIndex(
                    run_id=run_id,
                    tenant_id=row.get('tenant_id') or 'default',
                    request_hash=row['request_hash'],
                    created_at=parse_datetime(row['created_at']) or datetime.now(timezone.utc),
                    endpoint=row['endpoint'],
                    status=row['status'],
                    cache_hit=bool(row.get('cache_hit', 0)),
                    schema_version=row.get('schema_version'),
                    assumptions_version=row.get('assumptions_version'),
                    compute_time_ms=row.get('compute_time_ms'),
                    label=row.get('label'),
                    tags_json=row.get('tags_json'),
                    notes=row.get('notes'),
                    updated_at=parse_datetime(row.get('updated_at')),
                    request_blob=row.get('request_blob'),
                    response_blob=row.get('response_blob'),
                )
                session.add(run_index)
                inserted += 1

            except Exception as e:
                print(f"    ERROR: Failed to insert run {row.get('run_id')}: {e}")
                errors += 1

        # Commit batch
        if not dry_run:
            session.commit()

        offset += batch_size
        print(f"    Processed {min(offset, total)}/{total} runs...")

    return {"total": total, "inserted": inserted, "skipped": skipped, "errors": errors}


def backfill_jobs(session, jobs_path: str, batch_size: int, dry_run: bool, skip_existing: bool) -> Dict[str, int]:
    """Backfill jobs from SQLite to PostgreSQL."""
    total = count_sqlite_jobs(jobs_path)
    if total == 0:
        print(f"  No jobs found in {jobs_path}")
        return {"total": 0, "inserted": 0, "skipped": 0, "errors": 0}

    print(f"  Found {total} jobs in SQLite")

    inserted = 0
    skipped = 0
    errors = 0
    offset = 0

    while offset < total:
        batch = get_sqlite_jobs(jobs_path, batch_size, offset)
        if not batch:
            break

        for row in batch:
            try:
                job_id = row['job_id']

                # Check if exists
                if skip_existing:
                    existing = session.query(JobIndex).filter(JobIndex.job_id == job_id).first()
                    if existing:
                        skipped += 1
                        continue

                if dry_run:
                    print(f"    [DRY-RUN] Would insert job {job_id}")
                    inserted += 1
                    continue

                # Create JobIndex record
                job_index = JobIndex(
                    job_id=job_id,
                    tenant_id=row.get('tenant_id') or 'default',
                    created_at=parse_datetime(row['created_at']) or datetime.now(timezone.utc),
                    updated_at=parse_datetime(row['updated_at']) or datetime.now(timezone.utc),
                    type=row['type'],
                    status=row.get('status') or 'pending',
                    batch_id=row.get('batch_id'),
                    idempotency_key=row.get('idempotency_key'),
                    items_total=row.get('items_total') or 0,
                    items_done=row.get('items_done') or 0,
                    error_count=row.get('error_count') or 0,
                    request_hash=row['request_hash'],
                    message=row.get('message'),
                    lease_owner=row.get('lease_owner'),
                    lease_expires_at=parse_datetime(row.get('lease_expires_at')),
                    attempts=row.get('attempts') or 0,
                    max_attempts=row.get('max_attempts') or 3,
                    started_at=parse_datetime(row.get('started_at')),
                    finished_at=parse_datetime(row.get('finished_at')),
                    last_error=row.get('last_error'),
                    label=row.get('label'),
                    tags_json=row.get('tags_json'),
                    notes=row.get('notes'),
                    request_blob=row.get('request_blob'),
                    result_blob=row.get('result_blob'),
                )
                session.add(job_index)
                inserted += 1

            except Exception as e:
                print(f"    ERROR: Failed to insert job {row.get('job_id')}: {e}")
                errors += 1

        # Commit batch
        if not dry_run:
            session.commit()

        offset += batch_size
        print(f"    Processed {min(offset, total)}/{total} jobs...")

    return {"total": total, "inserted": inserted, "skipped": skipped, "errors": errors}


def main():
    """Main entry point."""
    args = parse_args()

    print("=" * 60)
    print("Backfill Runs/Jobs from SQLite to PostgreSQL")
    print("=" * 60)

    if args.dry_run:
        print("MODE: DRY-RUN (no changes will be made)")
    else:
        print("MODE: LIVE (changes will be committed)")

    print(f"Batch size: {args.batch_size}")
    print()

    # Get paths
    runs_path = os.getenv('RUN_STORE_PATH', '/data/runs.sqlite')
    jobs_path = os.getenv('JOB_STORE_PATH', '/data/jobs.sqlite')

    print(f"Runs SQLite: {runs_path}")
    print(f"Jobs SQLite: {jobs_path}")
    print()

    # Get PostgreSQL session
    try:
        session = get_pg_session()
        print("Connected to PostgreSQL")
    except Exception as e:
        print(f"ERROR: Failed to connect to PostgreSQL: {e}")
        sys.exit(1)

    results = {}

    # Backfill runs
    if not args.jobs_only:
        print()
        print("Backfilling runs...")
        results['runs'] = backfill_runs(
            session, runs_path, args.batch_size, args.dry_run, args.skip_existing
        )

    # Backfill jobs
    if not args.runs_only:
        print()
        print("Backfilling jobs...")
        results['jobs'] = backfill_jobs(
            session, jobs_path, args.batch_size, args.dry_run, args.skip_existing
        )

    # Summary
    print()
    print("=" * 60)
    print("Summary")
    print("=" * 60)

    for table, stats in results.items():
        print(f"{table}:")
        print(f"  Total in SQLite: {stats['total']}")
        print(f"  Inserted: {stats['inserted']}")
        print(f"  Skipped (existing): {stats['skipped']}")
        print(f"  Errors: {stats['errors']}")

    # Close session
    session.close()

    # Exit with error if any failures
    total_errors = sum(s['errors'] for s in results.values())
    if total_errors > 0:
        print(f"\nCompleted with {total_errors} errors")
        sys.exit(1)
    else:
        print("\nCompleted successfully")
        sys.exit(0)


if __name__ == '__main__':
    main()

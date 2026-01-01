#!/usr/bin/env python3
"""
Retention cleanup script (v3.3.0 PR5).

Performs data retention cleanup for runs, jobs, and audit logs.

Usage:
    python scripts/db/retention_cleanup.py [--dry-run] [--all]

Environment:
    - DATABASE_URL: PostgreSQL connection URL (for Postgres mode)
    - DB_BACKEND: 'sqlite' or 'postgres' (default: sqlite)
    - RUN_STORE_RETENTION_DAYS: Days to keep runs (default: 30)
    - JOB_STORE_RETENTION_DAYS: Days to keep jobs (default: 14)
    - AUDIT_STORE_RETENTION_DAYS: Days to keep audit logs (default: 90)
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, Any

# Add services to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Run retention cleanup for BESS data stores'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be deleted without making changes'
    )
    parser.add_argument(
        '--all',
        action='store_true',
        help='Clean all stores (runs, jobs, audit)'
    )
    parser.add_argument(
        '--runs',
        action='store_true',
        help='Clean runs store'
    )
    parser.add_argument(
        '--jobs',
        action='store_true',
        help='Clean jobs store'
    )
    parser.add_argument(
        '--audit',
        action='store_true',
        help='Clean audit log'
    )
    parser.add_argument(
        '--backups',
        action='store_true',
        help='Clean old backups'
    )
    parser.add_argument(
        '--vacuum',
        action='store_true',
        help='Run VACUUM after cleanup (SQLite only)'
    )
    return parser.parse_args()


def get_db_backend() -> str:
    """Get configured database backend."""
    return os.getenv('DB_BACKEND', 'sqlite').lower()


def cleanup_sqlite_runs(retention_days: int, dry_run: bool) -> Dict[str, Any]:
    """Cleanup runs from SQLite store."""
    runs_path = os.getenv('RUN_STORE_PATH', '/data/runs.sqlite')

    if not os.path.exists(runs_path):
        return {'deleted': 0, 'error': 'Database not found'}

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    cutoff_str = cutoff.isoformat()

    conn = sqlite3.connect(runs_path)
    try:
        cursor = conn.cursor()

        # Count records to delete
        cursor.execute(
            "SELECT COUNT(*) FROM runs WHERE created_at < ?",
            (cutoff_str,)
        )
        count = cursor.fetchone()[0]

        if dry_run:
            return {'would_delete': count, 'dry_run': True}

        # Delete old records
        cursor.execute(
            "DELETE FROM runs WHERE created_at < ?",
            (cutoff_str,)
        )
        conn.commit()

        return {'deleted': count}
    except Exception as e:
        return {'deleted': 0, 'error': str(e)}
    finally:
        conn.close()


def cleanup_sqlite_jobs(retention_days: int, dry_run: bool) -> Dict[str, Any]:
    """Cleanup jobs from SQLite store."""
    jobs_path = os.getenv('JOB_STORE_PATH', '/data/jobs.sqlite')

    if not os.path.exists(jobs_path):
        return {'deleted': 0, 'error': 'Database not found'}

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    cutoff_str = cutoff.isoformat()

    conn = sqlite3.connect(jobs_path)
    try:
        cursor = conn.cursor()

        # Count records to delete
        cursor.execute(
            "SELECT COUNT(*) FROM jobs WHERE created_at < ?",
            (cutoff_str,)
        )
        count = cursor.fetchone()[0]

        if dry_run:
            return {'would_delete': count, 'dry_run': True}

        # Delete old records
        cursor.execute(
            "DELETE FROM jobs WHERE created_at < ?",
            (cutoff_str,)
        )
        conn.commit()

        return {'deleted': count}
    except Exception as e:
        return {'deleted': 0, 'error': str(e)}
    finally:
        conn.close()


def cleanup_sqlite_audit(retention_days: int, dry_run: bool) -> Dict[str, Any]:
    """Cleanup audit logs from SQLite store."""
    audit_path = os.getenv('AUDIT_STORE_PATH', '/data/audit.sqlite')

    if not os.path.exists(audit_path):
        return {'deleted': 0, 'error': 'Database not found'}

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    cutoff_str = cutoff.isoformat()

    conn = sqlite3.connect(audit_path)
    try:
        cursor = conn.cursor()

        # Count records to delete
        cursor.execute(
            "SELECT COUNT(*) FROM audit_log WHERE created_at < ?",
            (cutoff_str,)
        )
        count = cursor.fetchone()[0]

        if dry_run:
            return {'would_delete': count, 'dry_run': True}

        # Delete old records
        cursor.execute(
            "DELETE FROM audit_log WHERE created_at < ?",
            (cutoff_str,)
        )
        conn.commit()

        return {'deleted': count}
    except Exception as e:
        return {'deleted': 0, 'error': str(e)}
    finally:
        conn.close()


def cleanup_postgres_runs(retention_days: int, dry_run: bool) -> Dict[str, Any]:
    """Cleanup runs from PostgreSQL."""
    try:
        from sqlalchemy import create_engine, text
        from db_config import get_sync_database_url
        from db_models import RunIndex

        engine = create_engine(get_sync_database_url())

        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

        with engine.connect() as conn:
            # Count records to delete
            result = conn.execute(
                text("SELECT COUNT(*) FROM run_index WHERE created_at < :cutoff"),
                {'cutoff': cutoff}
            )
            count = result.scalar()

            if dry_run:
                return {'would_delete': count, 'dry_run': True}

            # Delete old records
            conn.execute(
                text("DELETE FROM run_index WHERE created_at < :cutoff"),
                {'cutoff': cutoff}
            )
            conn.commit()

            return {'deleted': count}
    except Exception as e:
        return {'deleted': 0, 'error': str(e)}


def cleanup_postgres_jobs(retention_days: int, dry_run: bool) -> Dict[str, Any]:
    """Cleanup jobs from PostgreSQL."""
    try:
        from sqlalchemy import create_engine, text
        from db_config import get_sync_database_url

        engine = create_engine(get_sync_database_url())

        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

        with engine.connect() as conn:
            # Count records to delete
            result = conn.execute(
                text("SELECT COUNT(*) FROM job_index WHERE created_at < :cutoff"),
                {'cutoff': cutoff}
            )
            count = result.scalar()

            if dry_run:
                return {'would_delete': count, 'dry_run': True}

            # Delete old records
            conn.execute(
                text("DELETE FROM job_index WHERE created_at < :cutoff"),
                {'cutoff': cutoff}
            )
            conn.commit()

            return {'deleted': count}
    except Exception as e:
        return {'deleted': 0, 'error': str(e)}


def cleanup_postgres_audit(retention_days: int, dry_run: bool) -> Dict[str, Any]:
    """Cleanup audit logs from PostgreSQL."""
    try:
        from sqlalchemy import create_engine, text
        from db_config import get_sync_database_url

        engine = create_engine(get_sync_database_url())

        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

        with engine.connect() as conn:
            # Count records to delete
            result = conn.execute(
                text("SELECT COUNT(*) FROM audit_log WHERE created_at < :cutoff"),
                {'cutoff': cutoff}
            )
            count = result.scalar()

            if dry_run:
                return {'would_delete': count, 'dry_run': True}

            # Delete old records
            conn.execute(
                text("DELETE FROM audit_log WHERE created_at < :cutoff"),
                {'cutoff': cutoff}
            )
            conn.commit()

            return {'deleted': count}
    except Exception as e:
        return {'deleted': 0, 'error': str(e)}


def cleanup_backups(retention_days: int, dry_run: bool) -> Dict[str, Any]:
    """Cleanup old backup files."""
    import shutil
    from pathlib import Path

    backup_dir = Path(os.getenv('BACKUP_DIR', '/data/backups'))

    if not backup_dir.exists():
        return {'deleted': 0, 'freed_bytes': 0}

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    deleted = 0
    freed_bytes = 0

    for item in backup_dir.iterdir():
        if not item.name.startswith('bess_backup_'):
            continue

        mtime = datetime.fromtimestamp(item.stat().st_mtime, tz=timezone.utc)
        if mtime < cutoff:
            if item.is_dir():
                size = sum(f.stat().st_size for f in item.rglob('*') if f.is_file())
            else:
                size = item.stat().st_size

            if dry_run:
                print(f"    Would delete: {item.name} ({size / 1024 / 1024:.2f} MB)")
            else:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
                print(f"    Deleted: {item.name}")

            deleted += 1
            freed_bytes += size

    result = {'deleted': deleted, 'freed_bytes': freed_bytes}
    if dry_run:
        result['dry_run'] = True
    return result


def vacuum_sqlite():
    """Run VACUUM on SQLite databases."""
    paths = [
        os.getenv('RUN_STORE_PATH', '/data/runs.sqlite'),
        os.getenv('JOB_STORE_PATH', '/data/jobs.sqlite'),
        os.getenv('AUDIT_STORE_PATH', '/data/audit.sqlite'),
        os.getenv('AUTH_DB_PATH', '/data/auth.sqlite'),
    ]

    results = {}
    for path in paths:
        if not os.path.exists(path):
            continue

        name = os.path.basename(path)
        size_before = os.path.getsize(path)

        conn = sqlite3.connect(path)
        try:
            conn.execute("VACUUM")
            conn.commit()
        finally:
            conn.close()

        size_after = os.path.getsize(path)
        results[name] = {
            'size_before': size_before,
            'size_after': size_after,
            'freed': size_before - size_after,
        }

    return results


def main():
    """Main entry point."""
    args = parse_args()

    # Default to --all if nothing specified
    if not any([args.all, args.runs, args.jobs, args.audit, args.backups]):
        args.all = True

    print("=" * 60)
    print("Retention Cleanup")
    print("=" * 60)

    if args.dry_run:
        print("MODE: DRY-RUN (no changes will be made)")
    else:
        print("MODE: LIVE (changes will be committed)")

    backend = get_db_backend()
    print(f"Database backend: {backend}")
    print()

    # Get retention settings
    run_retention = int(os.getenv('RUN_STORE_RETENTION_DAYS', '30'))
    job_retention = int(os.getenv('JOB_STORE_RETENTION_DAYS', '14'))
    audit_retention = int(os.getenv('AUDIT_STORE_RETENTION_DAYS', '90'))
    backup_retention = int(os.getenv('BACKUP_RETENTION_DAYS', '7'))

    results = {}

    # Cleanup runs
    if args.all or args.runs:
        print(f"Runs (retention: {run_retention} days)...")
        if backend == 'postgres':
            results['runs'] = cleanup_postgres_runs(run_retention, args.dry_run)
        else:
            results['runs'] = cleanup_sqlite_runs(run_retention, args.dry_run)
        _print_result(results['runs'])

    # Cleanup jobs
    if args.all or args.jobs:
        print(f"Jobs (retention: {job_retention} days)...")
        if backend == 'postgres':
            results['jobs'] = cleanup_postgres_jobs(job_retention, args.dry_run)
        else:
            results['jobs'] = cleanup_sqlite_jobs(job_retention, args.dry_run)
        _print_result(results['jobs'])

    # Cleanup audit
    if args.all or args.audit:
        print(f"Audit logs (retention: {audit_retention} days)...")
        if backend == 'postgres':
            results['audit'] = cleanup_postgres_audit(audit_retention, args.dry_run)
        else:
            results['audit'] = cleanup_sqlite_audit(audit_retention, args.dry_run)
        _print_result(results['audit'])

    # Cleanup backups
    if args.all or args.backups:
        print(f"Backups (retention: {backup_retention} days)...")
        results['backups'] = cleanup_backups(backup_retention, args.dry_run)
        _print_backup_result(results['backups'])

    # Vacuum SQLite
    if args.vacuum and backend == 'sqlite' and not args.dry_run:
        print()
        print("Running VACUUM on SQLite databases...")
        vacuum_results = vacuum_sqlite()
        for db_name, stats in vacuum_results.items():
            freed_mb = stats['freed'] / 1024 / 1024
            print(f"  {db_name}: freed {freed_mb:.2f} MB")

    print()
    print("Cleanup completed")


def _print_result(result: Dict[str, Any]):
    """Print cleanup result."""
    if result.get('error'):
        print(f"  Error: {result['error']}")
    elif result.get('dry_run'):
        print(f"  Would delete: {result['would_delete']} records")
    else:
        print(f"  Deleted: {result['deleted']} records")


def _print_backup_result(result: Dict[str, Any]):
    """Print backup cleanup result."""
    if result.get('dry_run'):
        freed_mb = result['freed_bytes'] / 1024 / 1024
        print(f"  Would delete: {result['deleted']} backups ({freed_mb:.2f} MB)")
    else:
        freed_mb = result['freed_bytes'] / 1024 / 1024
        print(f"  Deleted: {result['deleted']} backups ({freed_mb:.2f} MB freed)")


if __name__ == '__main__':
    main()

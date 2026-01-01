#!/usr/bin/env python3
"""
PostgreSQL backup script (v3.3.0 PR5).

Creates compressed backups of the BESS PostgreSQL database.

Usage:
    python scripts/db/backup_postgres.py [--output DIR] [--compress]

Environment:
    - DATABASE_URL: PostgreSQL connection URL (required)
    - BACKUP_RETENTION_DAYS: Days to keep backups (default: 7)
"""

import argparse
import gzip
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Create PostgreSQL database backup'
    )
    parser.add_argument(
        '--output',
        '-o',
        type=str,
        default='/data/backups',
        help='Output directory for backup (default: /data/backups)'
    )
    parser.add_argument(
        '--compress',
        '-z',
        action='store_true',
        default=True,
        help='Compress backup with gzip (default: True)'
    )
    parser.add_argument(
        '--format',
        '-F',
        choices=['custom', 'plain', 'directory', 'tar'],
        default='custom',
        help='pg_dump format (default: custom)'
    )
    parser.add_argument(
        '--tables',
        '-t',
        type=str,
        nargs='*',
        help='Specific tables to backup (default: all)'
    )
    parser.add_argument(
        '--schema-only',
        action='store_true',
        help='Backup schema only (no data)'
    )
    parser.add_argument(
        '--data-only',
        action='store_true',
        help='Backup data only (no schema)'
    )
    return parser.parse_args()


def parse_database_url(url: str) -> dict:
    """Parse DATABASE_URL into components."""
    # Format: postgresql://user:password@host:port/database
    from urllib.parse import urlparse
    parsed = urlparse(url)

    return {
        'user': parsed.username,
        'password': parsed.password,
        'host': parsed.hostname or 'localhost',
        'port': parsed.port or 5432,
        'database': parsed.path.lstrip('/'),
    }


def create_backup(
    output_dir: str,
    compress: bool,
    format: str,
    tables: Optional[list],
    schema_only: bool,
    data_only: bool,
) -> dict:
    """
    Create PostgreSQL backup.

    Returns:
        Dict with: success, filename, size_bytes, duration_seconds, error
    """
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        return {
            'success': False,
            'error': 'DATABASE_URL environment variable is required',
        }

    db_config = parse_database_url(database_url)

    # Ensure output directory exists
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Generate filename with timestamp
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    db_name = db_config['database']

    if format == 'directory':
        filename = f"bess_backup_{timestamp}"
        output_file = output_path / filename
    else:
        ext_map = {'custom': 'dump', 'plain': 'sql', 'tar': 'tar'}
        ext = ext_map.get(format, 'dump')
        filename = f"bess_backup_{timestamp}.{ext}"
        if compress and format == 'plain':
            filename += '.gz'
        output_file = output_path / filename

    # Build pg_dump command
    cmd = [
        'pg_dump',
        '-h', db_config['host'],
        '-p', str(db_config['port']),
        '-U', db_config['user'],
        '-d', db_config['database'],
        '-F', format[0],  # c=custom, p=plain, d=directory, t=tar
    ]

    if format != 'directory':
        cmd.extend(['-f', str(output_file)])

    if tables:
        for table in tables:
            cmd.extend(['-t', table])

    if schema_only:
        cmd.append('--schema-only')
    elif data_only:
        cmd.append('--data-only')

    # Set password in environment
    env = os.environ.copy()
    env['PGPASSWORD'] = db_config['password'] or ''

    start_time = datetime.now(timezone.utc)

    try:
        if format == 'directory':
            cmd.extend(['-f', str(output_file)])

        print(f"Running: pg_dump -h {db_config['host']} -d {db_config['database']} ...")
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=3600,  # 1 hour timeout
        )

        if result.returncode != 0:
            return {
                'success': False,
                'error': f"pg_dump failed: {result.stderr}",
            }

        # Compress if requested and plain format
        if compress and format == 'plain' and not filename.endswith('.gz'):
            uncompressed = output_file
            compressed = output_path / (filename + '.gz')
            with open(uncompressed, 'rb') as f_in:
                with gzip.open(compressed, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            uncompressed.unlink()
            output_file = compressed
            filename = compressed.name

        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()

        # Get file size
        if format == 'directory':
            size_bytes = sum(
                f.stat().st_size
                for f in output_file.rglob('*')
                if f.is_file()
            )
        else:
            size_bytes = output_file.stat().st_size

        return {
            'success': True,
            'filename': filename,
            'path': str(output_file),
            'size_bytes': size_bytes,
            'duration_seconds': duration,
            'format': format,
            'compressed': compress and format == 'plain',
        }

    except subprocess.TimeoutExpired:
        return {
            'success': False,
            'error': 'Backup timed out after 1 hour',
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
        }


def cleanup_old_backups(output_dir: str, retention_days: int) -> dict:
    """
    Delete backups older than retention period.

    Returns:
        Dict with: deleted_count, freed_bytes
    """
    from datetime import timedelta

    output_path = Path(output_dir)
    if not output_path.exists():
        return {'deleted_count': 0, 'freed_bytes': 0}

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    deleted_count = 0
    freed_bytes = 0

    for item in output_path.iterdir():
        if not item.name.startswith('bess_backup_'):
            continue

        mtime = datetime.fromtimestamp(item.stat().st_mtime, tz=timezone.utc)
        if mtime < cutoff:
            if item.is_dir():
                size = sum(f.stat().st_size for f in item.rglob('*') if f.is_file())
                shutil.rmtree(item)
            else:
                size = item.stat().st_size
                item.unlink()

            deleted_count += 1
            freed_bytes += size
            print(f"  Deleted old backup: {item.name}")

    return {'deleted_count': deleted_count, 'freed_bytes': freed_bytes}


def main():
    """Main entry point."""
    args = parse_args()

    print("=" * 60)
    print("PostgreSQL Backup")
    print("=" * 60)

    # Create backup
    print()
    print("Creating backup...")
    result = create_backup(
        output_dir=args.output,
        compress=args.compress,
        format=args.format,
        tables=args.tables,
        schema_only=args.schema_only,
        data_only=args.data_only,
    )

    if result['success']:
        print(f"  ✓ Backup created: {result['filename']}")
        print(f"    Path: {result['path']}")
        print(f"    Size: {result['size_bytes'] / 1024 / 1024:.2f} MB")
        print(f"    Duration: {result['duration_seconds']:.1f} seconds")
    else:
        print(f"  ✗ Backup failed: {result['error']}")
        sys.exit(1)

    # Cleanup old backups
    retention_days = int(os.getenv('BACKUP_RETENTION_DAYS', '7'))
    print()
    print(f"Cleaning up backups older than {retention_days} days...")
    cleanup = cleanup_old_backups(args.output, retention_days)
    if cleanup['deleted_count'] > 0:
        print(f"  Deleted {cleanup['deleted_count']} old backups")
        print(f"  Freed {cleanup['freed_bytes'] / 1024 / 1024:.2f} MB")
    else:
        print("  No old backups to delete")

    print()
    print("Backup completed successfully")


if __name__ == '__main__':
    main()

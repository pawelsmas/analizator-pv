#!/usr/bin/env python3
"""
PostgreSQL restore script (v3.3.0 PR5).

Restores BESS PostgreSQL database from backup.

Usage:
    python scripts/db/restore_postgres.py BACKUP_FILE [--no-owner] [--clean]

Environment:
    - DATABASE_URL: PostgreSQL connection URL (required)

WARNING: This will overwrite existing data!
"""

import argparse
import gzip
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Restore PostgreSQL database from backup'
    )
    parser.add_argument(
        'backup_file',
        type=str,
        help='Path to backup file (.dump, .sql, .sql.gz, or directory)'
    )
    parser.add_argument(
        '--no-owner',
        action='store_true',
        help='Skip restoring ownership (useful for different user)'
    )
    parser.add_argument(
        '--clean',
        '-c',
        action='store_true',
        help='Drop objects before creating them'
    )
    parser.add_argument(
        '--if-exists',
        action='store_true',
        help='Use IF EXISTS when dropping objects (with --clean)'
    )
    parser.add_argument(
        '--tables',
        '-t',
        type=str,
        nargs='*',
        help='Specific tables to restore (default: all)'
    )
    parser.add_argument(
        '--schema-only',
        action='store_true',
        help='Restore schema only (no data)'
    )
    parser.add_argument(
        '--data-only',
        action='store_true',
        help='Restore data only (no schema)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )
    return parser.parse_args()


def parse_database_url(url: str) -> dict:
    """Parse DATABASE_URL into components."""
    from urllib.parse import urlparse
    parsed = urlparse(url)

    return {
        'user': parsed.username,
        'password': parsed.password,
        'host': parsed.hostname or 'localhost',
        'port': parsed.port or 5432,
        'database': parsed.path.lstrip('/'),
    }


def detect_backup_format(backup_path: Path) -> str:
    """Detect backup format from file."""
    if backup_path.is_dir():
        return 'directory'

    name = backup_path.name.lower()
    if name.endswith('.sql.gz') or name.endswith('.sql'):
        return 'plain'
    elif name.endswith('.tar'):
        return 'tar'
    else:
        # Assume custom format for .dump
        return 'custom'


def restore_backup(
    backup_file: str,
    no_owner: bool,
    clean: bool,
    if_exists: bool,
    tables: list,
    schema_only: bool,
    data_only: bool,
    dry_run: bool,
) -> dict:
    """
    Restore PostgreSQL backup.

    Returns:
        Dict with: success, duration_seconds, error
    """
    from datetime import datetime, timezone

    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        return {
            'success': False,
            'error': 'DATABASE_URL environment variable is required',
        }

    backup_path = Path(backup_file)
    if not backup_path.exists():
        return {
            'success': False,
            'error': f'Backup file not found: {backup_file}',
        }

    db_config = parse_database_url(database_url)
    format = detect_backup_format(backup_path)

    print(f"  Backup file: {backup_path}")
    print(f"  Detected format: {format}")
    print(f"  Target database: {db_config['database']}@{db_config['host']}")

    if dry_run:
        print()
        print("  [DRY-RUN] Would restore backup to database")
        return {'success': True, 'dry_run': True}

    # Set password in environment
    env = os.environ.copy()
    env['PGPASSWORD'] = db_config['password'] or ''

    start_time = datetime.now(timezone.utc)
    temp_file = None

    try:
        # Handle compressed plain SQL
        if format == 'plain' and backup_path.name.endswith('.gz'):
            print("  Decompressing backup...")
            temp_file = tempfile.NamedTemporaryFile(suffix='.sql', delete=False)
            with gzip.open(backup_path, 'rb') as f_in:
                temp_file.write(f_in.read())
            temp_file.close()
            restore_file = Path(temp_file.name)
        else:
            restore_file = backup_path

        # Build restore command
        if format == 'plain':
            # Use psql for plain SQL
            cmd = [
                'psql',
                '-h', db_config['host'],
                '-p', str(db_config['port']),
                '-U', db_config['user'],
                '-d', db_config['database'],
                '-f', str(restore_file),
            ]
        else:
            # Use pg_restore for custom/directory/tar
            cmd = [
                'pg_restore',
                '-h', db_config['host'],
                '-p', str(db_config['port']),
                '-U', db_config['user'],
                '-d', db_config['database'],
            ]

            if no_owner:
                cmd.append('--no-owner')
            if clean:
                cmd.append('--clean')
            if if_exists:
                cmd.append('--if-exists')
            if schema_only:
                cmd.append('--schema-only')
            elif data_only:
                cmd.append('--data-only')

            if tables:
                for table in tables:
                    cmd.extend(['-t', table])

            cmd.append(str(restore_file))

        print()
        print("  Running restore...")
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=3600,  # 1 hour timeout
        )

        # Cleanup temp file
        if temp_file:
            Path(temp_file.name).unlink()

        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()

        # pg_restore may return non-zero even on success with some warnings
        if result.returncode != 0:
            # Check if it's just warnings
            if 'ERROR' in result.stderr:
                return {
                    'success': False,
                    'duration_seconds': duration,
                    'error': f"Restore failed: {result.stderr}",
                }
            else:
                print(f"  Warning: {result.stderr}")

        return {
            'success': True,
            'duration_seconds': duration,
            'format': format,
        }

    except subprocess.TimeoutExpired:
        return {
            'success': False,
            'error': 'Restore timed out after 1 hour',
        }
    except Exception as e:
        if temp_file:
            try:
                Path(temp_file.name).unlink()
            except Exception:
                pass
        return {
            'success': False,
            'error': str(e),
        }


def main():
    """Main entry point."""
    args = parse_args()

    print("=" * 60)
    print("PostgreSQL Restore")
    print("=" * 60)
    print()
    print("WARNING: This will overwrite existing data!")
    print()

    if not args.dry_run:
        confirm = input("Are you sure you want to proceed? [y/N] ")
        if confirm.lower() != 'y':
            print("Restore cancelled")
            sys.exit(0)

    print()
    print("Restoring backup...")
    result = restore_backup(
        backup_file=args.backup_file,
        no_owner=args.no_owner,
        clean=args.clean,
        if_exists=args.if_exists,
        tables=args.tables,
        schema_only=args.schema_only,
        data_only=args.data_only,
        dry_run=args.dry_run,
    )

    if result['success']:
        if result.get('dry_run'):
            print("  [DRY-RUN] Restore simulation completed")
        else:
            print(f"  ✓ Restore completed")
            print(f"    Duration: {result['duration_seconds']:.1f} seconds")
    else:
        print(f"  ✗ Restore failed: {result['error']}")
        sys.exit(1)

    print()
    print("Restore completed successfully")


if __name__ == '__main__':
    main()

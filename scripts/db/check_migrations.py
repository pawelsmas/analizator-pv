#!/usr/bin/env python3
"""
Check if database migrations are pending (v3.3.0).

Usage:
    python scripts/db/check_migrations.py

Exit codes:
    0 - No pending migrations (or sqlite mode)
    1 - Pending migrations exist
    2 - Error checking migrations

Environment:
    DB_BACKEND - 'sqlite' or 'postgres'
    DATABASE_URL - PostgreSQL connection URL
"""
import os
import sys

# Add service directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch'))


def get_pending_migrations() -> tuple[bool, list[str], str]:
    """
    Check for pending migrations.

    Returns:
        (has_pending, pending_list, error_message)
    """
    try:
        from db_config import DB_BACKEND, DBBackend

        # In SQLite mode, we don't use Alembic migrations
        if DB_BACKEND == DBBackend.SQLITE:
            return False, [], ""

        # For Postgres, check Alembic status
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from alembic.runtime.migration import MigrationContext
        from sqlalchemy import create_engine

        from db_config import get_sync_database_url

        # Get alembic config
        alembic_cfg = Config(os.path.join(
            os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch', 'alembic.ini'
        ))
        alembic_cfg.set_main_option('script_location', os.path.join(
            os.path.dirname(__file__), '..', '..', 'services', 'bess-dispatch', 'alembic'
        ))

        # Get script directory
        script = ScriptDirectory.from_config(alembic_cfg)

        # Get current revision from database
        engine = create_engine(get_sync_database_url())
        with engine.connect() as conn:
            context = MigrationContext.configure(conn)
            current_rev = context.get_current_revision()

        # Get head revision
        head_rev = script.get_current_head()

        if current_rev == head_rev:
            return False, [], ""

        # Get list of pending migrations
        pending = []
        for rev in script.iterate_revisions(head_rev, current_rev):
            if rev.revision != current_rev:
                pending.append(rev.revision)

        return len(pending) > 0, pending, ""

    except Exception as e:
        return False, [], str(e)


def main():
    """Main entry point."""
    print("Checking database migrations...")

    has_pending, pending, error = get_pending_migrations()

    if error:
        print(f"ERROR: Failed to check migrations: {error}")
        sys.exit(2)

    if has_pending:
        print(f"PENDING: {len(pending)} migration(s) need to be applied:")
        for rev in pending:
            print(f"  - {rev}")
        print("\nRun: alembic upgrade head")
        sys.exit(1)
    else:
        print("OK: No pending migrations")
        sys.exit(0)


if __name__ == "__main__":
    main()

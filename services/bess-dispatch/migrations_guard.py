"""
Migrations guard module (v3.3.0).

Provides runtime check for pending migrations.
When DB_MIGRATIONS_REQUIRED=true and migrations are pending,
the API will return 503 Service Unavailable.
"""
import os
from typing import Optional, Tuple

from db_config import DB_BACKEND, DBBackend, DB_MIGRATIONS_REQUIRED, DB_MIGRATIONS_PENDING


def check_migrations_status() -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Check if migrations are up to date.

    Returns:
        (is_ok, current_revision, head_revision)
        is_ok=True means no pending migrations or sqlite mode
    """
    # SQLite mode doesn't use Alembic
    if DB_BACKEND == DBBackend.SQLITE:
        DB_MIGRATIONS_PENDING.set(0)
        return True, None, None

    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from alembic.runtime.migration import MigrationContext
        from sqlalchemy import create_engine

        from db_config import get_sync_database_url

        # Get alembic config
        service_dir = os.path.dirname(os.path.abspath(__file__))
        alembic_cfg = Config(os.path.join(service_dir, 'alembic.ini'))
        alembic_cfg.set_main_option('script_location', os.path.join(service_dir, 'alembic'))

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
            DB_MIGRATIONS_PENDING.set(0)
            return True, current_rev, head_rev
        else:
            DB_MIGRATIONS_PENDING.set(1)
            return False, current_rev, head_rev

    except Exception as e:
        # On error, don't block if not required
        DB_MIGRATIONS_PENDING.set(1)
        return not DB_MIGRATIONS_REQUIRED, None, None


def migrations_required_and_pending() -> bool:
    """
    Check if migrations are required and pending.

    Returns True if app should return 503.
    """
    if not DB_MIGRATIONS_REQUIRED:
        return False

    if DB_BACKEND == DBBackend.SQLITE:
        return False

    is_ok, _, _ = check_migrations_status()
    return not is_ok


# Cached status (checked once at startup)
_migrations_ok: Optional[bool] = None


def check_migrations_at_startup() -> None:
    """Check migrations status at application startup."""
    global _migrations_ok
    _migrations_ok, current, head = check_migrations_status()

    if _migrations_ok:
        print(f"Migrations OK: current={current}, head={head}")
    else:
        print(f"WARNING: Migrations pending! current={current}, head={head}")
        if DB_MIGRATIONS_REQUIRED:
            print("ERROR: DB_MIGRATIONS_REQUIRED=true but migrations are pending!")
            print("Run: alembic upgrade head")


def get_migrations_error_response() -> dict:
    """Get error response body for pending migrations."""
    return {
        "error_code": "DB_MIGRATIONS_PENDING",
        "detail": "Database migrations are pending. Run: alembic upgrade head",
    }

"""
Database session factory (v3.3.0 PR3).

Provides SQLAlchemy session management for both SQLite and PostgreSQL backends.
"""

from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from db_config import get_sync_database_url, DB_BACKEND, DBBackend, DB_CONNECTIONS_OPEN


# Engine configuration
_engine = None
_SessionLocal = None


def get_engine():
    """Get or create the SQLAlchemy engine."""
    global _engine
    if _engine is None:
        url = get_sync_database_url()

        # Configure engine based on backend
        if DB_BACKEND == DBBackend.SQLITE:
            _engine = create_engine(
                url,
                connect_args={"check_same_thread": False},  # SQLite needs this
                echo=False,
            )
        else:
            # PostgreSQL with connection pool
            _engine = create_engine(
                url,
                pool_size=5,
                max_overflow=10,
                pool_pre_ping=True,  # Check connections before use
                echo=False,
            )

    return _engine


def get_session_factory():
    """Get or create the session factory."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=get_engine(),
        )
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency for database sessions.

    Usage:
        @router.get("/items")
        def get_items(db: Session = Depends(get_db)):
            ...
    """
    SessionLocal = get_session_factory()
    db = SessionLocal()
    DB_CONNECTIONS_OPEN.inc()
    try:
        yield db
    finally:
        db.close()
        DB_CONNECTIONS_OPEN.dec()


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """
    Context manager for database sessions.

    Usage:
        with get_db_session() as db:
            result = db.query(User).all()
    """
    SessionLocal = get_session_factory()
    db = SessionLocal()
    DB_CONNECTIONS_OPEN.inc()
    try:
        yield db
    finally:
        db.close()
        DB_CONNECTIONS_OPEN.dec()


def create_tables():
    """Create all tables (for testing/initialization)."""
    from db_models import Base
    engine = get_engine()
    Base.metadata.create_all(bind=engine)


def drop_tables():
    """Drop all tables (for testing)."""
    from db_models import Base
    engine = get_engine()
    Base.metadata.drop_all(bind=engine)

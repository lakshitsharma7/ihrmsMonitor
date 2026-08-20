"""SQLAlchemy engine and session factory.

This module receives an already-resolved database path from
``utils.paths`` - it has no knowledge of *which* operating system produced
that path.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from database.models import Base
from utils.logger import get_logger
from utils.paths import get_database_path

logger = get_logger(__name__)

_engine = None
_SessionFactory: sessionmaker | None = None


def init_database(db_path: Path | str | None = None) -> None:
    """Create the engine, session factory, and tables if they don't exist.

    Args:
        db_path: Optional explicit path to the SQLite file. Primarily used
            by tests to point at an in-memory or temp database. When
            omitted, the platform-appropriate app-data path is used.
    """
    global _engine, _SessionFactory

    resolved_path = str(db_path) if db_path is not None else str(get_database_path())
    logger.info("Initializing database at %s", resolved_path)

    _engine = create_engine(
        f"sqlite:///{resolved_path}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)

    try:
        Base.metadata.create_all(_engine)
    except Exception:  # noqa: BLE001 - we must never crash the app on DB init
        logger.exception("Failed to create database tables")
        raise


def get_session() -> Session:
    """Return a new SQLAlchemy session. Caller is responsible for closing it."""
    if _SessionFactory is None:
        init_database()
    assert _SessionFactory is not None
    return _SessionFactory()


def get_engine():
    """Return the active SQLAlchemy engine (mainly for diagnostics/tests)."""
    if _engine is None:
        init_database()
    return _engine

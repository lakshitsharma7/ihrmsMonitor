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
        # Migrate schema dynamically for SQLite
        with _engine.begin() as conn:
            from sqlalchemy import text
            columns = conn.execute(text("PRAGMA table_info(activity_sessions)")).fetchall()
            column_names = [col[1] for col in columns]
            if "screenshot_path" not in column_names:
                conn.execute(text("ALTER TABLE activity_sessions ADD COLUMN screenshot_path VARCHAR(512)"))
            if "server_session_id" not in column_names:
                conn.execute(text("ALTER TABLE activity_sessions ADD COLUMN server_session_id VARCHAR(100)"))
            if "screenshot_uploaded" not in column_names:
                conn.execute(text("ALTER TABLE activity_sessions ADD COLUMN screenshot_uploaded BOOLEAN NOT NULL DEFAULT 0"))
            if "idle_seconds" not in column_names:
                conn.execute(text("ALTER TABLE activity_sessions ADD COLUMN idle_seconds INTEGER NOT NULL DEFAULT 0"))
            
            # Migrate settings table
            settings_cols = conn.execute(text("PRAGMA table_info(settings)")).fetchall()
            settings_col_names = [col[1] for col in settings_cols]
            if "screenshot_interval_type" not in settings_col_names:
                conn.execute(text("ALTER TABLE settings ADD COLUMN screenshot_interval_type VARCHAR(50) NOT NULL DEFAULT '3_min'"))
            if "screenshot_custom_interval" not in settings_col_names:
                conn.execute(text("ALTER TABLE settings ADD COLUMN screenshot_custom_interval INTEGER NOT NULL DEFAULT 180"))
            if "capture_on_switch" not in settings_col_names:
                conn.execute(text("ALTER TABLE settings ADD COLUMN capture_on_switch BOOLEAN NOT NULL DEFAULT 1"))

            # Sanitize legacy corrupted sessions where duration exceeds 2 hours
            # caused by older builds extending sessions across offline/shutdown time
            conn.execute(text(
                "UPDATE activity_sessions "
                "SET duration_seconds = 300, ended_at = datetime(started_at, '+300 seconds') "
                "WHERE duration_seconds > 7200"
            ))
        _create_default_admin_if_needed()
        _create_default_settings_if_needed()
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


def _create_default_admin_if_needed() -> None:
    """Create a default admin user if the users table is completely empty."""
    session = get_session()
    try:
        from database.models import User
        from sqlalchemy import select
        from utils.security import hash_password
        import os
        from pathlib import Path

        stmt = select(User).limit(1)
        any_user = session.execute(stmt).scalars().first()
        if any_user is None:
            # Try to load from a local .env file in project root if it exists
            env_vars = {}
            try:
                root_path = Path(__file__).resolve().parents[2]
                env_path = root_path / ".env"
                if env_path.exists():
                    for line in env_path.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            k, v = line.split("=", 1)
                            env_vars[k.strip()] = v.strip().strip('"').strip("'")
            except Exception:
                logger.exception("Failed to parse .env file")

            admin_username = env_vars.get("DEFAULT_ADMIN_EMAIL") or os.environ.get(
                "DEFAULT_ADMIN_EMAIL", "admin@indovision.local"
            )
            temp_password = env_vars.get("DEFAULT_ADMIN_PASSWORD") or os.environ.get(
                "DEFAULT_ADMIN_PASSWORD", "admin@123"
            )

            hashed = hash_password(temp_password)
            admin_user = User(
                username=admin_username,
                password_hash=hashed,
                role="Admin",
                is_active=True,
            )
            session.add(admin_user)
            session.commit()

            # Log and print the credentials
            logger.warning("==================================================")
            logger.warning("CREATED DEFAULT ADMIN ACCOUNT:")
            logger.warning("Username: %s", admin_username)
            logger.warning("Password: %s", temp_password)
            logger.warning("==================================================")

            print("\n" + "=" * 50)
            print("CREATED DEFAULT ADMIN ACCOUNT:")
            print(f"Username: {admin_username}")
            print(f"Password: {temp_password}")
            print("=" * 50 + "\n")
    except Exception:
        session.rollback()
        logger.exception("Failed to create default admin user")
    finally:
        session.close()


def _create_default_settings_if_needed() -> None:
    """Create default settings record if empty."""
    session = get_session()
    try:
        from database.models import Settings
        from sqlalchemy import select
        from config.settings import (
            DEFAULT_IDLE_THRESHOLD_SECONDS,
            DEFAULT_START_WITH_SYSTEM,
            DEFAULT_TRACKING_ENABLED,
            DEFAULT_TRACK_WINDOW_TITLES,
        )
        stmt = select(Settings).limit(1)
        record = session.execute(stmt).scalars().first()
        if record is None:
            record = Settings(
                idle_threshold=DEFAULT_IDLE_THRESHOLD_SECONDS,
                start_with_system=DEFAULT_START_WITH_SYSTEM,
                tracking_enabled=DEFAULT_TRACKING_ENABLED,
                track_window_titles=DEFAULT_TRACK_WINDOW_TITLES,
                screenshot_interval_type="3_min",
                screenshot_custom_interval=180,
                capture_on_switch=True,
            )
            session.add(record)
            session.commit()
            logger.info("Created default settings record with updated defaults.")
    except Exception:
        session.rollback()
        logger.exception("Failed to initialize default settings")
    finally:
        session.close()


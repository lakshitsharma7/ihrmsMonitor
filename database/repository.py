"""Data-access layer. All SQL/ORM query logic lives here.

Higher layers (services, tracker) never issue SQLAlchemy queries directly -
they call into an ``ActivityRepository`` or ``SettingsRepository`` instance.
This keeps business logic testable without a GUI and keeps persistence
concerns in one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from config.settings import (
    DEFAULT_IDLE_THRESHOLD_SECONDS,
    DEFAULT_START_WITH_SYSTEM,
    DEFAULT_TRACK_WINDOW_TITLES,
    DEFAULT_TRACKING_ENABLED,
)
from database.models import ActivitySession, Settings
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ApplicationUsage:
    """Aggregated usage for a single application."""

    application_name: str
    total_seconds: int


class ActivityRepository:
    """CRUD and aggregation queries for ``ActivitySession`` rows."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create_session(
        self,
        application_name: str,
        process_id: int | None,
        window_title: str | None,
        started_at: datetime,
    ) -> ActivitySession:
        """Insert and return a new, still-open activity session."""
        try:
            record = ActivitySession(
                application_name=application_name,
                process_id=process_id,
                window_title=window_title,
                started_at=started_at,
                ended_at=None,
                duration_seconds=0,
            )
            self._session.add(record)
            self._session.commit()
            self._session.refresh(record)
            return record
        except Exception:  # noqa: BLE001
            self._session.rollback()
            logger.exception("Failed to create activity session for %s", application_name)
            raise

    def update_session_window_title(self, session_id: int, window_title: str | None) -> None:
        """Update the window title of an in-progress session in place."""
        try:
            record = self._session.get(ActivitySession, session_id)
            if record is None:
                logger.warning("Attempted to update missing session id=%s", session_id)
                return
            record.window_title = window_title
            self._session.commit()
        except Exception:  # noqa: BLE001
            self._session.rollback()
            logger.exception("Failed to update window title for session id=%s", session_id)

    def close_session(self, session_id: int, ended_at: datetime) -> ActivitySession | None:
        """Finalize a session's end time and duration."""
        try:
            record = self._session.get(ActivitySession, session_id)
            if record is None:
                logger.warning("Attempted to close missing session id=%s", session_id)
                return None
            record.ended_at = ended_at
            started = record.started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            if ended_at.tzinfo is None:
                ended_at = ended_at.replace(tzinfo=timezone.utc)
            duration = max(0, int((ended_at - started).total_seconds()))
            record.duration_seconds = duration
            self._session.commit()
            self._session.refresh(record)
            return record
        except Exception:  # noqa: BLE001
            self._session.rollback()
            logger.exception("Failed to close session id=%s", session_id)
            return None

    def get_sessions_between(self, start: datetime, end: datetime) -> list[ActivitySession]:
        """Return all sessions that started within [start, end), oldest first."""
        stmt = (
            select(ActivitySession)
            .where(ActivitySession.started_at >= start)
            .where(ActivitySession.started_at < end)
            .order_by(ActivitySession.started_at.asc())
        )
        return list(self._session.execute(stmt).scalars().all())

    def get_sessions_for_day(self, day: datetime) -> list[ActivitySession]:
        """Return all sessions that started on the given calendar day (local)."""
        start = datetime.combine(day.date(), time.min, tzinfo=day.tzinfo)
        end = datetime.combine(day.date(), time.max, tzinfo=day.tzinfo)
        return self.get_sessions_between(start, end)

    def get_total_duration_seconds(self, start: datetime, end: datetime) -> int:
        """Return the sum of durations for closed sessions in the window."""
        sessions = self.get_sessions_between(start, end)
        return sum(s.duration_seconds for s in sessions if s.ended_at is not None)

    def get_application_usage(self, start: datetime, end: datetime) -> list[ApplicationUsage]:
        """Return usage grouped by application, sorted by total time desc."""
        sessions = self.get_sessions_between(start, end)
        totals: dict[str, int] = {}
        for s in sessions:
            if s.ended_at is None:
                continue
            totals[s.application_name] = totals.get(s.application_name, 0) + s.duration_seconds
        usage = [ApplicationUsage(name, seconds) for name, seconds in totals.items()]
        usage.sort(key=lambda u: u.total_seconds, reverse=True)
        return usage

    def get_open_session(self) -> ActivitySession | None:
        """Return the most recent session that has not yet been closed, if any."""
        stmt = (
            select(ActivitySession)
            .where(ActivitySession.ended_at.is_(None))
            .order_by(ActivitySession.started_at.desc())
            .limit(1)
        )
        return self._session.execute(stmt).scalars().first()


class SettingsRepository:
    """CRUD for the single-row ``Settings`` table."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_or_create(self) -> Settings:
        stmt = select(Settings).limit(1)
        record = self._session.execute(stmt).scalars().first()
        if record is not None:
            return record

        record = Settings(
            idle_threshold=DEFAULT_IDLE_THRESHOLD_SECONDS,
            start_with_system=DEFAULT_START_WITH_SYSTEM,
            tracking_enabled=DEFAULT_TRACKING_ENABLED,
            track_window_titles=DEFAULT_TRACK_WINDOW_TITLES,
        )
        self._session.add(record)
        self._session.commit()
        self._session.refresh(record)
        return record

    def update(self, **fields) -> Settings:
        record = self.get_or_create()
        for key, value in fields.items():
            if not hasattr(record, key):
                raise AttributeError(f"Settings has no field {key!r}")
            setattr(record, key, value)
        self._session.commit()
        self._session.refresh(record)
        return record

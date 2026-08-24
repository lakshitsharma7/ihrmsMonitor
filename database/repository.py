"""Data-access layer.

All SQL/ORM query logic lives here.

Higher layers such as services, tracker, and API should use
ActivityRepository or SettingsRepository instead of issuing
SQLAlchemy queries directly.
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


# ==============================================================
# APPLICATION USAGE
# ==============================================================


@dataclass
class ApplicationUsage:
    """Aggregated usage for a single application."""

    application_name: str
    total_seconds: int


# ==============================================================
# ACTIVITY REPOSITORY
# ==============================================================


class ActivityRepository:
    """CRUD and aggregation operations for activity sessions."""

    def __init__(
        self,
        session: Session,
    ) -> None:
        self._session = session

    # ==========================================================
    # CREATE SESSION
    # ==========================================================

    def create_session(
        self,
        application_name: str,
        process_id: int | None,
        window_title: str | None,
        started_at: datetime,
    ) -> ActivitySession:
        """Create a new open activity session."""

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

            logger.exception(
                "Failed to create activity session for %s",
                application_name,
            )

            raise

    # ==========================================================
    # UPDATE WINDOW TITLE
    # ==========================================================

    def update_session_window_title(
        self,
        session_id: int,
        window_title: str | None,
    ) -> None:
        """Update the window title of an active session."""

        try:
            record = self._session.get(
                ActivitySession,
                session_id,
            )

            if record is None:
                logger.warning(
                    "Attempted to update missing session id=%s",
                    session_id,
                )
                return

            record.window_title = window_title

            self._session.commit()

        except Exception:  # noqa: BLE001

            self._session.rollback()

            logger.exception(
                "Failed to update window title for session id=%s",
                session_id,
            )

    # ==========================================================
    # CLOSE SESSION
    # ==========================================================

    def close_session(
        self,
        session_id: int,
        ended_at: datetime,
    ) -> ActivitySession | None:
        """Close an activity session and calculate its duration."""

        try:
            record = self._session.get(
                ActivitySession,
                session_id,
            )

            if record is None:
                logger.warning(
                    "Attempted to close missing session id=%s",
                    session_id,
                )
                return None

            record.ended_at = ended_at

            started = record.started_at

            if started.tzinfo is None:
                started = started.replace(
                    tzinfo=timezone.utc
                )

            if ended_at.tzinfo is None:
                ended_at = ended_at.replace(
                    tzinfo=timezone.utc
                )

            duration = max(
                0,
                int(
                    (
                        ended_at - started
                    ).total_seconds()
                ),
            )

            record.duration_seconds = duration

            self._session.commit()
            self._session.refresh(record)

            return record

        except Exception:  # noqa: BLE001

            self._session.rollback()

            logger.exception(
                "Failed to close session id=%s",
                session_id,
            )

            return None

    # ==========================================================
    # GET SESSIONS BETWEEN
    # ==========================================================

    def get_sessions_between(
        self,
        start: datetime,
        end: datetime,
    ) -> list[ActivitySession]:
        """
        Return activity sessions belonging to the requested
        time window.

        Closed sessions are returned only when they overlap
        the requested window.

        For open sessions, only the latest open session is
        considered active. This prevents stale sessions from
        previous tracker runs from appearing in the API.
        """

        # ------------------------------------------------------
        # Find the newest open session.
        # ------------------------------------------------------

        latest_open_stmt = (
            select(ActivitySession.id)
            .where(
                ActivitySession.ended_at.is_(None)
            )
            .order_by(
                ActivitySession.started_at.desc()
            )
            .limit(1)
        )

        latest_open_session_id = (
            self._session
            .execute(latest_open_stmt)
            .scalar_one_or_none()
        )

        # ------------------------------------------------------
        # Closed sessions:
        #
        # started_at < end
        # ended_at > start
        #
        # OR
        #
        # Latest open session.
        # ------------------------------------------------------

        stmt = (
            select(ActivitySession)
            .where(
                ActivitySession.started_at < end
            )
            .where(
                (
                    (
                        ActivitySession.ended_at.is_not(None)
                    )
                    & (
                        ActivitySession.ended_at > start
                    )
                )
                |
                (
                    (
                        ActivitySession.ended_at.is_(None)
                    )
                    & (
                        ActivitySession.id
                        == latest_open_session_id
                    )
                )
            )
            .order_by(
                ActivitySession.started_at.asc()
            )
        )

        return list(
            self._session
            .execute(stmt)
            .scalars()
            .all()
        )

    # ==========================================================
    # GET SESSIONS FOR DAY
    # ==========================================================

    def get_sessions_for_day(
        self,
        day: datetime,
    ) -> list[ActivitySession]:
        """Return sessions for a given calendar day."""

        start = datetime.combine(
            day.date(),
            time.min,
            tzinfo=day.tzinfo,
        )

        end = datetime.combine(
            day.date(),
            time.max,
            tzinfo=day.tzinfo,
        )

        return self.get_sessions_between(
            start,
            end,
        )

    # ==========================================================
    # TOTAL DURATION
    # ==========================================================

    def get_total_duration_seconds(
        self,
        start: datetime,
        end: datetime,
    ) -> int:
        """Return total duration of closed sessions."""

        sessions = self.get_sessions_between(
            start,
            end,
        )

        return sum(
            session.duration_seconds
            for session in sessions
            if session.ended_at is not None
        )

    # ==========================================================
    # APPLICATION USAGE
    # ==========================================================

    def get_application_usage(
        self,
        start: datetime,
        end: datetime,
    ) -> list[ApplicationUsage]:
        """Return usage grouped by application."""

        sessions = self.get_sessions_between(
            start,
            end,
        )

        totals: dict[str, int] = {}

        for session in sessions:

            if session.ended_at is None:
                continue

            application_name = (
                session.application_name
            )

            totals[application_name] = (
                totals.get(
                    application_name,
                    0,
                )
                + session.duration_seconds
            )

        usage = [
            ApplicationUsage(
                application_name=name,
                total_seconds=seconds,
            )
            for name, seconds in totals.items()
        ]

        usage.sort(
            key=lambda item: item.total_seconds,
            reverse=True,
        )

        return usage

    # ==========================================================
    # GET OPEN SESSION
    # ==========================================================

    def get_open_session(
        self,
    ) -> ActivitySession | None:
        """Return the newest currently open session."""

        stmt = (
            select(ActivitySession)
            .where(
                ActivitySession.ended_at.is_(None)
            )
            .order_by(
                ActivitySession.started_at.desc()
            )
            .limit(1)
        )

        return (
            self._session
            .execute(stmt)
            .scalars()
            .first()
        )


# ==============================================================
# SETTINGS REPOSITORY
# ==============================================================


class SettingsRepository:
    """CRUD operations for the Settings table."""

    def __init__(
        self,
        session: Session,
    ) -> None:
        self._session = session

    # ==========================================================
    # GET OR CREATE
    # ==========================================================

    def get_or_create(
        self,
    ) -> Settings:
        """Return existing settings or create defaults."""

        stmt = (
            select(Settings)
            .limit(1)
        )

        record = (
            self._session
            .execute(stmt)
            .scalars()
            .first()
        )

        if record is not None:
            return record

        record = Settings(
            idle_threshold=(
                DEFAULT_IDLE_THRESHOLD_SECONDS
            ),
            start_with_system=(
                DEFAULT_START_WITH_SYSTEM
            ),
            tracking_enabled=(
                DEFAULT_TRACKING_ENABLED
            ),
            track_window_titles=(
                DEFAULT_TRACK_WINDOW_TITLES
            ),
        )

        self._session.add(record)

        self._session.commit()

        self._session.refresh(record)

        return record

    # ==========================================================
    # UPDATE
    # ==========================================================

    def update(
        self,
        **fields,
    ) -> Settings:
        """Update settings fields."""

        record = self.get_or_create()

        for key, value in fields.items():

            if not hasattr(
                record,
                key,
            ):
                raise AttributeError(
                    f"Settings has no field {key!r}"
                )

            setattr(
                record,
                key,
                value,
            )

        self._session.commit()

        self._session.refresh(record)

        return record
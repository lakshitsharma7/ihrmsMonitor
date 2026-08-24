"""Data-access layer.

All SQL/ORM query logic lives here.

Higher layers such as services, tracker, and API should use
ActivityRepository or SettingsRepository instead of issuing
SQLAlchemy queries directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone

from sqlalchemy import func, select
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
# UTC HELPER
# ==============================================================


def _to_utc(value: datetime) -> datetime:
    """
    Normalize a datetime to UTC.

    SQLite can return naive datetime values even when the model
    uses DateTime(timezone=True).

    Naive values are treated as UTC.
    """

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


# ==============================================================
# APPLICATION USAGE
# ==============================================================


@dataclass
class ApplicationUsage:
    """Aggregated usage for a single application."""

    application_name: str
    total_seconds: int


# ==============================================================
# PAGINATED RESULT
# ==============================================================


@dataclass
class PaginatedSessions:
    """Paginated activity-session result."""

    items: list[ActivitySession]
    page: int
    page_size: int
    total: int
    has_next: bool
    has_previous: bool
    total_pages: int


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
            started_at = _to_utc(started_at)

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

            logger.info(
                "Created activity session: "
                "id=%s app=%s pid=%s started_at=%s",
                record.id,
                record.application_name,
                record.process_id,
                record.started_at,
            )

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
        """Update the window title of an activity session."""

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

            ended_at = _to_utc(ended_at)
            started_at = _to_utc(record.started_at)

            if ended_at < started_at:
                ended_at = started_at

            record.ended_at = ended_at

            record.duration_seconds = max(
                0,
                int(
                    (
                        ended_at - started_at
                    ).total_seconds()
                ),
            )

            self._session.commit()
            self._session.refresh(record)

            logger.info(
                "Closed activity session: "
                "id=%s app=%s ended_at=%s duration=%ss",
                record.id,
                record.application_name,
                record.ended_at,
                record.duration_seconds,
            )

            return record

        except Exception:  # noqa: BLE001
            self._session.rollback()

            logger.exception(
                "Failed to close session id=%s",
                session_id,
            )

            return None

    # ==========================================================
    # CLOSE ALL STALE OPEN SESSIONS
    # ==========================================================

    def close_stale_sessions(
        self,
        ended_at: datetime,
    ) -> int:
        """Close every ActivitySession whose ended_at is NULL."""

        try:
            ended_at = _to_utc(ended_at)

            stmt = (
                select(ActivitySession)
                .where(
                    ActivitySession.ended_at.is_(None)
                )
            )

            stale_sessions = list(
                self._session
                .execute(stmt)
                .scalars()
                .all()
            )

            if not stale_sessions:
                logger.info(
                    "No stale open activity sessions found"
                )
                return 0

            closed_count = 0

            for record in stale_sessions:

                started_at = _to_utc(
                    record.started_at
                )

                effective_end = max(
                    ended_at,
                    started_at,
                )

                record.ended_at = effective_end

                record.duration_seconds = max(
                    0,
                    int(
                        (
                            effective_end - started_at
                        ).total_seconds()
                    ),
                )

                closed_count += 1

                logger.warning(
                    "Closing stale activity session: "
                    "id=%s app=%s started_at=%s",
                    record.id,
                    record.application_name,
                    record.started_at,
                )

            self._session.commit()

            logger.info(
                "Closed %s stale open activity sessions",
                closed_count,
            )

            return closed_count

        except Exception:  # noqa: BLE001
            self._session.rollback()

            logger.exception(
                "Failed to close stale activity sessions"
            )

            return 0

    # ==========================================================
    # GET SESSIONS BETWEEN
    # ==========================================================

    def get_sessions_between(
        self,
        start: datetime,
        end: datetime,
    ) -> list[ActivitySession]:
        """
        Return activity sessions overlapping the requested interval.
        """

        start = _to_utc(start)
        end = _to_utc(end)

        if start >= end:
            return []

        stmt = (
            select(ActivitySession)
            .where(
                ActivitySession.started_at < end
            )
            .where(
                (
                    ActivitySession.ended_at.is_(None)
                )
                |
                (
                    ActivitySession.ended_at > start
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
    # GET ALL SESSIONS
    # ==========================================================

    def get_all_sessions(
        self,
    ) -> list[ActivitySession]:
        """
        Return ALL activity sessions stored in the database.

        No time filtering is applied.

        This is used by:

            GET /activity/all
        """

        stmt = (
            select(ActivitySession)
            .order_by(
                ActivitySession.started_at.desc()
            )
        )

        sessions = list(
            self._session
            .execute(stmt)
            .scalars()
            .all()
        )

        logger.info(
            "Fetched all activity sessions: %d",
            len(sessions),
        )

        return sessions

    # ==========================================================
    # GET ALL SESSIONS - PAGINATED
    # ==========================================================

    def get_sessions_paginated(
        self,
        page: int = 1,
        page_size: int = 50,
        newest_first: bool = True,
    ) -> PaginatedSessions:
        """
        Return all activity sessions using pagination.

        This method does NOT apply the 5-minute sync window.
        """

        page = max(
            1,
            int(page),
        )

        page_size = max(
            1,
            min(
                int(page_size),
                500,
            ),
        )

        # ------------------------------------------------------
        # Count total records.
        # ------------------------------------------------------

        count_stmt = select(
            func.count(ActivitySession.id)
        )

        total = (
            self._session
            .execute(count_stmt)
            .scalar_one()
        )

        # ------------------------------------------------------
        # Calculate pagination.
        # ------------------------------------------------------

        total_pages = (
            (total + page_size - 1) // page_size
            if total > 0
            else 0
        )

        offset = (
            (page - 1) * page_size
        )

        # ------------------------------------------------------
        # Ordering.
        # ------------------------------------------------------

        if newest_first:
            order_clause = (
                ActivitySession.started_at.desc()
            )
        else:
            order_clause = (
                ActivitySession.started_at.asc()
            )

        # ------------------------------------------------------
        # Query.
        # ------------------------------------------------------

        stmt = (
            select(ActivitySession)
            .order_by(order_clause)
            .offset(offset)
            .limit(page_size)
        )

        items = list(
            self._session
            .execute(stmt)
            .scalars()
            .all()
        )

        has_previous = page > 1
        has_next = page < total_pages

        logger.info(
            "Fetched activity page: "
            "page=%s page_size=%s total=%s items=%s",
            page,
            page_size,
            total,
            len(items),
        )

        return PaginatedSessions(
            items=items,
            page=page,
            page_size=page_size,
            total=total,
            has_next=has_next,
            has_previous=has_previous,
            total_pages=total_pages,
        )

    # ==========================================================
    # COUNT SESSIONS
    # ==========================================================

    def count_sessions(
        self,
    ) -> int:
        """Return the total number of activity sessions."""

        stmt = select(
            func.count(ActivitySession.id)
        )

        return int(
            self._session
            .execute(stmt)
            .scalar_one()
        )

    # ==========================================================
    # GET SESSIONS FOR DAY
    # ==========================================================

    def get_sessions_for_day(
        self,
        day: datetime,
    ) -> list[ActivitySession]:
        """Return sessions for a given UTC calendar day."""

        day = _to_utc(day)

        start = datetime.combine(
            day.date(),
            time.min,
            tzinfo=timezone.utc,
        )

        end = datetime.combine(
            day.date(),
            time.max,
            tzinfo=timezone.utc,
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
        """Return the newest currently-open session."""

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
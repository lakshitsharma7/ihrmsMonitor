"""Dashboard calculations and activity data service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone

from database.repository import (
    ActivityRepository,
    ApplicationUsage,
)


@dataclass
class TimelineEntry:
    """A single activity session for the dashboard timeline."""

    started_at: datetime
    application_name: str
    window_title: str | None
    duration_seconds: int
    process_id: int | None


class ActivityService:
    """Read-side business logic for the dashboard."""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    def _repo(
        self,
        db_session,
    ) -> ActivityRepository:
        """Create an activity repository."""

        return ActivityRepository(
            db_session
        )

    def get_today_total_seconds(
        self,
        now: datetime | None = None,
    ) -> int:
        """Return today's total tracked seconds."""

        now = now or datetime.now(
            timezone.utc
        )

        start = datetime.combine(
            now.date(),
            time.min,
            tzinfo=now.tzinfo,
        )

        end = datetime.combine(
            now.date(),
            time.max,
            tzinfo=now.tzinfo,
        )

        db_session = self._session_factory()

        try:
            return self._repo(
                db_session
            ).get_total_duration_seconds(
                start,
                end,
            )
        finally:
            db_session.close()

    def get_today_application_usage(
        self,
        now: datetime | None = None,
    ) -> list[ApplicationUsage]:
        """Return today's application usage."""

        now = now or datetime.now(
            timezone.utc
        )

        start = datetime.combine(
            now.date(),
            time.min,
            tzinfo=now.tzinfo,
        )

        end = datetime.combine(
            now.date(),
            time.max,
            tzinfo=now.tzinfo,
        )

        db_session = self._session_factory()

        try:
            return self._repo(
                db_session
            ).get_application_usage(
                start,
                end,
            )
        finally:
            db_session.close()

    def get_today_timeline(
        self,
        now: datetime | None = None,
    ) -> list[TimelineEntry]:
        """
        Return today's activity sessions.

        Each database session becomes one TimelineEntry,
        including its PID.
        """

        now = now or datetime.now(
            timezone.utc
        )

        start = datetime.combine(
            now.date(),
            time.min,
            tzinfo=now.tzinfo,
        )

        end = datetime.combine(
            now.date(),
            time.max,
            tzinfo=now.tzinfo,
        )

        db_session = self._session_factory()

        try:
            sessions = (
                self._repo(
                    db_session
                ).get_sessions_between(
                    start,
                    end,
                )
            )

            return [
                TimelineEntry(
                    started_at=session.started_at,
                    application_name=session.application_name,
                    window_title=session.window_title,
                    duration_seconds=session.duration_seconds,
                    process_id=session.process_id,
                )
                for session in sessions
            ]

        finally:
            db_session.close()

    @staticmethod
    def format_duration(
        total_seconds: int,
    ) -> str:
        """
        Format seconds for display.

        Examples:

            0   -> 0s
            5   -> 5s
            45  -> 45s
            60  -> 1m
            65  -> 1m 5s
            125 -> 2m 5s
            3600 -> 1h
            3665 -> 1h 1m
        """

        total_seconds = max(
            0,
            int(total_seconds),
        )

        hours, remainder = divmod(
            total_seconds,
            3600,
        )

        minutes, seconds = divmod(
            remainder,
            60,
        )

        if hours:
            if minutes:
                return f"{hours}h {minutes}m"

            return f"{hours}h"

        if minutes:
            if seconds:
                return f"{minutes}m {seconds}s"

            return f"{minutes}m"

        return f"{seconds}s"
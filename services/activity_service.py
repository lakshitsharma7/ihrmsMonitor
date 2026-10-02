"""Dashboard calculations and activity data service."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from database.repository import (
    ActivityRepository,
    ApplicationUsage,
)

logger = logging.getLogger(__name__)


@dataclass
class TimelineEntry:
    """A single activity session for the dashboard timeline."""

    started_at: datetime
    application_name: str
    window_title: str | None
    duration_seconds: int
    process_id: int | None
    idle_seconds: int = 0


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

    @staticmethod
    def _current_employee_id() -> str | None:
        try:
            from services.session_service import SessionService
            user = SessionService().current_user
            if user:
                return user.employee_id or user.indo_code or user.username or None
            from services.secure_session import SessionStore
            saved = SessionStore().load_session()
            if saved:
                return saved.get("employee_id") or saved.get("indo_code") or saved.get("username") or None
            return None
        except Exception:
            return None

    def save_daily_active_seconds(
        self,
        target_date: date,
        seconds: int,
        employee_id: str | None = None,
    ) -> None:
        """Persist accumulated active tracked seconds for a specific calendar date.

        Saves both date-scoped and user-scoped keys in persistent storage and updates
        the active today counter when target_date is today.
        """
        try:
            from services.secure_session import SessionStore
            store = SessionStore()
            date_str = str(target_date)
            sec_int = max(0, int(seconds))

            # Date-scoped key (retained across days as historical data)
            store.settings.setValue(f"dashboard/daily_active_seconds/{date_str}", sec_int)

            # Optional user-scoped key if employee_id is available
            emp_id = employee_id or self._current_employee_id()
            if emp_id:
                store.settings.setValue(
                    f"dashboard/user_daily_active_seconds/{emp_id}/{date_str}",
                    sec_int,
                )

            # Backward compatibility for today's date
            local_now = datetime.now().astimezone().date()
            if target_date == local_now:
                store.settings.setValue("dashboard/today_total_seconds", sec_int)
                store.settings.setValue("dashboard/today_date", date_str)
        except Exception as err:
            logger.debug("save_daily_active_seconds failed: %s", err)

    def get_persisted_daily_active_seconds(
        self,
        target_date: date,
        employee_id: str | None = None,
    ) -> int:
        """Retrieve persisted active tracked seconds for a given calendar date."""
        try:
            from services.secure_session import SessionStore
            store = SessionStore()
            date_str = str(target_date)

            # 1. User-scoped check if employee_id is available
            emp_id = employee_id or self._current_employee_id()
            if emp_id:
                user_val = store.settings.value(
                    f"dashboard/user_daily_active_seconds/{emp_id}/{date_str}"
                )
                if user_val is not None:
                    return max(0, int(user_val))

            # 2. General date-scoped key
            val = store.settings.value(f"dashboard/daily_active_seconds/{date_str}")
            if val is not None:
                return max(0, int(val))

            # 3. Fallback to legacy today key if target_date matches
            saved_date = store.settings.value("dashboard/today_date")
            if saved_date and str(saved_date) == date_str:
                legacy_val = store.settings.value("dashboard/today_total_seconds")
                if legacy_val is not None:
                    return max(0, int(legacy_val))

            return 0
        except Exception as err:
            logger.debug("get_persisted_daily_active_seconds failed: %s", err)
            return 0

    def get_day_total_seconds(
        self,
        target_date: date,
    ) -> int:
        """Return total active tracked seconds for a given local calendar date.

        Computes the exact local day bounds (00:00:00 to 23:59:59.999999)
        and converts to UTC to query the database, combining with locally
        persisted daily active time to guarantee accuracy across restarts.
        """
        local_now = datetime.now().astimezone()
        local_tz = local_now.tzinfo

        start_local = datetime.combine(
            target_date,
            time.min,
            tzinfo=local_tz,
        )

        end_local = datetime.combine(
            target_date,
            time.max,
            tzinfo=local_tz,
        )

        start_utc = start_local.astimezone(timezone.utc)
        end_utc = end_local.astimezone(timezone.utc)

        db_session = self._session_factory()
        try:
            db_total = self._repo(
                db_session
            ).get_total_duration_seconds(
                start_utc,
                end_utc,
                employee_id=self._current_employee_id(),
            )
        finally:
            db_session.close()

        persisted_s = self.get_persisted_daily_active_seconds(target_date)
        return max(db_total, persisted_s)

    def get_today_total_seconds(
        self,
        now: datetime | None = None,
    ) -> int:
        """Return today's total tracked seconds based on local calendar day.

        Persists across laptop and application restarts and automatically
        resets when the local calendar date changes.
        """
        if now is None:
            local_now = datetime.now().astimezone()
            target_date = local_now.date()
        else:
            target_date = now.astimezone().date() if now.tzinfo else now.date()

        return self.get_day_total_seconds(target_date)

    def get_today_total_idle_seconds(
        self,
        now: datetime | None = None,
    ) -> int:
        """Return today's total idle seconds based on local calendar day."""
        if now is None:
            local_now = datetime.now().astimezone()
            target_date = local_now.date()
        else:
            target_date = now.astimezone().date() if now.tzinfo else now.date()

        local_now = datetime.now().astimezone()
        local_tz = local_now.tzinfo

        start_local = datetime.combine(
            target_date,
            time.min,
            tzinfo=local_tz,
        )

        end_local = datetime.combine(
            target_date,
            time.max,
            tzinfo=local_tz,
        )

        start_utc = start_local.astimezone(timezone.utc)
        end_utc = end_local.astimezone(timezone.utc)

        db_session = self._session_factory()
        try:
            return self._repo(
                db_session
            ).get_total_idle_seconds(
                start_utc,
                end_utc,
                employee_id=self._current_employee_id(),
            )
        finally:
            db_session.close()

    @staticmethod
    def format_hours_minutes(total_seconds: int) -> str:
        """Format total seconds into hours and minutes, e.g. '7h 25m', '0h 0m'."""
        total_seconds = max(0, int(total_seconds))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        return f"{hours}h {minutes}m"

    def get_weekly_timeline_data(self) -> list[dict]:
        """
        Return the 7-day timeline data for the current week (Monday through Sunday).

        Each item contains:
            day_name: str (e.g. "Monday")
            short_day: str (e.g. "Mon")
            date_str: str (e.g. "01 Sep")
            date_obj: date object
            total_seconds: int
            total_hours: float
            formatted_time: str (e.g. "7h 25m")
            display_line: str (e.g. "Monday — 01 Sep — 7h 25m")
            is_today: bool
            is_future: bool
        """
        local_now = datetime.now().astimezone()
        today = local_now.date()

        # Monday of current week (weekday() is 0 for Monday)
        monday = today - timedelta(days=today.weekday())

        week_data = []
        for offset in range(7):
            day_date = monday + timedelta(days=offset)
            is_today = (day_date == today)
            is_future = (day_date > today)

            if is_future:
                total_seconds = 0
            else:
                total_seconds = self.get_day_total_seconds(day_date)

            day_name = day_date.strftime("%A")
            date_str = day_date.strftime("%d %b")
            formatted_time = self.format_hours_minutes(total_seconds)
            display_line = f"{day_name} — {date_str} — {formatted_time}"

            week_data.append({
                "day_name": day_name,
                "short_day": day_date.strftime("%a"),
                "date_str": date_str,
                "date_obj": day_date,
                "total_seconds": total_seconds,
                "total_hours": round(total_seconds / 3600.0, 2),
                "formatted_time": formatted_time,
                "display_line": display_line,
                "is_today": is_today,
                "is_future": is_future,
            })

        return week_data

    def get_today_application_usage(
        self,
        now: datetime | None = None,
    ) -> list[ApplicationUsage]:
        """Return today's application usage."""

        if now is None:
            local_now = datetime.now().astimezone()
            target_date = local_now.date()
        else:
            local_now = now.astimezone() if now.tzinfo else now.replace(tzinfo=timezone.utc).astimezone()
            target_date = local_now.date()

        local_tz = local_now.tzinfo

        start_local = datetime.combine(
            target_date,
            time.min,
            tzinfo=local_tz,
        )

        end_local = datetime.combine(
            target_date,
            time.max,
            tzinfo=local_tz,
        )

        start = start_local.astimezone(timezone.utc)
        end = end_local.astimezone(timezone.utc)

        db_session = self._session_factory()

        try:
            return self._repo(
                db_session
            ).get_application_usage(
                start,
                end,
                employee_id=self._current_employee_id(),
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

        if now is None:
            local_now = datetime.now().astimezone()
            target_date = local_now.date()
        else:
            local_now = now.astimezone() if now.tzinfo else now.replace(tzinfo=timezone.utc).astimezone()
            target_date = local_now.date()

        local_tz = local_now.tzinfo

        start_local = datetime.combine(
            target_date,
            time.min,
            tzinfo=local_tz,
        )

        end_local = datetime.combine(
            target_date,
            time.max,
            tzinfo=local_tz,
        )

        start = start_local.astimezone(timezone.utc)
        end = end_local.astimezone(timezone.utc)

        db_session = self._session_factory()

        try:
            sessions = (
                self._repo(
                    db_session
                ).get_sessions_between(
                    start,
                    end,
                    employee_id=self._current_employee_id(),
                )
            )

            now_utc = datetime.now(timezone.utc)
            entries = []
            for session in sessions:
                if session.ended_at is None:
                    s_start = session.started_at
                    if s_start.tzinfo is None:
                        s_start = s_start.replace(tzinfo=timezone.utc)
                    raw_duration = max(0, int((now_utc - s_start).total_seconds()))
                else:
                    raw_duration = session.duration_seconds or 0

                idle_s = session.idle_seconds or 0
                effective_duration = max(0, raw_duration - idle_s)

                entries.append(
                    TimelineEntry(
                        started_at=session.started_at,
                        application_name=session.application_name,
                        window_title=session.window_title,
                        duration_seconds=effective_duration,
                        process_id=session.process_id,
                        idle_seconds=idle_s,
                    )
                )

            return entries

        finally:
            db_session.close()

    def get_uploaded_records_count(self) -> int:
        """Return the count of records confirmed successfully uploaded to the server."""
        db_session = self._session_factory()
        try:
            return self._repo(db_session).get_uploaded_sessions_count(
                employee_id=self._current_employee_id()
            )
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
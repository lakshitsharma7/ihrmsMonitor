"""User-preferences business logic, backed by the SQLite ``settings`` table."""

from __future__ import annotations

from dataclasses import dataclass

from database.repository import SettingsRepository


@dataclass
class AppSettings:
    """Plain-data snapshot of user preferences for use outside the DB layer."""

    idle_threshold: int
    start_with_system: bool
    tracking_enabled: bool
    track_window_titles: bool
    screenshot_interval_type: str
    screenshot_custom_interval: int
    capture_on_switch: bool


class SettingsService:
    """Reads/writes :class:`AppSettings`, translating to/from the ORM model."""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    def get_settings(self) -> AppSettings:
        db_session = self._session_factory()
        try:
            record = SettingsRepository(db_session).get_or_create()
            return AppSettings(
                idle_threshold=record.idle_threshold,
                start_with_system=record.start_with_system,
                tracking_enabled=record.tracking_enabled,
                track_window_titles=record.track_window_titles,
                screenshot_interval_type=record.screenshot_interval_type,
                screenshot_custom_interval=record.screenshot_custom_interval,
                capture_on_switch=record.capture_on_switch,
            )
        finally:
            db_session.close()

    def update_settings(self, **fields) -> AppSettings:
        """Update one or more settings fields and return the new snapshot.

        Example: ``service.update_settings(idle_threshold=600)``
        """
        db_session = self._session_factory()
        try:
            record = SettingsRepository(db_session).update(**fields)
            return AppSettings(
                idle_threshold=record.idle_threshold,
                start_with_system=record.start_with_system,
                tracking_enabled=record.tracking_enabled,
                track_window_titles=record.track_window_titles,
                screenshot_interval_type=record.screenshot_interval_type,
                screenshot_custom_interval=record.screenshot_custom_interval,
                capture_on_switch=record.capture_on_switch,
            )
        finally:
            db_session.close()

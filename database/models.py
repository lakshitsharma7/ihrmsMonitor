"""SQLAlchemy ORM models shared identically across Windows and macOS."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from config.settings import get_running_app_version


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class ActivitySession(Base):
    """A contiguous span of time spent in one application.

    A new row is created whenever the focused application changes. A row's
    ``ended_at``/``duration_seconds`` are updated as the session continues,
    and finalized when the session closes (application changes, tracking
    stops, or the user goes idle).
    """

    __tablename__ = "activity_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    process_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    window_title: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    idle_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    screenshot_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    server_session_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    screenshot_uploaded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    employee_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return (
            f"<ActivitySession id={self.id} app={self.application_name!r} "
            f"duration={self.duration_seconds}s>"
        )


class Settings(Base):
    """User-editable application preferences. Expected to hold a single row."""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    idle_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    start_with_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tracking_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    track_window_titles: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    screenshot_interval_type: Mapped[str] = mapped_column(String(50), nullable=False, default="3_min")
    screenshot_custom_interval: Mapped[int] = mapped_column(Integer, nullable=False, default=180)
    capture_on_switch: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return (
            f"<Settings idle_threshold={self.idle_threshold} "
            f"start_with_system={self.start_with_system}>"
        )


class User(Base):
    """User accounts for desktop authentication."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="User")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<User id={self.id} username={self.username!r} role={self.role}>"


class EnrolledDevice(Base):
    """Enrolled Windows/desktop devices tracked for application updates and activity."""

    __tablename__ = "enrolled_devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_identifier: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    platform: Mapped[str] = mapped_column(String(100), nullable=False, default="Windows")
    os_username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    employee_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    device_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    installed_version: Mapped[str] = mapped_column(String(50), nullable=False, default=get_running_app_version)
    latest_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    update_status: Mapped[str] = mapped_column(String(50), nullable=False, default="Update Pending")
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    last_sync: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return (
            f"<EnrolledDevice id={self.id} hostname={self.hostname!r} "
            f"version={self.installed_version} status={self.update_status}>"
        )



from __future__ import annotations

from datetime import datetime, timedelta, timezone
import getpass
import platform
import socket
from pathlib import Path

from fastapi import APIRouter

from database.database import get_session
from database.repository import ActivityRepository
from api.schemaActivity import ActivitySyncRequest


router = APIRouter(
    prefix="/activity",
    tags=["Activity"],
)


# ==============================================================
# SCREENSHOT DIRECTORY
# ==============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SCREENSHOT_DIR = (
    PROJECT_ROOT / "screenshots"
)


# ==============================================================
# POST /activity/sync
# ==============================================================

@router.post("/sync")
async def sync_activity(
    payload: ActivitySyncRequest,
):
    """
    Receive activity data from the Activity Tracker.

    This endpoint only receives the data.
    The GET endpoint reads the actual activity
    information from the local database.
    """

    print("=" * 60)
    print("ACTIVITY SYNC RECEIVED")
    print("=" * 60)

    print(
        f"User     : {payload.device.username}"
    )

    print(
        f"Hostname : {payload.device.hostname}"
    )

    print(
        f"Platform : {payload.device.platform}"
    )

    print("-" * 60)

    for activity in payload.activities:

        print(
            f"APP       : "
            f"{activity.application_name}"
        )

        print(
            f"PID       : "
            f"{activity.process_id}"
        )

        print(
            f"START     : "
            f"{activity.started_at}"
        )

        print(
            f"END       : "
            f"{activity.ended_at}"
        )

        print(
            f"DURATION  : "
            f"{activity.duration_seconds}s"
        )

        print(
            f"SESSION ID: "
            f"{activity.activity_session_id}"
        )

        print("-" * 60)

    print("=" * 60)

    return {
        "success": True,
        "message": (
            "Activity data received successfully"
        ),
        "activities_received": len(
            payload.activities
        ),
    }


# ==============================================================
# GET /activity/sync
# ==============================================================

@router.get("/sync")
async def get_activity_sync():
    """
    Return ONLY activities that overlap the
    current last 5-minute window.

    Example:

        Current time:
            10:30:00

        Window:
            10:25:00 -> 10:30:00

    Every returned activity contains:

        - activity_session_id
        - application_name
        - process_id
        - started_at
        - ended_at
        - duration_seconds
        - screenshot
    """

    # ----------------------------------------------------------
    # Current UTC time
    # ----------------------------------------------------------

    now = datetime.now(
        timezone.utc
    )

    # ----------------------------------------------------------
    # Start of 5-minute window
    # ----------------------------------------------------------

    five_minutes_ago = (
        now - timedelta(
            minutes=5
        )
    )

    db_session = get_session()

    try:

        repository = ActivityRepository(
            db_session
        )

        # ------------------------------------------------------
        # Get sessions that potentially overlap the window.
        #
        # The repository already performs the database filter.
        # We additionally validate the timestamps below after
        # converting them to UTC.
        # ------------------------------------------------------

        sessions = (
            repository.get_sessions_between(
                five_minutes_ago,
                now,
            )
        )

        activities = []

        # ======================================================
        # PROCESS EACH SESSION
        # ======================================================

        for session in sessions:

            # --------------------------------------------------
            # Convert database timestamps to UTC
            # --------------------------------------------------

            started_at = _to_utc(
                session.started_at
            )

            ended_at = (
                _to_utc(
                    session.ended_at
                )
                if session.ended_at
                else None
            )

            # --------------------------------------------------
            # IMPORTANT:
            #
            # Ignore sessions that are completely outside
            # the current 5-minute window.
            # --------------------------------------------------

            # Session starts in the future.
            if started_at >= now:
                continue

            # Session ended before the window started.
            if (
                ended_at is not None
                and ended_at <= five_minutes_ago
            ):
                continue

            # --------------------------------------------------
            # Calculate the actual overlap with the
            # last 5-minute window.
            # --------------------------------------------------

            effective_start = max(
                started_at,
                five_minutes_ago,
            )

            effective_end = min(
                ended_at or now,
                now,
            )

            # --------------------------------------------------
            # Calculate duration only inside this window.
            # --------------------------------------------------

            duration_seconds = max(
                0,
                int(
                    (
                        effective_end
                        - effective_start
                    ).total_seconds()
                ),
            )

            # No usable activity.
            if duration_seconds <= 0:
                continue

            # --------------------------------------------------
            # Find screenshot belonging to this session.
            # --------------------------------------------------

            screenshot = _find_screenshot(
                activity_session_id=session.id,
                captured_after=five_minutes_ago,
                captured_before=now,
            )

            # --------------------------------------------------
            # Build response.
            # --------------------------------------------------

            activity_data = {
                "activity_session_id": (
                    session.id
                ),

                "application_name": (
                    session.application_name
                ),

                "process_id": (
                    session.process_id
                ),

                "started_at": (
                    effective_start.strftime(
                        "%H:%M:%S"
                    )
                ),

                "ended_at": (
                    effective_end.strftime(
                        "%H:%M:%S"
                    )
                    if effective_end
                    else None
                ),

                "duration_seconds": (
                    duration_seconds
                ),

                "screenshot": screenshot,
            }

            activities.append(
                activity_data
            )

        # ======================================================
        # RESPONSE
        # ======================================================

        return {
            "device": {
                "username": (
                    _get_username()
                ),

                "hostname": (
                    socket.gethostname()
                ),

                "platform": (
                    platform.system()
                ),
            },

            "sync": {
                "from": (
                    five_minutes_ago.strftime(
                        "%H:%M:%S"
                    )
                ),

                "to": (
                    now.strftime(
                        "%H:%M:%S"
                    )
                ),
            },

            "activities": activities,
        }

    finally:

        db_session.close()


# ==============================================================
# FIND SCREENSHOT
# ==============================================================

def _find_screenshot(
    activity_session_id: int,
    captured_after: datetime,
    captured_before: datetime,
) -> dict | None:
    """
    Find the screenshot associated with an activity session.

    Expected filename:

        session_<session_id>_<timestamp>_<uuid>.png
    """

    if not SCREENSHOT_DIR.exists():
        return None

    prefix = (
        f"session_{activity_session_id}_"
    )

    matching_files: list[Path] = []

    # ----------------------------------------------------------
    # Find files belonging to this activity session.
    # ----------------------------------------------------------

    for filepath in SCREENSHOT_DIR.iterdir():

        if not filepath.is_file():
            continue

        if not filepath.name.startswith(
            prefix
        ):
            continue

        if filepath.suffix.lower() not in {
            ".png",
            ".jpg",
            ".jpeg",
        }:
            continue

        matching_files.append(
            filepath
        )

    if not matching_files:
        return None

    # ----------------------------------------------------------
    # Most recent screenshot first.
    # ----------------------------------------------------------

    matching_files.sort(
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    # ----------------------------------------------------------
    # Find the first screenshot that is actually
    # inside the current 5-minute window.
    # ----------------------------------------------------------

    for filepath in matching_files:

        captured_at = (
            datetime.fromtimestamp(
                filepath.stat().st_mtime,
                tz=timezone.utc,
            )
        )

        if (
            captured_at < captured_after
            or captured_at > captured_before
        ):
            continue

        return {
            "captured_at": (
                captured_at.strftime(
                    "%H:%M:%S"
                )
            ),

            "filename": (
                filepath.name
            ),

            "path": (
                str(filepath)
            ),
        }

    return None


# ==============================================================
# UTC HELPER
# ==============================================================

def _to_utc(
    value: datetime,
) -> datetime:
    """
    Convert a datetime to UTC.

    SQLite may return a naive datetime,
    so naive values are treated as UTC.
    """

    if value.tzinfo is None:

        return value.replace(
            tzinfo=timezone.utc
        )

    return value.astimezone(
        timezone.utc
    )


# ==============================================================
# USERNAME HELPER
# ==============================================================

def _get_username() -> str:

    try:

        return getpass.getuser()

    except Exception:

        return "unknown"
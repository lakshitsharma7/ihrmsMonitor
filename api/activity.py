from __future__ import annotations

import getpass
import platform
import re
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from api.schemaActivity import ActivitySyncRequest
from database.database import get_session
from database.repository import ActivityRepository


# ==============================================================
# ROUTER
# ==============================================================

router = APIRouter(
    prefix="/activity",
    tags=["Activity"],
)


# ==============================================================
# SCREENSHOT DIRECTORY
# ==============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SCREENSHOT_DIR = PROJECT_ROOT / "screenshots"

SCREENSHOT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


# ==============================================================
# SCREENSHOT FILENAME
# ==============================================================

SCREENSHOT_PATTERN = re.compile(
    r"^session_(\d+)_"
    r"(\d{4}-\d{2}-\d{2}_"
    r"\d{2}-\d{2}-\d{2}-\d{6})"
    r"(?:_[a-fA-F0-9]+)?"
    r"\.(png|jpg|jpeg)$"
)


# Prevent duplicate activity submissions
_received_session_ids: set[int] = set()


# ==============================================================
# POST /activity/sync
# ==============================================================

@router.post("/sync")
async def sync_activity(
    payload: ActivitySyncRequest,
):
    """
    Receive activity data from desktop tracker.
    """

    print("=" * 60)
    print("ACTIVITY SYNC RECEIVED")
    if payload.page is not None:
        print(f"Page     : {payload.page} / Page Size: {payload.page_size}")
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

    new_activities = []
    duplicate_count = 0

    for activity in payload.activities:
        if activity.activity_session_id in _received_session_ids:
            duplicate_count += 1
            continue

        _received_session_ids.add(activity.activity_session_id)
        new_activities.append(activity)

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
    if duplicate_count > 0:
        print(f"Duplicates Filtered: {duplicate_count}")
        print("=" * 60)

    return {
        "success": True,
        "message": (
            "Activity data received successfully"
        ),
        "activities_received": len(new_activities),
        "duplicates_filtered": duplicate_count,
    }


# ==============================================================
# GET /activity/sync
# ==============================================================

@router.get("/sync")
async def get_activity_sync():
    """
    Return activity from the last five minutes.

    This endpoint remains a five-minute sync endpoint.
    For complete history use /activity/all.
    """

    now = datetime.now(
        timezone.utc
    )

    window_start = (
        now - timedelta(minutes=5)
    )

    db_session = get_session()

    try:

        repository = ActivityRepository(
            db_session
        )

        sessions = (
            repository.get_sessions_between(
                window_start,
                now,
            )
        )

        activities = []

        for session in sessions:

            started_at = _to_utc(
                session.started_at
            )

            ended_at = (
                _to_utc(
                    session.ended_at
                )
                if session.ended_at is not None
                else None
            )

            # --------------------------------------------------
            # Ignore future sessions.
            # --------------------------------------------------

            if started_at >= now:
                continue

            # --------------------------------------------------
            # Ignore sessions completely before window.
            # --------------------------------------------------

            if (
                ended_at is not None
                and ended_at <= window_start
            ):
                continue

            effective_start = max(
                started_at,
                window_start,
            )

            effective_end = min(
                ended_at or now,
                now,
            )

            duration_seconds = max(
                0,
                int(
                    (
                        effective_end
                        - effective_start
                    ).total_seconds()
                ),
            )

            if duration_seconds <= 0:
                continue

            screenshot = _find_screenshot(
                session.id
            )

            activities.append(
                {
                    "activity_session_id": (
                        session.id
                    ),

                    "application_name": (
                        session.application_name
                    ),

                    "process_id": (
                        session.process_id
                    ),

                    "window_title": (
                        session.window_title
                    ),

                    "started_at": (
                        effective_start.strftime(
                            "%H:%M:%S"
                        )
                    ),

                    "ended_at": (
                        ended_at.strftime(
                            "%H:%M:%S"
                        )
                        if ended_at is not None
                        else None
                    ),

                    "duration_seconds": (
                        duration_seconds
                    ),

                    "screenshot": screenshot,
                }
            )

        return {
            "device": {
                "username": _get_username(),
                "hostname": socket.gethostname(),
                "platform": platform.system(),
            },

            "sync": {
                "from": window_start.strftime(
                    "%H:%M:%S"
                ),

                "to": now.strftime(
                    "%H:%M:%S"
                ),
            },

            "activities": activities,
        }

    finally:

        db_session.close()


# ==============================================================
# GET /activity/all
# ==============================================================

@router.get("/all")
async def get_all_activity():
    """
    Return ALL activity sessions.

    No five-minute filter.

    Newest session comes first.
    """

    db_session = get_session()

    try:

        repository = ActivityRepository(
            db_session
        )

        # ------------------------------------------------------
        # IMPORTANT:
        #
        # repository.get_all_sessions()
        # must use:
        #
        # ActivitySession.started_at.desc()
        #
        # so latest activity appears first.
        # ------------------------------------------------------

        sessions = (
            repository.get_all_sessions()
        )

        activities = []

        for session in sessions:

            started_at = _to_utc(
                session.started_at
            )

            ended_at = (
                _to_utc(
                    session.ended_at
                )
                if session.ended_at is not None
                else None
            )

            # --------------------------------------------------
            # Find screenshot for this exact session.
            # --------------------------------------------------

            screenshot = _find_screenshot(
                session.id
            )

            activities.append(
                {
                    "activity_session_id": (
                        session.id
                    ),

                    "application_name": (
                        session.application_name
                    ),

                    "process_id": (
                        session.process_id
                    ),

                    "window_title": (
                        session.window_title
                    ),

                    "started_at": (
                        started_at.strftime(
                            "%H:%M:%S"
                        )
                    ),

                    "ended_at": (
                        ended_at.strftime(
                            "%H:%M:%S"
                        )
                        if ended_at is not None
                        else None
                    ),

                    "duration_seconds": (
                        session.duration_seconds
                    ),

                    "screenshot": screenshot,
                }
            )

        return {
            "device": {
                "username": _get_username(),
                "hostname": socket.gethostname(),
                "platform": platform.system(),
            },

            "total": len(
                activities
            ),

            "activities": activities,
        }

    finally:

        db_session.close()


# ==============================================================
# GET /activity/screenshot/{filename}
# ==============================================================

@router.get(
    "/screenshot/{filename}"
)
async def get_activity_screenshot(
    filename: str,
):
    """
    Open a screenshot directly in the browser.
    """

    # ----------------------------------------------------------
    # Prevent directory traversal.
    # ----------------------------------------------------------

    requested_path = (
        SCREENSHOT_DIR / filename
    ).resolve()

    screenshot_root = (
        SCREENSHOT_DIR.resolve()
    )

    try:

        requested_path.relative_to(
            screenshot_root
        )

    except ValueError:

        raise HTTPException(
            status_code=400,
            detail="Invalid screenshot path",
        )

    # ----------------------------------------------------------
    # File must exist.
    # ----------------------------------------------------------

    if not requested_path.is_file():

        raise HTTPException(
            status_code=404,
            detail="Screenshot not found",
        )

    # ----------------------------------------------------------
    # Only images.
    # ----------------------------------------------------------

    if requested_path.suffix.lower() not in {
        ".png",
        ".jpg",
        ".jpeg",
    }:

        raise HTTPException(
            status_code=400,
            detail="Invalid screenshot format",
        )

    # ----------------------------------------------------------
    # Return image directly.
    #
    # NO filename parameter here.
    #
    # This makes browser display the image instead of forcing
    # download.
    # ----------------------------------------------------------

    return FileResponse(
        path=str(requested_path),
        media_type=_get_image_media_type(
            requested_path
        ),
    )


# ==============================================================
# FIND SCREENSHOT
# ==============================================================

def _find_screenshot(
    activity_session_id: int,
) -> dict | None:
    """
    Find newest screenshot belonging to a session.

    Expected:

        session_9_2026-08-24_07-34-21-123456.png

    Also supports:

        session_9_2026-08-24_07-34-21-123456_a1b2c3d4.png
    """

    if not SCREENSHOT_DIR.exists():
        return None

    prefix = (
        f"session_{activity_session_id}_"
    )

    matches: list[
        tuple[Path, datetime]
    ] = []

    try:

        files = list(
            SCREENSHOT_DIR.iterdir()
        )

    except Exception as exc:

        print(
            "SCREENSHOT DIRECTORY ERROR |",
            exc,
        )

        return None

    for filepath in files:

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

        match = (
            SCREENSHOT_PATTERN.match(
                filepath.name
            )
        )

        if match is None:
            continue

        try:

            captured_at = (
                datetime.strptime(
                    match.group(2),
                    "%Y-%m-%d_%H-%M-%S-%f",
                ).replace(
                    tzinfo=timezone.utc
                )
            )

        except ValueError:

            continue

        matches.append(
            (
                filepath,
                captured_at,
            )
        )

    # ----------------------------------------------------------
    # No screenshot.
    # ----------------------------------------------------------

    if not matches:
        return None

    # ----------------------------------------------------------
    # Newest screenshot.
    # ----------------------------------------------------------

    matches.sort(
        key=lambda item: item[1],
        reverse=True,
    )

    filepath, captured_at = (
        matches[0]
    )

    # ----------------------------------------------------------
    # URL.
    # ----------------------------------------------------------

    return {
        "filename": filepath.name,

        "captured_at": (
            captured_at.strftime(
                "%H:%M:%S"
            )
        ),

        "url": (
            f"/activity/screenshot/"
            f"{filepath.name}"
        ),
    }


# ==============================================================
# IMAGE MEDIA TYPE
# ==============================================================

def _get_image_media_type(
    filepath: Path,
) -> str:

    extension = (
        filepath.suffix.lower()
    )

    if extension == ".png":
        return "image/png"

    if extension in {
        ".jpg",
        ".jpeg",
    }:
        return "image/jpeg"

    return "application/octet-stream"


# ==============================================================
# UTC
# ==============================================================

def _to_utc(
    value: datetime,
) -> datetime:
    """
    Convert datetime to UTC.

    Naive SQLite datetime is treated as UTC.
    """

    if value.tzinfo is None:

        return value.replace(
            tzinfo=timezone.utc
        )

    return value.astimezone(
        timezone.utc
    )


# ==============================================================
# USERNAME
# ==============================================================

def _get_username() -> str:

    try:

        return getpass.getuser()

    except Exception:

        return "unknown"
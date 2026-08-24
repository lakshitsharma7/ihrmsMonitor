from __future__ import annotations

import getpass
import platform
import socket
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from fastapi.responses import FileResponse

from database.database import get_session
from database.repository import ActivityRepository


# ==============================================================
# HELPERS
# ==============================================================

def _get_username() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"

def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# ==============================================================
# ROUTER
# ==============================================================

router = APIRouter(
    prefix="/screenshots",
    tags=["Screenshots"],
)


# ==============================================================
# SCREENSHOT DIRECTORY
# ==============================================================

PROJECT_ROOT = (
    Path(__file__).resolve().parent.parent
)

SCREENSHOT_DIR = (
    PROJECT_ROOT / "screenshots"
)

SCREENSHOT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


# ==============================================================
# UPLOAD SCREENSHOT
# ==============================================================


@router.post("")
async def upload_screenshot(
    activity_session_id: int = Form(...),
    captured_at: datetime = Form(...),
    application_name: str = Form(...),
    process_id: int | None = Form(None),
    file: UploadFile = File(...),
):
    """
    Save a screenshot and associate it with an
    ActivitySession ID.
    """

    # ----------------------------------------------------------
    # Validate content type
    # ----------------------------------------------------------

    allowed_types = {
        "image/png",
        "image/jpeg",
    }

    if file.content_type not in allowed_types:

        raise HTTPException(
            status_code=400,
            detail=(
                "Only PNG and JPEG screenshots "
                "are allowed"
            ),
        )

    # ----------------------------------------------------------
    # Determine extension
    # ----------------------------------------------------------

    original_name = (
        file.filename or ""
    )

    extension = (
        Path(original_name)
        .suffix
        .lower()
    )

    if extension not in {
        ".png",
        ".jpg",
        ".jpeg",
    }:

        extension = ".png"

    # ----------------------------------------------------------
    # Normalize captured time
    # ----------------------------------------------------------

    if captured_at.tzinfo is None:

        captured_at = (
            captured_at.replace(
                tzinfo=timezone.utc
            )
        )

    else:

        captured_at = (
            captured_at.astimezone(
                timezone.utc
            )
        )

    # ----------------------------------------------------------
    # Create timestamp
    # ----------------------------------------------------------

    timestamp = (
        captured_at.strftime(
            "%Y-%m-%d_%H-%M-%S-%f"
        )
    )

    # ----------------------------------------------------------
    # Unique ID
    # ----------------------------------------------------------

    unique_id = uuid4().hex[:8]

    # ----------------------------------------------------------
    # Session-specific filename
    # ----------------------------------------------------------

    filename = (
        f"session_{activity_session_id}_"
        f"{timestamp}_"
        f"{unique_id}"
        f"{extension}"
    )

    filepath = (
        SCREENSHOT_DIR / filename
    )

    # ----------------------------------------------------------
    # Read file
    # ----------------------------------------------------------

    contents = await file.read()

    if not contents:

        raise HTTPException(
            status_code=400,
            detail="Screenshot file is empty",
        )

    # ----------------------------------------------------------
    # Save screenshot
    # ----------------------------------------------------------

    filepath.write_bytes(
        contents
    )

    print("=" * 60)
    print("SCREENSHOT RECEIVED")
    print("=" * 60)

    print(
        f"Session     : "
        f"{activity_session_id}"
    )

    print(
        f"Application : "
        f"{application_name}"
    )

    print(
        f"PID         : "
        f"{process_id}"
    )

    print(
        f"Captured    : "
        f"{captured_at}"
    )

    print(
        f"File        : "
        f"{filepath}"
    )

    print("=" * 60)

    # ----------------------------------------------------------
    # Store screenshot path in database
    # ----------------------------------------------------------
    db_session = get_session()
    try:
        repository = ActivityRepository(db_session)
        repository.update_session_screenshot_path(activity_session_id, str(filepath))
    except Exception as db_err:
        print(f"DATABASE ERROR | Failed to update screenshot path: {db_err}")
    finally:
        db_session.close()

    # ----------------------------------------------------------
    # Return API information
    # ----------------------------------------------------------

    return {
        "success": True,

        "message": (
            "Screenshot uploaded successfully"
        ),

        "activity_session_id": (
            activity_session_id
        ),

        "application_name": (
            application_name
        ),

        "process_id": process_id,

        "captured_at": captured_at,

        "filename": filename,

        "path": str(filepath),

        "url": (
            f"/screenshots/"
            f"{filename}"
        ),
    }


# ==============================================================
# GET ALL SCREENSHOTS
# ==============================================================

@router.get("/all")
async def get_all_screenshots():
    """
    Return ALL screenshot metadata matching the pattern of /activity/all.
    """
    db_session = get_session()
    try:
        repository = ActivityRepository(db_session)
        sessions = repository.get_all_sessions()
        screenshots = []

        for session in sessions:
            if session.screenshot_path:
                filepath = Path(session.screenshot_path)
                if filepath.exists() and filepath.is_file():
                    started_at = _to_utc(session.started_at)
                    screenshots.append({
                        "activity_session_id": session.id,
                        "application_name": session.application_name,
                        "process_id": session.process_id,
                        "window_title": session.window_title,
                        "filename": filepath.name,
                        "path": str(filepath),
                        "url": f"/screenshots/{filepath.name}",
                        "captured_at": started_at.strftime("%H:%M:%S"),
                    })

        return {
            "device": {
                "username": _get_username(),
                "hostname": socket.gethostname(),
                "platform": platform.system(),
            },
            "total": len(screenshots),
            "screenshots": screenshots,
        }
    finally:
        db_session.close()


# ==============================================================
# RETRIEVE SCREENSHOT
# ==============================================================

@router.get("/{filename}")
async def get_screenshot(filename: str):
    """
    Retrieve/open a screenshot directly.
    """
    requested_path = (SCREENSHOT_DIR / filename).resolve()
    screenshot_root = SCREENSHOT_DIR.resolve()

    try:
        requested_path.relative_to(screenshot_root)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid screenshot path",
        )

    if not requested_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Screenshot not found",
        )

    if requested_path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        raise HTTPException(
            status_code=400,
            detail="Invalid screenshot format",
        )

    # Get media type
    extension = requested_path.suffix.lower()
    if extension == ".png":
        media_type = "image/png"
    elif extension in {".jpg", ".jpeg"}:
        media_type = "image/jpeg"
    else:
        media_type = "application/octet-stream"

    return FileResponse(
        path=str(requested_path),
        media_type=media_type,
    )
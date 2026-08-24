from __future__ import annotations

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
            f"/activity/screenshot/"
            f"{filename}"
        ),
    }
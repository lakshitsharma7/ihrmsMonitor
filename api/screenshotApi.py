from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile


router = APIRouter(
    prefix="/screenshots",
    tags=["Screenshots"],
)


# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Where server will store uploaded screenshots
SCREENSHOT_DIR = PROJECT_ROOT / "screenshots"

SCREENSHOT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


@router.post("")
async def upload_screenshot(
    activity_session_id: int = Form(...),
    captured_at: datetime = Form(...),
    application_name: str = Form(...),
    process_id: int | None = Form(None),
    file: UploadFile = File(...),
):

    # ---------------------------------------------------------
    # Validate file type
    # ---------------------------------------------------------

    allowed_types = {
        "image/png",
        "image/jpeg",
    }

    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail="Only PNG and JPEG screenshots are allowed",
        )

    # ---------------------------------------------------------
    # Determine extension
    # ---------------------------------------------------------

    original_name = file.filename or ""

    extension = Path(
        original_name
    ).suffix.lower()

    if extension not in {
        ".png",
        ".jpg",
        ".jpeg",
    }:
        extension = ".png"

    # ---------------------------------------------------------
    # Generate unique filename
    # ---------------------------------------------------------

    timestamp = captured_at.strftime(
        "%Y-%m-%d_%H-%M-%S"
    )

    unique_id = uuid4().hex[:8]

    filename = (
        f"session_{activity_session_id}_"
        f"{timestamp}_"
        f"{unique_id}"
        f"{extension}"
    )

    filepath = SCREENSHOT_DIR / filename

    # ---------------------------------------------------------
    # Save screenshot
    # ---------------------------------------------------------

    contents = await file.read()

    filepath.write_bytes(contents)

    print("=" * 60)
    print("SCREENSHOT RECEIVED")
    print("=" * 60)

    print(
        f"Session     : {activity_session_id}"
    )

    print(
        f"Application : {application_name}"
    )

    print(
        f"PID         : {process_id}"
    )

    print(
        f"Captured    : {captured_at}"
    )

    print(
        f"File        : {filepath}"
    )

    print("=" * 60)

    return {
        "success": True,
        "message": "Screenshot uploaded successfully",
        "activity_session_id": activity_session_id,
        "application_name": application_name,
        "process_id": process_id,
        "captured_at": captured_at,
        "filename": filename,
        "path": str(filepath),
    }
from __future__ import annotations

import getpass
import platform
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from database.database import get_session
from database.repository import ActivityRepository
from utils.logger import get_logger


logger = get_logger(__name__)


class SyncService:
    """
    Sends Activity Tracker data to the FastAPI server.

    Background activity sync:
        Sends only activity sessions from the last 5 minutes.

    Activity history:
        Retrieves all locally stored activity sessions using
        pagination.

    Screenshot sync:
        Uploads a screenshot immediately when requested by the tracker.

    This service does not run its own timer.
    """

    # ----------------------------------------------------------
    # Background sync window.
    #
    # DO NOT remove this.
    #
    # This is intentionally used for incremental syncing.
    # ----------------------------------------------------------

    ACTIVITY_WINDOW_MINUTES = 5

    # Maximum number of records returned in one history page.
    MAX_PAGE_SIZE = 500

    def __init__(
        self,
        api_url: str = "http://127.0.0.1:8000",
    ) -> None:

        self._api_url = api_url.rstrip("/")

        logger.info(
            "SyncService initialized: %s",
            self._api_url,
        )

    # ==============================================================
    # ACTIVITY SYNC
    # ==============================================================

    def sync_activity_now(self) -> bool:
        """
        Immediately send activity data for the last 5 minutes.

        This is the background/incremental sync operation.

        It intentionally does NOT send the entire activity history.
        """

        sync_to = datetime.now(timezone.utc)

        sync_from = (
            sync_to
            - timedelta(
                minutes=self.ACTIVITY_WINDOW_MINUTES
            )
        )

        logger.info(
            "Activity sync window: %s -> %s",
            sync_from,
            sync_to,
        )

        try:

            payload = self._build_activity_payload(
                sync_from=sync_from,
                sync_to=sync_to,
            )

            logger.info(
                "Sending activity data to %s/activity/sync",
                self._api_url,
            )

            response = requests.post(
                f"{self._api_url}/activity/sync",
                json=payload,
                timeout=10,
            )

            response.raise_for_status()

            logger.info(
                "Activity sync successful: HTTP %s",
                response.status_code,
            )

            return True

        except requests.RequestException as exc:

            logger.error(
                "Activity sync request failed: %s",
                exc,
            )

            return False

        except Exception:

            logger.exception(
                "Unexpected error during activity sync"
            )

            return False

    # ==============================================================
    # ACTIVITY HISTORY
    # ==============================================================

    def get_activity_history(
        self,
        page: int = 1,
        page_size: int = 50,
        newest_first: bool = True,
    ) -> dict:
        """
        Return all locally stored activity sessions page by page.

        Example:

            get_activity_history(
                page=1,
                page_size=50,
            )

        returns records 1-50.

            get_activity_history(
                page=2,
                page_size=50,
            )

        returns records 51-100.

        This method is NOT limited to the last 5 minutes.
        """

        page = max(1, int(page))

        page_size = max(
            1,
            min(
                int(page_size),
                self.MAX_PAGE_SIZE,
            ),
        )

        db_session = get_session()

        try:

            repository = ActivityRepository(
                db_session
            )

            result = (
                repository.get_sessions_paginated(
                    page=page,
                    page_size=page_size,
                    newest_first=newest_first,
                )
            )

            activities = []

            for session in result.items:

                started_at = self._to_utc(
                    session.started_at
                )

                ended_at = (
                    self._to_utc(
                        session.ended_at
                    )
                    if session.ended_at
                    else None
                )

                activities.append(
                    {
                        "activity_session_id": session.id,
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
                            started_at.isoformat()
                        ),
                        "ended_at": (
                            ended_at.isoformat()
                            if ended_at
                            else None
                        ),
                        "duration_seconds": (
                            session.duration_seconds
                        ),
                        "screenshot": None,
                    }
                )

            return {
                "page": result.page,
                "page_size": result.page_size,
                "total": result.total,
                "total_pages": result.total_pages,
                "has_next": result.has_next,
                "has_previous": result.has_previous,
                "activities": activities,
            }

        finally:

            db_session.close()

    # ==============================================================
    # GET ALL LOCAL ACTIVITY
    # ==============================================================

    def get_all_activity_pages(
        self,
        page_size: int = 50,
        newest_first: bool = True,
    ) -> list[dict]:
        """
        Retrieve every locally stored activity session.

        This repeatedly loads pages until all records are retrieved.

        Use get_activity_history() when the UI itself handles
        pagination. Use this method only when the entire history
        is actually required.
        """

        page = 1

        all_pages: list[dict] = []

        while True:

            result = self.get_activity_history(
                page=page,
                page_size=page_size,
                newest_first=newest_first,
            )

            all_pages.append(result)

            if not result["has_next"]:
                break

            page += 1

        return all_pages

    # ==============================================================
    # BUILD ACTIVITY PAYLOAD
    # ==============================================================

    def _build_activity_payload(
        self,
        sync_from: datetime,
        sync_to: datetime,
    ) -> dict:
        """
        Build the payload for POST /activity/sync.

        IMPORTANT:
        This method intentionally uses the requested sync window.
        Background synchronization remains incremental.
        """

        db_session = get_session()

        try:

            repository = ActivityRepository(
                db_session
            )

            sessions = (
                repository.get_sessions_between(
                    sync_from,
                    sync_to,
                )
            )

            usage = (
                repository.get_application_usage(
                    sync_from,
                    sync_to,
                )
            )

            activities = []

            for session in sessions:

                started_at = self._to_utc(
                    session.started_at
                )

                ended_at = (
                    self._to_utc(
                        session.ended_at
                    )
                    if session.ended_at
                    else None
                )

                # --------------------------------------------------
                # Calculate duration inside the sync window.
                # --------------------------------------------------

                effective_start = max(
                    started_at,
                    sync_from,
                )

                effective_end = min(
                    ended_at or sync_to,
                    sync_to,
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

                # Ignore sessions that have no time
                # inside the requested window.
                if duration_seconds <= 0:
                    continue

                activities.append(
                    {
                        "activity_session_id": session.id,
                        "application_name": (
                            session.application_name
                        ),
                        "process_id": (
                            session.process_id
                        ),
                        "started_at": (
                            started_at.isoformat()
                        ),
                        "ended_at": (
                            ended_at.isoformat()
                            if ended_at
                            else None
                        ),
                        "duration_seconds": (
                            duration_seconds
                        ),
                    }
                )

            # ------------------------------------------------------
            # Calculate totals.
            # ------------------------------------------------------

            totals_map: dict[str, int] = {}

            for activity in activities:

                application_name = (
                    activity["application_name"]
                )

                duration = int(
                    activity["duration_seconds"]
                )

                totals_map[application_name] = (
                    totals_map.get(
                        application_name,
                        0,
                    )
                    + duration
                )

            totals = [
                {
                    "application_name": (
                        application_name
                    ),
                    "total_duration_seconds": (
                        total_seconds
                    ),
                }
                for (
                    application_name,
                    total_seconds,
                ) in totals_map.items()
            ]

            totals.sort(
                key=lambda item: item[
                    "total_duration_seconds"
                ],
                reverse=True,
            )

            # ------------------------------------------------------
            # Final payload.
            # ------------------------------------------------------

            payload = {
                "device": {
                    "username": self._get_username(),
                    "hostname": socket.gethostname(),
                    "platform": platform.system(),
                },

                "sync": {
                    "from": sync_from.isoformat(),
                    "to": sync_to.isoformat(),
                },

                "activities": activities,

                "totals": totals,
            }

            logger.info(
                "Activity payload created: "
                "%d activities, %d totals",
                len(activities),
                len(totals),
            )

            return payload

        finally:

            db_session.close()

    # ==============================================================
    # SCREENSHOT UPLOAD
    # ==============================================================

    def upload_screenshot_now(
        self,
        screenshot_path: str | Path,
        activity_session_id: int,
        application_name: str,
        process_id: int | None,
        captured_at: datetime | None = None,
    ) -> bool:
        """
        Immediately upload a screenshot to:

            POST /screenshots
        """

        screenshot_path = Path(
            screenshot_path
        )

        if not screenshot_path.exists():

            logger.error(
                "Screenshot does not exist: %s",
                screenshot_path,
            )

            return False

        if captured_at is None:

            captured_at = datetime.now(
                timezone.utc
            )

        try:

            with screenshot_path.open(
                "rb"
            ) as screenshot_file:

                files = {
                    "file": (
                        screenshot_path.name,
                        screenshot_file,
                        self._get_content_type(
                            screenshot_path
                        ),
                    )
                }

                data = {
                    "activity_session_id": str(
                        activity_session_id
                    ),

                    "captured_at": (
                        self._to_utc(
                            captured_at
                        ).isoformat()
                    ),

                    "application_name": (
                        application_name
                    ),

                    "process_id": (
                        str(process_id)
                        if process_id is not None
                        else ""
                    ),
                }

                logger.info(
                    "Uploading screenshot: %s",
                    screenshot_path,
                )

                response = requests.post(
                    f"{self._api_url}/screenshots",
                    files=files,
                    data=data,
                    timeout=30,
                )

                response.raise_for_status()

            logger.info(
                "Screenshot upload successful: %s",
                screenshot_path.name,
            )

            return True

        except requests.RequestException as exc:

            logger.error(
                "Screenshot upload failed: %s",
                exc,
            )

            return False

        except Exception:

            logger.exception(
                "Unexpected screenshot upload error"
            )

            return False

    # ==============================================================
    # HELPERS
    # ==============================================================

    @staticmethod
    def _get_username() -> str:

        try:
            return getpass.getuser()

        except Exception:
            return "unknown"

    @staticmethod
    def _to_utc(
        value: datetime,
    ) -> datetime:

        if value.tzinfo is None:
            return value.replace(
                tzinfo=timezone.utc
            )

        return value.astimezone(
            timezone.utc
        )

    @staticmethod
    def _get_content_type(
        path: Path,
    ) -> str:

        extension = path.suffix.lower()

        if extension == ".png":
            return "image/png"

        if extension in {
            ".jpg",
            ".jpeg",
        }:
            return "image/jpeg"

        return "application/octet-stream"
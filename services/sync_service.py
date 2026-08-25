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
        api_url: str | None = None,
    ) -> None:

        import os
        if api_url is None:
            api_url = os.environ.get("API_URL", "https://softdev.indovisionservices.in/ihrms84/hrms_api/ci4/api")

        self._api_url = api_url.rstrip("/")
        self._synced_session_ids = set()

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

        It processes records in batches of 100 max, divided into 4 requests of 25 records each.
        """
        # Call tracking/get_settings at the start of every sync cycle
        from services.session_service import SessionService
        device_token = SessionService().device_token
        if device_token:
            try:
                response = requests.post(
                    f"{self._api_url}/tracking/get_settings",
                    json={"device_token": device_token},
                    timeout=5,
                )
                response.raise_for_status()
                res_data = response.json()
                if res_data.get("status") == 1:
                    settings_data = res_data.get("settings", {})
                    # Update local database settings
                    db_session = get_session()
                    try:
                        from database.repository import SettingsRepository
                        repo = SettingsRepository(db_session)
                        
                        capture_interval = settings_data.get("capture_interval", 180)
                        capture_mode = settings_data.get("capture_mode", "activity_with_screenshots")
                        tracking_enabled = settings_data.get("tracking_enabled", True)
                        
                        repo.update(
                            screenshot_custom_interval=capture_interval,
                            screenshot_interval_type="custom",
                            capture_on_switch=(capture_mode == "activity_with_screenshots"),
                            tracking_enabled=tracking_enabled
                        )
                    except Exception as err:
                        logger.error("Failed to update database settings from get_settings response: %s", err)
                    finally:
                        db_session.close()
            except Exception as err:
                logger.error("Failed to retrieve settings from tracking/get_settings: %s", err)

        sync_to = datetime.now(timezone.utc)
        sync_from = sync_to - timedelta(minutes=self.ACTIVITY_WINDOW_MINUTES)

        logger.info(
            "Activity sync window: %s -> %s",
            sync_from,
            sync_to,
        )

        db_session = get_session()
        try:
            repository = ActivityRepository(db_session)
            sessions = repository.get_sessions_between(sync_from, sync_to)

            # Filter out duplicate submissions (already synced session IDs)
            unsynced_sessions = [s for s in sessions if s.id not in self._synced_session_ids]

            if not unsynced_sessions:
                logger.info("No new/unsynced activities to sync in this window.")
                return True

            logger.info("Syncing %d new/unsynced sessions in batches", len(unsynced_sessions))

            BATCH_SIZE = 100
            for i in range(0, len(unsynced_sessions), BATCH_SIZE):
                batch = unsynced_sessions[i:i + BATCH_SIZE]
                
                uploaded_count = 0
                # Divide batch of 100 into 4 requests of 25 records each
                PAGE_SIZE = 25
                for page_num in range(1, 5): # page 1, 2, 3, 4
                    start_idx = (page_num - 1) * PAGE_SIZE
                    if start_idx >= len(batch):
                        break
                    
                    page_sessions = batch[start_idx:start_idx + PAGE_SIZE]
                    if not page_sessions:
                        break
                        
                    payload = self._build_page_payload(
                        sessions=page_sessions,
                        sync_from=sync_from,
                        sync_to=sync_to,
                        page=page_num,
                        page_size=PAGE_SIZE
                    )

                    new_payload = {
                        "device_token": device_token or "mock_device_token",
                        "sessions": payload["activities"]
                    }
                    
                    success = self._send_request_with_retry(new_payload, page=page_num)
                    if not success:
                        logger.error("Activity sync batch page failed. Halting sync.")
                        return False
                        
                    # Mark successful sessions as synced
                    for s in page_sessions:
                        self._synced_session_ids.add(s.id)

                    uploaded_count += len(page_sessions)
                    logger.info("%d/%d records uploaded", uploaded_count, len(batch))

            return True

        except Exception as exc:
            logger.exception("Unexpected error during activity sync: %s", exc)
            return False
        finally:
            db_session.close()

    def _send_request_with_retry(self, payload: dict, page: int, retries: int = 3) -> bool:
        for attempt in range(1, retries + 1):
            try:
                response = requests.post(
                    f"{self._api_url}/tracking/save_activity_batch",
                    json=payload,
                    timeout=10,
                )
                response.raise_for_status()
                logger.info(
                    "Activity sync page %d successful: HTTP %s (attempt %d)",
                    page,
                    response.status_code,
                    attempt,
                )
                return True
            except requests.RequestException as exc:
                logger.warning(
                    "Activity sync page %d failed (attempt %d/%d): %s",
                    page,
                    attempt,
                    retries,
                    exc,
                )
                if attempt == retries:
                    logger.error("Activity sync failed after maximum retries.")
                    return False
        return False

    def _build_page_payload(
        self,
        sessions: list,
        sync_from: datetime,
        sync_to: datetime,
        page: int,
        page_size: int,
    ) -> dict:
        activities = []
        totals_map = {}

        for session in sessions:
            started_at = self._to_utc(session.started_at)
            ended_at = self._to_utc(session.ended_at) if session.ended_at else None

            effective_start = max(started_at, sync_from)
            effective_end = min(ended_at or sync_to, sync_to)
            duration_seconds = max(0, int((effective_end - effective_start).total_seconds()))

            activities.append({
                "activity_session_id": session.id,
                "application_name": session.application_name,
                "process_id": session.process_id,
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat() if ended_at else None,
                "duration_seconds": duration_seconds,
            })

            totals_map[session.application_name] = totals_map.get(session.application_name, 0) + duration_seconds

        totals = [
            {
                "application_name": app_name,
                "total_duration_seconds": total_seconds,
            }
            for app_name, total_seconds in totals_map.items()
        ]
        totals.sort(key=lambda item: item["total_duration_seconds"], reverse=True)

        return {
            "device": {
                "username": self._get_username(),
                "hostname": socket.gethostname(),
                "platform": platform.system(),
            },
            "sync": {
                "from_": sync_from.isoformat(),
                "to": sync_to.isoformat(),
            },
            "activities": activities,
            "totals": totals,
            "page": page,
            "page_size": page_size,
        }

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

            POST /tracking/upload_screenshot
        """
        # Only call this API when capture_mode is activity_with_screenshots
        db_session = get_session()
        try:
            from database.repository import SettingsRepository
            repo = SettingsRepository(db_session)
            settings_record = repo.get_settings()
            if settings_record and not settings_record.capture_on_switch:
                logger.info("Screenshot upload skipped (capture_mode is not activity_with_screenshots)")
                return True
        except Exception as err:
            logger.error("Failed to check capture_mode in settings db: %s", err)
        finally:
            db_session.close()

        screenshot_path = Path(
            screenshot_path
        )

        import time
        attempts = 0
        while not screenshot_path.exists() and attempts < 50:
            time.sleep(0.1)
            attempts += 1

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
                    "screenshot": (
                        screenshot_path.name,
                        screenshot_file,
                        self._get_content_type(
                            screenshot_path
                        ),
                    )
                }

                from services.session_service import SessionService
                device_token = SessionService().device_token
                data = {
                    "device_token": device_token or "mock_device_token",
                    "activity_session_id": str(
                        activity_session_id
                    ),
                    "captured_at": (
                        self._to_utc(
                            captured_at
                        ).isoformat()
                    ),
                }

                logger.info(
                    "Uploading screenshot: %s",
                    screenshot_path,
                )

                response = requests.post(
                    f"{self._api_url}/tracking/upload_screenshot",
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
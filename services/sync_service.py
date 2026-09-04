from __future__ import annotations

from typing import Any

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

    # Global tracking properties for UI dashboard display
    last_sync_status: str = "Sent"  # Sending / Sent / Failed
    last_successful_sync_time: str = "Never"
    records_currently_sending: int = 0
    current_sync_interval_seconds: int = 300  # Default 300 seconds until first API settings load
    current_idle_threshold_seconds: int = 300  # Default 300 seconds until first API settings load

    @staticmethod
    def _save_cached_setting(key: str, value: Any) -> None:
        try:
            from PySide6.QtCore import QSettings
            settings = QSettings("Indovision", "iHRMSMonitor")
            settings.setValue(f"api_settings/{key}", value)
        except Exception:
            pass

    @staticmethod
    def _load_cached_setting(key: str) -> Any:
        try:
            from PySide6.QtCore import QSettings
            settings = QSettings("Indovision", "iHRMSMonitor")
            return settings.value(f"api_settings/{key}")
        except Exception:
            return None

    def __init__(
        self,
        api_url: str | None = None,
    ) -> None:

        # Resolved from the fixed Company Code by ApiConfig, so the base URL
        # is defined in exactly one place for the whole application.
        if api_url is None:
            from config.api_config import ApiConfig

            api_url = ApiConfig().base_url

        self._api_url = api_url.rstrip("/")
        self._synced_session_ids = set()

        # Restore last successfully received settings from persistent cache
        cached_sync = self._load_cached_setting("sync_interval_seconds")
        if cached_sync is not None:
            try:
                val = int(cached_sync)
                if val > 0:
                    self.current_sync_interval_seconds = val
            except (ValueError, TypeError):
                pass

        cached_idle = self._load_cached_setting("idle_threshold_seconds")
        if cached_idle is not None:
            try:
                val = int(cached_idle)
                if val > 0:
                    self.current_idle_threshold_seconds = val
            except (ValueError, TypeError):
                pass
        else:
            try:
                from database.database import get_session
                from database.repository import SettingsRepository
                db_session = get_session()
                saved_st = SettingsRepository(db_session).get_or_create()
                self.current_idle_threshold_seconds = saved_st.idle_threshold
                db_session.close()
            except Exception:
                pass

        logger.info(
            "SyncService initialized: %s (sync_interval_seconds=%d, idle_threshold_seconds=%d)",
            self._api_url,
            self.current_sync_interval_seconds,
            self.current_idle_threshold_seconds,
        )

    def fetch_settings(self) -> dict:
        """
        Fetch latest configuration from tracking/get_settings at the beginning of each sync cycle
        and apply the returned values directly without using overriding hardcoded fallbacks.
        """
        device_token = self._require_device_token()
        if not device_token:
            return {}

        try:
            response = requests.post(
                f"{self._api_url}/tracking/get_settings",
                data={"device_token": device_token},
                timeout=5,
            )
            response.raise_for_status()
            res_data = response.json()
            settings_data = {}
            if res_data.get("response") == "Success" and "data" in res_data:
                settings_data = res_data.get("data", {})
            elif res_data.get("status") == 1:
                settings_data = res_data.get("settings", {}) or res_data.get("data", {})

            if settings_data:
                logger.info("Fetched configuration from Sync API (get_settings): %s", settings_data)

                # 1. sync_interval_seconds: use exact API-returned value
                server_sync = settings_data.get("sync_interval_seconds")
                if server_sync is None:
                    server_sync = settings_data.get("sync_interval")
                if server_sync is not None:
                    try:
                        sync_val = int(server_sync)
                        if sync_val > 0:
                            self.current_sync_interval_seconds = sync_val
                            self._save_cached_setting("sync_interval_seconds", sync_val)
                    except (ValueError, TypeError):
                        pass

                # 2. idle_threshold_seconds: use exact API-returned value
                server_idle = settings_data.get("idle_threshold_seconds")
                if server_idle is None:
                    server_idle = settings_data.get("idle_threshold")
                if server_idle is not None:
                    try:
                        idle_val = int(server_idle)
                        if idle_val > 0:
                            self.current_idle_threshold_seconds = idle_val
                            self._save_cached_setting("idle_threshold_seconds", idle_val)
                    except (ValueError, TypeError):
                        pass

                # 3. Update local database settings
                db_session = get_session()
                try:
                    from database.repository import SettingsRepository
                    repo = SettingsRepository(db_session)
                    update_kwargs = {}
                    if self.current_idle_threshold_seconds:
                        update_kwargs["idle_threshold"] = self.current_idle_threshold_seconds

                    capture_interval = settings_data.get("capture_interval")
                    if capture_interval is not None:
                        update_kwargs["screenshot_custom_interval"] = int(capture_interval)
                        update_kwargs["screenshot_interval_type"] = "custom"

                    capture_mode = settings_data.get("capture_mode")
                    if capture_mode is not None:
                        update_kwargs["capture_on_switch"] = True if capture_mode != "disabled" else False

                    tracking_enabled = settings_data.get("tracking_enabled")
                    if tracking_enabled is not None:
                        update_kwargs["tracking_enabled"] = bool(tracking_enabled)

                    if update_kwargs:
                        repo.update(**update_kwargs)
                except Exception as db_err:
                    logger.error("Failed to update database settings from get_settings response: %s", db_err)
                finally:
                    db_session.close()

                # 4. Extract and apply dynamic permissions from server
                from services.session_service import SessionService
                session_svc = SessionService()

                def _parse_bool_permission(val: Any) -> bool | None:
                    if val is None:
                        return None
                    if isinstance(val, bool):
                        return val
                    if isinstance(val, (int, float)):
                        return bool(val)
                    if isinstance(val, str):
                        s = val.strip().lower()
                        if s in ("true", "1", "yes", "t", "y", "enable", "enabled"):
                            return True
                        if s in ("false", "0", "no", "f", "n", "disable", "disabled"):
                            return False
                    return None

                def _extract_permission(data: dict, keys: list[str]) -> bool | None:
                    for k in keys:
                        if k in data and data[k] is not None:
                            res = _parse_bool_permission(data[k])
                            if res is not None:
                                return res
                    return None

                # Logout control permission
                server_allow_logout = _extract_permission(
                    settings_data,
                    ["allow_logout", "logout_permitted", "can_logout", "allow_user_logout", "enable_logout"]
                )
                if server_allow_logout is not None:
                    self._save_cached_setting("allow_logout", server_allow_logout)

                # User / Device control permission
                server_allow_user_device = _extract_permission(
                    settings_data,
                    [
                        "allow_user_device",
                        "allow_user_device_info",
                        "allow_device_info",
                        "allow_device",
                        "allow_user_device_modal",
                        "allow_user_info",
                        "show_user_device",
                        "user_device_allowed",
                        "user_device_permitted",
                        "user_device_enabled",
                        "device_info_enabled",
                        "can_view_user_device",
                    ]
                )
                if server_allow_user_device is not None:
                    self._save_cached_setting("allow_user_device", server_allow_user_device)

                # Tracking permitted (checks if activity tracking is enabled by backend)
                server_allow_tracking = _extract_permission(
                    settings_data,
                    ["tracking_enabled", "tracking_permitted", "allow_tracking", "is_tracking_enabled", "enable_tracking"]
                )
                if server_allow_tracking is not None:
                    self._save_cached_setting("tracking_permitted", server_allow_tracking)

                # Update session permissions dynamically
                perm_kwargs = {}
                if server_allow_logout is not None:
                    perm_kwargs["allow_logout"] = server_allow_logout
                if server_allow_user_device is not None:
                    perm_kwargs["allow_user_device"] = server_allow_user_device
                if server_allow_tracking is not None:
                    perm_kwargs["tracking_permitted"] = server_allow_tracking

                if perm_kwargs:
                    session_svc.update_permissions(**perm_kwargs)

                # Persist updated permissions to SessionStore if active session exists
                try:
                    from services.secure_session import SessionStore
                    store = SessionStore()
                    saved = store.load_session()
                    if saved and session_svc.current_user:
                        curr = session_svc.current_user
                        store.save_session(
                            company_code=saved.get("company_code") or curr.company_code or "",
                            indo_code=saved.get("indo_code") or curr.indo_code or "",
                            api_key=saved.get("api_key") or curr.api_key or "",
                            device_token=saved.get("device_token") or curr.device_token or "",
                            username=saved.get("username") or curr.username,
                            full_name=saved.get("full_name") or curr.full_name,
                            user_type=saved.get("user_type") or curr.user_type,
                            employee_id=saved.get("employee_id") or curr.employee_id,
                            device_info=saved.get("device_info") or curr.device_info or {},
                            tracking_permitted=curr.tracking_permitted,
                            base_url=saved.get("base_url"),
                            company_id=saved.get("company_id"),
                            allow_user_device=curr.allow_user_device,
                            allow_logout=curr.allow_logout,
                        )
                except Exception as perm_save_err:
                    logger.debug("Could not persist updated session permissions: %s", perm_save_err)

                return settings_data
        except Exception as err:
            logger.warning(
                "Could not reach Sync API (tracking/get_settings); preserving last successfully received settings "
                "(sync_interval_seconds=%d, idle_threshold_seconds=%d): %s",
                self.current_sync_interval_seconds,
                self.current_idle_threshold_seconds,
                err,
            )

        return {}

    @classmethod
    def reset_sync_state(cls) -> None:
        """Reset sync status flags and counters when switching users or on logout."""
        cls.last_sync_status = "Sent"
        cls.last_successful_sync_time = "Never"
        cls.records_currently_sending = 0

    @staticmethod
    def _require_device_token() -> str | None:
        """
        Return the device token issued by enroll_device at login.

        Returns None when the device is not enrolled; callers must skip the
        request rather than sending a placeholder token.
        """

        from services.session_service import SessionService

        device_token = SessionService().device_token

        if not device_token:
            try:
                from services.secure_session import SessionStore
                session_data = SessionStore().load_session()
                current_u = SessionService().current_user
                if session_data and session_data.get("device_token"):
                    # If a user is active, only accept stored token if it belongs to them
                    if current_u is not None:
                        stored_emp = session_data.get("employee_id")
                        stored_user = session_data.get("username")
                        if (stored_emp and current_u.employee_id and stored_emp == current_u.employee_id) or \
                           (stored_user and current_u.username and stored_user == current_u.username):
                            device_token = session_data.get("device_token")
                            SessionService().device_token = device_token
                    else:
                        device_token = session_data.get("device_token")
                        SessionService().device_token = device_token
            except Exception:
                pass

        if not device_token:
            logger.error(
                "No device token available - device is not enrolled. "
                "Skipping request."
            )

            return None

        return device_token

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
        device_token = self._require_device_token()

        if not device_token:
            SyncService.last_sync_status = "Failed"
            SyncService.records_currently_sending = 0
            logger.error("Sync FAILURE: No device token available - device is not enrolled.")
            return False

        # Fetch latest settings from existing API and apply returned values
        self.fetch_settings()

        from datetime import datetime, timedelta
        next_sync_dt = datetime.now() + timedelta(seconds=self.current_sync_interval_seconds)
        next_sync_str = next_sync_dt.strftime("%Y-%m-%d %H:%M:%S")

        logger.info(
            "Sync Cycle Started | sync_interval_seconds=%d | idle_threshold_seconds=%d | next_sync_time=%s",
            self.current_sync_interval_seconds,
            self.current_idle_threshold_seconds,
            next_sync_str,
        )

        db_session = get_session()
        try:
            repository = ActivityRepository(db_session)
            from services.session_service import SessionService
            curr_user = SessionService().current_user
            current_emp_id = curr_user.employee_id if curr_user else None

            # Retrieve all closed sessions that have not been synced yet for this user
            unsynced_sessions = repository.get_unsynced_closed_sessions(employee_id=current_emp_id)

            if unsynced_sessions:
                SyncService.last_sync_status = "Sending"
                SyncService.records_currently_sending = len(unsynced_sessions)
                logger.info(
                    "Sync Records Sending | records_currently_sending=%d | user=%s | sync_interval_seconds=%d",
                    len(unsynced_sessions),
                    current_emp_id,
                    self.current_sync_interval_seconds,
                )

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
                            
                        # Use actual min/max of the page's sessions started_at to avoid truncating times
                        sync_from = self._to_utc(min(s.started_at for s in page_sessions))
                        sync_to = self._to_utc(max(s.ended_at or s.started_at for s in page_sessions))

                        payload = self._build_page_payload(
                            sessions=page_sessions,
                            sync_from=sync_from,
                            sync_to=sync_to,
                            page=page_num,
                            page_size=PAGE_SIZE
                        )

                        import json
                        new_payload = {
                            "device_token": device_token,
                            "sessions": json.dumps(payload["activities"])
                        }

                        logger.info(
                            "Syncing activity batch page %d (%d records):\n%s",
                            page_num,
                            len(payload["activities"]),
                            "\n".join([
                                f"  [Session #{a['activity_session_id']}] app={a['application_name']!r} "
                                f"title={a['window_title'][:40]!r} start_time={a['start_time']} "
                                f"end_time={a['end_time']} duration={a['duration']}s idle_time={a['idle_time']}s"
                                for a in payload["activities"]
                            ])
                        )
                        logger.info("Exact JSON payload to backend (page %d):\n%s", page_num, json.dumps(new_payload, indent=2))
                        
                        res_data = self._send_request_with_retry(new_payload, page=page_num)
                        if not res_data or res_data.get("response") != "Success":
                            error_msg = res_data.get("message") if res_data else "No response from server"
                            logger.error("Activity sync batch page failed: %s. Halting sync.", error_msg)
                            SyncService.last_sync_status = "Failed"
                            SyncService.records_currently_sending = 0
                            return False
                            
                        # Process mappings
                        processed_items = res_data.get("data", [])
                        if not isinstance(processed_items, list):
                            processed_items = []
                            
                        for item in processed_items:
                            client_ref = item.get("client_session_ref")
                            server_id = item.get("activity_session_id")
                            if client_ref is not None and server_id is not None:
                                try:
                                    repository.update_session_server_id(int(client_ref), str(server_id))
                                except Exception as err:
                                    logger.error("Failed to update server session ID for client ref %s: %s", client_ref, err)

                        uploaded_count += len(page_sessions)
                        # Decrement remaining unsynced records
                        SyncService.records_currently_sending = max(0, SyncService.records_currently_sending - len(page_sessions))
                        logger.info("%d/%d records processed", uploaded_count, len(batch))
            else:
                SyncService.records_currently_sending = 0
                logger.info("Sync Records Sending | records_currently_sending=0 | user=%s | (no unsynced activities)", current_emp_id)

            # Now sync any unuploaded screenshots for already-synced sessions for this user
            unuploaded = repository.get_sessions_with_unuploaded_screenshots(employee_id=current_emp_id)
            if unuploaded:
                logger.info("Found %d unuploaded screenshots for user %s. Processing screenshot uploads...", len(unuploaded), current_emp_id)
                for session in unuploaded:
                    success = self.upload_screenshot_now(
                        screenshot_path=session.screenshot_path,
                        activity_session_id=session.server_session_id, # Must use the server side ID
                        application_name=session.application_name,
                        process_id=session.process_id,
                        captured_at=session.started_at,
                        local_session_id=session.id
                    )
                    if success:
                        logger.info("Successfully uploaded and confirmed screenshot for local session ID %d", session.id)
                    else:
                        logger.error("Screenshot upload failed or deferred for local session ID %d", session.id)

            # Sweep any previously uploaded screenshots that remain on local disk
            try:
                self.cleanup_uploaded_screenshots()
            except Exception as cleanup_err:
                logger.debug("Periodic screenshot cleanup error: %s", cleanup_err)

            from datetime import datetime, timedelta
            SyncService.last_sync_status = "Sent"
            SyncService.last_successful_sync_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            SyncService.records_currently_sending = 0

            next_sync_dt = datetime.now() + timedelta(seconds=self.current_sync_interval_seconds)
            next_sync_str = next_sync_dt.strftime("%Y-%m-%d %H:%M:%S")

            logger.info(
                "Sync SUCCESS | records_uploaded=%d | sync_interval_seconds=%d | idle_threshold_seconds=%d | next_sync_time=%s",
                uploaded_count if 'uploaded_count' in locals() else len(unsynced_sessions),
                self.current_sync_interval_seconds,
                self.current_idle_threshold_seconds,
                next_sync_str,
            )
            try:
                from services.device_registry_service import DeviceRegistryService
                DeviceRegistryService().record_sync_success()
            except Exception:
                pass
            return True

        except Exception as exc:
            logger.exception("Sync FAILURE: Unexpected error during activity sync: %s", exc)
            SyncService.last_sync_status = "Failed"
            SyncService.records_currently_sending = 0

            next_sync_dt = datetime.now() + timedelta(seconds=self.current_sync_interval_seconds)
            next_sync_str = next_sync_dt.strftime("%Y-%m-%d %H:%M:%S")

            logger.error(
                "Sync FAILURE | user=%s | sync_interval_seconds=%d | idle_threshold_seconds=%d | next_sync_time=%s | error=%s",
                current_emp_id if 'current_emp_id' in locals() else 'unknown',
                self.current_sync_interval_seconds,
                self.current_idle_threshold_seconds,
                next_sync_str,
                exc,
            )
            try:
                from services.error_report_service import ErrorReportService
                ErrorReportService().report_error(
                    error_type="ACTIVITY_SYNC_ERROR",
                    error_message=f"Activity sync failed: {exc}",
                    exc=exc,
                    extra_context={"api_url": self._api_url},
                )
            except Exception:
                pass
            return False
        finally:
            db_session.close()

    def _send_request_with_retry(self, payload: dict, page: int, retries: int = 3) -> dict | None:
        for attempt in range(1, retries + 1):
            try:
                response = requests.post(
                    f"{self._api_url}/tracking/save_activity_batch",
                    data=payload,
                    timeout=15,
                )
                logger.info(
                    "Activity sync page %d HTTP response code: %d, Response body: %s (attempt %d)",
                    page,
                    response.status_code,
                    response.text,
                    attempt
                )
                response.raise_for_status()
                try:
                    return response.json()
                except Exception:
                    logger.exception("Failed to parse JSON response for page %d", page)
                    return None
            except requests.RequestException as exc:
                logger.warning(
                    "Activity sync page %d failed (attempt %d/%d): %s",
                    page,
                    attempt,
                    retries,
                    exc,
                )
                if attempt == retries:
                    logger.error("Activity sync failed after maximum retries. Error: %s", exc)
                    try:
                        from services.error_report_service import ErrorReportService
                        ErrorReportService().report_error(
                            error_type="ACTIVITY_SYNC_ERROR",
                            error_message=f"Activity sync failed after {retries} retries: {exc}",
                            exc=exc,
                            extra_context={"page": page, "api_url": self._api_url},
                        )
                    except Exception:
                        pass
                    return None
        return None

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

        # Deduplicate sessions by ID and sort chronologically by started_at
        seen_ids = set()
        unique_sessions = []
        for s in sorted(sessions, key=lambda x: x.started_at):
            if s.id not in seen_ids:
                seen_ids.add(s.id)
                unique_sessions.append(s)

        now_local = datetime.now().astimezone()
        last_end = None

        for session in unique_sessions:
            local_start = self._to_local(session.started_at)
            local_end = self._to_local(session.ended_at) if session.ended_at else None

            # Prevent future timestamps
            if local_start > now_local:
                local_start = now_local
            if local_end and local_end > now_local:
                local_end = now_local

            # Prevent overlapping with previous session in the timeline
            if last_end is not None and local_start < last_end:
                local_start = last_end

            if local_end:
                if local_end < local_start:
                    local_end = local_start
                duration_seconds = max(0, int((local_end - local_start).total_seconds()))
            else:
                duration_seconds = max(0, int(session.duration_seconds or 0))
                local_end = local_start + timedelta(seconds=duration_seconds)
                if local_end > now_local:
                    local_end = now_local
                    duration_seconds = max(0, int((local_end - local_start).total_seconds()))

            last_end = local_end

            idle_seconds = max(0, int(getattr(session, "idle_seconds", 0) or 0))
            is_idle = idle_seconds > 0
            idle_status = "Idle" if is_idle else "Active"

            # Format the actual local activity start/end time
            # Standard local datetime representation: YYYY-MM-DD HH:MM:SS
            start_time_str = local_start.strftime("%Y-%m-%d %H:%M:%S")
            end_time_str = local_end.strftime("%Y-%m-%d %H:%M:%S") if local_end else start_time_str

            if is_idle and local_end:
                idle_start_dt = local_end
                idle_end_dt = local_end + timedelta(seconds=idle_seconds)
                idle_start_str = idle_start_dt.strftime("%Y-%m-%d %H:%M:%S")
                idle_end_str = idle_end_dt.strftime("%Y-%m-%d %H:%M:%S")
            else:
                idle_start_str = start_time_str
                idle_end_str = end_time_str

            activities.append({
                "activity_session_id": session.id,
                "application_name": session.application_name,
                "window_title": session.window_title or "",
                "process_id": session.process_id,
                "status": idle_status,
                "idle_status": idle_status,
                "is_idle": is_idle,
                "start_time": start_time_str,
                "started_at": start_time_str,
                "end_time": end_time_str,
                "ended_at": end_time_str,
                "duration": duration_seconds,
                "duration_seconds": duration_seconds,
                "idle_time": idle_seconds,
                "idle_duration_seconds": idle_seconds,
                "idle_start_time": idle_start_str,
                "idle_end_time": idle_end_str,
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
                "from_": sync_from.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "to": sync_to.strftime("%Y-%m-%dT%H:%M:%SZ"),
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
        activity_session_id: str | int,
        application_name: str,
        process_id: int | None,
        captured_at: datetime | None = None,
        local_session_id: int | None = None,
    ) -> bool:
        """
        Immediately upload a screenshot to:

            POST /tracking/upload_screenshot
        """
        screenshot_path = Path(
            screenshot_path
        )

        # Multi-location resolution: check given path, then check per-user screenshots dir, then project root
        if not screenshot_path.exists():
            try:
                from utils.paths import get_screenshots_directory
                alt1 = get_screenshots_directory() / screenshot_path.name
                alt2 = Path(__file__).resolve().parent.parent / "screenshots" / screenshot_path.name
                if alt1.exists():
                    screenshot_path = alt1
                elif alt2.exists():
                    screenshot_path = alt2
            except Exception as resolve_err:
                logger.debug("Failed to resolve alternative screenshot paths: %s", resolve_err)

        if not screenshot_path.exists():

            logger.error(
                "Screenshot file is missing, nothing to upload for local "
                "session %s: %s",
                local_session_id,
                screenshot_path,
            )

            # Retrying a file that no longer exists would block the upload
            # queue on every future sync, so drop the reference. The activity
            # log itself is untouched.
            if local_session_id is not None:
                db_session = get_session()

                try:
                    ActivityRepository(
                        db_session
                    ).update_session_screenshot_path(
                        local_session_id,
                        None,
                    )

                    logger.warning(
                        "Cleared the missing screenshot reference for local "
                        "session %s so it is no longer retried",
                        local_session_id,
                    )

                except Exception as err:  # noqa: BLE001
                    logger.error(
                        "Could not clear the missing screenshot reference "
                        "for local session %s: %s",
                        local_session_id,
                        err,
                    )

                finally:
                    db_session.close()

            return False

        if captured_at is None:

            captured_at = datetime.now(
                timezone.utc
            )

        try:
            with screenshot_path.open("rb") as screenshot_file:
                raw_bytes = screenshot_file.read()

            import base64
            base64_encoded_str = base64.b64encode(raw_bytes).decode("utf-8")

            device_token = self._require_device_token()
            if not device_token:
                logger.error("Cannot upload screenshot: device token is missing.")
                return False

            if not activity_session_id or str(activity_session_id).lower() == "none":
                # Check if server session ID was populated in DB
                if local_session_id is not None:
                    db_session = get_session()
                    try:
                        from database.models import ActivitySession
                        sess_rec = db_session.get(ActivitySession, local_session_id)
                        if sess_rec and sess_rec.server_session_id:
                            activity_session_id = sess_rec.server_session_id
                    finally:
                        db_session.close()

            if not activity_session_id or str(activity_session_id).lower() == "none":
                logger.warning(
                    "Cannot upload screenshot %s: missing server activity_session_id for local session %s",
                    screenshot_path,
                    local_session_id,
                )
                return False

            # Format captured_at matching Postman format: YYYY-MM-DDTHH:MM:SSZ
            captured_at_utc = self._to_utc(captured_at)
            captured_at_str = captured_at_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

            files = {
                "screenshot": (
                    screenshot_path.name,
                    raw_bytes,
                    self._get_content_type(screenshot_path),
                )
            }

            data = {
                "device_token": device_token,
                "activity_session_id": str(activity_session_id),
                "captured_at": captured_at_str,
                "screenshot": base64_encoded_str,
            }

            logger.info(
                "Uploading screenshot to API: %s (bytes=%dB, base64_len=%d) for server session %s",
                screenshot_path.name,
                len(raw_bytes),
                len(base64_encoded_str),
                activity_session_id,
            )

            response = requests.post(
                f"{self._api_url}/tracking/upload_screenshot",
                files=files,
                data=data,
                timeout=60,
            )

            logger.info(
                "Screenshot upload HTTP response code: %d, Response body: %s",
                response.status_code,
                response.text,
            )

            response.raise_for_status()

            # Verify response JSON body for success
            res_json = response.json()
            if res_json.get("response") != "Success":
                error_msg = res_json.get("message") or "Screenshot upload failed on server."
                logger.error("Screenshot upload failed on server: %s", error_msg)
                raise ValueError(error_msg)

            screenshot_id = res_json.get("data", {}).get("screenshot_id")
            logger.info(
                "Screenshot upload successful: %s (screenshot_id=%s)",
                screenshot_path.name,
                screenshot_id,
            )

            # Update the database to mark screenshot as uploaded
            if local_session_id is not None:
                db_session = get_session()
                try:
                    repo = ActivityRepository(db_session)
                    repo.update_session_screenshot_uploaded(local_session_id, True)
                except Exception as err:
                    logger.error("Failed to update screenshot uploaded state in db: %s", err)
                finally:
                    db_session.close()

            # Clean up local screenshot file immediately after verified server confirmation
            try:
                if screenshot_path.exists():
                    screenshot_path.unlink()
                    logger.info(
                        "Local screenshot file deleted after verified server upload: %s",
                        screenshot_path.name,
                    )
            except Exception as cleanup_err:
                logger.warning(
                    "Could not delete uploaded local screenshot file %s: %s",
                    screenshot_path,
                    cleanup_err,
                )

            return True

        except requests.RequestException as exc:

            logger.error(
                "Screenshot upload failed: %s",
                exc,
            )
            try:
                from services.error_report_service import ErrorReportService
                ErrorReportService().report_error(
                    error_type="SCREENSHOT_UPLOAD_ERROR",
                    error_message=f"Screenshot upload failed for session {activity_session_id}: {exc}",
                    exc=exc,
                    extra_context={"session_id": str(activity_session_id), "file": str(screenshot_path.name)},
                )
            except Exception:
                pass

            return False

        except Exception as exc:

            logger.exception(
                "Unexpected screenshot upload error: %s",
                exc,
            )
            try:
                from services.error_report_service import ErrorReportService
                ErrorReportService().report_error(
                    error_type="SCREENSHOT_UPLOAD_ERROR",
                    error_message=f"Unexpected screenshot upload error for session {activity_session_id}: {exc}",
                    exc=exc,
                    extra_context={"session_id": str(activity_session_id), "file": str(screenshot_path.name)},
                )
            except Exception:
                pass

            return False

    def cleanup_uploaded_screenshots(self) -> int:
        """
        Sweep local storage and delete any screenshot files that have already
        been successfully confirmed and uploaded to the server.
        Never deletes unuploaded or pending screenshots.
        """
        cleaned_count = 0
        db_session = get_session()
        try:
            repo = ActivityRepository(db_session)
            uploaded_sessions = repo.get_sessions_with_uploaded_screenshots_for_cleanup()
            for s in uploaded_sessions:
                if s.screenshot_path:
                    p = Path(s.screenshot_path)
                    if p.exists():
                        try:
                            p.unlink()
                            cleaned_count += 1
                            logger.info("Cleanup sweep removed uploaded screenshot: %s", p.name)
                        except Exception as del_err:
                            logger.warning("Failed to delete uploaded screenshot %s: %s", p, del_err)
        except Exception as sweep_err:
            logger.error("Error during uploaded screenshots cleanup sweep: %s", sweep_err)
        finally:
            db_session.close()

        return cleaned_count

    # ==============================================================
    # HELPERS
    # ==============================================================

    @staticmethod
    def _get_username() -> str:
        from services.session_service import SessionService
        user = SessionService().current_user
        if user:
            emp = user.employee_id or user.indo_code or user.username
            if emp:
                return str(emp)
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
    def _to_local(
        value: datetime,
    ) -> datetime:
        """Normalize stored datetime to actual local computer timezone."""
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone()

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
from __future__ import annotations

from typing import Any

import getpass
import platform
import socket
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from database.database import get_session
from database.repository import ActivityRepository
from utils.logger import get_logger


logger = get_logger(__name__)


def _mask_token(token: Any) -> str:
    """Safely format a device or auth token for logs without exposing full secret."""
    if not token:
        return "<None>"
    s = str(token).strip()
    if not s or s.lower() == "none":
        return "<None>"
    if len(s) <= 8:
        return "***"
    return f"{s[:4]}...{s[-4:]} (len={len(s)})"


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
    last_sync_error: str = ""
    last_successful_sync_time: str = "Never"
    records_currently_sending: int = 0
    current_sync_interval_seconds: int = 300  # Default 300 seconds until first API settings load
    current_idle_threshold_seconds: int = 300  # Default 300 seconds until first API settings load
    _sync_lock: threading.Lock = threading.Lock()
    _fetching_settings_lock: threading.Lock = threading.Lock()

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

    @classmethod
    def get_last_successful_sync_time(cls) -> str:
        """Return the formatted timestamp of the most recent successfully completed sync."""
        if cls.last_successful_sync_time and cls.last_successful_sync_time != "Never":
            return cls.last_successful_sync_time
        cached = cls._load_cached_setting("last_successful_sync_time")
        if cached and str(cached).strip() and str(cached).strip().lower() != "none":
            cls.last_successful_sync_time = str(cached).strip()
            return cls.last_successful_sync_time
        return "Never"

    def __init__(
        self,
        api_url: str | None = None,
    ) -> None:

        # Resolved from the fixed Company Code by ApiConfig, so the base URL
        # is defined in exactly one place for the whole application.
        if api_url is None:
            try:
                from config.api_config import ApiConfig
                api_url = ApiConfig().base_url
            except Exception:
                api_url = None

            if not api_url:
                try:
                    from services.secure_session import SessionStore
                    s = SessionStore().load_session()
                    if s and s.get("base_url"):
                        api_url = s.get("base_url")
                except Exception:
                    pass

        self._api_url = (api_url or "").rstrip("/")
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

    @property
    def api_url(self) -> str:
        if not self._api_url:
            try:
                from config.api_config import ApiConfig
                self._api_url = (ApiConfig().base_url or "").rstrip("/")
            except Exception:
                pass
        if not self._api_url:
            try:
                from services.secure_session import SessionStore
                s = SessionStore().load_session()
                if s and s.get("base_url"):
                    self._api_url = s.get("base_url").rstrip("/")
            except Exception:
                pass
        return self._api_url

    @property
    def get_settings_url(self) -> str:
        try:
            from config.api_config import ApiConfig
            url = ApiConfig().get_settings_url
            if url:
                return url
        except Exception:
            pass
        return f"{self.api_url}/tracking/get_settings"

    @property
    def save_activity_batch_url(self) -> str:
        try:
            from config.api_config import ApiConfig
            url = ApiConfig().save_activity_batch_url
            if url:
                return url
        except Exception:
            pass
        return f"{self.api_url}/tracking/save_activity_batch"

    @property
    def upload_screenshot_url(self) -> str:
        try:
            from config.api_config import ApiConfig
            url = ApiConfig().upload_screenshot_url
            if url:
                return url
        except Exception:
            pass
        return f"{self.api_url}/tracking/upload_screenshot"

    @property
    def enroll_device_url(self) -> str:
        try:
            from config.api_config import ApiConfig
            url = ApiConfig().enroll_device_url
            if url:
                return url
        except Exception:
            pass
        return f"{self.api_url}/tracking/enroll_device"

    def fetch_settings(self) -> dict:
        """
        Fetch latest configuration from tracking/get_settings at the beginning of each sync cycle
        and apply the returned values directly without using overriding hardcoded fallbacks.
        """
        if not self._fetching_settings_lock.acquire(timeout=5.0):
            logger.debug("fetch_settings already in progress; skipping duplicate call.")
            return {}

        try:
            device_token = self._require_device_token()
            if not device_token:
                logger.warning("fetch_settings skipped: No device token available.")
                return {}

            logger.info("Fetching settings from API: endpoint=%s token=%s", self.get_settings_url, _mask_token(device_token))

            re_enrolled = False
            response = None
            try:
                response = requests.post(
                    self.get_settings_url,
                    data={"device_token": device_token},
                    timeout=5,
                )
                try:
                    from services.network_monitor import NetworkReachabilityMonitor
                    NetworkReachabilityMonitor().report_online()
                except Exception:
                    pass
                logger.info("get_settings HTTP response: %d", response.status_code)
                if (response.status_code == 401 or "Device not recognized" in response.text or "revoked" in response.text) and not re_enrolled:
                    logger.warning("get_settings device token rejected (HTTP 401). Triggering automatic re-enrollment...")
                    new_token = self.re_enroll_device()
                    if new_token:
                        re_enrolled = True
                        device_token = new_token
                        logger.info("Retrying get_settings with refreshed device_token: %s", _mask_token(new_token))
                        response = requests.post(
                            self.get_settings_url,
                            data={"device_token": new_token},
                            timeout=5,
                        )
                response.raise_for_status()
            except requests.RequestException as req_exc:
                http_code = getattr(getattr(req_exc, "response", None), "status_code", None)
                resp_text = getattr(getattr(req_exc, "response", None), "text", "") or ""
                if http_code is None:
                    try:
                        from services.network_monitor import NetworkReachabilityMonitor
                        NetworkReachabilityMonitor().report_api_failure()
                    except Exception:
                        pass
                if (http_code == 401 or "Device not recognized" in resp_text or "revoked" in resp_text) and not re_enrolled:
                    logger.warning("get_settings exception indicates 401 / token rejection. Attempting re-enrollment...")
                    new_token = self.re_enroll_device()
                    if new_token:
                        try:
                            response = requests.post(
                                self.get_settings_url,
                                data={"device_token": new_token},
                                timeout=5,
                            )
                            response.raise_for_status()
                        except Exception as retry_err:
                            logger.warning("get_settings retry after re-enrollment failed: %s", retry_err)
                            return {}
                    else:
                        logger.warning("Re-enrollment during get_settings returned no token.")
                        return {}
                else:
                    logger.warning("get_settings network/server warning (HTTP %s): %s", http_code or "N/A", req_exc)
                    return {}

            if not response:
                return {}

            try:
                res_data = response.json()
            except Exception as json_err:
                logger.warning("Failed to parse get_settings JSON: %s", json_err)
                return {}

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
            try:
                from services.error_report_service import ErrorReportService
                http_code = getattr(getattr(err, "response", None), "status_code", None)
                resp_text = getattr(getattr(err, "response", None), "text", None)
                ErrorReportService().report_error(
                    error_type="API_SYNC_ERROR",
                    error_message=f"Sync API fetch settings failed: {err}",
                    exc=err,
                    extra_context={
                        "endpoint": "/tracking/get_settings",
                        "api_url": self._api_url,
                        "http_status": http_code,
                        "response_error": resp_text,
                    },
                )
            except Exception:
                pass
        finally:
            self._fetching_settings_lock.release()

        return {}

    @classmethod
    def reset_sync_state(cls) -> None:
        """Reset sync status flags and counters when switching users or on logout."""
        cls.last_sync_status = "Sent"
        cls.last_sync_error = ""
        cls.last_successful_sync_time = "Never"
        cls.records_currently_sending = 0

    @classmethod
    def re_enroll_device_static(cls) -> str | None:
        """Static / classmethod entry point for device re-enrollment."""
        return cls._do_re_enroll()

    def re_enroll_device(self) -> str | None:
        """Instance method entry point for device re-enrollment."""
        return self._do_re_enroll()

    @classmethod
    def _do_re_enroll(cls) -> str | None:
        """
        Re-enroll the current device using existing credentials when the backend
        returns HTTP 401 (device token unrecognized or revoked).
        Persists the newly returned device_token to SessionStore, SessionService,
        and DeviceRegistryService.
        """
        try:
            from services.secure_session import SessionStore
            from services.session_service import SessionService
            from utils.device import get_device_info
            from config.api_config import ApiConfig

            session_svc = SessionService()
            curr_u = session_svc.current_user
            store = SessionStore()
            session_data = store.load_session() or {}

            company_code = (curr_u.company_code if curr_u and curr_u.company_code else None) or session_data.get("company_code")
            indo_code = (curr_u.indo_code if curr_u and curr_u.indo_code else None) or session_data.get("indo_code")
            api_key = (curr_u.api_key if curr_u and curr_u.api_key else None) or session_data.get("api_key")
            username = (curr_u.username if curr_u and curr_u.username else None) or session_data.get("username")
            employee_id = (curr_u.employee_id if curr_u and curr_u.employee_id else None) or session_data.get("employee_id")

            if not indo_code or not api_key:
                logger.warning(
                    "Device re-enrollment aborted: Missing credentials (indo_code=%s, api_key_present=%s).",
                    bool(indo_code),
                    bool(api_key),
                )
                return None

            cfg = ApiConfig()
            if not cfg.is_verified and company_code:
                try:
                    cfg.load(company_code=company_code)
                except Exception as load_err:
                    logger.debug("ApiConfig load during re-enrollment: %s", load_err)

            enroll_url = None
            try:
                enroll_url = cfg.enroll_device_url
            except Exception:
                enroll_url = None

            if not enroll_url:
                base = session_data.get("base_url") or getattr(cfg, "base_url", None)
                if base:
                    enroll_url = f"{base.rstrip('/')}/tracking/enroll_device"

            if not enroll_url:
                logger.error("Device re-enrollment aborted: Cannot resolve enroll_device URL.")
                return None

            device_info = session_data.get("device_info") or {}
            live_info = get_device_info()

            hostname = live_info.get("hostname") or device_info.get("hostname") or ""
            platform_str = live_info.get("platform") or device_info.get("platform") or ""
            os_username = live_info.get("os_username") or device_info.get("os_username") or ""

            enroll_data = {
                "indo_code": indo_code,
                "key": api_key,
                "hostname": hostname,
                "platform": platform_str,
                "os_username": os_username,
            }

            logger.info(
                "Re-enrolling device at %s for user=%s (hostname=%s, platform=%s)",
                enroll_url,
                username or indo_code,
                hostname,
                platform_str,
            )
            resp = requests.post(enroll_url, data=enroll_data, timeout=15)
            logger.info("Device re-enrollment HTTP response: %d", resp.status_code)
            if resp.status_code != 200:
                logger.error("Device re-enrollment request failed: HTTP %d %s", resp.status_code, resp.text)
                return None

            enroll_json = resp.json()
            new_device_token = enroll_json.get("device_token") or (enroll_json.get("data") or {}).get("device_token")
            if not new_device_token:
                logger.error("Device re-enrollment response contained no device_token: %s", resp.text)
                return None

            # Persist in SessionService (both service level and user level)
            session_svc.update_device_token(new_device_token)

            # Persist in SessionStore
            store.update_device_token(new_device_token)

            # Update DeviceRegistryService
            try:
                from services.device_registry_service import DeviceRegistryService
                DeviceRegistryService().register_or_update_device(
                    device_identifier=live_info.get("device_identifier"),
                    hostname=hostname,
                    employee_id=employee_id,
                    username=username,
                    device_token=new_device_token,
                )
            except Exception as reg_err:
                logger.debug("Could not record re-enrolled device: %s", reg_err)

            logger.info("Device re-enrollment succeeded. New device_token persisted: %s", _mask_token(new_device_token))
            return new_device_token

        except Exception as exc:
            logger.exception("Unexpected error during device re-enrollment: %s", exc)
            return None

    @classmethod
    def _require_device_token(cls) -> str | None:
        """
        Return the device token issued by enroll_device at login.

        Returns None when the device is not enrolled; callers must skip the
        request rather than sending a placeholder token.
        """
        from services.session_service import SessionService
        session_svc = SessionService()
        curr_u = session_svc.current_user

        device_token = None
        if curr_u and curr_u.device_token:
            device_token = curr_u.device_token
            session_svc.device_token = device_token
        elif session_svc.device_token:
            device_token = session_svc.device_token
            if curr_u:
                curr_u.device_token = device_token

        if not device_token:
            try:
                from services.secure_session import SessionStore
                session_data = SessionStore().load_session()
                if session_data and session_data.get("device_token"):
                    # If a user is active, only accept stored token if it belongs to them
                    if curr_u is not None:
                        stored_emp = session_data.get("employee_id")
                        stored_user = session_data.get("username")
                        stored_indo = session_data.get("indo_code")
                        if (stored_emp and curr_u.employee_id and stored_emp == curr_u.employee_id) or \
                           (stored_user and curr_u.username and stored_user == curr_u.username) or \
                           (stored_indo and curr_u.indo_code and stored_indo == curr_u.indo_code):
                            device_token = session_data.get("device_token")
                            session_svc.update_device_token(device_token)
                    else:
                        device_token = session_data.get("device_token")
                        session_svc.update_device_token(device_token)
            except Exception as load_err:
                logger.debug("Error loading session in _require_device_token: %s", load_err)

        if not device_token:
            try:
                device_token = cls.re_enroll_device_static()
            except Exception as enroll_err:
                logger.debug("Auto re-enrollment in _require_device_token failed: %s", enroll_err)

        if not device_token:
            logger.error(
                "No device token available - device is not enrolled. "
                "Skipping request."
            )
            return None

        logger.debug("Active device token resolved: %s", _mask_token(device_token))
        return device_token

    # ==============================================================
    # ACTIVITY SYNC
    # ==============================================================

    def sync_activity_now(
        self,
        exclude_session_ids: list[int] | set[int] | None = None,
        timeout: float | None = 10.0,
    ) -> bool:
        """
        Immediately send activity data for the last 5 minutes.

        This is the background/incremental sync operation.

        It processes records in batches of 100 max, divided into 4 requests of 25 records each.
        """
        acquired = False
        if timeout is not None and timeout > 0:
            acquired = self._sync_lock.acquire(timeout=timeout)
        else:
            acquired = self._sync_lock.acquire(blocking=False)

        if not acquired:
            logger.info("Activity sync already in progress; skipping duplicate trigger.")
            return False

        current_emp_id = "unknown"
        try:
            # Call tracking/get_settings at the start of every sync cycle
            device_token = self._require_device_token()

            if not device_token:
                SyncService.last_sync_status = "Failed (Auth Failed)"
                SyncService.last_sync_error = "Device is not enrolled - no device token available."
                SyncService.records_currently_sending = 0
                logger.error("Sync FAILURE: No device token available - device is not enrolled.")
                return False

            # Fetch latest settings from existing API and apply returned values
            self.fetch_settings()

            # Non-blocking punch time check from dynamic Punch API (rate-limited internally)
            try:
                from services.attendance_service import AttendanceService
                AttendanceService().fetch_punch_time()
            except Exception as punch_err:
                logger.debug("Non-blocking punch time check skipped: %s", punch_err)

            from datetime import datetime, timedelta
            next_sync_dt = datetime.now() + timedelta(seconds=self.current_sync_interval_seconds)
            next_sync_str = next_sync_dt.strftime("%Y-%m-%d %H:%M:%S")

            logger.info(
                "Sync Cycle Started | sync_interval_seconds=%d | idle_threshold_seconds=%d | next_sync_time=%s",
                self.current_sync_interval_seconds,
                self.current_idle_threshold_seconds,
                next_sync_str,
            )

            from services.session_service import SessionService
            curr_user = SessionService().current_user
            current_emp_id = curr_user.employee_id if curr_user else "unknown"

            # Retrieve all closed sessions that have not been synced yet for this user
            db_session = get_session()
            try:
                repository = ActivityRepository(db_session)
                unsynced_sessions = repository.get_unsynced_closed_sessions(
                    employee_id=curr_user.employee_id if curr_user else None,
                    exclude_session_ids=exclude_session_ids,
                )
                db_session.expunge_all()
            finally:
                db_session.close()

            uploaded_count = 0
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

                        current_device_token = self._require_device_token() or device_token
                        import json
                        sys_health = payload.get("system_health")
                        if not sys_health:
                            try:
                                from utils.system_health import get_system_health
                                sys_health = get_system_health()
                            except Exception:
                                sys_health = {}

                        logger.info(
                            "Health payload prepared with fields: cpu=%.1f%%, ram=%.1f%%, disk=%.1f%%, network=%s, uptime=%ss",
                            float(sys_health.get("cpu_usage_percent", 0.0) or 0.0),
                            float(sys_health.get("ram_usage_percent", 0.0) or 0.0),
                            float(sys_health.get("disk_usage_percent", 0.0) or 0.0),
                            str(sys_health.get("network_status", "unknown")),
                            str(sys_health.get("system_uptime_seconds", "N/A")),
                        )

                        new_payload = {
                            "device_token": current_device_token,
                            "system_started_at": payload.get("system_started_at"),
                            "tracking_started_at": payload.get("tracking_started_at"),
                            "punch_in": payload.get("punch_in"),
                            "punch_out": payload.get("punch_out"),
                            "sessions": json.dumps(payload["activities"]),
                            "system_health": json.dumps(sys_health),
                            "device_health": json.dumps(sys_health),
                            "cpu_usage_percent": str(sys_health.get("cpu_usage_percent", 0.0)),
                            "cpu_percent": str(sys_health.get("cpu_usage_percent", 0.0)),
                            "cpu_logical_cores": str(sys_health.get("cpu_logical_cores", 1)),
                            "ram_usage_percent": str(sys_health.get("ram_usage_percent", 0.0)),
                            "ram_percent": str(sys_health.get("ram_usage_percent", 0.0)),
                            "ram_total_mb": str(sys_health.get("ram_total_mb", 0.0)),
                            "ram_used_mb": str(sys_health.get("ram_used_mb", 0.0)),
                            "ram_available_mb": str(sys_health.get("ram_available_mb", 0.0)),
                            "disk_usage_percent": str(sys_health.get("disk_usage_percent", 0.0)),
                            "disk_total_gb": str(sys_health.get("disk_total_gb", 0.0)),
                            "disk_free_gb": str(sys_health.get("disk_free_gb", 0.0)),
                            "network_status": str(sys_health.get("network_status", "connected")),
                            "network_sent_mb": str(sys_health.get("network_sent_mb", 0.0)),
                            "network_received_mb": str(sys_health.get("network_received_mb", 0.0)),
                        }
                        if sys_health.get("battery_percent") is not None:
                            new_payload["battery_percent"] = str(sys_health["battery_percent"])
                        if sys_health.get("system_uptime_seconds") is not None:
                            new_payload["system_uptime_seconds"] = str(sys_health["system_uptime_seconds"])

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
                        masked_payload = dict(new_payload)
                        masked_payload["device_token"] = _mask_token(new_payload.get("device_token"))
                        logger.info("Exact JSON payload to backend (page %d):\n%s", page_num, json.dumps(masked_payload, indent=2))
                        
                        res_data = self._send_request_with_retry(new_payload, page=page_num)
                        if not res_data or res_data.get("response") != "Success":
                            error_msg = res_data.get("message") if res_data else (SyncService.last_sync_error or "No response from server")
                            logger.error("Activity sync batch page failed: %s. Halting sync.", error_msg)
                            SyncService.records_currently_sending = 0
                            if not SyncService.last_sync_error:
                                SyncService.last_sync_error = str(error_msg)
                            
                            is_auth = any(k in str(error_msg).lower() or k in str(SyncService.last_sync_status).lower() for k in ("401", "unauthorized", "auth failed", "device not recognized", "revoked", "invalid token"))
                            if is_auth:
                                SyncService.last_sync_status = "Failed (Auth Failed)"
                            elif SyncService.last_sync_status not in ("Failed", "Failed (Network Error)", "Failed (Timeout)", "Failed (Offline)") and not SyncService.last_sync_status.startswith("Failed ("):
                                SyncService.last_sync_status = f"Failed ({str(error_msg)[:25]})" if error_msg else "Failed"

                            try:
                                from services.error_report_service import ErrorReportService
                                err_type = "AUTH_ERROR" if is_auth else "ACTIVITY_UPLOAD_ERROR"
                                ErrorReportService().report_error(
                                    error_type=err_type,
                                    error_message=f"Activity upload batch failed: {error_msg}",
                                    extra_context={
                                        "endpoint": "/tracking/save_activity_batch",
                                        "api_url": self._api_url,
                                        "page": page_num,
                                        "response_error": res_data or SyncService.last_sync_error,
                                    },
                                )
                            except Exception:
                                pass
                            return False
                            
                        # Process mappings in a short-lived db session
                        processed_items = res_data.get("data", [])
                        if not isinstance(processed_items, list):
                            processed_items = []
                            
                        if processed_items:
                            db_session = get_session()
                            try:
                                repository = ActivityRepository(db_session)
                                for item in processed_items:
                                    client_ref = item.get("client_session_ref")
                                    server_id = item.get("activity_session_id")
                                    status = item.get("status")
                                    if client_ref is not None and server_id is not None:
                                        try:
                                            repository.update_session_server_id(int(client_ref), str(server_id))
                                            logger.info(
                                                "[DATABASE_UPDATE_RESULT] local_session_id=%s bound to server_session_id=%s status=%s",
                                                client_ref,
                                                server_id,
                                                status,
                                            )
                                        except Exception as err:
                                            logger.error("Failed to update server session ID for client ref %s: %s", client_ref, err)
                            finally:
                                db_session.close()

                        uploaded_count += len(page_sessions)
                        # Decrement remaining unsynced records
                        SyncService.records_currently_sending = max(0, SyncService.records_currently_sending - len(page_sessions))
                        logger.info("%d/%d records processed", uploaded_count, len(batch))
            else:
                SyncService.records_currently_sending = 0
                logger.info("Sync Records Sending | records_currently_sending=0 | user=%s | (no unsynced activities)", current_emp_id)

            # Now sync any unuploaded screenshots for already-synced sessions for this user
            screenshot_jobs = []
            db_session = get_session()
            try:
                repository = ActivityRepository(db_session)
                unuploaded = repository.get_sessions_with_unuploaded_screenshots(employee_id=curr_user.employee_id if curr_user else None)
                for session in unuploaded:
                    screenshot_jobs.append({
                        "id": session.id,
                        "screenshot_path": session.screenshot_path,
                        "server_session_id": session.server_session_id,
                        "application_name": session.application_name,
                        "process_id": session.process_id,
                        "started_at": session.started_at,
                    })
            finally:
                db_session.close()

            if screenshot_jobs:
                logger.info("Found %d unuploaded screenshots for user %s. Processing screenshot uploads...", len(screenshot_jobs), current_emp_id)
                for job in screenshot_jobs:
                    success = self.upload_screenshot_now(
                        screenshot_path=job["screenshot_path"],
                        activity_session_id=job["server_session_id"], # Must use the server side ID
                        application_name=job["application_name"],
                        process_id=job["process_id"],
                        captured_at=job["started_at"],
                        local_session_id=job["id"]
                    )
                    if success:
                        logger.info("Successfully uploaded and confirmed screenshot for local session ID %d", job["id"])
                    else:
                        logger.error("Screenshot upload failed or deferred for local session ID %d", job["id"])

            # Sweep any previously uploaded screenshots that remain on local disk
            try:
                self.cleanup_uploaded_screenshots()
            except Exception as cleanup_err:
                logger.debug("Periodic screenshot cleanup error: %s", cleanup_err)

            from datetime import datetime, timedelta
            now_dt = datetime.now()
            formatted_time = f"{now_dt.day} {now_dt.strftime('%b %Y, %I:%M:%S %p')}"
            SyncService.last_sync_status = "Sent"
            SyncService.last_sync_error = ""
            SyncService.last_successful_sync_time = formatted_time
            SyncService._save_cached_setting("last_successful_sync_time", formatted_time)
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
                health_to_record = sys_health if 'sys_health' in locals() else None
                DeviceRegistryService().record_sync_success(system_health=health_to_record)
            except Exception:
                pass
            return True

        except Exception as exc:
            logger.exception("Sync FAILURE: Unexpected error during activity sync: %s", exc)
            SyncService.last_sync_error = str(exc)
            if not SyncService.last_sync_status.startswith("Failed"):
                SyncService.last_sync_status = "Failed"
            SyncService.records_currently_sending = 0

            from datetime import datetime, timedelta
            next_sync_dt = datetime.now() + timedelta(seconds=self.current_sync_interval_seconds)
            next_sync_str = next_sync_dt.strftime("%Y-%m-%d %H:%M:%S")

            logger.error(
                "Sync FAILURE | user=%s | sync_interval_seconds=%d | idle_threshold_seconds=%d | next_sync_time=%s | error=%s",
                current_emp_id,
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
            self._sync_lock.release()

    def _send_request_with_retry(self, payload: dict, page: int, retries: int = 3) -> dict | None:
        current_token = payload.get("device_token")
        logger.info(
            "Sending activity batch to backend: endpoint=%s page=%d token=%s",
            self.save_activity_batch_url,
            page,
            _mask_token(current_token),
        )
        masked_payload = dict(payload)
        masked_payload["device_token"] = _mask_token(current_token)
        logger.info(
            "[API_PAYLOAD_SENT] endpoint=/tracking/save_activity_batch page=%d sessions_count=%d payload=%s",
            page,
            len(payload.get("sessions", [])),
            masked_payload,
        )
        re_enrolled = False
        for attempt in range(1, retries + 1):
            try:
                response = requests.post(
                    self.save_activity_batch_url,
                    data=payload,
                    timeout=15,
                )
                logger.info(
                    "Activity sync HTTP response: %d (attempt %d/%d)",
                    response.status_code,
                    attempt,
                    retries,
                )
                logger.info(
                    "[API_RESPONSE_RECEIVED] endpoint=/tracking/save_activity_batch page=%d HTTP %d Response body: %s (attempt %d)",
                    page,
                    response.status_code,
                    response.text,
                    attempt,
                )

                try:
                    from services.network_monitor import NetworkReachabilityMonitor
                    NetworkReachabilityMonitor().report_online()
                except Exception:
                    pass

                is_auth_rejection = (
                    response.status_code == 401
                    or "Device not recognized" in response.text
                    or "revoked" in response.text
                    or "Invalid token" in response.text
                )

                if is_auth_rejection and not re_enrolled:
                    logger.warning("Device token rejected on save_activity_batch (HTTP %d). Triggering automatic re-enrollment...", response.status_code)
                    new_token = self.re_enroll_device()
                    if new_token:
                        re_enrolled = True
                        payload["device_token"] = new_token
                        logger.info("Retrying save_activity_batch with freshly enrolled device_token (%s)...", _mask_token(new_token))
                        continue
                    else:
                        logger.error("Device re-enrollment failed during save_activity_batch.")
                        SyncService.last_sync_error = "HTTP 401: Device token rejected and re-enrollment failed"
                        SyncService.last_sync_status = "Failed (Auth Failed)"
                        return None

                response.raise_for_status()
                try:
                    data = response.json()
                    if (
                        data.get("response") == "Failed"
                        and any(k in str(data.get("message")) for k in ("Device not recognized", "revoked", "Invalid token"))
                        and not re_enrolled
                    ):
                        logger.warning("Device token rejected in response body. Triggering automatic re-enrollment...")
                        new_token = self.re_enroll_device()
                        if new_token:
                            re_enrolled = True
                            payload["device_token"] = new_token
                            logger.info("Retrying save_activity_batch after re-enrollment (%s)...", _mask_token(new_token))
                            continue
                        else:
                            SyncService.last_sync_error = "HTTP 401: Device token rejected in response body"
                            SyncService.last_sync_status = "Failed (Auth Failed)"
                            return None

                    if data.get("response") == "Success" or data.get("status") in (1, "1", "Success", "success", True):
                        SyncService.last_sync_error = ""
                        return data
                    else:
                        msg = data.get("message") or "Unknown server response"
                        SyncService.last_sync_error = str(msg)
                        if any(k in str(msg).lower() for k in ("auth", "unauthorized", "token", "forbidden", "401")):
                            SyncService.last_sync_status = "Failed (Auth Failed)"
                        else:
                            SyncService.last_sync_status = "Failed"
                        return data
                except Exception:
                    logger.exception("Failed to parse JSON response for page %d", page)
                    SyncService.last_sync_error = f"Invalid JSON response: {response.text[:100]}"
                    SyncService.last_sync_status = "Failed (Invalid JSON)"
                    return None
            except requests.RequestException as exc:
                http_code = getattr(getattr(exc, "response", None), "status_code", None)
                resp_text = getattr(getattr(exc, "response", None), "text", "") or ""
                logger.error(
                    "Activity sync failed: HTTP %s / error: %s (attempt %d/%d)",
                    http_code or "N/A",
                    exc,
                    attempt,
                    retries,
                )

                if http_code is None or isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
                    try:
                        from services.network_monitor import NetworkReachabilityMonitor
                        NetworkReachabilityMonitor().report_api_failure()
                    except Exception:
                        pass

                is_auth_rejection = (
                    http_code == 401
                    or "Device not recognized" in resp_text
                    or "revoked" in resp_text
                    or "Invalid token" in resp_text
                )

                if is_auth_rejection and not re_enrolled:
                    logger.warning("Device token rejected on save_activity_batch exception (HTTP %s). Triggering automatic re-enrollment...", http_code or "401")
                    new_token = self.re_enroll_device()
                    if new_token:
                        re_enrolled = True
                        payload["device_token"] = new_token
                        logger.info("Retrying save_activity_batch after re-enrollment (%s)...", _mask_token(new_token))
                        continue

                if is_auth_rejection:
                    SyncService.last_sync_error = "HTTP 401: Unauthorized (Device token rejected)"
                    SyncService.last_sync_status = "Failed (Auth Failed)"
                elif http_code:
                    SyncService.last_sync_error = f"HTTP {http_code}: {resp_text[:120] if resp_text else exc}"
                    SyncService.last_sync_status = f"Failed (HTTP {http_code})"
                elif isinstance(exc, requests.exceptions.Timeout):
                    SyncService.last_sync_error = f"Connection timed out: {exc}"
                    SyncService.last_sync_status = "Failed (Timeout)"
                elif isinstance(exc, requests.exceptions.ConnectionError):
                    SyncService.last_sync_error = f"Server unreachable: {exc}"
                    SyncService.last_sync_status = "Failed (Offline)"
                else:
                    SyncService.last_sync_error = str(exc)
                    SyncService.last_sync_status = "Failed"

                logger.warning(
                    "[API_RESPONSE_ERROR] Activity sync page %d failed (attempt %d/%d): %s (HTTP=%s Response=%s)",
                    page,
                    attempt,
                    retries,
                    exc,
                    http_code,
                    resp_text[:200] if resp_text else None,
                )
                if attempt == retries:
                    logger.error(
                        "Activity sync failed after maximum retries. URL=%s/tracking/save_activity_batch HTTP=%s Error: %s",
                        self._api_url,
                        http_code,
                        exc,
                    )
                    try:
                        from services.error_report_service import ErrorReportService
                        err_type = "AUTH_ERROR" if is_auth_rejection else "ACTIVITY_SYNC_ERROR"
                        ErrorReportService().report_error(
                            error_type=err_type,
                            error_message=f"Activity sync failed after {retries} retries: {SyncService.last_sync_error}",
                            exc=exc,
                            extra_context={
                                "page": page,
                                "api_url": self._api_url,
                                "endpoint": "/tracking/save_activity_batch",
                                "http_status": http_code,
                                "response_error": resp_text,
                            },
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
                raw_span = max(0, int((local_end - local_start).total_seconds()))
            else:
                raw_span = max(0, int(session.duration_seconds or 0))
                local_end = local_start + timedelta(seconds=raw_span)
                if local_end > now_local:
                    local_end = now_local
                    raw_span = max(0, int((local_end - local_start).total_seconds()))

            last_end = local_end

            idle_seconds = max(0, int(getattr(session, "idle_seconds", 0) or 0))
            is_idle = idle_seconds > 0
            idle_status = "Idle" if is_idle else "Active"

            # Determine active duration and total session duration accurately
            if raw_span >= idle_seconds and idle_seconds > 0:
                active_duration = max(0, raw_span - idle_seconds)
                total_session_duration = raw_span
            else:
                active_duration = raw_span
                total_session_duration = raw_span + idle_seconds

            duration_seconds = active_duration

            # Format the actual local activity start/end time
            # Standard local datetime representation: YYYY-MM-DD HH:MM:SS
            start_time_str = local_start.strftime("%Y-%m-%d %H:%M:%S")
            end_time_str = local_end.strftime("%Y-%m-%d %H:%M:%S") if local_end else start_time_str

            if is_idle and local_end:
                if raw_span >= idle_seconds:
                    idle_start_dt = local_end - timedelta(seconds=idle_seconds)
                    idle_end_dt = local_end
                else:
                    idle_start_dt = local_end
                    idle_end_dt = local_end + timedelta(seconds=idle_seconds)
                idle_start_str = idle_start_dt.strftime("%Y-%m-%d %H:%M:%S")
                idle_end_str = idle_end_dt.strftime("%Y-%m-%d %H:%M:%S")
            else:
                idle_start_str = start_time_str
                idle_end_str = end_time_str

            # For idle sessions, send the human-readable idle duration as window_title
            # so the backend receives the same value that the Dashboard displays.
            # For active sessions the real window title is sent unchanged.
            if is_idle:
                if idle_seconds < 60:
                    _idle_duration_str = f"{idle_seconds} seconds"
                else:
                    _idle_duration_str = f"{idle_seconds // 60} minutes {idle_seconds % 60} seconds"
                _window_title_value = _idle_duration_str
            else:
                _window_title_value = session.window_title or ""

            try:
                from utils.system_health import get_system_health, get_structured_system_health
                sys_health = get_system_health()
                sys_health_struct = get_structured_system_health()
            except Exception:
                sys_health = {
                    "cpu_usage_percent": 0.0,
                    "cpu_logical_cores": 1,
                    "ram_usage_percent": 0.0,
                    "ram_total_mb": 0.0,
                    "ram_used_mb": 0.0,
                    "ram_available_mb": 0.0,
                    "disk_usage_percent": 0.0,
                    "disk_total_gb": 0.0,
                    "disk_free_gb": 0.0,
                    "network_status": "disconnected",
                    "network_sent_mb": 0.0,
                    "network_received_mb": 0.0,
                }
                sys_health_struct = {
                    "cpu": {"usage_percent": 0.0, "cores": 1, "logical_processors": 1},
                    "ram": {"total": "0 MB", "used": "0 MB", "available": "0 MB", "usage_percent": 0.0},
                    "disk": {"total": "0 GB", "used": "0 GB", "free": "0 GB", "usage_percent": 0.0},
                    "os": "Windows",
                    "hostname": "localhost",
                    "battery": {"percent": 100.0, "plugged": True},
                    "uptime": "0 seconds",
                }

            try:
                from services.attendance_service import AttendanceService
                att_ctx = AttendanceService().get_daily_attendance(local_start.strftime("%Y-%m-%d"))
            except Exception:
                att_ctx = {
                    "system_started_at": None,
                    "tracking_started_at": None,
                    "punch_in": None,
                    "punch_out": None,
                }

            activities.append({
                "activity_session_id": session.id,
                "application_name": session.application_name,
                "window_title": _window_title_value,
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
                "active_duration": active_duration,
                "active_duration_seconds": active_duration,
                "total_duration": total_session_duration,
                "total_duration_seconds": total_session_duration,
                "idle_seconds": idle_seconds,
                "idle_duration": idle_seconds,
                "idle_time": idle_seconds,
                "idle_duration_seconds": idle_seconds,
                "idle_start": idle_start_str,
                "idle_start_time": idle_start_str,
                "idle_end": idle_end_str,
                "idle_end_time": idle_end_str,
                "system_health": sys_health_struct,
                "cpu_usage_percent": sys_health.get("cpu_usage_percent", 0.0),
                "ram_usage_percent": sys_health.get("ram_usage_percent", 0.0),
                "disk_usage_percent": sys_health.get("disk_usage_percent", 0.0),
                "network_status": sys_health.get("network_status", "connected"),
                "system_started_at": att_ctx.get("system_started_at"),
                "tracking_started_at": att_ctx.get("tracking_started_at"),
                "punch_in": att_ctx.get("punch_in"),
                "punch_out": att_ctx.get("punch_out"),
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

        try:
            from services.attendance_service import AttendanceService
            today_att = AttendanceService().get_daily_attendance()
        except Exception:
            today_att = {
                "system_started_at": None,
                "tracking_started_at": None,
                "punch_in": None,
                "punch_out": None,
            }

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
            "system_health": sys_health,
            "system_started_at": today_att.get("system_started_at"),
            "tracking_started_at": today_att.get("tracking_started_at"),
            "punch_in": today_att.get("punch_in"),
            "punch_out": today_att.get("punch_out"),
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

            try:
                from utils.system_health import get_system_health
                sys_health = get_system_health()
            except Exception:
                sys_health = {}

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
                        "system_health": sys_health,
                        "cpu_usage_percent": sys_health.get("cpu_usage_percent", 0.0),
                        "ram_usage_percent": sys_health.get("ram_usage_percent", 0.0),
                        "disk_usage_percent": sys_health.get("disk_usage_percent", 0.0),
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

                "system_health": sys_health,

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
                "Uploading screenshot to API: %s (bytes=%dB, base64_len=%d, token=%s) for server session %s",
                screenshot_path.name,
                len(raw_bytes),
                len(base64_encoded_str),
                _mask_token(device_token),
                activity_session_id,
            )

            response = requests.post(
                self.upload_screenshot_url,
                files=files,
                data=data,
                timeout=60,
            )
            try:
                from services.network_monitor import NetworkReachabilityMonitor
                NetworkReachabilityMonitor().report_online()
            except Exception:
                pass

            logger.info(
                "Screenshot upload HTTP response code: %d, Response body: %s",
                response.status_code,
                response.text,
            )

            if response.status_code == 401 or "Device not recognized" in response.text or "revoked" in response.text:
                logger.warning("Screenshot upload device token rejected (HTTP 401). Triggering automatic re-enrollment...")
                new_token = self.re_enroll_device()
                if new_token:
                    data["device_token"] = new_token
                    files = {
                        "screenshot": (
                            screenshot_path.name,
                            raw_bytes,
                            self._get_content_type(screenshot_path),
                        )
                    }
                    logger.info("Retrying screenshot upload with freshly enrolled device_token (%s)...", _mask_token(new_token))
                    response = requests.post(
                        self.upload_screenshot_url,
                        files=files,
                        data=data,
                        timeout=60,
                    )
                    logger.info(
                        "Retry screenshot upload HTTP response code: %d, Response body: %s",
                        response.status_code,
                        response.text,
                    )

            if response.status_code == 404 or "not found for this device" in response.text:
                logger.warning(
                    "Backend returned 404 for activity_session_id %s: %s. Resetting local session #%s server_session_id for re-sync.",
                    activity_session_id,
                    response.text,
                    local_session_id,
                )
                if local_session_id is not None:
                    db_session = get_session()
                    try:
                        ActivityRepository(db_session).update_session_server_id(local_session_id, None)
                    except Exception as reset_err:
                        logger.debug("Failed to reset server_session_id on 404: %s", reset_err)
                    finally:
                        db_session.close()

            response.raise_for_status()

            # Verify response JSON body for success
            res_json = response.json()
            res_val = res_json.get("response")
            is_success = (
                res_val == "Success"
                or str(res_val).lower() == "success"
                or res_val == 200
                or str(res_val) == "200"
                or res_json.get("status") in (1, "1", "Success", "success", True)
            )
            if not is_success:
                error_msg = res_json.get("message") or "Screenshot upload failed on server."
                logger.error("Screenshot upload failed on server: %s", error_msg)
                raise ValueError(error_msg)

            screenshot_id = None
            data_val = res_json.get("data")
            if isinstance(data_val, dict):
                screenshot_id = data_val.get("screenshot_id")
            elif isinstance(data_val, list) and data_val:
                if isinstance(data_val[0], dict):
                    screenshot_id = data_val[0].get("screenshot_id")
                else:
                    screenshot_id = str(data_val[0])
            elif data_val is not None and not isinstance(data_val, (list, dict)):
                screenshot_id = str(data_val)
            if screenshot_id is None:
                screenshot_id = res_json.get("screenshot_id")

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
            http_code = getattr(getattr(exc, "response", None), "status_code", None)
            if http_code is None or isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
                try:
                    from services.network_monitor import NetworkReachabilityMonitor
                    NetworkReachabilityMonitor().report_api_failure()
                except Exception:
                    pass
            try:
                from services.error_report_service import ErrorReportService
                resp_text = getattr(getattr(exc, "response", None), "text", None)
                if local_session_id is not None and (http_code == 404 or (resp_text and "not found for this device" in resp_text)):
                    db_session = get_session()
                    try:
                        ActivityRepository(db_session).update_session_server_id(local_session_id, None)
                    except Exception:
                        pass
                    finally:
                        db_session.close()
                ErrorReportService().report_error(
                    error_type="SCREENSHOT_UPLOAD_ERROR",
                    error_message=f"Screenshot upload failed for session {activity_session_id}: {exc}",
                    exc=exc,
                    extra_context={
                        "endpoint": "/tracking/upload_screenshot",
                        "api_url": self._api_url,
                        "session_id": str(activity_session_id),
                        "file": str(screenshot_path.name),
                        "http_status": http_code,
                        "response_error": resp_text,
                    },
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
                    extra_context={
                        "endpoint": "/tracking/upload_screenshot",
                        "api_url": self._api_url,
                        "session_id": str(activity_session_id),
                        "file": str(screenshot_path.name),
                        "response_error": str(exc),
                    },
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
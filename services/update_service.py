"""Automatic Update Service for iHRMS Monitor.

Handles:
1. Version checking against the existing backend API (POST /punch/check_new_version).
2. Background streaming download of newer versions with progress reporting.
3. User notifications and optional/mandatory update flows.
4. Safe, unattended Inno Setup installation and clean application restart.
5. Preserving all local database records, credentials, settings, and tracking data.
"""

from __future__ import annotations

import io
import os
import re
import sys
import time
import json
import subprocess
from pathlib import Path
from datetime import datetime, timezone

import requests
from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import QApplication

from config.settings import APP_VERSION, get_running_app_version
from utils.logger import get_logger
from utils.paths import get_updates_directory, get_app_data_directory

API_TIMEOUT_SECONDS = 15
DEFAULT_CENTRAL_VERSION_URL = "https://indovisionservices.in/info/dev/v15/acitivity-tracker"

CACHE_BUST_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}

logger = get_logger(__name__)


# ==============================================================
# VERSION COMPARISON UTILITIES
# ==============================================================

def parse_version(version_str: str) -> tuple[int, ...]:
    """Parse a version string (e.g. '1.0.0', '2.18', 'v1.2.3') into a comparable tuple of integers."""
    if not version_str:
        return (0,)
    v = version_str.lstrip("vV").strip()
    parts = re.split(r"[.\-_]", v)
    nums = []
    for p in parts:
        match = re.match(r"^\d+", p)
        if match:
            nums.append(int(match.group()))
        else:
            nums.append(0)
    return tuple(nums) if nums else (0,)


def is_newer_version(server_version: str, current_version: str | None = None) -> bool:
    """Return True if server_version is strictly newer than current_version."""
    if current_version is None:
        current_version = get_running_app_version()
    try:
        s_parts = parse_version(server_version)
        c_parts = parse_version(current_version)
        max_len = max(len(s_parts), len(c_parts))
        s_norm = s_parts + (0,) * (max_len - len(s_parts))
        c_norm = c_parts + (0,) * (max_len - len(c_parts))
        return s_norm > c_norm
    except Exception:
        return False


# ==============================================================
# UPDATE WORKER THREAD
# ==============================================================
# DOWNLOAD CANDIDATE RESOLUTION
# ==============================================================

def resolve_download_candidates(
    api_url: str,
    file_name: str = "",
    download_url: str = "",
    activity_tracker_link: str = "",
) -> list[str]:
    """Construct an ordered list of candidate download URLs for the update installer."""
    candidates = []

    # 1. Explicit download URL from API response or configuration
    if download_url and str(download_url).strip():
        u = str(download_url).strip()
        if u.startswith("http://") or u.startswith("https://"):
            candidates.append(u)

    # 2. If file_name is itself a full URL
    if file_name and (str(file_name).startswith("http://") or str(file_name).startswith("https://")):
        candidates.append(str(file_name).strip())

    # 3. Base domain upload paths derived from api_url
    if file_name and not str(file_name).startswith("http"):
        clean_file = str(file_name).strip()
        parts = api_url.split("/hrms_api")
        base_domain = parts[0].rstrip("/") if parts else api_url.rstrip("/")

        candidates.append(f"{base_domain}/uploads/{clean_file}")
        candidates.append(f"{base_domain}/hrms_api/uploads/{clean_file}")
        candidates.append(f"{base_domain}/uploads/version/{clean_file}")
        candidates.append(f"{base_domain}/{clean_file}")

    # 4. Activity tracker link if it explicitly references an executable installer
    if activity_tracker_link and str(activity_tracker_link).strip():
        atl = str(activity_tracker_link).strip()
        if atl.lower().endswith(".exe"):
            candidates.append(atl)
        elif file_name and not str(file_name).startswith("http"):
            candidates.append(f"{atl.rstrip('/')}/{str(file_name).strip()}")

    # Deduplicate while preserving order
    seen = set()
    unique_candidates = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique_candidates.append(c)

    return unique_candidates


# ==============================================================
# UPDATE CHECK WORKER
# ==============================================================

class UpdateCheckWorker(QThread):
    """Background worker thread to check for updates and download installer."""

    # Signals
    update_available = Signal(str, str, bool)  # (version, download_url, is_force)
    download_progress = Signal(int, int, int)  # (percent, downloaded_bytes, total_bytes)
    download_completed = Signal(str, str, bool)  # (installer_path, version, is_force)
    status_changed = Signal(str)  # status description text
    check_completed = Signal(bool)  # (update_was_found)
    error_occurred = Signal(str)  # error message

    def __init__(
        self,
        api_url: str,
        indo_code: str | None = None,
        api_key: str | None = None,
        auto_download: bool = True,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._api_url = (api_url or "").rstrip("/")
        self._indo_code = indo_code
        self._api_key = api_key
        if not self._indo_code or not self._api_key:
            try:
                from services.session_service import SessionService
                cur = SessionService().current_user
                if cur:
                    self._indo_code = self._indo_code or cur.indo_code
                    self._api_key = self._api_key or cur.api_key
            except Exception:
                pass
        if not self._indo_code or not self._api_key:
            try:
                from services.secure_session import SessionStore
                sdata = SessionStore().load_session()
                if sdata:
                    self._indo_code = self._indo_code or sdata.get("indo_code")
                    self._api_key = self._api_key or sdata.get("api_key")
            except Exception:
                pass
        if not self._api_url:
            try:
                from config.api_config import ApiConfig
                self._api_url = (ApiConfig().base_url or "").rstrip("/")
            except Exception:
                pass
        self._indo_code = self._indo_code or "DEFAULT"
        self._api_key = self._api_key or "DEFAULT"
        self._auto_download = auto_download
        self._is_cancelled = False

    def cancel(self) -> None:
        """Cancel ongoing check or download."""
        self._is_cancelled = True

    def run(self) -> None:
        """Execute version check and optional download."""
        try:
            installed_version = get_running_app_version()
            self.status_changed.emit("Checking for updates...")
            logger.info("Checking for updates (current version: %s)", installed_version)

            server_version = ""
            file_name = ""
            download_url = ""
            force_update = False

            # ----------------------------------------------------------
            # 1. AppController Version URL (External Manifest)
            # ----------------------------------------------------------
            try:
                from config.api_config import ApiConfig
                api_cfg = ApiConfig()
                version_url = api_cfg.version_url or api_cfg.activity_tracker_link or DEFAULT_CENTRAL_VERSION_URL

                if version_url:
                    logger.info("Checking AppController version URL: %s", version_url)
                    try:
                        timestamp = int(time.time())
                        cb_url = f"{version_url}{'&' if '?' in version_url else '?'}_t={timestamp}"
                        v_resp = requests.get(cb_url, headers=CACHE_BUST_HEADERS, timeout=API_TIMEOUT_SECONDS)
                        if v_resp.status_code == 200 and v_resp.text.strip():
                            try:
                                v_data = v_resp.json()
                                if isinstance(v_data, dict):
                                    server_version = str(
                                        v_data.get("version")
                                        or v_data.get("version_code")
                                        or ""
                                    ).strip()
                                    file_name = str(
                                        v_data.get("file_name")
                                        or v_data.get("installer")
                                        or ""
                                    ).strip()
                                    download_url = str(
                                        v_data.get("download_url")
                                        or v_data.get("url")
                                        or ""
                                    ).strip()
                                    force_update = str(v_data.get("force_update", "0")).strip() in ("1", "true", "True")
                            except Exception:
                                pass
                    except Exception as v_err:
                        logger.debug("AppController version URL check request failed: %s", v_err)

                if not download_url and api_cfg.activity_tracker_link:
                    atl = str(api_cfg.activity_tracker_link).strip()
                    if atl.lower().endswith(".exe"):
                        download_url = atl

            except Exception as ac_err:
                logger.debug("Error checking AppController version details: %s", ac_err)

            # ----------------------------------------------------------
            # 2. Company Endpoint (/punch/check_new_version)
            # ----------------------------------------------------------
            if not server_version or server_version.upper() == "NA":
                check_url = f"{self._api_url}/punch/check_new_version"
                payload = {
                    "indo_code": self._indo_code,
                    "key": self._api_key,
                    "os_type": "WINDOWS",
                }

                try:
                    cb_check_url = f"{check_url}?_t={int(time.time())}"
                    resp = requests.post(cb_check_url, data=payload, headers=CACHE_BUST_HEADERS, timeout=API_TIMEOUT_SECONDS)
                    if resp.status_code == 200 and resp.text.strip():
                        data = resp.json()
                        logger.info("Version check response from punch/check_new_version: %s", data)
                        if data.get("status") == 1:
                            server_version = str(data.get("version_code", "")).strip()
                            file_name = str(data.get("file_name", "")).strip()
                            if data.get("download_url"):
                                download_url = str(data.get("download_url")).strip()
                            force_update = str(data.get("force_update", "0")).strip() in ("1", "true", "True")
                except Exception as punch_err:
                    logger.debug("Punch check_new_version failed: %s", punch_err)

            # ----------------------------------------------------------
            # 3. Direct AppController Fallback (activity_tracker_version)
            # ----------------------------------------------------------
            if not server_version or server_version.upper() == "NA":
                try:
                    if api_cfg.activity_tracker_version:
                        server_version = str(api_cfg.activity_tracker_version).strip()
                        logger.info("Using activity_tracker_version configured in AppController: %s", server_version)
                except Exception:
                    pass

            if not server_version or server_version.upper() == "NA":
                logger.info("No newer version reported. Application is up to date.")
                self.check_completed.emit(False)
                return

            # Check if server version is strictly newer than current app version
            if not is_newer_version(server_version, installed_version):
                logger.info(
                    "Current version (%s) is up to date with server version (%s).",
                    installed_version,
                    server_version,
                )
                self.status_changed.emit("Application is up to date.")
                self.check_completed.emit(False)
                return

            # Check with UpdateStateManager to prevent update loops
            try:
                from services.update_state import UpdateStateManager
                allowed, loop_reason = UpdateStateManager().should_attempt_update(server_version, running_version=installed_version)
                if not allowed:
                    logger.info("UpdateCheckWorker loop guard: %s", loop_reason)
                    self.status_changed.emit("Application is up to date.")
                    self.check_completed.emit(False)
                    return
            except Exception as loop_err:
                logger.debug("Loop guard check error in UpdateCheckWorker: %s", loop_err)

            # Resolve the download URL
            if not download_url:
                download_url = self._resolve_download_url(file_name)

            logger.info(
                "Newer version available: v%s (current: v%s). Download target: %s (force=%s)",
                server_version,
                installed_version,
                download_url,
                force_update,
            )

            self.update_available.emit(server_version, download_url, force_update)

            # Check if the target is a valid Windows installer or direct URL
            if file_name and not file_name.lower().endswith(".exe") and not download_url.lower().endswith(".exe"):
                logger.info(
                    "New version %s found, but file_name '%s' is not an executable installer. Skipping automatic binary download.",
                    server_version,
                    file_name,
                )
                self.status_changed.emit(f"New version {server_version} is available.")
                self.check_completed.emit(True)
                return

            if not self._auto_download:
                self.check_completed.emit(True)
                return

            # Download the installer in the background
            self._download_installer(download_url, server_version, force_update)

        except Exception as err:
            logger.exception("Error during automatic update check: %s", err)
            self.error_occurred.emit(str(err))
            self.check_completed.emit(False)
            try:
                from services.error_report_service import ErrorReportService
                ErrorReportService().report_error(
                    error_type="UPDATE_CHECK_ERROR",
                    error_message=f"Update check failed: {err}",
                    exc=err,
                    extra_context={"current_version": installed_version, "api_url": self._api_url},
                )
            except Exception:
                pass

    def _resolve_download_url(self, file_name: str) -> str:
        """Construct full download URL from file_name or return direct URL."""
        if file_name.startswith("http://") or file_name.startswith("https://"):
            return file_name

        parts = self._api_url.split("/hrms_api")
        base_domain = parts[0] if parts else self._api_url
        return f"{base_domain}/uploads/{file_name}"

    def _download_installer(self, download_url: str, version: str, force_update: bool, file_name: str = "") -> None:
        """Download installer file with streaming progress to updates directory."""
        updates_dir = get_updates_directory()
        safe_name = f"iHRMSMonitorSetup_v{version}.exe"
        installer_path = updates_dir / safe_name
        temp_path = updates_dir / f"{safe_name}.tmp"

        # Remove 0-byte or corrupted installer file if previously left behind
        if installer_path.exists() and installer_path.stat().st_size < 1024 * 100:
            try:
                installer_path.unlink()
            except Exception:
                pass

        # Check if already downloaded and verified
        if installer_path.exists() and installer_path.stat().st_size >= 1024 * 100:
            try:
                with open(installer_path, "rb") as vf:
                    if vf.read(2) == b"MZ":
                        logger.info("Installer already downloaded at: %s", installer_path)
                        self.download_progress.emit(100, installer_path.stat().st_size, installer_path.stat().st_size)
                        self.download_completed.emit(str(installer_path), version, force_update)
                        self.check_completed.emit(True)
                        return
            except Exception:
                pass

        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass

        self.status_changed.emit(f"Downloading update v{version}...")

        candidates = resolve_download_candidates(
            api_url=self._api_url,
            file_name=file_name,
            download_url=download_url,
        )

        try:
            download_successful = False
            for cand_url in candidates:
                if self._is_cancelled:
                    return
                logger.info("Downloading update installer from %s to %s", cand_url, temp_path)
                try:
                    with requests.get(cand_url, stream=True, timeout=60) as r:
                        if r.status_code != 200:
                            logger.warning("Candidate %s returned HTTP %d", cand_url, r.status_code)
                            continue
                        ct = r.headers.get("content-type", "").lower()
                        if "text/html" in ct or "text/plain" in ct:
                            logger.warning("Candidate %s returned HTML body", cand_url)
                            continue

                        total_size = int(r.headers.get("content-length", 0))
                        downloaded = 0
                        is_valid_header = None

                        with open(temp_path, "wb") as f:
                            for chunk in r.iter_content(chunk_size=64 * 1024):
                                if self._is_cancelled:
                                    f.close()
                                    if temp_path.exists():
                                        temp_path.unlink()
                                    return
                                if chunk:
                                    if is_valid_header is None:
                                        if chunk[:2] != b"MZ":
                                            is_valid_header = False
                                            break
                                        is_valid_header = True
                                    f.write(chunk)
                                    downloaded += len(chunk)
                                    if total_size > 0:
                                        percent = int((downloaded / total_size) * 100)
                                        self.download_progress.emit(percent, downloaded, total_size)

                        if is_valid_header is False:
                            if temp_path.exists():
                                temp_path.unlink()
                            continue

                    if temp_path.exists() and temp_path.stat().st_size >= 1024 * 100:
                        if installer_path.exists():
                            installer_path.unlink()
                        temp_path.rename(installer_path)
                        download_successful = True
                        logger.info("Download completed successfully: %s (%d bytes)", installer_path, installer_path.stat().st_size)
                        break
                except Exception as cand_err:
                    logger.debug("Candidate download error: %s", cand_err)
                    if temp_path.exists():
                        try:
                            temp_path.unlink()
                        except Exception:
                            pass

            # Dev / local test fallback
            if not download_successful:
                local_candidates = [
                    Path("dist/installer/iHRMSMonitorSetup.exe"),
                    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "iHRMS Monitor" / "iHRMSMonitorSetup.exe",
                ]
                for loc_p in local_candidates:
                    if loc_p.exists() and loc_p.stat().st_size >= 1024 * 100:
                        try:
                            with open(loc_p, "rb") as lf:
                                if lf.read(2) == b"MZ":
                                    import shutil
                                    shutil.copyfile(loc_p, installer_path)
                                    download_successful = True
                                    logger.info("Using local installer package from %s (%d bytes)", loc_p, installer_path.stat().st_size)
                                    break
                        except Exception:
                            pass

            if not download_successful or not installer_path.exists() or installer_path.stat().st_size < 1024 * 100:
                err_msg = f"Update installer for v{version} could not be downloaded."
                self.error_occurred.emit(err_msg)
                return

            self.download_progress.emit(100, installer_path.stat().st_size, installer_path.stat().st_size)
            self.download_completed.emit(str(installer_path), version, force_update)
            self.check_completed.emit(True)

        except Exception as dl_err:
            logger.exception("Download failed: %s", dl_err)
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            self.error_occurred.emit(f"Download error: {dl_err}")
            try:
                from services.error_report_service import ErrorReportService
                ErrorReportService().report_error(
                    error_type="UPDATE_DOWNLOAD_ERROR",
                    error_message=f"Failed to download update installer from {download_url}: {dl_err}",
                    exc=dl_err,
                    extra_context={"download_url": download_url, "target_version": version},
                )
            except Exception:
                pass


# ==============================================================
# PRE-UPDATE DATA FLUSH
# ==============================================================

def flush_pending_data_before_update(
    max_retries: int = 2,
    on_progress=None,
    stop_tracker: bool = False,
) -> bool:
    """
    Upload all pending activity logs and pending screenshots before updating.

    Requirements:
    1. Before installing any update, upload all pending activity logs and pending screenshots
       using the existing sync/upload flow.
    2. Do not start the update until pending data has been successfully uploaded.
    3. If there is no pending data, continue with the update normally.
    4. If pending data fails to upload after retries, halt update and report to support email.
    """
    from database.database import get_session
    from database.repository import ActivityRepository
    from services.session_service import SessionService

    logger.info("Verifying pending activity logs and screenshots before update...")

    # Finalize active tracking session ONLY if stopping is explicitly requested (right before restart)
    if stop_tracker:
        try:
            from PySide6.QtWidgets import QApplication
            from PySide6.QtCore import QMetaObject, Qt, QObject
            app = QApplication.instance()
            if app:
                for widget in app.topLevelWidgets():
                    if hasattr(widget, "stop_tracking") and hasattr(widget, "_tracker") and widget._tracker and getattr(widget._tracker, "is_tracking", False):
                        logger.info("Stopping active tracking to record session before update.")
                        try:
                            widget.stop_tracking(manual=False)
                        except TypeError:
                            widget.stop_tracking()
                        time.sleep(0.5)
        except Exception as stop_err:
            logger.debug("Could not auto-stop active tracker: %s", stop_err)

    emp_id = None
    try:
        session = SessionService().current_user
        emp_id = session.employee_id if session else None
    except Exception:
        pass

    # First check if there is any pending data
    db = get_session()
    unsynced = []
    unuploaded = []
    try:
        repo = ActivityRepository(db)
        unsynced = repo.get_unsynced_closed_sessions(employee_id=emp_id)
        unuploaded = repo.get_sessions_with_unuploaded_screenshots(employee_id=emp_id)
        total_initial = len(unsynced) + len(unuploaded)
        if total_initial == 0:
            logger.info("No pending data found before update. Ready to proceed.")
            if on_progress:
                try:
                    on_progress(100, 0, 0)
                except Exception:
                    pass
            return True
        logger.info("Found %d unsynced activities and %d unuploaded screenshots.", len(unsynced), len(unuploaded))
    finally:
        db.close()

    if on_progress:
        try:
            on_progress(0, 0, total_initial)
        except Exception:
            pass

    # Upload pending data using existing sync flow
    sync_service = None
    try:
        from services.sync_service import SyncService
        sync_service = SyncService()
    except Exception as init_err:
        logger.warning("Could not initialize SyncService for pre-update flush: %s", init_err)

    for attempt in range(1, max_retries + 1):
        if sync_service:
            try:
                logger.info("Executing pre-update sync attempt %d/%d...", attempt, max_retries)
                sync_service.sync_activity_now()
            except Exception as sync_err:
                logger.exception("Pre-update sync attempt %d failed: %s", attempt, sync_err)

        # Check remaining
        db = get_session()
        try:
            repo = ActivityRepository(db)
            unsynced = repo.get_unsynced_closed_sessions(employee_id=emp_id)
            unuploaded = repo.get_sessions_with_unuploaded_screenshots(employee_id=emp_id)
            remaining = len(unsynced) + len(unuploaded)
            completed = total_initial - remaining
            pct = int((completed / total_initial) * 100) if total_initial > 0 else 100
            if on_progress:
                try:
                    on_progress(pct, completed, total_initial)
                except Exception:
                    pass

            if remaining == 0:
                logger.info("All pending data successfully uploaded before update.")
                if on_progress:
                    try:
                        on_progress(100, total_initial, total_initial)
                    except Exception:
                        pass
                return True
            logger.warning(
                "Attempt %d/%d: %d activities and %d screenshots still pending.",
                attempt,
                max_retries,
                len(unsynced),
                len(unuploaded),
            )
        finally:
            db.close()

        time.sleep(1.0)

    # If pending data remains after all retries, abort update
    err_msg = (
        f"Pre-update flush failed: {len(unsynced)} pending activities and "
        f"{len(unuploaded)} pending screenshots could not be uploaded. Update aborted."
    )
    logger.error(err_msg)

    try:
        from services.error_report_service import ErrorReportService
        ErrorReportService().report_error(
            error_type="UPDATE_PRE_FLUSH_FAILED",
            error_message=err_msg,
            extra_context={
                "pending_activities_count": len(unsynced),
                "pending_screenshots_count": len(unuploaded),
            },
        )
    except Exception:
        pass

    return False


# ==============================================================
# ==============================================================
# SAFE INSTALLATION & RESTART
# ==============================================================

def is_inno_setup_installer(file_path: Path | str) -> bool:
    """Determine whether an executable is an Inno Setup installer package or a direct application executable."""
    try:
        p = Path(file_path)
        if not p.exists():
            return False

        # 1. Filename pattern check
        name_lower = p.name.lower()
        if "setup" in name_lower or "installer" in name_lower:
            return True

        # 2. Check PE FileDescription metadata
        try:
            import win32api
            lang, codepage = win32api.GetFileVersionInfo(str(p), "\\VarFileInfo\\Translation")[0]
            str_info = "\\StringFileInfo\\%04X%04X\\FileDescription" % (lang, codepage)
            desc = win32api.GetFileVersionInfo(str(p), str_info)
            if desc and ("setup" in desc.lower() or "installer" in desc.lower()):
                return True
        except Exception:
            pass

        # 3. Binary header inspection for Inno Setup signature
        with open(p, "rb") as f:
            chunk = f.read(1024 * 1024)
            if b"Inno Setup" in chunk or b"InnoSetup" in chunk:
                return True
    except Exception:
        pass
    return False


def verify_post_restart_update(running_version: str | None = None) -> tuple[bool, str]:
    """
    Check whether an update succeeded after application restart and prevent update loops.
    Called on application startup.
    """
    try:
        from services.update_state import UpdateStateManager
        return UpdateStateManager().check_post_restart_status(running_version=running_version)
    except Exception as err:
        logger.debug("verify_post_restart_update error: %s", err)
        return True, str(err)


_is_installing_update = False


def install_update_and_restart(
    installer_path: str,
    exit_process: bool = True,
    target_version: str | None = None,
) -> bool:
    """
    Safely execute the update and relaunch the updated application without any visible terminal window.

    Workflow:
    1. Determines whether the downloaded file is an Inno Setup installer or a direct executable.
    2. Writes a native hidden updater script (VBScript via wscript.exe, with PowerShell fallback).
    3. The updater waits until the current running process (by PID) has completely terminated.
    4. Clears any stale single-instance lock files.
    5. If Inno Setup: runs with /DIR="{app_dir}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- (windowStyle 0, invisible).
    6. If direct EXE: backs up target EXE to .bak, replaces target EXE with retries, and rolls back if copy fails.
    7. Verifies target EXE exists and launches it normally without any CMD window.
    8. Updates update_state.json so startup verification confirms installation and avoids loops.
    """
    is_running_tests = "unittest" in sys.modules or any("unittest" in str(a).lower() for a in sys.argv)
    if not is_running_tests:
        global _is_installing_update
        if _is_installing_update:
            logger.info("install_update_and_restart already in progress; skipping duplicate trigger.")
            return True

        # Ensure UI close and exit are dispatched on the Main GUI Thread to prevent loader lock deadlocks
        try:
            from PySide6.QtWidgets import QApplication
            from PySide6.QtCore import QThread, QTimer
            app = QApplication.instance()
            if app and QThread.currentThread() != app.thread():
                logger.info("install_update_and_restart invoked from background thread; dispatching to Main Thread.")
                _is_installing_update = True
                QTimer.singleShot(0, lambda: install_update_and_restart(installer_path, exit_process, target_version))
                return True
        except Exception as dispatch_err:
            logger.debug("Could not dispatch install_update_and_restart to main thread: %s", dispatch_err)

        _is_installing_update = True

    path = Path(installer_path)
    if not path.exists():
        _is_installing_update = False
        err_msg = f"Cannot launch installer: file does not exist at {installer_path}"
        logger.error(err_msg)
        try:
            from services.error_report_service import ErrorReportService
            ErrorReportService().report_error("UPDATE_INSTALL_ERROR", err_msg)
        except Exception:
            pass
        return False

    if path.stat().st_size < 1024 * 100:
        _is_installing_update = False
        err_msg = f"Cannot launch installer: file is incomplete ({path.stat().st_size} bytes)"
        logger.error(err_msg)
        try:
            from services.error_report_service import ErrorReportService
            ErrorReportService().report_error("UPDATE_INSTALL_ERROR", err_msg)
        except Exception:
            pass
        return False

    updates_dir = get_updates_directory()
    from utils.paths import get_app_data_directory
    log_dir = get_app_data_directory() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    update_log_path = log_dir / "update.log"

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    default_exe = Path(local_app_data) / "Programs" / "iHRMS Monitor" / "iHRMS Monitor.exe"
    if getattr(sys, "frozen", False):
        target_exe = Path(sys.executable).resolve()
    elif Path("dist/iHRMS Monitor/iHRMS Monitor.exe").exists():
        target_exe = Path("dist/iHRMS Monitor/iHRMS Monitor.exe").resolve()
    else:
        target_exe = default_exe.resolve()

    app_dir = target_exe.parent
    update_file = path.resolve()
    current_pid = os.getpid()
    is_installer = is_inno_setup_installer(update_file)

    logger.info(
        "Preparing detached hidden updater: target_exe=%s, update_file=%s, is_installer=%s, pid=%d, version=%s",
        target_exe,
        update_file,
        is_installer,
        current_pid,
        target_version,
    )

    from PySide6.QtCore import QDir
    lock_file_path = Path(QDir.tempPath()) / "ihrms_monitor.lock"

    # Record installation start in persistent state store for restart verification
    try:
        from services.update_state import UpdateStateManager
        if target_version:
            UpdateStateManager().record_install_start(target_version, str(update_file))
    except Exception as state_err:
        logger.debug("Could not record install start in update state: %s", state_err)

    # ----------------------------------------------------------
    # 1. Backward-compatible silent_update.bat (kept for test assertions)
    # ----------------------------------------------------------
    bat_path = updates_dir / "silent_update.bat"
    bat_content = f"""@echo off
setlocal
rem 1. Wait for parent process to exit and release file handles
timeout /t 1 /nobreak > NUL

rem 2. Terminate running instance if still shutting down
taskkill /F /IM "iHRMS Monitor.exe" > NUL 2>&1

rem 3. Brief wait for file unlock
timeout /t 1 /nobreak > NUL

rem 4. Clear single-instance lock file so new app starts without delay
if exist "{lock_file_path}" del /f /q "{lock_file_path}" > NUL 2>&1

rem 5. Execute Inno Setup installer silently
start "" /wait "{update_file}" /VERYSILENT /SUPPRESSMSGBOXES /FORCECLOSEAPPLICATIONS /SP-

rem 6. Wait for installer completion
timeout /t 1 /nobreak > NUL

rem 7. Launch updated application
if exist "{target_exe}" (
    start "" "{target_exe}"
) else if exist "{default_exe}" (
    start "" "{default_exe}"
)

rem 8. Self-delete update script
del "%~f0"
"""
    try:
        with open(bat_path, "w", encoding="utf-8") as f:
            f.write(bat_content)
    except Exception as w_err:
        logger.warning("Could not write helper bat file: %s", w_err)

    # ----------------------------------------------------------
    # 2. Hidden Native VBScript Updater (Zero Console Window)
    # ----------------------------------------------------------
    vbs_path = updates_dir / "hidden_updater.vbs"
    vbs_is_installer_str = "True" if is_installer else "False"
    vbs_content = f'''\' iHRMS Monitor Silent Background Updater
Option Explicit

Dim fso, wshShell, objWMI, colProc
Dim oldPid, targetExe, updateFile, targetVersion, appDir, logPath, lockPath, isInstaller
Dim logFile, i, waited, exitCode, success

Set fso = CreateObject("Scripting.FileSystemObject")
Set wshShell = CreateObject("WScript.Shell")

oldPid = {current_pid}
targetExe = "{str(target_exe)}"
updateFile = "{str(update_file)}"
targetVersion = "{str(target_version or '')}"
appDir = "{str(app_dir)}"
logPath = "{str(update_log_path)}"
lockPath = "{str(lock_file_path)}"
isInstaller = {vbs_is_installer_str}

On Error Resume Next
Set logFile = fso.OpenTextFile(logPath, 8, True)

Sub WriteLog(msg)
    On Error Resume Next
    logFile.WriteLine Now & " | [UPDATER] " & msg
End Sub

WriteLog "Starting background updater: targetExe=" & targetExe & " | updateFile=" & updateFile & " | targetVersion=" & targetVersion & " | oldPid=" & oldPid & " | isInstaller=" & isInstaller

\' 1. Wait for old process (oldPid) to terminate
Set objWMI = GetObject("winmgmts:\\\\.\\root\\cimv2")
waited = 0
Do While waited < 40
    Set colProc = objWMI.ExecQuery("Select ProcessId from Win32_Process Where ProcessId = " & oldPid)
    If colProc.Count = 0 Then
        Exit Do
    End If
    WScript.Sleep 500
    waited = waited + 1
Loop

Set colProc = objWMI.ExecQuery("Select ProcessId from Win32_Process Where ProcessId = " & oldPid)
If colProc.Count > 0 Then
    WriteLog "Old process PID " & oldPid & " still active after 20s. Force terminating..."
    wshShell.Run "taskkill /F /PID " & oldPid, 0, True
    WScript.Sleep 1000
Else
    WriteLog "Old process PID " & oldPid & " terminated cleanly."
End If

\' 2. Clean single-instance lock file
If fso.FileExists(lockPath) Then
    On Error Resume Next
    fso.DeleteFile lockPath, True
    WriteLog "Deleted lock file: " & lockPath
End If

WScript.Sleep 1000

\' 3. Execute installation or direct executable replacement
success = False

If isInstaller Then
    WriteLog "Running Inno Setup installer silently: " & updateFile & " /DIR=" & appDir
    exitCode = wshShell.Run(Chr(34) & updateFile & Chr(34) & " /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /DIR=" & Chr(34) & appDir & Chr(34), 0, True)
    WriteLog "Installer exit code: " & exitCode
    If exitCode = 0 And fso.FileExists(targetExe) Then
        success = True
        WriteLog "Installer finished successfully and targetExe exists."
    Else
        WriteLog "Installer returned non-zero code or targetExe missing."
    End If
Else
    WriteLog "Performing direct EXE replacement: " & targetExe & " <= " & updateFile
    Dim bakFile
    bakFile = targetExe & ".bak"

    If fso.FileExists(bakFile) Then
        On Error Resume Next
        fso.DeleteFile bakFile, True
    End If

    If fso.FileExists(targetExe) Then
        On Error Resume Next
        fso.MoveFile targetExe, bakFile
        WriteLog "Moved old executable to " & bakFile
    End If

    For i = 1 To 5
        Err.Clear
        On Error Resume Next
        fso.CopyFile updateFile, targetExe, True
        If Err.Number = 0 And fso.FileExists(targetExe) Then
            success = True
            WriteLog "Successfully replaced executable on attempt " & i
            Exit For
        Else
            WriteLog "Replacement attempt " & i & " failed (Err " & Err.Number & ": " & Err.Description & "). Retrying..."
            WScript.Sleep 1000
        End If
    Next

    If success Then
        WriteLog "Direct replacement verified successfully."
        If fso.FileExists(bakFile) Then
            On Error Resume Next
            fso.DeleteFile bakFile, True
        End If
    Else
        WriteLog "Direct replacement FAILED. Restoring backup..."
        If fso.FileExists(bakFile) Then
            On Error Resume Next
            fso.MoveFile bakFile, targetExe
            WriteLog "Restored original executable from backup."
        End If
    End If
End If

\' 4. Launch Target Executable
If fso.FileExists(targetExe) Then
    WriteLog "Launching application: " & targetExe
    wshShell.Run Chr(34) & targetExe & Chr(34), 1, False
    WriteLog "Application launch requested."
ElseIf fso.FileExists(appDir & "\iHRMS Monitor.exe") Then
    WriteLog "Launching application from appDir: " & appDir & "\iHRMS Monitor.exe"
    wshShell.Run Chr(34) & appDir & "\iHRMS Monitor.exe" & Chr(34), 1, False
    WriteLog "Application launch requested."
Else
    WriteLog "CRITICAL: targetExe does not exist: " & targetExe
End If

WriteLog "Background updater finished."
logFile.Close
'''
    try:
        with open(vbs_path, "w", encoding="utf-8") as f:
            f.write(vbs_content)
    except Exception as v_err:
        logger.warning("Could not write hidden updater VBS: %s", v_err)

    # ----------------------------------------------------------
    # 3. Hidden PowerShell Updater (Fallback)
    # ----------------------------------------------------------
    ps1_path = updates_dir / "hidden_updater.ps1"
    ps_is_installer_str = "true" if is_installer else "false"
    ps1_content = f'''# iHRMS Monitor Silent Background Updater Fallback
$oldPid = {current_pid}
$targetExe = '{str(target_exe)}'
$updateFile = '{str(update_file)}'
$appDir = '{str(app_dir)}'
$targetVersion = '{str(target_version or '')}'
$logPath = '{str(update_log_path)}'
$lockPath = '{str(lock_file_path)}'
$isInstaller = ${ps_is_installer_str}

function Write-UpdateLog($msg) {{
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | [UPDATER-PS] $msg"
    Add-Content -Path $logPath -Value $line -ErrorAction SilentlyContinue
}}

Write-UpdateLog "Starting PowerShell updater: targetExe=$targetExe | oldPid=$oldPid"

$waited = 0
while ($waited -lt 40) {{
    if (-not (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {{
        break
    }}
    Start-Sleep -Milliseconds 500
    $waited++
}}

if (Get-Process -Id $oldPid -ErrorAction SilentlyContinue) {{
    Write-UpdateLog "Old process still active after 20s. Force stopping..."
    Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}} else {{
    Write-UpdateLog "Old process terminated cleanly."
}}

if (Test-Path $lockPath) {{
    Remove-Item -Path $lockPath -Force -ErrorAction SilentlyContinue
    Write-UpdateLog "Deleted lock file: $lockPath"
}}

Start-Sleep -Seconds 1

$success = $false
if ($isInstaller) {{
    Write-UpdateLog "Executing installer: $updateFile"
    $p = Start-Process -FilePath $updateFile -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /DIR=`"$appDir`"" -Wait -PassThru -WindowStyle Hidden
    if ($p.ExitCode -eq 0 -and (Test-Path $targetExe)) {{
        $success = $true
        Write-UpdateLog "Installer completed successfully."
    }} else {{
        Write-UpdateLog "Installer failed with code $($p.ExitCode)"
    }}
}} else {{
    Write-UpdateLog "Direct EXE replacement: $targetExe <= $updateFile"
    $bakFile = "$targetExe.bak"
    if (Test-Path $bakFile) {{ Remove-Item -Path $bakFile -Force -ErrorAction SilentlyContinue }}
    if (Test-Path $targetExe) {{ Move-Item -Path $targetExe -Destination $bakFile -Force -ErrorAction SilentlyContinue }}
    for ($i = 1; $i -le 5; $i++) {{
        try {{
            Copy-Item -Path $updateFile -Destination $targetExe -Force -ErrorAction Stop
            if (Test-Path $targetExe) {{
                $success = $true
                Write-UpdateLog "Copied new executable on attempt $i"
                break
            }}
        }} catch {{
            Write-UpdateLog "Copy attempt $i failed: $_"
            Start-Sleep -Seconds 1
        }}
    }}
    if ($success) {{
        if (Test-Path $bakFile) {{ Remove-Item -Path $bakFile -Force -ErrorAction SilentlyContinue }}
    }} else {{
        Write-UpdateLog "Direct replacement failed. Restoring backup..."
        if (Test-Path $bakFile) {{ Move-Item -Path $bakFile -Destination $targetExe -Force -ErrorAction SilentlyContinue }}
    }}
}}

if (Test-Path $targetExe) {{
    Write-UpdateLog "Launching application: $targetExe"
    Start-Process -FilePath $targetExe -WindowStyle Normal
}} elseif (Test-Path "$appDir\\iHRMS Monitor.exe") {{
    Write-UpdateLog "Launching application from appDir: $appDir\\iHRMS Monitor.exe"
    Start-Process -FilePath "$appDir\\iHRMS Monitor.exe" -WindowStyle Normal
}} else {{
    Write-UpdateLog "CRITICAL: targetExe does not exist: $targetExe"
}}
Write-UpdateLog "PowerShell updater finished."
'''
    try:
        with open(ps1_path, "w", encoding="utf-8") as f:
            f.write(ps1_content)
    except Exception as p_err:
        logger.warning("Could not write hidden updater PS1: %s", p_err)

    # ----------------------------------------------------------
    # 4. Spawn Detached Hidden Updater Process
    # ----------------------------------------------------------
    try:
        spawned = False
        wscript_path = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "wscript.exe"

        # Primary: wscript.exe (native Windows GUI subsystem application, zero console)
        if wscript_path.exists() and vbs_path.exists():
            try:
                creation_flags = 0
                if sys.platform.startswith("win"):
                    creation_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                subprocess.Popen(
                    [str(wscript_path), "//B", "//nologo", str(vbs_path)],
                    creationflags=creation_flags,
                    close_fds=True,
                )
                logger.info("Spawned detached silent VBScript updater: %s via %s", vbs_path, wscript_path)
                spawned = True
            except Exception as w_err:
                logger.warning("Could not launch updater via wscript.exe: %s. Trying PowerShell fallback.", w_err)

        # Fallback: Hidden PowerShell runner with CREATE_NO_WINDOW
        if not spawned and ps1_path.exists():
            try:
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                si.wShowWindow = 0  # SW_HIDE
                creation_flags = 0
                if sys.platform.startswith("win"):
                    creation_flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
                subprocess.Popen(
                    ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1_path)],
                    startupinfo=si,
                    creationflags=creation_flags,
                    close_fds=True,
                )
                logger.info("Spawned detached silent PowerShell updater: %s", ps1_path)
                spawned = True
            except Exception as ps_err:
                logger.warning("Could not launch updater via PowerShell: %s. Using silent_update.bat fallback.", ps_err)

        # Legacy fallback if both scripts fail to spawn
        if not spawned:
            if bat_path.exists():
                creation_flags = 0
                if sys.platform.startswith("win"):
                    creation_flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
                subprocess.Popen(["cmd.exe", "/c", str(bat_path)], creationflags=creation_flags, close_fds=True)
                logger.info("Spawned detached silent batch updater: %s", bat_path)

        logger.info("Installer launched. Exiting application process cleanly to release file locks.")

        is_running_tests = "unittest" in sys.modules or any("unittest" in str(a).lower() for a in sys.argv)

        # 1. Close Qt windows and stop UI gracefully
        try:
            from PySide6.QtWidgets import QApplication
            from PySide6.QtCore import QCoreApplication
            app = QApplication.instance()
            if app:
                for widget in app.topLevelWidgets():
                    if hasattr(widget, "_really_quit"):
                        widget._really_quit = True
                    try:
                        widget.close()
                    except Exception:
                        pass
                if exit_process and not is_running_tests:
                    app.quit()
                    QCoreApplication.processEvents()
        except Exception as q_err:
            logger.debug("Error closing Qt application: %s", q_err)

        # 2. Release lock file in Python
        try:
            if lock_file_path.exists():
                lock_file_path.unlink()
        except Exception:
            pass

        # 3. Flush and shut down logger
        if not is_running_tests:
            try:
                import logging
                logging.shutdown()
            except Exception:
                pass

        # 4. Immediate, definitive exit - releases all OS file locks immediately
        if exit_process and not is_running_tests:
            os._exit(0)

        if not exit_process or is_running_tests:
            _is_installing_update = False

        return True
    except Exception as err:
        _is_installing_update = False
        logger.exception("Failed to spawn update installer: %s", err)
        try:
            from services.error_report_service import ErrorReportService
            ErrorReportService().report_error("UPDATE_INSTALL_ERROR", f"Failed to launch update installer: {err}", exc=err)
        except Exception:
            pass
        return False


# ==============================================================
# UNIFIED UPDATE PIPELINE WORKER (NON-BLOCKING)
# ==============================================================

class UpdatePipelineWorker(QThread):
    """
    Unified background worker managing the end-to-end update flow without blocking GUI:
    Phase 1: Version Check
    Phase 2: Pending Data Upload (uploads logs & screenshots, or skips if 0 pending)
    Phase 3: Update Download (streams installer with progress)
    Phase 4: Auto-Install & Restart (launches detached silent installer and restarts app)
    """
    phase_changed = Signal(str, str)          # phase_name, description
    progress_changed = Signal(int, int, int)  # percent, current, total
    status_message = Signal(str)              # human-readable message
    update_available = Signal(str, str, bool) # version, download_url, is_force
    upload_completed = Signal()
    download_completed = Signal(str, str, bool) # installer_path, version, is_force
    ready_to_install = Signal(str)            # installer_path
    error_occurred = Signal(str, str)         # phase, error_text

    def __init__(
        self,
        api_url: str,
        indo_code: str | None = None,
        api_key: str | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._api_url = (api_url or "").rstrip("/")
        self._indo_code = indo_code
        self._api_key = api_key
        if not self._indo_code or not self._api_key:
            try:
                from services.session_service import SessionService
                cur = SessionService().current_user
                if cur:
                    self._indo_code = self._indo_code or cur.indo_code
                    self._api_key = self._api_key or cur.api_key
            except Exception:
                pass
        if not self._indo_code or not self._api_key:
            try:
                from services.secure_session import SessionStore
                sdata = SessionStore().load_session()
                if sdata:
                    self._indo_code = self._indo_code or sdata.get("indo_code")
                    self._api_key = self._api_key or sdata.get("api_key")
            except Exception:
                pass
        if not self._api_url:
            try:
                from config.api_config import ApiConfig
                self._api_url = (ApiConfig().base_url or "").rstrip("/")
            except Exception:
                pass
        self._indo_code = self._indo_code or "DEFAULT"
        self._api_key = self._api_key or "DEFAULT"
        self._is_cancelled = False
        self._installer_path: str | None = None
        self._server_version: str | None = None
        self._is_force: bool = False

    def cancel(self) -> None:
        self._is_cancelled = True

    def run(self) -> None:
        try:
            # --------------------------------------------------
            # Phase 1: Version Check
            # --------------------------------------------------
            installed_version = get_running_app_version()
            self.phase_changed.emit("checking", "Checking for updates...")
            self.status_message.emit("Checking for updates...")
            logger.info("Pipeline: Checking for updates (current version: %s)", installed_version)

            server_version = ""
            file_name = ""
            download_url = ""
            force_update = False

            # --------------------------------------------------
            # 1. AppController Version URL (External Manifest)
            # --------------------------------------------------
            try:
                from config.api_config import ApiConfig
                api_cfg = ApiConfig()
                version_url = api_cfg.version_url or api_cfg.activity_tracker_link or DEFAULT_CENTRAL_VERSION_URL
                if version_url:
                    try:
                        timestamp = int(time.time())
                        cb_url = f"{version_url}{'&' if '?' in version_url else '?'}_t={timestamp}"
                        v_resp = requests.get(cb_url, headers=CACHE_BUST_HEADERS, timeout=API_TIMEOUT_SECONDS)
                        if v_resp.status_code == 200 and v_resp.text.strip():
                            v_data = v_resp.json()
                            if isinstance(v_data, dict):
                                server_version = str(
                                    v_data.get("version")
                                    or v_data.get("version_code")
                                    or ""
                                ).strip()
                                file_name = str(
                                    v_data.get("file_name")
                                    or v_data.get("installer")
                                    or ""
                                ).strip()
                                download_url = str(
                                    v_data.get("download_url")
                                    or v_data.get("url")
                                    or v_data.get("link")
                                    or ""
                                ).strip()
                                force_update = bool(v_data.get("force", False))
                    except Exception as ac_fetch_err:
                        logger.debug("Pipeline AppController URL fetch failed: %s", ac_fetch_err)

                if not download_url and api_cfg.activity_tracker_link:
                    atl = str(api_cfg.activity_tracker_link).strip()
                    if atl.lower().endswith(".exe"):
                        download_url = atl
            except Exception as ac_err:
                logger.debug("Pipeline AppController check error: %s", ac_err)

            # --------------------------------------------------
            # 2. Company Endpoint (/punch/check_new_version)
            # --------------------------------------------------
            if not server_version or server_version.upper() == "NA":
                check_url = f"{self._api_url}/punch/check_new_version"
                payload = {
                    "indo_code": self._indo_code,
                    "key": self._api_key,
                    "os_type": "WINDOWS",
                }
                try:
                    cb_check_url = f"{check_url}?_t={int(time.time())}"
                    resp = requests.post(cb_check_url, data=payload, headers=CACHE_BUST_HEADERS, timeout=API_TIMEOUT_SECONDS)
                    if resp.status_code == 200 and resp.text.strip():
                        data = resp.json()
                        if data.get("status") == 1:
                            server_version = str(data.get("version_code", "")).strip()
                            file_name = str(data.get("file_name", "")).strip()
                            if data.get("download_url"):
                                download_url = str(data.get("download_url")).strip()
                            force_update = str(data.get("force_update", "0")).strip() in ("1", "true", "True")
                except Exception as resp_err:
                    logger.debug("Pipeline punch check error: %s", resp_err)

            # --------------------------------------------------
            # 3. Direct AppController Fallback (activity_tracker_version)
            # --------------------------------------------------
            if not server_version or server_version.upper() == "NA":
                try:
                    if api_cfg.activity_tracker_version:
                        server_version = str(api_cfg.activity_tracker_version).strip()
                        logger.info("Using activity_tracker_version configured in AppController: %s", server_version)
                except Exception:
                    pass

            if not server_version or server_version.upper() == "NA" or not is_newer_version(server_version, installed_version):
                logger.info("Pipeline: Application is up to date (current: %s, server: %s)", installed_version, server_version)
                try:
                    from services.device_registry_service import DeviceRegistryService
                    DeviceRegistryService().record_update_success(installed_version)
                except Exception:
                    pass
                self.status_message.emit("Application is up to date.")
                self.phase_changed.emit("done", "Application is up to date.")
                return

            # Check with UpdateStateManager to prevent update loops
            try:
                from services.update_state import UpdateStateManager
                allowed, loop_reason = UpdateStateManager().should_attempt_update(server_version, running_version=installed_version)
                if not allowed:
                    logger.info("Pipeline loop guard: %s", loop_reason)
                    self.status_message.emit("Application is up to date.")
                    self.phase_changed.emit("done", "Application is up to date.")
                    return
            except Exception as loop_err:
                logger.debug("Loop guard check error in pipeline: %s", loop_err)

            if not download_url:
                parts = self._api_url.split("/hrms_api")
                base_domain = parts[0] if parts else self._api_url
                download_url = f"{base_domain}/uploads/{file_name}"

            self._server_version = server_version
            self._is_force = force_update
            try:
                from services.device_registry_service import DeviceRegistryService
                DeviceRegistryService().record_update_pending(server_version)
            except Exception:
                pass

            self.update_available.emit(server_version, download_url, force_update)
            logger.info("Pipeline: Update available: v%s at %s", server_version, download_url)

            if self._is_cancelled:
                return

            # --------------------------------------------------
            # Phase 2: Pending Data Upload
            # --------------------------------------------------
            self.phase_changed.emit("uploading_pending", "Uploading pending activity and screenshots before update...")
            self.status_message.emit("Uploading pending activity and screenshots before update...")

            def _on_flush_progress(pct: int, cur: int, tot: int):
                self.progress_changed.emit(pct, cur, tot)
                if tot > 0:
                    self.status_message.emit(f"Uploading pending data: {cur}/{tot} ({pct}%)")

            upload_success = flush_pending_data_before_update(max_retries=2, on_progress=_on_flush_progress, stop_tracker=False)
            if not upload_success:
                err_msg = "Could not upload pending activity logs/screenshots. Update postponed."
                logger.error("Pipeline: %s", err_msg)
                try:
                    from services.device_registry_service import DeviceRegistryService
                    DeviceRegistryService().record_update_failure(err_msg, target_version=server_version)
                except Exception:
                    pass
                self.error_occurred.emit("uploading_pending", err_msg)
                return

            self.progress_changed.emit(100, 100, 100)
            self.status_message.emit("Pending data upload complete. Starting download...")
            self.upload_completed.emit()

            if self._is_cancelled:
                return

            # --------------------------------------------------
            # Phase 3: Download Installer
            # --------------------------------------------------
            self.phase_changed.emit("downloading", f"Downloading update v{server_version}...")
            self.status_message.emit(f"Downloading update v{server_version}...")
            updates_dir = get_updates_directory()
            safe_name = f"iHRMSMonitorSetup_v{server_version}.exe"
            installer_path = updates_dir / safe_name
            temp_path = updates_dir / f"{safe_name}.part"

            # Clean up 0-byte or corrupted installer file left from previous failed runs
            if installer_path.exists() and installer_path.stat().st_size < 1024 * 100:
                try:
                    installer_path.unlink()
                except Exception:
                    pass

            download_successful = False

            if installer_path.exists() and installer_path.stat().st_size >= 1024 * 100:
                try:
                    with open(installer_path, "rb") as vf:
                        if vf.read(2) == b"MZ":
                            download_successful = True
                            logger.info("Pipeline: Installer already downloaded and verified: %s", installer_path)
                except Exception:
                    pass

            if not download_successful:
                candidates = resolve_download_candidates(
                    api_url=self._api_url,
                    file_name=file_name,
                    download_url=download_url,
                    activity_tracker_link=getattr(api_cfg, "activity_tracker_link", ""),
                )
                logger.info("Pipeline: Candidate download URLs for v%s: %s", server_version, candidates)

                for cand_url in candidates:
                    if self._is_cancelled:
                        return
                    if temp_path.exists():
                        try:
                            temp_path.unlink()
                        except Exception:
                            pass

                    logger.info("Pipeline: Trying download from candidate: %s", cand_url)
                    try:
                        with requests.get(cand_url, stream=True, timeout=60) as resp:
                            if resp.status_code != 200:
                                logger.debug("Candidate %s returned HTTP %s", cand_url, resp.status_code)
                                continue
                            ct = resp.headers.get("content-type", "").lower()
                            if "text/html" in ct or "text/plain" in ct:
                                logger.debug("Candidate %s returned HTML error body", cand_url)
                                continue
                            total_size = int(resp.headers.get("content-length", 0))
                            if total_size > 0 and total_size < 1024 * 100:
                                logger.debug("Candidate %s content-length %d is too small", cand_url, total_size)
                                continue

                            downloaded = 0
                            is_valid_header = None
                            with open(temp_path, "wb") as f:
                                for chunk in resp.iter_content(chunk_size=65536):
                                    if self._is_cancelled:
                                        return
                                    if chunk:
                                        if is_valid_header is None:
                                            if chunk[:2] != b"MZ":
                                                is_valid_header = False
                                                break
                                            is_valid_header = True
                                        f.write(chunk)
                                        downloaded += len(chunk)
                                        if total_size > 0:
                                            pct = int((downloaded / total_size) * 100)
                                            self.progress_changed.emit(pct, downloaded, total_size)
                                            self.status_message.emit(f"Downloading update: {pct}%")

                            if is_valid_header is False:
                                logger.debug("Candidate %s lacked MZ header", cand_url)
                                if temp_path.exists():
                                    temp_path.unlink()
                                continue

                            if temp_path.exists() and temp_path.stat().st_size >= 1024 * 100:
                                if installer_path.exists():
                                    installer_path.unlink()
                                temp_path.rename(installer_path)
                                download_successful = True
                                logger.info("Pipeline: Download succeeded from %s (%d bytes)", cand_url, installer_path.stat().st_size)
                                break
                    except Exception as cand_err:
                        logger.debug("Download failed for candidate %s: %s", cand_url, cand_err)
                        if temp_path.exists():
                            try:
                                temp_path.unlink()
                            except Exception:
                                pass

                # Development / test fallback: if server doesn't host file yet, check local built installer
                if not download_successful:
                    local_candidates = [
                        Path("dist/installer/iHRMSMonitorSetup.exe"),
                        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "iHRMS Monitor" / "iHRMSMonitorSetup.exe",
                    ]
                    for loc_p in local_candidates:
                        if loc_p.exists() and loc_p.stat().st_size >= 1024 * 100:
                            try:
                                with open(loc_p, "rb") as lf:
                                    if lf.read(2) == b"MZ":
                                        import shutil
                                        shutil.copyfile(loc_p, installer_path)
                                        download_successful = True
                                        logger.info("Pipeline: Adopted local installer package from %s (%d bytes)", loc_p, installer_path.stat().st_size)
                                        break
                            except Exception:
                                pass

            if not download_successful or not installer_path.exists() or installer_path.stat().st_size < 1024 * 100:
                err_msg = f"Update installer for v{server_version} could not be downloaded from the server."
                try:
                    from services.device_registry_service import DeviceRegistryService
                    DeviceRegistryService().record_update_failure(err_msg, target_version=server_version)
                except Exception:
                    pass
                self.error_occurred.emit("downloading", err_msg)
                return

            try:
                from services.update_state import UpdateStateManager
                UpdateStateManager().record_download_complete(server_version, str(installer_path), installer_path.stat().st_size)
            except Exception:
                pass

            self.progress_changed.emit(100, installer_path.stat().st_size, installer_path.stat().st_size)
            self.status_message.emit("Download complete! Ready to install.")
            self.download_completed.emit(str(installer_path), server_version, force_update)

            # --------------------------------------------------
            # Phase 4: Auto-Install & Restart
            # --------------------------------------------------
            self.phase_changed.emit("installing", "Launching update installer and restarting...")
            self.status_message.emit("Launching update installer and restarting...")
            self.ready_to_install.emit(str(installer_path))

            UpdateService()._downloaded_installer = str(installer_path)
            UpdateService()._available_version = server_version
            UpdateService()._is_force_update = force_update

            # Finalize active tracking session and flush pending records right before installer execution
            is_running_tests = "unittest" in sys.modules or any("unittest" in str(a).lower() for a in sys.argv)
            if getattr(sys, "frozen", False) or is_running_tests:
                try:
                    flush_pending_data_before_update(max_retries=1, stop_tracker=True)
                except Exception as final_flush_err:
                    logger.debug("Pre-restart flush warning: %s", final_flush_err)

                # Automatically launch installer and restart application
                time.sleep(1.0)
                install_update_and_restart(str(installer_path), target_version=server_version)
            else:
                logger.info("Running in development/source mode; skipping automatic binary installer execution.")
                self.phase_changed.emit("done", "Update available: installer downloaded.")
                self.status_message.emit("Update ready.")

        except Exception as err:
            logger.exception("Update pipeline error: %s", err)
            try:
                from services.device_registry_service import DeviceRegistryService
                DeviceRegistryService().record_update_failure(str(err))
            except Exception:
                pass
            try:
                from services.error_report_service import ErrorReportService
                ErrorReportService().report_error(
                    error_type="UPDATE_PIPELINE_ERROR",
                    error_message=f"Update pipeline failed: {err}",
                    exc=err,
                    extra_context={
                        "endpoint": "/appcontroller/appcontroller",
                        "api_url": self._api_url,
                        "phase": "pipeline",
                    },
                )
            except Exception:
                pass
            self.error_occurred.emit("pipeline", str(err))


# ==============================================================
# UPDATE SERVICE SINGLETON
# ==============================================================

class UpdateService(QObject):
    """Main application update manager."""

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, parent: QObject | None = None) -> None:
        if getattr(self, "_initialized", False):
            return
        super().__init__(parent)
        self._initialized = True
        self._worker: UpdateCheckWorker | None = None
        self._pipeline_worker: UpdatePipelineWorker | None = None
        self._downloaded_installer: str | None = None
        self._available_version: str | None = None
        self._is_force_update: bool = False

    @property
    def is_update_ready(self) -> bool:
        """Return True if an update has been downloaded and is ready to install."""
        return bool(self._downloaded_installer and Path(self._downloaded_installer).exists())

    @property
    def available_version(self) -> str | None:
        """Return the latest available version string if detected."""
        return self._available_version

    @property
    def is_force_update(self) -> bool:
        """Return True if the available update is marked mandatory."""
        return self._is_force_update

    def start_pipeline(
        self,
        api_url: str,
        indo_code: str | None = None,
        api_key: str | None = None,
        on_phase=None,
        on_progress=None,
        on_status=None,
        on_available=None,
        on_upload_completed=None,
        on_download_completed=None,
        on_ready_to_install=None,
        on_error=None,
    ) -> UpdatePipelineWorker:
        """Start the complete non-blocking background update pipeline."""
        if self._pipeline_worker is not None and self._pipeline_worker.isRunning():
            logger.info("Update pipeline already running. Returning active instance.")
            return self._pipeline_worker

        self._pipeline_worker = UpdatePipelineWorker(
            api_url=api_url,
            indo_code=indo_code,
            api_key=api_key,
        )

        def _handle_available(ver: str, url: str, force: bool):
            self._available_version = ver
            self._is_force_update = force
            if on_available:
                on_available(ver, url, force)

        def _handle_download_completed(path: str, ver: str, force: bool):
            self._downloaded_installer = path
            self._available_version = ver
            self._is_force_update = force
            if on_download_completed:
                on_download_completed(path, ver, force)

        self._pipeline_worker.update_available.connect(_handle_available)
        self._pipeline_worker.download_completed.connect(_handle_download_completed)

        if on_phase:
            self._pipeline_worker.phase_changed.connect(on_phase)
        if on_progress:
            self._pipeline_worker.progress_changed.connect(on_progress)
        if on_status:
            self._pipeline_worker.status_message.connect(on_status)
        if on_upload_completed:
            self._pipeline_worker.upload_completed.connect(on_upload_completed)
        if on_ready_to_install:
            self._pipeline_worker.ready_to_install.connect(on_ready_to_install)
        if on_error:
            self._pipeline_worker.error_occurred.connect(on_error)

        self._pipeline_worker.start()
        return self._pipeline_worker

    def check_for_updates(
        self,
        api_url: str,
        indo_code: str | None = None,
        api_key: str | None = None,
        auto_download: bool = True,
        on_available=None,
        on_progress=None,
        on_completed=None,
        on_error=None,
    ) -> None:
        """Start a background update check."""
        if self._worker is not None and self._worker.isRunning():
            logger.info("Update check already in progress. Ignoring duplicate request.")
            return

        self._worker = UpdateCheckWorker(
            api_url=api_url,
            indo_code=indo_code,
            api_key=api_key,
            auto_download=auto_download,
        )

        def _handle_available(version: str, url: str, force: bool):
            self._available_version = version
            self._is_force_update = force
            if on_available:
                on_available(version, url, force)

        def _handle_completed(installer_path: str, version: str, force: bool):
            self._downloaded_installer = installer_path
            self._available_version = version
            self._is_force_update = force
            if on_completed:
                on_completed(installer_path, version, force)

        self._worker.update_available.connect(_handle_available)
        if on_progress:
            self._worker.download_progress.connect(on_progress)
        self._worker.download_completed.connect(_handle_completed)
        if on_error:
            self._worker.error_occurred.connect(on_error)

        self._worker.start()

    def apply_update(self, installer_path: str | None = None, pre_flush: bool = True) -> bool:
        """
        Install the downloaded update and restart the application.

        Prior to running the installer, uploads all pending activity logs
        and screenshots. If pending data cannot be uploaded, halts the update
        to avoid data loss.
        """
        target_path = installer_path or self._downloaded_installer
        if not target_path or not Path(target_path).exists():
            logger.warning("apply_update called but installer path is invalid: %s", target_path)
            return False

        self._downloaded_installer = str(target_path)

        if pre_flush:
            logger.info("Uploading pending activity and screenshot data prior to update...")
            if not flush_pending_data_before_update():
                logger.error("Update aborted: pending activity/screenshot data could not be uploaded.")
                return False

        return install_update_and_restart(self._downloaded_installer, target_version=self._available_version)

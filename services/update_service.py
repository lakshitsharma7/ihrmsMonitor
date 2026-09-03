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
from utils.paths import get_updates_directory

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
        self._api_url = api_url.rstrip("/")
        self._indo_code = indo_code or "DEFAULT"
        self._api_key = api_key or "DEFAULT"
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
            # 1. AppController Version URL & Configuration Source
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
                        if v_resp.status_code == 200:
                            try:
                                v_data = v_resp.json()
                                if isinstance(v_data, dict):
                                    server_version = str(
                                        v_data.get("version")
                                        or v_data.get("version_code")
                                        or v_data.get("activity_tracker_version")
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

                # If version not resolved from URL GET, check direct activity_tracker_version in AppController
                if not server_version and api_cfg.activity_tracker_version:
                    server_version = str(api_cfg.activity_tracker_version).strip()
                    logger.info("Using activity_tracker_version configured in AppController: %s", server_version)

                if not download_url and api_cfg.activity_tracker_link:
                    download_url = api_cfg.activity_tracker_link

            except Exception as ac_err:
                logger.debug("Error checking AppController version details: %s", ac_err)

            # ----------------------------------------------------------
            # 2. Company Endpoint Fallback (/punch/check_new_version)
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
                    if resp.status_code == 200:
                        data = resp.json()
                        logger.info("Version check response from punch/check_new_version: %s", data)
                        if data.get("status") == 1:
                            server_version = str(data.get("version_code", "")).strip()
                            file_name = str(data.get("file_name", "")).strip()
                            force_update = str(data.get("force_update", "0")).strip() in ("1", "true", "True")
                except Exception as punch_err:
                    logger.debug("Punch check_new_version failed: %s", punch_err)

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

            # Resolve the download URL
            if not download_url:
                download_url = self._resolve_download_url(file_name)

            logger.info(
                "Newer version available: v%s (current: v%s). Download target: %s (force=%s)",
                server_version,
                APP_VERSION,
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
                    extra_context={"current_version": APP_VERSION, "api_url": self._api_url},
                )
            except Exception:
                pass

    def _resolve_download_url(self, file_name: str) -> str:
        """Construct full download URL from file_name or return direct URL."""
        if file_name.startswith("http://") or file_name.startswith("https://"):
            return file_name

        # Deriving from api_url base domain
        # e.g. https://softdev.indovisionservices.in/ihrms84/hrms_api/ci4/api -> https://softdev.indovisionservices.in/ihrms84
        parts = self._api_url.split("/hrms_api")
        base_domain = parts[0] if parts else self._api_url
        return f"{base_domain}/uploads/{file_name}"

    def _download_installer(self, download_url: str, version: str, force_update: bool) -> None:
        """Download installer file with streaming progress to updates directory."""
        updates_dir = get_updates_directory()
        installer_path = updates_dir / f"iHRMSMonitorSetup_v{version}.exe"

        # Check if already downloaded and verified
        if installer_path.exists() and installer_path.stat().st_size > 1024 * 1024:
            logger.info("Installer already downloaded at: %s", installer_path)
            self.download_progress.emit(100, installer_path.stat().st_size, installer_path.stat().st_size)
            self.download_completed.emit(str(installer_path), version, force_update)
            self.check_completed.emit(True)
            return

        temp_path = updates_dir / f"iHRMSMonitorSetup_v{version}.tmp"
        self.status_changed.emit(f"Downloading update v{version}...")
        logger.info("Downloading update installer from %s to %s", download_url, temp_path)

        try:
            with requests.get(download_url, stream=True, timeout=60) as r:
                if r.status_code != 200:
                    logger.warning("Failed to download installer (HTTP %d)", r.status_code)
                    self.error_occurred.emit(f"Download failed with HTTP {r.status_code}")
                    return

                total_size = int(r.headers.get("content-length", 0))
                downloaded = 0
                chunk_size = 64 * 1024  # 64 KB chunks

                with open(temp_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=chunk_size):
                        if self._is_cancelled:
                            logger.info("Update download cancelled by user.")
                            f.close()
                            if temp_path.exists():
                                temp_path.unlink()
                            return

                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                percent = int((downloaded / total_size) * 100)
                                self.download_progress.emit(percent, downloaded, total_size)

            # Atomic rename from .tmp to .exe
            if temp_path.exists():
                if installer_path.exists():
                    installer_path.unlink()
                temp_path.rename(installer_path)

            logger.info("Download completed successfully: %s (%d bytes)", installer_path, installer_path.stat().st_size)
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

    # Finalize active tracking session if tracker is running
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app:
            for widget in app.topLevelWidgets():
                if hasattr(widget, "stop_tracking") and hasattr(widget, "_tracker") and widget._tracker and getattr(widget._tracker, "is_tracking", False):
                    logger.info("Stopping active tracking to record session before update.")
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
# SAFE INSTALLATION & RESTART
# ==============================================================

def install_update_and_restart(installer_path: str) -> bool:
    """
    Safely execute the Inno Setup installer in silent/unattended upgrade mode and relaunch the updated app.

    Inno Setup flags:
    /SILENT: Show progress window without interactive wizard pages.
    /SP-: Skip initial 'This will install...' prompt.
    /CLOSEAPPLICATIONS: Gracefully close running app processes.
    """
    path = Path(installer_path)
    if not path.exists():
        err_msg = f"Cannot launch installer: file does not exist at {installer_path}"
        logger.error(err_msg)
        try:
            from services.error_report_service import ErrorReportService
            ErrorReportService().report_error("UPDATE_INSTALL_ERROR", err_msg)
        except Exception:
            pass
        return False

    if path.stat().st_size < 1024 * 100:
        err_msg = f"Cannot launch installer: file is incomplete ({path.stat().st_size} bytes)"
        logger.error(err_msg)
        try:
            from services.error_report_service import ErrorReportService
            ErrorReportService().report_error("UPDATE_INSTALL_ERROR", err_msg)
        except Exception:
            pass
        return False

    logger.info("Preparing detached installer launch: %s", path)

    updates_dir = get_updates_directory()
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    target_exe = Path(local_app_data) / "Programs" / "iHRMS Monitor" / "iHRMS Monitor.exe"

    bat_path = updates_dir / "silent_update.bat"
    bat_content = f"""@echo off
timeout /t 2 /nobreak > NUL
start "" /wait "{path}" /SILENT /SP- /CLOSEAPPLICATIONS
if exist "{target_exe}" (
    start "" "{target_exe}"
)
del "%~f0"
"""
    try:
        with open(bat_path, "w", encoding="utf-8") as f:
            f.write(bat_content)
    except Exception as w_err:
        logger.warning("Could not write helper bat file: %s", w_err)

    try:
        creation_flags = 0
        if sys.platform.startswith("win"):
            creation_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

        if bat_path.exists():
            subprocess.Popen(["cmd.exe", "/c", str(bat_path)], creationflags=creation_flags, close_fds=True)
            logger.info("Spawned detached silent update script: %s", bat_path)
        else:
            cmd = f'cmd.exe /c start "" "{path}" /SILENT /SP- /CLOSEAPPLICATIONS'
            subprocess.Popen(cmd, shell=True, creationflags=creation_flags)

        logger.info("Installer launched. Quitting current application cleanly.")

        # Cleanly quit application
        app = QApplication.instance()
        if app:
            app.quit()
        return True
    except Exception as err:
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
        self._api_url = api_url.rstrip("/")
        self._indo_code = indo_code or "DEFAULT"
        self._api_key = api_key or "DEFAULT"
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

            # AppController
            try:
                from config.api_config import ApiConfig
                api_cfg = ApiConfig()
                version_url = api_cfg.version_url or api_cfg.activity_tracker_link or DEFAULT_CENTRAL_VERSION_URL
                if version_url:
                    try:
                        timestamp = int(time.time())
                        cb_url = f"{version_url}{'&' if '?' in version_url else '?'}_t={timestamp}"
                        v_resp = requests.get(cb_url, headers=CACHE_BUST_HEADERS, timeout=API_TIMEOUT_SECONDS)
                        if v_resp.status_code == 200:
                            v_data = v_resp.json()
                            if isinstance(v_data, dict):
                                server_version = str(
                                    v_data.get("version")
                                    or v_data.get("version_code")
                                    or v_data.get("activity_tracker_version")
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

                if not server_version and api_cfg.activity_tracker_version:
                    server_version = str(api_cfg.activity_tracker_version).strip()
                if not download_url and api_cfg.activity_tracker_link:
                    download_url = api_cfg.activity_tracker_link
            except Exception as ac_err:
                logger.debug("Pipeline AppController check error: %s", ac_err)

            # Punch check_new_version fallback
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
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("status") == 1:
                            server_version = str(data.get("version_code", "")).strip()
                            file_name = str(data.get("file_name", "")).strip()
                            force_update = str(data.get("force_update", "0")).strip() in ("1", "true", "True")
                except Exception as resp_err:
                    logger.debug("Pipeline punch check error: %s", resp_err)

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

            upload_success = flush_pending_data_before_update(max_retries=2, on_progress=_on_flush_progress)
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

            if installer_path.exists() and installer_path.stat().st_size > 1024 * 100:
                logger.info("Pipeline: Installer already downloaded and verified: %s", installer_path)
            else:
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except Exception:
                        pass

                logger.info("Pipeline: Downloading installer from %s to %s", download_url, temp_path)
                with requests.get(download_url, stream=True, timeout=60) as resp:
                    resp.raise_for_status()
                    total_size = int(resp.headers.get("content-length", 0))
                    downloaded = 0
                    with open(temp_path, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=65536):
                            if self._is_cancelled:
                                return
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                if total_size > 0:
                                    pct = int((downloaded / total_size) * 100)
                                    self.progress_changed.emit(pct, downloaded, total_size)
                                    self.status_message.emit(f"Downloading update: {pct}%")

                if temp_path.exists():
                    if installer_path.exists():
                        installer_path.unlink()
                    temp_path.rename(installer_path)

            if not installer_path.exists() or installer_path.stat().st_size < 1024 * 100:
                err_msg = "Downloaded installer is incomplete or corrupt."
                try:
                    from services.device_registry_service import DeviceRegistryService
                    DeviceRegistryService().record_update_failure(err_msg, target_version=server_version)
                except Exception:
                    pass
                self.error_occurred.emit("downloading", err_msg)
                return

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

            # Automatically launch installer and restart application
            time.sleep(1.0)
            install_update_and_restart(str(installer_path))

        except Exception as err:
            logger.exception("Update pipeline error: %s", err)
            try:
                from services.device_registry_service import DeviceRegistryService
                DeviceRegistryService().record_update_failure(str(err))
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

        return install_update_and_restart(self._downloaded_installer)

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
import json
import subprocess
from pathlib import Path
from datetime import datetime, timezone

import requests
from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import QApplication

from config.settings import APP_VERSION
from utils.logger import get_logger
from utils.paths import get_updates_directory

API_TIMEOUT_SECONDS = 15

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


def is_newer_version(server_version: str, current_version: str = APP_VERSION) -> bool:
    """Return True if server_version is strictly newer than current_version."""
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
            self.status_changed.emit("Checking for updates...")
            logger.info("Checking for updates against API: %s (current version: %s)", self._api_url, APP_VERSION)

            check_url = f"{self._api_url}/punch/check_new_version"
            payload = {
                "indo_code": self._indo_code,
                "key": self._api_key,
                "os_type": "WINDOWS",
            }

            resp = requests.post(check_url, data=payload, timeout=API_TIMEOUT_SECONDS)
            if resp.status_code != 200:
                logger.warning("Version check failed with HTTP status: %d", resp.status_code)
                self.check_completed.emit(False)
                return

            data = resp.json()
            logger.info("Version check response: %s", data)

            if data.get("status") != 1:
                logger.info("No active update available on server (status != 1).")
                self.check_completed.emit(False)
                return

            server_version = str(data.get("version_code", "")).strip()
            file_name = str(data.get("file_name", "")).strip()
            force_update = str(data.get("force_update", "0")).strip() == "1"

            if not server_version or server_version.upper() == "NA":
                logger.info("Server version code is NA. Application is up to date.")
                self.check_completed.emit(False)
                return

            # Check if server version is strictly newer than current app version
            if not is_newer_version(server_version, APP_VERSION):
                logger.info(
                    "Current version (%s) is up to date with server version (%s).",
                    APP_VERSION,
                    server_version,
                )
                self.status_changed.emit("Application is up to date.")
                self.check_completed.emit(False)
                return

            # Resolve the download URL
            download_url = self._resolve_download_url(file_name)
            logger.info(
                "Newer version available: v%s (current: v%s). Download target: %s (force=%s)",
                server_version,
                APP_VERSION,
                download_url,
                force_update,
            )

            self.update_available.emit(server_version, download_url, force_update)

            # Check if the file is a Windows executable (.exe)
            if not file_name.lower().endswith(".exe") and not download_url.lower().endswith(".exe"):
                logger.info(
                    "New version %s found, but file_name '%s' is not a Windows installer (.exe). Skipping automatic binary download.",
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
        logger.error("Cannot launch installer: file does not exist at %s", installer_path)
        return False

    if not str(path).lower().endswith(".exe"):
        logger.error("Cannot launch installer: file is not a Windows executable (%s)", installer_path)
        return False

    logger.info("Launching update installer: %s", path)

    # Inno Setup installation target executable
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    target_exe = Path(local_app_data) / "Programs" / "iHRMS Monitor" / "iHRMS Monitor.exe"

    # Command: run installer silently, wait for installation completion, then launch the updated app
    if target_exe.parent.exists():
        cmd = f'cmd.exe /c "start /wait \"\" \"{path}\" /SILENT /SP- /CLOSEAPPLICATIONS & start \"\" \"{target_exe}\""'
    else:
        cmd = f'cmd.exe /c start "" "{path}" /SILENT /SP- /CLOSEAPPLICATIONS'

    try:
        subprocess.Popen(cmd, shell=True)
        logger.info("Installer and restart sequence spawned. Quitting current application cleanly.")

        # Cleanly quit application
        app = QApplication.instance()
        if app:
            app.quit()
        return True
    except Exception as err:
        logger.exception("Failed to spawn update installer: %s", err)
        return False


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

    def apply_update(self) -> bool:
        """Install the downloaded update and restart the application."""
        if not self._downloaded_installer:
            logger.warning("apply_update called but no installer was downloaded.")
            return False
        return install_update_and_restart(self._downloaded_installer)

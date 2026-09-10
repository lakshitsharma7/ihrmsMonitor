"""Persistent Update State Management and Loop Prevention for iHRMS Monitor.

Maintains an atomic state store in %LOCALAPPDATA%\\iHRMS Monitor\\updates\\update_state.json.
Guarantees that:
1. After restarting, the application verifies whether the newly installed executable
   version matches or exceeds the target version.
2. If replacement failed (e.g. file lock or permissions error), the old running EXE detects
   this immediately, records the failure, and prevents infinite download/restart loops.
3. If repeated attempts (>= 2) fail for the same server version, automatic updates for that
   version are placed on a 24-hour cooldown while keeping the current application fully functional.
4. On-demand manual update checks by the user reset cooldown.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from config.settings import get_running_app_version
from utils.logger import get_logger
from utils.paths import get_updates_directory

logger = get_logger(__name__)

MAX_INSTALL_ATTEMPTS = 2
DEFAULT_COOLDOWN_SECONDS = 86400  # 24 hours


def _parse_version(v_str: str) -> tuple[int, ...]:
    import re
    if not v_str:
        return (0,)
    v = v_str.lstrip("vV").strip()
    parts = re.split(r"[.\-_]", v)
    nums = []
    for p in parts:
        m = re.match(r"^\d+", p)
        if m:
            val_str = m.group()
            if len(val_str) > 1 and val_str.startswith("0"):
                for ch in val_str:
                    nums.append(int(ch))
            else:
                nums.append(int(val_str))
        else:
            nums.append(0)
    return tuple(nums) if nums else (0,)


def _is_version_ge(v1: str, v2: str) -> bool:
    """Return True if v1 >= v2."""
    p1 = _parse_version(v1)
    p2 = _parse_version(v2)
    max_len = max(len(p1), len(p2))
    p1_norm = p1 + (0,) * (max_len - len(p1))
    p2_norm = p2 + (0,) * (max_len - len(p2))
    return p1_norm >= p2_norm


class UpdateStateManager:
    """Thread-safe persistent update state store."""

    _instance: UpdateStateManager | None = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs) -> UpdateStateManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, state_file: Path | None = None) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._state_file = state_file or (get_updates_directory() / "update_state.json")
        self._io_lock = threading.Lock()

    @property
    def state_file(self) -> Path:
        return self._state_file

    def _read_raw(self) -> dict:
        if not self._state_file.exists():
            return {}
        try:
            with open(self._state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as err:
            logger.debug("Could not parse update state file %s: %s", self._state_file, err)
            return {}

    def _write_raw(self, data: dict) -> None:
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            temp_file = self._state_file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            temp_file.replace(self._state_file)
        except Exception as err:
            logger.warning("Could not save update state to %s: %s", self._state_file, err)

    def get_state(self) -> dict:
        """Return a copy of the current update state."""
        with self._io_lock:
            return self._read_raw()

    def check_post_restart_status(self, running_version: str | None = None) -> tuple[bool, str]:
        """
        Verify update outcome on application startup.

        Returns:
            (is_success, summary_message)
        """
        with self._io_lock:
            state = self._read_raw()
            if not state:
                return True, "No pending update state."

            status = state.get("status")
            target_version = str(state.get("target_version") or "").strip()

            if not target_version or status not in ("pending_install", "installing"):
                return True, "No pending installation to verify."

            if running_version is None:
                running_version = get_running_app_version()

            now_iso = datetime.now(timezone.utc).isoformat()

            # Check if running version successfully reached or exceeded target version
            if _is_version_ge(running_version, target_version):
                msg = (
                    f"Update verification SUCCESSFUL: application upgraded to v{running_version} "
                    f"(target was v{target_version})."
                )
                logger.info(msg)
                state.update({
                    "status": "success",
                    "last_installed_version": running_version,
                    "verified_at": now_iso,
                    "install_attempts": 0,
                    "cooldown_until": 0,
                    "last_error": None,
                })
                self._write_raw(state)

                # Clean up downloaded installer files
                self._cleanup_downloaded_packages(target_version)

                try:
                    from services.device_registry_service import DeviceRegistryService
                    DeviceRegistryService().record_update_success(running_version)
                except Exception:
                    pass

                return True, msg

            # If here: executable was NOT updated, but the app restarted!
            attempts = int(state.get("install_attempts", 0)) + 1
            max_attempts = int(state.get("max_attempts", MAX_INSTALL_ATTEMPTS))
            cooldown_until = 0

            if attempts >= max_attempts:
                cooldown_until = time.time() + DEFAULT_COOLDOWN_SECONDS
                err_msg = (
                    f"Update verification FAILED: expected v{target_version}, but running application "
                    f"is still v{running_version}. Max install attempts ({attempts}/{max_attempts}) reached. "
                    f"Automatic updates for v{target_version} are paused for 24 hours to prevent restart loops."
                )
                logger.error(err_msg)
                state["status"] = "failed"
            else:
                err_msg = (
                    f"Update verification FAILED: expected v{target_version}, but running application "
                    f"is still v{running_version}. (Attempt {attempts}/{max_attempts})"
                )
                logger.warning(err_msg)
                state["status"] = "failed"

            state.update({
                "install_attempts": attempts,
                "last_attempt_at": now_iso,
                "cooldown_until": cooldown_until,
                "last_error": err_msg,
            })
            self._write_raw(state)

            try:
                from services.device_registry_service import DeviceRegistryService
                DeviceRegistryService().record_update_failure(
                    reason=err_msg,
                    target_version=target_version,
                )
            except Exception:
                pass

            try:
                from services.error_report_service import ErrorReportService
                ErrorReportService().report_error(
                    error_type="AUTO_UPDATE_FAILED",
                    error_message=err_msg,
                    extra_context={
                        "target_version": target_version,
                        "running_version": running_version,
                        "install_attempts": attempts,
                        "max_attempts": max_attempts,
                        "cooldown_until": cooldown_until,
                    },
                )
            except Exception:
                pass

            return False, err_msg

    def should_attempt_update(
        self,
        server_version: str,
        running_version: str | None = None,
        manual: bool = False,
    ) -> tuple[bool, str]:
        """
        Determine whether an update to server_version should proceed.

        Returns:
            (allow_update, reason)
        """
        if not server_version:
            return False, "Server version is empty."

        if running_version is None:
            running_version = get_running_app_version()

        if _is_version_ge(running_version, server_version):
            return False, f"Running version v{running_version} is already up to date with v{server_version}."

        with self._io_lock:
            state = self._read_raw()
            target_version = str(state.get("target_version") or "").strip()

            if manual:
                # User clicked "Check for Updates" or "Retry Update" manually; reset cooldown
                if target_version == server_version:
                    state["cooldown_until"] = 0
                    state["install_attempts"] = 0
                    self._write_raw(state)
                return True, "Manual update request."

            if target_version == server_version:
                cooldown_until = float(state.get("cooldown_until", 0) or 0)
                attempts = int(state.get("install_attempts", 0))
                now = time.time()

                if cooldown_until > now:
                    remaining_hours = max(0.1, round((cooldown_until - now) / 3600, 1))
                    reason = (
                        f"Update to v{server_version} previously failed {attempts} times and is in cooldown "
                        f"for another {remaining_hours} hours to prevent restart loops."
                    )
                    logger.info("Loop Guard: %s", reason)
                    return False, reason

        return True, "Update permitted."

    def record_download_start(self, target_version: str) -> None:
        """Mark download started."""
        with self._io_lock:
            state = self._read_raw()
            state.update({
                "target_version": target_version,
                "status": "downloading",
                "download_started_at": datetime.now(timezone.utc).isoformat(),
            })
            self._write_raw(state)

    def record_download_complete(self, target_version: str, file_path: str, file_size: int) -> None:
        """Mark download completed and ready to install."""
        with self._io_lock:
            state = self._read_raw()
            state.update({
                "target_version": target_version,
                "status": "pending_install",
                "downloaded_file": str(file_path),
                "download_size": file_size,
                "download_completed_at": datetime.now(timezone.utc).isoformat(),
            })
            self._write_raw(state)

    def record_install_start(self, target_version: str, file_path: str) -> None:
        """Mark installation about to be executed by the hidden updater."""
        with self._io_lock:
            state = self._read_raw()
            state.update({
                "target_version": target_version,
                "status": "installing",
                "downloaded_file": str(file_path),
                "last_attempt_at": datetime.now(timezone.utc).isoformat(),
            })
            self._write_raw(state)

    def reset_cooldown(self, target_version: str | None = None) -> None:
        """Clear cooldown and reset attempt counters."""
        with self._io_lock:
            state = self._read_raw()
            if not target_version or state.get("target_version") == target_version:
                state["cooldown_until"] = 0
                state["install_attempts"] = 0
                state["last_error"] = None
                self._write_raw(state)

    def clear_state(self) -> None:
        """Clear all stored state from state file."""
        with self._io_lock:
            if self._state_file.exists():
                try:
                    self._state_file.unlink()
                except Exception:
                    pass

    def _cleanup_downloaded_packages(self, current_target_version: str) -> None:
        """Purge temporary installer and update packages after success."""
        try:
            updates_dir = get_updates_directory()
            for item in updates_dir.glob("*"):
                if item.is_file() and item.name != "update_state.json":
                    try:
                        item.unlink()
                        logger.debug("Cleaned up installer package: %s", item)
                    except Exception:
                        pass
        except Exception as err:
            logger.debug("Error cleaning updates directory: %s", err)

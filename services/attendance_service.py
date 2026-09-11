"""Attendance and System Start tracking service for iHRMS Monitor.

Tracks:
1. Daily Windows/System boot time (system_started_at) via psutil.boot_time().
2. Daily iHRMS Monitor tracking start time (tracking_started_at).
3. Optional Punch-In (punch_in) and Punch-Out (punch_out) timestamps.
4. Handles multiple application/system restarts without overwriting daily start time.
5. Offline-first local JSON/QSettings persistence.
"""

from __future__ import annotations

import json
import os
import socket
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil
from PySide6.QtCore import QSettings

from utils.logger import get_logger

logger = get_logger(__name__)


def _get_boot_datetime() -> datetime:
    """Return the system boot time as a localized datetime."""
    try:
        boot_ts = psutil.boot_time()
        return datetime.fromtimestamp(boot_ts).astimezone()
    except Exception as exc:
        logger.debug("Could not read psutil.boot_time: %s", exc)
        return datetime.now().astimezone()


def _format_dt(dt: datetime | None) -> str | None:
    """Format datetime to standard string YYYY-MM-DD HH:MM:SS."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%d %H:%M:%S")


class AttendanceService:
    """Singleton service for daily system start, tracking start, and punch tracking."""

    _instance: AttendanceService | None = None
    _lock = threading.Lock()

    def __new__(cls) -> AttendanceService:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._state_lock = threading.Lock()
        self._settings = QSettings("Indovision", "iHRMSMonitor")
        self._state_file = self._resolve_state_file_path()

    def _resolve_state_file_path(self) -> Path:
        """Resolve persistent JSON file path in user app data or local directory."""
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            data_dir = Path(local_app_data) / "iHRMS Monitor" / "data"
        else:
            data_dir = Path.home() / ".ihrms_monitor" / "data"
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return data_dir / "attendance_state.json"

    def _load_state(self) -> dict:
        """Load attendance dictionary from persistent JSON file."""
        if self._state_file.exists():
            try:
                with open(self._state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
            except Exception as read_err:
                logger.debug("Could not read attendance_state.json: %s", read_err)
        return {}

    def _save_state(self, state: dict) -> None:
        """Save attendance dictionary to persistent JSON file."""
        try:
            with open(self._state_file, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
        except Exception as write_err:
            logger.debug("Could not write attendance_state.json: %s", write_err)

    def clear_state(self, date_str: str | None = None) -> None:
        """Clear state for a specific date or all dates (used during resets / tests)."""
        with self._state_lock:
            if date_str:
                state = self._load_state()
                if date_str in state:
                    del state[date_str]
                    self._save_state(state)
            else:
                self._save_state({})

    def record_tracking_start(self, timestamp: datetime | None = None) -> dict:
        """
        Record the start of tracking for today and capture system boot time.
        
        If tracking already started for today's boot, the initial start time is preserved.
        """
        with self._state_lock:
            now_local = (timestamp or datetime.now()).astimezone()
            date_key = now_local.strftime("%Y-%m-%d")
            boot_dt = _get_boot_datetime()
            boot_str = _format_dt(boot_dt)
            now_str = _format_dt(now_local)

            state = self._load_state()
            day_data = state.get(date_key, {})

            # Set system boot time if not already present
            if not day_data.get("system_started_at"):
                day_data["system_started_at"] = boot_str

            # Preserve the initial tracking_started_at time across application restarts
            if not day_data.get("tracking_started_at"):
                day_data["tracking_started_at"] = now_str

            day_data["date"] = date_key
            day_data["hostname"] = socket.gethostname()
            if "punch_in" not in day_data:
                day_data["punch_in"] = None
            if "punch_out" not in day_data:
                day_data["punch_out"] = None

            state[date_key] = day_data
            self._save_state(state)

            logger.info(
                "Attendance recorded: date=%s system_started_at=%s tracking_started_at=%s punch_in=%s punch_out=%s",
                date_key,
                day_data["system_started_at"],
                day_data["tracking_started_at"],
                day_data.get("punch_in"),
                day_data.get("punch_out"),
            )
            return dict(day_data)

    def record_punch_in(self, punch_time: datetime | str | None = None, date_str: str | None = None) -> dict:
        """Record or update Punch-In timestamp for a given date (defaults to today)."""
        with self._state_lock:
            now_local = datetime.now().astimezone()
            date_key = date_str or now_local.strftime("%Y-%m-%d")

            if isinstance(punch_time, datetime):
                p_str = _format_dt(punch_time.astimezone())
            elif isinstance(punch_time, str):
                p_str = punch_time.strip()
            else:
                p_str = _format_dt(now_local)

            state = self._load_state()
            day_data = state.get(date_key, {})
            day_data["date"] = date_key
            day_data["hostname"] = socket.gethostname()
            if not day_data.get("system_started_at"):
                day_data["system_started_at"] = _format_dt(_get_boot_datetime())
            if not day_data.get("tracking_started_at"):
                day_data["tracking_started_at"] = _format_dt(now_local)

            day_data["punch_in"] = p_str
            if "punch_out" not in day_data:
                day_data["punch_out"] = None

            state[date_key] = day_data
            self._save_state(state)
            logger.info("Recorded Punch-In for %s: %s", date_key, p_str)
            return dict(day_data)

    def record_punch_out(self, punch_time: datetime | str | None = None, date_str: str | None = None) -> dict:
        """Record or update Punch-Out timestamp for a given date (defaults to today)."""
        with self._state_lock:
            now_local = datetime.now().astimezone()
            date_key = date_str or now_local.strftime("%Y-%m-%d")

            if isinstance(punch_time, datetime):
                p_str = _format_dt(punch_time.astimezone())
            elif isinstance(punch_time, str):
                p_str = punch_time.strip()
            else:
                p_str = _format_dt(now_local)

            state = self._load_state()
            day_data = state.get(date_key, {})
            day_data["date"] = date_key
            day_data["hostname"] = socket.gethostname()
            if not day_data.get("system_started_at"):
                day_data["system_started_at"] = _format_dt(_get_boot_datetime())
            if not day_data.get("tracking_started_at"):
                day_data["tracking_started_at"] = _format_dt(now_local)

            day_data["punch_out"] = p_str

            state[date_key] = day_data
            self._save_state(state)
            logger.info("Recorded Punch-Out for %s: %s", date_key, p_str)
            return dict(day_data)

    def _normalize_punch_time_str(self, time_val: Any, date_key: str) -> str | None:
        """Normalize various punch time formats into YYYY-MM-DD HH:MM:SS format."""
        if not time_val:
            return None
        time_str = str(time_val).strip()
        if not time_str or time_str.lower() in ("null", "none", "00:00:00", "-"):
            return None

        # If already full date-time string YYYY-MM-DD HH:MM:SS
        if len(time_str) >= 19 and time_str[4] == "-" and time_str[7] == "-":
            return time_str[:19]

        # If format is DD-MM-YYYY HH:MM:SS or DD/MM/YYYY HH:MM:SS
        if len(time_str) >= 19 and (time_str[2] in ("-", "/") and time_str[5] in ("-", "/")):
            try:
                sep = time_str[2]
                dt = datetime.strptime(time_str[:19], f"%d{sep}%m{sep}%Y %H:%M:%S")
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass

        # If only time string HH:MM:SS or HH:MM
        if ":" in time_str:
            parts = time_str.split(":")
            if len(parts) == 2:
                time_str = f"{time_str}:00"
            elif len(parts) >= 3:
                time_str = ":".join(parts[:3])
            # If 12-hour AM/PM is present
            if "am" in time_str.lower() or "pm" in time_str.lower():
                try:
                    dt = datetime.strptime(time_str, "%I:%M:%S %p" if len(parts) >= 3 else "%I:%M %p")
                    time_str = dt.strftime("%H:%M:%S")
                except Exception:
                    pass
            return f"{date_key} {time_str}"

        return time_str

    def fetch_punch_time(
        self,
        punch_date: str | datetime | None = None,
        indo_code: str | None = None,
        key: str | None = None,
        force: bool = False,
    ) -> dict | None:
        """
        Fetch Punch-In and Punch-Out times from the dynamic Punch API:
        Endpoint: Punch/get_punch_time
        Parameters:
          - indo_code: employee/indo code (e.g. 'EC-098')
          - key: API key (e.g. 'testapikey111')
          - punch_date: date in 'DD-MM-YYYY' format (e.g. '22-05-2025')
        
        This method is rate-limited and offline-resilient to avoid unnecessary polling.
        """
        import requests
        import time

        now_local = datetime.now().astimezone()

        # 1. Resolve date strings
        if isinstance(punch_date, datetime):
            date_key = punch_date.strftime("%Y-%m-%d")
            punch_date_api_str = punch_date.strftime("%d-%m-%Y")
        elif isinstance(punch_date, str) and punch_date.strip():
            raw_d = punch_date.strip()
            # If input is YYYY-MM-DD
            if len(raw_d) == 10 and raw_d[4] == "-" and raw_d[7] == "-":
                date_key = raw_d
                dt = datetime.strptime(raw_d, "%Y-%m-%d")
                punch_date_api_str = dt.strftime("%d-%m-%Y")
            # If input is DD-MM-YYYY or DD/MM/YYYY
            elif len(raw_d) == 10 and (raw_d[2] in ("-", "/") and raw_d[5] in ("-", "/")):
                sep = raw_d[2]
                dt = datetime.strptime(raw_d, f"%d{sep}%m{sep}%Y")
                date_key = dt.strftime("%Y-%m-%d")
                punch_date_api_str = dt.strftime("%d-%m-%Y")
            else:
                date_key = now_local.strftime("%Y-%m-%d")
                punch_date_api_str = now_local.strftime("%d-%m-%Y")
        else:
            date_key = now_local.strftime("%Y-%m-%d")
            punch_date_api_str = now_local.strftime("%d-%m-%Y")

        # 2. Check rate limit / cooldown (unless force is True)
        if not hasattr(self, "_last_punch_fetch_ts"):
            self._last_punch_fetch_ts = {}

        last_fetch = self._last_punch_fetch_ts.get(date_key, 0.0)
        current_ts = time.time()

        with self._state_lock:
            state = self._load_state()
            day_data = state.get(date_key, {})
            has_both_punches = bool(day_data.get("punch_in") and day_data.get("punch_out"))

        # If both punches are already recorded for this day, limit checks to once every hour
        if not force:
            if has_both_punches and (current_ts - last_fetch < 3600):
                return day_data
            # Cooldown of 3 minutes between checks to prevent continuous polling
            if current_ts - last_fetch < 180:
                return day_data

        # 3. Resolve indo_code and key
        resolved_indo_code = indo_code
        if not resolved_indo_code:
            try:
                from services.session_service import SessionService
                u = SessionService().current_user
                if u:
                    resolved_indo_code = u.indo_code or u.employee_id or u.username
            except Exception:
                pass

        if not resolved_indo_code:
            try:
                from services.secure_session import SessionStore
                s = SessionStore().load_session()
                if s:
                    resolved_indo_code = s.get("indo_code") or s.get("employee_id") or s.get("username")
            except Exception:
                pass

        if not resolved_indo_code:
            try:
                from PySide6.QtCore import QSettings
                st = QSettings("Indovision", "iHRMSMonitor")
                resolved_indo_code = st.value("last_employee_id") or None
            except Exception:
                pass

        if not resolved_indo_code:
            logger.debug("Punch API: No indo_code / employee_id available; skipping punch fetch.")
            return None

        resolved_key = key or os.environ.get("IHRMS_PUNCH_API_KEY")
        if not resolved_key:
            try:
                from services.session_service import SessionService
                u = SessionService().current_user
                if u and u.api_key:
                    resolved_key = u.api_key
            except Exception:
                pass

        if not resolved_key:
            try:
                from services.secure_session import SessionStore
                s = SessionStore().load_session()
                if s and s.get("api_key"):
                    resolved_key = s.get("api_key")
            except Exception:
                pass

        if not resolved_key:
            resolved_key = "testapikey111"

        # 4. Resolve Punch endpoint URL
        try:
            from config.api_config import ApiConfig
            punch_url = ApiConfig().punch_url
        except Exception:
            punch_url = os.environ.get("IHRMS_PUNCH_API_URL")

        if not punch_url:
            logger.debug("Punch API: endpoint URL not available; skipping.")
            return None

        # 5. Call Punch API
        self._last_punch_fetch_ts[date_key] = current_ts
        req_payload = {
            "indo_code": str(resolved_indo_code),
            "key": str(resolved_key),
            "punch_date": str(punch_date_api_str),
        }

        logger.info(
            "Calling Punch API: url=%s data=%s",
            punch_url,
            {"indo_code": resolved_indo_code, "key": "***", "punch_date": punch_date_api_str},
        )

        try:
            resp = requests.post(punch_url, data=req_payload, timeout=10)
            logger.info("Punch API response: HTTP %d %s", resp.status_code, resp.text[:200])
            resp.raise_for_status()
            res_json = resp.json()
        except Exception as api_err:
            logger.warning("Punch API call failed gracefully: %s", api_err)
            return None

        # 6. Parse punch times from response
        # Expected response schema:
        # {
        #   "response": 200,
        #   "status": 1,
        #   "message": "Data found",
        #   "punch_date": "22-05-2025",
        #   "punch_in_time": "10:36:42",
        #   "punch_out_time": "14:39:41"
        # }
        punch_in_val = None
        punch_out_val = None

        if isinstance(res_json, dict):
            # Check top-level keys first (primary format from /punch/get_punch_time)
            punch_in_val = (
                res_json.get("punch_in_time")
                or res_json.get("punch_in")
                or res_json.get("in_time")
            )
            punch_out_val = (
                res_json.get("punch_out_time")
                or res_json.get("punch_out")
                or res_json.get("out_time")
            )

            # Check nested data object if present
            data_obj = res_json.get("data")
            if isinstance(data_obj, dict):
                if not punch_in_val:
                    punch_in_val = (
                        data_obj.get("punch_in_time")
                        or data_obj.get("punch_in")
                        or data_obj.get("in_time")
                        or data_obj.get("first_in")
                        or data_obj.get("first_punch")
                    )
                if not punch_out_val:
                    punch_out_val = (
                        data_obj.get("punch_out_time")
                        or data_obj.get("punch_out")
                        or data_obj.get("out_time")
                        or data_obj.get("last_out")
                        or data_obj.get("last_punch")
                    )
            elif isinstance(data_obj, list) and data_obj:
                # Array of punch logs
                times = []
                for item in data_obj:
                    if isinstance(item, dict):
                        t = item.get("punch_time") or item.get("in_time") or item.get("out_time") or item.get("time") or item.get("punch_in_time") or item.get("punch_out_time")
                        if t:
                            times.append(str(t))
                    elif isinstance(item, str):
                        times.append(item)
                if times:
                    if not punch_in_val:
                        punch_in_val = times[0]
                    if not punch_out_val and len(times) > 1:
                        punch_out_val = times[-1]

        norm_punch_in = self._normalize_punch_time_str(punch_in_val, date_key)
        norm_punch_out = self._normalize_punch_time_str(punch_out_val, date_key)

        if norm_punch_in:
            self.record_punch_in(norm_punch_in, date_str=date_key)
        if norm_punch_out:
            self.record_punch_out(norm_punch_out, date_str=date_key)

        return self.get_daily_attendance(date_key)

    def get_daily_attendance(self, date_str: str | None = None) -> dict:
        """
        Get attendance context (system_started_at, tracking_started_at, punch_in, punch_out).
        
        Guarantees that system_started_at and tracking_started_at are always populated
        even if tracking start was not explicitly invoked yet or Punch was never performed.
        """
        with self._state_lock:
            now_local = datetime.now().astimezone()
            date_key = date_str or now_local.strftime("%Y-%m-%d")
            state = self._load_state()
            day_data = state.get(date_key)

            if not day_data:
                # Auto-initialize on demand
                boot_str = _format_dt(_get_boot_datetime())
                now_str = _format_dt(now_local)
                day_data = {
                    "date": date_key,
                    "hostname": socket.gethostname(),
                    "system_started_at": boot_str,
                    "tracking_started_at": now_str,
                    "punch_in": None,
                    "punch_out": None,
                }
                state[date_key] = day_data
                self._save_state(state)

            return {
                "date": day_data.get("date", date_key),
                "hostname": day_data.get("hostname", socket.gethostname()),
                "system_started_at": day_data.get("system_started_at") or _format_dt(_get_boot_datetime()),
                "tracking_started_at": day_data.get("tracking_started_at") or _format_dt(now_local),
                "punch_in": day_data.get("punch_in"),
                "punch_out": day_data.get("punch_out"),
            }

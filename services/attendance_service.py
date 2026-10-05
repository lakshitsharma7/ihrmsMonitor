"""Attendance and System Start workpulse service for iHRMS Monitor.

Tracks:
1. Daily Windows/System boot time (system_started_at) via psutil.boot_time().
2. Daily iHRMS Monitor workpulse start time (workpulse_started_at).
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


from utils.paths import get_data_directory


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
    """Singleton service for daily system start, workpulse start, and punch workpulse."""

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
        try:
            data_dir = get_data_directory()
        except Exception:
            local_app_data = os.environ.get("LOCALAPPDATA", "")
            if local_app_data:
                data_dir = Path(local_app_data) / "Workpulse" / "data"
            else:
                data_dir = Path.home() / ".workpulse" / "data"
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        target_file = data_dir / "attendance_state.json"
        if not target_file.exists():
            local_app_data = os.environ.get("LOCALAPPDATA", "")
            if local_app_data:
                legacy_file = Path(local_app_data) / "iHRMS Monitor" / "data" / "attendance_state.json"
                if legacy_file.exists():
                    try:
                        import shutil
                        shutil.copy2(legacy_file, target_file)
                    except Exception:
                        pass
        return target_file

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

    def record_workpulse_start(self, timestamp: datetime | None = None) -> dict:
        """
        Record the start of workpulse for today and capture system boot time.
        
        If workpulse already started for today's boot, the initial start time is preserved.
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

            # Preserve the initial workpulse_started_at time across application restarts
            if not day_data.get("workpulse_started_at"):
                day_data["workpulse_started_at"] = now_str

            day_data["date"] = date_key
            day_data["hostname"] = socket.gethostname()
            if "punch_in" not in day_data:
                day_data["punch_in"] = None
            if "punch_out" not in day_data:
                day_data["punch_out"] = None

            state[date_key] = day_data
            self._save_state(state)

            logger.info(
                "Attendance recorded: date=%s system_started_at=%s workpulse_started_at=%s punch_in=%s punch_out=%s",
                date_key,
                day_data["system_started_at"],
                day_data["workpulse_started_at"],
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
            if not day_data.get("workpulse_started_at"):
                day_data["workpulse_started_at"] = _format_dt(now_local)

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
            if not day_data.get("workpulse_started_at"):
                day_data["workpulse_started_at"] = _format_dt(now_local)

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
        Get attendance context (system_started_at, workpulse_started_at, punch_in, punch_out).
        
        Guarantees that system_started_at and workpulse_started_at are always populated
        even if workpulse start was not explicitly invoked yet or Punch was never performed.
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
                    "workpulse_started_at": now_str,
                    "punch_in": None,
                    "punch_out": None,
                }
                state[date_key] = day_data
                self._save_state(state)

            return {
                "date": day_data.get("date", date_key),
                "hostname": day_data.get("hostname", socket.gethostname()),
                "system_started_at": day_data.get("system_started_at") or _format_dt(_get_boot_datetime()),
                "workpulse_started_at": day_data.get("workpulse_started_at") or _format_dt(now_local),
                "punch_in": day_data.get("punch_in"),
                "punch_out": day_data.get("punch_out"),
            }

    def get_monthly_attendance_record(
        self,
        month: str | int | None = None,
        year: int | str | None = None,
        indo_code: str | None = None,
        key: str | None = None,
        force: bool = False,
    ) -> dict:
        """
        Fetch monthly attendance records from the dynamic Attendance API:
        Endpoint: attendance/get_attendance_record
        Parameters:
          - indo_code: employee / indo code (e.g. 'EC-100')
          - key: API key (e.g. 'testapikey111')
          - month: full month name (e.g. 'September')
          - year: 4-digit year (e.g. 2025 or '2025')
        
        Returns a structured dictionary with:
          - response: int
          - status: int
          - month: str
          - year: int
          - days: list of daily attendance dicts (date, day_num, day_name, status, status_label, color)
          - summary: {present, absent, week_off, leave, holiday, total_days}
          - freezed: bool
          - raw_result: dict
          - error: str | None
        """
        import calendar
        import requests
        import time

        now = datetime.now()

        # 1. Resolve Month and Year
        month_names = [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December"
        ]
        short_month_map = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
            "sept": 9
        }
        full_month_map = {m.lower(): i + 1 for i, m in enumerate(month_names)}

        if isinstance(month, int):
            if 1 <= month <= 12:
                resolved_month_num = month
                resolved_month_name = month_names[month - 1]
            elif month == 0:
                resolved_month_num = 1
                resolved_month_name = month_names[0]
            else:
                resolved_month_num = now.month
                resolved_month_name = month_names[now.month - 1]
        elif isinstance(month, str) and month.strip():
            m_clean = month.strip().lower()
            if m_clean in full_month_map:
                resolved_month_num = full_month_map[m_clean]
                resolved_month_name = month_names[resolved_month_num - 1]
            elif m_clean[:3] in short_month_map:
                resolved_month_num = short_month_map[m_clean[:3]]
                resolved_month_name = month_names[resolved_month_num - 1]
            else:
                try:
                    m_int = int(m_clean)
                    if 1 <= m_int <= 12:
                        resolved_month_num = m_int
                        resolved_month_name = month_names[m_int - 1]
                    elif m_int == 0:
                        resolved_month_num = 1
                        resolved_month_name = month_names[0]
                    else:
                        resolved_month_num = now.month
                        resolved_month_name = month_names[now.month - 1]
                except ValueError:
                    resolved_month_num = now.month
                    resolved_month_name = month_names[now.month - 1]
        else:
            resolved_month_num = now.month
            resolved_month_name = month_names[now.month - 1]

        if year is not None:
            try:
                resolved_year = int(str(year).strip())
            except ValueError:
                resolved_year = now.year
        else:
            resolved_year = now.year

        # 2. Resolve indo_code and key from active session context
        resolved_indo = indo_code
        if not resolved_indo:
            try:
                from services.session_service import SessionService
                u = SessionService().current_user
                if u:
                    resolved_indo = u.indo_code or u.employee_id or u.username
            except Exception:
                pass

        if not resolved_indo:
            try:
                from services.secure_session import SessionStore
                s = SessionStore().load_session()
                if s:
                    resolved_indo = s.get("indo_code") or s.get("employee_id") or s.get("username")
            except Exception:
                pass

        if not resolved_indo:
            try:
                st = QSettings("Indovision", "iHRMSMonitor")
                resolved_indo = st.value("last_employee_id") or None
            except Exception:
                pass

        if not resolved_indo:
            resolved_indo = "EC-100"

        resolved_key = key or os.environ.get("IHRMS_ATTENDANCE_API_KEY")
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

        # 3. Check Cache
        if not hasattr(self, "_monthly_cache"):
            self._monthly_cache = {}
            self._monthly_cache_ts = {}

        cache_key = f"{resolved_indo}_{resolved_month_name}_{resolved_year}"
        now_ts = time.time()
        if not force and cache_key in self._monthly_cache:
            if now_ts - self._monthly_cache_ts.get(cache_key, 0) < 300: # 5 min cache
                return self._monthly_cache[cache_key]

        # 4. Resolve URL
        try:
            from config.api_config import ApiConfig
            att_url = ApiConfig().get_attendance_record_url
        except Exception:
            att_url = os.environ.get("IHRMS_GET_ATTENDANCE_RECORD_API_URL")

        if not att_url:
            att_url = "https://softdev.indovisionservices.in/ihrms84/hrms_api/ci4/api/attendance/get_attendance_record"

        req_payload = {
            "indo_code": str(resolved_indo),
            "key": str(resolved_key),
            "month": str(resolved_month_name),
            "year": str(resolved_year),
        }

        logger.info(
            "Calling Attendance Record API: url=%s data=%s",
            att_url,
            {"indo_code": resolved_indo, "key": "***", "month": resolved_month_name, "year": resolved_year},
        )

        res_json = None
        error_msg = None
        try:
            resp = requests.post(att_url, data=req_payload, timeout=12)
            logger.info("Attendance Record API response: HTTP %d (size: %d bytes)", resp.status_code, len(resp.content))
            resp.raise_for_status()
            res_json = resp.json()
        except Exception as api_err:
            logger.warning("Attendance Record API call failed: %s", api_err)
            error_msg = str(api_err)

        if not res_json or not isinstance(res_json, dict):
            # Fallback structure on error
            fallback_res = {
                "response": 500 if error_msg else 400,
                "status": 0,
                "month": resolved_month_name,
                "year": resolved_year,
                "days": [],
                "summary": {
                    "present": 0,
                    "absent": 0,
                    "week_off": 0,
                    "leave": 0,
                    "holiday": 0,
                    "total_days": 0,
                },
                "freezed": False,
                "raw_result": {},
                "error": error_msg or "Unable to load attendance data.",
            }
            return fallback_res

        # 5. Parse Days
        result = res_json.get("result", {})
        if not isinstance(result, dict):
            result = {}

        # 5. Parse Days and Build Lookup Tables
        result = res_json.get("result", {})
        if not isinstance(result, dict):
            result = {}

        def _is_valid_punch_time(val: Any) -> bool:
            """Check if a value contains a valid, non-empty punch timestamp."""
            if val is None:
                return False
            if isinstance(val, (dict, list)) and not val:
                return False
            s = str(val).strip()
            if not s or s.lower() in ("none", "null", "undefined", "-", "--", "--:--", "00:00:00", "00:00", "0:00:00", "0:00", "0", "false", "{}", "[]", "n/a", "na"):
                return False
            return any(c.isdigit() for c in s)

        def _clean_time_str(val: Any) -> str | None:
            """Clean and format timestamp string into concise time component."""
            if not _is_valid_punch_time(val):
                return None
            s = str(val).strip()
            if " " in s:
                parts = s.split(" ", 1)
                if len(parts) == 2 and any(c.isdigit() for c in parts[1]):
                    s = parts[1].strip()
            if "T" in s:
                parts = s.split("T", 1)
                if len(parts) == 2 and any(c.isdigit() for c in parts[1]):
                    s = parts[1].strip()
            return s if _is_valid_punch_time(s) else None

        def _normalize_date_key(raw_val: Any, target_year: int, target_month: int) -> str | None:
            """Normalize various date formats (DD-MM-YYYY, YYYY-MM-DD, DD/MM/YYYY, named months, day num) into 'YYYY-MM-DD'."""
            if raw_val is None:
                return None
            s = str(raw_val).strip()
            if not s or s.lower() in ("none", "null", "undefined", "-", "--", "n/a", "na", "{}", "[]"):
                return None

            # Strip time component if separated by space or T
            if " " in s:
                s = s.split(" ")[0].strip()
            if "T" in s:
                s = s.split("T")[0].strip()

            import re

            # Pattern 1: YYYY-MM-DD or YYYY/MM/DD (1 or 2 digits for month/day)
            m1 = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", s)
            if m1:
                y, mo, d = int(m1.group(1)), int(m1.group(2)), int(m1.group(3))
                if 1 <= mo <= 12 and 1 <= d <= 31:
                    return f"{y:04d}-{mo:02d}-{d:02d}"

            # Pattern 2: DD-MM-YYYY or DD/MM/YYYY (1 or 2 digits for day/month)
            m2 = re.match(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$", s)
            if m2:
                d, mo, y = int(m2.group(1)), int(m2.group(2)), int(m2.group(3))
                if 1 <= mo <= 12 and 1 <= d <= 31:
                    return f"{y:04d}-{mo:02d}-{d:02d}"

            # Pattern 3: DD-Mon-YYYY, DD Mon YYYY, DD-Month-YYYY (e.g. 15-Aug-2025, 01-August-2025)
            m3 = re.match(r"^(\d{1,2})[-/\s]([a-zA-Z]+)[-/\s](\d{4})$", s)
            if m3:
                d, mon_str, y = int(m3.group(1)), m3.group(2).lower(), int(m3.group(3))
                mo = short_month_map.get(mon_str[:3]) or full_month_map.get(mon_str)
                if mo and 1 <= d <= 31:
                    return f"{y:04d}-{mo:02d}-{d:02d}"

            # Pattern 4: Pure day number (1..31 or '01'..'31')
            m4 = re.match(r"^\d{1,2}$", s)
            if m4:
                d = int(s)
                if 1 <= d <= 31:
                    return f"{target_year:04d}-{target_month:02d}-{d:02d}"

            return None

        def _extract_punch_and_details(
            val: Any,
            date_str: str,
            local_punch: dict | None = None,
            api_punch: Any = None,
        ) -> tuple[str | None, str | None, list[str]]:
            """Extract clean punch display string, details line, and raw punch times list from API and local store."""
            punches: list[str] = []
            working_hrs: str | None = None

            def _inspect_dict(d: dict) -> None:
                nonlocal punches, working_hrs
                if not isinstance(d, dict):
                    return

                # 1. Direct punch in / out fields
                p_in = (
                    d.get("punch_in")
                    or d.get("punchIn")
                    or d.get("punch_in_time")
                    or d.get("punchInTime")
                    or d.get("in_time")
                    or d.get("inTime")
                    or d.get("first_punch")
                    or d.get("firstPunch")
                    or d.get("first_in")
                    or d.get("firstIn")
                    or d.get("check_in")
                    or d.get("checkIn")
                    or d.get("start_time")
                    or d.get("startTime")
                    or d.get("sign_in")
                    or d.get("signIn")
                    or d.get("login_time")
                    or d.get("loginTime")
                    or d.get("time_in")
                    or d.get("timeIn")
                    or d.get("in")
                )
                p_out = (
                    d.get("punch_out")
                    or d.get("punchOut")
                    or d.get("punch_out_time")
                    or d.get("punchOutTime")
                    or d.get("out_time")
                    or d.get("outTime")
                    or d.get("last_punch")
                    or d.get("lastPunch")
                    or d.get("last_out")
                    or d.get("lastOut")
                    or d.get("check_out")
                    or d.get("checkOut")
                    or d.get("end_time")
                    or d.get("endTime")
                    or d.get("sign_out")
                    or d.get("signOut")
                    or d.get("logout_time")
                    or d.get("logoutTime")
                    or d.get("time_out")
                    or d.get("timeOut")
                    or d.get("out")
                )

                c_in = _clean_time_str(p_in)
                c_out = _clean_time_str(p_out)
                if c_in and c_in not in punches:
                    punches.append(c_in)
                if c_out and c_out != c_in and c_out not in punches:
                    punches.append(c_out)

                # 2. punch_time / punchTime / punch / punches / attendance_time
                p_time = (
                    d.get("punchTime")
                    or d.get("punch_time")
                    or d.get("punch_times")
                    or d.get("punchTimes")
                    or d.get("punch")
                    or d.get("punches")
                    or d.get("attendance_time")
                    or d.get("attendanceTime")
                    or d.get("time")
                    or d.get("times")
                    or d.get("clock_in")
                    or d.get("clock_out")
                )
                if isinstance(p_time, list):
                    for item in p_time:
                        c = _clean_time_str(item)
                        if c and c not in punches:
                            punches.append(c)
                elif isinstance(p_time, str) and _is_valid_punch_time(p_time):
                    if "," in p_time:
                        parts = [_clean_time_str(p) for p in p_time.split(",") if _is_valid_punch_time(p)]
                        punches = [p for p in parts if p]
                    elif " - " in p_time:
                        parts = [_clean_time_str(p) for p in p_time.split(" - ") if _is_valid_punch_time(p)]
                        punches = [p for p in parts if p]
                    elif not punches:
                        c = _clean_time_str(p_time)
                        if c:
                            punches.append(c)

                # 3. working hours
                w_hrs = d.get("working_hours") or d.get("work_duration") or d.get("hours") or d.get("total_hours") or d.get("work_hours")
                if _is_valid_punch_time(w_hrs) and not working_hrs:
                    working_hrs = str(w_hrs).strip()

            if isinstance(val, dict):
                _inspect_dict(val)
            elif isinstance(val, str) and _is_valid_punch_time(val):
                if "," in val:
                    parts = [_clean_time_str(p) for p in val.split(",") if _is_valid_punch_time(p)]
                    punches = [p for p in parts if p]
                elif " - " in val:
                    parts = [_clean_time_str(p) for p in val.split(" - ") if _is_valid_punch_time(p)]
                    punches = [p for p in parts if p]
                elif not punches:
                    c = _clean_time_str(val)
                    if c:
                        punches.append(c)

            # Inspect separate API punch record if present for this date
            if isinstance(api_punch, dict):
                _inspect_dict(api_punch)
            elif isinstance(api_punch, str) and _is_valid_punch_time(api_punch):
                c = _clean_time_str(api_punch)
                if c and c not in punches:
                    punches.append(c)

            # 4. Merge local store punch if available for date
            if local_punch and isinstance(local_punch, dict):
                l_in = _clean_time_str(local_punch.get("punch_in"))
                l_out = _clean_time_str(local_punch.get("punch_out"))
                if l_in and l_in not in punches:
                    punches.insert(0, l_in)
                if l_out and l_out not in punches:
                    punches.append(l_out)

            # Build punch display string
            punch_display: str | None = None
            if len(punches) == 2:
                if punches[0] == punches[1]:
                    punch_display = f"Punch: {punches[0]}, {punches[1]}"
                else:
                    punch_display = f"Punch: {punches[0]} - {punches[1]}"
            elif len(punches) == 1:
                punch_display = f"Punch: {punches[0]}"
            elif len(punches) > 2:
                punch_display = f"Punch: {', '.join(punches)}"

            # Detail parts
            detail_parts = []
            if punch_display:
                detail_parts.append(punch_display)
            if working_hrs:
                detail_parts.append(f"Hrs: {working_hrs}")

            details_str = " | ".join(detail_parts) if detail_parts else None
            return punch_display, details_str, punches

        def _collect_items(raw_val: Any) -> list:
            """Ensure dictionary or list collection is returned as list of items."""
            if raw_val is None:
                return []
            if isinstance(raw_val, list):
                return raw_val
            if isinstance(raw_val, dict):
                items = []
                for k, v in raw_val.items():
                    if isinstance(v, dict):
                        if not (v.get("date") or v.get("lastUpdate") or v.get("punch_date")):
                            v_copy = dict(v)
                            v_copy["date"] = k
                            items.append(v_copy)
                        else:
                            items.append(v)
                    elif isinstance(v, (str, int, float, bool)):
                        items.append({"date": k, "name": str(v), "status": str(v)})
                    else:
                        items.append(v)
                return items
            return []

        # Holidays
        holiday_days = _collect_items(result.get("holiday_days") or result.get("holidays"))
        holiday_map = {}
        for h in holiday_days:
            if isinstance(h, dict) and (h.get("date") or h.get("holiday_date") or h.get("day")):
                raw_d = h.get("date") or h.get("holiday_date") or h.get("day")
                k = _normalize_date_key(raw_d, resolved_year, resolved_month_num)
                if k:
                    holiday_map[k] = h.get("name") or h.get("holiday_name") or h.get("title") or "Holiday"
            elif isinstance(h, str):
                k = _normalize_date_key(h, resolved_year, resolved_month_num)
                if k:
                    holiday_map[k] = "Holiday"

        # Weekoffs
        weekoff_days = _collect_items(result.get("weekoff") or result.get("weekoffs") or result.get("week_offs"))
        weekoff_set = set()
        for w in weekoff_days:
            if isinstance(w, dict) and (w.get("date") or w.get("day")):
                k = _normalize_date_key(w.get("date") or w.get("day"), resolved_year, resolved_month_num)
                if k:
                    weekoff_set.add(k)
            elif isinstance(w, str):
                k = _normalize_date_key(w, resolved_year, resolved_month_num)
                if k:
                    weekoff_set.add(k)

        # Leaves
        leave_days = _collect_items(
            result.get("leave_days")
            or result.get("leaves")
            or result.get("leave_records")
            or result.get("leave_list")
            or result.get("leaves_list")
            or result.get("applied_leaves")
            or result.get("leave_data")
            or result.get("leave")
        )
        leave_set = set()
        leave_name_map = {}
        for l in leave_days:
            if isinstance(l, dict):
                raw_d = l.get("date") or l.get("leave_date") or l.get("day") or l.get("from_date") or l.get("lastUpdate")
                k = _normalize_date_key(raw_d, resolved_year, resolved_month_num)
                if k:
                    leave_set.add(k)
                    leave_name_map[k] = l.get("leave_type") or l.get("name") or l.get("status") or "Leave"
            elif isinstance(l, str):
                k = _normalize_date_key(l, resolved_year, resolved_month_num)
                if k:
                    leave_set.add(k)
                    leave_name_map[k] = "Leave"

        # Comp Offs
        comp_off_days = _collect_items(result.get("comp_off_days") or result.get("comp_offs") or result.get("compoffs"))
        comp_off_set = set()
        for c in comp_off_days:
            if isinstance(c, dict) and (c.get("date") or c.get("day")):
                k = _normalize_date_key(c.get("date") or c.get("day"), resolved_year, resolved_month_num)
                if k:
                    comp_off_set.add(k)
            elif isinstance(c, str):
                k = _normalize_date_key(c, resolved_year, resolved_month_num)
                if k:
                    comp_off_set.add(k)

        # Missed Punch Days (mispunch_days / missed_punch / mispunch / etc.)
        mispunch_days = _collect_items(
            result.get("mispunch_days")
            or result.get("mispunch")
            or result.get("mis_punch")
            or result.get("mis_punches")
            or result.get("missed_punch")
            or result.get("missed_punches")
            or result.get("mispunches")
        )
        mispunch_set = set()
        for mp in mispunch_days:
            if isinstance(mp, dict) and (mp.get("date") or mp.get("lastUpdate") or mp.get("day")):
                k = _normalize_date_key(mp.get("date") or mp.get("lastUpdate") or mp.get("day"), resolved_year, resolved_month_num)
                if k:
                    mispunch_set.add(k)
            elif isinstance(mp, str):
                k = _normalize_date_key(mp, resolved_year, resolved_month_num)
                if k:
                    mispunch_set.add(k)

        # Separate Punch Records collection (punches, punch_data, punch_records, etc.)
        punches_raw = (
            result.get("punches")
            or result.get("punch_records")
            or result.get("punch_data")
            or result.get("punch_list")
            or result.get("daily_punches")
            or result.get("in_out_details")
            or result.get("punch_times")
            or result.get("punches_list")
            or result.get("raw_punches")
        )
        punches_list = _collect_items(punches_raw)
        punches_by_date: dict[str, Any] = {}
        for p in punches_list:
            if isinstance(p, dict):
                raw_d = (
                    p.get("date")
                    or p.get("lastUpdate")
                    or p.get("punch_date")
                    or p.get("attendance_date")
                    or p.get("att_date")
                    or p.get("AttDate")
                    or p.get("punchDate")
                    or p.get("attendanceDate")
                    or p.get("in_date")
                    or p.get("in_time")
                    or p.get("punch_in")
                    or p.get("punchIn")
                    or p.get("punch_time")
                    or p.get("punchTime")
                    or p.get("datetime")
                    or p.get("day")
                    or p.get("day_num")
                )
                k = _normalize_date_key(raw_d, resolved_year, resolved_month_num)
                if k:
                    punches_by_date[k] = p
            elif isinstance(p, str):
                k = _normalize_date_key(p, resolved_year, resolved_month_num)
                if k:
                    punches_by_date[k] = p

        # Present / Attendance Records Normalization (By Date vs By Month Array)
        present_days_raw = (
            result.get("present_days")
            or result.get("attendance_records")
            or result.get("attendance")
            or result.get("records")
            or result.get("data")
            or result.get("punch_data")
            or result.get("punch_list")
            or result.get("details")
        )
        if present_days_raw is None and isinstance(result, list):
            present_days_raw = result

        present_days_list = _collect_items(present_days_raw)

        present_days_by_date: dict[str, Any] = {}
        is_full_month_status_array = False

        if present_days_list:
            all_simple = all(
                isinstance(item, str) and item.strip().upper() in (
                    "P", "PRESENT", "A", "ABSENT", "EL", "CL", "SL", "PL", "ML",
                    "WEEK OFF", "WO", "W/O", "HOLIDAY", "H", "HD", "HALF DAY", "LATE", "L", "COMP OFF", "CO", "MP", "MISSED PUNCH", "-"
                )
                for item in present_days_list if item is not None and str(item).strip()
            )
            if all_simple and len(present_days_list) > 10:
                is_full_month_status_array = True
            else:
                for idx, item in enumerate(present_days_list):
                    if item is None:
                        continue
                    if isinstance(item, dict):
                        raw_d = (
                            item.get("date")
                            or item.get("lastUpdate")
                            or item.get("punch_date")
                            or item.get("attendance_date")
                            or item.get("att_date")
                            or item.get("AttDate")
                            or item.get("punchDate")
                            or item.get("attendanceDate")
                            or item.get("in_date")
                            or item.get("punch_in")
                            or item.get("punchIn")
                            or item.get("in_time")
                            or item.get("punch_time")
                            or item.get("punchTime")
                            or item.get("datetime")
                            or item.get("dateTime")
                            or item.get("date_time")
                            or item.get("punch_datetime")
                            or item.get("created_at")
                            or item.get("updated_at")
                            or item.get("day")
                            or item.get("day_num")
                            or item.get("day_no")
                        )
                        d_key = _normalize_date_key(raw_d, resolved_year, resolved_month_num)
                        if d_key:
                            present_days_by_date[d_key] = item
                        else:
                            d_key = f"{resolved_year:04d}-{resolved_month_num:02d}-{(idx + 1):02d}"
                            present_days_by_date[d_key] = item
                    elif isinstance(item, str):
                        d_key = _normalize_date_key(item, resolved_year, resolved_month_num)
                        if d_key:
                            present_days_by_date[d_key] = {"date": d_key, "status": "P"}
                        elif item.strip().upper() in ("P", "PRESENT", "A", "ABSENT", "EL", "CL", "SL", "PL", "ML", "WEEK OFF", "WO", "HOLIDAY", "H", "HD", "LATE", "MP", "MISSED PUNCH"):
                            d_key = f"{resolved_year:04d}-{resolved_month_num:02d}-{(idx + 1):02d}"
                            present_days_by_date[d_key] = {"date": d_key, "status": item.strip()}

        # Load local state punches for merging (today / tracked days)
        local_state_map = {}
        try:
            with self._state_lock:
                local_state_map = self._load_state() or {}
        except Exception:
            local_state_map = {}

        is_freezed = str(res_json.get("freezed", "0")) in ("1", "true", "True")
        _, num_days = calendar.monthrange(resolved_year, resolved_month_num)

        parsed_days = []
        present_cnt = 0
        missed_punch_cnt = 0
        absent_cnt = 0
        week_off_cnt = 0
        leave_cnt = 0
        holiday_cnt = 0

        for day_idx in range(1, num_days + 1):
            day_date = datetime(resolved_year, resolved_month_num, day_idx)
            date_str = day_date.strftime("%Y-%m-%d")
            day_name = day_date.strftime("%a")

            # Extract day payload
            val = None
            if is_full_month_status_array and day_idx - 1 < len(present_days_list):
                val = present_days_list[day_idx - 1]
            else:
                val = present_days_by_date.get(date_str)

            # Extract punch times and details (from day record, separate punch record, and local punch)
            api_punch = punches_by_date.get(date_str)
            local_punch = local_state_map.get(date_str)
            punch_display, day_detail, punches = _extract_punch_and_details(
                val=val,
                date_str=date_str,
                local_punch=local_punch,
                api_punch=api_punch,
            )
            has_valid_punch = bool(punch_display)
            is_single_or_same_punch = (
                len(punches) == 1 or (len(punches) == 2 and punches[0] == punches[1])
            )

            # Extract raw API status
            raw_status = None
            if isinstance(val, dict):
                raw_status = (
                    val.get("status")
                    or val.get("attendance_status")
                    or val.get("attendance")
                    or val.get("day_status")
                    or val.get("status_name")
                    or val.get("type")
                    or val.get("mark")
                    or val.get("code")
                )
                if isinstance(raw_status, dict):
                    raw_status = raw_status.get("name") or raw_status.get("status") or raw_status.get("code")
            elif isinstance(val, str) and not _is_valid_punch_time(val):
                raw_status = val

            raw_status_str = str(raw_status).strip() if raw_status is not None else None
            if raw_status_str and raw_status_str.lower() in ("none", "null", "undefined", "-", "{}"):
                raw_status_str = None

            raw_upper = raw_status_str.upper() if raw_status_str else ""

            # Saturday / Sunday business rules (used only when API weekoff is not explicitly provided)
            is_sunday = (day_date.weekday() == 6)
            is_saturday = (day_date.weekday() == 5)
            sat_idx = (day_idx - 1) // 7 + 1 if is_saturday else 0
            is_working_saturday = (is_saturday and sat_idx in (1, 3))

            # Status Precedence Resolution:
            # 1. Holiday from API
            # 2. Explicit Leave / Comp Off from API
            # 3. Explicit Missed Punch (from API mispunch_days or raw status)
            # 4. Explicit Week Off from API
            # 5. Valid punch / attendance detected -> Present (or Half Day / Late / Missed Punch)
            # 6. Fallback Week Off (Sunday, 2nd/4th/5th Sat when API weekoff list is omitted)
            # 7. Explicit Absent from API
            # 8. Past / today working day with no attendance -> Absent
            # 9. Future working day -> "-"
            if date_str in holiday_map:
                status_code = f"Holiday: {holiday_map[date_str]}"
            elif date_str in leave_set:
                status_code = leave_name_map.get(date_str) or "Leave"
            elif raw_upper in ("EL", "CL", "SL", "PL", "ML", "RH", "LWP", "LEAVE") or (raw_status_str and "LEAVE" in raw_upper):
                status_code = raw_status_str if raw_status_str else "Leave"
            elif raw_upper in ("COMP OFF", "COMP_OFF", "CO") or date_str in comp_off_set:
                status_code = "Comp Off"
            elif date_str in mispunch_set or raw_upper in ("MISSED PUNCH", "MISSEDPUNCH", "MISSED_PUNCH", "MISPUNCH", "MIS_PUNCH", "MP"):
                status_code = "Missed Punch"
            elif date_str in weekoff_set:
                status_code = "Week Off"
            elif has_valid_punch or raw_upper in ("P", "PRESENT"):
                if raw_upper in ("HD", "HALF DAY", "HALF_DAY"):
                    status_code = "Half Day"
                elif raw_upper in ("LATE", "L"):
                    status_code = "Late"
                elif date_str in mispunch_set:
                    status_code = "Missed Punch"
                else:
                    status_code = "P"
            elif raw_upper in ("WEEK OFF", "WEEKOFF", "WO", "W/O") or (raw_status_str and "WEEK OFF" in raw_upper):
                status_code = "Week Off"
            elif not weekoff_set and (is_sunday or (is_saturday and not is_working_saturday)):
                status_code = "Week Off"
            elif raw_upper in ("A", "ABSENT"):
                status_code = "A"
            elif is_working_saturday and not weekoff_set:
                if day_date.date() <= now.date():
                    status_code = "A"
                else:
                    status_code = "-"
            elif day_date.date() <= now.date():
                status_code = "A"
            else:
                status_code = "-"

            # Map status code to human readable label & color tokens
            code_upper = status_code.upper() if status_code else "-"
            if code_upper in ("P", "PRESENT"):
                status_label = "Present"
                status_badge = "P"
                color = "#16a34a"  # Green
                bg_color = "#dcfce7"
                present_cnt += 1
            elif "MISSED" in code_upper or "MISPUNCH" in code_upper or code_upper == "MP":
                status_label = "Missed Punch"
                status_badge = "MP"
                color = "#dc2626"  # Red
                bg_color = "#fee2e2"
                missed_punch_cnt += 1
            elif code_upper in ("A", "ABSENT"):
                status_label = "Absent"
                status_badge = "A"
                color = "#dc2626"  # Red
                bg_color = "#fee2e2"
                absent_cnt += 1
            elif "WEEK OFF" in code_upper or code_upper in ("WO", "W/O"):
                status_label = "Week Off"
                status_badge = "WO"
                color = "#2563eb"  # Blue
                bg_color = "#dbeafe"
                week_off_cnt += 1
            elif "HOLIDAY" in code_upper or code_upper == "H":
                status_label = status_code if "Holiday:" in status_code else "Holiday"
                status_badge = "H"
                color = "#9333ea"  # Purple
                bg_color = "#f3e8ff"
                holiday_cnt += 1
            elif code_upper in ("EL", "CL", "SL", "PL", "ML", "RH", "LWP", "LEAVE") or "LEAVE" in code_upper:
                status_label = f"Leave ({status_code})" if len(status_code) <= 3 else status_code
                status_badge = status_code if len(status_code) <= 3 else "L"
                color = "#7e22ce"  # Purple matching reference UI
                bg_color = "#f3e8ff"
                leave_cnt += 1
            elif "COMP" in code_upper:
                status_label = "Comp Off"
                status_badge = "CO"
                color = "#0891b2"  # Cyan
                bg_color = "#cffafe"
                leave_cnt += 1
            elif code_upper in ("HD", "HALF DAY"):
                status_label = "Half Day"
                status_badge = "HD"
                color = "#ca8a04"  # Yellow
                bg_color = "#fef9c3"
                present_cnt += 1
            elif "LATE" in code_upper:
                status_label = "Late"
                status_badge = "L"
                color = "#b45309"
                bg_color = "#fef3c7"
                present_cnt += 1
            else:
                status_label = status_code if status_code != "-" else "—"
                status_badge = "-" if status_code == "-" else status_code[:2]
                color = "#64748b"
                bg_color = "#f1f5f9"

            # Production logging of attendance status resolution
            logger.info(
                "Attendance Status Resolution: Date: %s (%s) | API Record: %s | API Status: %s | Punch: %s | Detected Attendance: %s | Final Status: %s",
                date_str,
                day_name,
                val is not None,
                raw_status_str,
                punch_display,
                has_valid_punch,
                status_label,
            )

            parsed_days.append({
                "day_num": day_idx,
                "date": date_str,
                "day_name": day_name,
                "status_code": status_code or "—",
                "status_label": status_label,
                "status_badge": status_badge,
                "color": color,
                "bg_color": bg_color,
                "details": day_detail,
                "is_today": day_date.date() == now.date(),
            })

        output_data = {
            "response": res_json.get("response", 200),
            "status": res_json.get("status", 1),
            "month": resolved_month_name,
            "year": resolved_year,
            "days": parsed_days,
            "summary": {
                "present": present_cnt,
                "missed_punch": missed_punch_cnt,
                "absent": absent_cnt,
                "week_off": week_off_cnt,
                "leave": leave_cnt,
                "holiday": holiday_cnt,
                "total_days": num_days,
            },
            "freezed": is_freezed,
            "raw_result": result,
            "error": None,
        }

        self._monthly_cache[cache_key] = output_data
        self._monthly_cache_ts[cache_key] = now_ts
        return output_data

    def get_leave_quota(
        self,
        indo_code: str | None = None,
        key: str | None = None,
        force: bool = False,
    ) -> dict:
        """
        Fetch employee leave balance and quota from dynamic Leave Quota API:
        Endpoint: leave/leave_quota
        Parameters:
          - indo_code: employee code (e.g. 'EC-047' or 'EC-100')
          - key: API key (e.g. 'testapikey111')

        Returns a structured dictionary with:
          - response: str | int
          - status: int
          - items: list of normalized leave items
          - summary: {total_quota, total_used, total_available, leave_types_count}
          - raw_data: any
          - error: str | None
        """
        import requests
        import time

        # 1. Resolve indo_code and key from active session context
        resolved_indo = indo_code
        if not resolved_indo:
            try:
                from services.session_service import SessionService
                u = SessionService().current_user
                if u:
                    resolved_indo = u.indo_code or u.employee_id or u.username
            except Exception:
                pass

        if not resolved_indo:
            try:
                from services.secure_session import SessionStore
                s = SessionStore().load_session()
                if s and s.get("indo_code"):
                    resolved_indo = s.get("indo_code")
            except Exception:
                pass

        if not resolved_indo:
            try:
                from PySide6.QtCore import QSettings
                st = QSettings("Indovision", "iHRMSMonitor")
                resolved_indo = st.value("last_employee_id") or None
            except Exception:
                pass

        if not resolved_indo:
            resolved_indo = "EC-047"

        resolved_key = key or os.environ.get("IHRMS_LEAVE_API_KEY") or os.environ.get("IHRMS_ATTENDANCE_API_KEY")
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

        # 2. Check Cache
        if not hasattr(self, "_leave_cache"):
            self._leave_cache = {}
            self._leave_cache_ts = {}

        cache_key = f"{resolved_indo}_{resolved_key}"
        now_ts = time.time()
        if not force and cache_key in self._leave_cache:
            if now_ts - self._leave_cache_ts.get(cache_key, 0) < 300:  # 5 min cache
                return self._leave_cache[cache_key]

        # 3. Resolve URL
        try:
            from config.api_config import ApiConfig
            leave_url = ApiConfig().leave_quota_url
        except Exception:
            leave_url = os.environ.get("IHRMS_LEAVE_QUOTA_API_URL")

        if not leave_url:
            leave_url = "https://softdev.indovisionservices.in/ihrms84/hrms_api/ci4/api/leave/leave_quota"

        req_payload = {
            "indo_code": str(resolved_indo),
            "key": str(resolved_key),
        }

        logger.info(
            "Calling Leave Quota API: url=%s data=%s",
            leave_url,
            {"indo_code": resolved_indo, "key": "***"},
        )

        res_json = None
        error_msg = None
        try:
            resp = requests.post(leave_url, data=req_payload, timeout=12)
            logger.info("Leave Quota API response: HTTP %d (size: %d bytes)", resp.status_code, len(resp.content))
            
            # If backend returns non-200 with JSON error message
            try:
                res_json = resp.json()
            except Exception:
                res_json = None

            if resp.status_code >= 400:
                if isinstance(res_json, dict):
                    msgs = res_json.get("messages") or res_json.get("message")
                    if isinstance(msgs, dict):
                        error_msg = msgs.get("message") or msgs.get("response") or str(msgs)
                    elif msgs:
                        error_msg = str(msgs)
                    else:
                        error_msg = res_json.get("error") or f"HTTP {resp.status_code}"
                else:
                    error_msg = f"HTTP {resp.status_code}: {resp.text[:100]}"
                logger.warning("Leave Quota API returned error: %s", error_msg)

        except Exception as exc:
            error_msg = f"Network/Connection error: {str(exc)}"
            logger.error("Failed to fetch leave quota from %s: %s", leave_url, exc)

        if error_msg or not res_json:
            return {
                "response": "Failed",
                "status": 400,
                "items": [],
                "summary": {
                    "total_quota": 0.0,
                    "total_used": 0.0,
                    "total_available": 0.0,
                    "leave_types_count": 0,
                },
                "raw_data": res_json,
                "error": error_msg or "Empty or invalid response from server.",
            }

        # 4. Parse & Normalize Leave Items
        # Data container can be in `data`, `result`, `leave_quota`, `leave_balances`, or root
        raw_items = None
        if isinstance(res_json, dict):
            # Check for API failure inside 200 OK body
            if res_json.get("response") == "Failed" or res_json.get("status") in (400, 401, 404, 500):
                msgs = res_json.get("messages") or res_json.get("message")
                err_text = "Server returned failure response"
                if isinstance(msgs, dict):
                    err_text = msgs.get("message") or msgs.get("response") or str(msgs)
                elif msgs:
                    err_text = str(msgs)
                return {
                    "response": "Failed",
                    "status": res_json.get("status", 400),
                    "items": [],
                    "summary": {
                        "total_quota": 0.0,
                        "total_used": 0.0,
                        "total_available": 0.0,
                        "leave_types_count": 0,
                    },
                    "raw_data": res_json,
                    "error": err_text,
                }

            for key_candidate in (
                "data", "result", "leave_quota", "leave_balances", "leave_types",
                "leaves", "leave_details", "records", "items", "list", "rows", "quota_details"
            ):
                if key_candidate in res_json and res_json[key_candidate] is not None:
                    raw_items = res_json[key_candidate]
                    break
            if raw_items is None:
                # If no container found, check if dictionary itself has leave entries
                raw_items = res_json

            # If raw_items is a dict, check if it contains a nested list
            if isinstance(raw_items, dict):
                for inner_key in (
                    "leaves", "leave_types", "leave_balances", "leave_list",
                    "leave_details", "records", "items", "list", "rows", "details",
                    "data", "result", "quota_details"
                ):
                    if inner_key in raw_items and isinstance(raw_items[inner_key], list):
                        raw_items = raw_items[inner_key]
                        break
        elif isinstance(res_json, list):
            raw_items = res_json

        # Fixed 7 Leave Types Configuration
        FIXED_LEAVE_TYPES = [
            {"code": "CL", "name": "Casual Leave", "aliases": ("cl", "casual", "casual leave")},
            {"code": "SL", "name": "Sick Leave", "aliases": ("sl", "sick", "sick leave")},
            {"code": "CO", "name": "Comp Off", "aliases": ("co", "comp", "comp off", "compensatory", "compensatory off")},
            {"code": "OD", "name": "Business Trip", "aliases": ("od", "business", "business trip", "on duty", "official duty")},
            {"code": "LWP", "name": "Leave Without Pay", "aliases": ("lwp", "without pay", "leave without pay", "unpaid")},
            {"code": "EL", "name": "Paid Leave", "aliases": ("el", "pl", "paid", "paid leave", "earned", "earned leave", "privilege", "privilege leave")},
            {"code": "RH", "name": "Restricted/Floating", "aliases": ("rh", "fl", "restricted", "floating", "restricted holiday", "restricted/floating", "floating holiday")},
        ]

        def _to_num(val) -> float:
            if val is None or val == "":
                return 0.0
            try:
                return float(val)
            except (ValueError, TypeError):
                return 0.0

        def _fmt_num(val: float) -> str:
            if val.is_integer():
                return f"{int(val)}"
            s = f"{val:.2f}"
            if s.endswith(".00"):
                return s[:-3]
            if s.endswith("0") and "." in s:
                return s[:-1]
            return s

        def _extract_csv_list(container_dict: dict, candidate_keys: tuple[str, ...]) -> list[str]:
            for cand in candidate_keys:
                for k, v in container_dict.items():
                    if k.lower() == cand.lower() and v is not None:
                        if isinstance(v, (list, tuple)):
                            return [str(x).strip() for x in v if not isinstance(x, dict)]
                        if isinstance(v, (int, float)):
                            return [str(v).strip()]
                        if isinstance(v, str):
                            if "," in v:
                                return [x.strip() for x in v.split(",")]
                            v_str = v.strip()
                            return [v_str] if v_str else []
            return []

        # ------------------------------------------------------------------
        # Format A: Comma-separated strings / lists inside container dict
        # (Can be a dict or a list containing a dict with CSV fields)
        # ------------------------------------------------------------------
        CSV_LT_ID_KEYS = ("lt_id", "lt_ids", "leave_type_id", "leave_type_ids", "leave_types", "leave_type", "ltid")
        CSV_LEAVES_KEYS = ("leaves", "total_leaves", "total_quota", "allotted", "quota", "total", "allocated")
        CSV_TAKED_KEYS = ("leavestaked", "leaves_taked", "leaves_taken", "leavestaken", "taken", "used", "availed", "consumed")
        CSV_REMAINING_KEYS = ("remaining", "remains", "leave_balance", "available", "balance", "available_leave", "balance_quota")
        CSV_CARRY_KEYS = ("carry_over", "carry_overs", "carryover", "carryovers")

        def _is_csv_container(d: dict) -> bool:
            if not isinstance(d, dict):
                return False
            for k, v in d.items():
                k_lower = k.lower()
                if k_lower in CSV_LT_ID_KEYS:
                    if isinstance(v, str) and "," in v:
                        return True
                    if isinstance(v, (list, tuple)) and len(v) > 1:
                        return True
                if isinstance(v, str) and "," in v:
                    if any(cand in k_lower for cand in ("leaves", "taked", "taken", "remain", "quota", "balance", "carry")):
                        return True
                if isinstance(v, (list, tuple)) and len(v) > 1 and not isinstance(v[0], dict):
                    if any(cand in k_lower for cand in ("leaves", "taked", "taken", "remain", "quota", "balance", "carry")):
                        return True
            return False

        is_csv_dict = False
        csv_container = None
        if isinstance(raw_items, dict):
            if _is_csv_container(raw_items):
                is_csv_dict = True
                csv_container = raw_items
        elif isinstance(raw_items, list) and raw_items:
            # Check if list has a dictionary containing CSV fields (e.g. leave_quota: [{lt_id: "...", leaves: "..."}])
            if isinstance(raw_items[0], dict) and _is_csv_container(raw_items[0]):
                is_csv_dict = True
                csv_container = raw_items[0]

        parsed_items = []

        if is_csv_dict and isinstance(csv_container, dict):
            raw_lt_ids = _extract_csv_list(csv_container, CSV_LT_ID_KEYS)
            raw_leaves = _extract_csv_list(csv_container, CSV_LEAVES_KEYS)
            raw_taken = _extract_csv_list(csv_container, CSV_TAKED_KEYS)
            raw_remaining = _extract_csv_list(csv_container, CSV_REMAINING_KEYS)
            raw_carry = _extract_csv_list(csv_container, CSV_CARRY_KEYS)

            ID_NAME_MAP = {
                "1": ("CL", "Casual Leave"),
                "2": ("SL", "Sick Leave"),
                "3": ("CO", "Comp Off"),
                "4": ("OD", "Business Trip"),
                "5": ("LWP", "Leave Without Pay"),
                "6": ("EL", "Paid Leave"),
                "7": ("RH", "Restricted/Floating"),
            }

            max_len = max(len(raw_lt_ids), len(raw_leaves), len(raw_taken), len(raw_remaining), len(FIXED_LEAVE_TYPES))
            for i in range(max_len):
                raw_id = raw_lt_ids[i] if i < len(raw_lt_ids) else (str(i + 1) if i < len(FIXED_LEAVE_TYPES) else str(i + 1))
                q_str = raw_leaves[i] if i < len(raw_leaves) else "0"
                u_str = raw_taken[i] if i < len(raw_taken) else "0"
                r_str = raw_remaining[i] if i < len(raw_remaining) else ""
                c_str = raw_carry[i] if i < len(raw_carry) else "0"

                q_num = _to_num(q_str)
                u_num = _to_num(u_str)
                if r_str:
                    r_num = _to_num(r_str)
                else:
                    r_num = max(0.0, q_num - u_num)
                    r_str = _fmt_num(r_num)
                c_num = _to_num(c_str)

                # Determine code and name
                if raw_id in ID_NAME_MAP:
                    short_code, type_name = ID_NAME_MAP[raw_id]
                elif raw_id and raw_id not in ("1", "2", "3", "4", "5", "6", "7"):
                    short_code = raw_id if raw_id.isalpha() else f"LT{raw_id}"
                    type_name = f"Leave Type {raw_id}"
                elif i < len(FIXED_LEAVE_TYPES):
                    short_code = FIXED_LEAVE_TYPES[i]["code"]
                    type_name = FIXED_LEAVE_TYPES[i]["name"]
                else:
                    short_code = f"LT{raw_id}"
                    type_name = f"Leave Type {raw_id}"

                total_quota_str = q_str if q_str else _fmt_num(q_num)
                used_str = u_str if u_str else _fmt_num(u_num)
                avail_str = r_str if r_str else _fmt_num(r_num)
                carry_str = c_str if c_str else _fmt_num(c_num)

                status_label = "Available" if r_num > 0 else ("Exhausted" if q_num > 0 else "N/A")
                color = "#16A34A" if r_num > 0 else ("#64748B" if q_num > 0 else "#94A3B8")
                bg_color = "#DCFCE7" if r_num > 0 else ("#F1F5F9" if q_num > 0 else "#F8FAFC")

                parsed_items.append({
                    "leave_type_id": raw_id,
                    "leave_type": type_name,
                    "name": type_name,
                    "short_name": short_code,
                    "code": short_code,
                    "carry_over": c_num,
                    "carry_over_str": carry_str,
                    "total_quota": q_num,
                    "total_quota_str": total_quota_str,
                    "total": q_num,
                    "total_str": total_quota_str,
                    "used": u_num,
                    "used_str": used_str,
                    "available": r_num,
                    "available_str": avail_str,
                    "left": r_num,
                    "left_str": avail_str,
                    "remaining": r_num,
                    "remaining_str": avail_str,
                    "dynamic_fields": {
                        "total": total_quota_str,
                        "used": used_str,
                        "remaining": avail_str,
                    },
                    "unit": "Days",
                    "status_label": status_label,
                    "color": color,
                    "bg_color": bg_color,
                    "raw": {
                        "lt_id": raw_id,
                        "leaves": q_str,
                        "leavesTaked": u_str,
                        "remaining": r_str,
                    },
                })

        # ------------------------------------------------------------------
        # Format B: List of dictionaries or Format C: Dict of dicts
        # ------------------------------------------------------------------
        else:
            raw_list: list[dict] = []
            if isinstance(raw_items, list):
                raw_list = [entry for entry in raw_items if isinstance(entry, dict)]
            elif isinstance(raw_items, dict):
                for k, v in raw_items.items():
                    if k in ("response", "status", "error", "message", "messages", "code", "token"):
                        continue
                    if isinstance(v, dict):
                        d = dict(v)
                        if "leave_type" not in d and "name" not in d:
                            d["leave_type"] = k
                        raw_list.append(d)
                    elif isinstance(v, (int, float, str)) and str(v).replace(".", "", 1).isdigit():
                        raw_list.append({"leave_type": k, "available": v, "total_quota": v, "used": 0})

            # Pass 1: Try exact code or alias match for all fixed types
            assigned: dict[int, dict] = {}
            matched_raw_indices = set()

            for fixed_idx, fixed in enumerate(FIXED_LEAVE_TYPES):
                code = fixed["code"].lower()
                aliases = fixed.get("aliases", ())
                for r_idx, entry in enumerate(raw_list):
                    if r_idx in matched_raw_indices:
                        continue
                    entry_code = str(
                        entry.get("short_name")
                        or entry.get("short_code")
                        or entry.get("code")
                        or entry.get("leave_code")
                        or entry.get("leaveCode")
                        or ""
                    ).strip().lower()
                    entry_name = str(
                        entry.get("leave_type_name")
                        or entry.get("leave_name")
                        or entry.get("leave_type")
                        or entry.get("name")
                        or entry.get("type")
                        or ""
                    ).strip().lower()

                    if (entry_code and (entry_code == code or entry_code in aliases)) or (entry_name and any(alias in entry_name for alias in aliases)):
                        assigned[fixed_idx] = entry
                        matched_raw_indices.add(r_idx)
                        break

            # Pass 2: For any fixed type that didn't match by code/name, match positional if unmapped raw items exist
            unmatched_raw = [entry for r_idx, entry in enumerate(raw_list) if r_idx not in matched_raw_indices]
            unmatched_fixed = [f_idx for f_idx in range(len(FIXED_LEAVE_TYPES)) if f_idx not in assigned]
            for f_idx, entry in zip(unmatched_fixed, unmatched_raw):
                assigned[f_idx] = entry

            for fixed_idx, fixed in enumerate(FIXED_LEAVE_TYPES):
                type_name = fixed["name"]
                short_code = fixed["code"]
                entry = assigned.get(fixed_idx, {})
                carry_over_num = _to_num(entry.get("carry_over"))
                quota_raw = (
                    entry.get("total_quota")
                    or entry.get("totalQuota")
                    or entry.get("total_leaves")
                    or entry.get("totalLeaves")
                    or entry.get("allotted")
                    or entry.get("quota")
                    or entry.get("total")
                    or entry.get("allocated")
                    or entry.get("leaves")
                    or entry.get("credit")
                )
                used_raw = (
                    entry.get("used")
                    or entry.get("taken")
                    or entry.get("leavesTaken")
                    or entry.get("leaves_taken")
                    or entry.get("leavesTaked")
                    or entry.get("leaves_taked")
                    or entry.get("consumed")
                    or entry.get("applied")
                    or entry.get("availed")
                )
                avail_raw = (
                    entry.get("available")
                    or entry.get("balance")
                    or entry.get("remaining")
                    or entry.get("remains")
                    or entry.get("leave_balance")
                    or entry.get("available_leave")
                    or entry.get("balance_quota")
                    or entry.get("net_balance")
                )

                quota_num = _to_num(quota_raw)
                used_num = _to_num(used_raw)
                if avail_raw is not None:
                    avail_num = _to_num(avail_raw)
                else:
                    avail_num = max(0.0, quota_num - used_num)

                if quota_raw is None and (avail_raw is not None or used_raw is not None):
                    quota_num = avail_num + used_num

                status_label = "Available" if avail_num > 0 else ("Exhausted" if quota_num > 0 else "N/A")
                color = "#16A34A" if avail_num > 0 else ("#64748B" if quota_num > 0 else "#94A3B8")
                bg_color = "#DCFCE7" if avail_num > 0 else ("#F1F5F9" if quota_num > 0 else "#F8FAFC")

                parsed_items.append({
                    "leave_type_id": str(entry.get("leave_type_id") or entry.get("lt_id") or fixed_idx + 1),
                    "leave_type": type_name,
                    "name": type_name,
                    "short_name": short_code,
                    "code": short_code,
                    "carry_over": carry_over_num,
                    "carry_over_str": _fmt_num(carry_over_num),
                    "total_quota": quota_num,
                    "total_quota_str": _fmt_num(quota_num),
                    "total": quota_num,
                    "total_str": _fmt_num(quota_num),
                    "used": used_num,
                    "used_str": _fmt_num(used_num),
                    "available": avail_num,
                    "available_str": _fmt_num(avail_num),
                    "left": avail_num,
                    "left_str": _fmt_num(avail_num),
                    "remaining": avail_num,
                    "remaining_str": _fmt_num(avail_num),
                    "dynamic_fields": {
                        "total": _fmt_num(quota_num),
                        "used": _fmt_num(used_num),
                        "remaining": _fmt_num(avail_num),
                    },
                    "unit": "Days",
                    "status_label": status_label,
                    "color": color,
                    "bg_color": bg_color,
                    "raw": entry,
                })

        dynamic_columns = [
            {"key": "carry_over", "label": "Carry Over"},
            {"key": "total_quota", "label": "Total Allotted"},
            {"key": "used", "label": "Availed / Used"},
            {"key": "available", "label": "Available Balance"},
        ]

        # Calculate totals dynamically across all 7 items
        tot_quota = sum(item["total_quota"] for item in parsed_items)
        tot_used = sum(item["used"] for item in parsed_items)
        tot_avail = sum(item["available"] for item in parsed_items)

        output_data = {
            "response": res_json.get("response", "Success") if isinstance(res_json, dict) else "Success",
            "status": res_json.get("status", 200) if isinstance(res_json, dict) else 200,
            "items": parsed_items,
            "columns": dynamic_columns,
            "summary": {
                "total_quota": tot_quota,
                "total_quota_str": _fmt_num(tot_quota),
                "total_used": tot_used,
                "total_used_str": _fmt_num(tot_used),
                "total_available": tot_avail,
                "total_available_str": _fmt_num(tot_avail),
                "leave_types_count": len(parsed_items),
            },
            "raw_data": res_json,
            "error": None,
        }

        self._leave_cache[cache_key] = output_data
        self._leave_cache_ts[cache_key] = now_ts
        return output_data


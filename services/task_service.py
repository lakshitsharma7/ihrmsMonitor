"""Service for fetching and managing Assigned Tasks / KRAs."""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests

from config.api_config import ApiConfig
from utils.logger import get_logger

logger = get_logger(__name__)


class TaskService:
    """Singleton service for querying assigned tasks / KRAs from dynamic backend APIs."""

    _instance: TaskService | None = None
    _lock = threading.Lock()

    def __new__(cls) -> TaskService:
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
        self._last_fetch_ts: Dict[str, float] = {}
        self._cached_tasks: Dict[str, List[Dict[str, Any]]] = {}
        self._submitted_dates: set[str] = set()
        self._submitted_additional_dates: set[str] = set()
        self._baseline_done_cache: Dict[str, Dict[str, str]] = {}
        self._last_error: Optional[str] = None

    @property
    def last_error(self) -> Optional[str]:
        """Return the most recent error message from a fetch attempt, if any."""
        with self._state_lock:
            return self._last_error

    def clear_cache(self) -> None:
        """Clear cached task results and timestamps."""
        with self._state_lock:
            self._cached_tasks.clear()
            self._last_fetch_ts.clear()
            self._submitted_dates.clear()
            self._submitted_additional_dates.clear()
            self._baseline_done_cache.clear()
            self._last_error = None

    def mark_timesheet_submitted(self, date: Optional[str]) -> None:
        """Record that a timesheet for date has been confirmed submitted."""
        if date and str(date).strip():
            with self._state_lock:
                self._submitted_dates.add(str(date).strip())

    def unmark_timesheet_submitted(self, date: Optional[str]) -> None:
        """Remove submitted timesheet status for date (e.g. after draft save)."""
        if date and str(date).strip():
            with self._state_lock:
                self._submitted_dates.discard(str(date).strip())

    def is_timesheet_submitted(self, date: Optional[str]) -> bool:
        """Return True if timesheet for date was confirmed submitted."""
        if not date or not str(date).strip():
            return False
        with self._state_lock:
            return str(date).strip() in self._submitted_dates

    def mark_additional_task_submitted(self, date: Optional[str]) -> None:
        """Record that an additional task for date has been confirmed submitted."""
        if date and str(date).strip():
            with self._state_lock:
                self._submitted_additional_dates.add(str(date).strip())

    def unmark_additional_task_submitted(self, date: Optional[str]) -> None:
        """Remove submitted additional task status for date (e.g. after draft save)."""
        if date and str(date).strip():
            with self._state_lock:
                self._submitted_additional_dates.discard(str(date).strip())

    def is_additional_task_submitted(self, date: Optional[str]) -> bool:
        """Return True if additional task for date was confirmed submitted."""
        if not date or not str(date).strip():
            return False
        with self._state_lock:
            return str(date).strip() in self._submitted_additional_dates

    def _resolve_auth_credentials(
        self,
        indo_code: Optional[str] = None,
        key: Optional[str] = None,
    ) -> tuple[Optional[str], Optional[str]]:
        """Resolve employee indo_code and API key from active session context."""
        resolved_indo = indo_code
        if not resolved_indo:
            try:
                from services.session_service import SessionService

                user = SessionService().current_user
                if user:
                    resolved_indo = (
                        user.indo_code or user.employee_id or user.username
                    )
            except Exception:
                pass

        if not resolved_indo:
            try:
                from services.secure_session import SessionStore

                saved = SessionStore().load_session()
                if saved:
                    resolved_indo = (
                        saved.get("indo_code")
                        or saved.get("employee_id")
                        or saved.get("username")
                    )
            except Exception:
                pass

        if not resolved_indo:
            try:
                from PySide6.QtCore import QSettings

                st = QSettings("Indovision", "iHRMSMonitor")
                resolved_indo = st.value("last_employee_id") or None
            except Exception:
                pass

        resolved_key = key or os.environ.get("IHRMS_TASK_API_KEY")
        if not resolved_key:
            try:
                from services.session_service import SessionService

                user = SessionService().current_user
                if user and user.api_key:
                    resolved_key = user.api_key
            except Exception:
                pass

        if not resolved_key:
            try:
                from services.secure_session import SessionStore

                saved = SessionStore().load_session()
                if saved and saved.get("api_key"):
                    resolved_key = saved.get("api_key")
            except Exception:
                pass

        if not resolved_key:
            resolved_key = "testapikey111"

        return resolved_indo, resolved_key

    def _resolve_base_url(self) -> Optional[str]:
        """Resolve base API URL with fallback across ApiConfig, SessionStore, and QSettings."""
        try:
            from config.api_config import ApiConfig
            cfg = ApiConfig()
            if getattr(cfg, "_base_url", None):
                return cfg._base_url.rstrip("/")
            if cfg.is_verified:
                return cfg.base_url.rstrip("/")
        except Exception:
            pass

        try:
            from services.secure_session import SessionStore
            sess = SessionStore().load_session()
            if sess and sess.get("base_url"):
                return str(sess.get("base_url")).rstrip("/")
        except Exception:
            pass

        try:
            from PySide6.QtCore import QSettings
            st = QSettings("Indovision", "iHRMSMonitor")
            b = st.value("ApiConfig/last_base_url") or st.value("session/base_url")
            if not b:
                st_leg = QSettings("Indovision", "iHRMS")
                b = st_leg.value("ApiConfig/last_base_url") or st_leg.value("session/base_url")
            if b:
                return str(b).rstrip("/")
        except Exception:
            pass

        return None

    def _resolve_kra_url(self) -> Optional[str]:
        try:
            url = ApiConfig().get_kra_url
            if url:
                return url
        except Exception:
            pass
        env_url = os.environ.get("IHRMS_GET_KRA_API_URL")
        if env_url:
            return env_url
        base = self._resolve_base_url()
        if base:
            return f"{base}/TaskPMS/get_kra"
        return None

    def _resolve_fill_timesheet_url(self) -> Optional[str]:
        try:
            url = ApiConfig().fill_time_sheet_url
            if url:
                return url
        except Exception:
            pass
        env_url = os.environ.get("IHRMS_FILL_TIME_SHEET_API_URL")
        if env_url:
            return env_url
        base = self._resolve_base_url()
        if base:
            return f"{base}/TaskPMS/fill_time_sheet"
        return None

    def _resolve_save_additional_task_url(self) -> Optional[str]:
        try:
            url = ApiConfig().save_additional_task_url
            if url:
                return url
        except Exception:
            pass
        env_url = os.environ.get("IHRMS_SAVE_ADDITIONAL_TASK_API_URL")
        if env_url:
            return env_url
        base = self._resolve_base_url()
        if base:
            return f"{base}/TaskPMS/save_additional_task"
        return None

    def _resolve_draft_kra_date_url(self) -> Optional[str]:
        try:
            url = ApiConfig().get_draft_kra_date_url
            if url:
                return url
        except Exception:
            pass
        env_url = os.environ.get("IHRMS_GET_DRAFT_KRA_DATE_API_URL")
        if env_url:
            return env_url
        base = self._resolve_base_url()
        if base:
            return f"{base}/TaskPMS/get_draft_kra_date"
        return None

    def _resolve_submit_kra_date_url(self) -> Optional[str]:
        try:
            url = ApiConfig().get_submit_kra_date_url
            if url:
                return url
        except Exception:
            pass
        env_url = os.environ.get("IHRMS_GET_SUBMIT_KRA_DATE_API_URL")
        if env_url:
            return env_url
        base = self._resolve_base_url()
        if base:
            return f"{base}/TaskPMS/get_submit_kra_date_v2"
        return None

    def _normalize_task_item(self, item: Any, default_date: str) -> Optional[Dict[str, Any]]:
        """Normalize various API task / KRA response dict formats into uniform structure."""
        if not isinstance(item, dict):
            return None

        kra_id = str(
            item.get("kra_id")
            or item.get("id")
            or item.get("task_id")
            or item.get("pk_id")
            or ""
        ).strip()

        timesheet_id = str(
            item.get("TimeSheet_id")
            or item.get("timesheet_id")
            or item.get("time_sheet_id")
            or item.get("timesheetId")
            or item.get("ts_id")
            or ""
        ).strip()

        title = str(
            item.get("task_name")
            or item.get("kra_name")
            or item.get("name")
            or item.get("task_title")
            or item.get("title")
            or item.get("kra_title")
            or item.get("kra")
            or "Assigned Task"
        ).strip()

        description = str(
            item.get("description")
            or item.get("task_desc")
            or item.get("details")
            or item.get("task_details")
            or item.get("kra_description")
            or item.get("measurement_criteria")
            or ""
        ).strip()

        remark = str(
            item.get("comment")
            or item.get("remark")
            or item.get("employee_remark")
            or item.get("task_remark")
            or item.get("notes")
            or ""
        ).strip()

        submit_status = str(
            item.get("submit_status")
            or item.get("submitStatus")
            or item.get("is_submitted")
            or item.get("isSubmitted")
            or item.get("timesheet_status")
            or item.get("time_sheet_status")
            or ""
        ).strip()

        # Resolve task completion numeric value and status
        raw_completed = item.get("task_completed")
        if raw_completed is not None and str(raw_completed).strip() not in ("None", "null", ""):
            task_completed_str = str(raw_completed).strip()
        elif (
            timesheet_id
            or submit_status in ("1", "2", "true", "True")
            or str(item.get("status")).strip().lower() in ("completed", "submitted")
        ) and item.get("task_done") is not None:
            # When get_kra returns a timesheet entry (draft or submitted), the progress recorded for the timesheet is returned in task_done
            raw_d = str(item.get("task_done")).strip()
            if raw_d and raw_d not in ("None", "null", "-"):
                task_completed_str = raw_d
            else:
                task_completed_str = ""
        else:
            task_completed_str = ""

        # Resolve status cleanly
        raw_status = (
            item.get("status")
            or item.get("task_status")
            or item.get("kra_status")
            or item.get("state")
        )
        raw_status_str = str(raw_status or "").strip()

        if submit_status in ("1", "2", "true", "True") or raw_status_str.lower() in ("completed", "submitted"):
            submit_status = "1"
            status = "Completed"
        elif raw_status_str:
            status = raw_status_str
        elif task_completed_str in ("100", "1", "Completed") or str(raw_completed).strip().lower() in ("completed", "done"):
            status = "Completed"
        elif item.get("target") and str(item.get("target")).strip().lower() in (
            "completed",
            "in progress",
            "pending",
            "active",
            "done",
            "closed",
            "assigned",
        ):
            status = str(item.get("target")).strip().title()
        elif task_completed_str and task_completed_str not in ("0", "0.00", ""):
            status = "In Progress"
        elif item.get("task_done") and str(item.get("task_done")).strip() not in ("None", "null", "0", "0.00", ""):
            status = "In Progress"
        else:
            status = "Pending"

        raw_date = (
            item.get("date")
            or item.get("assigned_date")
            or item.get("due_date")
            or item.get("target_date")
            or item.get("created_at")
            or default_date
            or ""
        )
        date_val = str(raw_date).strip() if raw_date is not None else ""
        if date_val.lower() in ("none", "null", ""):
            date_val = ""

        raw_weight = (
            item.get("weightage")
            or item.get("weight")
            or item.get("percentage")
            or item.get("priority")
            or "-"
        )
        weightage = str(raw_weight).strip()
        if weightage and weightage != "-" and not weightage.endswith("%"):
            try:
                f_val = float(weightage)
                if f_val.is_integer():
                    weightage = f"{int(f_val)}%"
                else:
                    weightage = f"{f_val:g}%"
            except ValueError:
                pass

        category = str(
            item.get("category_name")
            or item.get("category")
            or item.get("kra_category")
            or item.get("project_name")
            or item.get("project")
            or item.get("type")
            or "-"
        ).strip()

        raw_target = item.get("target")
        if raw_target is None:
            raw_target = item.get("target_criteria")
        if raw_target is None:
            raw_target = item.get("target_value")
        if raw_target is None:
            raw_target = item.get("target_date")

        if raw_target is not None and str(raw_target).strip() not in ("None", "null", ""):
            target = str(raw_target).strip()
        else:
            target = "-"

        raw_mc = item.get("measurement_criteria")
        if raw_mc is None:
            raw_mc = item.get("measurement")
        if raw_mc is None:
            raw_mc = item.get("criteria")
        if raw_mc is None:
            raw_mc = item.get("kpi")

        if raw_mc is not None and str(raw_mc).strip() not in ("None", "null", ""):
            measurement_criteria = str(raw_mc).strip()
        else:
            measurement_criteria = "-"

        raw_done = item.get("task_done")
        if raw_done is None:
            raw_done = item.get("task_done_till_now")
        if raw_done is None:
            raw_done = item.get("taskDoneTillNow")
        if raw_done is None:
            raw_done = item.get("taskDone")
        if raw_done is None:
            raw_done = item.get("done_till_now")
        if raw_done is None:
            raw_done = item.get("task_progress")
        if raw_done is None:
            raw_done = item.get("progress")
        if raw_done is None:
            raw_done = item.get("hours_done")
        if raw_done is None:
            raw_done = item.get("total_done")
        if raw_done is None:
            raw_done = item.get("completed_till_now")

        if raw_done is not None and str(raw_done).strip() not in ("None", "null", ""):
            task_done = str(raw_done).strip()
        else:
            task_done = "-"

        emp_name = str(
            item.get("employee_name")
            or item.get("emp_name")
            or item.get("user_name")
            or item.get("full_name")
            or item.get("employeeName")
            or ""
        ).strip()
        emp_code = str(
            item.get("indo_code")
            or item.get("employee_code")
            or item.get("emp_code")
            or item.get("employee_id")
            or item.get("empCode")
            or ""
        ).strip()

        submit_status = str(
            item.get("submit_status")
            or item.get("submitStatus")
            or item.get("is_submitted")
            or item.get("isSubmitted")
            or ""
        ).strip()

        return {
            "id": kra_id or timesheet_id or "task",
            "kra_id": kra_id,
            "timesheet_id": timesheet_id,
            "title": title,
            "name": title,
            "description": description,
            "category": category,
            "target": target,
            "measurement_criteria": measurement_criteria,
            "weightage": weightage,
            "task_done": task_done,
            "task_done_till_now": task_done,
            "task_completed": task_completed_str,
            "status": status,
            "submit_status": submit_status,
            "remark": remark,
            "comment": remark,
            "date": date_val,
            "employee_name": emp_name,
            "indo_code": emp_code,
            "is_additional": False,
            "raw": item,
        }

    def fetch_assigned_tasks(
        self,
        date: Optional[str] = None,
        indo_code: Optional[str] = None,
        key: Optional[str] = None,
        force: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Fetch assigned tasks / KRAs for the given date and user.

        API Contract:
          Endpoint: TaskPMS/get_kra
          Payload:
            key: <api_key>
            indo_code: <indo_code>
            date: <YYYY-MM-DD>
        """
        now_dt = datetime.now().astimezone()
        raw_date_str = str(date or now_dt.strftime("%Y-%m-%d")).strip()
        if len(raw_date_str) == 10 and (raw_date_str[2] in ("-", "/") and raw_date_str[5] in ("-", "/")):
            sep = raw_date_str[2]
            try:
                dt = datetime.strptime(raw_date_str, f"%d{sep}%m{sep}%Y")
                date_key = dt.strftime("%Y-%m-%d")
            except Exception:
                date_key = raw_date_str
        else:
            date_key = raw_date_str

        # Check rate-limiting cooldown (120 seconds) unless force=True
        current_ts = time.time()
        with self._state_lock:
            last_ts = self._last_fetch_ts.get(date_key, 0.0)
            if not force and (current_ts - last_ts < 120.0) and (date_key in self._cached_tasks):
                return list(self._cached_tasks[date_key])

        resolved_indo, resolved_key = self._resolve_auth_credentials(
            indo_code=indo_code, key=key
        )

        if not resolved_indo:
            with self._state_lock:
                self._last_error = "User not logged in or employee code missing."
            logger.debug("TaskService: missing indo_code, returning empty task list.")
            return []

        # Resolve endpoint URL with fallback
        kra_url = self._resolve_kra_url()

        if not kra_url:
            with self._state_lock:
                self._last_error = "Task API endpoint not configured."
            logger.debug("TaskService: get_kra endpoint URL not available.")
            return []

        req_payload = {
            "key": str(resolved_key),
            "indo_code": str(resolved_indo),
            "date": str(date_key),
        }

        logger.info(
            "Calling Task API: url=%s payload=%s",
            kra_url,
            {"key": "***", "indo_code": resolved_indo, "date": date_key},
        )

        try:
            resp = requests.post(kra_url, data=req_payload, timeout=10)
            logger.info(
                "Task API response: HTTP %d (response_len=%d) %s",
                resp.status_code,
                len(resp.text),
                resp.text[:1000],
            )
            resp.raise_for_status()
            res_json = resp.json()
        except Exception as api_err:
            with self._state_lock:
                self._last_error = f"API Error: {api_err}"
            logger.warning("Task API request failed gracefully: %s", api_err)
            # Return cached tasks if available
            with self._state_lock:
                return list(self._cached_tasks.get(date_key, []))

        # Parse tasks from response
        raw_items: List[Any] = []
        if isinstance(res_json, list):
            raw_items = res_json
        elif isinstance(res_json, dict):
            # Check emp_kra, kra_list, kraList, data, tasks, kra, result
            if isinstance(res_json.get("emp_kra"), list):
                raw_items = res_json["emp_kra"]
            elif isinstance(res_json.get("kra_list"), list):
                raw_items = res_json["kra_list"]
            elif isinstance(res_json.get("kraList"), list):
                raw_items = res_json["kraList"]
            elif isinstance(res_json.get("data"), list):
                raw_items = res_json["data"]
            elif isinstance(res_json.get("tasks"), list):
                raw_items = res_json["tasks"]
            elif isinstance(res_json.get("kra"), list):
                raw_items = res_json["kra"]
            elif isinstance(res_json.get("result"), list):
                raw_items = res_json["result"]
            elif isinstance(res_json.get("data"), dict):
                nested_data = res_json["data"]
                if isinstance(nested_data.get("emp_kra"), list):
                    raw_items = nested_data["emp_kra"]
                elif isinstance(nested_data.get("kra_list"), list):
                    raw_items = nested_data["kra_list"]
                elif isinstance(nested_data.get("kraList"), list):
                    raw_items = nested_data["kraList"]
                elif isinstance(nested_data.get("tasks"), list):
                    raw_items = nested_data["tasks"]
                else:
                    raw_items = [nested_data]
            elif isinstance(res_json.get("result"), dict):
                nested_res = res_json["result"]
                if isinstance(nested_res.get("emp_kra"), list):
                    raw_items = nested_res["emp_kra"]
                elif isinstance(nested_res.get("kra_list"), list):
                    raw_items = nested_res["kra_list"]
                elif isinstance(nested_res.get("kraList"), list):
                    raw_items = nested_res["kraList"]
                elif isinstance(nested_res.get("tasks"), list):
                    raw_items = nested_res["tasks"]
                else:
                    raw_items = [nested_res]
            elif any(k in res_json for k in ("kra_id", "task_id", "task_name", "kra_name", "title")):
                raw_items = [res_json]

        root_emp_name = ""
        root_emp_code = ""
        if isinstance(res_json, dict):
            for f in ("employee_name", "emp_name", "user_name", "full_name", "name", "employeeName"):
                v = res_json.get(f)
                if v and str(v).strip():
                    root_emp_name = str(v).strip()
                    break
            for f in ("indo_code", "employee_code", "emp_code", "employee_id", "emp_id", "empCode"):
                v = res_json.get(f)
                if v and str(v).strip():
                    root_emp_code = str(v).strip()
                    break
        if not root_emp_code and resolved_indo:
            root_emp_code = resolved_indo

        root_date = ""
        if isinstance(res_json, dict):
            for df in ("date", "task_date", "kra_date", "assigned_date"):
                if res_json.get(df) and str(res_json.get(df)).strip():
                    root_date = str(res_json.get(df)).strip()
                    break

        default_task_date = str(date).strip() if date else (root_date or date_key)

        root_submit_status = ""
        data_dict = res_json.get("data") if isinstance(res_json.get("data"), dict) else {}
        is_server_submitted = False
        if isinstance(res_json, dict):
            for sf in ("submit_status", "submitStatus", "is_submitted", "isSubmitted", "timesheet_status", "time_sheet_status", "timesheet_submit_status"):
                v = res_json.get(sf) if res_json.get(sf) is not None else data_dict.get(sf)
                if v is not None and str(v).strip() not in ("None", "null", ""):
                    root_submit_status = str(v).strip()
                    break

            resp_st = str(res_json.get("status") or "").strip()
            resp_msg = str(res_json.get("message") or res_json.get("response") or "").lower()
            if resp_st == "2" or "already submitted" in resp_msg or bool(res_json.get("is_already_submitted")):
                root_submit_status = "1"
                is_server_submitted = True

        if date_key in self._submitted_dates:
            root_submit_status = "1"
            is_server_submitted = True
        elif root_submit_status in ("1", "2", "true", "True") or is_server_submitted:
            self._submitted_dates.add(date_key)

        normalized: List[Dict[str, Any]] = []
        for raw in raw_items:
            norm = self._normalize_task_item(raw, default_date=default_task_date)
            if norm:
                if not norm.get("date"):
                    norm["date"] = default_task_date
                if not norm.get("employee_name") and root_emp_name:
                    norm["employee_name"] = root_emp_name
                if not norm.get("indo_code") and root_emp_code:
                    norm["indo_code"] = root_emp_code
                if root_submit_status in ("1", "2", "true", "True") or is_server_submitted:
                    norm["submit_status"] = "1"
                    norm["status"] = "Completed"
                elif not norm.get("submit_status") and root_submit_status:
                    norm["submit_status"] = root_submit_status
                normalized.append(norm)

        if any(t.get("submit_status") in ("1", "2", "true", "True") or str(t.get("status")).lower() in ("completed", "submitted") for t in normalized if not t.get("is_additional")):
            self._submitted_dates.add(date_key)

        logger.info(
            "Task API parse: raw_items=%d  normalized=%d  date=%s  response_status=%s",
            len(raw_items),
            len(normalized),
            date_key,
            res_json.get("status") if isinstance(res_json, dict) else "n/a",
        )

        # Also check additional_task if provided
        if isinstance(res_json, dict):
            add_task = (
                res_json.get("additional_task")
                or data_dict.get("additional_task")
                or res_json.get("additionalTask")
                or data_dict.get("additionalTask")
                or res_json.get("daily_task")
                or data_dict.get("daily_task")
                or res_json.get("daily_activity")
                or data_dict.get("daily_activity")
            )
            if add_task and str(add_task).strip() and str(add_task).strip().lower() not in ("none", "null"):
                add_status_val = str(
                    res_json.get("additional_task_status")
                    or data_dict.get("additional_task_status")
                    or res_json.get("additionalTaskStatus")
                    or data_dict.get("additionalTaskStatus")
                    or res_json.get("submit_status")
                    or data_dict.get("submit_status")
                    or ""
                ).strip()
                is_add_sub = (
                    add_status_val in ("1", "2", "true", "True")
                    or str(add_status_val).lower() in ("completed", "submitted")
                    or date_key in self._submitted_additional_dates
                    or is_server_submitted
                )
                if is_add_sub:
                    self.mark_additional_task_submitted(date_key)
                add_status = "Completed" if is_add_sub else "In Progress"
                normalized.append({
                    "id": "add_task_1",
                    "kra_id": "",
                    "timesheet_id": "",
                    "title": "Daily Activity / Additional Task",
                    "description": str(add_task).strip(),
                    "remark": str(add_task).strip(),
                    "task_completed": "1" if is_add_sub else "0",
                    "status": add_status,
                    "submit_status": "1" if is_add_sub else "0",
                    "additional_task_status": "1" if is_add_sub else add_status_val,
                    "date": date_key,
                    "weightage": "-",
                    "is_additional": True,
                    "raw": res_json,
                })

        # ── Resolve Task Done Till Now Baseline Progress ────────────────────────
        # On unsubmitted dates, get_kra returns task_done: null because no daily
        # record exists yet. Query prior submitted/drafted timesheets to resolve
        # the employee's latest cumulative progress for each KRA.
        # ──────────────────────────────────────────────────────────────────────
        kra_tasks_needing_done = [
            t
            for t in normalized
            if not t.get("is_additional")
            and not t.get("timesheet_id")
            and (
                t.get("task_done") == "-"
                or t.get("task_done") is None
                or str(t.get("task_done")).strip() in ("None", "null", "")
            )
        ]
        if kra_tasks_needing_done and resolved_indo and resolved_key:
            baseline_map = self._fetch_baseline_task_done_map(
                target_date=date_key,
                indo_code=resolved_indo,
                key=resolved_key,
            )
            if baseline_map:
                for t in kra_tasks_needing_done:
                    kid = str(t.get("kra_id") or "").strip()
                    kname = str(t.get("name") or t.get("title") or "").strip()
                    val = baseline_map.get(kid) or baseline_map.get(kname)
                    if val is not None and str(val).strip() not in ("None", "null", "", "-"):
                        t["task_done"] = str(val).strip()
                        t["task_done_till_now"] = str(val).strip()

        # ── KRA date-cycle fallback ────────────────────────────────────────────
        # The backend KRA system assigns tasks to specific cycle dates (not to
        # today's calendar date). When the response status is 2 (no KRA found
        # for the requested date) AND the caller did not pass an explicit date,
        # ask the get_draft_kra_date endpoint for the active KRA cycle date and
        # retry get_kra with that date.  This is the standard flow the backend
        # expects.  Skip the retry when a date was explicitly supplied by the
        # caller, because that means a different subsystem is in control.
        # ──────────────────────────────────────────────────────────────────────
        api_status = res_json.get("status") if isinstance(res_json, dict) else None
        caller_gave_date = date is not None
        if (
            not normalized
            and api_status == 2
            and not caller_gave_date
        ):
            kra_cycle_date = self._resolve_kra_cycle_date(
                resolved_indo, resolved_key
            )
            if kra_cycle_date and kra_cycle_date != date_key:
                logger.info(
                    "KRA cycle date resolved to %s (today=%s); retrying get_kra.",
                    kra_cycle_date,
                    date_key,
                )
                # Delegate to a fresh call with the resolved cycle date.
                # Pass force=True so the cache for the new date is populated
                # even if it was fetched recently (unlikely on first login).
                return self.fetch_assigned_tasks(
                    date=kra_cycle_date,
                    indo_code=resolved_indo,
                    key=resolved_key,
                    force=force,
                )

        with self._state_lock:
            self._last_fetch_ts[date_key] = current_ts
            self._cached_tasks[date_key] = normalized
            self._last_error = None

        return list(normalized)

    def save_time_sheet(
        self,
        kra_list: List[Dict[str, Any]],
        date: Optional[str] = None,
        submit_status: str = "0",
        indo_code: Optional[str] = None,
        key: Optional[str] = None,
    ) -> tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Save/fill timesheet for KRA tasks.

        API Contract:
          Endpoint: TaskPMS/fill_time_sheet
          Method: POST (JSON body)
          Headers: Content-Type: application/json
          JSON Payload:
            {
              "key": "<api_key>",
              "indo_code": "<indo_code>",
              "date": "<YYYY-MM-DD>",
              "submit_status": "<0 or 1>",
              "kraList": [
                {
                  "TimeSheet_id": "<timesheet_id>",
                  "kra_id": "<kra_id>",
                  "remark": "<remark>",
                  "task_completed": "<0 or 1>"
                }
              ]
            }
        """
        now_dt = datetime.now().astimezone()
        date_val = str(date or now_dt.strftime("%Y-%m-%d")).strip()

        resolved_indo, resolved_key = self._resolve_auth_credentials(
            indo_code=indo_code, key=key
        )

        if not resolved_indo:
            return False, "User not logged in or employee code missing.", None

        # Build clean kraList according to API specification
        formatted_kra_list: List[Dict[str, str]] = []
        for item in kra_list:
            if not isinstance(item, dict):
                continue
            ts_id = str(
                item.get("TimeSheet_id")
                or item.get("timesheet_id")
                or item.get("time_sheet_id")
                or item.get("timesheetId")
                or item.get("ts_id")
                or ""
            ).strip()
            k_id = str(
                item.get("kra_id")
                or item.get("id")
                or item.get("task_id")
                or ""
            ).strip()
            rem = str(
                item.get("remark")
                or item.get("employee_remark")
                or item.get("task_remark")
                or item.get("notes")
                or item.get("description")
                or ""
            ).strip()
            raw_comp = item.get("task_completed")
            if raw_comp is not None and str(raw_comp).strip() != "":
                comp = str(raw_comp).strip()
            elif str(item.get("status")).strip().lower() in ("completed", "done", "closed"):
                comp = "1"
            else:
                comp = "0"

            formatted_kra_list.append({
                "TimeSheet_id": ts_id,
                "kra_id": k_id,
                "remark": rem,
                "task_completed": comp,
            })

        if not formatted_kra_list:
            return False, "No KRA items provided to save.", None

        fill_url = self._resolve_fill_timesheet_url()

        if not fill_url:
            return False, "Fill timesheet API endpoint not configured.", None

        payload = {
            "key": str(resolved_key),
            "indo_code": str(resolved_indo),
            "date": str(date_val),
            "submit_status": str(submit_status),
            "kraList": formatted_kra_list,
        }

        logger.info(
            "Calling Fill Timesheet API: url=%s payload=%s",
            fill_url,
            {**payload, "key": "***"},
        )

        try:
            resp = requests.post(
                fill_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=15,
            )
            logger.info(
                "Fill Timesheet API response: HTTP %d %s",
                resp.status_code,
                resp.text[:500],
            )
            resp.raise_for_status()
            res_json = resp.json()
        except Exception as api_err:
            logger.warning("Fill Timesheet API call failed: %s", api_err)
            return False, f"Failed to save timesheet: {api_err}", None

        # Invalidate task cache for this date so next fetch gets fresh data
        with self._state_lock:
            self._cached_tasks.pop(date_val, None)
            self._last_fetch_ts.pop(date_val, None)

        msg = "Timesheet saved successfully."
        if isinstance(res_json, dict):
            resp_status = res_json.get("status")
            resp_msg = res_json.get("message") or res_json.get("response") or msg
            is_already_sub = (
                str(resp_status) == "2"
                or "already submitted" in str(resp_msg).lower()
                or bool(res_json.get("is_already_submitted"))
            )
            if is_already_sub:
                res_json["is_already_submitted"] = True
                self.mark_timesheet_submitted(date_val)
                return True, str(resp_msg or "Timesheet already submitted"), res_json

            if str(resp_status) in ("1", "200", "True", "true") or str(res_json.get("response")).lower() in ("success", "200"):
                if str(submit_status) == "1":
                    self.mark_timesheet_submitted(date_val)
                elif str(submit_status) == "0":
                    self.unmark_timesheet_submitted(date_val)
                return True, str(resp_msg), res_json
            elif resp_status is not None and str(resp_status) not in ("1", "200"):
                return False, str(resp_msg or f"Server returned status {resp_status}"), res_json

            if str(submit_status) == "1":
                self.mark_timesheet_submitted(date_val)
            return True, str(resp_msg), res_json

        if str(submit_status) == "1":
            self.mark_timesheet_submitted(date_val)
        return True, msg, res_json if isinstance(res_json, dict) else {}

    def save_additional_task(
        self,
        task: str,
        date: Optional[str] = None,
        status: Any = 1,
        indo_code: Optional[str] = None,
        key: Optional[str] = None,
    ) -> tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Save additional task / daily activity.

        API Contract:
          Endpoint: TaskPMS/save_additional_task
          Method: POST
          Data:
            key: <api_key>
            indo_code: <indo_code>
            date: <YYYY-MM-DD>
            status: 1
            task: <task description>
        """
        now_dt = datetime.now().astimezone()
        date_val = str(date or now_dt.strftime("%Y-%m-%d")).strip()

        if not task or not str(task).strip():
            return False, "Task description cannot be empty.", None

        resolved_indo, resolved_key = self._resolve_auth_credentials(
            indo_code=indo_code, key=key
        )

        if not resolved_indo:
            return False, "User not logged in or employee code missing.", None

        save_url = self._resolve_save_additional_task_url()

        if not save_url:
            return False, "Save additional task API endpoint not configured.", None

        multipart_data = {
            "key": (None, str(resolved_key)),
            "indo_code": (None, str(resolved_indo)),
            "date": (None, str(date_val)),
            "status": (None, str(status)),
            "task": (None, str(task).strip()),
        }

        logger.info(
            "Calling Save Additional Task API: url=%s fields=%s",
            save_url,
            {k: ("***" if k == "key" else v[1]) for k, v in multipart_data.items()},
        )

        try:
            resp = requests.post(
                save_url,
                files=multipart_data,
                timeout=15,
            )
            logger.info(
                "Save Additional Task API response: HTTP %d %s",
                resp.status_code,
                resp.text[:500],
            )
            if resp.status_code >= 400:
                err_detail = f"HTTP {resp.status_code}"
                try:
                    err_json = resp.json()
                    if isinstance(err_json, dict):
                        m = err_json.get("message") or err_json.get("title")
                        if m:
                            err_detail += f": {m}"
                except Exception:
                    pass
                return False, f"Server error ({err_detail})", None

            res_json = resp.json()
        except Exception as api_err:
            logger.warning("Save Additional Task API call failed: %s", api_err)
            return False, f"Failed to save additional task: {api_err}", None

        # Invalidate task cache for this date
        with self._state_lock:
            self._cached_tasks.pop(date_val, None)
            self._last_fetch_ts.pop(date_val, None)

        msg = "Additional task saved successfully."
        if isinstance(res_json, dict):
            resp_status = str(res_json.get("status") or "").strip()
            resp_msg = str(res_json.get("message") or res_json.get("response") or msg).strip()
            resp_code = str(res_json.get("response") or "").strip()

            is_already_sub = (
                resp_status == "2"
                or "already submitted" in resp_msg.lower()
            )
            is_new_saved = (
                resp_status == "1"
                or "successfully saved" in resp_msg.lower()
                or (resp_code in ("200", "success") and not is_already_sub)
            )

            result_data = {
                **res_json,
                "is_newly_saved": is_new_saved and not is_already_sub,
                "is_already_submitted": is_already_sub,
            }

            if is_already_sub:
                self.mark_additional_task_submitted(date_val)
                return True, resp_msg or "Task already submitted", result_data
            elif is_new_saved:
                if str(status) in ("1", 1):
                    self.mark_additional_task_submitted(date_val)
                elif str(status) in ("0", 0):
                    self.unmark_additional_task_submitted(date_val)
                return True, resp_msg or "Task successfully saved", result_data
            elif resp_status and resp_status not in ("1", "2", "200"):
                return False, resp_msg or f"Server returned status {resp_status}", result_data

            if str(status) in ("1", 1):
                self.mark_additional_task_submitted(date_val)
            return True, resp_msg, result_data

        if str(status) in ("1", 1):
            self.mark_additional_task_submitted(date_val)
        return True, msg, res_json if isinstance(res_json, dict) else {}

    # ------------------------------------------------------------------
    # KRA cycle date resolution
    # ------------------------------------------------------------------

    def _resolve_kra_cycle_date(
        self,
        indo_code: str,
        key: str,
        month: Optional[str] = None,
        year: Optional[str] = None,
    ) -> Optional[str]:
        """
        Query get_draft_kra_date (and fall back to get_submit_kra_date_v2) to
        find the active KRA cycle date for this employee.

        Returns a ``YYYY-MM-DD`` string on success, or ``None`` on any failure.
        The date is extracted from the first ``date`` / ``kra_date`` /
        ``assigned_date`` field found in the response body.
        """
        date_apis: list[tuple[str, str]] = []

        draft_url = self._resolve_draft_kra_date_url()
        if draft_url:
            date_apis.append(("draft_kra_date", draft_url))

        submit_url = self._resolve_submit_kra_date_url()
        if submit_url:
            date_apis.append(("submit_kra_date", submit_url))

        if not date_apis:
            logger.debug("_resolve_kra_cycle_date: no date-discovery API available.")
            return None

        now_dt = datetime.now().astimezone()
        month_str = month or now_dt.strftime("%B")
        year_str = str(year or now_dt.year)

        payload = {
            "key": key,
            "indo_code": indo_code,
            "month": month_str,
            "year": year_str,
        }

        for api_name, api_url in date_apis:
            try:
                logger.info(
                    "Querying %s for active KRA cycle date: url=%s",
                    api_name,
                    api_url,
                )
                r = requests.post(api_url, data=payload, timeout=8)
                logger.info(
                    "%s response: HTTP %d %s",
                    api_name,
                    r.status_code,
                    r.text[:500],
                )
                r.raise_for_status()
                body = r.json()

                # Extract a date string from various possible fields
                candidate: Optional[str] = None
                if isinstance(body, dict):
                    candidate = (
                        body.get("date")
                        or body.get("kra_date")
                        or body.get("assigned_date")
                        or body.get("draft_date")
                        or body.get("submit_date")
                    )
                    # Also support submit_kra_date array or data array
                    if not candidate and isinstance(body.get("submit_kra_date"), list) and body["submit_kra_date"]:
                        last_elem = body["submit_kra_date"][-1]
                        if isinstance(last_elem, str):
                            candidate = last_elem
                        elif isinstance(last_elem, dict):
                            candidate = last_elem.get("task_date") or last_elem.get("date")
                    # Sometimes the date is nested inside data/kra_date_data
                    if not candidate and isinstance(body.get("data"), dict):
                        d = body["data"]
                        candidate = (
                            d.get("date")
                            or d.get("kra_date")
                            or d.get("assigned_date")
                            or d.get("task_date")
                        )
                    if not candidate and isinstance(body.get("data"), list) and body["data"]:
                        last_row = body["data"][-1]
                        if isinstance(last_row, dict):
                            candidate = (
                                last_row.get("date")
                                or last_row.get("kra_date")
                                or last_row.get("assigned_date")
                                or last_row.get("task_date")
                            )
                        elif isinstance(last_row, str):
                            candidate = last_row
                elif isinstance(body, list) and body:
                    last_row = body[-1]
                    if isinstance(last_row, dict):
                        candidate = (
                            last_row.get("date")
                            or last_row.get("kra_date")
                            or last_row.get("assigned_date")
                            or last_row.get("task_date")
                        )
                    elif isinstance(last_row, str):
                        candidate = last_row

                if candidate:
                    candidate = str(candidate).strip()
                    # Normalise to YYYY-MM-DD (drop time portion if present)
                    if len(candidate) >= 10 and candidate[4] == "-" and candidate[7] == "-":
                        kra_date = candidate[:10]
                        logger.info(
                            "Active KRA cycle date from %s: %s", api_name, kra_date
                        )
                        return kra_date
            except Exception as err:
                logger.debug("%s query failed: %s", api_name, err)

        logger.info(
            "_resolve_kra_cycle_date: no date found from any date-discovery API."
        )
        return None

    def _fetch_baseline_task_done_map(
        self,
        target_date: str,
        indo_code: str,
        key: str,
    ) -> Dict[str, str]:
        """
        Query prior submitted and drafted timesheet dates for the employee to
        resolve the baseline cumulative progress (Task Done Till Now) for each KRA.
        Returns a mapping from kra_id (and task title) to the latest valid task_done value.
        """
        cache_key = f"{indo_code}::{target_date}"
        with self._state_lock:
            if cache_key in self._baseline_done_cache:
                return dict(self._baseline_done_cache[cache_key])

        baseline_map: Dict[str, str] = {}
        try:
            target_dt = datetime.strptime(target_date, "%Y-%m-%d")
        except Exception:
            return baseline_map

        month_str = target_dt.strftime("%B")
        year_str = str(target_dt.year)

        candidate_dates: set[str] = set()

        def _collect_dates(m: str, y: str) -> None:
            submit_url = self._resolve_submit_kra_date_url()
            if submit_url:
                try:
                    payload = {
                        "key": key,
                        "indo_code": indo_code,
                        "month": m,
                        "year": y,
                    }
                    r = requests.post(submit_url, data=payload, timeout=8)
                    if r.status_code == 200:
                        data = r.json()
                        dates = data.get("submit_kra_date") or data.get("data") or []
                        for d in dates:
                            if isinstance(d, str) and len(d) >= 10:
                                candidate_dates.add(d[:10])
                            elif isinstance(d, dict):
                                dv = d.get("task_date") or d.get("date")
                                if dv and len(str(dv)) >= 10:
                                    candidate_dates.add(str(dv)[:10])
                except Exception as e:
                    logger.debug("Failed querying submit_kra_date for baseline: %s", e)

            draft_url = self._resolve_draft_kra_date_url()
            if draft_url:
                try:
                    payload = {
                        "key": key,
                        "indo_code": indo_code,
                        "month": m,
                        "year": y,
                    }
                    r = requests.post(draft_url, data=payload, timeout=8)
                    if r.status_code == 200:
                        data = r.json()
                        rows = data.get("submit_kra_date") or data.get("data") or []
                        for row in rows:
                            if isinstance(row, dict):
                                dv = row.get("task_date") or row.get("date")
                                if dv and len(str(dv)) >= 10:
                                    candidate_dates.add(str(dv)[:10])
                            elif isinstance(row, str) and len(row) >= 10:
                                candidate_dates.add(row[:10])
                except Exception as e:
                    logger.debug("Failed querying draft_kra_date for baseline: %s", e)

        _collect_dates(month_str, year_str)

        prior_dates = sorted([d for d in candidate_dates if d < target_date], reverse=True)
        if not prior_dates and target_dt.day <= 7:
            # Check previous month if near start of current month
            prev_month_dt = target_dt.replace(day=1) - timedelta(days=1)
            _collect_dates(prev_month_dt.strftime("%B"), str(prev_month_dt.year))
            prior_dates = sorted([d for d in candidate_dates if d < target_date], reverse=True)

        kra_url = self._resolve_kra_url()
        if kra_url and prior_dates:
            for p_date in prior_dates:
                try:
                    p_payload = {
                        "key": key,
                        "indo_code": indo_code,
                        "date": p_date,
                    }
                    r_p = requests.post(kra_url, data=p_payload, timeout=8)
                    if r_p.status_code == 200:
                        p_json = r_p.json()
                        items: List[Any] = []
                        if isinstance(p_json, dict):
                            items = p_json.get("emp_kra") or p_json.get("kra_list") or p_json.get("data") or []
                        elif isinstance(p_json, list):
                            items = p_json

                        for item in items:
                            if not isinstance(item, dict):
                                continue
                            kid = str(item.get("kra_id") or item.get("id") or "").strip()
                            kname = str(item.get("name") or item.get("title") or item.get("task_name") or "").strip()
                            raw_done = item.get("task_done")
                            if raw_done is None:
                                raw_done = item.get("task_done_till_now")
                            if raw_done is None:
                                raw_done = item.get("taskDoneTillNow")
                            if raw_done is None:
                                raw_done = item.get("taskDone")
                            if raw_done is None:
                                raw_done = item.get("done_till_now")
                            if raw_done is None:
                                raw_done = item.get("task_progress")
                            if raw_done is None:
                                raw_done = item.get("progress")
                            if raw_done is None:
                                raw_done = item.get("hours_done")
                            if raw_done is None:
                                raw_done = item.get("total_done")
                            if raw_done is None:
                                raw_done = item.get("completed_till_now")

                            if raw_done is not None and str(raw_done).strip() not in ("None", "null", "", "-"):
                                val_str = str(raw_done).strip()
                                if kid and kid not in baseline_map:
                                    baseline_map[kid] = val_str
                                if kname and kname not in baseline_map:
                                    baseline_map[kname] = val_str

                        if baseline_map:
                            break
                except Exception as p_err:
                    logger.debug("Failed querying get_kra on prior date %s: %s", p_date, p_err)

        with self._state_lock:
            self._baseline_done_cache[cache_key] = baseline_map

        return baseline_map


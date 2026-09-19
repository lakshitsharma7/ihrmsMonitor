"""Service for fetching and managing Assigned Tasks / KRAs."""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime
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
            self._last_error = None

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

        # Resolve task completion numeric value and status
        raw_completed = item.get("task_completed")
        if raw_completed is not None and str(raw_completed).strip() not in ("None", "null", ""):
            task_completed_str = str(raw_completed).strip()
        else:
            task_completed_str = ""

        # Resolve status cleanly
        raw_status = (
            item.get("status")
            or item.get("task_status")
            or item.get("kra_status")
            or item.get("state")
        )
        if raw_status:
            status = str(raw_status).strip()
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

        date_val = str(
            item.get("date")
            or item.get("assigned_date")
            or item.get("due_date")
            or item.get("target_date")
            or item.get("created_at")
            or default_date
        ).strip()

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

        target = str(
            item.get("target")
            or item.get("target_criteria")
            or item.get("target_value")
            or item.get("target_date")
            or "-"
        ).strip()

        measurement_criteria = str(
            item.get("measurement_criteria")
            or item.get("measurement")
            or item.get("criteria")
            or item.get("kpi")
            or "-"
        ).strip()

        task_done = str(
            item.get("task_done")
            or item.get("task_done_till_now")
            or item.get("progress")
            or item.get("hours_done")
            or "-"
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
            "remark": remark,
            "comment": remark,
            "date": date_val,
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
        date_key = str(date or now_dt.strftime("%Y-%m-%d")).strip()

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

        # Resolve endpoint URL from ApiConfig
        try:
            kra_url = ApiConfig().get_kra_url
        except Exception as config_err:
            logger.debug("TaskService: could not resolve get_kra_url from ApiConfig: %s", config_err)
            kra_url = None

        if not kra_url:
            kra_url = os.environ.get("IHRMS_GET_KRA_API_URL")

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
            # Check emp_kra, data, tasks, or kra array
            if isinstance(res_json.get("emp_kra"), list):
                raw_items = res_json["emp_kra"]
            elif isinstance(res_json.get("data"), list):
                raw_items = res_json["data"]
            elif isinstance(res_json.get("tasks"), list):
                raw_items = res_json["tasks"]
            elif isinstance(res_json.get("kra"), list):
                raw_items = res_json["kra"]
            elif isinstance(res_json.get("data"), dict):
                raw_items = [res_json["data"]]
            elif any(k in res_json for k in ("kra_id", "task_id", "task_name", "kra_name", "title")):
                raw_items = [res_json]

        normalized: List[Dict[str, Any]] = []
        for raw in raw_items:
            norm = self._normalize_task_item(raw, default_date=date_key)
            if norm:
                normalized.append(norm)

        logger.info(
            "Task API parse: raw_items=%d  normalized=%d  date=%s  response_status=%s",
            len(raw_items),
            len(normalized),
            date_key,
            res_json.get("status") if isinstance(res_json, dict) else "n/a",
        )

        # Also check additional_task if provided
        if isinstance(res_json, dict):
            add_task = res_json.get("additional_task")
            if add_task and str(add_task).strip() and str(add_task).strip().lower() not in ("none", "null"):
                add_status_val = str(res_json.get("additional_task_status") or "").strip()
                add_status = "Completed" if add_status_val in ("1", "true", "True") else "In Progress"
                normalized.append({
                    "id": "add_task_1",
                    "kra_id": "",
                    "timesheet_id": "",
                    "title": "Daily Activity / Additional Task",
                    "description": str(add_task).strip(),
                    "remark": str(add_task).strip(),
                    "task_completed": "1" if add_status_val in ("1", "true", "True") else "0",
                    "status": add_status,
                    "date": date_key,
                    "weightage": "-",
                    "is_additional": True,
                    "raw": res_json,
                })

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

        try:
            fill_url = ApiConfig().fill_time_sheet_url
        except Exception as config_err:
            logger.debug("TaskService: could not resolve fill_time_sheet_url: %s", config_err)
            fill_url = None

        if not fill_url:
            fill_url = os.environ.get("IHRMS_FILL_TIME_SHEET_API_URL")

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
            if str(resp_status) in ("1", "200", "True", "true") or str(res_json.get("response")).lower() in ("success", "200"):
                return True, str(resp_msg), res_json
            elif resp_status is not None and str(resp_status) not in ("1", "200"):
                return False, str(resp_msg or f"Server returned status {resp_status}"), res_json
            return True, str(resp_msg), res_json

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

        try:
            save_url = ApiConfig().save_additional_task_url
        except Exception as config_err:
            logger.debug("TaskService: could not resolve save_additional_task_url: %s", config_err)
            save_url = None

        if not save_url:
            save_url = os.environ.get("IHRMS_SAVE_ADDITIONAL_TASK_API_URL")

        if not save_url:
            return False, "Save additional task API endpoint not configured.", None

        req_data = {
            "key": str(resolved_key),
            "indo_code": str(resolved_indo),
            "date": str(date_val),
            "status": str(status),
            "task": str(task).strip(),
        }

        logger.info(
            "Calling Save Additional Task API: url=%s data=%s",
            save_url,
            {**req_data, "key": "***"},
        )

        try:
            resp = requests.post(
                save_url,
                data=req_data,
                timeout=15,
            )
            logger.info(
                "Save Additional Task API response: HTTP %d %s",
                resp.status_code,
                resp.text[:500],
            )
            resp.raise_for_status()
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
            resp_status = res_json.get("status")
            resp_msg = res_json.get("message") or res_json.get("response") or msg
            if str(resp_status) in ("1", "200", "True", "true") or str(res_json.get("response")).lower() in ("success", "200"):
                return True, str(resp_msg), res_json
            elif resp_status is not None and str(resp_status) not in ("1", "200"):
                return False, str(resp_msg or f"Server returned status {resp_status}"), res_json
            return True, str(resp_msg), res_json

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

        try:
            draft_url = ApiConfig().get_draft_kra_date_url
            if draft_url:
                date_apis.append(("draft_kra_date", draft_url))
        except Exception:
            pass

        try:
            submit_url = ApiConfig().get_submit_kra_date_url
            if submit_url:
                date_apis.append(("submit_kra_date", submit_url))
        except Exception:
            pass

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
                    # Sometimes the date is nested inside data/kra_date_data
                    if not candidate and isinstance(body.get("data"), dict):
                        d = body["data"]
                        candidate = (
                            d.get("date")
                            or d.get("kra_date")
                            or d.get("assigned_date")
                        )
                    if not candidate and isinstance(body.get("data"), list) and body["data"]:
                        first = body["data"][0]
                        if isinstance(first, dict):
                            candidate = (
                                first.get("date")
                                or first.get("kra_date")
                                or first.get("assigned_date")
                            )
                elif isinstance(body, list) and body:
                    first = body[0]
                    if isinstance(first, dict):
                        candidate = (
                            first.get("date")
                            or first.get("kra_date")
                            or first.get("assigned_date")
                        )
                    elif isinstance(first, str):
                        candidate = first

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


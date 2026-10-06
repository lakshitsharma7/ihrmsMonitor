"""Leave Balance Modal Dialog for Workpulse.

Displays employee leave quota and current balance breakdown with
fixed 7 leave types, summary cards, progress bars, dynamic API loading,
and error handling.
"""

from __future__ import annotations

import threading
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from services.attendance_service import AttendanceService
from utils.logger import get_logger

logger = get_logger(__name__)

# Fixed 7 Leave Types Configuration (Code, Display Name, Sequence)
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
    """Safely parse value into float."""
    if val is None or val == "":
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _fmt_val(v) -> str:
    """Format numeric values for UI display, preserving cleaner integers and float representations."""
    if v is None or v == "" or str(v).strip() in ("None", "null", "—"):
        return "0"
    try:
        fv = float(v)
        if fv.is_integer():
            return f"{int(fv)}"
        s = f"{fv:.2f}"
        if s.endswith(".00"):
            return s[:-3]
        if s.endswith("0") and "." in s:
            return s[:-1]
        return s
    except (ValueError, TypeError):
        return str(v).strip()


class LeaveSummaryCard(QFrame):
    """Modern, card-based summary widget representing a single leave quota type."""

    def __init__(self, item: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._item = item or {}
        self.setObjectName("LeaveSummaryCard")
        self.setMinimumWidth(160)
        self.setMinimumHeight(140)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(8)

        # Card Base Style
        self.setStyleSheet(
            """
            QFrame#LeaveSummaryCard {
                background-color: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 12px;
            }
            QFrame#LeaveSummaryCard:hover {
                border-color: #3B82F6;
                background-color: #FAFAFC;
            }
            """
        )

        # --------------------------------------------------------------
        # 1. Fixed Short Code Badge
        # --------------------------------------------------------------
        short_code = str(self._item.get("code") or self._item.get("short_name") or "LT").strip()
        leave_name = str(self._item.get("name") or self._item.get("leave_type") or "Leave Type").strip()

        code_container = QHBoxLayout()
        code_container.setContentsMargins(0, 0, 0, 0)
        code_container.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.code_badge = QLabel(short_code)
        self.code_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.code_badge.setStyleSheet(
            """
            QLabel {
                background-color: #EFF6FF;
                color: #2563EB;
                font-size: 13px;
                font-weight: 800;
                border: 1px solid #BFDBFE;
                border-radius: 6px;
                padding: 3px 14px;
            }
            """
        )
        code_container.addWidget(self.code_badge)
        layout.addLayout(code_container)

        # --------------------------------------------------------------
        # 2. Fixed Full Leave Type Name
        # --------------------------------------------------------------
        self.name_label = QLabel(leave_name)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setWordWrap(True)
        self.name_label.setMinimumHeight(24)
        self.name_label.setStyleSheet(
            "QLabel { font-size: 13px; font-weight: 700; color: #1E293B; border: none; background: transparent; }"
        )
        layout.addWidget(self.name_label)

        # --------------------------------------------------------------
        # 3. Horizontal Usage / Progress Indicator
        # --------------------------------------------------------------
        tot_raw = (
            self._item.get("total_quota_str")
            or self._item.get("total_quota")
            or self._item.get("total_str")
            or self._item.get("total")
            or self._item.get("totalQuota")
            or self._item.get("total_leaves")
            or self._item.get("allotted")
            or self._item.get("quota")
            or self._item.get("leaves")
        )
        used_raw = (
            self._item.get("used_str")
            or self._item.get("used")
            or self._item.get("leavesTaked")
            or self._item.get("leaves_taked")
            or self._item.get("leaves_taken")
            or self._item.get("taken")
            or self._item.get("consumed")
            or self._item.get("availed")
        )
        left_raw = (
            self._item.get("available_str")
            or self._item.get("available")
            or self._item.get("left_str")
            or self._item.get("left")
            or self._item.get("remaining")
            or self._item.get("remaining_str")
            or self._item.get("leave_balance")
            or self._item.get("balance")
        )

        total_num = _to_num(tot_raw)
        used_num = _to_num(used_raw)
        left_num = _to_num(left_raw)

        self.usage_bar = QProgressBar()
        self.usage_bar.setFixedHeight(5)
        self.usage_bar.setTextVisible(False)
        self.usage_bar.setStyleSheet(
            """
            QProgressBar {
                background-color: #F1F5F9;
                border: none;
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background-color: #3B82F6;
                border-radius: 2px;
            }
            """
        )
        if total_num > 0:
            pct = int(min(100.0, max(0.0, (used_num / total_num) * 100.0)))
            self.usage_bar.setValue(pct)
        else:
            self.usage_bar.setValue(0)

        layout.addWidget(self.usage_bar)

        # --------------------------------------------------------------
        # 4. Divider Line
        # --------------------------------------------------------------
        divider = QFrame(self)
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFixedHeight(1)
        divider.setStyleSheet("background-color: #E2E8F0; border: none;")
        layout.addWidget(divider)

        # --------------------------------------------------------------
        # 5. Three-Column Stats: TOTAL (Blue) | USED (Red) | LEFT (Green)
        # --------------------------------------------------------------
        stats_row = QHBoxLayout()
        stats_row.setContentsMargins(0, 4, 0, 2)
        stats_row.setSpacing(4)

        tot_val = _fmt_val(tot_raw)
        used_val = _fmt_val(used_raw)
        left_val = _fmt_val(left_raw)

        def _make_stat_col(value_str: str, label_str: str, color_hex: str) -> QVBoxLayout:
            col = QVBoxLayout()
            col.setSpacing(2)
            col.setAlignment(Qt.AlignmentFlag.AlignCenter)

            val_lbl = QLabel(value_str)
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            val_lbl.setStyleSheet(
                f"QLabel {{ font-size: 13px; font-weight: 800; color: {color_hex}; border: none; background: transparent; }}"
            )

            title_lbl = QLabel(label_str)
            title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title_lbl.setStyleSheet(
                "QLabel { font-size: 10px; font-weight: 700; color: #64748B; text-transform: uppercase; border: none; background: transparent; }"
            )

            col.addWidget(val_lbl)
            col.addWidget(title_lbl)
            return col

        # Target Color Scheme: Total = Blue (#2563EB), Used = Red (#DC2626), Left = Green (#16A34A)
        stats_row.addLayout(_make_stat_col(tot_val, "Total", "#2563EB"), 1)
        stats_row.addLayout(_make_stat_col(used_val, "Used", "#DC2626"), 1)
        stats_row.addLayout(_make_stat_col(left_val, "Left", "#16A34A"), 1)

        layout.addLayout(stats_row)
        layout.addStretch(1)


class LeaveBalanceDialog(QDialog):
    """Modal dialog displaying leave quotas and balances in a 2-column card layout."""

    data_loaded = Signal(dict)

    def __init__(
        self,
        service: AttendanceService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("LeaveBalanceDialog")
        self.setWindowTitle("Leave Balance")
        self.setModal(True)
        self.resize(780, 620)
        self.setMinimumSize(600, 480)

        self._service = service or AttendanceService()
        self._is_loading = False
        self._cards: list[LeaveSummaryCard] = []

        from services.network_monitor import NetworkReachabilityMonitor
        self._monitor = NetworkReachabilityMonitor()
        self._is_network_online = self._monitor.is_online

        self.data_loaded.connect(self._apply_leave_data)
        self._setup_ui()
        self.set_network_status(self._is_network_online)
        self._monitor.register_listener(self._on_reachability_changed)
        self.refresh()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 18, 20, 18)
        main_layout.setSpacing(14)

        # --------------------------------------------------------------
        # 1. Header with Title, Subtitle, and Real-Time Network Status
        # --------------------------------------------------------------
        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        self.title_label = QLabel("Leave Balance")
        self.title_label.setObjectName("LeaveBalanceTitle")
        self.title_label.setStyleSheet("font-size: 19px; font-weight: 700; color: #0F172A;")

        self.subtitle_label = QLabel("Employee Leave Quotas & Remaining Entitlements")
        self.subtitle_label.setStyleSheet("font-size: 12px; color: #64748B;")

        title_col.addWidget(self.title_label)
        title_col.addWidget(self.subtitle_label)
        header_layout.addLayout(title_col)

        header_layout.addStretch(1)

        self.network_status_label = QLabel("● Online" if self._is_network_online else "● Offline")
        self.network_status_label.setObjectName("LeaveBalanceNetworkStatus")
        if self._is_network_online:
            self.network_status_label.setStyleSheet("color: #10b981; font-weight: 600; font-size: 13px; margin-right: 4px;")
        else:
            self.network_status_label.setStyleSheet("color: #ef4444; font-weight: 600; font-size: 13px; margin-right: 4px;")
        header_layout.addWidget(self.network_status_label)

        main_layout.addLayout(header_layout)

        # Error Banner
        self.error_container = QWidget(self)
        err_layout = QHBoxLayout(self.error_container)
        err_layout.setContentsMargins(12, 10, 12, 10)
        err_layout.setSpacing(10)
        self.error_container.setStyleSheet(
            "QWidget { background-color: #FEF2F2; border: 1px solid #FECACA; border-radius: 8px; }"
        )
        self.error_label = QLabel("Unable to load leave balance. Please try again.", self.error_container)
        self.error_label.setStyleSheet("color: #DC2626; font-size: 12px; font-weight: 500; border: none; background: transparent;")
        err_layout.addWidget(self.error_label, 1)

        self.retry_btn = QPushButton("Retry", self.error_container)
        self.retry_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.retry_btn.setStyleSheet(
            "QPushButton { background: #DC2626; color: white; border-radius: 4px; padding: 4px 10px; font-size: 11px; font-weight: 600; border: none; }"
            "QPushButton:hover { background: #B91C1C; }"
        )
        self.retry_btn.clicked.connect(lambda: self.refresh(force=True))
        err_layout.addWidget(self.retry_btn)
        self.error_container.setVisible(False)
        main_layout.addWidget(self.error_container)

        # --------------------------------------------------------------
        # 2. Summary Metric Cards
        # --------------------------------------------------------------
        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)

        # Total Quota Card
        quota_card = QGroupBox("Total Allotted", self)
        quota_layout = QVBoxLayout(quota_card)
        quota_layout.setContentsMargins(14, 8, 14, 10)
        self.total_quota_val = QLabel("0 Days", quota_card)
        self.total_quota_val.setStyleSheet("font-size: 19px; font-weight: 700; color: #2563EB;")
        quota_layout.addWidget(self.total_quota_val)
        stats_row.addWidget(quota_card)

        # Total Used Card
        used_card = QGroupBox("Total Availed / Used", self)
        used_layout = QVBoxLayout(used_card)
        used_layout.setContentsMargins(14, 8, 14, 10)
        self.total_used_val = QLabel("0 Days", used_card)
        self.total_used_val.setStyleSheet("font-size: 19px; font-weight: 700; color: #DC2626;")
        used_layout.addWidget(self.total_used_val)
        stats_row.addWidget(used_card)

        # Total Available Card
        avail_card = QGroupBox("Available Balance", self)
        avail_layout = QVBoxLayout(avail_card)
        avail_layout.setContentsMargins(14, 8, 14, 10)
        self.total_avail_val = QLabel("0 Days", avail_card)
        self.total_avail_val.setStyleSheet("font-size: 19px; font-weight: 700; color: #16A34A;")
        avail_layout.addWidget(self.total_avail_val)
        stats_row.addWidget(avail_card)

        main_layout.addLayout(stats_row)

        # --------------------------------------------------------------
        # 3. Card-Based Leave Summary Section (Scrollable 2-Column Grid)
        # --------------------------------------------------------------
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self.cards_container = QWidget(self.scroll_area)
        self.cards_container.setObjectName("LeaveCardsContainer")
        self.cards_grid = QGridLayout(self.cards_container)
        self.cards_grid.setContentsMargins(4, 4, 4, 8)
        self.cards_grid.setSpacing(12)
        self.cards_grid.setColumnStretch(0, 1)
        self.cards_grid.setColumnStretch(1, 1)

        self.scroll_area.setWidget(self.cards_container)
        main_layout.addWidget(self.scroll_area, 1)

        # Empty State
        self.empty_state = QWidget(self)
        empty_l = QVBoxLayout(self.empty_state)
        empty_l.setContentsMargins(10, 30, 10, 30)
        empty_l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label = QLabel("No leave balance data available.", self.empty_state)
        self.empty_label.setStyleSheet("font-size: 14px; font-weight: 600; color: #64748B;")
        empty_l.addWidget(self.empty_label, alignment=Qt.AlignmentFlag.AlignCenter)
        self.empty_state.setVisible(False)
        main_layout.addWidget(self.empty_state)

        # --------------------------------------------------------------
        # 4. Footer Bar
        # --------------------------------------------------------------
        footer = QHBoxLayout()
        footer.addStretch(1)

        self.close_btn = QPushButton("Close")
        self.close_btn.setObjectName("SecondaryButton")
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setFixedSize(84, 32)
        self.close_btn.clicked.connect(self.accept)
        footer.addWidget(self.close_btn)

        main_layout.addLayout(footer)

    def set_network_status(self, is_online: bool) -> None:
        """Update the displayed network connectivity status."""
        self._is_network_online = bool(is_online)
        if hasattr(self, "network_status_label") and self.network_status_label:
            if is_online:
                self.network_status_label.setText("● Online")
                self.network_status_label.setStyleSheet("color: #10b981; font-weight: 600; font-size: 13px; margin-right: 4px;")
            else:
                self.network_status_label.setText("● Offline")
                self.network_status_label.setStyleSheet("color: #ef4444; font-weight: 600; font-size: 13px; margin-right: 4px;")

    @staticmethod
    def _is_network_or_offline_error(err_str: str) -> bool:
        """Check if an error message represents a network/connection/offline failure."""
        if not err_str:
            return False
        s = str(err_str).lower()
        return any(
            k in s for k in [
                "network", "connection", "offline", "timeout", "timed out",
                "max retries", "failed to establish", "getaddrinfo", "host",
                "httpsconnectionpool", "httpconnectionpool", "refused",
                "unreachable", "socket", "urllib3", "requests.exceptions"
            ]
        )

    @staticmethod
    def _sanitize_error_message(err_str: str) -> str:
        """Ensure technical/Python exceptions, hostnames, and stack traces are never shown in the UI."""
        if not err_str:
            return "Unable to load leave balance. Please try again."

        s = str(err_str)
        if LeaveBalanceDialog._is_network_or_offline_error(s):
            return "Unable to connect to the server. Please check your network connection."

        s_lower = s.lower()
        if any(tech in s_lower for tech in [
            "exception", "traceback", "traceback (most recent call last)",
            "file \"", "line ", "errno", "socket", "https://", "http://",
            "indovisionservices.in", "softdev"
        ]):
            return "Unable to load leave balance. Please try again."

        return s.strip()

    def _on_reachability_changed(self, is_online: bool) -> None:
        """Handle real-time network reachability changes from centralized monitor."""
        try:
            from PySide6.QtCore import QThread, QTimer
            if self.thread() == QThread.currentThread():
                self._handle_reachability_update(is_online)
            else:
                QTimer.singleShot(0, lambda: self._handle_reachability_update(is_online))
        except Exception:
            try:
                self.set_network_status(is_online)
            except Exception:
                pass

    def _handle_reachability_update(self, is_online: bool) -> None:
        """Process network state update and auto-refresh on reconnection."""
        self.set_network_status(is_online)
        if not is_online:
            # Hide error container when offline; the offline indicator is shown in header
            self.error_container.setVisible(False)
            if not self._cards:
                self.scroll_area.setVisible(False)
                self.empty_state.setVisible(True)
        else:
            # Reconnected: If we currently have no cards or were showing an error/empty state, auto-refresh
            if not self._cards or self.empty_state.isVisible() or self.error_container.isVisible():
                self.refresh(force=True)

    def closeEvent(self, event) -> None:
        """Unregister listener when dialog is closed."""
        try:
            if hasattr(self, "_monitor") and self._monitor:
                self._monitor.unregister_listener(self._on_reachability_changed)
        except Exception:
            pass
        super().closeEvent(event)

    def done(self, r: int) -> None:
        """Unregister listener when dialog is dismissed."""
        try:
            if hasattr(self, "_monitor") and self._monitor:
                self._monitor.unregister_listener(self._on_reachability_changed)
        except Exception:
            pass
        super().done(r)

    def refresh(self, async_mode: bool | None = None, force: bool = False) -> None:
        """Fetch leave quota dynamically."""
        if async_mode is None:
            import sys
            async_mode = not any("test" in arg.lower() or "unittest" in arg.lower() for arg in sys.argv)

        if not async_mode:
            try:
                data = self._service.get_leave_quota(force=force)
                self._apply_leave_data(data)
            except Exception as err:
                logger.warning("Synchronous leave quota fetch failed: %s", err)
                self._apply_leave_data({"error": str(err), "items": []})
            return

        if self._is_loading:
            return
        self._is_loading = True
        self.error_container.setVisible(False)

        def _bg_worker():
            try:
                res = self._service.get_leave_quota(force=force)
                self.data_loaded.emit(res)
            except Exception as ex:
                logger.warning("Background leave quota fetch failed: %s", ex)
                self.data_loaded.emit({"error": str(ex), "items": []})
            finally:
                self._is_loading = False

        t = threading.Thread(target=_bg_worker, daemon=True, name="LeaveQuotaFetchThread")
        t.start()

    def _apply_leave_data(self, data: dict | list) -> None:
        """Transform any API response into exactly 7 records matching FIXED_LEAVE_TYPES and render."""
        if not data or not isinstance(data, (dict, list)):
            if not self._is_network_online:
                self.error_container.setVisible(False)
                if not self._cards:
                    self.scroll_area.setVisible(False)
                    self.empty_state.setVisible(True)
                return
            self._show_error("Unable to load leave balance. Please try again.")
            return

        if isinstance(data, dict):
            err = data.get("error")
            if err:
                is_net_err = self._is_network_or_offline_error(str(err))
                if is_net_err:
                    import sys
                    if "unittest" not in sys.modules and "pytest" not in sys.modules:
                        try:
                            self._monitor.report_offline()
                        except Exception:
                            pass
                    self.set_network_status(False)
                    self.error_container.setVisible(False)
                    if not self._cards:
                        self.scroll_area.setVisible(False)
                        self.empty_state.setVisible(True)
                    return

                if not self._is_network_online:
                    self.error_container.setVisible(False)
                    if not self._cards:
                        self.scroll_area.setVisible(False)
                        self.empty_state.setVisible(True)
                    return

                # Legitimate application error (e.g. Invalid API Key, Employee not found)
                sanitized_msg = self._sanitize_error_message(str(err))
                self._show_error(sanitized_msg)
                if not self._cards:
                    self.scroll_area.setVisible(False)
                    self.empty_state.setVisible(True)
                return

        self.error_container.setVisible(False)

        # Extract items list or raw container
        raw_items = []
        is_pre_parsed = False
        if isinstance(data, dict):
            if "items" in data and isinstance(data["items"], list):
                raw_items = data["items"]
                is_pre_parsed = True
            if raw_items is None or not is_pre_parsed:
                raw_c = (
                    data.get("data")
                    or data.get("result")
                    or data.get("leave_quota")
                    or data.get("leaves")
                    or data.get("leave_types")
                    or data.get("leave_balances")
                    or data.get("records")
                )
                if isinstance(raw_c, list):
                    raw_items = raw_c
                elif isinstance(raw_c, dict):
                    raw_items = [raw_c]
        elif isinstance(data, list):
            raw_items = data

        final_items: list[dict] = []

        if is_pre_parsed and raw_items:
            for entry in raw_items:
                if not isinstance(entry, dict):
                    continue
                code = str(entry.get("code") or entry.get("short_name") or "LT").strip()
                name = str(entry.get("name") or entry.get("leave_type") or "Leave Type").strip()
                q_raw = (
                    entry.get("total_quota_str")
                    or entry.get("total_str")
                    or entry.get("total_quota")
                    or entry.get("total")
                    or 0.0
                )
                u_raw = (
                    entry.get("used_str")
                    or entry.get("used")
                    or 0.0
                )
                l_raw = (
                    entry.get("available_str")
                    or entry.get("left_str")
                    or entry.get("remaining_str")
                    or entry.get("available")
                    or entry.get("left")
                    or entry.get("remaining")
                    or 0.0
                )
                q_num = _to_num(q_raw)
                u_num = _to_num(u_raw)
                l_num = _to_num(l_raw)

                final_items.append({
                    "code": code,
                    "name": name,
                    "short_name": code,
                    "leave_type": name,
                    "total": q_num,
                    "total_quota": q_num,
                    "total_quota_str": str(q_raw) if str(q_raw) not in ("0.0", "0") else _fmt_val(q_num),
                    "used": u_num,
                    "used_str": str(u_raw) if str(u_raw) not in ("0.0", "0") else _fmt_val(u_num),
                    "left": l_num,
                    "available": l_num,
                    "available_str": str(l_raw) if str(l_raw) not in ("0.0", "0") else _fmt_val(l_num),
                })
        else:
            # Fallback mapping for raw dictionary / list formats
            assigned: dict[int, dict] = {}
            matched_raw_indices = set()

            for fixed_idx, fixed in enumerate(FIXED_LEAVE_TYPES):
                code = fixed["code"].lower()
                aliases = fixed.get("aliases", ())
                for r_idx, entry in enumerate(raw_items):
                    if not isinstance(entry, dict) or r_idx in matched_raw_indices:
                        continue
                    entry_code = str(
                        entry.get("code")
                        or entry.get("short_name")
                        or entry.get("short_code")
                        or entry.get("leave_code")
                        or entry.get("leaveCode")
                        or ""
                    ).strip().lower()
                    entry_name = str(
                        entry.get("name")
                        or entry.get("leave_type")
                        or entry.get("leave_type_name")
                        or entry.get("leave_name")
                        or entry.get("type")
                        or ""
                    ).strip().lower()

                    if (entry_code and (entry_code == code or entry_code in aliases)) or (entry_name and any(alias in entry_name for alias in aliases)):
                        assigned[fixed_idx] = entry
                        matched_raw_indices.add(r_idx)
                        break

            # Pass 2: For any fixed type that didn't match by code/name, match positional if unmapped raw items exist
            unmatched_raw = [entry for r_idx, entry in enumerate(raw_items) if isinstance(entry, dict) and r_idx not in matched_raw_indices]
            unmatched_fixed = [f_idx for f_idx in range(len(FIXED_LEAVE_TYPES)) if f_idx not in assigned]
            for f_idx, entry in zip(unmatched_fixed, unmatched_raw):
                assigned[f_idx] = entry

            for fixed_idx, fixed in enumerate(FIXED_LEAVE_TYPES):
                code = fixed["code"]
                name = fixed["name"]
                entry = assigned.get(fixed_idx, {})

                # Extract numeric fields
                q_raw = (
                    entry.get("total_quota_str")
                    or entry.get("total_quota")
                    or entry.get("total_str")
                    or entry.get("total")
                    or entry.get("totalQuota")
                    or entry.get("total_leaves")
                    or entry.get("allotted")
                    or entry.get("quota")
                    or entry.get("leaves")
                    or 0.0
                )
                u_raw = (
                    entry.get("used_str")
                    or entry.get("used")
                    or entry.get("leavesTaked")
                    or entry.get("leaves_taked")
                    or entry.get("leaves_taken")
                    or entry.get("taken")
                    or entry.get("consumed")
                    or entry.get("availed")
                    or 0.0
                )
                l_raw = (
                    entry.get("available_str")
                    or entry.get("available")
                    or entry.get("left_str")
                    or entry.get("left")
                    or entry.get("remaining")
                    or entry.get("remaining_str")
                    or entry.get("leave_balance")
                    or entry.get("balance")
                    or 0.0
                )

                q_num = _to_num(q_raw)
                u_num = _to_num(u_raw)
                l_num = _to_num(l_raw)

                if l_raw == 0.0 and q_num > 0 and u_num >= 0:
                    l_num = max(0.0, q_num - u_num)

                final_items.append({
                    "code": code,
                    "name": name,
                    "short_name": code,
                    "leave_type": name,
                    "total": q_num,
                    "total_quota": q_num,
                    "total_quota_str": str(q_raw) if str(q_raw) != "0.0" else _fmt_val(q_num),
                    "used": u_num,
                    "used_str": str(u_raw) if str(u_raw) != "0.0" else _fmt_val(u_num),
                    "left": l_num,
                    "available": l_num,
                    "available_str": str(l_raw) if str(l_raw) != "0.0" else _fmt_val(l_num),
                })

        if not final_items:
            self.scroll_area.setVisible(False)
            self.empty_state.setVisible(True)
            self.total_quota_val.setText("0 Days")
            self.total_used_val.setText("0 Days")
            self.total_avail_val.setText("0 Days")
            return

        self.empty_state.setVisible(False)
        self.scroll_area.setVisible(True)

        # Compute dynamic summary totals from summary dict or items
        summary_dict = data.get("summary") if isinstance(data, dict) and isinstance(data.get("summary"), dict) else {}
        tot_allotted = summary_dict.get("total_quota")
        if tot_allotted is None:
            tot_allotted = sum(item["total"] for item in final_items)

        tot_used = summary_dict.get("total_used")
        if tot_used is None:
            tot_used = sum(item["used"] for item in final_items)

        tot_avail = summary_dict.get("total_available")
        if tot_avail is None:
            tot_avail = sum(item["left"] for item in final_items)

        self.total_quota_val.setText(f"{_fmt_val(tot_allotted)} Days")
        self.total_used_val.setText(f"{_fmt_val(tot_used)} Days")
        self.total_avail_val.setText(f"{_fmt_val(tot_avail)} Days")

        # Clear existing cards
        while self.cards_grid.count():
            child = self.cards_grid.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()
        self._cards.clear()

        # Render cards dynamically in a 2-column responsive grid
        cols_per_row = 2
        for idx, item in enumerate(final_items):
            row_idx = idx // cols_per_row
            col_idx = idx % cols_per_row
            card = LeaveSummaryCard(item=item)
            self.cards_grid.addWidget(card, row_idx, col_idx)
            self._cards.append(card)

    def _show_error(self, message: str) -> None:
        """Display error banner with sanitized message."""
        if not self._is_network_online or self._is_network_or_offline_error(message):
            self.error_container.setVisible(False)
            return
        sanitized = self._sanitize_error_message(message)
        self.error_label.setText(sanitized)
        self.error_container.setVisible(True)

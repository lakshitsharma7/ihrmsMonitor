"""
Generate Genuine Application Screenshots for iHRMS Desktop User Manual.
Renders real Qt widgets in offscreen mode with realistic corporate demonstration data.
"""

import os
import sys

# Set offscreen platform before importing PySide6
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from datetime import date, datetime
from PySide6.QtCore import Qt, QSize, QDate
from PySide6.QtGui import QIcon, QPixmap, QColor, QPainter, QFont
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QDialog,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
SCREENSHOTS_DIR = os.path.join(BASE_DIR, "docs", "screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

app = QApplication.instance() or QApplication(sys.argv)

from ui.styles import APP_STYLESHEET
app.setStyleSheet(APP_STYLESHEET)

print(f"Generating screenshots into: {SCREENSHOTS_DIR}")

# ----------------------------------------------------------------------
# 1. Fig 01: Login Window - Company Code Step
# ----------------------------------------------------------------------
try:
    from ui.login_window import LoginWindow
    login1 = LoginWindow()
    login1.resize(760, 520)
    login1.company_code_input.setText("INDOVISION")
    login1.login_step = 1
    login1.credentials_container.setVisible(False)
    login1.consent_row.setVisible(False)
    login1.login_button.setText("Verify Company")
    login1.show()
    app.processEvents()
    pix = login1.grab()
    path1 = os.path.join(SCREENSHOTS_DIR, "fig01_login_company_code.png")
    pix.save(path1)
    login1.close()
    print("Saved:", path1)
except Exception as e:
    print("Error fig01:", e)

# ----------------------------------------------------------------------
# 2. Fig 02: Login Window - Credentials & Consent Step
# ----------------------------------------------------------------------
try:
    login2 = LoginWindow()
    login2.resize(760, 520)
    login2.company_code_input.setText("INDOVISION")
    login2.company_code_input.setEnabled(False)
    login2.login_step = 2
    login2.credentials_container.setVisible(True)
    login2.username_input.setText("EMP10482")
    login2.password_input.setText("••••••••••••")
    login2.consent_row.setVisible(True)
    login2.consent_checkbox.setChecked(True)
    login2.login_button.setText("Login")
    login2.show()
    app.processEvents()
    pix = login2.grab()
    path2 = os.path.join(SCREENSHOTS_DIR, "fig02_login_credentials.png")
    pix.save(path2)
    login2.close()
    print("Saved:", path2)
except Exception as e:
    print("Error fig02:", e)

# ----------------------------------------------------------------------
# 3. Fig 03: Main Window & Dashboard
# ----------------------------------------------------------------------
try:
    from database.database import get_session
    from services.activity_service import ActivityService
    from ui.main_window import MainWindow

    # Prevent background tracker and network syncing during screenshot capture
    orig_tracker = MainWindow._build_tracker
    orig_sync = MainWindow._sync_permissions_from_backend
    orig_start = MainWindow.start_workpulse
    MainWindow._build_tracker = lambda self: None
    MainWindow._sync_permissions_from_backend = lambda self: None
    MainWindow.start_workpulse = lambda self: None

    win = MainWindow()
    win.resize(1024, 720)
    win.user_label.setText("Welcome, Priya Sharma")
    win.status_badge.setText("● Tracking Active")
    win.status_badge.setStyleSheet("color: #10b981; font-weight: 700; font-size: 13px; background-color: #d1fae5; border-radius: 12px; padding: 4px 12px;")

    # Populate Dashboard page values
    dash = win.dashboard_page
    dash.active_time_val_label.setText("04:22:15")
    dash.attendance_status_badge.setText("● Punched In")
    dash.attendance_status_badge.setStyleSheet("background-color: #dcfce7; color: #15803d; font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 6px; border: 1px solid #86efac;")
    dash.attendance_start_val_label.setText("🖥 09:15 AM")
    dash.attendance_punch_val_label.setText("09:30 AM")
    dash.network_status_label.setText("● Online")
    dash.network_status_label.setStyleSheet("color: #10b981; font-weight: 700; font-size: 12px;")
    dash.version_label.setText("Version: 1.0.0")
    dash.idle_time_label.setText("Idle Time: 0 seconds")
    dash.last_update_label.setText("Last Update: 23-10-2026, 01:30 PM")
    dash.workpulse_toggle_button.setText("Paused")

    # Populate Timesheet tasks
    if hasattr(dash, "task_table"):
        table = dash.task_table
        table.setRowCount(3)
        sample_tasks = [
            ("1", "Enterprise Cloud Infrastructure & Monitoring", "100%", "85%", "40%", "Production cluster deployment & node health verified"),
            ("2", "Security Audit & Rate-Limiting Implementation", "100%", "90%", "35%", "All critical endpoints audited and passed"),
            ("3", "Database Index Optimization & Query Tuning", "100%", "70%", "25%", "Reduced slow query frequency by 42%"),
        ]
        for row_idx, task_info in enumerate(sample_tasks):
            for col_idx, text in enumerate(task_info):
                item = QTableWidgetItem(text)
                if col_idx in (0, 2, 3, 4):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row_idx, col_idx, item)

    win.show()
    app.processEvents()
    pix = win.grab()
    path3 = os.path.join(SCREENSHOTS_DIR, "fig03_dashboard_main.png")
    pix.save(path3)
    win.close()
    MainWindow._build_tracker = orig_tracker
    MainWindow._sync_permissions_from_backend = orig_sync
    MainWindow.start_workpulse = orig_start
    print("Saved:", path3)
except Exception as e:
    print("Error fig03:", e)

# ----------------------------------------------------------------------
# 4. Fig 04: Attendance Calendar Page
# ----------------------------------------------------------------------
try:
    from ui.attendance_page import AttendancePage
    att_page = AttendancePage(parent=None)
    att_page.resize(1024, 700)

    # Set mock attendance statistics on actual widgets
    att_page.ring_widget.set_percentage(91)
    att_page.working_days_val_label.setText("21")
    att_page.present_val_label.setText("19")
    att_page.absent_val_label.setText("1")
    att_page.missed_punch_val_label.setText("0")
    att_page.half_day_val_label.setText("0")
    att_page.leave_val_label.setText("1")
    att_page.weekoff_val_label.setText("4")
    att_page.total_days_val_label.setText("25")
    att_page.rating_badge.setText("Good")

    att_page.show()
    app.processEvents()
    pix = att_page.grab()
    path4 = os.path.join(SCREENSHOTS_DIR, "fig04_attendance_calendar.png")
    pix.save(path4)
    att_page.close()
    print("Saved:", path4)
except Exception as e:
    print("Error fig04:", e)

# ----------------------------------------------------------------------
# 5. Fig 05: Timesheet & KRA Tasks Table
# ----------------------------------------------------------------------
try:
    from ui.task_table import AssignedTasksTable
    tasks_widget = QWidget()
    tasks_widget.resize(960, 360)
    t_layout = QVBoxLayout(tasks_widget)
    t_layout.setContentsMargins(12, 12, 12, 12)
    t_layout.setSpacing(8)

    t_table = AssignedTasksTable(parent=tasks_widget)
    t_layout.addWidget(t_table.title_label)
    t_layout.addWidget(t_table)
    t_layout.addWidget(t_table.actions_widget)

    t_table.setRowCount(3)
    sample_tasks = [
        ("1", "Enterprise Cloud Infrastructure & Monitoring", "100%", "85%", "40%", "Production cluster deployment & node health verified"),
        ("2", "Security Audit & Rate-Limiting Implementation", "100%", "90%", "35%", "All critical endpoints audited and passed"),
        ("3", "Database Index Optimization & Query Tuning", "100%", "70%", "25%", "Reduced slow query frequency by 42%"),
    ]
    for row_idx, task_info in enumerate(sample_tasks):
        for col_idx, text in enumerate(task_info):
            item = QTableWidgetItem(text)
            if col_idx in (0, 2, 3, 4):
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            t_table.setItem(row_idx, col_idx, item)

    tasks_widget.show()
    app.processEvents()
    pix = tasks_widget.grab()
    path5 = os.path.join(SCREENSHOTS_DIR, "fig05_timesheet_kra.png")
    pix.save(path5)
    tasks_widget.close()
    print("Saved:", path5)
except Exception as e:
    print("Error fig05:", e)

# ----------------------------------------------------------------------
# 6. Fig 06: Additional Tasks Logger Widget
# ----------------------------------------------------------------------
try:
    from ui.additional_task_widget import AdditionalTaskWidget
    add_task_box = QWidget()
    add_task_box.resize(960, 260)
    at_layout = QVBoxLayout(add_task_box)
    at_layout.setContentsMargins(10, 10, 10, 10)

    at_widget = AdditionalTaskWidget(parent=add_task_box)
    at_layout.addWidget(at_widget)

    # Set realistic input values
    if hasattr(at_widget, "task_input"):
        at_widget.task_input.setText("Production Hotfix - SSL Certificate Renewal")
    if hasattr(at_widget, "desc_input"):
        at_widget.desc_input.setPlainText("Updated wildcard certificates across staging and production Kubernetes ingress controllers.")
    if hasattr(at_widget, "hours_input"):
        at_widget.hours_input.setValue(2.5)

    add_task_box.show()
    app.processEvents()
    pix = add_task_box.grab()
    path6 = os.path.join(SCREENSHOTS_DIR, "fig06_additional_tasks.png")
    pix.save(path6)
    add_task_box.close()
    print("Saved:", path6)
except Exception as e:
    print("Error fig06:", e)

# ----------------------------------------------------------------------
# 7. Fig 07: Leave Balance Modal Dialog
# ----------------------------------------------------------------------
try:
    from ui.leave_balance_dialog import LeaveBalanceDialog
    leave_dlg = LeaveBalanceDialog(parent=None)
    leave_dlg.resize(780, 520)

    # Supply realistic leave quota and utilization data
    mock_leave_payload = {
        "items": [
            {"code": "CL", "name": "Casual Leave", "total": 12, "used": 3, "available": 9},
            {"code": "SL", "name": "Sick Leave", "total": 10, "used": 2, "available": 8},
            {"code": "CO", "name": "Comp Off", "total": 4, "used": 1, "available": 3},
            {"code": "OD", "name": "Business Trip", "total": 15, "used": 5, "available": 10},
            {"code": "LWP", "name": "Leave Without Pay", "total": 0, "used": 0, "available": 0},
            {"code": "EL", "name": "Paid Leave", "total": 18, "used": 4, "available": 14},
            {"code": "RH", "name": "Restricted/Floating", "total": 2, "used": 1, "available": 1},
        ]
    }
    leave_dlg._apply_leave_data(mock_leave_payload)

    leave_dlg.show()
    app.processEvents()
    pix = leave_dlg.grab()
    path7 = os.path.join(SCREENSHOTS_DIR, "fig07_leave_balance.png")
    pix.save(path7)
    leave_dlg.close()
    print("Saved:", path7)
except Exception as e:
    print("Error fig07:", e)

# ----------------------------------------------------------------------
# 8. Fig 08: Settings Page Dialog
# ----------------------------------------------------------------------
try:
    from services.settings_service import SettingsService
    from ui.settings import SettingsPage

    settings_frame = QFrame()
    settings_frame.resize(700, 500)
    settings_frame.setStyleSheet("background-color: #ffffff; border-radius: 8px;")
    sf_layout = QVBoxLayout(settings_frame)
    sf_layout.setContentsMargins(20, 20, 20, 20)

    title = QLabel("iHRMS Desktop Settings & Preferences", settings_frame)
    title.setStyleSheet("font-size: 16px; font-weight: 700; color: #0f172a; margin-bottom: 12px;")
    sf_layout.addWidget(title)

    sp = SettingsPage(SettingsService(get_session), parent=settings_frame)
    sp.start_with_system_checkbox.setChecked(True)
    sp.idle_threshold_spinbox.setValue(5)
    sp.track_window_titles_checkbox.setChecked(True)
    sp.interval_combobox.setCurrentIndex(0)  # 3 minutes
    sp.capture_on_switch_checkbox.setChecked(True)
    sp.current_interval_label.setText("3 minutes")
    sp.capture_status_label.setText("Active (Monitoring Foreground App)")
    sp.capture_status_label.setStyleSheet("color: #10b981; font-weight: 600;")
    sf_layout.addWidget(sp)

    settings_frame.show()
    app.processEvents()
    pix = settings_frame.grab()
    path8 = os.path.join(SCREENSHOTS_DIR, "fig08_settings_dialog.png")
    pix.save(path8)
    settings_frame.close()
    print("Saved:", path8)
except Exception as e:
    print("Error fig08:", e)

# ----------------------------------------------------------------------
# 9. Fig 09: Software Update Dialog
# ----------------------------------------------------------------------
try:
    from ui.update_dialog import UpdateDialog
    upd_dlg = UpdateDialog(version="1.0.1", is_force=False)
    upd_dlg.resize(480, 260)
    upd_dlg.status_label.setText("Verified update package ready for deployment.")
    upd_dlg.progress_bar.setValue(100)
    upd_dlg.show()
    app.processEvents()
    pix = upd_dlg.grab()
    path9 = os.path.join(SCREENSHOTS_DIR, "fig09_software_update.png")
    pix.save(path9)
    upd_dlg.close()
    print("Saved:", path9)
except Exception as e:
    print("Error fig09:", e)

# ----------------------------------------------------------------------
# 10. Fig 10: User & Device Fleet Verification Dialog
# ----------------------------------------------------------------------
try:
    from ui.main_window import UserDeviceDialog
    info_data = {
        "name": "Priya Sharma",
        "employee_id": "EMP10482",
        "username": "priya.sharma",
        "email": "priya.s@indovision.in",
        "company_code": "INDOVISION",
        "role": "Senior Software Engineer",
        "device": "CORP-W11-LT0482",
        "platform": "Windows",
        "os_version": "11 Pro (10.0.22631)",
        "app_version": "1.0.0",
        "device_identifier": "DEV-HW-4B82-9F12-88C1",
    }
    dev_dlg = UserDeviceDialog(information=info_data)
    dev_dlg.resize(800, 520)
    dev_dlg.show()
    app.processEvents()
    pix = dev_dlg.grab()
    path10 = os.path.join(SCREENSHOTS_DIR, "fig10_device_verification.png")
    pix.save(path10)
    dev_dlg.close()
    print("Saved:", path10)
except Exception as e:
    print("Error fig10:", e)

# ----------------------------------------------------------------------
# 11. Fig 11: Release Summary & Version History Dialog
# ----------------------------------------------------------------------
try:
    from ui.release_summary_dialog import ReleaseSummaryDialog
    rel_dlg = ReleaseSummaryDialog(parent=None)
    rel_dlg.resize(780, 520)
    rel_dlg.show()
    app.processEvents()
    pix = rel_dlg.grab()
    path11 = os.path.join(SCREENSHOTS_DIR, "fig11_release_notes.png")
    pix.save(path11)
    rel_dlg.close()
    print("Saved:", path11)
except Exception as e:
    print("Error fig11:", e)

# ----------------------------------------------------------------------
# 12. Fig 12: System Tray & Notification Context Menu
# ----------------------------------------------------------------------
try:
    tray_widget = QWidget()
    tray_widget.resize(360, 240)
    tray_widget.setStyleSheet("background-color: #1e293b; border-radius: 8px; color: #ffffff;")
    tw_layout = QVBoxLayout(tray_widget)
    tw_layout.setContentsMargins(16, 16, 16, 16)
    tw_layout.setSpacing(10)

    header_tray = QLabel("iHRMS Desktop — System Tray Menu", tray_widget)
    header_tray.setStyleSheet("font-size: 13px; font-weight: 700; color: #38bdf8;")
    tw_layout.addWidget(header_tray)

    menu_box = QFrame(tray_widget)
    menu_box.setStyleSheet("background-color: #0f172a; border: 1px solid #334155; border-radius: 6px;")
    mb_layout = QVBoxLayout(menu_box)
    mb_layout.setContentsMargins(8, 8, 8, 8)
    mb_layout.setSpacing(6)

    items = [
        ("🖥  Open iHRMS Desktop", "#f8fafc", True),
        ("●  Status: Online & Tracking Active", "#10b981", False),
        ("📅  View Attendance Calendar", "#94a3b8", False),
        ("🔄  Check for Updates (v1.0.0)", "#94a3b8", False),
        ("🌐  Open iHRMS Web Portal", "#94a3b8", False),
        ("❌  Exit Application", "#ef4444", True),
    ]

    for label_txt, color_hex, is_bold in items:
        lbl = QLabel(label_txt, menu_box)
        weight = "700" if is_bold else "500"
        lbl.setStyleSheet(f"color: {color_hex}; font-size: 12px; font-weight: {weight}; padding: 3px 6px;")
        mb_layout.addWidget(lbl)

    tw_layout.addWidget(menu_box)
    tray_widget.show()
    app.processEvents()
    pix = tray_widget.grab()
    path12 = os.path.join(SCREENSHOTS_DIR, "fig12_system_tray.png")
    pix.save(path12)
    tray_widget.close()
    print("Saved:", path12)
except Exception as e:
    print("Error fig12:", e)

print("All screenshots generated successfully!")

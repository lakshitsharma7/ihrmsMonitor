# iHRMS Desktop

A cross-platform enterprise desktop activity monitoring, timesheet management, and attendance companion for **Windows** and **macOS**, built with **Python + PySide6**. One codebase, one unified UI, one database schema, and seamless multi-tenant cloud synchronization.

---

## 1. Project Overview

**iHRMS Desktop** runs quietly in the system tray or menu bar to provide:
- **Active Workspace Productivity Monitoring**: Captures active application, process ID, window title, and exact focus duration.
- **Smart Idle Detection**: Halts active duration counting during periods of user inactivity (mouse/keyboard idle).
- **Automated Cloud Synchronization**: Local-first SQLite queue with transactional batch uploads (`POST /workpulse/save_activity_batch`).
- **Screenshot Capture**: Periodic desktop screen captures with offline queuing and macOS Screen Recording permission management.
- **Attendance & Punch WorkPulse**: Integration with company punch-in/out timestamps and monthly attendance records.
- **Leave Balance & Quotas**: Real-time retrieval of accrued leave types and remaining quotas.
- **Task PMS & Timesheets**: Interactive timesheet management for Key Result Areas (KRAs) and assigned tasks.
- **Single Sign-On HRMS Portal Bridge**: Instant browser navigation to the full HRMS Web Portal with automated credential passing.
- **Authoritative Unattended Auto-Updates**: Seamless background update checks (`POST /api/appcontroller/appcontroller`), silent Inno Setup installation, detached execution, and update loop prevention.

---

## 2. Supported Operating Systems

- **Windows 10 / Windows 11 (64-bit)**
- **macOS 12 (Monterey), macOS 13 (Ventura), macOS 14 (Sonoma), macOS 15 (Sequoia)**

---

## 3. Architecture

```
                 ActivityTracker (tracker/activity_tracker.py)
                       │
                       ▼
             PlatformActivityProvider (platform_support/base.py)
                       │
             ┌─────────┴─────────┐
             ▼                   ▼
     WindowsActivityProvider   MacOSActivityProvider
             │                   │
       pywin32 / ctypes        PyObjC / Quartz
             │                   │
             └─────────┬─────────┘
                       ▼
                Common ActiveSession
                       │
             ┌─────────┴─────────┐
             ▼                   ▼
     Local SQLite DB       SyncService (REST API)
             │                   │
             └─────────┬─────────┘
                       ▼
               PySide6 Dashboard & Tray
```

### Layer Responsibilities

| Layer | Directory | Responsibility |
|---|---|---|
| **GUI** | `ui/` | Login, Dashboard, Attendance, Tasks, Leave, Update Dialog, System Tray |
| **Tracker** | `tracker/` | Session state machine, window polling worker, idle workpulse |
| **Platform** | `platform_support/` | Abstract OS interface (`base.py`) + OS-specific implementations |
| **Services** | `services/` | Sync, Authentication, Screenshots, Attendance, Tasks, Auto-Updates, Health |
| **Database** | `database/` | SQLAlchemy models, engine, and repository access layer |
| **Configuration** | `config/` | Dynamic API configuration (`ApiConfig`), app versioning, constants |
| **System** | `system/` | Auto-start registration (Windows Run key / macOS LaunchAgent), Tray |
| **Utils** | `utils/` | System health telemetry, device identifier, logger, security |

---

## 4. Environment Setup

### Windows
```powershell
python -m venv venv
venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

### macOS
```bash
python3 -m venv venv
source venv/bin/activate
pip3 install --upgrade pip
pip3 install -r requirements.txt -r requirements-macos.txt
```

---

## 5. Running from Source

```bash
# Windows
python app.py

# macOS
python3 app.py
```

---

## 6. Endpoints & Integrations

iHRMS Desktop connects dynamically to tenant-specific company endpoints resolved through AppController:

- **Company Verification**: `POST /appcontroller/appcontroller`
- **User Authentication**: `POST /login/login`
- **Device Enrollment**: `POST /workpulse/enroll_device`
- **Sync Settings**: `POST /workpulse/get_settings`
- **Batch Activity Sync**: `POST /workpulse/save_activity_batch`
- **Screenshot Upload**: `POST /workpulse/upload_screenshot`
- **Punch Time**: `POST /punch/get_punch_time`
- **Monthly Attendance**: `POST /attendance/get_attendance_record`
- **Leave Balance**: `POST /LeaveApply/view_balance`
- **KRA / Tasks**: `POST /TaskPMS/get_kra`
- **Timesheet Submission**: `POST /TaskPMS/fill_time_sheet`
- **Version Check**: `POST /api/appcontroller/appcontroller`
- **Diagnostic Logging**: `POST /dashboard/post_front_end_error_log`

For detailed request/response schemas and architectural workflows, see [docs/WORKPULSE_SYSTEM_DOCUMENTATION.md](file:///d:/New%20folder/ihrms_monitor/docs/WORKPULSE_SYSTEM_DOCUMENTATION.md).

---

## 7. Auto-Update Mechanism

1. **Source of Truth**: The live App Controller update API (`POST /api/appcontroller/appcontroller`) dynamically provides the server version and download URL (`data.apps.WINDOWS` / `data.apps.MAC`).
2. **Semantic Precedence**: Updates trigger **only** when `server_version > installed_version` (evaluated numerically by major, minor, patch).
3. **Loop Guard & Cooldown**: If an installation attempt fails (e.g. file lock), automatic retries for that version enter a 24-hour cooldown while keeping normal workpulse operational.
4. **Silent Detached Execution**: Windows installers run silently via detached VBScript/PowerShell runners without blocking or keeping open file locks.

---

## 8. Building & Packaging

### Windows Executable & Inno Setup Installer
```powershell
# Build executable via PyInstaller
pyinstaller Workpulse.spec --clean --noconfirm

# Build installer via Inno Setup
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\WorkpulseSetup.iss
```
Output: `dist\installer\WorkpulseSetup.exe`

### macOS App & DMG
```bash
./build_macos.sh
```
Output: `dist/Workpulse.dmg` and `dist/Workpulse.app`

---

## 9. Automated Testing

iHRMS Desktop includes a complete test suite of 295 unit and integration tests:

```bash
# Run all unit and integration tests
python -m unittest discover tests

# Run version and update logic tests specifically
python -m unittest tests/test_auto_update_version_check.py
```

---

## 10. Privacy & Security

- **Strict HTTPS/TLS**: All communication with cloud endpoints enforces valid TLS certificates.
- **Credential Protection**: Passwords, tokens, and authorization keys are scrubbed from log files.
- **Non-Invasive Activity Monitoring**: iHRMS Desktop captures active application names, window titles, durations, and system health metrics. It does not perform keylogging, clipboard extraction, or covert microphone/webcam recording.

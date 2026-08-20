# Activity Tracker

A cross-platform desktop activity tracker for **Windows** and **macOS**, built with **Python + PySide6**. One codebase, one GUI, one database schema, one set of business logic — only the thin OS-integration layer differs between platforms.

---

## 1. Project Overview

Activity Tracker runs quietly in the background, detects which application (and, where the OS permits, which window) currently has focus, and records how long you spend in each one. It shows a live dashboard with today's total active time, a per-application breakdown, and a chronological timeline, and it can start with your system and live in the tray/menu bar.

It deliberately does **not** do anything invasive — see [Privacy Considerations](#18-privacy-considerations).

## 2. Supported Operating Systems

- Windows 10 and later
- macOS 12 (Monterey) and later

Running on any other OS shows a clear message ("This version of Activity Tracker supports Windows and macOS.") instead of crashing.

## 3. Features

- Native PySide6 desktop GUI, identical on both platforms
- Background tracking on a `QThread` — the GUI never blocks or freezes
- Active application detection (name + PID), with window title where the OS allows it
- Automatic session creation on application switch; in-place updates for window-title-only changes
- Idle detection (default 5 minutes) that stops counting idle time as active usage
- Dashboard: current app, today's total, per-application usage, activity timeline, manual refresh
- System tray (Windows) / menu bar (macOS) via the same `QSystemTrayIcon` abstraction
- "Start with system" via a user-level mechanism (Windows Run key / macOS LaunchAgent) — no admin/root required
- Settings screen: idle threshold, start-with-system, track-window-titles — changes apply live, no restart needed
- Close-button dialog: Stop Tracking / Continue in Background / Cancel
- SQLite persistence via SQLAlchemy, same schema on both platforms
- Structured logging to a rotating log file (never `print()`)
- Packaging into a Windows `.exe` and a macOS `.app`

## 4. Architecture

```
                 ActivityTracker (tracker/activity_tracker.py)
                       │
                       ▼
             PlatformActivityProvider (platform_support/base.py)
                       │
             ┌─────────┴─────────┐
             ▼                   ▼
     WindowsActivityProvider MacOSActivityProvider
             │                   │
          pywin32              PyObjC
             │                   │
             └─────────┬─────────┘
                       ▼
                Common ActiveApplication
                       │
                       ▼
                 Repository / Database
                       │
                       ▼
                PySide6 Dashboard / Tray
```

Layers, top to bottom:

| Layer | Package | Responsibility |
|---|---|---|
| GUI | `ui/` | Windows, widgets, styling — 100% platform-independent |
| Tracker | `tracker/` | Session/idle state machine + `QThread` worker adapter |
| Platform | `platform_support/` | **Only** place that branches on OS |
| Services | `services/` | Dashboard calculations, settings read/write |
| Database | `database/` | SQLAlchemy models, engine, repository (query layer) |
| System | `system/` | Tray icon, start-with-system registration |
| Config/Utils | `config/`, `utils/` | Constants, logging, cross-platform paths |

## 5. Cross-Platform Architecture Explanation

The rule enforced throughout this codebase: **no `if platform == "windows"` scattered through business logic.** Instead:

- `platform_support/base.py` defines one abstract interface, `PlatformActivityProvider`, with `get_active_application()` and `get_idle_seconds()`.
- `platform_support/windows/provider.py` and `platform_support/macos/provider.py` each implement it using `pywin32`/ctypes and `PyObjC`/Quartz respectively.
- `platform_support/__init__.py` contains **the single factory function**, `create_activity_provider()`, that is the only place in the whole application allowed to check `sys.platform`.
- Everything else — the tracker, the database, the dashboard, settings — talks only to the `PlatformActivityProvider` interface and never knows which OS it's running on.

> **Why `platform_support/` and not `platform/`?** Python's standard library already has a module called `platform`. Because this project's own directory sits on `sys.path` when you run `python app.py`, naming our package `platform` would shadow the real standard-library module for *every* library in the process that imports it internally (e.g. `uuid`, `pytest`) — causing confusing crashes unrelated to our code. `platform_support/` avoids the collision while keeping the same internal structure the spec describes (`base.py`, `windows/`, `macos/`). The codebase also never imports the stdlib `platform` module itself — it uses `sys.platform` instead (see `utils/paths.py`).

## 6. Windows Setup

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt -r requirements-windows.txt
```

## 7. macOS Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip3 install -r requirements.txt -r requirements-macos.txt
```

## 8. Running From Source

```bash
python app.py      # Windows: python app.py  |  macOS: python3 app.py
```

On first run the app creates its database and log directory automatically (see below), shows the dashboard, and adds a tray/menu-bar icon.

## 9. Database Structure

SQLite via SQLAlchemy, same schema on both platforms.

**`activity_sessions`**

| Column | Type | Notes |
|---|---|---|
| id | int, PK | |
| application_name | string | |
| process_id | int, nullable | |
| window_title | string, nullable | omitted where OS/permissions disallow it |
| started_at | datetime | |
| ended_at | datetime, nullable | null while the session is still open |
| duration_seconds | int | finalized when the session closes |
| created_at | datetime | row insert timestamp |

**`settings`** (single row)

| Column | Type |
|---|---|
| id | int, PK |
| idle_threshold | int (seconds) |
| start_with_system | bool |
| tracking_enabled | bool |
| track_window_titles | bool |

Database file location:

- Windows: `%LOCALAPPDATA%\ActivityTracker\activity_tracker.db`
- macOS: `~/Library/Application Support/ActivityTracker/activity_tracker.db`

Resolved once, centrally, by `utils/paths.get_database_path()` — no other module hardcodes an OS path.

## 10. Activity Tracking Flow

1. `TrackerWorker` (on a background `QThread`) polls `ActivityTracker.poll()` roughly once per second via a `QTimer`.
2. `ActivityTracker` asks the injected `PlatformActivityProvider` for the current app and idle time.
3. If the application changed since the last poll, the old session is closed (duration computed) and a new one is opened.
4. If only the window title changed (same app), the *existing* open session's title is updated in place — no new row.
5. Results are emitted back to the GUI thread as a `TrackerState` via a Qt signal; the GUI is never blocked and never runs the loop itself.

## 11. Idle Detection

- Default threshold: 5 minutes (`config/settings.DEFAULT_IDLE_THRESHOLD_SECONDS`), editable in Settings.
- Windows: `GetLastInputInfo` (via `ctypes`) vs. `GetTickCount`.
- macOS: `CGEventSourceSecondsSinceLastEventType` (Quartz) — requires no special permission.
- When idle time crosses the threshold, the current session is closed immediately so idle time is never counted as active usage. When activity resumes, a fresh session opens on the next poll.

## 12. macOS Permissions

- **Application name / PID**: works out of the box via `NSWorkspace`, no permission needed.
- **Window title**: requires the **Screen Recording** (or **Accessibility**, depending on macOS version) permission under *System Settings → Privacy & Security*. If not granted, `platform_support/macos/active_window.py` simply returns `window_title=None` — the app keeps tracking the application name/PID and logs the situation; it never crashes over a missing permission.
- **Idle detection**: no special permission required.

## 13. Windows Permissions

- No administrator privileges are required for normal operation or for "start with system" (which uses the per-user `HKEY_CURRENT_USER\...\Run` registry key, not a system-wide location).
- Some windows owned by elevated (admin) processes may not be inspectable by a non-elevated tracker process — this is standard Windows UIPI behavior, not a bug; the app falls back to whatever it can read.

## 14. System Tray Behavior

Implemented once, using `QSystemTrayIcon`, which natively maps to the Windows tray and the macOS menu bar:

```
Activity Tracker
----------------
Show Dashboard
Start Tracking
Stop Tracking
Today's Activity
Settings
Exit
```

Closing the main window doesn't necessarily quit the app — see below.

## 15. Building the Windows `.exe`

**Must be run on Windows** (PyInstaller does not cross-compile):

```powershell
build_windows.bat
```

Equivalent to:

```powershell
pip install -r requirements.txt -r requirements-windows.txt
pyinstaller --noconfirm --clean --windowed --onefile --name ActivityTracker app.py
```

Output: `dist\ActivityTracker.exe`

## 16. Building the macOS `.app`

**Must be run on macOS** (PyInstaller does not cross-compile):

```bash
./build_macos.sh
```

Equivalent to:

```bash
pip3 install -r requirements.txt -r requirements-macos.txt
pyinstaller --noconfirm --clean --windowed --name ActivityTracker app.py
```

Output: `dist/ActivityTracker.app`

On first launch, macOS will prompt for Screen Recording/Accessibility permission (see [macOS Permissions](#12-macos-permissions)).

## 17. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Window titles are always blank on macOS | Grant Screen Recording permission in System Settings → Privacy & Security, then restart the app. |
| "This version of Activity Tracker supports Windows and macOS." on launch | You're running on an unsupported OS (e.g. Linux). |
| Tray icon doesn't appear | Some minimal Linux/VM/CI environments have no system tray; this doesn't affect Windows/macOS. |
| Database/log files not found | Check `%LOCALAPPDATA%\ActivityTracker` (Windows) or `~/Library/Application Support/ActivityTracker` (macOS). |
| `pywin32`/`pyobjc` install errors | Make sure you installed the OS-specific requirements file for *your* OS only (`requirements-windows.txt` on Windows, `requirements-macos.txt` on macOS) — never both. |
| App seems to "lose" a few seconds per switch | Expected: the poll interval is ~1s, so a session boundary can be off by up to one poll tick. Lower `POLL_INTERVAL_SECONDS` in `config/settings.py` if you need finer granularity. |

## 18. Privacy Considerations

Activity Tracker only ever records: application name, process ID, window title (where permitted), and timestamps/durations. It deliberately does **not** implement keylogging, password/credential capture, clipboard monitoring, screenshots, webcam/microphone recording, browser history extraction, or any hidden/background surveillance beyond what's visibly described above. The GUI always shows a clear tracking-status indicator.

---

## Development

### Running tests

Shared business logic (session/idle state machine, repository queries, dashboard/settings services, the platform factory) is fully unit-tested without any GUI or real OS API, using a fake `PlatformActivityProvider` and a throwaway SQLite file:

```bash
pip install pytest
pytest
```

### Project layout

```
activity_tracker/
├── app.py                     # Entry point
├── config/settings.py         # Constants & defaults
├── ui/                        # PySide6 GUI (platform-independent)
│   ├── main_window.py
│   ├── dashboard.py
│   ├── activity_table.py
│   ├── settings.py
│   └── styles.py
├── tracker/                   # Core tracking logic (platform-independent)
│   ├── activity_tracker.py    # Pure state machine (no Qt, no OS)
│   ├── activity_session.py
│   └── tracker_worker.py      # QThread adapter
├── platform_support/          # THE ONLY place that branches on OS
│   ├── base.py                # PlatformActivityProvider interface
│   ├── windows/
│   └── macos/
├── database/                  # SQLAlchemy models, engine, repository
├── services/                  # Dashboard + settings business logic
├── system/                    # Tray icon, start-with-system
├── utils/                     # Cross-platform paths, logging
├── tests/                     # Unit tests for shared logic
├── requirements*.txt
├── build_windows.bat
└── build_macos.sh
```

### Known OS-specific limitations

- Window titles on macOS depend on a user-granted permission; on Windows they can be blocked by UIPI for elevated processes.
- `pywin32` and `pyobjc-framework-*` cannot be installed on the "wrong" OS — the requirements files use PEP 508 environment markers (`sys_platform == "..."`) so a blanket `pip install -r requirements.txt -r requirements-windows.txt -r requirements-macos.txt` is harmless (the wrong-OS file's packages are simply skipped), but the provided per-OS install commands above are the intended path.
- PyInstaller cannot cross-compile: build the `.exe` on Windows and the `.app` on macOS.

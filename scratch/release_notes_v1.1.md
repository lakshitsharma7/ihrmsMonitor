## Workpulse v1.1 Production Release

### Key Updates & Enhancements:
- **Application Startup Reliability**: Resolved potential hang and black-screen initialization issues on Windows by ensuring zero-blocking UI instantiation on startup.
- **Windows Automatic Startup**: Normalized working directory and application path handling during automatic system login via Windows Registry Run keys.
- **Active Single-Instance Protection**: Added dead-process PID validation to automatically recover stale lock files and properly bring existing tray instances to the foreground.
- **Real-Time Online/Offline Detection**: Autonomous network reachability monitor detecting live connectivity independently of individual API endpoint states.
- **Attendance Status & Calendar Display**: Fixed Attendance day categorization (Present, Missed Punch, Absent, Week Off, Leave) and updated Missed Punch day cards to use a clear green theme.
- **Dynamic Leave Balance Integration**: Accurate parsing of dynamic comma-separated leave quota records and updated status rendering.

### Release Artifacts:
- **Windows**: `Workpulse-Setup-1.1.exe`
- **macOS**: `Workpulse-1.1.dmg`

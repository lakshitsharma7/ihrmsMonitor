import os
import re

pattern = re.compile(r'workpulse', re.I)

def scan_file(filepath):
    results = []
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        for idx, line in enumerate(f, 1):
            if pattern.search(line):
                results.append((idx, line.strip()))
    return results

files = [
    'config/settings.py',
    'utils/paths.py',
    'app.py',
    'system/tray.py',
    'system/startup.py',
    'ui/login_window.py',
    'ui/main_window.py',
    'ui/dashboard.py',
    'ui/settings.py',
    'ui/update_dialog.py',
    'ui/attendance_page.py',
    'ui/leave_balance_dialog.py',
    'Workpulse.iss',
    'Workpulse.spec',
    'Workpulse-macos.spec',
    'file_version_info.txt',
    'README.md',
    'RELEASE_NOTES.md',
    'build_windows.bat',
    'build_macos.sh'
]

for fp in ['ui/main_window.py', 'ui/dashboard.py', 'ui/settings.py', 'system/tray.py', 'app.py']:
    if os.path.exists(fp):
        res = scan_file(fp)
        print(f"\n=== {fp} ({len(res)} matches) ===")
        for idx, line in res:
            if any(k in line for k in ['"', "'", "QLabel", "QPushButton", "setWindowTitle", "setToolTip", "QAction", "QMessageBox"]):
                print(f"{idx:4d}: {line}")


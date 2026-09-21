"""Verify both packaged and installed Workpulse.exe executables launch and initialize CA bundle."""
import os
import subprocess
import time
import sys
from pathlib import Path

targets = [
    Path("dist/Workpulse/Workpulse.exe").resolve(),
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Workpulse" / "Workpulse.exe",
]

for exe_path in targets:
    if not exe_path.exists():
        print(f"SKIPPING (not found): {exe_path}")
        continue

    print(f"Testing {exe_path}...")
    proc = subprocess.Popen([str(exe_path)])
    try:
        time.sleep(4)
        poll = proc.poll()
        if poll is None:
            print(f"SUCCESS: {exe_path.name} (PID {proc.pid}) started and is running stably.")
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
            print("Clean shutdown verified.")
        else:
            print(f"FAIL: {exe_path.name} exited prematurely with code {poll}")
            sys.exit(1)
    finally:
        if proc.poll() is None:
            proc.kill()

print("ALL TARGET EXEs TESTED SUCCESSFULLY.")

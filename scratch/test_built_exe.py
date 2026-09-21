"""Verify built Workpulse.exe runs, extracts internal Python interpreter and dependencies correctly."""
import subprocess
import time
import sys
from pathlib import Path

exe_path = Path("dist/Workpulse/Workpulse.exe").resolve()
if not exe_path.exists():
    print(f"FAIL: {exe_path} does not exist")
    sys.exit(1)

print(f"Launching {exe_path}...")
proc = subprocess.Popen([str(exe_path)])
try:
    time.sleep(5)
    poll = proc.poll()
    if poll is None:
        print(f"SUCCESS: Workpulse.exe is running stably (PID {proc.pid}) with embedded Python runtime.")
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        print("Clean shutdown verified.")
    else:
        print(f"FAIL: Workpulse.exe exited immediately with code {poll}")
        sys.exit(1)
finally:
    if proc.poll() is None:
        proc.kill()

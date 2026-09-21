#!/usr/bin/env python3
"""Verification CLI script for Workpulse Windows EXE auto-updates across all enrolled laptops.

Usage:
    python scripts/verify_device_updates.py [--json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import get_running_app_version, APP_VERSION
from database.database import init_database
from services.device_registry_service import DeviceRegistryService


def print_fleet_verification_report(as_json: bool = False, check_offline: bool = False) -> int:
    """Generate and display the complete device update verification report."""
    init_database()
    svc = DeviceRegistryService()

    # Ensure current device is recorded with real executable version
    svc.record_heartbeat()

    if check_offline:
        alerted = svc.check_offline_devices()
        if not as_json and alerted:
            print(f"[*] Offline / Uninstall check triggered: {len(alerted)} device(s) flagged.")

    devices = svc.get_all_devices()
    summary = svc.get_device_summary()
    current_running_ver = get_running_app_version()

    if as_json:
        output_data = {
            "current_executable_version": current_running_ver,
            "summary": summary,
            "devices": devices,
        }
        print(json.dumps(output_data, indent=2))
        return 0

    print("\n" + "=" * 80)
    print("      WORKPULSE - ENROLLED WINDOWS DEVICES AUTO-UPDATE VERIFICATION      ")
    print("=" * 80)
    print(f"Current Host Running Version : {current_running_ver} (Authoritative Build Metadata)")
    print(f"Total Enrolled Devices       : {summary['total']}")
    print(f"  - [UPDATED]               : {summary['updated']}")
    print(f"  - [UPDATE PENDING]        : {summary['pending']}")
    print(f"  - [UPDATE FAILED]         : {summary['failed']}")
    print(f"  - [OFFLINE / STALE]       : {summary['offline']}")
    print("-" * 80)

    # Format Table
    header = f"{'Hostname / Laptop':<20} | {'User / EmpID':<18} | {'Installed':<10} | {'Latest':<10} | {'Status':<16} | {'Last Seen'}"
    print(header)
    print("-" * 80)

    for d in devices:
        host = (d.get("hostname") or "Unknown")[:19]
        emp = f"{d.get('username') or ''} ({d.get('employee_id') or '-'})"[:17]
        inst = (d.get("installed_version") or "1.0.0")[:9]
        latest = str(d.get("latest_version") or "N/A")[:9]
        status = d.get("update_status", "Unknown")[:15]
        last_seen = str(d.get("last_seen") or d.get("last_sync") or "Never")
        if "T" in last_seen:
            last_seen = last_seen.split(".")[0].replace("T", " ")

        status_marker = "  "
        if status == "Updated":
            status_marker = "[OK]"
        elif "Pending" in status:
            status_marker = "[..]"
        elif "Failed" in status:
            status_marker = "[!!]"
        elif "Offline" in status:
            status_marker = "[--]"

        line = f"{host:<20} | {emp:<18} | {inst:<10} | {latest:<10} | {status_marker} {status:<12} | {last_seen}"
        print(line)

        if d.get("failure_reason"):
            print(f"   --> Reason: {d['failure_reason']}")

    print("=" * 80 + "\n")
    return 0


if __name__ == "__main__":
    as_json = "--json" in sys.argv
    check_offline = "--check-offline" in sys.argv
    sys.exit(print_fleet_verification_report(as_json=as_json, check_offline=check_offline))

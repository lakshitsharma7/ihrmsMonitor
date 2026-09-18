"""System health metrics collector for iHRMS Monitor."""

from __future__ import annotations

import os
import platform
import socket
import time
import psutil
from utils.logger import get_logger

logger = get_logger(__name__)


def get_system_health() -> dict:
    """
    Collect overall laptop/workstation system health metrics dynamically.
    
    Returns a structured dictionary matching the backend schema:
    - cpu: {usage_percent, cores, logical_processors}
    - ram: {total, used, available, usage_percent}
    - disk: {total, used, free, usage_percent}
    - network: {status, sent, received}
    - battery: {percent, plugged}
    - os: string
    - hostname: string
    - uptime: string
    - flat keys (for backward compatibility)
    """
    # Base defaults
    cpu_usage = 0.0
    cpu_logical = os.cpu_count() or 1
    cpu_physical = 1
    ram_usage = 0.0
    ram_total_mb = 0.0
    ram_used_mb = 0.0
    ram_available_mb = 0.0
    disk_usage = 0.0
    disk_total_gb = 0.0
    disk_used_gb = 0.0
    disk_free_gb = 0.0
    net_status = "disconnected"
    net_sent_mb = 0.0
    net_recv_mb = 0.0
    battery_pct = 100.0
    battery_plugged = True
    uptime_sec = 0
    hostname_val = socket.gethostname()
    os_val = f"{platform.system()} {platform.version()}"

    # 1. CPU
    try:
        cpu_usage = round(float(psutil.cpu_percent(interval=None)), 1)
        cores = psutil.cpu_count(logical=True) or os.cpu_count()
        if cores:
            cpu_logical = int(cores)
        phys_cores = psutil.cpu_count(logical=False)
        if phys_cores:
            cpu_physical = int(phys_cores)
        else:
            cpu_physical = cpu_logical
    except Exception as cpu_err:
        logger.debug("SystemHealth: CPU metric collection error: %s", cpu_err)

    # 2. Memory / RAM
    try:
        mem = psutil.virtual_memory()
        ram_usage = round(float(mem.percent), 1)
        ram_total_mb = round(float(mem.total) / (1024 * 1024), 2)
        ram_used_mb = round(float(mem.used) / (1024 * 1024), 2)
        ram_available_mb = round(float(mem.available) / (1024 * 1024), 2)
    except Exception as mem_err:
        logger.debug("SystemHealth: Memory metric collection error: %s", mem_err)

    # 3. Disk
    try:
        root_path = os.path.abspath(os.sep)
        disk = psutil.disk_usage(root_path)
        disk_usage = round(float(disk.percent), 1)
        disk_total_gb = round(float(disk.total) / (1024 * 1024 * 1024), 2)
        disk_used_gb = round(float(disk.used) / (1024 * 1024 * 1024), 2)
        disk_free_gb = round(float(disk.free) / (1024 * 1024 * 1024), 2)
    except Exception as disk_err:
        logger.debug("SystemHealth: Disk metric collection error: %s", disk_err)

    # 4. Network
    try:
        net_io = psutil.net_io_counters()
        if net_io:
            net_sent_mb = round(float(net_io.bytes_sent) / (1024 * 1024), 2)
            net_recv_mb = round(float(net_io.bytes_recv) / (1024 * 1024), 2)

        is_connected = False
        try:
            if_stats = psutil.net_if_stats()
            for iface_name, stat in if_stats.items():
                if stat.isup and not iface_name.lower().startswith("loopback") and stat.speed > 0:
                    is_connected = True
                    break
        except Exception:
            pass

        if not is_connected and net_io and (net_io.bytes_sent > 0 or net_io.bytes_recv > 0):
            is_connected = True

        net_status = "connected" if is_connected else "disconnected"
    except Exception as net_err:
        logger.debug("SystemHealth: Network metric collection error: %s", net_err)

    # 5. Battery (if present)
    try:
        battery = psutil.sensors_battery()
        if battery is not None:
            battery_pct = round(float(battery.percent), 1)
            battery_plugged = bool(battery.power_plugged)
    except Exception as bat_err:
        logger.debug("SystemHealth: Battery metric collection error: %s", bat_err)

    # 6. System Uptime
    try:
        boot_time = psutil.boot_time()
        if boot_time:
            uptime_sec = int(time.time() - boot_time)
    except Exception as up_err:
        logger.debug("SystemHealth: Uptime metric collection error: %s", up_err)

    # 7. Hostname and OS
    try:
        hostname_val = socket.gethostname()
        os_val = f"{platform.system()} {platform.version()}"
    except Exception as host_err:
        logger.debug("SystemHealth: Hostname/OS metric collection error: %s", host_err)

    logger.info(
        "Health collection: CPU usage: %.1f%% | RAM usage: %.1f%% | Disk usage: %.1f%% | Network: %s",
        cpu_usage,
        ram_usage,
        disk_usage,
        net_status,
    )

    # Clean structured representation matching backend/Postman format
    structured_health = {
        "cpu": {
            "usage_percent": cpu_usage,
            "cores": cpu_physical,
            "logical_processors": cpu_logical,
        },
        "ram": {
            "total": f"{int(ram_total_mb)} MB",
            "used": f"{int(ram_used_mb)} MB",
            "available": f"{int(ram_available_mb)} MB",
            "usage_percent": ram_usage,
        },
        "disk": {
            "total": f"{int(disk_total_gb)} GB",
            "used": f"{int(disk_used_gb)} GB",
            "free": f"{int(disk_free_gb)} GB",
            "usage_percent": disk_usage,
        },
        "network": {
            "status": net_status,
            "sent": f"{net_sent_mb} MB",
            "received": f"{net_recv_mb} MB",
        },
        "os": os_val,
        "hostname": hostname_val,
        "battery": {
            "percent": battery_pct,
            "plugged": battery_plugged,
        },
        "uptime": f"{uptime_sec} seconds",
        # Flat legacy keys
        "cpu_usage_percent": cpu_usage,
        "cpu_logical_cores": cpu_logical,
        "cpu_physical_cores": cpu_physical,
        "ram_usage_percent": ram_usage,
        "ram_total_mb": ram_total_mb,
        "ram_used_mb": ram_used_mb,
        "ram_available_mb": ram_available_mb,
        "disk_usage_percent": disk_usage,
        "disk_total_gb": disk_total_gb,
        "disk_used_gb": disk_used_gb,
        "disk_free_gb": disk_free_gb,
        "network_status": net_status,
        "network_sent_mb": net_sent_mb,
        "network_received_mb": net_recv_mb,
        "battery_percent": battery_pct,
        "battery_plugged": battery_plugged,
        "system_uptime_seconds": uptime_sec,
    }

    return structured_health


def get_structured_system_health() -> dict:
    """Returns only the clean nested system_health dictionary for API serialization."""
    full = get_system_health()
    return {
        "cpu": full["cpu"],
        "ram": full["ram"],
        "disk": full["disk"],
        "os": full["os"],
        "hostname": full["hostname"],
        "battery": full["battery"],
        "uptime": full["uptime"],
    }

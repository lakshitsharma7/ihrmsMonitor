"""System health metrics collector for iHRMS Monitor."""

from __future__ import annotations

import os
import psutil
from utils.logger import get_logger

logger = get_logger(__name__)


def get_system_health() -> dict:
    """
    Collect overall laptop/workstation system health metrics.
    
    Returns a dictionary containing:
    - cpu_usage_percent
    - cpu_logical_cores
    - ram_usage_percent
    - ram_total_mb
    - ram_used_mb
    - ram_available_mb
    - disk_usage_percent
    - disk_total_gb
    - disk_free_gb
    - network_status
    - network_sent_mb
    - network_received_mb
    """
    health = {
        "cpu_usage_percent": 0.0,
        "cpu_logical_cores": os.cpu_count() or 1,
        "ram_usage_percent": 0.0,
        "ram_total_mb": 0.0,
        "ram_used_mb": 0.0,
        "ram_available_mb": 0.0,
        "disk_usage_percent": 0.0,
        "disk_total_gb": 0.0,
        "disk_free_gb": 0.0,
        "network_status": "disconnected",
        "network_sent_mb": 0.0,
        "network_received_mb": 0.0,
    }

    try:
        # 1. CPU
        try:
            health["cpu_usage_percent"] = round(float(psutil.cpu_percent(interval=None)), 1)
            cores = psutil.cpu_count(logical=True) or os.cpu_count()
            if cores:
                health["cpu_logical_cores"] = int(cores)
        except Exception as cpu_err:
            logger.debug("SystemHealth: CPU metric collection error: %s", cpu_err)

        # 2. Memory / RAM
        try:
            mem = psutil.virtual_memory()
            health["ram_usage_percent"] = round(float(mem.percent), 1)
            health["ram_total_mb"] = round(float(mem.total) / (1024 * 1024), 2)
            health["ram_used_mb"] = round(float(mem.used) / (1024 * 1024), 2)
            health["ram_available_mb"] = round(float(mem.available) / (1024 * 1024), 2)
        except Exception as mem_err:
            logger.debug("SystemHealth: Memory metric collection error: %s", mem_err)

        # 3. Disk
        try:
            root_path = os.path.abspath(os.sep)
            disk = psutil.disk_usage(root_path)
            health["disk_usage_percent"] = round(float(disk.percent), 1)
            health["disk_total_gb"] = round(float(disk.total) / (1024 * 1024 * 1024), 2)
            health["disk_free_gb"] = round(float(disk.free) / (1024 * 1024 * 1024), 2)
        except Exception as disk_err:
            logger.debug("SystemHealth: Disk metric collection error: %s", disk_err)

        # 4. Network
        try:
            net_io = psutil.net_io_counters()
            if net_io:
                health["network_sent_mb"] = round(float(net_io.bytes_sent) / (1024 * 1024), 2)
                health["network_received_mb"] = round(float(net_io.bytes_recv) / (1024 * 1024), 2)

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

            health["network_status"] = "connected" if is_connected else "disconnected"
        except Exception as net_err:
            logger.debug("SystemHealth: Network metric collection error: %s", net_err)

    except Exception as exc:
        logger.debug("SystemHealth: Unexpected error collecting metrics: %s", exc)

    return health

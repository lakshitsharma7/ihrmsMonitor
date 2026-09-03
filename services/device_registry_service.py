"""Device registry and auto-update verification service for iHRMS Monitor.

Tracks and verifies:
1. Every enrolled/registered Windows laptop device.
2. The real installed executable application version on each machine (from build metadata).
3. Status comparison against latest server release (Updated, Update Pending, Update Failed, Offline).
4. Failure reporting and last seen / last sync timestamps.
"""

from __future__ import annotations

import getpass
import platform
import socket
import threading
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from config.settings import get_running_app_version, APP_VERSION
from database.database import get_session
from database.models import EnrolledDevice
from services.update_service import is_newer_version
from utils.device import get_device_identifier
from utils.logger import get_logger

logger = get_logger(__name__)

# Threshold in seconds after which an inactive device is marked Offline / Not Recently Seen
OFFLINE_THRESHOLD_SECONDS = 2 * 60 * 60  # 2 hours


class DeviceRegistryService:
    """Service to track, verify, and report enrolled devices and their update status."""

    _instance: Optional[DeviceRegistryService] = None
    _lock = threading.Lock()

    def __new__(cls) -> DeviceRegistryService:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    @staticmethod
    def calculate_device_status(
        installed_version: str,
        latest_version: Optional[str] = None,
        last_seen: Optional[datetime] = None,
        has_failed: bool = False,
        failure_reason: Optional[str] = None,
    ) -> str:
        """Evaluate real-time update status for a device."""
        if has_failed or failure_reason:
            return "Update Failed"

        if last_seen:
            now = datetime.now(timezone.utc)
            # Normalize naive datetimes if needed
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            if (now - last_seen).total_seconds() > OFFLINE_THRESHOLD_SECONDS:
                return "Offline / Not Recently Seen"

        if latest_version and is_newer_version(latest_version, installed_version):
            return "Update Pending"

        return "Updated"

    def record_heartbeat(
        self,
        device_identifier: Optional[str] = None,
        hostname: Optional[str] = None,
        installed_version: Optional[str] = None,
        employee_id: Optional[str] = None,
        username: Optional[str] = None,
        device_token: Optional[str] = None,
        latest_version: Optional[str] = None,
    ) -> EnrolledDevice:
        """Record or update current machine heartbeat and real installed version."""
        dev_id = device_identifier or get_device_identifier()
        host = hostname or socket.gethostname()
        version = installed_version or get_running_app_version()
        os_user = getpass.getuser()
        now = datetime.now(timezone.utc)

        db = get_session()
        try:
            stmt = select(EnrolledDevice).where(EnrolledDevice.device_identifier == dev_id)
            device = db.execute(stmt).scalars().first()

            if device is None:
                device = EnrolledDevice(
                    device_identifier=dev_id,
                    hostname=host,
                    platform=platform.system(),
                    os_username=os_user,
                    employee_id=str(employee_id) if employee_id is not None else None,
                    username=username,
                    device_token=device_token,
                    installed_version=version,
                    latest_version=latest_version,
                    update_status="Updated" if (latest_version and not is_newer_version(latest_version, version)) else "Update Pending",
                    last_seen=now,
                )
                db.add(device)
            else:
                device.hostname = host
                device.installed_version = version
                device.last_seen = now
                if employee_id is not None:
                    device.employee_id = str(employee_id)
                if username is not None:
                    device.username = username
                if device_token is not None:
                    device.device_token = device_token
                if latest_version is not None:
                    device.latest_version = latest_version

                # Re-evaluate status
                device.update_status = self.calculate_device_status(
                    installed_version=device.installed_version,
                    latest_version=device.latest_version,
                    last_seen=device.last_seen,
                    has_failed=bool(device.failure_reason),
                    failure_reason=device.failure_reason,
                )

            db.commit()
            db.refresh(device)
            return device
        except Exception as e:
            db.rollback()
            logger.exception("Failed to record device heartbeat: %s", e)
            raise
        finally:
            db.close()

    def record_sync_success(self, device_identifier: Optional[str] = None) -> None:
        """Update last_sync and last_seen timestamp on successful activity sync."""
        dev_id = device_identifier or get_device_identifier()
        now = datetime.now(timezone.utc)
        db = get_session()
        try:
            stmt = select(EnrolledDevice).where(EnrolledDevice.device_identifier == dev_id)
            device = db.execute(stmt).scalars().first()
            if device:
                device.last_sync = now
                device.last_seen = now
                device.update_status = self.calculate_device_status(
                    installed_version=device.installed_version,
                    latest_version=device.latest_version,
                    last_seen=device.last_seen,
                    has_failed=bool(device.failure_reason),
                    failure_reason=device.failure_reason,
                )
                db.commit()
        except Exception as e:
            db.rollback()
            logger.debug("Could not record sync timestamp: %s", e)
        finally:
            db.close()

    def record_update_pending(
        self,
        latest_version: str,
        device_identifier: Optional[str] = None,
    ) -> None:
        """Mark update available and pending on device."""
        dev_id = device_identifier or get_device_identifier()
        now = datetime.now(timezone.utc)
        db = get_session()
        try:
            stmt = select(EnrolledDevice).where(EnrolledDevice.device_identifier == dev_id)
            device = db.execute(stmt).scalars().first()
            if not device:
                self.record_heartbeat(device_identifier=dev_id, latest_version=latest_version)
                return

            device.latest_version = latest_version
            device.last_seen = now
            device.failure_reason = None
            device.update_status = "Update Pending"
            db.commit()
            logger.info("Device %s marked Update Pending for v%s", dev_id, latest_version)
        except Exception as e:
            db.rollback()
            logger.debug("Could not record update pending: %s", e)
        finally:
            db.close()

    def record_update_failure(
        self,
        reason: str,
        device_identifier: Optional[str] = None,
        target_version: Optional[str] = None,
    ) -> None:
        """Record update failure and reason for this device."""
        dev_id = device_identifier or get_device_identifier()
        now = datetime.now(timezone.utc)
        db = get_session()
        try:
            stmt = select(EnrolledDevice).where(EnrolledDevice.device_identifier == dev_id)
            device = db.execute(stmt).scalars().first()
            if not device:
                device = self.record_heartbeat(device_identifier=dev_id)

            device.failure_reason = str(reason)[:500]
            device.update_status = "Update Failed"
            if target_version:
                device.latest_version = target_version
            device.last_seen = now
            db.commit()
            logger.warning("Device %s marked Update Failed: %s", dev_id, reason)
        except Exception as e:
            db.rollback()
            logger.debug("Could not record update failure: %s", e)
        finally:
            db.close()

    def record_update_success(
        self,
        new_version: Optional[str] = None,
        device_identifier: Optional[str] = None,
    ) -> None:
        """Record that device is now running the new version."""
        dev_id = device_identifier or get_device_identifier()
        version = new_version or get_running_app_version()
        now = datetime.now(timezone.utc)
        db = get_session()
        try:
            stmt = select(EnrolledDevice).where(EnrolledDevice.device_identifier == dev_id)
            device = db.execute(stmt).scalars().first()
            if not device:
                device = self.record_heartbeat(device_identifier=dev_id, installed_version=version)

            device.installed_version = version
            device.failure_reason = None
            device.update_status = "Updated"
            device.last_seen = now
            db.commit()
            logger.info("Device %s verified and marked Updated (running v%s)", dev_id, version)
        except Exception as e:
            db.rollback()
            logger.debug("Could not record update success: %s", e)
        finally:
            db.close()

    def get_all_devices(self) -> List[Dict[str, Any]]:
        """Retrieve all enrolled devices with refreshed real-time status."""
        db = get_session()
        try:
            stmt = select(EnrolledDevice).order_by(EnrolledDevice.last_seen.desc())
            devices = db.execute(stmt).scalars().all()
            result = []

            for d in devices:
                status = self.calculate_device_status(
                    installed_version=d.installed_version,
                    latest_version=d.latest_version,
                    last_seen=d.last_seen,
                    has_failed=bool(d.failure_reason),
                    failure_reason=d.failure_reason,
                )
                result.append({
                    "id": d.id,
                    "device_identifier": d.device_identifier,
                    "hostname": d.hostname,
                    "platform": d.platform,
                    "os_username": d.os_username,
                    "employee_id": d.employee_id,
                    "username": d.username,
                    "installed_version": d.installed_version,
                    "latest_version": d.latest_version or "N/A",
                    "update_status": status,
                    "failure_reason": d.failure_reason,
                    "last_seen": d.last_seen.isoformat() if d.last_seen else None,
                    "last_sync": d.last_sync.isoformat() if d.last_sync else None,
                })

            return result
        finally:
            db.close()

    def get_device_summary(self) -> Dict[str, int]:
        """Return counts of devices grouped by update status."""
        devices = self.get_all_devices()
        summary = {
            "total": len(devices),
            "updated": 0,
            "pending": 0,
            "failed": 0,
            "offline": 0,
        }

        for d in devices:
            st = d["update_status"]
            if st == "Updated":
                summary["updated"] += 1
            elif st == "Update Pending":
                summary["pending"] += 1
            elif st == "Update Failed":
                summary["failed"] += 1
            elif "Offline" in st:
                summary["offline"] += 1

        return summary

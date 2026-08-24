from datetime import datetime
from pydantic import BaseModel


class DeviceInfo(BaseModel):
    username: str
    hostname: str
    platform: str


class SyncPeriod(BaseModel):
    from_: datetime
    to: datetime

    class Config:
        populate_by_name = True


class ActivitySession(BaseModel):
    activity_session_id: int
    application_name: str
    process_id: int | None = None
    started_at: datetime
    ended_at: datetime | None = None
    duration_seconds: float


class ApplicationTotal(BaseModel):
    application_name: str
    total_duration_seconds: float


class ActivitySyncRequest(BaseModel):
    device: DeviceInfo
    sync: SyncPeriod
    activities: list[ActivitySession]
    totals: list[ApplicationTotal]
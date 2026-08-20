"""Lightweight, platform-independent representation of the current session.

This is distinct from ``database.models.ActivitySession`` (the persisted
row) - this class just tracks in-memory state that the tracker uses to
decide when a *new* database session needs to be created.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class CurrentSession:
    """The activity session currently being tracked in memory.

    ``db_id`` mirrors the primary key of the corresponding
    ``ActivitySession`` row so the tracker can update/close it later.
    """

    db_id: int
    application_name: str
    process_id: int | None
    window_title: str | None
    started_at: datetime

    def matches_application(self, application_name: str, process_id: int | None) -> bool:
        """Return True if the given app/pid is a continuation of this session.

        We compare on application name AND process id when both sides have a
        pid, since the same application name could legitimately correspond
        to a fresh process (e.g. app restarted). If either pid is missing we
        fall back to comparing names only, to remain resilient to platforms
        where pid resolution occasionally fails.
        """
        if self.application_name != application_name:
            return False
        if self.process_id is not None and process_id is not None:
            return self.process_id == process_id
        return True

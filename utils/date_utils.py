"""
Shared Date and Time Formatting Utilities for iHRMS Desktop.

Standard Display Date Format: DD-MM-YYYY (represented by Python's %d-%m-%Y).
Converts internal or API date formats (e.g. YYYY-MM-DD) into user-facing DD-MM-YYYY
without modifying backend API contracts or database storage.
"""

from __future__ import annotations

from datetime import date, datetime
import re
from typing import Any

# Standard user-facing date display format throughout iHRMS Desktop
DISPLAY_DATE_FORMAT = "%d-%m-%Y"


def format_date_display(val: Any, default: str = "") -> str:
    """
    Format any date object or date string into standard DD-MM-YYYY format.

    Examples:
        '2026-09-09'       -> '09-09-2026'
        '2026-10-13'       -> '13-10-2026'
        '2026-09-09 (Wed)' -> '09-09-2026 (Wed)'
        '2026-09-09, Wed'  -> '09-09-2026, Wed'
        date(2026, 10, 13) -> '13-10-2026'
        '13-10-2026'       -> '13-10-2026'
        None               -> default

    Args:
        val: datetime, date, or date string representation.
        default: Fallback string if value is empty or invalid.

    Returns:
        Formatted string in DD-MM-YYYY format.
    """
    if val is None:
        return default

    if isinstance(val, (datetime, date)):
        return val.strftime(DISPLAY_DATE_FORMAT)

    val_str = str(val).strip()
    if not val_str or val_str.lower() in ("none", "null", "-", "—"):
        return default

    # Match ISO/standard patterns with optional trailing weekday/suffix
    # e.g. "2026-09-09 (Wed)", "2026-09-09, Wed", "2026-09-09"
    match_iso = re.match(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})(\s*.*)$", val_str)
    if match_iso:
        year, month, day, extra = match_iso.groups()
        return f"{int(day):02d}-{int(month):02d}-{int(year):04d}{extra}"

    # Already in DD-MM-YYYY format (with optional suffix)
    match_dmy = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})(\s*.*)$", val_str)
    if match_dmy:
        day, month, year, extra = match_dmy.groups()
        return f"{int(day):02d}-{int(month):02d}-{int(year):04d}{extra}"

    # Try standard string parsing formats
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
    ):
        try:
            # Check prefix length to handle ISO timestamps
            dt = datetime.strptime(val_str[:19] if len(val_str) >= 19 else val_str[:10], fmt)
            return dt.strftime(DISPLAY_DATE_FORMAT)
        except Exception:
            pass

    return val_str


def parse_date_safe(val: Any) -> date | None:
    """Safely parse a date string or object into a datetime.date."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val

    val_str = str(val).strip()
    if not val_str:
        return None

    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(val_str[:10], fmt).date()
        except Exception:
            pass

    return None

"""Relative posted-at text parsing into Central-time calendar dates."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import re
from zoneinfo import ZoneInfo


CENTRAL_TZ = ZoneInfo("America/Chicago")

# Supported high-confidence patterns from Serp detected_extensions.posted_at.
HOURS_AGO_PATTERN = re.compile(r"^(\d+)\s+hours?\s+ago$")
DAYS_AGO_PATTERN = re.compile(r"^(\d+)\+?\s+days?\s+ago$")
WEEKS_AGO_PATTERN = re.compile(r"^(\d+)\s+weeks?\s+ago$")


def derive_posted_date(
    posted_at_text: str | None,
    anchor_requested_at_utc: str,
) -> str | None:
    """Convert relative posted-at text to a Central date (YYYY-MM-DD)."""
    if not posted_at_text:
        return None

    anchor_dt_utc = _parse_anchor_utc(anchor_requested_at_utc)
    text = posted_at_text.strip().lower()

    if text == "today":
        return anchor_dt_utc.astimezone(CENTRAL_TZ).date().isoformat()

    if text == "yesterday":
        anchor_local_date = anchor_dt_utc.astimezone(CENTRAL_TZ).date()
        return (anchor_local_date - timedelta(days=1)).isoformat()

    hours_match = HOURS_AGO_PATTERN.match(text)
    if hours_match:
        hours = int(hours_match.group(1))
        return _to_central_date(anchor_dt_utc - timedelta(hours=hours))

    days_match = DAYS_AGO_PATTERN.match(text)
    if days_match:
        days = int(days_match.group(1))
        return _to_central_date(anchor_dt_utc - timedelta(days=days))

    weeks_match = WEEKS_AGO_PATTERN.match(text)
    if weeks_match:
        weeks = int(weeks_match.group(1))
        return _to_central_date(anchor_dt_utc - timedelta(weeks=weeks))

    return None


def _parse_anchor_utc(anchor_requested_at_utc: str) -> datetime:
    """Parse an ISO timestamp and normalize to timezone-aware UTC."""
    parsed = datetime.fromisoformat(anchor_requested_at_utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _to_central_date(dt_utc: datetime) -> str:
    """Convert UTC datetime to America/Chicago date."""
    return dt_utc.astimezone(CENTRAL_TZ).date().isoformat()

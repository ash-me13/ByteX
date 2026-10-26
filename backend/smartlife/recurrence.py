"""
Recurrence and time-zone arithmetic. Pure functions, no I/O.

Conventions
-----------
* Instants are stored in UTC ("YYYY-MM-DDTHH:MM:SSZ"); the item's IANA time zone says what "wall clock" means.
* A recurrence rule is a plain dict: {"freq": daily|weekly|monthly|yearly, "interval": 1.., "anchor": "YYYY-MM-DD",
  "anchor_time": "HH:MM" (the local wall time of the series; keeps it stable after a DST gap), "until": "YYYY-MM-DD" (optional)}. The anchor date is the first local date of the series, so a monthly rule anchored
  on the 31st gives Jan 31, Feb 28/29, Mar 31 ... (it clamps to the month end but never drifts) and a yearly rule
  anchored on 29 Feb gives 28 Feb in non-leap years and 29 Feb in leap years.
* The local wall-clock time is preserved across daylight-saving changes. A wall time that does not exist (spring
  forward) moves forward by the gap; an ambiguous wall time (fall back) uses its first occurrence.
"""
import calendar
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

FREQUENCIES = ("daily", "weekly", "monthly", "yearly")
UTC = timezone.utc
_MAX_STEPS = 100000


class RecurrenceError(ValueError):
    pass


def get_zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise RecurrenceError(f"Unknown time zone '{name}'.")


def to_utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise RecurrenceError("A timezone-aware datetime is required.")
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def from_utc_iso(text: str) -> datetime:
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except (TypeError, ValueError):
        raise RecurrenceError(f"Invalid stored timestamp '{text}'.")


def local_to_utc(d: date, t: time, zone: ZoneInfo) -> datetime:
    """Wall-clock date+time in ``zone`` -> aware UTC datetime. Non-existent wall times move forward by the gap."""
    naive = datetime.combine(d, t.replace(tzinfo=None))
    aware = naive.replace(tzinfo=zone, fold=0)
    utc = aware.astimezone(UTC)
    back = utc.astimezone(zone).replace(tzinfo=None)
    if back != naive:  # the wall time falls in a DST gap: use the instant just after the gap
        return utc
    return utc


def validate_rule(rule: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if rule is None:
        return None
    if not isinstance(rule, dict):
        raise RecurrenceError("Recurrence must be an object.")
    freq = str(rule.get("freq", "")).lower()
    if freq not in FREQUENCIES:
        raise RecurrenceError(f"Recurrence frequency must be one of {', '.join(FREQUENCIES)}.")
    try:
        interval = int(rule.get("interval", 1))
    except (TypeError, ValueError):
        raise RecurrenceError("Recurrence interval must be a whole number.")
    if not 1 <= interval <= 366:
        raise RecurrenceError("Recurrence interval must be between 1 and 366.")
    out: Dict[str, Any] = {"freq": freq, "interval": interval}
    anchor = rule.get("anchor")
    if anchor is not None:
        try:
            out["anchor"] = date.fromisoformat(str(anchor)).isoformat()
        except ValueError:
            raise RecurrenceError("Recurrence anchor must be a date like 2026-10-27.")
    anchor_time = rule.get("anchor_time")
    if anchor_time is not None:
        try:
            out["anchor_time"] = time.fromisoformat(str(anchor_time)).replace(second=0, microsecond=0).isoformat()
        except ValueError:
            raise RecurrenceError("Recurrence anchor_time must be a time like 09:00.")
    until = rule.get("until")
    if until:
        try:
            out["until"] = date.fromisoformat(str(until)).isoformat()
        except ValueError:
            raise RecurrenceError("Recurrence 'until' must be a date like 2027-10-27.")
    extra = set(rule) - {"freq", "interval", "anchor", "anchor_time", "until"}
    if extra:
        raise RecurrenceError(f"Unsupported recurrence field(s): {', '.join(sorted(extra))}.")
    return out


def _advance_date(anchor: date, current: date, rule: Dict[str, Any]) -> date:
    interval = rule["interval"]
    freq = rule["freq"]
    if freq == "daily":
        return current + timedelta(days=interval)
    if freq == "weekly":
        return current + timedelta(days=7 * interval)
    if freq == "monthly":
        index = current.year * 12 + current.month - 1 + interval
        year, month = divmod(index, 12)
        month += 1
        return date(year, month, min(anchor.day, calendar.monthrange(year, month)[1]))
    year = current.year + interval  # yearly
    if not 1 <= year <= 9999:
        raise RecurrenceError("Recurrence runs past the supported year range.")
    return date(year, anchor.month, min(anchor.day, calendar.monthrange(year, anchor.month)[1]))


def next_occurrence(rule: Dict[str, Any], tz_name: str, current_utc: datetime, after_utc: Optional[datetime] = None) -> Optional[datetime]:
    """
    First occurrence strictly after ``max(current, after)``, preserving the local wall-clock time, or None when the
    series has ended (``until``). ``current_utc`` is the current occurrence (it fixes the local time of day).
    """
    rule = validate_rule(rule)
    zone = get_zone(tz_name)
    current_local = current_utc.astimezone(zone)
    wall = time.fromisoformat(rule["anchor_time"]) if rule.get("anchor_time") else current_local.time().replace(tzinfo=None)
    anchor = date.fromisoformat(rule["anchor"]) if rule.get("anchor") else current_local.date()
    floor = current_utc if after_utc is None or after_utc < current_utc else after_utc
    until = date.fromisoformat(rule["until"]) if rule.get("until") else None

    cursor = current_local.date()
    for _ in range(_MAX_STEPS):
        cursor = _advance_date(anchor, cursor, rule)
        if until and cursor > until:
            return None
        candidate = local_to_utc(cursor, wall, zone)
        if candidate > floor:
            return candidate
    raise RecurrenceError("Could not compute the next occurrence.")


def occurrences_between(rule: Dict[str, Any], tz_name: str, first_utc: datetime, start_utc: datetime, end_utc: datetime, limit: int = 400):
    """Occurrences (starting with ``first_utc``) that fall in [start, end]."""
    out = []
    cur: Optional[datetime] = first_utc
    while cur is not None and cur <= end_utc and len(out) < limit:
        if cur >= start_utc:
            out.append(cur)
        cur = next_occurrence(rule, tz_name, cur)
    return out

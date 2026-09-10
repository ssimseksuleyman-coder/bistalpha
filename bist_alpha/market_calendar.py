"""Versioned, offline XIST market-calendar authority.

Runtime decisions use the checked-in Borsa Istanbul calendar artifact. Network
checks and exchange_calendars are validation tools, not runtime authorities.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


CALENDAR_DIR = Path(__file__).resolve().parents[1] / "data" / "calendar"
CALENDAR_REJECT_CODE = "CALENDAR_UNAVAILABLE"


class CalendarUnavailableError(RuntimeError):
    reject_code = CALENDAR_REJECT_CODE


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _as_time(value) -> time:
    return time.fromisoformat(str(value))


def _local_now(value, calendar) -> datetime:
    timezone = ZoneInfo(calendar["timezone"])
    if value is None:
        return datetime.now(timezone)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone)
    return value.astimezone(timezone)


def _validate_calendar(calendar, path) -> None:
    required = {
        "market", "timezone", "valid_from", "valid_through",
        "session_hours", "full_day_closures", "half_days", "source",
        "renewal_policy", "source_check_contract",
    }
    missing = sorted(required - set(calendar))
    if missing:
        raise CalendarUnavailableError(
            f"Takvim artefakti eksik alan tasiyor: {', '.join(missing)}"
        )
    if calendar["market"] != "XIST":
        raise CalendarUnavailableError("Takvim market alani XIST degil")
    try:
        ZoneInfo(calendar["timezone"])
        valid_from = _as_date(calendar["valid_from"])
        valid_through = _as_date(calendar["valid_through"])
        if valid_from > valid_through:
            raise ValueError("valid_from valid_through sonrasinda")
        hours = calendar["session_hours"]
        _as_time(hours["regular_close"])
        _as_time(hours["half_day_close"])
        closures = [_as_date(item) for item in calendar["full_day_closures"]]
        half_days = {
            _as_date(item["date"]): _as_time(item["close"])
            for item in calendar["half_days"]
        }
        source_sha = calendar["source"]["sha256"]
        if not re.fullmatch(r"[0-9a-f]{64}", source_sha):
            raise ValueError("source.sha256 gecersiz")
        warning_days = int(
            calendar["renewal_policy"]["warning_days_before_expiry"]
        )
        if warning_days < 0:
            raise ValueError("yenileme uyari gunu negatif")
    except (KeyError, TypeError, ValueError) as exc:
        raise CalendarUnavailableError(
            f"Takvim artefakti gecersiz ({path}): {exc}"
        ) from exc

    calendar["_valid_from"] = valid_from
    calendar["_valid_through"] = valid_through
    calendar["_closures"] = frozenset(closures)
    calendar["_half_days"] = half_days
    calendar["_path"] = str(path)


def load_calendar(path=None, *, year=None):
    """Load and validate one checked-in annual XIST calendar."""
    if path is None:
        if year is None:
            year = datetime.now(ZoneInfo("Europe/Istanbul")).year
        path = CALENDAR_DIR / f"xist_{int(year)}.json"
    path = Path(path)
    try:
        calendar = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CalendarUnavailableError(
            f"Takvim artefakti okunamadi ({path}): {exc}"
        ) from exc
    if not isinstance(calendar, dict):
        raise CalendarUnavailableError(f"Takvim artefakti nesne degil: {path}")
    _validate_calendar(calendar, path)
    return calendar


def is_session(day, calendar) -> bool:
    day = _as_date(day)
    return (
        calendar["_valid_from"] <= day <= calendar["_valid_through"]
        and day.weekday() < 5
        and day not in calendar["_closures"]
    )


def sessions_between(start, end, calendar):
    """Return inclusive official sessions inside the artifact's valid range."""
    start = max(_as_date(start), calendar["_valid_from"])
    end = min(_as_date(end), calendar["_valid_through"])
    if start > end:
        return []
    sessions = []
    current = start
    while current <= end:
        if is_session(current, calendar):
            sessions.append(current)
        current += timedelta(days=1)
    return sessions


def expected_last_closed_session(now, calendar):
    """Return the latest XIST session whose official close has passed."""
    local_now = _local_now(now, calendar)
    current = local_now.date()
    if not (calendar["_valid_from"] <= current <= calendar["_valid_through"]):
        raise CalendarUnavailableError(
            f"Takvim {current.isoformat()} tarihini kapsamiyor"
        )

    while current >= calendar["_valid_from"]:
        if is_session(current, calendar):
            close_at = calendar["_half_days"].get(
                current,
                _as_time(calendar["session_hours"]["regular_close"]),
            )
            if current < local_now.date() or local_now.time() >= close_at:
                return current
        current -= timedelta(days=1)
    raise CalendarUnavailableError("Takvimde kapanmis bir seans bulunamadi")


def assess_freshness(last_data_date, now, calendar):
    """Assess session freshness without claiming that an intraday bar is final."""
    expected = expected_last_closed_session(now, calendar)
    try:
        actual = _as_date(last_data_date)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"last_data_date gecersiz: {last_data_date}") from exc
    fresh = actual >= expected
    return {
        "freshness_status": "FRESH" if fresh else "STALE",
        "last_data_date": actual.isoformat(),
        "expected_last_closed_session": expected.isoformat(),
        "bar_completeness": "unknown",
        "reject_code": None if fresh else "STALE_LAST_DATA",
    }


def renewal_status(now, next_calendar_available, calendar):
    """Report lifecycle state; an expired annual artifact is fail-closed."""
    local_now = _local_now(now, calendar)
    current = local_now.date()
    valid_from = calendar["_valid_from"]
    valid_through = calendar["_valid_through"]
    if current < valid_from or current > valid_through:
        return {
            "status": "UNAVAILABLE",
            "days_remaining": (valid_through - current).days,
            "reject_code": CALENDAR_REJECT_CODE,
        }
    days_remaining = (valid_through - current).days
    warning_days = int(
        calendar["renewal_policy"]["warning_days_before_expiry"]
    )
    warning = days_remaining <= warning_days and not next_calendar_available
    return {
        "status": "WARNING" if warning else "OK",
        "days_remaining": days_remaining,
        "reject_code": None,
    }


def classify_source_check(reachable, observed_sha256, expected_sha256):
    """Keep an unreachable authority distinct from a measured hash change."""
    if not reachable:
        return "UNREACHABLE"
    return "UNCHANGED" if observed_sha256 == expected_sha256 else "CHANGED"

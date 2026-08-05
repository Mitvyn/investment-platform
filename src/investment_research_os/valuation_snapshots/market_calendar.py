from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from importlib import resources
from typing import cast
from zoneinfo import ZoneInfo

from investment_research_os.valuation_snapshots import ValuationSnapshotError
from investment_research_os.valuation_snapshots.market_proofs import (
    UsEquitiesSessionDefinition,
    VersionedUsEquitiesCalendar,
)


PACKAGED_US_EQUITIES_CALENDAR_VERSION = "us-equities-calendar-2026.v1"
_CALENDAR_RESOURCE_PACKAGE = "investment_research_os.valuation_snapshots.data"
_CALENDAR_RESOURCES = {
    PACKAGED_US_EQUITIES_CALENDAR_VERSION: "us_equities_calendar_2026.v1.json",
}
_EXPECTED_KEYS = frozenset(
    {
        "calendar_version",
        "coverage_start",
        "coverage_end",
        "timezone",
        "supported_exchanges",
        "regular_session",
        "closed_weekdays",
        "holiday_dates",
        "early_closes",
    }
)


def load_packaged_us_equities_calendar(
    calendar_version: str = PACKAGED_US_EQUITIES_CALENDAR_VERSION,
) -> VersionedUsEquitiesCalendar:
    """Load a pinned calendar artifact without network or mutable state."""

    resource_name = _CALENDAR_RESOURCES.get(calendar_version)
    if resource_name is None:
        raise ValuationSnapshotError("market calendar version is not packaged")
    try:
        raw = (
            resources.files(_CALENDAR_RESOURCE_PACKAGE)
            .joinpath(resource_name)
            .read_text(encoding="utf-8")
        )
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        raise ValuationSnapshotError(
            "packaged market calendar is unreadable"
        ) from error
    if not isinstance(payload, dict) or set(payload) != _EXPECTED_KEYS:
        raise ValuationSnapshotError("packaged market calendar schema is invalid")
    if payload["calendar_version"] != calendar_version:
        raise ValuationSnapshotError("packaged market calendar version mismatches")

    coverage_start = _parse_date(payload["coverage_start"])
    coverage_end = _parse_date(payload["coverage_end"])
    try:
        timezone = ZoneInfo(_require_string(payload["timezone"]))
    except (KeyError, ValueError) as error:
        raise ValuationSnapshotError(
            "packaged market calendar timezone is invalid"
        ) from error

    exchanges = payload["supported_exchanges"]
    weekdays = payload["closed_weekdays"]
    holidays = payload["holiday_dates"]
    regular_session = payload["regular_session"]
    early_closes = payload["early_closes"]
    if (
        not isinstance(exchanges, list)
        or not all(isinstance(exchange, str) for exchange in exchanges)
        or not isinstance(weekdays, list)
        or not all(type(weekday) is int for weekday in weekdays)
        or not isinstance(holidays, list)
        or not isinstance(regular_session, dict)
        or set(regular_session) != {"opens_at", "closes_at"}
        or not isinstance(early_closes, list)
    ):
        raise ValuationSnapshotError("packaged market calendar schema is invalid")

    open_time = _parse_time(regular_session["opens_at"])
    regular_close_time = _parse_time(regular_session["closes_at"])
    holiday_dates = frozenset(_parse_date(value) for value in holidays)
    closed_weekdays = frozenset(weekdays)
    if not closed_weekdays.issubset(range(7)):
        raise ValuationSnapshotError("packaged market calendar weekdays are invalid")
    early_close_by_date = _parse_early_closes(early_closes)

    sessions: list[UsEquitiesSessionDefinition] = []
    closed_dates: set[date] = set()
    for session_date in _date_range(coverage_start, coverage_end):
        if session_date.weekday() in closed_weekdays or session_date in holiday_dates:
            closed_dates.add(session_date)
            continue
        close_time = early_close_by_date.get(session_date, regular_close_time)
        sessions.append(
            UsEquitiesSessionDefinition(
                session_date=session_date,
                opens_at=datetime.combine(session_date, open_time, timezone),
                closes_at=datetime.combine(session_date, close_time, timezone),
                early_close=session_date in early_close_by_date,
            )
        )
    if not set(early_close_by_date).issubset(
        {session.session_date for session in sessions}
    ):
        raise ValuationSnapshotError("packaged market calendar early close is invalid")

    try:
        return VersionedUsEquitiesCalendar(
            calendar_version=calendar_version,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            sessions=tuple(sessions),
            closed_dates=frozenset(closed_dates),
            supported_exchanges=frozenset(cast(list[str], exchanges)),
        )
    except ValueError as error:
        raise ValuationSnapshotError("packaged market calendar is invalid") from error


def _date_range(start: date, end: date) -> tuple[date, ...]:
    if end < start:
        raise ValuationSnapshotError("packaged market calendar coverage is invalid")
    return tuple(
        start + timedelta(days=offset) for offset in range((end - start).days + 1)
    )


def _parse_early_closes(value: list[object]) -> dict[date, time]:
    result: dict[date, time] = {}
    for item in value:
        if not isinstance(item, dict) or set(item) != {"session_date", "closes_at"}:
            raise ValuationSnapshotError(
                "packaged market calendar early close is invalid"
            )
        session_date = _parse_date(item["session_date"])
        if session_date in result:
            raise ValuationSnapshotError(
                "packaged market calendar early close is invalid"
            )
        result[session_date] = _parse_time(item["closes_at"])
    return result


def _parse_date(value: object) -> date:
    text = _require_string(value)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as error:
        raise ValuationSnapshotError(
            "packaged market calendar date is invalid"
        ) from error
    if parsed.isoformat() != text:
        raise ValuationSnapshotError("packaged market calendar date is invalid")
    return parsed


def _parse_time(value: object) -> time:
    text = _require_string(value)
    try:
        parsed = time.fromisoformat(text)
    except ValueError as error:
        raise ValuationSnapshotError(
            "packaged market calendar time is invalid"
        ) from error
    if parsed.tzinfo is not None or parsed.strftime("%H:%M:%S") != text:
        raise ValuationSnapshotError("packaged market calendar time is invalid")
    return parsed


def _require_string(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValuationSnapshotError("packaged market calendar value is invalid")
    return value


__all__ = [
    "PACKAGED_US_EQUITIES_CALENDAR_VERSION",
    "load_packaged_us_equities_calendar",
]

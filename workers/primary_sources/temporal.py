from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
import re


_DATE_ONLY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True, slots=True)
class PublicationTimeAssessment:
    state: str
    reason_code: str
    valid_at_cutoff: bool
    published_at: datetime | None
    publication_date: date | None


def _require_cutoff(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("cutoff must include timezone")
    return value.astimezone(UTC)


def assess_publication_time(
    value: object,
    as_of_cutoff: datetime,
) -> PublicationTimeAssessment:
    cutoff = _require_cutoff(as_of_cutoff)
    if value is None:
        return PublicationTimeAssessment(
            state="unavailable",
            reason_code="publication_time_unavailable",
            valid_at_cutoff=False,
            published_at=None,
            publication_date=None,
        )
    if not isinstance(value, str):
        raise ValueError("publication time is invalid")
    if _DATE_ONLY_PATTERN.fullmatch(value):
        try:
            publication_date = date.fromisoformat(value)
        except ValueError as error:
            raise ValueError("publication time is invalid") from error
        latest_possible_time = datetime.combine(
            publication_date,
            time.max,
            tzinfo=UTC,
        )
        valid = latest_possible_time <= cutoff
        return PublicationTimeAssessment(
            state="date_only",
            reason_code=(
                "publication_date_verified_before_cutoff"
                if valid
                else "publication_time_date_only_at_cutoff"
            ),
            valid_at_cutoff=valid,
            published_at=None,
            publication_date=publication_date,
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("publication time is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return PublicationTimeAssessment(
            state="timezone_ambiguous",
            reason_code="publication_timezone_unresolved",
            valid_at_cutoff=False,
            published_at=None,
            publication_date=parsed.date(),
        )
    published_at = parsed.astimezone(UTC)
    valid = published_at <= cutoff
    return PublicationTimeAssessment(
        state="exact" if valid else "after_cutoff",
        reason_code=(
            "publication_time_verified_at_cutoff"
            if valid
            else "publication_after_cutoff"
        ),
        valid_at_cutoff=valid,
        published_at=published_at,
        publication_date=published_at.date(),
    )

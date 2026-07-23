from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
import hashlib
import json
from typing import Callable, Mapping

from workers.primary_sources.models import PrimarySourceRequest
from workers.primary_sources.temporal import assess_publication_time

from .collector import (
    ACCESSION_PATTERN,
    DOCUMENT_PATTERN,
    BytesTransport,
    SecSettings,
)


_RECENT_FIELDS = (
    "accessionNumber",
    "acceptanceDateTime",
    "filingDate",
    "reportDate",
    "form",
    "primaryDocument",
)


class SecSubmissionsError(RuntimeError):
    """Raised when SEC submissions metadata cannot be trusted."""


@dataclass(frozen=True, slots=True)
class SecSubmissionFiling:
    accession_number: str
    form: str
    filing_date: date
    report_date: date | None
    primary_document: str
    archive_url: str
    acceptance_time_raw: str | None
    publication_state: str
    publication_reason_code: str
    valid_at_cutoff: bool
    published_at: datetime | None
    publication_date: date | None

    @property
    def reason_code(self) -> str:
        return self.publication_reason_code


@dataclass(frozen=True, slots=True)
class SecSubmissionsSnapshot:
    operator_id: str
    security_id: str
    cik: str
    issuer_name: str
    sec_issuer_name: str
    as_of_cutoff: datetime
    source_url: str
    retrieved_at: datetime
    content_sha256: str
    included_filings: tuple[SecSubmissionFiling, ...]
    excluded_filings: tuple[SecSubmissionFiling, ...]


class SecSubmissionsCollector:
    def __init__(
        self,
        settings: SecSettings,
        *,
        transport: BytesTransport,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if settings.base_url.rstrip("/") != "https://data.sec.gov":
            raise ValueError("SEC submissions base URL is unsupported")
        self.settings = settings
        self.transport = transport
        self.clock = clock or (lambda: datetime.now(UTC))

    def discover(
        self,
        request: PrimarySourceRequest,
    ) -> SecSubmissionsSnapshot:
        source_url = (
            f"{self.settings.base_url.rstrip('/')}/submissions/"
            f"CIK{request.cik}.json"
        )
        response = self.transport.request(
            source_url,
            headers={
                "Accept": "application/json",
                "User-Agent": self.settings.user_agent,
            },
        )
        if not 200 <= response.status < 300:
            raise SecSubmissionsError(
                f"SEC returned HTTP {response.status} for submissions request"
            )
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SecSubmissionsError(
                "SEC submissions response is invalid JSON"
            ) from error
        if not isinstance(payload, dict):
            raise SecSubmissionsError("SEC submissions response is invalid")
        response_cik = self._canonical_cik(payload.get("cik"))
        if response_cik != request.cik:
            raise SecSubmissionsError("SEC submissions CIK mismatch")
        sec_issuer_name = payload.get("name")
        if not isinstance(sec_issuer_name, str) or not sec_issuer_name.strip():
            raise SecSubmissionsError("SEC submissions issuer name is invalid")
        recent = self._recent(payload)
        filings = tuple(
            self._filing(
                request=request,
                row={field: recent[field][index] for field in _RECENT_FIELDS},
            )
            for index in range(len(recent[_RECENT_FIELDS[0]]))
        )
        retrieved_at = self.clock()
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise RuntimeError("SEC submissions clock must include timezone")
        return SecSubmissionsSnapshot(
            operator_id=request.operator_id,
            security_id=request.security_id,
            cik=request.cik,
            issuer_name=request.issuer_name,
            sec_issuer_name=sec_issuer_name.strip(),
            as_of_cutoff=request.as_of_cutoff,
            source_url=source_url,
            retrieved_at=retrieved_at.astimezone(UTC),
            content_sha256=hashlib.sha256(response.body).hexdigest(),
            included_filings=tuple(
                filing for filing in filings if filing.valid_at_cutoff
            ),
            excluded_filings=tuple(
                filing for filing in filings if not filing.valid_at_cutoff
            ),
        )

    @staticmethod
    def _canonical_cik(value: object) -> str:
        if isinstance(value, int) and value >= 0:
            return f"{value:010d}"
        if isinstance(value, str) and value.isdigit() and len(value) <= 10:
            return value.zfill(10)
        raise SecSubmissionsError("SEC submissions CIK is invalid")

    @staticmethod
    def _recent(payload: Mapping[str, object]) -> dict[str, list[object]]:
        filings = payload.get("filings")
        recent = filings.get("recent") if isinstance(filings, dict) else None
        if not isinstance(recent, dict):
            raise SecSubmissionsError("SEC submissions recent filings are invalid")
        columns: dict[str, list[object]] = {}
        for field in _RECENT_FIELDS:
            value = recent.get(field)
            if not isinstance(value, list):
                raise SecSubmissionsError(
                    "SEC submissions invalid recent filings"
                )
            columns[field] = value
        lengths = {len(column) for column in columns.values()}
        if len(lengths) != 1:
            raise SecSubmissionsError("SEC submissions invalid recent filings")
        return columns

    @staticmethod
    def _filing(
        *,
        request: PrimarySourceRequest,
        row: Mapping[str, object],
    ) -> SecSubmissionFiling:
        accession = row["accessionNumber"]
        form = row["form"]
        primary_document = row["primaryDocument"]
        if (
            not isinstance(accession, str)
            or ACCESSION_PATTERN.fullmatch(accession) is None
            or not isinstance(form, str)
            or not form.strip()
            or not isinstance(primary_document, str)
            or DOCUMENT_PATTERN.fullmatch(primary_document) is None
        ):
            raise SecSubmissionsError("SEC submissions filing identity is invalid")
        if accession[:10] != request.cik:
            raise SecSubmissionsError("SEC submissions filing CIK mismatch")
        filing_date = SecSubmissionsCollector._date(
            row["filingDate"],
            required=True,
        )
        report_date = SecSubmissionsCollector._date(
            row["reportDate"],
            required=False,
        )
        acceptance = row["acceptanceDateTime"]
        if acceptance is not None and not isinstance(acceptance, str):
            raise SecSubmissionsError(
                "SEC submissions acceptance time is invalid"
            )
        try:
            temporal = assess_publication_time(
                acceptance,
                request.as_of_cutoff,
            )
        except ValueError as error:
            raise SecSubmissionsError(
                "SEC submissions acceptance time is invalid"
            ) from error
        archive_cik = request.cik.lstrip("0") or "0"
        archive_url = (
            "https://www.sec.gov/Archives/edgar/data/"
            f"{archive_cik}/{accession.replace('-', '')}/{primary_document}"
        )
        return SecSubmissionFiling(
            accession_number=accession,
            form=form.strip(),
            filing_date=filing_date,
            report_date=report_date,
            primary_document=primary_document,
            archive_url=archive_url,
            acceptance_time_raw=acceptance,
            publication_state=temporal.state,
            publication_reason_code=temporal.reason_code,
            valid_at_cutoff=temporal.valid_at_cutoff,
            published_at=temporal.published_at,
            publication_date=temporal.publication_date,
        )

    @staticmethod
    def _date(value: object, *, required: bool) -> date | None:
        if value in (None, "") and not required:
            return None
        if not isinstance(value, str):
            raise SecSubmissionsError("SEC submissions filing date is invalid")
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise SecSubmissionsError(
                "SEC submissions filing date is invalid"
            ) from error


__all__ = [
    "SecSubmissionFiling",
    "SecSubmissionsCollector",
    "SecSubmissionsError",
    "SecSubmissionsSnapshot",
]

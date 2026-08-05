from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import hashlib
import json
import re
from typing import Callable, Mapping
import unicodedata

from workers.primary_sources.models import PrimarySourceRequest
from workers.primary_sources.temporal import assess_publication_time

from .collector import (
    ACCESSION_PATTERN,
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
_MAX_HISTORY_FILES = 20
_SUBMISSION_DOCUMENT_PATTERN = re.compile(r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$")
SEC_ISSUER_IDENTITY_POLICY_VERSION = "sec-issuer-identity-v1"


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
class SecSubmissionHistoryFile:
    name: str
    filing_count: int
    filing_from: date
    filing_to: date
    source_url: str
    retrieved_at: datetime
    content_sha256: str


@dataclass(frozen=True, slots=True)
class SecIssuerFormerName:
    name: str
    normalized_name: str
    from_date: date
    to_date: date


@dataclass(frozen=True, slots=True)
class SecIssuerIdentityEvidence:
    policy_version: str
    state: str
    reason_code: str
    request_name: str
    normalized_request_name: str
    sec_current_name: str
    normalized_sec_current_name: str
    match_type: str | None
    matched_name: str | None
    normalized_matched_name: str | None
    former_names: tuple[SecIssuerFormerName, ...]


@dataclass(frozen=True, slots=True)
class _SecSubmissionHistoryReference:
    name: str
    filing_count: int
    filing_from: date
    filing_to: date


@dataclass(frozen=True, slots=True)
class SecSubmissionsSnapshot:
    operator_id: str
    security_id: str
    cik: str
    issuer_name: str
    sec_issuer_name: str
    identity_evidence: SecIssuerIdentityEvidence
    as_of_cutoff: datetime
    source_url: str
    retrieved_at: datetime
    content_sha256: str
    included_filings: tuple[SecSubmissionFiling, ...]
    excluded_filings: tuple[SecSubmissionFiling, ...]
    history_files: tuple[SecSubmissionHistoryFile, ...]
    submission_history_complete: bool


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
            f"{self.settings.base_url.rstrip('/')}/submissions/CIK{request.cik}.json"
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
        if response.final_url != source_url:
            raise SecSubmissionsError("SEC submissions response redirected")
        retrieved_at = self._retrieved_at()
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
        identity_evidence = self._issuer_identity(
            request.issuer_name,
            sec_issuer_name.strip(),
            payload.get("formerNames", []),
        )
        recent = self._recent(payload)
        history_files, history_metadata_complete = self._history(payload)
        filings = [
            self._filing(
                request=request,
                row={field: recent[field][index] for field in _RECENT_FIELDS},
            )
            for index in range(len(recent[_RECENT_FIELDS[0]]))
        ]
        fetched_history_files: list[SecSubmissionHistoryFile] = []
        for history_file in history_files:
            if not history_file.name.startswith(f"CIK{request.cik}-"):
                raise SecSubmissionsError("SEC submissions history file CIK mismatch")
            history_source_url = (
                f"{self.settings.base_url.rstrip('/')}/submissions/{history_file.name}"
            )
            history_response = self.transport.request(
                history_source_url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": self.settings.user_agent,
                },
            )
            if not 200 <= history_response.status < 300:
                raise SecSubmissionsError(
                    "SEC returned HTTP "
                    f"{history_response.status} for submissions history request"
                )
            if history_response.final_url != history_source_url:
                raise SecSubmissionsError("SEC submissions history response redirected")
            try:
                history_payload = json.loads(history_response.body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise SecSubmissionsError(
                    "SEC submissions history response is invalid JSON"
                ) from error
            if not isinstance(history_payload, dict):
                raise SecSubmissionsError("SEC submissions history response is invalid")
            history_columns = self._filing_columns(history_payload)
            if len(history_columns[_RECENT_FIELDS[0]]) != history_file.filing_count:
                raise SecSubmissionsError(
                    "SEC submissions history filing count mismatch"
                )
            history_filings = tuple(
                self._filing(
                    request=request,
                    row={
                        field: history_columns[field][index] for field in _RECENT_FIELDS
                    },
                )
                for index in range(len(history_columns[_RECENT_FIELDS[0]]))
            )
            if any(
                not (
                    history_file.filing_from - timedelta(days=1)
                    <= filing.filing_date
                    <= history_file.filing_to + timedelta(days=1)
                )
                for filing in history_filings
            ):
                raise SecSubmissionsError(
                    "SEC submissions history filing date is outside advertised window"
                )
            filings.extend(history_filings)
            history_retrieved_at = self._retrieved_at()
            fetched_history_files.append(
                SecSubmissionHistoryFile(
                    name=history_file.name,
                    filing_count=history_file.filing_count,
                    filing_from=history_file.filing_from,
                    filing_to=history_file.filing_to,
                    source_url=history_source_url,
                    retrieved_at=history_retrieved_at,
                    content_sha256=hashlib.sha256(history_response.body).hexdigest(),
                )
            )
        filings = list(self._deduplicate_filings(filings))
        return SecSubmissionsSnapshot(
            operator_id=request.operator_id,
            security_id=request.security_id,
            cik=request.cik,
            issuer_name=request.issuer_name,
            sec_issuer_name=sec_issuer_name.strip(),
            identity_evidence=identity_evidence,
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
            history_files=tuple(fetched_history_files),
            submission_history_complete=(
                history_metadata_complete or bool(fetched_history_files)
            ),
        )

    @classmethod
    def _issuer_identity(
        cls,
        request_name: str,
        sec_current_name: str,
        former_names_value: object,
    ) -> SecIssuerIdentityEvidence:
        if not isinstance(former_names_value, list):
            raise SecSubmissionsError("SEC submissions former names are invalid")
        former_names: list[SecIssuerFormerName] = []
        for value in former_names_value:
            if not isinstance(value, dict):
                raise SecSubmissionsError("SEC submissions former name is invalid")
            name = value.get("name")
            from_value = value.get("from")
            to_value = value.get("to")
            if (
                not isinstance(name, str)
                or not name.strip()
                or not isinstance(from_value, str)
                or not isinstance(to_value, str)
            ):
                raise SecSubmissionsError("SEC submissions former name is invalid")
            try:
                from_date = cls._former_name_date(from_value)
                to_date = cls._former_name_date(to_value)
            except ValueError as error:
                raise SecSubmissionsError(
                    "SEC submissions former name dates are invalid"
                ) from error
            if from_date > to_date:
                raise SecSubmissionsError(
                    "SEC submissions former name dates are invalid"
                )
            former_names.append(
                SecIssuerFormerName(
                    name=name.strip(),
                    normalized_name=cls._normalize_issuer_name(name),
                    from_date=from_date,
                    to_date=to_date,
                )
            )
        former_names.sort(
            key=lambda item: (
                item.from_date,
                item.to_date,
                item.normalized_name,
                item.name,
            )
        )
        normalized_request = cls._normalize_issuer_name(request_name)
        normalized_current = cls._normalize_issuer_name(sec_current_name)
        match_type: str | None = None
        matched_name: str | None = None
        normalized_matched_name: str | None = None
        if normalized_request == normalized_current:
            match_type = "current_name"
            matched_name = sec_current_name
            normalized_matched_name = normalized_current
        else:
            matching_former_names = tuple(
                former_name
                for former_name in former_names
                if former_name.normalized_name == normalized_request
            )
            if matching_former_names:
                matched = matching_former_names[-1]
                match_type = "former_name"
                matched_name = matched.name
                normalized_matched_name = matched.normalized_name
        verified = match_type is not None
        return SecIssuerIdentityEvidence(
            policy_version=SEC_ISSUER_IDENTITY_POLICY_VERSION,
            state="verified" if verified else "mismatch",
            reason_code=(
                "sec_issuer_name_verified"
                if verified
                else "sec_issuer_name_not_in_verified_history"
            ),
            request_name=request_name,
            normalized_request_name=normalized_request,
            sec_current_name=sec_current_name,
            normalized_sec_current_name=normalized_current,
            match_type=match_type,
            matched_name=matched_name,
            normalized_matched_name=normalized_matched_name,
            former_names=tuple(former_names),
        )

    @staticmethod
    def _former_name_date(value: str) -> date:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return date.fromisoformat(value)
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("former name timestamp needs timezone")
        return parsed.astimezone(UTC).date()

    @staticmethod
    def _normalize_issuer_name(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value).casefold()
        normalized = normalized.replace("&", " and ")
        return " ".join(re.sub(r"[^\w]+", " ", normalized).split())

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
        return SecSubmissionsCollector._filing_columns(recent)

    @staticmethod
    def _filing_columns(
        payload: Mapping[str, object],
    ) -> dict[str, list[object]]:
        columns: dict[str, list[object]] = {}
        for field in _RECENT_FIELDS:
            value = payload.get(field)
            if not isinstance(value, list):
                raise SecSubmissionsError("SEC submissions invalid recent filings")
            columns[field] = value
        lengths = {len(column) for column in columns.values()}
        if len(lengths) != 1:
            raise SecSubmissionsError("SEC submissions invalid recent filings")
        return columns

    def _retrieved_at(self) -> datetime:
        retrieved_at = self.clock()
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise RuntimeError("SEC submissions clock must include timezone")
        return retrieved_at.astimezone(UTC)

    @staticmethod
    def _deduplicate_filings(
        filings: list[SecSubmissionFiling],
    ) -> tuple[SecSubmissionFiling, ...]:
        by_accession: dict[str, SecSubmissionFiling] = {}
        ordered: list[SecSubmissionFiling] = []
        for filing in filings:
            existing = by_accession.get(filing.accession_number)
            if existing is not None:
                if existing != filing:
                    raise SecSubmissionsError(
                        "SEC submissions filing identity conflict"
                    )
                continue
            by_accession[filing.accession_number] = filing
            ordered.append(filing)
        return tuple(ordered)

    @staticmethod
    def _history(
        payload: Mapping[str, object],
    ) -> tuple[tuple[_SecSubmissionHistoryReference, ...], bool]:
        filings = payload.get("filings")
        files = filings.get("files") if isinstance(filings, dict) else None
        if files is None:
            return (), False
        if not isinstance(files, list):
            raise SecSubmissionsError("SEC submissions history files are invalid")
        if len(files) > _MAX_HISTORY_FILES:
            raise SecSubmissionsError("SEC submissions has too many history files")
        history: list[_SecSubmissionHistoryReference] = []
        names: set[str] = set()
        for value in files:
            if not isinstance(value, dict):
                raise SecSubmissionsError("SEC submissions history files are invalid")
            name = value.get("name")
            filing_count = value.get("filingCount")
            if (
                not isinstance(name, str)
                or re.fullmatch(
                    r"CIK\d{10}-submissions-\d{3}\.json",
                    name,
                )
                is None
                or not isinstance(filing_count, int)
                or isinstance(filing_count, bool)
                or filing_count < 0
            ):
                raise SecSubmissionsError("SEC submissions history files are invalid")
            if name in names:
                raise SecSubmissionsError("SEC submissions duplicate history file")
            names.add(name)
            filing_from = SecSubmissionsCollector._date(
                value.get("filingFrom"),
                required=True,
            )
            filing_to = SecSubmissionsCollector._date(
                value.get("filingTo"),
                required=True,
            )
            if filing_from > filing_to:
                raise SecSubmissionsError("SEC submissions history files are invalid")
            history.append(
                _SecSubmissionHistoryReference(
                    name=name,
                    filing_count=filing_count,
                    filing_from=filing_from,
                    filing_to=filing_to,
                )
            )
        return tuple(history), not history

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
            or _SUBMISSION_DOCUMENT_PATTERN.fullmatch(primary_document) is None
            or any(
                segment in {"", ".", ".."} for segment in primary_document.split("/")
            )
        ):
            raise SecSubmissionsError("SEC submissions filing identity is invalid")
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
            raise SecSubmissionsError("SEC submissions acceptance time is invalid")
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


def evaluate_sec_issuer_identity(
    request_name: str,
    sec_current_name: str,
    former_names: tuple[SecIssuerFormerName, ...],
) -> SecIssuerIdentityEvidence:
    return SecSubmissionsCollector._issuer_identity(
        request_name,
        sec_current_name,
        [
            {
                "name": former_name.name,
                "from": former_name.from_date.isoformat(),
                "to": former_name.to_date.isoformat(),
            }
            for former_name in former_names
        ],
    )


__all__ = [
    "SEC_ISSUER_IDENTITY_POLICY_VERSION",
    "SecIssuerFormerName",
    "SecIssuerIdentityEvidence",
    "SecSubmissionFiling",
    "SecSubmissionHistoryFile",
    "SecSubmissionsCollector",
    "SecSubmissionsError",
    "SecSubmissionsSnapshot",
    "evaluate_sec_issuer_identity",
]

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
import hashlib
from typing import Callable

from workers.primary_sources.temporal import assess_publication_time

from .collector import (
    ACCESSION_PATTERN,
    DOCUMENT_PATTERN,
    BytesTransport,
    SecSettings,
)
from .selection import SecFilingSelection


class SecFilingDocumentError(RuntimeError):
    """Raised when a selected SEC filing document cannot be trusted."""


@dataclass(frozen=True, slots=True)
class SecFilingDocument:
    operator_id: str
    security_id: str
    cik: str
    accession_number: str
    form: str
    filing_date: date
    report_date: date | None
    primary_document: str
    source_class: str
    source_url: str
    published_at: datetime | None
    publication_date: date | None
    retrieved_at: datetime
    content_sha256: str
    content_text: str

    @property
    def document_name(self) -> str:
        return self.primary_document


@dataclass(frozen=True, slots=True)
class SecFilingDocumentSnapshot:
    operator_id: str
    security_id: str
    cik: str
    as_of_cutoff: datetime
    policy_version: str
    documents: tuple[SecFilingDocument, ...]


class SecFilingDocumentCollector:
    def __init__(
        self,
        settings: SecSettings,
        *,
        transport: BytesTransport,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if settings.base_url.rstrip("/") != "https://www.sec.gov":
            raise ValueError("SEC filing archive base URL is unsupported")
        self.settings = settings
        self.transport = transport
        self.clock = clock or (lambda: datetime.now(UTC))

    def collect(
        self,
        selection: SecFilingSelection,
    ) -> SecFilingDocumentSnapshot:
        if (
            selection.coverage_state != "complete"
            or "required_sec_filings"
            not in selection.eligibility_coverage
        ):
            raise SecFilingDocumentError(
                "SEC filing selection is not complete"
            )
        if not selection.selected_filings:
            raise SecFilingDocumentError(
                "SEC filing selection has no documents"
            )
        documents: list[SecFilingDocument] = []
        for filing in selection.selected_filings:
            try:
                publication = assess_publication_time(
                    filing.acceptance_time_raw,
                    selection.as_of_cutoff,
                )
            except ValueError as error:
                raise SecFilingDocumentError(
                    "SEC filing publication metadata is invalid at cutoff"
                ) from error
            if not publication.valid_at_cutoff:
                raise SecFilingDocumentError(
                    "SEC filing publication metadata is invalid at cutoff"
                )
            if not filing.valid_at_cutoff:
                raise SecFilingDocumentError(
                    "SEC filing is not valid at cutoff"
                )
            expected_url = self._document_url(
                cik=selection.cik,
                accession_number=filing.accession_number,
                primary_document=filing.primary_document,
            )
            if filing.archive_url != expected_url:
                raise SecFilingDocumentError(
                    "SEC filing document URL mismatch"
                )
            response = self.transport.request(
                expected_url,
                headers={
                    "Accept": "text/html,application/xhtml+xml",
                    "User-Agent": self.settings.user_agent,
                },
            )
            if not 200 <= response.status < 300:
                raise SecFilingDocumentError(
                    f"SEC returned HTTP {response.status} for filing document"
                )
            if response.final_url != expected_url:
                raise SecFilingDocumentError(
                    "SEC filing document redirected"
                )
            content_type = next(
                (
                    value
                    for key, value in response.headers.items()
                    if key.lower() == "content-type"
                ),
                "",
            )
            media_type = content_type.partition(";")[0].strip().lower()
            if media_type not in {"text/html", "application/xhtml+xml"}:
                raise SecFilingDocumentError(
                    "SEC filing document content type is invalid"
                )
            try:
                content_text = response.body.decode("utf-8")
            except UnicodeDecodeError as error:
                raise SecFilingDocumentError(
                    "SEC filing document is not valid UTF-8"
                ) from error
            if not content_text.strip():
                raise SecFilingDocumentError(
                    "SEC filing document is empty"
                )
            retrieved_at = self.clock()
            if (
                retrieved_at.tzinfo is None
                or retrieved_at.utcoffset() is None
            ):
                raise RuntimeError(
                    "SEC filing document clock must include timezone"
                )
            documents.append(
                SecFilingDocument(
                    operator_id=selection.operator_id,
                    security_id=selection.security_id,
                    cik=selection.cik,
                    accession_number=filing.accession_number,
                    form=filing.form,
                    filing_date=filing.filing_date,
                    report_date=filing.report_date,
                    primary_document=filing.primary_document,
                    source_class="sec_filing",
                    source_url=expected_url,
                    published_at=filing.published_at,
                    publication_date=filing.publication_date,
                    retrieved_at=retrieved_at.astimezone(UTC),
                    content_sha256=hashlib.sha256(response.body).hexdigest(),
                    content_text=content_text,
                )
            )
        return SecFilingDocumentSnapshot(
            operator_id=selection.operator_id,
            security_id=selection.security_id,
            cik=selection.cik,
            as_of_cutoff=selection.as_of_cutoff,
            policy_version=selection.policy_version,
            documents=tuple(documents),
        )

    @staticmethod
    def _document_url(
        *,
        cik: str,
        accession_number: str,
        primary_document: str,
    ) -> str:
        if (
            ACCESSION_PATTERN.fullmatch(accession_number) is None
            or DOCUMENT_PATTERN.fullmatch(primary_document) is None
        ):
            raise SecFilingDocumentError(
                "SEC filing document identity is invalid"
            )
        archive_cik = cik.lstrip("0") or "0"
        return (
            "https://www.sec.gov/Archives/edgar/data/"
            f"{archive_cik}/{accession_number.replace('-', '')}/"
            f"{primary_document}"
        )


__all__ = [
    "SecFilingDocument",
    "SecFilingDocumentCollector",
    "SecFilingDocumentError",
    "SecFilingDocumentSnapshot",
]

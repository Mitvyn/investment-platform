from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
import hashlib
from html.parser import HTMLParser
import re
from typing import Callable

from .collector import (
    ACCESSION_PATTERN,
    DOCUMENT_PATTERN,
    BytesResponse,
    BytesTransport,
    SecSettings,
)
from .documents import SecFilingDocument, SecFilingDocumentSnapshot


class SecFilingExhibitError(RuntimeError):
    """Raised when SEC exhibit discovery or collection cannot be trusted."""


ARCHIVE_FILE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True, slots=True)
class SecFilingIndexManifest:
    accession_number: str
    source_url: str
    retrieved_at: datetime
    content_sha256: str
    content_text: str


@dataclass(frozen=True, slots=True)
class SecFilingExhibitReference:
    accession_number: str
    sequence: str
    description: str
    exhibit_type: str
    document_name: str
    source_class: str
    source_url: str
    collection_state: str


@dataclass(frozen=True, slots=True)
class SecFilingExhibit:
    operator_id: str
    security_id: str
    cik: str
    accession_number: str
    form: str
    filing_date: date
    report_date: date | None
    sequence: str
    description: str
    exhibit_type: str
    document_name: str
    source_class: str
    source_url: str
    published_at: datetime | None
    publication_date: date | None
    retrieved_at: datetime
    content_sha256: str
    content_text: str


@dataclass(frozen=True, slots=True)
class SecFilingExhibitSnapshot:
    operator_id: str
    security_id: str
    cik: str
    as_of_cutoff: datetime
    policy_version: str
    indexes: tuple[SecFilingIndexManifest, ...]
    references: tuple[SecFilingExhibitReference, ...]
    exhibits: tuple[SecFilingExhibit, ...]


@dataclass(frozen=True, slots=True)
class _IndexRow:
    sequence: str
    description: str
    document_name: str
    href: str
    exhibit_type: str


class _FilingIndexParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_document_table = False
        self._in_row = False
        self._in_cell = False
        self._cells: list[list[str]] = []
        self._hrefs: list[str | None] = []
        self.document_manifest_count = 0
        self.rows: list[_IndexRow] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = dict(attrs)
        if tag == "table":
            summary = (attributes.get("summary") or "").strip().lower()
            self._in_document_table = summary == "document format files"
            if self._in_document_table:
                self.document_manifest_count += 1
        elif tag == "tr" and self._in_document_table:
            self._in_row = True
            self._cells = []
            self._hrefs = []
        elif tag == "td" and self._in_row:
            self._in_cell = True
            self._cells.append([])
            self._hrefs.append(None)
        elif tag == "a" and self._in_cell and self._hrefs:
            if self._hrefs[-1] is None:
                self._hrefs[-1] = attributes.get("href")

    def handle_data(self, data: str) -> None:
        if self._in_cell and self._cells:
            self._cells[-1].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td":
            self._in_cell = False
        elif tag == "tr" and self._in_row:
            self._finish_row()
            self._in_row = False
        elif tag == "table" and self._in_document_table:
            self._in_document_table = False

    def _finish_row(self) -> None:
        if len(self._cells) < 4:
            return
        values = tuple(" ".join("".join(cell).split()) for cell in self._cells)
        href = self._hrefs[2] if len(self._hrefs) > 2 else None
        if not href:
            return
        self.rows.append(
            _IndexRow(
                sequence=values[0],
                description=values[1],
                document_name=values[2].split()[0],
                href=href,
                exhibit_type=values[3].upper(),
            )
        )


class SecFilingExhibitCollector:
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
        documents: SecFilingDocumentSnapshot,
    ) -> SecFilingExhibitSnapshot:
        indexes: list[SecFilingIndexManifest] = []
        references: list[SecFilingExhibitReference] = []
        exhibits: list[SecFilingExhibit] = []
        ordered_documents = sorted(
            documents.documents,
            key=lambda item: (
                item.filing_date,
                item.accession_number,
                item.primary_document,
            ),
        )
        for document in ordered_documents:
            self._validate_document_identity(documents, document)
            index_url = self._index_url(document)
            index_response = self._request_html(index_url, "filing index")
            retrieved_at = self._retrieved_at()
            index_text = self._decode_nonempty(
                index_response,
                "filing index",
            )
            indexes.append(
                SecFilingIndexManifest(
                    accession_number=document.accession_number,
                    source_url=index_url,
                    retrieved_at=retrieved_at,
                    content_sha256=hashlib.sha256(index_response.body).hexdigest(),
                    content_text=index_text,
                )
            )
            parser = _FilingIndexParser()
            parser.feed(index_text)
            if parser.document_manifest_count == 0:
                raise SecFilingExhibitError("SEC filing document manifest is missing")
            if parser.document_manifest_count > 1:
                raise SecFilingExhibitError("SEC filing document manifest is ambiguous")
            unique_rows: dict[str, _IndexRow] = {}
            for row in parser.rows:
                if not row.exhibit_type.startswith("EX-"):
                    continue
                if ARCHIVE_FILE_PATTERN.fullmatch(row.document_name) is None:
                    raise SecFilingExhibitError(
                        "SEC filing exhibit filename is invalid"
                    )
                prior = unique_rows.get(row.document_name)
                if prior is not None and prior != row:
                    raise SecFilingExhibitError(
                        "SEC filing index has conflicting duplicate exhibit"
                    )
                unique_rows[row.document_name] = row
            ordered_rows = sorted(
                unique_rows.values(),
                key=self._row_sort_key,
            )
            for row in ordered_rows:
                exhibit_url = self._exhibit_url(
                    document,
                    row.document_name,
                    row.href,
                )
                collect_html = DOCUMENT_PATTERN.fullmatch(row.document_name) is not None
                references.append(
                    SecFilingExhibitReference(
                        accession_number=document.accession_number,
                        sequence=row.sequence,
                        description=row.description,
                        exhibit_type=row.exhibit_type,
                        document_name=row.document_name,
                        source_class="sec_filing_exhibit",
                        source_url=exhibit_url,
                        collection_state=(
                            "collected_html" if collect_html else "unsupported_media"
                        ),
                    )
                )
                if not collect_html:
                    continue
                response = self._request_html(exhibit_url, "filing exhibit")
                exhibit_text = self._decode_nonempty(
                    response,
                    "filing exhibit",
                )
                exhibits.append(
                    SecFilingExhibit(
                        operator_id=documents.operator_id,
                        security_id=documents.security_id,
                        cik=documents.cik,
                        accession_number=document.accession_number,
                        form=document.form,
                        filing_date=document.filing_date,
                        report_date=document.report_date,
                        sequence=row.sequence,
                        description=row.description,
                        exhibit_type=row.exhibit_type,
                        document_name=row.document_name,
                        source_class="sec_filing_exhibit",
                        source_url=exhibit_url,
                        published_at=document.published_at,
                        publication_date=document.publication_date,
                        retrieved_at=self._retrieved_at(),
                        content_sha256=hashlib.sha256(response.body).hexdigest(),
                        content_text=exhibit_text,
                    )
                )
        return SecFilingExhibitSnapshot(
            operator_id=documents.operator_id,
            security_id=documents.security_id,
            cik=documents.cik,
            as_of_cutoff=documents.as_of_cutoff,
            policy_version="sec-html-exhibits-v1",
            indexes=tuple(indexes),
            references=tuple(references),
            exhibits=tuple(exhibits),
        )

    @staticmethod
    def _row_sort_key(
        row: _IndexRow,
    ) -> tuple[int, int, str, str]:
        if row.sequence.isdecimal():
            return (
                0,
                int(row.sequence),
                row.document_name,
                row.exhibit_type,
            )
        return (1, 0, row.sequence, row.document_name)

    def _request_html(self, url: str, label: str) -> BytesResponse:
        response = self.transport.request(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": self.settings.user_agent,
            },
        )
        if not 200 <= response.status < 300:
            raise SecFilingExhibitError(
                f"SEC returned HTTP {response.status} for {label}"
            )
        if response.final_url != url:
            raise SecFilingExhibitError(f"SEC {label} redirected")
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
            raise SecFilingExhibitError(f"SEC {label} content type is invalid")
        return response

    @staticmethod
    def _decode_nonempty(
        response: BytesResponse,
        label: str,
    ) -> str:
        try:
            content_text = response.body.decode("utf-8")
        except UnicodeDecodeError as error:
            raise SecFilingExhibitError(f"SEC {label} is not valid UTF-8") from error
        if not content_text.strip():
            raise SecFilingExhibitError(f"SEC {label} is empty")
        return content_text

    def _retrieved_at(self) -> datetime:
        retrieved_at = self.clock()
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise RuntimeError("SEC exhibit clock must include timezone")
        return retrieved_at.astimezone(UTC)

    @staticmethod
    def _validate_document_identity(
        snapshot: SecFilingDocumentSnapshot,
        document: SecFilingDocument,
    ) -> None:
        if (
            document.operator_id != snapshot.operator_id
            or document.security_id != snapshot.security_id
            or document.cik != snapshot.cik
        ):
            raise SecFilingExhibitError(
                "SEC filing document identity does not match snapshot"
            )
        expected_document_url = SecFilingExhibitCollector._primary_document_url(
            document
        )
        if document.source_url != expected_document_url:
            raise SecFilingExhibitError("SEC filing primary document URL mismatch")
        if (
            snapshot.as_of_cutoff.tzinfo is None
            or snapshot.as_of_cutoff.utcoffset() is None
        ):
            raise SecFilingExhibitError("SEC filing cutoff must include timezone")
        if document.published_at is not None and (
            document.published_at.tzinfo is None
            or document.published_at.utcoffset() is None
        ):
            raise SecFilingExhibitError(
                "SEC filing publication timestamp must include timezone"
            )
        if document.published_at is not None and document.published_at.astimezone(
            UTC
        ) > snapshot.as_of_cutoff.astimezone(UTC):
            raise SecFilingExhibitError("SEC filing document is after cutoff")
        if (
            document.publication_date is not None
            and document.publication_date > snapshot.as_of_cutoff.date()
        ):
            raise SecFilingExhibitError("SEC filing document is after cutoff")

    @staticmethod
    def _index_url(document: SecFilingDocument) -> str:
        if (
            ACCESSION_PATTERN.fullmatch(document.accession_number) is None
        ):
            raise SecFilingExhibitError("SEC filing identity is invalid")
        archive_cik = document.cik.lstrip("0") or "0"
        compact_accession = document.accession_number.replace("-", "")
        return (
            "https://www.sec.gov/Archives/edgar/data/"
            f"{archive_cik}/{compact_accession}/"
            f"{document.accession_number}-index.html"
        )

    @staticmethod
    def _primary_document_url(document: SecFilingDocument) -> str:
        if (
            ACCESSION_PATTERN.fullmatch(document.accession_number) is None
            or DOCUMENT_PATTERN.fullmatch(document.primary_document) is None
        ):
            raise SecFilingExhibitError("SEC filing identity is invalid")
        archive_cik = document.cik.lstrip("0") or "0"
        compact_accession = document.accession_number.replace("-", "")
        return (
            "https://www.sec.gov/Archives/edgar/data/"
            f"{archive_cik}/{compact_accession}/"
            f"{document.primary_document}"
        )

    @staticmethod
    def _exhibit_url(
        document: SecFilingDocument,
        document_name: str,
        href: str,
    ) -> str:
        archive_cik = document.cik.lstrip("0") or "0"
        compact_accession = document.accession_number.replace("-", "")
        expected_url = (
            "https://www.sec.gov/Archives/edgar/data/"
            f"{archive_cik}/{compact_accession}/{document_name}"
        )
        archive_path = (
            f"/Archives/edgar/data/{archive_cik}/"
            f"{compact_accession}/{document_name}"
        )
        if href not in {
            document_name,
            archive_path,
            f"/ix?doc={archive_path}",
        }:
            raise SecFilingExhibitError("SEC filing exhibit URL is not canonical")
        return expected_url


__all__ = [
    "SecFilingExhibit",
    "SecFilingExhibitCollector",
    "SecFilingExhibitError",
    "SecFilingExhibitReference",
    "SecFilingExhibitSnapshot",
    "SecFilingIndexManifest",
]

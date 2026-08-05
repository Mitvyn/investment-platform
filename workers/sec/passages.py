from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
from html.parser import HTMLParser
from typing import Protocol

from .collector import ACCESSION_PATTERN, DOCUMENT_PATTERN


class SecPassageExtractionError(RuntimeError):
    """Raised when collected SEC HTML provenance cannot be trusted."""


class SecCollectedHtml(Protocol):
    operator_id: str
    security_id: str
    cik: str
    accession_number: str
    document_name: str
    source_class: str
    source_url: str
    published_at: datetime | None
    publication_date: date | None
    retrieved_at: datetime
    content_sha256: str
    content_text: str


@dataclass(frozen=True, slots=True)
class SecExactPassageResult:
    state: str
    reason_code: str
    occurrence_count: int
    query_text: str
    query_sha256: str
    passage_text: str | None
    passage_sha256: str | None
    locator: str | None
    operator_id: str
    security_id: str
    cik: str
    accession_number: str
    document_name: str
    source_class: str
    source_url: str
    source_content_sha256: str
    published_at: datetime | None
    publication_date: date | None
    retrieved_at: datetime


class _VisibleTextParser(HTMLParser):
    _HIDDEN_TAGS = frozenset({"head", "script", "style", "noscript"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._hidden_depth = 0
        self.parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        if tag.lower() in self._HIDDEN_TAGS:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._HIDDEN_TAGS and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self.parts.append(data)


def _normalize_text(value: str) -> str:
    return " ".join(value.split())


class SecExactPassageExtractor:
    def extract(
        self,
        source: SecCollectedHtml,
        exact_text: str,
    ) -> SecExactPassageResult:
        if source.source_class not in {
            "sec_filing",
            "sec_filing_exhibit",
        }:
            raise SecPassageExtractionError("SEC HTML source class is invalid")
        if (
            ACCESSION_PATTERN.fullmatch(source.accession_number) is None
            or DOCUMENT_PATTERN.fullmatch(source.document_name) is None
        ):
            raise SecPassageExtractionError("SEC HTML source identity is invalid")
        archive_cik = source.cik.lstrip("0") or "0"
        compact_accession = source.accession_number.replace("-", "")
        expected_url = (
            "https://www.sec.gov/Archives/edgar/data/"
            f"{archive_cik}/{compact_accession}/{source.document_name}"
        )
        if source.source_url != expected_url:
            raise SecPassageExtractionError("SEC HTML source URL is not canonical")
        observed_content_hash = hashlib.sha256(
            source.content_text.encode("utf-8")
        ).hexdigest()
        if observed_content_hash != source.content_sha256:
            raise SecPassageExtractionError("SEC HTML content hash mismatch")
        query_text = _normalize_text(exact_text)
        if not query_text:
            raise ValueError("exact passage text cannot be empty")
        parser = _VisibleTextParser()
        parser.feed(source.content_text)
        visible_text = _normalize_text(" ".join(parser.parts))
        start = visible_text.find(query_text)
        occurrence_count = visible_text.count(query_text)
        if start < 0:
            state = "not_found"
            reason_code = "exact_passage_not_found"
            occurrence_count = 0
            passage_text = None
            passage_sha256 = None
            locator = None
        elif occurrence_count > 1:
            state = "ambiguous"
            reason_code = "exact_passage_ambiguous"
            passage_text = None
            passage_sha256 = None
            locator = None
        else:
            occurrence_count = 1
            state = "found"
            reason_code = "exact_passage_found"
            passage_text = query_text
            passage_sha256 = hashlib.sha256(query_text.encode()).hexdigest()
            locator = f"normalized_text_chars:{start}-{start + len(query_text)}"
        return SecExactPassageResult(
            state=state,
            reason_code=reason_code,
            occurrence_count=occurrence_count,
            query_text=query_text,
            query_sha256=hashlib.sha256(query_text.encode()).hexdigest(),
            passage_text=passage_text,
            passage_sha256=passage_sha256,
            locator=locator,
            operator_id=source.operator_id,
            security_id=source.security_id,
            cik=source.cik,
            accession_number=source.accession_number,
            document_name=source.document_name,
            source_class=source.source_class,
            source_url=source.source_url,
            source_content_sha256=source.content_sha256,
            published_at=source.published_at,
            publication_date=source.publication_date,
            retrieved_at=source.retrieved_at,
        )


__all__ = [
    "SecCollectedHtml",
    "SecExactPassageExtractor",
    "SecExactPassageResult",
    "SecPassageExtractionError",
]

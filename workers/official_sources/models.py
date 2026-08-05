from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Mapping


@dataclass(frozen=True, slots=True)
class OfficialBytesResponse:
    body: bytes
    status: int
    headers: Mapping[str, str]
    final_url: str | None


@dataclass(frozen=True, slots=True)
class OfficialPassageSpec:
    passage_key: str
    locator: str
    exact_text: str

    def __post_init__(self) -> None:
        if not self.passage_key.strip():
            raise ValueError("passage key is required")
        if not self.locator.strip():
            raise ValueError("passage locator is required")
        if not self.exact_text.strip():
            raise ValueError("exact passage text is required")


@dataclass(frozen=True, slots=True)
class OfficialSourceLocator:
    source_key: str
    requirement_id: str
    title: str
    source_url: str
    publication_time: object
    effective_date: date | None
    passages: tuple[OfficialPassageSpec, ...]
    coverage_role: str = "required"
    coverage_mode: str = "all"

    def __post_init__(self) -> None:
        for field_name in (
            "source_key",
            "requirement_id",
            "title",
            "source_url",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name.replace('_', ' ')} is required")
        passage_keys = tuple(passage.passage_key for passage in self.passages)
        if len(passage_keys) != len(set(passage_keys)):
            raise ValueError("passage keys must be unique")
        if self.coverage_role not in {"required", "optional"}:
            raise ValueError("coverage role must be required or optional")
        if self.coverage_mode not in {"all", "any"}:
            raise ValueError("coverage mode must be all or any")


@dataclass(frozen=True, slots=True)
class OfficialSourceDocument:
    document_id: str
    source_key: str
    source_class: str
    title: str
    source_url: str
    final_url: str
    publication_state: str
    publication_reason_code: str
    published_at: datetime | None
    publication_date: date | None
    effective_date: date | None
    retrieved_at: datetime
    content_sha256: str
    content_text: str


@dataclass(frozen=True, slots=True)
class OfficialPassage:
    passage_id: str
    document_id: str
    passage_key: str
    locator: str
    passage_text: str
    passage_sha256: str


@dataclass(frozen=True, slots=True)
class OfficialSourceResult:
    source_key: str
    requirement_id: str
    coverage_role: str
    coverage_mode: str
    source_url: str
    state: str
    reason_code: str
    document: OfficialSourceDocument | None
    passages: tuple[OfficialPassage, ...]


@dataclass(frozen=True, slots=True)
class OfficialSourceCoverageResult:
    requirement_id: str
    coverage_mode: str
    state: str
    required_source_keys: tuple[str, ...]
    optional_source_keys: tuple[str, ...]
    collected_source_keys: tuple[str, ...]
    unresolved_required_source_keys: tuple[str, ...]
    unresolved_optional_source_keys: tuple[str, ...]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OfficialSourceSnapshot:
    operator_id: str
    security_id: str
    cik: str
    issuer_name: str
    as_of_cutoff: datetime
    source_class: str
    source_results: tuple[OfficialSourceResult, ...]
    coverage_state: str
    coverage_results: tuple[OfficialSourceCoverageResult, ...]


__all__ = [
    "OfficialBytesResponse",
    "OfficialPassage",
    "OfficialPassageSpec",
    "OfficialSourceCoverageResult",
    "OfficialSourceDocument",
    "OfficialSourceLocator",
    "OfficialSourceResult",
    "OfficialSourceSnapshot",
]

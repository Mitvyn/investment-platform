from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PassageRequest:
    key: str
    locator: str
    expected_text: str


@dataclass(frozen=True, slots=True)
class ReleaseRequest:
    ticker: str
    company_name: str
    release_type: str
    title: str
    published_at: str
    source_url: str
    passages: tuple[PassageRequest, ...]


@dataclass(frozen=True, slots=True)
class CollectedRelease:
    request: ReleaseRequest
    retrieved_at: str
    html: str
    content_sha256: str


@dataclass(frozen=True, slots=True)
class IssuerPassage:
    id: str
    locator: str
    passage_text: str
    passage_sha256: str


@dataclass(frozen=True, slots=True)
class FinancialMetric:
    id: str
    passage_id: str
    metric_key: str
    metric_label: str
    metric_kind: str
    value: float
    unit: str
    source_period: str
    comparison_period: str | None = None
    formula: str | None = None


@dataclass(frozen=True, slots=True)
class Catalyst:
    id: str
    passage_id: str
    title: str
    status: str
    window_start: str
    window_end: str


@dataclass(frozen=True, slots=True)
class Risk:
    id: str
    passage_id: str
    title: str
    risk_type: str
    severity: str
    status: str


@dataclass(frozen=True, slots=True)
class IssuerContext:
    operator_id: str
    research_run_id: str
    release_id: str
    idempotency_key: str
    ticker: str
    company_name: str
    run_status: str
    release_type: str
    title: str
    published_at: str
    source_url: str
    retrieved_at: str
    content_sha256: str
    passages: tuple[IssuerPassage, ...]
    metrics: tuple[FinancialMetric, ...]
    catalysts: tuple[Catalyst, ...]
    risks: tuple[Risk, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

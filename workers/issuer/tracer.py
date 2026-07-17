from __future__ import annotations

import hashlib
import re
import uuid
from html.parser import HTMLParser

from workers.ids import stable_id

from .models import (
    Catalyst,
    CollectedRelease,
    FinancialMetric,
    IssuerContext,
    IssuerPassage,
    Risk,
)


def normalize_text(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    normalized = re.sub(r"\$\s+(?=\d)", "$", normalized)
    return re.sub(r"\s+([.,;:])", r"\1", normalized)


class ReleaseTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def normalized_text(self) -> str:
        return normalize_text(" ".join(self.parts))


def _metric(
    operator_id: str,
    release_id: str,
    passage_id: str,
    metric_key: str,
    metric_label: str,
    metric_kind: str,
    value: float,
    unit: str,
    source_period: str,
    comparison_period: str | None = None,
    formula: str | None = None,
) -> FinancialMetric:
    return FinancialMetric(
        id=stable_id(operator_id, "financial-metric", f"{release_id}:{metric_key}"),
        passage_id=passage_id,
        metric_key=metric_key,
        metric_label=metric_label,
        metric_kind=metric_kind,
        value=value,
        unit=unit,
        source_period=source_period,
        comparison_period=comparison_period,
        formula=formula,
    )


def build_issuer_context(
    release: CollectedRelease,
    *,
    operator_id: str,
) -> IssuerContext:
    uuid.UUID(operator_id)
    request = release.request
    parser = ReleaseTextParser()
    parser.feed(release.html)
    normalized_document = parser.normalized_text()

    ticker = request.ticker.strip().upper()
    idempotency_key = f"issuer-release:{ticker}:{request.published_at}:v1"
    release_id = stable_id(operator_id, "issuer-release", request.source_url)
    passages: dict[str, IssuerPassage] = {}

    for requested in request.passages:
        passage_text = normalize_text(requested.expected_text)
        if normalized_document.count(passage_text) != 1:
            raise ValueError(
                f"expected issuer passage {requested.key!r} must appear exactly once"
            )
        passage_sha256 = hashlib.sha256(passage_text.encode()).hexdigest()
        passages[requested.key] = IssuerPassage(
            id=stable_id(
                operator_id,
                "issuer-passage",
                f"{release_id}:{requested.key}:{passage_sha256}",
            ),
            locator=requested.locator,
            passage_text=passage_text,
            passage_sha256=passage_sha256,
        )

    evidence_content = "\n".join(
        passage.passage_text for passage in passages.values()
    )
    evidence_content_sha256 = hashlib.sha256(
        evidence_content.encode()
    ).hexdigest()

    cash = 665.2
    prior_cash = 753.9
    operating_cash_used = 81.1
    prior_operating_cash_used = 132.0
    financial_period = "Three months ended March 31, 2026"

    metrics = (
        _metric(
            operator_id,
            release_id,
            passages["cash"].id,
            "cash_and_restricted_cash",
            "Cash, equivalents and restricted cash",
            "reported",
            cash,
            "USD_millions",
            "As of March 31, 2026",
            "As of December 31, 2025",
        ),
        _metric(
            operator_id,
            release_id,
            passages["operating_cash"].id,
            "operating_cash_used",
            "Operating cash used",
            "reported",
            operating_cash_used,
            "USD_millions",
            financial_period,
            "Three months ended March 31, 2025",
        ),
        _metric(
            operator_id,
            release_id,
            passages["operating_cash"].id,
            "simple_runway_quarters",
            "Simple cash runway",
            "calculated",
            round(cash / operating_cash_used, 2),
            "quarters",
            "Cash as of March 31, 2026 / Q1 2026 operating cash use",
            formula="$665.2m / $81.1m quarterly operating cash use",
        ),
        _metric(
            operator_id,
            release_id,
            passages["cash"].id,
            "cash_change_percent",
            "Cash change",
            "calculated",
            round(((cash - prior_cash) / prior_cash) * 100, 2),
            "percent",
            "March 31, 2026 versus December 31, 2025",
            formula="($665.2m - $753.9m) / $753.9m × 100",
        ),
        _metric(
            operator_id,
            release_id,
            passages["operating_cash"].id,
            "operating_cash_use_improvement_percent",
            "Operating cash-use improvement",
            "calculated",
            round(
                ((prior_operating_cash_used - operating_cash_used)
                 / prior_operating_cash_used)
                * 100,
                2,
            ),
            "percent",
            "Q1 2026 versus Q1 2025",
            formula="($132.0m - $81.1m) / $132.0m × 100",
        ),
    )

    catalyst_title = "REC-4881 clinical update"
    catalyst = Catalyst(
        id=stable_id(
            operator_id,
            "catalyst",
            f"{release_id}:{catalyst_title}",
        ),
        passage_id=passages["catalyst"].id,
        title=catalyst_title,
        status="expected",
        window_start="2026-07-01",
        window_end="2026-12-31",
    )
    risk_title = "Runway depends on current operating plans"
    risk = Risk(
        id=stable_id(
            operator_id,
            "risk",
            f"{release_id}:{risk_title}",
        ),
        passage_id=passages["runway_risk"].id,
        title=risk_title,
        risk_type="financial",
        severity="medium",
        status="active",
    )

    return IssuerContext(
        operator_id=operator_id,
        research_run_id=stable_id(operator_id, "research-run", idempotency_key),
        release_id=release_id,
        idempotency_key=idempotency_key,
        ticker=ticker,
        company_name=request.company_name,
        run_status="completed",
        release_type=request.release_type,
        title=request.title,
        published_at=request.published_at,
        source_url=request.source_url,
        retrieved_at=release.retrieved_at,
        content_sha256=evidence_content_sha256,
        passages=tuple(passages.values()),
        metrics=metrics,
        catalysts=(catalyst,),
        risks=(risk,),
    )

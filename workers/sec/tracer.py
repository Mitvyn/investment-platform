from __future__ import annotations

import hashlib
import re
import uuid
from html.parser import HTMLParser

from workers.ids import stable_id

from .models import CollectedFiling, EvidenceTrace


def normalize_text(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    return re.sub(r"\$\s+(?=\d)", "$", normalized)


class FilingTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def normalized_text(self) -> str:
        return normalize_text(" ".join(self.parts))


def build_evidence_trace(
    filing: CollectedFiling,
    *,
    operator_id: str,
) -> EvidenceTrace:
    uuid.UUID(operator_id)
    request = filing.request
    parser = FilingTextParser()
    parser.feed(filing.html)
    normalized_document = parser.normalized_text()
    passage = normalize_text(request.expected_passage)

    if normalized_document.count(passage) != 1:
        raise ValueError("expected SEC passage must appear exactly once")

    ticker = request.ticker.strip().upper()
    accession = request.accession_number
    idempotency_key = f"sec:{ticker}:{accession}:v1"
    passage_sha256 = hashlib.sha256(passage.encode()).hexdigest()
    claim = normalize_text(request.claim_text)
    claim_sha256 = hashlib.sha256(claim.encode()).hexdigest()

    return EvidenceTrace(
        operator_id=operator_id,
        research_run_id=stable_id(operator_id, "research-run", idempotency_key),
        source_id=stable_id(operator_id, "source", f"sec:{request.cik.zfill(10)}"),
        document_id=stable_id(operator_id, "document", accession),
        passage_id=stable_id(
            operator_id,
            "passage",
            f"{accession}:{passage_sha256}",
        ),
        claim_id=stable_id(
            operator_id,
            "claim",
            f"{ticker}:{claim_sha256}",
        ),
        claim_evidence_id=stable_id(
            operator_id,
            "claim-evidence",
            f"{ticker}:{claim_sha256}:{passage_sha256}",
        ),
        idempotency_key=idempotency_key,
        ticker=ticker,
        company_name=request.company_name,
        run_status="completed",
        source_provider="sec",
        source_external_id=f"cik:{request.cik.zfill(10)}",
        source_title=f"{request.company_name} SEC filings",
        source_canonical_url=(
            "https://www.sec.gov/edgar/browse/"
            f"?CIK={request.cik.zfill(10)}&owner=exclude"
        ),
        filing_form=request.filing_form,
        filed_at=request.filed_at,
        period_end=request.period_end,
        accession_number=accession,
        primary_document=request.primary_document,
        source_url=filing.source_url,
        retrieved_at=filing.retrieved_at,
        content_sha256=filing.content_sha256,
        locator=request.passage_locator,
        passage_text=passage,
        passage_sha256=passage_sha256,
        claim_text=claim,
        claim_sha256=claim_sha256,
        verification_state="supported",
        relationship="supports",
    )

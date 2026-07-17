from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class FilingRequest:
    ticker: str
    company_name: str
    cik: str
    accession_number: str
    primary_document: str
    filing_form: str
    filed_at: str
    period_end: str
    passage_locator: str
    expected_passage: str
    claim_text: str


@dataclass(frozen=True, slots=True)
class CollectedFiling:
    request: FilingRequest
    source_url: str
    retrieved_at: str
    html: str
    content_sha256: str


@dataclass(frozen=True, slots=True)
class EvidenceTrace:
    operator_id: str
    research_run_id: str
    source_id: str
    document_id: str
    passage_id: str
    claim_id: str
    claim_evidence_id: str
    idempotency_key: str
    ticker: str
    company_name: str
    run_status: str
    source_provider: str
    source_external_id: str
    source_title: str
    source_canonical_url: str
    filing_form: str
    filed_at: str
    period_end: str
    accession_number: str
    primary_document: str
    source_url: str
    retrieved_at: str
    content_sha256: str
    locator: str
    passage_text: str
    passage_sha256: str
    claim_text: str
    claim_sha256: str
    verification_state: str
    relationship: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def dashboard_record(self) -> dict[str, str]:
        return {
            "ticker": self.ticker,
            "companyName": self.company_name,
            "researchRunId": self.research_run_id,
            "runStatus": self.run_status,
            "sourceProvider": self.source_provider,
            "sourceTitle": self.source_title,
            "filingForm": self.filing_form,
            "filedAt": self.filed_at,
            "periodEnd": self.period_end,
            "accessionNumber": self.accession_number,
            "sourceUrl": self.source_url,
            "retrievedAt": self.retrieved_at,
            "locator": self.locator,
            "passage": self.passage_text,
            "passageSha256": self.passage_sha256,
            "claim": self.claim_text,
            "verificationState": self.verification_state,
        }

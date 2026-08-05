from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from workers.clinical_trials.collector import (
    ClinicalTrialsCollector,
    ClinicalTrialsSettings,
    ClinicalTrialsSnapshot,
)
from workers.official_sources import OfficialIssuerEvidenceAdapter
from workers.official_sources.models import OfficialSourceSnapshot
from workers.regulatory import FDARegulatoryEvidenceAdapter
from workers.sec.collector import SecSettings
from workers.sec.documents import (
    SecFilingDocumentCollector,
    SecFilingDocumentSnapshot,
)
from workers.sec.exhibits import (
    SecFilingExhibitCollector,
    SecFilingExhibitSnapshot,
)
from workers.sec.passages import (
    SecExactPassageExtractor,
    SecExactPassageResult,
)
from workers.sec.selection import (
    RequiredSecFilingSelector,
    SecFilingSelection,
)
from workers.sec.submissions import (
    SecSubmissionsCollector,
    SecSubmissionsSnapshot,
)
from workers.security_registry.client import SecurityRegistryClient
from workers.security_registry.models import RegisteredSecurity

from .captures import (
    PrimarySourceCapture,
    load_primary_source_capture,
)
from .companyfacts import (
    SecCompanyFactsCollector,
    SecCompanyFactsSettings,
    SecCompanyFactsSnapshot,
)
from .models import PrimarySourceRequest
from .plans import SecPassagePlan, resolve_sec_passage_sources


@dataclass(frozen=True, slots=True)
class ReplayedSecPassage:
    plan: SecPassagePlan
    extraction: SecExactPassageResult


@dataclass(frozen=True, slots=True)
class PrimarySourceReplayResult:
    capture: PrimarySourceCapture
    registered_security: RegisteredSecurity
    submissions: SecSubmissionsSnapshot
    selection: SecFilingSelection
    documents: SecFilingDocumentSnapshot
    exhibits: SecFilingExhibitSnapshot
    sec_passages: tuple[ReplayedSecPassage, ...]
    issuer: OfficialSourceSnapshot
    clinical_trials: ClinicalTrialsSnapshot
    regulatory: OfficialSourceSnapshot
    companyfacts: SecCompanyFactsSnapshot


def replay_primary_source_capture(
    raw_archive: bytes,
    *,
    request: PrimarySourceRequest,
    ticker: str,
    sec_user_agent: str,
    trusted_issuer_hosts: tuple[str, ...],
    accepted_at: Callable[[], datetime],
) -> PrimarySourceReplayResult:
    capture = load_primary_source_capture(
        raw_archive,
        request=request,
        trusted_issuer_hosts=trusted_issuer_hosts,
        accepted_at=accepted_at,
    )
    session = capture.open_session()

    registry_transport = session.sec_transport()
    registered_security = SecurityRegistryClient(
        SecSettings(
            user_agent=sec_user_agent,
            base_url="https://www.sec.gov",
        ),
        transport=registry_transport,
        clock=registry_transport.clock,
    ).resolve(ticker, operator_id=request.operator_id)

    submissions_transport = session.sec_transport()
    submissions = SecSubmissionsCollector(
        SecSettings(
            user_agent=sec_user_agent,
            base_url="https://data.sec.gov",
        ),
        transport=submissions_transport,
        clock=submissions_transport.clock,
    ).discover(request)
    selection = RequiredSecFilingSelector().select(submissions)

    document_transport = session.sec_transport()
    documents = SecFilingDocumentCollector(
        SecSettings(user_agent=sec_user_agent),
        transport=document_transport,
        clock=document_transport.clock,
    ).collect(selection)

    exhibit_transport = session.sec_transport()
    exhibits = SecFilingExhibitCollector(
        SecSettings(user_agent=sec_user_agent),
        transport=exhibit_transport,
        clock=exhibit_transport.clock,
    ).collect(documents)

    extractor = SecExactPassageExtractor()
    sec_passages = tuple(
        ReplayedSecPassage(
            plan=resolved.plan,
            extraction=extractor.extract(
                resolved.document,
                resolved.plan.exact_text,
            ),
        )
        for resolved in resolve_sec_passage_sources(capture.plan, documents)
    )

    issuer_transport = session.official_transport("issuer_document")
    issuer = OfficialIssuerEvidenceAdapter(
        allowed_hosts=capture.plan.trusted_issuer_hosts,
        transport=issuer_transport,
        clock=issuer_transport.clock,
    ).collect(request, capture.plan.issuer_sources)

    clinical_transport = session.clinical_trials_transport()
    clinical_trials = ClinicalTrialsCollector(
        ClinicalTrialsSettings(),
        transport=clinical_transport,
        clock=clinical_transport.clock,
    ).collect(request, capture.plan.clinical_trial_search)

    regulatory_transport = session.official_transport(
        "regulatory_document"
    )
    regulatory = FDARegulatoryEvidenceAdapter(
        allowed_hosts=capture.plan.regulatory_allowed_hosts,
        transport=regulatory_transport,
        clock=regulatory_transport.clock,
    ).collect(request, capture.plan.regulatory_sources)

    companyfacts_transport = session.sec_transport()
    companyfacts = SecCompanyFactsCollector(
        SecCompanyFactsSettings(user_agent=sec_user_agent),
        transport=companyfacts_transport,
        clock=companyfacts_transport.clock,
    ).collect(request, submissions=submissions)

    session.assert_all_consumed()
    return PrimarySourceReplayResult(
        capture=capture,
        registered_security=registered_security,
        submissions=submissions,
        selection=selection,
        documents=documents,
        exhibits=exhibits,
        sec_passages=sec_passages,
        issuer=issuer,
        clinical_trials=clinical_trials,
        regulatory=regulatory,
        companyfacts=companyfacts,
    )


__all__ = [
    "PrimarySourceReplayResult",
    "ReplayedSecPassage",
    "replay_primary_source_capture",
]

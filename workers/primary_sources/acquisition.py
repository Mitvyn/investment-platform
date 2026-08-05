from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
import time

from workers.clinical_trials.collector import (
    ClinicalTrialsCollector,
    ClinicalTrialsSettings,
)
from workers.official_sources import OfficialIssuerEvidenceAdapter
from workers.regulatory import FDARegulatoryEvidenceAdapter
from workers.sec.collector import BytesTransport, SecSettings
from workers.sec.documents import SecFilingDocumentCollector
from workers.sec.exhibits import SecFilingExhibitCollector
from workers.sec.passages import SecExactPassageExtractor
from workers.sec.selection import RequiredSecFilingSelector
from workers.sec.submissions import SecSubmissionsCollector
from workers.security_registry.client import SecurityRegistryClient

from .capture_recording import PrimarySourceCaptureRecorder
from .companyfacts import (
    SecCompanyFactsCollector,
    SecCompanyFactsSettings,
)
from .models import PrimarySourceRequest
from .plans import resolve_sec_passage_sources


class PrimarySourceAcquisitionError(RuntimeError):
    """Raised when live sources cannot produce one coherent capture."""


@dataclass(frozen=True, slots=True)
class PrimarySourceAcquisitionResult:
    archive: bytes
    selected_accessions: tuple[str, ...]
    issuer_source_count: int
    clinical_study_count: int
    regulatory_source_count: int
    companyfact_count: int


class SpacedBytesTransport:
    """Serialize requests and enforce one process-wide minimum spacing."""

    def __init__(
        self,
        transport: BytesTransport,
        *,
        user_agent: str,
        minimum_interval_seconds: float,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not user_agent.strip():
            raise ValueError("source contact user agent is required")
        if minimum_interval_seconds < 0:
            raise ValueError(
                "source request interval must not be negative"
            )
        self._transport = transport
        self._user_agent = user_agent
        self._minimum_interval_seconds = minimum_interval_seconds
        self._monotonic = monotonic
        self._sleeper = sleeper
        self._last_started_at: float | None = None
        self._lock = Lock()

    def request(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
    ):
        request_headers = dict(headers)
        request_headers.setdefault("User-Agent", self._user_agent)
        with self._lock:
            now = self._monotonic()
            if self._last_started_at is not None:
                remaining = (
                    self._minimum_interval_seconds
                    - (now - self._last_started_at)
                )
                if remaining > 0:
                    self._sleeper(remaining)
                    now = self._monotonic()
            self._last_started_at = now
            return self._transport.request(
                url,
                headers=request_headers,
            )


def acquire_primary_source_capture(
    *,
    request: PrimarySourceRequest,
    ticker: str,
    source_plan: bytes,
    trusted_issuer_hosts: tuple[str, ...],
    user_agent: str,
    transport: BytesTransport,
    clock: Callable[[], datetime],
    capture_id: str,
    revision: int,
    assembled_at: datetime | None,
) -> PrimarySourceAcquisitionResult:
    """Collect and seal one plan-bound capture using injected transport."""

    recorder = PrimarySourceCaptureRecorder(
        source_plan=source_plan,
        request=request,
        trusted_issuer_hosts=trusted_issuer_hosts,
        clock=clock,
    )
    recorded_transport = recorder.transport(transport)
    registered = SecurityRegistryClient(
        SecSettings(
            user_agent=user_agent,
            base_url="https://www.sec.gov",
        ),
        transport=recorded_transport,
        clock=recorded_transport.clock,
    ).resolve(ticker, operator_id=request.operator_id)
    if (
        registered.security_id != request.security_id
        or registered.cik != request.cik
        or registered.primary_listing_exchange.casefold()
        != request.primary_listing_exchange.casefold()
    ):
        raise PrimarySourceAcquisitionError(
            "SEC security registry does not match request"
        )

    submissions = SecSubmissionsCollector(
        SecSettings(
            user_agent=user_agent,
            base_url="https://data.sec.gov",
        ),
        transport=recorded_transport,
        clock=recorded_transport.clock,
    ).discover(request)
    selection = RequiredSecFilingSelector().select(submissions)
    if selection.coverage_state != "complete":
        raise PrimarySourceAcquisitionError(
            "required SEC filing coverage is incomplete"
        )
    documents = SecFilingDocumentCollector(
        SecSettings(user_agent=user_agent),
        transport=recorded_transport,
        clock=recorded_transport.clock,
    ).collect(selection)
    exhibits = SecFilingExhibitCollector(
        SecSettings(user_agent=user_agent),
        transport=recorded_transport,
        clock=recorded_transport.clock,
    ).collect(documents)
    del exhibits

    for resolved in resolve_sec_passage_sources(
        recorder.plan,
        documents,
    ):
        passage = SecExactPassageExtractor().extract(
            resolved.document,
            resolved.plan.exact_text,
        )
        if passage.state != "found":
            raise PrimarySourceAcquisitionError(
                "planned SEC passage is not uniquely available"
            )

    issuer = OfficialIssuerEvidenceAdapter(
        allowed_hosts=trusted_issuer_hosts,
        transport=recorded_transport,
        clock=recorded_transport.clock,
    ).collect(request, recorder.plan.issuer_sources)
    if any(
        coverage.state != "complete"
        for coverage in issuer.coverage_results
    ):
        raise PrimarySourceAcquisitionError(
            "planned issuer evidence is incomplete"
        )

    clinical = ClinicalTrialsCollector(
        ClinicalTrialsSettings(),
        transport=recorded_transport,
        clock=recorded_transport.clock,
    ).collect(request, recorder.plan.clinical_trial_search)
    if clinical.coverage.status != "covered":
        raise PrimarySourceAcquisitionError(
            "planned clinical evidence is incomplete"
        )

    regulatory = FDARegulatoryEvidenceAdapter(
        allowed_hosts=recorder.plan.regulatory_allowed_hosts,
        transport=recorded_transport,
        clock=recorded_transport.clock,
    ).collect(request, recorder.plan.regulatory_sources)
    if any(
        coverage.state != "complete"
        for coverage in regulatory.coverage_results
    ):
        raise PrimarySourceAcquisitionError(
            "planned regulatory evidence is incomplete"
        )

    companyfacts = SecCompanyFactsCollector(
        SecCompanyFactsSettings(user_agent=user_agent),
        transport=recorded_transport,
        clock=recorded_transport.clock,
    ).collect(request, submissions=submissions)
    if companyfacts.coverage_state != "complete":
        raise PrimarySourceAcquisitionError(
            "SEC Company Facts core metrics are incomplete"
        )

    return PrimarySourceAcquisitionResult(
        archive=recorder.assemble(
            capture_id=capture_id,
            revision=revision,
            assembled_at=(
                assembled_at
                if assembled_at is not None
                else clock()
            ),
        ),
        selected_accessions=tuple(
            filing.accession_number
            for filing in selection.selected_filings
        ),
        issuer_source_count=len(issuer.source_results),
        clinical_study_count=len(clinical.included_studies),
        regulatory_source_count=len(regulatory.source_results),
        companyfact_count=len(companyfacts.facts),
    )


__all__ = [
    "PrimarySourceAcquisitionError",
    "PrimarySourceAcquisitionResult",
    "SpacedBytesTransport",
    "acquire_primary_source_capture",
]

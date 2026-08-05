from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Callable, Mapping

from workers.sec.collector import (
    BytesTransport,
    EMAIL_PATTERN,
)
from workers.sec.submissions import SecSubmissionsSnapshot

from .models import PrimarySourceRequest
from .temporal import assess_publication_time

if TYPE_CHECKING:
    from .share_growth import BasicShareObservation


_POLICY_VERSION = "sec-companyfacts-core-metrics-v1"
_COMPOSITE_FINANCING_POLICY_VERSION = "biotech-financing-share-capital-v1"


@dataclass(frozen=True, slots=True)
class _ConceptSpec:
    taxonomy: str
    concept: str
    unit: str
    normalization: str = "reported"


_CONCEPTS = (
    (
        "basic_shares_outstanding",
        (
            _ConceptSpec(
                "us-gaap",
                "CommonStockSharesOutstanding",
                "shares",
            ),
            _ConceptSpec(
                "dei",
                "EntityCommonStockSharesOutstanding",
                "shares",
            ),
        ),
    ),
    (
        "cash_and_cash_equivalents",
        (
            _ConceptSpec(
                "us-gaap",
                "CashAndCashEquivalentsAtCarryingValue",
                "USD",
            ),
        ),
    ),
    (
        "debt_current",
        (
            _ConceptSpec(
                "us-gaap",
                "LongTermDebtAndCapitalLeaseObligationsCurrent",
                "USD",
            ),
            _ConceptSpec(
                "us-gaap",
                "LongTermDebtCurrent",
                "USD",
            ),
        ),
    ),
    (
        "operating_cash_used",
        (
            _ConceptSpec(
                "us-gaap",
                "NetCashUsedInOperatingActivities",
                "USD",
            ),
            _ConceptSpec(
                "us-gaap",
                "NetCashProvidedByUsedInOperatingActivities",
                "USD",
                normalization="cash_used_from_signed_cash_flow",
            ),
        ),
    ),
)


class SecCompanyFactsCollectorError(RuntimeError):
    """Raised when SEC Company Facts data cannot be trusted."""


@dataclass(frozen=True, slots=True)
class SecCompanyFactsSettings:
    user_agent: str
    base_url: str = "https://data.sec.gov"

    def __post_init__(self) -> None:
        if self.base_url.rstrip("/") != "https://data.sec.gov":
            raise ValueError("SEC Company Facts base URL is unsupported")
        if EMAIL_PATTERN.search(self.user_agent) is None:
            raise ValueError("SEC user agent must include a monitored email address")


@dataclass(frozen=True, slots=True)
class SecCompanyFact:
    metric_key: str
    taxonomy: str
    concept: str
    value: str
    unit: str
    period_start: date | None
    period_end: date
    filed_date: date
    accession_number: str
    form: str
    source_locator: str
    source_payload: str
    freshness: str
    reported_value: str | None = None
    published_at: datetime | None = None
    calculation_method: str = "reported"
    formula: str | None = None


@dataclass(frozen=True, slots=True)
class SecCompanyFactsSnapshot:
    operator_id: str
    security_id: str
    cik: str
    issuer_name: str
    as_of_cutoff: datetime
    policy_version: str
    coverage_state: str
    reason_codes: tuple[str, ...]
    source_url: str
    retrieved_at: datetime
    source_payload: str
    content_sha256: str
    facts: tuple[SecCompanyFact, ...]
    basic_share_facts: tuple[SecCompanyFact, ...] = ()


class SecCompanyFactsCollector:
    def __init__(
        self,
        settings: SecCompanyFactsSettings,
        *,
        transport: BytesTransport,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport
        self.clock = clock or (lambda: datetime.now(UTC))

    def collect(
        self,
        request: PrimarySourceRequest,
        *,
        submissions: SecSubmissionsSnapshot | None = None,
    ) -> SecCompanyFactsSnapshot:
        source_url = (
            f"{self.settings.base_url.rstrip('/')}/api/xbrl/companyfacts/"
            f"CIK{request.cik}.json"
        )
        response = self.transport.request(
            source_url,
            headers={
                "Accept": "application/json",
                "User-Agent": self.settings.user_agent,
            },
        )
        if not 200 <= response.status < 300:
            raise SecCompanyFactsCollectorError(
                f"SEC returned HTTP {response.status} for Company Facts"
            )
        if response.final_url != source_url:
            raise SecCompanyFactsCollectorError("SEC Company Facts response redirected")
        media_type = (
            next(
                (
                    value
                    for key, value in response.headers.items()
                    if key.lower() == "content-type"
                ),
                "",
            )
            .partition(";")[0]
            .strip()
            .lower()
        )
        if media_type != "application/json":
            raise SecCompanyFactsCollectorError(
                "SEC Company Facts content type is invalid"
            )
        try:
            source_payload = response.body.decode("utf-8")
            payload = json.loads(source_payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SecCompanyFactsCollectorError(
                "SEC Company Facts response is invalid JSON"
            ) from error
        if not isinstance(payload, dict):
            raise SecCompanyFactsCollectorError("SEC Company Facts response is invalid")
        cik = payload.get("cik")
        if (
            isinstance(cik, bool)
            or not isinstance(cik, int)
            or f"{cik:010d}" != request.cik
        ):
            raise SecCompanyFactsCollectorError(
                "SEC Company Facts CIK does not match request"
            )
        entity_name = payload.get("entityName")
        if (
            not isinstance(entity_name, str)
            or " ".join(entity_name.split()).casefold()
            != " ".join(request.issuer_name.split()).casefold()
        ):
            raise SecCompanyFactsCollectorError(
                "SEC Company Facts issuer does not match request"
            )
        facts_root = payload.get("facts")
        if not isinstance(facts_root, dict):
            raise SecCompanyFactsCollectorError("SEC Company Facts facts are invalid")

        publication_times = self._publication_times(request, submissions)
        selected_facts: list[SecCompanyFact] = []
        basic_share_facts: tuple[SecCompanyFact, ...] = ()
        for metric_key, concept_specs in _CONCEPTS:
            candidates = tuple(
                (
                    priority,
                    facts,
                )
                for priority, spec in enumerate(concept_specs)
                if (
                    facts := self._accepted_facts(
                        facts_root,
                        metric_key=metric_key,
                        spec=spec,
                        cutoff=request.as_of_cutoff,
                        publication_times=publication_times,
                    )
                )
            )
            if candidates:
                selected = max(
                    candidates,
                    key=lambda item: (
                        item[1][-1].period_end,
                        item[1][-1].filed_date,
                        item[1][-1].accession_number,
                        -item[0],
                    ),
                )[1]
                selected_facts.append(selected[-1])
                if metric_key == "basic_shares_outstanding":
                    basic_share_facts = selected
        facts = tuple(selected_facts)
        available_keys = {fact.metric_key for fact in facts}
        missing = tuple(
            metric_key
            for metric_key, _concept_specs in _CONCEPTS
            if metric_key not in available_keys
        )
        retrieved_at = self.clock()
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise RuntimeError("SEC Company Facts clock must include timezone")
        return SecCompanyFactsSnapshot(
            operator_id=request.operator_id,
            security_id=request.security_id,
            cik=request.cik,
            issuer_name=request.issuer_name,
            as_of_cutoff=request.as_of_cutoff,
            policy_version=_POLICY_VERSION,
            coverage_state="complete" if not missing else "incomplete",
            reason_codes=(
                ("sec_companyfacts_core_metrics_complete",)
                if not missing
                else (
                    *(f"sec_companyfacts_missing_{key}" for key in missing),
                    "sec_companyfacts_core_metrics_incomplete",
                )
            ),
            source_url=source_url,
            retrieved_at=retrieved_at.astimezone(UTC),
            source_payload=source_payload,
            content_sha256=hashlib.sha256(response.body).hexdigest(),
            facts=facts,
            basic_share_facts=basic_share_facts,
        )

    @staticmethod
    def _publication_times(
        request: PrimarySourceRequest,
        submissions: SecSubmissionsSnapshot | None,
    ) -> Mapping[str, datetime | None] | None:
        if submissions is None:
            return None
        if (
            submissions.operator_id != request.operator_id
            or submissions.security_id != request.security_id
            or submissions.cik != request.cik
            or submissions.issuer_name != request.issuer_name
            or submissions.as_of_cutoff != request.as_of_cutoff
        ):
            raise SecCompanyFactsCollectorError(
                "SEC submissions context does not match Company Facts request"
            )
        return {
            filing.accession_number: filing.published_at
            for filing in (
                *submissions.included_filings,
                *submissions.excluded_filings,
            )
        }

    @staticmethod
    def _accepted_facts(
        facts_root: Mapping[str, object],
        *,
        metric_key: str,
        spec: _ConceptSpec,
        cutoff: datetime,
        publication_times: Mapping[str, datetime | None] | None,
    ) -> tuple[SecCompanyFact, ...]:
        taxonomy_payload = facts_root.get(spec.taxonomy)
        if not isinstance(taxonomy_payload, dict):
            return ()
        concept_payload = taxonomy_payload.get(spec.concept)
        if not isinstance(concept_payload, dict):
            return ()
        units_payload = concept_payload.get("units")
        if not isinstance(units_payload, dict):
            return ()
        observations = units_payload.get(spec.unit)
        if not isinstance(observations, list):
            return ()

        accepted: list[SecCompanyFact] = []
        for observation in observations:
            if not isinstance(observation, dict):
                raise SecCompanyFactsCollectorError(
                    "SEC Company Facts observation is invalid"
                )
            form = observation.get("form")
            filed_raw = observation.get("filed")
            end_raw = observation.get("end")
            accession = observation.get("accn")
            if (
                form not in {"10-Q", "10-Q/A", "10-K", "10-K/A"}
                or not isinstance(filed_raw, str)
                or not isinstance(end_raw, str)
                or not isinstance(accession, str)
            ):
                continue
            try:
                filed_date = date.fromisoformat(filed_raw)
                period_end = date.fromisoformat(end_raw)
                start_raw = observation.get("start")
                period_start = (
                    date.fromisoformat(start_raw)
                    if isinstance(start_raw, str)
                    else None
                )
            except ValueError as error:
                raise SecCompanyFactsCollectorError(
                    "SEC Company Facts period is invalid"
                ) from error
            published_at: datetime | None = None
            if publication_times is None:
                publication = assess_publication_time(filed_raw, cutoff)
                if not publication.valid_at_cutoff:
                    continue
            else:
                if accession not in publication_times:
                    continue
                published_at = publication_times[accession]
                if published_at is None or published_at > cutoff:
                    continue
            if period_end > cutoff.date() or (
                period_start is not None and period_start > period_end
            ):
                continue
            value = observation.get("val")
            if isinstance(value, bool) or not isinstance(
                value,
                (int, float, str),
            ):
                raise SecCompanyFactsCollectorError(
                    "SEC Company Facts value is invalid"
                )
            try:
                reported_value = Decimal(str(value))
            except InvalidOperation as error:
                raise SecCompanyFactsCollectorError(
                    "SEC Company Facts value is invalid"
                ) from error
            canonical_reported_value = format(reported_value, "f")
            if spec.normalization == "reported":
                canonical_value = canonical_reported_value
                calculation_method = "reported"
                formula = None
            elif spec.normalization == "cash_used_from_signed_cash_flow":
                canonical_value = format(max(-reported_value, Decimal(0)), "f")
                calculation_method = "derived"
                formula = "max(-reported_value,0)"
            else:
                raise AssertionError("unsupported Company Facts normalization")
            accepted.append(
                SecCompanyFact(
                    metric_key=metric_key,
                    taxonomy=spec.taxonomy,
                    concept=spec.concept,
                    value=canonical_value,
                    unit=spec.unit,
                    period_start=period_start,
                    period_end=period_end,
                    filed_date=filed_date,
                    accession_number=accession,
                    form=form,
                    source_locator=(
                        f"facts.{spec.taxonomy}.{spec.concept}.units.{spec.unit}"
                    ),
                    source_payload=json.dumps(
                        {
                            "calculation_method": calculation_method,
                            "concept": spec.concept,
                            "formula": formula,
                            "normalized_value": canonical_value,
                            "observation": observation,
                            "reported_value": canonical_reported_value,
                            "taxonomy": spec.taxonomy,
                            "unit": spec.unit,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    freshness=(
                        "current"
                        if (cutoff.date() - filed_date).days <= 200
                        else "stale"
                    ),
                    reported_value=canonical_reported_value,
                    published_at=published_at,
                    calculation_method=calculation_method,
                    formula=formula,
                )
            )
        return tuple(
            sorted(
                accepted,
                key=lambda fact: (
                    fact.period_end,
                    fact.filed_date,
                    fact.accession_number,
                ),
            )
        )


def companyfacts_pipeline_inputs(
    snapshot: SecCompanyFactsSnapshot,
):
    from .pipeline import NormalizedMetricFact, PrimaryEvidencePassage

    coverage_keys: frozenset[str] = frozenset()
    passages = tuple(
        PrimaryEvidencePassage(
            reference_key=f"sec-companyfacts:{fact.metric_key}",
            source_class="financing",
            coverage_keys=coverage_keys,
            source_locator=fact.source_locator,
            canonical_url=snapshot.source_url,
            publication_at=None,
            retrieved_at=snapshot.retrieved_at,
            effective_at=None,
            filing_period_start=fact.period_start,
            filing_period_end=fact.period_end,
            document_content_hash=hashlib.sha256(
                fact.source_payload.encode()
            ).hexdigest(),
            passage_text=fact.source_payload,
            freshness=fact.freshness,
            origin_policy_version="sec-origin-v1",
            available_at=datetime.combine(
                fact.filed_date,
                time.max,
                tzinfo=UTC,
            )
            if fact.published_at is None
            else fact.published_at,
        )
        for fact in snapshot.facts
    )
    metrics = tuple(
        NormalizedMetricFact(
            reference_key=f"sec-companyfacts:{fact.metric_key}",
            source_class="financing",
            metric_key=fact.metric_key,
            value=fact.value,
            unit=fact.unit,
            period_start=fact.period_start,
            period_end=fact.period_end,
            calculation_method=fact.calculation_method,
            formula=fact.formula,
            supporting_passage_keys=(f"sec-companyfacts:{fact.metric_key}",),
        )
        for fact in snapshot.facts
    )
    return passages, metrics


def _basic_share_reference_key(fact: SecCompanyFact) -> str:
    return (
        "sec-companyfacts:basic_shares_outstanding:"
        f"{fact.period_end.isoformat()}:{fact.accession_number}"
    )


def companyfacts_basic_share_growth_passages(
    snapshot: SecCompanyFactsSnapshot,
):
    from .pipeline import PrimaryEvidencePassage

    return tuple(
        PrimaryEvidencePassage(
            reference_key=_basic_share_reference_key(fact),
            source_class="financing",
            coverage_keys=frozenset(),
            source_locator=(
                f"{fact.source_locator}#observation="
                f"{fact.period_end.isoformat()}:{fact.accession_number}"
            ),
            canonical_url=snapshot.source_url,
            publication_at=None,
            retrieved_at=snapshot.retrieved_at,
            effective_at=None,
            filing_period_start=fact.period_start,
            filing_period_end=fact.period_end,
            document_content_hash=hashlib.sha256(
                fact.source_payload.encode()
            ).hexdigest(),
            passage_text=fact.source_payload,
            freshness=fact.freshness,
            origin_policy_version="sec-origin-v1",
            available_at=fact.published_at,
        )
        for fact in snapshot.basic_share_facts
        if fact.published_at is not None
    )


def companyfacts_basic_share_growth_observations(
    snapshot: SecCompanyFactsSnapshot,
) -> tuple[BasicShareObservation, ...]:
    from .share_growth import BasicShareObservation

    observations = []
    for fact in snapshot.basic_share_facts:
        if fact.published_at is None:
            continue
        observations.append(
            BasicShareObservation(
                security_id=snapshot.security_id,
                cik=snapshot.cik,
                period_end=fact.period_end,
                accession_number=fact.accession_number,
                accepted_at=fact.published_at,
                reference_key=_basic_share_reference_key(fact),
                value=fact.value,
                unit=fact.unit,
                concept=f"{fact.taxonomy}:{fact.concept}",
                measurement_basis="point_in_time",
                economic_basis="issuer_reported_total_basic_common_equity",
                is_amendment=fact.form.endswith("/A"),
            )
        )
    return tuple(observations)


def companyfacts_coverage_proof(
    snapshot: SecCompanyFactsSnapshot,
):
    from .pipeline import PrimarySourceCoverageProof

    return PrimarySourceCoverageProof(
        requirement_id="financing_share_capital",
        source_class="financing",
        policy_version=_COMPOSITE_FINANCING_POLICY_VERSION,
        state="incomplete",
        reason_codes=(
            *snapshot.reason_codes,
            "financing_capital_structure_scan_missing",
        ),
        evidence_reference_keys=tuple(
            f"sec-companyfacts:{fact.metric_key}" for fact in snapshot.facts
        ),
    )


__all__ = [
    "SecCompanyFact",
    "SecCompanyFactsCollector",
    "SecCompanyFactsCollectorError",
    "SecCompanyFactsSettings",
    "SecCompanyFactsSnapshot",
    "companyfacts_basic_share_growth_passages",
    "companyfacts_basic_share_growth_observations",
    "companyfacts_coverage_proof",
    "companyfacts_pipeline_inputs",
]

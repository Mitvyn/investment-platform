from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Mapping
from urllib.parse import urlparse

from investment_research_os.evidence_bundles import (
    CatalystSnapshot,
    EvidenceBundleCandidate,
    EvidenceGap,
    EvidenceItem,
    RiskSnapshot,
    VerifiedMetricSnapshot,
    validate_evidence_source_url,
)
from investment_research_os.research_runs import (
    REQUIRED_PRIMARY_SOURCE_COVERAGE,
    RULE_IDS,
    CatalystCandidate,
    EvidenceReference,
    SecurityEligibilitySnapshot,
)

from workers.ids import stable_id

from .models import PrimarySourceRequest
from .regulatory_linkage import has_programme_designation_link

if TYPE_CHECKING:
    from .eligibility import DerivedEligibilityProfile


EVIDENCE_POLICY_VERSION = "biotech-primary-evidence-v3"
FRESHNESS_POLICY_VERSION = "biotech-evidence-freshness-v1"
SOURCE_CLASS_ORDER = ("sec", "issuer", "clinical", "regulatory", "financing")
_SOURCE_COVERAGE = {
    "sec": frozenset({"sec_issuer_security", "required_sec_filings"}),
    "issuer": frozenset({"issuer_pipeline"}),
    "clinical": frozenset({"authoritative_trial"}),
    "regulatory": frozenset({"us_regulatory"}),
    "financing": frozenset({"financing_share_capital"}),
}
_COVERAGE_SOURCE_CLASS = {
    coverage_key: source_class
    for source_class, coverage_keys in _SOURCE_COVERAGE.items()
    for coverage_key in coverage_keys
}
_COVERAGE_POLICY_VERSION = {
    "sec_issuer_security": "sec-issuer-identity-v1",
    "required_sec_filings": "biotech-required-sec-filings-v1",
    "issuer_pipeline": "official-issuer-source-v1",
    "authoritative_trial": "clinical-trials-source-v2",
    "us_regulatory": "fda-regulatory-source-v2",
    "financing_share_capital": "biotech-financing-share-capital-v1",
}
_SOURCE_ORIGIN_POLICY_VERSION = {
    "sec": "sec-origin-v1",
    "issuer": "official-issuer-origin-v1",
    "clinical": "clinical-trials-origin-v1",
    "regulatory": "fda-origin-v1",
    "financing": "sec-origin-v1",
}
_SOURCE_ALLOWED_HOSTS = {
    "sec": frozenset({"data.sec.gov", "www.sec.gov"}),
    "clinical": frozenset({"clinicaltrials.gov", "www.clinicaltrials.gov"}),
    "regulatory": frozenset(
        {
            "accessdata.fda.gov",
            "fda.gov",
            "precision.fda.gov",
            "www.accessdata.fda.gov",
            "www.fda.gov",
        }
    ),
    "financing": frozenset({"data.sec.gov", "www.sec.gov"}),
}
_RULE_SOURCE_CLASSES = {
    "security_identity_verified": frozenset({"sec"}),
    "us_listing": frozenset({"sec"}),
    "cik_match": frozenset({"sec"}),
    "common_equity": frozenset({"sec"}),
    "operating_company": frozenset({"sec", "issuer", "clinical"}),
    "therapeutics_classification": frozenset({"issuer", "clinical"}),
    "active_therapeutic_program": frozenset({"issuer", "clinical"}),
    "defined_clinical_or_regulatory_catalyst": frozenset(
        {"issuer", "clinical", "regulatory"}
    ),
    "required_primary_source_coverage": frozenset(
        {"sec", "issuer", "clinical", "regulatory", "financing"}
    ),
}
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class PrimarySourcePipelineError(ValueError):
    """Raised when collected primary evidence cannot be normalized safely."""


def _has_regulatory_programme_linkage(
    passages: tuple[PrimaryEvidencePassage, ...],
    program_names: tuple[str, ...],
    evidence_reference_keys: tuple[str, ...],
) -> bool:
    cited_references = frozenset(evidence_reference_keys)
    grouped_text: dict[tuple[str, str], list[str]] = {}
    for passage in passages:
        if (
            passage.source_class != "regulatory"
            or passage.reference_key not in cited_references
        ):
            continue
        grouped_text.setdefault(
            (passage.canonical_url, passage.document_content_hash),
            [],
        ).append(passage.passage_text)
    return has_programme_designation_link(
        text_groups=tuple(tuple(texts) for texts in grouped_text.values()),
        program_names=program_names,
    )


@dataclass(frozen=True, slots=True)
class PrimaryEvidencePassage:
    reference_key: str
    source_class: str
    coverage_keys: frozenset[str]
    source_locator: str
    canonical_url: str
    publication_at: datetime | None
    retrieved_at: datetime
    effective_at: datetime | None
    filing_period_start: date | None
    filing_period_end: date | None
    document_content_hash: str
    passage_text: str
    freshness: str
    origin_policy_version: str
    available_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PrimarySourceCoverageProof:
    requirement_id: str
    source_class: str
    policy_version: str
    state: str
    reason_codes: tuple[str, ...]
    evidence_reference_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NormalizedMetricFact:
    reference_key: str
    source_class: str
    metric_key: str
    value: str
    unit: str
    period_start: date | None
    period_end: date | None
    calculation_method: str
    formula: str | None
    supporting_passage_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NormalizedCatalystFact:
    reference_key: str
    source_class: str
    event: str
    program: str
    basis: str
    status: str
    window_start: date
    window_end: date
    supporting_passage_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NormalizedRiskFact:
    reference_key: str
    source_class: str
    title: str
    risk_type: str
    severity: str
    status: str
    supporting_passage_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PrimarySourceCaptureIdentity:
    capture_id: str
    capture_revision: int
    capture_content_hash: str


@dataclass(frozen=True, slots=True)
class PrimarySourcePipelineResult:
    eligibility_snapshot: SecurityEligibilitySnapshot
    bundle_candidate: EvidenceBundleCandidate
    reason_codes: tuple[str, ...]
    source_capture_identity: PrimarySourceCaptureIdentity | None = None


def _utc(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PrimarySourcePipelineError(f"{label} must include timezone")
    return value.astimezone(UTC)


def _passage_item(
    request: PrimarySourceRequest,
    passage: PrimaryEvidencePassage,
) -> EvidenceItem:
    if not passage.reference_key.strip():
        raise PrimarySourcePipelineError("passage reference key is required")
    if passage.source_class not in _SOURCE_COVERAGE:
        raise PrimarySourcePipelineError("unsupported primary source class")
    if not passage.coverage_keys <= _SOURCE_COVERAGE[passage.source_class]:
        raise PrimarySourcePipelineError(
            "source class cannot claim requested eligibility coverage"
        )
    if not passage.source_locator.strip() or not passage.passage_text.strip():
        raise PrimarySourcePipelineError("exact primary-source passage is required")
    validate_evidence_source_url(passage.canonical_url)
    if (
        passage.origin_policy_version
        != _SOURCE_ORIGIN_POLICY_VERSION[passage.source_class]
    ):
        raise PrimarySourcePipelineError("primary evidence origin policy is invalid")
    hostname = (urlparse(passage.canonical_url).hostname or "").casefold()
    allowed_hosts = _SOURCE_ALLOWED_HOSTS.get(passage.source_class)
    if allowed_hosts is not None and hostname not in allowed_hosts:
        raise PrimarySourcePipelineError("primary evidence origin is not authoritative")
    publication_at = (
        _utc(passage.publication_at, "publication time")
        if passage.publication_at is not None
        else None
    )
    available_at = (
        _utc(passage.available_at, "source availability time")
        if passage.available_at is not None
        else publication_at
    )
    if available_at is None:
        raise PrimarySourcePipelineError("source availability time is required")
    retrieved_at = _utc(passage.retrieved_at, "retrieval time")
    effective_at = (
        _utc(passage.effective_at, "effective time")
        if passage.effective_at is not None
        else None
    )
    if publication_at is not None and publication_at > request.as_of_cutoff:
        raise PrimarySourcePipelineError("primary evidence is after cutoff")
    if available_at > request.as_of_cutoff:
        raise PrimarySourcePipelineError("primary evidence is unavailable at cutoff")
    if retrieved_at < available_at:
        raise PrimarySourcePipelineError(
            "primary evidence retrieval predates availability"
        )
    if effective_at is not None and effective_at > request.as_of_cutoff:
        raise PrimarySourcePipelineError("primary evidence is effective after cutoff")
    if (
        passage.filing_period_start is not None
        and passage.filing_period_end is not None
        and passage.filing_period_start > passage.filing_period_end
    ):
        raise PrimarySourcePipelineError("primary evidence period is invalid")
    if (
        passage.filing_period_end is not None
        and passage.filing_period_end > request.as_of_cutoff.date()
    ):
        raise PrimarySourcePipelineError("primary evidence period is after cutoff")
    if _SHA256_PATTERN.fullmatch(passage.document_content_hash) is None:
        raise PrimarySourcePipelineError("document content hash is invalid")
    if passage.freshness not in {"current", "stale", "indeterminate"}:
        raise PrimarySourcePipelineError("primary evidence freshness is invalid")

    passage_hash = hashlib.sha256(passage.passage_text.encode()).hexdigest()
    evidence_identity = (
        f"{request.security_id}:{passage.source_class}:"
        f"{passage.canonical_url}:{passage.reference_key}"
    )
    evidence_id = stable_id(
        request.operator_id,
        "primary-evidence",
        evidence_identity,
    )
    return EvidenceItem(
        evidence_id=evidence_id,
        evidence_version_id=stable_id(
            request.operator_id,
            "primary-evidence-version",
            (f"{evidence_id}:{passage.document_content_hash}:{passage_hash}"),
        ),
        provenance_type="primary_source",
        item_kind="passage",
        source_class=passage.source_class,
        source_locator=passage.source_locator,
        canonical_url=passage.canonical_url,
        publication_at=publication_at,
        retrieved_at=retrieved_at,
        effective_at=effective_at,
        filing_period_start=passage.filing_period_start,
        filing_period_end=passage.filing_period_end,
        content_hash=passage.document_content_hash,
        passage_id=stable_id(
            request.operator_id,
            "primary-passage",
            evidence_identity,
        ),
        passage_hash=passage_hash,
        freshness=passage.freshness,
        passage_text=passage.passage_text,
    )


def _fact_hash(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _fact_item(
    request: PrimarySourceRequest,
    *,
    reference_key: str,
    source_class: str,
    item_kind: str,
    payload: Mapping[str, object],
    supporting_passage_keys: tuple[str, ...],
    items_by_reference: Mapping[str, EvidenceItem],
) -> tuple[EvidenceItem, tuple[str, ...]]:
    if not reference_key.strip():
        raise PrimarySourcePipelineError("normalized fact reference key is required")
    if source_class not in _SOURCE_COVERAGE:
        raise PrimarySourcePipelineError("normalized fact source class is invalid")
    if not supporting_passage_keys:
        raise PrimarySourcePipelineError("normalized fact requires supporting evidence")
    try:
        supporting_items = tuple(
            items_by_reference[key] for key in supporting_passage_keys
        )
    except KeyError as error:
        raise PrimarySourcePipelineError(
            "normalized fact evidence reference is unresolved"
        ) from error
    if not any(item.source_class == source_class for item in supporting_items):
        raise PrimarySourcePipelineError(
            "normalized fact lacks same-class primary evidence"
        )
    canonical_payload = {
        "reference_key": reference_key,
        "source_class": source_class,
        "item_kind": item_kind,
        **payload,
        "supporting_evidence_ids": [item.evidence_id for item in supporting_items],
    }
    content_hash = _fact_hash(canonical_payload)
    identity = f"{request.security_id}:{item_kind}:{source_class}:{reference_key}"
    evidence_id = stable_id(request.operator_id, item_kind, identity)
    primary_item = next(
        item for item in supporting_items if item.source_class == source_class
    )
    effective_values = tuple(
        item.effective_at for item in supporting_items if item.effective_at is not None
    )
    return (
        EvidenceItem(
            evidence_id=evidence_id,
            evidence_version_id=stable_id(
                request.operator_id,
                f"{item_kind}-version",
                f"{evidence_id}:{content_hash}",
            ),
            provenance_type="primary_source",
            item_kind=item_kind,
            source_class=source_class,
            source_locator=f"{item_kind}:{reference_key}",
            canonical_url=primary_item.canonical_url,
            publication_at=(
                max(
                    item.publication_at
                    for item in supporting_items
                    if item.publication_at is not None
                )
                if any(item.publication_at is not None for item in supporting_items)
                else None
            ),
            retrieved_at=max(item.retrieved_at for item in supporting_items),
            effective_at=max(effective_values) if effective_values else None,
            filing_period_start=None,
            filing_period_end=None,
            content_hash=content_hash,
            passage_id=None,
            passage_hash=None,
            freshness=(
                "indeterminate"
                if any(item.freshness == "indeterminate" for item in supporting_items)
                else (
                    "stale"
                    if any(item.freshness == "stale" for item in supporting_items)
                    else "current"
                )
            ),
            passage_text=None,
        ),
        tuple(item.evidence_id for item in supporting_items),
    )


class PrimarySourcePipeline:
    def assemble(
        self,
        *,
        request: PrimarySourceRequest,
        profile: DerivedEligibilityProfile,
        passages: tuple[PrimaryEvidencePassage, ...],
        coverage_proofs: tuple[PrimarySourceCoverageProof, ...],
        metrics: tuple[NormalizedMetricFact, ...] = (),
        catalysts: tuple[NormalizedCatalystFact, ...] = (),
        risks: tuple[NormalizedRiskFact, ...] = (),
        regulatory_program_names: tuple[str, ...] = (),
    ) -> PrimarySourcePipelineResult:
        if not passages:
            raise PrimarySourcePipelineError("primary evidence is required")
        reference_keys = [passage.reference_key for passage in passages]
        if len(set(reference_keys)) != len(reference_keys):
            raise PrimarySourcePipelineError("duplicate primary evidence reference key")
        items_by_reference = {
            passage.reference_key: _passage_item(request, passage)
            for passage in passages
        }
        passages_by_reference = {passage.reference_key: passage for passage in passages}
        from .eligibility import (
            ELIGIBILITY_RULE_IDS,
            ELIGIBILITY_SOURCE_POLICY_VERSION,
            DerivedEligibilityProfile,
        )

        if not isinstance(profile, DerivedEligibilityProfile):
            raise PrimarySourcePipelineError(
                "eligibility profile must be deterministically derived"
            )
        if profile.policy_version != ELIGIBILITY_SOURCE_POLICY_VERSION:
            raise PrimarySourcePipelineError("eligibility source policy is invalid")
        outcome_rule_ids = tuple(outcome.rule_id for outcome in profile.outcomes)
        if outcome_rule_ids != ELIGIBILITY_RULE_IDS or ELIGIBILITY_RULE_IDS != RULE_IDS:
            raise PrimarySourcePipelineError(
                "eligibility source outcomes do not match locked rules"
            )
        for outcome in profile.outcomes:
            if (
                outcome.rule_version != f"{outcome.rule_id}.source.v1"
                or outcome.state not in {"pass", "fail"}
                or not outcome.reason_code.strip()
                or not outcome.normalized_values
                or any(not value.strip() for value in outcome.normalized_values)
            ):
                raise PrimarySourcePipelineError(
                    "eligibility source outcome is invalid"
                )
            if outcome.state == "pass" and not outcome.evidence_reference_keys:
                raise PrimarySourcePipelineError(
                    "passed eligibility outcome requires evidence"
                )
        outcome_references = {
            reference_key
            for outcome in profile.outcomes
            for reference_key in outcome.evidence_reference_keys
        }
        if outcome_references - set(items_by_reference):
            raise PrimarySourcePipelineError(
                "eligibility rule evidence reference is unresolved"
            )
        invalid_rule_sources = {
            outcome.rule_id
            for outcome in profile.outcomes
            for reference_key in outcome.evidence_reference_keys
            if items_by_reference[reference_key].source_class
            not in _RULE_SOURCE_CLASSES[outcome.rule_id]
        }
        if invalid_rule_sources:
            raise PrimarySourcePipelineError(
                "eligibility rule evidence source is invalid: "
                + ", ".join(sorted(invalid_rule_sources))
            )

        source_order = {
            source_class: ordinal
            for ordinal, source_class in enumerate(SOURCE_CLASS_ORDER)
        }
        ordered_passages = tuple(
            sorted(
                passages,
                key=lambda passage: (
                    source_order[passage.source_class],
                    passage.reference_key,
                ),
            )
        )
        passage_items = tuple(
            items_by_reference[passage.reference_key] for passage in ordered_passages
        )
        metric_snapshots: list[VerifiedMetricSnapshot] = []
        catalyst_snapshots: list[CatalystSnapshot] = []
        risk_snapshots: list[RiskSnapshot] = []
        fact_items: list[EvidenceItem] = []
        fact_reference_keys = [
            fact.reference_key for fact in (*metrics, *catalysts, *risks)
        ]
        if len(set(fact_reference_keys)) != len(fact_reference_keys):
            raise PrimarySourcePipelineError("duplicate normalized fact reference key")
        for metric in metrics:
            if (
                metric.period_start is not None
                and metric.period_end is not None
                and metric.period_start > metric.period_end
            ):
                raise PrimarySourcePipelineError("normalized metric period is invalid")
            if (
                metric.period_end is not None
                and metric.period_end > request.as_of_cutoff.date()
            ):
                raise PrimarySourcePipelineError(
                    "normalized metric period is after cutoff"
                )
            item, support_ids = _fact_item(
                request,
                reference_key=metric.reference_key,
                source_class=metric.source_class,
                item_kind="metric",
                payload={
                    "metric_key": metric.metric_key,
                    "value": metric.value,
                    "unit": metric.unit,
                    "period_start": (
                        metric.period_start.isoformat()
                        if metric.period_start is not None
                        else None
                    ),
                    "period_end": (
                        metric.period_end.isoformat()
                        if metric.period_end is not None
                        else None
                    ),
                    "calculation_method": metric.calculation_method,
                    "formula": metric.formula,
                },
                supporting_passage_keys=metric.supporting_passage_keys,
                items_by_reference=items_by_reference,
            )
            item = replace(
                item,
                filing_period_start=metric.period_start,
                filing_period_end=metric.period_end,
            )
            fact_items.append(item)
            metric_snapshots.append(
                VerifiedMetricSnapshot(
                    snapshot_id=item.evidence_id,
                    metric_key=metric.metric_key,
                    value=metric.value,
                    unit=metric.unit,
                    period_start=metric.period_start,
                    period_end=metric.period_end,
                    calculation_method=metric.calculation_method,
                    formula=metric.formula,
                    supporting_evidence_ids=support_ids,
                )
            )
        for catalyst in catalysts:
            item, support_ids = _fact_item(
                request,
                reference_key=catalyst.reference_key,
                source_class=catalyst.source_class,
                item_kind="catalyst",
                payload={
                    "event": catalyst.event,
                    "program": catalyst.program,
                    "basis": catalyst.basis,
                    "status": catalyst.status,
                    "window_start": catalyst.window_start.isoformat(),
                    "window_end": catalyst.window_end.isoformat(),
                },
                supporting_passage_keys=catalyst.supporting_passage_keys,
                items_by_reference=items_by_reference,
            )
            fact_items.append(item)
            catalyst_snapshots.append(
                CatalystSnapshot(
                    snapshot_id=item.evidence_id,
                    event=catalyst.event,
                    program=catalyst.program,
                    basis=catalyst.basis,
                    status=catalyst.status,
                    window_start=catalyst.window_start,
                    window_end=catalyst.window_end,
                    supporting_evidence_ids=support_ids,
                )
            )
        for risk in risks:
            item, support_ids = _fact_item(
                request,
                reference_key=risk.reference_key,
                source_class=risk.source_class,
                item_kind="risk",
                payload={
                    "title": risk.title,
                    "risk_type": risk.risk_type,
                    "severity": risk.severity,
                    "status": risk.status,
                },
                supporting_passage_keys=risk.supporting_passage_keys,
                items_by_reference=items_by_reference,
            )
            fact_items.append(item)
            risk_snapshots.append(
                RiskSnapshot(
                    snapshot_id=item.evidence_id,
                    title=risk.title,
                    risk_type=risk.risk_type,
                    severity=risk.severity,
                    status=risk.status,
                    supporting_evidence_ids=support_ids,
                )
            )
        item_kind_order = {
            item_kind: ordinal
            for ordinal, item_kind in enumerate(
                ("passage", "metric", "catalyst", "risk")
            )
        }
        items = tuple(
            sorted(
                (*passage_items, *fact_items),
                key=lambda item: (
                    source_order[item.source_class],
                    item_kind_order[item.item_kind],
                    item.evidence_id,
                ),
            )
        )
        proof_requirements = [proof.requirement_id for proof in coverage_proofs]
        if len(set(proof_requirements)) != len(proof_requirements):
            raise PrimarySourcePipelineError("duplicate primary source coverage proof")
        for proof in coverage_proofs:
            expected_source_class = _COVERAGE_SOURCE_CLASS.get(proof.requirement_id)
            if expected_source_class is None:
                raise PrimarySourcePipelineError(
                    "unsupported primary source coverage requirement"
                )
            if proof.source_class != expected_source_class:
                raise PrimarySourcePipelineError(
                    "primary source coverage class mismatch"
                )
            if proof.policy_version != _COVERAGE_POLICY_VERSION[proof.requirement_id]:
                raise PrimarySourcePipelineError(
                    "primary source coverage policy is invalid"
                )
            if proof.state not in {
                "complete",
                "incomplete",
                "indeterminate",
            }:
                raise PrimarySourcePipelineError(
                    "primary source coverage state is invalid"
                )
            if not proof.reason_codes or any(
                not code.strip() for code in proof.reason_codes
            ):
                raise PrimarySourcePipelineError(
                    "primary source coverage reason is required"
                )
            unresolved = set(proof.evidence_reference_keys) - set(items_by_reference)
            if unresolved:
                raise PrimarySourcePipelineError(
                    "primary source coverage evidence is unresolved"
                )
            if any(
                items_by_reference[key].source_class != proof.source_class
                for key in proof.evidence_reference_keys
            ):
                raise PrimarySourcePipelineError(
                    "primary source coverage evidence class mismatch"
                )
            if proof.state == "complete" and any(
                proof.requirement_id not in passages_by_reference[key].coverage_keys
                for key in proof.evidence_reference_keys
            ):
                raise PrimarySourcePipelineError(
                    "primary source coverage evidence lacks requirement"
                )
            if proof.state == "complete" and not proof.evidence_reference_keys:
                raise PrimarySourcePipelineError(
                    "complete primary source coverage requires evidence"
                )
            if (
                proof.requirement_id == "us_regulatory"
                and proof.state == "complete"
                and not _has_regulatory_programme_linkage(
                    passages,
                    tuple(
                        dict.fromkeys(
                            (
                                *profile.active_therapeutic_programs,
                                *regulatory_program_names,
                            )
                        )
                    ),
                    proof.evidence_reference_keys,
                )
            ):
                raise PrimarySourcePipelineError(
                    "regulatory programme linkage is unresolved"
                )
        coverage = frozenset(
            proof.requirement_id
            for proof in coverage_proofs
            if proof.state == "complete"
        )
        outcome_states = {
            outcome.rule_id: outcome.state for outcome in profile.outcomes
        }
        has_defined_catalyst = any(
            catalyst.event.strip()
            and catalyst.program.strip()
            and catalyst.basis in {"clinical", "regulatory"}
            and catalyst.window_start <= catalyst.window_end
            and catalyst.window_end >= request.as_of_cutoff.date()
            for catalyst in catalysts
        )
        eligibility_predicates = {
            "security_identity_verified": (profile.security_identity_verified),
            "us_listing": (
                profile.primary_listing_country == "US"
                and bool(request.primary_listing_exchange.strip())
            ),
            "cik_match": profile.cik_matches_issuer,
            "common_equity": profile.security_type == "common_equity",
            "operating_company": profile.issuer_status == "operating",
            "therapeutics_classification": (
                profile.therapeutics_classification
                in {"therapeutics_biotech", "therapeutics_biopharma"}
            ),
            "active_therapeutic_program": any(
                program.strip() for program in profile.active_therapeutic_programs
            ),
            "defined_clinical_or_regulatory_catalyst": (has_defined_catalyst),
            "required_primary_source_coverage": (
                REQUIRED_PRIMARY_SOURCE_COVERAGE <= coverage
            ),
        }
        expected_pass_values = {
            "security_identity_verified": ("true",),
            "us_listing": (
                "US",
                request.primary_listing_exchange.strip().upper(),
            ),
            "cik_match": (request.cik,),
            "common_equity": (profile.security_type,),
            "operating_company": (profile.issuer_status,),
            "therapeutics_classification": (profile.therapeutics_classification,),
            "active_therapeutic_program": (profile.active_therapeutic_programs),
            "required_primary_source_coverage": tuple(sorted(coverage)),
        }
        inconsistent_outcomes = tuple(
            rule_id
            for rule_id in RULE_IDS
            if (outcome_states[rule_id] == "pass") != eligibility_predicates[rule_id]
        )
        outcomes_by_rule = {outcome.rule_id: outcome for outcome in profile.outcomes}
        inconsistent_values = tuple(
            rule_id
            for rule_id, expected_values in expected_pass_values.items()
            if outcome_states[rule_id] == "pass"
            and outcomes_by_rule[rule_id].normalized_values != expected_values
        )
        if inconsistent_outcomes or inconsistent_values:
            raise PrimarySourcePipelineError(
                "eligibility source outcome conflicts with normalized "
                "evidence: "
                + ", ".join(
                    dict.fromkeys((*inconsistent_outcomes, *inconsistent_values))
                )
            )
        evidence_by_rule = {
            outcome.rule_id: EvidenceReference(
                evidence_id=items_by_reference[
                    outcome.evidence_reference_keys[0]
                ].evidence_id,
                available_at=(
                    _utc(
                        passages_by_reference[
                            outcome.evidence_reference_keys[0]
                        ].available_at,
                        "source availability time",
                    )
                    if passages_by_reference[
                        outcome.evidence_reference_keys[0]
                    ].available_at
                    is not None
                    else _utc(
                        passages_by_reference[
                            outcome.evidence_reference_keys[0]
                        ].publication_at,
                        "publication time",
                    )
                ),
            )
            for outcome in profile.outcomes
            if outcome.evidence_reference_keys
        }
        eligibility_snapshot = SecurityEligibilitySnapshot(
            security_id=request.security_id,
            as_of_cutoff=request.as_of_cutoff,
            issuer_name=request.issuer_name,
            display_symbol=profile.display_symbol,
            security_identity_verified=profile.security_identity_verified,
            primary_listing_country=profile.primary_listing_country,
            primary_listing_exchange=request.primary_listing_exchange,
            cik=request.cik,
            cik_matches_issuer=profile.cik_matches_issuer,
            security_type=profile.security_type,
            issuer_status=profile.issuer_status,
            therapeutics_classification=profile.therapeutics_classification,
            active_therapeutic_programs=profile.active_therapeutic_programs,
            catalysts=tuple(
                CatalystCandidate(
                    event=catalyst.event,
                    program=catalyst.program,
                    basis=catalyst.basis,
                    window_start=catalyst.window_start.isoformat(),
                    window_end=catalyst.window_end.isoformat(),
                )
                for catalyst in catalysts
            ),
            primary_source_coverage=coverage,
            evidence_by_rule=evidence_by_rule,
        )
        missing_coverage = tuple(sorted(REQUIRED_PRIMARY_SOURCE_COVERAGE - coverage))
        missing_coverage_gaps = tuple(
            EvidenceGap(
                code=f"missing_blocking_{coverage_key}_evidence",
                source_class=_COVERAGE_SOURCE_CLASS[coverage_key],
                blocking=True,
                explanation=(
                    f"Blocking {coverage_key} primary evidence is unavailable."
                ),
                requirement_id=coverage_key,
                reason_code="missing_blocking_primary_evidence",
            )
            for coverage_key in missing_coverage
        )
        metric_groups: dict[
            tuple[str, str, date | None, date | None],
            list[NormalizedMetricFact],
        ] = {}
        for metric in metrics:
            metric_groups.setdefault(
                (
                    metric.metric_key,
                    metric.unit,
                    metric.period_start,
                    metric.period_end,
                ),
                [],
            ).append(metric)
        contradictory_metrics = tuple(
            sorted(
                {
                    metric_key
                    for (
                        metric_key,
                        _unit,
                        _period_start,
                        _period_end,
                    ), observations in metric_groups.items()
                    if len({item.value for item in observations}) > 1
                }
            )
        )
        contradiction_gaps = tuple(
            EvidenceGap(
                code=f"contradictory_metric_{metric_key}",
                source_class=sorted(
                    {
                        metric.source_class
                        for metric in metrics
                        if metric.metric_key == metric_key
                    },
                    key=SOURCE_CLASS_ORDER.index,
                )[0],
                blocking=True,
                explanation=(f"Contradictory reported values exist for {metric_key}."),
                requirement_id=f"metric_consistency:{metric_key}",
                reason_code="contradictory_reported_metric",
            )
            for metric_key in contradictory_metrics
        )
        declared_gaps = (*missing_coverage_gaps, *contradiction_gaps)
        incomplete_proof_reasons = tuple(
            reason_code
            for proof in sorted(
                coverage_proofs,
                key=lambda proof: proof.requirement_id,
            )
            if proof.state != "complete"
            for reason_code in proof.reason_codes
        )
        return PrimarySourcePipelineResult(
            eligibility_snapshot=eligibility_snapshot,
            bundle_candidate=EvidenceBundleCandidate(
                security_id=request.security_id,
                as_of_cutoff=request.as_of_cutoff,
                evidence_policy_version=EVIDENCE_POLICY_VERSION,
                freshness_policy_version=FRESHNESS_POLICY_VERSION,
                items=items,
                metrics=tuple(metric_snapshots),
                catalysts=tuple(catalyst_snapshots),
                risks=tuple(risk_snapshots),
                declared_gaps=declared_gaps,
            ),
            reason_codes=(
                (
                    *(
                        f"contradictory_metric_{metric_key}"
                        for metric_key in contradictory_metrics
                    ),
                    *incomplete_proof_reasons,
                    "primary_source_coverage_complete",
                )
                if not missing_coverage
                else (
                    *(
                        f"contradictory_metric_{metric_key}"
                        for metric_key in contradictory_metrics
                    ),
                    *incomplete_proof_reasons,
                    *(f"missing_{coverage_key}" for coverage_key in missing_coverage),
                    "primary_source_coverage_incomplete",
                )
            ),
        )


__all__ = [
    "NormalizedCatalystFact",
    "NormalizedMetricFact",
    "NormalizedRiskFact",
    "PrimaryEvidencePassage",
    "PrimarySourceCoverageProof",
    "PrimarySourcePipeline",
    "PrimarySourcePipelineError",
    "PrimarySourcePipelineResult",
]

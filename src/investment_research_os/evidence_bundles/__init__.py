from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from typing import Callable, Mapping, Protocol
from urllib.parse import urlparse
from uuid import UUID

from investment_research_os.ids import stable_id
from investment_research_os.research_runs import (
    AuthenticatedOperator,
    EligibilityResult,
    ResearchRun,
    ResearchRunNotFound,
    ResearchRunRepository,
    SecurityIdentity,
)


class EvidenceBundleError(ValueError):
    """Raised when evidence cannot produce a valid immutable bundle."""


class EvidenceBundleNotFound(LookupError):
    """Raised when a bundle is absent or outside the operator boundary."""


@dataclass(frozen=True, slots=True)
class EvidencePolicyDefinition:
    version: str
    freshness_policy_version: str
    source_class_order: tuple[str, ...]
    blocking_source_classes: tuple[str, ...]


class EvidencePolicyRegistry(Protocol):
    def resolve(
        self,
        evidence_policy_version: str,
        freshness_policy_version: str,
    ) -> EvidencePolicyDefinition | None: ...


class FixedEvidencePolicyRegistry:
    def __init__(self, policy: EvidencePolicyDefinition | None = None) -> None:
        self._policy = policy or EvidencePolicyDefinition(
            version="biotech-primary-evidence-v1",
            freshness_policy_version="biotech-evidence-freshness-v1",
            source_class_order=(
                "sec",
                "issuer",
                "clinical",
                "regulatory",
                "financing",
            ),
            blocking_source_classes=(
                "sec",
                "issuer",
                "clinical",
                "regulatory",
                "financing",
            ),
        )

    def resolve(
        self,
        evidence_policy_version: str,
        freshness_policy_version: str,
    ) -> EvidencePolicyDefinition | None:
        if (
            evidence_policy_version == self._policy.version
            and freshness_policy_version == self._policy.freshness_policy_version
        ):
            return self._policy
        return None


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    evidence_id: str
    evidence_version_id: str
    provenance_type: str
    item_kind: str
    source_class: str
    source_locator: str
    canonical_url: str
    publication_at: datetime | None
    retrieved_at: datetime
    effective_at: datetime | None
    filing_period_start: date | None
    filing_period_end: date | None
    content_hash: str
    passage_id: str | None
    passage_hash: str | None
    freshness: str


@dataclass(frozen=True, slots=True)
class VerifiedMetricSnapshot:
    snapshot_id: str
    metric_key: str
    value: str
    unit: str
    period_start: date | None
    period_end: date | None
    calculation_method: str
    formula: str | None
    supporting_evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CatalystSnapshot:
    snapshot_id: str
    event: str
    program: str
    basis: str
    status: str
    window_start: date
    window_end: date
    supporting_evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RiskSnapshot:
    snapshot_id: str
    title: str
    risk_type: str
    severity: str
    status: str
    supporting_evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvidenceBundleCandidate:
    security_id: str
    as_of_cutoff: datetime
    evidence_policy_version: str
    freshness_policy_version: str
    items: tuple[EvidenceItem, ...]
    metrics: tuple[VerifiedMetricSnapshot, ...] = ()
    catalysts: tuple[CatalystSnapshot, ...] = ()
    risks: tuple[RiskSnapshot, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceGap:
    code: str
    source_class: str
    blocking: bool
    explanation: str


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    id: str
    operator_id: str
    research_run_id: str
    security_id: str
    security_identity: SecurityIdentity
    as_of_cutoff: datetime
    content_hash: str
    manifest: tuple[EvidenceItem, ...]
    metrics: tuple[VerifiedMetricSnapshot, ...]
    catalysts: tuple[CatalystSnapshot, ...]
    risks: tuple[RiskSnapshot, ...]
    grader_ready: bool
    gaps: tuple[EvidenceGap, ...]
    eligibility: EligibilityResult
    evidence_policy_version: str
    freshness_policy_version: str
    created_at: datetime

    def as_dict(self) -> dict[str, object]:
        return _bundle_wire(self)


class EvidenceBundleSource(Protocol):
    def load(
        self,
        security_id: str,
        as_of_cutoff: datetime,
    ) -> EvidenceBundleCandidate: ...


class EvidenceBundleRepository(Protocol):
    def save(self, bundle: EvidenceBundle) -> EvidenceBundle: ...

    def get(self, operator_id: str, bundle_id: str) -> EvidenceBundle | None: ...

    def get_for_run(
        self,
        operator_id: str,
        research_run_id: str,
    ) -> EvidenceBundle | None: ...


class InMemoryEvidenceBundleRepository:
    def __init__(self) -> None:
        self._bundles: dict[tuple[str, str], EvidenceBundle] = {}
        self._bundle_ids_by_run: dict[tuple[str, str], str] = {}

    def save(self, bundle: EvidenceBundle) -> EvidenceBundle:
        key = (bundle.operator_id, bundle.id)
        existing = self._bundles.get(key)
        if existing is not None:
            if existing != bundle:
                raise EvidenceBundleError("conflicting immutable evidence bundle")
            return existing
        run_key = (bundle.operator_id, bundle.research_run_id)
        existing_bundle_id = self._bundle_ids_by_run.get(run_key)
        if existing_bundle_id is not None and existing_bundle_id != bundle.id:
            raise EvidenceBundleError(
                "research run already has immutable evidence bundle"
            )
        self._bundles[key] = bundle
        self._bundle_ids_by_run[run_key] = bundle.id
        return bundle

    def get(self, operator_id: str, bundle_id: str) -> EvidenceBundle | None:
        return self._bundles.get((operator_id, bundle_id))

    def get_for_run(
        self,
        operator_id: str,
        research_run_id: str,
    ) -> EvidenceBundle | None:
        bundle_id = self._bundle_ids_by_run.get((operator_id, research_run_id))
        if bundle_id is None:
            return None
        return self.get(operator_id, bundle_id)


def _require_uuid(value: str, label: str) -> None:
    try:
        UUID(value)
    except (ValueError, AttributeError) as error:
        raise EvidenceBundleError(f"invalid {label}") from error


def _require_sha256(value: str, label: str) -> None:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise EvidenceBundleError(f"invalid {label}")


def _require_non_empty(value: str, label: str) -> None:
    if not value:
        raise EvidenceBundleError(f"invalid {label}")


def _wire_value(value: object):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {key: _wire_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_wire_value(item) for item in value]
    return value


def _manifest_wire(
    manifest: tuple[EvidenceItem, ...],
    freshness_policy_version: str,
) -> list[dict[str, object]]:
    return [
        {
            "ordinal": ordinal,
            "item_id": item.evidence_id,
            "item_version_id": item.evidence_version_id,
            "item_kind": item.item_kind,
            "source_class": item.source_class,
            "source_locator": item.canonical_url,
            "locator": item.source_locator,
            "content_sha256": item.passage_hash or item.content_hash,
            "published_at": _wire_value(item.publication_at),
            "retrieved_at": _wire_value(item.retrieved_at),
            "effective_at": _wire_value(item.effective_at),
            "filing_period_start": _wire_value(item.filing_period_start),
            "filing_period_end": _wire_value(item.filing_period_end),
            "freshness_state": item.freshness,
            "freshness_reason_code": f"source_{item.freshness}_at_cutoff",
            "freshness_policy_version": freshness_policy_version,
        }
        for ordinal, item in enumerate(manifest, start=1)
    ]


def _metrics_wire(
    metrics: tuple[VerifiedMetricSnapshot, ...],
) -> list[dict[str, object]]:
    return [
        {
            "id": metric.snapshot_id,
            "metric_key": metric.metric_key,
            "value": metric.value,
            "unit": metric.unit,
            "period_start": _wire_value(metric.period_start),
            "period_end": _wire_value(metric.period_end),
            "calculation_method": metric.calculation_method,
            "formula": metric.formula,
            "supporting_evidence_ids": list(metric.supporting_evidence_ids),
        }
        for metric in metrics
    ]


def _catalysts_wire(
    catalysts: tuple[CatalystSnapshot, ...],
) -> list[dict[str, object]]:
    return [
        {
            "id": catalyst.snapshot_id,
            "program": catalyst.program,
            "event": catalyst.event,
            "basis": catalyst.basis,
            "status": catalyst.status,
            "window_start": catalyst.window_start.isoformat(),
            "window_end": catalyst.window_end.isoformat(),
            "supporting_evidence_ids": list(catalyst.supporting_evidence_ids),
        }
        for catalyst in catalysts
    ]


def _risks_wire(risks: tuple[RiskSnapshot, ...]) -> list[dict[str, object]]:
    return [
        {
            "id": risk.snapshot_id,
            "title": risk.title,
            "risk_type": risk.risk_type,
            "severity": risk.severity,
            "status": risk.status,
            "supporting_evidence_ids": list(risk.supporting_evidence_ids),
        }
        for risk in risks
    ]


def _gaps_wire(gaps: tuple[EvidenceGap, ...]) -> list[dict[str, object]]:
    return [
        {
            "gap_id": gap.code,
            "requirement_id": f"{gap.source_class}_primary_evidence",
            "source_class": gap.source_class,
            "reason_code": "missing_blocking_primary_evidence",
            "explanation": gap.explanation,
        }
        for gap in gaps
    ]


def _bundle_wire(bundle: EvidenceBundle) -> dict[str, object]:
    return {
        "contract_version": "evidence_bundle.v1",
        "id": bundle.id,
        "operator_id": bundle.operator_id,
        "research_run_id": bundle.research_run_id,
        "security_id": bundle.security_id,
        "security_identity": _wire_value(asdict(bundle.security_identity)),
        "as_of_cutoff": bundle.as_of_cutoff.isoformat(),
        "bundle_hash": bundle.content_hash,
        "manifest": _manifest_wire(
            bundle.manifest,
            bundle.freshness_policy_version,
        ),
        "verified_metrics": _metrics_wire(bundle.metrics),
        "catalysts": _catalysts_wire(bundle.catalysts),
        "risks": _risks_wire(bundle.risks),
        "eligibility": _wire_value(asdict(bundle.eligibility)),
        "evidence_policy_version": bundle.evidence_policy_version,
        "freshness_policy_version": bundle.freshness_policy_version,
        "grader_ready": bundle.grader_ready,
        "gaps": _gaps_wire(bundle.gaps),
        "created_at": bundle.created_at.isoformat(),
    }


def _canonical_hash(payload: Mapping[str, object]) -> str:
    serialized = json.dumps(
        _wire_value(payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(serialized.encode()).hexdigest()


def _eligibility_hash_payload(eligibility: EligibilityResult) -> dict[str, object]:
    return {
        "policy_version": eligibility.policy_version,
        "eligible": eligibility.eligible,
        "checks": [
            {
                "rule_id": check.rule_id,
                "rule_version": check.rule_version,
                "passed": check.passed,
                "evidence_reference": check.evidence_reference,
                "reason_code": check.reason_code,
                "explanation": check.explanation,
            }
            for check in eligibility.checks
        ],
    }


def _valid_at_cutoff(item: EvidenceItem, cutoff: datetime) -> bool:
    return (
        (item.publication_at is None or item.publication_at <= cutoff)
        and (item.effective_at is None or item.effective_at <= cutoff)
        and (
            item.filing_period_end is None
            or item.filing_period_end <= cutoff.date()
        )
    )


def _blocking_gaps(
    manifest: tuple[EvidenceItem, ...],
    policy: EvidencePolicyDefinition,
) -> tuple[EvidenceGap, ...]:
    available_classes = {item.source_class for item in manifest}
    return tuple(
        EvidenceGap(
            code=f"missing_blocking_{source_class}_evidence",
            source_class=source_class,
            blocking=True,
            explanation=f"Blocking {source_class} primary evidence is unavailable.",
        )
        for source_class in policy.blocking_source_classes
        if source_class not in available_classes
    )


@dataclass(frozen=True, slots=True)
class _PreparedCandidate:
    content_hash: str
    manifest: tuple[EvidenceItem, ...]
    metrics: tuple[VerifiedMetricSnapshot, ...]
    catalysts: tuple[CatalystSnapshot, ...]
    risks: tuple[RiskSnapshot, ...]
    gaps: tuple[EvidenceGap, ...]


def _prepare_candidate(
    run: ResearchRun,
    candidate: EvidenceBundleCandidate,
    policy_registry: EvidencePolicyRegistry,
) -> _PreparedCandidate:
    if candidate.security_id != run.security_id:
        raise EvidenceBundleError("evidence bundle security identity mismatch")
    if candidate.as_of_cutoff != run.as_of_cutoff:
        raise EvidenceBundleError("evidence bundle cutoff mismatch")
    policy = policy_registry.resolve(
        candidate.evidence_policy_version,
        candidate.freshness_policy_version,
    )
    if policy is None:
        raise EvidenceBundleError("evidence bundle policy is unavailable")
    source_class_order = {
        source_class: ordinal
        for ordinal, source_class in enumerate(policy.source_class_order)
    }
    item_kind_order = {
        item_kind: ordinal
        for ordinal, item_kind in enumerate(("passage", "metric", "catalyst", "risk"))
    }
    for item in candidate.items:
        _require_uuid(item.evidence_id, "evidence item identity")
        _require_uuid(item.evidence_version_id, "evidence version identity")
        _require_non_empty(item.source_locator, "evidence locator")
        _require_sha256(item.content_hash, "evidence content hash")
        if item.passage_hash is not None:
            _require_sha256(item.passage_hash, "evidence passage hash")
        if item.provenance_type != "primary_source":
            raise EvidenceBundleError(
                f"{item.provenance_type} cannot enter evidence bundle"
            )
        if item.source_class not in source_class_order:
            raise EvidenceBundleError(
                f"unsupported evidence source class: {item.source_class}"
            )
        if item.item_kind not in item_kind_order:
            raise EvidenceBundleError(
                f"unsupported evidence item kind: {item.item_kind}"
            )
        if urlparse(item.canonical_url).scheme != "https":
            raise EvidenceBundleError("source URL must use HTTPS")
    manifest = tuple(
        sorted(
            (
                item
                for item in candidate.items
                if _valid_at_cutoff(item, run.as_of_cutoff)
            ),
            key=lambda item: (
                source_class_order[item.source_class],
                item_kind_order[item.item_kind],
                item.evidence_id,
                item.evidence_version_id,
            ),
        )
    )
    item_ids = [item.evidence_id for item in manifest]
    version_ids = [item.evidence_version_id for item in manifest]
    if len(set(item_ids)) != len(item_ids) or len(set(version_ids)) != len(
        version_ids
    ):
        raise EvidenceBundleError("duplicate evidence manifest identity")
    if any(
        item.freshness not in {"current", "stale", "indeterminate"}
        for item in manifest
    ):
        raise EvidenceBundleError("invalid evidence freshness state")
    gaps = _blocking_gaps(manifest, policy)
    metrics = tuple(sorted(candidate.metrics, key=lambda item: item.snapshot_id))
    catalysts = tuple(sorted(candidate.catalysts, key=lambda item: item.snapshot_id))
    risks = tuple(sorted(candidate.risks, key=lambda item: item.snapshot_id))
    snapshot_ids = [
        snapshot.snapshot_id for snapshot in (*metrics, *catalysts, *risks)
    ]
    if len(set(snapshot_ids)) != len(snapshot_ids):
        raise EvidenceBundleError("duplicate evidence snapshot identity")
    for metric in metrics:
        _require_uuid(metric.snapshot_id, "verified metric identity")
        _require_non_empty(metric.metric_key, "verified metric key")
        _require_non_empty(metric.unit, "verified metric unit")
        if re.fullmatch(r"-?(?:0|[1-9]\d*)(?:\.\d+)?", metric.value) is None:
            raise EvidenceBundleError(
                "verified metric value must be canonical decimal text"
            )
        if metric.calculation_method not in {"reported", "calculated"}:
            raise EvidenceBundleError("invalid verified metric calculation method")
        if metric.calculation_method == "calculated" and not metric.formula:
            raise EvidenceBundleError("calculated metric requires formula")
        if (
            metric.period_start is not None
            and metric.period_end is not None
            and metric.period_start > metric.period_end
        ):
            raise EvidenceBundleError("invalid verified metric period")
    for catalyst in catalysts:
        _require_uuid(catalyst.snapshot_id, "catalyst identity")
        _require_non_empty(catalyst.program, "catalyst program")
        _require_non_empty(catalyst.event, "catalyst event")
        _require_non_empty(catalyst.status, "catalyst status")
        if catalyst.basis not in {"clinical", "regulatory"}:
            raise EvidenceBundleError("invalid catalyst basis")
        if catalyst.window_start > catalyst.window_end:
            raise EvidenceBundleError("invalid catalyst window")
    for risk in risks:
        _require_uuid(risk.snapshot_id, "risk identity")
        _require_non_empty(risk.title, "risk title")
        _require_non_empty(risk.risk_type, "risk type")
        _require_non_empty(risk.severity, "risk severity")
        _require_non_empty(risk.status, "risk status")
    manifest_kinds = {item.evidence_id: item.item_kind for item in manifest}
    evidence_ids = {
        item.evidence_id for item in manifest if item.item_kind == "passage"
    }
    for snapshot in (*metrics, *catalysts, *risks):
        if (
            not snapshot.supporting_evidence_ids
            or not set(snapshot.supporting_evidence_ids) <= evidence_ids
        ):
            raise EvidenceBundleError("snapshot evidence reference is unresolved")
    for snapshots, expected_kind in (
        (metrics, "metric"),
        (catalysts, "catalyst"),
        (risks, "risk"),
    ):
        if any(
            manifest_kinds.get(snapshot.snapshot_id) != expected_kind
            for snapshot in snapshots
        ):
            raise EvidenceBundleError(
                f"{expected_kind} snapshot lacks matching manifest entry"
            )
    hash_payload = {
        "security_identity": asdict(run.security_identity),
        "as_of_cutoff": run.as_of_cutoff,
        "manifest": _manifest_wire(
            manifest,
            candidate.freshness_policy_version,
        ),
        "verified_metrics": _metrics_wire(metrics),
        "catalysts": _catalysts_wire(catalysts),
        "risks": _risks_wire(risks),
        "grader_ready": not gaps,
        "gaps": _gaps_wire(gaps),
        "eligibility": _eligibility_hash_payload(run.eligibility),
        "evidence_policy_version": candidate.evidence_policy_version,
        "freshness_policy_version": candidate.freshness_policy_version,
    }
    return _PreparedCandidate(
        content_hash=_canonical_hash(hash_payload),
        manifest=manifest,
        metrics=metrics,
        catalysts=catalysts,
        risks=risks,
        gaps=gaps,
    )


class EvidenceBundleWorkflow:
    def __init__(
        self,
        *,
        research_run_repository: ResearchRunRepository,
        bundle_repository: EvidenceBundleRepository,
        evidence_source: EvidenceBundleSource,
        evidence_policy_registry: EvidencePolicyRegistry | None = None,
        clock: Callable[[], datetime],
    ) -> None:
        self._research_run_repository = research_run_repository
        self._bundle_repository = bundle_repository
        self._evidence_source = evidence_source
        self._evidence_policy_registry = (
            evidence_policy_registry or FixedEvidencePolicyRegistry()
        )
        self._clock = clock

    def materialize(
        self,
        operator: AuthenticatedOperator,
        research_run_id: str,
    ) -> EvidenceBundle:
        existing = self._bundle_repository.get_for_run(operator.id, research_run_id)
        if existing is not None:
            return existing

        run = self._research_run_repository.get(operator.id, research_run_id)
        if run is None:
            raise ResearchRunNotFound("research run not found")
        if not run.eligibility.eligible:
            raise EvidenceBundleError("evidence bundle requires eligible research run")

        candidate = self._evidence_source.load(run.security_id, run.as_of_cutoff)
        prepared = _prepare_candidate(
            run,
            candidate,
            self._evidence_policy_registry,
        )
        return self._bundle_repository.save(
            self._build_bundle(operator, run, candidate, prepared, self._now())
        )

    def materialize_correction(
        self,
        operator: AuthenticatedOperator,
        previous_bundle_id: str,
    ) -> EvidenceBundle:
        previous = self.get(operator, previous_bundle_id)
        previous_run = self._research_run_repository.get(
            operator.id,
            previous.research_run_id,
        )
        if previous_run is None:
            raise ResearchRunNotFound("research run not found")
        candidate = self._evidence_source.load(
            previous_run.security_id,
            previous_run.as_of_cutoff,
        )
        prepared = _prepare_candidate(
            previous_run,
            candidate,
            self._evidence_policy_registry,
        )
        if prepared.content_hash == previous.content_hash:
            return previous

        created_at = self._now()
        revision_key = _canonical_hash(
            {
                "previous_research_run_id": previous_run.id,
                "evidence_bundle_hash": prepared.content_hash,
            }
        )
        corrected_run = replace(
            previous_run,
            id=stable_id(
                operator.id,
                "committee-research-run-revision",
                revision_key,
            ),
            idempotency_key=revision_key,
            created_at=created_at,
        )
        corrected_run = self._research_run_repository.save(corrected_run)
        existing = self._bundle_repository.get_for_run(
            operator.id,
            corrected_run.id,
        )
        if existing is not None:
            return existing
        return self._bundle_repository.save(
            self._build_bundle(
                operator,
                corrected_run,
                candidate,
                prepared,
                created_at,
            )
        )

    def _now(self) -> datetime:
        created_at = self._clock()
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise RuntimeError("bundle clock must return timezone-aware timestamp")
        return created_at

    @staticmethod
    def _build_bundle(
        operator: AuthenticatedOperator,
        run: ResearchRun,
        candidate: EvidenceBundleCandidate,
        prepared: _PreparedCandidate,
        created_at: datetime,
    ) -> EvidenceBundle:
        return EvidenceBundle(
            id=stable_id(
                operator.id,
                "evidence-bundle",
                prepared.content_hash,
            ),
            operator_id=operator.id,
            research_run_id=run.id,
            security_id=run.security_id,
            security_identity=run.security_identity,
            as_of_cutoff=run.as_of_cutoff,
            content_hash=prepared.content_hash,
            manifest=prepared.manifest,
            metrics=prepared.metrics,
            catalysts=prepared.catalysts,
            risks=prepared.risks,
            grader_ready=not prepared.gaps,
            gaps=prepared.gaps,
            eligibility=run.eligibility,
            evidence_policy_version=candidate.evidence_policy_version,
            freshness_policy_version=candidate.freshness_policy_version,
            created_at=created_at,
        )

    def get(
        self,
        operator: AuthenticatedOperator,
        bundle_id: str,
    ) -> EvidenceBundle:
        bundle = self._bundle_repository.get(operator.id, bundle_id)
        if bundle is None:
            raise EvidenceBundleNotFound("evidence bundle not found")
        return bundle


__all__ = [
    "CatalystSnapshot",
    "EvidenceBundle",
    "EvidenceBundleCandidate",
    "EvidenceBundleError",
    "EvidenceGap",
    "EvidenceBundleNotFound",
    "EvidenceBundleWorkflow",
    "EvidenceItem",
    "EvidencePolicyDefinition",
    "FixedEvidencePolicyRegistry",
    "InMemoryEvidenceBundleRepository",
    "RiskSnapshot",
    "VerifiedMetricSnapshot",
]

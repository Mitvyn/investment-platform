from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from investment_research_os.evidence_bundles import EvidenceBundleRepository
from investment_research_os.grader_executions import (
    GraderExecution,
    GraderExecutionRequest,
    GraderExecutionWorkflow,
    GraderOpinion,
)
from investment_research_os.ids import stable_id
from investment_research_os.research_runs import AuthenticatedOperator


class ResearchCommitteeError(ValueError):
    """Raised when committee orchestration violates locked workflow contract."""


@dataclass(frozen=True, slots=True)
class CommitteeGraderDefinition:
    grader_id: str
    grader_version: str
    owned_decision_question: str
    required_when_eligible: bool = True


MVP_GRADER_ROSTER = (
    CommitteeGraderDefinition(
        "moonshot",
        "moonshot-grader-v1",
        "Is the opportunity meaningfully asymmetric?",
    ),
    CommitteeGraderDefinition(
        "catalyst",
        "catalyst-grader-v1",
        "What event resolves uncertainty, when, and with what outcomes?",
    ),
    CommitteeGraderDefinition(
        "biotech",
        "biotech-grader-v1",
        "Is the scientific and clinical evidence credible?",
    ),
    CommitteeGraderDefinition(
        "risk_dilution",
        "risk_dilution-grader-v1",
        "Can shareholders survive financially until the thesis resolves?",
    ),
    CommitteeGraderDefinition(
        "valuation",
        "valuation-grader-v1",
        "What outcomes and assumptions justify the current or implied value?",
    ),
)


@dataclass(frozen=True, slots=True)
class CommitteeGraderResult:
    grader_id: str
    grader_version: str
    grader_contract_version: str
    output_schema_version: str
    eligibility_rule_version: str
    owned_decision_question: str
    required: bool
    eligible: bool
    execution_state: str
    evidence_bundle_id: str
    evidence_bundle_hash: str
    opinion: GraderOpinion | None
    execution: GraderExecution | None
    reason_code: str | None
    persisted_at: datetime

    @property
    def stance(self) -> str | None:
        if self.execution_state != "accepted" or self.opinion is None:
            return None
        return self.opinion.grader_stance

    def as_dict(self) -> dict[str, object]:
        execution_contract = (
            self.execution.as_dict() if self.execution is not None else None
        )
        opinion = (
            _committee_opinion(
                self.opinion,
                self.execution,
                self.persisted_at,
            )
            if self.opinion is not None
            else None
        )
        not_eligible = None
        not_executed = None
        failure = None
        execution_id = None
        if self.execution_state == "not_eligible":
            not_eligible = {
                "eligibility_rule_version": self.eligibility_rule_version,
                "eligibility_inputs": {"workflow_eligible": False},
                "reason_code": self.reason_code,
                "reason": "Versioned grader eligibility rule does not apply.",
                "evaluated_at": self.persisted_at.isoformat(),
            }
        elif self.execution_state == "not_executed":
            if execution_contract is None:
                raise ResearchCommitteeError("not executed detail missing")
            not_executed = execution_contract["not_executed"]
        elif self.execution_state == "failed":
            if execution_contract is None:
                raise ResearchCommitteeError("failure detail missing")
            execution_id = self.execution.execution_id
            failure = execution_contract["failure"]
        else:
            if self.execution is None:
                raise ResearchCommitteeError("execution detail missing")
            execution_id = self.execution.execution_id
        return {
            "contract_version": "committee_grader_result.v1",
            "grader_id": self.grader_id,
            "grader_version": self.grader_version,
            "grader_contract_version": self.grader_contract_version,
            "output_schema_version": self.output_schema_version,
            "required": self.required,
            "evidence_bundle_id": self.evidence_bundle_id,
            "evidence_bundle_hash": self.evidence_bundle_hash,
            "execution_id": execution_id,
            "execution_state": self.execution_state,
            "opinion": opinion,
            "not_eligible": not_eligible,
            "not_executed": not_executed,
            "failure": failure,
            "persisted_at": self.persisted_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class CommitteeAccounting:
    eligible_count: int
    accepted_count: int
    abstained_count: int
    not_eligible_count: int
    failed_count: int
    not_executed_count: int
    supports_count: int
    mixed_count: int
    challenges_count: int


@dataclass(frozen=True, slots=True)
class ResearchCommitteeResult:
    committee_id: str
    committee_key: str
    operator_id: str
    research_run_id: str
    security_id: str
    evidence_bundle_id: str
    evidence_bundle_hash: str
    question_type_id: str
    question_type_version: str
    workflow_config_version: str
    proposition_id: str
    proposition_version: str
    rendered_proposition_text: str
    grader_results: tuple[CommitteeGraderResult, ...]
    status: str
    accounting: CommitteeAccounting
    created_at: datetime

    def as_dict(self) -> dict[str, object]:
        stance_matrix = [
            {
                "grader_id": item.grader_id,
                "opinion_id": item.opinion.opinion_id,
                "stance": item.opinion.grader_stance,
                "stance_rationale": item.opinion.stance_rationale,
            }
            for item in self.grader_results
            if item.execution_state == "accepted"
            and item.opinion is not None
            and item.opinion.grader_stance is not None
        ]
        return {
            "contract_version": "committee_state.v1",
            "research_run_id": self.research_run_id,
            "evidence_bundle_id": self.evidence_bundle_id,
            "evidence_bundle_hash": self.evidence_bundle_hash,
            "workflow_config_version": self.workflow_config_version,
            "proposition_id": self.proposition_id,
            "proposition_version": self.proposition_version,
            "rendered_proposition_text": self.rendered_proposition_text,
            "committee_status": self.status,
            "accounting": {
                "eligible_count": self.accounting.eligible_count,
                "accepted_count": self.accounting.accepted_count,
                "abstained_count": self.accounting.abstained_count,
                "not_eligible_count": self.accounting.not_eligible_count,
                "failed_count": self.accounting.failed_count,
                "not_executed_count": self.accounting.not_executed_count,
            },
            "stance_counts": {
                "supports": self.accounting.supports_count,
                "mixed": self.accounting.mixed_count,
                "challenges": self.accounting.challenges_count,
            },
            "stance_matrix": stance_matrix,
            "grader_results": [item.as_dict() for item in self.grader_results],
            "derived_at": self.created_at.isoformat(),
        }


class ResearchCommitteeRepository(Protocol):
    def begin_committee(
        self,
        result: ResearchCommitteeResult,
    ) -> ResearchCommitteeResult: ...

    def save_grader_state(
        self,
        committee: ResearchCommitteeResult,
        result: CommitteeGraderResult,
    ) -> CommitteeGraderResult: ...

    def finalize_committee(
        self,
        result: ResearchCommitteeResult,
    ) -> ResearchCommitteeResult: ...

    def get(
        self,
        operator_id: str,
        committee_key: str,
    ) -> ResearchCommitteeResult | None: ...

    def get_by_id(
        self,
        operator_id: str,
        committee_id: str,
    ) -> ResearchCommitteeResult | None: ...


class InMemoryResearchCommitteeRepository:
    def __init__(self) -> None:
        self._grader_states: dict[tuple[str, str, str], CommitteeGraderResult] = {}
        self._committees: dict[tuple[str, str], ResearchCommitteeResult] = {}
        self._drafts: dict[tuple[str, str], ResearchCommitteeResult] = {}
        self._persistence_order: list[str] = []

    @property
    def persistence_order(self) -> tuple[str, ...]:
        return tuple(self._persistence_order)

    def begin_committee(
        self,
        result: ResearchCommitteeResult,
    ) -> ResearchCommitteeResult:
        key = (result.operator_id, result.committee_key)
        existing = self._committees.get(key) or self._drafts.get(key)
        if existing is not None:
            if existing != result:
                raise ResearchCommitteeError("conflicting immutable committee draft")
            return existing
        self._drafts[key] = result
        self._persistence_order.append("committee_draft")
        return result

    def save_grader_state(
        self,
        committee: ResearchCommitteeResult,
        result: CommitteeGraderResult,
    ) -> CommitteeGraderResult:
        draft_key = (committee.operator_id, committee.committee_key)
        if self._drafts.get(draft_key) != committee:
            raise ResearchCommitteeError(
                "committee draft must persist before grader state"
            )
        key = (
            committee.operator_id,
            committee.committee_key,
            result.grader_id,
        )
        existing = self._grader_states.get(key)
        if existing is not None:
            if existing != result:
                raise ResearchCommitteeError(
                    "conflicting immutable committee grader state"
                )
            return existing
        self._grader_states[key] = result
        self._persistence_order.append(result.grader_id)
        return result

    def finalize_committee(
        self,
        result: ResearchCommitteeResult,
    ) -> ResearchCommitteeResult:
        key = (result.operator_id, result.committee_key)
        draft = self._drafts.get(key)
        if draft is None or draft != result:
            raise ResearchCommitteeError(
                "committee draft must persist before grader states"
            )
        expected_ids = {item.grader_id for item in MVP_GRADER_ROSTER}
        persisted_ids = {
            grader_id
            for operator_id, committee_key, grader_id in self._grader_states
            if operator_id == result.operator_id
            and committee_key == result.committee_key
        }
        if persisted_ids != expected_ids:
            raise ResearchCommitteeError(
                "all terminal grader states must persist before committee"
            )
        existing = self._committees.get(key)
        if existing is not None:
            if existing != result:
                raise ResearchCommitteeError("conflicting immutable committee")
            return existing
        self._committees[key] = result
        self._persistence_order.append("committee")
        return result

    def get(
        self,
        operator_id: str,
        committee_key: str,
    ) -> ResearchCommitteeResult | None:
        return self._committees.get((operator_id, committee_key))

    def get_by_id(
        self,
        operator_id: str,
        committee_id: str,
    ) -> ResearchCommitteeResult | None:
        return next(
            (
                result
                for (owner_id, _), result in self._committees.items()
                if owner_id == operator_id and result.committee_id == committee_id
            ),
            None,
        )


class ResearchCommitteeWorkflow:
    def __init__(
        self,
        *,
        grader_workflow: GraderExecutionWorkflow,
        evidence_bundle_repository: EvidenceBundleRepository,
        repository: ResearchCommitteeRepository,
        clock: Callable[[], datetime],
    ) -> None:
        self._grader_workflow = grader_workflow
        self._evidence_bundle_repository = evidence_bundle_repository
        self._repository = repository
        self._clock = clock

    def execute(
        self,
        operator: AuthenticatedOperator,
        requests: tuple[GraderExecutionRequest, ...],
    ) -> ResearchCommitteeResult:
        ordered_requests = _validate_and_order_requests(requests)
        bundle = self._evidence_bundle_repository.get(
            operator.id,
            ordered_requests[0].evidence_bundle_id,
        )
        if bundle is None:
            raise ResearchCommitteeError("evidence bundle not found")
        committee_key = _committee_key(
            operator.id,
            ordered_requests,
            bundle.content_hash,
        )
        existing = self._repository.get(operator.id, committee_key)
        if existing is not None:
            return existing
        executions_by_grader = {
            request.grader.grader_id: self._grader_workflow.execute(
                operator,
                request,
            )
            for request in ordered_requests
            if request.grader.eligible
        }
        persisted_at = self._clock()
        results: tuple[CommitteeGraderResult, ...] = tuple(
            _committee_grader_result(
                request,
                executions_by_grader.get(request.grader.grader_id),
                bundle.id,
                bundle.content_hash,
                persisted_at,
            )
            for request in ordered_requests
        )
        created_at = self._clock()
        if created_at <= persisted_at:
            raise ResearchCommitteeError(
                "committee derivation must follow grader persistence"
            )
        accounting = _derive_accounting(results)
        status = _derive_status(results, accounting)
        committee = ResearchCommitteeResult(
            committee_id=stable_id(
                operator.id,
                "research-committee",
                committee_key,
            ),
            committee_key=committee_key,
            operator_id=operator.id,
            research_run_id=bundle.research_run_id,
            security_id=bundle.security_id,
            evidence_bundle_id=bundle.id,
            evidence_bundle_hash=bundle.content_hash,
            question_type_id=ordered_requests[0].question_type_id,
            question_type_version=ordered_requests[0].question_type_version,
            workflow_config_version=(ordered_requests[0].workflow_config_version),
            proposition_id=ordered_requests[0].proposition_id,
            proposition_version=ordered_requests[0].proposition_version,
            rendered_proposition_text=(ordered_requests[0].rendered_proposition),
            grader_results=results,
            status=status,
            accounting=accounting,
            created_at=created_at,
        )
        self._repository.begin_committee(committee)
        for result in results:
            self._repository.save_grader_state(
                committee,
                result,
            )
        return self._repository.finalize_committee(committee)


def _committee_grader_result(
    request: GraderExecutionRequest,
    execution: GraderExecution | None,
    evidence_bundle_id: str,
    evidence_bundle_hash: str,
    persisted_at: datetime,
) -> CommitteeGraderResult:
    if execution is None:
        return CommitteeGraderResult(
            grader_id=request.grader.grader_id,
            grader_version=request.grader.grader_version,
            grader_contract_version=(request.grader.grader_contract_version),
            output_schema_version=request.grader.output_schema_version,
            eligibility_rule_version=(request.grader.eligibility_rule_version),
            owned_decision_question=request.grader.owned_decision_question,
            required=request.grader.required,
            eligible=False,
            execution_state="not_eligible",
            evidence_bundle_id=evidence_bundle_id,
            evidence_bundle_hash=evidence_bundle_hash,
            opinion=None,
            execution=None,
            reason_code="grader_not_eligible",
            persisted_at=persisted_at,
        )
    return CommitteeGraderResult(
        grader_id=execution.grader_id,
        grader_version=execution.grader_version,
        grader_contract_version=request.grader.grader_contract_version,
        output_schema_version=request.grader.output_schema_version,
        eligibility_rule_version=request.grader.eligibility_rule_version,
        owned_decision_question=request.grader.owned_decision_question,
        required=request.grader.required,
        eligible=True,
        execution_state=execution.execution_state,
        evidence_bundle_id=execution.evidence_bundle_id,
        evidence_bundle_hash=execution.bundle_hash,
        opinion=execution.opinion,
        execution=execution,
        reason_code=(
            execution.blocking_reasons[0] if execution.blocking_reasons else None
        ),
        persisted_at=persisted_at,
    )


def _committee_opinion(
    opinion: GraderOpinion,
    execution: GraderExecution | None,
    created_at: datetime,
) -> dict[str, object]:
    if execution is None or execution.request is None:
        raise ResearchCommitteeError("opinion execution metadata missing")
    return {
        "opinion_id": opinion.opinion_id,
        "owned_decision_question": opinion.owned_decision_question,
        "stance": opinion.grader_stance,
        "confidence": opinion.confidence,
        "summary": opinion.summary,
        "material_claims": [
            {
                "claim_id": claim.claim_id,
                "claim": claim.claim,
                "materiality": claim.materiality,
                "evidence_ids": list(claim.evidence_ids),
            }
            for claim in opinion.material_claims
        ],
        "assumptions": list(opinion.assumptions),
        "contradicting_evidence": [
            {
                "evidence_id": item.evidence_id,
                "explanation": item.explanation,
            }
            for item in opinion.contradicting_evidence
        ],
        "evidence_gaps": [
            {
                "gap_id": item.gap_id,
                "description": item.description,
                "required_evidence": item.required_evidence,
            }
            for item in opinion.evidence_gaps
        ],
        "invalidation_signals": list(opinion.invalidation_signals),
        "proposition": {
            "proposition_id": opinion.proposition_id,
            "proposition_version": opinion.proposition_version,
            "rendered_proposition_text": opinion.rendered_proposition_text,
            "grader_stance": opinion.grader_stance,
            "stance_rationale": (
                opinion.stance_rationale
                if opinion.execution_state == "accepted"
                else None
            ),
        },
        "domain_payload": dict(opinion.domain_payload),
        "abstention": (opinion.abstention.as_dict() if opinion.abstention else None),
        "execution_metadata": {
            "execution_id": execution.execution_id,
            "grader_execution_contract_version": "grader_execution.v1",
            "prompt_version": execution.prompt_version,
            "model_config_id": execution.request.model.config_id,
            "provider": execution.request.model.provider,
            "model": execution.request.model.model,
            "attempt_count": len(execution.attempts),
        },
        "created_at": created_at.isoformat(),
    }


def _validate_and_order_requests(
    requests: Iterable[GraderExecutionRequest],
) -> tuple[GraderExecutionRequest, ...]:
    requests_by_id: dict[str, GraderExecutionRequest] = {}
    for request in requests:
        grader_id = request.grader.grader_id
        if grader_id in requests_by_id:
            raise ResearchCommitteeError("duplicate committee grader")
        requests_by_id[grader_id] = request
    roster_ids = tuple(item.grader_id for item in MVP_GRADER_ROSTER)
    if set(requests_by_id) != set(roster_ids):
        raise ResearchCommitteeError("committee roster must contain five graders")
    ordered = tuple(requests_by_id[item] for item in roster_ids)
    reference = ordered[0]
    shared_fields = (
        "evidence_bundle_id",
        "question_type_id",
        "question_type_version",
        "workflow_config_version",
        "proposition_id",
        "proposition_version",
        "rendered_proposition",
    )
    for request, definition in zip(ordered, MVP_GRADER_ROSTER, strict=True):
        if (
            request.grader.grader_version != definition.grader_version
            or request.grader.owned_decision_question
            != definition.owned_decision_question
            or request.grader.required != definition.required_when_eligible
        ):
            raise ResearchCommitteeError("committee grader definition mismatch")
        if any(
            getattr(request, field) != getattr(reference, field)
            for field in shared_fields
        ):
            raise ResearchCommitteeError("committee input identity mismatch")
    return ordered


def _committee_key(
    operator_id: str,
    requests: tuple[GraderExecutionRequest, ...],
    bundle_hash: str,
) -> str:
    payload = {
        "operator_id": operator_id,
        "bundle_id": requests[0].evidence_bundle_id,
        "bundle_hash": bundle_hash,
        "question_type_id": requests[0].question_type_id,
        "question_type_version": requests[0].question_type_version,
        "workflow_config_version": requests[0].workflow_config_version,
        "proposition_id": requests[0].proposition_id,
        "proposition_version": requests[0].proposition_version,
        "executions": [
            {
                "grader_id": request.grader.grader_id,
                "grader_version": request.grader.grader_version,
                "prompt_version": request.prompt.prompt_version,
                "model_config_version": request.model.config_version,
            }
            for request in requests
        ],
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _derive_accounting(
    results: tuple[CommitteeGraderResult, ...],
) -> CommitteeAccounting:
    states = [item.execution_state for item in results]
    stances = [item.stance for item in results if item.stance is not None]
    return CommitteeAccounting(
        eligible_count=sum(item.eligible for item in results),
        accepted_count=states.count("accepted"),
        abstained_count=states.count("abstained"),
        not_eligible_count=states.count("not_eligible"),
        failed_count=states.count("failed"),
        not_executed_count=states.count("not_executed"),
        supports_count=stances.count("supports"),
        mixed_count=stances.count("mixed"),
        challenges_count=stances.count("challenges"),
    )


def _derive_status(
    results: tuple[CommitteeGraderResult, ...],
    accounting: CommitteeAccounting,
) -> str:
    if any(
        item.required and item.eligible and item.execution_state == "failed"
        for item in results
    ):
        return "incomplete_required_grader_failed"
    if accounting.eligible_count == 0 or accounting.not_executed_count:
        return "insufficient_accepted_opinions"
    if accounting.abstained_count:
        return "complete_with_abstentions"
    if accounting.accepted_count == accounting.eligible_count:
        return "complete"
    return "insufficient_accepted_opinions"


__all__ = [
    "MVP_GRADER_ROSTER",
    "CommitteeAccounting",
    "CommitteeGraderDefinition",
    "CommitteeGraderResult",
    "InMemoryResearchCommitteeRepository",
    "ResearchCommitteeError",
    "ResearchCommitteeRepository",
    "ResearchCommitteeResult",
    "ResearchCommitteeWorkflow",
]

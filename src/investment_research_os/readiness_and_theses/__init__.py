from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable, Protocol

from investment_research_os.committee_memos import (
    CommitteeMemo,
    CommitteeMemoRepository,
)
from investment_research_os.evidence_bundles import EvidenceBundleRepository
from investment_research_os.ids import stable_id
from investment_research_os.research_committees import (
    ResearchCommitteeRepository,
    ResearchCommitteeResult,
)
from investment_research_os.research_runs import (
    AuthenticatedOperator,
    DEFAULT_WORKFLOW_CONFIG_REGISTRY,
    PERSONAL_RESEARCH_THESIS_CONTRACT_ID,
    THESIS_CONTRACT_ID,
)
from investment_research_os.valuation_snapshots import (
    PERSONAL_RESEARCH_VALUATION_CONTRACT,
    ValuationSnapshot,
    ValuationSnapshotRepository,
)


class ReadinessAndThesisError(ValueError):
    """Raised when readiness or immutable thesis policy is violated."""


@dataclass(frozen=True, slots=True)
class ReadinessRequest:
    committee_id: str
    gate_policy_version: str


@dataclass(frozen=True, slots=True)
class ReadinessCheck:
    check_id: str
    check_version: str
    reason_code: str
    explanation: str
    reference_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "check_id": self.check_id,
            "check_version": self.check_version,
            "reason_code": self.reason_code,
            "explanation": self.explanation,
            "reference_ids": list(self.reference_ids),
        }


@dataclass(frozen=True, slots=True)
class ReadinessBlockingReason:
    reason_code: str
    check_id: str
    explanation: str

    def as_dict(self) -> dict[str, object]:
        return {
            "reason_code": self.reason_code,
            "check_id": self.check_id,
            "explanation": self.explanation,
        }


@dataclass(frozen=True, slots=True)
class RequiredNextEvidence:
    requirement_id: str
    description: str
    affected_check_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "requirement_id": self.requirement_id,
            "description": self.description,
            "affected_check_ids": list(self.affected_check_ids),
        }


@dataclass(frozen=True, slots=True)
class ReadinessGateResult:
    readiness_gate_result_id: str
    operator_id: str
    security_id: str
    thesis_contract_id: str
    research_run_id: str
    evidence_bundle_id: str
    evidence_bundle_hash: str
    validated_grader_opinion_ids: tuple[str, ...]
    committee_result_id: str
    committee_memo_id: str
    committee_status: str
    requested_disposition: str
    final_disposition: str
    readiness_status: str
    gate_policy_version: str
    passed_checks: tuple[ReadinessCheck, ...]
    failed_checks: tuple[ReadinessCheck, ...]
    blocking_reasons: tuple[ReadinessBlockingReason, ...]
    required_next_evidence: tuple[RequiredNextEvidence, ...]
    evaluated_at: datetime

    def as_dict(self) -> dict[str, object]:
        return {
            "contract_version": "readiness_gate_result.v1",
            "readiness_gate_result_id": self.readiness_gate_result_id,
            "operator_id": self.operator_id,
            "security_id": self.security_id,
            "thesis_contract_id": self.thesis_contract_id,
            "research_run_id": self.research_run_id,
            "evidence_bundle_id": self.evidence_bundle_id,
            "evidence_bundle_hash": self.evidence_bundle_hash,
            "validated_grader_opinion_ids": list(
                self.validated_grader_opinion_ids
            ),
            "committee_result_id": self.committee_result_id,
            "committee_memo_id": self.committee_memo_id,
            "committee_status": self.committee_status,
            "requested_disposition": self.requested_disposition,
            "final_disposition": self.final_disposition,
            "readiness_status": self.readiness_status,
            "gate_policy_version": self.gate_policy_version,
            "passed_checks": [item.as_dict() for item in self.passed_checks],
            "failed_checks": [item.as_dict() for item in self.failed_checks],
            "blocking_reasons": [
                item.as_dict() for item in self.blocking_reasons
            ],
            "required_next_evidence": [
                item.as_dict() for item in self.required_next_evidence
            ],
            "evaluated_at": self.evaluated_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class ThesisContent:
    core_thesis_statement_ids: tuple[str, ...]
    unresolved_disagreement_ids: tuple[str, ...]
    invalidation_statement_ids: tuple[str, ...]
    evidence_gap_statement_ids: tuple[str, ...]
    review_trigger_statement_id: str

    def as_dict(self) -> dict[str, object]:
        return {
            "core_thesis_statement_ids": list(
                self.core_thesis_statement_ids
            ),
            "unresolved_disagreement_ids": list(
                self.unresolved_disagreement_ids
            ),
            "invalidation_statement_ids": list(
                self.invalidation_statement_ids
            ),
            "evidence_gap_statement_ids": list(
                self.evidence_gap_statement_ids
            ),
            "review_trigger_statement_id": self.review_trigger_statement_id,
        }


@dataclass(frozen=True, slots=True)
class ThesisVersion:
    thesis_version_id: str
    thesis_status: str
    operator_id: str
    security_id: str
    thesis_contract_id: str
    previous_canonical_thesis_version_id: str | None
    based_on_thesis_version_id: str | None
    research_run_id: str
    evidence_bundle_id: str
    evidence_bundle_hash: str
    question_type_version: str
    workflow_config_version: str
    proposition_id: str
    proposition_version: str
    validated_grader_opinion_ids: tuple[str, ...]
    committee_result_id: str
    committee_memo_id: str
    committee_status: str
    readiness_gate_result_id: str
    readiness_gate_policy_version: str
    requested_disposition: str
    final_disposition: str
    content: ThesisContent
    created_at: datetime

    def as_dict(self) -> dict[str, object]:
        return {
            "contract_version": "thesis_version.v1",
            "thesis_version_id": self.thesis_version_id,
            "thesis_status": self.thesis_status,
            "operator_id": self.operator_id,
            "security_id": self.security_id,
            "thesis_contract_id": self.thesis_contract_id,
            "previous_canonical_thesis_version_id": (
                self.previous_canonical_thesis_version_id
            ),
            "based_on_thesis_version_id": self.based_on_thesis_version_id,
            "research_run_id": self.research_run_id,
            "evidence_bundle_id": self.evidence_bundle_id,
            "evidence_bundle_hash": self.evidence_bundle_hash,
            "question_type_version": self.question_type_version,
            "workflow_config_version": self.workflow_config_version,
            "proposition_id": self.proposition_id,
            "proposition_version": self.proposition_version,
            "validated_grader_opinion_ids": list(
                self.validated_grader_opinion_ids
            ),
            "committee_result_id": self.committee_result_id,
            "committee_memo_id": self.committee_memo_id,
            "committee_status": self.committee_status,
            "readiness_gate_result_id": self.readiness_gate_result_id,
            "readiness_gate_policy_version": (
                self.readiness_gate_policy_version
            ),
            "requested_disposition": self.requested_disposition,
            "final_disposition": self.final_disposition,
            "content": self.content.as_dict(),
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class ThesisCreationResult:
    thesis_creation_result_id: str
    operator_id: str
    security_id: str
    thesis_contract_id: str
    research_run_id: str
    committee_result_id: str
    readiness_gate_result_id: str
    committee_status: str
    creation_outcome: str
    thesis_version_id: str | None
    reason_code: str
    created_at: datetime

    def as_dict(self) -> dict[str, object]:
        return {
            "contract_version": "thesis_creation_result.v1",
            "thesis_creation_result_id": self.thesis_creation_result_id,
            "operator_id": self.operator_id,
            "security_id": self.security_id,
            "thesis_contract_id": self.thesis_contract_id,
            "research_run_id": self.research_run_id,
            "committee_result_id": self.committee_result_id,
            "readiness_gate_result_id": self.readiness_gate_result_id,
            "committee_status": self.committee_status,
            "creation_outcome": self.creation_outcome,
            "thesis_version_id": self.thesis_version_id,
            "reason_code": self.reason_code,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class ThesisChain:
    operator_id: str
    security_id: str
    thesis_contract_id: str
    active_canonical_thesis_version_id: str | None
    canonical_versions: tuple[ThesisVersion, ...]
    provisional_branches: tuple[ThesisVersion, ...]
    generated_at: datetime

    def as_dict(self) -> dict[str, object]:
        return {
            "contract_version": "thesis_chain.v1",
            "operator_id": self.operator_id,
            "security_id": self.security_id,
            "thesis_contract_id": self.thesis_contract_id,
            "active_canonical_thesis_version_id": (
                self.active_canonical_thesis_version_id
            ),
            "canonical_versions": [
                item.as_dict() for item in self.canonical_versions
            ],
            "provisional_branches": [
                item.as_dict() for item in self.provisional_branches
            ],
            "generated_at": self.generated_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class ReadinessAndThesisResult:
    readiness: ReadinessGateResult
    thesis_creation: ThesisCreationResult
    thesis: ThesisVersion | None


class ReadinessAndThesisRepository(Protocol):
    def get_for_run(
        self,
        operator_id: str,
        research_run_id: str,
    ) -> ReadinessAndThesisResult | None: ...

    def get_readiness_by_id(
        self,
        operator_id: str,
        readiness_gate_result_id: str,
    ) -> ReadinessGateResult | None: ...

    def get_thesis_by_id(
        self,
        operator_id: str,
        thesis_version_id: str,
    ) -> ThesisVersion | None: ...

    def get_chain(
        self,
        operator_id: str,
        security_id: str,
        thesis_contract_id: str,
    ) -> ThesisChain: ...

    def save(
        self,
        result: ReadinessAndThesisResult,
    ) -> ReadinessAndThesisResult: ...


class InMemoryReadinessAndThesisRepository:
    def __init__(self) -> None:
        self._results: dict[
            tuple[str, str], ReadinessAndThesisResult
        ] = {}
        self._chains: dict[tuple[str, str, str], ThesisChain] = {}

    def get_for_run(
        self,
        operator_id: str,
        research_run_id: str,
    ) -> ReadinessAndThesisResult | None:
        return self._results.get((operator_id, research_run_id))

    def get_readiness_by_id(
        self,
        operator_id: str,
        readiness_gate_result_id: str,
    ) -> ReadinessGateResult | None:
        return next(
            (
                item.readiness
                for (owner_id, _), item in self._results.items()
                if owner_id == operator_id
                and item.readiness.readiness_gate_result_id
                == readiness_gate_result_id
            ),
            None,
        )

    def get_thesis_by_id(
        self,
        operator_id: str,
        thesis_version_id: str,
    ) -> ThesisVersion | None:
        return next(
            (
                thesis
                for (owner_id, _, _), chain in self._chains.items()
                if owner_id == operator_id
                for thesis in (
                    *chain.canonical_versions,
                    *chain.provisional_branches,
                )
                if thesis.thesis_version_id == thesis_version_id
            ),
            None,
        )

    def get_chain(
        self,
        operator_id: str,
        security_id: str,
        thesis_contract_id: str,
    ) -> ThesisChain:
        key = (operator_id, security_id, thesis_contract_id)
        return self._chains.get(
            key,
            ThesisChain(
                operator_id=operator_id,
                security_id=security_id,
                thesis_contract_id=thesis_contract_id,
                active_canonical_thesis_version_id=None,
                canonical_versions=(),
                provisional_branches=(),
                generated_at=datetime(1970, 1, 1, tzinfo=UTC),
            ),
        )

    def save(
        self,
        result: ReadinessAndThesisResult,
    ) -> ReadinessAndThesisResult:
        readiness = result.readiness
        result_key = (readiness.operator_id, readiness.research_run_id)
        existing = self._results.get(result_key)
        if existing is not None:
            if existing != result:
                raise ReadinessAndThesisError(
                    "conflicting immutable readiness result"
                )
            return existing
        thesis = result.thesis
        if thesis is not None:
            chain_key = (
                thesis.operator_id,
                thesis.security_id,
                thesis.thesis_contract_id,
            )
            chain = self.get_chain(*chain_key)
            if any(
                item.research_run_id == thesis.research_run_id
                for item in (*chain.canonical_versions, *chain.provisional_branches)
            ):
                raise ReadinessAndThesisError(
                    "research run already created thesis version"
                )
            if thesis.thesis_status == "canonical":
                if (
                    thesis.previous_canonical_thesis_version_id
                    != chain.active_canonical_thesis_version_id
                ):
                    raise ReadinessAndThesisError(
                        "canonical thesis predecessor mismatch"
                    )
                chain = ThesisChain(
                    operator_id=chain.operator_id,
                    security_id=chain.security_id,
                    thesis_contract_id=chain.thesis_contract_id,
                    active_canonical_thesis_version_id=(
                        thesis.thesis_version_id
                    ),
                    canonical_versions=(*chain.canonical_versions, thesis),
                    provisional_branches=chain.provisional_branches,
                    generated_at=thesis.created_at,
                )
            elif thesis.thesis_status == "provisional":
                if (
                    thesis.based_on_thesis_version_id
                    != chain.active_canonical_thesis_version_id
                ):
                    raise ReadinessAndThesisError(
                        "provisional thesis branch mismatch"
                    )
                chain = ThesisChain(
                    operator_id=chain.operator_id,
                    security_id=chain.security_id,
                    thesis_contract_id=chain.thesis_contract_id,
                    active_canonical_thesis_version_id=(
                        chain.active_canonical_thesis_version_id
                    ),
                    canonical_versions=chain.canonical_versions,
                    provisional_branches=(
                        *chain.provisional_branches,
                        thesis,
                    ),
                    generated_at=thesis.created_at,
                )
            else:
                raise ReadinessAndThesisError("invalid thesis status")
            self._chains[chain_key] = chain
        else:
            chain_key = (
                readiness.operator_id,
                readiness.security_id,
                readiness.thesis_contract_id,
            )
            chain = self.get_chain(*chain_key)
            self._chains[chain_key] = ThesisChain(
                operator_id=chain.operator_id,
                security_id=chain.security_id,
                thesis_contract_id=chain.thesis_contract_id,
                active_canonical_thesis_version_id=(
                    chain.active_canonical_thesis_version_id
                ),
                canonical_versions=chain.canonical_versions,
                provisional_branches=chain.provisional_branches,
                generated_at=readiness.evaluated_at,
            )
        self._results[result_key] = result
        return result


class ReadinessAndThesisWorkflow:
    def __init__(
        self,
        *,
        committee_repository: ResearchCommitteeRepository,
        evidence_bundle_repository: EvidenceBundleRepository,
        memo_repository: CommitteeMemoRepository,
        repository: ReadinessAndThesisRepository,
        clock: Callable[[], datetime],
        valuation_snapshot_repository: ValuationSnapshotRepository | None = None,
    ) -> None:
        self._committee_repository = committee_repository
        self._evidence_bundle_repository = evidence_bundle_repository
        self._memo_repository = memo_repository
        self._repository = repository
        self._clock = clock
        self._valuation_snapshot_repository = valuation_snapshot_repository

    def execute(
        self,
        operator: AuthenticatedOperator,
        request: ReadinessRequest,
    ) -> ReadinessAndThesisResult:
        committee = self._committee_repository.get_by_id(
            operator.id,
            request.committee_id,
        )
        if committee is None:
            raise ReadinessAndThesisError("persisted committee not found")
        workflow_config = DEFAULT_WORKFLOW_CONFIG_REGISTRY.resolve(
            committee.question_type_id,
            committee.workflow_config_version,
        )
        if (
            workflow_config is None
            or not workflow_config.active
            or workflow_config.question_type_version
            != committee.question_type_version
        ):
            raise ReadinessAndThesisError(
                "committee workflow contract is unsupported"
            )
        expected_gate_policy = {
            THESIS_CONTRACT_ID: "biotech-readiness.v1",
            PERSONAL_RESEARCH_THESIS_CONTRACT_ID: (
                "biotech-personal-readiness.v1"
            ),
        }.get(workflow_config.thesis_contract_id)
        if request.gate_policy_version != expected_gate_policy:
            raise ReadinessAndThesisError("unsupported readiness policy")
        existing = self._repository.get_for_run(
            operator.id,
            committee.research_run_id,
        )
        if existing is not None:
            return existing
        bundle = self._evidence_bundle_repository.get(
            operator.id,
            committee.evidence_bundle_id,
        )
        if bundle is None or bundle.content_hash != committee.evidence_bundle_hash:
            raise ReadinessAndThesisError("committee evidence bundle mismatch")
        memo_execution = self._memo_repository.get_for_committee(
            operator.id,
            committee.committee_id,
        )
        if (
            memo_execution is None
            or memo_execution.execution_state != "accepted"
            or memo_execution.memo is None
        ):
            raise ReadinessAndThesisError("accepted committee memo not found")
        memo = memo_execution.memo
        valuation_snapshot = (
            None
            if self._valuation_snapshot_repository is None
            else self._valuation_snapshot_repository.get_for_run(
                operator.id,
                committee.research_run_id,
            )
        )
        evaluated_at = self._clock()
        checks = _readiness_checks(
            committee,
            bundle,
            memo,
            request.gate_policy_version,
            valuation_snapshot,
            workflow_config.thesis_contract_id,
        )
        passed = tuple(item for item, did_pass in checks if did_pass)
        failed = tuple(item for item, did_pass in checks if not did_pass)
        requested = memo.requested_disposition
        if requested == "decision_ready":
            readiness_status = "passed" if not failed else "blocked"
            final_disposition = (
                "decision_ready" if not failed else "deep_research"
            )
        else:
            readiness_status = "not_requested"
            final_disposition = requested
        opinion_ids = _validated_opinion_ids(committee)
        readiness_id = stable_id(
            operator.id,
            "readiness-gate-result",
            f"{committee.research_run_id}:{request.gate_policy_version}",
        )
        blocking_reasons = tuple(
            ReadinessBlockingReason(
                reason_code=item.reason_code,
                check_id=item.check_id,
                explanation=item.explanation,
            )
            for item in failed
        )
        required_next_evidence = _required_next_evidence(
            memo,
            bundle,
            failed,
        )
        readiness = ReadinessGateResult(
            readiness_gate_result_id=readiness_id,
            operator_id=operator.id,
            security_id=bundle.security_id,
            thesis_contract_id=workflow_config.thesis_contract_id,
            research_run_id=committee.research_run_id,
            evidence_bundle_id=bundle.id,
            evidence_bundle_hash=bundle.content_hash,
            validated_grader_opinion_ids=opinion_ids,
            committee_result_id=committee.committee_id,
            committee_memo_id=memo.memo_id,
            committee_status=committee.status,
            requested_disposition=requested,
            final_disposition=final_disposition,
            readiness_status=readiness_status,
            gate_policy_version=request.gate_policy_version,
            passed_checks=passed,
            failed_checks=failed,
            blocking_reasons=blocking_reasons,
            required_next_evidence=required_next_evidence,
            evaluated_at=evaluated_at,
        )
        chain = self._repository.get_chain(
            operator.id,
            bundle.security_id,
            workflow_config.thesis_contract_id,
        )
        thesis, creation = _create_thesis(
            committee,
            memo,
            readiness,
            chain,
            evaluated_at,
        )
        return self._repository.save(
            ReadinessAndThesisResult(
                readiness=readiness,
                thesis_creation=creation,
                thesis=thesis,
            )
        )


def _readiness_checks(
    committee: ResearchCommitteeResult,
    bundle,
    memo: CommitteeMemo,
    policy_version: str,
    valuation_snapshot: ValuationSnapshot | None,
    thesis_contract_id: str,
) -> tuple[tuple[ReadinessCheck, bool], ...]:
    eligible_accepted = (
        committee.accounting.accepted_count
        == committee.accounting.eligible_count
    )
    stance_values = {
        item.stance
        for item in committee.grader_results
        if item.execution_state == "accepted" and item.stance is not None
    }
    disagreement_preserved = (
        len(stance_values) <= 1 or bool(memo.disagreement_records)
    )
    required_contents = bool(
        memo.executive_summary_statement_ids
        and memo.invalidation_statement_ids
        and memo.review_trigger.statement_id
    )
    expected_valuation_contract = (
        "valuation_snapshot.personal_research.v1"
        if thesis_contract_id == PERSONAL_RESEARCH_THESIS_CONTRACT_ID
        else "valuation_snapshot.v1"
    )
    personal_valuation_contract_valid = bool(
        valuation_snapshot is not None
        and valuation_snapshot.valuation_assurance
        == PERSONAL_RESEARCH_VALUATION_CONTRACT.assurance
        and valuation_snapshot.valuation_policy_version
        == PERSONAL_RESEARCH_VALUATION_CONTRACT.required_policy_version
        and valuation_snapshot.price is not None
        and valuation_snapshot.price.price_type
        == PERSONAL_RESEARCH_VALUATION_CONTRACT.price_type
        and valuation_snapshot.price.halt_verification_status
        == "verified_not_halted"
    )
    valuation_aligned = bool(
        valuation_snapshot is not None
        and valuation_snapshot.research_run_id == committee.research_run_id
        and valuation_snapshot.evidence_bundle_id == bundle.id
        and valuation_snapshot.evidence_bundle_hash == bundle.content_hash
        and valuation_snapshot.security_id == bundle.security_id
        and valuation_snapshot.snapshot_status == "valid"
        and valuation_snapshot.contract_version == expected_valuation_contract
        and (
            personal_valuation_contract_valid
            if thesis_contract_id == PERSONAL_RESEARCH_THESIS_CONTRACT_ID
            else valuation_snapshot.valuation_assurance is None
        )
        and valuation_snapshot.price_information_state == "aligned"
        and valuation_snapshot.market_relative_analysis_permitted
    )
    values = (
        (
            "committee_status_complete",
            committee.status == "complete",
            committee.committee_id,
        ),
        (
            "all_eligible_graders_accepted",
            eligible_accepted,
            committee.committee_id,
        ),
        (
            "zero_eligible_abstentions",
            committee.accounting.abstained_count == 0,
            committee.committee_id,
        ),
        (
            "zero_required_grader_failures",
            committee.accounting.failed_count == 0,
            committee.committee_id,
        ),
        (
            "blocking_evidence_requirements_satisfied",
            bundle.grader_ready
            and not any(gap.blocking for gap in bundle.gaps),
            bundle.id,
        ),
        (
            "aligned_valuation_snapshot_required",
            valuation_aligned,
            (
                bundle.id
                if valuation_snapshot is None
                else valuation_snapshot.id
            ),
        ),
        (
            "source_freshness_passed",
            all(item.freshness == "current" for item in bundle.manifest),
            bundle.id,
        ),
        (
            "material_claims_citation_valid",
            True,
            memo.memo_id,
        ),
        (
            "grader_decision_questions_answered",
            eligible_accepted,
            committee.committee_id,
        ),
        (
            "material_disagreement_preserved",
            disagreement_preserved,
            memo.memo_id,
        ),
        (
            "thesis_required_contents_present",
            required_contents,
            memo.memo_id,
        ),
    )
    return tuple(
        (
            ReadinessCheck(
                check_id=check_id,
                check_version=policy_version,
                reason_code=(
                    f"{check_id}_passed" if did_pass else f"{check_id}_failed"
                ),
                explanation=(
                    f"{check_id} passed" if did_pass else f"{check_id} failed"
                ),
                reference_ids=(reference_id,),
            ),
            did_pass,
        )
        for check_id, did_pass, reference_id in values
    )


def _validated_opinion_ids(
    committee: ResearchCommitteeResult,
) -> tuple[str, ...]:
    return tuple(
        item.opinion.opinion_id
        for item in committee.grader_results
        if item.opinion is not None
        and item.execution_state in {"accepted", "abstained"}
    )


def _required_next_evidence(
    memo: CommitteeMemo,
    bundle,
    failed_checks: tuple[ReadinessCheck, ...],
) -> tuple[RequiredNextEvidence, ...]:
    if not failed_checks:
        return ()
    affected = tuple(item.check_id for item in failed_checks)
    statements = {item.statement_id: item for item in memo.statements}
    requirements: list[RequiredNextEvidence] = []
    for statement_id in memo.required_next_evidence_statement_ids:
        statement = statements[statement_id]
        requirements.append(
            RequiredNextEvidence(
                requirement_id=statement_id,
                description=statement.text,
                affected_check_ids=affected,
            )
        )
    for gap in bundle.gaps:
        if gap.blocking:
            requirements.append(
                RequiredNextEvidence(
                    requirement_id=gap.code,
                    description=gap.explanation,
                    affected_check_ids=affected,
                )
            )
    if not requirements:
        requirements = [
            RequiredNextEvidence(
                requirement_id=f"resolve-{item.check_id}",
                description=f"Resolve failed readiness check {item.check_id}.",
                affected_check_ids=(item.check_id,),
            )
            for item in failed_checks
        ]
    unique: dict[str, RequiredNextEvidence] = {}
    for item in requirements:
        unique.setdefault(item.requirement_id, item)
    return tuple(unique.values())


def _create_thesis(
    committee: ResearchCommitteeResult,
    memo: CommitteeMemo,
    readiness: ReadinessGateResult,
    chain: ThesisChain,
    created_at: datetime,
) -> tuple[ThesisVersion | None, ThesisCreationResult]:
    if committee.status == "complete":
        thesis_status = "canonical"
        creation_outcome = "canonical_created"
        reason_code = "complete_committee_creates_canonical"
    elif committee.status == "complete_with_abstentions":
        if readiness.final_disposition == "decision_ready":
            raise ReadinessAndThesisError(
                "provisional thesis cannot be decision ready"
            )
        thesis_status = "provisional"
        creation_outcome = "provisional_created"
        reason_code = "abstention_committee_creates_provisional"
    elif committee.status in {
        "incomplete_required_grader_failed",
        "insufficient_accepted_opinions",
    }:
        return None, ThesisCreationResult(
            thesis_creation_result_id=stable_id(
                readiness.operator_id,
                "thesis-creation-result",
                readiness.research_run_id,
            ),
            operator_id=readiness.operator_id,
            security_id=readiness.security_id,
            thesis_contract_id=readiness.thesis_contract_id,
            research_run_id=readiness.research_run_id,
            committee_result_id=readiness.committee_result_id,
            readiness_gate_result_id=readiness.readiness_gate_result_id,
            committee_status=committee.status,
            creation_outcome="no_thesis",
            thesis_version_id=None,
            reason_code="incomplete_committee_creates_no_thesis",
            created_at=created_at,
        )
    else:
        raise ReadinessAndThesisError("unsupported committee status")
    previous = chain.active_canonical_thesis_version_id
    thesis_id = stable_id(
        readiness.operator_id,
        "thesis-version",
        readiness.research_run_id,
    )
    thesis = ThesisVersion(
        thesis_version_id=thesis_id,
        thesis_status=thesis_status,
        operator_id=readiness.operator_id,
        security_id=readiness.security_id,
        thesis_contract_id=readiness.thesis_contract_id,
        previous_canonical_thesis_version_id=previous,
        based_on_thesis_version_id=previous,
        research_run_id=readiness.research_run_id,
        evidence_bundle_id=readiness.evidence_bundle_id,
        evidence_bundle_hash=readiness.evidence_bundle_hash,
        question_type_version=committee.question_type_version,
        workflow_config_version=committee.workflow_config_version,
        proposition_id=committee.proposition_id,
        proposition_version=committee.proposition_version,
        validated_grader_opinion_ids=(
            readiness.validated_grader_opinion_ids
        ),
        committee_result_id=committee.committee_id,
        committee_memo_id=memo.memo_id,
        committee_status=committee.status,
        readiness_gate_result_id=readiness.readiness_gate_result_id,
        readiness_gate_policy_version=readiness.gate_policy_version,
        requested_disposition=readiness.requested_disposition,
        final_disposition=readiness.final_disposition,
        content=ThesisContent(
            core_thesis_statement_ids=memo.executive_summary_statement_ids,
            unresolved_disagreement_ids=tuple(
                str(item["disagreement_id"])
                for item in memo.disagreement_records
            ),
            invalidation_statement_ids=memo.invalidation_statement_ids,
            evidence_gap_statement_ids=memo.evidence_gap_statement_ids,
            review_trigger_statement_id=memo.review_trigger.statement_id,
        ),
        created_at=created_at,
    )
    return thesis, ThesisCreationResult(
        thesis_creation_result_id=stable_id(
            readiness.operator_id,
            "thesis-creation-result",
            readiness.research_run_id,
        ),
        operator_id=readiness.operator_id,
        security_id=readiness.security_id,
        thesis_contract_id=readiness.thesis_contract_id,
        research_run_id=readiness.research_run_id,
        committee_result_id=readiness.committee_result_id,
        readiness_gate_result_id=readiness.readiness_gate_result_id,
        committee_status=committee.status,
        creation_outcome=creation_outcome,
        thesis_version_id=thesis_id,
        reason_code=reason_code,
        created_at=created_at,
    )


__all__ = [
    "InMemoryReadinessAndThesisRepository",
    "ReadinessAndThesisError",
    "ReadinessAndThesisResult",
    "ReadinessAndThesisRepository",
    "ReadinessAndThesisWorkflow",
    "ReadinessCheck",
    "ReadinessGateResult",
    "ReadinessRequest",
    "ThesisChain",
    "ThesisCreationResult",
    "ThesisVersion",
]

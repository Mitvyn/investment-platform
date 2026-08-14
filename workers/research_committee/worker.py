from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import Event, Thread
import uuid
from typing import Protocol

from investment_research_os.committee_memos import CommitteeMemoError
from investment_research_os.evidence_bundles import (
    EvidenceBundle,
    EvidenceBundleError,
    EvidenceBundleNotFound,
    EvidenceBundleRepository,
)
from investment_research_os.readiness_and_theses import ReadinessAndThesisError
from investment_research_os.research_runs import (
    AuthenticatedOperator,
    PERSONAL_RESEARCH_QUESTION_TYPE,
    PERSONAL_RESEARCH_QUESTION_TYPE_VERSION,
    PERSONAL_RESEARCH_THESIS_CONTRACT_ID,
    PERSONAL_RESEARCH_WORKFLOW_CONFIG_VERSION,
    QUESTION_TYPE,
    QUESTION_TYPE_VERSION,
    ResearchRun,
    ResearchRunNotFound,
    ResearchRunRepository,
    ResearchRunRequestError,
    ResearchRunSourceIdentity,
    THESIS_CONTRACT_ID,
    WORKFLOW_CONFIG_VERSION,
)
from investment_research_os.valuation_snapshots import (
    ValuationSnapshot,
    ValuationSnapshotError,
    ValuationSnapshotRepository,
)
from investment_research_os.valuation_snapshots.massive import (
    MassiveRateLimitError,
    MassiveValuationError,
)
from workers.sec.storage import EvidenceStorageError


class ResearchRunStageError(RuntimeError):
    def __init__(self, error_code: str, *, retryable: bool) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class CommitteeCommandClaim:
    command_id: str
    operator_id: str
    security_id: str
    capture_id: str
    capture_revision: int
    capture_content_hash: str
    question_type_version: str
    workflow_config_version: str
    as_of_cutoff: datetime
    operator_focus: str | None
    attempt_id: str
    attempt_number: int
    lease_token: str
    next_stage: str
    completed_stages: tuple[str, ...]
    research_run_id: str | None


class CommitteeCommandStore(Protocol):
    def claim_next(self, worker_id: str) -> CommitteeCommandClaim | None: ...

    def renew_lease(self, claim: CommitteeCommandClaim) -> None: ...

    def checkpoint(
        self,
        claim: CommitteeCommandClaim,
        *,
        stage: str,
        artifact_id: str,
    ) -> None: ...

    def fail(
        self,
        claim: CommitteeCommandClaim,
        *,
        stage: str,
        error_code: str,
        retryable: bool,
    ) -> None: ...


class ResearchRunStage(Protocol):
    def execute(self, claim: CommitteeCommandClaim) -> str: ...


class CommitteeLeaseLostError(RuntimeError):
    pass


class ThreadedCommitteeLeaseKeeper:
    def __init__(
        self,
        commands: CommitteeCommandStore,
        *,
        interval_seconds: float,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("heartbeat interval must be positive")
        self._commands = commands
        self._interval_seconds = interval_seconds

    def execute(
        self,
        claim: CommitteeCommandClaim,
        stage: ResearchRunStage,
    ) -> str:
        stop = Event()
        heartbeat_errors: list[Exception] = []

        def renew_until_stopped() -> None:
            while not stop.wait(self._interval_seconds):
                try:
                    self._commands.renew_lease(claim)
                except Exception as error:
                    heartbeat_errors.append(error)
                    stop.set()
                    return

        thread = Thread(
            target=renew_until_stopped,
            name=f"iros-lease-{claim.attempt_id}",
            daemon=True,
        )
        stage_error: BaseException | None = None
        artifact_id: str | None = None
        thread.start()
        try:
            artifact_id = stage.execute(claim)
        except BaseException as error:
            stage_error = error
        finally:
            stop.set()
            thread.join()

        if heartbeat_errors:
            raise CommitteeLeaseLostError(
                "research run command lease renewal failed"
            ) from heartbeat_errors[0]
        if stage_error is not None:
            raise stage_error
        assert artifact_id is not None
        return artifact_id


class ResearchRunWorkflowBoundary(Protocol):
    def create(
        self,
        operator: AuthenticatedOperator,
        payload: dict[str, object],
        *,
        source_identity: ResearchRunSourceIdentity,
    ) -> ResearchRun: ...


class EvidenceBundleWorkflowBoundary(Protocol):
    def materialize(
        self,
        operator: AuthenticatedOperator,
        research_run_id: str,
    ) -> EvidenceBundle: ...


class ValuationSnapshotWorkflowBoundary(Protocol):
    def materialize(
        self,
        operator: AuthenticatedOperator,
        evidence_bundle_id: str,
    ) -> ValuationSnapshot: ...


@dataclass(frozen=True, slots=True)
class PersistentGraderCommitteeArtifact:
    id: str
    operator_id: str
    research_run_id: str
    security_id: str
    as_of_cutoff: datetime
    question_type_version: str
    workflow_config_version: str


class PersistentGraderCommitteeWorkflowBoundary(Protocol):
    def execute(
        self,
        operator: AuthenticatedOperator,
        research_run_id: str,
    ) -> PersistentGraderCommitteeArtifact: ...


@dataclass(frozen=True, slots=True)
class PersistentCommitteeMemoArtifact:
    id: str
    operator_id: str
    research_run_id: str
    security_id: str
    as_of_cutoff: datetime
    question_type_version: str
    workflow_config_version: str
    committee_id: str


class PersistentCommitteeMemoWorkflowBoundary(Protocol):
    def execute(
        self,
        operator: AuthenticatedOperator,
        research_run_id: str,
    ) -> PersistentCommitteeMemoArtifact: ...


@dataclass(frozen=True, slots=True)
class PersistentReadinessThesisArtifact:
    id: str
    operator_id: str
    research_run_id: str
    security_id: str
    as_of_cutoff: datetime
    question_type_version: str
    workflow_config_version: str
    committee_id: str
    committee_memo_id: str
    readiness_gate_result_id: str


class PersistentReadinessThesisWorkflowBoundary(Protocol):
    def execute(
        self,
        operator: AuthenticatedOperator,
        research_run_id: str,
    ) -> PersistentReadinessThesisArtifact: ...


class PersistentResearchRunStage:
    def __init__(self, workflow: ResearchRunWorkflowBoundary) -> None:
        self._workflow = workflow

    def execute(self, claim: CommitteeCommandClaim) -> str:
        question_type_by_identity = {
            (QUESTION_TYPE_VERSION, WORKFLOW_CONFIG_VERSION): QUESTION_TYPE,
            (
                PERSONAL_RESEARCH_QUESTION_TYPE_VERSION,
                PERSONAL_RESEARCH_WORKFLOW_CONFIG_VERSION,
            ): PERSONAL_RESEARCH_QUESTION_TYPE,
        }
        question_type = question_type_by_identity.get(
            (
                claim.question_type_version,
                claim.workflow_config_version,
            )
        )
        if question_type is None:
            raise ResearchRunStageError(
                "research_run_request_invalid",
                retryable=False,
            )
        try:
            run = self._workflow.create(
                AuthenticatedOperator(claim.operator_id),
                {
                    "question_type": question_type,
                    "security_id": claim.security_id,
                    "as_of_cutoff": claim.as_of_cutoff.isoformat(),
                    "workflow_config_version": (claim.workflow_config_version),
                    "operator_focus": claim.operator_focus,
                },
                source_identity=ResearchRunSourceIdentity(
                    capture_id=claim.capture_id,
                    capture_revision=claim.capture_revision,
                    capture_content_hash=claim.capture_content_hash,
                ),
            )
        except ResearchRunRequestError as error:
            raise ResearchRunStageError(
                "research_run_request_invalid",
                retryable=False,
            ) from error
        except EvidenceStorageError as error:
            raise ResearchRunStageError(
                "research_run_persistence_failed",
                retryable=True,
            ) from error
        if (
            run.operator_id != claim.operator_id
            or run.security_id != claim.security_id
            or run.question_type_version != claim.question_type_version
            or run.workflow_config_version != claim.workflow_config_version
            or run.as_of_cutoff != claim.as_of_cutoff
        ):
            raise ResearchRunStageError(
                "research_run_identity_mismatch",
                retryable=False,
            )
        try:
            return str(uuid.UUID(run.id))
        except (AttributeError, TypeError, ValueError) as error:
            raise ResearchRunStageError(
                "research_run_identity_invalid",
                retryable=False,
            ) from error


class PersistentEvidenceBundleStage:
    def __init__(self, workflow: EvidenceBundleWorkflowBoundary) -> None:
        self._workflow = workflow

    def execute(self, claim: CommitteeCommandClaim) -> str:
        if claim.research_run_id is None:
            raise ResearchRunStageError(
                "evidence_bundle_research_run_missing",
                retryable=False,
            )
        try:
            bundle = self._workflow.materialize(
                AuthenticatedOperator(claim.operator_id),
                claim.research_run_id,
            )
        except ResearchRunNotFound as error:
            raise ResearchRunStageError(
                "evidence_bundle_research_run_missing",
                retryable=False,
            ) from error
        except EvidenceBundleError as error:
            raise ResearchRunStageError(
                "evidence_bundle_contract_invalid",
                retryable=False,
            ) from error
        except EvidenceStorageError as error:
            raise ResearchRunStageError(
                "evidence_bundle_persistence_failed",
                retryable=True,
            ) from error
        if (
            bundle.operator_id != claim.operator_id
            or bundle.research_run_id != claim.research_run_id
            or bundle.security_id != claim.security_id
            or bundle.as_of_cutoff != claim.as_of_cutoff
        ):
            raise ResearchRunStageError(
                "evidence_bundle_identity_mismatch",
                retryable=False,
            )
        try:
            return str(uuid.UUID(bundle.id))
        except (AttributeError, TypeError, ValueError) as error:
            raise ResearchRunStageError(
                "evidence_bundle_identity_invalid",
                retryable=False,
            ) from error


class PersistentValuationSnapshotStage:
    def __init__(
        self,
        *,
        research_run_repository: ResearchRunRepository,
        evidence_bundle_repository: EvidenceBundleRepository,
        valuation_snapshot_repository: ValuationSnapshotRepository,
        workflow: ValuationSnapshotWorkflowBoundary,
        personal_research_workflow: ValuationSnapshotWorkflowBoundary | None = None,
    ) -> None:
        self._research_runs = research_run_repository
        self._evidence_bundles = evidence_bundle_repository
        self._valuation_snapshots = valuation_snapshot_repository
        self._workflow = workflow
        self._personal_research_workflow = personal_research_workflow

    def execute(self, claim: CommitteeCommandClaim) -> str:
        if claim.research_run_id is None:
            raise ResearchRunStageError(
                "valuation_snapshot_research_run_missing",
                retryable=False,
            )
        try:
            run = self._research_runs.get(
                claim.operator_id,
                claim.research_run_id,
            )
            bundle = self._evidence_bundles.get_for_run(
                claim.operator_id,
                claim.research_run_id,
            )
        except EvidenceStorageError as error:
            raise ResearchRunStageError(
                "valuation_snapshot_persistence_failed",
                retryable=True,
            ) from error
        if run is None:
            raise ResearchRunStageError(
                "valuation_snapshot_research_run_missing",
                retryable=False,
            )
        if bundle is None:
            raise ResearchRunStageError(
                "valuation_snapshot_evidence_bundle_missing",
                retryable=False,
            )
        if (
            run.operator_id != claim.operator_id
            or run.id != claim.research_run_id
            or run.security_id != claim.security_id
            or run.as_of_cutoff != claim.as_of_cutoff
            or run.question_type_version != claim.question_type_version
            or run.workflow_config_version != claim.workflow_config_version
        ):
            raise ResearchRunStageError(
                "valuation_snapshot_research_run_identity_mismatch",
                retryable=False,
            )
        if (
            bundle.operator_id != claim.operator_id
            or bundle.research_run_id != claim.research_run_id
            or bundle.security_id != claim.security_id
            or bundle.as_of_cutoff != claim.as_of_cutoff
        ):
            raise ResearchRunStageError(
                "valuation_snapshot_evidence_bundle_identity_mismatch",
                retryable=False,
            )
        try:
            evidence_bundle_id = str(uuid.UUID(bundle.id))
        except (AttributeError, TypeError, ValueError) as error:
            raise ResearchRunStageError(
                "valuation_snapshot_evidence_bundle_identity_invalid",
                retryable=False,
            ) from error
        try:
            if run.thesis_contract_id == THESIS_CONTRACT_ID:
                workflow = self._workflow
            elif run.thesis_contract_id == PERSONAL_RESEARCH_THESIS_CONTRACT_ID:
                if self._personal_research_workflow is None:
                    raise ResearchRunStageError(
                        "personal_research_valuation_workflow_unavailable",
                        retryable=False,
                    )
                workflow = self._personal_research_workflow
            else:
                raise ResearchRunStageError(
                    "valuation_snapshot_workflow_contract_unsupported",
                    retryable=False,
                )
            snapshot = workflow.materialize(
                AuthenticatedOperator(claim.operator_id),
                evidence_bundle_id,
            )
            persisted = self._valuation_snapshots.get_for_run(
                claim.operator_id,
                claim.research_run_id,
            )
        except EvidenceBundleNotFound as error:
            raise ResearchRunStageError(
                "valuation_snapshot_evidence_bundle_missing",
                retryable=False,
            ) from error
        except MassiveRateLimitError as error:
            raise ResearchRunStageError(
                "valuation_market_source_rate_limited",
                retryable=True,
            ) from error
        except MassiveValuationError as error:
            raise ResearchRunStageError(
                "valuation_market_source_invalid",
                retryable=False,
            ) from error
        except ValuationSnapshotError as error:
            raise ResearchRunStageError(
                "valuation_snapshot_contract_invalid",
                retryable=False,
            ) from error
        except EvidenceStorageError as error:
            raise ResearchRunStageError(
                "valuation_snapshot_persistence_failed",
                retryable=True,
            ) from error
        if persisted is None or persisted != snapshot:
            raise ResearchRunStageError(
                "valuation_snapshot_persistence_incomplete",
                retryable=True,
            )
        if (
            persisted.operator_id != claim.operator_id
            or persisted.research_run_id != claim.research_run_id
            or persisted.evidence_bundle_id != bundle.id
            or persisted.evidence_bundle_hash != bundle.content_hash
            or persisted.security_id != claim.security_id
            or persisted.as_of_cutoff != claim.as_of_cutoff
        ):
            raise ResearchRunStageError(
                "valuation_snapshot_identity_mismatch",
                retryable=False,
            )
        try:
            return str(uuid.UUID(persisted.id))
        except (AttributeError, TypeError, ValueError) as error:
            raise ResearchRunStageError(
                "valuation_snapshot_identity_invalid",
                retryable=False,
            ) from error


class PersistentGraderCommitteeStage:
    def __init__(
        self,
        *,
        research_run_repository: ResearchRunRepository,
        workflow: PersistentGraderCommitteeWorkflowBoundary,
    ) -> None:
        self._research_runs = research_run_repository
        self._workflow = workflow

    def execute(self, claim: CommitteeCommandClaim) -> str:
        if claim.research_run_id is None:
            raise ResearchRunStageError(
                "grader_committee_research_run_missing",
                retryable=False,
            )
        try:
            run = self._research_runs.get(
                claim.operator_id,
                claim.research_run_id,
            )
        except EvidenceStorageError as error:
            raise ResearchRunStageError(
                "grader_committee_persistence_failed",
                retryable=True,
            ) from error
        if run is None:
            raise ResearchRunStageError(
                "grader_committee_research_run_missing",
                retryable=False,
            )
        if (
            run.id != claim.research_run_id
            or run.operator_id != claim.operator_id
            or run.security_id != claim.security_id
            or run.as_of_cutoff != claim.as_of_cutoff
            or run.question_type_version != claim.question_type_version
            or run.workflow_config_version != claim.workflow_config_version
        ):
            raise ResearchRunStageError(
                "grader_committee_research_run_identity_mismatch",
                retryable=False,
            )
        try:
            artifact = self._workflow.execute(
                AuthenticatedOperator(claim.operator_id),
                claim.research_run_id,
            )
        except EvidenceStorageError as error:
            raise ResearchRunStageError(
                "grader_committee_persistence_failed",
                retryable=True,
            ) from error
        if (
            artifact.operator_id != claim.operator_id
            or artifact.research_run_id != claim.research_run_id
            or artifact.security_id != claim.security_id
            or artifact.as_of_cutoff != claim.as_of_cutoff
            or artifact.question_type_version != claim.question_type_version
            or artifact.workflow_config_version != claim.workflow_config_version
        ):
            raise ResearchRunStageError(
                "grader_committee_identity_mismatch",
                retryable=False,
            )
        try:
            return str(uuid.UUID(artifact.id))
        except (AttributeError, TypeError, ValueError) as error:
            raise ResearchRunStageError(
                "grader_committee_identity_invalid",
                retryable=False,
            ) from error


class PersistentCommitteeMemoStage:
    def __init__(
        self,
        *,
        research_run_repository: ResearchRunRepository,
        workflow: PersistentCommitteeMemoWorkflowBoundary,
    ) -> None:
        self._research_runs = research_run_repository
        self._workflow = workflow

    def execute(self, claim: CommitteeCommandClaim) -> str:
        if claim.research_run_id is None:
            raise ResearchRunStageError(
                "committee_memo_research_run_missing",
                retryable=False,
            )
        try:
            run = self._research_runs.get(
                claim.operator_id,
                claim.research_run_id,
            )
        except EvidenceStorageError as error:
            raise ResearchRunStageError(
                "committee_memo_persistence_failed",
                retryable=True,
            ) from error
        if run is None:
            raise ResearchRunStageError(
                "committee_memo_research_run_missing",
                retryable=False,
            )
        if (
            run.id != claim.research_run_id
            or run.operator_id != claim.operator_id
            or run.security_id != claim.security_id
            or run.as_of_cutoff != claim.as_of_cutoff
            or run.question_type_version != claim.question_type_version
            or run.workflow_config_version != claim.workflow_config_version
        ):
            raise ResearchRunStageError(
                "committee_memo_research_run_identity_mismatch",
                retryable=False,
            )
        try:
            artifact = self._workflow.execute(
                AuthenticatedOperator(claim.operator_id),
                claim.research_run_id,
            )
        except CommitteeMemoError as error:
            raise ResearchRunStageError(
                "committee_memo_contract_invalid",
                retryable=False,
            ) from error
        except EvidenceStorageError as error:
            raise ResearchRunStageError(
                "committee_memo_persistence_failed",
                retryable=True,
            ) from error
        if (
            artifact.operator_id != claim.operator_id
            or artifact.research_run_id != claim.research_run_id
            or artifact.security_id != claim.security_id
            or artifact.as_of_cutoff != claim.as_of_cutoff
            or artifact.question_type_version != claim.question_type_version
            or artifact.workflow_config_version != claim.workflow_config_version
        ):
            raise ResearchRunStageError(
                "committee_memo_identity_mismatch",
                retryable=False,
            )
        try:
            artifact_id = str(uuid.UUID(artifact.id))
            uuid.UUID(artifact.committee_id)
        except (AttributeError, TypeError, ValueError) as error:
            raise ResearchRunStageError(
                "committee_memo_identity_invalid",
                retryable=False,
            ) from error
        return artifact_id


class PersistentReadinessThesisStage:
    def __init__(
        self,
        *,
        research_run_repository: ResearchRunRepository,
        workflow: PersistentReadinessThesisWorkflowBoundary,
    ) -> None:
        self._research_runs = research_run_repository
        self._workflow = workflow

    def execute(self, claim: CommitteeCommandClaim) -> str:
        if claim.research_run_id is None:
            raise ResearchRunStageError(
                "readiness_thesis_research_run_missing",
                retryable=False,
            )
        try:
            run = self._research_runs.get(
                claim.operator_id,
                claim.research_run_id,
            )
        except EvidenceStorageError as error:
            raise ResearchRunStageError(
                "readiness_thesis_persistence_failed",
                retryable=True,
            ) from error
        if run is None:
            raise ResearchRunStageError(
                "readiness_thesis_research_run_missing",
                retryable=False,
            )
        if (
            run.id != claim.research_run_id
            or run.operator_id != claim.operator_id
            or run.security_id != claim.security_id
            or run.as_of_cutoff != claim.as_of_cutoff
            or run.question_type_version != claim.question_type_version
            or run.workflow_config_version != claim.workflow_config_version
        ):
            raise ResearchRunStageError(
                "readiness_thesis_research_run_identity_mismatch",
                retryable=False,
            )
        try:
            artifact = self._workflow.execute(
                AuthenticatedOperator(claim.operator_id),
                claim.research_run_id,
            )
        except ReadinessAndThesisError as error:
            raise ResearchRunStageError(
                "readiness_thesis_contract_invalid",
                retryable=False,
            ) from error
        except EvidenceStorageError as error:
            raise ResearchRunStageError(
                "readiness_thesis_persistence_failed",
                retryable=True,
            ) from error
        if (
            artifact.operator_id != claim.operator_id
            or artifact.research_run_id != claim.research_run_id
            or artifact.security_id != claim.security_id
            or artifact.as_of_cutoff != claim.as_of_cutoff
            or artifact.question_type_version != claim.question_type_version
            or artifact.workflow_config_version != claim.workflow_config_version
        ):
            raise ResearchRunStageError(
                "readiness_thesis_identity_mismatch",
                retryable=False,
            )
        try:
            artifact_id = str(uuid.UUID(artifact.id))
            uuid.UUID(artifact.committee_id)
            uuid.UUID(artifact.committee_memo_id)
            uuid.UUID(artifact.readiness_gate_result_id)
        except (AttributeError, TypeError, ValueError) as error:
            raise ResearchRunStageError(
                "readiness_thesis_identity_invalid",
                retryable=False,
            ) from error
        return artifact_id


class PersistentCommitteeWorker:
    def __init__(
        self,
        *,
        worker_id: str,
        commands: CommitteeCommandStore,
        research_run_stage: ResearchRunStage,
        evidence_bundle_stage: ResearchRunStage,
        valuation_snapshot_stage: ResearchRunStage | None = None,
        grader_committee_stage: ResearchRunStage | None = None,
        committee_memo_stage: ResearchRunStage | None = None,
        readiness_thesis_stage: ResearchRunStage | None = None,
        heartbeat_interval_seconds: float = 60.0,
    ) -> None:
        if not worker_id.strip():
            raise ValueError("worker_id is required")
        self._worker_id = worker_id.strip()
        self._commands = commands
        self._research_run_stage = research_run_stage
        self._evidence_bundle_stage = evidence_bundle_stage
        self._valuation_snapshot_stage = valuation_snapshot_stage
        self._grader_committee_stage = grader_committee_stage
        self._committee_memo_stage = committee_memo_stage
        self._readiness_thesis_stage = readiness_thesis_stage
        self._lease_keeper = ThreadedCommitteeLeaseKeeper(
            commands,
            interval_seconds=heartbeat_interval_seconds,
        )

    def run_once(self) -> bool:
        claim = self._commands.claim_next(self._worker_id)
        if claim is None:
            return False
        if claim.next_stage == "research_run":
            stage = self._research_run_stage
        elif claim.next_stage == "evidence_bundle":
            stage = self._evidence_bundle_stage
        elif (
            claim.next_stage == "valuation_snapshot"
            and self._valuation_snapshot_stage is not None
        ):
            stage = self._valuation_snapshot_stage
        elif (
            claim.next_stage == "grader_committee"
            and self._grader_committee_stage is not None
        ):
            stage = self._grader_committee_stage
        elif (
            claim.next_stage == "committee_memo"
            and self._committee_memo_stage is not None
        ):
            stage = self._committee_memo_stage
        elif (
            claim.next_stage == "readiness_thesis"
            and self._readiness_thesis_stage is not None
        ):
            stage = self._readiness_thesis_stage
        else:
            self._commands.fail(
                claim,
                stage=claim.next_stage,
                error_code="worker_stage_unavailable",
                retryable=False,
            )
            return True
        try:
            artifact_id = self._lease_keeper.execute(claim, stage)
        except CommitteeLeaseLostError:
            return True
        except ResearchRunStageError as error:
            self._commands.fail(
                claim,
                stage=claim.next_stage,
                error_code=error.error_code,
                retryable=error.retryable,
            )
            return True
        self._commands.checkpoint(
            claim,
            stage=claim.next_stage,
            artifact_id=artifact_id,
        )
        return True

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime
from time import sleep
from types import SimpleNamespace

from investment_research_os.committee_memos import CommitteeMemoError
from investment_research_os.evidence_bundles import (
    InMemoryEvidenceBundleRepository,
)
from investment_research_os.readiness_and_theses import ReadinessAndThesisError
from investment_research_os.research_runs import (
    InMemoryResearchRunRepository,
    PERSONAL_RESEARCH_QUESTION_TYPE,
    PERSONAL_RESEARCH_QUESTION_TYPE_VERSION,
    PERSONAL_RESEARCH_THESIS_CONTRACT_ID,
    PERSONAL_RESEARCH_WORKFLOW_CONFIG_VERSION,
)
from investment_research_os.valuation_snapshots import (
    InMemoryValuationSnapshotRepository,
    PersonalResearchValuationSnapshotWorkflow,
    ValuationSnapshotWorkflow,
)
from investment_research_os.valuation_snapshots.massive import (
    MassiveRateLimitError,
    MassiveValuationError,
)
from tests.test_evidence_bundle_storage import materialized_bundle
from tests.test_evidence_bundle_workflow import (
    CUTOFF,
    OPERATOR_ID,
    RUN_ID as FIXTURE_RUN_ID,
    SECURITY_ID,
    eligible_run,
)
from tests.test_valuation_snapshot_workflow import (
    FixedCalendar,
    FixedValuationSource,
    SESSION,
    input_candidate,
    personal_input_candidate,
)
from workers.sec.storage import EvidenceStorageError
from workers.research_committee.worker import (
    CommitteeCommandClaim,
    PersistentCommitteeMemoArtifact,
    PersistentCommitteeMemoStage,
    PersistentEvidenceBundleStage,
    PersistentCommitteeWorker,
    PersistentResearchRunStage,
    PersistentReadinessThesisArtifact,
    PersistentReadinessThesisStage,
    PersistentValuationSnapshotStage,
    ResearchRunStageError,
)


RUN_ID = "66666666-6666-4666-8666-666666666666"
BUNDLE_ID = "77777777-7777-4777-8777-777777777777"


class CommandStoreFake:
    def __init__(self, claim: CommitteeCommandClaim | None) -> None:
        self.claim = claim
        self.checkpoints: list[tuple[CommitteeCommandClaim, str, str]] = []
        self.failures: list[tuple[CommitteeCommandClaim, str, str, bool]] = []
        self.renewals: list[CommitteeCommandClaim] = []

    def claim_next(self, worker_id: str) -> CommitteeCommandClaim | None:
        self.worker_id = worker_id
        return self.claim

    def checkpoint(
        self,
        claim: CommitteeCommandClaim,
        *,
        stage: str,
        artifact_id: str,
    ) -> None:
        self.checkpoints.append((claim, stage, artifact_id))

    def renew_lease(self, claim: CommitteeCommandClaim) -> None:
        self.renewals.append(claim)

    def fail(
        self,
        claim: CommitteeCommandClaim,
        *,
        stage: str,
        error_code: str,
        retryable: bool,
    ) -> None:
        self.failures.append((claim, stage, error_code, retryable))


class ResearchRunStageFake:
    def execute(self, claim: CommitteeCommandClaim) -> str:
        self.claim = claim
        return RUN_ID


class EvidenceBundleStageFake:
    def execute(self, claim: CommitteeCommandClaim) -> str:
        self.claim = claim
        return BUNDLE_ID


class FailingValuationWorkflow:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def materialize(self, operator, evidence_bundle_id):
        raise self.error


class FailingResearchRunStageFake:
    def execute(self, claim: CommitteeCommandClaim) -> str:
        raise ResearchRunStageError(
            "research_run_persistence_failed",
            retryable=True,
        )


class SlowResearchRunStageFake:
    def execute(self, claim: CommitteeCommandClaim) -> str:
        sleep(0.02)
        return RUN_ID


class HeartbeatFailingCommandStoreFake(CommandStoreFake):
    def renew_lease(self, claim: CommitteeCommandClaim) -> None:
        raise EvidenceStorageError("heartbeat unavailable")


class ResearchRunWorkflowFake:
    def create(self, operator, payload):
        self.operator = operator
        self.payload = payload
        return SimpleNamespace(
            id=RUN_ID,
            operator_id=operator.id,
            security_id=payload["security_id"],
            question_type_version=("biotech_moonshot_catalyst_assessment.v1"),
            workflow_config_version="biotech-moonshot-catalyst-v1",
            as_of_cutoff=datetime.fromisoformat(str(payload["as_of_cutoff"])),
        )


class PersonalResearchRunWorkflowFake(ResearchRunWorkflowFake):
    def create(self, operator, payload):
        self.operator = operator
        self.payload = payload
        return SimpleNamespace(
            id=RUN_ID,
            operator_id=operator.id,
            security_id=payload["security_id"],
            question_type_version=(
                "biotech_moonshot_catalyst_personal_research_assessment.v1"
            ),
            workflow_config_version=(
                "biotech-moonshot-catalyst-personal-research-v1"
            ),
            as_of_cutoff=datetime.fromisoformat(str(payload["as_of_cutoff"])),
        )


class EvidenceBundleWorkflowFake:
    def materialize(self, operator, research_run_id):
        self.operator = operator
        self.research_run_id = research_run_id
        return SimpleNamespace(
            id=BUNDLE_ID,
            operator_id=operator.id,
            research_run_id=research_run_id,
            security_id=command_claim().security_id,
            as_of_cutoff=command_claim().as_of_cutoff,
        )


class CommitteeMemoWorkflowFake:
    def execute(self, operator, research_run_id):
        self.operator = operator
        self.research_run_id = research_run_id
        claim = command_claim()
        return PersistentCommitteeMemoArtifact(
            id="88888888-8888-4888-8888-888888888888",
            operator_id=operator.id,
            research_run_id=research_run_id,
            security_id=claim.security_id,
            as_of_cutoff=claim.as_of_cutoff,
            question_type_version=claim.question_type_version,
            workflow_config_version=claim.workflow_config_version,
            committee_id="99999999-9999-4999-8999-999999999999",
        )


class ReadinessThesisWorkflowFake:
    def execute(self, operator, research_run_id):
        self.operator = operator
        self.research_run_id = research_run_id
        claim = command_claim()
        return PersistentReadinessThesisArtifact(
            id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            operator_id=operator.id,
            research_run_id=research_run_id,
            security_id=claim.security_id,
            as_of_cutoff=claim.as_of_cutoff,
            question_type_version=claim.question_type_version,
            workflow_config_version=claim.workflow_config_version,
            committee_id="99999999-9999-4999-8999-999999999999",
            committee_memo_id="88888888-8888-4888-8888-888888888888",
            readiness_gate_result_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        )


class StaticStageWorkflowFake:
    def __init__(self, *, artifact=None, error: Exception | None = None) -> None:
        self.artifact = artifact
        self.error = error

    def execute(self, operator, research_run_id):
        if self.error is not None:
            raise self.error
        return self.artifact


class UnavailableResearchRunRepository:
    def get(self, operator_id: str, run_id: str):
        raise EvidenceStorageError("research run store unavailable")


def command_claim() -> CommitteeCommandClaim:
    return CommitteeCommandClaim(
        command_id="11111111-1111-4111-8111-111111111111",
        operator_id="027d7f1b-d928-48d9-b6c8-f10d3c7ba792",
        security_id="22222222-2222-4222-8222-222222222222",
        question_type_version=("biotech_moonshot_catalyst_assessment.v1"),
        workflow_config_version="biotech-moonshot-catalyst-v1",
        as_of_cutoff=datetime(2026, 5, 6, 23, 59, 59, tzinfo=UTC),
        operator_focus="Review financing through catalyst.",
        attempt_id="44444444-4444-4444-8444-444444444444",
        attempt_number=1,
        lease_token="55555555-5555-4555-8555-555555555555",
        next_stage="research_run",
        completed_stages=(),
        research_run_id=None,
    )


def downstream_claim(stage: str) -> CommitteeCommandClaim:
    completed_stages = (
        "research_run",
        "evidence_bundle",
        "valuation_snapshot",
        "grader_committee",
    )
    if stage == "readiness_thesis":
        completed_stages += ("committee_memo",)
    return replace(
        command_claim(),
        next_stage=stage,
        completed_stages=completed_stages,
        research_run_id=RUN_ID,
    )


def downstream_worker(
    claim: CommitteeCommandClaim,
    workflow: StaticStageWorkflowFake,
) -> tuple[CommandStoreFake, PersistentCommitteeWorker]:
    stage = (
        PersistentCommitteeMemoStage(
            research_run_repository=_research_run_repository(claim),
            workflow=workflow,
        )
        if claim.next_stage == "committee_memo"
        else PersistentReadinessThesisStage(
            research_run_repository=_research_run_repository(claim),
            workflow=workflow,
        )
    )
    jobs = CommandStoreFake(claim)
    return jobs, PersistentCommitteeWorker(
        worker_id="iros-committee-worker-1",
        commands=jobs,
        research_run_stage=ResearchRunStageFake(),
        evidence_bundle_stage=EvidenceBundleStageFake(),
        committee_memo_stage=(stage if claim.next_stage == "committee_memo" else None),
        readiness_thesis_stage=(
            stage if claim.next_stage == "readiness_thesis" else None
        ),
    )


def _research_run_repository(claim: CommitteeCommandClaim):
    return SimpleNamespace(
        get=lambda operator_id, research_run_id: SimpleNamespace(
            id=research_run_id,
            operator_id=operator_id,
            security_id=claim.security_id,
            as_of_cutoff=claim.as_of_cutoff,
            question_type_version=claim.question_type_version,
            workflow_config_version=claim.workflow_config_version,
        )
    )


class PersistentCommitteeWorkerTests(unittest.TestCase):
    def assert_downstream_failure(
        self,
        claim: CommitteeCommandClaim,
        workflow: StaticStageWorkflowFake,
        *,
        error_code: str,
        retryable: bool,
    ) -> None:
        jobs, worker = downstream_worker(claim, workflow)

        self.assertTrue(worker.run_once())
        self.assertEqual(jobs.checkpoints, [])
        self.assertEqual(
            jobs.failures,
            [(claim, claim.next_stage, error_code, retryable)],
        )

    def test_readiness_thesis_stage_rejects_drifted_artifact_identity(
        self,
    ) -> None:
        claim = downstream_claim("readiness_thesis")
        artifact = replace(
            ReadinessThesisWorkflowFake().execute(
                SimpleNamespace(id=claim.operator_id),
                RUN_ID,
            ),
            workflow_config_version="other-workflow-v1",
        )
        self.assert_downstream_failure(
            claim,
            StaticStageWorkflowFake(artifact=artifact),
            error_code="readiness_thesis_identity_mismatch",
            retryable=False,
        )

    def test_readiness_thesis_stage_rejects_invalid_linkage_uuids(self) -> None:
        claim = downstream_claim("readiness_thesis")
        valid_artifact = ReadinessThesisWorkflowFake().execute(
            SimpleNamespace(id=claim.operator_id),
            RUN_ID,
        )
        for field in (
            "committee_id",
            "committee_memo_id",
            "readiness_gate_result_id",
        ):
            with self.subTest(field=field):
                self.assert_downstream_failure(
                    claim,
                    StaticStageWorkflowFake(
                        artifact=replace(
                            valid_artifact,
                            **{field: "not-a-linkage-uuid"},
                        ),
                    ),
                    error_code="readiness_thesis_identity_invalid",
                    retryable=False,
                )

    def test_readiness_thesis_stage_rejects_invalid_artifact_uuid(self) -> None:
        claim = downstream_claim("readiness_thesis")
        artifact = replace(
            ReadinessThesisWorkflowFake().execute(
                SimpleNamespace(id=claim.operator_id),
                RUN_ID,
            ),
            id="not-a-thesis-result-uuid",
        )
        self.assert_downstream_failure(
            claim,
            StaticStageWorkflowFake(artifact=artifact),
            error_code="readiness_thesis_identity_invalid",
            retryable=False,
        )

    def test_readiness_thesis_storage_failure_is_retryable(self) -> None:
        claim = downstream_claim("readiness_thesis")
        self.assert_downstream_failure(
            claim,
            StaticStageWorkflowFake(
                error=EvidenceStorageError("thesis store unavailable"),
            ),
            error_code="readiness_thesis_persistence_failed",
            retryable=True,
        )

    def test_readiness_thesis_domain_failure_is_not_retryable(self) -> None:
        claim = downstream_claim("readiness_thesis")
        self.assert_downstream_failure(
            claim,
            StaticStageWorkflowFake(
                error=ReadinessAndThesisError(
                    "readiness contract invalid",
                ),
            ),
            error_code="readiness_thesis_contract_invalid",
            retryable=False,
        )

    def test_committee_memo_stage_rejects_drifted_artifact_identity(self) -> None:
        claim = downstream_claim("committee_memo")
        artifact = replace(
            CommitteeMemoWorkflowFake().execute(
                SimpleNamespace(id=claim.operator_id),
                RUN_ID,
            ),
            security_id="33333333-3333-4333-8333-333333333333",
        )
        self.assert_downstream_failure(
            claim,
            StaticStageWorkflowFake(artifact=artifact),
            error_code="committee_memo_identity_mismatch",
            retryable=False,
        )

    def test_committee_memo_stage_rejects_invalid_committee_linkage(self) -> None:
        claim = downstream_claim("committee_memo")
        artifact = replace(
            CommitteeMemoWorkflowFake().execute(
                SimpleNamespace(id=claim.operator_id),
                RUN_ID,
            ),
            committee_id="not-a-committee-uuid",
        )
        self.assert_downstream_failure(
            claim,
            StaticStageWorkflowFake(artifact=artifact),
            error_code="committee_memo_identity_invalid",
            retryable=False,
        )

    def test_committee_memo_stage_rejects_invalid_artifact_uuid(self) -> None:
        claim = downstream_claim("committee_memo")
        artifact = replace(
            CommitteeMemoWorkflowFake().execute(
                SimpleNamespace(id=claim.operator_id),
                RUN_ID,
            ),
            id="not-a-memo-uuid",
        )
        self.assert_downstream_failure(
            claim,
            StaticStageWorkflowFake(artifact=artifact),
            error_code="committee_memo_identity_invalid",
            retryable=False,
        )

    def test_committee_memo_storage_failure_is_retryable(self) -> None:
        claim = downstream_claim("committee_memo")
        self.assert_downstream_failure(
            claim,
            StaticStageWorkflowFake(
                error=EvidenceStorageError("memo store unavailable"),
            ),
            error_code="committee_memo_persistence_failed",
            retryable=True,
        )

    def test_committee_memo_domain_failure_is_not_retryable(self) -> None:
        claim = downstream_claim("committee_memo")
        self.assert_downstream_failure(
            claim,
            StaticStageWorkflowFake(
                error=CommitteeMemoError("memo contract invalid"),
            ),
            error_code="committee_memo_contract_invalid",
            retryable=False,
        )

    def test_claimed_command_persists_readiness_thesis_before_checkpoint(
        self,
    ) -> None:
        claim = replace(
            command_claim(),
            next_stage="readiness_thesis",
            completed_stages=(
                "research_run",
                "evidence_bundle",
                "valuation_snapshot",
                "grader_committee",
                "committee_memo",
            ),
            research_run_id=RUN_ID,
        )
        jobs = CommandStoreFake(claim)
        workflow = ReadinessThesisWorkflowFake()
        worker = PersistentCommitteeWorker(
            worker_id="iros-committee-worker-1",
            commands=jobs,
            research_run_stage=ResearchRunStageFake(),
            evidence_bundle_stage=EvidenceBundleStageFake(),
            readiness_thesis_stage=PersistentReadinessThesisStage(
                research_run_repository=SimpleNamespace(
                    get=lambda operator_id, research_run_id: SimpleNamespace(
                        id=research_run_id,
                        operator_id=operator_id,
                        security_id=claim.security_id,
                        as_of_cutoff=claim.as_of_cutoff,
                        question_type_version=claim.question_type_version,
                        workflow_config_version=claim.workflow_config_version,
                    )
                ),
                workflow=workflow,
            ),
        )

        self.assertTrue(worker.run_once())

        self.assertEqual(workflow.operator.id, claim.operator_id)
        self.assertEqual(workflow.research_run_id, claim.research_run_id)
        self.assertEqual(
            jobs.checkpoints,
            [
                (
                    claim,
                    "readiness_thesis",
                    "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                )
            ],
        )
        self.assertEqual(jobs.failures, [])

    def test_claimed_command_persists_committee_memo_before_checkpoint(
        self,
    ) -> None:
        claim = replace(
            command_claim(),
            next_stage="committee_memo",
            completed_stages=(
                "research_run",
                "evidence_bundle",
                "valuation_snapshot",
                "grader_committee",
            ),
            research_run_id=RUN_ID,
        )
        jobs = CommandStoreFake(claim)
        workflow = CommitteeMemoWorkflowFake()
        worker = PersistentCommitteeWorker(
            worker_id="iros-committee-worker-1",
            commands=jobs,
            research_run_stage=ResearchRunStageFake(),
            evidence_bundle_stage=EvidenceBundleStageFake(),
            committee_memo_stage=PersistentCommitteeMemoStage(
                research_run_repository=SimpleNamespace(
                    get=lambda operator_id, research_run_id: SimpleNamespace(
                        id=research_run_id,
                        operator_id=operator_id,
                        security_id=claim.security_id,
                        as_of_cutoff=claim.as_of_cutoff,
                        question_type_version=claim.question_type_version,
                        workflow_config_version=claim.workflow_config_version,
                    )
                ),
                workflow=workflow,
            ),
        )

        self.assertTrue(worker.run_once())

        self.assertEqual(workflow.operator.id, claim.operator_id)
        self.assertEqual(workflow.research_run_id, claim.research_run_id)
        self.assertEqual(
            jobs.checkpoints,
            [
                (
                    claim,
                    "committee_memo",
                    "88888888-8888-4888-8888-888888888888",
                )
            ],
        )
        self.assertEqual(jobs.failures, [])

    def test_long_stage_renews_lease_before_checkpoint(self) -> None:
        claim = command_claim()
        jobs = CommandStoreFake(claim)
        worker = PersistentCommitteeWorker(
            worker_id="iros-committee-worker-1",
            commands=jobs,
            research_run_stage=SlowResearchRunStageFake(),
            evidence_bundle_stage=EvidenceBundleStageFake(),
            heartbeat_interval_seconds=0.001,
        )

        self.assertTrue(worker.run_once())

        self.assertGreaterEqual(len(jobs.renewals), 1)
        self.assertEqual(jobs.checkpoints, [(claim, "research_run", RUN_ID)])
        self.assertEqual(jobs.failures, [])

    def test_heartbeat_failure_fails_closed_without_checkpoint(self) -> None:
        claim = command_claim()
        jobs = HeartbeatFailingCommandStoreFake(claim)
        worker = PersistentCommitteeWorker(
            worker_id="iros-committee-worker-1",
            commands=jobs,
            research_run_stage=SlowResearchRunStageFake(),
            evidence_bundle_stage=EvidenceBundleStageFake(),
            heartbeat_interval_seconds=0.001,
        )

        self.assertTrue(worker.run_once())

        self.assertEqual(jobs.checkpoints, [])
        self.assertEqual(jobs.failures, [])

    def test_valuation_snapshot_storage_failure_is_retryable(self) -> None:
        bundle_repository = InMemoryEvidenceBundleRepository()
        valuation_repository = InMemoryValuationSnapshotRepository()
        claim = replace(
            command_claim(),
            next_stage="valuation_snapshot",
            completed_stages=("research_run", "evidence_bundle"),
            research_run_id=RUN_ID,
        )
        jobs = CommandStoreFake(claim)
        worker = PersistentCommitteeWorker(
            worker_id="iros-committee-worker-1",
            commands=jobs,
            research_run_stage=ResearchRunStageFake(),
            evidence_bundle_stage=EvidenceBundleStageFake(),
            valuation_snapshot_stage=PersistentValuationSnapshotStage(
                research_run_repository=UnavailableResearchRunRepository(),
                evidence_bundle_repository=bundle_repository,
                valuation_snapshot_repository=valuation_repository,
                workflow=ValuationSnapshotWorkflow(
                    evidence_bundle_repository=bundle_repository,
                    valuation_snapshot_repository=valuation_repository,
                    market_calendar=FixedCalendar(),
                    input_source=FixedValuationSource(input_candidate()),
                    clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
                ),
            ),
        )

        self.assertTrue(worker.run_once())

        self.assertEqual(jobs.checkpoints, [])
        self.assertEqual(
            jobs.failures,
            [
                (
                    claim,
                    "valuation_snapshot",
                    "valuation_snapshot_persistence_failed",
                    True,
                )
            ],
        )

    def test_valuation_snapshot_stage_reuses_persisted_snapshot_on_retry(
        self,
    ) -> None:
        run_repository = InMemoryResearchRunRepository()
        run_repository.save(eligible_run())
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        valuation_repository = InMemoryValuationSnapshotRepository()
        source = FixedValuationSource(input_candidate())
        workflow = ValuationSnapshotWorkflow(
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=valuation_repository,
            market_calendar=FixedCalendar(),
            input_source=source,
            clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
        )
        stage = PersistentValuationSnapshotStage(
            research_run_repository=run_repository,
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=valuation_repository,
            workflow=workflow,
        )
        claim = replace(
            command_claim(),
            operator_id=OPERATOR_ID,
            security_id=SECURITY_ID,
            as_of_cutoff=CUTOFF,
            next_stage="valuation_snapshot",
            completed_stages=("research_run", "evidence_bundle"),
            research_run_id=FIXTURE_RUN_ID,
        )

        first_snapshot_id = stage.execute(claim)
        second_snapshot_id = stage.execute(claim)

        self.assertEqual(second_snapshot_id, first_snapshot_id)
        self.assertEqual(
            source.requests,
            [(bundle, SESSION)],
        )

    def test_valuation_snapshot_stage_routes_personal_contract_without_strict_reuse(
        self,
    ) -> None:
        run = replace(
            eligible_run(),
            question_type=PERSONAL_RESEARCH_QUESTION_TYPE,
            question_type_version=PERSONAL_RESEARCH_QUESTION_TYPE_VERSION,
            workflow_config_version=PERSONAL_RESEARCH_WORKFLOW_CONFIG_VERSION,
            thesis_contract_id=PERSONAL_RESEARCH_THESIS_CONTRACT_ID,
        )
        run_repository = InMemoryResearchRunRepository()
        run_repository.save(run)
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        valuation_repository = InMemoryValuationSnapshotRepository()
        strict_source = FixedValuationSource(input_candidate())
        personal_source = FixedValuationSource(personal_input_candidate())
        stage = PersistentValuationSnapshotStage(
            research_run_repository=run_repository,
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=valuation_repository,
            workflow=ValuationSnapshotWorkflow(
                evidence_bundle_repository=bundle_repository,
                valuation_snapshot_repository=valuation_repository,
                market_calendar=FixedCalendar(),
                input_source=strict_source,
                clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
            ),
            personal_research_workflow=PersonalResearchValuationSnapshotWorkflow(
                evidence_bundle_repository=bundle_repository,
                valuation_snapshot_repository=valuation_repository,
                market_calendar=FixedCalendar(),
                input_source=personal_source,
                clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
            ),
        )
        claim = replace(
            command_claim(),
            operator_id=OPERATOR_ID,
            security_id=SECURITY_ID,
            question_type_version=PERSONAL_RESEARCH_QUESTION_TYPE_VERSION,
            workflow_config_version=PERSONAL_RESEARCH_WORKFLOW_CONFIG_VERSION,
            as_of_cutoff=CUTOFF,
            next_stage="valuation_snapshot",
            completed_stages=("research_run", "evidence_bundle"),
            research_run_id=FIXTURE_RUN_ID,
        )

        snapshot_id = stage.execute(claim)
        snapshot = valuation_repository.get_for_run(OPERATOR_ID, FIXTURE_RUN_ID)

        self.assertEqual(snapshot.id, snapshot_id)
        self.assertEqual(
            snapshot.contract_version,
            "valuation_snapshot.personal_research.v1",
        )
        self.assertEqual(strict_source.requests, [])
        self.assertEqual(personal_source.requests, [(bundle, SESSION)])

    def test_valuation_snapshot_stage_classifies_massive_source_failures(self) -> None:
        run = replace(
            eligible_run(),
            question_type=PERSONAL_RESEARCH_QUESTION_TYPE,
            question_type_version=PERSONAL_RESEARCH_QUESTION_TYPE_VERSION,
            workflow_config_version=PERSONAL_RESEARCH_WORKFLOW_CONFIG_VERSION,
            thesis_contract_id=PERSONAL_RESEARCH_THESIS_CONTRACT_ID,
        )
        run_repository = InMemoryResearchRunRepository()
        run_repository.save(run)
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(materialized_bundle())
        claim = replace(
            command_claim(),
            operator_id=OPERATOR_ID,
            security_id=SECURITY_ID,
            question_type_version=PERSONAL_RESEARCH_QUESTION_TYPE_VERSION,
            workflow_config_version=PERSONAL_RESEARCH_WORKFLOW_CONFIG_VERSION,
            as_of_cutoff=CUTOFF,
            next_stage="valuation_snapshot",
            completed_stages=("research_run", "evidence_bundle"),
            research_run_id=FIXTURE_RUN_ID,
        )
        cases = (
            (
                MassiveRateLimitError(47),
                "valuation_market_source_rate_limited",
                True,
            ),
            (
                MassiveValuationError("invalid provider response"),
                "valuation_market_source_invalid",
                False,
            ),
        )

        for error, expected_code, retryable in cases:
            with self.subTest(expected_code):
                stage = PersistentValuationSnapshotStage(
                    research_run_repository=run_repository,
                    evidence_bundle_repository=bundle_repository,
                    valuation_snapshot_repository=(
                        InMemoryValuationSnapshotRepository()
                    ),
                    workflow=FailingValuationWorkflow(
                        AssertionError("strict workflow must not run")
                    ),
                    personal_research_workflow=FailingValuationWorkflow(error),
                )
                with self.assertRaises(ResearchRunStageError) as caught:
                    stage.execute(claim)
                self.assertEqual(caught.exception.error_code, expected_code)
                self.assertEqual(caught.exception.retryable, retryable)

    def test_valuation_snapshot_stage_rejects_invalid_persisted_bundle_identity(
        self,
    ) -> None:
        run_repository = InMemoryResearchRunRepository()
        run_repository.save(eligible_run())
        bundle = replace(materialized_bundle(), id="not-a-bundle-uuid")
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        valuation_repository = InMemoryValuationSnapshotRepository()
        source = FixedValuationSource(input_candidate())
        workflow = ValuationSnapshotWorkflow(
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=valuation_repository,
            market_calendar=FixedCalendar(),
            input_source=source,
            clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
        )
        claim = replace(
            command_claim(),
            operator_id=OPERATOR_ID,
            security_id=SECURITY_ID,
            as_of_cutoff=CUTOFF,
            next_stage="valuation_snapshot",
            completed_stages=("research_run", "evidence_bundle"),
            research_run_id=FIXTURE_RUN_ID,
        )
        jobs = CommandStoreFake(claim)
        worker = PersistentCommitteeWorker(
            worker_id="iros-committee-worker-1",
            commands=jobs,
            research_run_stage=ResearchRunStageFake(),
            evidence_bundle_stage=EvidenceBundleStageFake(),
            valuation_snapshot_stage=PersistentValuationSnapshotStage(
                research_run_repository=run_repository,
                evidence_bundle_repository=bundle_repository,
                valuation_snapshot_repository=valuation_repository,
                workflow=workflow,
            ),
        )

        self.assertTrue(worker.run_once())

        self.assertEqual(source.requests, [])
        self.assertEqual(jobs.checkpoints, [])
        self.assertEqual(
            jobs.failures,
            [
                (
                    claim,
                    "valuation_snapshot",
                    "valuation_snapshot_evidence_bundle_identity_invalid",
                    False,
                )
            ],
        )

    def test_valuation_snapshot_stage_fails_closed_without_persisted_bundle(
        self,
    ) -> None:
        run_repository = InMemoryResearchRunRepository()
        run_repository.save(eligible_run())
        bundle_repository = InMemoryEvidenceBundleRepository()
        valuation_repository = InMemoryValuationSnapshotRepository()
        source = FixedValuationSource(input_candidate())
        workflow = ValuationSnapshotWorkflow(
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=valuation_repository,
            market_calendar=FixedCalendar(),
            input_source=source,
            clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
        )
        claim = replace(
            command_claim(),
            operator_id=OPERATOR_ID,
            security_id=SECURITY_ID,
            as_of_cutoff=CUTOFF,
            next_stage="valuation_snapshot",
            completed_stages=("research_run", "evidence_bundle"),
            research_run_id=FIXTURE_RUN_ID,
        )
        jobs = CommandStoreFake(claim)
        worker = PersistentCommitteeWorker(
            worker_id="iros-committee-worker-1",
            commands=jobs,
            research_run_stage=ResearchRunStageFake(),
            evidence_bundle_stage=EvidenceBundleStageFake(),
            valuation_snapshot_stage=PersistentValuationSnapshotStage(
                research_run_repository=run_repository,
                evidence_bundle_repository=bundle_repository,
                valuation_snapshot_repository=valuation_repository,
                workflow=workflow,
            ),
        )

        self.assertTrue(worker.run_once())

        self.assertEqual(source.requests, [])
        self.assertEqual(jobs.checkpoints, [])
        self.assertEqual(
            jobs.failures,
            [
                (
                    claim,
                    "valuation_snapshot",
                    "valuation_snapshot_evidence_bundle_missing",
                    False,
                )
            ],
        )

    def test_claimed_command_persists_valuation_snapshot_before_checkpoint(
        self,
    ) -> None:
        run_repository = InMemoryResearchRunRepository()
        run_repository.save(eligible_run())
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        valuation_repository = InMemoryValuationSnapshotRepository()
        workflow = ValuationSnapshotWorkflow(
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=valuation_repository,
            market_calendar=FixedCalendar(),
            input_source=FixedValuationSource(input_candidate()),
            clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
        )
        claim = replace(
            command_claim(),
            operator_id=OPERATOR_ID,
            security_id=SECURITY_ID,
            as_of_cutoff=CUTOFF,
            next_stage="valuation_snapshot",
            completed_stages=("research_run", "evidence_bundle"),
            research_run_id=FIXTURE_RUN_ID,
        )
        jobs = CommandStoreFake(claim)
        stage = PersistentValuationSnapshotStage(
            research_run_repository=run_repository,
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=valuation_repository,
            workflow=workflow,
        )
        worker = PersistentCommitteeWorker(
            worker_id="iros-committee-worker-1",
            commands=jobs,
            research_run_stage=ResearchRunStageFake(),
            evidence_bundle_stage=EvidenceBundleStageFake(),
            valuation_snapshot_stage=stage,
        )

        self.assertTrue(worker.run_once())

        persisted = valuation_repository.get_for_run(
            claim.operator_id,
            FIXTURE_RUN_ID,
        )
        self.assertIsNotNone(persisted)
        assert persisted is not None
        self.assertEqual(
            jobs.checkpoints,
            [(claim, "valuation_snapshot", persisted.id)],
        )
        self.assertEqual(jobs.failures, [])

    def test_claimed_command_persists_evidence_bundle_before_checkpoint(
        self,
    ) -> None:
        claim = replace(
            command_claim(),
            next_stage="evidence_bundle",
            completed_stages=("research_run",),
            research_run_id=RUN_ID,
        )
        jobs = CommandStoreFake(claim)
        workflow = EvidenceBundleWorkflowFake()
        stage = PersistentEvidenceBundleStage(workflow)
        worker = PersistentCommitteeWorker(
            worker_id="iros-committee-worker-1",
            commands=jobs,
            research_run_stage=ResearchRunStageFake(),
            evidence_bundle_stage=stage,
        )

        self.assertTrue(worker.run_once())

        self.assertEqual(workflow.operator.id, claim.operator_id)
        self.assertEqual(workflow.research_run_id, RUN_ID)
        self.assertEqual(
            jobs.checkpoints,
            [(claim, "evidence_bundle", BUNDLE_ID)],
        )
        self.assertEqual(jobs.failures, [])

    def test_worker_rejects_claim_for_unimplemented_next_stage(self) -> None:
        claim = replace(
            command_claim(),
            next_stage="valuation_snapshot",
            completed_stages=("research_run", "evidence_bundle"),
            research_run_id=RUN_ID,
        )
        jobs = CommandStoreFake(claim)
        stage = ResearchRunStageFake()
        worker = PersistentCommitteeWorker(
            worker_id="iros-committee-worker-1",
            commands=jobs,
            research_run_stage=stage,
            evidence_bundle_stage=EvidenceBundleStageFake(),
        )

        self.assertTrue(worker.run_once())

        self.assertFalse(hasattr(stage, "claim"))
        self.assertEqual(jobs.checkpoints, [])
        self.assertEqual(
            jobs.failures,
            [
                (
                    claim,
                    "valuation_snapshot",
                    "worker_stage_unavailable",
                    False,
                )
            ],
        )

    def test_research_run_stage_uses_fixed_contract_and_authenticated_owner(
        self,
    ) -> None:
        workflow = ResearchRunWorkflowFake()
        stage = PersistentResearchRunStage(workflow)
        claim = command_claim()

        run_id = stage.execute(claim)

        self.assertEqual(run_id, RUN_ID)
        self.assertEqual(workflow.operator.id, claim.operator_id)
        self.assertEqual(
            workflow.payload,
            {
                "question_type": ("biotech_moonshot_catalyst_assessment"),
                "security_id": claim.security_id,
                "as_of_cutoff": claim.as_of_cutoff.isoformat(),
                "workflow_config_version": ("biotech-moonshot-catalyst-v1"),
                "operator_focus": claim.operator_focus,
            },
        )

    def test_research_run_stage_routes_personal_research_contract(self) -> None:
        workflow = PersonalResearchRunWorkflowFake()
        stage = PersistentResearchRunStage(workflow)
        claim = replace(
            command_claim(),
            question_type_version=(
                "biotech_moonshot_catalyst_personal_research_assessment.v1"
            ),
            workflow_config_version=(
                "biotech-moonshot-catalyst-personal-research-v1"
            ),
        )

        run_id = stage.execute(claim)

        self.assertEqual(run_id, RUN_ID)
        self.assertEqual(
            workflow.payload["question_type"],
            "biotech_moonshot_catalyst_personal_research_assessment",
        )
        self.assertEqual(
            workflow.payload["workflow_config_version"],
            "biotech-moonshot-catalyst-personal-research-v1",
        )

    def test_claimed_command_persists_research_run_before_checkpoint(
        self,
    ) -> None:
        claim = command_claim()
        jobs = CommandStoreFake(claim)
        stage = ResearchRunStageFake()
        worker = PersistentCommitteeWorker(
            worker_id="iros-committee-worker-1",
            commands=jobs,
            research_run_stage=stage,
            evidence_bundle_stage=EvidenceBundleStageFake(),
        )

        processed = worker.run_once()

        self.assertTrue(processed)
        self.assertEqual(jobs.worker_id, "iros-committee-worker-1")
        self.assertEqual(stage.claim, claim)
        self.assertEqual(
            jobs.checkpoints,
            [(claim, "research_run", RUN_ID)],
        )
        self.assertEqual(jobs.failures, [])

    def test_research_run_stage_failure_is_bounded_and_retryable(self) -> None:
        claim = command_claim()
        jobs = CommandStoreFake(claim)
        worker = PersistentCommitteeWorker(
            worker_id="iros-committee-worker-1",
            commands=jobs,
            research_run_stage=FailingResearchRunStageFake(),
            evidence_bundle_stage=EvidenceBundleStageFake(),
        )

        self.assertTrue(worker.run_once())

        self.assertEqual(jobs.checkpoints, [])
        self.assertEqual(
            jobs.failures,
            [
                (
                    claim,
                    "research_run",
                    "research_run_persistence_failed",
                    True,
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()

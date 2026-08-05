from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace

from investment_research_os.research_runs import AuthenticatedOperator
from tests.test_persistent_committee_worker import (
    CommandStoreFake,
    EvidenceBundleStageFake,
    ResearchRunStageFake,
    command_claim,
)
from workers.research_committee.worker import (
    PersistentCommitteeWorker,
    PersistentGraderCommitteeArtifact,
    PersistentGraderCommitteeStage,
)
from workers.sec.storage import EvidenceStorageError


COMMITTEE_ID = "88888888-8888-4888-8888-888888888888"


class GraderCommitteeStageFake:
    def execute(self, claim):
        self.claim = claim
        return COMMITTEE_ID


class ResearchRunRepositoryFake:
    def __init__(self, run) -> None:
        self.run = run

    def get(self, operator_id: str, run_id: str):
        self.request = (operator_id, run_id)
        return self.run


class GraderCommitteeBoundaryFake:
    def execute(
        self,
        operator: AuthenticatedOperator,
        research_run_id: str,
    ) -> PersistentGraderCommitteeArtifact:
        self.request = (operator, research_run_id)
        claim = command_claim()
        return PersistentGraderCommitteeArtifact(
            id=COMMITTEE_ID,
            operator_id=operator.id,
            research_run_id=research_run_id,
            security_id=claim.security_id,
            as_of_cutoff=claim.as_of_cutoff,
            question_type_version=claim.question_type_version,
            workflow_config_version=claim.workflow_config_version,
        )


class UnexpectedGraderCommitteeBoundary:
    def execute(self, operator, research_run_id):
        raise AssertionError("grader boundary must not execute")


class FixedGraderCommitteeBoundary:
    def __init__(self, artifact: PersistentGraderCommitteeArtifact) -> None:
        self.artifact = artifact

    def execute(self, operator, research_run_id):
        return self.artifact


class UnavailableGraderCommitteeBoundary:
    def execute(self, operator, research_run_id):
        raise EvidenceStorageError("grader store unavailable")


class PersistentGraderCommitteeStageTests(unittest.TestCase):
    def test_worker_checkpoints_persisted_grader_committee_artifact(self) -> None:
        claim = replace(
            command_claim(),
            next_stage="grader_committee",
            completed_stages=(
                "research_run",
                "evidence_bundle",
                "valuation_snapshot",
            ),
            research_run_id="66666666-6666-4666-8666-666666666666",
        )
        jobs = CommandStoreFake(claim)
        stage = GraderCommitteeStageFake()
        worker = PersistentCommitteeWorker(
            worker_id="iros-committee-worker-1",
            commands=jobs,
            research_run_stage=ResearchRunStageFake(),
            evidence_bundle_stage=EvidenceBundleStageFake(),
            grader_committee_stage=stage,
        )

        self.assertTrue(worker.run_once())

        self.assertEqual(stage.claim, claim)
        self.assertEqual(
            jobs.checkpoints,
            [(claim, "grader_committee", COMMITTEE_ID)],
        )
        self.assertEqual(jobs.failures, [])

    def test_stage_returns_persisted_committee_for_exact_run_identity(self) -> None:
        claim = replace(
            command_claim(),
            next_stage="grader_committee",
            completed_stages=(
                "research_run",
                "evidence_bundle",
                "valuation_snapshot",
            ),
            research_run_id="66666666-6666-4666-8666-666666666666",
        )
        run = SimpleNamespace(
            id=claim.research_run_id,
            operator_id=claim.operator_id,
            security_id=claim.security_id,
            as_of_cutoff=claim.as_of_cutoff,
            question_type_version=claim.question_type_version,
            workflow_config_version=claim.workflow_config_version,
        )
        runs = ResearchRunRepositoryFake(run)
        boundary = GraderCommitteeBoundaryFake()
        stage = PersistentGraderCommitteeStage(
            research_run_repository=runs,
            workflow=boundary,
        )

        artifact_id = stage.execute(claim)

        self.assertEqual(artifact_id, COMMITTEE_ID)
        self.assertEqual(
            runs.request,
            (claim.operator_id, claim.research_run_id),
        )
        self.assertEqual(boundary.request[0].id, claim.operator_id)
        self.assertEqual(boundary.request[1], claim.research_run_id)

    def test_stage_rejects_drifted_persisted_research_run_identity(self) -> None:
        claim = replace(
            command_claim(),
            next_stage="grader_committee",
            completed_stages=(
                "research_run",
                "evidence_bundle",
                "valuation_snapshot",
            ),
            research_run_id="66666666-6666-4666-8666-666666666666",
        )
        matching_identity = {
            "id": claim.research_run_id,
            "operator_id": claim.operator_id,
            "security_id": claim.security_id,
            "as_of_cutoff": claim.as_of_cutoff,
            "question_type_version": claim.question_type_version,
            "workflow_config_version": claim.workflow_config_version,
        }
        drifted_values = {
            "id": "99999999-9999-4999-8999-999999999999",
            "operator_id": "99999999-9999-4999-8999-999999999999",
            "security_id": "99999999-9999-4999-8999-999999999999",
            "as_of_cutoff": claim.as_of_cutoff.replace(year=2025),
            "question_type_version": ("biotech_moonshot_catalyst_assessment.v0"),
            "workflow_config_version": "biotech-moonshot-catalyst-v0",
        }

        for field, drifted_value in drifted_values.items():
            with self.subTest(field=field):
                identity = dict(matching_identity)
                identity[field] = drifted_value
                stage = PersistentGraderCommitteeStage(
                    research_run_repository=ResearchRunRepositoryFake(
                        SimpleNamespace(**identity)
                    ),
                    workflow=UnexpectedGraderCommitteeBoundary(),
                )

                with self.assertRaisesRegex(
                    RuntimeError,
                    "grader_committee_research_run_identity_mismatch",
                ):
                    stage.execute(claim)

    def test_stage_rejects_drifted_persisted_committee_identity(self) -> None:
        claim = replace(
            command_claim(),
            next_stage="grader_committee",
            completed_stages=(
                "research_run",
                "evidence_bundle",
                "valuation_snapshot",
            ),
            research_run_id="66666666-6666-4666-8666-666666666666",
        )
        run = SimpleNamespace(
            id=claim.research_run_id,
            operator_id=claim.operator_id,
            security_id=claim.security_id,
            as_of_cutoff=claim.as_of_cutoff,
            question_type_version=claim.question_type_version,
            workflow_config_version=claim.workflow_config_version,
        )
        matching_artifact = PersistentGraderCommitteeArtifact(
            id=COMMITTEE_ID,
            operator_id=claim.operator_id,
            research_run_id=claim.research_run_id,
            security_id=claim.security_id,
            as_of_cutoff=claim.as_of_cutoff,
            question_type_version=claim.question_type_version,
            workflow_config_version=claim.workflow_config_version,
        )
        drifted_values = {
            "operator_id": "99999999-9999-4999-8999-999999999999",
            "research_run_id": "99999999-9999-4999-8999-999999999999",
            "security_id": "99999999-9999-4999-8999-999999999999",
            "as_of_cutoff": claim.as_of_cutoff.replace(year=2025),
            "question_type_version": ("biotech_moonshot_catalyst_assessment.v0"),
            "workflow_config_version": "biotech-moonshot-catalyst-v0",
        }

        for field, drifted_value in drifted_values.items():
            with self.subTest(field=field):
                stage = PersistentGraderCommitteeStage(
                    research_run_repository=ResearchRunRepositoryFake(run),
                    workflow=FixedGraderCommitteeBoundary(
                        replace(
                            matching_artifact,
                            **{field: drifted_value},
                        )
                    ),
                )

                with self.assertRaisesRegex(
                    RuntimeError,
                    "grader_committee_identity_mismatch",
                ):
                    stage.execute(claim)

    def test_worker_classifies_grader_committee_persistence_failure(self) -> None:
        claim = replace(
            command_claim(),
            next_stage="grader_committee",
            completed_stages=(
                "research_run",
                "evidence_bundle",
                "valuation_snapshot",
            ),
            research_run_id="66666666-6666-4666-8666-666666666666",
        )
        run = SimpleNamespace(
            id=claim.research_run_id,
            operator_id=claim.operator_id,
            security_id=claim.security_id,
            as_of_cutoff=claim.as_of_cutoff,
            question_type_version=claim.question_type_version,
            workflow_config_version=claim.workflow_config_version,
        )
        jobs = CommandStoreFake(claim)
        worker = PersistentCommitteeWorker(
            worker_id="iros-committee-worker-1",
            commands=jobs,
            research_run_stage=ResearchRunStageFake(),
            evidence_bundle_stage=EvidenceBundleStageFake(),
            grader_committee_stage=PersistentGraderCommitteeStage(
                research_run_repository=ResearchRunRepositoryFake(run),
                workflow=UnavailableGraderCommitteeBoundary(),
            ),
        )

        self.assertTrue(worker.run_once())

        self.assertEqual(jobs.checkpoints, [])
        self.assertEqual(
            jobs.failures,
            [
                (
                    claim,
                    "grader_committee",
                    "grader_committee_persistence_failed",
                    True,
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from datetime import UTC, datetime
import unittest
from uuid import NAMESPACE_URL, uuid5

from workers.research_committee.storage import STAGES
from workers.research_committee.worker import (
    CommitteeCommandClaim,
    PersistentCommitteeWorker,
)
from workers.sec.storage import EvidenceStorageError


OPERATOR_ID = "027d7f1b-d928-48d9-b6c8-f10d3c7ba792"
COMMAND_ID = "11111111-1111-4111-8111-111111111111"
ATTEMPT_ID = "44444444-4444-4444-8444-444444444444"
LEASE_TOKEN = "55555555-5555-4555-8555-555555555555"
QUESTION_VERSION = "biotech_moonshot_catalyst_assessment.v1"
WORKFLOW_VERSION = "biotech-moonshot-catalyst-v1"
CUTOFF = datetime(2026, 5, 6, 23, 59, 59, tzinfo=UTC)


def stable_uuid(value: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"iros-worker-e2e:{value}"))


class RestartableCommandStore:
    def __init__(
        self,
        security_id: str,
        *,
        fail_checkpoint_once_at: str | None = None,
    ) -> None:
        self.security_id = security_id
        self.fail_checkpoint_once_at = fail_checkpoint_once_at
        self.completed: list[str] = []
        self.checkpoints: list[tuple[str, str]] = []
        self.failures: list[tuple[str, str, bool]] = []

    def claim_next(self, worker_id: str) -> CommitteeCommandClaim | None:
        if len(self.completed) == len(STAGES):
            return None
        stage = STAGES[len(self.completed)]
        research_run_id = (
            None if not self.completed else stable_uuid(f"{self.security_id}:run")
        )
        return CommitteeCommandClaim(
            command_id=COMMAND_ID,
            operator_id=OPERATOR_ID,
            security_id=self.security_id,
            capture_id="33333333-3333-4333-8333-333333333333",
            capture_revision=1,
            capture_content_hash="3" * 64,
            question_type_version=QUESTION_VERSION,
            workflow_config_version=WORKFLOW_VERSION,
            as_of_cutoff=CUTOFF,
            operator_focus=None,
            attempt_id=ATTEMPT_ID,
            attempt_number=1,
            lease_token=LEASE_TOKEN,
            next_stage=stage,
            completed_stages=tuple(self.completed),
            research_run_id=research_run_id,
        )

    def renew_lease(self, claim: CommitteeCommandClaim) -> None:
        return None

    def checkpoint(
        self,
        claim: CommitteeCommandClaim,
        *,
        stage: str,
        artifact_id: str,
    ) -> None:
        if self.fail_checkpoint_once_at == stage:
            self.fail_checkpoint_once_at = None
            raise EvidenceStorageError("simulated checkpoint response loss")
        if stage != STAGES[len(self.completed)]:
            raise AssertionError("checkpoint order changed")
        self.completed.append(stage)
        self.checkpoints.append((stage, artifact_id))

    def fail(
        self,
        claim: CommitteeCommandClaim,
        *,
        stage: str,
        error_code: str,
        retryable: bool,
    ) -> None:
        self.failures.append((stage, error_code, retryable))


class IdempotentPersistentStage:
    def __init__(self, stage: str) -> None:
        self.stage = stage
        self.calls: list[tuple[str, str | None]] = []
        self.persisted_by_security: dict[str, str] = {}

    def execute(self, claim: CommitteeCommandClaim) -> str:
        self.calls.append((claim.security_id, claim.research_run_id))
        return self.persisted_by_security.setdefault(
            claim.security_id,
            stable_uuid(f"{claim.security_id}:{self.stage}"),
        )


def worker(
    store: RestartableCommandStore,
    stages: dict[str, IdempotentPersistentStage],
) -> PersistentCommitteeWorker:
    return PersistentCommitteeWorker(
        worker_id="iros-committee-worker-1",
        commands=store,
        research_run_stage=stages["research_run"],
        evidence_bundle_stage=stages["evidence_bundle"],
        valuation_snapshot_stage=stages["valuation_snapshot"],
        grader_committee_stage=stages["grader_committee"],
        committee_memo_stage=stages["committee_memo"],
        readiness_thesis_stage=stages["readiness_thesis"],
        heartbeat_interval_seconds=1,
    )


class PersistentCommitteeWorkerEndToEndTests(unittest.TestCase):
    def test_restart_after_every_stage_completes_one_ordered_chain(self) -> None:
        store = RestartableCommandStore(stable_uuid("platform-security"))
        stages = {stage: IdempotentPersistentStage(stage) for stage in STAGES}

        for expected_stage in STAGES:
            self.assertTrue(worker(store, stages).run_once())
            self.assertEqual(store.completed[-1], expected_stage)

        self.assertFalse(worker(store, stages).run_once())
        self.assertEqual(tuple(store.completed), STAGES)
        self.assertEqual([stage for stage, _ in store.checkpoints], list(STAGES))
        self.assertEqual(store.failures, [])
        self.assertTrue(all(len(stage.calls) == 1 for stage in stages.values()))

    def test_response_loss_after_persistence_reuses_same_artifact(self) -> None:
        store = RestartableCommandStore(
            stable_uuid("platform-security"),
            fail_checkpoint_once_at="committee_memo",
        )
        stages = {stage: IdempotentPersistentStage(stage) for stage in STAGES}

        for _ in STAGES[:4]:
            self.assertTrue(worker(store, stages).run_once())
        with self.assertRaisesRegex(
            EvidenceStorageError,
            "simulated checkpoint response loss",
        ):
            worker(store, stages).run_once()
        persisted_id = stages["committee_memo"].persisted_by_security[store.security_id]

        self.assertTrue(worker(store, stages).run_once())

        self.assertEqual(store.checkpoints[-1], ("committee_memo", persisted_id))
        self.assertEqual(len(stages["committee_memo"].persisted_by_security), 1)
        self.assertEqual(len(stages["committee_memo"].calls), 2)

    def test_two_materially_different_securities_use_same_stage_contract(
        self,
    ) -> None:
        stage_orders: list[tuple[str, ...]] = []
        artifact_shapes: list[tuple[str, ...]] = []

        for fixture_name in ("platform-security", "single-asset-security"):
            store = RestartableCommandStore(stable_uuid(fixture_name))
            stages = {stage: IdempotentPersistentStage(stage) for stage in STAGES}
            while worker(store, stages).run_once():
                pass
            stage_orders.append(tuple(store.completed))
            artifact_shapes.append(
                tuple(stage for stage, artifact_id in store.checkpoints if artifact_id)
            )

        self.assertEqual(stage_orders, [STAGES, STAGES])
        self.assertEqual(artifact_shapes, [STAGES, STAGES])


if __name__ == "__main__":
    unittest.main()

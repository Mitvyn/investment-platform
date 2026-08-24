from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from workers.research_committee.local_commands import (
    FileResearchRunCommandStore,
    LocalCommandStoreError,
)


OPERATOR = "027d7f1b-d928-48d9-b6c8-f10d3c7ba792"
SECURITY = "22222222-2222-4222-8222-222222222222"
CAPTURE = "33333333-3333-4333-8333-333333333333"
CAPTURE_HASH = "3" * 64
CUTOFF = datetime(2026, 5, 6, 23, 59, 59, tzinfo=UTC)
START = datetime(2026, 5, 7, 4, tzinfo=UTC)
QUESTION_TYPE_VERSION = "biotech_moonshot_catalyst_assessment.v1"
WORKFLOW_CONFIG_VERSION = "biotech-moonshot-catalyst-v1"
ARTIFACT = "66666666-6666-4666-8666-666666666666"


class MovableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value = self.value + timedelta(seconds=seconds)


class LocalResearchRunCommandStoreTests(unittest.TestCase):
    def _store(
        self,
        directory: str,
        clock: MovableClock,
    ) -> FileResearchRunCommandStore:
        return FileResearchRunCommandStore(
            Path(directory) / "commands",
            operator_id=OPERATOR,
            clock=clock,
        )

    @staticmethod
    def _enqueue(store: FileResearchRunCommandStore, **changes):
        values = {
            "security_id": SECURITY,
            "as_of_cutoff": CUTOFF,
            "operator_focus": "  Review financing   through catalyst. ",
            "question_type_version": QUESTION_TYPE_VERSION,
            "workflow_config_version": WORKFLOW_CONFIG_VERSION,
            "capture_id": CAPTURE,
            "capture_revision": 1,
            "capture_content_hash": CAPTURE_HASH,
        }
        values.update(changes)
        return store.enqueue(**values)

    def test_enqueue_normalizes_focus_and_starts_queued(self) -> None:
        clock = MovableClock(START)
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory, clock)

            command = self._enqueue(store)

        self.assertEqual(command.contract_version, "research_run_command_receipt.v2")
        self.assertEqual(command.command_state, "queued")
        self.assertEqual(
            command.operator_focus_normalized,
            "Review financing through catalyst.",
        )
        self.assertEqual(command.blocking_reason_codes, ())
        self.assertIsNone(command.error_code)
        self.assertIsNone(command.research_run_id)
        self.assertIsNone(command.started_at)
        self.assertIsNone(command.finished_at)

    def test_duplicate_delivery_reuses_one_command(self) -> None:
        clock = MovableClock(START)
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory, clock)

            first = self._enqueue(store)
            clock.advance(120)
            second = self._enqueue(store)
            corrected = self._enqueue(store, capture_revision=2)

        self.assertEqual(second, first)
        self.assertEqual(second.idempotency_key, first.idempotency_key)
        self.assertNotEqual(corrected.command_id, first.command_id)

    def test_enqueue_rejects_foreign_workflow_identity(self) -> None:
        clock = MovableClock(START)
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory, clock)

            with self.assertRaisesRegex(
                LocalCommandStoreError,
                "unsupported research workflow identity",
            ):
                self._enqueue(store, workflow_config_version="other-workflow-v9")

    def test_enqueue_rejects_invalid_capture_identity(self) -> None:
        clock = MovableClock(START)
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory, clock)

            with self.assertRaisesRegex(
                LocalCommandStoreError,
                "capture identity is invalid",
            ):
                self._enqueue(store, capture_content_hash="not-a-hash")
            with self.assertRaisesRegex(
                LocalCommandStoreError,
                "capture identity is invalid",
            ):
                self._enqueue(store, capture_revision=0)

    def test_queued_command_becomes_claimed_once(self) -> None:
        clock = MovableClock(START)
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory, clock)
            command = self._enqueue(store)

            claim = store.claim_next("desktop-worker")
            second_worker_claim = store.claim_next("other-worker")
            receipt = store.get(command.command_id)

        self.assertIsNotNone(claim)
        self.assertIsNone(second_worker_claim)
        self.assertEqual(claim.command_id, command.command_id)
        self.assertEqual(claim.operator_id, OPERATOR)
        self.assertEqual(claim.security_id, SECURITY)
        self.assertEqual(claim.capture_id, CAPTURE)
        self.assertEqual(claim.capture_revision, 1)
        self.assertEqual(claim.capture_content_hash, CAPTURE_HASH)
        self.assertEqual(claim.as_of_cutoff, CUTOFF)
        self.assertEqual(claim.question_type_version, QUESTION_TYPE_VERSION)
        self.assertEqual(claim.workflow_config_version, WORKFLOW_CONFIG_VERSION)
        self.assertEqual(claim.attempt_number, 1)
        self.assertEqual(claim.next_stage, "research_run")
        self.assertEqual(claim.completed_stages, ())
        self.assertIsNone(claim.research_run_id)
        self.assertEqual(receipt.command_state, "running")
        self.assertEqual(receipt.started_at, START)

    def test_same_worker_resumes_its_unexpired_attempt(self) -> None:
        clock = MovableClock(START)
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory, clock)
            self._enqueue(store)

            first = store.claim_next("desktop-worker")
            store.checkpoint(first, stage="research_run", artifact_id=ARTIFACT)
            clock.advance(30)
            resumed = store.claim_next("desktop-worker")

        self.assertEqual(resumed.attempt_id, first.attempt_id)
        self.assertEqual(resumed.attempt_number, 1)
        self.assertEqual(resumed.next_stage, "evidence_bundle")
        self.assertEqual(resumed.completed_stages, ("research_run",))
        self.assertEqual(resumed.research_run_id, ARTIFACT)

    def test_checkpoint_replay_is_idempotent_and_conflict_is_rejected(self) -> None:
        clock = MovableClock(START)
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory, clock)
            self._enqueue(store)
            claim = store.claim_next("desktop-worker")

            store.checkpoint(claim, stage="research_run", artifact_id=ARTIFACT)
            store.checkpoint(claim, stage="research_run", artifact_id=ARTIFACT)
            with self.assertRaisesRegex(
                LocalCommandStoreError,
                "conflicting research run checkpoint",
            ):
                store.checkpoint(
                    claim,
                    stage="research_run",
                    artifact_id="77777777-7777-4777-8777-777777777777",
                )
            progress = store.progress(claim.command_id)

        self.assertEqual(progress["completed_stages"], ["research_run"])

    def test_retryable_failure_requeues_once_then_terminalizes(self) -> None:
        clock = MovableClock(START)
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory, clock)
            command = self._enqueue(store)

            first = store.claim_next("desktop-worker")
            store.fail(
                first,
                stage="research_run",
                error_code="research_run_persistence_failed",
                retryable=True,
            )
            requeued = store.get(command.command_id)
            second = store.claim_next("desktop-worker")
            store.fail(
                second,
                stage="research_run",
                error_code="research_run_persistence_failed",
                retryable=True,
            )
            terminal = store.get(command.command_id)
            exhausted = store.claim_next("desktop-worker")

        self.assertEqual(requeued.command_state, "queued")
        self.assertIsNone(requeued.error_code)
        self.assertEqual(second.attempt_number, 2)
        self.assertEqual(terminal.command_state, "failed")
        self.assertEqual(terminal.error_code, "research_run_persistence_failed")
        self.assertIsNone(exhausted)

    def test_nonretryable_failure_is_terminal_on_first_attempt(self) -> None:
        clock = MovableClock(START)
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory, clock)
            command = self._enqueue(store)
            claim = store.claim_next("desktop-worker")

            store.fail(
                claim,
                stage="research_run",
                error_code="research_run_accepted_capture_invalid",
                retryable=False,
            )
            receipt = store.get(command.command_id)
            progress = store.progress(command.command_id)

        self.assertEqual(receipt.command_state, "failed")
        self.assertIsNone(receipt.research_run_id)
        self.assertEqual(progress["command_state"], "failed")
        self.assertEqual(progress["failure_stage"], "research_run")
        self.assertFalse(progress["retryable"])

    def test_expired_lease_recovery_requeues_deterministically(self) -> None:
        clock = MovableClock(START)
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory, clock)
            command = self._enqueue(store)
            first = store.claim_next("desktop-worker")

            clock.advance(600)
            recovered = store.claim_next("desktop-worker")
            receipt = store.get(command.command_id)

        self.assertIsNotNone(recovered)
        self.assertNotEqual(recovered.attempt_id, first.attempt_id)
        self.assertEqual(recovered.attempt_number, 2)
        self.assertEqual(receipt.command_state, "running")

    def test_expired_lease_on_last_attempt_fails_command(self) -> None:
        clock = MovableClock(START)
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory, clock)
            command = self._enqueue(store)
            store.claim_next("desktop-worker")
            clock.advance(600)
            store.claim_next("desktop-worker")

            clock.advance(600)
            exhausted = store.claim_next("desktop-worker")
            receipt = store.get(command.command_id)

        self.assertIsNone(exhausted)
        self.assertEqual(receipt.command_state, "failed")
        self.assertEqual(receipt.error_code, "worker_lease_expired")

    def test_lease_renewal_requires_active_stage_and_token(self) -> None:
        clock = MovableClock(START)
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory, clock)
            self._enqueue(store)
            claim = store.claim_next("desktop-worker")

            clock.advance(60)
            store.renew_lease(claim)
            renewed = store.progress(claim.command_id)
            forged = claim.__class__(
                **{
                    **{
                        field: getattr(claim, field)
                        for field in claim.__dataclass_fields__
                    },
                    "lease_token": "88888888-8888-4888-8888-888888888888",
                }
            )
            with self.assertRaisesRegex(
                LocalCommandStoreError,
                "research run command lease is invalid",
            ):
                store.renew_lease(forged)

        self.assertEqual(
            renewed["lease_expires_at"],
            (START + timedelta(seconds=60 + 300)).isoformat(),
        )

    def test_completed_command_replay_creates_no_second_attempt(self) -> None:
        clock = MovableClock(START)
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory, clock)
            command = self._enqueue(store)
            claim = store.claim_next("desktop-worker")
            for index, stage in enumerate(
                (
                    "research_run",
                    "evidence_bundle",
                    "valuation_snapshot",
                    "grader_committee",
                    "committee_memo",
                    "readiness_thesis",
                )
            ):
                store.checkpoint(
                    claim,
                    stage=stage,
                    artifact_id=f"{index + 1}0000000-0000-4000-8000-000000000000",
                )
                claim = store.claim_next("desktop-worker") or claim

            receipt = store.get(command.command_id)
            replay = store.claim_next("desktop-worker")
            replayed_receipt = store.get(command.command_id)
            progress = store.progress(command.command_id)

        self.assertEqual(receipt.command_state, "completed")
        self.assertEqual(receipt.research_run_id, "10000000-0000-4000-8000-000000000000")
        self.assertIsNone(replay)
        self.assertEqual(replayed_receipt, receipt)
        self.assertEqual(progress["command_state"], "completed")
        self.assertEqual(progress["attempt_state"], "completed")
        self.assertEqual(len(progress["completed_stages"]), 6)

    def test_block_records_reason_codes_without_claiming_completion(self) -> None:
        clock = MovableClock(START)
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory, clock)
            command = self._enqueue(store)
            claim = store.claim_next("desktop-worker")
            store.checkpoint(claim, stage="research_run", artifact_id=ARTIFACT)
            resumed = store.claim_next("desktop-worker")

            store.block(
                resumed,
                stage="evidence_bundle",
                blocking_reason_codes=("evidence_bundle_local_persistence_unavailable",),
            )
            receipt = store.get(command.command_id)
            progress = store.progress(command.command_id)
            further = store.claim_next("desktop-worker")

        self.assertEqual(receipt.command_state, "blocked")
        self.assertEqual(
            receipt.blocking_reason_codes,
            ("evidence_bundle_local_persistence_unavailable",),
        )
        self.assertEqual(receipt.research_run_id, ARTIFACT)
        self.assertEqual(progress["command_state"], "blocked")
        self.assertEqual(progress["completed_stages"], ["research_run"])
        self.assertIsNone(further)

    def test_progress_survives_store_restart_and_excludes_lease_token(self) -> None:
        clock = MovableClock(START)
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory, clock)
            command = self._enqueue(store)
            claim = store.claim_next("desktop-worker")
            store.checkpoint(claim, stage="research_run", artifact_id=ARTIFACT)

            restarted = self._store(directory, clock)
            progress = restarted.progress(command.command_id)
            receipt = restarted.get(command.command_id)
            resumed = restarted.claim_next("desktop-worker")

        self.assertEqual(
            progress["contract_version"],
            "research_run_command_progress.v1",
        )
        self.assertEqual(progress["operator_id"], OPERATOR)
        self.assertEqual(progress["command_id"], command.command_id)
        self.assertEqual(progress["completed_stages"], ["research_run"])
        self.assertEqual(progress["attempt_id"], claim.attempt_id)
        self.assertNotIn("lease_token", progress)
        self.assertNotIn("worker_id", progress)
        self.assertNotIn(claim.lease_token, repr(receipt))
        self.assertEqual(resumed.next_stage, "evidence_bundle")

    def test_unknown_command_has_no_receipt_or_progress(self) -> None:
        clock = MovableClock(START)
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory, clock)

            self.assertIsNone(store.get("99999999-9999-4999-8999-999999999999"))
            self.assertIsNone(store.progress("99999999-9999-4999-8999-999999999999"))

    def test_store_rejects_symlinked_root(self) -> None:
        clock = MovableClock(START)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "real"
            target.mkdir()
            link = Path(directory) / "linked"
            link.symlink_to(target)

            with self.assertRaisesRegex(
                LocalCommandStoreError,
                "command storage root must not be a symlink",
            ):
                FileResearchRunCommandStore(link, operator_id=OPERATOR, clock=clock)


if __name__ == "__main__":
    unittest.main()

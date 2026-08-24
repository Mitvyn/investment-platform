from __future__ import annotations

import tempfile
import threading
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from workers.research_committee.local_commands import FileResearchRunCommandStore
from workers.research_committee.local_execution import (
    LOCAL_STAGE_BLOCKING_REASONS,
    LocalExecutionDiagnostics,
    LocalExecutionError,
    LocalResearchCommandExecutor,
)
from workers.research_committee.worker import ResearchRunStageError


OPERATOR = "027d7f1b-d928-48d9-b6c8-f10d3c7ba792"
SECURITY = "22222222-2222-4222-8222-222222222222"
CAPTURE = "33333333-3333-4333-8333-333333333333"
CAPTURE_HASH = "3" * 64
CUTOFF = datetime(2026, 5, 6, 23, 59, 59, tzinfo=UTC)
START = datetime(2026, 5, 7, 4, tzinfo=UTC)
RUN = "10000000-0000-4000-8000-000000000000"
QUESTION_TYPE_VERSION = "biotech_moonshot_catalyst_assessment.v1"
WORKFLOW_CONFIG_VERSION = "biotech-moonshot-catalyst-v1"


class MovableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value = self.value + timedelta(seconds=seconds)


class StageFake:
    def __init__(self, artifact_id: str) -> None:
        self.artifact_id = artifact_id
        self.claims = []

    def execute(self, claim) -> str:
        self.claims.append(claim)
        return self.artifact_id


class FailingStage:
    def __init__(self, error_code: str, *, retryable: bool) -> None:
        self.error_code = error_code
        self.retryable = retryable
        self.calls = 0

    def execute(self, claim) -> str:
        self.calls += 1
        raise ResearchRunStageError(self.error_code, retryable=self.retryable)


class LocalResearchCommandExecutorTests(unittest.TestCase):
    def _store(self, directory: str, clock: MovableClock):
        return FileResearchRunCommandStore(
            Path(directory) / "commands",
            operator_id=OPERATOR,
            clock=clock,
        )

    @staticmethod
    def _enqueue(store):
        return store.enqueue(
            security_id=SECURITY,
            as_of_cutoff=CUTOFF,
            operator_focus=None,
            question_type_version=QUESTION_TYPE_VERSION,
            workflow_config_version=WORKFLOW_CONFIG_VERSION,
            capture_id=CAPTURE,
            capture_revision=1,
            capture_content_hash=CAPTURE_HASH,
        )

    def _executor(self, store, stages, diagnostics=None):
        return LocalResearchCommandExecutor(
            worker_id="desktop-worker",
            commands=store,
            stages=stages,
            diagnostics=diagnostics,
        )

    def test_idle_when_no_command_is_queued(self) -> None:
        clock = MovableClock(START)
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory, clock)
            outcome = self._executor(store, {"research_run": StageFake(RUN)}).run_once()

        self.assertEqual(outcome.status, "idle")
        self.assertIsNone(outcome.command_id)

    def test_queued_command_executes_research_run_and_checkpoints(self) -> None:
        clock = MovableClock(START)
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory, clock)
            command = self._enqueue(store)
            stage = StageFake(RUN)
            diagnostics = LocalExecutionDiagnostics()

            outcome = self._executor(
                store,
                {"research_run": stage},
                diagnostics,
            ).run_once()
            progress = store.progress(command.command_id)

        self.assertEqual(outcome.status, "checkpointed")
        self.assertEqual(outcome.stage, "research_run")
        self.assertEqual(outcome.artifact_id, RUN)
        self.assertEqual(len(stage.claims), 1)
        self.assertEqual(stage.claims[0].capture_content_hash, CAPTURE_HASH)
        self.assertEqual(progress["completed_stages"], ["research_run"])
        self.assertEqual(
            tuple(event["event"] for event in diagnostics.events()),
            ("command_claimed", "stage_checkpointed"),
        )

    def test_missing_stage_records_blocked_state_not_completion(self) -> None:
        clock = MovableClock(START)
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory, clock)
            command = self._enqueue(store)
            executor = self._executor(store, {"research_run": StageFake(RUN)})

            first = executor.run_once()
            second = executor.run_once()
            receipt = store.get(command.command_id)

        self.assertEqual(first.status, "checkpointed")
        self.assertEqual(second.status, "blocked")
        self.assertEqual(second.stage, "evidence_bundle")
        self.assertEqual(
            second.blocking_reason_codes,
            LOCAL_STAGE_BLOCKING_REASONS["evidence_bundle"],
        )
        self.assertEqual(receipt.command_state, "blocked")
        self.assertEqual(receipt.research_run_id, RUN)

    def test_provider_and_model_boundaries_record_activation_blocks(self) -> None:
        clock = MovableClock(START)
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory, clock)
            command = self._enqueue(store)
            executor = self._executor(
                store,
                {
                    "research_run": StageFake(RUN),
                    "evidence_bundle": StageFake(
                        "20000000-0000-4000-8000-000000000000"
                    ),
                },
            )

            outcomes = executor.run_bounded(max_stages=6)
            receipt = store.get(command.command_id)
            progress = store.progress(command.command_id)

        self.assertEqual(
            tuple(outcome.status for outcome in outcomes),
            ("checkpointed", "checkpointed", "blocked"),
        )
        self.assertEqual(outcomes[-1].stage, "valuation_snapshot")
        self.assertEqual(
            outcomes[-1].blocking_reason_codes,
            ("approved_valuation_source_activation",),
        )
        self.assertEqual(receipt.command_state, "blocked")
        self.assertEqual(
            receipt.blocking_reason_codes,
            ("approved_valuation_source_activation",),
        )
        self.assertEqual(
            progress["completed_stages"],
            ["research_run", "evidence_bundle"],
        )

    def test_model_stage_boundary_names_model_activation(self) -> None:
        self.assertEqual(
            LOCAL_STAGE_BLOCKING_REASONS["grader_committee"],
            ("approved_model_provider_activation",),
        )
        self.assertEqual(
            LOCAL_STAGE_BLOCKING_REASONS["committee_memo"],
            ("approved_model_provider_activation",),
        )
        self.assertEqual(
            LOCAL_STAGE_BLOCKING_REASONS["readiness_thesis"],
            ("approved_model_provider_activation",),
        )

    def test_retryable_stage_failure_requeues_then_terminalizes(self) -> None:
        clock = MovableClock(START)
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory, clock)
            command = self._enqueue(store)
            stage = FailingStage(
                "research_run_persistence_failed",
                retryable=True,
            )
            executor = self._executor(store, {"research_run": stage})

            first = executor.run_once()
            requeued = store.get(command.command_id)
            second = executor.run_once()
            terminal = store.get(command.command_id)
            third = executor.run_once()

        self.assertEqual(first.status, "failed")
        self.assertTrue(first.retryable)
        self.assertEqual(requeued.command_state, "queued")
        self.assertEqual(second.status, "failed")
        self.assertEqual(terminal.command_state, "failed")
        self.assertEqual(terminal.error_code, "research_run_persistence_failed")
        self.assertEqual(third.status, "idle")
        self.assertEqual(stage.calls, 2)

    def test_nonretryable_stage_failure_is_terminal_immediately(self) -> None:
        clock = MovableClock(START)
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory, clock)
            command = self._enqueue(store)
            stage = FailingStage(
                "research_run_accepted_capture_invalid",
                retryable=False,
            )
            diagnostics = LocalExecutionDiagnostics()

            outcome = self._executor(store, {"research_run": stage}, diagnostics).run_once()
            receipt = store.get(command.command_id)

        self.assertEqual(outcome.status, "failed")
        self.assertFalse(outcome.retryable)
        self.assertEqual(receipt.command_state, "failed")
        self.assertEqual(stage.calls, 1)
        self.assertEqual(
            tuple(event["event"] for event in diagnostics.events()),
            ("command_claimed", "stage_failed"),
        )

    def test_second_worker_cannot_execute_active_command_twice(self) -> None:
        clock = MovableClock(START)
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory, clock)
            self._enqueue(store)
            first_stage = StageFake(RUN)
            second_stage = StageFake(RUN)
            LocalResearchCommandExecutor(
                worker_id="desktop-worker",
                commands=store,
                stages={"research_run": first_stage},
            ).run_once()

            competing = LocalResearchCommandExecutor(
                worker_id="other-worker",
                commands=store,
                stages={"research_run": second_stage},
            ).run_once()

        self.assertEqual(len(first_stage.claims), 1)
        self.assertEqual(second_stage.claims, [])
        self.assertEqual(competing.status, "idle")

    def test_bounded_run_stops_at_first_blocked_boundary(self) -> None:
        clock = MovableClock(START)
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory, clock)
            self._enqueue(store)
            executor = self._executor(store, {"research_run": StageFake(RUN)})

            outcomes = executor.run_bounded(max_stages=6)

        self.assertEqual(
            tuple(outcome.status for outcome in outcomes),
            ("checkpointed", "blocked"),
        )

    def test_bounded_run_rejects_unbounded_stage_budget(self) -> None:
        clock = MovableClock(START)
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory, clock)
            executor = self._executor(store, {"research_run": StageFake(RUN)})

            for invalid in (0, -1, 13):
                with self.assertRaisesRegex(
                    LocalExecutionError,
                    "stage budget must be between 1 and 12",
                ):
                    executor.run_bounded(max_stages=invalid)

    def test_execution_leaves_no_lease_thread_behind(self) -> None:
        clock = MovableClock(START)
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory, clock)
            self._enqueue(store)
            executor = LocalResearchCommandExecutor(
                worker_id="desktop-worker",
                commands=store,
                stages={"research_run": StageFake(RUN)},
                heartbeat_interval_seconds=0.05,
            )

            executor.run_once()

        residue = [
            thread.name
            for thread in threading.enumerate()
            if thread.name.startswith("iros-lease-")
        ]
        self.assertEqual(residue, [])

    def test_diagnostics_are_bounded_and_reject_unsafe_content(self) -> None:
        diagnostics = LocalExecutionDiagnostics(limit=3)
        for index in range(5):
            diagnostics.record(
                "command_claimed",
                command_id=RUN,
                stage="research_run",
                attempt_number=1 + index % 2,
            )

        with self.assertRaisesRegex(
            LocalExecutionError,
            "diagnostic field is unsafe",
        ):
            diagnostics.record(
                "command_claimed",
                command_id="/Users/mwong/private/archive.zip",
            )
        with self.assertRaisesRegex(
            LocalExecutionError,
            "diagnostic field is unsafe",
        ):
            diagnostics.record("command_claimed", archive_path="research_run")

        self.assertEqual(len(diagnostics.events()), 3)


if __name__ == "__main__":
    unittest.main()

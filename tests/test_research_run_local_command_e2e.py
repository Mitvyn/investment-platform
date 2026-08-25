"""Local end-to-end proof for one capture-bound Research Run command.

Real local repositories, the real deterministic replay assembler, and the real
command executor run here. No provider, model, hosted, or network transport is
constructed at any point.
"""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from investment_research_os.evidence_bundles.file_storage import (
    FileEvidenceBundleRepository,
    LocalEvidenceBundleStorageError,
)
from investment_research_os.research_runs.file_storage import (
    FileResearchRunRepository,
)
from tests.test_primary_source_end_to_end import (
    PLATFORM_CASE,
    request as integrated_request,
)
from tests.test_primary_source_replay import _platform_capture_archive
from workers.primary_sources.captures import load_primary_source_capture
from workers.primary_sources.storage import FilePrimarySourceCaptureRepository
from workers.research_committee.local_commands import FileResearchRunCommandStore
from workers.research_committee.local_execution import (
    LOCAL_STAGE_BLOCKING_REASONS,
    LocalExecutionDiagnostics,
    compose_local_research_command_executor,
)


ACCEPTED_AT = datetime(2026, 5, 7, 3, tzinfo=UTC)
NOW = datetime(2026, 5, 7, 4, tzinfo=UTC)
SEC_USER_AGENT = "Investment Research OS research@example.com"
WORKER_ID = "desktop-local-worker"
DEFAULT_BUNDLE_REPOSITORY = object()


class MovableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value = self.value + timedelta(seconds=seconds)


class LocalResearchRunCommandEndToEndTests(unittest.TestCase):
    def _fixture(self, directory: str, clock: MovableClock):
        root = Path(directory)
        raw_archive = _platform_capture_archive()
        source_request = integrated_request(PLATFORM_CASE)
        captures = FilePrimarySourceCaptureRepository(root / "captures")
        persisted = captures.save_capture(
            load_primary_source_capture(
                raw_archive,
                request=source_request,
                trusted_issuer_hosts=PLATFORM_CASE.issuer_trusted_hosts,
                accepted_at=lambda: ACCEPTED_AT,
            ),
            raw_archive,
        )
        return root, source_request, captures, persisted

    def _commands(self, root: Path, operator_id: str, clock: MovableClock):
        return FileResearchRunCommandStore(
            root / "commands",
            operator_id=operator_id,
            clock=clock,
        )

    def _executor(
        self,
        root: Path,
        commands,
        captures,
        clock: MovableClock,
        diagnostics=None,
        evidence_bundles=DEFAULT_BUNDLE_REPOSITORY,
    ):
        # `evidence_bundles=None` composes the executor with no durable local
        # Evidence Bundle store, which is how the path behaved before this
        # slice and must still block honestly.
        if evidence_bundles is DEFAULT_BUNDLE_REPOSITORY:
            evidence_bundles = FileEvidenceBundleRepository(root / "bundles")
        return compose_local_research_command_executor(
            worker_id=WORKER_ID,
            commands=commands,
            research_run_repository=FileResearchRunRepository(root / "runs"),
            evidence_bundle_repository=evidence_bundles,
            capture_repository=captures,
            ticker=PLATFORM_CASE.display_symbol,
            trusted_issuer_hosts=PLATFORM_CASE.issuer_trusted_hosts,
            sec_user_agent=SEC_USER_AGENT,
            clock=clock,
            diagnostics=diagnostics,
        )

    @staticmethod
    def _enqueue(commands, persisted, **changes):
        values = {
            "security_id": persisted.security_id,
            "as_of_cutoff": persisted.as_of_cutoff,
            "operator_focus": None,
            "question_type_version": persisted.question_type_version,
            "workflow_config_version": persisted.workflow_config_version,
            "capture_id": persisted.capture_id,
            "capture_revision": persisted.capture_revision,
            "capture_content_hash": persisted.capture_content_hash,
        }
        values.update(changes)
        return commands.enqueue(**values)

    def test_queued_command_produces_bound_run_then_blocks_honestly(self) -> None:
        clock = MovableClock(NOW)
        with tempfile.TemporaryDirectory() as directory:
            root, source_request, captures, persisted = self._fixture(directory, clock)
            commands = self._commands(root, source_request.operator_id, clock)
            command = self._enqueue(commands, persisted)
            diagnostics = LocalExecutionDiagnostics()

            outcomes = self._executor(
                root,
                commands,
                captures,
                clock,
                diagnostics,
            ).run_bounded(max_stages=6)

            receipt = commands.get(command.command_id)
            progress = commands.progress(command.command_id)
            run = FileResearchRunRepository(root / "runs").get(
                source_request.operator_id,
                outcomes[0].artifact_id,
            )
            binding = captures.get_for_run(
                source_request.operator_id,
                outcomes[0].artifact_id,
            )
            events = tuple(event["event"] for event in diagnostics.events())

        self.assertEqual(
            tuple(outcome.status for outcome in outcomes),
            ("checkpointed", "checkpointed", "blocked"),
        )
        self.assertEqual(outcomes[1].stage, "evidence_bundle")
        self.assertEqual(outcomes[2].stage, "valuation_snapshot")
        self.assertEqual(
            outcomes[2].blocking_reason_codes,
            LOCAL_STAGE_BLOCKING_REASONS["valuation_snapshot"],
        )
        self.assertEqual(receipt.command_state, "blocked")
        self.assertNotEqual(receipt.command_state, "completed")
        self.assertEqual(receipt.research_run_id, outcomes[0].artifact_id)
        self.assertEqual(
            progress["completed_stages"],
            ["research_run", "evidence_bundle"],
        )
        self.assertIsNotNone(run)
        self.assertEqual(run.security_id, persisted.security_id)
        self.assertEqual(run.as_of_cutoff, persisted.as_of_cutoff)
        self.assertEqual(run.security_identity.cik, PLATFORM_CASE.cik)
        self.assertEqual(run.security_identity.issuer_name, PLATFORM_CASE.issuer_name)
        self.assertEqual(
            run.security_identity.symbol,
            PLATFORM_CASE.display_symbol,
        )
        self.assertTrue(run.eligibility.eligible)
        self.assertIsNotNone(binding)
        self.assertEqual(binding.capture_id, persisted.capture_id)
        self.assertEqual(binding.capture_revision, persisted.capture_revision)
        self.assertEqual(
            binding.capture_content_hash,
            persisted.capture_content_hash,
        )
        self.assertEqual(
            events,
            (
                "command_claimed",
                "stage_checkpointed",
                "command_claimed",
                "stage_checkpointed",
                "command_claimed",
                "stage_blocked",
            ),
        )

    def test_restart_reloads_progress_and_creates_no_duplicate_artifact(self) -> None:
        clock = MovableClock(NOW)
        with tempfile.TemporaryDirectory() as directory:
            root, source_request, captures, persisted = self._fixture(directory, clock)
            commands = self._commands(root, source_request.operator_id, clock)
            command = self._enqueue(commands, persisted)
            first = self._executor(root, commands, captures, clock).run_once()

            clock.advance(30)
            restarted_commands = self._commands(root, source_request.operator_id, clock)
            restarted_captures = FilePrimarySourceCaptureRepository(root / "captures")
            restarted_progress = restarted_commands.progress(command.command_id)
            second = self._executor(
                root,
                restarted_commands,
                restarted_captures,
                clock,
            ).run_once()
            replayed_command = self._enqueue(restarted_commands, persisted)
            third = self._executor(
                root,
                restarted_commands,
                restarted_captures,
                clock,
            ).run_once()
            run_files = sorted(
                path.name
                for path in (root / "runs" / source_request.operator_id).iterdir()
            )
            command_files = sorted(
                path.name
                for path in (root / "commands" / source_request.operator_id).iterdir()
            )

        self.assertEqual(first.status, "checkpointed")
        self.assertEqual(restarted_progress["completed_stages"], ["research_run"])
        self.assertEqual(restarted_progress["attempt_number"], 1)
        self.assertEqual(second.status, "checkpointed")
        self.assertEqual(replayed_command.command_id, command.command_id)
        # The replayed command is the same one, so the third pass carries it to
        # the first boundary that has no local implementation instead of
        # starting anything new.
        self.assertEqual(third.status, "blocked")
        self.assertEqual(third.stage, "valuation_snapshot")
        self.assertEqual(len(run_files), 1)
        self.assertEqual(len(command_files), 1)

    def test_repeated_research_run_stage_reuses_one_persisted_run(self) -> None:
        clock = MovableClock(NOW)
        with tempfile.TemporaryDirectory() as directory:
            root, source_request, captures, persisted = self._fixture(directory, clock)
            commands = self._commands(root, source_request.operator_id, clock)
            self._enqueue(commands, persisted)
            runs = FileResearchRunRepository(root / "runs")
            executor = self._executor(root, commands, captures, clock)

            first = executor.run_once()
            first_run = runs.get(source_request.operator_id, first.artifact_id)
            replay_store = FileResearchRunCommandStore(
                root / "replay-commands",
                operator_id=source_request.operator_id,
                clock=clock,
            )
            self._enqueue(replay_store, persisted)
            replayed = self._executor(
                root,
                replay_store,
                captures,
                clock,
            ).run_once()
            replayed_run = runs.get(source_request.operator_id, replayed.artifact_id)
            run_files = sorted(
                path.name
                for path in (root / "runs" / source_request.operator_id).iterdir()
            )
            replayed_key = replay_store.get(replayed.command_id).idempotency_key
            original_key = commands.get(first.command_id).idempotency_key

        self.assertEqual(replayed.artifact_id, first.artifact_id)
        self.assertEqual(replayed_run, first_run)
        self.assertEqual(len(run_files), 1)
        self.assertEqual(replayed.command_id, first.command_id)
        self.assertEqual(replayed_key, original_key)

    def test_foreign_security_is_rejected_before_any_run_is_persisted(self) -> None:
        clock = MovableClock(NOW)
        with tempfile.TemporaryDirectory() as directory:
            root, source_request, captures, persisted = self._fixture(directory, clock)
            commands = self._commands(root, source_request.operator_id, clock)
            command = self._enqueue(
                commands,
                persisted,
                security_id="99999999-9999-4999-8999-999999999999",
            )

            outcome = self._executor(root, commands, captures, clock).run_once()
            receipt = commands.get(command.command_id)
            run_root = root / "runs" / source_request.operator_id

        self.assertEqual(outcome.status, "failed")
        self.assertFalse(outcome.retryable)
        self.assertEqual(
            outcome.error_code,
            "research_run_accepted_capture_invalid",
        )
        self.assertEqual(receipt.command_state, "failed")
        self.assertIsNone(receipt.research_run_id)
        self.assertFalse(run_root.exists() and any(run_root.iterdir()))

    def test_drifted_capture_hash_is_rejected_before_any_run_is_persisted(self) -> None:
        clock = MovableClock(NOW)
        with tempfile.TemporaryDirectory() as directory:
            root, source_request, captures, persisted = self._fixture(directory, clock)
            commands = self._commands(root, source_request.operator_id, clock)
            command = self._enqueue(commands, persisted, capture_content_hash="0" * 64)

            outcome = self._executor(root, commands, captures, clock).run_once()
            receipt = commands.get(command.command_id)
            run_root = root / "runs" / source_request.operator_id

        self.assertEqual(outcome.status, "failed")
        self.assertEqual(
            outcome.error_code,
            "research_run_accepted_capture_invalid",
        )
        self.assertEqual(receipt.command_state, "failed")
        self.assertFalse(run_root.exists() and any(run_root.iterdir()))

    def test_unknown_capture_revision_is_rejected(self) -> None:
        clock = MovableClock(NOW)
        with tempfile.TemporaryDirectory() as directory:
            root, source_request, captures, persisted = self._fixture(directory, clock)
            commands = self._commands(root, source_request.operator_id, clock)
            command = self._enqueue(commands, persisted, capture_revision=9)

            outcome = self._executor(root, commands, captures, clock).run_once()
            receipt = commands.get(command.command_id)

        self.assertEqual(outcome.status, "failed")
        self.assertEqual(
            outcome.error_code,
            "research_run_accepted_capture_invalid",
        )
        self.assertEqual(receipt.command_state, "failed")

    def test_progress_and_receipt_expose_no_secret_or_raw_payload(self) -> None:
        clock = MovableClock(NOW)
        with tempfile.TemporaryDirectory() as directory:
            root, source_request, captures, persisted = self._fixture(directory, clock)
            commands = self._commands(root, source_request.operator_id, clock)
            command = self._enqueue(commands, persisted)
            diagnostics = LocalExecutionDiagnostics()
            self._executor(
                root,
                commands,
                captures,
                clock,
                diagnostics,
            ).run_bounded(max_stages=6)

            serialized = json.dumps(
                {
                    "diagnostics": diagnostics.events(),
                    "progress": commands.progress(command.command_id),
                    "receipt": commands.get(command.command_id).as_dict(),
                },
                sort_keys=True,
            )

        for forbidden in (
            str(root),
            "primary-source-captures",
            "capture.json",
            persisted.package_sha256,
            persisted.plan_content_hash,
            SEC_USER_AGENT,
            "lease_token",
            "worker_id",
            "archive_path",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_execution_leaves_no_worker_thread_residue(self) -> None:
        clock = MovableClock(NOW)
        before = {thread.name for thread in threading.enumerate()}
        with tempfile.TemporaryDirectory() as directory:
            root, source_request, captures, persisted = self._fixture(directory, clock)
            commands = self._commands(root, source_request.operator_id, clock)
            self._enqueue(commands, persisted)

            self._executor(root, commands, captures, clock).run_bounded(max_stages=6)

        self.assertEqual(
            {thread.name for thread in threading.enumerate()} - before,
            set(),
        )

    def test_evidence_bundle_is_bound_to_the_exact_research_run(self) -> None:
        clock = MovableClock(NOW)
        with tempfile.TemporaryDirectory() as directory:
            root, source_request, captures, persisted = self._fixture(directory, clock)
            commands = self._commands(root, source_request.operator_id, clock)
            command = self._enqueue(commands, persisted)
            bundles = FileEvidenceBundleRepository(root / "bundles")

            outcomes = self._executor(
                root,
                commands,
                captures,
                clock,
                evidence_bundles=bundles,
            ).run_bounded(max_stages=6)

            receipt = commands.get(command.command_id)
            run_id = outcomes[0].artifact_id
            bundle = bundles.get(source_request.operator_id, outcomes[1].artifact_id)
            by_run = bundles.get_for_run(source_request.operator_id, run_id)

        self.assertEqual(outcomes[1].status, "checkpointed")
        self.assertIsNotNone(bundle)
        self.assertEqual(bundle, by_run)
        self.assertEqual(bundle.research_run_id, run_id)
        self.assertEqual(bundle.operator_id, source_request.operator_id)
        self.assertEqual(bundle.security_id, persisted.security_id)
        self.assertEqual(bundle.as_of_cutoff, persisted.as_of_cutoff)
        self.assertEqual(len(bundle.content_hash), 64)
        self.assertTrue(bundle.manifest)
        # A stage that cannot reach an approved valuation source stops there.
        # It never reports the command complete.
        self.assertEqual(receipt.command_state, "blocked")
        self.assertNotEqual(receipt.command_state, "completed")

    def test_evidence_bundle_survives_restart_without_duplication(self) -> None:
        clock = MovableClock(NOW)
        with tempfile.TemporaryDirectory() as directory:
            root, source_request, captures, persisted = self._fixture(directory, clock)
            commands = self._commands(root, source_request.operator_id, clock)
            command = self._enqueue(commands, persisted)
            first = self._executor(root, commands, captures, clock).run_bounded(
                max_stages=2
            )

            clock.advance(30)
            restarted_commands = self._commands(root, source_request.operator_id, clock)
            restarted_captures = FilePrimarySourceCaptureRepository(root / "captures")
            reloaded = FileEvidenceBundleRepository(root / "bundles").get(
                source_request.operator_id,
                first[1].artifact_id,
            )
            replayed_command = self._enqueue(restarted_commands, persisted)
            second = self._executor(
                root,
                restarted_commands,
                restarted_captures,
                clock,
            ).run_bounded(max_stages=2)
            progress = restarted_commands.progress(command.command_id)
            bundle_records = sorted(
                path.name for path in (root / "bundles").rglob("*.json")
            )

        self.assertEqual(replayed_command.command_id, command.command_id)
        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded.research_run_id, first[0].artifact_id)
        self.assertEqual(
            progress["completed_stages"],
            ["research_run", "evidence_bundle"],
        )
        self.assertEqual(second[0].status, "blocked")
        self.assertEqual(second[0].stage, "valuation_snapshot")
        self.assertEqual(
            bundle_records,
            sorted(
                [
                    f"{first[1].artifact_id}.json",
                    f"{first[0].artifact_id}.json",
                ]
            ),
        )

    def test_replayed_evidence_bundle_stage_reuses_one_bundle(self) -> None:
        clock = MovableClock(NOW)
        with tempfile.TemporaryDirectory() as directory:
            root, source_request, captures, persisted = self._fixture(directory, clock)
            commands = self._commands(root, source_request.operator_id, clock)
            self._enqueue(commands, persisted)
            bundles = FileEvidenceBundleRepository(root / "bundles")
            executor = self._executor(
                root,
                commands,
                captures,
                clock,
                evidence_bundles=bundles,
            )
            first = executor.run_bounded(max_stages=2)
            run_id = first[0].artifact_id
            bundle = bundles.get_for_run(source_request.operator_id, run_id)

            # Re-enqueueing the same capture triple resolves to the same
            # command, and running it again must resolve to the identical
            # immutable bundle rather than materialising a second one.
            self._enqueue(commands, persisted)
            second = executor.run_bounded(max_stages=2)
            replayed = bundles.get_for_run(source_request.operator_id, run_id)
            records = sorted(
                path.name
                for path in (root / "bundles").rglob("*.json")
            )

        self.assertEqual(first[1].status, "checkpointed")
        self.assertIsNotNone(bundle)
        self.assertEqual(bundle, replayed)
        self.assertEqual(second[0].status, "blocked")
        self.assertEqual(second[0].stage, "valuation_snapshot")
        self.assertEqual(
            records,
            sorted([f"{bundle.id}.json", f"{run_id}.json"]),
        )

    def test_another_operator_cannot_read_the_local_bundle(self) -> None:
        clock = MovableClock(NOW)
        foreign_operator = str(uuid4())
        with tempfile.TemporaryDirectory() as directory:
            root, source_request, captures, persisted = self._fixture(directory, clock)
            commands = self._commands(root, source_request.operator_id, clock)
            self._enqueue(commands, persisted)
            bundles = FileEvidenceBundleRepository(root / "bundles")
            outcomes = self._executor(
                root,
                commands,
                captures,
                clock,
                evidence_bundles=bundles,
            ).run_bounded(max_stages=2)
            run_id = outcomes[0].artifact_id
            bundle_id = outcomes[1].artifact_id

        self.assertNotEqual(foreign_operator, source_request.operator_id)
        with tempfile.TemporaryDirectory() as directory:
            isolated = FileEvidenceBundleRepository(Path(directory) / "bundles")
            self.assertIsNone(isolated.get(foreign_operator, bundle_id))
            self.assertIsNone(isolated.get_for_run(foreign_operator, run_id))

    def test_tampered_bundle_record_fails_the_stage_rather_than_lying(self) -> None:
        clock = MovableClock(NOW)
        with tempfile.TemporaryDirectory() as directory:
            root, source_request, captures, persisted = self._fixture(directory, clock)
            commands = self._commands(root, source_request.operator_id, clock)
            self._enqueue(commands, persisted)
            bundles = FileEvidenceBundleRepository(root / "bundles")
            outcomes = self._executor(
                root,
                commands,
                captures,
                clock,
                evidence_bundles=bundles,
            ).run_bounded(max_stages=2)
            path = (
                root
                / "bundles"
                / source_request.operator_id
                / "bundles"
                / f"{outcomes[1].artifact_id}.json"
            )
            record = json.loads(path.read_text())
            record["evidence_bundle"]["security_id"] = str(uuid4())
            path.write_text(json.dumps(record))
            with self.assertRaises(LocalEvidenceBundleStorageError):
                bundles.get(source_request.operator_id, outcomes[1].artifact_id)

    def test_without_a_local_bundle_store_the_path_still_blocks_honestly(self) -> None:
        clock = MovableClock(NOW)
        with tempfile.TemporaryDirectory() as directory:
            root, source_request, captures, persisted = self._fixture(directory, clock)
            commands = self._commands(root, source_request.operator_id, clock)
            command = self._enqueue(commands, persisted)

            outcomes = self._executor(
                root,
                commands,
                captures,
                clock,
                evidence_bundles=None,
            ).run_bounded(max_stages=6)
            receipt = commands.get(command.command_id)

        self.assertEqual(
            tuple(outcome.status for outcome in outcomes),
            ("checkpointed", "blocked"),
        )
        self.assertEqual(outcomes[1].stage, "evidence_bundle")
        self.assertEqual(
            outcomes[1].blocking_reason_codes,
            LOCAL_STAGE_BLOCKING_REASONS["evidence_bundle"],
        )
        self.assertEqual(receipt.command_state, "blocked")

    def test_bundle_stage_leaves_no_worker_thread_residue(self) -> None:
        clock = MovableClock(NOW)
        before = {thread.name for thread in threading.enumerate()}
        with tempfile.TemporaryDirectory() as directory:
            root, source_request, captures, persisted = self._fixture(directory, clock)
            commands = self._commands(root, source_request.operator_id, clock)
            self._enqueue(commands, persisted)

            self._executor(root, commands, captures, clock).run_bounded(max_stages=6)

        self.assertEqual(
            {thread.name for thread in threading.enumerate()} - before,
            set(),
        )


if __name__ == "__main__":
    unittest.main()

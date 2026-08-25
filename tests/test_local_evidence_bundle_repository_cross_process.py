"""Cross-process concurrency proof for durable local Evidence Bundle storage.

The thread-based regression in `test_local_evidence_bundle_repository` cannot
prove the guarantee that matters: the desktop worker and the offline
acceptance CLI are separate operating-system processes, and a lock that only
excludes threads of one interpreter would still let two processes both claim
one research run. These tests therefore drive two independently spawned
processes, each building its own repository over the same storage root, and
pin the outcome to exactly one durable bundle.

The fixtures are seeded so both processes can build byte-identical bundles
without anything being pickled between them.

No provider, model, hosted, or network client is constructed here.
"""

from __future__ import annotations

import multiprocessing
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from investment_research_os.evidence_bundles import EvidenceBundleError
from investment_research_os.evidence_bundles.file_storage import (
    FileEvidenceBundleRepository,
    LocalEvidenceBundleStorageError,
)

from tests.test_local_evidence_bundle_repository import _bundle

# `spawn` is used explicitly rather than inherited from the platform default.
# A forked child would share the parent's already-open lock descriptors and
# could prove a weaker property than the one under test.
CONTEXT = multiprocessing.get_context("spawn")
JOIN_TIMEOUT_SECONDS = 60


def _save_in_child(
    root: str,
    operator_id: str,
    research_run_id: str,
    identity_seed: str,
    barrier: object,
    results: object,
) -> None:
    """Save one bundle from a process of its own and report the outcome.

    Runs in a spawned child, so it takes only picklable arguments and rebuilds
    both the bundle and the repository from scratch.
    """

    bundle = _bundle(
        operator_id=operator_id,
        research_run_id=research_run_id,
        identity_seed=identity_seed,
    )
    repository = FileEvidenceBundleRepository(Path(root))
    barrier.wait(timeout=JOIN_TIMEOUT_SECONDS)
    try:
        stored = repository.save(bundle)
    except EvidenceBundleError as error:
        results.put((identity_seed, "refused", type(error).__name__, str(error)))
    except LocalEvidenceBundleStorageError as error:  # pragma: no cover
        results.put((identity_seed, "storage_error", type(error).__name__, str(error)))
    else:
        results.put((identity_seed, "saved", stored.id, stored.research_run_id))


class CrossProcessEvidenceBundleSaveTests(unittest.TestCase):
    def _race(
        self,
        root: Path,
        operator_id: str,
        research_run_id: str,
        seeds: tuple[str, ...],
    ) -> list[tuple[str, str, str, str]]:
        barrier = CONTEXT.Barrier(len(seeds))
        results = CONTEXT.Queue()
        processes = [
            CONTEXT.Process(
                target=_save_in_child,
                args=(
                    str(root),
                    operator_id,
                    research_run_id,
                    seed,
                    barrier,
                    results,
                ),
            )
            for seed in seeds
        ]
        for process in processes:
            process.start()
        collected: list[tuple[str, str, str, str]] = []
        try:
            for _ in seeds:
                collected.append(results.get(timeout=JOIN_TIMEOUT_SECONDS))
        finally:
            for process in processes:
                process.join(timeout=JOIN_TIMEOUT_SECONDS)
                if process.is_alive():  # pragma: no cover
                    process.terminate()
                    process.join(timeout=JOIN_TIMEOUT_SECONDS)
        for process in processes:
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(len(collected), len(seeds))
        return collected

    def test_two_processes_saving_one_run_leave_exactly_one_bundle(self) -> None:
        operator_id = str(uuid4())
        research_run_id = str(uuid4())
        seeds = ("cross-process-first", "cross-process-second")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "bundles"
            collected = self._race(root, operator_id, research_run_id, seeds)

            outcomes = sorted(result[1] for result in collected)
            self.assertEqual(outcomes, ["refused", "saved"])
            winner = next(
                result for result in collected if result[1] == "saved"
            )
            loser = next(result for result in collected if result[1] == "refused")
            winner_seed, loser_seed = winner[0], loser[0]
            self.assertNotEqual(winner_seed, loser_seed)
            self.assertEqual(loser[2], "EvidenceBundleError")

            expected = _bundle(
                operator_id=operator_id,
                research_run_id=research_run_id,
                identity_seed=winner_seed,
            )
            orphan = _bundle(
                operator_id=operator_id,
                research_run_id=research_run_id,
                identity_seed=loser_seed,
            )
            self.assertNotEqual(expected.id, orphan.id)
            self.assertEqual(winner[2], expected.id)
            self.assertEqual(winner[3], research_run_id)

            bundle_records = sorted(
                path.name for path in (root / operator_id / "bundles").iterdir()
            )
            run_records = sorted(
                path.name for path in (root / operator_id / "runs").iterdir()
            )
            self.assertEqual(bundle_records, [f"{expected.id}.json"])
            self.assertEqual(run_records, [f"{research_run_id}.json"])

            # Reopening the repository proves the winner is durable and that
            # the loser left no record reachable by id or by run.
            reopened = FileEvidenceBundleRepository(root)
            self.assertEqual(reopened.get(operator_id, expected.id), expected)
            self.assertEqual(
                reopened.get_for_run(operator_id, research_run_id), expected
            )
            self.assertIsNone(reopened.get(operator_id, orphan.id))

    def test_two_processes_saving_one_bundle_stay_idempotent(self) -> None:
        # The losing process must not be punished for a byte-identical bundle:
        # an immutable record replayed across processes still resolves to one
        # record and one run claim.
        operator_id = str(uuid4())
        research_run_id = str(uuid4())
        seed = "cross-process-identical"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "bundles"
            collected = self._race(
                root, operator_id, research_run_id, (seed, seed)
            )

            expected = _bundle(
                operator_id=operator_id,
                research_run_id=research_run_id,
                identity_seed=seed,
            )
            self.assertEqual([result[1] for result in collected], ["saved"] * 2)
            self.assertEqual({result[2] for result in collected}, {expected.id})

            bundle_records = sorted(
                path.name for path in (root / operator_id / "bundles").iterdir()
            )
            run_records = sorted(
                path.name for path in (root / operator_id / "runs").iterdir()
            )
            self.assertEqual(bundle_records, [f"{expected.id}.json"])
            self.assertEqual(run_records, [f"{research_run_id}.json"])
            self.assertEqual(
                FileEvidenceBundleRepository(root).get_for_run(
                    operator_id, research_run_id
                ),
                expected,
            )


if __name__ == "__main__":
    unittest.main()

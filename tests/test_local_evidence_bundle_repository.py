"""Durable local Evidence Bundle persistence.

`InMemoryEvidenceBundleRepository` cannot survive a restart and the Supabase
repository needs hosted access, so the desktop-local command path had no way
to persist the one artifact the `evidence_bundle` stage produces. These tests
pin the durable local adapter to the same `EvidenceBundleRepository` port.

No provider, model, hosted, or network client is constructed here.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from investment_research_os.evidence_bundles import (
    CatalystSnapshot,
    EvidenceBundle,
    EvidenceBundleError,
    EvidenceGap,
    EvidenceItem,
    RiskSnapshot,
    VerifiedMetricSnapshot,
)
from investment_research_os.evidence_bundles.file_storage import (
    RECORD_CONTRACT_VERSION,
    FileEvidenceBundleRepository,
    LocalEvidenceBundleStorageError,
)
from investment_research_os.research_runs import (
    EligibilityCheck,
    EligibilityResult,
    SecurityIdentity,
)


CUTOFF = datetime(2026, 5, 6, tzinfo=UTC)
CREATED_AT = datetime(2026, 5, 7, 4, tzinfo=UTC)
OPERATOR_ID = str(uuid4())
OTHER_OPERATOR_ID = str(uuid4())


def _identity(seed: str | None, label: str) -> str:
    """Return a random identity, or a reproducible one when a seed is given.

    A cross-process test cannot pickle a fixture between two independently
    spawned processes, so both must be able to build the byte-identical
    bundle from a seed alone.
    """

    if seed is None:
        return str(uuid4())
    return str(uuid5(NAMESPACE_URL, f"local-evidence-bundle/{seed}/{label}"))


def _bundle(
    *,
    operator_id: str = OPERATOR_ID,
    bundle_id: str | None = None,
    research_run_id: str | None = None,
    content_hash: str = "a" * 64,
    with_snapshots: bool = True,
    identity_seed: str | None = None,
) -> EvidenceBundle:
    passage_id = _identity(identity_seed, "passage")
    metric_id = _identity(identity_seed, "metric")
    catalyst_id = _identity(identity_seed, "catalyst")
    risk_id = _identity(identity_seed, "risk")
    manifest = (
        EvidenceItem(
            evidence_id=passage_id,
            evidence_version_id=_identity(identity_seed, "evidence-version"),
            provenance_type="primary",
            item_kind="passage",
            source_class="sec",
            source_locator="0000320193-26-000010",
            canonical_url="https://www.sec.gov/Archives/example.htm",
            publication_at=datetime(2026, 4, 1, tzinfo=UTC),
            retrieved_at=datetime(2026, 5, 5, tzinfo=UTC),
            effective_at=datetime(2026, 4, 1, tzinfo=UTC),
            filing_period_start=date(2026, 1, 1),
            filing_period_end=date(2026, 3, 31),
            content_hash="b" * 64,
            passage_id=_identity(identity_seed, "passage-locator"),
            passage_hash="c" * 64,
            freshness="fresh",
            passage_text="Cash and equivalents were 412.0 million dollars.",
        ),
    )
    if not with_snapshots:
        return EvidenceBundle(
            id=bundle_id or _identity(identity_seed, "bundle"),
            operator_id=operator_id,
            research_run_id=research_run_id or _identity(identity_seed, "run"),
            security_id=_identity(identity_seed, "security"),
            security_identity=SecurityIdentity(
                id=_identity(identity_seed, "security-identity"),
                cik="0000320193",
                issuer_name="Example Therapeutics Inc",
                symbol="EXTX",
                primary_listing_exchange="NASDAQ",
            ),
            as_of_cutoff=CUTOFF,
            content_hash=content_hash,
            manifest=manifest,
            metrics=(),
            catalysts=(),
            risks=(),
            grader_ready=False,
            gaps=(),
            eligibility=_eligibility(),
            evidence_policy_version="biotech-primary-evidence-v3",
            freshness_policy_version="biotech-evidence-freshness-v1",
            created_at=CREATED_AT,
        )
    return EvidenceBundle(
        id=bundle_id or _identity(identity_seed, "bundle"),
        operator_id=operator_id,
        research_run_id=research_run_id or _identity(identity_seed, "run"),
        security_id=_identity(identity_seed, "security"),
        security_identity=SecurityIdentity(
            id=_identity(identity_seed, "security-identity"),
            cik="0000320193",
            issuer_name="Example Therapeutics Inc",
            symbol="EXTX",
            primary_listing_exchange="NASDAQ",
        ),
        as_of_cutoff=CUTOFF,
        content_hash=content_hash,
        manifest=manifest,
        metrics=(
            VerifiedMetricSnapshot(
                snapshot_id=metric_id,
                metric_key="cash_and_equivalents",
                value="412000000",
                unit="USD",
                period_start=date(2026, 1, 1),
                period_end=date(2026, 3, 31),
                calculation_method="reported",
                formula=None,
                supporting_evidence_ids=(passage_id,),
            ),
        ),
        catalysts=(
            CatalystSnapshot(
                snapshot_id=catalyst_id,
                event="Phase 2 readout",
                program="EXTX-101",
                basis="clinical",
                status="expected",
                window_start=date(2026, 7, 1),
                window_end=date(2026, 9, 30),
                supporting_evidence_ids=(passage_id,),
            ),
        ),
        risks=(
            RiskSnapshot(
                snapshot_id=risk_id,
                title="Financing runway",
                risk_type="financing",
                severity="high",
                status="open",
                supporting_evidence_ids=(passage_id,),
            ),
        ),
        grader_ready=False,
        gaps=(
            EvidenceGap(
                code="missing_blocking_regulatory_evidence",
                source_class="regulatory",
                blocking=True,
                explanation="Blocking regulatory primary evidence is unavailable.",
                requirement_id="regulatory_primary_evidence",
                reason_code="missing_blocking_primary_evidence",
            ),
        ),
        eligibility=_eligibility(),
        evidence_policy_version="biotech-primary-evidence-v3",
        freshness_policy_version="biotech-evidence-freshness-v1",
        created_at=CREATED_AT,
    )


def _eligibility() -> EligibilityResult:
    return EligibilityResult(
        policy_version="biotech-eligibility-v1",
        eligible=True,
        checks=(
            EligibilityCheck(
                rule_id="listed_on_supported_exchange",
                rule_version="v1",
                passed=True,
                evidence_reference=None,
                reason_code="listing_supported",
                explanation="Security is listed on a supported exchange.",
                evaluated_at=datetime(2026, 5, 6, 12, tzinfo=UTC),
            ),
        ),
        evaluated_at=datetime(2026, 5, 6, 12, tzinfo=UTC),
    )


class FileEvidenceBundleRepositoryTests(unittest.TestCase):
    def test_saved_bundle_round_trips_losslessly(self) -> None:
        bundle = _bundle()
        with tempfile.TemporaryDirectory() as directory:
            repository = FileEvidenceBundleRepository(Path(directory) / "bundles")
            saved = repository.save(bundle)
            loaded = repository.get(bundle.operator_id, bundle.id)
        self.assertEqual(saved, bundle)
        self.assertEqual(loaded, bundle)

    def test_bundle_survives_restart_through_a_new_repository(self) -> None:
        bundle = _bundle()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "bundles"
            FileEvidenceBundleRepository(root).save(bundle)
            reloaded = FileEvidenceBundleRepository(root).get(
                bundle.operator_id,
                bundle.id,
            )
            by_run = FileEvidenceBundleRepository(root).get_for_run(
                bundle.operator_id,
                bundle.research_run_id,
            )
        self.assertEqual(reloaded, bundle)
        self.assertEqual(by_run, bundle)

    def test_bundle_without_snapshots_round_trips(self) -> None:
        bundle = _bundle(with_snapshots=False)
        with tempfile.TemporaryDirectory() as directory:
            repository = FileEvidenceBundleRepository(Path(directory) / "bundles")
            repository.save(bundle)
            loaded = repository.get(bundle.operator_id, bundle.id)
        self.assertEqual(loaded, bundle)

    def test_replayed_save_is_idempotent_and_creates_no_second_record(self) -> None:
        bundle = _bundle()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "bundles"
            repository = FileEvidenceBundleRepository(root)
            first = repository.save(bundle)
            second = repository.save(bundle)
            records = sorted(path.name for path in root.rglob("*.json"))
        self.assertEqual(first, bundle)
        self.assertEqual(second, bundle)
        self.assertEqual(
            records,
            sorted([f"{bundle.id}.json", f"{bundle.research_run_id}.json"]),
        )

    def test_conflicting_bundle_for_same_identity_is_refused(self) -> None:
        bundle = _bundle()
        conflicting = _bundle(
            bundle_id=bundle.id,
            research_run_id=bundle.research_run_id,
            content_hash="d" * 64,
        )
        with tempfile.TemporaryDirectory() as directory:
            repository = FileEvidenceBundleRepository(Path(directory) / "bundles")
            repository.save(bundle)
            with self.assertRaises(EvidenceBundleError):
                repository.save(conflicting)

    def test_second_bundle_for_one_research_run_is_refused(self) -> None:
        bundle = _bundle()
        rival = _bundle(research_run_id=bundle.research_run_id)
        with tempfile.TemporaryDirectory() as directory:
            repository = FileEvidenceBundleRepository(Path(directory) / "bundles")
            repository.save(bundle)
            with self.assertRaises(EvidenceBundleError):
                repository.save(rival)

    def test_another_operator_cannot_read_the_bundle(self) -> None:
        bundle = _bundle()
        with tempfile.TemporaryDirectory() as directory:
            repository = FileEvidenceBundleRepository(Path(directory) / "bundles")
            repository.save(bundle)
            self.assertIsNone(repository.get(OTHER_OPERATOR_ID, bundle.id))
            self.assertIsNone(
                repository.get_for_run(OTHER_OPERATOR_ID, bundle.research_run_id)
            )

    def test_bundles_of_two_operators_stay_in_separate_directories(self) -> None:
        mine = _bundle()
        theirs = _bundle(operator_id=OTHER_OPERATOR_ID)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "bundles"
            repository = FileEvidenceBundleRepository(root)
            repository.save(mine)
            repository.save(theirs)
            self.assertEqual(repository.get(OPERATOR_ID, mine.id), mine)
            self.assertEqual(
                repository.get(OTHER_OPERATOR_ID, theirs.id),
                theirs,
            )
            self.assertIsNone(repository.get(OPERATOR_ID, theirs.id))
            operators = sorted(path.name for path in root.iterdir())
        self.assertEqual(operators, sorted([OPERATOR_ID, OTHER_OPERATOR_ID]))

    def test_tampered_bundle_record_is_refused_rather_than_returned(self) -> None:
        bundle = _bundle()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "bundles"
            repository = FileEvidenceBundleRepository(root)
            repository.save(bundle)
            path = root / bundle.operator_id / "bundles" / f"{bundle.id}.json"
            record = json.loads(path.read_text())
            record["evidence_bundle"]["security_id"] = str(uuid4())
            path.write_text(json.dumps(record))
            with self.assertRaises(LocalEvidenceBundleStorageError):
                repository.get(bundle.operator_id, bundle.id)

    def test_tampered_passage_text_is_refused(self) -> None:
        bundle = _bundle()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "bundles"
            repository = FileEvidenceBundleRepository(root)
            repository.save(bundle)
            path = root / bundle.operator_id / "bundles" / f"{bundle.id}.json"
            record = json.loads(path.read_text())
            record["evidence_bundle"]["manifest"][0]["passage_text"] = "rewritten"
            path.write_text(json.dumps(record))
            with self.assertRaises(LocalEvidenceBundleStorageError):
                repository.get(bundle.operator_id, bundle.id)

    def test_record_of_an_unknown_contract_version_is_refused(self) -> None:
        bundle = _bundle()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "bundles"
            repository = FileEvidenceBundleRepository(root)
            repository.save(bundle)
            path = root / bundle.operator_id / "bundles" / f"{bundle.id}.json"
            record = json.loads(path.read_text())
            self.assertEqual(record["contract_version"], RECORD_CONTRACT_VERSION)
            record["contract_version"] = "local_evidence_bundle_record.v99"
            path.write_text(json.dumps(record))
            with self.assertRaises(LocalEvidenceBundleStorageError):
                repository.get(bundle.operator_id, bundle.id)

    def test_unreadable_record_is_refused_rather_than_treated_as_absent(self) -> None:
        bundle = _bundle()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "bundles"
            repository = FileEvidenceBundleRepository(root)
            repository.save(bundle)
            path = root / bundle.operator_id / "bundles" / f"{bundle.id}.json"
            path.write_text("{not json")
            with self.assertRaises(LocalEvidenceBundleStorageError):
                repository.get(bundle.operator_id, bundle.id)

    def test_missing_bundle_reads_as_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = FileEvidenceBundleRepository(Path(directory) / "bundles")
            self.assertIsNone(repository.get(OPERATOR_ID, str(uuid4())))
            self.assertIsNone(repository.get_for_run(OPERATOR_ID, str(uuid4())))

    def test_symlinked_record_is_never_read(self) -> None:
        bundle = _bundle()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "bundles"
            repository = FileEvidenceBundleRepository(root)
            repository.save(bundle)
            path = root / bundle.operator_id / "bundles" / f"{bundle.id}.json"
            elsewhere = Path(directory) / "elsewhere.json"
            elsewhere.write_bytes(path.read_bytes())
            path.unlink()
            path.symlink_to(elsewhere)
            self.assertIsNone(repository.get(bundle.operator_id, bundle.id))

    def test_symlinked_storage_root_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            real = Path(directory) / "real"
            real.mkdir()
            link = Path(directory) / "link"
            link.symlink_to(real)
            with self.assertRaises(LocalEvidenceBundleStorageError):
                FileEvidenceBundleRepository(link)

    def test_non_uuid_identities_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = FileEvidenceBundleRepository(Path(directory) / "bundles")
            with self.assertRaises(LocalEvidenceBundleStorageError):
                repository.get("../escape", str(uuid4()))
            with self.assertRaises(LocalEvidenceBundleStorageError):
                repository.get(OPERATOR_ID, "../escape")
            with self.assertRaises(LocalEvidenceBundleStorageError):
                repository.get_for_run(OPERATOR_ID, "../escape")

    def test_records_are_private_to_the_operator_account(self) -> None:
        bundle = _bundle()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "bundles"
            FileEvidenceBundleRepository(root).save(bundle)
            path = root / bundle.operator_id / "bundles" / f"{bundle.id}.json"
            self.assertEqual(os.stat(root).st_mode & 0o777, 0o700)
            self.assertEqual(os.stat(path.parent).st_mode & 0o777, 0o700)
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_symlinked_operator_directory_is_never_read(self) -> None:
        # Checking only the immediate parent would let a symlinked operator
        # directory serve records from outside the storage root.
        bundle = _bundle()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "bundles"
            repository = FileEvidenceBundleRepository(root)
            repository.save(bundle)
            operator_root = root / bundle.operator_id
            elsewhere = Path(directory) / "elsewhere"
            operator_root.rename(elsewhere)
            operator_root.symlink_to(elsewhere)
            self.assertIsNone(repository.get(bundle.operator_id, bundle.id))
            self.assertIsNone(
                repository.get_for_run(bundle.operator_id, bundle.research_run_id)
            )

    def test_symlinked_operator_directory_is_never_written_through(self) -> None:
        bundle = _bundle()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "bundles"
            repository = FileEvidenceBundleRepository(root)
            elsewhere = Path(directory) / "elsewhere"
            elsewhere.mkdir()
            (root / bundle.operator_id).symlink_to(elsewhere)
            with self.assertRaises(LocalEvidenceBundleStorageError):
                repository.save(bundle)
            self.assertEqual(list(elsewhere.iterdir()), [])

    def test_symlinked_bundle_directory_is_never_written_through(self) -> None:
        bundle = _bundle()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "bundles"
            repository = FileEvidenceBundleRepository(root)
            elsewhere = Path(directory) / "elsewhere"
            elsewhere.mkdir()
            operator_root = root / bundle.operator_id
            operator_root.mkdir(parents=True)
            (operator_root / "bundles").symlink_to(elsewhere)
            with self.assertRaises(LocalEvidenceBundleStorageError):
                repository.save(bundle)
            self.assertEqual(list(elsewhere.iterdir()), [])

    def test_concurrent_saves_for_one_run_leave_no_orphaned_bundle(self) -> None:
        # Two processes claiming one research run must resolve to exactly one
        # bundle record. Without a lock around the claim and the write, both
        # read an unclaimed index and both write.
        research_run_id = str(uuid4())
        first = _bundle(research_run_id=research_run_id)
        second = _bundle(research_run_id=research_run_id)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "bundles"
            repository = FileEvidenceBundleRepository(root)
            barrier = threading.Barrier(2)
            failures: list[BaseException] = []

            def attempt(bundle: EvidenceBundle) -> None:
                barrier.wait()
                try:
                    FileEvidenceBundleRepository(root).save(bundle)
                except BaseException as error:  # noqa: BLE001
                    failures.append(error)

            workers = [
                threading.Thread(target=attempt, args=(first,)),
                threading.Thread(target=attempt, args=(second,)),
            ]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=30)
                self.assertFalse(worker.is_alive())

            self.assertEqual(len(failures), 1)
            self.assertIsInstance(failures[0], EvidenceBundleError)
            stored = repository.get_for_run(OPERATOR_ID, research_run_id)
            self.assertIsNotNone(stored)
            records = sorted(
                (root / OPERATOR_ID / "bundles").iterdir()
            )
            self.assertEqual(
                [path.name for path in records], [f"{stored.id}.json"]
            )


if __name__ == "__main__":
    unittest.main()

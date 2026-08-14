from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

from investment_research_os.evidence_bundles import EvidenceBundleCandidate
from investment_research_os.research_runs import (
    CatalystCandidate,
    EvidenceReference,
    InMemoryResearchRunRepository,
    REQUIRED_PRIMARY_SOURCE_COVERAGE,
    RULE_IDS,
    SecurityEligibilitySnapshot,
)
from tests.test_persistent_committee_worker import command_claim
from tests.test_primary_source_captures import (
    archive_bytes,
    capture_value,
    request,
)
from workers.primary_sources.captures import load_primary_source_capture
from workers.primary_sources.pipeline import PrimarySourcePipelineResult
from workers.primary_sources.storage import FilePrimarySourceCaptureRepository
from workers.research_committee.capture_research_run import (
    AcceptedCaptureResearchInput,
    AcceptedCaptureResearchRunStage,
)
from workers.research_committee.worker import ResearchRunStageError


ACCEPTED_AT = datetime(2026, 5, 7, 3, tzinfo=UTC)
NOW = datetime(2026, 5, 7, 4, tzinfo=UTC)


class FixedCaptureResolver:
    def __init__(self, value: AcceptedCaptureResearchInput) -> None:
        self.value = value
        self.calls = 0

    def resolve(self, claim):
        self.calls += 1
        return self.value


class PipelineAssemblerFake:
    def __init__(self) -> None:
        self.calls = 0

    def assemble_result(
        self,
        raw_archive: bytes,
        *,
        request,
        ticker: str,
        sec_user_agent: str,
        trusted_issuer_hosts: tuple[str, ...],
        accepted_at: datetime,
    ) -> PrimarySourcePipelineResult:
        self.calls += 1
        self.raw_archive = raw_archive
        self.request = request
        self.ticker = ticker
        evidence = {
            rule_id: EvidenceReference(
                evidence_id=f"evidence-{rule_id}",
                available_at=request.as_of_cutoff,
            )
            for rule_id in RULE_IDS
        }
        return PrimarySourcePipelineResult(
            eligibility_snapshot=SecurityEligibilitySnapshot(
                security_id=request.security_id,
                as_of_cutoff=request.as_of_cutoff,
                issuer_name=request.issuer_name,
                display_symbol=ticker,
                security_identity_verified=True,
                primary_listing_country="US",
                primary_listing_exchange=request.primary_listing_exchange,
                cik=request.cik,
                cik_matches_issuer=True,
                security_type="common_equity",
                issuer_status="operating",
                therapeutics_classification="therapeutics_biotech",
                active_therapeutic_programs=("REC-4881",),
                catalysts=(
                    CatalystCandidate(
                        event="Phase 2 data",
                        program="REC-4881",
                        basis="clinical",
                        window_start=date(2026, 6, 1).isoformat(),
                        window_end=date(2026, 12, 31).isoformat(),
                    ),
                ),
                primary_source_coverage=REQUIRED_PRIMARY_SOURCE_COVERAGE,
                evidence_by_rule=evidence,
            ),
            bundle_candidate=EvidenceBundleCandidate(
                security_id=request.security_id,
                as_of_cutoff=request.as_of_cutoff,
                evidence_policy_version="biotech-primary-evidence-v3",
                freshness_policy_version="biotech-evidence-freshness-v1",
                items=(),
            ),
            reason_codes=("primary_source_coverage_complete",),
        )


class DriftedIdentityAssembler(PipelineAssemblerFake):
    def assemble_result(self, *args, **kwargs) -> PrimarySourcePipelineResult:
        result = super().assemble_result(*args, **kwargs)
        return replace(
            result,
            eligibility_snapshot=replace(
                result.eligibility_snapshot,
                cik="0000000001",
                issuer_name="Different Issuer, Inc.",
                display_symbol="OTHER",
                primary_listing_exchange="NYSE",
            ),
        )


class CountingResearchRunRepository(InMemoryResearchRunRepository):
    def __init__(self) -> None:
        super().__init__()
        self.save_calls = 0

    def save(self, run):
        self.save_calls += 1
        return super().save(run)


class ArchiveUnavailableRepository(FilePrimarySourceCaptureRepository):
    unavailable = False

    def read_archive(self, operator_id: str, capture_id: str, revision: int) -> bytes:
        if self.unavailable:
            raise OSError("capture disk unavailable")
        return super().read_archive(operator_id, capture_id, revision)


class BindingUnavailableRepository(FilePrimarySourceCaptureRepository):
    unavailable = False

    def bind_to_run(self, *args, **kwargs):
        if self.unavailable:
            raise OSError("binding disk unavailable")
        return super().bind_to_run(*args, **kwargs)


class AcceptedCaptureResearchRunStageTests(unittest.TestCase):
    def _fixture(
        self,
        directory: str,
        repository_type=FilePrimarySourceCaptureRepository,
    ):
        value, payloads, source_plan = capture_value()
        raw_archive = archive_bytes(value, payloads, source_plan)
        capture = load_primary_source_capture(
            raw_archive,
            request=request(),
            trusted_issuer_hosts=("ir.recursion.com",),
            accepted_at=lambda: ACCEPTED_AT,
        )
        captures = repository_type(Path(directory))
        persisted = captures.save_capture(capture, raw_archive)
        resolver = FixedCaptureResolver(
            AcceptedCaptureResearchInput(
                capture=persisted,
                request=request(),
                ticker="RXRX",
                trusted_issuer_hosts=("ir.recursion.com",),
            )
        )
        assembler = PipelineAssemblerFake()
        runs = CountingResearchRunRepository()
        stage = AcceptedCaptureResearchRunStage(
            research_run_repository=runs,
            capture_repository=captures,
            capture_resolver=resolver,
            assembler=assembler,
            sec_user_agent="Investment Research OS research@example.com",
            clock=lambda: NOW,
        )
        return captures, persisted, resolver, assembler, runs, stage

    def test_persists_run_then_binds_same_capture_idempotently(self) -> None:
        claim = replace(
            command_claim(),
            operator_id=request().operator_id,
            security_id=request().security_id,
            as_of_cutoff=request().as_of_cutoff,
            operator_focus=None,
        )

        with tempfile.TemporaryDirectory() as directory:
            captures, persisted, resolver, assembler, runs, stage = self._fixture(
                directory
            )

            first_run_id = stage.execute(claim)
            second_run_id = stage.execute(claim)
            binding = captures.get_for_run(claim.operator_id, first_run_id)
            run = runs.get(claim.operator_id, first_run_id)

        self.assertEqual(second_run_id, first_run_id)
        self.assertIsNotNone(run)
        self.assertTrue(run.eligibility.eligible)
        self.assertIsNotNone(binding)
        self.assertEqual(binding.capture_id, persisted.capture_id)
        self.assertEqual(binding.package_sha256, persisted.package_sha256)
        self.assertEqual(binding.evidence_policy_version, "biotech-primary-evidence-v3")
        self.assertEqual(assembler.calls, 1)
        self.assertEqual(resolver.calls, 2)

    def test_rejects_foreign_capture_before_replay_or_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, _, _, assembler, _, stage = self._fixture(directory)
            foreign_claim = replace(
                command_claim(),
                operator_id=request().operator_id,
                security_id="99999999-9999-4999-8999-999999999999",
                as_of_cutoff=request().as_of_cutoff,
                operator_focus=None,
            )

            with self.assertRaisesRegex(
                ResearchRunStageError,
                "research_run_accepted_capture_invalid",
            ):
                stage.execute(foreign_claim)

        self.assertEqual(assembler.calls, 0)

    def test_rejects_forged_capture_metadata_before_replay_or_run_save(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            captures, persisted, _, assembler, runs, _ = self._fixture(directory)
            resolver = FixedCaptureResolver(
                AcceptedCaptureResearchInput(
                    capture=replace(persisted, package_sha256="0" * 64),
                    request=request(),
                    ticker="RXRX",
                    trusted_issuer_hosts=("ir.recursion.com",),
                )
            )
            stage = AcceptedCaptureResearchRunStage(
                research_run_repository=runs,
                capture_repository=captures,
                capture_resolver=resolver,
                assembler=assembler,
                sec_user_agent="Investment Research OS research@example.com",
                clock=lambda: NOW,
            )
            claim = replace(
                command_claim(),
                operator_id=request().operator_id,
                security_id=request().security_id,
                as_of_cutoff=request().as_of_cutoff,
                operator_focus=None,
            )

            with self.assertRaisesRegex(
                ResearchRunStageError,
                "research_run_accepted_capture_invalid",
            ):
                stage.execute(claim)

        self.assertEqual(assembler.calls, 0)
        self.assertEqual(runs.save_calls, 0)

    def test_existing_run_rejects_drifted_security_identity_input(self) -> None:
        claim = replace(
            command_claim(),
            operator_id=request().operator_id,
            security_id=request().security_id,
            as_of_cutoff=request().as_of_cutoff,
            operator_focus=None,
        )
        with tempfile.TemporaryDirectory() as directory:
            captures, persisted, _, _, runs, stage = self._fixture(directory)
            stage.execute(claim)
            replay = PipelineAssemblerFake()
            drifted_stage = AcceptedCaptureResearchRunStage(
                research_run_repository=runs,
                capture_repository=captures,
                capture_resolver=FixedCaptureResolver(
                    AcceptedCaptureResearchInput(
                        capture=persisted,
                        request=replace(
                            request(),
                            issuer_name="Different Issuer, Inc.",
                        ),
                        ticker="RXRX",
                        trusted_issuer_hosts=("ir.recursion.com",),
                    )
                ),
                assembler=replay,
                sec_user_agent="Investment Research OS research@example.com",
                clock=lambda: NOW,
            )

            with self.assertRaisesRegex(
                ResearchRunStageError,
                "research_run_capture_binding_invalid",
            ):
                drifted_stage.execute(claim)

        self.assertEqual(replay.calls, 0)

    def test_rejects_replayed_security_identity_before_run_save(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            captures, persisted, _, _, runs, _ = self._fixture(directory)
            assembler = DriftedIdentityAssembler()
            stage = AcceptedCaptureResearchRunStage(
                research_run_repository=runs,
                capture_repository=captures,
                capture_resolver=FixedCaptureResolver(
                    AcceptedCaptureResearchInput(
                        capture=persisted,
                        request=request(),
                        ticker="RXRX",
                        trusted_issuer_hosts=("ir.recursion.com",),
                    )
                ),
                assembler=assembler,
                sec_user_agent="Investment Research OS research@example.com",
                clock=lambda: NOW,
            )
            claim = replace(
                command_claim(),
                operator_id=request().operator_id,
                security_id=request().security_id,
                as_of_cutoff=request().as_of_cutoff,
                operator_focus=None,
            )

            with self.assertRaisesRegex(
                ResearchRunStageError,
                "research_run_accepted_capture_replay_invalid",
            ):
                stage.execute(claim)

        self.assertEqual(runs.save_calls, 0)

    def test_classifies_archive_io_failure_as_retryable_before_run_save(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            captures, _, _, _, runs, stage = self._fixture(
                directory,
                ArchiveUnavailableRepository,
            )
            captures.unavailable = True
            claim = replace(
                command_claim(),
                operator_id=request().operator_id,
                security_id=request().security_id,
                as_of_cutoff=request().as_of_cutoff,
                operator_focus=None,
            )

            with self.assertRaises(ResearchRunStageError) as raised:
                stage.execute(claim)

        self.assertEqual(
            raised.exception.error_code,
            "research_run_accepted_capture_replay_unavailable",
        )
        self.assertTrue(raised.exception.retryable)
        self.assertEqual(runs.save_calls, 0)

    def test_classifies_binding_io_failure_as_retryable_after_run_save(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            captures, _, _, _, runs, stage = self._fixture(
                directory,
                BindingUnavailableRepository,
            )
            captures.unavailable = True
            claim = replace(
                command_claim(),
                operator_id=request().operator_id,
                security_id=request().security_id,
                as_of_cutoff=request().as_of_cutoff,
                operator_focus=None,
            )

            with self.assertRaises(ResearchRunStageError) as raised:
                stage.execute(claim)

        self.assertEqual(
            raised.exception.error_code,
            "research_run_capture_binding_unavailable",
        )
        self.assertTrue(raised.exception.retryable)
        self.assertEqual(runs.save_calls, 1)


if __name__ == "__main__":
    unittest.main()

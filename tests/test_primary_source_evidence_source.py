from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from investment_research_os.evidence_bundles import (
    EvidenceBundleCandidate,
    EvidenceBundleWorkflow,
    InMemoryEvidenceBundleRepository,
)
from investment_research_os.research_runs import (
    AuthenticatedOperator,
    InMemoryResearchRunRepository,
    SecurityIdentity,
)
from tests.test_primary_source_captures import archive_bytes, capture_value, request
from tests.test_primary_source_end_to_end import (
    PLATFORM_CASE,
    request as integrated_request,
)
from tests.test_primary_source_replay import (
    CORPORATE_ACTION_NO_CHANGE,
    _platform_capture_archive,
)
from tests.test_primary_source_plans import research_run
from workers.primary_sources.captures import load_primary_source_capture
from workers.primary_sources.evidence_source import (
    PersistedPrimarySourceEvidenceError,
    PersistedPrimarySourceEvidenceSource,
    ReplayEvidenceCandidateAssembler,
)
from workers.primary_sources.storage import FilePrimarySourceCaptureRepository


class CandidateAssemblerFake:
    def __init__(
        self,
        evidence_policy_version: str = "biotech-primary-evidence-v2",
    ) -> None:
        self.evidence_policy_version = evidence_policy_version

    def assemble(
        self,
        raw_archive: bytes,
        *,
        request,
        ticker: str,
        sec_user_agent: str,
        trusted_issuer_hosts: tuple[str, ...],
        accepted_at: datetime,
    ) -> EvidenceBundleCandidate:
        self.raw_archive = raw_archive
        self.request = request
        self.ticker = ticker
        self.sec_user_agent = sec_user_agent
        self.trusted_issuer_hosts = trusted_issuer_hosts
        self.accepted_at = accepted_at
        return EvidenceBundleCandidate(
            security_id=request.security_id,
            as_of_cutoff=request.as_of_cutoff,
            evidence_policy_version=self.evidence_policy_version,
            freshness_policy_version="biotech-evidence-freshness-v1",
            items=(),
        )


class PersistedPrimarySourceEvidenceSourceTests(unittest.TestCase):
    def test_bound_capture_materializes_grader_ready_bundle_after_restart(
        self,
    ) -> None:
        raw_archive = _platform_capture_archive()
        source_request = integrated_request(PLATFORM_CASE)
        accepted_at = datetime(2026, 5, 7, 3, tzinfo=UTC)
        capture = load_primary_source_capture(
            raw_archive,
            request=source_request,
            trusted_issuer_hosts=PLATFORM_CASE.issuer_trusted_hosts,
            accepted_at=lambda: accepted_at,
        )
        run = replace(
            research_run(),
            security_id=PLATFORM_CASE.security_id,
            security_identity=SecurityIdentity(
                id=PLATFORM_CASE.security_id,
                cik=PLATFORM_CASE.cik,
                issuer_name=PLATFORM_CASE.issuer_name,
                symbol=PLATFORM_CASE.display_symbol,
                primary_listing_exchange="NASDAQ",
            ),
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = FilePrimarySourceCaptureRepository(root)
            persisted = first.save_capture(capture, raw_archive)
            first.bind_to_run(
                persisted,
                run,
                evidence_policy_version="biotech-primary-evidence-v2",
                bound_at=datetime(2026, 5, 7, 4, tzinfo=UTC),
            )
            source = PersistedPrimarySourceEvidenceSource(
                repository=FilePrimarySourceCaptureRepository(root),
                research_run=run,
                assembler=ReplayEvidenceCandidateAssembler(),
                sec_user_agent="Investment Research OS research@example.com",
                trusted_issuer_hosts=PLATFORM_CASE.issuer_trusted_hosts,
            )
            runs = InMemoryResearchRunRepository()
            runs.save(run)
            bundle = EvidenceBundleWorkflow(
                research_run_repository=runs,
                bundle_repository=InMemoryEvidenceBundleRepository(),
                evidence_source=source,
                clock=lambda: datetime(2026, 5, 7, 5, tzinfo=UTC),
            ).materialize(AuthenticatedOperator(run.operator_id), run.id)

        self.assertTrue(bundle.grader_ready)
        self.assertEqual(bundle.gaps, ())
        self.assertEqual(
            {item.source_class for item in bundle.manifest},
            {"sec", "issuer", "clinical", "regulatory", "financing"},
        )

    def test_replay_assembler_builds_candidate_without_network_fallback(
        self,
    ) -> None:
        candidate = ReplayEvidenceCandidateAssembler().assemble(
            _platform_capture_archive(),
            request=integrated_request(PLATFORM_CASE),
            ticker=PLATFORM_CASE.display_symbol,
            sec_user_agent="Investment Research OS research@example.com",
            trusted_issuer_hosts=PLATFORM_CASE.issuer_trusted_hosts,
            accepted_at=datetime(2026, 5, 7, 3, tzinfo=UTC),
        )

        self.assertEqual(candidate.security_id, PLATFORM_CASE.security_id)
        self.assertEqual(
            {item.source_class for item in candidate.items},
            {"sec", "issuer", "clinical", "regulatory", "financing"},
        )
        self.assertEqual(candidate.declared_gaps, ())
        self.assertEqual(len(candidate.catalysts), 2)
        share_observations = tuple(
            item
            for item in candidate.items
            if item.item_kind == "passage"
            and item.source_class == "financing"
            and "#observation=" in item.source_locator
        )
        self.assertEqual(share_observations, ())

    def test_v3_replay_derives_share_growth_only_with_frozen_reconciliation(
        self,
    ) -> None:
        candidate = ReplayEvidenceCandidateAssembler().assemble(
            _platform_capture_archive(corporate_action_text=CORPORATE_ACTION_NO_CHANGE),
            request=integrated_request(PLATFORM_CASE),
            ticker=PLATFORM_CASE.display_symbol,
            sec_user_agent="Investment Research OS research@example.com",
            trusted_issuer_hosts=PLATFORM_CASE.issuer_trusted_hosts,
            accepted_at=datetime(2026, 5, 7, 3, tzinfo=UTC),
        )

        growth = next(
            metric
            for metric in candidate.metrics
            if metric.metric_key == "basic_share_growth"
        )
        self.assertEqual(growth.value, "4.166667")
        self.assertEqual(growth.unit, "percent")
        self.assertEqual(len(growth.supporting_evidence_ids), 3)
        self.assertEqual(candidate.declared_gaps, ())
        self.assertEqual(
            len(
                tuple(
                    item
                    for item in candidate.items
                    if item.item_kind == "passage"
                    and "#observation=" in item.source_locator
                )
            ),
            2,
        )

    def test_v3_ambiguous_corporate_action_keeps_gap_and_no_growth_metric(
        self,
    ) -> None:
        candidate = ReplayEvidenceCandidateAssembler().assemble(
            _platform_capture_archive(
                corporate_action_text=(
                    "The company reviewed its corporate action history."
                )
            ),
            request=integrated_request(PLATFORM_CASE),
            ticker=PLATFORM_CASE.display_symbol,
            sec_user_agent="Investment Research OS research@example.com",
            trusted_issuer_hosts=PLATFORM_CASE.issuer_trusted_hosts,
            accepted_at=datetime(2026, 5, 7, 3, tzinfo=UTC),
        )

        self.assertNotIn(
            "basic_share_growth",
            {metric.metric_key for metric in candidate.metrics},
        )
        self.assertIn(
            "corporate_action_evidence_ambiguous",
            {gap.reason_code for gap in candidate.declared_gaps},
        )

    def test_missing_run_binding_fails_without_assembling_or_collecting(self) -> None:
        run = research_run()
        assembler = CandidateAssemblerFake()

        with tempfile.TemporaryDirectory() as directory:
            source = PersistedPrimarySourceEvidenceSource(
                repository=FilePrimarySourceCaptureRepository(Path(directory)),
                research_run=run,
                assembler=assembler,
                sec_user_agent="Investment Research OS research@example.com",
                trusted_issuer_hosts=("ir.recursion.com",),
            )

            with self.assertRaisesRegex(
                PersistedPrimarySourceEvidenceError,
                "no accepted capture binding",
            ):
                source.load(
                    run.operator_id,
                    run.security_id,
                    run.as_of_cutoff,
                )

        self.assertFalse(hasattr(assembler, "raw_archive"))

    def test_restart_loads_only_capture_bound_to_exact_research_run(self) -> None:
        value, payloads, source_plan = capture_value()
        archive = archive_bytes(value, payloads, source_plan)
        accepted_at = datetime(2026, 5, 7, 3, tzinfo=UTC)
        capture = load_primary_source_capture(
            archive,
            request=request(),
            trusted_issuer_hosts=("ir.recursion.com",),
            accepted_at=lambda: accepted_at,
        )
        run = research_run()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = FilePrimarySourceCaptureRepository(root)
            persisted = repository.save_capture(capture, archive)
            repository.bind_to_run(
                persisted,
                run,
                evidence_policy_version="biotech-primary-evidence-v2",
                bound_at=datetime(2026, 5, 7, 4, tzinfo=UTC),
            )
            restarted = FilePrimarySourceCaptureRepository(root)
            assembler = CandidateAssemblerFake()
            source = PersistedPrimarySourceEvidenceSource(
                repository=restarted,
                research_run=run,
                assembler=assembler,
                sec_user_agent="Investment Research OS research@example.com",
                trusted_issuer_hosts=("ir.recursion.com",),
            )

            candidate = source.load(
                run.operator_id,
                run.security_id,
                run.as_of_cutoff,
            )

        self.assertEqual(candidate.security_id, run.security_id)
        self.assertEqual(assembler.raw_archive, archive)
        self.assertEqual(assembler.request.operator_id, run.operator_id)
        self.assertEqual(assembler.request.cik, run.security_identity.cik)
        self.assertEqual(assembler.ticker, run.security_identity.symbol)
        self.assertEqual(assembler.accepted_at, accepted_at)

    def test_restart_rejects_assembler_under_different_evidence_policy(self) -> None:
        value, payloads, source_plan = capture_value()
        archive = archive_bytes(value, payloads, source_plan)
        accepted_at = datetime(2026, 5, 7, 3, tzinfo=UTC)
        capture = load_primary_source_capture(
            archive,
            request=request(),
            trusted_issuer_hosts=("ir.recursion.com",),
            accepted_at=lambda: accepted_at,
        )
        run = research_run()

        with tempfile.TemporaryDirectory() as directory:
            repository = FilePrimarySourceCaptureRepository(Path(directory))
            persisted = repository.save_capture(capture, archive)
            repository.bind_to_run(
                persisted,
                run,
                evidence_policy_version="biotech-primary-evidence-v2",
                bound_at=datetime(2026, 5, 7, 4, tzinfo=UTC),
            )
            source = PersistedPrimarySourceEvidenceSource(
                repository=repository,
                research_run=run,
                assembler=CandidateAssemblerFake(
                    evidence_policy_version="biotech-primary-evidence-v1"
                ),
                sec_user_agent="Investment Research OS research@example.com",
                trusted_issuer_hosts=("ir.recursion.com",),
            )

            with self.assertRaisesRegex(
                PersistedPrimarySourceEvidenceError,
                "assembled evidence does not match Research Run",
            ):
                source.load(
                    run.operator_id,
                    run.security_id,
                    run.as_of_cutoff,
                )


if __name__ == "__main__":
    unittest.main()

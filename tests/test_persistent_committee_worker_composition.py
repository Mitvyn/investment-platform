from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from investment_research_os.evidence_bundles import (
    InMemoryEvidenceBundleRepository,
)
from investment_research_os.providers.openai_contracts import (
    OpenAIExecutionContractRegistry,
)
from investment_research_os.research_committees import (
    InMemoryResearchCommitteeRepository,
)
from investment_research_os.research_runs import (
    InMemoryResearchRunRepository,
    SecurityIdentity,
)
from investment_research_os.research_workflows import build_offline_mvp_config
from investment_research_os.valuation_snapshots.capital import (
    FrozenEvidenceCapitalFreshnessPort,
    FrozenEvidenceCapitalPort,
)
from investment_research_os.valuation_snapshots.materiality import (
    FrozenEvidenceMaterialityPort,
)
from investment_research_os.valuation_snapshots.market_proofs import (
    NasdaqTraderHistoricalHaltVerifier,
    VersionedUsEquitiesCalendar,
)
from investment_research_os.valuation_snapshots.corporate_actions import (
    MassivePersonalResearchCorporateActionAdapter,
)
from investment_research_os.valuation_snapshots.composite import OfficialCloseInput
from tests.test_composite_valuation_source import (
    CapitalPortFake,
    CorporateActionPortFake,
    FreshnessPortFake,
    MaterialityPortFake,
)
from tests.test_evidence_bundle_storage import materialized_bundle
from tests.test_five_grader_committee import completed_committee_fixture
from tests.test_openai_execution_contract_registry import CONTRACTS, PROMPTS
from tests.test_primary_source_end_to_end import (
    PLATFORM_CASE,
)
from tests.test_primary_source_end_to_end import (
    request as integrated_request,
)
from tests.test_primary_source_plans import research_run
from tests.test_primary_source_replay import _platform_capture_archive
from tests.test_valuation_snapshot_workflow import (
    FixedCalendar,
    SESSION,
    personal_input_candidate,
)
from workers.primary_sources.captures import load_primary_source_capture
from workers.primary_sources.storage import FilePrimarySourceCaptureRepository
from workers.research_committee.composition import (
    FixedTrustedIssuerHostRegistry,
    PersistentCommitteeCompositionError,
    TrustedIssuerHostConfiguration,
    compose_dynamic_persistent_evidence_bundle_stage,
    compose_persistent_committee_worker,
    compose_persistent_evidence_bundle_stage,
    compose_persistent_grader_committee_stage,
    compose_personal_research_valuation_input_source,
    compose_registry_bound_grader_committee_stage,
    compose_supabase_committee_memo_stage,
    compose_supabase_persistent_grader_lifecycle_factory,
    compose_supabase_personal_research_valuation_snapshot_stage,
    compose_supabase_readiness_thesis_stage,
    compose_supabase_registry_bound_grader_committee_stage,
    compose_supabase_valuation_snapshot_stage,
)
from workers.research_committee.grader import (
    PersistentGraderBudgetContext,
    PersistentGraderExecutionBinding,
)
from workers.research_committee.worker import (
    CommitteeCommandClaim,
    PersistentCommitteeWorker,
    PersistentCommitteeMemoStage,
    PersistentGraderCommitteeStage,
    PersistentReadinessThesisStage,
    PersistentValuationSnapshotStage,
)
from workers.sec.storage import SupabaseStorageSettings


class CommandStoreFake:
    def __init__(self, claim: CommitteeCommandClaim) -> None:
        self.claim = claim
        self.checkpoints: list[tuple[CommitteeCommandClaim, str, str]] = []
        self.failures: list[tuple[CommitteeCommandClaim, str, str, bool]] = []

    def claim_next(self, worker_id: str) -> CommitteeCommandClaim:
        return self.claim

    def checkpoint(
        self,
        claim: CommitteeCommandClaim,
        *,
        stage: str,
        artifact_id: str,
    ) -> None:
        self.checkpoints.append((claim, stage, artifact_id))

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
        return claim.research_run_id or "66666666-6666-4666-8666-666666666666"


class ClaimScopedCommitteeFactoryFake:
    def __init__(self) -> None:
        self.runs = []

    def create(self, run):
        self.runs.append(run)

        class Execution:
            def execute(self, operator):
                return SimpleNamespace(
                    committee_id="88888888-8888-4888-8888-888888888888",
                    operator_id=run.operator_id,
                    research_run_id=run.id,
                    security_id=run.security_id,
                    question_type_version=run.question_type_version,
                    workflow_config_version=run.workflow_config_version,
                )

        return Execution()


def command_claim() -> CommitteeCommandClaim:
    return CommitteeCommandClaim(
        command_id="11111111-1111-4111-8111-111111111111",
        operator_id="027d7f1b-d928-48d9-b6c8-f10d3c7ba792",
        security_id="22222222-2222-4222-8222-222222222222",
        question_type_version="biotech_moonshot_catalyst_assessment.v1",
        workflow_config_version="biotech-moonshot-catalyst-v1",
        as_of_cutoff=datetime(2026, 5, 6, 23, 59, 59, tzinfo=UTC),
        operator_focus=None,
        attempt_id="44444444-4444-4444-8444-444444444444",
        attempt_number=1,
        lease_token="55555555-5555-4555-8555-555555555555",
        next_stage="research_run",
        completed_stages=(),
        research_run_id=None,
    )


class PersistentCommitteeWorkerCompositionTests(unittest.TestCase):
    def test_personal_valuation_composition_runs_with_injected_close_without_massive(
        self,
    ) -> None:
        class OfficialClosePortFake:
            def __init__(self) -> None:
                self.requests = []

            def load(self, bundle, session):
                self.requests.append((bundle, session))
                candidate = personal_input_candidate()
                return OfficialCloseInput(
                    prices=candidate.prices,
                    source_references=(candidate.source_references[0],),
                )

        close_port = OfficialClosePortFake()
        source = compose_personal_research_valuation_input_source(
            environment={},
            market_calendar=FixedCalendar(),
            historical_halt_verifier=None,
            close_port=close_port,
            capital_port=CapitalPortFake(),
            corporate_action_port=CorporateActionPortFake(),
            materiality_port=MaterialityPortFake(),
            freshness_port=FreshnessPortFake(),
            clock=lambda: datetime(2026, 7, 31, tzinfo=UTC),
        )

        candidate = source.load(materialized_bundle(), SESSION)

        self.assertEqual(candidate.prices, personal_input_candidate().prices)
        self.assertEqual(
            close_port.requests,
            [(materialized_bundle(), SESSION)],
        )

    def test_injected_close_requires_explicit_corporate_action_port(self) -> None:
        with self.assertRaises(PersistentCommitteeCompositionError) as raised:
            compose_personal_research_valuation_input_source(
                environment={},
                market_calendar=FixedCalendar(),
                historical_halt_verifier=None,
                close_port=SimpleNamespace(load=lambda bundle, session: None),
                capital_port=None,
                corporate_action_port=None,
                materiality_port=None,
                freshness_port=None,
                clock=lambda: datetime(2026, 7, 31, tzinfo=UTC),
            )

        self.assertEqual(
            raised.exception.error_code,
            "personal_research_corporate_action_port_required_with_injected_close",
        )

    def test_personal_valuation_composition_fails_before_market_without_proof_ports(
        self,
    ) -> None:
        class NoLiveTransport:
            def __init__(self) -> None:
                self.calls = []

            def request_json(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                raise AssertionError("live Massive interaction is not permitted")

        transport = NoLiveTransport()

        with self.assertRaises(PersistentCommitteeCompositionError) as raised:
            compose_personal_research_valuation_input_source(
                environment={"MASSIVE_API_KEY": "massive_test_key"},
                market_calendar=SimpleNamespace(
                    latest_completed_session=lambda exchange, cutoff: None
                ),
                historical_halt_verifier=None,
                capital_port=None,
                corporate_action_port=None,
                materiality_port=None,
                freshness_port=None,
                transport=transport,
                clock=lambda: datetime(2026, 7, 31, tzinfo=UTC),
            )

        self.assertEqual(
            raised.exception.error_code,
            "personal_research_historical_halt_configuration_invalid",
        )
        self.assertEqual(transport.calls, [])

    def test_personal_valuation_composition_rejects_nonfunctional_capital_port(
        self,
    ) -> None:
        with self.assertRaises(PersistentCommitteeCompositionError) as raised:
            compose_personal_research_valuation_input_source(
                environment={"MASSIVE_API_KEY": "massive_test_key"},
                market_calendar=SimpleNamespace(
                    latest_completed_session=lambda exchange, cutoff: None
                ),
                historical_halt_verifier=SimpleNamespace(
                    verify=lambda bundle, session, evidence: "indeterminate"
                ),
                capital_port=SimpleNamespace(),
                corporate_action_port=SimpleNamespace(
                    reconcile=lambda bundle, session, prices, capital: None
                ),
                materiality_port=SimpleNamespace(assess=lambda bundle, session: None),
                freshness_port=SimpleNamespace(
                    assess=lambda bundle, session, capital: None
                ),
                clock=lambda: datetime(2026, 7, 31, tzinfo=UTC),
            )

        self.assertEqual(
            raised.exception.error_code,
            "personal_research_capital_evidence_port_missing",
        )

    def test_personal_valuation_composition_builds_offline_safe_default_ports(
        self,
    ) -> None:
        class NoLiveTransport:
            def __init__(self) -> None:
                self.calls = []

            def request_json(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                raise AssertionError("live Massive interaction is not permitted")

        transport = NoLiveTransport()
        source = compose_personal_research_valuation_input_source(
            environment={
                "MASSIVE_API_KEY": "massive_test_key",
                "SEC_USER_AGENT": "Investment Research OS operator@example.com",
            },
            market_calendar=None,
            historical_halt_verifier=None,
            capital_port=None,
            corporate_action_port=None,
            materiality_port=None,
            freshness_port=None,
            transport=transport,
            clock=lambda: datetime(2026, 7, 31, tzinfo=UTC),
        )

        self.assertIsInstance(source.capital_port, FrozenEvidenceCapitalPort)
        self.assertIsInstance(source.market_calendar, VersionedUsEquitiesCalendar)
        self.assertIsInstance(
            source.close_port.halt_verifier,
            NasdaqTraderHistoricalHaltVerifier,
        )
        self.assertIsInstance(
            source.corporate_action_port,
            MassivePersonalResearchCorporateActionAdapter,
        )
        self.assertIsInstance(
            source.freshness_port,
            FrozenEvidenceCapitalFreshnessPort,
        )
        self.assertIsInstance(
            source.materiality_port,
            FrozenEvidenceMaterialityPort,
        )
        self.assertEqual(transport.calls, [])

    def test_composes_supabase_valuation_stage_without_live_interaction(
        self,
    ) -> None:
        class NoLiveTransport:
            def __init__(self) -> None:
                self.calls = []

            def request_json(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                raise AssertionError("live Supabase interaction is not permitted")

        transport = NoLiveTransport()
        stage = compose_supabase_valuation_snapshot_stage(
            settings=SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="secret-test-key",
            ),
            transport=transport,
            market_calendar=SimpleNamespace(),
            input_source=SimpleNamespace(),
            personal_research_input_source=SimpleNamespace(),
            clock=lambda: datetime(2026, 7, 31, tzinfo=UTC),
        )

        self.assertIsInstance(stage, PersistentValuationSnapshotStage)
        self.assertIsNotNone(stage._personal_research_workflow)
        self.assertEqual(transport.calls, [])

    def test_composes_massive_personal_valuation_stage_without_live_interaction(
        self,
    ) -> None:
        class NoLiveTransport:
            def __init__(self) -> None:
                self.calls = []

            def request_json(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                raise AssertionError("external interaction is not permitted")

        supabase_transport = NoLiveTransport()
        massive_transport = NoLiveTransport()
        stage = compose_supabase_personal_research_valuation_snapshot_stage(
            settings=SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="secret-test-key",
            ),
            environment={
                "MASSIVE_API_KEY": "massive_test_key",
                "SEC_USER_AGENT": "Investment Research OS operator@example.com",
            },
            market_calendar=None,
            strict_input_source=SimpleNamespace(),
            historical_halt_verifier=None,
            capital_port=None,
            corporate_action_port=None,
            materiality_port=None,
            freshness_port=None,
            supabase_transport=supabase_transport,
            massive_transport=massive_transport,
            clock=lambda: datetime(2026, 7, 31, tzinfo=UTC),
        )

        self.assertIsInstance(stage, PersistentValuationSnapshotStage)
        self.assertIsNotNone(stage._personal_research_workflow)
        self.assertEqual(supabase_transport.calls, [])
        self.assertEqual(massive_transport.calls, [])

    def test_composes_personal_valuation_stage_with_injected_close_without_massive(
        self,
    ) -> None:
        class NoLiveTransport:
            def __init__(self) -> None:
                self.calls = []

            def request_json(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                raise AssertionError("external interaction is not permitted")

        supabase_transport = NoLiveTransport()
        stage = compose_supabase_personal_research_valuation_snapshot_stage(
            settings=SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="secret-test-key",
            ),
            environment={},
            market_calendar=FixedCalendar(),
            strict_input_source=SimpleNamespace(),
            historical_halt_verifier=None,
            close_port=SimpleNamespace(load=lambda bundle, session: None),
            capital_port=None,
            corporate_action_port=CorporateActionPortFake(),
            materiality_port=None,
            freshness_port=None,
            supabase_transport=supabase_transport,
            clock=lambda: datetime(2026, 7, 31, tzinfo=UTC),
        )

        self.assertIsInstance(stage, PersistentValuationSnapshotStage)
        self.assertIsNotNone(stage._personal_research_workflow)
        self.assertEqual(supabase_transport.calls, [])

    def test_composes_complete_supabase_readiness_stage_without_live_interaction(
        self,
    ) -> None:
        class NoLiveTransport:
            def __init__(self) -> None:
                self.calls = []

            def request_json(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                raise AssertionError("live Supabase interaction is not permitted")

        transport = NoLiveTransport()
        stage = compose_supabase_readiness_thesis_stage(
            settings=SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="secret-test-key",
            ),
            transport=transport,
            clock=lambda: datetime(2026, 7, 31, tzinfo=UTC),
        )

        self.assertIsInstance(stage, PersistentReadinessThesisStage)
        self.assertEqual(transport.calls, [])

    def test_composes_complete_supabase_memo_stage_without_live_interaction(
        self,
    ) -> None:
        class NoLiveTransport:
            def __init__(self) -> None:
                self.calls = []

            def request_json(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                raise AssertionError("live Supabase interaction is not permitted")

        transport = NoLiveTransport()
        stage = compose_supabase_committee_memo_stage(
            settings=SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="secret-test-key",
            ),
            transport=transport,
            config=build_offline_mvp_config(),
            provider=SimpleNamespace(),
            clock=lambda: datetime(2026, 7, 31, tzinfo=UTC),
        )

        self.assertIsInstance(stage, PersistentCommitteeMemoStage)
        self.assertEqual(transport.calls, [])

    def test_supabase_grader_composition_rejects_non_https_url(self) -> None:
        with self.assertRaises(PersistentCommitteeCompositionError) as raised:
            compose_supabase_persistent_grader_lifecycle_factory(
                settings=SupabaseStorageSettings(
                    url="http://example.supabase.co",
                    secret_key="secret-test-key",
                ),
                transport=object(),
            )

        self.assertEqual(
            raised.exception.error_code,
            "supabase_url_not_https",
        )

    def test_supabase_grader_composition_rejects_missing_secret_key(self) -> None:
        with self.assertRaises(PersistentCommitteeCompositionError) as raised:
            compose_supabase_persistent_grader_lifecycle_factory(
                settings=SupabaseStorageSettings(
                    url="https://example.supabase.co",
                    secret_key=" ",
                ),
                transport=object(),
            )

        self.assertEqual(
            raised.exception.error_code,
            "supabase_secret_key_missing",
        )

    def test_composes_complete_supabase_grader_stage_without_live_interaction(
        self,
    ) -> None:
        class NoLiveTransport:
            def __init__(self) -> None:
                self.calls = []

            def request_json(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                raise AssertionError("live Supabase interaction is not permitted")

        transport = NoLiveTransport()
        stage = compose_supabase_registry_bound_grader_committee_stage(
            settings=SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="secret-test-key",
            ),
            transport=transport,
            registry=OpenAIExecutionContractRegistry.load(
                contract_path=CONTRACTS,
                prompt_path=PROMPTS,
            ),
            config=build_offline_mvp_config(),
            provider=SimpleNamespace(),
            budget=PersistentGraderBudgetContext(
                budget_id="70000000-0000-4000-8000-000000000001",
                snapshot={"status": "available"},
            ),
            clock=lambda: datetime(2026, 7, 31, tzinfo=UTC),
        )

        self.assertIsInstance(stage, PersistentGraderCommitteeStage)
        self.assertEqual(transport.calls, [])

    def test_composes_supabase_grader_lifecycle_without_live_interaction(
        self,
    ) -> None:
        bundle, committee, _, _ = completed_committee_fixture()
        expected = committee.grader_results[0].execution
        contract = OpenAIExecutionContractRegistry.load(
            contract_path=CONTRACTS,
            prompt_path=PROMPTS,
        ).contracts[0]

        class NoLiveTransport:
            def request_json(self, *args, **kwargs):
                raise AssertionError("live Supabase interaction is not permitted")

        factory = compose_supabase_persistent_grader_lifecycle_factory(
            settings=SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="secret-test-key",
            ),
            transport=NoLiveTransport(),
        )
        bound = factory.create(
            PersistentGraderExecutionBinding(
                research_run=SimpleNamespace(
                    id=bundle.research_run_id,
                    operator_id=bundle.operator_id,
                    security_id=bundle.security_id,
                    question_type_version=("biotech_moonshot_catalyst_assessment.v1"),
                    workflow_config_version="biotech-moonshot-catalyst-v1",
                    as_of_cutoff=bundle.as_of_cutoff,
                ),
                evidence_bundle=bundle,
                request=expected.request,
                execution_contract=contract,
                provider=SimpleNamespace(),
                budget=PersistentGraderBudgetContext(
                    budget_id="70000000-0000-4000-8000-000000000001",
                    snapshot={"status": "available"},
                ),
                clock=lambda: expected.created_at,
            )
        )

        self.assertTrue(callable(bound.execute))

    def test_composes_registry_bound_grader_stage_without_activation(
        self,
    ) -> None:
        stage = compose_registry_bound_grader_committee_stage(
            research_run_repository=InMemoryResearchRunRepository(),
            evidence_bundle_repository=InMemoryEvidenceBundleRepository(),
            committee_repository=InMemoryResearchCommitteeRepository(),
            registry=OpenAIExecutionContractRegistry.load(
                contract_path=CONTRACTS,
                prompt_path=PROMPTS,
            ),
            config=build_offline_mvp_config(),
            lifecycle_factory=object(),
            provider=object(),
            budget=PersistentGraderBudgetContext(
                budget_id="70000000-0000-4000-8000-000000000001",
                snapshot={"status": "available"},
            ),
            clock=lambda: datetime(2026, 7, 30, tzinfo=UTC),
        )

        self.assertIsInstance(stage, PersistentGraderCommitteeStage)

    def test_composes_grader_committee_execution_after_claiming_run(
        self,
    ) -> None:
        run = research_run()
        runs = InMemoryResearchRunRepository()
        runs.save(run)
        factory = ClaimScopedCommitteeFactoryFake()
        stage = compose_persistent_grader_committee_stage(
            research_run_repository=runs,
            execution_factory=factory,
        )
        claim = replace(
            command_claim(),
            operator_id=run.operator_id,
            security_id=run.security_id,
            question_type_version=run.question_type_version,
            workflow_config_version=run.workflow_config_version,
            as_of_cutoff=run.as_of_cutoff,
            next_stage="grader_committee",
            completed_stages=(
                "research_run",
                "evidence_bundle",
                "valuation_snapshot",
            ),
            research_run_id=run.id,
        )

        artifact_id = stage.execute(claim)

        self.assertEqual(
            artifact_id,
            "88888888-8888-4888-8888-888888888888",
        )
        self.assertEqual(factory.runs, [run])

    def test_full_worker_composition_requires_every_persistent_stage(self) -> None:
        claim = command_claim()
        jobs = CommandStoreFake(claim)
        stages = {
            "research_run_stage": ResearchRunStageFake(),
            "evidence_bundle_stage": ResearchRunStageFake(),
            "valuation_snapshot_stage": ResearchRunStageFake(),
            "grader_committee_stage": ResearchRunStageFake(),
            "committee_memo_stage": ResearchRunStageFake(),
            "readiness_thesis_stage": ResearchRunStageFake(),
        }

        worker = compose_persistent_committee_worker(
            worker_id="iros-committee-worker-1",
            commands=jobs,
            **stages,
        )

        self.assertIsInstance(worker, PersistentCommitteeWorker)

        for stage_name in stages:
            with self.subTest(stage=stage_name):
                incomplete = dict(stages)
                incomplete[stage_name] = None
                with self.assertRaisesRegex(
                    PersistentCommitteeCompositionError,
                    f"{stage_name}_missing",
                ):
                    compose_persistent_committee_worker(
                        worker_id="iros-committee-worker-1",
                        commands=jobs,
                        **incomplete,
                    )

    def test_duplicate_trusted_host_configuration_fails_closed(self) -> None:
        run = research_run()
        configuration = TrustedIssuerHostConfiguration(
            security_id=run.security_id,
            question_type_version=run.question_type_version,
            workflow_config_version=run.workflow_config_version,
            hosts=("ir.recursion.com",),
        )

        with self.assertRaises(PersistentCommitteeCompositionError) as raised:
            FixedTrustedIssuerHostRegistry((configuration, configuration)).resolve(run)

        self.assertEqual(
            raised.exception.error_code,
            "trusted_issuer_host_configuration_ambiguous",
        )

    def test_drifted_trusted_host_configuration_fails_before_checkpoint(
        self,
    ) -> None:
        run = research_run()
        drifted = TrustedIssuerHostConfiguration(
            security_id=run.security_id,
            question_type_version=run.question_type_version,
            workflow_config_version="biotech-moonshot-catalyst-v0",
            hosts=("ir.recursion.com",),
        )
        jobs = CommandStoreFake(command_claim())

        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(
                PersistentCommitteeCompositionError,
            ) as raised,
        ):
            compose_persistent_evidence_bundle_stage(
                research_run=run,
                research_run_repository=InMemoryResearchRunRepository(),
                evidence_bundle_repository=InMemoryEvidenceBundleRepository(),
                capture_repository=FilePrimarySourceCaptureRepository(Path(directory)),
                trusted_issuer_host_registry=(
                    FixedTrustedIssuerHostRegistry((drifted,))
                ),
                sec_user_agent=("Investment Research OS research@example.com"),
                clock=lambda: datetime(2026, 5, 7, 5, tzinfo=UTC),
            )

        self.assertEqual(
            raised.exception.error_code,
            "trusted_issuer_host_configuration_drift",
        )
        self.assertEqual(jobs.checkpoints, [])
        self.assertEqual(jobs.failures, [])

    def test_missing_trusted_host_configuration_fails_before_checkpoint(
        self,
    ) -> None:
        run = research_run()
        jobs = CommandStoreFake(command_claim())

        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(
                PersistentCommitteeCompositionError,
            ) as raised,
        ):
            compose_persistent_evidence_bundle_stage(
                research_run=run,
                research_run_repository=InMemoryResearchRunRepository(),
                evidence_bundle_repository=InMemoryEvidenceBundleRepository(),
                capture_repository=FilePrimarySourceCaptureRepository(Path(directory)),
                trusted_issuer_host_registry=(FixedTrustedIssuerHostRegistry(())),
                sec_user_agent=("Investment Research OS research@example.com"),
                clock=lambda: datetime(2026, 5, 7, 5, tzinfo=UTC),
            )

        self.assertEqual(
            raised.exception.error_code,
            "trusted_issuer_host_configuration_missing",
        )
        self.assertEqual(jobs.checkpoints, [])
        self.assertEqual(jobs.failures, [])

    def test_dynamic_accepted_capture_materializes_before_worker_checkpoint(
        self,
    ) -> None:
        raw_archive = _platform_capture_archive()
        accepted_at = datetime(2026, 5, 7, 3, tzinfo=UTC)
        capture = load_primary_source_capture(
            raw_archive,
            request=integrated_request(PLATFORM_CASE),
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
        claim = replace(
            command_claim(),
            operator_id=run.operator_id,
            security_id=run.security_id,
            as_of_cutoff=run.as_of_cutoff,
            next_stage="evidence_bundle",
            completed_stages=("research_run",),
            research_run_id=run.id,
        )

        with tempfile.TemporaryDirectory() as directory:
            captures = FilePrimarySourceCaptureRepository(Path(directory))
            persisted = captures.save_capture(capture, raw_archive)
            captures.bind_to_run(
                persisted,
                run,
                evidence_policy_version="biotech-primary-evidence-v3",
                bound_at=datetime(2026, 5, 7, 4, tzinfo=UTC),
            )
            runs = InMemoryResearchRunRepository()
            runs.save(run)
            bundles = InMemoryEvidenceBundleRepository()
            stage = compose_dynamic_persistent_evidence_bundle_stage(
                research_run_repository=runs,
                evidence_bundle_repository=bundles,
                capture_repository=captures,
                trusted_issuer_host_registry=FixedTrustedIssuerHostRegistry(
                    (
                        TrustedIssuerHostConfiguration(
                            security_id=run.security_id,
                            question_type_version=run.question_type_version,
                            workflow_config_version=run.workflow_config_version,
                            hosts=PLATFORM_CASE.issuer_trusted_hosts,
                        ),
                    )
                ),
                sec_user_agent="Investment Research OS research@example.com",
                clock=lambda: datetime(2026, 5, 7, 5, tzinfo=UTC),
            )
            jobs = CommandStoreFake(claim)
            worker = PersistentCommitteeWorker(
                worker_id="iros-committee-worker-1",
                commands=jobs,
                research_run_stage=ResearchRunStageFake(),
                evidence_bundle_stage=stage,
            )

            self.assertTrue(worker.run_once())

        self.assertEqual(jobs.failures, [])
        self.assertEqual(len(jobs.checkpoints), 1)
        checkpoint_claim, checkpoint_stage, checkpoint_id = jobs.checkpoints[0]
        self.assertEqual(checkpoint_claim, claim)
        self.assertEqual(checkpoint_stage, "evidence_bundle")
        self.assertEqual(bundles.get_for_run(run.operator_id, run.id).id, checkpoint_id)


if __name__ == "__main__":
    unittest.main()

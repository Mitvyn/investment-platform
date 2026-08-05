from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from urllib.parse import urlsplit

from investment_research_os.committee_memos import (
    CommitteeMemoWorkflow,
)
from investment_research_os.committee_memos.persistent_read_model import (
    SupabaseCommitteeMemoReadModel,
)
from investment_research_os.committee_memos.storage import (
    RuntimeManagedSynthesisBudgetLedger,
    SupabaseCommitteeMemoRepository,
    SupabaseCommitteeMemoRuntimeStore,
)
from investment_research_os.evidence_bundles import (
    EvidenceBundleRepository,
    EvidenceBundleWorkflow,
)
from investment_research_os.evidence_bundles.storage import (
    SupabaseEvidenceBundleRepository,
)
from investment_research_os.grader_executions import GraderProvider
from investment_research_os.grader_executions.lifecycle_storage import (
    SupabaseGraderExecutionLifecycle,
)
from investment_research_os.grader_executions.persistent_read_model import (
    SupabasePersistentExecutionReadModel,
)
from investment_research_os.grader_executions.storage import (
    SupabaseGraderExecutionRuntimeStore,
)
from investment_research_os.providers.openai_contracts import (
    OpenAIExecutionContractRegistry,
)
from investment_research_os.provider_input_token_preflight import (
    PersistentInputTokenPreflightGate,
)
from investment_research_os.provider_input_token_preflight_storage import (
    SupabaseInputTokenPreflightStore,
)
from investment_research_os.readiness_and_theses import (
    ReadinessAndThesisWorkflow,
)
from investment_research_os.readiness_and_theses.storage import (
    SupabaseReadinessAndThesisRepository,
    SupabaseReadinessThesisReadModel,
    SupabaseReadinessThesisRuntimeStore,
)
from investment_research_os.research_committees import (
    ResearchCommitteeRepository,
)
from investment_research_os.research_committees.storage import (
    SupabaseResearchCommitteeRepository,
)
from investment_research_os.research_runs import (
    ResearchRun,
    ResearchRunRepository,
)
from investment_research_os.research_runs.storage import (
    SupabaseResearchRunRepository,
)
from investment_research_os.research_workflows import (
    BiotechResearchCommitteeConfig,
)
from investment_research_os.valuation_snapshots import (
    MarketCalendar,
    PersonalResearchValuationSnapshotWorkflow,
    ValuationInputSource,
    ValuationSnapshotRepository,
    ValuationSnapshotWorkflow,
)
from investment_research_os.valuation_snapshots.storage import (
    SupabaseValuationSnapshotRepository,
)
from investment_research_os.valuation_snapshots.composite import (
    CapitalPort,
    CorporateActionPort,
    FreshnessPort,
    MaterialityPort,
    PersonalResearchValuationInputSource,
)
from investment_research_os.valuation_snapshots.capital import (
    FrozenEvidenceCapitalFreshnessPort,
    FrozenEvidenceCapitalPort,
)
from investment_research_os.valuation_snapshots.corporate_actions import (
    MassivePersonalResearchCorporateActionAdapter,
)
from investment_research_os.valuation_snapshots.massive import (
    HistoricalHaltVerifier,
    MassivePersonalResearchCloseAdapter,
    MassiveSettings,
    MassiveValuationClient,
)
from investment_research_os.valuation_snapshots.materiality import (
    FrozenEvidenceMaterialityPort,
)
from investment_research_os.valuation_snapshots.market_calendar import (
    load_packaged_us_equities_calendar,
)
from investment_research_os.valuation_snapshots.market_proofs import (
    NasdaqTraderHistoricalHaltVerifier,
)
from investment_research_os.valuation_snapshots.nasdaq_halt_http import (
    NasdaqTraderHaltHttpSettings,
    NasdaqTraderHaltHttpTransport,
)
from workers.primary_sources.evidence_source import (
    EvidenceCandidateAssembler,
    PersistedPrimarySourceEvidenceSource,
    ReplayEvidenceCandidateAssembler,
)
from workers.primary_sources.storage import FilePrimarySourceCaptureRepository
from workers.sec.storage import (
    EvidenceStorageError,
    JsonTransport,
    SupabaseStorageSettings,
)

from .grader import (
    DomainPersistentGraderLifecycleFactory,
    OpenAIClaimScopedCommitteeExecutionFactory,
    PersistentGraderBudgetContext,
    PersistentGraderCommitteeExecutionFactory,
    PersistentGraderCommitteeWorkflowAdapter,
    PersistentGraderLifecycleFactory,
)
from .memo import PersistentCommitteeMemoWorkflowAdapter
from .readiness import PersistentReadinessThesisWorkflowAdapter
from .worker import (
    CommitteeCommandClaim,
    CommitteeCommandStore,
    PersistentCommitteeMemoStage,
    PersistentCommitteeWorker,
    PersistentEvidenceBundleStage,
    PersistentGraderCommitteeStage,
    PersistentReadinessThesisStage,
    PersistentValuationSnapshotStage,
    ResearchRunStageError,
    ResearchRunStage,
)


class PersistentCommitteeCompositionError(ValueError):
    """Raised when fixed worker composition does not match its Research Run."""

    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


def _validate_supabase_storage_settings(
    settings: SupabaseStorageSettings,
) -> None:
    parsed_url = urlsplit(settings.url)
    if parsed_url.scheme != "https" or not parsed_url.netloc:
        raise PersistentCommitteeCompositionError("supabase_url_not_https")
    if not settings.secret_key.strip():
        raise PersistentCommitteeCompositionError("supabase_secret_key_missing")


@dataclass(frozen=True, slots=True)
class TrustedIssuerHostConfiguration:
    security_id: str
    question_type_version: str
    workflow_config_version: str
    hosts: tuple[str, ...]


class TrustedIssuerHostRegistry(Protocol):
    def resolve(self, research_run: ResearchRun) -> tuple[str, ...]: ...


class FixedTrustedIssuerHostRegistry:
    def __init__(
        self,
        configurations: tuple[TrustedIssuerHostConfiguration, ...],
    ) -> None:
        self._configurations = configurations

    def resolve(self, research_run: ResearchRun) -> tuple[str, ...]:
        security_configurations = tuple(
            configuration
            for configuration in self._configurations
            if configuration.security_id == research_run.security_id
        )
        if not security_configurations:
            raise PersistentCommitteeCompositionError(
                "trusted_issuer_host_configuration_missing"
            )
        compatible = tuple(
            configuration
            for configuration in security_configurations
            if (
                configuration.question_type_version
                == research_run.question_type_version
                and configuration.workflow_config_version
                == research_run.workflow_config_version
            )
        )
        if len(compatible) > 1:
            raise PersistentCommitteeCompositionError(
                "trusted_issuer_host_configuration_ambiguous"
            )
        if compatible:
            return compatible[0].hosts
        raise PersistentCommitteeCompositionError(
            "trusted_issuer_host_configuration_drift"
        )


def compose_persistent_committee_worker(
    *,
    worker_id: str,
    commands: CommitteeCommandStore,
    research_run_stage: ResearchRunStage,
    evidence_bundle_stage: ResearchRunStage,
    valuation_snapshot_stage: ResearchRunStage,
    grader_committee_stage: ResearchRunStage,
    committee_memo_stage: ResearchRunStage,
    readiness_thesis_stage: ResearchRunStage,
    heartbeat_interval_seconds: float = 60.0,
) -> PersistentCommitteeWorker:
    stages = {
        "research_run_stage": research_run_stage,
        "evidence_bundle_stage": evidence_bundle_stage,
        "valuation_snapshot_stage": valuation_snapshot_stage,
        "grader_committee_stage": grader_committee_stage,
        "committee_memo_stage": committee_memo_stage,
        "readiness_thesis_stage": readiness_thesis_stage,
    }
    for name, stage in stages.items():
        if stage is None:
            raise PersistentCommitteeCompositionError(f"{name}_missing")
    return PersistentCommitteeWorker(
        worker_id=worker_id,
        commands=commands,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
        **stages,
    )


def compose_persistent_evidence_bundle_stage(
    *,
    research_run: ResearchRun,
    research_run_repository: ResearchRunRepository,
    evidence_bundle_repository: EvidenceBundleRepository,
    capture_repository: FilePrimarySourceCaptureRepository,
    trusted_issuer_host_registry: TrustedIssuerHostRegistry,
    sec_user_agent: str,
    clock: Callable[[], datetime],
    assembler: EvidenceCandidateAssembler | None = None,
) -> PersistentEvidenceBundleStage:
    source = PersistedPrimarySourceEvidenceSource(
        repository=capture_repository,
        research_run=research_run,
        assembler=assembler or ReplayEvidenceCandidateAssembler(),
        sec_user_agent=sec_user_agent,
        trusted_issuer_hosts=trusted_issuer_host_registry.resolve(research_run),
    )
    return PersistentEvidenceBundleStage(
        EvidenceBundleWorkflow(
            research_run_repository=research_run_repository,
            bundle_repository=evidence_bundle_repository,
            evidence_source=source,
            clock=clock,
        )
    )


class _DynamicPersistentEvidenceBundleStage:
    def __init__(
        self,
        *,
        research_run_repository: ResearchRunRepository,
        evidence_bundle_repository: EvidenceBundleRepository,
        capture_repository: FilePrimarySourceCaptureRepository,
        trusted_issuer_host_registry: TrustedIssuerHostRegistry,
        sec_user_agent: str,
        clock: Callable[[], datetime],
        assembler: EvidenceCandidateAssembler | None,
    ) -> None:
        self._research_runs = research_run_repository
        self._evidence_bundles = evidence_bundle_repository
        self._captures = capture_repository
        self._trusted_hosts = trusted_issuer_host_registry
        self._sec_user_agent = sec_user_agent
        self._clock = clock
        self._assembler = assembler

    def execute(self, claim: CommitteeCommandClaim) -> str:
        if claim.research_run_id is None:
            raise ResearchRunStageError(
                "evidence_bundle_research_run_missing",
                retryable=False,
            )
        try:
            run = self._research_runs.get(
                claim.operator_id,
                claim.research_run_id,
            )
        except EvidenceStorageError as error:
            raise ResearchRunStageError(
                "evidence_bundle_persistence_failed",
                retryable=True,
            ) from error
        if run is None:
            raise ResearchRunStageError(
                "evidence_bundle_research_run_missing",
                retryable=False,
            )
        if (
            run.id != claim.research_run_id
            or run.operator_id != claim.operator_id
            or run.security_id != claim.security_id
            or run.as_of_cutoff != claim.as_of_cutoff
            or run.question_type_version != claim.question_type_version
            or run.workflow_config_version != claim.workflow_config_version
        ):
            raise ResearchRunStageError(
                "evidence_bundle_research_run_identity_mismatch",
                retryable=False,
            )
        try:
            stage = compose_persistent_evidence_bundle_stage(
                research_run=run,
                research_run_repository=self._research_runs,
                evidence_bundle_repository=self._evidence_bundles,
                capture_repository=self._captures,
                trusted_issuer_host_registry=self._trusted_hosts,
                sec_user_agent=self._sec_user_agent,
                clock=self._clock,
                assembler=self._assembler,
            )
        except PersistentCommitteeCompositionError as error:
            raise ResearchRunStageError(
                error.error_code,
                retryable=False,
            ) from error
        return stage.execute(claim)


def compose_dynamic_persistent_evidence_bundle_stage(
    *,
    research_run_repository: ResearchRunRepository,
    evidence_bundle_repository: EvidenceBundleRepository,
    capture_repository: FilePrimarySourceCaptureRepository,
    trusted_issuer_host_registry: TrustedIssuerHostRegistry,
    sec_user_agent: str,
    clock: Callable[[], datetime],
    assembler: EvidenceCandidateAssembler | None = None,
) -> ResearchRunStage:
    return _DynamicPersistentEvidenceBundleStage(
        research_run_repository=research_run_repository,
        evidence_bundle_repository=evidence_bundle_repository,
        capture_repository=capture_repository,
        trusted_issuer_host_registry=trusted_issuer_host_registry,
        sec_user_agent=sec_user_agent,
        clock=clock,
        assembler=assembler,
    )


def compose_persistent_grader_committee_stage(
    *,
    research_run_repository: ResearchRunRepository,
    execution_factory: PersistentGraderCommitteeExecutionFactory,
) -> PersistentGraderCommitteeStage:
    return PersistentGraderCommitteeStage(
        research_run_repository=research_run_repository,
        workflow=PersistentGraderCommitteeWorkflowAdapter(
            research_run_repository=research_run_repository,
            execution_factory=execution_factory,
        ),
    )


def compose_supabase_valuation_snapshot_stage(
    *,
    settings: SupabaseStorageSettings,
    market_calendar: MarketCalendar,
    input_source: ValuationInputSource,
    personal_research_input_source: ValuationInputSource | None = None,
    clock: Callable[[], datetime],
    transport: JsonTransport | None = None,
) -> PersistentValuationSnapshotStage:
    _validate_supabase_storage_settings(settings)
    research_runs = SupabaseResearchRunRepository(settings, transport=transport)
    evidence_bundles = SupabaseEvidenceBundleRepository(
        settings,
        transport=transport,
    )
    valuations = SupabaseValuationSnapshotRepository(
        settings,
        transport=transport,
    )
    return PersistentValuationSnapshotStage(
        research_run_repository=research_runs,
        evidence_bundle_repository=evidence_bundles,
        valuation_snapshot_repository=valuations,
        workflow=ValuationSnapshotWorkflow(
            evidence_bundle_repository=evidence_bundles,
            valuation_snapshot_repository=valuations,
            market_calendar=market_calendar,
            input_source=input_source,
            clock=clock,
        ),
        personal_research_workflow=(
            None
            if personal_research_input_source is None
            else PersonalResearchValuationSnapshotWorkflow(
                evidence_bundle_repository=evidence_bundles,
                valuation_snapshot_repository=valuations,
                market_calendar=market_calendar,
                input_source=personal_research_input_source,
                clock=clock,
            )
        ),
    )


def compose_personal_research_valuation_input_source(
    *,
    environment: Mapping[str, str],
    market_calendar: MarketCalendar | None,
    historical_halt_verifier: HistoricalHaltVerifier | None,
    capital_port: CapitalPort | None,
    corporate_action_port: CorporateActionPort | None,
    materiality_port: MaterialityPort | None,
    freshness_port: FreshnessPort | None,
    transport: JsonTransport | None = None,
    clock: Callable[[], datetime],
) -> PersonalResearchValuationInputSource:
    if market_calendar is None:
        market_calendar = load_packaged_us_equities_calendar()
    if historical_halt_verifier is None:
        halt_user_agent = environment.get(
            "IROS_NASDAQ_TRADER_USER_AGENT",
            environment.get("SEC_USER_AGENT", ""),
        )
        try:
            halt_transport = NasdaqTraderHaltHttpTransport(
                NasdaqTraderHaltHttpSettings(user_agent=halt_user_agent),
                clock=clock,
            )
        except ValueError as error:
            raise PersistentCommitteeCompositionError(
                "personal_research_historical_halt_configuration_invalid"
            ) from error
        historical_halt_verifier = NasdaqTraderHistoricalHaltVerifier(
            transport=halt_transport,
            source_version="nasdaq-trader-halt-search.v2",
            coverage_start=market_calendar.coverage_start,
            coverage_end=market_calendar.coverage_end,
        )
    required_dependencies = (
        ("market_calendar", market_calendar, "latest_completed_session"),
        ("historical_halt_verifier", historical_halt_verifier, "verify"),
    )
    for name, dependency, method_name in required_dependencies:
        if dependency is None or not callable(getattr(dependency, method_name, None)):
            raise PersistentCommitteeCompositionError(
                f"personal_research_{name}_missing"
            )
    optional_dependencies = (
        ("capital_evidence_port", capital_port, "load"),
        ("corporate_action_port", corporate_action_port, "reconcile"),
        ("materiality_port", materiality_port, "assess"),
        ("freshness_port", freshness_port, "assess"),
    )
    for name, dependency, method_name in optional_dependencies:
        if dependency is not None and not callable(
            getattr(dependency, method_name, None)
        ):
            raise PersistentCommitteeCompositionError(
                f"personal_research_{name}_missing"
            )
    try:
        settings = MassiveSettings.from_environment(environment)
    except ValueError as error:
        raise PersistentCommitteeCompositionError(
            "personal_research_massive_configuration_invalid"
        ) from error
    assert market_calendar is not None
    assert historical_halt_verifier is not None
    client = MassiveValuationClient(
        settings,
        transport=transport,
        clock=clock,
    )
    close_port = MassivePersonalResearchCloseAdapter(
        client=client,
        halt_verifier=historical_halt_verifier,
    )
    return PersonalResearchValuationInputSource(
        market_calendar=market_calendar,
        close_port=close_port,
        capital_port=capital_port or FrozenEvidenceCapitalPort(),
        corporate_action_port=(
            corporate_action_port
            or MassivePersonalResearchCorporateActionAdapter(client=client)
        ),
        materiality_port=materiality_port or FrozenEvidenceMaterialityPort(),
        freshness_port=freshness_port or FrozenEvidenceCapitalFreshnessPort(),
    )


def compose_supabase_personal_research_valuation_snapshot_stage(
    *,
    settings: SupabaseStorageSettings,
    environment: Mapping[str, str],
    market_calendar: MarketCalendar | None,
    strict_input_source: ValuationInputSource,
    historical_halt_verifier: HistoricalHaltVerifier | None,
    capital_port: CapitalPort | None,
    corporate_action_port: CorporateActionPort | None,
    materiality_port: MaterialityPort | None,
    freshness_port: FreshnessPort | None,
    clock: Callable[[], datetime],
    supabase_transport: JsonTransport | None = None,
    massive_transport: JsonTransport | None = None,
) -> PersistentValuationSnapshotStage:
    _validate_supabase_storage_settings(settings)
    personal_source = compose_personal_research_valuation_input_source(
        environment=environment,
        market_calendar=market_calendar,
        historical_halt_verifier=historical_halt_verifier,
        capital_port=capital_port,
        corporate_action_port=corporate_action_port,
        materiality_port=materiality_port,
        freshness_port=freshness_port,
        transport=massive_transport,
        clock=clock,
    )
    return compose_supabase_valuation_snapshot_stage(
        settings=settings,
        market_calendar=personal_source.market_calendar,
        input_source=strict_input_source,
        personal_research_input_source=personal_source,
        clock=clock,
        transport=supabase_transport,
    )


def compose_registry_bound_grader_committee_stage(
    *,
    research_run_repository: ResearchRunRepository,
    evidence_bundle_repository: EvidenceBundleRepository,
    committee_repository: ResearchCommitteeRepository,
    registry: OpenAIExecutionContractRegistry,
    config: BiotechResearchCommitteeConfig,
    lifecycle_factory: PersistentGraderLifecycleFactory,
    provider: GraderProvider,
    budget: PersistentGraderBudgetContext,
    clock: Callable[[], datetime],
) -> PersistentGraderCommitteeStage:
    return compose_persistent_grader_committee_stage(
        research_run_repository=research_run_repository,
        execution_factory=OpenAIClaimScopedCommitteeExecutionFactory(
            evidence_bundle_repository=evidence_bundle_repository,
            committee_repository=committee_repository,
            registry=registry,
            config=config,
            lifecycle_factory=lifecycle_factory,
            provider=provider,
            budget=budget,
            clock=clock,
        ),
    )


def compose_supabase_persistent_grader_lifecycle_factory(
    *,
    settings: SupabaseStorageSettings,
    transport: JsonTransport | None = None,
    valuation_snapshot_repository: ValuationSnapshotRepository | None = None,
) -> PersistentGraderLifecycleFactory:
    _validate_supabase_storage_settings(settings)
    runtime_store = SupabaseGraderExecutionRuntimeStore(
        settings,
        transport=transport,
    )
    input_token_preflight_store = SupabaseInputTokenPreflightStore(
        settings,
        transport=transport,
    )
    return DomainPersistentGraderLifecycleFactory(
        lifecycle_factory=lambda _: SupabaseGraderExecutionLifecycle(runtime_store),
        read_model_factory=lambda binding: SupabasePersistentExecutionReadModel(
            store=runtime_store,
            bundle=binding.evidence_bundle,
            request=binding.request,
        ),
        valuation_snapshot_repository=valuation_snapshot_repository,
        input_token_preflight_store=input_token_preflight_store,
    )


def compose_supabase_registry_bound_grader_committee_stage(
    *,
    settings: SupabaseStorageSettings,
    registry: OpenAIExecutionContractRegistry,
    config: BiotechResearchCommitteeConfig,
    provider: GraderProvider,
    budget: PersistentGraderBudgetContext,
    clock: Callable[[], datetime],
    transport: JsonTransport | None = None,
) -> PersistentGraderCommitteeStage:
    research_runs = SupabaseResearchRunRepository(settings, transport=transport)
    evidence_bundles = SupabaseEvidenceBundleRepository(
        settings,
        transport=transport,
    )
    valuation_snapshots = SupabaseValuationSnapshotRepository(
        settings,
        transport=transport,
    )
    committees = SupabaseResearchCommitteeRepository(
        settings,
        transport=transport,
    )
    lifecycle_factory = compose_supabase_persistent_grader_lifecycle_factory(
        settings=settings,
        transport=transport,
        valuation_snapshot_repository=valuation_snapshots,
    )
    return compose_registry_bound_grader_committee_stage(
        research_run_repository=research_runs,
        evidence_bundle_repository=evidence_bundles,
        committee_repository=committees,
        registry=registry,
        config=config,
        lifecycle_factory=lifecycle_factory,
        provider=provider,
        budget=budget,
        clock=clock,
    )


def compose_supabase_committee_memo_stage(
    *,
    settings: SupabaseStorageSettings,
    config: BiotechResearchCommitteeConfig,
    provider: GraderProvider,
    clock: Callable[[], datetime],
    transport: JsonTransport | None = None,
) -> PersistentCommitteeMemoStage:
    _validate_supabase_storage_settings(settings)
    research_runs = SupabaseResearchRunRepository(settings, transport=transport)
    evidence_bundles = SupabaseEvidenceBundleRepository(
        settings,
        transport=transport,
    )
    valuations = SupabaseValuationSnapshotRepository(
        settings,
        transport=transport,
    )
    committees = SupabaseResearchCommitteeRepository(
        settings,
        transport=transport,
    )
    memo_read_model = SupabaseCommitteeMemoReadModel(
        settings,
        transport=transport,
    )
    memo_repository = SupabaseCommitteeMemoRepository(
        runtime_store=SupabaseCommitteeMemoRuntimeStore(
            settings,
            transport=transport,
        ),
        read_model=memo_read_model,
    )
    workflow = CommitteeMemoWorkflow(
        committee_repository=committees,
        evidence_bundle_repository=evidence_bundles,
        memo_repository=memo_repository,
        budget_ledger=RuntimeManagedSynthesisBudgetLedger(),
        provider=provider,
        input_token_preflight_gate=PersistentInputTokenPreflightGate(
            store=SupabaseInputTokenPreflightStore(
                settings,
                transport=transport,
            ),
            clock=clock,
        ),
        clock=clock,
    )
    return PersistentCommitteeMemoStage(
        research_run_repository=research_runs,
        workflow=PersistentCommitteeMemoWorkflowAdapter(
            research_run_repository=research_runs,
            committee_read_model=committees,
            valuation_snapshot_repository=valuations,
            config=config,
            workflow=workflow,
            memo_repository=memo_repository,
        ),
    )


def compose_supabase_readiness_thesis_stage(
    *,
    settings: SupabaseStorageSettings,
    clock: Callable[[], datetime],
    transport: JsonTransport | None = None,
) -> PersistentReadinessThesisStage:
    _validate_supabase_storage_settings(settings)
    research_runs = SupabaseResearchRunRepository(settings, transport=transport)
    evidence_bundles = SupabaseEvidenceBundleRepository(
        settings,
        transport=transport,
    )
    valuations = SupabaseValuationSnapshotRepository(
        settings,
        transport=transport,
    )
    committees = SupabaseResearchCommitteeRepository(
        settings,
        transport=transport,
    )
    memo_read_model = SupabaseCommitteeMemoReadModel(
        settings,
        transport=transport,
    )
    memo_repository = SupabaseCommitteeMemoRepository(
        runtime_store=SupabaseCommitteeMemoRuntimeStore(
            settings,
            transport=transport,
        ),
        read_model=memo_read_model,
    )
    readiness_read_model = SupabaseReadinessThesisReadModel(
        settings,
        transport=transport,
    )
    readiness_repository = SupabaseReadinessAndThesisRepository(
        runtime_store=SupabaseReadinessThesisRuntimeStore(
            settings,
            transport=transport,
        ),
        read_model=readiness_read_model,
    )
    workflow = ReadinessAndThesisWorkflow(
        committee_repository=committees,
        evidence_bundle_repository=evidence_bundles,
        memo_repository=memo_repository,
        repository=readiness_repository,
        clock=clock,
        valuation_snapshot_repository=valuations,
    )
    return PersistentReadinessThesisStage(
        research_run_repository=research_runs,
        workflow=PersistentReadinessThesisWorkflowAdapter(
            research_run_repository=research_runs,
            committee_read_model=committees,
            workflow=workflow,
        ),
    )


__all__ = [
    "FixedTrustedIssuerHostRegistry",
    "PersistentCommitteeCompositionError",
    "TrustedIssuerHostConfiguration",
    "TrustedIssuerHostRegistry",
    "compose_dynamic_persistent_evidence_bundle_stage",
    "compose_persistent_committee_worker",
    "compose_persistent_evidence_bundle_stage",
    "compose_persistent_grader_committee_stage",
    "compose_personal_research_valuation_input_source",
    "compose_registry_bound_grader_committee_stage",
    "compose_supabase_committee_memo_stage",
    "compose_supabase_persistent_grader_lifecycle_factory",
    "compose_supabase_personal_research_valuation_snapshot_stage",
    "compose_supabase_readiness_thesis_stage",
    "compose_supabase_registry_bound_grader_committee_stage",
    "compose_supabase_valuation_snapshot_stage",
]

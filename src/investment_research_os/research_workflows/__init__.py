from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
import threading
from typing import Callable, Mapping, Protocol

from investment_research_os.committee_memos import (
    CommitteeMemoExecution,
    CommitteeMemoWorkflow,
    InMemoryCommitteeMemoRepository,
    SynthesisRequest,
)
from investment_research_os.evidence_bundles import (
    EvidenceBundle,
    EvidenceBundleSource,
    EvidenceBundleWorkflow,
    InMemoryEvidenceBundleRepository,
)
from investment_research_os.grader_executions import (
    ExecutionPolicy,
    GraderContract,
    GraderExecutionRequest,
    GraderExecutionWorkflow,
    GraderProvider,
    InMemoryBudgetLedger,
    InMemoryGraderExecutionRepository,
    ModelConfiguration,
    ModelPriceCard,
    PromptContract,
)
from investment_research_os.readiness_and_theses import (
    InMemoryReadinessAndThesisRepository,
    ReadinessAndThesisResult,
    ReadinessAndThesisWorkflow,
    ReadinessRequest,
)
from investment_research_os.research_committees import (
    InMemoryResearchCommitteeRepository,
    MVP_GRADER_ROSTER,
    ResearchCommitteeResult,
    ResearchCommitteeWorkflow,
)
from investment_research_os.research_runs import (
    AuthenticatedOperator,
    InMemoryResearchRunRepository,
    PERSONAL_RESEARCH_QUESTION_TYPE,
    PERSONAL_RESEARCH_QUESTION_TYPE_VERSION,
    PERSONAL_RESEARCH_WORKFLOW_CONFIG_VERSION,
    QUESTION_TYPE,
    QUESTION_TYPE_VERSION,
    ResearchRun,
    ResearchRunWorkflow,
    SecurityEligibilitySource,
    WORKFLOW_CONFIG_VERSION,
)
from investment_research_os.valuation_snapshots import (
    InMemoryValuationSnapshotRepository,
    MarketCalendar,
    ValuationInputSource,
    ValuationSnapshot,
    ValuationSnapshotWorkflow,
)


PROPOSITION_ID = "biotech_moonshot_catalyst_case"
PROPOSITION_VERSION = "biotech_moonshot_catalyst_case.v1"
PROPOSITION_TEXT = (
    "As of the cutoff, the available evidence supports a credible Moonshot "
    "research case with an identifiable catalyst capable of materially "
    "resolving uncertainty."
)

_SUPPORTED_COMMITTEE_CONTRACTS = {
    (
        QUESTION_TYPE,
        QUESTION_TYPE_VERSION,
        WORKFLOW_CONFIG_VERSION,
    ): "biotech-readiness.v1",
    (
        PERSONAL_RESEARCH_QUESTION_TYPE,
        PERSONAL_RESEARCH_QUESTION_TYPE_VERSION,
        PERSONAL_RESEARCH_WORKFLOW_CONFIG_VERSION,
    ): "biotech-personal-readiness.v1",
}


class BiotechResearchWorkflowError(ValueError):
    """Raised when the pinned public workflow surface is inconsistent."""


class GraderEligibilityRouter(Protocol):
    """Deterministically route versioned graders from a frozen bundle."""

    def route(
        self,
        bundle: EvidenceBundle,
        grader_ids: tuple[str, ...],
    ) -> Mapping[str, bool]: ...


@dataclass(frozen=True, slots=True)
class BiotechResearchRequest:
    security_id: str
    as_of_cutoff: datetime
    operator_focus: str | None = None

    def as_payload(self) -> dict[str, object]:
        return {
            "question_type": QUESTION_TYPE,
            "security_id": self.security_id,
            "as_of_cutoff": self.as_of_cutoff.isoformat(),
            "workflow_config_version": WORKFLOW_CONFIG_VERSION,
            "operator_focus": self.operator_focus,
        }


@dataclass(frozen=True, slots=True)
class GraderRuntimeConfiguration:
    contract: GraderContract
    prompt: PromptContract
    model: ModelConfiguration
    price_card: ModelPriceCard
    policy: ExecutionPolicy


@dataclass(frozen=True, slots=True)
class SynthesizerRuntimeConfiguration:
    prompt: PromptContract
    model: ModelConfiguration
    price_card: ModelPriceCard
    policy: ExecutionPolicy


def _runtime_contract_payload(
    runtime: GraderRuntimeConfiguration | SynthesizerRuntimeConfiguration,
) -> dict[str, object]:
    prompt = runtime.prompt
    model = runtime.model
    price_card = runtime.price_card
    policy = runtime.policy
    return {
        "prompt": {
            "prompt_id": prompt.prompt_id,
            "prompt_version": prompt.prompt_version,
            "input_schema_version": prompt.input_schema_version,
            "output_schema_version": prompt.output_schema_version,
            "active": prompt.active,
            "evaluation_passed": prompt.evaluation_passed,
            "content_sha256": prompt.content_sha256,
            "evaluation_corpus_id": prompt.evaluation_corpus_id,
            "evaluation_corpus_version": prompt.evaluation_corpus_version,
            "evaluation_corpus_sha256": prompt.evaluation_corpus_sha256,
            "evaluation_identity_sha256": prompt.evaluation_identity_sha256,
        },
        "model": {
            "config_id": model.config_id,
            "config_version": model.config_version,
            "provider": model.provider,
            "model": model.model,
            "reasoning_effort": model.reasoning_effort,
            "thinking_enabled": model.thinking_enabled,
            "temperature": model.temperature,
            "input_token_cap": model.input_token_cap,
            "output_token_cap": model.output_token_cap,
            "active": model.active,
            "evaluation_passed": model.evaluation_passed,
            "retention_approved": model.retention_approved,
            "source_processing_approved": model.source_processing_approved,
            "environment": model.environment,
        },
        "price_card": {
            "price_card_id": price_card.price_card_id,
            "provider": price_card.provider,
            "model": price_card.model,
            "currency": price_card.currency,
            "input_per_million": str(price_card.input_per_million),
            "cached_input_per_million": str(price_card.cached_input_per_million),
            "cache_write_per_million": str(price_card.cache_write_per_million),
            "output_per_million": str(price_card.output_per_million),
            "effective_from": price_card.effective_from.isoformat(),
            "effective_to": (
                price_card.effective_to.isoformat()
                if price_card.effective_to is not None
                else None
            ),
            "verified_at": price_card.verified_at.isoformat(),
        },
        "policy": {
            "policy_version": policy.policy_version,
            "retry_policy_version": policy.retry_policy_version,
            "budget_policy_version": policy.budget_policy_version,
            "max_attempts": policy.max_attempts,
            "required_environment": policy.required_environment,
        },
    }


@dataclass(frozen=True, slots=True)
class BiotechResearchCommitteeConfig:
    question_type: str
    question_type_version: str
    workflow_config_version: str
    proposition_id: str
    proposition_version: str
    proposition_text: str
    graders: tuple[GraderRuntimeConfiguration, ...]
    synthesizer: SynthesizerRuntimeConfiguration
    readiness_policy_version: str
    grader_budget_usd: Decimal
    synthesis_budget_usd: Decimal

    def __post_init__(self) -> None:
        research_contract = (
            self.question_type,
            self.question_type_version,
            self.workflow_config_version,
        )
        if (
            research_contract not in _SUPPORTED_COMMITTEE_CONTRACTS
            or self.proposition_id != PROPOSITION_ID
            or self.proposition_version != PROPOSITION_VERSION
            or self.proposition_text != PROPOSITION_TEXT
        ):
            raise BiotechResearchWorkflowError("workflow contract mismatch")
        expected = tuple(
            (
                item.grader_id,
                item.grader_version,
                item.owned_decision_question,
                item.required_when_eligible,
            )
            for item in MVP_GRADER_ROSTER
        )
        actual = tuple(
            (
                item.contract.grader_id,
                item.contract.grader_version,
                item.contract.owned_decision_question,
                item.contract.required,
            )
            for item in self.graders
        )
        if actual != expected or any(
            not item.contract.eligible for item in self.graders
        ):
            raise BiotechResearchWorkflowError("grader roster mismatch")
        if (
            self.readiness_policy_version
            != _SUPPORTED_COMMITTEE_CONTRACTS[research_contract]
        ):
            raise BiotechResearchWorkflowError("readiness policy mismatch")
        if self.grader_budget_usd <= 0 or self.synthesis_budget_usd <= 0:
            raise BiotechResearchWorkflowError("offline budget must be positive")

    @property
    def contract_fingerprint(self) -> str:
        payload = {
            "question_type": self.question_type,
            "question_type_version": self.question_type_version,
            "workflow_config_version": self.workflow_config_version,
            "proposition_id": self.proposition_id,
            "proposition_version": self.proposition_version,
            "graders": [
                {
                    "grader_id": item.contract.grader_id,
                    "grader_version": item.contract.grader_version,
                    "grader_contract_version": (item.contract.grader_contract_version),
                    "eligibility_rule_version": (
                        item.contract.eligibility_rule_version
                    ),
                    "rubric_version": item.contract.rubric_version,
                    "output_schema_version": (item.contract.output_schema_version),
                    "abstention_rule_version": (item.contract.abstention_rule_version),
                    "runtime": _runtime_contract_payload(item),
                }
                for item in self.graders
            ],
            "synthesizer": _runtime_contract_payload(self.synthesizer),
            "readiness_policy_version": self.readiness_policy_version,
            "grader_budget_usd": str(self.grader_budget_usd),
            "synthesis_budget_usd": str(self.synthesis_budget_usd),
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    def grader_requests(
        self,
        evidence_bundle_id: str,
        grader_eligibility: Mapping[str, bool] | None = None,
    ) -> tuple[GraderExecutionRequest, ...]:
        grader_ids = tuple(item.contract.grader_id for item in self.graders)
        eligibility = (
            {grader_id: True for grader_id in grader_ids}
            if grader_eligibility is None
            else dict(grader_eligibility)
        )
        if set(eligibility) != set(grader_ids) or any(
            type(value) is not bool for value in eligibility.values()
        ):
            raise BiotechResearchWorkflowError(
                "grader routing must cover the exact versioned roster"
            )
        return tuple(
            GraderExecutionRequest(
                evidence_bundle_id=evidence_bundle_id,
                question_type_id=self.question_type,
                question_type_version=self.question_type_version,
                workflow_config_version=self.workflow_config_version,
                proposition_id=self.proposition_id,
                proposition_version=self.proposition_version,
                rendered_proposition=self.proposition_text,
                grader=replace(
                    item.contract,
                    eligible=eligibility[item.contract.grader_id],
                ),
                prompt=item.prompt,
                model=item.model,
                price_card=item.price_card,
                policy=item.policy,
            )
            for item in self.graders
        )

    def synthesis_request(
        self,
        committee_id: str,
        calculation_ids: tuple[str, ...],
    ) -> SynthesisRequest:
        return SynthesisRequest(
            committee_id=committee_id,
            calculation_ids=calculation_ids,
            prompt=self.synthesizer.prompt,
            model=self.synthesizer.model,
            price_card=self.synthesizer.price_card,
            policy=self.synthesizer.policy,
        )


@dataclass(frozen=True, slots=True)
class BiotechResearchCommitteeResult:
    run: ResearchRun
    evidence_bundle: EvidenceBundle
    valuation_snapshot: ValuationSnapshot
    committee: ResearchCommitteeResult
    memo_execution: CommitteeMemoExecution
    readiness_and_thesis: ReadinessAndThesisResult
    contract_fingerprint: str


def _model_config(config_id: str, *, output_token_cap: int) -> ModelConfiguration:
    return ModelConfiguration(
        config_id=config_id,
        config_version=config_id,
        provider="openai",
        model="gpt-5.6-sol",
        reasoning_effort="medium",
        thinking_enabled=True,
        temperature="0",
        input_token_cap=32000 if output_token_cap == 4000 else 16000,
        output_token_cap=output_token_cap,
        active=True,
        evaluation_passed=True,
        retention_approved=True,
        source_processing_approved=True,
        environment="test",
    )


def _price_card() -> ModelPriceCard:
    return ModelPriceCard(
        price_card_id="gpt_5_6_sol_usd.v1",
        provider="openai",
        model="gpt-5.6-sol",
        currency="USD",
        input_per_million=Decimal("5.00"),
        cached_input_per_million=Decimal("0.50"),
        cache_write_per_million=Decimal("6.25"),
        output_per_million=Decimal("30.00"),
        effective_from=datetime(2026, 7, 1, tzinfo=UTC),
        effective_to=datetime(2026, 8, 21, 23, 59, 59, tzinfo=UTC),
        verified_at=datetime(2026, 7, 22, tzinfo=UTC),
    )


def _execution_policy() -> ExecutionPolicy:
    return ExecutionPolicy(
        policy_version="grader-execution-policy-v1",
        retry_policy_version="grader-retry-policy-v1",
        budget_policy_version="research-budget-policy-v1",
        max_attempts=2,
        required_environment="test",
    )


def _build_offline_mvp_config(
    *,
    question_type: str,
    question_type_version: str,
    workflow_config_version: str,
    readiness_policy_version: str,
) -> BiotechResearchCommitteeConfig:
    prompt_hashes = {
        "moonshot": "c44aff2da6de9cd8f74a24d48a65754bd703f4db5ff3596b56c29691ec78205b",
        "catalyst": "94ea632087eeb24a5760560902c0f0d9ed66f5872373ca0dfe1c6ef7833590e9",
        "biotech": "ccaa944db5e6547e3a5c2729fe724869868c46e254879d1c5ca6f248ad53d49a",
        "risk_dilution": (
            "0b28eeb4d66f018e90bd50174839a90b6d33a6cc05a8fdb3a60aeb22b40ed2d7"
        ),
        "valuation": "69f89ade22d287028790a617ac4ff0eecf80d07a027778ce690e7832fbce10db",
    }
    model = _model_config(
        "biotech_committee_graders_openai_sol_medium_test_v1",
        output_token_cap=2000,
    )
    graders = tuple(
        GraderRuntimeConfiguration(
            contract=GraderContract(
                grader_id=definition.grader_id,
                grader_version=definition.grader_version,
                grader_contract_version=(f"{definition.grader_id}-grader-contract-v1"),
                owned_decision_question=definition.owned_decision_question,
                eligibility_rule_version=(f"{definition.grader_id}-eligibility-v1"),
                rubric_version=f"{definition.grader_id}-rubric-v1",
                output_schema_version=(f"{definition.grader_id}_grader_payload.v1"),
                abstention_rule_version=(f"{definition.grader_id}-abstention-v1"),
                required=definition.required_when_eligible,
                eligible=True,
            ),
            prompt=PromptContract(
                prompt_id=f"{definition.grader_id}_grader_v1",
                prompt_version=f"{definition.grader_id}_grader_v1",
                input_schema_version="grader-input-v1",
                output_schema_version=(f"{definition.grader_id}_grader_payload.v1"),
                active=True,
                evaluation_passed=True,
                content_sha256=prompt_hashes[definition.grader_id],
            ),
            model=model,
            price_card=_price_card(),
            policy=_execution_policy(),
        )
        for definition in MVP_GRADER_ROSTER
    )
    synthesizer = SynthesizerRuntimeConfiguration(
        prompt=PromptContract(
            prompt_id="committee_reconcile_v1",
            prompt_version="committee_reconcile_v1",
            input_schema_version="committee-synthesis-input-v1",
            output_schema_version="committee_memo_payload.v1",
            active=True,
            evaluation_passed=True,
            content_sha256=(
                "bb2c90264cf56a6950abf635ef6ff348c6bdfd21c6772480ffc9bb4b10000ba2"
            ),
        ),
        model=_model_config(
            "biotech_committee_synthesizer_gpt_5_6_sol_medium_test_v1",
            output_token_cap=4000,
        ),
        price_card=_price_card(),
        policy=_execution_policy(),
    )
    return BiotechResearchCommitteeConfig(
        question_type=question_type,
        question_type_version=question_type_version,
        workflow_config_version=workflow_config_version,
        proposition_id=PROPOSITION_ID,
        proposition_version=PROPOSITION_VERSION,
        proposition_text=PROPOSITION_TEXT,
        graders=graders,
        synthesizer=synthesizer,
        readiness_policy_version=readiness_policy_version,
        grader_budget_usd=Decimal("7.00"),
        synthesis_budget_usd=Decimal("2.00"),
    )


def build_offline_mvp_config() -> BiotechResearchCommitteeConfig:
    """Build pinned strict config without authorizing live execution."""

    return _build_offline_mvp_config(
        question_type=QUESTION_TYPE,
        question_type_version=QUESTION_TYPE_VERSION,
        workflow_config_version=WORKFLOW_CONFIG_VERSION,
        readiness_policy_version="biotech-readiness.v1",
    )


def build_personal_research_mvp_config() -> BiotechResearchCommitteeConfig:
    """Build pinned lower-assurance config over the same five grader contracts."""

    return _build_offline_mvp_config(
        question_type=PERSONAL_RESEARCH_QUESTION_TYPE,
        question_type_version=PERSONAL_RESEARCH_QUESTION_TYPE_VERSION,
        workflow_config_version=PERSONAL_RESEARCH_WORKFLOW_CONFIG_VERSION,
        readiness_policy_version="biotech-personal-readiness.v1",
    )


def build_inactive_production_personal_research_mvp_config() -> (
    BiotechResearchCommitteeConfig
):
    """Build exact approved production profile without activating execution."""

    offline = build_personal_research_mvp_config()
    production_policy = replace(
        _execution_policy(),
        required_environment="production",
    )
    grader_model = ModelConfiguration(
        config_id="biotech_committee_graders_openai_sol_medium_v1",
        config_version="biotech_committee_graders_openai_sol_medium_v1",
        provider="openai",
        model="gpt-5.6-sol",
        reasoning_effort="medium",
        thinking_enabled=True,
        temperature="provider_default",
        input_token_cap=48_000,
        output_token_cap=4_000,
        active=False,
        evaluation_passed=False,
        retention_approved=True,
        source_processing_approved=True,
        environment="production",
    )
    synthesizer_model = ModelConfiguration(
        config_id="biotech_committee_synthesizer_gpt_5_6_sol_medium_v1",
        config_version=("biotech_committee_synthesizer_gpt_5_6_sol_medium_v1"),
        provider="openai",
        model="gpt-5.6-sol",
        reasoning_effort="medium",
        thinking_enabled=True,
        temperature="provider_default",
        input_token_cap=160_000,
        output_token_cap=6_000,
        active=False,
        evaluation_passed=False,
        retention_approved=True,
        source_processing_approved=True,
        environment="production",
    )
    graders = tuple(
        replace(
            grader,
            prompt=replace(
                grader.prompt,
                active=False,
                evaluation_passed=False,
            ),
            model=grader_model,
            policy=production_policy,
        )
        for grader in offline.graders
    )
    synthesizer = replace(
        offline.synthesizer,
        prompt=replace(
            offline.synthesizer.prompt,
            active=False,
            evaluation_passed=False,
        ),
        model=synthesizer_model,
        policy=production_policy,
    )
    return replace(
        offline,
        graders=graders,
        synthesizer=synthesizer,
    )


class BiotechResearchCommitteeWorkflow:
    """Generic orchestration over versioned stages and injected boundaries."""

    def __init__(
        self,
        *,
        config: BiotechResearchCommitteeConfig,
        eligibility_source: SecurityEligibilitySource,
        evidence_source: EvidenceBundleSource,
        market_calendar: MarketCalendar,
        valuation_input_source: ValuationInputSource,
        grader_provider: GraderProvider,
        synthesis_provider: GraderProvider,
        clock: Callable[[], datetime],
        grader_router: GraderEligibilityRouter | None = None,
    ) -> None:
        self._config = config
        self._grader_router = grader_router
        self._request_locks_guard = threading.Lock()
        self._request_locks: dict[str, object] = {}
        run_repository = InMemoryResearchRunRepository()
        bundle_repository = InMemoryEvidenceBundleRepository()
        valuation_repository = InMemoryValuationSnapshotRepository()
        committee_repository = InMemoryResearchCommitteeRepository()
        memo_repository = InMemoryCommitteeMemoRepository()
        readiness_repository = InMemoryReadinessAndThesisRepository()

        self._run_workflow = ResearchRunWorkflow(
            repository=run_repository,
            eligibility_source=eligibility_source,
            clock=clock,
        )
        self._bundle_workflow = EvidenceBundleWorkflow(
            research_run_repository=run_repository,
            bundle_repository=bundle_repository,
            evidence_source=evidence_source,
            clock=clock,
        )
        self._valuation_workflow = ValuationSnapshotWorkflow(
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=valuation_repository,
            market_calendar=market_calendar,
            input_source=valuation_input_source,
            clock=clock,
        )
        grader_workflow = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=valuation_repository,
            execution_repository=InMemoryGraderExecutionRepository(),
            budget_ledger=InMemoryBudgetLedger(
                hard_limit_usd=config.grader_budget_usd,
            ),
            provider=grader_provider,
            clock=clock,
        )
        self._committee_workflow = ResearchCommitteeWorkflow(
            grader_workflow=grader_workflow,
            evidence_bundle_repository=bundle_repository,
            repository=committee_repository,
            clock=clock,
        )
        self._memo_workflow = CommitteeMemoWorkflow(
            committee_repository=committee_repository,
            evidence_bundle_repository=bundle_repository,
            memo_repository=memo_repository,
            budget_ledger=InMemoryBudgetLedger(
                hard_limit_usd=config.synthesis_budget_usd,
            ),
            provider=synthesis_provider,
            clock=clock,
        )
        self._readiness_workflow = ReadinessAndThesisWorkflow(
            committee_repository=committee_repository,
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=valuation_repository,
            memo_repository=memo_repository,
            repository=readiness_repository,
            clock=clock,
        )

    def execute(
        self,
        operator: AuthenticatedOperator,
        request: BiotechResearchRequest,
    ) -> BiotechResearchCommitteeResult:
        execution_key = hashlib.sha256(
            json.dumps(
                {
                    "operator_id": operator.id,
                    "request": request.as_payload(),
                    "contract_fingerprint": self._config.contract_fingerprint,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        with self._request_locks_guard:
            request_lock = self._request_locks.setdefault(
                execution_key,
                threading.Lock(),
            )
        with request_lock:
            return self._execute_once(operator, request)

    def _execute_once(
        self,
        operator: AuthenticatedOperator,
        request: BiotechResearchRequest,
    ) -> BiotechResearchCommitteeResult:
        run = self._run_workflow.create(operator, request.as_payload())
        bundle = self._bundle_workflow.materialize(operator, run.id)
        valuation = self._valuation_workflow.materialize(operator, bundle.id)
        grader_ids = tuple(item.contract.grader_id for item in self._config.graders)
        grader_eligibility = (
            None
            if self._grader_router is None
            else self._grader_router.route(bundle, grader_ids)
        )
        committee = self._committee_workflow.execute(
            operator,
            self._config.grader_requests(bundle.id, grader_eligibility),
        )
        memo_execution = self._memo_workflow.execute(
            operator,
            self._config.synthesis_request(
                committee.committee_id,
                valuation.calculation_ids,
            ),
        )
        readiness = self._readiness_workflow.execute(
            operator,
            ReadinessRequest(
                committee_id=committee.committee_id,
                gate_policy_version=self._config.readiness_policy_version,
            ),
        )
        return BiotechResearchCommitteeResult(
            run=run,
            evidence_bundle=bundle,
            valuation_snapshot=valuation,
            committee=committee,
            memo_execution=memo_execution,
            readiness_and_thesis=readiness,
            contract_fingerprint=self._config.contract_fingerprint,
        )


__all__ = [
    "BiotechResearchCommitteeConfig",
    "BiotechResearchCommitteeResult",
    "BiotechResearchCommitteeWorkflow",
    "BiotechResearchRequest",
    "BiotechResearchWorkflowError",
    "GraderRuntimeConfiguration",
    "GraderEligibilityRouter",
    "SynthesizerRuntimeConfiguration",
    "build_inactive_production_personal_research_mvp_config",
    "build_offline_mvp_config",
    "build_personal_research_mvp_config",
]

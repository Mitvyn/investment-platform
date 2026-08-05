from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Mapping, Protocol

from investment_research_os.evidence_bundles import (
    EvidenceBundle,
    EvidenceBundleRepository,
)
from investment_research_os.grader_executions import (
    GraderExecution,
    GraderExecutionRequest,
    GraderProvider,
)
from investment_research_os.grader_executions.lifecycle_storage import (
    GraderExecutionLifecycleStorageError,
)
from investment_research_os.grader_executions.persistent_read_model import (
    PersistentExecutionReadError,
)
from investment_research_os.grader_executions.persistent_workflow import (
    DomainPersistentAttemptDriver,
    PersistentExecutionReadModel,
    PersistentGraderExecutionWorkflow,
    build_persistent_grader_execution_start,
)
from investment_research_os.grader_executions.runtime import (
    GraderExecutionLifecycle,
)
from investment_research_os.production_execution import (
    MVP_EVALUATION_EXECUTION_ROLES,
)
from investment_research_os.provider_input_token_preflight import (
    InputTokenPreflightStore,
    PersistentInputTokenPreflightGate,
)
from investment_research_os.providers.openai_contracts import (
    OpenAIExecutionContract,
    OpenAIExecutionContractRegistry,
)
from investment_research_os.research_committees import (
    ResearchCommitteeRepository,
    ResearchCommitteeResult,
    ResearchCommitteeWorkflow,
)
from investment_research_os.research_committees.storage import (
    ResearchCommitteeStorageError,
)
from investment_research_os.research_runs import (
    AuthenticatedOperator,
    ResearchRun,
    ResearchRunRepository,
)
from investment_research_os.research_workflows import (
    BiotechResearchCommitteeConfig,
)
from investment_research_os.valuation_snapshots import (
    ValuationSnapshotRepository,
)

from .worker import PersistentGraderCommitteeArtifact


class PersistentGraderCommitteeWorkflowError(ValueError):
    """Raised when a claim-scoped committee execution violates run identity."""


class ClaimScopedCommitteeExecution(Protocol):
    def execute(
        self,
        operator: AuthenticatedOperator,
    ) -> ResearchCommitteeResult: ...


class PersistentGraderCommitteeExecutionFactory(Protocol):
    def create(
        self,
        research_run: ResearchRun,
    ) -> ClaimScopedCommitteeExecution: ...


@dataclass(frozen=True, slots=True)
class PersistentGraderBudgetContext:
    budget_id: str
    snapshot: Mapping[str, object]

    def __post_init__(self) -> None:
        try:
            uuid.UUID(self.budget_id)
        except (AttributeError, TypeError, ValueError) as error:
            raise ValueError("persistent grader budget ID is invalid") from error
        if self.snapshot.get("status") != "available":
            raise ValueError("persistent grader budget is unavailable")


@dataclass(frozen=True, slots=True)
class PersistentGraderExecutionBinding:
    research_run: ResearchRun
    evidence_bundle: EvidenceBundle
    request: GraderExecutionRequest
    execution_contract: OpenAIExecutionContract
    provider: GraderProvider
    budget: PersistentGraderBudgetContext
    clock: Callable[[], datetime]


class BoundPersistentGraderExecution(Protocol):
    def execute(
        self,
        operator: AuthenticatedOperator,
    ) -> GraderExecution: ...


class PersistentGraderLifecycleFactory(Protocol):
    def create(
        self,
        binding: PersistentGraderExecutionBinding,
    ) -> BoundPersistentGraderExecution: ...


class _BoundPersistentGraderLifecycleExecution:
    def __init__(
        self,
        *,
        binding: PersistentGraderExecutionBinding,
        workflow: PersistentGraderExecutionWorkflow,
        start,
    ) -> None:
        self._binding = binding
        self._workflow = workflow
        self._start = start

    def execute(
        self,
        operator: AuthenticatedOperator,
    ) -> GraderExecution:
        if operator.id != self._binding.research_run.operator_id:
            raise PersistentGraderCommitteeWorkflowError(
                "grader_lifecycle_operator_mismatch"
            )
        result = self._workflow.execute(self._start)
        bundle = self._binding.evidence_bundle
        request = self._binding.request
        if (
            result.execution_identity != self._start.execution_key
            or result.execution_id != self._start.execution_id
            or result.operator_id != operator.id
            or result.research_run_id != bundle.research_run_id
            or result.evidence_bundle_id != bundle.id
            or result.bundle_hash != bundle.content_hash
            or result.grader_id != request.grader.grader_id
            or result.request != request
        ):
            raise PersistentGraderCommitteeWorkflowError(
                "grader_lifecycle_result_identity_mismatch"
            )
        return result


class DomainPersistentGraderLifecycleFactory:
    """Composes one contract-bound persistent lifecycle per grader binding."""

    def __init__(
        self,
        *,
        lifecycle_factory: Callable[
            [PersistentGraderExecutionBinding],
            GraderExecutionLifecycle,
        ],
        read_model_factory: Callable[
            [PersistentGraderExecutionBinding],
            PersistentExecutionReadModel,
        ],
        valuation_snapshot_repository: (ValuationSnapshotRepository | None) = None,
        input_token_preflight_store: InputTokenPreflightStore | None = None,
    ) -> None:
        self._lifecycle_factory = lifecycle_factory
        self._read_model_factory = read_model_factory
        self._valuation_snapshots = valuation_snapshot_repository
        self._input_token_preflight_store = input_token_preflight_store

    def create(
        self,
        binding: PersistentGraderExecutionBinding,
    ) -> BoundPersistentGraderExecution:
        self._validate_binding(binding)
        valuation_snapshot = (
            None
            if self._valuation_snapshots is None
            else self._valuation_snapshots.get_for_run(
                binding.research_run.operator_id,
                binding.research_run.id,
            )
        )
        started_at = binding.clock()
        start = build_persistent_grader_execution_start(
            operator_id=binding.research_run.operator_id,
            bundle=binding.evidence_bundle,
            request=binding.request,
            execution_contract=binding.execution_contract,
            budget_id=binding.budget.budget_id,
            budget_snapshot=binding.budget.snapshot,
            started_at=started_at,
            valuation_snapshot=valuation_snapshot,
        )
        workflow = PersistentGraderExecutionWorkflow(
            lifecycle=self._lifecycle_factory(binding),
            attempt_driver=DomainPersistentAttemptDriver(
                operator_id=binding.research_run.operator_id,
                bundle=binding.evidence_bundle,
                request=binding.request,
                execution_contract=binding.execution_contract,
                provider=binding.provider,
                input_token_preflight_gate=(
                    None
                    if self._input_token_preflight_store is None
                    else PersistentInputTokenPreflightGate(
                        store=self._input_token_preflight_store,
                        clock=binding.clock,
                    )
                ),
                clock=binding.clock,
                valuation_snapshot=valuation_snapshot,
            ),
            read_model=self._read_model_factory(binding),
        )
        return _BoundPersistentGraderLifecycleExecution(
            binding=binding,
            workflow=workflow,
            start=start,
        )

    @staticmethod
    def _validate_binding(
        binding: PersistentGraderExecutionBinding,
    ) -> None:
        run = binding.research_run
        bundle = binding.evidence_bundle
        request = binding.request
        contract = binding.execution_contract
        if (
            not isinstance(binding.budget, PersistentGraderBudgetContext)
            or bundle.operator_id != run.operator_id
            or bundle.research_run_id != run.id
            or bundle.security_id != run.security_id
            or bundle.as_of_cutoff != run.as_of_cutoff
            or request.evidence_bundle_id != bundle.id
            or request.question_type_version != run.question_type_version
            or request.workflow_config_version != run.workflow_config_version
            or contract.execution_role != f"grader:{request.grader.grader_id}"
            or contract.execution_contract_version
            != request.grader.grader_contract_version
            or contract.owned_decision_question
            != request.grader.owned_decision_question
            or contract.eligibility_rule_version
            != request.grader.eligibility_rule_version
            or contract.rubric_version != request.grader.rubric_version
            or contract.abstention_rule_version
            != request.grader.abstention_rule_version
            or contract.prompt.prompt_id != request.prompt.prompt_id
            or contract.prompt.prompt_version != request.prompt.prompt_version
            or contract.prompt.content_sha256 != request.prompt.content_sha256
            or contract.prompt.input_schema_version
            != request.prompt.input_schema_version
            or contract.prompt.output_schema_version
            != request.prompt.output_schema_version
            or contract.prompt.output_schema_version
            != request.grader.output_schema_version
        ):
            raise PersistentGraderCommitteeWorkflowError(
                "grader_lifecycle_contract_binding_mismatch"
            )


@dataclass(frozen=True, slots=True)
class _BoundGrader:
    binding: PersistentGraderExecutionBinding
    execution: BoundPersistentGraderExecution


class _BoundGraderWorkflow:
    def __init__(self, graders: tuple[_BoundGrader, ...]) -> None:
        self._graders = {
            grader.binding.request.grader.grader_id: grader for grader in graders
        }

    def execute(
        self,
        operator: AuthenticatedOperator,
        request: GraderExecutionRequest,
    ) -> GraderExecution:
        grader = self._graders.get(request.grader.grader_id)
        if grader is None or grader.binding.request != request:
            raise PersistentGraderCommitteeWorkflowError(
                "grader_committee_request_binding_mismatch"
            )
        result = grader.execution.execute(operator)
        run = grader.binding.research_run
        bundle = grader.binding.evidence_bundle
        if (
            operator.id != run.operator_id
            or result.operator_id != operator.id
            or result.research_run_id != run.id
            or result.evidence_bundle_id != bundle.id
            or result.bundle_hash != bundle.content_hash
            or result.question_type_id != request.question_type_id
            or result.question_type_version != request.question_type_version
            or result.workflow_config_version != request.workflow_config_version
            or result.grader_id != request.grader.grader_id
            or result.grader_version != request.grader.grader_version
            or result.prompt_version != request.prompt.prompt_version
            or result.model_config_version != request.model.config_version
        ):
            raise PersistentGraderCommitteeWorkflowError(
                "grader_committee_execution_identity_mismatch"
            )
        return result


class _ClaimScopedResearchCommitteeExecution:
    def __init__(
        self,
        *,
        workflow: ResearchCommitteeWorkflow,
        requests: tuple[GraderExecutionRequest, ...],
    ) -> None:
        self._workflow = workflow
        self._requests = requests

    def execute(
        self,
        operator: AuthenticatedOperator,
    ) -> ResearchCommitteeResult:
        return self._workflow.execute(operator, self._requests)


class OpenAIClaimScopedCommitteeExecutionFactory:
    """Binds one frozen run to five isolated persistent grader lifecycles."""

    def __init__(
        self,
        *,
        evidence_bundle_repository: EvidenceBundleRepository,
        committee_repository: ResearchCommitteeRepository,
        registry: OpenAIExecutionContractRegistry,
        config: BiotechResearchCommitteeConfig,
        lifecycle_factory: PersistentGraderLifecycleFactory,
        provider: GraderProvider,
        budget: PersistentGraderBudgetContext,
        clock: Callable[[], datetime],
    ) -> None:
        self._evidence_bundles = evidence_bundle_repository
        self._committees = committee_repository
        self._config = config
        self._registry = registry.for_research_contract(
            question_type_version=config.question_type_version,
            workflow_config_version=config.workflow_config_version,
        )
        self._lifecycle_factory = lifecycle_factory
        self._provider = provider
        self._budget = budget
        self._clock = clock

    def create(
        self,
        research_run: ResearchRun,
    ) -> ClaimScopedCommitteeExecution:
        bundle = self._evidence_bundles.get_for_run(
            research_run.operator_id,
            research_run.id,
        )
        if bundle is None:
            raise PersistentGraderCommitteeWorkflowError(
                "grader_committee_evidence_bundle_missing"
            )
        self._validate_claim_identity(research_run, bundle)
        contracts = self._grader_contracts()
        requests = tuple(
            self._request(bundle, runtime, contract)
            for runtime, contract in zip(
                self._config.graders,
                contracts,
                strict=True,
            )
        )
        bindings = tuple(
            PersistentGraderExecutionBinding(
                research_run=research_run,
                evidence_bundle=bundle,
                request=request,
                execution_contract=contract,
                provider=self._provider,
                budget=self._budget,
                clock=self._clock,
            )
            for request, contract in zip(
                requests,
                contracts,
                strict=True,
            )
        )
        executions = tuple(
            self._lifecycle_factory.create(binding) for binding in bindings
        )
        if len({id(execution) for execution in executions}) != 5:
            raise PersistentGraderCommitteeWorkflowError(
                "grader_committee_execution_isolation_failed"
            )
        graders = tuple(
            _BoundGrader(binding, execution)
            for binding, execution in zip(
                bindings,
                executions,
                strict=True,
            )
        )
        return _ClaimScopedResearchCommitteeExecution(
            workflow=ResearchCommitteeWorkflow(
                grader_workflow=_BoundGraderWorkflow(graders),
                evidence_bundle_repository=self._evidence_bundles,
                repository=self._committees,
                clock=self._clock,
            ),
            requests=requests,
        )

    def _validate_claim_identity(
        self,
        research_run: ResearchRun,
        bundle: EvidenceBundle,
    ) -> None:
        if (
            self._registry.question_type_version != research_run.question_type_version
            or self._registry.workflow_config_version
            != research_run.workflow_config_version
            or self._config.question_type_version != research_run.question_type_version
            or self._config.workflow_config_version
            != research_run.workflow_config_version
            or bundle.operator_id != research_run.operator_id
            or bundle.research_run_id != research_run.id
            or bundle.security_id != research_run.security_id
            or bundle.as_of_cutoff != research_run.as_of_cutoff
        ):
            raise PersistentGraderCommitteeWorkflowError(
                "grader_committee_claim_identity_mismatch"
            )

    def _grader_contracts(self) -> tuple[OpenAIExecutionContract, ...]:
        expected_roles = MVP_EVALUATION_EXECUTION_ROLES[:-1]
        contracts = self._registry.contracts[:-1]
        if (
            self._registry.execution_roles != MVP_EVALUATION_EXECUTION_ROLES
            or tuple(contract.execution_role for contract in contracts)
            != expected_roles
            or len(contracts) != 5
        ):
            raise PersistentGraderCommitteeWorkflowError(
                "grader_committee_registry_roster_mismatch"
            )
        for runtime, contract in zip(
            self._config.graders,
            contracts,
            strict=True,
        ):
            if (
                contract.execution_role != f"grader:{runtime.contract.grader_id}"
                or contract.execution_contract_version
                != runtime.contract.grader_contract_version
                or contract.owned_decision_question
                != runtime.contract.owned_decision_question
                or contract.eligibility_rule_version
                != runtime.contract.eligibility_rule_version
                or contract.rubric_version != runtime.contract.rubric_version
                or contract.abstention_rule_version
                != runtime.contract.abstention_rule_version
                or contract.prompt.prompt_id != runtime.prompt.prompt_id
                or contract.prompt.prompt_version != runtime.prompt.prompt_version
                or contract.prompt.content_sha256 != runtime.prompt.content_sha256
                or contract.prompt.input_schema_version
                != runtime.prompt.input_schema_version
                or contract.prompt.output_schema_version
                != runtime.prompt.output_schema_version
            ):
                raise PersistentGraderCommitteeWorkflowError(
                    "grader_committee_registry_binding_mismatch"
                )
        return contracts

    def _request(
        self,
        bundle: EvidenceBundle,
        runtime,
        contract: OpenAIExecutionContract,
    ) -> GraderExecutionRequest:
        return GraderExecutionRequest(
            evidence_bundle_id=bundle.id,
            question_type_id=self._config.question_type,
            question_type_version=self._config.question_type_version,
            workflow_config_version=self._config.workflow_config_version,
            proposition_id=self._config.proposition_id,
            proposition_version=self._config.proposition_version,
            rendered_proposition=self._config.proposition_text,
            grader=replace(
                runtime.contract,
                grader_contract_version=(contract.execution_contract_version),
                owned_decision_question=contract.owned_decision_question,
                eligibility_rule_version=contract.eligibility_rule_version,
                rubric_version=contract.rubric_version,
                output_schema_version=(contract.prompt.output_schema_version),
                abstention_rule_version=(contract.abstention_rule_version),
            ),
            prompt=replace(
                runtime.prompt,
                prompt_id=contract.prompt.prompt_id,
                prompt_version=contract.prompt.prompt_version,
                input_schema_version=(contract.prompt.input_schema_version),
                output_schema_version=(contract.prompt.output_schema_version),
                content_sha256=contract.prompt.content_sha256,
            ),
            model=runtime.model,
            price_card=runtime.price_card,
            policy=runtime.policy,
        )


class PersistentGraderCommitteeWorkflowAdapter:
    """Creates isolated run-specific committee execution after a claim."""

    def __init__(
        self,
        *,
        research_run_repository: ResearchRunRepository,
        execution_factory: PersistentGraderCommitteeExecutionFactory,
    ) -> None:
        self._research_runs = research_run_repository
        self._execution_factory = execution_factory

    def execute(
        self,
        operator: AuthenticatedOperator,
        research_run_id: str,
    ) -> PersistentGraderCommitteeArtifact:
        run = self._research_runs.get(operator.id, research_run_id)
        if run is None:
            raise PersistentGraderCommitteeWorkflowError(
                "grader_committee_research_run_missing"
            )
        try:
            execution = self._execution_factory.create(run)
            committee = execution.execute(operator)
        except (
            GraderExecutionLifecycleStorageError,
            PersistentExecutionReadError,
        ) as error:
            raise ResearchCommitteeStorageError(
                "persistent grader execution state is unavailable"
            ) from error
        if (
            committee.operator_id != run.operator_id
            or committee.research_run_id != run.id
            or committee.security_id != run.security_id
            or committee.question_type_version != run.question_type_version
            or committee.workflow_config_version != run.workflow_config_version
        ):
            raise PersistentGraderCommitteeWorkflowError(
                "grader_committee_identity_mismatch"
            )
        try:
            committee_id = str(uuid.UUID(committee.committee_id))
        except (AttributeError, TypeError, ValueError) as error:
            raise PersistentGraderCommitteeWorkflowError(
                "grader_committee_identity_invalid"
            ) from error
        return PersistentGraderCommitteeArtifact(
            id=committee_id,
            operator_id=run.operator_id,
            research_run_id=run.id,
            security_id=run.security_id,
            as_of_cutoff=run.as_of_cutoff,
            question_type_version=run.question_type_version,
            workflow_config_version=run.workflow_config_version,
        )


__all__ = [
    "BoundPersistentGraderExecution",
    "ClaimScopedCommitteeExecution",
    "DomainPersistentGraderLifecycleFactory",
    "OpenAIClaimScopedCommitteeExecutionFactory",
    "PersistentGraderBudgetContext",
    "PersistentGraderCommitteeExecutionFactory",
    "PersistentGraderCommitteeWorkflowAdapter",
    "PersistentGraderCommitteeWorkflowError",
    "PersistentGraderExecutionBinding",
    "PersistentGraderLifecycleFactory",
]

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

from investment_research_os.evidence_bundles import (
    InMemoryEvidenceBundleRepository,
)
from investment_research_os.grader_executions.lifecycle_storage import (
    GraderExecutionLifecycleStorageError,
)
from investment_research_os.grader_executions.runtime import (
    RuntimeExecutionSnapshot,
)
from investment_research_os.ids import stable_id
from investment_research_os.providers.openai_contracts import (
    OpenAIExecutionContractRegistry,
)
from investment_research_os.research_committees import (
    InMemoryResearchCommitteeRepository,
)
from investment_research_os.research_committees.storage import (
    ResearchCommitteeStorageError,
)
from investment_research_os.research_runs import AuthenticatedOperator
from investment_research_os.research_runs import (
    PERSONAL_RESEARCH_QUESTION_TYPE,
    PERSONAL_RESEARCH_QUESTION_TYPE_VERSION,
    PERSONAL_RESEARCH_WORKFLOW_CONFIG_VERSION,
)
from investment_research_os.research_workflows import (
    build_offline_mvp_config,
    build_personal_research_mvp_config,
)
from tests.test_five_grader_committee import completed_committee_fixture
from tests.test_openai_execution_contract_registry import CONTRACTS, PROMPTS
from tests.test_primary_source_plans import research_run
from workers.research_committee.grader import (
    DomainPersistentGraderLifecycleFactory,
    OpenAIClaimScopedCommitteeExecutionFactory,
    PersistentGraderBudgetContext,
    PersistentGraderCommitteeWorkflowAdapter,
    PersistentGraderCommitteeWorkflowError,
    PersistentGraderExecutionBinding,
)


class ResearchRunRepositoryFake:
    def __init__(self, runs) -> None:
        self.runs = {run.id: run for run in runs}

    def get(self, operator_id: str, research_run_id: str):
        run = self.runs.get(research_run_id)
        if run is None or run.operator_id != operator_id:
            return None
        return run


class ClaimScopedExecution:
    def __init__(self, run) -> None:
        self.run = run
        self.operators: list[str] = []

    def execute(self, operator: AuthenticatedOperator):
        self.operators.append(operator.id)
        return SimpleNamespace(
            committee_id=replace_id(self.run.id, "8"),
            operator_id=self.run.operator_id,
            research_run_id=self.run.id,
            security_id=self.run.security_id,
            question_type_version=self.run.question_type_version,
            workflow_config_version=self.run.workflow_config_version,
        )


class RecordingClaimScopedFactory:
    def __init__(self) -> None:
        self.runs = []
        self.executions = []

    def create(self, run):
        self.runs.append(run)
        execution = ClaimScopedExecution(run)
        self.executions.append(execution)
        return execution


class FailingClaimScopedFactory:
    def create(self, run):
        raise GraderExecutionLifecycleStorageError(
            "persistent grader state unavailable"
        )


class BoundExecution:
    def __init__(self, execution) -> None:
        self.execution = execution
        self.operators = []

    def execute(self, operator):
        self.operators.append(operator.id)
        return self.execution


class RecordingLifecycleFactory:
    def __init__(self, executions) -> None:
        self.executions = {execution.grader_id: execution for execution in executions}
        self.bindings = []
        self.bound_executions = []

    def create(self, binding):
        self.bindings.append(binding)
        fixture = self.executions[binding.request.grader.grader_id]
        execution = BoundExecution(
            replace(
                fixture,
                model_config_version=binding.request.model.config_version,
                request=binding.request,
            )
        )
        self.bound_executions.append(execution)
        return execution


class ClaimBoundRecordingLifecycleFactory:
    def __init__(self, executions) -> None:
        self.executions = {execution.grader_id: execution for execution in executions}
        self.bindings = []
        self.bound_executions = []

    def create(self, binding):
        self.bindings.append(binding)
        execution = self.executions[binding.request.grader.grader_id]
        rebound = replace(
            execution,
            question_type_id=binding.request.question_type_id,
            question_type_version=binding.request.question_type_version,
            workflow_config_version=binding.request.workflow_config_version,
            model_config_version=binding.request.model.config_version,
            request=binding.request,
        )
        bound = BoundExecution(rebound)
        self.bound_executions.append(bound)
        return bound


class ReusingLifecycle:
    def __init__(self, execution):
        self.execution = execution

    def load(self, operator_id, execution_key):
        execution_id = stable_id(
            operator_id,
            "grader-execution",
            execution_key,
        )
        canonical = replace(
            self.execution,
            execution_id=execution_id,
            execution_identity=execution_key,
        ).as_dict()
        return RuntimeExecutionSnapshot(
            operator_id,
            execution_id,
            execution_key,
            "complete",
            (),
            canonical,
        )


class ReusingReadModel:
    def __init__(self, execution):
        self.execution = execution

    def reconstruct_terminal(self, start, snapshot):
        return replace(
            self.execution,
            execution_id=start.execution_id,
            execution_identity=start.execution_key,
        )


def replace_id(value: str, replacement: str) -> str:
    return f"{replacement}{value[1:]}"


class PersistentGraderCommitteeWorkflowAdapterTests(unittest.TestCase):
    def test_concrete_lifecycle_factory_reuses_contract_bound_execution(self):
        bundle, fixture_committee, _, _ = completed_committee_fixture()
        expected = fixture_committee.grader_results[0].execution
        registry = OpenAIExecutionContractRegistry.load(
            contract_path=CONTRACTS,
            prompt_path=PROMPTS,
        )
        contract = registry.contracts[0]
        provider = SimpleNamespace(requests=[])
        binding = PersistentGraderExecutionBinding(
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
            provider=provider,
            budget=PersistentGraderBudgetContext(
                budget_id=replace_id(bundle.operator_id, "7"),
                snapshot={"status": "available"},
            ),
            clock=lambda: expected.created_at,
        )
        factory = DomainPersistentGraderLifecycleFactory(
            lifecycle_factory=lambda _: ReusingLifecycle(expected),
            read_model_factory=lambda _: ReusingReadModel(expected),
        )

        result = factory.create(binding).execute(
            AuthenticatedOperator(bundle.operator_id)
        )

        self.assertEqual(result.operator_id, bundle.operator_id)
        self.assertEqual(result.bundle_hash, bundle.content_hash)
        self.assertEqual(result.grader_id, "moonshot")
        self.assertEqual(provider.requests, [])

    def test_concrete_lifecycle_factory_rejects_tampered_contract_before_reuse(
        self,
    ):
        bundle, fixture_committee, _, _ = completed_committee_fixture()
        expected = fixture_committee.grader_results[0].execution
        contract = OpenAIExecutionContractRegistry.load(
            contract_path=CONTRACTS,
            prompt_path=PROMPTS,
        ).contracts[0]
        binding = PersistentGraderExecutionBinding(
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
            execution_contract=replace(
                contract,
                execution_role="grader:catalyst",
            ),
            provider=SimpleNamespace(requests=[]),
            budget=PersistentGraderBudgetContext(
                budget_id=replace_id(bundle.operator_id, "7"),
                snapshot={"status": "available"},
            ),
            clock=lambda: expected.created_at,
        )
        lifecycle_calls = []
        factory = DomainPersistentGraderLifecycleFactory(
            lifecycle_factory=lambda _: lifecycle_calls.append(True),
            read_model_factory=lambda _: ReusingReadModel(expected),
        )

        with self.assertRaisesRegex(
            PersistentGraderCommitteeWorkflowError,
            "grader_lifecycle_contract_binding_mismatch",
        ):
            factory.create(binding)

        self.assertEqual(lifecycle_calls, [])

    def test_concrete_lifecycle_factory_enforces_pre_call_gate(self):
        bundle, fixture_committee, _, _ = completed_committee_fixture()
        expected = fixture_committee.grader_results[0].execution
        contract = OpenAIExecutionContractRegistry.load(
            contract_path=CONTRACTS,
            prompt_path=PROMPTS,
        ).contracts[0]
        binding = PersistentGraderExecutionBinding(
            research_run=SimpleNamespace(
                id=bundle.research_run_id,
                operator_id=bundle.operator_id,
                security_id=bundle.security_id,
                question_type_version=("biotech_moonshot_catalyst_assessment.v1"),
                workflow_config_version="biotech-moonshot-catalyst-v1",
                as_of_cutoff=bundle.as_of_cutoff,
            ),
            evidence_bundle=bundle,
            request=replace(
                expected.request,
                prompt=replace(expected.request.prompt, active=False),
            ),
            execution_contract=contract,
            provider=SimpleNamespace(requests=[]),
            budget=PersistentGraderBudgetContext(
                budget_id=replace_id(bundle.operator_id, "7"),
                snapshot={"status": "available"},
            ),
            clock=lambda: expected.created_at,
        )
        lifecycle_calls = []
        factory = DomainPersistentGraderLifecycleFactory(
            lifecycle_factory=lambda _: lifecycle_calls.append(True),
            read_model_factory=lambda _: ReusingReadModel(expected),
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "grader_pre_call_gate_blocked:prompt_inactive",
        ):
            factory.create(binding)

        self.assertEqual(lifecycle_calls, [])

    def test_factory_builds_exactly_five_isolated_registry_bound_executions(
        self,
    ) -> None:
        bundle, fixture_committee, _, _ = completed_committee_fixture()
        bundles = InMemoryEvidenceBundleRepository()
        bundles.save(bundle)
        run = SimpleNamespace(
            id=bundle.research_run_id,
            operator_id=bundle.operator_id,
            security_id=bundle.security_id,
            question_type_version=("biotech_moonshot_catalyst_assessment.v1"),
            workflow_config_version="biotech-moonshot-catalyst-v1",
            as_of_cutoff=bundle.as_of_cutoff,
        )
        lifecycle_factory = RecordingLifecycleFactory(
            tuple(result.execution for result in fixture_committee.grader_results)
        )
        provider = object()
        budget = PersistentGraderBudgetContext(
            budget_id=replace_id(bundle.operator_id, "7"),
            snapshot={"status": "available"},
        )
        clock_values = iter(
            (
                fixture_committee.created_at + timedelta(seconds=1),
                fixture_committee.created_at + timedelta(seconds=2),
            )
        )
        factory = OpenAIClaimScopedCommitteeExecutionFactory(
            evidence_bundle_repository=bundles,
            committee_repository=InMemoryResearchCommitteeRepository(),
            registry=OpenAIExecutionContractRegistry.load(
                contract_path=CONTRACTS,
                prompt_path=PROMPTS,
            ),
            config=build_offline_mvp_config(),
            lifecycle_factory=lifecycle_factory,
            provider=provider,
            budget=budget,
            clock=lambda: next(clock_values),
        )

        execution = factory.create(run)
        committee = execution.execute(AuthenticatedOperator(bundle.operator_id))

        self.assertEqual(
            tuple(
                binding.execution_contract.execution_role
                for binding in lifecycle_factory.bindings
            ),
            (
                "grader:moonshot",
                "grader:catalyst",
                "grader:biotech",
                "grader:risk_dilution",
                "grader:valuation",
            ),
        )
        self.assertEqual(len(lifecycle_factory.bound_executions), 5)
        self.assertEqual(
            len({id(item) for item in lifecycle_factory.bound_executions}),
            5,
        )
        self.assertTrue(
            all(
                binding.provider is provider and binding.budget is budget
                for binding in lifecycle_factory.bindings
            )
        )
        self.assertEqual(committee.status, "complete")
        self.assertEqual(committee.accounting.accepted_count, 5)

    def test_personal_research_executes_same_five_isolated_grader_contracts(
        self,
    ) -> None:
        bundle, fixture_committee, _, _ = completed_committee_fixture()
        bundles = InMemoryEvidenceBundleRepository()
        bundles.save(bundle)
        run = SimpleNamespace(
            id=bundle.research_run_id,
            operator_id=bundle.operator_id,
            security_id=bundle.security_id,
            question_type_version=PERSONAL_RESEARCH_QUESTION_TYPE_VERSION,
            workflow_config_version=(PERSONAL_RESEARCH_WORKFLOW_CONFIG_VERSION),
            as_of_cutoff=bundle.as_of_cutoff,
        )
        source_registry = OpenAIExecutionContractRegistry.load(
            contract_path=CONTRACTS,
            prompt_path=PROMPTS,
        )
        lifecycle_factory = ClaimBoundRecordingLifecycleFactory(
            tuple(result.execution for result in fixture_committee.grader_results)
        )
        clock_values = iter(
            (
                fixture_committee.created_at + timedelta(seconds=1),
                fixture_committee.created_at + timedelta(seconds=2),
            )
        )
        factory = OpenAIClaimScopedCommitteeExecutionFactory(
            evidence_bundle_repository=bundles,
            committee_repository=InMemoryResearchCommitteeRepository(),
            registry=source_registry,
            config=build_personal_research_mvp_config(),
            lifecycle_factory=lifecycle_factory,
            provider=object(),
            budget=PersistentGraderBudgetContext(
                budget_id=replace_id(bundle.operator_id, "7"),
                snapshot={"status": "available"},
            ),
            clock=lambda: next(clock_values),
        )

        committee = factory.create(run).execute(
            AuthenticatedOperator(bundle.operator_id)
        )

        self.assertEqual(committee.question_type_id, PERSONAL_RESEARCH_QUESTION_TYPE)
        self.assertEqual(
            tuple(
                binding.request.question_type_version
                for binding in lifecycle_factory.bindings
            ),
            (PERSONAL_RESEARCH_QUESTION_TYPE_VERSION,) * 5,
        )
        self.assertEqual(
            tuple(
                binding.execution_contract.content_sha256
                for binding in lifecycle_factory.bindings
            ),
            tuple(
                contract.content_sha256 for contract in source_registry.contracts[:5]
            ),
        )
        self.assertEqual(len(lifecycle_factory.bound_executions), 5)
        self.assertEqual(
            len({id(item) for item in lifecycle_factory.bound_executions}),
            5,
        )
        self.assertEqual(committee.status, "complete")
        self.assertEqual(committee.accounting.accepted_count, 5)

    def test_builds_an_independent_execution_for_each_claimed_run(self) -> None:
        first = research_run()
        second = replace(
            first,
            id=replace_id(first.id, "7"),
            security_id=replace_id(first.security_id, "6"),
        )
        factory = RecordingClaimScopedFactory()
        workflow = PersistentGraderCommitteeWorkflowAdapter(
            research_run_repository=ResearchRunRepositoryFake((first, second)),
            execution_factory=factory,
        )
        operator = AuthenticatedOperator(first.operator_id)

        first_artifact = workflow.execute(operator, first.id)
        second_artifact = workflow.execute(operator, second.id)

        self.assertEqual([run.id for run in factory.runs], [first.id, second.id])
        self.assertIsNot(factory.executions[0], factory.executions[1])
        self.assertEqual(first_artifact.research_run_id, first.id)
        self.assertEqual(second_artifact.research_run_id, second.id)
        self.assertEqual(first_artifact.security_id, first.security_id)
        self.assertEqual(second_artifact.security_id, second.security_id)

    def test_restart_reuses_committee_without_reexecuting_graders(self) -> None:
        bundle, fixture_committee, _, _ = completed_committee_fixture()
        bundles = InMemoryEvidenceBundleRepository()
        bundles.save(bundle)
        committees = InMemoryResearchCommitteeRepository()
        run = SimpleNamespace(
            id=bundle.research_run_id,
            operator_id=bundle.operator_id,
            security_id=bundle.security_id,
            question_type_version=("biotech_moonshot_catalyst_assessment.v1"),
            workflow_config_version="biotech-moonshot-catalyst-v1",
            as_of_cutoff=bundle.as_of_cutoff,
        )
        lifecycle_factory = RecordingLifecycleFactory(
            tuple(result.execution for result in fixture_committee.grader_results)
        )
        clock_values = iter(
            (
                fixture_committee.created_at + timedelta(seconds=1),
                fixture_committee.created_at + timedelta(seconds=2),
            )
        )
        factory = OpenAIClaimScopedCommitteeExecutionFactory(
            evidence_bundle_repository=bundles,
            committee_repository=committees,
            registry=OpenAIExecutionContractRegistry.load(
                contract_path=CONTRACTS,
                prompt_path=PROMPTS,
            ),
            config=build_offline_mvp_config(),
            lifecycle_factory=lifecycle_factory,
            provider=object(),
            budget=PersistentGraderBudgetContext(
                budget_id=replace_id(bundle.operator_id, "7"),
                snapshot={"status": "available"},
            ),
            clock=lambda: next(clock_values),
        )
        operator = AuthenticatedOperator(bundle.operator_id)

        first = factory.create(run).execute(operator)
        second = factory.create(run).execute(operator)

        self.assertIs(second, first)
        self.assertEqual(len(lifecycle_factory.bound_executions), 10)
        self.assertTrue(
            all(
                len(execution.operators) == 1
                for execution in lifecycle_factory.bound_executions[:5]
            )
        )
        self.assertTrue(
            all(
                execution.operators == []
                for execution in lifecycle_factory.bound_executions[5:]
            )
        )

    def test_rejects_foreign_terminal_grader_execution_identity(self) -> None:
        bundle, fixture_committee, _, _ = completed_committee_fixture()
        bundles = InMemoryEvidenceBundleRepository()
        bundles.save(bundle)
        run = SimpleNamespace(
            id=bundle.research_run_id,
            operator_id=bundle.operator_id,
            security_id=bundle.security_id,
            question_type_version=("biotech_moonshot_catalyst_assessment.v1"),
            workflow_config_version="biotech-moonshot-catalyst-v1",
            as_of_cutoff=bundle.as_of_cutoff,
        )
        executions = [result.execution for result in fixture_committee.grader_results]
        executions[0] = replace(
            executions[0],
            operator_id="99999999-9999-4999-8999-999999999999",
        )
        clock_values = iter(
            (
                fixture_committee.created_at + timedelta(seconds=1),
                fixture_committee.created_at + timedelta(seconds=2),
            )
        )
        factory = OpenAIClaimScopedCommitteeExecutionFactory(
            evidence_bundle_repository=bundles,
            committee_repository=InMemoryResearchCommitteeRepository(),
            registry=OpenAIExecutionContractRegistry.load(
                contract_path=CONTRACTS,
                prompt_path=PROMPTS,
            ),
            config=build_offline_mvp_config(),
            lifecycle_factory=RecordingLifecycleFactory(tuple(executions)),
            provider=object(),
            budget=PersistentGraderBudgetContext(
                budget_id=replace_id(bundle.operator_id, "7"),
                snapshot={"status": "available"},
            ),
            clock=lambda: next(clock_values),
        )

        with self.assertRaisesRegex(
            PersistentGraderCommitteeWorkflowError,
            "grader_committee_execution_identity_mismatch",
        ):
            factory.create(run).execute(AuthenticatedOperator(bundle.operator_id))

    def test_normalizes_storage_failure_while_building_claim_execution(
        self,
    ) -> None:
        run = research_run()
        workflow = PersistentGraderCommitteeWorkflowAdapter(
            research_run_repository=ResearchRunRepositoryFake((run,)),
            execution_factory=FailingClaimScopedFactory(),
        )

        with self.assertRaisesRegex(
            ResearchCommitteeStorageError,
            "persistent grader execution state is unavailable",
        ):
            workflow.execute(AuthenticatedOperator(run.operator_id), run.id)


if __name__ == "__main__":
    unittest.main()

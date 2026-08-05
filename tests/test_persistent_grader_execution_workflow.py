from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
import unittest
import uuid

from investment_research_os.grader_executions import (
    GraderContract,
    GraderExecution,
    GraderExecutionRequest,
    GraderOpinion,
    ModelConfiguration,
    ModelPriceCard,
    PromptContract,
    ExecutionPolicy,
    ProviderResponse,
    ProviderTransportError,
    ProviderUsage,
)
from investment_research_os.grader_executions.persistent_workflow import (
    DomainPersistentAttemptDriver,
    PersistentAttemptDriver,
    PersistentExecutionReadModel,
    PersistentGraderExecutionError,
    PersistentGraderExecutionWorkflow,
    persistent_grader_execution_identity,
)
from investment_research_os.ids import stable_id
from investment_research_os.provider_input_token_preflight import (
    InputTokenPreflightReceipt,
    PersistentInputTokenPreflightGate,
)
from investment_research_os.providers import OpenAIInputTokenPreflight
from investment_research_os.providers.openai_contracts import (
    OpenAIExecutionContractRegistry,
)
from tests.test_evidence_bundle_storage import materialized_bundle
from tests.test_grader_execution_workflow import (
    FakeProvider as DomainFakeProvider,
    accepted_output,
    approved_request,
)
from tests.test_openai_execution_contract_registry import CONTRACTS, PROMPTS
from investment_research_os.grader_executions.runtime import (
    AttemptCompletion,
    AttemptStart,
    ExecutionFinalization,
    ExecutionStart,
    RuntimeAttemptSnapshot,
    RuntimeExecutionSnapshot,
)


NOW = datetime(2026, 7, 29, 2, 0, tzinfo=UTC)
OPERATOR_ID = "00000000-0000-4000-8000-000000000001"
RUN_ID = "00000000-0000-4000-8000-000000000002"
SECURITY_ID = "00000000-0000-4000-8000-000000000003"
BUNDLE_ID = "00000000-0000-4000-8000-000000000004"
EXECUTION_ID = "00000000-0000-4000-8000-000000000005"
ATTEMPT_ID = "00000000-0000-4000-8000-000000000006"
RAW_ID = "00000000-0000-4000-8000-000000000007"
RESERVATION_ID = "00000000-0000-4000-8000-000000000008"
BUDGET_ID = "00000000-0000-4000-8000-000000000009"
OPINION_ID = "00000000-0000-4000-8000-000000000010"
HASH = "a" * 64


class PreflightStoreFake:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def begin(self, start):
        self.events.append("preflight_request_persisted")
        return InputTokenPreflightReceipt(
            preflight_id=start.preflight_id,
            state="pending",
            reused=False,
        )

    def complete(self, completion):
        self.events.append("preflight_result_persisted")
        return InputTokenPreflightReceipt(
            preflight_id=completion.preflight_id,
            state=completion.state,
            reused=False,
        )


class PreflightDomainProvider(DomainFakeProvider):
    def __init__(self, responses, events: list[str]) -> None:
        super().__init__(responses)
        self.events = events

    def audit_input_token_count_request(self, request):
        return {
            "method": "POST",
            "url": "https://api.openai.com/v1/responses/input_tokens",
            "headers": {"Authorization": "[REDACTED]"},
            "payload": {"model": request.model, "input": request.logical_input},
        }

    def count_input_tokens(self, request):
        self.events.append("input_tokens_counted")
        payload = self.audit_input_token_count_request(request)["payload"]
        return OpenAIInputTokenPreflight(
            execution_identity=request.execution_identity,
            request_hash=request.request_hash,
            model=request.model,
            input_payload_sha256=hashlib.sha256(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode()
            ).hexdigest(),
            input_tokens=80,
            input_token_cap=request.input_token_cap,
            within_cap=True,
            raw_provider_response={
                "object": "response.input_tokens",
                "input_tokens": 80,
            },
        )

    def execute(self, request):
        self.events.append("generation")
        return super().execute(request)


def execution_request() -> GraderExecutionRequest:
    return GraderExecutionRequest(
        evidence_bundle_id=BUNDLE_ID,
        question_type_id="biotech_moonshot_catalyst_assessment",
        question_type_version="v1",
        workflow_config_version="v1",
        proposition_id="credible_moonshot_case",
        proposition_version="v1",
        rendered_proposition="Credible Moonshot case exists.",
        grader=GraderContract(
            grader_id="moonshot",
            grader_version="v1",
            grader_contract_version="v1",
            owned_decision_question="Is opportunity meaningfully asymmetric?",
            eligibility_rule_version="v1",
            rubric_version="v1",
            output_schema_version="v1",
            abstention_rule_version="v1",
            required=True,
            eligible=True,
        ),
        prompt=PromptContract(
            prompt_id="moonshot",
            prompt_version="v1",
            input_schema_version="v1",
            output_schema_version="v1",
            active=True,
            evaluation_passed=True,
        ),
        model=ModelConfiguration(
            config_id="openai-test",
            config_version="v1",
            provider="openai",
            model="gpt-test",
            reasoning_effort="low",
            thinking_enabled=False,
            temperature="0",
            input_token_cap=100,
            output_token_cap=100,
            active=True,
            evaluation_passed=True,
            retention_approved=True,
            source_processing_approved=True,
            environment="test",
        ),
        price_card=ModelPriceCard(
            price_card_id="test-v1",
            provider="openai",
            model="gpt-test",
            currency="USD",
            input_per_million=Decimal("1"),
            cached_input_per_million=Decimal("0"),
            cache_write_per_million=Decimal("0"),
            output_per_million=Decimal("1"),
            effective_from=NOW,
            effective_to=None,
            verified_at=NOW,
        ),
        policy=ExecutionPolicy(
            policy_version="v1",
            retry_policy_version="v1",
            budget_policy_version="v1",
            max_attempts=2,
            required_environment="test",
        ),
    )


def terminal_execution(state: str = "accepted") -> GraderExecution:
    opinion = GraderOpinion(
        opinion_id=OPINION_ID,
        execution_state=state,
        grader_id="moonshot",
        grader_version="v1",
        owned_decision_question="Is opportunity meaningfully asymmetric?",
        proposition_id="credible_moonshot_case",
        proposition_version="v1",
        rendered_proposition_text="Credible Moonshot case exists.",
        grader_stance="supports" if state == "accepted" else None,
        stance_rationale="Evidence supports case." if state == "accepted" else "",
        confidence="medium",
        summary="Evidence supports continued research.",
        material_claims=(),
        assumptions=(),
        contradicting_evidence=(),
        evidence_gaps=(),
        invalidation_signals=(),
        abstention=None,
        domain_payload={},
    )
    return GraderExecution(
        execution_id=EXECUTION_ID,
        execution_identity=HASH,
        operator_id=OPERATOR_ID,
        research_run_id=RUN_ID,
        evidence_bundle_id=BUNDLE_ID,
        bundle_hash=HASH,
        question_type_id="biotech_moonshot_catalyst_assessment",
        question_type_version="v1",
        workflow_config_version="v1",
        grader_id="moonshot",
        grader_version="v1",
        prompt_version="v1",
        model_config_version="v1",
        execution_state=state,
        attempts=(),
        opinion=opinion,
        blocking_reasons=(),
        policy_version="v1",
        retry_policy_version="v1",
        created_at=NOW,
        request=execution_request(),
    )


def execution_start() -> ExecutionStart:
    canonical = terminal_execution().as_dict()
    canonical["execution_state"] = None
    canonical["opinion"] = None
    canonical["not_executed"] = None
    return ExecutionStart.from_payload(
        OPERATOR_ID,
        {
            "id": EXECUTION_ID,
            "research_run_id": RUN_ID,
            "security_id": SECURITY_ID,
            "evidence_bundle_id": BUNDLE_ID,
            "evidence_bundle_hash": HASH,
            "execution_key": HASH,
            "question_type_id": "biotech_moonshot_catalyst_assessment",
            "question_type_version": "v1",
            "workflow_config_version": "v1",
            "thesis_contract_id": "biotech_moonshot_catalyst_assessment",
            "grader_id": "moonshot",
            "grader_version": "v1",
            "grader_contract_version": "v1",
            "eligibility_rule_version": "v1",
            "rubric_version": "v1",
            "output_schema_version": "v1",
            "abstention_rules_version": "v1",
            "prompt_version": "v1",
            "model_config_id": "openai-test",
            "price_card_id": "test-v1",
            "budget_id": BUDGET_ID,
            "provider": "openai",
            "model": "gpt-test",
            "inference_parameter_hash": HASH,
            "retry_policy_version": "v1",
            "max_attempts": 2,
            "required": True,
            "pre_call_gate": {"status": "passed"},
            "budget_snapshot": {"status": "available"},
            "started_at": NOW.isoformat(),
            "canonical_execution": canonical,
        },
    )


def domain_execution_start(bundle) -> ExecutionStart:
    execution_id = stable_id(bundle.operator_id, "grader-execution", HASH)
    request = approved_request(bundle.id)
    return ExecutionStart.from_payload(
        bundle.operator_id,
        {
            "id": execution_id,
            "research_run_id": bundle.research_run_id,
            "security_id": bundle.security_id,
            "evidence_bundle_id": bundle.id,
            "evidence_bundle_hash": bundle.content_hash,
            "execution_key": HASH,
            "question_type_id": request.question_type_id,
            "question_type_version": request.question_type_version,
            "workflow_config_version": request.workflow_config_version,
            "thesis_contract_id": request.question_type_id,
            "grader_id": request.grader.grader_id,
            "grader_version": request.grader.grader_version,
            "grader_contract_version": request.grader.grader_contract_version,
            "eligibility_rule_version": request.grader.eligibility_rule_version,
            "rubric_version": request.grader.rubric_version,
            "output_schema_version": request.grader.output_schema_version,
            "abstention_rules_version": request.grader.abstention_rule_version,
            "prompt_version": request.prompt.prompt_version,
            "model_config_id": request.model.config_id,
            "price_card_id": request.price_card.price_card_id,
            "budget_id": BUDGET_ID,
            "provider": request.model.provider,
            "model": request.model.model,
            "inference_parameter_hash": HASH,
            "retry_policy_version": request.policy.retry_policy_version,
            "max_attempts": 2,
            "required": True,
            "pre_call_gate": {"status": "passed"},
            "budget_snapshot": {"status": "available"},
            "started_at": NOW.isoformat(),
            "canonical_execution": {
                "contract_version": "grader_execution.v1",
                "id": execution_id,
            },
        },
    )


def attempt_start(number: int = 1) -> AttemptStart:
    return AttemptStart.create(
        operator_id=OPERATOR_ID,
        execution_id=EXECUTION_ID,
        attempt_id=str(uuid.UUID(int=5 + number)),
        attempt_number=number,
        request_sha256=HASH,
        provider="openai",
        model="gpt-test",
        model_config_id="openai-test",
        prompt_version="v1",
        started_at=NOW,
        raw_payload_id=str(uuid.UUID(int=6 + number)),
        price_card_id="test-v1",
        reserved_cost_usd=Decimal("0.01"),
        retry_reason=None if number == 1 else "validation_error",
        sanitized_request={"model": "gpt-test", "input": []},
        reservation_id=str(uuid.UUID(int=7 + number)),
        budget_id=BUDGET_ID,
        reserved_tokens=200,
    )


def accepted_completion(start: AttemptStart) -> AttemptCompletion:
    return AttemptCompletion.create(
        operator_id=OPERATOR_ID,
        execution_id=EXECUTION_ID,
        attempt_id=start.attempt_id,
        attempt_number=start.attempt_number,
        reservation_id=start.reservation_id,
        result="accepted",
        finished_at=NOW,
        duration_ms=10,
        provider_request_id="response-1",
        raw_payload_id=start.raw_payload_id,
        input_tokens=10,
        cached_input_tokens=0,
        cache_write_tokens=0,
        output_tokens=5,
        reasoning_tokens=0,
        tool_call_count=0,
        estimated_cost_usd=Decimal("0.01"),
        billed_cost_usd=None,
        usage_complete=True,
        validation_status="passed",
        schema_valid=True,
        citations_valid=True,
        validation_errors=(),
        retry_reason=None,
        reservation_state="reconciled",
        actual_cost_usd=Decimal("0.01"),
        sanitized_request=start.sanitized_request,
        sanitized_response={"id": "response-1", "output": []},
        validated_opinion={
            "opinion_id": OPINION_ID,
            "execution_id": EXECUTION_ID,
            "execution_state": "accepted",
        },
    )


def rejected_completion(start: AttemptStart) -> AttemptCompletion:
    return AttemptCompletion.create(
        operator_id=OPERATOR_ID,
        execution_id=EXECUTION_ID,
        attempt_id=start.attempt_id,
        attempt_number=start.attempt_number,
        reservation_id=start.reservation_id,
        result="validation_error",
        finished_at=NOW,
        duration_ms=10,
        provider_request_id=f"response-{start.attempt_number}",
        raw_payload_id=start.raw_payload_id,
        input_tokens=10,
        cached_input_tokens=0,
        cache_write_tokens=0,
        output_tokens=5,
        reasoning_tokens=0,
        tool_call_count=0,
        estimated_cost_usd=Decimal("0.01"),
        billed_cost_usd=None,
        usage_complete=True,
        validation_status="failed",
        schema_valid=False,
        citations_valid=None,
        validation_errors=("malformed_schema",),
        retry_reason="validation_error",
        reservation_state="reconciled",
        actual_cost_usd=Decimal("0.01"),
        sanitized_request=start.sanitized_request,
        sanitized_response={
            "id": f"response-{start.attempt_number}",
            "output": [],
        },
        validated_opinion=None,
    )


class FakeLifecycle:
    def __init__(
        self,
        events: list[str],
        snapshot: RuntimeExecutionSnapshot | None = None,
    ) -> None:
        self.events = events
        self.snapshot = snapshot

    def load(self, operator_id: str, execution_key: str):
        self.events.append("load")
        return self.snapshot

    def begin_execution(self, start: ExecutionStart):
        self.events.append("begin_execution")
        self.snapshot = RuntimeExecutionSnapshot(
            OPERATOR_ID, EXECUTION_ID, HASH, "draft", (), None
        )
        return self.snapshot

    def begin_attempt(self, start: AttemptStart):
        self.events.append("begin_attempt")
        previous = () if self.snapshot is None else self.snapshot.attempts
        self.snapshot = RuntimeExecutionSnapshot(
            OPERATOR_ID,
            EXECUTION_ID,
            HASH,
            "draft",
            (
                *previous,
                RuntimeAttemptSnapshot(
                    start.attempt_id,
                    start.attempt_number,
                    "draft",
                    "reserved",
                    None,
                    False,
                    None,
                    start.raw_payload_sha256,
                    None,
                ),
            ),
            None,
        )
        return self.snapshot

    def finish_attempt(self, completion: AttemptCompletion):
        self.events.append("finish_attempt")
        previous = () if self.snapshot is None else self.snapshot.attempts[:-1]
        is_opinion = completion.result in {"accepted", "abstained"}
        self.snapshot = RuntimeExecutionSnapshot(
            OPERATOR_ID,
            EXECUTION_ID,
            HASH,
            "draft",
            (
                *previous,
                RuntimeAttemptSnapshot(
                    completion.attempt_id,
                    completion.attempt_number,
                    "complete",
                    (
                        "released"
                        if completion.result == "transport_error"
                        else "reconciled"
                    ),
                    completion.result,
                    completion.result != "transport_error",
                    OPINION_ID if is_opinion else None,
                    completion.raw_payload_sha256,
                    NOW,
                ),
            ),
            None,
        )
        return self.snapshot

    def finalize_execution(self, finalization: ExecutionFinalization):
        self.events.append("finalize_execution")
        self.snapshot = RuntimeExecutionSnapshot(
            OPERATOR_ID,
            EXECUTION_ID,
            HASH,
            "complete",
            self.snapshot.attempts if self.snapshot else (),
            finalization.canonical_execution,
        )
        return self.snapshot


class FakeDriver(PersistentAttemptDriver):
    def __init__(
        self,
        events: list[str],
        results: tuple[str, ...] = ("accepted",),
    ) -> None:
        self.events = events
        self.results = results
        self.prepared_numbers: list[int] = []

    def prepare_attempt(
        self,
        start: ExecutionStart,
        snapshot: RuntimeExecutionSnapshot,
        attempt_number: int,
    ) -> AttemptStart:
        self.events.append("prepare_attempt")
        self.prepared_numbers.append(attempt_number)
        return attempt_start(attempt_number)

    def invoke_provider(self, start: AttemptStart) -> AttemptCompletion:
        self.events.append("provider")
        result = self.results[start.attempt_number - 1]
        if result == "accepted":
            return accepted_completion(start)
        return rejected_completion(start)


class FakeReadModel(PersistentExecutionReadModel):
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def reconstruct_terminal(
        self,
        start: ExecutionStart,
        snapshot: RuntimeExecutionSnapshot,
    ) -> GraderExecution:
        self.events.append("reconstruct_terminal")
        return terminal_execution()


class PersistentGraderExecutionWorkflowTests(unittest.TestCase):
    def test_domain_driver_requires_persisted_preflight_before_generation(self):
        bundle = materialized_bundle()
        request = approved_request(bundle.id)
        events: list[str] = []
        provider = PreflightDomainProvider(
            (
                ProviderResponse(
                    provider_request_id="response-domain-1",
                    raw_output=accepted_output(bundle.manifest[0].evidence_id),
                    usage=ProviderUsage(80, 0, 20, 5, 100),
                    resolved_model=request.model.model,
                    system_fingerprint="offline-test",
                ),
            ),
            events,
        )
        driver = DomainPersistentAttemptDriver(
            operator_id=bundle.operator_id,
            bundle=bundle,
            request=request,
            execution_contract=OpenAIExecutionContractRegistry.load(
                contract_path=CONTRACTS,
                prompt_path=PROMPTS,
            ).contracts[0],
            provider=provider,
            input_token_preflight_gate=PersistentInputTokenPreflightGate(
                store=PreflightStoreFake(events),
                clock=lambda: NOW,
            ),
            clock=lambda: NOW,
        )
        start = domain_execution_start(bundle)
        snapshot = RuntimeExecutionSnapshot(
            bundle.operator_id,
            start.execution_id,
            HASH,
            "draft",
            (),
            None,
        )

        attempt = driver.prepare_attempt(start, snapshot, 1)
        completion = driver.invoke_provider(attempt)

        self.assertEqual(completion.result, "accepted")
        self.assertEqual(
            events,
            [
                "preflight_request_persisted",
                "input_tokens_counted",
                "preflight_result_persisted",
                "generation",
            ],
        )

    def test_domain_driver_marks_nonretryable_provider_error_terminal(self):
        bundle = materialized_bundle()
        request = approved_request(bundle.id)
        contract = OpenAIExecutionContractRegistry.load(
            contract_path=CONTRACTS,
            prompt_path=PROMPTS,
        ).contracts[0]
        driver = DomainPersistentAttemptDriver(
            operator_id=bundle.operator_id,
            bundle=bundle,
            request=request,
            execution_contract=contract,
            provider=DomainFakeProvider(
                (
                    ProviderTransportError(
                        "openai_response_refusal",
                        retryable=False,
                        category="refusal",
                    ),
                )
            ),
            clock=lambda: NOW,
        )
        start = domain_execution_start(bundle)
        snapshot = RuntimeExecutionSnapshot(
            bundle.operator_id,
            start.execution_id,
            HASH,
            "draft",
            (),
            None,
        )

        attempt = driver.prepare_attempt(start, snapshot, 1)
        completion = driver.invoke_provider(attempt)
        payload, _, _ = completion.storage_arguments()

        self.assertEqual(completion.result, "transport_error")
        self.assertEqual(
            payload["retry_reason"],
            "nonretryable:openai_response_refusal",
        )

    def test_persistent_execution_identity_changes_with_contract_content(self):
        bundle = materialized_bundle()
        request = approved_request(bundle.id)
        contract = OpenAIExecutionContractRegistry.load(
            contract_path=CONTRACTS,
            prompt_path=PROMPTS,
        ).contracts[0]

        original = persistent_grader_execution_identity(
            bundle=bundle,
            request=request,
            execution_contract=contract,
        )
        drifted = persistent_grader_execution_identity(
            bundle=bundle,
            request=request,
            execution_contract=replace(
                contract,
                content_sha256="f" * 64,
            ),
        )

        self.assertNotEqual(original, drifted)

    def test_domain_driver_audits_exact_registry_execution_contract(self):
        bundle = materialized_bundle()
        request = approved_request(bundle.id)
        registry = OpenAIExecutionContractRegistry.load(
            contract_path=CONTRACTS,
            prompt_path=PROMPTS,
        )
        contract = registry.contracts[0]
        provider = DomainFakeProvider(())
        driver = DomainPersistentAttemptDriver(
            operator_id=bundle.operator_id,
            bundle=bundle,
            request=request,
            execution_contract=contract,
            provider=provider,
            clock=lambda: NOW,
        )
        start = domain_execution_start(bundle)
        snapshot = RuntimeExecutionSnapshot(
            bundle.operator_id,
            start.execution_id,
            HASH,
            "draft",
            (),
            None,
        )

        attempt = driver.prepare_attempt(start, snapshot, 1)

        self.assertEqual(
            attempt.sanitized_request["logical_input"]["execution_contract"],
            contract.logical_input_contract(),
        )

    def test_persists_attempt_before_provider_and_finalizes_persisted_opinion(self):
        events: list[str] = []
        workflow = PersistentGraderExecutionWorkflow(
            lifecycle=FakeLifecycle(events),
            attempt_driver=FakeDriver(events),
            read_model=FakeReadModel(events),
        )

        result = workflow.execute(execution_start())

        self.assertEqual(result.execution_state, "accepted")
        self.assertEqual(
            events,
            [
                "load",
                "begin_execution",
                "prepare_attempt",
                "begin_attempt",
                "provider",
                "finish_attempt",
                "reconstruct_terminal",
                "finalize_execution",
            ],
        )

    def test_reuses_complete_execution_without_provider_call(self):
        events: list[str] = []
        canonical = terminal_execution().as_dict()
        complete = RuntimeExecutionSnapshot(
            OPERATOR_ID,
            EXECUTION_ID,
            HASH,
            "complete",
            (),
            canonical,
        )
        workflow = PersistentGraderExecutionWorkflow(
            lifecycle=FakeLifecycle(events, complete),
            attempt_driver=FakeDriver(events),
            read_model=FakeReadModel(events),
        )

        result = workflow.execute(execution_start())

        self.assertEqual(result.execution_state, "accepted")
        self.assertEqual(events, ["load", "reconstruct_terminal"])

    def test_finalizes_persisted_validated_opinion_without_provider_call(self):
        events: list[str] = []
        completed_attempt = RuntimeAttemptSnapshot(
            ATTEMPT_ID,
            1,
            "complete",
            "reconciled",
            "accepted",
            True,
            OPINION_ID,
            HASH,
            NOW,
        )
        draft = RuntimeExecutionSnapshot(
            OPERATOR_ID,
            EXECUTION_ID,
            HASH,
            "draft",
            (completed_attempt,),
            None,
        )
        lifecycle = FakeLifecycle(events, draft)
        workflow = PersistentGraderExecutionWorkflow(
            lifecycle=lifecycle,
            attempt_driver=FakeDriver(events),
            read_model=FakeReadModel(events),
        )

        result = workflow.execute(execution_start())

        self.assertEqual(result.execution_state, "accepted")
        self.assertEqual(
            events,
            ["load", "reconstruct_terminal", "finalize_execution"],
        )

    def test_ambiguous_draft_attempt_fails_closed_without_provider_call(self):
        events: list[str] = []
        start = attempt_start()
        ambiguous = RuntimeExecutionSnapshot(
            OPERATOR_ID,
            EXECUTION_ID,
            HASH,
            "draft",
            (
                RuntimeAttemptSnapshot(
                    start.attempt_id,
                    1,
                    "draft",
                    "reserved",
                    None,
                    False,
                    None,
                    start.raw_payload_sha256,
                    None,
                ),
            ),
            None,
        )
        workflow = PersistentGraderExecutionWorkflow(
            lifecycle=FakeLifecycle(events, ambiguous),
            attempt_driver=FakeDriver(events),
            read_model=FakeReadModel(events),
        )

        with self.assertRaisesRegex(
            PersistentGraderExecutionError,
            "provider_dispatch_state_ambiguous",
        ):
            workflow.execute(execution_start())

        self.assertEqual(events, ["load"])

    def test_completed_retryable_failure_advances_to_second_attempt(self):
        events: list[str] = []
        failed_attempt = RuntimeAttemptSnapshot(
            ATTEMPT_ID,
            1,
            "complete",
            "reconciled",
            "validation_error",
            True,
            None,
            HASH,
            NOW,
        )
        draft = RuntimeExecutionSnapshot(
            OPERATOR_ID,
            EXECUTION_ID,
            HASH,
            "draft",
            (failed_attempt,),
            None,
        )
        driver = FakeDriver(events, ("validation_error", "accepted"))
        workflow = PersistentGraderExecutionWorkflow(
            lifecycle=FakeLifecycle(events, draft),
            attempt_driver=driver,
            read_model=FakeReadModel(events),
        )

        result = workflow.execute(execution_start())

        self.assertEqual(result.execution_state, "accepted")
        self.assertEqual(driver.prepared_numbers, [2])
        self.assertEqual(events.count("provider"), 1)
        self.assertLess(events.index("begin_attempt"), events.index("provider"))
        self.assertLess(
            events.index("finish_attempt"), events.index("finalize_execution")
        )

    def test_domain_driver_persists_canonical_validated_opinion_shape(self):
        bundle = materialized_bundle()
        request = approved_request(bundle.id)
        provider = DomainFakeProvider(
            (
                ProviderResponse(
                    provider_request_id="response-domain-1",
                    raw_output=accepted_output(bundle.manifest[0].evidence_id),
                    usage=ProviderUsage(1000, 200, 300, 100, 1300),
                    resolved_model=request.model.model,
                    system_fingerprint="offline-test",
                    raw_provider_response={
                        "id": "response-domain-1",
                        "reasoning_content": "must not persist",
                        "output": [],
                    },
                ),
            )
        )
        driver = DomainPersistentAttemptDriver(
            operator_id=bundle.operator_id,
            bundle=bundle,
            request=request,
            execution_contract=OpenAIExecutionContractRegistry.load(
                contract_path=CONTRACTS,
                prompt_path=PROMPTS,
            ).contracts[0],
            provider=provider,
            clock=lambda: NOW,
        )
        start = domain_execution_start(bundle)
        snapshot = RuntimeExecutionSnapshot(
            bundle.operator_id,
            start.execution_id,
            HASH,
            "draft",
            (),
            None,
        )

        attempt = driver.prepare_attempt(start, snapshot, 1)
        completion = driver.invoke_provider(attempt)
        _, response, opinion = completion.storage_arguments()

        self.assertEqual(completion.result, "accepted")
        self.assertEqual(opinion["execution_id"], start.execution_id)
        self.assertEqual(opinion["stance"], "supports")
        self.assertNotIn("grader_stance", opinion)
        self.assertIn("created_at", opinion)
        self.assertNotIn("reasoning_content", response)


if __name__ == "__main__":
    unittest.main()

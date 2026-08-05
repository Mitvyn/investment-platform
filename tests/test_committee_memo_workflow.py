from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import unittest
import json
import subprocess

from investment_research_os.committee_memos import (
    CommitteeMemoError,
    CommitteeMemoWorkflow,
    InMemoryCommitteeMemoRepository,
    SynthesisRequest,
)
from investment_research_os.evidence_bundles import AuthenticatedOperator
from investment_research_os.grader_executions import (
    GraderExecutionError,
    InMemoryBudgetLedger,
    ModelPriceCard,
    PromptContract,
    ProviderResponse,
    ProviderTransportError,
    ProviderUsage,
)
from investment_research_os.provider_input_token_preflight import (
    InputTokenPreflightReceipt,
    PersistentInputTokenPreflightGate,
)
from investment_research_os.providers import OpenAIInputTokenPreflight
from tests.test_five_grader_committee import completed_committee_fixture
from tests.test_grader_execution_workflow import (
    FakeProvider,
    approved_request,
)


class SynthesisPreflightStoreFake:
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


class PreflightSynthesisProvider(FakeProvider):
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
            input_tokens=100,
            input_token_cap=request.input_token_cap,
            within_cap=True,
            raw_provider_response={
                "object": "response.input_tokens",
                "input_tokens": 100,
            },
        )

    def execute(self, request):
        self.events.append("generation")
        return super().execute(request)


def approved_synthesis_request(committee) -> SynthesisRequest:
    grader_request = approved_request(committee.evidence_bundle_id)
    model = replace(
        grader_request.model,
        config_id=("biotech_committee_synthesizer_gpt_5_6_sol_medium_v1"),
        config_version=("biotech_committee_synthesizer_gpt_5_6_sol_medium_v1"),
        provider="openai",
        model="gpt-5.6-sol",
    )
    return SynthesisRequest(
        committee_id=committee.committee_id,
        calculation_ids=(),
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
            evaluation_corpus_id="biotech_committee_offline_v1",
            evaluation_corpus_version="biotech_committee_offline_v1",
            evaluation_corpus_sha256=(
                "54336b11da0e63fa433c8434def8bc3b710d008a75b85dc1ff8ad7ca6252cf4f"
            ),
            evaluation_identity_sha256=(
                "ba8eb4f564d729c16221f480b7fa021b1c66888a65d9038e337bbff29b0196c3"
            ),
        ),
        model=model,
        price_card=ModelPriceCard(
            price_card_id="gpt_5_6_sol_usd.v1",
            provider=model.provider,
            model=model.model,
            currency="USD",
            input_per_million=Decimal("1.00"),
            cached_input_per_million=Decimal("0.10"),
            cache_write_per_million=Decimal("0"),
            output_per_million=Decimal("2.00"),
            effective_from=datetime(2026, 7, 1, tzinfo=UTC),
            effective_to=None,
            verified_at=datetime(2026, 7, 22, tzinfo=UTC),
        ),
        policy=grader_request.policy,
    )


def valid_memo_output(committee) -> dict[str, object]:
    results = committee.grader_results
    opinions = [item.opinion for item in results if item.opinion is not None]
    opinion_ids = [item.opinion_id for item in opinions]
    first_claim = next(
        claim for opinion in opinions for claim in opinion.material_claims
    )
    evidence_id = first_claim.evidence_ids[0]
    statements = [
        {
            "statement_id": "fact-1",
            "text": first_claim.claim,
            "provenance_type": "fact",
            "evidence_ids": [evidence_id],
            "opinion_ids": [],
            "calculation_ids": [],
        },
        {
            "statement_id": "common-ground-1",
            "text": "Moonshot and Catalyst graders support continued research.",
            "provenance_type": "synthesis_interpretation",
            "evidence_ids": [],
            "opinion_ids": opinion_ids[:2],
            "calculation_ids": [],
        },
        {
            "statement_id": "gap-1",
            "text": "Controlled clinical evidence remains limited.",
            "provenance_type": "gap",
            "evidence_ids": [],
            "opinion_ids": [opinion_ids[2]],
            "calculation_ids": [],
        },
        {
            "statement_id": "invalidation-1",
            "text": "Lead programme failure would invalidate core case.",
            "provenance_type": "grader_interpretation",
            "evidence_ids": [],
            "opinion_ids": [opinion_ids[0]],
            "calculation_ids": [],
        },
        {
            "statement_id": "next-evidence-1",
            "text": "Obtain controlled clinical readout.",
            "provenance_type": "gap",
            "evidence_ids": [],
            "opinion_ids": [opinion_ids[2]],
            "calculation_ids": [],
        },
        {
            "statement_id": "review-trigger-1",
            "text": "Review when controlled clinical data publishes.",
            "provenance_type": "gap",
            "evidence_ids": [],
            "opinion_ids": [opinion_ids[2]],
            "calculation_ids": [],
        },
    ]
    return {
        "requested_disposition": "deep_research",
        "executive_summary_statement_ids": ["fact-1", "common-ground-1"],
        "statements": statements,
        "common_ground_statement_ids": ["common-ground-1"],
        "disagreement_records": [],
        "disputed_assumption_statement_ids": [],
        "evidence_gap_statement_ids": ["gap-1"],
        "invalidation_statement_ids": ["invalidation-1"],
        "required_next_evidence_statement_ids": ["next-evidence-1"],
        "review_trigger": {
            "trigger_type": "evidence_event",
            "review_at": None,
            "statement_id": "review-trigger-1",
        },
        "state_disclosure": [
            {
                "grader_id": item.grader_id,
                "execution_state": item.execution_state,
                "opinion_id": (
                    item.opinion.opinion_id if item.opinion is not None else None
                ),
                "stance": item.stance,
            }
            for item in results
        ],
    }


class CommitteeMemoWorkflowTests(unittest.TestCase):
    def test_synthesizer_requires_persisted_preflight_before_generation(
        self,
    ) -> None:
        bundle, committee, bundle_repository, committee_repository = (
            completed_committee_fixture()
        )
        events: list[str] = []
        provider = PreflightSynthesisProvider(
            (
                ProviderResponse(
                    provider_request_id="fake-synthesis-response",
                    raw_output=valid_memo_output(committee),
                    usage=ProviderUsage(100, 0, 50, 10, 150),
                    resolved_model="gpt-5.6-sol",
                    system_fingerprint="offline-synthesis-fingerprint-v1",
                ),
            ),
            events,
        )
        now = datetime(2026, 7, 22, 4, 0, tzinfo=UTC)

        execution = CommitteeMemoWorkflow(
            committee_repository=committee_repository,
            evidence_bundle_repository=bundle_repository,
            memo_repository=InMemoryCommitteeMemoRepository(),
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("2.00")),
            provider=provider,
            input_token_preflight_gate=PersistentInputTokenPreflightGate(
                store=SynthesisPreflightStoreFake(events),
                clock=lambda: now,
            ),
            clock=lambda: now,
        ).execute(
            AuthenticatedOperator(bundle.operator_id),
            approved_synthesis_request(committee),
        )

        self.assertEqual(execution.execution_state, "accepted")
        self.assertEqual(
            events,
            [
                "preflight_request_persisted",
                "input_tokens_counted",
                "preflight_result_persisted",
                "generation",
            ],
        )

    def test_synthesis_rejects_provider_model_drift_after_bounded_retry(
        self,
    ) -> None:
        bundle, committee, bundle_repository, committee_repository = (
            completed_committee_fixture()
        )
        drifted = ProviderResponse(
            provider_request_id="fake-synthesis-model-drift",
            raw_output=valid_memo_output(committee),
            usage=ProviderUsage(2000, 500, 500, 100, 2500),
            resolved_model="moving-provider-alias",
            system_fingerprint="offline-synthesis-fingerprint-v1",
        )
        provider = FakeProvider((drifted, drifted))
        times = iter(
            datetime(2026, 7, 22, 4, minute, tzinfo=UTC) for minute in range(10)
        )

        execution = CommitteeMemoWorkflow(
            committee_repository=committee_repository,
            evidence_bundle_repository=bundle_repository,
            memo_repository=InMemoryCommitteeMemoRepository(),
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("2.00")),
            provider=provider,
            clock=lambda: next(times),
        ).execute(
            AuthenticatedOperator(bundle.operator_id),
            approved_synthesis_request(committee),
        )

        self.assertEqual(execution.execution_state, "failed")
        self.assertEqual(len(execution.attempts), 2)
        self.assertEqual(
            execution.attempts[-1].validation_errors,
            ("provider_model_mismatch",),
        )

    def test_synthesis_transport_failure_retries_same_logical_input(
        self,
    ) -> None:
        bundle, committee, bundle_repository, committee_repository = (
            completed_committee_fixture()
        )
        response = ProviderResponse(
            provider_request_id="fake-synthesis-after-timeout",
            raw_output=valid_memo_output(committee),
            usage=ProviderUsage(2000, 500, 500, 100, 2500),
            resolved_model="gpt-5.6-sol",
            system_fingerprint="offline-synthesis-fingerprint-v1",
        )
        provider = FakeProvider(
            (
                ProviderTransportError("provider_timeout"),
                response,
            )
        )
        repository = InMemoryCommitteeMemoRepository()
        times = iter(
            datetime(2026, 7, 22, 4, minute, tzinfo=UTC) for minute in range(8)
        )

        execution = CommitteeMemoWorkflow(
            committee_repository=committee_repository,
            evidence_bundle_repository=bundle_repository,
            memo_repository=repository,
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("2.00")),
            provider=provider,
            clock=lambda: next(times),
        ).execute(
            AuthenticatedOperator(bundle.operator_id),
            approved_synthesis_request(committee),
        )

        self.assertEqual(execution.execution_state, "accepted")
        self.assertEqual(len(execution.attempts), 2)
        self.assertEqual(
            execution.attempts[0].validation_errors,
            ("provider_timeout",),
        )
        self.assertEqual(
            execution.memo.as_dict()["execution_metadata"]["attempts"][0]["result"],
            "transport_error",
        )
        self.assertEqual(
            provider.requests[0].logical_input,
            provider.requests[1].logical_input,
        )
        first_raw = repository.read_raw_attempt(
            bundle.operator_id,
            execution.attempts[0].attempt_id,
            audit_authorized=True,
        )
        self.assertIsNone(first_raw["response"])

    def test_synthesis_nonretryable_provider_error_stops_after_one_attempt(
        self,
    ) -> None:
        bundle, committee, bundle_repository, committee_repository = (
            completed_committee_fixture()
        )
        provider = FakeProvider(
            (
                ProviderTransportError(
                    "openai_response_refusal",
                    retryable=False,
                    category="refusal",
                ),
            )
        )
        times = iter(
            datetime(2026, 7, 22, 4, minute, tzinfo=UTC) for minute in range(5)
        )

        execution = CommitteeMemoWorkflow(
            committee_repository=committee_repository,
            evidence_bundle_repository=bundle_repository,
            memo_repository=InMemoryCommitteeMemoRepository(),
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("2.00")),
            provider=provider,
            clock=lambda: next(times),
        ).execute(
            AuthenticatedOperator(bundle.operator_id),
            approved_synthesis_request(committee),
        )

        self.assertEqual(execution.execution_state, "failed")
        self.assertEqual(len(execution.attempts), 1)
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(
            execution.attempts[0].validation_errors,
            ("openai_response_refusal",),
        )

    def test_cache_write_tokens_replace_ordinary_uncached_input_pricing(
        self,
    ) -> None:
        bundle, committee, bundle_repository, committee_repository = (
            completed_committee_fixture()
        )
        request = approved_synthesis_request(committee)
        request = replace(
            request,
            price_card=replace(
                request.price_card,
                cache_write_per_million=Decimal("3.00"),
            ),
        )
        response = ProviderResponse(
            provider_request_id="fake-synthesis-cache-write",
            raw_output=valid_memo_output(committee),
            usage=ProviderUsage(
                input_tokens=2000,
                cached_input_tokens=500,
                cache_write_tokens=700,
                output_tokens=500,
                reasoning_tokens=100,
                total_tokens=2500,
            ),
            resolved_model=request.model.model,
            system_fingerprint="offline-synthesis-fingerprint-v1",
        )
        budget = InMemoryBudgetLedger(hard_limit_usd=Decimal("2.00"))
        times = iter(
            datetime(2026, 7, 22, 4, minute, tzinfo=UTC) for minute in range(4)
        )

        execution = CommitteeMemoWorkflow(
            committee_repository=committee_repository,
            evidence_bundle_repository=bundle_repository,
            memo_repository=InMemoryCommitteeMemoRepository(),
            budget_ledger=budget,
            provider=FakeProvider((response,)),
            clock=lambda: next(times),
        ).execute(AuthenticatedOperator(bundle.operator_id), request)

        self.assertEqual(budget.reconciled_usd, Decimal("0.00395"))
        self.assertEqual(execution.memo.estimated_cost_usd, "0.00395")
        self.assertEqual(
            execution.memo.as_dict()["execution_metadata"]["cache_write_tokens"],
            700,
        )

    def test_invalid_cache_token_partition_is_rejected_before_costing(
        self,
    ) -> None:
        bundle, committee, bundle_repository, committee_repository = (
            completed_committee_fixture()
        )
        request = approved_synthesis_request(committee)
        invalid_response = ProviderResponse(
            provider_request_id="fake-synthesis-invalid-cache-partition",
            raw_output=valid_memo_output(committee),
            usage=ProviderUsage(
                input_tokens=1000,
                cached_input_tokens=600,
                cache_write_tokens=500,
                output_tokens=300,
                reasoning_tokens=100,
                total_tokens=1300,
            ),
            resolved_model=request.model.model,
            system_fingerprint="offline-synthesis-fingerprint-v1",
        )
        budget = InMemoryBudgetLedger(hard_limit_usd=Decimal("2.00"))
        times = iter(
            datetime(2026, 7, 22, 4, minute, tzinfo=UTC) for minute in range(8)
        )

        execution = CommitteeMemoWorkflow(
            committee_repository=committee_repository,
            evidence_bundle_repository=bundle_repository,
            memo_repository=InMemoryCommitteeMemoRepository(),
            budget_ledger=budget,
            provider=FakeProvider((invalid_response, invalid_response)),
            clock=lambda: next(times),
        ).execute(AuthenticatedOperator(bundle.operator_id), request)

        self.assertEqual(execution.execution_state, "failed")
        self.assertEqual(len(execution.attempts), 2)
        self.assertEqual(
            execution.attempts[-1].validation_errors,
            ("invalid_provider_usage",),
        )
        self.assertEqual(budget.reconciled_usd, Decimal("0"))
        self.assertEqual(budget.reserved_usd, Decimal("0"))

    def test_reservation_uses_highest_input_category_rate_once_per_token(
        self,
    ) -> None:
        bundle, committee, bundle_repository, committee_repository = (
            completed_committee_fixture()
        )
        request = approved_synthesis_request(committee)
        request = replace(
            request,
            price_card=replace(
                request.price_card,
                cache_write_per_million=Decimal("3.00"),
            ),
        )
        provider = FakeProvider(())
        workflow = CommitteeMemoWorkflow(
            committee_repository=committee_repository,
            evidence_bundle_repository=bundle_repository,
            memo_repository=InMemoryCommitteeMemoRepository(),
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("0.03")),
            provider=provider,
            clock=lambda: datetime(2026, 7, 22, 4, 0, tzinfo=UTC),
        )

        with self.assertRaisesRegex(
            GraderExecutionError,
            "hard budget unavailable",
        ):
            workflow.execute(AuthenticatedOperator(bundle.operator_id), request)

        self.assertEqual(provider.requests, [])

    def test_production_price_card_without_expiry_fails_before_provider(
        self,
    ) -> None:
        bundle, committee, bundle_repository, committee_repository = (
            completed_committee_fixture()
        )
        request = approved_synthesis_request(committee)
        request = replace(
            request,
            model=replace(request.model, environment="production"),
            policy=replace(
                request.policy,
                required_environment="production",
            ),
        )
        provider = FakeProvider(())
        budget = InMemoryBudgetLedger(hard_limit_usd=Decimal("2.00"))
        workflow = CommitteeMemoWorkflow(
            committee_repository=committee_repository,
            evidence_bundle_repository=bundle_repository,
            memo_repository=InMemoryCommitteeMemoRepository(),
            budget_ledger=budget,
            provider=provider,
            clock=lambda: datetime(2026, 7, 22, 4, 0, tzinfo=UTC),
        )

        with self.assertRaisesRegex(
            CommitteeMemoError,
            "synthesis price card invalid",
        ):
            workflow.execute(AuthenticatedOperator(bundle.operator_id), request)

        self.assertEqual(provider.requests, [])
        self.assertEqual(budget.reserved_usd, Decimal("0"))

    def test_production_prompt_without_content_hash_fails_before_provider(
        self,
    ) -> None:
        bundle, committee, bundle_repository, committee_repository = (
            completed_committee_fixture()
        )
        checked_at = datetime(2026, 7, 22, 4, 0, tzinfo=UTC)
        request = approved_synthesis_request(committee)
        request = replace(
            request,
            prompt=replace(request.prompt, content_sha256=""),
            model=replace(request.model, environment="production"),
            policy=replace(
                request.policy,
                required_environment="production",
            ),
            price_card=replace(
                request.price_card,
                effective_to=datetime(2026, 8, 21, tzinfo=UTC),
            ),
        )
        provider = FakeProvider(())

        with self.assertRaisesRegex(
            CommitteeMemoError,
            "synthesis prompt content hash invalid",
        ):
            CommitteeMemoWorkflow(
                committee_repository=committee_repository,
                evidence_bundle_repository=bundle_repository,
                memo_repository=InMemoryCommitteeMemoRepository(),
                budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("2.00")),
                provider=provider,
                clock=lambda: checked_at,
            ).execute(AuthenticatedOperator(bundle.operator_id), request)

        self.assertEqual(provider.requests, [])

    def test_production_prompt_without_corpus_identity_fails_before_provider(
        self,
    ) -> None:
        bundle, committee, bundle_repository, committee_repository = (
            completed_committee_fixture()
        )
        checked_at = datetime(2026, 7, 22, 4, 0, tzinfo=UTC)
        request = approved_synthesis_request(committee)
        request = replace(
            request,
            prompt=replace(
                request.prompt,
                content_sha256="a" * 64,
                evaluation_corpus_sha256="",
                evaluation_identity_sha256="",
            ),
            model=replace(request.model, environment="production"),
            policy=replace(
                request.policy,
                required_environment="production",
            ),
            price_card=replace(
                request.price_card,
                effective_to=datetime(2026, 8, 21, tzinfo=UTC),
            ),
        )
        provider = FakeProvider(())

        with self.assertRaisesRegex(
            CommitteeMemoError,
            "synthesis prompt evaluation identity invalid",
        ):
            CommitteeMemoWorkflow(
                committee_repository=committee_repository,
                evidence_bundle_repository=bundle_repository,
                memo_repository=InMemoryCommitteeMemoRepository(),
                budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("2.00")),
                provider=provider,
                clock=lambda: checked_at,
            ).execute(AuthenticatedOperator(bundle.operator_id), request)

        self.assertEqual(provider.requests, [])

    def test_production_prompt_drift_invalidates_evaluation_identity(
        self,
    ) -> None:
        bundle, committee, bundle_repository, committee_repository = (
            completed_committee_fixture()
        )
        checked_at = datetime(2026, 7, 22, 4, 0, tzinfo=UTC)
        request = approved_synthesis_request(committee)
        request = replace(
            request,
            prompt=replace(request.prompt, content_sha256="d" * 64),
            model=replace(request.model, environment="production"),
            policy=replace(
                request.policy,
                required_environment="production",
            ),
            price_card=replace(
                request.price_card,
                effective_to=datetime(2026, 8, 21, tzinfo=UTC),
            ),
        )
        provider = FakeProvider(())

        with self.assertRaisesRegex(
            CommitteeMemoError,
            "synthesis prompt evaluation identity mismatch",
        ):
            CommitteeMemoWorkflow(
                committee_repository=committee_repository,
                evidence_bundle_repository=bundle_repository,
                memo_repository=InMemoryCommitteeMemoRepository(),
                budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("2.00")),
                provider=provider,
                clock=lambda: checked_at,
            ).execute(AuthenticatedOperator(bundle.operator_id), request)

        self.assertEqual(provider.requests, [])

    def test_stale_production_price_card_fails_before_provider(self) -> None:
        bundle, committee, bundle_repository, committee_repository = (
            completed_committee_fixture()
        )
        request = approved_synthesis_request(committee)
        request = replace(
            request,
            model=replace(request.model, environment="production"),
            policy=replace(
                request.policy,
                required_environment="production",
            ),
            price_card=replace(
                request.price_card,
                effective_to=datetime(2026, 8, 31, tzinfo=UTC),
                verified_at=datetime(2026, 6, 1, tzinfo=UTC),
            ),
        )
        provider = FakeProvider(())

        with self.assertRaisesRegex(
            CommitteeMemoError,
            "synthesis price card invalid",
        ):
            CommitteeMemoWorkflow(
                committee_repository=committee_repository,
                evidence_bundle_repository=bundle_repository,
                memo_repository=InMemoryCommitteeMemoRepository(),
                budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("2.00")),
                provider=provider,
                clock=lambda: datetime(2026, 7, 22, 4, 0, tzinfo=UTC),
            ).execute(AuthenticatedOperator(bundle.operator_id), request)

        self.assertEqual(provider.requests, [])

    def test_negative_cache_write_rate_fails_before_provider(self) -> None:
        bundle, committee, bundle_repository, committee_repository = (
            completed_committee_fixture()
        )
        request = approved_synthesis_request(committee)
        request = replace(
            request,
            price_card=replace(
                request.price_card,
                cache_write_per_million=Decimal("-0.01"),
            ),
        )
        provider = FakeProvider(())

        with self.assertRaisesRegex(
            CommitteeMemoError,
            "synthesis price card invalid",
        ):
            CommitteeMemoWorkflow(
                committee_repository=committee_repository,
                evidence_bundle_repository=bundle_repository,
                memo_repository=InMemoryCommitteeMemoRepository(),
                budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("2.00")),
                provider=provider,
                clock=lambda: datetime(2026, 7, 22, 4, 0, tzinfo=UTC),
            ).execute(AuthenticatedOperator(bundle.operator_id), request)

        self.assertEqual(provider.requests, [])

    def test_raw_provider_payload_is_sanitized_and_audit_restricted(
        self,
    ) -> None:
        repository = InMemoryCommitteeMemoRepository()
        repository.begin_raw_attempt(
            "10000000-0000-4000-8000-000000000001",
            "attempt-1",
            {
                "provider": "openai",
                "reasoning_content": "private chain of thought",
            },
        )
        repository.finish_raw_attempt(
            "10000000-0000-4000-8000-000000000001",
            "attempt-1",
            {
                "requested_disposition": "monitor",
                "reasoning_content": "private chain of thought",
            },
        )

        with self.assertRaisesRegex(
            CommitteeMemoError,
            "raw provider payload audit denied",
        ):
            repository.read_raw_attempt(
                "10000000-0000-4000-8000-000000000001",
                "attempt-1",
                audit_authorized=False,
            )
        self.assertEqual(
            repository.read_raw_attempt(
                "10000000-0000-4000-8000-000000000001",
                "attempt-1",
                audit_authorized=True,
            ),
            {
                "request": {"provider": "openai"},
                "response": {"requested_disposition": "monitor"},
            },
        )

    def test_valid_persisted_committee_produces_retrievable_typed_memo(
        self,
    ) -> None:
        bundle, committee, bundle_repository, committee_repository = (
            completed_committee_fixture()
        )
        request = approved_synthesis_request(committee)
        response = ProviderResponse(
            provider_request_id="fake-synthesis-1",
            raw_output=valid_memo_output(committee),
            usage=ProviderUsage(2000, 500, 500, 100, 2500),
            resolved_model=request.model.model,
            system_fingerprint="offline-synthesis-fingerprint-v1",
        )
        repository = InMemoryCommitteeMemoRepository()
        times = iter(
            datetime(2026, 7, 22, 4, minute, tzinfo=UTC) for minute in range(4)
        )
        workflow = CommitteeMemoWorkflow(
            committee_repository=committee_repository,
            evidence_bundle_repository=bundle_repository,
            memo_repository=repository,
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("2.00")),
            provider=FakeProvider((response,)),
            clock=lambda: next(times),
        )

        execution = workflow.execute(
            AuthenticatedOperator(bundle.operator_id),
            request,
        )

        self.assertEqual(execution.execution_state, "accepted")
        self.assertEqual(execution.memo.committee_id, committee.committee_id)
        self.assertEqual(execution.memo.evidence_bundle_hash, bundle.content_hash)
        self.assertEqual(execution.memo.requested_disposition, "deep_research")
        self.assertEqual(
            repository.get_for_committee(
                bundle.operator_id,
                committee.committee_id,
            ),
            execution,
        )
        payload = {
            "value": execution.memo.as_dict(),
            "context": {
                "committeeId": committee.committee_id,
                "researchRunId": committee.research_run_id,
                "evidenceBundleId": bundle.id,
                "evidenceBundleHash": bundle.content_hash,
                "workflowConfigVersion": committee.workflow_config_version,
                "propositionId": committee.proposition_id,
                "propositionVersion": committee.proposition_version,
                "committeeStatus": committee.status,
                "evidenceIds": [item.evidence_id for item in bundle.manifest],
                "calculationIds": [],
                "graderResults": [
                    {
                        "graderId": item.grader_id,
                        "executionState": item.execution_state,
                        "opinionId": item.opinion.opinion_id,
                        "stance": item.stance,
                    }
                    for item in committee.grader_results
                ],
            },
        }
        result = subprocess.run(
            [
                "node",
                "--experimental-strip-types",
                "--input-type=module",
                "--eval",
                (
                    "import { parseCommitteeMemo } from "
                    "'./packages/types/committee-memo.ts';"
                    "let input=''; for await (const chunk of process.stdin) "
                    "input += chunk; const payload=JSON.parse(input); "
                    "parseCommitteeMemo(payload.value,payload.context);"
                ),
            ],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_disagreement_rejects_unknown_contributing_opinion(self) -> None:
        bundle, committee, bundle_repository, committee_repository = (
            completed_committee_fixture()
        )
        request = approved_synthesis_request(committee)
        output = valid_memo_output(committee)
        opinion_ids = [item.opinion.opinion_id for item in committee.grader_results]
        output["statements"].extend(
            (
                {
                    "statement_id": "disputed-question-1",
                    "text": "Can shareholders reach catalyst without dilution?",
                    "provenance_type": "synthesis_interpretation",
                    "evidence_ids": [],
                    "opinion_ids": opinion_ids[3:5],
                    "calculation_ids": [],
                },
                {
                    "statement_id": "position-risk-1",
                    "text": "Risk grader sees financing need as material.",
                    "provenance_type": "grader_interpretation",
                    "evidence_ids": [],
                    "opinion_ids": [opinion_ids[3]],
                    "calculation_ids": [],
                },
                {
                    "statement_id": "position-valuation-1",
                    "text": "Valuation grader models dilution sensitivity.",
                    "provenance_type": "grader_interpretation",
                    "evidence_ids": [],
                    "opinion_ids": [opinion_ids[4]],
                    "calculation_ids": [],
                },
                {
                    "statement_id": "resolve-dispute-1",
                    "text": "Obtain updated financing terms.",
                    "provenance_type": "gap",
                    "evidence_ids": [],
                    "opinion_ids": opinion_ids[3:5],
                    "calculation_ids": [],
                },
            )
        )
        output["disagreement_records"] = [
            {
                "disagreement_id": "dilution-disagreement-1",
                "disputed_question_statement_id": "disputed-question-1",
                "position_statement_ids": [
                    "position-risk-1",
                    "position-valuation-1",
                ],
                "contributing_opinion_ids": [
                    opinion_ids[3],
                    "00000000-0000-4000-8000-000000000000",
                ],
                "affects_disposition": True,
                "resolving_evidence_statement_ids": ["resolve-dispute-1"],
            }
        ]
        response = ProviderResponse(
            provider_request_id="fake-synthesis-invalid-disagreement",
            raw_output=output,
            usage=ProviderUsage(2000, 500, 500, 100, 2500),
            resolved_model=request.model.model,
            system_fingerprint="offline-synthesis-fingerprint-v1",
        )
        times = iter(
            datetime(2026, 7, 22, 4, minute, tzinfo=UTC) for minute in range(4)
        )
        workflow = CommitteeMemoWorkflow(
            committee_repository=committee_repository,
            evidence_bundle_repository=bundle_repository,
            memo_repository=InMemoryCommitteeMemoRepository(),
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("2.00")),
            provider=FakeProvider((response, response)),
            clock=lambda: next(times),
        )

        execution = workflow.execute(
            AuthenticatedOperator(bundle.operator_id),
            request,
        )

        self.assertEqual(execution.execution_state, "failed")
        self.assertIsNone(execution.memo)
        self.assertEqual(len(execution.attempts), 2)
        self.assertEqual(
            execution.attempts[-1].validation_errors,
            ("invalid_memo_opinion_reference",),
        )

    def test_memo_rejects_target_price_hidden_inside_statement_text(self) -> None:
        bundle, committee, bundle_repository, committee_repository = (
            completed_committee_fixture()
        )
        request = approved_synthesis_request(committee)
        output = valid_memo_output(committee)
        output["statements"][0]["text"] = "Target price is USD 12 per share."
        response = ProviderResponse(
            provider_request_id="fake-synthesis-prohibited-output",
            raw_output=output,
            usage=ProviderUsage(2000, 500, 500, 100, 2500),
            resolved_model=request.model.model,
            system_fingerprint="offline-synthesis-fingerprint-v1",
        )
        times = iter(
            datetime(2026, 7, 22, 4, minute, tzinfo=UTC) for minute in range(4)
        )
        workflow = CommitteeMemoWorkflow(
            committee_repository=committee_repository,
            evidence_bundle_repository=bundle_repository,
            memo_repository=InMemoryCommitteeMemoRepository(),
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("2.00")),
            provider=FakeProvider((response, response)),
            clock=lambda: next(times),
        )

        execution = workflow.execute(
            AuthenticatedOperator(bundle.operator_id),
            request,
        )

        self.assertEqual(execution.execution_state, "failed")
        self.assertIsNone(execution.memo)
        self.assertEqual(
            execution.attempts[-1].validation_errors,
            ("prohibited_memo_output",),
        )

    def test_hidden_grader_state_and_invented_calculation_are_rejected(
        self,
    ) -> None:
        bundle, committee, bundle_repository, committee_repository = (
            completed_committee_fixture()
        )
        request = approved_synthesis_request(committee)
        hidden_state = valid_memo_output(committee)
        hidden_state["state_disclosure"].pop()
        invented_calculation = valid_memo_output(committee)
        invented_calculation["statements"][0]["calculation_ids"] = [
            "invented-calculation"
        ]
        provider = FakeProvider(
            (
                ProviderResponse(
                    provider_request_id="fake-synthesis-hidden-state",
                    raw_output=hidden_state,
                    usage=ProviderUsage(2000, 500, 500, 100, 2500),
                    resolved_model=request.model.model,
                    system_fingerprint="offline-synthesis-fingerprint-v1",
                ),
                ProviderResponse(
                    provider_request_id="fake-synthesis-invented-calculation",
                    raw_output=invented_calculation,
                    usage=ProviderUsage(2000, 500, 500, 100, 2500),
                    resolved_model=request.model.model,
                    system_fingerprint="offline-synthesis-fingerprint-v1",
                ),
            )
        )
        times = iter(
            datetime(2026, 7, 22, 4, minute, tzinfo=UTC) for minute in range(4)
        )
        workflow = CommitteeMemoWorkflow(
            committee_repository=committee_repository,
            evidence_bundle_repository=bundle_repository,
            memo_repository=InMemoryCommitteeMemoRepository(),
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("2.00")),
            provider=provider,
            clock=lambda: next(times),
        )

        execution = workflow.execute(
            AuthenticatedOperator(bundle.operator_id),
            request,
        )

        self.assertEqual(execution.execution_state, "failed")
        self.assertIsNone(execution.memo)
        self.assertEqual(
            execution.attempts[0].validation_errors,
            ("state_disclosure_mismatch",),
        )
        self.assertEqual(
            execution.attempts[1].validation_errors,
            ("invalid_memo_provenance_reference",),
        )

    def test_validation_rejection_gets_one_bounded_repair_retry(self) -> None:
        bundle, committee, bundle_repository, committee_repository = (
            completed_committee_fixture()
        )
        request = approved_synthesis_request(committee)
        invalid = deepcopy(valid_memo_output(committee))
        invalid["statements"][0]["evidence_ids"] = [
            "00000000-0000-4000-8000-000000000000"
        ]
        valid = valid_memo_output(committee)
        provider = FakeProvider(
            (
                ProviderResponse(
                    provider_request_id="fake-synthesis-invalid",
                    raw_output=invalid,
                    usage=ProviderUsage(2000, 500, 500, 100, 2500),
                    resolved_model=request.model.model,
                    system_fingerprint="offline-synthesis-fingerprint-v1",
                ),
                ProviderResponse(
                    provider_request_id="fake-synthesis-repaired",
                    raw_output=valid,
                    usage=ProviderUsage(2000, 500, 500, 100, 2500),
                    resolved_model=request.model.model,
                    system_fingerprint="offline-synthesis-fingerprint-v1",
                ),
            )
        )
        times = iter(
            (
                datetime(2026, 7, 22, 4, 0, tzinfo=UTC),
                datetime(2026, 7, 22, 4, 1, tzinfo=UTC),
                datetime(2026, 7, 22, 4, 2, tzinfo=UTC),
                datetime(2026, 7, 22, 4, 3, tzinfo=UTC),
            )
        )
        workflow = CommitteeMemoWorkflow(
            committee_repository=committee_repository,
            evidence_bundle_repository=bundle_repository,
            memo_repository=InMemoryCommitteeMemoRepository(),
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("2.00")),
            provider=provider,
            clock=lambda: next(times),
        )

        execution = workflow.execute(
            AuthenticatedOperator(bundle.operator_id),
            request,
        )

        self.assertEqual(execution.execution_state, "accepted")
        self.assertEqual(len(execution.attempts), 2)
        self.assertEqual(
            execution.attempts[0].validation_errors,
            ("invalid_memo_provenance_reference",),
        )
        self.assertEqual(
            provider.requests[0].logical_input,
            provider.requests[1].logical_input,
        )
        self.assertEqual(
            provider.requests[1].validation_errors,
            ("invalid_memo_provenance_reference",),
        )

    def test_identical_synthesis_request_reuses_validated_memo(self) -> None:
        bundle, committee, bundle_repository, committee_repository = (
            completed_committee_fixture()
        )
        request = approved_synthesis_request(committee)
        provider = FakeProvider(
            (
                ProviderResponse(
                    provider_request_id="fake-synthesis-1",
                    raw_output=valid_memo_output(committee),
                    usage=ProviderUsage(2000, 500, 500, 100, 2500),
                    resolved_model=request.model.model,
                    system_fingerprint="offline-synthesis-fingerprint-v1",
                ),
            )
        )
        repository = InMemoryCommitteeMemoRepository()
        times = iter(
            (
                datetime(2026, 7, 22, 4, 0, tzinfo=UTC),
                datetime(2026, 7, 22, 4, 1, tzinfo=UTC),
            )
        )
        workflow = CommitteeMemoWorkflow(
            committee_repository=committee_repository,
            evidence_bundle_repository=bundle_repository,
            memo_repository=repository,
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("2.00")),
            provider=provider,
            clock=lambda: next(times),
        )

        first = workflow.execute(
            AuthenticatedOperator(bundle.operator_id),
            request,
        )
        second = workflow.execute(
            AuthenticatedOperator(bundle.operator_id),
            request,
        )

        self.assertIs(second, first)
        self.assertEqual(len(provider.requests), 1)


if __name__ == "__main__":
    unittest.main()

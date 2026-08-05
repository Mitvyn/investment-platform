from __future__ import annotations

import json
import subprocess
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from investment_research_os.evidence_bundles import (
    AuthenticatedOperator,
    InMemoryEvidenceBundleRepository,
)
from investment_research_os.grader_executions import (
    BudgetLedger,
    ExecutionPolicy,
    GraderContract,
    GraderExecutionRepository,
    GraderExecutionRequest,
    GraderExecutionError,
    GraderExecutionWorkflow,
    InMemoryBudgetLedger,
    InMemoryGraderExecutionRepository,
    ModelConfiguration,
    ModelPriceCard,
    PromptContract,
    ProviderTransportError,
    ProviderResponse,
    ProviderUsage,
)
from investment_research_os.valuation_snapshots import (
    InMemoryValuationSnapshotRepository,
    ValuationSnapshotWorkflow,
)
from tests.test_evidence_bundle_storage import materialized_bundle
from tests.test_valuation_snapshot_workflow import (
    FixedCalendar,
    FixedValuationSource,
    input_candidate,
)


class FakeProvider:
    def __init__(
        self,
        responses: tuple[ProviderResponse | Exception, ...],
    ) -> None:
        self._responses = iter(responses)
        self.requests = []

    def audit_request(self, request):
        return request.as_dict()

    def execute(self, request):
        self.requests.append(request)
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response


def aligned_valuation_repository(bundle):
    bundle_repository = InMemoryEvidenceBundleRepository()
    bundle_repository.save(bundle)
    repository = InMemoryValuationSnapshotRepository()
    snapshot = ValuationSnapshotWorkflow(
        evidence_bundle_repository=bundle_repository,
        valuation_snapshot_repository=repository,
        market_calendar=FixedCalendar(),
        input_source=FixedValuationSource(input_candidate()),
        clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
    ).materialize(AuthenticatedOperator(bundle.operator_id), bundle.id)
    return repository, snapshot


def approved_request(bundle_id: str) -> GraderExecutionRequest:
    return GraderExecutionRequest(
        evidence_bundle_id=bundle_id,
        question_type_id="biotech_moonshot_catalyst_assessment",
        question_type_version="biotech_moonshot_catalyst_assessment.v1",
        workflow_config_version="biotech-moonshot-catalyst-v1",
        proposition_id="biotech_moonshot_catalyst_case",
        proposition_version="biotech_moonshot_catalyst_case.v1",
        rendered_proposition=(
            "As of the cutoff, the available evidence supports a credible "
            "Moonshot research case with an identifiable catalyst capable of "
            "materially resolving uncertainty."
        ),
        grader=GraderContract(
            grader_id="moonshot",
            grader_version="moonshot-grader-v1",
            grader_contract_version="moonshot-grader-contract-v1",
            owned_decision_question=("Is the opportunity meaningfully asymmetric?"),
            eligibility_rule_version="moonshot-eligibility-v1",
            rubric_version="moonshot-rubric-v1",
            output_schema_version="moonshot_grader_payload.v1",
            abstention_rule_version="moonshot-abstention-v1",
            required=True,
            eligible=True,
        ),
        prompt=PromptContract(
            prompt_id="moonshot_grader_v1",
            prompt_version="moonshot_grader_v1",
            input_schema_version="grader-input-v1",
            output_schema_version="moonshot_grader_payload.v1",
            active=True,
            evaluation_passed=True,
            content_sha256=(
                "c44aff2da6de9cd8f74a24d48a65754bd703f4db5ff3596b56c29691ec78205b"
            ),
            evaluation_corpus_id="biotech_committee_offline_v1",
            evaluation_corpus_version="biotech_committee_offline_v1",
            evaluation_corpus_sha256=(
                "54336b11da0e63fa433c8434def8bc3b710d008a75b85dc1ff8ad7ca6252cf4f"
            ),
            evaluation_identity_sha256=(
                "a69c01fec86076d113d5cb7e7441ef53d700296dc9a945f9cc915840938e3991"
            ),
        ),
        model=ModelConfiguration(
            config_id=("biotech_committee_graders_openai_sol_medium_v1"),
            config_version=("biotech_committee_graders_openai_sol_medium_v1"),
            provider="openai",
            model="gpt-5.6-sol",
            reasoning_effort="medium",
            thinking_enabled=True,
            temperature="0",
            input_token_cap=16000,
            output_token_cap=2000,
            active=True,
            evaluation_passed=True,
            retention_approved=True,
            source_processing_approved=True,
            environment="test",
        ),
        price_card=ModelPriceCard(
            price_card_id="gpt_5_6_sol_usd.v1",
            provider="openai",
            model="gpt-5.6-sol",
            currency="USD",
            input_per_million=Decimal("1.00"),
            cached_input_per_million=Decimal("0.10"),
            cache_write_per_million=Decimal("0"),
            output_per_million=Decimal("2.00"),
            effective_from=datetime(2026, 7, 1, tzinfo=UTC),
            effective_to=None,
            verified_at=datetime(2026, 7, 21, tzinfo=UTC),
        ),
        policy=ExecutionPolicy(
            policy_version="grader-execution-policy-v1",
            retry_policy_version="grader-retry-policy-v1",
            budget_policy_version="research-budget-policy-v1",
            max_attempts=2,
            required_environment="test",
        ),
    )


def accepted_output(evidence_id: str) -> dict[str, object]:
    return {
        "execution_state": "accepted",
        "grader_id": "moonshot",
        "grader_version": "moonshot-grader-v1",
        "owned_decision_question": "Is the opportunity meaningfully asymmetric?",
        "stance": "supports",
        "confidence": "medium",
        "summary": "Opportunity is asymmetric enough for continued research.",
        "material_claims": [
            {
                "claim_id": "moonshot-claim-1",
                "claim": "Platform evidence supports meaningful upside scope.",
                "materiality": "high",
                "evidence_ids": [evidence_id],
            }
        ],
        "assumptions": ["Clinical translation remains uncertain."],
        "contradicting_evidence": [],
        "evidence_gaps": [
            {
                "gap_id": "moonshot-gap-1",
                "description": "Independent clinical replication is unavailable.",
                "required_evidence": "Independent clinical replication.",
            }
        ],
        "invalidation_signals": ["Lead programme fails to translate."],
        "proposition": {
            "proposition_id": "biotech_moonshot_catalyst_case",
            "proposition_version": "biotech_moonshot_catalyst_case.v1",
            "rendered_proposition_text": (
                "As of the cutoff, the available evidence supports a credible "
                "Moonshot research case with an identifiable catalyst capable of "
                "materially resolving uncertainty."
            ),
            "grader_stance": "supports",
            "stance_rationale": "Platform scope supports continued research.",
        },
        "abstention": None,
        "moonshot_payload": {
            "contract_version": "moonshot_grader_payload.v1",
            "mission_relevance": "material",
            "asymmetry_assessment": "credible",
            "asymmetry_drivers": ["Platform reuse across programmes"],
            "evidence_maturity": "clinical",
            "strategic_or_societal_value": "material",
            "limiting_factors": ["Clinical translation remains uncertain."],
        },
    }


def abstained_output(evidence_id: str) -> dict[str, object]:
    output = accepted_output(evidence_id)
    output["execution_state"] = "abstained"
    output["stance"] = None
    output["proposition"]["grader_stance"] = None
    output["proposition"]["stance_rationale"] = None
    output["material_claims"] = []
    output["abstention"] = {
        "reason_code": "insufficient_clinical_evidence",
        "reason": "Clinical evidence maturity is insufficient.",
        "missing_or_inadequate_evidence": ["Controlled clinical efficacy data"],
        "evidence_required": ["Primary clinical results with endpoints"],
        "confidence": "high",
    }
    return output


def assert_typescript_contract(test, execution, bundle) -> None:
    payload = {
        "value": execution.as_dict(),
        "context": {
            "evidenceBundleId": bundle.id,
            "evidenceBundleHash": bundle.content_hash,
            "evidenceIds": [item.evidence_id for item in bundle.manifest],
        },
    }
    result = subprocess.run(
        [
            "node",
            "--experimental-strip-types",
            "--input-type=module",
            "--eval",
            (
                "import { parseGraderExecution } from "
                "'./packages/types/grader-execution.ts';"
                "let input=''; for await (const chunk of process.stdin) "
                "input += chunk; const payload=JSON.parse(input); "
                "parseGraderExecution(payload.value,payload.context);"
            ),
        ],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
    )
    test.assertEqual(result.returncode, 0, result.stderr)


class GraderExecutionWorkflowTests(unittest.TestCase):
    def test_in_memory_ports_satisfy_public_workflow_protocols(self) -> None:
        self.assertIsInstance(
            InMemoryGraderExecutionRepository(),
            GraderExecutionRepository,
        )
        self.assertIsInstance(
            InMemoryBudgetLedger(hard_limit_usd=Decimal("1.00")),
            BudgetLedger,
        )

    def test_raw_audit_strips_provider_reasoning_items(self) -> None:
        repository = InMemoryGraderExecutionRepository()
        operator_id = "10000000-0000-4000-8000-000000000001"
        attempt_id = "10000000-0000-4000-8000-000000000002"
        repository.begin_raw_attempt(
            operator_id,
            attempt_id,
            {"provider": "openai"},
        )
        repository.finish_raw_attempt(
            operator_id,
            attempt_id,
            {
                "id": "resp_123",
                "output": [
                    {
                        "type": "reasoning",
                        "encrypted_content": "private-reasoning",
                    },
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": '{"execution_state":"accepted"}',
                            }
                        ],
                    },
                ],
            },
        )

        audit = repository.read_raw_attempt(
            operator_id,
            attempt_id,
            audit_authorized=True,
        )

        self.assertEqual(
            audit["response"]["output"],
            [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": '{"execution_state":"accepted"}',
                        }
                    ],
                }
            ],
        )
        self.assertNotIn("encrypted_content", json.dumps(audit))

    def test_grader_receives_exact_frozen_passages_in_manifest_order(
        self,
    ) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        provider = FakeProvider(
            (
                ProviderResponse(
                    provider_request_id="fake-passage-input",
                    raw_output=accepted_output(bundle.manifest[0].evidence_id),
                    usage=ProviderUsage(1000, 200, 300, 100, 1300),
                    resolved_model="gpt-5.6-sol",
                    system_fingerprint="offline-fingerprint-v1",
                ),
            )
        )
        workflow = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=InMemoryGraderExecutionRepository(),
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("5.00")),
            provider=provider,
            clock=lambda: datetime(2026, 7, 22, 3, 0, tzinfo=UTC),
        )

        workflow.execute(
            AuthenticatedOperator(bundle.operator_id),
            approved_request(bundle.id),
        )

        passages = provider.requests[0].logical_input["evidence_passages"]
        self.assertEqual(
            [passage["evidence_id"] for passage in passages],
            [
                item.evidence_id
                for item in bundle.manifest
                if item.item_kind == "passage"
            ],
        )
        self.assertEqual(
            passages[0]["passage_text"],
            "exact liquidity passage",
        )
        self.assertEqual(
            passages[0]["passage_sha256"],
            bundle.manifest[0].passage_hash,
        )

    def test_missing_frozen_passage_content_blocks_provider_call(self) -> None:
        bundle = materialized_bundle()
        bundle = replace(
            bundle,
            manifest=tuple(
                replace(item, passage_text=None)
                if item.item_kind == "passage"
                else item
                for item in bundle.manifest
            ),
        )
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        provider = FakeProvider(
            (
                ProviderResponse(
                    provider_request_id="must-not-run",
                    raw_output=accepted_output(bundle.manifest[0].evidence_id),
                    usage=ProviderUsage(1000, 200, 300, 100, 1300),
                    resolved_model="gpt-5.6-sol",
                    system_fingerprint="offline-fingerprint-v1",
                ),
            )
        )

        execution = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=InMemoryGraderExecutionRepository(),
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("5.00")),
            provider=provider,
            clock=lambda: datetime(2026, 7, 22, 3, 0, tzinfo=UTC),
        ).execute(
            AuthenticatedOperator(bundle.operator_id),
            approved_request(bundle.id),
        )

        self.assertEqual(execution.execution_state, "not_executed")
        self.assertIn(
            "evidence_passage_content_unavailable",
            execution.blocking_reasons,
        )
        self.assertEqual(provider.requests, [])

    def test_mismatched_frozen_passage_hash_blocks_provider_call(self) -> None:
        bundle = materialized_bundle()
        bundle = replace(
            bundle,
            manifest=(
                replace(bundle.manifest[0], passage_text="tampered passage"),
                *bundle.manifest[1:],
            ),
        )
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        provider = FakeProvider(())

        execution = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=InMemoryGraderExecutionRepository(),
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("5.00")),
            provider=provider,
            clock=lambda: datetime(2026, 7, 22, 3, 0, tzinfo=UTC),
        ).execute(
            AuthenticatedOperator(bundle.operator_id),
            approved_request(bundle.id),
        )

        self.assertEqual(execution.execution_state, "not_executed")
        self.assertIn(
            "evidence_passage_hash_mismatch",
            execution.blocking_reasons,
        )
        self.assertEqual(provider.requests, [])

    def test_frozen_valuation_snapshot_is_part_of_every_grader_logical_input(
        self,
    ) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        valuation_repository, snapshot = aligned_valuation_repository(bundle)
        provider = FakeProvider(
            (
                ProviderResponse(
                    provider_request_id="fake-valuation-input",
                    raw_output=accepted_output(bundle.manifest[0].evidence_id),
                    usage=ProviderUsage(1000, 200, 300, 100, 1300),
                    resolved_model="gpt-5.6-sol",
                    system_fingerprint="offline-fingerprint-v1",
                ),
            )
        )
        workflow = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=valuation_repository,
            execution_repository=InMemoryGraderExecutionRepository(),
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("5.00")),
            provider=provider,
            clock=lambda: datetime(2026, 7, 22, 3, 0, tzinfo=UTC),
        )

        workflow.execute(
            AuthenticatedOperator(bundle.operator_id),
            approved_request(bundle.id),
        )

        self.assertEqual(
            provider.requests[0].logical_input["valuation_snapshot"],
            snapshot.as_dict(),
        )

    def test_cache_write_tokens_are_costed_and_exposed(self) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        provider = FakeProvider(
            (
                ProviderResponse(
                    provider_request_id="fake-request-cache-write",
                    raw_output=accepted_output(bundle.manifest[0].evidence_id),
                    usage=ProviderUsage(
                        input_tokens=1000,
                        cached_input_tokens=200,
                        output_tokens=300,
                        reasoning_tokens=100,
                        total_tokens=1300,
                        cache_write_tokens=400,
                    ),
                    resolved_model="gpt-5.6-sol",
                    system_fingerprint="offline-fingerprint-v1",
                ),
            )
        )
        request = approved_request(bundle.id)
        request = replace(
            request,
            price_card=replace(
                request.price_card,
                cache_write_per_million=Decimal("1.25"),
            ),
        )

        execution = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=InMemoryGraderExecutionRepository(),
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("1.00")),
            provider=provider,
            clock=lambda: datetime(2026, 7, 22, 1, 0, tzinfo=UTC),
        ).execute(AuthenticatedOperator(bundle.operator_id), request)

        self.assertEqual(
            execution.attempts[0].estimated_cost_usd,
            "0.00152",
        )
        self.assertEqual(
            execution.as_dict()["attempts"][0]["usage"]["cache_write_tokens"],
            400,
        )

    def test_cache_read_and_write_tokens_cannot_exceed_input(self) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        response = ProviderResponse(
            provider_request_id="fake-request-invalid-cache-usage",
            raw_output=accepted_output(bundle.manifest[0].evidence_id),
            usage=ProviderUsage(
                input_tokens=1000,
                cached_input_tokens=700,
                output_tokens=300,
                reasoning_tokens=100,
                total_tokens=1300,
                cache_write_tokens=400,
            ),
            resolved_model="gpt-5.6-sol",
            system_fingerprint="offline-fingerprint-v1",
        )
        provider = FakeProvider((response, response))

        execution = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=InMemoryGraderExecutionRepository(),
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("1.00")),
            provider=provider,
            clock=lambda: datetime(2026, 7, 22, 1, 0, tzinfo=UTC),
        ).execute(
            AuthenticatedOperator(bundle.operator_id),
            approved_request(bundle.id),
        )

        self.assertEqual(execution.execution_state, "failed")
        self.assertEqual(
            execution.blocking_reasons,
            ("validation_retry_exhausted", "invalid_provider_usage"),
        )

    def test_budget_reservation_prices_each_input_token_once(self) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        request = approved_request(bundle.id)
        request = replace(
            request,
            price_card=replace(
                request.price_card,
                cache_write_per_million=Decimal("1.25"),
            ),
        )
        provider = FakeProvider(
            (
                ProviderResponse(
                    provider_request_id="fake-request-bounded-reservation",
                    raw_output=accepted_output(bundle.manifest[0].evidence_id),
                    usage=ProviderUsage(1000, 0, 300, 100, 1300),
                    resolved_model="gpt-5.6-sol",
                    system_fingerprint="offline-fingerprint-v1",
                ),
            )
        )

        execution = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=InMemoryGraderExecutionRepository(),
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("0.03")),
            provider=provider,
            clock=lambda: datetime(2026, 7, 22, 1, 0, tzinfo=UTC),
        ).execute(AuthenticatedOperator(bundle.operator_id), request)

        self.assertEqual(execution.execution_state, "accepted")

    def test_successful_isolated_execution_creates_validated_opinion(self) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        provider = FakeProvider(
            (
                ProviderResponse(
                    provider_request_id="fake-request-1",
                    raw_output=accepted_output(bundle.manifest[0].evidence_id),
                    usage=ProviderUsage(
                        input_tokens=1000,
                        cached_input_tokens=200,
                        output_tokens=300,
                        reasoning_tokens=100,
                        total_tokens=1300,
                    ),
                    resolved_model="gpt-5.6-sol",
                    system_fingerprint="offline-fingerprint-v1",
                ),
            )
        )
        repository = InMemoryGraderExecutionRepository()
        workflow = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=repository,
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("1.00")),
            provider=provider,
            clock=lambda: datetime(2026, 7, 22, 1, 0, tzinfo=UTC),
        )

        execution = workflow.execute(
            AuthenticatedOperator(bundle.operator_id),
            approved_request(bundle.id),
        )

        self.assertEqual(execution.execution_state, "accepted")
        self.assertEqual(execution.bundle_hash, bundle.content_hash)
        self.assertEqual(len(execution.attempts), 1)
        self.assertEqual(execution.attempts[0].validation_state, "accepted")
        self.assertEqual(execution.attempts[0].estimated_cost_usd, "0.00142")
        self.assertEqual(execution.opinion.grader_stance, "supports")
        self.assertEqual(
            execution.opinion.material_claims[0].evidence_ids,
            (bundle.manifest[0].evidence_id,),
        )
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(
            repository.get_for_identity(
                bundle.operator_id,
                execution.execution_identity,
            ),
            execution,
        )
        self.assertNotIn("raw_output", execution.as_dict())

    def test_inactive_model_config_is_not_executed_without_provider_call(
        self,
    ) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        provider = FakeProvider(())
        budget = InMemoryBudgetLedger(hard_limit_usd=Decimal("1.00"))
        request = approved_request(bundle.id)

        execution = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=InMemoryGraderExecutionRepository(),
            budget_ledger=budget,
            provider=provider,
            clock=lambda: datetime(2026, 7, 22, 1, 0, tzinfo=UTC),
        ).execute(
            AuthenticatedOperator(bundle.operator_id),
            replace(request, model=replace(request.model, active=False)),
        )

        self.assertEqual(execution.execution_state, "not_executed")
        self.assertEqual(execution.blocking_reasons, ("model_config_inactive",))
        self.assertEqual(execution.attempts, ())
        self.assertIsNone(execution.opinion)
        self.assertEqual(provider.requests, [])
        self.assertEqual(budget.reserved_usd, Decimal("0"))
        assert_typescript_contract(self, execution, bundle)

    def test_discovery_only_source_in_persisted_bundle_blocks_provider_call(
        self,
    ) -> None:
        bundle = materialized_bundle()
        malformed_item = replace(
            bundle.manifest[0],
            source_class="issuer",
            canonical_url=(
                "https://www.reddit.com/r/biotech/comments/example/"
                "claimed_primary_document/"
            ),
        )
        malformed_bundle = replace(
            bundle,
            manifest=(malformed_item, *bundle.manifest[1:]),
        )
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(malformed_bundle)
        provider = FakeProvider(())
        budget = InMemoryBudgetLedger(hard_limit_usd=Decimal("1.00"))

        execution = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=InMemoryGraderExecutionRepository(),
            budget_ledger=budget,
            provider=provider,
            clock=lambda: datetime(2026, 7, 22, 1, 0, tzinfo=UTC),
        ).execute(
            AuthenticatedOperator(malformed_bundle.operator_id),
            approved_request(malformed_bundle.id),
        )

        self.assertEqual(execution.execution_state, "not_executed")
        self.assertEqual(
            execution.blocking_reasons,
            ("unapproved_evidence_source",),
        )
        self.assertEqual(provider.requests, [])
        self.assertEqual(budget.reserved_usd, Decimal("0"))

    def test_production_price_card_without_expiry_fails_closed(self) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        request = approved_request(bundle.id)
        request = replace(
            request,
            model=replace(request.model, environment="production"),
            policy=replace(
                request.policy,
                required_environment="production",
            ),
        )
        provider = FakeProvider(())

        execution = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=InMemoryGraderExecutionRepository(),
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("1.00")),
            provider=provider,
            clock=lambda: datetime(2026, 7, 22, 1, 0, tzinfo=UTC),
        ).execute(AuthenticatedOperator(bundle.operator_id), request)

        self.assertEqual(execution.execution_state, "not_executed")
        self.assertEqual(execution.blocking_reasons, ("price_card_invalid",))
        self.assertEqual(provider.requests, [])

    def test_production_prompt_without_content_hash_fails_closed(self) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        checked_at = datetime(2026, 7, 22, 1, 0, tzinfo=UTC)
        request = approved_request(bundle.id)
        request = replace(
            request,
            prompt=replace(request.prompt, content_sha256=""),
            model=replace(request.model, environment="production"),
            price_card=replace(
                request.price_card,
                effective_to=checked_at + timedelta(days=30),
            ),
            policy=replace(
                request.policy,
                required_environment="production",
            ),
        )
        provider = FakeProvider(())

        execution = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=InMemoryGraderExecutionRepository(),
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("1.00")),
            provider=provider,
            clock=lambda: checked_at,
        ).execute(AuthenticatedOperator(bundle.operator_id), request)

        self.assertEqual(execution.execution_state, "not_executed")
        self.assertEqual(
            execution.blocking_reasons,
            ("prompt_content_hash_invalid",),
        )
        self.assertEqual(provider.requests, [])

    def test_production_prompt_without_corpus_identity_fails_closed(self) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        checked_at = datetime(2026, 7, 22, 1, 0, tzinfo=UTC)
        request = approved_request(bundle.id)
        request = replace(
            request,
            prompt=replace(
                request.prompt,
                content_sha256="a" * 64,
                evaluation_corpus_sha256="",
                evaluation_identity_sha256="",
            ),
            model=replace(request.model, environment="production"),
            price_card=replace(
                request.price_card,
                effective_to=checked_at + timedelta(days=30),
            ),
            policy=replace(
                request.policy,
                required_environment="production",
            ),
        )
        provider = FakeProvider(())

        execution = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=InMemoryGraderExecutionRepository(),
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("1.00")),
            provider=provider,
            clock=lambda: checked_at,
        ).execute(AuthenticatedOperator(bundle.operator_id), request)

        self.assertEqual(execution.execution_state, "not_executed")
        self.assertEqual(
            execution.blocking_reasons,
            ("prompt_evaluation_identity_invalid",),
        )
        self.assertEqual(provider.requests, [])

    def test_production_prompt_drift_invalidates_evaluation_identity(self) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        checked_at = datetime(2026, 7, 22, 1, 0, tzinfo=UTC)
        request = approved_request(bundle.id)
        request = replace(
            request,
            prompt=replace(request.prompt, content_sha256="d" * 64),
            model=replace(request.model, environment="production"),
            price_card=replace(
                request.price_card,
                effective_to=checked_at + timedelta(days=30),
            ),
            policy=replace(
                request.policy,
                required_environment="production",
            ),
        )
        provider = FakeProvider(())

        execution = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=InMemoryGraderExecutionRepository(),
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("1.00")),
            provider=provider,
            clock=lambda: checked_at,
        ).execute(AuthenticatedOperator(bundle.operator_id), request)

        self.assertEqual(execution.execution_state, "not_executed")
        self.assertEqual(
            execution.blocking_reasons,
            ("prompt_evaluation_identity_mismatch",),
        )
        self.assertEqual(provider.requests, [])

    def test_stale_production_price_card_fails_closed(self) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        checked_at = datetime(2026, 7, 22, 1, 0, tzinfo=UTC)
        request = approved_request(bundle.id)
        request = replace(
            request,
            model=replace(request.model, environment="production"),
            price_card=replace(
                request.price_card,
                verified_at=checked_at - timedelta(days=31),
                effective_to=checked_at + timedelta(days=30),
            ),
            policy=replace(
                request.policy,
                required_environment="production",
            ),
        )
        provider = FakeProvider(())

        execution = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=InMemoryGraderExecutionRepository(),
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("1.00")),
            provider=provider,
            clock=lambda: checked_at,
        ).execute(AuthenticatedOperator(bundle.operator_id), request)

        self.assertEqual(execution.execution_state, "not_executed")
        self.assertEqual(execution.blocking_reasons, ("price_card_invalid",))

    def test_negative_price_rate_fails_closed_before_provider_call(self) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        request = approved_request(bundle.id)
        request = replace(
            request,
            price_card=replace(
                request.price_card,
                cache_write_per_million=Decimal("-0.01"),
            ),
        )
        provider = FakeProvider(())

        execution = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=InMemoryGraderExecutionRepository(),
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("1.00")),
            provider=provider,
            clock=lambda: datetime(2026, 7, 22, 1, 0, tzinfo=UTC),
        ).execute(AuthenticatedOperator(bundle.operator_id), request)

        self.assertEqual(execution.execution_state, "not_executed")
        self.assertEqual(execution.blocking_reasons, ("price_card_invalid",))
        self.assertEqual(provider.requests, [])
        self.assertEqual(provider.requests, [])

    def test_unavailable_hard_budget_is_not_executed(self) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        provider = FakeProvider(())

        execution = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=InMemoryGraderExecutionRepository(),
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("0.001")),
            provider=provider,
            clock=lambda: datetime(2026, 7, 22, 1, 0, tzinfo=UTC),
        ).execute(
            AuthenticatedOperator(bundle.operator_id),
            approved_request(bundle.id),
        )

        self.assertEqual(execution.execution_state, "not_executed")
        self.assertEqual(execution.blocking_reasons, ("hard_budget_unavailable",))
        self.assertEqual(execution.attempts, ())
        self.assertEqual(provider.requests, [])

    def test_invalid_citation_retries_once_with_unchanged_logical_input(
        self,
    ) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        invalid = accepted_output(bundle.manifest[0].evidence_id)
        invalid["material_claims"][0]["evidence_ids"] = [
            "00000000-0000-4000-8000-000000000000"
        ]
        provider = FakeProvider(
            (
                ProviderResponse(
                    provider_request_id="fake-request-1",
                    raw_output=invalid,
                    usage=ProviderUsage(1000, 200, 300, 100, 1300),
                    resolved_model="gpt-5.6-sol",
                    system_fingerprint="offline-fingerprint-v1",
                ),
                ProviderResponse(
                    provider_request_id="fake-request-2",
                    raw_output=accepted_output(bundle.manifest[0].evidence_id),
                    usage=ProviderUsage(1000, 200, 300, 100, 1300),
                    resolved_model="gpt-5.6-sol",
                    system_fingerprint="offline-fingerprint-v1",
                ),
            )
        )
        budget = InMemoryBudgetLedger(hard_limit_usd=Decimal("1.00"))

        execution = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=InMemoryGraderExecutionRepository(),
            budget_ledger=budget,
            provider=provider,
            clock=lambda: datetime(2026, 7, 22, 1, 0, tzinfo=UTC),
        ).execute(
            AuthenticatedOperator(bundle.operator_id),
            approved_request(bundle.id),
        )

        self.assertEqual(execution.execution_state, "accepted")
        self.assertEqual(len(execution.attempts), 2)
        self.assertEqual(execution.attempts[0].validation_state, "rejected")
        self.assertEqual(
            execution.attempts[0].validation_errors,
            ("invalid_opinion_citation",),
        )
        self.assertEqual(
            execution.attempts[1].validation_state,
            "accepted",
        )
        self.assertEqual(
            provider.requests[0].logical_input,
            provider.requests[1].logical_input,
        )
        self.assertEqual(
            provider.requests[0].request_hash,
            provider.requests[1].request_hash,
        )
        self.assertEqual(
            provider.requests[1].validation_errors,
            ("invalid_opinion_citation",),
        )
        self.assertEqual(budget.reconciled_usd, Decimal("0.00284"))

    def test_valid_abstention_creates_opinion_without_stance(self) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        provider = FakeProvider(
            (
                ProviderResponse(
                    provider_request_id="fake-request-abstain",
                    raw_output=abstained_output(bundle.manifest[0].evidence_id),
                    usage=ProviderUsage(900, 100, 200, 50, 1100),
                    resolved_model="gpt-5.6-sol",
                    system_fingerprint="offline-fingerprint-v1",
                ),
            )
        )

        execution = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=InMemoryGraderExecutionRepository(),
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("1.00")),
            provider=provider,
            clock=lambda: datetime(2026, 7, 22, 1, 0, tzinfo=UTC),
        ).execute(
            AuthenticatedOperator(bundle.operator_id),
            approved_request(bundle.id),
        )

        self.assertEqual(execution.execution_state, "abstained")
        self.assertIsNotNone(execution.opinion)
        self.assertIsNone(execution.opinion.grader_stance)
        self.assertEqual(
            execution.opinion.abstention.evidence_required,
            ("Primary clinical results with endpoints",),
        )
        self.assertEqual(execution.attempts[0].validation_state, "accepted")
        assert_typescript_contract(self, execution, bundle)

    def test_two_invalid_outputs_fail_without_opinion_or_third_attempt(
        self,
    ) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        invalid = accepted_output(bundle.manifest[0].evidence_id)
        invalid["material_claims"][0]["evidence_ids"] = [
            "00000000-0000-4000-8000-000000000000"
        ]
        provider = FakeProvider(
            tuple(
                ProviderResponse(
                    provider_request_id=f"fake-invalid-{attempt}",
                    raw_output=invalid,
                    usage=ProviderUsage(1000, 200, 300, 100, 1300),
                    resolved_model="gpt-5.6-sol",
                    system_fingerprint="offline-fingerprint-v1",
                )
                for attempt in (1, 2)
            )
        )

        execution = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=InMemoryGraderExecutionRepository(),
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("1.00")),
            provider=provider,
            clock=lambda: datetime(2026, 7, 22, 1, 0, tzinfo=UTC),
        ).execute(
            AuthenticatedOperator(bundle.operator_id),
            approved_request(bundle.id),
        )

        self.assertEqual(execution.execution_state, "failed")
        self.assertEqual(len(execution.attempts), 2)
        self.assertIsNone(execution.opinion)
        self.assertEqual(len(provider.requests), 2)
        self.assertEqual(execution.failure.category, "validation_failure")
        self.assertEqual(execution.failure.attempt_count, 2)
        self.assertEqual(
            execution.failure.validation_errors,
            ("invalid_opinion_citation",),
        )
        self.assertEqual(
            execution.failure.final_reason,
            "validation_retry_exhausted",
        )
        assert_typescript_contract(self, execution, bundle)

    def test_transport_retry_repeats_identical_logical_request(self) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        provider = FakeProvider(
            (
                ProviderTransportError("provider_timeout"),
                ProviderResponse(
                    provider_request_id="fake-request-after-timeout",
                    raw_output=accepted_output(bundle.manifest[0].evidence_id),
                    usage=ProviderUsage(1000, 200, 300, 100, 1300),
                    resolved_model="gpt-5.6-sol",
                    system_fingerprint="offline-fingerprint-v1",
                ),
            )
        )
        budget = InMemoryBudgetLedger(hard_limit_usd=Decimal("1.00"))

        execution = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=InMemoryGraderExecutionRepository(),
            budget_ledger=budget,
            provider=provider,
            clock=lambda: datetime(2026, 7, 22, 1, 0, tzinfo=UTC),
        ).execute(
            AuthenticatedOperator(bundle.operator_id),
            approved_request(bundle.id),
        )

        self.assertEqual(execution.execution_state, "accepted")
        self.assertEqual(len(execution.attempts), 2)
        self.assertEqual(
            execution.attempts[0].validation_state,
            "transport_error",
        )
        self.assertEqual(
            execution.attempts[0].retry_reason,
            "provider_timeout",
        )
        self.assertEqual(
            provider.requests[0].logical_input,
            provider.requests[1].logical_input,
        )
        self.assertEqual(provider.requests[1].validation_errors, ())
        self.assertEqual(budget.reserved_usd, Decimal("0"))
        self.assertEqual(budget.reconciled_usd, Decimal("0.00142"))

    def test_nonretryable_provider_error_stops_after_one_attempt(self) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        provider = FakeProvider(
            (
                ProviderTransportError(
                    "openai_response_refusal",
                    retryable=False,
                    category="refusal",
                ),
            )
        )

        execution = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=InMemoryGraderExecutionRepository(),
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("1.00")),
            provider=provider,
            clock=lambda: datetime(2026, 7, 22, 1, 0, tzinfo=UTC),
        ).execute(
            AuthenticatedOperator(bundle.operator_id),
            approved_request(bundle.id),
        )

        self.assertEqual(execution.execution_state, "failed")
        self.assertEqual(len(execution.attempts), 1)
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(
            execution.failure.final_reason,
            "openai_response_refusal",
        )

    def test_identical_request_reuses_validated_execution_without_new_call(
        self,
    ) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        provider = FakeProvider(
            (
                ProviderResponse(
                    provider_request_id="fake-request-reused",
                    raw_output=accepted_output(bundle.manifest[0].evidence_id),
                    usage=ProviderUsage(1000, 200, 300, 100, 1300),
                    resolved_model="gpt-5.6-sol",
                    system_fingerprint="offline-fingerprint-v1",
                ),
            )
        )
        repository = InMemoryGraderExecutionRepository()
        budget = InMemoryBudgetLedger(hard_limit_usd=Decimal("1.00"))
        workflow = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=repository,
            budget_ledger=budget,
            provider=provider,
            clock=lambda: datetime(2026, 7, 22, 1, 0, tzinfo=UTC),
        )
        operator = AuthenticatedOperator(bundle.operator_id)
        request = approved_request(bundle.id)

        first = workflow.execute(operator, request)
        repeated = workflow.execute(operator, request)

        self.assertIs(repeated, first)
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(budget.reconciled_usd, Decimal("0.00142"))

    def test_prompt_content_drift_creates_new_execution_identity(self) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        response = ProviderResponse(
            provider_request_id="fake-prompt-identity",
            raw_output=accepted_output(bundle.manifest[0].evidence_id),
            usage=ProviderUsage(1000, 200, 300, 100, 1300),
            resolved_model="gpt-5.6-sol",
            system_fingerprint="offline-fingerprint-v1",
        )
        provider = FakeProvider((response, response))
        workflow = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=InMemoryGraderExecutionRepository(),
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("1.00")),
            provider=provider,
            clock=lambda: datetime(2026, 7, 22, 1, 0, tzinfo=UTC),
        )
        operator = AuthenticatedOperator(bundle.operator_id)
        request = approved_request(bundle.id)
        original = replace(
            request,
            prompt=replace(request.prompt, content_sha256="a" * 64),
        )
        drifted = replace(
            request,
            prompt=replace(request.prompt, content_sha256="b" * 64),
        )

        first = workflow.execute(operator, original)
        second = workflow.execute(operator, drifted)

        self.assertNotEqual(
            first.execution_identity,
            second.execution_identity,
        )
        self.assertEqual(len(provider.requests), 2)

    def test_input_schema_change_creates_new_execution_identity(self) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        response = ProviderResponse(
            provider_request_id="fake-input-schema-identity",
            raw_output=accepted_output(bundle.manifest[0].evidence_id),
            usage=ProviderUsage(1000, 200, 300, 100, 1300),
            resolved_model="gpt-5.6-sol",
            system_fingerprint="offline-fingerprint-v1",
        )
        provider = FakeProvider((response, response))
        workflow = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=InMemoryGraderExecutionRepository(),
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("1.00")),
            provider=provider,
            clock=lambda: datetime(2026, 7, 22, 1, 0, tzinfo=UTC),
        )
        operator = AuthenticatedOperator(bundle.operator_id)
        request = approved_request(bundle.id)

        first = workflow.execute(operator, request)
        second = workflow.execute(
            operator,
            replace(
                request,
                prompt=replace(
                    request.prompt,
                    input_schema_version="grader-input-v2",
                ),
            ),
        )

        self.assertNotEqual(
            first.execution_identity,
            second.execution_identity,
        )
        self.assertEqual(len(provider.requests), 2)

    def test_invalid_provider_usage_is_rejected_before_cost_reconciliation(
        self,
    ) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        provider = FakeProvider(
            (
                ProviderResponse(
                    provider_request_id="fake-invalid-usage",
                    raw_output=accepted_output(bundle.manifest[0].evidence_id),
                    usage=ProviderUsage(100, 200, 300, 100, 400),
                    resolved_model="gpt-5.6-sol",
                    system_fingerprint="offline-fingerprint-v1",
                ),
                ProviderResponse(
                    provider_request_id="fake-valid-usage",
                    raw_output=accepted_output(bundle.manifest[0].evidence_id),
                    usage=ProviderUsage(1000, 200, 300, 100, 1300),
                    resolved_model="gpt-5.6-sol",
                    system_fingerprint="offline-fingerprint-v1",
                ),
            )
        )
        budget = InMemoryBudgetLedger(hard_limit_usd=Decimal("1.00"))

        execution = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=InMemoryGraderExecutionRepository(),
            budget_ledger=budget,
            provider=provider,
            clock=lambda: datetime(2026, 7, 22, 1, 0, tzinfo=UTC),
        ).execute(
            AuthenticatedOperator(bundle.operator_id),
            approved_request(bundle.id),
        )

        self.assertEqual(execution.execution_state, "accepted")
        self.assertEqual(len(execution.attempts), 2)
        self.assertEqual(
            execution.attempts[0].validation_errors,
            ("invalid_provider_usage",),
        )
        self.assertEqual(budget.reconciled_usd, Decimal("0.00142"))

    def test_provider_model_drift_is_a_contract_validation_failure(self) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        provider = FakeProvider(
            (
                ProviderResponse(
                    provider_request_id="fake-model-drift",
                    raw_output=accepted_output(bundle.manifest[0].evidence_id),
                    usage=ProviderUsage(1000, 200, 300, 100, 1300),
                    resolved_model="gpt-5.6",
                    system_fingerprint="offline-fingerprint-v2",
                ),
                ProviderResponse(
                    provider_request_id="fake-pinned-model",
                    raw_output=accepted_output(bundle.manifest[0].evidence_id),
                    usage=ProviderUsage(1000, 200, 300, 100, 1300),
                    resolved_model="gpt-5.6-sol",
                    system_fingerprint="offline-fingerprint-v1",
                ),
            )
        )

        execution = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=InMemoryGraderExecutionRepository(),
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("1.00")),
            provider=provider,
            clock=lambda: datetime(2026, 7, 22, 1, 0, tzinfo=UTC),
        ).execute(
            AuthenticatedOperator(bundle.operator_id),
            approved_request(bundle.id),
        )

        self.assertEqual(execution.execution_state, "accepted")
        self.assertEqual(len(execution.attempts), 2)
        self.assertEqual(
            execution.attempts[0].validation_errors,
            ("provider_model_mismatch",),
        )

    def test_public_execution_serialization_matches_typescript_contract(
        self,
    ) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        provider = FakeProvider(
            (
                ProviderResponse(
                    provider_request_id="fake-contract-validation",
                    raw_output=accepted_output(bundle.manifest[0].evidence_id),
                    usage=ProviderUsage(1000, 200, 300, 100, 1300),
                    resolved_model="gpt-5.6-sol",
                    system_fingerprint="offline-fingerprint-v1",
                ),
            )
        )
        execution = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=InMemoryGraderExecutionRepository(),
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("1.00")),
            provider=provider,
            clock=lambda: datetime(2026, 7, 22, 1, 0, tzinfo=UTC),
        ).execute(
            AuthenticatedOperator(bundle.operator_id),
            approved_request(bundle.id),
        )
        assert_typescript_contract(self, execution, bundle)

    def test_raw_payload_requires_audit_permission_and_never_stores_reasoning(
        self,
    ) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        unsafe = accepted_output(bundle.manifest[0].evidence_id)
        unsafe["reasoning_content"] = "private chain of thought"
        provider = FakeProvider(
            tuple(
                ProviderResponse(
                    provider_request_id=f"fake-reasoning-{attempt}",
                    raw_output=unsafe,
                    usage=ProviderUsage(1000, 200, 300, 100, 1300),
                    resolved_model="gpt-5.6-sol",
                    system_fingerprint="offline-fingerprint-v1",
                )
                for attempt in (1, 2)
            )
        )
        repository = InMemoryGraderExecutionRepository()
        execution = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=repository,
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("1.00")),
            provider=provider,
            clock=lambda: datetime(2026, 7, 22, 1, 0, tzinfo=UTC),
        ).execute(
            AuthenticatedOperator(bundle.operator_id),
            approved_request(bundle.id),
        )

        self.assertEqual(execution.execution_state, "failed")
        attempt_id = execution.attempts[0].attempt_id
        with self.assertRaises(GraderExecutionError):
            repository.read_raw_attempt(
                bundle.operator_id,
                attempt_id,
                audit_authorized=False,
            )
        raw = repository.read_raw_attempt(
            bundle.operator_id,
            attempt_id,
            audit_authorized=True,
        )
        self.assertNotIn("reasoning_content", json.dumps(raw))
        self.assertEqual(raw["request"]["attempt_number"], 1)
        self.assertEqual(
            raw["request"]["provider"],
            "openai",
        )
        self.assertEqual(
            raw["response"]["grader_id"],
            "moonshot",
        )


if __name__ == "__main__":
    unittest.main()

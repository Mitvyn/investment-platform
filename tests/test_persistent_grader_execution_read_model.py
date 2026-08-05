from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
import unittest

from investment_research_os.evidence_bundles import (
    AuthenticatedOperator,
    InMemoryEvidenceBundleRepository,
)
from investment_research_os.grader_executions import (
    GraderExecutionWorkflow,
    InMemoryBudgetLedger,
    InMemoryGraderExecutionRepository,
    ProviderResponse,
    ProviderUsage,
)
from investment_research_os.grader_executions.persistent_read_model import (
    PersistentExecutionReadError,
    SupabasePersistentExecutionReadModel,
)
from investment_research_os.grader_executions.runtime import (
    ExecutionStart,
    RuntimeAttemptSnapshot,
    RuntimeExecutionSnapshot,
)
from tests.test_evidence_bundle_storage import materialized_bundle
from tests.test_grader_execution_workflow import (
    FakeProvider,
    accepted_output,
    approved_request,
)


NOW = datetime(2026, 7, 29, 3, 0, tzinfo=UTC)
BUDGET_ID = "00000000-0000-4000-8000-000000000099"


class RawStoreFake:
    def __init__(self, payload):
        self.payload = payload

    def load(self, operator_id, execution_key):
        return deepcopy(self.payload)


def accepted_fixture():
    bundle = materialized_bundle()
    request = approved_request(bundle.id)
    bundle_repository = InMemoryEvidenceBundleRepository()
    bundle_repository.save(bundle)
    execution_repository = InMemoryGraderExecutionRepository()
    execution = GraderExecutionWorkflow(
        evidence_bundle_repository=bundle_repository,
        execution_repository=execution_repository,
        budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("5")),
        provider=FakeProvider(
            (
                ProviderResponse(
                    provider_request_id="response-1",
                    raw_output=accepted_output(bundle.manifest[0].evidence_id),
                    usage=ProviderUsage(100, 20, 25, 5, 125),
                    resolved_model=request.model.model,
                    system_fingerprint=None,
                ),
            )
        ),
        clock=lambda: NOW,
    ).execute(AuthenticatedOperator(bundle.operator_id), request)
    canonical = execution.as_dict()
    attempt = execution.attempts[0]
    audit = execution_repository.read_raw_attempt(
        bundle.operator_id,
        attempt.attempt_id,
        audit_authorized=True,
    )
    attempt_contract = canonical["attempts"][0]
    raw_attempt = {
        "id": attempt.attempt_id,
        "grader_execution_id": execution.execution_id,
        "attempt_number": 1,
        "request_sha256": attempt.request_hash,
        "provider": attempt.provider,
        "model": attempt.requested_model,
        "model_config_id": request.model.config_id,
        "prompt_version": request.prompt.prompt_version,
        "started_at": attempt.started_at.isoformat(),
        "finished_at": attempt.finished_at.isoformat(),
        "duration_ms": 0,
        "result": "accepted",
        "provider_request_id": attempt.provider_request_id,
        "raw_payload_id": attempt.raw_payload_id,
        "raw_payload_sha256": attempt.raw_payload_sha256,
        "input_tokens": attempt.usage.input_tokens,
        "cached_input_tokens": attempt.usage.cached_input_tokens,
        "cache_write_tokens": attempt.usage.cache_write_tokens,
        "uncached_input_tokens": (
            attempt.usage.input_tokens
            - attempt.usage.cached_input_tokens
            - attempt.usage.cache_write_tokens
        ),
        "output_tokens": attempt.usage.output_tokens,
        "reasoning_tokens": attempt.usage.reasoning_tokens,
        "total_tokens": attempt.usage.total_tokens,
        "tool_call_count": attempt.usage.tool_call_count,
        "reserved_cost_usd": attempt_contract["cost"]["reserved_cost_usd"],
        "estimated_cost_usd": attempt.estimated_cost_usd,
        "billed_cost_usd": attempt.estimated_cost_usd,
        "price_card_id": attempt.price_card_id,
        "usage_complete": True,
        "validation_status": "passed",
        "schema_valid": True,
        "citations_valid": True,
        "validation_errors": [],
        "retry_reason": None,
        "persistence_state": "complete",
    }
    reservation = {
        "id": "00000000-0000-4000-8000-000000000098",
        "budget_id": BUDGET_ID,
        "grader_execution_id": execution.execution_id,
        "attempt_number": 1,
        "price_card_id": attempt.price_card_id,
        "reserved_cost_usd": attempt_contract["cost"]["reserved_cost_usd"],
        "reserved_tokens": (
            request.model.input_token_cap + request.model.output_token_cap
        ),
        "actual_cost_usd": attempt.estimated_cost_usd,
        "actual_tokens": attempt.usage.total_tokens,
        "reservation_state": "reconciled",
        "reserved_at": NOW.isoformat(),
        "reconciled_at": NOW.isoformat(),
    }
    raw = {
        "operator_id": bundle.operator_id,
        "grader_execution_id": execution.execution_id,
        "execution_key": execution.execution_identity,
        "evidence_bundle_hash": bundle.content_hash,
        "inference_parameter_hash": canonical["inference_parameter_hash"],
        "persistence_state": "complete",
        "canonical_execution": canonical,
        "attempts": [
            {
                "attempt": raw_attempt,
                "reservation": reservation,
                "request_payload": audit["request"],
                "response_payload": audit["response"],
            }
        ],
        "validated_opinion": canonical["opinion"],
    }
    start_canonical = deepcopy(canonical)
    start_canonical["execution_state"] = None
    start = ExecutionStart.from_payload(
        bundle.operator_id,
        {
            "id": execution.execution_id,
            "research_run_id": bundle.research_run_id,
            "security_id": bundle.security_id,
            "evidence_bundle_id": bundle.id,
            "evidence_bundle_hash": bundle.content_hash,
            "execution_key": execution.execution_identity,
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
            "inference_parameter_hash": canonical["inference_parameter_hash"],
            "retry_policy_version": request.policy.retry_policy_version,
            "max_attempts": 2,
            "required": True,
            "pre_call_gate": canonical["pre_call_gate"],
            "budget_snapshot": {"status": "available"},
            "started_at": NOW.isoformat(),
            "canonical_execution": start_canonical,
        },
    )
    reduced = RuntimeExecutionSnapshot(
        bundle.operator_id,
        execution.execution_id,
        execution.execution_identity,
        "complete",
        (
            RuntimeAttemptSnapshot(
                attempt.attempt_id,
                1,
                "complete",
                "reconciled",
                "accepted",
                True,
                execution.opinion.opinion_id,
                attempt.raw_payload_sha256,
                NOW,
            ),
        ),
        canonical,
    )
    return bundle, request, execution, raw, start, reduced


class PersistentExecutionReadModelTests(unittest.TestCase):
    def test_reconstructs_complete_execution_with_exact_canonical_contract(self):
        bundle, request, expected, raw, start, reduced = accepted_fixture()
        model = SupabasePersistentExecutionReadModel(
            store=RawStoreFake(raw),
            bundle=bundle,
            request=request,
        )

        actual = model.reconstruct_terminal(start, reduced)

        self.assertEqual(actual, expected)
        self.assertEqual(actual.as_dict(), raw["canonical_execution"])

    def test_rejects_foreign_or_malformed_persisted_state(self):
        bundle, request, _, raw, start, reduced = accepted_fixture()
        cases = []
        foreign = deepcopy(raw)
        foreign["operator_id"] = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        cases.append(foreign)
        malformed = deepcopy(raw)
        malformed["attempts"][0]["attempt"]["total_tokens"] += 1
        cases.append(malformed)

        for payload in cases:
            with self.subTest(payload=payload):
                model = SupabasePersistentExecutionReadModel(
                    store=RawStoreFake(payload),
                    bundle=bundle,
                    request=request,
                )
                with self.assertRaises(PersistentExecutionReadError):
                    model.reconstruct_terminal(start, reduced)

    def test_reconstructs_draft_with_persisted_validated_opinion(self):
        bundle, request, expected, raw, start, reduced = accepted_fixture()
        raw["persistence_state"] = "draft"
        raw["canonical_execution"] = start.storage_payload()["canonical_execution"]
        reduced = RuntimeExecutionSnapshot(
            reduced.operator_id,
            reduced.execution_id,
            reduced.execution_key,
            "draft",
            reduced.attempts,
            None,
        )
        model = SupabasePersistentExecutionReadModel(
            store=RawStoreFake(raw),
            bundle=bundle,
            request=request,
        )

        actual = model.reconstruct_terminal(start, reduced)

        self.assertEqual(actual.as_dict(), expected.as_dict())


if __name__ == "__main__":
    unittest.main()

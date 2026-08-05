from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
import unittest

from investment_research_os.grader_executions.runtime import (
    AttemptCompletion,
    AttemptStart,
    ExecutionFinalization,
    GraderExecutionLifecycle,
    ExecutionStart,
    GraderExecutionRuntimeError,
    RestartAction,
    RuntimeAttemptSnapshot,
    RuntimeExecutionSnapshot,
    decide_restart,
)


OPERATOR_ID = "027d7f1b-d928-48d9-b6c8-f10d3c7ba792"
EXECUTION_ID = "11111111-1111-4111-8111-111111111111"
ATTEMPT_ID = "22222222-2222-4222-8222-222222222222"
PAYLOAD_ID = "33333333-3333-4333-8333-333333333333"
RESERVATION_ID = "44444444-4444-4444-8444-444444444444"
BUDGET_ID = "55555555-5555-4555-8555-555555555555"
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def _hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def execution_start_payload() -> dict[str, object]:
    return {
        "id": EXECUTION_ID,
        "research_run_id": "66666666-6666-4666-8666-666666666666",
        "security_id": "77777777-7777-4777-8777-777777777777",
        "evidence_bundle_id": "88888888-8888-4888-8888-888888888888",
        "evidence_bundle_hash": HASH_A,
        "execution_key": HASH_B,
        "question_type_id": "biotech_moonshot_catalyst_assessment",
        "question_type_version": "biotech_moonshot_catalyst_assessment.v1",
        "workflow_config_version": "biotech-moonshot-catalyst-v1",
        "thesis_contract_id": "biotech_moonshot_catalyst_assessment",
        "grader_id": "moonshot",
        "grader_version": "moonshot-grader-v1",
        "grader_contract_version": "moonshot-grader-contract-v1",
        "eligibility_rule_version": "moonshot-eligibility-v1",
        "rubric_version": "moonshot-rubric-v1",
        "output_schema_version": "moonshot_grader_payload.v1",
        "abstention_rules_version": "moonshot-abstention-v1",
        "prompt_version": "moonshot_grader_v1",
        "model_config_id": "grader-config-v1",
        "price_card_id": "openai-sol-medium-v1",
        "budget_id": BUDGET_ID,
        "provider": "openai",
        "model": "gpt-5.6-sol",
        "inference_parameter_hash": HASH_C,
        "retry_policy_version": "grader-retry-policy-v1",
        "max_attempts": 2,
        "required": True,
        "pre_call_gate": {"status": "passed"},
        "budget_snapshot": {"status": "pending"},
        "started_at": "2026-05-07T02:00:00+00:00",
        "canonical_execution": {
            "contract_version": "grader_execution.v1",
            "id": EXECUTION_ID,
        },
    }


class GraderExecutionRuntimeTests(unittest.TestCase):
    def test_execution_start_is_canonical_and_immutable(self) -> None:
        payload = execution_start_payload()

        start = ExecutionStart.from_payload(OPERATOR_ID, payload)
        payload["pre_call_gate"]["status"] = "blocked"  # type: ignore[index]

        self.assertEqual(start.storage_payload()["pre_call_gate"], {"status": "passed"})
        self.assertEqual(
            start.payload_sha256,
            _hash(execution_start_payload()),
        )

    def test_execution_start_rejects_blocked_or_terminal_provider_start(
        self,
    ) -> None:
        blocked = execution_start_payload()
        blocked["pre_call_gate"] = {"status": "blocked"}
        terminal = execution_start_payload()
        terminal["canonical_execution"]["execution_state"] = "accepted"  # type: ignore[index]

        for payload in (blocked, terminal):
            with self.subTest(payload=payload):
                with self.assertRaises(GraderExecutionRuntimeError):
                    ExecutionStart.from_payload(OPERATOR_ID, payload)

    def test_attempt_start_binds_request_and_reservation_before_provider_call(
        self,
    ) -> None:
        request = {"input": {"bundle_hash": HASH_A}, "model": "gpt-5.6-sol"}

        start = AttemptStart.create(
            operator_id=OPERATOR_ID,
            execution_id=EXECUTION_ID,
            attempt_id=ATTEMPT_ID,
            attempt_number=1,
            request_sha256=_hash(request),
            provider="openai",
            model="gpt-5.6-sol",
            model_config_id="biotech_committee_graders_openai_sol_medium_v1",
            prompt_version="moonshot_grader_v1",
            started_at=datetime(2026, 5, 7, 2, 0, 1, tzinfo=UTC),
            raw_payload_id=PAYLOAD_ID,
            price_card_id="openai-sol-medium-v1",
            reserved_cost_usd=Decimal("0.45"),
            retry_reason=None,
            sanitized_request=request,
            reservation_id=RESERVATION_ID,
            budget_id=BUDGET_ID,
            reserved_tokens=18_000,
        )

        attempt, sanitized_request, reservation = start.storage_arguments()

        self.assertEqual(sanitized_request, request)
        self.assertEqual(
            attempt["raw_payload_sha256"],
            _hash({"request": request, "response": None}),
        )
        self.assertEqual(attempt["reserved_cost_usd"], "0.45")
        self.assertEqual(reservation["reserved_cost_usd"], "0.45")
        self.assertEqual(reservation["reserved_tokens"], 18_000)

    def test_attempt_start_rejects_malformed_or_sensitive_values(self) -> None:
        base = {
            "operator_id": OPERATOR_ID,
            "execution_id": EXECUTION_ID,
            "attempt_id": ATTEMPT_ID,
            "attempt_number": 1,
            "request_sha256": HASH_A,
            "provider": "openai",
            "model": "gpt-5.6-sol",
            "model_config_id": "grader-config-v1",
            "prompt_version": "moonshot_grader_v1",
            "started_at": datetime(2026, 5, 7, 2, 0, 1, tzinfo=UTC),
            "raw_payload_id": PAYLOAD_ID,
            "price_card_id": "openai-sol-medium-v1",
            "reserved_cost_usd": Decimal("0.45"),
            "retry_reason": None,
            "sanitized_request": {"input": "safe"},
            "reservation_id": RESERVATION_ID,
            "budget_id": BUDGET_ID,
            "reserved_tokens": 18_000,
        }
        cases = (
            {"operator_id": "not-a-uuid"},
            {"request_sha256": "short"},
            {"attempt_number": 3},
            {"attempt_number": 2, "retry_reason": None},
            {"attempt_number": 1, "retry_reason": "previous_timeout"},
            {"started_at": datetime(2026, 5, 7, 2, 0, 1)},
            {"reserved_cost_usd": Decimal("-0.01")},
            {"reserved_tokens": True},
            {"sanitized_request": {"reasoning_content": "secret"}},
        )

        for override in cases:
            with self.subTest(override=override):
                with self.assertRaises(GraderExecutionRuntimeError):
                    AttemptStart.create(**(base | override))

    def test_attempt_completion_binds_response_settlement_and_opinion(self) -> None:
        request = {"input": "safe"}
        response = {"id": "resp_123", "output": [{"type": "message"}]}
        opinion = {
            "opinion_id": "99999999-9999-4999-8999-999999999999",
            "execution_id": EXECUTION_ID,
            "execution_state": "accepted",
            "grader_id": "moonshot",
        }

        completion = AttemptCompletion.create(
            operator_id=OPERATOR_ID,
            execution_id=EXECUTION_ID,
            attempt_id=ATTEMPT_ID,
            attempt_number=1,
            reservation_id=RESERVATION_ID,
            result="accepted",
            finished_at=datetime(2026, 5, 7, 2, 0, 3, tzinfo=UTC),
            duration_ms=2_000,
            provider_request_id="resp_123",
            raw_payload_id=PAYLOAD_ID,
            input_tokens=100,
            cached_input_tokens=20,
            cache_write_tokens=0,
            output_tokens=25,
            reasoning_tokens=5,
            tool_call_count=0,
            estimated_cost_usd=Decimal("0.00015"),
            billed_cost_usd=Decimal("0.00015"),
            usage_complete=True,
            validation_status="passed",
            schema_valid=True,
            citations_valid=True,
            validation_errors=(),
            retry_reason=None,
            reservation_state="reconciled",
            actual_cost_usd=Decimal("0.00015"),
            sanitized_request=request,
            sanitized_response=response,
            validated_opinion=opinion,
        )

        payload, stored_response, stored_opinion = completion.storage_arguments()

        self.assertEqual(stored_response, response)
        self.assertEqual(stored_opinion, opinion)
        self.assertEqual(
            payload["raw_payload_sha256"],
            _hash({"request": request, "response": response}),
        )
        self.assertEqual(payload["uncached_input_tokens"], 80)
        self.assertEqual(payload["total_tokens"], 125)
        self.assertEqual(payload["actual_tokens"], 125)

    def test_attempt_completion_rejects_inconsistent_terminal_state(self) -> None:
        base = {
            "operator_id": OPERATOR_ID,
            "execution_id": EXECUTION_ID,
            "attempt_id": ATTEMPT_ID,
            "attempt_number": 1,
            "reservation_id": RESERVATION_ID,
            "result": "accepted",
            "finished_at": datetime(2026, 5, 7, 2, 0, 3, tzinfo=UTC),
            "duration_ms": 2_000,
            "provider_request_id": "resp_123",
            "raw_payload_id": PAYLOAD_ID,
            "input_tokens": 100,
            "cached_input_tokens": 20,
            "cache_write_tokens": 0,
            "output_tokens": 25,
            "reasoning_tokens": 5,
            "tool_call_count": 0,
            "estimated_cost_usd": Decimal("0.00015"),
            "billed_cost_usd": Decimal("0.00015"),
            "usage_complete": True,
            "validation_status": "passed",
            "schema_valid": True,
            "citations_valid": True,
            "validation_errors": (),
            "retry_reason": None,
            "reservation_state": "reconciled",
            "actual_cost_usd": Decimal("0.00015"),
            "sanitized_request": {"input": "safe"},
            "sanitized_response": {"id": "resp_123"},
            "validated_opinion": {
                "opinion_id": "99999999-9999-4999-8999-999999999999",
                "execution_id": EXECUTION_ID,
                "execution_state": "accepted",
            },
        }
        cases = (
            {"finished_at": datetime(2026, 5, 7, 2, 0, 3)},
            {"usage_complete": False},
            {"validation_status": "failed"},
            {"schema_valid": None},
            {"citations_valid": None},
            {"validation_errors": ("invalid",)},
            {"reservation_state": "released"},
            {"actual_cost_usd": Decimal("-0.01")},
            {"sanitized_response": {"reasoning_content": "secret"}},
        )

        for override in cases:
            with self.subTest(override=override):
                with self.assertRaises(GraderExecutionRuntimeError):
                    AttemptCompletion.create(**(base | override))

    def test_restart_decision_never_silently_duplicates_provider_call(self) -> None:
        completed_attempt = RuntimeAttemptSnapshot(
            attempt_id=ATTEMPT_ID,
            attempt_number=1,
            persistence_state="complete",
            reservation_state="reconciled",
            result="accepted",
            response_persisted=True,
            opinion_id="99999999-9999-4999-8999-999999999999",
            raw_payload_sha256=HASH_A,
            finished_at=datetime(2026, 5, 7, 2, 0, 3, tzinfo=UTC),
        )
        complete = RuntimeExecutionSnapshot(
            operator_id=OPERATOR_ID,
            execution_id=EXECUTION_ID,
            execution_key=HASH_B,
            persistence_state="complete",
            attempts=(completed_attempt,),
            canonical_execution={"contract_version": "grader_execution.v1"},
        )
        ready_to_finalize = RuntimeExecutionSnapshot(
            operator_id=OPERATOR_ID,
            execution_id=EXECUTION_ID,
            execution_key=HASH_B,
            persistence_state="draft",
            attempts=(completed_attempt,),
            canonical_execution=None,
        )
        ambiguous_attempt = RuntimeAttemptSnapshot(
            attempt_id=ATTEMPT_ID,
            attempt_number=1,
            persistence_state="draft",
            reservation_state="reserved",
            result=None,
            response_persisted=False,
            opinion_id=None,
            raw_payload_sha256=HASH_A,
            finished_at=None,
        )
        ambiguous = RuntimeExecutionSnapshot(
            operator_id=OPERATOR_ID,
            execution_id=EXECUTION_ID,
            execution_key=HASH_B,
            persistence_state="draft",
            attempts=(ambiguous_attempt,),
            canonical_execution=None,
        )

        self.assertEqual(decide_restart(complete).action, RestartAction.REUSE)
        self.assertEqual(
            decide_restart(ready_to_finalize).action,
            RestartAction.FINALIZE,
        )
        decision = decide_restart(ambiguous)
        self.assertEqual(decision.action, RestartAction.MANUAL_RECOVERY)
        self.assertFalse(decision.provider_call_permitted)

    def test_nonretryable_provider_error_finalizes_after_one_attempt(self):
        attempt = RuntimeAttemptSnapshot(
            attempt_id=ATTEMPT_ID,
            attempt_number=1,
            persistence_state="complete",
            reservation_state="released",
            result="transport_error",
            response_persisted=False,
            opinion_id=None,
            raw_payload_sha256=HASH_A,
            finished_at=datetime(2026, 5, 7, 2, 0, 3, tzinfo=UTC),
            retry_reason="nonretryable:openai_response_refusal",
        )
        snapshot = RuntimeExecutionSnapshot(
            operator_id=OPERATOR_ID,
            execution_id=EXECUTION_ID,
            execution_key=HASH_B,
            persistence_state="draft",
            attempts=(attempt,),
            canonical_execution=None,
        )

        decision = decide_restart(snapshot)

        self.assertEqual(decision.action, RestartAction.FINALIZE)
        self.assertFalse(decision.provider_call_permitted)
        self.assertEqual(
            decision.reason_code,
            "nonretryable_provider_error",
        )

    def test_finalization_maps_canonical_terminal_execution(self) -> None:
        canonical = {
            "contract_version": "grader_execution.v1",
            "id": EXECUTION_ID,
            "operator_id": OPERATOR_ID,
            "execution_key": HASH_B,
            "execution_state": "accepted",
            "total_usage": {
                "input_tokens": 100,
                "output_tokens": 25,
                "reasoning_tokens": 5,
                "total_tokens": 125,
            },
            "total_cost": {"estimated_cost_usd": "0.00015"},
            "finished_at": "2026-05-07T02:00:04+00:00",
            "opinion": {
                "opinion_id": "99999999-9999-4999-8999-999999999999",
            },
        }

        finalization = ExecutionFinalization.from_canonical(
            OPERATOR_ID,
            canonical,
        )
        canonical["total_usage"]["total_tokens"] = 999  # type: ignore[index]

        payload = finalization.storage_payload()
        self.assertEqual(payload["total_tokens"], 125)
        self.assertEqual(payload["total_cost_usd"], "0.00015")
        self.assertEqual(
            finalization.canonical_execution_sha256,
            _hash(finalization.canonical_execution),
        )
        self.assertTrue(issubclass(GraderExecutionLifecycle, object))


if __name__ == "__main__":
    unittest.main()

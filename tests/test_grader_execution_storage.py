from __future__ import annotations

import unittest
from typing import Any, Mapping

from investment_research_os.grader_executions.storage import (
    GraderExecutionStorageError,
    SupabaseGraderExecutionRuntimeStore,
)
from workers.sec.storage import (
    JsonResponse,
    SupabaseStorageSettings,
)


OPERATOR_ID = "027d7f1b-d928-48d9-b6c8-f10d3c7ba792"
EXECUTION_ID = "11111111-1111-4111-8111-111111111111"
RUN_ID = "22222222-2222-4222-8222-222222222222"
SECURITY_ID = "33333333-3333-4333-8333-333333333333"
BUNDLE_ID = "44444444-4444-4444-8444-444444444444"
BUDGET_ID = "55555555-5555-4555-8555-555555555555"
PRICE_CARD_ID = "66666666-6666-4666-8666-666666666666"
ATTEMPT_ID = "77777777-7777-4777-8777-777777777777"
RAW_PAYLOAD_ID = "88888888-8888-4888-8888-888888888888"
RESERVATION_ID = "99999999-9999-4999-8999-999999999999"
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64


class TransportFake:
    def __init__(self, responses: tuple[JsonResponse, ...]) -> None:
        self._responses = iter(responses)
        self.requests: list[
            tuple[str, str, Mapping[str, str], Mapping[str, Any] | None]
        ] = []

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any] | None = None,
    ) -> JsonResponse:
        self.requests.append((method, url, headers, payload))
        return next(self._responses)


def execution_payload() -> dict[str, object]:
    canonical_execution = {
        "contract_version": "grader_execution.v1",
        "id": EXECUTION_ID,
        "operator_id": OPERATOR_ID,
        "research_run_id": RUN_ID,
        "evidence_bundle_id": BUNDLE_ID,
        "evidence_bundle_hash": HASH_A,
        "execution_key": HASH_B,
        "question_type_id": "biotech_moonshot_catalyst_assessment",
        "question_type_version": ("biotech_moonshot_catalyst_assessment.v1"),
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
        "model_config_id": ("biotech_committee_graders_openai_sol_medium_v1"),
        "provider": "openai",
        "model": "gpt-5.6-sol",
        "inference_parameter_hash": HASH_C,
        "retry_policy_version": "grader-retry-policy-v1",
        "required": True,
        "execution_state": None,
        "pre_call_gate": {"status": "passed"},
        "budget": {"status": "pending"},
        "attempts": [],
        "total_usage": {},
        "total_cost": {},
        "not_executed": None,
        "failure": None,
        "opinion": None,
        "started_at": "2026-05-07T02:00:00+00:00",
        "finished_at": None,
    }
    return {
        "id": EXECUTION_ID,
        "research_run_id": RUN_ID,
        "security_id": SECURITY_ID,
        "evidence_bundle_id": BUNDLE_ID,
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
        "model_config_id": "biotech_committee_graders_openai_sol_medium_v1",
        "price_card_id": PRICE_CARD_ID,
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
        "canonical_execution": canonical_execution,
    }


def execution_receipt(*, state: str = "draft", reused: bool = False):
    return {
        "operator_id": OPERATOR_ID,
        "grader_execution_id": EXECUTION_ID,
        "execution_key": HASH_B,
        "persistence_state": state,
        "reused": reused,
        "evidence_bundle_hash": HASH_A,
        "inference_parameter_hash": HASH_C,
    }


def attempt_payload() -> dict[str, object]:
    return {
        "id": ATTEMPT_ID,
        "grader_execution_id": EXECUTION_ID,
        "attempt_number": 1,
        "request_sha256": HASH_D,
        "provider": "openai",
        "model": "gpt-5.6-sol",
        "model_config_id": "biotech_committee_graders_openai_sol_medium_v1",
        "prompt_version": "moonshot_grader_v1",
        "started_at": "2026-05-07T02:00:01+00:00",
        "raw_payload_id": RAW_PAYLOAD_ID,
        "raw_payload_sha256": HASH_E,
        "price_card_id": PRICE_CARD_ID,
        "reserved_cost_usd": "0.45",
        "retry_reason": None,
    }


def reservation_payload() -> dict[str, object]:
    return {
        "id": RESERVATION_ID,
        "budget_id": BUDGET_ID,
        "reserved_cost_usd": "0.45",
        "reserved_tokens": 18000,
        "price_card_id": PRICE_CARD_ID,
    }


def attempt_receipt(
    *,
    state: str = "draft",
    reservation_state: str = "reserved",
    reused: bool = False,
    raw_payload_sha256: str = HASH_E,
):
    return {
        "operator_id": OPERATOR_ID,
        "grader_execution_id": EXECUTION_ID,
        "grader_attempt_id": ATTEMPT_ID,
        "budget_reservation_id": RESERVATION_ID,
        "attempt_number": 1,
        "persistence_state": state,
        "reservation_state": reservation_state,
        "reused": reused,
        "request_sha256": HASH_D,
        "raw_payload_id": RAW_PAYLOAD_ID,
        "raw_payload_sha256": raw_payload_sha256,
    }


def completion_payload() -> dict[str, object]:
    return {
        "grader_execution_id": EXECUTION_ID,
        "attempt_id": ATTEMPT_ID,
        "attempt_number": 1,
        "reservation_id": RESERVATION_ID,
        "result": "accepted",
        "finished_at": "2026-05-07T02:00:03+00:00",
        "duration_ms": 2000,
        "provider_request_id": "resp_123",
        "raw_payload_id": RAW_PAYLOAD_ID,
        "raw_payload_sha256": HASH_E,
        "input_tokens": 100,
        "cached_input_tokens": 20,
        "cache_write_tokens": 0,
        "uncached_input_tokens": 80,
        "output_tokens": 25,
        "reasoning_tokens": 5,
        "total_tokens": 125,
        "tool_call_count": 0,
        "estimated_cost_usd": "0.00015",
        "billed_cost_usd": "0.00015",
        "usage_complete": True,
        "validation_status": "passed",
        "schema_valid": True,
        "citations_valid": True,
        "validation_errors": [],
        "retry_reason": None,
        "reservation_state": "reconciled",
        "actual_cost_usd": "0.00015",
        "actual_tokens": 125,
    }


def opinion_payload() -> dict[str, object]:
    return {
        "opinion_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "execution_id": EXECUTION_ID,
        "execution_state": "accepted",
        "grader_id": "moonshot",
        "grader_version": "moonshot-grader-v1",
        "owned_decision_question": "Is the opportunity asymmetric?",
        "proposition_id": "credible_moonshot_catalyst_case",
        "proposition_version": "credible_moonshot_catalyst_case.v1",
        "rendered_proposition_text": "Evidence supports a credible case.",
        "stance": "supports",
        "stance_rationale": "Supported.",
        "confidence": "medium",
        "summary": "Supported.",
        "material_claims": [],
        "assumptions": [],
        "contradicting_evidence": [],
        "evidence_gaps": [],
        "invalidation_signals": [],
        "abstention": None,
        "domain_payload": {},
    }


def finalization_payload() -> dict[str, object]:
    payload = execution_receipt(state="complete")
    return {
        "id": EXECUTION_ID,
        "execution_state": "accepted",
        "total_input_tokens": 100,
        "total_output_tokens": 25,
        "total_reasoning_tokens": 5,
        "total_tokens": 125,
        "total_cost_usd": "0.00015",
        "finished_at": "2026-05-07T02:00:04+00:00",
        "canonical_execution": {
            "contract_version": "grader_execution.v1",
            "id": payload["grader_execution_id"],
            "execution_key": payload["execution_key"],
            "evidence_bundle_hash": payload["evidence_bundle_hash"],
            "inference_parameter_hash": payload["inference_parameter_hash"],
        },
    }


class GraderExecutionStorageTests(unittest.TestCase):
    def test_begins_execution_with_exact_rpc_contract(self) -> None:
        transport = TransportFake(
            (
                JsonResponse(
                    payload=execution_receipt(),
                    status=200,
                    headers={},
                ),
            )
        )
        store = SupabaseGraderExecutionRuntimeStore(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
        )
        payload = execution_payload()

        receipt = store.begin_execution(OPERATOR_ID, payload)

        self.assertEqual(receipt.execution_id, EXECUTION_ID)
        self.assertEqual(receipt.execution_key, HASH_B)
        self.assertEqual(receipt.persistence_state, "draft")
        self.assertFalse(receipt.reused)
        method, url, headers, request_payload = transport.requests[0]
        self.assertEqual(method, "POST")
        self.assertTrue(
            url.endswith("/rest/v1/rpc/iros_begin_grader_execution_runtime")
        )
        self.assertEqual(
            request_payload,
            {
                "p_operator_id": OPERATOR_ID,
                "p_execution": payload,
            },
        )
        self.assertEqual(headers["apikey"], "sb_secret_test")
        self.assertNotIn("Authorization", headers)

    def test_begins_attempt_and_redacts_reasoning_from_request(self) -> None:
        transport = TransportFake(
            (
                JsonResponse(
                    payload=attempt_receipt(),
                    status=200,
                    headers={},
                ),
            )
        )
        store = SupabaseGraderExecutionRuntimeStore(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
        )
        attempt = attempt_payload()
        reservation = reservation_payload()

        receipt = store.begin_attempt(
            OPERATOR_ID,
            attempt,
            {
                "output": [
                    {"type": "reasoning", "encrypted_content": "secret"},
                    {"type": "message", "text": "safe"},
                ],
                "reasoning_content": "secret",
            },
            reservation,
        )

        self.assertEqual(receipt.attempt_id, ATTEMPT_ID)
        self.assertEqual(receipt.reservation_id, RESERVATION_ID)
        self.assertEqual(
            transport.requests[0][3],
            {
                "p_operator_id": OPERATOR_ID,
                "p_attempt": attempt,
                "p_sanitized_request": {
                    "output": [{"type": "message", "text": "safe"}],
                },
                "p_reservation": reservation,
            },
        )
        self.assertTrue(
            transport.requests[0][1].endswith(
                "/rest/v1/rpc/iros_begin_grader_attempt_runtime"
            )
        )

    def test_finishes_attempt_with_exact_rpc_contract(self) -> None:
        transport = TransportFake(
            (
                JsonResponse(
                    payload=attempt_receipt(
                        state="complete",
                        reservation_state="reconciled",
                    ),
                    status=200,
                    headers={},
                ),
            )
        )
        store = SupabaseGraderExecutionRuntimeStore(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
        )
        completion = completion_payload()

        receipt = store.finish_attempt(
            OPERATOR_ID,
            completion,
            {
                "id": "resp_123",
                "output": [
                    {"type": "reasoning", "encrypted_content": "secret"},
                    {"type": "message", "text": "safe"},
                ],
            },
            opinion_payload(),
        )

        self.assertEqual(receipt.persistence_state, "complete")
        self.assertEqual(receipt.reservation_state, "reconciled")
        self.assertEqual(
            transport.requests[0][3],
            {
                "p_operator_id": OPERATOR_ID,
                "p_completion": completion,
                "p_sanitized_response": {
                    "id": "resp_123",
                    "output": [{"type": "message", "text": "safe"}],
                },
                "p_validated_opinion": opinion_payload(),
            },
        )
        self.assertTrue(
            transport.requests[0][1].endswith(
                "/rest/v1/rpc/iros_finish_grader_attempt_runtime"
            )
        )

    def test_loads_restart_snapshot_with_ordered_attempts_and_opinion(self) -> None:
        snapshot = {
            "operator_id": OPERATOR_ID,
            "grader_execution_id": EXECUTION_ID,
            "execution_key": HASH_B,
            "evidence_bundle_hash": HASH_A,
            "inference_parameter_hash": HASH_C,
            "persistence_state": "draft",
            "canonical_execution": execution_payload()["canonical_execution"],
            "attempts": [
                {
                    "attempt": attempt_payload()
                    | {
                        "persistence_state": "complete",
                        "result": "accepted",
                    },
                    "reservation": reservation_payload()
                    | {"reservation_state": "reconciled"},
                    "request_payload": {"input": "safe"},
                    "response_payload": {"id": "resp_123"},
                }
            ],
            "validated_opinion": opinion_payload(),
        }
        transport = TransportFake(
            (JsonResponse(payload=snapshot, status=200, headers={}),)
        )
        store = SupabaseGraderExecutionRuntimeStore(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
        )

        loaded = store.load(OPERATOR_ID, HASH_B)

        self.assertEqual(loaded, snapshot)
        self.assertEqual(
            transport.requests[0][3],
            {
                "p_operator_id": OPERATOR_ID,
                "p_execution_key": HASH_B,
            },
        )
        self.assertTrue(
            transport.requests[0][1].endswith(
                "/rest/v1/rpc/iros_load_grader_execution_runtime"
            )
        )

    def test_finalizes_execution_with_exact_rpc_contract(self) -> None:
        transport = TransportFake(
            (
                JsonResponse(
                    payload=execution_receipt(state="complete"),
                    status=200,
                    headers={},
                ),
            )
        )
        store = SupabaseGraderExecutionRuntimeStore(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
        )
        finalization = finalization_payload()

        receipt = store.finalize_execution(
            OPERATOR_ID,
            finalization,
            execution_key=HASH_B,
            evidence_bundle_hash=HASH_A,
            inference_parameter_hash=HASH_C,
        )

        self.assertEqual(receipt.persistence_state, "complete")
        self.assertEqual(
            transport.requests[0][3],
            {
                "p_operator_id": OPERATOR_ID,
                "p_execution": finalization,
            },
        )
        self.assertTrue(
            transport.requests[0][1].endswith(
                "/rest/v1/rpc/iros_finalize_grader_execution_runtime"
            )
        )

    def test_completed_attempt_reuse_accepts_terminal_payload_hash(self) -> None:
        transport = TransportFake(
            (
                JsonResponse(
                    payload=attempt_receipt(
                        state="complete",
                        reservation_state="reconciled",
                        reused=True,
                        raw_payload_sha256=HASH_A,
                    ),
                    status=200,
                    headers={},
                ),
            )
        )
        store = SupabaseGraderExecutionRuntimeStore(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
        )

        receipt = store.begin_attempt(
            OPERATOR_ID,
            attempt_payload(),
            {"input": "safe"},
            reservation_payload(),
        )

        self.assertEqual(receipt.persistence_state, "complete")
        self.assertTrue(receipt.reused)
        self.assertEqual(receipt.raw_payload_sha256, HASH_A)

    def test_rejects_incomplete_canonical_execution_before_rpc(self) -> None:
        transport = TransportFake(())
        store = SupabaseGraderExecutionRuntimeStore(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
        )
        payload = execution_payload()
        payload["canonical_execution"] = {"contract_version": "grader_execution.v1"}

        with self.assertRaisesRegex(
            GraderExecutionStorageError,
            "grader execution request is malformed",
        ):
            store.begin_execution(OPERATOR_ID, payload)

        self.assertEqual(transport.requests, [])

    def test_rejects_blocked_or_terminal_execution_start_before_rpc(self) -> None:
        for mutate in ("blocked", "terminal"):
            with self.subTest(mutate=mutate):
                transport = TransportFake(())
                store = SupabaseGraderExecutionRuntimeStore(
                    SupabaseStorageSettings(
                        url="https://example.supabase.co",
                        secret_key="sb_secret_test",
                    ),
                    transport=transport,
                )
                payload = execution_payload()
                if mutate == "blocked":
                    payload["pre_call_gate"] = {"status": "blocked"}
                    payload["canonical_execution"]["pre_call_gate"] = {  # type: ignore[index]
                        "status": "blocked"
                    }
                else:
                    payload["canonical_execution"]["execution_state"] = "accepted"  # type: ignore[index]

                with self.assertRaises(GraderExecutionStorageError):
                    store.begin_execution(OPERATOR_ID, payload)

                self.assertEqual(transport.requests, [])

    def test_rejects_foreign_malformed_and_http_receipts(self) -> None:
        cases = (
            execution_receipt()
            | {"operator_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"},
            execution_receipt() | {"unexpected": True},
        )
        for payload in cases:
            with self.subTest(payload=payload):
                store = SupabaseGraderExecutionRuntimeStore(
                    SupabaseStorageSettings(
                        url="https://example.supabase.co",
                        secret_key="sb_secret_test",
                    ),
                    transport=TransportFake(
                        (JsonResponse(payload=payload, status=200, headers={}),)
                    ),
                )
                with self.assertRaises(GraderExecutionStorageError):
                    store.begin_execution(OPERATOR_ID, execution_payload())

        store = SupabaseGraderExecutionRuntimeStore(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=TransportFake(
                (JsonResponse(payload={}, status=409, headers={}),)
            ),
        )
        with self.assertRaisesRegex(
            GraderExecutionStorageError,
            "returned HTTP 409",
        ):
            store.begin_execution(OPERATOR_ID, execution_payload())


if __name__ == "__main__":
    unittest.main()

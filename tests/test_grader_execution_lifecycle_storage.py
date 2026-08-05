from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import unittest
from types import SimpleNamespace
from typing import Mapping

from investment_research_os.grader_executions.lifecycle_storage import (
    GraderExecutionLifecycleStorageError,
    SupabaseGraderExecutionLifecycle,
)
from investment_research_os.grader_executions.runtime import (
    AttemptCompletion,
    AttemptStart,
    ExecutionFinalization,
    ExecutionStart,
)


OPERATOR_ID = "027d7f1b-d928-48d9-b6c8-f10d3c7ba792"
EXECUTION_ID = "11111111-1111-4111-8111-111111111111"
RUN_ID = "22222222-2222-4222-8222-222222222222"
SECURITY_ID = "33333333-3333-4333-8333-333333333333"
BUNDLE_ID = "44444444-4444-4444-8444-444444444444"
BUDGET_ID = "55555555-5555-4555-8555-555555555555"
ATTEMPT_ID = "66666666-6666-4666-8666-666666666666"
PAYLOAD_ID = "77777777-7777-4777-8777-777777777777"
RESERVATION_ID = "88888888-8888-4888-8888-888888888888"
OPINION_ID = "99999999-9999-4999-8999-999999999999"
SECOND_ATTEMPT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64


def canonical_execution(*, state: str | None = None) -> dict[str, object]:
    return {
        "contract_version": "grader_execution.v1",
        "id": EXECUTION_ID,
        "operator_id": OPERATOR_ID,
        "research_run_id": RUN_ID,
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
        "provider": "openai",
        "model": "gpt-5.6-sol",
        "inference_parameter_hash": HASH_C,
        "retry_policy_version": "grader-retry-policy-v1",
        "required": True,
        "execution_state": state,
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


def execution_start() -> ExecutionStart:
    return ExecutionStart.from_payload(
        OPERATOR_ID,
        {
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
            "price_card_id": "grader-price-card-v1",
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
            "canonical_execution": canonical_execution(),
        },
    )


def attempt_start() -> AttemptStart:
    return AttemptStart.create(
        operator_id=OPERATOR_ID,
        execution_id=EXECUTION_ID,
        attempt_id=ATTEMPT_ID,
        attempt_number=1,
        request_sha256=HASH_D,
        provider="openai",
        model="gpt-5.6-sol",
        model_config_id="biotech_committee_graders_openai_sol_medium_v1",
        prompt_version="moonshot_grader_v1",
        started_at=datetime(2026, 5, 7, 2, 0, 1, tzinfo=UTC),
        raw_payload_id=PAYLOAD_ID,
        price_card_id="grader-price-card-v1",
        reserved_cost_usd=Decimal("0.45"),
        retry_reason=None,
        sanitized_request={"input": "safe"},
        reservation_id=RESERVATION_ID,
        budget_id=BUDGET_ID,
        reserved_tokens=18_000,
    )


def attempt_completion(*, state: str = "accepted") -> AttemptCompletion:
    return AttemptCompletion.create(
        operator_id=OPERATOR_ID,
        execution_id=EXECUTION_ID,
        attempt_id=ATTEMPT_ID,
        attempt_number=1,
        reservation_id=RESERVATION_ID,
        result=state,
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
        sanitized_request={"input": "safe"},
        sanitized_response={"id": "resp_123"},
        validated_opinion=validated_opinion(state=state),
    )


def execution_finalization() -> ExecutionFinalization:
    terminal = canonical_execution(state="accepted")
    terminal["opinion"] = validated_opinion()
    terminal["total_usage"] = {
        "input_tokens": 100,
        "output_tokens": 25,
        "reasoning_tokens": 5,
        "total_tokens": 125,
    }
    terminal["total_cost"] = {"estimated_cost_usd": "0.00015"}
    terminal["finished_at"] = "2026-05-07T02:00:04+00:00"
    return ExecutionFinalization.from_canonical(OPERATOR_ID, terminal)


def raw_snapshot(
    *,
    persistence_state: str = "draft",
    attempts: list[dict[str, object]] | None = None,
    opinion: Mapping[str, object] | None = None,
    canonical: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "operator_id": OPERATOR_ID,
        "grader_execution_id": EXECUTION_ID,
        "execution_key": HASH_B,
        "evidence_bundle_hash": HASH_A,
        "inference_parameter_hash": HASH_C,
        "persistence_state": persistence_state,
        "canonical_execution": (
            canonical_execution() if canonical is None else dict(canonical)
        ),
        "attempts": [] if attempts is None else attempts,
        "validated_opinion": None if opinion is None else dict(opinion),
    }


def raw_attempt(
    *,
    attempt_id: str = ATTEMPT_ID,
    attempt_number: int = 1,
    persistence_state: str = "complete",
    result: str | None = "accepted",
    reservation_state: str = "reconciled",
    response: Mapping[str, object] | None = None,
    raw_payload_sha256: str = HASH_D,
) -> dict[str, object]:
    return {
        "attempt": {
            "id": attempt_id,
            "grader_execution_id": EXECUTION_ID,
            "attempt_number": attempt_number,
            "persistence_state": persistence_state,
            "result": result,
            "raw_payload_sha256": raw_payload_sha256,
            "finished_at": (
                None if persistence_state == "draft" else "2026-05-07T02:00:03+00:00"
            ),
        },
        "reservation": {
            "id": RESERVATION_ID,
            "grader_execution_id": EXECUTION_ID,
            "attempt_number": attempt_number,
            "reservation_state": reservation_state,
        },
        "request_payload": {"input": "safe"},
        "response_payload": (
            ({"id": "resp_123"} if response is None else dict(response))
            if persistence_state == "complete" and result != "transport_error"
            else None
        ),
    }


def validated_opinion(*, state: str = "accepted") -> dict[str, object]:
    return {
        "opinion_id": OPINION_ID,
        "execution_id": EXECUTION_ID,
        "execution_state": state,
        "grader_id": "moonshot",
        "grader_version": "moonshot-grader-v1",
        "confidence": "medium",
    }


class RuntimeStoreFake:
    def __init__(
        self,
        snapshots: list[Mapping[str, object] | None],
        *,
        begin_attempt_reused: bool = False,
    ) -> None:
        self.snapshots = iter(snapshots)
        self.begin_attempt_reused = begin_attempt_reused
        self.calls: list[tuple[object, ...]] = []

    def begin_execution(
        self,
        operator_id: str,
        execution: Mapping[str, object],
    ) -> object:
        self.calls.append(("begin_execution", operator_id, execution))
        return object()

    def begin_attempt(
        self,
        operator_id: str,
        attempt: Mapping[str, object],
        request_payload: Mapping[str, object],
        reservation: Mapping[str, object],
    ) -> object:
        self.calls.append(
            (
                "begin_attempt",
                operator_id,
                attempt,
                request_payload,
                reservation,
            )
        )
        return SimpleNamespace(reused=self.begin_attempt_reused)

    def finish_attempt(
        self,
        operator_id: str,
        completion: Mapping[str, object],
        response_payload: Mapping[str, object] | None,
        validated_opinion: Mapping[str, object] | None,
    ) -> object:
        self.calls.append(
            (
                "finish_attempt",
                operator_id,
                completion,
                response_payload,
                validated_opinion,
            )
        )
        return object()

    def load(
        self,
        operator_id: str,
        execution_key: str,
    ) -> Mapping[str, object] | None:
        self.calls.append(("load", operator_id, execution_key))
        return next(self.snapshots)

    def finalize_execution(
        self,
        operator_id: str,
        execution: Mapping[str, object],
        *,
        execution_key: str,
        evidence_bundle_hash: str,
        inference_parameter_hash: str,
    ) -> object:
        self.calls.append(
            (
                "finalize_execution",
                operator_id,
                execution,
                execution_key,
                evidence_bundle_hash,
                inference_parameter_hash,
            )
        )
        return object()


class SupabaseGraderExecutionLifecycleTests(unittest.TestCase):
    def test_begin_execution_persists_then_returns_loaded_draft_snapshot(self) -> None:
        store = RuntimeStoreFake([raw_snapshot()])
        lifecycle = SupabaseGraderExecutionLifecycle(store)  # type: ignore[arg-type]
        start = execution_start()

        snapshot = lifecycle.begin_execution(start)

        self.assertEqual(snapshot.operator_id, OPERATOR_ID)
        self.assertEqual(snapshot.execution_id, EXECUTION_ID)
        self.assertEqual(snapshot.execution_key, HASH_B)
        self.assertEqual(snapshot.persistence_state, "draft")
        self.assertEqual(snapshot.attempts, ())
        self.assertIsNone(snapshot.canonical_execution)
        self.assertEqual(
            store.calls,
            [
                ("begin_execution", OPERATOR_ID, start.storage_payload()),
                ("load", OPERATOR_ID, HASH_B),
            ],
        )

    def test_load_maps_completed_attempt_and_binds_validated_opinion(self) -> None:
        terminal = canonical_execution(state="accepted")
        terminal["opinion"] = validated_opinion()
        store = RuntimeStoreFake(
            [
                raw_snapshot(
                    persistence_state="complete",
                    attempts=[raw_attempt()],
                    opinion=validated_opinion(),
                    canonical=terminal,
                )
            ]
        )
        lifecycle = SupabaseGraderExecutionLifecycle(store)  # type: ignore[arg-type]

        snapshot = lifecycle.load(OPERATOR_ID, HASH_B)

        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.canonical_execution, terminal)
        self.assertEqual(len(snapshot.attempts), 1)
        attempt = snapshot.attempts[0]
        self.assertEqual(attempt.attempt_id, ATTEMPT_ID)
        self.assertEqual(attempt.attempt_number, 1)
        self.assertEqual(attempt.persistence_state, "complete")
        self.assertEqual(attempt.reservation_state, "reconciled")
        self.assertEqual(attempt.result, "accepted")
        self.assertTrue(attempt.response_persisted)
        self.assertEqual(attempt.opinion_id, OPINION_ID)
        self.assertEqual(
            attempt.finished_at,
            datetime(2026, 5, 7, 2, 0, 3, tzinfo=UTC),
        )
        self.assertEqual(store.calls, [("load", OPERATOR_ID, HASH_B)])

    def test_begin_attempt_persists_atomic_arguments_then_reloads_ambiguous_draft(
        self,
    ) -> None:
        store = RuntimeStoreFake(
            [
                raw_snapshot(),
                raw_snapshot(
                    attempts=[
                        raw_attempt(
                            persistence_state="draft",
                            result=None,
                            reservation_state="reserved",
                        )
                    ]
                ),
            ]
        )
        lifecycle = SupabaseGraderExecutionLifecycle(store)  # type: ignore[arg-type]
        lifecycle.begin_execution(execution_start())
        start = attempt_start()

        snapshot = lifecycle.begin_attempt(start)

        self.assertEqual(len(snapshot.attempts), 1)
        attempt = snapshot.attempts[0]
        self.assertEqual(attempt.persistence_state, "draft")
        self.assertEqual(attempt.reservation_state, "reserved")
        self.assertFalse(attempt.response_persisted)
        self.assertIsNone(attempt.result)
        self.assertIsNone(attempt.opinion_id)
        stored_attempt, stored_request, stored_reservation = start.storage_arguments()
        self.assertEqual(
            store.calls[-2:],
            [
                (
                    "begin_attempt",
                    OPERATOR_ID,
                    stored_attempt,
                    stored_request,
                    stored_reservation,
                ),
                ("load", OPERATOR_ID, HASH_B),
            ],
        )

    def test_reused_attempt_blocks_duplicate_provider_dispatch(self) -> None:
        store = RuntimeStoreFake(
            [raw_snapshot()],
            begin_attempt_reused=True,
        )
        lifecycle = SupabaseGraderExecutionLifecycle(store)  # type: ignore[arg-type]
        lifecycle.begin_execution(execution_start())

        with self.assertRaisesRegex(
            GraderExecutionLifecycleStorageError,
            "already existed before provider dispatch",
        ):
            lifecycle.begin_attempt(attempt_start())

        self.assertEqual(
            [call[0] for call in store.calls],
            ["begin_execution", "load", "begin_attempt"],
        )

    def test_finish_attempt_persists_settlement_and_opinion_then_reloads(
        self,
    ) -> None:
        completion = attempt_completion()
        draft_attempt = raw_attempt(
            persistence_state="draft",
            result=None,
            reservation_state="reserved",
            raw_payload_sha256=attempt_start().raw_payload_sha256,
        )
        completed_attempt = raw_attempt(
            raw_payload_sha256=completion.raw_payload_sha256
        )
        store = RuntimeStoreFake(
            [
                raw_snapshot(),
                raw_snapshot(attempts=[draft_attempt]),
                raw_snapshot(
                    attempts=[completed_attempt],
                    opinion=validated_opinion(),
                ),
            ]
        )
        lifecycle = SupabaseGraderExecutionLifecycle(store)  # type: ignore[arg-type]
        lifecycle.begin_execution(execution_start())
        lifecycle.begin_attempt(attempt_start())

        snapshot = lifecycle.finish_attempt(completion)

        self.assertEqual(snapshot.persistence_state, "draft")
        self.assertEqual(snapshot.attempts[0].persistence_state, "complete")
        self.assertEqual(snapshot.attempts[0].opinion_id, OPINION_ID)
        stored_completion, stored_response, stored_opinion = (
            completion.storage_arguments()
        )
        self.assertEqual(
            store.calls[-2:],
            [
                (
                    "finish_attempt",
                    OPERATOR_ID,
                    stored_completion,
                    stored_response,
                    stored_opinion,
                ),
                ("load", OPERATOR_ID, HASH_B),
            ],
        )

    def test_finalize_execution_persists_canonical_then_reloads_terminal(
        self,
    ) -> None:
        finalization = execution_finalization()
        completed = raw_attempt(
            raw_payload_sha256=attempt_completion().raw_payload_sha256
        )
        store = RuntimeStoreFake(
            [
                raw_snapshot(
                    persistence_state="complete",
                    attempts=[completed],
                    opinion=validated_opinion(),
                    canonical=finalization.canonical_execution,
                )
            ]
        )
        lifecycle = SupabaseGraderExecutionLifecycle(store)  # type: ignore[arg-type]

        snapshot = lifecycle.finalize_execution(finalization)

        self.assertEqual(snapshot.persistence_state, "complete")
        self.assertEqual(
            snapshot.canonical_execution,
            finalization.canonical_execution,
        )
        self.assertEqual(
            store.calls,
            [
                (
                    "finalize_execution",
                    OPERATOR_ID,
                    finalization.storage_payload(),
                    HASH_B,
                    HASH_A,
                    HASH_C,
                ),
                ("load", OPERATOR_ID, HASH_B),
            ],
        )

    def test_load_preserves_attempt_order_and_binds_abstention_to_final_attempt(
        self,
    ) -> None:
        opinion = validated_opinion(state="abstained")
        terminal = canonical_execution(state="abstained")
        terminal["opinion"] = opinion
        store = RuntimeStoreFake(
            [
                raw_snapshot(
                    persistence_state="complete",
                    attempts=[
                        raw_attempt(
                            result="validation_error",
                            raw_payload_sha256=HASH_C,
                        ),
                        raw_attempt(
                            attempt_id=SECOND_ATTEMPT_ID,
                            attempt_number=2,
                            result="abstained",
                            raw_payload_sha256=HASH_D,
                        ),
                    ],
                    opinion=opinion,
                    canonical=terminal,
                )
            ]
        )
        lifecycle = SupabaseGraderExecutionLifecycle(store)  # type: ignore[arg-type]

        snapshot = lifecycle.load(OPERATOR_ID, HASH_B)

        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(
            tuple(attempt.attempt_number for attempt in snapshot.attempts),
            (1, 2),
        )
        self.assertIsNone(snapshot.attempts[0].opinion_id)
        self.assertEqual(snapshot.attempts[1].result, "abstained")
        self.assertEqual(snapshot.attempts[1].opinion_id, OPINION_ID)

    def test_load_rejects_snapshot_that_does_not_match_lookup_identity(
        self,
    ) -> None:
        foreign_operator = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        foreign_canonical = canonical_execution()
        foreign_canonical["operator_id"] = foreign_operator
        raw = raw_snapshot(canonical=foreign_canonical)
        raw["operator_id"] = foreign_operator
        store = RuntimeStoreFake([raw])
        lifecycle = SupabaseGraderExecutionLifecycle(store)  # type: ignore[arg-type]

        with self.assertRaisesRegex(
            GraderExecutionLifecycleStorageError,
            "does not match lookup",
        ):
            lifecycle.load(OPERATOR_ID, HASH_B)

    def test_load_rejects_malformed_nested_attempt_payload(self) -> None:
        terminal = canonical_execution(state="accepted")
        terminal["opinion"] = validated_opinion()
        malformed_attempt = raw_attempt()
        malformed_attempt["response_payload"] = "not-an-object"
        store = RuntimeStoreFake(
            [
                raw_snapshot(
                    persistence_state="complete",
                    attempts=[malformed_attempt],
                    opinion=validated_opinion(),
                    canonical=terminal,
                )
            ]
        )
        lifecycle = SupabaseGraderExecutionLifecycle(store)  # type: ignore[arg-type]

        with self.assertRaisesRegex(
            GraderExecutionLifecycleStorageError,
            "attempt is malformed",
        ):
            lifecycle.load(OPERATOR_ID, HASH_B)

    def test_restart_load_restores_execution_key_for_next_attempt_write(
        self,
    ) -> None:
        start = attempt_start()
        store = RuntimeStoreFake(
            [
                raw_snapshot(),
                raw_snapshot(
                    attempts=[
                        raw_attempt(
                            persistence_state="draft",
                            result=None,
                            reservation_state="reserved",
                            raw_payload_sha256=start.raw_payload_sha256,
                        )
                    ]
                ),
            ]
        )
        lifecycle = SupabaseGraderExecutionLifecycle(store)  # type: ignore[arg-type]
        lifecycle.load(OPERATOR_ID, HASH_B)

        snapshot = lifecycle.begin_attempt(start)

        self.assertEqual(snapshot.attempts[0].attempt_id, ATTEMPT_ID)
        self.assertEqual(
            store.calls[-2][0],
            "begin_attempt",
        )


if __name__ == "__main__":
    unittest.main()

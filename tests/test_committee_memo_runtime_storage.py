from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Mapping
import unittest

from investment_research_os.committee_memos import (
    CommitteeMemoError,
    CommitteeMemoWorkflow,
    InMemoryCommitteeMemoRepository,
)
from investment_research_os.committee_memos import _raw_attempt_identity
from investment_research_os.evidence_bundles import AuthenticatedOperator
from investment_research_os.grader_executions import InMemoryBudgetLedger
from investment_research_os.committee_memos.storage import (
    CommitteeMemoRuntimeStorageError,
    RuntimeManagedSynthesisBudgetLedger,
    SupabaseCommitteeMemoRepository,
    SupabaseCommitteeMemoRuntimeStore,
)
from tests.test_committee_memo_persistent_read_model import _attempt_rows
from tests.test_committee_memo_workflow import approved_synthesis_request
from tests.test_five_grader_committee import completed_committee_fixture
from tests.test_grader_execution_workflow import FakeProvider
from tests.test_readiness_and_thesis import synthesized_fixture
from workers.sec.storage import JsonResponse, SupabaseStorageSettings


class RecordingTransport:
    def __init__(self, responses: list[JsonResponse]) -> None:
        self.responses = iter(responses)
        self.requests: list[dict[str, Any]] = []

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any] | None = None,
    ) -> JsonResponse:
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "payload": payload,
            }
        )
        return next(self.responses)


class RuntimeStoreFake:
    def __init__(self, *, reused_attempt: bool = False) -> None:
        self.reused_attempt = reused_attempt
        self.calls: list[tuple[object, ...]] = []

    def begin_execution(self, operator_id, execution):
        self.calls.append(("begin_execution", operator_id, execution))
        return type(
            "Receipt",
            (),
            {
                "operator_id": operator_id,
                "execution_id": execution["id"],
                "execution_key": execution["execution_key"],
                "persistence_state": "draft",
                "reused": False,
            },
        )()

    def begin_attempt(self, operator_id, attempt, request):
        self.calls.append(("begin_attempt", operator_id, attempt, request))
        return type(
            "Receipt",
            (),
            {
                "operator_id": operator_id,
                "execution_id": attempt["synthesis_execution_id"],
                "attempt_id": attempt["id"],
                "attempt_number": attempt["attempt_number"],
                "raw_payload_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "raw_payload_sha256": "a" * 64,
                "persistence_state": "draft",
                "reused": self.reused_attempt,
            },
        )()

    def finish_attempt(self, operator_id, execution_id, attempt, response):
        self.calls.append(
            ("finish_attempt", operator_id, execution_id, attempt, response)
        )
        return object()

    def finalize_execution(self, execution):
        self.calls.append(("finalize_execution", execution))
        return object()


class ReadModelFake:
    def __init__(self, result) -> None:
        self.result = result
        self.calls: list[tuple[str, str, str]] = []

    def get_for_key(self, operator_id: str, execution_key: str):
        self.calls.append(("key", operator_id, execution_key))
        return self.result

    def get_for_committee(self, operator_id: str, committee_id: str):
        self.calls.append(("committee", operator_id, committee_id))
        return self.result


class SimulatedCrash(RuntimeError):
    pass


class CrashAfterAttemptStartRepository(InMemoryCommitteeMemoRepository):
    def __init__(self) -> None:
        super().__init__()
        self.crash_once = True

    def begin_attempt(self, operator_id, attempt, request_payload):
        receipt = super().begin_attempt(operator_id, attempt, request_payload)
        if self.crash_once:
            self.crash_once = False
            raise SimulatedCrash("process stopped after durable attempt start")
        return receipt


class CommitteeMemoRuntimeStorageTests(unittest.TestCase):
    def test_runtime_managed_budget_issues_uuid_without_duplicate_rpc(self) -> None:
        ledger = RuntimeManagedSynthesisBudgetLedger()

        reservation_id = ledger.reserve(Decimal("0.25"))
        ledger.reconcile(reservation_id, Decimal("0.10"))

        self.assertRegex(
            reservation_id,
            r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
            r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
        )
        with self.assertRaisesRegex(
            CommitteeMemoError,
            "synthesis budget reservation not found",
        ):
            ledger.release(reservation_id)

    def test_begin_attempt_uses_named_rpc_and_sanitizes_request(self) -> None:
        bundle, _, *_, execution = synthesized_fixture(
            requested_disposition="deep_research"
        )
        attempt = _attempt_rows(execution)[0]
        start = {
            "id": attempt["id"],
            "synthesis_execution_id": execution.execution_id,
            "attempt_number": 1,
            "request_sha256": attempt["request_sha256"],
            "reservation_id": "90000000-0000-4000-8000-000000000001",
            "reserved_cost_usd": "0.01",
            "started_at": attempt["started_at"],
        }
        expected_raw_id, expected_raw_hash = _raw_attempt_identity(
            bundle.operator_id,
            attempt["id"],
            {"request": {"provider": "openai"}, "response": None},
        )
        transport = RecordingTransport(
            [
                JsonResponse(
                    payload=[
                        {
                            "operator_id": bundle.operator_id,
                            "synthesis_execution_id": execution.execution_id,
                            "synthesis_attempt_id": attempt["id"],
                            "attempt_number": 1,
                            "raw_payload_id": expected_raw_id,
                            "raw_payload_sha256": expected_raw_hash,
                            "persistence_state": "draft",
                            "reused": False,
                        }
                    ],
                    status=200,
                    headers={},
                )
            ]
        )
        store = SupabaseCommitteeMemoRuntimeStore(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
        )

        receipt = store.begin_attempt(
            bundle.operator_id,
            start,
            {
                "provider": "openai",
                "reasoning_content": "never persist this",
            },
        )

        self.assertEqual(receipt.attempt_id, attempt["id"])
        request = transport.requests[0]
        self.assertTrue(
            request["url"].endswith("/rest/v1/rpc/iros_begin_synthesis_attempt_runtime")
        )
        self.assertEqual(
            request["payload"]["p_sanitized_request"],
            {"provider": "openai"},
        )
        self.assertEqual(
            request["payload"]["p_attempt"]["raw_payload_id"],
            expected_raw_id,
        )
        self.assertEqual(
            request["payload"]["p_attempt"]["raw_payload_sha256"],
            expected_raw_hash,
        )
        self.assertNotIn("reasoning_content", str(request["payload"]))

    def test_repository_finalizes_then_requires_exact_reload(self) -> None:
        *_, execution = synthesized_fixture(requested_disposition="deep_research")
        store = RuntimeStoreFake()
        read_model = ReadModelFake(execution)
        repository = SupabaseCommitteeMemoRepository(
            runtime_store=store,  # type: ignore[arg-type]
            read_model=read_model,  # type: ignore[arg-type]
        )

        persisted = repository.finalize_execution(execution)

        self.assertIs(persisted, execution)
        self.assertEqual(store.calls, [("finalize_execution", execution)])
        self.assertEqual(
            read_model.calls,
            [("committee", execution.operator_id, execution.committee_id)],
        )

    def test_repository_rejects_reused_attempt_before_dispatch(self) -> None:
        *_, execution = synthesized_fixture(requested_disposition="deep_research")
        store = RuntimeStoreFake(reused_attempt=True)
        repository = SupabaseCommitteeMemoRepository(
            runtime_store=store,  # type: ignore[arg-type]
            read_model=ReadModelFake(None),  # type: ignore[arg-type]
        )

        with self.assertRaisesRegex(
            CommitteeMemoError,
            "conflicting immutable synthesis start|"
            "already existed before provider dispatch",
        ):
            repository.begin_attempt(
                execution.operator_id,
                {
                    "id": execution.attempts[0].attempt_id,
                    "synthesis_execution_id": execution.execution_id,
                    "attempt_number": 1,
                    "request_sha256": execution.attempts[0].request_hash,
                    "reservation_id": ("90000000-0000-4000-8000-000000000001"),
                    "reserved_cost_usd": "0.01",
                    "started_at": execution.attempts[0].started_at.isoformat(),
                },
                {"provider": "openai"},
            )

    def test_repository_blocks_non_atomic_offline_budget_reservation(self) -> None:
        *_, execution = synthesized_fixture(requested_disposition="deep_research")
        store = RuntimeStoreFake()
        repository = SupabaseCommitteeMemoRepository(
            runtime_store=store,  # type: ignore[arg-type]
            read_model=ReadModelFake(None),  # type: ignore[arg-type]
        )

        with self.assertRaisesRegex(
            CommitteeMemoRuntimeStorageError,
            "atomic budget reservation",
        ):
            repository.begin_attempt(
                execution.operator_id,
                {
                    "id": execution.attempts[0].attempt_id,
                    "synthesis_execution_id": execution.execution_id,
                    "attempt_number": 1,
                    "request_sha256": execution.attempts[0].request_hash,
                    "reservation_id": "offline-budget-reservation",
                    "reserved_cost_usd": "0.01",
                    "started_at": execution.attempts[0].started_at.isoformat(),
                },
                {"provider": "openai"},
            )

        self.assertEqual(store.calls, [])

    def test_finish_and_finalize_use_named_rpcs_with_exact_usage(self) -> None:
        bundle, committee, *_, execution = synthesized_fixture(
            requested_disposition="deep_research"
        )
        attempt = execution.attempts[0]
        transport = RecordingTransport(
            [
                JsonResponse(
                    payload=[
                        {
                            "operator_id": bundle.operator_id,
                            "synthesis_execution_id": execution.execution_id,
                            "synthesis_attempt_id": attempt.attempt_id,
                            "attempt_number": attempt.attempt_number,
                            "raw_payload_id": attempt.raw_payload_id,
                            "raw_payload_sha256": attempt.raw_payload_sha256,
                            "persistence_state": "complete",
                            "reused": False,
                        }
                    ],
                    status=200,
                    headers={},
                ),
                JsonResponse(
                    payload=[
                        {
                            "operator_id": bundle.operator_id,
                            "committee_result_id": committee.committee_id,
                            "synthesis_execution_id": execution.execution_id,
                            "execution_key": execution.execution_key,
                            "execution_state": "accepted",
                            "memo_id": execution.memo.memo_id,
                            "persistence_state": "complete",
                            "reused": False,
                        }
                    ],
                    status=200,
                    headers={},
                ),
            ]
        )
        store = SupabaseCommitteeMemoRuntimeStore(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
        )

        store.finish_attempt(
            bundle.operator_id,
            execution.execution_id,
            attempt,
            {"reasoning_content": "private", "result": "accepted"},
        )
        store.finalize_execution(execution)

        self.assertTrue(
            transport.requests[0]["url"].endswith(
                "/rest/v1/rpc/iros_finish_synthesis_attempt_runtime"
            )
        )
        self.assertEqual(
            transport.requests[0]["payload"]["p_completion"]["reasoning_tokens"],
            attempt.usage.reasoning_tokens,
        )
        self.assertEqual(
            transport.requests[0]["payload"]["p_sanitized_response"],
            {"result": "accepted"},
        )
        self.assertTrue(
            transport.requests[1]["url"].endswith(
                "/rest/v1/rpc/iros_finalize_synthesis_execution_runtime"
            )
        )
        self.assertEqual(
            transport.requests[1]["payload"]["p_execution"]["total_reasoning_tokens"],
            attempt.usage.reasoning_tokens,
        )
        self.assertNotIn("reasoning_content", str(transport.requests))

    def test_repository_rejects_non_exact_terminal_reload(self) -> None:
        *_, execution = synthesized_fixture(requested_disposition="deep_research")
        drifted = replace(execution, execution_state="failed", memo=None)
        repository = SupabaseCommitteeMemoRepository(
            runtime_store=RuntimeStoreFake(),  # type: ignore[arg-type]
            read_model=ReadModelFake(drifted),  # type: ignore[arg-type]
        )

        with self.assertRaisesRegex(
            CommitteeMemoRuntimeStorageError,
            "does not match",
        ):
            repository.finalize_execution(execution)

    def test_crash_replay_fails_closed_before_duplicate_provider_dispatch(
        self,
    ) -> None:
        bundle, committee, bundle_repository, committee_repository = (
            completed_committee_fixture()
        )
        repository = CrashAfterAttemptStartRepository()
        provider = FakeProvider(())
        times = iter(
            datetime(2026, 7, 22, 4, minute, tzinfo=UTC) for minute in range(4)
        )
        workflow = CommitteeMemoWorkflow(
            committee_repository=committee_repository,
            evidence_bundle_repository=bundle_repository,
            memo_repository=repository,
            budget_ledger=InMemoryBudgetLedger(hard_limit_usd=Decimal("2.00")),
            provider=provider,
            clock=lambda: next(times),
        )
        operator = AuthenticatedOperator(bundle.operator_id)
        request = approved_synthesis_request(committee)

        with self.assertRaises(SimulatedCrash):
            workflow.execute(operator, request)
        with self.assertRaisesRegex(
            CommitteeMemoError,
            "already existed before provider dispatch",
        ):
            workflow.execute(operator, request)

        self.assertEqual(provider.requests, [])


if __name__ == "__main__":
    unittest.main()

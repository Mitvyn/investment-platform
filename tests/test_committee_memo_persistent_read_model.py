from __future__ import annotations

from copy import deepcopy
import unittest
from typing import Any, Mapping

from investment_research_os.committee_memos.persistent_read_model import (
    SupabaseCommitteeMemoReadModel,
)
from tests.test_readiness_and_thesis import synthesized_fixture
from workers.sec.storage import (
    EvidenceStorageError,
    JsonResponse,
    SupabaseStorageSettings,
)


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
                "payload": None if payload is None else dict(payload),
            }
        )
        return next(self.responses)


def _execution_row(bundle, committee, execution):
    memo = execution.memo
    return {
        "id": execution.execution_id,
        "operator_id": execution.operator_id,
        "committee_result_id": execution.committee_id,
        "research_run_id": committee.research_run_id,
        "security_id": bundle.security_id,
        "evidence_bundle_id": committee.evidence_bundle_id,
        "evidence_bundle_hash": committee.evidence_bundle_hash,
        "workflow_config_version": committee.workflow_config_version,
        "proposition_id": committee.proposition_id,
        "proposition_version": committee.proposition_version,
        "committee_status": committee.status,
        "execution_key": execution.execution_key,
        "prompt_version": memo.prompt_version,
        "model_config_id": memo.model_config_id,
        "provider": memo.provider,
        "model": memo.model,
        "price_card_version": memo.price_card_version,
        "retry_policy_version": memo.retry_policy_version,
        "budget_policy_version": "committee-budget.v1",
        "max_attempts": 2,
        "budget_id": "90000000-0000-4000-8000-000000000001",
        "execution_state": execution.execution_state,
        "attempt_count": len(execution.attempts),
        "total_input_tokens": memo.usage.input_tokens,
        "total_cached_input_tokens": memo.usage.cached_input_tokens,
        "total_cache_write_tokens": memo.usage.cache_write_tokens,
        "total_uncached_input_tokens": (
            memo.usage.input_tokens
            - memo.usage.cached_input_tokens
            - memo.usage.cache_write_tokens
        ),
        "total_output_tokens": memo.usage.output_tokens,
        "total_reasoning_tokens": memo.usage.reasoning_tokens,
        "total_tokens": memo.usage.total_tokens,
        "usage_complete": memo.usage.usage_complete,
        "total_cost_usd": memo.estimated_cost_usd,
        "final_validation_errors": [],
        "started_at": memo.started_at.isoformat(),
        "completed_at": execution.created_at.isoformat(),
        "persistence_state": "complete",
        "created_at": memo.started_at.isoformat(),
    }


def _attempt_rows(execution):
    return [
        {
            "id": attempt.attempt_id,
            "operator_id": execution.operator_id,
            "synthesis_execution_id": execution.execution_id,
            "attempt_number": attempt.attempt_number,
            "request_sha256": attempt.request_hash,
            "provider_request_id": attempt.provider_request_id,
            "result": attempt.as_dict()["result"],
            "raw_payload_id": attempt.raw_payload_id,
            "raw_payload_sha256": attempt.raw_payload_sha256,
            "budget_reservation_id": (
                f"90000000-0000-4000-8000-{attempt.attempt_number:012d}"
            ),
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
            "usage_complete": attempt.usage.usage_complete,
            "estimated_cost_usd": attempt.estimated_cost_usd,
            "validation_status": ("failed" if attempt.validation_errors else "passed"),
            "validation_errors": list(attempt.validation_errors),
            "retry_reason": (
                attempt.validation_errors[0] if attempt.validation_errors else None
            ),
            "started_at": attempt.started_at.isoformat(),
            "completed_at": attempt.finished_at.isoformat(),
            "duration_ms": int(
                (attempt.finished_at - attempt.started_at).total_seconds() * 1000
            ),
            "persistence_state": "complete",
            "created_at": attempt.started_at.isoformat(),
        }
        for attempt in execution.attempts
    ]


class SupabaseCommitteeMemoReadModelTests(unittest.TestCase):
    def _read_model(
        self,
        responses: list[JsonResponse],
    ) -> tuple[SupabaseCommitteeMemoReadModel, RecordingTransport]:
        transport = RecordingTransport(responses)
        return (
            SupabaseCommitteeMemoReadModel(
                SupabaseStorageSettings(
                    url="https://example.supabase.co",
                    secret_key="sb_secret_test",
                ),
                transport=transport,
            ),
            transport,
        )

    def test_reconstructs_accepted_synthesis_and_provenance_memo(self) -> None:
        fixture = synthesized_fixture(requested_disposition="deep_research")
        bundle, committee, *_, execution = fixture
        memo_row = {
            "operator_id": execution.operator_id,
            "research_run_id": committee.research_run_id,
            "committee_result_id": committee.committee_id,
            "memo_id": execution.memo.memo_id,
            "canonical_memo": execution.memo.as_dict(),
        }
        read_model, transport = self._read_model(
            [
                JsonResponse(
                    payload=[_execution_row(bundle, committee, execution)],
                    status=200,
                    headers={},
                ),
                JsonResponse(
                    payload=_attempt_rows(execution),
                    status=200,
                    headers={},
                ),
                JsonResponse(payload=[memo_row], status=200, headers={}),
            ]
        )

        loaded = read_model.get_for_committee(
            execution.operator_id,
            execution.committee_id,
        )

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.execution_id, execution.execution_id)
        self.assertEqual(loaded.execution_key, execution.execution_key)
        self.assertEqual(loaded.execution_state, "accepted")
        self.assertEqual(loaded.attempts, execution.attempts)
        self.assertEqual(loaded.memo.as_dict(), execution.memo.as_dict())
        self.assertEqual(
            loaded.memo.statements,
            execution.memo.statements,
        )
        self.assertTrue(
            all(
                "iros_synthesis_attempt_payloads" not in request["url"]
                for request in transport.requests
            )
        )
        self.assertTrue(
            all(
                request["headers"]["apikey"] == "sb_secret_test"
                for request in transport.requests
            )
        )

    def test_reconstructs_failed_synthesis_without_provider_body(self) -> None:
        bundle, committee, *_, execution = synthesized_fixture(
            requested_disposition="deep_research"
        )
        execution_row = _execution_row(bundle, committee, execution)
        attempt_row = _attempt_rows(execution)[0]
        execution_row["execution_state"] = "failed"
        execution_row["final_validation_errors"] = ["provider_model_mismatch"]
        attempt_row["result"] = "validation_error"
        attempt_row["validation_status"] = "failed"
        attempt_row["validation_errors"] = ["provider_model_mismatch"]
        attempt_row["retry_reason"] = "provider_model_mismatch"
        read_model, transport = self._read_model(
            [
                JsonResponse(payload=[execution_row], status=200, headers={}),
                JsonResponse(payload=[attempt_row], status=200, headers={}),
                JsonResponse(payload=[], status=200, headers={}),
            ]
        )

        loaded = read_model.get_for_committee(
            execution.operator_id,
            execution.committee_id,
        )

        self.assertEqual(loaded.execution_state, "failed")
        self.assertIsNone(loaded.memo)
        self.assertEqual(len(loaded.attempts), 1)
        self.assertEqual(
            loaded.attempts[0].validation_errors,
            ("provider_model_mismatch",),
        )
        self.assertEqual(loaded.attempts[0].request_hash, attempt_row["request_sha256"])
        self.assertEqual(
            loaded.attempts[0].raw_payload_sha256,
            attempt_row["raw_payload_sha256"],
        )
        self.assertEqual(
            loaded.attempts[0].usage.reasoning_tokens,
            attempt_row["reasoning_tokens"],
        )
        self.assertEqual(
            loaded.attempts[0].usage.usage_complete,
            attempt_row["usage_complete"],
        )
        self.assertTrue(
            all(
                "iros_synthesis_attempt_payloads" not in request["url"]
                for request in transport.requests
            )
        )

    def test_reconstructs_by_execution_key_with_owner_scope(self) -> None:
        bundle, committee, *_, execution = synthesized_fixture(
            requested_disposition="deep_research"
        )
        read_model, transport = self._read_model(
            [
                JsonResponse(
                    payload=[_execution_row(bundle, committee, execution)],
                    status=200,
                    headers={},
                ),
                JsonResponse(
                    payload=_attempt_rows(execution),
                    status=200,
                    headers={},
                ),
                JsonResponse(
                    payload=[
                        {
                            "operator_id": execution.operator_id,
                            "research_run_id": committee.research_run_id,
                            "committee_result_id": committee.committee_id,
                            "memo_id": execution.memo.memo_id,
                            "canonical_memo": execution.memo.as_dict(),
                        }
                    ],
                    status=200,
                    headers={},
                ),
            ]
        )

        loaded = read_model.get_for_key(
            execution.operator_id,
            execution.execution_key,
        )

        self.assertEqual(loaded, execution)
        self.assertIn(
            f"execution_key=eq.{execution.execution_key}",
            transport.requests[0]["url"],
        )

    def test_rejects_duplicate_synthesis_executions(self) -> None:
        bundle, committee, *_, execution = synthesized_fixture(
            requested_disposition="deep_research"
        )
        row = _execution_row(bundle, committee, execution)
        read_model, _ = self._read_model(
            [JsonResponse(payload=[row, row], status=200, headers={})]
        )

        with self.assertRaisesRegex(EvidenceStorageError, "duplicate"):
            read_model.get_for_committee(
                execution.operator_id,
                execution.committee_id,
            )

    def test_rejects_foreign_attempt_row(self) -> None:
        bundle, committee, *_, execution = synthesized_fixture(
            requested_disposition="deep_research"
        )
        attempt_rows = _attempt_rows(execution)
        attempt_rows[0]["operator_id"] = "10000000-0000-4000-8000-000000000099"
        read_model, _ = self._read_model(
            [
                JsonResponse(
                    payload=[_execution_row(bundle, committee, execution)],
                    status=200,
                    headers={},
                ),
                JsonResponse(payload=attempt_rows, status=200, headers={}),
                JsonResponse(payload=[], status=200, headers={}),
            ]
        )

        with self.assertRaisesRegex(EvidenceStorageError, "inconsistent"):
            read_model.get_for_committee(
                execution.operator_id,
                execution.committee_id,
            )

    def test_rejects_memo_usage_drift(self) -> None:
        bundle, committee, *_, execution = synthesized_fixture(
            requested_disposition="deep_research"
        )
        canonical = deepcopy(execution.memo.as_dict())
        canonical["execution_metadata"]["reasoning_tokens"] += 1
        read_model, _ = self._read_model(
            [
                JsonResponse(
                    payload=[_execution_row(bundle, committee, execution)],
                    status=200,
                    headers={},
                ),
                JsonResponse(
                    payload=_attempt_rows(execution),
                    status=200,
                    headers={},
                ),
                JsonResponse(
                    payload=[
                        {
                            "operator_id": execution.operator_id,
                            "research_run_id": committee.research_run_id,
                            "committee_result_id": committee.committee_id,
                            "memo_id": execution.memo.memo_id,
                            "canonical_memo": canonical,
                        }
                    ],
                    status=200,
                    headers={},
                ),
            ]
        )

        with self.assertRaisesRegex(EvidenceStorageError, "inconsistent"):
            read_model.get_for_committee(
                execution.operator_id,
                execution.committee_id,
            )

    def test_rejects_internal_opinion_provenance_drift(self) -> None:
        bundle, committee, *_, execution = synthesized_fixture(
            requested_disposition="deep_research"
        )
        canonical = deepcopy(execution.memo.as_dict())
        interpretation = next(
            statement
            for statement in canonical["statements"]
            if statement["provenance_type"] == "grader_interpretation"
        )
        interpretation["opinion_ids"] = ["ffffffff-ffff-4fff-8fff-ffffffffffff"]
        read_model, _ = self._read_model(
            [
                JsonResponse(
                    payload=[_execution_row(bundle, committee, execution)],
                    status=200,
                    headers={},
                ),
                JsonResponse(
                    payload=_attempt_rows(execution),
                    status=200,
                    headers={},
                ),
                JsonResponse(
                    payload=[
                        {
                            "operator_id": execution.operator_id,
                            "research_run_id": committee.research_run_id,
                            "committee_result_id": committee.committee_id,
                            "memo_id": execution.memo.memo_id,
                            "canonical_memo": canonical,
                        }
                    ],
                    status=200,
                    headers={},
                ),
            ]
        )

        with self.assertRaisesRegex(EvidenceStorageError, "inconsistent"):
            read_model.get_for_committee(
                execution.operator_id,
                execution.committee_id,
            )


if __name__ == "__main__":
    unittest.main()

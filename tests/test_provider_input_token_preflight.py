from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import unittest

from investment_research_os.grader_executions import (
    ProviderRequest,
    ProviderTransportError,
)
from investment_research_os.provider_input_token_preflight import (
    InputTokenPreflightError,
    InputTokenPreflightReceipt,
    PersistentInputTokenPreflightGate,
)
from investment_research_os.providers import OpenAIInputTokenPreflight
from investment_research_os.provider_input_token_preflight_storage import (
    InputTokenPreflightStorageError,
    SupabaseInputTokenPreflightStore,
)
from workers.sec.storage import JsonResponse, SupabaseStorageSettings


OPERATOR_ID = "10000000-0000-4000-8000-000000000001"
RUN_ID = "20000000-0000-4000-8000-000000000002"
ATTEMPT_ID = "30000000-0000-4000-8000-000000000003"
NOW = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)


def provider_request() -> ProviderRequest:
    return ProviderRequest(
        execution_identity="a" * 64,
        request_hash="b" * 64,
        provider="openai",
        model="gpt-5.6-sol",
        logical_input={"bundle": {"id": "bundle-1"}},
        reasoning_effort="medium",
        thinking_enabled=True,
        temperature="provider_default",
        input_token_cap=16_000,
        output_token_cap=2_000,
        execution_role="grader:moonshot",
        prompt_id="moonshot_grader_v1",
        prompt_version="moonshot_grader_v1",
        prompt_content_sha256="c" * 64,
        input_schema_version="grader-input-v1",
        output_schema_version="moonshot_grader_payload.v1",
        attempt_number=1,
        validation_errors=(),
    )


class RecordingStore:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.starts = []
        self.completions = []

    def begin(self, start):
        self.events.append("persist_request")
        self.starts.append(start)
        return InputTokenPreflightReceipt(
            preflight_id=start.preflight_id,
            state="pending",
            reused=False,
        )

    def complete(self, completion):
        self.events.append("persist_result")
        self.completions.append(completion)
        return InputTokenPreflightReceipt(
            preflight_id=completion.preflight_id,
            state=completion.state,
            reused=False,
        )


class RecordingJsonTransport:
    def __init__(self, responses) -> None:
        self.responses = iter(responses)
        self.requests = []

    def request_json(self, method, url, *, headers, payload=None):
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "payload": payload,
            }
        )
        return next(self.responses)


class CountingProvider:
    def __init__(self, events: list[str], *, input_tokens: int = 321) -> None:
        self.events = events
        self.input_tokens = input_tokens
        self.audit = {
            "method": "POST",
            "url": "https://api.openai.com/v1/responses/input_tokens",
            "headers": {
                "Authorization": "[REDACTED]",
                "Content-Type": "application/json",
            },
            "payload": {"model": "gpt-5.6-sol", "input": []},
        }

    def audit_input_token_count_request(self, request):
        return self.audit

    def count_input_tokens(self, request):
        self.events.append("count")
        payload_hash = hashlib.sha256(
            json.dumps(
                self.audit["payload"],
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest()
        return OpenAIInputTokenPreflight(
            execution_identity=request.execution_identity,
            request_hash=request.request_hash,
            model=request.model,
            input_payload_sha256=payload_hash,
            input_tokens=self.input_tokens,
            input_token_cap=request.input_token_cap,
            within_cap=self.input_tokens <= request.input_token_cap,
            raw_provider_response={
                "object": "response.input_tokens",
                "input_tokens": self.input_tokens,
            },
        )


class FailingCountingProvider(CountingProvider):
    def count_input_tokens(self, request):
        self.events.append("count")
        raise ProviderTransportError(
            "openai_input_token_count_timeout",
            retryable=True,
            category="timeout",
        )


class ReusingStore(RecordingStore):
    def begin(self, start):
        self.events.append("persist_request")
        self.starts.append(start)
        return InputTokenPreflightReceipt(
            preflight_id=start.preflight_id,
            state="pending",
            reused=True,
        )


class MismatchedCountingProvider(CountingProvider):
    def count_input_tokens(self, request):
        result = super().count_input_tokens(request)
        return OpenAIInputTokenPreflight(
            execution_identity=result.execution_identity,
            request_hash=result.request_hash,
            model="unexpected-model",
            input_payload_sha256=result.input_payload_sha256,
            input_tokens=result.input_tokens,
            input_token_cap=result.input_token_cap,
            within_cap=result.within_cap,
            raw_provider_response=result.raw_provider_response,
        )


class PersistentInputTokenPreflightGateTests(unittest.TestCase):
    def test_reused_pending_preflight_blocks_duplicate_count_dispatch(self) -> None:
        events: list[str] = []
        gate = PersistentInputTokenPreflightGate(
            store=ReusingStore(events),
            clock=lambda: NOW,
        )

        with self.assertRaisesRegex(
            InputTokenPreflightError,
            "already existed before token-count dispatch",
        ):
            gate.authorize(
                operator_id=OPERATOR_ID,
                research_run_id=RUN_ID,
                attempt_kind="grader",
                attempt_id=ATTEMPT_ID,
                request=provider_request(),
                provider=CountingProvider(events),
            )

        self.assertEqual(events, ["persist_request"])

    def test_identity_mismatch_is_persisted_as_nonretryable_failure(self) -> None:
        events: list[str] = []
        store = RecordingStore(events)
        gate = PersistentInputTokenPreflightGate(
            store=store,
            clock=lambda: NOW,
        )

        with self.assertRaises(ProviderTransportError) as raised:
            gate.authorize(
                operator_id=OPERATOR_ID,
                research_run_id=RUN_ID,
                attempt_kind="grader",
                attempt_id=ATTEMPT_ID,
                request=provider_request(),
                provider=MismatchedCountingProvider(events),
            )

        self.assertEqual(
            raised.exception.code,
            "input_token_preflight_identity_mismatch",
        )
        self.assertFalse(raised.exception.retryable)
        self.assertEqual(store.completions[0].state, "failed")
        self.assertEqual(
            store.completions[0].error_code,
            "input_token_preflight_identity_mismatch",
        )

    def test_persists_exact_request_and_result_before_generation_is_allowed(
        self,
    ) -> None:
        events: list[str] = []
        store = RecordingStore(events)
        provider = CountingProvider(events)
        request = provider_request()
        gate = PersistentInputTokenPreflightGate(
            store=store,
            clock=lambda: NOW,
        )

        result = gate.authorize(
            operator_id=OPERATOR_ID,
            research_run_id=RUN_ID,
            attempt_kind="grader",
            attempt_id=ATTEMPT_ID,
            request=request,
            provider=provider,
        )
        events.append("generation")

        self.assertTrue(result.within_cap)
        self.assertEqual(
            events,
            ["persist_request", "count", "persist_result", "generation"],
        )
        self.assertEqual(store.starts[0].request_payload, provider.audit)
        self.assertEqual(store.completions[0].input_tokens, 321)
        self.assertEqual(store.completions[0].state, "passed")

    def test_persists_over_cap_result_and_blocks_generation(self) -> None:
        events: list[str] = []
        store = RecordingStore(events)
        gate = PersistentInputTokenPreflightGate(
            store=store,
            clock=lambda: NOW,
        )

        with self.assertRaises(ProviderTransportError) as raised:
            gate.authorize(
                operator_id=OPERATOR_ID,
                research_run_id=RUN_ID,
                attempt_kind="synthesis",
                attempt_id=ATTEMPT_ID,
                request=provider_request(),
                provider=CountingProvider(events, input_tokens=16_001),
            )

        self.assertEqual(raised.exception.code, "input_token_cap_exceeded")
        self.assertFalse(raised.exception.retryable)
        self.assertEqual(raised.exception.category, "usage")
        self.assertEqual(events, ["persist_request", "count", "persist_result"])
        self.assertEqual(store.completions[0].state, "blocked")

    def test_persists_retryable_count_failure_before_reraising(self) -> None:
        events: list[str] = []
        store = RecordingStore(events)
        gate = PersistentInputTokenPreflightGate(
            store=store,
            clock=lambda: NOW,
        )

        with self.assertRaises(ProviderTransportError) as raised:
            gate.authorize(
                operator_id=OPERATOR_ID,
                research_run_id=RUN_ID,
                attempt_kind="grader",
                attempt_id=ATTEMPT_ID,
                request=provider_request(),
                provider=FailingCountingProvider(events),
            )

        self.assertEqual(
            raised.exception.code,
            "openai_input_token_count_timeout",
        )
        self.assertTrue(raised.exception.retryable)
        self.assertEqual(events, ["persist_request", "count", "persist_result"])
        self.assertEqual(store.completions[0].state, "failed")
        self.assertEqual(
            store.completions[0].error_code,
            "openai_input_token_count_timeout",
        )

    def test_supabase_store_maps_begin_and_complete_to_narrow_rpcs(self) -> None:
        events: list[str] = []
        domain_store = RecordingStore(events)
        provider = CountingProvider(events)
        request = provider_request()
        PersistentInputTokenPreflightGate(
            store=domain_store,
            clock=lambda: NOW,
        ).authorize(
            operator_id=OPERATOR_ID,
            research_run_id=RUN_ID,
            attempt_kind="grader",
            attempt_id=ATTEMPT_ID,
            request=request,
            provider=provider,
        )
        start = domain_store.starts[0]
        completion = domain_store.completions[0]
        transport = RecordingJsonTransport(
            (
                JsonResponse(
                    payload=[
                        {
                            "operator_id": OPERATOR_ID,
                            "preflight_id": start.preflight_id,
                            "state": "pending",
                            "reused": False,
                        }
                    ],
                    status=200,
                    headers={},
                ),
                JsonResponse(
                    payload=[
                        {
                            "operator_id": OPERATOR_ID,
                            "preflight_id": start.preflight_id,
                            "state": "passed",
                            "reused": False,
                        }
                    ],
                    status=200,
                    headers={},
                ),
            )
        )
        store = SupabaseInputTokenPreflightStore(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
        )

        begin_receipt = store.begin(start)
        completion_receipt = store.complete(completion)

        self.assertEqual(begin_receipt.state, "pending")
        self.assertEqual(completion_receipt.state, "passed")
        self.assertTrue(
            transport.requests[0]["url"].endswith(
                "/rest/v1/rpc/iros_begin_provider_input_token_preflight"
            )
        )
        self.assertTrue(
            transport.requests[1]["url"].endswith(
                "/rest/v1/rpc/iros_complete_provider_input_token_preflight"
            )
        )
        self.assertEqual(
            transport.requests[0]["payload"]["p_sanitized_request"],
            start.request_payload,
        )
        self.assertEqual(
            transport.requests[1]["payload"]["p_sanitized_response"],
            completion.response_payload,
        )

    def test_supabase_store_rejects_multirow_receipt(self) -> None:
        events: list[str] = []
        domain_store = RecordingStore(events)
        PersistentInputTokenPreflightGate(
            store=domain_store,
            clock=lambda: NOW,
        ).authorize(
            operator_id=OPERATOR_ID,
            research_run_id=RUN_ID,
            attempt_kind="grader",
            attempt_id=ATTEMPT_ID,
            request=provider_request(),
            provider=CountingProvider(events),
        )
        start = domain_store.starts[0]
        row = {
            "operator_id": OPERATOR_ID,
            "preflight_id": start.preflight_id,
            "state": "pending",
            "reused": False,
        }
        store = SupabaseInputTokenPreflightStore(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=RecordingJsonTransport(
                (
                    JsonResponse(
                        payload=[row, row],
                        status=200,
                        headers={},
                    ),
                )
            ),
        )

        with self.assertRaisesRegex(
            InputTokenPreflightStorageError,
            "malformed response",
        ):
            store.begin(start)


if __name__ == "__main__":
    unittest.main()

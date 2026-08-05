from __future__ import annotations

import hashlib
import json
import unittest

from investment_research_os.grader_executions import (
    ProviderRequest,
    ProviderTransportError,
)
from investment_research_os.production_execution import PromptTemplate
from investment_research_os.providers.openai_responses import (
    OpenAIHttpResponse,
    OpenAIInputTokenPreflight,
    OpenAIResponseContract,
    OpenAIResponsesProvider,
)


class TransportFake:
    def __init__(self, response: OpenAIHttpResponse) -> None:
        self.response = response
        self.requests = []

    def post_json(self, url, *, headers, payload):
        self.requests.append((url, headers, payload))
        return self.response


class RaisingTransport:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def post_json(self, url, *, headers, payload):
        raise self.error


def frozen_prompt() -> PromptTemplate:
    return PromptTemplate.freeze(
        prompt_id="moonshot_grader_v1",
        prompt_version="moonshot_grader_v1",
        execution_role="grader:moonshot",
        input_schema_version="grader-input-v1",
        output_schema_version="moonshot_grader_payload.v1",
        system_instructions=("Use frozen evidence only.",),
        task_template="Assess asymmetric research case.",
    )


def response_contract() -> OpenAIResponseContract:
    prompt = frozen_prompt()
    return OpenAIResponseContract(
        execution_role=prompt.execution_role,
        prompt_id=prompt.prompt_id,
        prompt_version=prompt.prompt_version,
        prompt_content_sha256=prompt.content_sha256,
        input_schema_version=prompt.input_schema_version,
        output_schema_version=prompt.output_schema_version,
        system_instructions=prompt.system_instructions,
        task_template=prompt.task_template,
        output_schema_name="moonshot_grader_payload_v1",
        output_schema={
            "type": "object",
            "properties": {
                "execution_state": {
                    "type": "string",
                    "enum": ["accepted"],
                }
            },
            "required": ["execution_state"],
            "additionalProperties": False,
        },
    )


def provider_request() -> ProviderRequest:
    prompt = frozen_prompt()
    return ProviderRequest(
        execution_identity="b" * 64,
        request_hash="c" * 64,
        provider="openai",
        model="gpt-5.6-sol",
        logical_input={"bundle": {"id": "bundle-1"}},
        reasoning_effort="medium",
        thinking_enabled=True,
        temperature="provider_default",
        input_token_cap=16_000,
        output_token_cap=2_000,
        execution_role="grader:moonshot",
        prompt_id=prompt.prompt_id,
        prompt_version=prompt.prompt_version,
        prompt_content_sha256=prompt.content_sha256,
        input_schema_version=prompt.input_schema_version,
        output_schema_version=prompt.output_schema_version,
        attempt_number=1,
        validation_errors=(),
    )


class OpenAIResponsesProviderTests(unittest.TestCase):
    def test_counts_exact_frozen_request_before_response_generation(self) -> None:
        transport = TransportFake(
            OpenAIHttpResponse(
                status=200,
                headers={"x-request-id": "req_tokens_123"},
                payload={
                    "object": "response.input_tokens",
                    "input_tokens": 321,
                },
            )
        )
        provider = OpenAIResponsesProvider(
            api_key="sk-test-not-real",
            contract_resolver=lambda request: response_contract(),
            transport=transport,
        )
        request = provider_request()

        audit_request = provider.audit_input_token_count_request(request)
        preflight = provider.count_input_tokens(request)
        payload_sha256 = hashlib.sha256(
            json.dumps(
                audit_request["payload"],
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest()

        self.assertEqual(
            preflight,
            OpenAIInputTokenPreflight(
                execution_identity=request.execution_identity,
                request_hash=request.request_hash,
                model=request.model,
                input_payload_sha256=payload_sha256,
                input_tokens=321,
                input_token_cap=16_000,
                within_cap=True,
                raw_provider_response={
                    "object": "response.input_tokens",
                    "input_tokens": 321,
                },
            ),
        )
        self.assertEqual(len(transport.requests), 1)
        url, headers, payload = transport.requests[0]
        self.assertEqual(
            url,
            "https://api.openai.com/v1/responses/input_tokens",
        )
        self.assertEqual(headers["Authorization"], "Bearer sk-test-not-real")
        self.assertEqual(
            audit_request,
            {
                "method": "POST",
                "url": "https://api.openai.com/v1/responses/input_tokens",
                "headers": {
                    "Authorization": "[REDACTED]",
                    "Content-Type": "application/json",
                },
                "payload": payload,
            },
        )
        self.assertEqual(payload["model"], request.model)
        self.assertEqual(
            payload["input"],
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": '{"bundle":{"id":"bundle-1"}}',
                        }
                    ],
                }
            ],
        )
        self.assertIn("instructions", payload)
        self.assertIn("reasoning", payload)
        self.assertIn("text", payload)
        self.assertEqual(payload["tools"], [])
        self.assertEqual(payload["tool_choice"], "none")
        self.assertNotIn("max_output_tokens", payload)
        self.assertNotIn("store", payload)
        self.assertNotIn("background", payload)

    def test_input_token_preflight_reports_cap_failure_without_generation(self) -> None:
        transport = TransportFake(
            OpenAIHttpResponse(
                status=200,
                headers={},
                payload={
                    "object": "response.input_tokens",
                    "input_tokens": 16_001,
                },
            )
        )
        provider = OpenAIResponsesProvider(
            api_key="sk-test-not-real",
            contract_resolver=lambda request: response_contract(),
            transport=transport,
        )

        preflight = provider.count_input_tokens(provider_request())

        self.assertEqual(preflight.input_tokens, 16_001)
        self.assertEqual(preflight.input_token_cap, 16_000)
        self.assertFalse(preflight.within_cap)
        self.assertEqual(
            [url for url, _, _ in transport.requests],
            ["https://api.openai.com/v1/responses/input_tokens"],
        )

    def test_input_token_timeout_is_explicit_and_retryable(self) -> None:
        provider = OpenAIResponsesProvider(
            api_key="sk-test-not-real",
            contract_resolver=lambda request: response_contract(),
            transport=RaisingTransport(TimeoutError("timed out")),
        )

        with self.assertRaises(ProviderTransportError) as raised:
            provider.count_input_tokens(provider_request())

        self.assertEqual(
            raised.exception.code,
            "openai_input_token_count_timeout",
        )
        self.assertEqual(raised.exception.category, "timeout")
        self.assertTrue(raised.exception.retryable)

    def test_input_token_http_status_has_explicit_retry_policy(self) -> None:
        cases = ((400, False), (429, True), (503, True))

        for status, retryable in cases:
            with self.subTest(status=status):
                provider = OpenAIResponsesProvider(
                    api_key="sk-test-not-real",
                    contract_resolver=lambda request: response_contract(),
                    transport=TransportFake(
                        OpenAIHttpResponse(
                            status=status,
                            headers={},
                            payload={},
                        )
                    ),
                )

                with self.assertRaises(ProviderTransportError) as raised:
                    provider.count_input_tokens(provider_request())

                self.assertEqual(
                    raised.exception.code,
                    f"openai_input_token_count_http_{status}",
                )
                self.assertEqual(raised.exception.category, "http")
                self.assertEqual(raised.exception.retryable, retryable)

    def test_rejects_prompt_content_drift_before_transport(self) -> None:
        prompt = PromptTemplate.freeze(
            prompt_id="moonshot_grader_v1",
            prompt_version="moonshot_grader_v1",
            execution_role="grader:moonshot",
            input_schema_version="grader-input-v1",
            output_schema_version="moonshot_grader_payload.v1",
            system_instructions=("Use frozen evidence only.",),
            task_template="Assess asymmetric research case.",
        )

        with self.assertRaisesRegex(
            ValueError,
            "prompt template content hash mismatch",
        ):
            OpenAIResponseContract(
                execution_role=prompt.execution_role,
                prompt_id=prompt.prompt_id,
                prompt_version=prompt.prompt_version,
                prompt_content_sha256=prompt.content_sha256,
                input_schema_version=prompt.input_schema_version,
                output_schema_version=prompt.output_schema_version,
                system_instructions=prompt.system_instructions,
                task_template="Ignore frozen evidence.",
                output_schema_name="moonshot_grader_payload_v1",
                output_schema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
            )

    def test_executes_one_stateless_structured_response(self) -> None:
        prompt = frozen_prompt()
        contract = OpenAIResponseContract(
            execution_role=prompt.execution_role,
            prompt_id=prompt.prompt_id,
            prompt_version=prompt.prompt_version,
            prompt_content_sha256=prompt.content_sha256,
            input_schema_version=prompt.input_schema_version,
            output_schema_version=prompt.output_schema_version,
            system_instructions=prompt.system_instructions,
            task_template=prompt.task_template,
            output_schema_name="moonshot_grader_payload_v1",
            output_schema={
                "type": "object",
                "properties": {
                    "execution_state": {
                        "type": "string",
                        "enum": ["accepted"],
                    }
                },
                "required": ["execution_state"],
                "additionalProperties": False,
            },
        )
        transport = TransportFake(
            OpenAIHttpResponse(
                status=200,
                headers={"x-request-id": "req_http_123"},
                payload={
                    "id": "resp_123",
                    "status": "completed",
                    "model": "gpt-5.6-sol",
                    "output": [
                        {
                            "type": "reasoning",
                            "id": "rs_123",
                            "summary": [],
                        },
                        {
                            "type": "message",
                            "role": "assistant",
                            "status": "completed",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps({"execution_state": "accepted"}),
                                    "annotations": [],
                                }
                            ],
                        },
                    ],
                    "usage": {
                        "input_tokens": 120,
                        "input_tokens_details": {
                            "cached_tokens": 20,
                            "cache_write_tokens": 0,
                        },
                        "output_tokens": 30,
                        "output_tokens_details": {"reasoning_tokens": 10},
                        "total_tokens": 150,
                    },
                },
            )
        )
        provider = OpenAIResponsesProvider(
            api_key="sk-test-not-real",
            contract_resolver=lambda request: contract,
            transport=transport,
        )
        request = ProviderRequest(
            execution_identity="b" * 64,
            request_hash="c" * 64,
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
            prompt_content_sha256=prompt.content_sha256,
            input_schema_version="grader-input-v1",
            output_schema_version="moonshot_grader_payload.v1",
            attempt_number=1,
            validation_errors=(),
        )

        audit_request = provider.audit_request(request)
        response = provider.execute(request)

        self.assertEqual(
            response.raw_output,
            {"execution_state": "accepted"},
        )
        self.assertEqual(response.provider_request_id, "resp_123")
        self.assertEqual(response.resolved_model, "gpt-5.6-sol")
        self.assertEqual(response.usage.input_tokens, 120)
        self.assertEqual(response.usage.cached_input_tokens, 20)
        self.assertEqual(response.usage.reasoning_tokens, 10)
        self.assertEqual(response.usage.total_tokens, 150)
        self.assertEqual(response.raw_provider_response, transport.response.payload)

        url, headers, payload = transport.requests[0]
        self.assertEqual(url, "https://api.openai.com/v1/responses")
        self.assertEqual(headers["Authorization"], "Bearer sk-test-not-real")
        self.assertEqual(
            audit_request,
            {
                "method": "POST",
                "url": "https://api.openai.com/v1/responses",
                "headers": {
                    "Authorization": "[REDACTED]",
                    "Content-Type": "application/json",
                },
                "payload": payload,
            },
        )
        self.assertEqual(
            payload,
            {
                "model": "gpt-5.6-sol",
                "instructions": (
                    "Use frozen evidence only.\n\nAssess asymmetric research case."
                ),
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": '{"bundle":{"id":"bundle-1"}}',
                            }
                        ],
                    }
                ],
                "reasoning": {"effort": "medium"},
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "moonshot_grader_payload_v1",
                        "strict": True,
                        "schema": contract.output_schema,
                    }
                },
                "max_output_tokens": 2_000,
                "store": False,
                "background": False,
                "tools": [],
                "tool_choice": "none",
            },
        )

    def test_schema_version_mismatch_blocks_before_transport(self) -> None:
        prompt = frozen_prompt()
        contract = OpenAIResponseContract(
            execution_role=prompt.execution_role,
            prompt_id=prompt.prompt_id,
            prompt_version=prompt.prompt_version,
            prompt_content_sha256=prompt.content_sha256,
            input_schema_version=prompt.input_schema_version,
            output_schema_version=prompt.output_schema_version,
            system_instructions=prompt.system_instructions,
            task_template=prompt.task_template,
            output_schema_name="moonshot_grader_payload_v1",
            output_schema={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        )
        transport = TransportFake(
            OpenAIHttpResponse(status=500, headers={}, payload={})
        )
        provider = OpenAIResponsesProvider(
            api_key="sk-test-not-real",
            contract_resolver=lambda request: contract,
            transport=transport,
        )
        request = ProviderRequest(
            execution_identity="b" * 64,
            request_hash="c" * 64,
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
            prompt_content_sha256=prompt.content_sha256,
            input_schema_version="grader-input-v1",
            output_schema_version="different-schema.v1",
            attempt_number=1,
            validation_errors=(),
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "openai_prompt_contract_mismatch",
        ):
            provider.execute(request)

        self.assertEqual(transport.requests, [])

    def test_refusal_is_explicit_and_nonretryable(self) -> None:
        transport = TransportFake(
            OpenAIHttpResponse(
                status=200,
                headers={},
                payload={
                    "id": "resp_refusal",
                    "status": "completed",
                    "model": "gpt-5.6-sol",
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "status": "completed",
                            "content": [
                                {
                                    "type": "refusal",
                                    "refusal": "I cannot provide this output.",
                                }
                            ],
                        }
                    ],
                    "usage": {
                        "input_tokens": 10,
                        "input_tokens_details": {
                            "cached_tokens": 0,
                            "cache_write_tokens": 0,
                        },
                        "output_tokens": 2,
                        "output_tokens_details": {"reasoning_tokens": 0},
                        "total_tokens": 12,
                    },
                },
            )
        )
        provider = OpenAIResponsesProvider(
            api_key="sk-test-not-real",
            contract_resolver=lambda request: response_contract(),
            transport=transport,
        )

        with self.assertRaises(ProviderTransportError) as raised:
            provider.execute(provider_request())

        self.assertEqual(raised.exception.code, "openai_response_refusal")
        self.assertEqual(raised.exception.category, "refusal")
        self.assertFalse(raised.exception.retryable)

    def test_http_status_has_explicit_retry_policy(self) -> None:
        cases = ((400, False), (401, False), (429, True), (503, True))

        for status, retryable in cases:
            with self.subTest(status=status):
                provider = OpenAIResponsesProvider(
                    api_key="sk-test-not-real",
                    contract_resolver=lambda request: response_contract(),
                    transport=TransportFake(
                        OpenAIHttpResponse(
                            status=status,
                            headers={},
                            payload={},
                        )
                    ),
                )

                with self.assertRaises(ProviderTransportError) as raised:
                    provider.execute(provider_request())

                self.assertEqual(
                    raised.exception.code,
                    f"openai_http_{status}",
                )
                self.assertEqual(raised.exception.category, "http")
                self.assertEqual(raised.exception.retryable, retryable)

    def test_transport_exception_has_explicit_retryable_taxonomy(self) -> None:
        cases = (
            (TimeoutError("timed out"), "openai_transport_timeout", "timeout"),
            (OSError("connection reset"), "openai_transport_error", "transport"),
        )

        for error, code, category in cases:
            with self.subTest(category=category):
                provider = OpenAIResponsesProvider(
                    api_key="sk-test-not-real",
                    contract_resolver=lambda request: response_contract(),
                    transport=RaisingTransport(error),
                )

                with self.assertRaises(ProviderTransportError) as raised:
                    provider.execute(provider_request())

                self.assertEqual(raised.exception.code, code)
                self.assertEqual(raised.exception.category, category)
                self.assertTrue(raised.exception.retryable)

    def test_invalid_response_states_have_distinct_nonretryable_taxonomy(
        self,
    ) -> None:
        message = {
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": "{"}],
        }
        cases = (
            (
                {
                    "id": "resp_incomplete",
                    "status": "incomplete",
                    "model": "gpt-5.6-sol",
                    "incomplete_details": {"reason": "max_output_tokens"},
                    "output": [],
                },
                "openai_response_incomplete",
                "incomplete",
            ),
            (
                {
                    "id": "resp_bad_json",
                    "status": "completed",
                    "model": "gpt-5.6-sol",
                    "output": [message],
                },
                "openai_response_json_invalid",
                "malformed_json",
            ),
            (
                {
                    "id": "resp_unsupported",
                    "status": "completed",
                    "model": "gpt-5.6-sol",
                    "output": [
                        message,
                        {"type": "file_search_call", "id": "call_1"},
                    ],
                },
                "openai_response_output_unsupported",
                "unsupported_output",
            ),
        )

        for payload, code, category in cases:
            payload["usage"] = {
                "input_tokens": 10,
                "input_tokens_details": {
                    "cached_tokens": 0,
                    "cache_write_tokens": 0,
                },
                "output_tokens": 2,
                "output_tokens_details": {"reasoning_tokens": 0},
                "total_tokens": 12,
            }
            with self.subTest(category=category):
                provider = OpenAIResponsesProvider(
                    api_key="sk-test-not-real",
                    contract_resolver=lambda request: response_contract(),
                    transport=TransportFake(
                        OpenAIHttpResponse(
                            status=200,
                            headers={},
                            payload=payload,
                        )
                    ),
                )

                with self.assertRaises(ProviderTransportError) as raised:
                    provider.execute(provider_request())

                self.assertEqual(raised.exception.code, code)
                self.assertEqual(raised.exception.category, category)
                self.assertFalse(raised.exception.retryable)

    def test_usage_rejects_coercion_negative_and_inconsistent_counts(self) -> None:
        valid = {
            "input_tokens": 10,
            "input_tokens_details": {
                "cached_tokens": 2,
                "cache_write_tokens": 1,
            },
            "output_tokens": 4,
            "output_tokens_details": {"reasoning_tokens": 1},
            "total_tokens": 14,
        }
        invalid_values = []
        for field, value in (
            ("input_tokens", True),
            ("input_tokens", 10.5),
            ("input_tokens", "10"),
            ("input_tokens", -1),
            ("total_tokens", 99),
        ):
            usage = json.loads(json.dumps(valid))
            usage[field] = value
            invalid_values.append(usage)
        invalid_partition = json.loads(json.dumps(valid))
        invalid_partition["input_tokens_details"]["cached_tokens"] = 10
        invalid_partition["input_tokens_details"]["cache_write_tokens"] = 1
        invalid_values.append(invalid_partition)
        invalid_reasoning = json.loads(json.dumps(valid))
        invalid_reasoning["output_tokens_details"]["reasoning_tokens"] = 5
        invalid_values.append(invalid_reasoning)

        for usage in invalid_values:
            with self.subTest(usage=usage):
                payload = {
                    "id": "resp_usage",
                    "status": "completed",
                    "model": "gpt-5.6-sol",
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "status": "completed",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps({"execution_state": "accepted"}),
                                }
                            ],
                        }
                    ],
                    "usage": usage,
                }
                provider = OpenAIResponsesProvider(
                    api_key="sk-test-not-real",
                    contract_resolver=lambda request: response_contract(),
                    transport=TransportFake(
                        OpenAIHttpResponse(
                            status=200,
                            headers={},
                            payload=payload,
                        )
                    ),
                )

                with self.assertRaises(ProviderTransportError) as raised:
                    provider.execute(provider_request())

                self.assertEqual(raised.exception.code, "openai_usage_invalid")
                self.assertEqual(raised.exception.category, "usage")
                self.assertFalse(raised.exception.retryable)


if __name__ == "__main__":
    unittest.main()

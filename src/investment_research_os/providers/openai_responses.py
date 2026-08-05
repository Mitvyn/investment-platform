from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Callable, Mapping, Protocol

from investment_research_os.grader_executions import (
    ProviderRequest,
    ProviderResponse,
    ProviderTransportError,
    ProviderUsage,
)
from investment_research_os.production_execution import PromptTemplate


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SCHEMA_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass(frozen=True, slots=True)
class OpenAIResponseContract:
    execution_role: str
    prompt_id: str
    prompt_version: str
    prompt_content_sha256: str
    input_schema_version: str
    output_schema_version: str
    system_instructions: tuple[str, ...]
    task_template: str
    output_schema_name: str
    output_schema: Mapping[str, object]

    def __post_init__(self) -> None:
        PromptTemplate.from_dict(
            {
                "contract_version": "prompt_template.v1",
                "prompt_id": self.prompt_id,
                "prompt_version": self.prompt_version,
                "execution_role": self.execution_role,
                "input_schema_version": self.input_schema_version,
                "output_schema_version": self.output_schema_version,
                "system_instructions": list(self.system_instructions),
                "task_template": self.task_template,
                "content_sha256": self.prompt_content_sha256,
            }
        )


@dataclass(frozen=True, slots=True)
class OpenAIHttpResponse:
    status: int
    payload: Mapping[str, object]
    headers: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class OpenAIInputTokenPreflight:
    execution_identity: str
    request_hash: str
    model: str
    input_payload_sha256: str
    input_tokens: int
    input_token_cap: int
    within_cap: bool
    raw_provider_response: Mapping[str, object]


class OpenAIHttpTransport(Protocol):
    def post_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
    ) -> OpenAIHttpResponse: ...


class OpenAIResponsesProvider:
    """Maps one pinned role contract onto an injected Responses transport."""

    def __init__(
        self,
        *,
        api_key: str,
        contract_resolver: Callable[[ProviderRequest], OpenAIResponseContract],
        transport: OpenAIHttpTransport,
        base_url: str = "https://api.openai.com/v1",
    ) -> None:
        if not api_key.strip():
            raise ValueError("OpenAI API key is required")
        if base_url != "https://api.openai.com/v1":
            raise ValueError("OpenAI Responses base URL is not approved")
        self._api_key = api_key.strip()
        self._contract_resolver = contract_resolver
        self._transport = transport
        self._base_url = base_url

    def execute(self, request: ProviderRequest) -> ProviderResponse:
        contract = self._contract_resolver(request)
        self._validate_contract(request, contract)
        payload = self._request_payload(request, contract)
        try:
            response = self._transport.post_json(
                f"{self._base_url}/responses",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                payload=payload,
            )
        except TimeoutError as error:
            raise ProviderTransportError(
                "openai_transport_timeout",
                retryable=True,
                category="timeout",
            ) from error
        except OSError as error:
            raise ProviderTransportError(
                "openai_transport_error",
                retryable=True,
                category="transport",
            ) from error
        if not 200 <= response.status < 300:
            raise ProviderTransportError(
                f"openai_http_{response.status}",
                retryable=(
                    response.status in {408, 409, 429} or 500 <= response.status < 600
                ),
                category="http",
            )
        return self._map_response(response.payload)

    def audit_request(self, request: ProviderRequest) -> Mapping[str, object]:
        contract = self._contract_resolver(request)
        self._validate_contract(request, contract)
        return {
            "method": "POST",
            "url": f"{self._base_url}/responses",
            "headers": {
                "Authorization": "[REDACTED]",
                "Content-Type": "application/json",
            },
            "payload": self._request_payload(request, contract),
        }

    def audit_input_token_count_request(
        self,
        request: ProviderRequest,
    ) -> Mapping[str, object]:
        contract = self._contract_resolver(request)
        self._validate_contract(request, contract)
        return {
            "method": "POST",
            "url": f"{self._base_url}/responses/input_tokens",
            "headers": {
                "Authorization": "[REDACTED]",
                "Content-Type": "application/json",
            },
            "payload": self._input_token_count_payload(request, contract),
        }

    def count_input_tokens(
        self,
        request: ProviderRequest,
    ) -> OpenAIInputTokenPreflight:
        contract = self._contract_resolver(request)
        self._validate_contract(request, contract)
        payload = self._input_token_count_payload(request, contract)
        try:
            response = self._transport.post_json(
                f"{self._base_url}/responses/input_tokens",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                payload=payload,
            )
        except TimeoutError as error:
            raise ProviderTransportError(
                "openai_input_token_count_timeout",
                retryable=True,
                category="timeout",
            ) from error
        except OSError as error:
            raise ProviderTransportError(
                "openai_input_token_count_transport_error",
                retryable=True,
                category="transport",
            ) from error
        if not 200 <= response.status < 300:
            raise ProviderTransportError(
                f"openai_input_token_count_http_{response.status}",
                retryable=(
                    response.status in {408, 409, 429} or 500 <= response.status < 600
                ),
                category="http",
            )
        input_tokens = response.payload.get("input_tokens")
        if (
            response.payload.get("object") != "response.input_tokens"
            or type(input_tokens) is not int
            or input_tokens < 0
        ):
            raise ProviderTransportError(
                "openai_input_token_count_invalid",
                retryable=False,
                category="usage",
            )
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
            input_tokens=input_tokens,
            input_token_cap=request.input_token_cap,
            within_cap=input_tokens <= request.input_token_cap,
            raw_provider_response=response.payload,
        )

    @staticmethod
    def _validate_contract(
        request: ProviderRequest,
        contract: OpenAIResponseContract,
    ) -> None:
        if request.provider != "openai":
            raise ProviderTransportError(
                "openai_provider_mismatch",
                retryable=False,
                category="contract",
            )
        if (
            contract.execution_role != request.execution_role
            or contract.prompt_id != request.prompt_id
            or contract.prompt_version != request.prompt_version
            or contract.prompt_content_sha256 != request.prompt_content_sha256
            or contract.input_schema_version != request.input_schema_version
            or contract.output_schema_version != request.output_schema_version
            or SHA256_PATTERN.fullmatch(contract.prompt_content_sha256) is None
        ):
            raise ProviderTransportError(
                "openai_prompt_contract_mismatch",
                retryable=False,
                category="contract",
            )
        if (
            not contract.system_instructions
            or any(not item.strip() for item in contract.system_instructions)
            or not contract.task_template.strip()
            or SCHEMA_NAME_PATTERN.fullmatch(contract.output_schema_name) is None
            or contract.output_schema.get("type") != "object"
            or contract.output_schema.get("additionalProperties") is not False
        ):
            raise ProviderTransportError(
                "openai_output_contract_invalid",
                retryable=False,
                category="contract",
            )
        if request.temperature != "provider_default":
            raise ProviderTransportError(
                "openai_temperature_unsupported",
                retryable=False,
                category="contract",
            )
        if not request.thinking_enabled:
            raise ProviderTransportError(
                "openai_reasoning_configuration_invalid",
                retryable=False,
                category="contract",
            )

    @staticmethod
    def _request_payload(
        request: ProviderRequest,
        contract: OpenAIResponseContract,
    ) -> dict[str, object]:
        logical_input = json.dumps(
            request.logical_input,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return {
            "model": request.model,
            "instructions": (
                "\n".join(contract.system_instructions)
                + "\n\n"
                + contract.task_template
            ),
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": logical_input,
                        }
                    ],
                }
            ],
            "reasoning": {"effort": request.reasoning_effort},
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": contract.output_schema_name,
                    "strict": True,
                    "schema": contract.output_schema,
                }
            },
            "max_output_tokens": request.output_token_cap,
            "store": False,
            "background": False,
            "tools": [],
            "tool_choice": "none",
        }

    @classmethod
    def _input_token_count_payload(
        cls,
        request: ProviderRequest,
        contract: OpenAIResponseContract,
    ) -> dict[str, object]:
        response_payload = cls._request_payload(request, contract)
        return {
            key: response_payload[key]
            for key in (
                "model",
                "instructions",
                "input",
                "reasoning",
                "text",
                "tools",
                "tool_choice",
            )
        }

    @staticmethod
    def _map_response(payload: Mapping[str, object]) -> ProviderResponse:
        if payload.get("status") == "incomplete":
            raise ProviderTransportError(
                "openai_response_incomplete",
                retryable=False,
                category="incomplete",
            )
        if (
            payload.get("status") != "completed"
            or not isinstance(payload.get("id"), str)
            or not payload["id"]
            or not isinstance(payload.get("model"), str)
            or not payload["model"]
        ):
            raise ProviderTransportError(
                "openai_response_invalid",
                retryable=False,
                category="invalid_response",
            )
        output = payload.get("output")
        if not isinstance(output, list):
            raise ProviderTransportError(
                "openai_response_output_invalid",
                retryable=False,
                category="invalid_output",
            )
        messages = [
            item
            for item in output
            if isinstance(item, Mapping) and item.get("type") == "message"
        ]
        unsupported_items = [
            item
            for item in output
            if not (
                isinstance(item, Mapping)
                and item.get("type") in {"message", "reasoning"}
            )
        ]
        if unsupported_items:
            raise ProviderTransportError(
                "openai_response_output_unsupported",
                retryable=False,
                category="unsupported_output",
            )
        if len(messages) != 1:
            raise ProviderTransportError(
                "openai_response_output_invalid",
                retryable=False,
                category="invalid_output",
            )
        content = messages[0].get("content")
        if not isinstance(content, list):
            raise ProviderTransportError(
                "openai_response_output_invalid",
                retryable=False,
                category="invalid_output",
            )
        refusals = [
            item.get("refusal")
            for item in content
            if isinstance(item, Mapping) and item.get("type") == "refusal"
        ]
        if len(refusals) == 1 and isinstance(refusals[0], str):
            raise ProviderTransportError(
                "openai_response_refusal",
                retryable=False,
                category="refusal",
            )
        output_text = [
            item.get("text")
            for item in content
            if isinstance(item, Mapping) and item.get("type") == "output_text"
        ]
        if len(output_text) != 1 or not isinstance(output_text[0], str):
            raise ProviderTransportError(
                "openai_response_output_invalid",
                retryable=False,
                category="invalid_output",
            )
        try:
            raw_output = json.loads(output_text[0])
        except json.JSONDecodeError as error:
            raise ProviderTransportError(
                "openai_response_json_invalid",
                retryable=False,
                category="malformed_json",
            ) from error
        if not isinstance(raw_output, dict):
            raise ProviderTransportError(
                "openai_response_json_invalid",
                retryable=False,
                category="malformed_json",
            )
        usage = OpenAIResponsesProvider._usage(payload.get("usage"))
        return ProviderResponse(
            provider_request_id=str(payload["id"]),
            raw_output=raw_output,
            usage=usage,
            resolved_model=str(payload["model"]),
            system_fingerprint=(
                None
                if payload.get("system_fingerprint") is None
                else str(payload["system_fingerprint"])
            ),
            raw_provider_response=payload,
        )

    @staticmethod
    def _usage(value: object) -> ProviderUsage:
        if not isinstance(value, Mapping):
            raise ProviderTransportError(
                "openai_usage_invalid",
                retryable=False,
                category="usage",
            )
        input_details = value.get("input_tokens_details")
        output_details = value.get("output_tokens_details")
        if not isinstance(input_details, Mapping) or not isinstance(
            output_details,
            Mapping,
        ):
            raise ProviderTransportError(
                "openai_usage_invalid",
                retryable=False,
                category="usage",
            )
        try:
            counts = {
                "input_tokens": value["input_tokens"],
                "cached_input_tokens": input_details["cached_tokens"],
                "cache_write_tokens": input_details["cache_write_tokens"],
                "output_tokens": value["output_tokens"],
                "reasoning_tokens": output_details["reasoning_tokens"],
                "total_tokens": value["total_tokens"],
            }
            if any(type(count) is not int or count < 0 for count in counts.values()):
                raise ValueError("usage counts must be nonnegative integers")
            if (
                counts["cached_input_tokens"] + counts["cache_write_tokens"]
                > counts["input_tokens"]
                or counts["reasoning_tokens"] > counts["output_tokens"]
                or counts["total_tokens"]
                != counts["input_tokens"] + counts["output_tokens"]
            ):
                raise ValueError("usage counts are inconsistent")
            return ProviderUsage(
                input_tokens=counts["input_tokens"],
                cached_input_tokens=counts["cached_input_tokens"],
                cache_write_tokens=counts["cache_write_tokens"],
                output_tokens=counts["output_tokens"],
                reasoning_tokens=counts["reasoning_tokens"],
                total_tokens=counts["total_tokens"],
                tool_call_count=0,
                usage_complete=True,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ProviderTransportError(
                "openai_usage_invalid",
                retryable=False,
                category="usage",
            ) from error


__all__ = [
    "OpenAIHttpResponse",
    "OpenAIHttpTransport",
    "OpenAIInputTokenPreflight",
    "OpenAIResponseContract",
    "OpenAIResponsesProvider",
]

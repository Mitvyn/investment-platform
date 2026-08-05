from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re
from typing import Callable, Mapping, Protocol
import uuid

from investment_research_os.grader_executions import (
    ProviderRequest,
    ProviderTransportError,
    _without_reasoning_content,
)
from investment_research_os.ids import stable_id


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class InputTokenPreflightError(RuntimeError):
    """Raised when durable input-token preflight state is inconsistent."""


class InputTokenCountResult(Protocol):
    execution_identity: str
    request_hash: str
    model: str
    input_payload_sha256: str
    input_tokens: int
    input_token_cap: int
    within_cap: bool
    raw_provider_response: Mapping[str, object]


class InputTokenCountingProvider(Protocol):
    def audit_input_token_count_request(
        self,
        request: ProviderRequest,
    ) -> Mapping[str, object]: ...

    def count_input_tokens(
        self,
        request: ProviderRequest,
    ) -> InputTokenCountResult: ...


@dataclass(frozen=True, slots=True)
class InputTokenPreflightStart:
    preflight_id: str
    operator_id: str
    research_run_id: str
    attempt_kind: str
    attempt_id: str
    execution_identity: str
    request_hash: str
    provider: str
    model: str
    input_payload_sha256: str
    input_token_cap: int
    request_payload: Mapping[str, object]
    started_at: datetime

    def __post_init__(self) -> None:
        _uuid(self.preflight_id)
        _uuid(self.operator_id)
        _uuid(self.research_run_id)
        _uuid(self.attempt_id)
        if self.attempt_kind not in {"grader", "synthesis"}:
            raise InputTokenPreflightError("preflight attempt kind is invalid")
        for value in (
            self.execution_identity,
            self.request_hash,
            self.input_payload_sha256,
        ):
            _sha256(value)
        if self.provider != "openai" or not self.model.strip():
            raise InputTokenPreflightError("preflight provider identity is invalid")
        if (
            not isinstance(self.input_token_cap, int)
            or isinstance(self.input_token_cap, bool)
            or self.input_token_cap <= 0
        ):
            raise InputTokenPreflightError("preflight token cap is invalid")
        request = _safe_payload(self.request_payload)
        if (
            request.get("method") != "POST"
            or not str(request.get("url", "")).startswith("https://")
            or not isinstance(request.get("payload"), Mapping)
        ):
            raise InputTokenPreflightError("preflight audit request is invalid")
        headers = request.get("headers")
        if not isinstance(headers, Mapping) or headers.get("Authorization") != (
            "[REDACTED]"
        ):
            raise InputTokenPreflightError("preflight audit request is not redacted")
        if _payload_sha256(request["payload"]) != self.input_payload_sha256:
            raise InputTokenPreflightError("preflight request hash mismatch")
        object.__setattr__(self, "request_payload", request)
        object.__setattr__(self, "started_at", _timestamp(self.started_at))


@dataclass(frozen=True, slots=True)
class InputTokenPreflightCompletion:
    preflight_id: str
    operator_id: str
    state: str
    input_tokens: int | None
    within_cap: bool | None
    response_payload: Mapping[str, object] | None
    error_code: str | None
    retryable: bool | None
    completed_at: datetime

    def __post_init__(self) -> None:
        _uuid(self.preflight_id)
        _uuid(self.operator_id)
        if self.state not in {"passed", "blocked", "failed"}:
            raise InputTokenPreflightError("preflight completion state is invalid")
        if self.state in {"passed", "blocked"}:
            if (
                not isinstance(self.input_tokens, int)
                or isinstance(self.input_tokens, bool)
                or self.input_tokens < 0
                or self.within_cap is not (self.state == "passed")
                or not isinstance(self.response_payload, Mapping)
                or self.error_code is not None
                or self.retryable is not None
            ):
                raise InputTokenPreflightError(
                    "preflight counted completion is invalid"
                )
        elif (
            self.input_tokens is not None
            or self.within_cap is not None
            or self.response_payload is not None
            or not isinstance(self.error_code, str)
            or not self.error_code.strip()
            or not isinstance(self.retryable, bool)
        ):
            raise InputTokenPreflightError("preflight failure is invalid")
        if self.response_payload is not None:
            object.__setattr__(
                self,
                "response_payload",
                _safe_payload(self.response_payload),
            )
        object.__setattr__(self, "completed_at", _timestamp(self.completed_at))


@dataclass(frozen=True, slots=True)
class InputTokenPreflightReceipt:
    preflight_id: str
    state: str
    reused: bool

    def __post_init__(self) -> None:
        _uuid(self.preflight_id)
        if self.state not in {"pending", "passed", "blocked", "failed"}:
            raise InputTokenPreflightError("preflight receipt state is invalid")
        if not isinstance(self.reused, bool):
            raise InputTokenPreflightError("preflight reuse flag is invalid")


class InputTokenPreflightStore(Protocol):
    def begin(
        self,
        start: InputTokenPreflightStart,
    ) -> InputTokenPreflightReceipt: ...

    def complete(
        self,
        completion: InputTokenPreflightCompletion,
    ) -> InputTokenPreflightReceipt: ...


class PersistentInputTokenPreflightGate:
    """Persists exact count request and result before allowing generation."""

    def __init__(
        self,
        *,
        store: InputTokenPreflightStore,
        clock: Callable[[], datetime],
    ) -> None:
        self._store = store
        self._clock = clock

    def authorize(
        self,
        *,
        operator_id: str,
        research_run_id: str,
        attempt_kind: str,
        attempt_id: str,
        request: ProviderRequest,
        provider: InputTokenCountingProvider,
    ) -> InputTokenCountResult:
        audit_request = _safe_payload(provider.audit_input_token_count_request(request))
        payload = audit_request.get("payload")
        if not isinstance(payload, Mapping):
            raise InputTokenPreflightError("preflight request payload is invalid")
        preflight_id = stable_id(
            operator_id,
            "provider-input-token-preflight",
            f"{attempt_kind}:{attempt_id}",
        )
        start = InputTokenPreflightStart(
            preflight_id=preflight_id,
            operator_id=operator_id,
            research_run_id=research_run_id,
            attempt_kind=attempt_kind,
            attempt_id=attempt_id,
            execution_identity=request.execution_identity,
            request_hash=request.request_hash,
            provider=request.provider,
            model=request.model,
            input_payload_sha256=_payload_sha256(payload),
            input_token_cap=request.input_token_cap,
            request_payload=audit_request,
            started_at=self._clock(),
        )
        receipt = self._store.begin(start)
        _validate_receipt(receipt, preflight_id, "pending")
        if receipt.reused:
            raise InputTokenPreflightError(
                "preflight already existed before token-count dispatch"
            )
        try:
            result = provider.count_input_tokens(request)
        except ProviderTransportError as error:
            completion = InputTokenPreflightCompletion(
                preflight_id=preflight_id,
                operator_id=operator_id,
                state="failed",
                input_tokens=None,
                within_cap=None,
                response_payload=None,
                error_code=error.code,
                retryable=error.retryable,
                completed_at=self._clock(),
            )
            _validate_receipt(
                self._store.complete(completion),
                preflight_id,
                "failed",
            )
            raise
        mismatch = (
            result.execution_identity != request.execution_identity
            or result.request_hash != request.request_hash
            or result.model != request.model
            or result.input_payload_sha256 != start.input_payload_sha256
            or result.input_token_cap != request.input_token_cap
            or result.within_cap is not (result.input_tokens <= request.input_token_cap)
        )
        if mismatch:
            error = ProviderTransportError(
                "input_token_preflight_identity_mismatch",
                retryable=False,
                category="contract",
            )
            _validate_receipt(
                self._store.complete(
                    InputTokenPreflightCompletion(
                        preflight_id=preflight_id,
                        operator_id=operator_id,
                        state="failed",
                        input_tokens=None,
                        within_cap=None,
                        response_payload=None,
                        error_code=error.code,
                        retryable=False,
                        completed_at=self._clock(),
                    )
                ),
                preflight_id,
                "failed",
            )
            raise error
        state = "passed" if result.within_cap else "blocked"
        completion = InputTokenPreflightCompletion(
            preflight_id=preflight_id,
            operator_id=operator_id,
            state=state,
            input_tokens=result.input_tokens,
            within_cap=result.within_cap,
            response_payload=result.raw_provider_response,
            error_code=None,
            retryable=None,
            completed_at=self._clock(),
        )
        _validate_receipt(
            self._store.complete(completion),
            preflight_id,
            state,
        )
        if not result.within_cap:
            raise ProviderTransportError(
                "input_token_cap_exceeded",
                retryable=False,
                category="usage",
            )
        return result


def _validate_receipt(
    receipt: InputTokenPreflightReceipt,
    preflight_id: str,
    expected_state: str,
) -> None:
    if receipt.preflight_id != preflight_id or receipt.state != expected_state:
        raise InputTokenPreflightError("preflight persistence receipt mismatch")


def _safe_payload(value: Mapping[str, object]) -> dict[str, object]:
    safe = _without_reasoning_content(value)
    if not isinstance(safe, Mapping):
        raise InputTokenPreflightError("preflight audit payload is invalid")
    return json.loads(json.dumps(safe))


def _payload_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


def _uuid(value: object) -> str:
    try:
        parsed = uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError) as error:
        raise InputTokenPreflightError("preflight UUID is invalid") from error
    return str(parsed)


def _sha256(value: object) -> str:
    text = str(value)
    if not SHA256_PATTERN.fullmatch(text):
        raise InputTokenPreflightError("preflight SHA-256 is invalid")
    return text


def _timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InputTokenPreflightError("preflight timestamp must be timezone-aware")
    return value


__all__ = [
    "InputTokenCountResult",
    "InputTokenCountingProvider",
    "InputTokenPreflightCompletion",
    "InputTokenPreflightError",
    "InputTokenPreflightReceipt",
    "InputTokenPreflightStart",
    "InputTokenPreflightStore",
    "PersistentInputTokenPreflightGate",
]

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
import hashlib
import json
import re
from typing import Mapping, Protocol, runtime_checkable
import uuid


class GraderExecutionRuntimeError(ValueError):
    """Raised when a persistent grader lifecycle value is malformed."""


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
EXECUTION_START_FIELDS = {
    "id",
    "research_run_id",
    "security_id",
    "evidence_bundle_id",
    "evidence_bundle_hash",
    "execution_key",
    "question_type_id",
    "question_type_version",
    "workflow_config_version",
    "thesis_contract_id",
    "grader_id",
    "grader_version",
    "grader_contract_version",
    "eligibility_rule_version",
    "rubric_version",
    "output_schema_version",
    "abstention_rules_version",
    "prompt_version",
    "model_config_id",
    "price_card_id",
    "budget_id",
    "provider",
    "model",
    "inference_parameter_hash",
    "retry_policy_version",
    "max_attempts",
    "required",
    "pre_call_gate",
    "budget_snapshot",
    "started_at",
    "canonical_execution",
}


def canonical_payload_sha256(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise GraderExecutionRuntimeError("runtime payload is not canonical") from error
    return hashlib.sha256(encoded.encode()).hexdigest()


def _payload_copy(value: Mapping[str, object]) -> dict[str, object]:
    try:
        copied = json.loads(
            json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
    except (TypeError, ValueError) as error:
        raise GraderExecutionRuntimeError("runtime payload is not canonical") from error
    if not isinstance(copied, dict):
        raise GraderExecutionRuntimeError("runtime payload must be an object")
    return copied


def _uuid_text(value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (AttributeError, TypeError, ValueError) as error:
        raise GraderExecutionRuntimeError("runtime UUID is invalid") from error


def _sha256_text(value: object) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise GraderExecutionRuntimeError("runtime SHA-256 is invalid")
    return value


def _timestamp(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise GraderExecutionRuntimeError("runtime timestamp is invalid")
    return value


def _nonempty_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise GraderExecutionRuntimeError(f"runtime {field} is invalid")
    return value


def _cost(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or value < Decimal("0"):
        raise GraderExecutionRuntimeError("runtime cost is invalid")
    return value


def _contains_sensitive_reasoning(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            key in {"reasoning_content", "encrypted_content"}
            or _contains_sensitive_reasoning(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(
            (isinstance(item, Mapping) and item.get("type") == "reasoning")
            or _contains_sensitive_reasoning(item)
            for item in value
        )
    return False


def _nonnegative_int(value: object, *, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise GraderExecutionRuntimeError(f"runtime {field} is invalid")
    return value


@dataclass(frozen=True, slots=True)
class ExecutionStart:
    operator_id: str
    execution_id: str
    execution_key: str
    payload_sha256: str
    _payload: Mapping[str, object] = field(repr=False)

    @classmethod
    def from_payload(
        cls,
        operator_id: str,
        payload: Mapping[str, object],
    ) -> ExecutionStart:
        copied = _payload_copy(payload)
        if set(copied) != EXECUTION_START_FIELDS:
            raise GraderExecutionRuntimeError(
                "execution start payload fields are invalid"
            )
        if _contains_sensitive_reasoning(copied):
            raise GraderExecutionRuntimeError(
                "runtime payload contains sensitive reasoning"
            )
        for key in ("id", "research_run_id", "security_id", "evidence_bundle_id"):
            copied[key] = _uuid_text(copied[key])
        copied["budget_id"] = _uuid_text(copied["budget_id"])
        for key in (
            "evidence_bundle_hash",
            "execution_key",
            "inference_parameter_hash",
        ):
            copied[key] = _sha256_text(copied[key])
        for key in (
            "question_type_id",
            "question_type_version",
            "workflow_config_version",
            "thesis_contract_id",
            "grader_id",
            "grader_version",
            "grader_contract_version",
            "eligibility_rule_version",
            "rubric_version",
            "output_schema_version",
            "abstention_rules_version",
            "prompt_version",
            "model_config_id",
            "price_card_id",
            "provider",
            "model",
            "retry_policy_version",
        ):
            copied[key] = _nonempty_text(copied[key], field=key)
        if (
            copied["max_attempts"] != 2
            or not isinstance(copied["required"], bool)
            or not isinstance(copied["pre_call_gate"], dict)
            or not isinstance(copied["budget_snapshot"], dict)
            or not isinstance(copied["canonical_execution"], dict)
            or copied["pre_call_gate"].get("status") != "passed"
            or copied["canonical_execution"].get("contract_version")
            != "grader_execution.v1"
            or copied["canonical_execution"].get("id") != copied["id"]
            or copied["canonical_execution"].get("execution_state") is not None
        ):
            raise GraderExecutionRuntimeError("execution start payload is invalid")
        try:
            parsed_started_at = datetime.fromisoformat(str(copied["started_at"]))
        except ValueError as error:
            raise GraderExecutionRuntimeError("runtime timestamp is invalid") from error
        copied["started_at"] = _timestamp(parsed_started_at).isoformat()
        return cls(
            operator_id=_uuid_text(operator_id),
            execution_id=str(copied["id"]),
            execution_key=str(copied["execution_key"]),
            payload_sha256=canonical_payload_sha256(copied),
            _payload=copied,
        )

    def storage_payload(self) -> dict[str, object]:
        return _payload_copy(self._payload)


@dataclass(frozen=True, slots=True)
class AttemptStart:
    operator_id: str
    execution_id: str
    attempt_id: str
    attempt_number: int
    request_sha256: str
    provider: str
    model: str
    model_config_id: str
    prompt_version: str
    started_at: datetime
    raw_payload_id: str
    raw_payload_sha256: str
    price_card_id: str
    reserved_cost_usd: Decimal
    retry_reason: str | None
    sanitized_request: Mapping[str, object]
    reservation_id: str
    budget_id: str
    reserved_tokens: int

    @classmethod
    def create(
        cls,
        *,
        operator_id: str,
        execution_id: str,
        attempt_id: str,
        attempt_number: int,
        request_sha256: str,
        provider: str,
        model: str,
        model_config_id: str,
        prompt_version: str,
        started_at: datetime,
        raw_payload_id: str,
        price_card_id: str,
        reserved_cost_usd: Decimal,
        retry_reason: str | None,
        sanitized_request: Mapping[str, object],
        reservation_id: str,
        budget_id: str,
        reserved_tokens: int,
    ) -> AttemptStart:
        request = _payload_copy(sanitized_request)
        if _contains_sensitive_reasoning(request):
            raise GraderExecutionRuntimeError(
                "runtime payload contains sensitive reasoning"
            )
        if attempt_number not in (1, 2):
            raise GraderExecutionRuntimeError("runtime attempt number is invalid")
        if (
            not isinstance(reserved_tokens, int)
            or isinstance(reserved_tokens, bool)
            or reserved_tokens <= 0
        ):
            raise GraderExecutionRuntimeError("runtime token reservation is invalid")
        if (
            attempt_number == 1
            and retry_reason is not None
            or attempt_number == 2
            and (
                not isinstance(retry_reason, str)
                or not retry_reason.strip()
                or retry_reason != retry_reason.strip()
            )
        ):
            raise GraderExecutionRuntimeError("runtime retry linkage is invalid")
        return cls(
            operator_id=_uuid_text(operator_id),
            execution_id=_uuid_text(execution_id),
            attempt_id=_uuid_text(attempt_id),
            attempt_number=attempt_number,
            request_sha256=_sha256_text(request_sha256),
            provider=_nonempty_text(provider, field="provider"),
            model=_nonempty_text(model, field="model"),
            model_config_id=_nonempty_text(
                model_config_id,
                field="model configuration",
            ),
            prompt_version=_nonempty_text(prompt_version, field="prompt version"),
            started_at=_timestamp(started_at),
            raw_payload_id=_uuid_text(raw_payload_id),
            raw_payload_sha256=canonical_payload_sha256(
                {"request": request, "response": None}
            ),
            price_card_id=_nonempty_text(price_card_id, field="price card"),
            reserved_cost_usd=_cost(reserved_cost_usd),
            retry_reason=retry_reason,
            sanitized_request=request,
            reservation_id=_uuid_text(reservation_id),
            budget_id=_uuid_text(budget_id),
            reserved_tokens=reserved_tokens,
        )

    def storage_arguments(
        self,
    ) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        cost = format(self.reserved_cost_usd, "f")
        return (
            {
                "id": self.attempt_id,
                "grader_execution_id": self.execution_id,
                "attempt_number": self.attempt_number,
                "request_sha256": self.request_sha256,
                "provider": self.provider,
                "model": self.model,
                "model_config_id": self.model_config_id,
                "prompt_version": self.prompt_version,
                "started_at": self.started_at.isoformat(),
                "raw_payload_id": self.raw_payload_id,
                "raw_payload_sha256": self.raw_payload_sha256,
                "price_card_id": self.price_card_id,
                "reserved_cost_usd": cost,
                "retry_reason": self.retry_reason,
            },
            _payload_copy(self.sanitized_request),
            {
                "id": self.reservation_id,
                "budget_id": self.budget_id,
                "reserved_cost_usd": cost,
                "reserved_tokens": self.reserved_tokens,
                "price_card_id": self.price_card_id,
            },
        )


@dataclass(frozen=True, slots=True)
class AttemptCompletion:
    operator_id: str
    execution_id: str
    attempt_id: str
    attempt_number: int
    reservation_id: str
    result: str
    raw_payload_sha256: str
    _completion: Mapping[str, object] = field(repr=False)
    _response: Mapping[str, object] | None = field(repr=False)
    _opinion: Mapping[str, object] | None = field(repr=False)

    @classmethod
    def create(
        cls,
        *,
        operator_id: str,
        execution_id: str,
        attempt_id: str,
        attempt_number: int,
        reservation_id: str,
        result: str,
        finished_at: datetime,
        duration_ms: int,
        provider_request_id: str | None,
        raw_payload_id: str,
        input_tokens: int,
        cached_input_tokens: int,
        cache_write_tokens: int,
        output_tokens: int,
        reasoning_tokens: int,
        tool_call_count: int,
        estimated_cost_usd: Decimal,
        billed_cost_usd: Decimal | None,
        usage_complete: bool,
        validation_status: str,
        schema_valid: bool | None,
        citations_valid: bool | None,
        validation_errors: tuple[str, ...],
        retry_reason: str | None,
        reservation_state: str,
        actual_cost_usd: Decimal,
        sanitized_request: Mapping[str, object],
        sanitized_response: Mapping[str, object] | None,
        validated_opinion: Mapping[str, object] | None,
    ) -> AttemptCompletion:
        if attempt_number not in (1, 2):
            raise GraderExecutionRuntimeError("runtime attempt number is invalid")
        if result not in {
            "accepted",
            "abstained",
            "transport_error",
            "validation_error",
        }:
            raise GraderExecutionRuntimeError("runtime attempt result is invalid")
        request = _payload_copy(sanitized_request)
        response = (
            None if sanitized_response is None else _payload_copy(sanitized_response)
        )
        opinion = (
            None if validated_opinion is None else _payload_copy(validated_opinion)
        )
        if any(
            _contains_sensitive_reasoning(value)
            for value in (request, response, opinion)
            if value is not None
        ):
            raise GraderExecutionRuntimeError(
                "runtime payload contains sensitive reasoning"
            )
        execution_id = _uuid_text(execution_id)
        if result in {"accepted", "abstained"}:
            if (
                response is None
                or opinion is None
                or opinion.get("execution_id") != execution_id
                or opinion.get("execution_state") != result
            ):
                raise GraderExecutionRuntimeError(
                    "runtime completed opinion is invalid"
                )
            _uuid_text(opinion.get("opinion_id"))
        elif opinion is not None:
            raise GraderExecutionRuntimeError(
                "runtime non-opinion attempt contains opinion"
            )
        if (result == "transport_error") != (response is None):
            raise GraderExecutionRuntimeError(
                "runtime attempt response state is invalid"
            )
        if not isinstance(usage_complete, bool):
            raise GraderExecutionRuntimeError("runtime usage completeness is invalid")
        if not isinstance(validation_errors, tuple) or any(
            not isinstance(error, str) or not error.strip() or error != error.strip()
            for error in validation_errors
        ):
            raise GraderExecutionRuntimeError("runtime validation errors are invalid")
        if result in {"accepted", "abstained"} and (
            not usage_complete
            or validation_status != "passed"
            or schema_valid is not True
            or citations_valid is not True
            or validation_errors
            or reservation_state != "reconciled"
        ):
            raise GraderExecutionRuntimeError(
                "runtime accepted attempt state is invalid"
            )
        if result == "validation_error" and (
            not usage_complete
            or validation_status != "failed"
            or not validation_errors
            or (schema_valid is True and citations_valid is True)
            or reservation_state != "reconciled"
        ):
            raise GraderExecutionRuntimeError(
                "runtime rejected attempt state is invalid"
            )
        if result == "transport_error" and (
            validation_status != "not_run"
            or schema_valid is not None
            or citations_valid is not None
            or reservation_state != "released"
            or provider_request_id is not None
        ):
            raise GraderExecutionRuntimeError(
                "runtime transport attempt state is invalid"
            )
        token_values = {
            "input tokens": input_tokens,
            "cached input tokens": cached_input_tokens,
            "cache write tokens": cache_write_tokens,
            "output tokens": output_tokens,
            "reasoning tokens": reasoning_tokens,
            "tool call count": tool_call_count,
        }
        checked_tokens = {
            key: _nonnegative_int(value, field=key)
            for key, value in token_values.items()
        }
        if (
            cached_input_tokens > input_tokens
            or cache_write_tokens > input_tokens - cached_input_tokens
            or reasoning_tokens > output_tokens
        ):
            raise GraderExecutionRuntimeError("runtime usage is invalid")
        total_tokens = input_tokens + output_tokens
        uncached_input_tokens = input_tokens - cached_input_tokens
        raw_hash = canonical_payload_sha256({"request": request, "response": response})
        estimated_cost = _cost(estimated_cost_usd)
        billed_cost = None if billed_cost_usd is None else _cost(billed_cost_usd)
        actual_cost = _cost(actual_cost_usd)
        expected_actual_cost = (
            billed_cost if billed_cost is not None else estimated_cost
        )
        if actual_cost != expected_actual_cost or (
            reservation_state == "released" and actual_cost != Decimal("0")
        ):
            raise GraderExecutionRuntimeError("runtime attempt settlement is invalid")
        completion = {
            "grader_execution_id": execution_id,
            "attempt_id": _uuid_text(attempt_id),
            "attempt_number": attempt_number,
            "reservation_id": _uuid_text(reservation_id),
            "result": result,
            "finished_at": _timestamp(finished_at).isoformat(),
            "duration_ms": _nonnegative_int(duration_ms, field="duration"),
            "provider_request_id": (
                None
                if provider_request_id is None
                else _nonempty_text(provider_request_id, field="provider request")
            ),
            "raw_payload_id": _uuid_text(raw_payload_id),
            "raw_payload_sha256": raw_hash,
            "input_tokens": checked_tokens["input tokens"],
            "cached_input_tokens": checked_tokens["cached input tokens"],
            "cache_write_tokens": checked_tokens["cache write tokens"],
            "uncached_input_tokens": uncached_input_tokens,
            "output_tokens": checked_tokens["output tokens"],
            "reasoning_tokens": checked_tokens["reasoning tokens"],
            "total_tokens": total_tokens,
            "tool_call_count": checked_tokens["tool call count"],
            "estimated_cost_usd": format(estimated_cost, "f"),
            "billed_cost_usd": (
                None if billed_cost is None else format(billed_cost, "f")
            ),
            "usage_complete": usage_complete,
            "validation_status": validation_status,
            "schema_valid": schema_valid,
            "citations_valid": citations_valid,
            "validation_errors": list(validation_errors),
            "retry_reason": retry_reason,
            "reservation_state": reservation_state,
            "actual_cost_usd": format(actual_cost, "f"),
            "actual_tokens": total_tokens,
        }
        return cls(
            operator_id=_uuid_text(operator_id),
            execution_id=execution_id,
            attempt_id=str(completion["attempt_id"]),
            attempt_number=attempt_number,
            reservation_id=str(completion["reservation_id"]),
            result=result,
            raw_payload_sha256=raw_hash,
            _completion=completion,
            _response=response,
            _opinion=opinion,
        )

    def storage_arguments(
        self,
    ) -> tuple[
        dict[str, object],
        dict[str, object] | None,
        dict[str, object] | None,
    ]:
        return (
            _payload_copy(self._completion),
            None if self._response is None else _payload_copy(self._response),
            None if self._opinion is None else _payload_copy(self._opinion),
        )


@dataclass(frozen=True, slots=True)
class RuntimeAttemptSnapshot:
    attempt_id: str
    attempt_number: int
    persistence_state: str
    reservation_state: str
    result: str | None
    response_persisted: bool
    opinion_id: str | None
    raw_payload_sha256: str
    finished_at: datetime | None
    retry_reason: str | None = None

    def __post_init__(self) -> None:
        _uuid_text(self.attempt_id)
        _sha256_text(self.raw_payload_sha256)
        if self.retry_reason is not None:
            _nonempty_text(self.retry_reason, field="retry_reason")
        if self.attempt_number not in (1, 2):
            raise GraderExecutionRuntimeError("runtime attempt number is invalid")
        if self.persistence_state not in {"draft", "complete"}:
            raise GraderExecutionRuntimeError(
                "runtime attempt persistence state is invalid"
            )
        if self.reservation_state not in {
            "reserved",
            "reconciled",
            "released",
        }:
            raise GraderExecutionRuntimeError("runtime reservation state is invalid")
        if not isinstance(self.response_persisted, bool):
            raise GraderExecutionRuntimeError(
                "runtime response persistence state is invalid"
            )
        if self.persistence_state == "draft":
            if (
                self.reservation_state != "reserved"
                or self.result is not None
                or self.response_persisted
                or self.opinion_id is not None
                or self.finished_at is not None
            ):
                raise GraderExecutionRuntimeError(
                    "runtime draft attempt shape is invalid"
                )
            return
        if (
            self.result
            not in {
                "accepted",
                "abstained",
                "transport_error",
                "validation_error",
            }
            or self.finished_at is None
        ):
            raise GraderExecutionRuntimeError(
                "runtime completed attempt shape is invalid"
            )
        _timestamp(self.finished_at)
        if self.result in {"accepted", "abstained"}:
            if (
                self.reservation_state != "reconciled"
                or not self.response_persisted
                or self.opinion_id is None
            ):
                raise GraderExecutionRuntimeError(
                    "runtime completed opinion shape is invalid"
                )
            _uuid_text(self.opinion_id)
        elif self.opinion_id is not None:
            raise GraderExecutionRuntimeError(
                "runtime non-opinion attempt contains opinion"
            )
        elif self.result == "transport_error" and (
            self.reservation_state != "released" or self.response_persisted
        ):
            raise GraderExecutionRuntimeError(
                "runtime transport attempt shape is invalid"
            )
        elif self.result == "validation_error" and (
            self.reservation_state != "reconciled" or not self.response_persisted
        ):
            raise GraderExecutionRuntimeError(
                "runtime validation attempt shape is invalid"
            )


@dataclass(frozen=True, slots=True)
class RuntimeExecutionSnapshot:
    operator_id: str
    execution_id: str
    execution_key: str
    persistence_state: str
    attempts: tuple[RuntimeAttemptSnapshot, ...]
    canonical_execution: Mapping[str, object] | None

    def __post_init__(self) -> None:
        _uuid_text(self.operator_id)
        _uuid_text(self.execution_id)
        _sha256_text(self.execution_key)
        if self.persistence_state not in {"draft", "complete"}:
            raise GraderExecutionRuntimeError(
                "runtime execution persistence state is invalid"
            )
        if tuple(item.attempt_number for item in self.attempts) != tuple(
            range(1, len(self.attempts) + 1)
        ):
            raise GraderExecutionRuntimeError("runtime attempt sequence is invalid")
        if (
            self.persistence_state == "complete" and self.canonical_execution is None
        ) or (
            self.persistence_state == "draft" and self.canonical_execution is not None
        ):
            raise GraderExecutionRuntimeError(
                "runtime execution snapshot shape is invalid"
            )
        if self.canonical_execution is not None:
            canonical = _payload_copy(self.canonical_execution)
            if canonical.get(
                "contract_version"
            ) != "grader_execution.v1" or _contains_sensitive_reasoning(canonical):
                raise GraderExecutionRuntimeError(
                    "runtime canonical execution is invalid"
                )


class RestartAction(str, Enum):
    REUSE = "reuse_terminal"
    FINALIZE = "finalize_persisted_attempt"
    CONTINUE = "continue_without_repeating_attempt"
    MANUAL_RECOVERY = "manual_recovery"


@dataclass(frozen=True, slots=True)
class RestartDecision:
    action: RestartAction
    reason_code: str
    provider_call_permitted: bool


def decide_restart(snapshot: RuntimeExecutionSnapshot) -> RestartDecision:
    if snapshot.persistence_state == "complete":
        return RestartDecision(
            RestartAction.REUSE,
            "execution_complete",
            False,
        )
    if not snapshot.attempts:
        return RestartDecision(
            RestartAction.CONTINUE,
            "first_attempt_not_started",
            True,
        )
    latest = snapshot.attempts[-1]
    if latest.persistence_state == "draft":
        return RestartDecision(
            RestartAction.MANUAL_RECOVERY,
            "provider_dispatch_state_ambiguous",
            False,
        )
    if latest.result in {"accepted", "abstained"}:
        return RestartDecision(
            RestartAction.FINALIZE,
            "validated_opinion_persisted",
            False,
        )
    if latest.retry_reason is not None and latest.retry_reason.startswith(
        "nonretryable:"
    ):
        return RestartDecision(
            RestartAction.FINALIZE,
            "nonretryable_provider_error",
            False,
        )
    if latest.attempt_number < 2:
        return RestartDecision(
            RestartAction.CONTINUE,
            "next_attempt_permitted",
            True,
        )
    return RestartDecision(
        RestartAction.FINALIZE,
        "retry_policy_exhausted",
        False,
    )


@dataclass(frozen=True, slots=True)
class ExecutionFinalization:
    operator_id: str
    execution_id: str
    execution_state: str
    canonical_execution_sha256: str
    _canonical_execution: Mapping[str, object] = field(repr=False)
    _payload: Mapping[str, object] = field(repr=False)

    @classmethod
    def from_canonical(
        cls,
        operator_id: str,
        canonical_execution: Mapping[str, object],
    ) -> ExecutionFinalization:
        canonical = _payload_copy(canonical_execution)
        if canonical.get(
            "contract_version"
        ) != "grader_execution.v1" or _contains_sensitive_reasoning(canonical):
            raise GraderExecutionRuntimeError("runtime canonical execution is invalid")
        normalized_operator_id = _uuid_text(operator_id)
        if canonical.get("operator_id") != normalized_operator_id:
            raise GraderExecutionRuntimeError(
                "runtime canonical execution owner is invalid"
            )
        execution_id = _uuid_text(canonical.get("id"))
        _sha256_text(canonical.get("execution_key"))
        state = canonical.get("execution_state")
        if state not in {"not_executed", "failed", "abstained", "accepted"}:
            raise GraderExecutionRuntimeError("runtime execution state is invalid")
        opinion = canonical.get("opinion")
        if (state in {"accepted", "abstained"}) != isinstance(opinion, Mapping):
            raise GraderExecutionRuntimeError(
                "runtime terminal opinion state is invalid"
            )
        usage = canonical.get("total_usage")
        cost = canonical.get("total_cost")
        if not isinstance(usage, Mapping) or not isinstance(cost, Mapping):
            raise GraderExecutionRuntimeError("runtime terminal totals are invalid")
        input_tokens = _nonnegative_int(
            usage.get("input_tokens"),
            field="input tokens",
        )
        output_tokens = _nonnegative_int(
            usage.get("output_tokens"),
            field="output tokens",
        )
        reasoning_tokens = _nonnegative_int(
            usage.get("reasoning_tokens"),
            field="reasoning tokens",
        )
        total_tokens = _nonnegative_int(
            usage.get("total_tokens"),
            field="total tokens",
        )
        if (
            total_tokens != input_tokens + output_tokens
            or reasoning_tokens > output_tokens
        ):
            raise GraderExecutionRuntimeError("runtime terminal usage is invalid")
        try:
            total_cost = Decimal(str(cost["estimated_cost_usd"]))
        except (KeyError, TypeError, ValueError) as error:
            raise GraderExecutionRuntimeError(
                "runtime terminal cost is invalid"
            ) from error
        total_cost = _cost(total_cost)
        try:
            finished_at = datetime.fromisoformat(str(canonical["finished_at"]))
        except (KeyError, ValueError) as error:
            raise GraderExecutionRuntimeError("runtime timestamp is invalid") from error
        payload = {
            "id": execution_id,
            "execution_state": state,
            "total_input_tokens": input_tokens,
            "total_output_tokens": output_tokens,
            "total_reasoning_tokens": reasoning_tokens,
            "total_tokens": total_tokens,
            "total_cost_usd": format(total_cost, "f"),
            "finished_at": _timestamp(finished_at).isoformat(),
            "canonical_execution": canonical,
        }
        return cls(
            operator_id=normalized_operator_id,
            execution_id=execution_id,
            execution_state=str(state),
            canonical_execution_sha256=canonical_payload_sha256(canonical),
            _canonical_execution=canonical,
            _payload=payload,
        )

    @property
    def canonical_execution(self) -> dict[str, object]:
        return _payload_copy(self._canonical_execution)

    def storage_payload(self) -> dict[str, object]:
        return _payload_copy(self._payload)


@runtime_checkable
class GraderExecutionLifecycle(Protocol):
    def begin_execution(
        self,
        start: ExecutionStart,
    ) -> RuntimeExecutionSnapshot: ...

    def begin_attempt(
        self,
        start: AttemptStart,
    ) -> RuntimeExecutionSnapshot: ...

    def finish_attempt(
        self,
        completion: AttemptCompletion,
    ) -> RuntimeExecutionSnapshot: ...

    def load(
        self,
        operator_id: str,
        execution_key: str,
    ) -> RuntimeExecutionSnapshot | None: ...

    def finalize_execution(
        self,
        finalization: ExecutionFinalization,
    ) -> RuntimeExecutionSnapshot: ...


__all__ = [
    "AttemptCompletion",
    "AttemptStart",
    "ExecutionFinalization",
    "ExecutionStart",
    "GraderExecutionLifecycle",
    "GraderExecutionRuntimeError",
    "RestartAction",
    "RestartDecision",
    "RuntimeAttemptSnapshot",
    "RuntimeExecutionSnapshot",
    "canonical_payload_sha256",
    "decide_restart",
]

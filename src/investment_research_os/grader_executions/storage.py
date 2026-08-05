from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping
import uuid

from workers.sec.storage import (
    EvidenceStorageError,
    JsonTransport,
    SupabaseStorageSettings,
    UrllibJsonTransport,
)


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
EXECUTION_INPUT_FIELDS = {
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
EXECUTION_RECEIPT_FIELDS = {
    "operator_id",
    "grader_execution_id",
    "execution_key",
    "persistence_state",
    "reused",
    "evidence_bundle_hash",
    "inference_parameter_hash",
}
ATTEMPT_INPUT_FIELDS = {
    "id",
    "grader_execution_id",
    "attempt_number",
    "request_sha256",
    "provider",
    "model",
    "model_config_id",
    "prompt_version",
    "started_at",
    "raw_payload_id",
    "raw_payload_sha256",
    "price_card_id",
    "reserved_cost_usd",
    "retry_reason",
}
RESERVATION_INPUT_FIELDS = {
    "id",
    "budget_id",
    "reserved_cost_usd",
    "reserved_tokens",
    "price_card_id",
}
ATTEMPT_RECEIPT_FIELDS = {
    "operator_id",
    "grader_execution_id",
    "grader_attempt_id",
    "budget_reservation_id",
    "attempt_number",
    "persistence_state",
    "reservation_state",
    "reused",
    "request_sha256",
    "raw_payload_id",
    "raw_payload_sha256",
}
COMPLETION_INPUT_FIELDS = {
    "grader_execution_id",
    "attempt_id",
    "attempt_number",
    "reservation_id",
    "result",
    "finished_at",
    "duration_ms",
    "provider_request_id",
    "raw_payload_id",
    "raw_payload_sha256",
    "input_tokens",
    "cached_input_tokens",
    "cache_write_tokens",
    "uncached_input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "total_tokens",
    "tool_call_count",
    "estimated_cost_usd",
    "billed_cost_usd",
    "usage_complete",
    "validation_status",
    "schema_valid",
    "citations_valid",
    "validation_errors",
    "retry_reason",
    "reservation_state",
    "actual_cost_usd",
    "actual_tokens",
}
FINALIZATION_INPUT_FIELDS = {
    "id",
    "execution_state",
    "total_input_tokens",
    "total_output_tokens",
    "total_reasoning_tokens",
    "total_tokens",
    "total_cost_usd",
    "finished_at",
    "canonical_execution",
}
SNAPSHOT_FIELDS = {
    "operator_id",
    "grader_execution_id",
    "execution_key",
    "evidence_bundle_hash",
    "inference_parameter_hash",
    "persistence_state",
    "canonical_execution",
    "attempts",
    "validated_opinion",
}
CANONICAL_EXECUTION_FIELDS = {
    "contract_version",
    "id",
    "operator_id",
    "research_run_id",
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
    "provider",
    "model",
    "inference_parameter_hash",
    "retry_policy_version",
    "required",
    "execution_state",
    "pre_call_gate",
    "budget",
    "attempts",
    "total_usage",
    "total_cost",
    "not_executed",
    "failure",
    "opinion",
    "started_at",
    "finished_at",
}


class GraderExecutionStorageError(RuntimeError):
    """Raised when grader runtime persistence violates its contract."""


@dataclass(frozen=True, slots=True)
class GraderExecutionRuntimeReceipt:
    operator_id: str
    execution_id: str
    execution_key: str
    persistence_state: str
    reused: bool
    evidence_bundle_hash: str
    inference_parameter_hash: str


@dataclass(frozen=True, slots=True)
class GraderAttemptRuntimeReceipt:
    operator_id: str
    execution_id: str
    attempt_id: str
    reservation_id: str
    attempt_number: int
    persistence_state: str
    reservation_state: str
    reused: bool
    request_sha256: str
    raw_payload_id: str
    raw_payload_sha256: str


class SupabaseGraderExecutionRuntimeStore:
    """Maps crash-safe grader lifecycle steps onto narrow Supabase RPCs."""

    def __init__(
        self,
        settings: SupabaseStorageSettings,
        *,
        transport: JsonTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport or UrllibJsonTransport(settings.timeout_seconds)

    def begin_execution(
        self,
        operator_id: str,
        execution: Mapping[str, object],
    ) -> GraderExecutionRuntimeReceipt:
        operator_id = _uuid_text(operator_id)
        _validate_execution_input(execution)
        payload = self._rpc(
            "iros_begin_grader_execution_runtime",
            {
                "p_operator_id": operator_id,
                "p_execution": dict(execution),
            },
        )
        return _execution_receipt(
            payload,
            operator_id=operator_id,
            execution=execution,
            allowed_states={"draft", "complete"},
            complete_requires_reuse=True,
        )

    def begin_attempt(
        self,
        operator_id: str,
        attempt: Mapping[str, object],
        request_payload: Mapping[str, object],
        reservation: Mapping[str, object],
    ) -> GraderAttemptRuntimeReceipt:
        operator_id = _uuid_text(operator_id)
        _validate_attempt_input(attempt, reservation)
        payload = self._rpc(
            "iros_begin_grader_attempt_runtime",
            {
                "p_operator_id": operator_id,
                "p_attempt": dict(attempt),
                "p_sanitized_request": _without_reasoning_content(request_payload),
                "p_reservation": dict(reservation),
            },
        )
        return _attempt_receipt(
            payload,
            operator_id=operator_id,
            attempt=attempt,
            reservation=reservation,
            allowed_states={"draft", "complete"},
        )

    def finish_attempt(
        self,
        operator_id: str,
        completion: Mapping[str, object],
        response_payload: Mapping[str, object] | None,
        validated_opinion: Mapping[str, object] | None,
    ) -> GraderAttemptRuntimeReceipt:
        operator_id = _uuid_text(operator_id)
        _validate_completion_input(
            completion,
            response_payload,
            validated_opinion,
        )
        payload = self._rpc(
            "iros_finish_grader_attempt_runtime",
            {
                "p_operator_id": operator_id,
                "p_completion": dict(completion),
                "p_sanitized_response": (
                    None
                    if response_payload is None
                    else _without_reasoning_content(response_payload)
                ),
                "p_validated_opinion": (
                    None
                    if validated_opinion is None
                    else _without_reasoning_content(validated_opinion)
                ),
            },
        )
        return _finished_attempt_receipt(
            payload,
            operator_id=operator_id,
            completion=completion,
        )

    def load(
        self,
        operator_id: str,
        execution_key: str,
    ) -> Mapping[str, object] | None:
        operator_id = _uuid_text(operator_id)
        execution_key = _sha256_text(execution_key)
        payload = self._rpc(
            "iros_load_grader_execution_runtime",
            {
                "p_operator_id": operator_id,
                "p_execution_key": execution_key,
            },
        )
        if payload is None:
            return None
        _validate_snapshot(
            payload,
            operator_id=operator_id,
            execution_key=execution_key,
        )
        return dict(payload)

    def finalize_execution(
        self,
        operator_id: str,
        execution: Mapping[str, object],
        *,
        execution_key: str,
        evidence_bundle_hash: str,
        inference_parameter_hash: str,
    ) -> GraderExecutionRuntimeReceipt:
        operator_id = _uuid_text(operator_id)
        _validate_finalization_input(execution)
        expected = {
            "id": execution["id"],
            "execution_key": _sha256_text(execution_key),
            "evidence_bundle_hash": _sha256_text(evidence_bundle_hash),
            "inference_parameter_hash": _sha256_text(inference_parameter_hash),
        }
        payload = self._rpc(
            "iros_finalize_grader_execution_runtime",
            {
                "p_operator_id": operator_id,
                "p_execution": dict(execution),
            },
        )
        return _execution_receipt(
            payload,
            operator_id=operator_id,
            execution=expected,
            allowed_states={"complete"},
            complete_requires_reuse=False,
        )

    def _rpc(self, name: str, payload: Mapping[str, Any]) -> object:
        try:
            response = self.transport.request_json(
                "POST",
                f"{self.settings.url.rstrip('/')}/rest/v1/rpc/{name}",
                headers={
                    "Content-Type": "application/json",
                    "apikey": self.settings.secret_key,
                },
                payload=payload,
            )
        except EvidenceStorageError as error:
            raise GraderExecutionStorageError(
                f"grader execution store failed for {name}"
            ) from error
        if not 200 <= response.status < 300:
            raise GraderExecutionStorageError(
                f"grader execution store returned HTTP {response.status} for {name}"
            )
        return response.payload


def _validate_execution_input(execution: Mapping[str, object]) -> None:
    if set(execution) != EXECUTION_INPUT_FIELDS:
        raise GraderExecutionStorageError("grader execution request is malformed")
    try:
        for field in (
            "id",
            "research_run_id",
            "security_id",
            "evidence_bundle_id",
        ):
            _uuid_text(execution[field])
        for field in (
            "evidence_bundle_hash",
            "execution_key",
            "inference_parameter_hash",
        ):
            _sha256_text(execution[field])
    except (TypeError, ValueError) as error:
        raise GraderExecutionStorageError(
            "grader execution request is malformed"
        ) from error
    canonical_execution = execution["canonical_execution"]
    if (
        execution["max_attempts"] != 2
        or not isinstance(execution["required"], bool)
        or not isinstance(execution["pre_call_gate"], Mapping)
        or not isinstance(execution["budget_snapshot"], Mapping)
        or not isinstance(canonical_execution, Mapping)
        or set(canonical_execution) != CANONICAL_EXECUTION_FIELDS
        or canonical_execution["contract_version"] != "grader_execution.v1"
        or canonical_execution["id"] != execution["id"]
        or canonical_execution["research_run_id"] != execution["research_run_id"]
        or canonical_execution["evidence_bundle_id"] != execution["evidence_bundle_id"]
        or canonical_execution["evidence_bundle_hash"]
        != execution["evidence_bundle_hash"]
        or canonical_execution["execution_key"] != execution["execution_key"]
        or canonical_execution["question_type_id"] != execution["question_type_id"]
        or canonical_execution["question_type_version"]
        != execution["question_type_version"]
        or canonical_execution["workflow_config_version"]
        != execution["workflow_config_version"]
        or canonical_execution["thesis_contract_id"] != execution["thesis_contract_id"]
        or canonical_execution["grader_id"] != execution["grader_id"]
        or canonical_execution["grader_version"] != execution["grader_version"]
        or canonical_execution["grader_contract_version"]
        != execution["grader_contract_version"]
        or canonical_execution["eligibility_rule_version"]
        != execution["eligibility_rule_version"]
        or canonical_execution["rubric_version"] != execution["rubric_version"]
        or canonical_execution["output_schema_version"]
        != execution["output_schema_version"]
        or canonical_execution["abstention_rules_version"]
        != execution["abstention_rules_version"]
        or canonical_execution["prompt_version"] != execution["prompt_version"]
        or canonical_execution["model_config_id"] != execution["model_config_id"]
        or canonical_execution["provider"] != execution["provider"]
        or canonical_execution["model"] != execution["model"]
        or canonical_execution["inference_parameter_hash"]
        != execution["inference_parameter_hash"]
        or canonical_execution["retry_policy_version"]
        != execution["retry_policy_version"]
        or canonical_execution["required"] != execution["required"]
        or canonical_execution["pre_call_gate"] != execution["pre_call_gate"]
        or execution["pre_call_gate"].get("status") != "passed"
        or canonical_execution["execution_state"] is not None
        or _contains_reasoning_content(canonical_execution)
    ):
        raise GraderExecutionStorageError("grader execution request is malformed")


def _validate_attempt_input(
    attempt: Mapping[str, object],
    reservation: Mapping[str, object],
) -> None:
    if (
        set(attempt) != ATTEMPT_INPUT_FIELDS
        or set(reservation) != RESERVATION_INPUT_FIELDS
    ):
        raise GraderExecutionStorageError("grader attempt request is malformed")
    try:
        for value in (
            attempt["id"],
            attempt["grader_execution_id"],
            attempt["raw_payload_id"],
            reservation["id"],
            reservation["budget_id"],
        ):
            _uuid_text(value)
        _sha256_text(attempt["request_sha256"])
        _sha256_text(attempt["raw_payload_sha256"])
    except (TypeError, ValueError) as error:
        raise GraderExecutionStorageError(
            "grader attempt request is malformed"
        ) from error
    if (
        attempt["attempt_number"] not in (1, 2)
        or attempt["price_card_id"] != reservation["price_card_id"]
        or attempt["reserved_cost_usd"] != reservation["reserved_cost_usd"]
        or not isinstance(reservation["reserved_tokens"], int)
        or isinstance(reservation["reserved_tokens"], bool)
        or reservation["reserved_tokens"] <= 0
    ):
        raise GraderExecutionStorageError("grader attempt request is malformed")


def _validate_completion_input(
    completion: Mapping[str, object],
    response_payload: Mapping[str, object] | None,
    validated_opinion: Mapping[str, object] | None,
) -> None:
    if set(completion) != COMPLETION_INPUT_FIELDS:
        raise GraderExecutionStorageError("grader attempt completion is malformed")
    try:
        for value in (
            completion["grader_execution_id"],
            completion["attempt_id"],
            completion["reservation_id"],
            completion["raw_payload_id"],
        ):
            _uuid_text(value)
        _sha256_text(completion["raw_payload_sha256"])
    except (TypeError, ValueError) as error:
        raise GraderExecutionStorageError(
            "grader attempt completion is malformed"
        ) from error
    result = completion["result"]
    if (
        result
        not in {
            "accepted",
            "abstained",
            "transport_error",
            "validation_error",
        }
        or completion["attempt_number"] not in (1, 2)
        or completion["reservation_state"] not in {"reconciled", "released"}
        or (result == "transport_error") != (response_payload is None)
        or (
            result in {"accepted", "abstained"}
            and (
                not isinstance(validated_opinion, Mapping)
                or validated_opinion.get("execution_state") != result
                or validated_opinion.get("execution_id")
                != completion["grader_execution_id"]
                or _contains_reasoning_content(validated_opinion)
            )
        )
        or (result not in {"accepted", "abstained"} and validated_opinion is not None)
    ):
        raise GraderExecutionStorageError("grader attempt completion is malformed")


def _validate_snapshot(
    payload: object,
    *,
    operator_id: str,
    execution_key: str,
) -> None:
    if (
        not isinstance(payload, Mapping)
        or set(payload) != SNAPSHOT_FIELDS
        or _contains_reasoning_content(payload)
    ):
        raise GraderExecutionStorageError("grader execution snapshot is malformed")
    try:
        actual_operator_id = _uuid_text(payload["operator_id"])
        _uuid_text(payload["grader_execution_id"])
        actual_execution_key = _sha256_text(payload["execution_key"])
        _sha256_text(payload["evidence_bundle_hash"])
        _sha256_text(payload["inference_parameter_hash"])
    except (KeyError, TypeError, ValueError) as error:
        raise GraderExecutionStorageError(
            "grader execution snapshot is malformed"
        ) from error
    attempts = payload["attempts"]
    canonical = payload["canonical_execution"]
    if (
        actual_operator_id != operator_id
        or actual_execution_key != execution_key
        or payload["persistence_state"] not in {"draft", "complete"}
        or not isinstance(canonical, Mapping)
        or not isinstance(attempts, list)
        or any(
            not isinstance(item, Mapping)
            or set(item)
            != {
                "attempt",
                "reservation",
                "request_payload",
                "response_payload",
            }
            or not isinstance(item["attempt"], Mapping)
            or not isinstance(item["reservation"], Mapping)
            or not isinstance(item["request_payload"], Mapping)
            or (
                item["response_payload"] is not None
                and not isinstance(item["response_payload"], Mapping)
            )
            for item in attempts
        )
    ):
        raise GraderExecutionStorageError("grader execution snapshot is malformed")
    numbers = [item["attempt"].get("attempt_number") for item in attempts]
    if numbers != sorted(numbers) or len(numbers) != len(set(numbers)):
        raise GraderExecutionStorageError("grader execution snapshot is malformed")


def _validate_finalization_input(execution: Mapping[str, object]) -> None:
    if set(execution) != FINALIZATION_INPUT_FIELDS:
        raise GraderExecutionStorageError("grader execution finalization is malformed")
    try:
        _uuid_text(execution["id"])
    except (TypeError, ValueError) as error:
        raise GraderExecutionStorageError(
            "grader execution finalization is malformed"
        ) from error
    totals = (
        execution["total_input_tokens"],
        execution["total_output_tokens"],
        execution["total_reasoning_tokens"],
        execution["total_tokens"],
    )
    if (
        execution["execution_state"]
        not in {"not_executed", "failed", "abstained", "accepted"}
        or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in totals
        )
        or not isinstance(execution["canonical_execution"], Mapping)
        or _contains_reasoning_content(execution["canonical_execution"])
    ):
        raise GraderExecutionStorageError("grader execution finalization is malformed")


def _execution_receipt(
    payload: object,
    *,
    operator_id: str,
    execution: Mapping[str, object],
    allowed_states: set[str],
    complete_requires_reuse: bool,
) -> GraderExecutionRuntimeReceipt:
    if not isinstance(payload, dict) or set(payload) != EXECUTION_RECEIPT_FIELDS:
        raise GraderExecutionStorageError("grader execution receipt is malformed")
    try:
        receipt = GraderExecutionRuntimeReceipt(
            operator_id=_uuid_text(payload["operator_id"]),
            execution_id=_uuid_text(payload["grader_execution_id"]),
            execution_key=_sha256_text(payload["execution_key"]),
            persistence_state=str(payload["persistence_state"]),
            reused=_strict_bool(payload["reused"]),
            evidence_bundle_hash=_sha256_text(payload["evidence_bundle_hash"]),
            inference_parameter_hash=_sha256_text(payload["inference_parameter_hash"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise GraderExecutionStorageError(
            "grader execution receipt is malformed"
        ) from error
    if (
        receipt.operator_id != operator_id
        or receipt.execution_id != _uuid_text(execution["id"])
        or receipt.execution_key != execution["execution_key"]
        or receipt.evidence_bundle_hash != execution["evidence_bundle_hash"]
        or receipt.inference_parameter_hash != execution["inference_parameter_hash"]
        or receipt.persistence_state not in allowed_states
        or (
            complete_requires_reuse
            and receipt.persistence_state == "complete"
            and not receipt.reused
        )
    ):
        raise GraderExecutionStorageError(
            "grader execution receipt does not match request"
        )
    return receipt


def _attempt_receipt(
    payload: object,
    *,
    operator_id: str,
    attempt: Mapping[str, object],
    reservation: Mapping[str, object],
    allowed_states: set[str],
) -> GraderAttemptRuntimeReceipt:
    if not isinstance(payload, dict) or set(payload) != ATTEMPT_RECEIPT_FIELDS:
        raise GraderExecutionStorageError("grader attempt receipt is malformed")
    try:
        receipt = GraderAttemptRuntimeReceipt(
            operator_id=_uuid_text(payload["operator_id"]),
            execution_id=_uuid_text(payload["grader_execution_id"]),
            attempt_id=_uuid_text(payload["grader_attempt_id"]),
            reservation_id=_uuid_text(payload["budget_reservation_id"]),
            attempt_number=int(payload["attempt_number"]),
            persistence_state=str(payload["persistence_state"]),
            reservation_state=str(payload["reservation_state"]),
            reused=_strict_bool(payload["reused"]),
            request_sha256=_sha256_text(payload["request_sha256"]),
            raw_payload_id=_uuid_text(payload["raw_payload_id"]),
            raw_payload_sha256=_sha256_text(payload["raw_payload_sha256"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise GraderExecutionStorageError(
            "grader attempt receipt is malformed"
        ) from error
    if (
        receipt.operator_id != operator_id
        or receipt.execution_id != _uuid_text(attempt["grader_execution_id"])
        or receipt.attempt_id != _uuid_text(attempt["id"])
        or receipt.reservation_id != _uuid_text(reservation["id"])
        or receipt.attempt_number != attempt["attempt_number"]
        or receipt.request_sha256 != attempt["request_sha256"]
        or receipt.raw_payload_id != _uuid_text(attempt["raw_payload_id"])
        or (
            receipt.persistence_state == "draft"
            and receipt.raw_payload_sha256 != attempt["raw_payload_sha256"]
        )
        or receipt.persistence_state not in allowed_states
        or receipt.reservation_state not in {"reserved", "reconciled", "released"}
        or (receipt.persistence_state == "complete" and not receipt.reused)
    ):
        raise GraderExecutionStorageError(
            "grader attempt receipt does not match request"
        )
    return receipt


def _finished_attempt_receipt(
    payload: object,
    *,
    operator_id: str,
    completion: Mapping[str, object],
) -> GraderAttemptRuntimeReceipt:
    if not isinstance(payload, dict) or set(payload) != ATTEMPT_RECEIPT_FIELDS:
        raise GraderExecutionStorageError("grader attempt receipt is malformed")
    try:
        receipt = GraderAttemptRuntimeReceipt(
            operator_id=_uuid_text(payload["operator_id"]),
            execution_id=_uuid_text(payload["grader_execution_id"]),
            attempt_id=_uuid_text(payload["grader_attempt_id"]),
            reservation_id=_uuid_text(payload["budget_reservation_id"]),
            attempt_number=int(payload["attempt_number"]),
            persistence_state=str(payload["persistence_state"]),
            reservation_state=str(payload["reservation_state"]),
            reused=_strict_bool(payload["reused"]),
            request_sha256=_sha256_text(payload["request_sha256"]),
            raw_payload_id=_uuid_text(payload["raw_payload_id"]),
            raw_payload_sha256=_sha256_text(payload["raw_payload_sha256"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise GraderExecutionStorageError(
            "grader attempt receipt is malformed"
        ) from error
    if (
        receipt.operator_id != operator_id
        or receipt.execution_id != _uuid_text(completion["grader_execution_id"])
        or receipt.attempt_id != _uuid_text(completion["attempt_id"])
        or receipt.reservation_id != _uuid_text(completion["reservation_id"])
        or receipt.attempt_number != completion["attempt_number"]
        or receipt.raw_payload_id != _uuid_text(completion["raw_payload_id"])
        or receipt.raw_payload_sha256 != completion["raw_payload_sha256"]
        or receipt.persistence_state != "complete"
        or receipt.reservation_state != completion["reservation_state"]
    ):
        raise GraderExecutionStorageError(
            "grader attempt receipt does not match request"
        )
    return receipt


def _without_reasoning_content(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _without_reasoning_content(item)
            for key, item in value.items()
            if key not in {"reasoning_content", "encrypted_content"}
        }
    if isinstance(value, (list, tuple)):
        return [
            _without_reasoning_content(item)
            for item in value
            if not (isinstance(item, Mapping) and item.get("type") == "reasoning")
        ]
    return value


def _contains_reasoning_content(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            key in {"reasoning_content", "encrypted_content"}
            or _contains_reasoning_content(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(
            (isinstance(item, Mapping) and item.get("type") == "reasoning")
            or _contains_reasoning_content(item)
            for item in value
        )
    return False


def _uuid_text(value: object) -> str:
    return str(uuid.UUID(str(value)))


def _sha256_text(value: object) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError("invalid SHA-256")
    return value


def _strict_bool(value: object) -> bool:
    if not isinstance(value, bool):
        raise TypeError("expected boolean")
    return value


__all__ = [
    "GraderAttemptRuntimeReceipt",
    "GraderExecutionRuntimeReceipt",
    "GraderExecutionStorageError",
    "SupabaseGraderExecutionRuntimeStore",
]

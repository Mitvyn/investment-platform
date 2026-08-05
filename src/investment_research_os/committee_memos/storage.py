from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Protocol
import re
import uuid

from workers.sec.storage import (
    EvidenceStorageError,
    JsonTransport,
    SupabaseStorageSettings,
    UrllibJsonTransport,
)

from . import (
    CommitteeMemoError,
    CommitteeMemoExecution,
    SynthesisAttempt,
    SynthesisAttemptStartReceipt,
    _raw_attempt_identity,
    _without_reasoning_content,
)


EXECUTION_START_FIELDS = {
    "id",
    "committee_result_id",
    "research_run_id",
    "security_id",
    "evidence_bundle_id",
    "evidence_bundle_hash",
    "workflow_config_version",
    "proposition_id",
    "proposition_version",
    "committee_status",
    "execution_key",
    "prompt_version",
    "model_config_id",
    "provider",
    "model",
    "price_card_version",
    "retry_policy_version",
    "budget_policy_version",
    "max_attempts",
    "started_at",
}
ATTEMPT_START_FIELDS = {
    "id",
    "synthesis_execution_id",
    "attempt_number",
    "request_sha256",
    "reservation_id",
    "reserved_cost_usd",
    "started_at",
    "raw_payload_id",
    "raw_payload_sha256",
}
EXECUTION_RECEIPT_FIELDS = {
    "operator_id",
    "synthesis_execution_id",
    "execution_key",
    "persistence_state",
    "reused",
}
ATTEMPT_RECEIPT_FIELDS = {
    "operator_id",
    "synthesis_execution_id",
    "synthesis_attempt_id",
    "attempt_number",
    "raw_payload_id",
    "raw_payload_sha256",
    "persistence_state",
    "reused",
}
FINAL_RECEIPT_FIELDS = {
    "operator_id",
    "committee_result_id",
    "synthesis_execution_id",
    "execution_key",
    "execution_state",
    "memo_id",
    "persistence_state",
    "reused",
}


class CommitteeMemoRuntimeStorageError(RuntimeError):
    """Raised when synthesis runtime persistence cannot be trusted."""


class RuntimeManagedSynthesisBudgetLedger:
    """Issues IDs while runtime RPCs own atomic budget persistence."""

    def __init__(self) -> None:
        self._reservations: dict[str, Decimal] = {}

    def reserve(self, amount: Decimal) -> str:
        if amount <= 0:
            raise CommitteeMemoError("synthesis budget reservation is invalid")
        reservation_id = str(uuid.uuid4())
        self._reservations[reservation_id] = amount
        return reservation_id

    def reconcile(self, reservation_id: str, actual: Decimal) -> None:
        reserved = self._reservation(reservation_id)
        if actual < 0 or actual > reserved:
            raise CommitteeMemoError("synthesis budget reconciliation is invalid")
        del self._reservations[reservation_id]

    def release(self, reservation_id: str) -> None:
        self._reservation(reservation_id)
        del self._reservations[reservation_id]

    def _reservation(self, reservation_id: str) -> Decimal:
        try:
            uuid.UUID(reservation_id)
            return self._reservations[reservation_id]
        except (KeyError, TypeError, ValueError) as error:
            raise CommitteeMemoError(
                "synthesis budget reservation not found"
            ) from error


@dataclass(frozen=True, slots=True)
class SynthesisExecutionRuntimeReceipt:
    operator_id: str
    execution_id: str
    execution_key: str
    persistence_state: str
    reused: bool


@dataclass(frozen=True, slots=True)
class SynthesisAttemptRuntimeReceipt:
    operator_id: str
    execution_id: str
    attempt_id: str
    attempt_number: int
    raw_payload_id: str
    raw_payload_sha256: str
    persistence_state: str
    reused: bool


class CommitteeMemoReadModel(Protocol):
    def get_for_key(
        self,
        operator_id: str,
        execution_key: str,
    ) -> CommitteeMemoExecution | None: ...

    def get_for_committee(
        self,
        operator_id: str,
        committee_id: str,
    ) -> CommitteeMemoExecution | None: ...


class SupabaseCommitteeMemoRuntimeStore:
    """Maps synthesis lifecycle transitions onto narrow future RPCs."""

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
    ) -> SynthesisExecutionRuntimeReceipt:
        operator_id = _uuid_text(operator_id)
        _validate_execution_start(execution)
        payload = self._rpc(
            "iros_begin_synthesis_execution_runtime",
            {
                "p_operator_id": operator_id,
                "p_execution": dict(execution),
            },
        )
        return _execution_receipt(
            payload,
            operator_id,
            execution,
            allowed_states={"draft", "complete"},
        )

    def begin_attempt(
        self,
        operator_id: str,
        attempt: Mapping[str, object],
        request_payload: Mapping[str, object],
    ) -> SynthesisAttemptRuntimeReceipt:
        operator_id = _uuid_text(operator_id)
        sanitized_request = _without_reasoning_content(request_payload)
        raw_payload_id, raw_payload_sha256 = _raw_attempt_identity(
            operator_id,
            _uuid_text(attempt.get("id")),
            {"request": sanitized_request, "response": None},
        )
        persisted_attempt = {
            **dict(attempt),
            "raw_payload_id": raw_payload_id,
            "raw_payload_sha256": raw_payload_sha256,
        }
        _validate_attempt_start(persisted_attempt)
        payload = self._rpc(
            "iros_begin_synthesis_attempt_runtime",
            {
                "p_operator_id": operator_id,
                "p_attempt": persisted_attempt,
                "p_sanitized_request": sanitized_request,
            },
        )
        return _attempt_receipt(
            payload,
            operator_id,
            persisted_attempt,
            allowed_states={"draft", "complete"},
        )

    def finish_attempt(
        self,
        operator_id: str,
        execution_id: str,
        attempt: SynthesisAttempt,
        response_payload: Mapping[str, object] | None,
    ) -> SynthesisAttemptRuntimeReceipt:
        operator_id = _uuid_text(operator_id)
        execution_id = _uuid_text(execution_id)
        completion = _attempt_completion(execution_id, attempt)
        payload = self._rpc(
            "iros_finish_synthesis_attempt_runtime",
            {
                "p_operator_id": operator_id,
                "p_completion": completion,
                "p_sanitized_response": (
                    None
                    if response_payload is None
                    else _without_reasoning_content(response_payload)
                ),
            },
        )
        return _attempt_receipt(
            payload,
            operator_id,
            {
                "id": attempt.attempt_id,
                "synthesis_execution_id": execution_id,
                "attempt_number": attempt.attempt_number,
            },
            allowed_states={"complete"},
        )

    def finalize_execution(
        self,
        execution: CommitteeMemoExecution,
    ) -> object:
        payload = self._rpc(
            "iros_finalize_synthesis_execution_runtime",
            {
                "p_operator_id": _uuid_text(execution.operator_id),
                "p_execution": _execution_finalization(execution),
            },
        )
        return _final_receipt(payload, execution)

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
            raise CommitteeMemoRuntimeStorageError(
                f"committee memo runtime store failed for {name}"
            ) from error
        if not 200 <= response.status < 300:
            raise CommitteeMemoRuntimeStorageError(
                f"committee memo runtime store returned HTTP "
                f"{response.status} for {name}"
            )
        return response.payload


class SupabaseCommitteeMemoRepository:
    """Persists lifecycle transitions and trusts only exact terminal reloads."""

    def __init__(
        self,
        *,
        runtime_store: SupabaseCommitteeMemoRuntimeStore,
        read_model: CommitteeMemoReadModel,
    ) -> None:
        self._runtime_store = runtime_store
        self._read_model = read_model

    def begin_execution(
        self,
        operator_id: str,
        execution: Mapping[str, object],
    ) -> bool:
        return self._runtime_store.begin_execution(
            operator_id,
            execution,
        ).reused

    def begin_attempt(
        self,
        operator_id: str,
        attempt: Mapping[str, object],
        request_payload: Mapping[str, object],
    ) -> SynthesisAttemptStartReceipt:
        try:
            _uuid_text(attempt.get("reservation_id"))
        except (TypeError, ValueError) as error:
            raise CommitteeMemoRuntimeStorageError(
                "persistent synthesis requires an atomic budget reservation"
            ) from error
        receipt = self._runtime_store.begin_attempt(
            operator_id,
            attempt,
            request_payload,
        )
        if receipt.reused:
            raise CommitteeMemoError(
                "persisted synthesis attempt already existed before provider dispatch"
            )
        return SynthesisAttemptStartReceipt(
            raw_payload_id=receipt.raw_payload_id,
            raw_payload_sha256=receipt.raw_payload_sha256,
            reused=False,
        )

    def finish_attempt(
        self,
        operator_id: str,
        execution_id: str,
        attempt: SynthesisAttempt,
        response_payload: Mapping[str, object] | None,
    ) -> None:
        receipt = self._runtime_store.finish_attempt(
            operator_id,
            execution_id,
            attempt,
            response_payload,
        )
        if (
            receipt.execution_id != execution_id
            or receipt.attempt_id != attempt.attempt_id
            or receipt.attempt_number != attempt.attempt_number
            or receipt.persistence_state != "complete"
        ):
            raise CommitteeMemoRuntimeStorageError(
                "synthesis attempt receipt does not match completion"
            )

    def finalize_execution(
        self,
        execution: CommitteeMemoExecution,
    ) -> CommitteeMemoExecution:
        self._runtime_store.finalize_execution(execution)
        persisted = self._read_model.get_for_committee(
            execution.operator_id,
            execution.committee_id,
        )
        if persisted is None:
            raise CommitteeMemoRuntimeStorageError(
                "reloaded committee memo execution is unavailable"
            )
        if persisted != execution:
            raise CommitteeMemoRuntimeStorageError(
                "reloaded committee memo execution does not match"
            )
        return persisted

    def get_for_key(
        self,
        operator_id: str,
        execution_key: str,
    ) -> CommitteeMemoExecution | None:
        return self._read_model.get_for_key(operator_id, execution_key)

    def get_for_committee(
        self,
        operator_id: str,
        committee_id: str,
    ) -> CommitteeMemoExecution | None:
        return self._read_model.get_for_committee(operator_id, committee_id)


def _validate_execution_start(execution: Mapping[str, object]) -> None:
    try:
        if set(execution) != EXECUTION_START_FIELDS:
            raise ValueError
        for field in (
            "id",
            "committee_result_id",
            "research_run_id",
            "security_id",
            "evidence_bundle_id",
        ):
            _uuid_text(execution[field])
        _sha256_text(execution["evidence_bundle_hash"])
        _sha256_text(execution["execution_key"])
        _timestamp_text(execution["started_at"])
        if execution["max_attempts"] != 2 or _contains_reasoning_content(execution):
            raise ValueError
    except (KeyError, TypeError, ValueError) as error:
        raise CommitteeMemoRuntimeStorageError(
            "synthesis execution start is malformed"
        ) from error


def _validate_attempt_start(attempt: Mapping[str, object]) -> None:
    try:
        if set(attempt) != ATTEMPT_START_FIELDS:
            raise ValueError
        for field in (
            "id",
            "synthesis_execution_id",
            "reservation_id",
            "raw_payload_id",
        ):
            _uuid_text(attempt[field])
        _sha256_text(attempt["request_sha256"])
        _sha256_text(attempt["raw_payload_sha256"])
        _timestamp_text(attempt["started_at"])
        if attempt["attempt_number"] not in (1, 2) or not re.fullmatch(
            r"\d+(?:\.\d+)?", str(attempt["reserved_cost_usd"])
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError) as error:
        raise CommitteeMemoRuntimeStorageError(
            "synthesis attempt start is malformed"
        ) from error


def _attempt_completion(
    execution_id: str,
    attempt: SynthesisAttempt,
) -> dict[str, object]:
    return {
        "synthesis_execution_id": execution_id,
        "attempt_id": _uuid_text(attempt.attempt_id),
        "attempt_number": attempt.attempt_number,
        "request_sha256": _sha256_text(attempt.request_hash),
        "provider_request_id": attempt.provider_request_id,
        "result": (
            "transport_error"
            if attempt.validation_errors and attempt.provider_request_id is None
            else ("validation_error" if attempt.validation_errors else "accepted")
        ),
        "raw_payload_id": _uuid_text(attempt.raw_payload_id),
        "raw_payload_sha256": _sha256_text(attempt.raw_payload_sha256),
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
    }


def _execution_finalization(
    execution: CommitteeMemoExecution,
) -> dict[str, object]:
    attempts = execution.attempts
    # This field is mandatory in the future RPC contract. The currently
    # deployed synthesis tables omit it, so failed executions cannot reload
    # with exact usage and the repository intentionally fails closed.
    return {
        "id": _uuid_text(execution.execution_id),
        "committee_result_id": _uuid_text(execution.committee_id),
        "execution_key": _sha256_text(execution.execution_key),
        "execution_state": execution.execution_state,
        "attempt_count": len(attempts),
        "total_input_tokens": sum(item.usage.input_tokens for item in attempts),
        "total_cached_input_tokens": sum(
            item.usage.cached_input_tokens for item in attempts
        ),
        "total_cache_write_tokens": sum(
            item.usage.cache_write_tokens for item in attempts
        ),
        "total_uncached_input_tokens": sum(
            item.usage.input_tokens
            - item.usage.cached_input_tokens
            - item.usage.cache_write_tokens
            for item in attempts
        ),
        "total_output_tokens": sum(item.usage.output_tokens for item in attempts),
        "total_reasoning_tokens": sum(item.usage.reasoning_tokens for item in attempts),
        "total_tokens": sum(item.usage.total_tokens for item in attempts),
        "total_cost_usd": format(
            sum(
                (Decimal(item.estimated_cost_usd) for item in attempts),
                Decimal("0"),
            ),
            "f",
        ),
        "final_validation_errors": (
            list(attempts[-1].validation_errors) if attempts else []
        ),
        "completed_at": execution.created_at.isoformat(),
        "memo": None if execution.memo is None else execution.memo.as_dict(),
    }


def _execution_receipt(
    payload: object,
    operator_id: str,
    execution: Mapping[str, object],
    *,
    allowed_states: set[str],
) -> SynthesisExecutionRuntimeReceipt:
    row = _one_row(payload, EXECUTION_RECEIPT_FIELDS, "execution")
    try:
        receipt = SynthesisExecutionRuntimeReceipt(
            operator_id=_uuid_text(row["operator_id"]),
            execution_id=_uuid_text(row["synthesis_execution_id"]),
            execution_key=_sha256_text(row["execution_key"]),
            persistence_state=str(row["persistence_state"]),
            reused=_bool(row["reused"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise CommitteeMemoRuntimeStorageError(
            "synthesis execution receipt is malformed"
        ) from error
    if (
        receipt.operator_id != operator_id
        or receipt.execution_id != execution["id"]
        or receipt.execution_key != execution["execution_key"]
        or receipt.persistence_state not in allowed_states
        or (receipt.persistence_state == "complete" and not receipt.reused)
    ):
        raise CommitteeMemoRuntimeStorageError(
            "synthesis execution receipt does not match request"
        )
    return receipt


def _attempt_receipt(
    payload: object,
    operator_id: str,
    attempt: Mapping[str, object],
    *,
    allowed_states: set[str],
) -> SynthesisAttemptRuntimeReceipt:
    row = _one_row(payload, ATTEMPT_RECEIPT_FIELDS, "attempt")
    try:
        receipt = SynthesisAttemptRuntimeReceipt(
            operator_id=_uuid_text(row["operator_id"]),
            execution_id=_uuid_text(row["synthesis_execution_id"]),
            attempt_id=_uuid_text(row["synthesis_attempt_id"]),
            attempt_number=_positive_int(row["attempt_number"]),
            raw_payload_id=_uuid_text(row["raw_payload_id"]),
            raw_payload_sha256=_sha256_text(row["raw_payload_sha256"]),
            persistence_state=str(row["persistence_state"]),
            reused=_bool(row["reused"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise CommitteeMemoRuntimeStorageError(
            "synthesis attempt receipt is malformed"
        ) from error
    if (
        receipt.operator_id != operator_id
        or receipt.execution_id != attempt["synthesis_execution_id"]
        or receipt.attempt_id != attempt["id"]
        or receipt.attempt_number != attempt["attempt_number"]
        or receipt.persistence_state not in allowed_states
        or (
            "raw_payload_id" in attempt
            and receipt.raw_payload_id != attempt["raw_payload_id"]
        )
        or (
            "raw_payload_sha256" in attempt
            and receipt.raw_payload_sha256 != attempt["raw_payload_sha256"]
        )
    ):
        raise CommitteeMemoRuntimeStorageError(
            "synthesis attempt receipt does not match request"
        )
    return receipt


def _final_receipt(
    payload: object,
    execution: CommitteeMemoExecution,
) -> Mapping[str, object]:
    row = _one_row(payload, FINAL_RECEIPT_FIELDS, "finalization")
    expected_memo_id = None if execution.memo is None else execution.memo.memo_id
    try:
        valid = (
            _uuid_text(row["operator_id"]) == execution.operator_id
            and _uuid_text(row["committee_result_id"]) == execution.committee_id
            and _uuid_text(row["synthesis_execution_id"]) == execution.execution_id
            and _sha256_text(row["execution_key"]) == execution.execution_key
            and row["execution_state"] == execution.execution_state
            and (
                row["memo_id"] is None
                if expected_memo_id is None
                else _uuid_text(row["memo_id"]) == expected_memo_id
            )
            and row["persistence_state"] == "complete"
            and isinstance(row["reused"], bool)
        )
    except (KeyError, TypeError, ValueError) as error:
        raise CommitteeMemoRuntimeStorageError(
            "synthesis finalization receipt is malformed"
        ) from error
    if not valid:
        raise CommitteeMemoRuntimeStorageError(
            "synthesis finalization receipt does not match result"
        )
    return row


def _one_row(
    payload: object,
    fields: set[str],
    label: str,
) -> Mapping[str, object]:
    if (
        not isinstance(payload, list)
        or len(payload) != 1
        or not isinstance(payload[0], Mapping)
        or set(payload[0]) != fields
    ):
        raise CommitteeMemoRuntimeStorageError(
            f"synthesis {label} receipt is malformed"
        )
    return payload[0]


def _contains_reasoning_content(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            key == "reasoning_content" or _contains_reasoning_content(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_reasoning_content(item) for item in value)
    return False


def _timestamp_text(value: object) -> str:
    text = str(value)
    if "T" not in text or not (text.endswith("Z") or "+" in text[10:]):
        raise ValueError("timestamp timezone missing")
    return text


def _uuid_text(value: object) -> str:
    return str(uuid.UUID(str(value)))


def _sha256_text(value: object) -> str:
    text = str(value)
    if re.fullmatch(r"[0-9a-f]{64}", text) is None:
        raise ValueError("sha256 invalid")
    return text


def _positive_int(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError("positive integer required")
    return value


def _bool(value: object) -> bool:
    if type(value) is not bool:
        raise TypeError("boolean required")
    return value


__all__ = [
    "CommitteeMemoRuntimeStorageError",
    "RuntimeManagedSynthesisBudgetLedger",
    "SupabaseCommitteeMemoRepository",
    "SupabaseCommitteeMemoRuntimeStore",
    "SynthesisAttemptRuntimeReceipt",
    "SynthesisExecutionRuntimeReceipt",
]

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from urllib.parse import urlencode
import uuid

from investment_research_os.grader_executions import ProviderUsage
from workers.sec.storage import (
    EvidenceStorageError,
    JsonTransport,
    SupabaseStorageSettings,
    UrllibJsonTransport,
)

from . import (
    CommitteeMemo,
    CommitteeMemoExecution,
    MemoReviewTrigger,
    MemoStateDisclosure,
    MemoStatement,
    SynthesisAttempt,
)


EXECUTION_ROW_FIELDS = {
    "id",
    "operator_id",
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
    "budget_id",
    "execution_state",
    "attempt_count",
    "total_input_tokens",
    "total_cached_input_tokens",
    "total_cache_write_tokens",
    "total_uncached_input_tokens",
    "total_output_tokens",
    "total_reasoning_tokens",
    "total_tokens",
    "usage_complete",
    "total_cost_usd",
    "final_validation_errors",
    "started_at",
    "completed_at",
    "persistence_state",
    "created_at",
}
ATTEMPT_ROW_FIELDS = {
    "id",
    "operator_id",
    "synthesis_execution_id",
    "attempt_number",
    "request_sha256",
    "provider_request_id",
    "result",
    "raw_payload_id",
    "raw_payload_sha256",
    "budget_reservation_id",
    "input_tokens",
    "cached_input_tokens",
    "cache_write_tokens",
    "uncached_input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "total_tokens",
    "usage_complete",
    "estimated_cost_usd",
    "validation_status",
    "validation_errors",
    "retry_reason",
    "started_at",
    "completed_at",
    "duration_ms",
    "persistence_state",
    "created_at",
}
MEMO_ROW_FIELDS = {
    "operator_id",
    "research_run_id",
    "committee_result_id",
    "memo_id",
    "canonical_memo",
}
MEMO_FIELDS = {
    "contract_version",
    "memo_id",
    "synthesis_execution_id",
    "committee_id",
    "research_run_id",
    "evidence_bundle_id",
    "evidence_bundle_hash",
    "workflow_config_version",
    "proposition_id",
    "proposition_version",
    "committee_status",
    "requested_disposition",
    "executive_summary_statement_ids",
    "statements",
    "common_ground_statement_ids",
    "disagreement_records",
    "disputed_assumption_statement_ids",
    "evidence_gap_statement_ids",
    "invalidation_statement_ids",
    "required_next_evidence_statement_ids",
    "review_trigger",
    "state_disclosure",
    "execution_metadata",
    "created_at",
}
STATEMENT_FIELDS = {
    "statement_id",
    "text",
    "provenance_type",
    "evidence_ids",
    "opinion_ids",
    "calculation_ids",
}
REVIEW_TRIGGER_FIELDS = {"trigger_type", "review_at", "statement_id"}
STATE_DISCLOSURE_FIELDS = {
    "grader_id",
    "execution_state",
    "opinion_id",
    "stance",
}
EXECUTION_METADATA_FIELDS = {
    "prompt_version",
    "model_config_id",
    "provider",
    "model",
    "attempt_count",
    "provider_request_ids",
    "attempts",
    "input_tokens",
    "cached_input_tokens",
    "cache_write_tokens",
    "uncached_input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "total_tokens",
    "usage_complete",
    "estimated_cost_usd",
    "price_card_version",
    "retry_policy_version",
    "started_at",
    "completed_at",
}
ATTEMPT_METADATA_FIELDS = {
    "attempt_id",
    "attempt_number",
    "provider_request_id",
    "result",
    "validation_status",
    "validation_errors",
    "retry_reason",
    "started_at",
    "completed_at",
    "duration_ms",
    "input_tokens",
    "cached_input_tokens",
    "cache_write_tokens",
    "uncached_input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "total_tokens",
    "usage_complete",
    "estimated_cost_usd",
}


class SupabaseCommitteeMemoReadModel:
    """Reconstruct one owner-scoped terminal synthesis without raw provider bodies."""

    def __init__(
        self,
        settings: SupabaseStorageSettings,
        *,
        transport: JsonTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport or UrllibJsonTransport(settings.timeout_seconds)

    def get_for_committee(
        self,
        operator_id: str,
        committee_id: str,
    ) -> CommitteeMemoExecution | None:
        return self._get_one(
            operator_id,
            {
                "committee_result_id": f"eq.{_uuid_text(committee_id)}",
            },
        )

    def get_for_key(
        self,
        operator_id: str,
        execution_key: str,
    ) -> CommitteeMemoExecution | None:
        return self._get_one(
            operator_id,
            {
                "execution_key": f"eq.{_sha256(execution_key)}",
            },
        )

    def _get_one(
        self,
        operator_id: str,
        filters: Mapping[str, str],
    ) -> CommitteeMemoExecution | None:
        operator_id = _uuid_text(operator_id)
        execution_rows = self._read(
            "iros_synthesis_executions",
            {
                "operator_id": f"eq.{operator_id}",
                **filters,
                "persistence_state": "eq.complete",
                "select": ",".join(sorted(EXECUTION_ROW_FIELDS)),
            },
            "synthesis execution",
        )
        if not execution_rows:
            return None
        if len(execution_rows) != 1:
            raise EvidenceStorageError(
                "synthesis execution store returned duplicate rows"
            )
        execution_row = _exact_mapping(
            execution_rows[0],
            EXECUTION_ROW_FIELDS,
            "synthesis execution",
        )
        execution_id = _uuid_text(execution_row["id"])
        committee_id = _uuid_text(execution_row["committee_result_id"])
        attempt_rows = self._read(
            "iros_synthesis_attempts",
            {
                "operator_id": f"eq.{operator_id}",
                "synthesis_execution_id": f"eq.{execution_id}",
                "persistence_state": "eq.complete",
                "select": ",".join(sorted(ATTEMPT_ROW_FIELDS)),
                "order": "attempt_number.asc",
            },
            "synthesis attempt",
        )
        memo_rows = self._read(
            "iros_v_research_run_committee_memos",
            {
                "operator_id": f"eq.{operator_id}",
                "committee_result_id": f"eq.{committee_id}",
                "select": ",".join(sorted(MEMO_ROW_FIELDS)),
            },
            "committee memo",
        )
        try:
            return _execution(
                operator_id,
                committee_id,
                execution_row,
                attempt_rows,
                memo_rows,
            )
        except (KeyError, TypeError, ValueError, InvalidOperation) as error:
            raise EvidenceStorageError(
                "persisted committee memo state is inconsistent"
            ) from error

    def _read(
        self,
        table: str,
        filters: Mapping[str, str],
        label: str,
    ) -> list[object]:
        response = self.transport.request_json(
            "GET",
            (f"{self.settings.url.rstrip('/')}/rest/v1/{table}?{urlencode(filters)}"),
            headers={"apikey": self.settings.secret_key},
        )
        if response.status != 200 or not isinstance(response.payload, list):
            raise EvidenceStorageError(f"{label} store returned malformed response")
        return response.payload


def _execution(
    operator_id: str,
    committee_id: str,
    row: Mapping[str, object],
    raw_attempt_rows: list[object],
    raw_memo_rows: list[object],
) -> CommitteeMemoExecution:
    if (
        _uuid_text(row["operator_id"]) != operator_id
        or _uuid_text(row["committee_result_id"]) != committee_id
        or row["persistence_state"] != "complete"
    ):
        raise ValueError("synthesis execution ownership mismatch")
    execution_id = _uuid_text(row["id"])
    attempt_rows = tuple(
        _exact_mapping(item, ATTEMPT_ROW_FIELDS, "synthesis attempt")
        for item in raw_attempt_rows
    )
    if len(attempt_rows) != _nonnegative_int(row["attempt_count"]):
        raise ValueError("synthesis attempt count mismatch")
    for number, attempt_row in enumerate(attempt_rows, start=1):
        if (
            _uuid_text(attempt_row["operator_id"]) != operator_id
            or _uuid_text(attempt_row["synthesis_execution_id"]) != execution_id
            or attempt_row["persistence_state"] != "complete"
            or _positive_int(attempt_row["attempt_number"]) != number
        ):
            raise ValueError("synthesis attempt identity mismatch")

    state = _text(row["execution_state"])
    if state not in {"accepted", "failed"}:
        raise ValueError("synthesis execution is not terminal")
    memo_rows = tuple(
        _exact_mapping(item, MEMO_ROW_FIELDS, "committee memo")
        for item in raw_memo_rows
    )
    if state == "accepted" and len(memo_rows) != 1:
        raise ValueError("accepted synthesis must have one memo")
    if state == "failed" and memo_rows:
        raise ValueError("failed synthesis cannot have a memo")

    memo: CommitteeMemo | None = None
    if memo_rows:
        memo_row = memo_rows[0]
        if (
            _uuid_text(memo_row["operator_id"]) != operator_id
            or _uuid_text(memo_row["committee_result_id"]) != committee_id
            or _uuid_text(memo_row["research_run_id"])
            != _uuid_text(row["research_run_id"])
        ):
            raise ValueError("committee memo ownership mismatch")
        memo = _memo(row, attempt_rows, memo_row)
        attempts = memo.attempts
    else:
        attempts = tuple(_failed_attempt(item) for item in attempt_rows)

    _validate_totals(row, attempts)
    return CommitteeMemoExecution(
        execution_id=execution_id,
        execution_key=_sha256(row["execution_key"]),
        operator_id=operator_id,
        committee_id=committee_id,
        execution_state=state,
        attempts=attempts,
        memo=memo,
        created_at=_timestamp(row["completed_at"]),
    )


def _memo(
    execution_row: Mapping[str, object],
    attempt_rows: tuple[Mapping[str, object], ...],
    memo_row: Mapping[str, object],
) -> CommitteeMemo:
    payload = _exact_mapping(memo_row["canonical_memo"], MEMO_FIELDS, "canonical memo")
    if payload["contract_version"] != "committee_memo.v1":
        raise ValueError("committee memo contract version invalid")
    execution_id = _uuid_text(execution_row["id"])
    identity_pairs = (
        (payload["memo_id"], memo_row["memo_id"], _uuid_text),
        (payload["synthesis_execution_id"], execution_id, _uuid_text),
        (payload["committee_id"], execution_row["committee_result_id"], _uuid_text),
        (payload["research_run_id"], execution_row["research_run_id"], _uuid_text),
        (
            payload["evidence_bundle_id"],
            execution_row["evidence_bundle_id"],
            _uuid_text,
        ),
        (
            payload["evidence_bundle_hash"],
            execution_row["evidence_bundle_hash"],
            _sha256,
        ),
        (
            payload["workflow_config_version"],
            execution_row["workflow_config_version"],
            _text,
        ),
        (payload["proposition_id"], execution_row["proposition_id"], _text),
        (payload["proposition_version"], execution_row["proposition_version"], _text),
        (payload["committee_status"], execution_row["committee_status"], _text),
    )
    for actual, expected, normalizer in identity_pairs:
        if normalizer(actual) != normalizer(expected):
            raise ValueError("committee memo identity mismatch")

    metadata = _exact_mapping(
        payload["execution_metadata"],
        EXECUTION_METADATA_FIELDS,
        "synthesis execution metadata",
    )
    attempt_payloads = _mapping_list(metadata["attempts"])
    if len(attempt_payloads) != len(attempt_rows):
        raise ValueError("memo attempt count mismatch")
    attempts = tuple(
        _accepted_attempt(row, attempt_payload)
        for row, attempt_payload in zip(attempt_rows, attempt_payloads, strict=True)
    )
    usage = ProviderUsage(
        input_tokens=_nonnegative_int(metadata["input_tokens"]),
        cached_input_tokens=_nonnegative_int(metadata["cached_input_tokens"]),
        output_tokens=_nonnegative_int(metadata["output_tokens"]),
        reasoning_tokens=_nonnegative_int(metadata["reasoning_tokens"]),
        total_tokens=_nonnegative_int(metadata["total_tokens"]),
        usage_complete=_bool(metadata["usage_complete"]),
        cache_write_tokens=_nonnegative_int(metadata["cache_write_tokens"]),
    )
    statements = tuple(
        _statement(item) for item in _mapping_list(payload["statements"])
    )
    trigger_payload = _exact_mapping(
        payload["review_trigger"],
        REVIEW_TRIGGER_FIELDS,
        "review trigger",
    )
    disclosures = tuple(
        _state_disclosure(item) for item in _mapping_list(payload["state_disclosure"])
    )
    started_at = _timestamp(metadata["started_at"])
    completed_at = _timestamp(metadata["completed_at"])
    memo = CommitteeMemo(
        memo_id=_uuid_text(payload["memo_id"]),
        synthesis_execution_id=execution_id,
        committee_id=_uuid_text(payload["committee_id"]),
        research_run_id=_uuid_text(payload["research_run_id"]),
        evidence_bundle_id=_uuid_text(payload["evidence_bundle_id"]),
        evidence_bundle_hash=_sha256(payload["evidence_bundle_hash"]),
        workflow_config_version=_text(payload["workflow_config_version"]),
        proposition_id=_text(payload["proposition_id"]),
        proposition_version=_text(payload["proposition_version"]),
        committee_status=_text(payload["committee_status"]),
        requested_disposition=_text(payload["requested_disposition"]),
        executive_summary_statement_ids=_text_tuple(
            payload["executive_summary_statement_ids"]
        ),
        statements=statements,
        common_ground_statement_ids=_text_tuple(payload["common_ground_statement_ids"]),
        disagreement_records=tuple(
            dict(item) for item in _mapping_list(payload["disagreement_records"])
        ),
        disputed_assumption_statement_ids=_text_tuple(
            payload["disputed_assumption_statement_ids"]
        ),
        evidence_gap_statement_ids=_text_tuple(payload["evidence_gap_statement_ids"]),
        invalidation_statement_ids=_text_tuple(payload["invalidation_statement_ids"]),
        required_next_evidence_statement_ids=_text_tuple(
            payload["required_next_evidence_statement_ids"]
        ),
        review_trigger=MemoReviewTrigger(
            trigger_type=_text(trigger_payload["trigger_type"]),
            review_at=_optional_text(trigger_payload["review_at"]),
            statement_id=_text(trigger_payload["statement_id"]),
        ),
        state_disclosure=disclosures,
        prompt_version=_text(metadata["prompt_version"]),
        model_config_id=_text(metadata["model_config_id"]),
        provider=_text(metadata["provider"]),
        model=_text(metadata["model"]),
        attempt_count=_nonnegative_int(metadata["attempt_count"]),
        provider_request_ids=_optional_text_tuple(metadata["provider_request_ids"]),
        attempts=attempts,
        usage=usage,
        estimated_cost_usd=_decimal_text(metadata["estimated_cost_usd"]),
        price_card_version=_text(metadata["price_card_version"]),
        retry_policy_version=_text(metadata["retry_policy_version"]),
        started_at=started_at,
        created_at=completed_at,
    )
    _validate_memo_provenance(memo)
    _validate_memo_usage(memo)
    if memo.as_dict() != dict(payload):
        raise ValueError("canonical memo does not round-trip")
    for field in (
        "prompt_version",
        "model_config_id",
        "provider",
        "model",
        "price_card_version",
        "retry_policy_version",
    ):
        if _text(metadata[field]) != _text(execution_row[field]):
            raise ValueError("memo execution configuration mismatch")
    if (
        memo.attempt_count != len(attempts)
        or memo.created_at != _timestamp(execution_row["completed_at"])
        or memo.started_at != _timestamp(execution_row["started_at"])
    ):
        raise ValueError("memo execution timing mismatch")
    return memo


def _accepted_attempt(
    row: Mapping[str, object],
    raw_metadata: Mapping[str, object],
) -> SynthesisAttempt:
    metadata = _exact_mapping(
        raw_metadata,
        ATTEMPT_METADATA_FIELDS,
        "synthesis attempt metadata",
    )
    direct_pairs = (
        ("attempt_id", "id"),
        ("attempt_number", "attempt_number"),
        ("provider_request_id", "provider_request_id"),
        ("result", "result"),
        ("validation_status", "validation_status"),
        ("validation_errors", "validation_errors"),
        ("retry_reason", "retry_reason"),
        ("started_at", "started_at"),
        ("completed_at", "completed_at"),
        ("duration_ms", "duration_ms"),
        ("input_tokens", "input_tokens"),
        ("cached_input_tokens", "cached_input_tokens"),
        ("cache_write_tokens", "cache_write_tokens"),
        ("uncached_input_tokens", "uncached_input_tokens"),
        ("output_tokens", "output_tokens"),
        ("reasoning_tokens", "reasoning_tokens"),
        ("total_tokens", "total_tokens"),
        ("usage_complete", "usage_complete"),
    )
    for memo_key, row_key in direct_pairs:
        if metadata[memo_key] != row[row_key]:
            raise ValueError("canonical attempt does not match persisted attempt")
    if _decimal(metadata["estimated_cost_usd"]) != _decimal(row["estimated_cost_usd"]):
        raise ValueError("canonical attempt cost mismatch")
    usage = ProviderUsage(
        input_tokens=_nonnegative_int(metadata["input_tokens"]),
        cached_input_tokens=_nonnegative_int(metadata["cached_input_tokens"]),
        output_tokens=_nonnegative_int(metadata["output_tokens"]),
        reasoning_tokens=_nonnegative_int(metadata["reasoning_tokens"]),
        total_tokens=_nonnegative_int(metadata["total_tokens"]),
        usage_complete=_bool(metadata["usage_complete"]),
        cache_write_tokens=_nonnegative_int(metadata["cache_write_tokens"]),
    )
    return _attempt(row, usage)


def _failed_attempt(row: Mapping[str, object]) -> SynthesisAttempt:
    return _attempt(
        row,
        ProviderUsage(
            input_tokens=_nonnegative_int(row["input_tokens"]),
            cached_input_tokens=_nonnegative_int(row["cached_input_tokens"]),
            output_tokens=_nonnegative_int(row["output_tokens"]),
            reasoning_tokens=_nonnegative_int(row["reasoning_tokens"]),
            total_tokens=_nonnegative_int(row["total_tokens"]),
            usage_complete=_bool(row["usage_complete"]),
            cache_write_tokens=_nonnegative_int(row["cache_write_tokens"]),
        ),
    )


def _attempt(
    row: Mapping[str, object],
    usage: ProviderUsage,
) -> SynthesisAttempt:
    started_at = _timestamp(row["started_at"])
    completed_at = _timestamp(row["completed_at"])
    if int((completed_at - started_at).total_seconds() * 1000) != _nonnegative_int(
        row["duration_ms"]
    ):
        raise ValueError("synthesis attempt duration mismatch")
    errors = _text_tuple(row["validation_errors"])
    expected_result = (
        "transport_error"
        if errors and row["provider_request_id"] is None
        else ("validation_error" if errors else "accepted")
    )
    expected_status = "failed" if errors else "passed"
    if (
        row["result"] != expected_result
        or row["validation_status"] != expected_status
        or row["retry_reason"] != (errors[0] if errors else None)
    ):
        raise ValueError("synthesis attempt validation state mismatch")
    if (
        usage.input_tokens - usage.cached_input_tokens - usage.cache_write_tokens
        != _nonnegative_int(row["uncached_input_tokens"])
    ):
        raise ValueError("synthesis attempt uncached usage mismatch")
    return SynthesisAttempt(
        attempt_id=_uuid_text(row["id"]),
        attempt_number=_positive_int(row["attempt_number"]),
        request_hash=_sha256(row["request_sha256"]),
        provider_request_id=_optional_text(row["provider_request_id"]),  # type: ignore[arg-type]
        raw_payload_id=_uuid_text(row["raw_payload_id"]),
        raw_payload_sha256=_sha256(row["raw_payload_sha256"]),
        validation_errors=errors,
        usage=usage,
        estimated_cost_usd=_decimal_text(row["estimated_cost_usd"]),
        started_at=started_at,
        finished_at=completed_at,
    )


def _validate_memo_provenance(memo: CommitteeMemo) -> None:
    by_id = {item.statement_id: item for item in memo.statements}
    if len(by_id) != len(memo.statements):
        raise ValueError("duplicate memo statement")
    category_ids = (
        *memo.executive_summary_statement_ids,
        *memo.common_ground_statement_ids,
        *memo.disputed_assumption_statement_ids,
        *memo.evidence_gap_statement_ids,
        *memo.invalidation_statement_ids,
        *memo.required_next_evidence_statement_ids,
        memo.review_trigger.statement_id,
    )
    if any(statement_id not in by_id for statement_id in category_ids):
        raise ValueError("memo statement reference mismatch")
    allowed_opinions = {
        item.opinion_id for item in memo.state_disclosure if item.opinion_id is not None
    }
    for statement in memo.statements:
        if statement.provenance_type not in {
            "fact",
            "grader_interpretation",
            "synthesis_interpretation",
            "assumption",
            "gap",
        }:
            raise ValueError("memo provenance type invalid")
        if any(item not in allowed_opinions for item in statement.opinion_ids):
            raise ValueError("memo opinion provenance mismatch")
        if statement.provenance_type == "fact" and not statement.evidence_ids:
            raise ValueError("memo fact is uncited")
        if (
            statement.provenance_type == "grader_interpretation"
            and len(statement.opinion_ids) != 1
        ):
            raise ValueError("memo grader provenance invalid")
        if (
            statement.provenance_type == "synthesis_interpretation"
            and len(statement.opinion_ids) < 2
        ):
            raise ValueError("memo synthesis provenance invalid")
        if statement.provenance_type in {"assumption", "gap"} and not (
            statement.evidence_ids or statement.opinion_ids or statement.calculation_ids
        ):
            raise ValueError("memo statement provenance missing")


def _validate_memo_usage(memo: CommitteeMemo) -> None:
    if (
        memo.attempt_count != len(memo.attempts)
        or memo.provider_request_ids
        != tuple(item.provider_request_id for item in memo.attempts)
        or memo.usage.input_tokens
        != sum(item.usage.input_tokens for item in memo.attempts)
        or memo.usage.cached_input_tokens
        != sum(item.usage.cached_input_tokens for item in memo.attempts)
        or memo.usage.cache_write_tokens
        != sum(item.usage.cache_write_tokens for item in memo.attempts)
        or memo.usage.output_tokens
        != sum(item.usage.output_tokens for item in memo.attempts)
        or memo.usage.reasoning_tokens
        != sum(item.usage.reasoning_tokens for item in memo.attempts)
        or memo.usage.total_tokens
        != sum(item.usage.total_tokens for item in memo.attempts)
        or _decimal(memo.estimated_cost_usd)
        != sum(
            (_decimal(item.estimated_cost_usd) for item in memo.attempts),
            Decimal("0"),
        )
    ):
        raise ValueError("memo usage does not match attempts")


def _statement(value: Mapping[str, object]) -> MemoStatement:
    row = _exact_mapping(value, STATEMENT_FIELDS, "memo statement")
    return MemoStatement(
        statement_id=_text(row["statement_id"]),
        text=_text(row["text"]),
        provenance_type=_text(row["provenance_type"]),
        evidence_ids=_text_tuple(row["evidence_ids"]),
        opinion_ids=_text_tuple(row["opinion_ids"]),
        calculation_ids=_text_tuple(row["calculation_ids"]),
    )


def _state_disclosure(value: Mapping[str, object]) -> MemoStateDisclosure:
    row = _exact_mapping(value, STATE_DISCLOSURE_FIELDS, "state disclosure")
    return MemoStateDisclosure(
        grader_id=_text(row["grader_id"]),
        execution_state=_text(row["execution_state"]),
        opinion_id=_optional_text(row["opinion_id"]),
        stance=_optional_text(row["stance"]),
    )


def _validate_totals(
    row: Mapping[str, object],
    attempts: tuple[SynthesisAttempt, ...],
) -> None:
    totals = {
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
        "total_reasoning_tokens": sum(
            item.usage.reasoning_tokens for item in attempts
        ),
        "total_tokens": sum(item.usage.total_tokens for item in attempts),
    }
    if any(_nonnegative_int(row[key]) != value for key, value in totals.items()):
        raise ValueError("synthesis execution usage totals mismatch")
    if _decimal(row["total_cost_usd"]) != sum(
        (_decimal(item.estimated_cost_usd) for item in attempts),
        Decimal("0"),
    ):
        raise ValueError("synthesis execution cost total mismatch")
    if _bool(row["usage_complete"]) != all(
        item.usage.usage_complete for item in attempts
    ):
        raise ValueError("synthesis execution usage completeness mismatch")


def _exact_mapping(
    value: object,
    fields: set[str],
    label: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f"{label} is malformed")
    return value


def _mapping_list(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list) or any(
        not isinstance(item, Mapping) for item in value
    ):
        raise TypeError("expected object list")
    return value


def _text_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TypeError("expected string list")
    return tuple(_text(item) for item in value)


def _optional_text_tuple(value: object) -> tuple[str | None, ...]:
    if not isinstance(value, list):
        raise TypeError("expected optional string list")
    return tuple(_optional_text(item) for item in value)


def _text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("expected non-empty text")
    return value


def _optional_text(value: object) -> str | None:
    return None if value is None else _text(value)


def _bool(value: object) -> bool:
    if type(value) is not bool:
        raise TypeError("expected boolean")
    return value


def _nonnegative_int(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("expected nonnegative integer")
    return value


def _positive_int(value: object) -> int:
    parsed = _nonnegative_int(value)
    if parsed == 0:
        raise ValueError("expected positive integer")
    return parsed


def _decimal(value: object) -> Decimal:
    parsed = Decimal(str(value))
    if not parsed.is_finite() or parsed < 0:
        raise InvalidOperation
    return parsed


def _decimal_text(value: object) -> str:
    _decimal(value)
    return str(value)


def _timestamp(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp timezone missing")
    return parsed


def _uuid_text(value: object) -> str:
    return str(uuid.UUID(str(value)))


def _sha256(value: object) -> str:
    text = str(value)
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise ValueError("sha256 invalid")
    return text


__all__ = ["SupabaseCommitteeMemoReadModel"]

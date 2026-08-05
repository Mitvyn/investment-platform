from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Mapping, Protocol
import uuid

from investment_research_os.evidence_bundles import EvidenceBundle
from investment_research_os.grader_executions import (
    AbstentionResult,
    ContradictingEvidence,
    EvidenceGap,
    GraderAttempt,
    GraderExecution,
    GraderExecutionRequest,
    GraderOpinion,
    MaterialClaim,
    ProviderUsage,
    _terminal_execution,
)
from investment_research_os.grader_executions.runtime import (
    ExecutionStart,
    RuntimeExecutionSnapshot,
    canonical_payload_sha256,
)


class PersistentExecutionReadError(RuntimeError):
    """Raised when persisted grader state cannot reconstruct a terminal result."""


class RawGraderExecutionRuntimeStore(Protocol):
    def load(
        self,
        operator_id: str,
        execution_key: str,
    ) -> Mapping[str, object] | None: ...


ATTEMPT_FIELDS = {
    "id",
    "grader_execution_id",
    "attempt_number",
    "request_sha256",
    "provider",
    "model",
    "model_config_id",
    "prompt_version",
    "started_at",
    "finished_at",
    "duration_ms",
    "result",
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
    "reserved_cost_usd",
    "estimated_cost_usd",
    "billed_cost_usd",
    "price_card_id",
    "usage_complete",
    "validation_status",
    "schema_valid",
    "citations_valid",
    "validation_errors",
    "retry_reason",
    "persistence_state",
}
RESERVATION_FIELDS = {
    "id",
    "budget_id",
    "grader_execution_id",
    "attempt_number",
    "price_card_id",
    "reserved_cost_usd",
    "reserved_tokens",
    "actual_cost_usd",
    "actual_tokens",
    "reservation_state",
    "reserved_at",
    "reconciled_at",
}
OPINION_FIELDS = {
    "opinion_id",
    "execution_id",
    "grader_id",
    "grader_version",
    "execution_state",
    "owned_decision_question",
    "stance",
    "confidence",
    "summary",
    "material_claims",
    "assumptions",
    "contradicting_evidence",
    "evidence_gaps",
    "invalidation_signals",
    "proposition",
    "abstention",
    "created_at",
}


class SupabasePersistentExecutionReadModel:
    """Rebuilds terminal domain state from one owner-scoped runtime snapshot."""

    def __init__(
        self,
        *,
        store: RawGraderExecutionRuntimeStore,
        bundle: EvidenceBundle,
        request: GraderExecutionRequest,
    ) -> None:
        self._store = store
        self._bundle = bundle
        self._request = request

    def reconstruct_terminal(
        self,
        start: ExecutionStart,
        snapshot: RuntimeExecutionSnapshot,
    ) -> GraderExecution:
        raw = self._store.load(start.operator_id, start.execution_key)
        if raw is None:
            raise PersistentExecutionReadError("persistent execution is unavailable")
        self._validate_identity(start, snapshot, raw)
        attempts_payload = raw.get("attempts")
        if not isinstance(attempts_payload, list):
            raise PersistentExecutionReadError("persistent attempts are malformed")
        attempts = tuple(
            self._attempt(item, start, number)
            for number, item in enumerate(attempts_payload, start=1)
        )
        opinion_payload = raw.get("validated_opinion")
        opinion = (
            None if opinion_payload is None else self._opinion(opinion_payload, start)
        )
        state, blocking_reasons = self._terminal_state(attempts, opinion)
        finished_at = attempts[-1].finished_at
        terminal = _terminal_execution(
            start.operator_id,
            self._bundle,
            self._request,
            start.execution_key,
            state,
            attempts,
            opinion,
            blocking_reasons,
            finished_at,
        )
        canonical = terminal.as_dict()
        stored_canonical = raw.get("canonical_execution")
        if raw.get("persistence_state") == "complete":
            if canonical != stored_canonical:
                raise PersistentExecutionReadError(
                    "complete canonical execution does not match persisted state"
                )
        elif canonical.get("opinion") != opinion_payload:
            raise PersistentExecutionReadError(
                "persisted opinion does not match reconstructed state"
            )
        return terminal

    def _validate_identity(
        self,
        start: ExecutionStart,
        snapshot: RuntimeExecutionSnapshot,
        raw: Mapping[str, object],
    ) -> None:
        start_payload = start.storage_payload()
        if (
            start.operator_id != self._bundle.operator_id
            or start_payload["research_run_id"] != self._bundle.research_run_id
            or start_payload["security_id"] != self._bundle.security_id
            or start_payload["evidence_bundle_id"] != self._bundle.id
            or start_payload["evidence_bundle_hash"] != self._bundle.content_hash
            or start_payload["question_type_id"] != self._request.question_type_id
            or start_payload["question_type_version"]
            != self._request.question_type_version
            or start_payload["workflow_config_version"]
            != self._request.workflow_config_version
            or start_payload["grader_id"] != self._request.grader.grader_id
            or start_payload["grader_version"] != self._request.grader.grader_version
            or start_payload["prompt_version"] != self._request.prompt.prompt_version
            or start_payload["model_config_id"] != self._request.model.config_id
            or raw.get("operator_id") != start.operator_id
            or raw.get("grader_execution_id") != start.execution_id
            or raw.get("execution_key") != start.execution_key
            or raw.get("evidence_bundle_hash") != self._bundle.content_hash
            or raw.get("persistence_state") != snapshot.persistence_state
            or snapshot.operator_id != start.operator_id
            or snapshot.execution_id != start.execution_id
            or snapshot.execution_key != start.execution_key
        ):
            raise PersistentExecutionReadError("persistent execution identity mismatch")
        canonical = raw.get("canonical_execution")
        if not isinstance(canonical, Mapping):
            raise PersistentExecutionReadError(
                "persistent canonical execution is malformed"
            )
        for key, expected in (
            ("id", start.execution_id),
            ("operator_id", start.operator_id),
            ("research_run_id", self._bundle.research_run_id),
            ("evidence_bundle_id", self._bundle.id),
            ("evidence_bundle_hash", self._bundle.content_hash),
            ("execution_key", start.execution_key),
            ("question_type_id", self._request.question_type_id),
            ("question_type_version", self._request.question_type_version),
            ("workflow_config_version", self._request.workflow_config_version),
            ("grader_id", self._request.grader.grader_id),
            ("grader_version", self._request.grader.grader_version),
            ("prompt_version", self._request.prompt.prompt_version),
            ("model_config_id", self._request.model.config_id),
        ):
            if canonical.get(key) != expected:
                raise PersistentExecutionReadError(
                    "persistent canonical execution identity mismatch"
                )

    def _attempt(
        self,
        payload: object,
        start: ExecutionStart,
        expected_number: int,
    ) -> GraderAttempt:
        if not isinstance(payload, Mapping) or set(payload) != {
            "attempt",
            "reservation",
            "request_payload",
            "response_payload",
        }:
            raise PersistentExecutionReadError("persistent attempt is malformed")
        attempt = payload["attempt"]
        reservation = payload["reservation"]
        request_payload = payload["request_payload"]
        response_payload = payload["response_payload"]
        if (
            not isinstance(attempt, Mapping)
            or set(attempt) != ATTEMPT_FIELDS
            or not isinstance(reservation, Mapping)
            or set(reservation) != RESERVATION_FIELDS
            or not isinstance(request_payload, Mapping)
            or (
                response_payload is not None
                and not isinstance(response_payload, Mapping)
            )
        ):
            raise PersistentExecutionReadError("persistent attempt is malformed")
        result = attempt["result"]
        if (
            attempt["persistence_state"] != "complete"
            or attempt["grader_execution_id"] != start.execution_id
            or attempt["attempt_number"] != expected_number
            or reservation["grader_execution_id"] != start.execution_id
            or reservation["attempt_number"] != expected_number
            or reservation["price_card_id"] != attempt["price_card_id"]
            or reservation["reservation_state"]
            != ("released" if result == "transport_error" else "reconciled")
            or (result == "transport_error") != (response_payload is None)
        ):
            raise PersistentExecutionReadError("persistent attempt state is invalid")
        _uuid(attempt["id"])
        _uuid(attempt["raw_payload_id"])
        _uuid(reservation["id"])
        started_at = _timestamp(attempt["started_at"])
        finished_at = _timestamp(attempt["finished_at"])
        duration_ms = _integer(attempt["duration_ms"])
        if duration_ms != max(
            0,
            int((finished_at - started_at).total_seconds() * 1000),
        ):
            raise PersistentExecutionReadError("persistent attempt duration is invalid")
        usage = ProviderUsage(
            input_tokens=_integer(attempt["input_tokens"]),
            cached_input_tokens=_integer(attempt["cached_input_tokens"]),
            output_tokens=_integer(attempt["output_tokens"]),
            reasoning_tokens=_integer(attempt["reasoning_tokens"]),
            total_tokens=_integer(attempt["total_tokens"]),
            tool_call_count=_integer(attempt["tool_call_count"]),
            usage_complete=_boolean(attempt["usage_complete"]),
            cache_write_tokens=_integer(attempt["cache_write_tokens"]),
        )
        if (
            usage.total_tokens != usage.input_tokens + usage.output_tokens
            or usage.cached_input_tokens + usage.cache_write_tokens > usage.input_tokens
            or usage.reasoning_tokens > usage.output_tokens
            or attempt["uncached_input_tokens"]
            != usage.input_tokens - usage.cached_input_tokens - usage.cache_write_tokens
        ):
            raise PersistentExecutionReadError("persistent attempt usage is invalid")
        estimated_cost = _decimal(attempt["estimated_cost_usd"])
        actual_cost = _decimal(reservation["actual_cost_usd"])
        billed = (
            None
            if attempt["billed_cost_usd"] is None
            else _decimal(attempt["billed_cost_usd"])
        )
        if (
            actual_cost != (billed if billed is not None else estimated_cost)
            or reservation["actual_tokens"] != usage.total_tokens
            or reservation["price_card_id"] != self._request.price_card.price_card_id
            or attempt["provider"] != self._request.model.provider
            or attempt["model"] != self._request.model.model
            or attempt["model_config_id"] != self._request.model.config_id
            or attempt["prompt_version"] != self._request.prompt.prompt_version
        ):
            raise PersistentExecutionReadError(
                "persistent attempt settlement is invalid"
            )
        raw_hash = canonical_payload_sha256(
            {"request": request_payload, "response": response_payload}
        )
        if attempt["raw_payload_sha256"] != raw_hash:
            raise PersistentExecutionReadError(
                "persistent attempt payload hash is invalid"
            )
        errors = attempt["validation_errors"]
        if not isinstance(errors, list) or any(
            not isinstance(item, str) or not item for item in errors
        ):
            raise PersistentExecutionReadError(
                "persistent attempt validation is invalid"
            )
        if result == "transport_error":
            validation_state = "transport_error"
        elif result == "validation_error":
            validation_state = "rejected"
        elif result in {"accepted", "abstained"}:
            validation_state = "accepted"
        else:
            raise PersistentExecutionReadError("persistent attempt result is invalid")
        return GraderAttempt(
            attempt_id=str(attempt["id"]),
            attempt_number=expected_number,
            request_hash=str(attempt["request_sha256"]),
            provider_request_id=(
                None
                if attempt["provider_request_id"] is None
                else str(attempt["provider_request_id"])
            ),
            raw_payload_id=str(attempt["raw_payload_id"]),
            raw_payload_sha256=str(attempt["raw_payload_sha256"]),
            provider=str(attempt["provider"]),
            requested_model=str(attempt["model"]),
            resolved_model=str(attempt["model"]),
            system_fingerprint=None,
            validation_state=validation_state,
            validation_errors=tuple(errors),
            retry_reason=(
                None
                if attempt["retry_reason"] is None
                else str(attempt["retry_reason"])
            ),
            usage=usage,
            estimated_cost_usd=format(estimated_cost, "f"),
            price_card_id=str(attempt["price_card_id"]),
            started_at=started_at,
            finished_at=finished_at,
        )

    def _opinion(
        self,
        payload: object,
        start: ExecutionStart,
    ) -> GraderOpinion:
        if not isinstance(payload, Mapping):
            raise PersistentExecutionReadError("persistent opinion is malformed")
        domain_key = f"{self._request.grader.grader_id}_payload"
        if set(payload) != OPINION_FIELDS | {domain_key}:
            raise PersistentExecutionReadError("persistent opinion is malformed")
        proposition = payload["proposition"]
        if (
            payload["execution_id"] != start.execution_id
            or payload["grader_id"] != self._request.grader.grader_id
            or payload["grader_version"] != self._request.grader.grader_version
            or payload["owned_decision_question"]
            != self._request.grader.owned_decision_question
            or not isinstance(proposition, Mapping)
            or proposition.get("proposition_id") != self._request.proposition_id
            or proposition.get("proposition_version")
            != self._request.proposition_version
            or proposition.get("rendered_proposition_text")
            != self._request.rendered_proposition
        ):
            raise PersistentExecutionReadError("persistent opinion identity mismatch")
        state = payload["execution_state"]
        stance = payload["stance"]
        if state not in {"accepted", "abstained"} or (
            state == "accepted"
            and stance not in {"supports", "mixed", "challenges"}
            or state == "abstained"
            and stance is not None
        ):
            raise PersistentExecutionReadError("persistent opinion state is invalid")
        claims = _list_of_mappings(payload["material_claims"], "material claims")
        contradictions = _list_of_mappings(
            payload["contradicting_evidence"],
            "contradicting evidence",
        )
        gaps = _list_of_mappings(payload["evidence_gaps"], "evidence gaps")
        abstention_payload = payload["abstention"]
        abstention = None
        if abstention_payload is not None:
            if not isinstance(abstention_payload, Mapping):
                raise PersistentExecutionReadError("persistent abstention is malformed")
            abstention = AbstentionResult(
                reason_code=_text(abstention_payload.get("reason_code")),
                reason=_text(abstention_payload.get("reason")),
                missing_or_inadequate_evidence=_text_tuple(
                    abstention_payload.get("missing_or_inadequate_evidence")
                ),
                evidence_required=_text_tuple(
                    abstention_payload.get("evidence_required")
                ),
                confidence=_text(abstention_payload.get("confidence")),
            )
        if (state == "abstained") != (abstention is not None):
            raise PersistentExecutionReadError("persistent abstention state is invalid")
        domain_payload = payload[domain_key]
        if not isinstance(domain_payload, Mapping):
            raise PersistentExecutionReadError("persistent domain payload is malformed")
        return GraderOpinion(
            opinion_id=_uuid(payload["opinion_id"]),
            execution_state=str(state),
            grader_id=str(payload["grader_id"]),
            grader_version=str(payload["grader_version"]),
            owned_decision_question=str(payload["owned_decision_question"]),
            proposition_id=str(proposition["proposition_id"]),
            proposition_version=str(proposition["proposition_version"]),
            rendered_proposition_text=str(proposition["rendered_proposition_text"]),
            grader_stance=None if stance is None else str(stance),
            stance_rationale=(
                ""
                if proposition.get("stance_rationale") is None
                else str(proposition["stance_rationale"])
            ),
            confidence=_text(payload["confidence"]),
            summary=_text(payload["summary"]),
            material_claims=tuple(
                MaterialClaim(
                    claim_id=_text(item.get("claim_id")),
                    claim=_text(item.get("claim")),
                    materiality=_text(item.get("materiality")),
                    evidence_ids=_text_tuple(item.get("evidence_ids")),
                )
                for item in claims
            ),
            assumptions=_text_tuple(payload["assumptions"]),
            contradicting_evidence=tuple(
                ContradictingEvidence(
                    evidence_id=_text(item.get("evidence_id")),
                    explanation=_text(item.get("explanation")),
                )
                for item in contradictions
            ),
            evidence_gaps=tuple(
                EvidenceGap(
                    gap_id=_text(item.get("gap_id")),
                    description=_text(item.get("description")),
                    required_evidence=_text(item.get("required_evidence")),
                )
                for item in gaps
            ),
            invalidation_signals=_text_tuple(payload["invalidation_signals"]),
            abstention=abstention,
            domain_payload=dict(domain_payload),
        )

    @staticmethod
    def _terminal_state(
        attempts: tuple[GraderAttempt, ...],
        opinion: GraderOpinion | None,
    ) -> tuple[str, tuple[str, ...]]:
        if not attempts:
            raise PersistentExecutionReadError(
                "persistent terminal execution has no attempts"
            )
        latest = attempts[-1]
        if opinion is not None:
            if latest.validation_state != "accepted" or latest.attempt_id == "":
                raise PersistentExecutionReadError(
                    "persistent opinion attempt is invalid"
                )
            return opinion.execution_state, ()
        nonretryable = (
            latest.retry_reason is not None
            and latest.retry_reason.startswith("nonretryable:")
        )
        if len(attempts) != 2 and not nonretryable:
            raise PersistentExecutionReadError(
                "persistent failed execution has retry available"
            )
        if latest.validation_state == "transport_error":
            return (
                "failed",
                (
                    latest.retry_reason.removeprefix("nonretryable:")
                    if nonretryable and latest.retry_reason is not None
                    else "transport_retry_exhausted"
                ),
            )
        if latest.validation_state == "rejected":
            return (
                "failed",
                (
                    "validation_retry_exhausted",
                    *latest.validation_errors,
                ),
            )
        raise PersistentExecutionReadError("persistent terminal state is invalid")


def _uuid(value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (AttributeError, TypeError, ValueError) as error:
        raise PersistentExecutionReadError("persistent UUID is invalid") from error


def _timestamp(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as error:
        raise PersistentExecutionReadError("persistent timestamp is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PersistentExecutionReadError("persistent timestamp is invalid")
    return parsed


def _integer(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise PersistentExecutionReadError("persistent integer is invalid")
    return value


def _boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise PersistentExecutionReadError("persistent boolean is invalid")
    return value


def _decimal(value: object) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise PersistentExecutionReadError("persistent cost is invalid") from error
    if not parsed.is_finite() or parsed < 0:
        raise PersistentExecutionReadError("persistent cost is invalid")
    return parsed


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise PersistentExecutionReadError("persistent text is invalid")
    return value


def _text_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise PersistentExecutionReadError("persistent text list is invalid")
    return tuple(_text(item) for item in value)


def _list_of_mappings(value: object, field: str) -> list[Mapping[str, object]]:
    if not isinstance(value, list) or any(
        not isinstance(item, Mapping) for item in value
    ):
        raise PersistentExecutionReadError(f"persistent {field} is invalid")
    return list(value)


__all__ = [
    "PersistentExecutionReadError",
    "RawGraderExecutionRuntimeStore",
    "SupabasePersistentExecutionReadModel",
]

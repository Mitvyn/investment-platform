from __future__ import annotations

from datetime import datetime
from typing import Mapping

from investment_research_os.grader_executions.runtime import (
    AttemptCompletion,
    AttemptStart,
    ExecutionFinalization,
    ExecutionStart,
    GraderExecutionRuntimeError,
    RuntimeAttemptSnapshot,
    RuntimeExecutionSnapshot,
    canonical_payload_sha256,
)
from investment_research_os.grader_executions.storage import (
    SupabaseGraderExecutionRuntimeStore,
)


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


class GraderExecutionLifecycleStorageError(RuntimeError):
    """Raised when persisted grader lifecycle state cannot be trusted."""


class SupabaseGraderExecutionLifecycle:
    """Converts runtime commands into reload-verified Supabase snapshots."""

    def __init__(self, store: SupabaseGraderExecutionRuntimeStore) -> None:
        self.store = store
        self._execution_keys: dict[tuple[str, str], str] = {}

    def begin_execution(self, start: ExecutionStart) -> RuntimeExecutionSnapshot:
        self.store.begin_execution(start.operator_id, start.storage_payload())
        snapshot = self._load_required(start.operator_id, start.execution_key)
        if snapshot.execution_id != start.execution_id:
            raise GraderExecutionLifecycleStorageError(
                "persisted grader execution does not match start"
            )
        self._remember(snapshot)
        return snapshot

    def begin_attempt(self, start: AttemptStart) -> RuntimeExecutionSnapshot:
        execution_key = self._execution_key(
            start.operator_id,
            start.execution_id,
        )
        attempt, request, reservation = start.storage_arguments()
        receipt = self.store.begin_attempt(
            start.operator_id,
            attempt,
            request,
            reservation,
        )
        if receipt.reused:
            raise GraderExecutionLifecycleStorageError(
                "persisted grader attempt already existed before provider dispatch"
            )
        snapshot = self._load_required(start.operator_id, execution_key)
        if (
            snapshot.execution_id != start.execution_id
            or not snapshot.attempts
            or snapshot.attempts[-1].attempt_id != start.attempt_id
            or snapshot.attempts[-1].attempt_number != start.attempt_number
        ):
            raise GraderExecutionLifecycleStorageError(
                "persisted grader attempt does not match start"
            )
        return snapshot

    def finish_attempt(
        self,
        completion: AttemptCompletion,
    ) -> RuntimeExecutionSnapshot:
        execution_key = self._execution_key(
            completion.operator_id,
            completion.execution_id,
        )
        payload, response, opinion = completion.storage_arguments()
        self.store.finish_attempt(
            completion.operator_id,
            payload,
            response,
            opinion,
        )
        snapshot = self._load_required(completion.operator_id, execution_key)
        if (
            snapshot.execution_id != completion.execution_id
            or not snapshot.attempts
            or snapshot.attempts[-1].attempt_id != completion.attempt_id
            or snapshot.attempts[-1].attempt_number != completion.attempt_number
            or snapshot.attempts[-1].persistence_state != "complete"
            or snapshot.attempts[-1].result != completion.result
            or snapshot.attempts[-1].raw_payload_sha256 != completion.raw_payload_sha256
        ):
            raise GraderExecutionLifecycleStorageError(
                "persisted grader attempt does not match completion"
            )
        return snapshot

    def load(
        self,
        operator_id: str,
        execution_key: str,
    ) -> RuntimeExecutionSnapshot | None:
        raw = self.store.load(operator_id, execution_key)
        if raw is None:
            return None
        snapshot = _runtime_snapshot(raw)
        if (
            snapshot.operator_id != operator_id
            or snapshot.execution_key != execution_key
        ):
            raise GraderExecutionLifecycleStorageError(
                "persisted grader execution does not match lookup"
            )
        self._remember(snapshot)
        return snapshot

    def finalize_execution(
        self,
        finalization: ExecutionFinalization,
    ) -> RuntimeExecutionSnapshot:
        canonical = finalization.canonical_execution
        execution_key = str(canonical["execution_key"])
        evidence_bundle_hash = str(canonical["evidence_bundle_hash"])
        inference_parameter_hash = str(canonical["inference_parameter_hash"])
        self.store.finalize_execution(
            finalization.operator_id,
            finalization.storage_payload(),
            execution_key=execution_key,
            evidence_bundle_hash=evidence_bundle_hash,
            inference_parameter_hash=inference_parameter_hash,
        )
        snapshot = self._load_required(
            finalization.operator_id,
            execution_key,
        )
        if (
            snapshot.execution_id != finalization.execution_id
            or snapshot.persistence_state != "complete"
            or snapshot.canonical_execution is None
            or canonical_payload_sha256(snapshot.canonical_execution)
            != finalization.canonical_execution_sha256
        ):
            raise GraderExecutionLifecycleStorageError(
                "persisted grader execution does not match finalization"
            )
        return snapshot

    def _load_required(
        self,
        operator_id: str,
        execution_key: str,
    ) -> RuntimeExecutionSnapshot:
        snapshot = self.load(operator_id, execution_key)
        if snapshot is None:
            raise GraderExecutionLifecycleStorageError(
                "persisted grader execution is missing after lifecycle write"
            )
        return snapshot

    def _remember(self, snapshot: RuntimeExecutionSnapshot) -> None:
        self._execution_keys[(snapshot.operator_id, snapshot.execution_id)] = (
            snapshot.execution_key
        )

    def _execution_key(self, operator_id: str, execution_id: str) -> str:
        try:
            return self._execution_keys[(operator_id, execution_id)]
        except KeyError as error:
            raise GraderExecutionLifecycleStorageError(
                "grader execution must be loaded before attempt lifecycle write"
            ) from error


def _runtime_snapshot(raw: Mapping[str, object]) -> RuntimeExecutionSnapshot:
    if set(raw) != SNAPSHOT_FIELDS:
        raise GraderExecutionLifecycleStorageError(
            "persisted grader execution snapshot is malformed"
        )
    attempts = raw["attempts"]
    canonical = raw["canonical_execution"]
    persistence_state = raw["persistence_state"]
    if (
        not isinstance(attempts, list)
        or not isinstance(canonical, Mapping)
        or persistence_state not in {"draft", "complete"}
    ):
        raise GraderExecutionLifecycleStorageError(
            "persisted grader execution snapshot is malformed"
        )
    operator_id = str(raw["operator_id"])
    execution_id = str(raw["grader_execution_id"])
    execution_key = str(raw["execution_key"])
    if (
        canonical.get("contract_version") != "grader_execution.v1"
        or canonical.get("id") != execution_id
        or canonical.get("operator_id") != operator_id
        or canonical.get("execution_key") != execution_key
        or canonical.get("evidence_bundle_hash") != raw["evidence_bundle_hash"]
        or canonical.get("inference_parameter_hash") != raw["inference_parameter_hash"]
    ):
        raise GraderExecutionLifecycleStorageError(
            "persisted grader execution snapshot identity is malformed"
        )
    try:
        mapped_attempts = _runtime_attempts(
            attempts,
            execution_id=execution_id,
            validated_opinion=raw["validated_opinion"],
        )
        canonical_result = dict(canonical) if persistence_state == "complete" else None
        if (
            canonical_result is not None
            and raw["validated_opinion"] is not None
            and canonical_result.get("opinion") != raw["validated_opinion"]
        ):
            raise GraderExecutionLifecycleStorageError(
                "persisted grader opinion does not match canonical execution"
            )
        return RuntimeExecutionSnapshot(
            operator_id=operator_id,
            execution_id=execution_id,
            execution_key=execution_key,
            persistence_state=str(persistence_state),
            attempts=mapped_attempts,
            canonical_execution=canonical_result,
        )
    except (GraderExecutionRuntimeError, KeyError, TypeError, ValueError) as error:
        raise GraderExecutionLifecycleStorageError(
            "persisted grader execution snapshot is malformed"
        ) from error


def _runtime_attempts(
    raw_attempts: list[object],
    *,
    execution_id: str,
    validated_opinion: object,
) -> tuple[RuntimeAttemptSnapshot, ...]:
    opinion: Mapping[str, object] | None
    if validated_opinion is None:
        opinion = None
    elif isinstance(validated_opinion, Mapping):
        opinion = validated_opinion
    else:
        raise GraderExecutionLifecycleStorageError(
            "persisted grader opinion is malformed"
        )
    opinion_attempts = 0
    mapped: list[RuntimeAttemptSnapshot] = []
    for item in raw_attempts:
        if (
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
        ):
            raise GraderExecutionLifecycleStorageError(
                "persisted grader attempt is malformed"
            )
        attempt = item["attempt"]
        reservation = item["reservation"]
        for field in (
            "id",
            "grader_execution_id",
            "attempt_number",
            "persistence_state",
            "result",
            "raw_payload_sha256",
            "finished_at",
        ):
            if field not in attempt:
                raise GraderExecutionLifecycleStorageError(
                    "persisted grader attempt is malformed"
                )
        for field in (
            "grader_execution_id",
            "attempt_number",
            "reservation_state",
        ):
            if field not in reservation:
                raise GraderExecutionLifecycleStorageError(
                    "persisted grader reservation is malformed"
                )
        if (
            attempt["grader_execution_id"] != execution_id
            or reservation["grader_execution_id"] != execution_id
            or reservation["attempt_number"] != attempt["attempt_number"]
        ):
            raise GraderExecutionLifecycleStorageError(
                "persisted grader attempt identity is malformed"
            )
        result = attempt["result"]
        opinion_id: str | None = None
        if result in {"accepted", "abstained"}:
            opinion_attempts += 1
            if (
                opinion is None
                or opinion.get("execution_id") != execution_id
                or opinion.get("execution_state") != result
                or not isinstance(opinion.get("opinion_id"), str)
            ):
                raise GraderExecutionLifecycleStorageError(
                    "persisted grader opinion binding is malformed"
                )
            opinion_id = str(opinion["opinion_id"])
        finished_at = attempt["finished_at"]
        mapped.append(
            RuntimeAttemptSnapshot(
                attempt_id=str(attempt["id"]),
                attempt_number=attempt["attempt_number"],  # type: ignore[arg-type]
                persistence_state=str(attempt["persistence_state"]),
                reservation_state=str(reservation["reservation_state"]),
                result=None if result is None else str(result),
                response_persisted=item["response_payload"] is not None,
                opinion_id=opinion_id,
                raw_payload_sha256=str(attempt["raw_payload_sha256"]),
                finished_at=(
                    None
                    if finished_at is None
                    else datetime.fromisoformat(str(finished_at))
                ),
                retry_reason=(
                    None
                    if attempt.get("retry_reason") is None
                    else str(attempt["retry_reason"])
                ),
            )
        )
    if opinion_attempts > 1 or (opinion is not None and opinion_attempts != 1):
        raise GraderExecutionLifecycleStorageError(
            "persisted grader opinion binding is malformed"
        )
    return tuple(mapped)


__all__ = [
    "GraderExecutionLifecycleStorageError",
    "SupabaseGraderExecutionLifecycle",
]

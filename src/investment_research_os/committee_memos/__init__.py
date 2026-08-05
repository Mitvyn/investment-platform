from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
import re
from typing import Callable, Mapping, Protocol, cast

from investment_research_os.evidence_bundles import EvidenceBundleRepository
from investment_research_os.grader_executions import (
    BudgetLedger,
    ExecutionPolicy,
    GraderProvider,
    ModelConfiguration,
    ModelPriceCard,
    PromptContract,
    ProviderRequest,
    ProviderTransportError,
    ProviderUsage,
    _inference_parameter_hash,
)
from investment_research_os.ids import stable_id
from investment_research_os.provider_input_token_preflight import (
    InputTokenCountingProvider,
    PersistentInputTokenPreflightGate,
)
from investment_research_os.production_execution import (
    evaluation_execution_identity_sha256,
)
from investment_research_os.research_committees import (
    ResearchCommitteeRepository,
    ResearchCommitteeResult,
)
from investment_research_os.research_runs import AuthenticatedOperator


class CommitteeMemoError(ValueError):
    """Raised when synthesis violates reconciliation-only memo contract."""


PRODUCTION_PRICE_CARD_MAX_AGE = timedelta(days=30)


@dataclass(frozen=True, slots=True)
class SynthesisRequest:
    committee_id: str
    calculation_ids: tuple[str, ...]
    prompt: PromptContract
    model: ModelConfiguration
    price_card: ModelPriceCard
    policy: ExecutionPolicy


@dataclass(frozen=True, slots=True)
class MemoStatement:
    statement_id: str
    text: str
    provenance_type: str
    evidence_ids: tuple[str, ...]
    opinion_ids: tuple[str, ...]
    calculation_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "statement_id": self.statement_id,
            "text": self.text,
            "provenance_type": self.provenance_type,
            "evidence_ids": list(self.evidence_ids),
            "opinion_ids": list(self.opinion_ids),
            "calculation_ids": list(self.calculation_ids),
        }


@dataclass(frozen=True, slots=True)
class MemoReviewTrigger:
    trigger_type: str
    review_at: str | None
    statement_id: str

    def as_dict(self) -> dict[str, object]:
        return {
            "trigger_type": self.trigger_type,
            "review_at": self.review_at,
            "statement_id": self.statement_id,
        }


@dataclass(frozen=True, slots=True)
class MemoStateDisclosure:
    grader_id: str
    execution_state: str
    opinion_id: str | None
    stance: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "grader_id": self.grader_id,
            "execution_state": self.execution_state,
            "opinion_id": self.opinion_id,
            "stance": self.stance,
        }


@dataclass(frozen=True, slots=True)
class CommitteeMemo:
    memo_id: str
    synthesis_execution_id: str
    committee_id: str
    research_run_id: str
    evidence_bundle_id: str
    evidence_bundle_hash: str
    workflow_config_version: str
    proposition_id: str
    proposition_version: str
    committee_status: str
    requested_disposition: str
    executive_summary_statement_ids: tuple[str, ...]
    statements: tuple[MemoStatement, ...]
    common_ground_statement_ids: tuple[str, ...]
    disagreement_records: tuple[Mapping[str, object], ...]
    disputed_assumption_statement_ids: tuple[str, ...]
    evidence_gap_statement_ids: tuple[str, ...]
    invalidation_statement_ids: tuple[str, ...]
    required_next_evidence_statement_ids: tuple[str, ...]
    review_trigger: MemoReviewTrigger
    state_disclosure: tuple[MemoStateDisclosure, ...]
    prompt_version: str
    model_config_id: str
    provider: str
    model: str
    attempt_count: int
    provider_request_ids: tuple[str | None, ...]
    attempts: tuple[SynthesisAttempt, ...]
    usage: ProviderUsage
    estimated_cost_usd: str
    price_card_version: str
    retry_policy_version: str
    started_at: datetime
    created_at: datetime

    def as_dict(self) -> dict[str, object]:
        return {
            "contract_version": "committee_memo.v1",
            "memo_id": self.memo_id,
            "synthesis_execution_id": self.synthesis_execution_id,
            "committee_id": self.committee_id,
            "research_run_id": self.research_run_id,
            "evidence_bundle_id": self.evidence_bundle_id,
            "evidence_bundle_hash": self.evidence_bundle_hash,
            "workflow_config_version": self.workflow_config_version,
            "proposition_id": self.proposition_id,
            "proposition_version": self.proposition_version,
            "committee_status": self.committee_status,
            "requested_disposition": self.requested_disposition,
            "executive_summary_statement_ids": list(
                self.executive_summary_statement_ids
            ),
            "statements": [item.as_dict() for item in self.statements],
            "common_ground_statement_ids": list(self.common_ground_statement_ids),
            "disagreement_records": [dict(item) for item in self.disagreement_records],
            "disputed_assumption_statement_ids": list(
                self.disputed_assumption_statement_ids
            ),
            "evidence_gap_statement_ids": list(self.evidence_gap_statement_ids),
            "invalidation_statement_ids": list(self.invalidation_statement_ids),
            "required_next_evidence_statement_ids": list(
                self.required_next_evidence_statement_ids
            ),
            "review_trigger": self.review_trigger.as_dict(),
            "state_disclosure": [item.as_dict() for item in self.state_disclosure],
            "execution_metadata": {
                "prompt_version": self.prompt_version,
                "model_config_id": self.model_config_id,
                "provider": self.provider,
                "model": self.model,
                "attempt_count": self.attempt_count,
                "provider_request_ids": list(self.provider_request_ids),
                "attempts": [item.as_dict() for item in self.attempts],
                "input_tokens": self.usage.input_tokens,
                "cached_input_tokens": self.usage.cached_input_tokens,
                "cache_write_tokens": self.usage.cache_write_tokens,
                "uncached_input_tokens": (
                    self.usage.input_tokens
                    - self.usage.cached_input_tokens
                    - self.usage.cache_write_tokens
                ),
                "output_tokens": self.usage.output_tokens,
                "reasoning_tokens": self.usage.reasoning_tokens,
                "total_tokens": self.usage.total_tokens,
                "usage_complete": all(
                    item.usage.usage_complete for item in self.attempts
                ),
                "estimated_cost_usd": self.estimated_cost_usd,
                "price_card_version": self.price_card_version,
                "retry_policy_version": self.retry_policy_version,
                "started_at": self.started_at.isoformat(),
                "completed_at": self.created_at.isoformat(),
            },
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class SynthesisAttempt:
    attempt_id: str
    attempt_number: int
    request_hash: str
    provider_request_id: str | None
    raw_payload_id: str
    raw_payload_sha256: str
    validation_errors: tuple[str, ...]
    usage: ProviderUsage
    estimated_cost_usd: str
    started_at: datetime
    finished_at: datetime

    def as_dict(self) -> dict[str, object]:
        validation_failed = bool(self.validation_errors)
        result = (
            "transport_error"
            if validation_failed and self.provider_request_id is None
            else ("validation_error" if validation_failed else "accepted")
        )
        return {
            "attempt_id": self.attempt_id,
            "attempt_number": self.attempt_number,
            "provider_request_id": self.provider_request_id,
            "result": result,
            "validation_status": ("failed" if validation_failed else "passed"),
            "validation_errors": list(self.validation_errors),
            "retry_reason": (self.validation_errors[0] if validation_failed else None),
            "started_at": self.started_at.isoformat(),
            "completed_at": self.finished_at.isoformat(),
            "duration_ms": int(
                (self.finished_at - self.started_at).total_seconds() * 1000
            ),
            "input_tokens": self.usage.input_tokens,
            "cached_input_tokens": self.usage.cached_input_tokens,
            "cache_write_tokens": self.usage.cache_write_tokens,
            "uncached_input_tokens": (
                self.usage.input_tokens
                - self.usage.cached_input_tokens
                - self.usage.cache_write_tokens
            ),
            "output_tokens": self.usage.output_tokens,
            "reasoning_tokens": self.usage.reasoning_tokens,
            "total_tokens": self.usage.total_tokens,
            "usage_complete": self.usage.usage_complete,
            "estimated_cost_usd": self.estimated_cost_usd,
        }


@dataclass(frozen=True, slots=True)
class CommitteeMemoExecution:
    execution_id: str
    execution_key: str
    operator_id: str
    committee_id: str
    execution_state: str
    attempts: tuple[SynthesisAttempt, ...]
    memo: CommitteeMemo | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SynthesisAttemptStartReceipt:
    raw_payload_id: str
    raw_payload_sha256: str
    reused: bool


class CommitteeMemoRepository(Protocol):
    def begin_execution(
        self,
        operator_id: str,
        execution: Mapping[str, object],
    ) -> bool: ...

    def begin_attempt(
        self,
        operator_id: str,
        attempt: Mapping[str, object],
        request_payload: Mapping[str, object],
    ) -> SynthesisAttemptStartReceipt: ...

    def finish_attempt(
        self,
        operator_id: str,
        execution_id: str,
        attempt: SynthesisAttempt,
        response_payload: Mapping[str, object] | None,
    ) -> None: ...

    def finalize_execution(
        self,
        execution: CommitteeMemoExecution,
    ) -> CommitteeMemoExecution: ...

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


def _raw_attempt_identity(
    operator_id: str,
    attempt_id: str,
    audit: Mapping[str, object],
) -> tuple[str, str]:
    return (
        stable_id(operator_id, "synthesis-raw", attempt_id),
        hashlib.sha256(_canonical_json(audit).encode()).hexdigest(),
    )


class InMemoryCommitteeMemoRepository:
    def __init__(self) -> None:
        self._executions: dict[tuple[str, str], CommitteeMemoExecution] = {}
        self._committee_keys: dict[tuple[str, str], str] = {}
        self._draft_executions: dict[tuple[str, str], Mapping[str, object]] = {}
        self._draft_attempts: dict[
            tuple[str, str], tuple[Mapping[str, object], SynthesisAttempt | None]
        ] = {}
        self._raw_attempts: dict[tuple[str, str], Mapping[str, object]] = {}

    def begin_execution(
        self,
        operator_id: str,
        execution: Mapping[str, object],
    ) -> bool:
        execution_key = str(execution.get("execution_key"))
        key = (operator_id, execution_key)
        existing = self._draft_executions.get(key)
        if existing is not None:
            replay_identity = {
                field: value
                for field, value in execution.items()
                if field != "started_at"
            }
            existing_identity = {
                field: value
                for field, value in existing.items()
                if field != "started_at"
            }
            if existing_identity != replay_identity:
                raise CommitteeMemoError("conflicting immutable synthesis start")
            return True
        self._draft_executions[key] = dict(execution)
        return False

    def begin_attempt(
        self,
        operator_id: str,
        attempt: Mapping[str, object],
        request_payload: Mapping[str, object],
    ) -> SynthesisAttemptStartReceipt:
        attempt_id = str(attempt.get("id"))
        execution_id = str(attempt.get("synthesis_execution_id"))
        if not any(
            draft.get("id") == execution_id
            for (owner, _), draft in self._draft_executions.items()
            if owner == operator_id
        ):
            raise CommitteeMemoError("synthesis execution must begin before attempt")
        safe_request = _without_reasoning_content(request_payload)
        audit = {"request": safe_request, "response": None}
        raw_payload_id, raw_hash = _raw_attempt_identity(
            operator_id,
            attempt_id,
            audit,
        )
        expected = {
            **dict(attempt),
            "raw_payload_id": raw_payload_id,
            "raw_payload_sha256": raw_hash,
        }
        key = (operator_id, attempt_id)
        existing = self._draft_attempts.get(key)
        if existing is not None:
            existing_start, _ = existing
            replay_fields = {
                "id",
                "synthesis_execution_id",
                "attempt_number",
                "request_sha256",
                "reserved_cost_usd",
            }
            if (
                any(
                    existing_start.get(field) != expected.get(field)
                    for field in replay_fields
                )
                or self._raw_attempts[key].get("request") != safe_request
            ):
                raise CommitteeMemoError("conflicting immutable synthesis attempt")
            raise CommitteeMemoError(
                "persisted synthesis attempt already existed before provider dispatch"
            )
        self._raw_attempts[key] = audit
        self._draft_attempts[key] = (expected, None)
        return SynthesisAttemptStartReceipt(
            raw_payload_id=raw_payload_id,
            raw_payload_sha256=raw_hash,
            reused=False,
        )

    def finish_attempt(
        self,
        operator_id: str,
        execution_id: str,
        attempt: SynthesisAttempt,
        response_payload: Mapping[str, object] | None,
    ) -> None:
        key = (operator_id, attempt.attempt_id)
        existing = self._draft_attempts.get(key)
        if existing is None:
            raise CommitteeMemoError("synthesis attempt start is unavailable")
        start, completion = existing
        if start.get("synthesis_execution_id") != execution_id:
            raise CommitteeMemoError("synthesis attempt execution mismatch")
        if completion is not None:
            if completion != attempt:
                raise CommitteeMemoError("conflicting immutable synthesis completion")
            return
        audit = self._raw_attempts[key]
        safe_response = (
            None
            if response_payload is None
            else _without_reasoning_content(response_payload)
        )
        completed_audit = {
            "request": audit["request"],
            "response": safe_response,
        }
        raw_payload_id, raw_hash = _raw_attempt_identity(
            operator_id,
            attempt.attempt_id,
            completed_audit,
        )
        if (
            attempt.raw_payload_id != raw_payload_id
            or attempt.raw_payload_sha256 != raw_hash
        ):
            raise CommitteeMemoError("synthesis attempt payload identity mismatch")
        self._raw_attempts[key] = completed_audit
        self._draft_attempts[key] = (start, attempt)

    def finalize_execution(
        self,
        execution: CommitteeMemoExecution,
    ) -> CommitteeMemoExecution:
        draft_key = (execution.operator_id, execution.execution_key)
        draft = self._draft_executions.get(draft_key)
        if draft is None or draft.get("id") != execution.execution_id:
            raise CommitteeMemoError("synthesis execution start is unavailable")
        persisted_attempts = tuple(
            completion
            for (owner, _), (start, completion) in self._draft_attempts.items()
            if owner == execution.operator_id
            and start.get("synthesis_execution_id") == execution.execution_id
        )
        if (
            any(item is None for item in persisted_attempts)
            or persisted_attempts != execution.attempts
        ):
            raise CommitteeMemoError(
                "synthesis execution attempts do not match lifecycle"
            )
        return self._save_finalized(execution)

    # Compatibility helpers remain audit-only; the workflow never uses them.
    def begin_raw_attempt(
        self,
        operator_id: str,
        attempt_id: str,
        request_payload: Mapping[str, object],
    ) -> tuple[str, str]:
        safe_request = _without_reasoning_content(request_payload)
        key = (operator_id, attempt_id)
        existing = self._raw_attempts.get(key)
        if existing is not None:
            if existing.get("request") != safe_request:
                raise CommitteeMemoError("conflicting immutable synthesis request")
            return _raw_attempt_identity(operator_id, attempt_id, existing)
        audit = {"request": safe_request, "response": None}
        self._raw_attempts[key] = audit
        return _raw_attempt_identity(operator_id, attempt_id, audit)

    def finish_raw_attempt(
        self,
        operator_id: str,
        attempt_id: str,
        response_payload: Mapping[str, object],
    ) -> tuple[str, str]:
        safe_response = _without_reasoning_content(response_payload)
        key = (operator_id, attempt_id)
        existing = self._raw_attempts.get(key)
        if existing is None:
            raise CommitteeMemoError("synthesis request audit is unavailable")
        current_response = existing.get("response")
        if current_response is not None and current_response != safe_response:
            raise CommitteeMemoError("conflicting immutable synthesis response")
        if current_response is None:
            existing = {
                "request": existing["request"],
                "response": safe_response,
            }
            self._raw_attempts[key] = existing
        return _raw_attempt_identity(operator_id, attempt_id, existing)

    def read_raw_attempt(
        self,
        operator_id: str,
        attempt_id: str,
        *,
        audit_authorized: bool,
    ) -> Mapping[str, object] | None:
        if not audit_authorized:
            raise CommitteeMemoError("raw provider payload audit denied")
        return self._raw_attempts.get((operator_id, attempt_id))

    def _save_finalized(
        self,
        execution: CommitteeMemoExecution,
    ) -> CommitteeMemoExecution:
        key = (execution.operator_id, execution.execution_key)
        existing = self._executions.get(key)
        if existing is not None:
            if existing != execution:
                raise CommitteeMemoError("conflicting immutable synthesis")
            return existing
        self._executions[key] = execution
        self._committee_keys[(execution.operator_id, execution.committee_id)] = (
            execution.execution_key
        )
        return execution

    def get_for_key(
        self,
        operator_id: str,
        execution_key: str,
    ) -> CommitteeMemoExecution | None:
        return self._executions.get((operator_id, execution_key))

    def get_for_committee(
        self,
        operator_id: str,
        committee_id: str,
    ) -> CommitteeMemoExecution | None:
        execution_key = self._committee_keys.get((operator_id, committee_id))
        if execution_key is None:
            return None
        return self.get_for_key(operator_id, execution_key)


class CommitteeMemoWorkflow:
    def __init__(
        self,
        *,
        committee_repository: ResearchCommitteeRepository,
        evidence_bundle_repository: EvidenceBundleRepository,
        memo_repository: CommitteeMemoRepository,
        budget_ledger: BudgetLedger,
        provider: GraderProvider,
        input_token_preflight_gate: PersistentInputTokenPreflightGate | None = None,
        clock: Callable[[], datetime],
    ) -> None:
        self._committee_repository = committee_repository
        self._evidence_bundle_repository = evidence_bundle_repository
        self._memo_repository = memo_repository
        self._budget_ledger = budget_ledger
        self._provider = provider
        self._input_token_preflight_gate = input_token_preflight_gate
        self._clock = clock

    def execute(
        self,
        operator: AuthenticatedOperator,
        request: SynthesisRequest,
    ) -> CommitteeMemoExecution:
        committee = self._committee_repository.get_by_id(
            operator.id,
            request.committee_id,
        )
        if committee is None:
            raise CommitteeMemoError("persisted committee not found")
        bundle = self._evidence_bundle_repository.get(
            operator.id,
            committee.evidence_bundle_id,
        )
        if bundle is None or bundle.content_hash != committee.evidence_bundle_hash:
            raise CommitteeMemoError("committee evidence bundle mismatch")
        execution_key = _execution_key(committee, request)
        existing = self._memo_repository.get_for_key(
            operator.id,
            execution_key,
        )
        if existing is not None:
            return existing
        if (
            request.policy.required_environment == "production"
            and re.fullmatch(
                r"[0-9a-f]{64}",
                request.prompt.content_sha256,
            )
            is None
        ):
            raise CommitteeMemoError("synthesis prompt content hash invalid")
        if request.policy.required_environment == "production" and (
            not request.prompt.evaluation_corpus_id
            or not request.prompt.evaluation_corpus_version
            or re.fullmatch(
                r"[0-9a-f]{64}",
                request.prompt.evaluation_corpus_sha256,
            )
            is None
            or re.fullmatch(
                r"[0-9a-f]{64}",
                request.prompt.evaluation_identity_sha256,
            )
            is None
        ):
            raise CommitteeMemoError("synthesis prompt evaluation identity invalid")
        if (
            request.policy.required_environment == "production"
            and evaluation_execution_identity_sha256(
                execution_role="synthesizer",
                execution_contract_version=("committee-synthesis-contract-v1"),
                prompt_id=request.prompt.prompt_id,
                prompt_version=request.prompt.prompt_version,
                prompt_content_sha256=request.prompt.content_sha256,
                model_config_id=request.model.config_id,
                model_config_version=request.model.config_version,
                inference_parameter_hash=_inference_parameter_hash(request.model),
                corpus_id=request.prompt.evaluation_corpus_id,
                corpus_version=request.prompt.evaluation_corpus_version,
                corpus_content_sha256=(request.prompt.evaluation_corpus_sha256),
            )
            != request.prompt.evaluation_identity_sha256
        ):
            raise CommitteeMemoError("synthesis prompt evaluation identity mismatch")
        if not _price_card_rates_are_valid(request.price_card):
            raise CommitteeMemoError("synthesis price card invalid")
        maximum_cost = _maximum_cost(request.model, request.price_card)
        logical_input = {
            "committee": committee.as_dict(),
            "calculation_ids": list(request.calculation_ids),
            "authority": "reconciliation_only",
            "prompt": {
                "prompt_version": request.prompt.prompt_version,
                "content_sha256": request.prompt.content_sha256,
                "evaluation_corpus_sha256": (request.prompt.evaluation_corpus_sha256),
                "evaluation_corpus_id": (request.prompt.evaluation_corpus_id),
                "evaluation_corpus_version": (request.prompt.evaluation_corpus_version),
                "evaluation_identity_sha256": (
                    request.prompt.evaluation_identity_sha256
                ),
            },
        }
        request_hash = hashlib.sha256(
            _canonical_json(logical_input).encode()
        ).hexdigest()
        execution_id = stable_id(
            operator.id,
            "synthesis-execution",
            execution_key,
        )
        first_started_at = self._clock()
        self._memo_repository.begin_execution(
            operator.id,
            {
                "id": execution_id,
                "committee_result_id": committee.committee_id,
                "research_run_id": committee.research_run_id,
                "security_id": bundle.security_id,
                "evidence_bundle_id": committee.evidence_bundle_id,
                "evidence_bundle_hash": committee.evidence_bundle_hash,
                "workflow_config_version": committee.workflow_config_version,
                "proposition_id": committee.proposition_id,
                "proposition_version": committee.proposition_version,
                "committee_status": committee.status,
                "execution_key": execution_key,
                "prompt_version": request.prompt.prompt_version,
                "model_config_id": request.model.config_id,
                "provider": request.model.provider,
                "model": request.model.model,
                "price_card_version": request.price_card.price_card_id,
                "retry_policy_version": request.policy.retry_policy_version,
                "budget_policy_version": request.policy.budget_policy_version,
                "max_attempts": request.policy.max_attempts,
                "started_at": first_started_at.isoformat(),
            },
        )
        attempts: list[SynthesisAttempt] = []
        validation_errors: tuple[str, ...] = ()
        for attempt_number in range(1, request.policy.max_attempts + 1):
            reservation_id = self._budget_ledger.reserve(maximum_cost)
            started_at = first_started_at if attempt_number == 1 else self._clock()
            if not _price_card_is_valid(request, started_at):
                self._budget_ledger.release(reservation_id)
                raise CommitteeMemoError("synthesis price card invalid")
            provider_request = ProviderRequest(
                execution_identity=execution_key,
                request_hash=request_hash,
                provider=request.model.provider,
                model=request.model.model,
                logical_input=logical_input,
                reasoning_effort=request.model.reasoning_effort,
                thinking_enabled=request.model.thinking_enabled,
                temperature=request.model.temperature,
                input_token_cap=request.model.input_token_cap,
                output_token_cap=request.model.output_token_cap,
                execution_role="synthesizer",
                prompt_id=request.prompt.prompt_id,
                prompt_version=request.prompt.prompt_version,
                prompt_content_sha256=request.prompt.content_sha256,
                input_schema_version=request.prompt.input_schema_version,
                output_schema_version=request.prompt.output_schema_version,
                attempt_number=attempt_number,
                validation_errors=validation_errors,
            )
            attempt_id = stable_id(
                operator.id,
                "synthesis-attempt",
                f"{execution_key}:{attempt_number}",
            )
            audited_request = self._provider.audit_request(provider_request)
            receipt = self._memo_repository.begin_attempt(
                operator.id,
                {
                    "id": attempt_id,
                    "synthesis_execution_id": execution_id,
                    "attempt_number": attempt_number,
                    "request_sha256": request_hash,
                    "reservation_id": reservation_id,
                    "reserved_cost_usd": format(maximum_cost, "f"),
                    "started_at": started_at.isoformat(),
                },
                audited_request,
            )
            expected_raw_id, expected_raw_hash = _raw_attempt_identity(
                operator.id,
                attempt_id,
                {
                    "request": _without_reasoning_content(audited_request),
                    "response": None,
                },
            )
            if (
                receipt.reused
                or receipt.raw_payload_id != expected_raw_id
                or receipt.raw_payload_sha256 != expected_raw_hash
            ):
                self._budget_ledger.release(reservation_id)
                raise CommitteeMemoError(
                    "persisted synthesis attempt already existed before provider dispatch"
                )
            try:
                if self._input_token_preflight_gate is not None:
                    self._input_token_preflight_gate.authorize(
                        operator_id=operator.id,
                        research_run_id=committee.research_run_id,
                        attempt_kind="synthesis",
                        attempt_id=attempt_id,
                        request=provider_request,
                        provider=cast(
                            InputTokenCountingProvider,
                            self._provider,
                        ),
                    )
                response = self._provider.execute(provider_request)
            except ProviderTransportError as error:
                self._budget_ledger.release(reservation_id)
                finished_at = self._clock()
                attempt = SynthesisAttempt(
                    attempt_id=attempt_id,
                    attempt_number=attempt_number,
                    request_hash=request_hash,
                    provider_request_id=None,
                    raw_payload_id=receipt.raw_payload_id,
                    raw_payload_sha256=receipt.raw_payload_sha256,
                    validation_errors=(error.code,),
                    usage=ProviderUsage(0, 0, 0, 0, 0),
                    estimated_cost_usd="0",
                    started_at=started_at,
                    finished_at=finished_at,
                )
                self._memo_repository.finish_attempt(
                    operator.id,
                    execution_id,
                    attempt,
                    None,
                )
                attempts.append(attempt)
                validation_errors = (error.code,)
                if not error.retryable:
                    break
                continue
            response_payload = response.raw_provider_response or response.raw_output
            raw_payload_id, raw_hash = _raw_attempt_identity(
                operator.id,
                attempt_id,
                {
                    "request": _without_reasoning_content(audited_request),
                    "response": _without_reasoning_content(response_payload),
                },
            )
            usage_error = (
                "provider_model_mismatch"
                if response.resolved_model != request.model.model
                else _provider_usage_error(response.usage)
            )
            if usage_error is not None:
                self._budget_ledger.release(reservation_id)
                finished_at = self._clock()
                attempt = SynthesisAttempt(
                    attempt_id=attempt_id,
                    attempt_number=attempt_number,
                    request_hash=request_hash,
                    provider_request_id=response.provider_request_id,
                    raw_payload_id=raw_payload_id,
                    raw_payload_sha256=raw_hash,
                    validation_errors=(usage_error,),
                    usage=response.usage,
                    estimated_cost_usd="0",
                    started_at=started_at,
                    finished_at=finished_at,
                )
                self._memo_repository.finish_attempt(
                    operator.id,
                    execution_id,
                    attempt,
                    response_payload,
                )
                attempts.append(attempt)
                validation_errors = (usage_error,)
                continue
            actual_cost = _actual_cost(response.usage, request.price_card)
            self._budget_ledger.reconcile(reservation_id, actual_cost)
            finished_at = self._clock()
            attempt = SynthesisAttempt(
                attempt_id=attempt_id,
                attempt_number=attempt_number,
                request_hash=request_hash,
                provider_request_id=response.provider_request_id,
                raw_payload_id=raw_payload_id,
                raw_payload_sha256=raw_hash,
                validation_errors=(),
                usage=response.usage,
                estimated_cost_usd=format(actual_cost, "f"),
                started_at=started_at,
                finished_at=finished_at,
            )
            try:
                memo = _validate_memo(
                    operator.id,
                    execution_key,
                    committee,
                    bundle,
                    request,
                    response.raw_output,
                    (*attempts, attempt),
                    first_started_at,
                    finished_at,
                )
            except CommitteeMemoError as error:
                error_code = _memo_validation_code(error)
                attempt = SynthesisAttempt(
                    attempt_id=attempt.attempt_id,
                    attempt_number=attempt.attempt_number,
                    request_hash=attempt.request_hash,
                    provider_request_id=attempt.provider_request_id,
                    raw_payload_id=attempt.raw_payload_id,
                    raw_payload_sha256=attempt.raw_payload_sha256,
                    validation_errors=(error_code,),
                    usage=attempt.usage,
                    estimated_cost_usd=attempt.estimated_cost_usd,
                    started_at=attempt.started_at,
                    finished_at=attempt.finished_at,
                )
                self._memo_repository.finish_attempt(
                    operator.id,
                    execution_id,
                    attempt,
                    response_payload,
                )
                attempts.append(attempt)
                validation_errors = (error_code,)
                continue
            self._memo_repository.finish_attempt(
                operator.id,
                execution_id,
                attempt,
                response_payload,
            )
            attempts.append(attempt)
            execution = CommitteeMemoExecution(
                execution_id=execution_id,
                execution_key=execution_key,
                operator_id=operator.id,
                committee_id=committee.committee_id,
                execution_state="accepted",
                attempts=tuple(attempts),
                memo=memo,
                created_at=finished_at,
            )
            return self._memo_repository.finalize_execution(execution)

        execution = CommitteeMemoExecution(
            execution_id=execution_id,
            execution_key=execution_key,
            operator_id=operator.id,
            committee_id=committee.committee_id,
            execution_state="failed",
            attempts=tuple(attempts),
            memo=None,
            created_at=attempts[-1].finished_at,
        )
        return self._memo_repository.finalize_execution(execution)


def _validate_memo(
    operator_id: str,
    execution_key: str,
    committee: ResearchCommitteeResult,
    bundle,
    request: SynthesisRequest,
    output: Mapping[str, object],
    attempts: tuple[SynthesisAttempt, ...],
    started_at: datetime,
    finished_at: datetime,
) -> CommitteeMemo:
    expected_keys = {
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
    }
    if set(output) != expected_keys:
        raise CommitteeMemoError("invalid memo output fields")
    disposition = output.get("requested_disposition")
    if disposition not in {
        "reject",
        "monitor",
        "deep_research",
        "decision_ready",
    }:
        raise CommitteeMemoError("invalid requested disposition")
    raw_statements = output.get("statements")
    if not isinstance(raw_statements, list) or not raw_statements:
        raise CommitteeMemoError("invalid memo statements")
    allowed_evidence = {item.evidence_id for item in bundle.manifest}
    allowed_opinions = {
        item.opinion.opinion_id
        for item in committee.grader_results
        if item.opinion is not None
    }
    allowed_calculations = set(request.calculation_ids)
    statements = tuple(
        _validate_statement(
            item,
            allowed_evidence,
            allowed_opinions,
            allowed_calculations,
        )
        for item in raw_statements
    )
    by_id = {item.statement_id: item for item in statements}
    if len(by_id) != len(statements):
        raise CommitteeMemoError("duplicate memo statement")
    category_fields = (
        "executive_summary_statement_ids",
        "common_ground_statement_ids",
        "disputed_assumption_statement_ids",
        "evidence_gap_statement_ids",
        "invalidation_statement_ids",
        "required_next_evidence_statement_ids",
    )
    categories: dict[str, tuple[str, ...]] = {}
    for field in category_fields:
        value = output.get(field)
        if not isinstance(value, list) or any(
            not isinstance(item, str) or item not in by_id for item in value
        ):
            raise CommitteeMemoError("invalid memo statement reference")
        categories[field] = tuple(value)
    raw_disagreements = output.get("disagreement_records")
    if not isinstance(raw_disagreements, list):
        raise CommitteeMemoError("invalid memo disagreements")
    disagreements = _validate_disagreements(
        raw_disagreements,
        by_id,
        allowed_opinions,
    )
    raw_trigger = output.get("review_trigger")
    if not isinstance(raw_trigger, dict) or set(raw_trigger) != {
        "trigger_type",
        "review_at",
        "statement_id",
    }:
        raise CommitteeMemoError("invalid review trigger")
    if raw_trigger.get("trigger_type") not in {"date", "evidence_event"}:
        raise CommitteeMemoError("invalid review trigger")
    if raw_trigger.get("statement_id") not in by_id:
        raise CommitteeMemoError("invalid review trigger")
    disclosures = _validate_state_disclosure(
        committee,
        output.get("state_disclosure"),
    )
    usage = _sum_usage(attempts)
    return CommitteeMemo(
        memo_id=stable_id(operator_id, "committee-memo", execution_key),
        synthesis_execution_id=stable_id(
            operator_id,
            "synthesis-execution",
            execution_key,
        ),
        committee_id=committee.committee_id,
        research_run_id=committee.research_run_id,
        evidence_bundle_id=committee.evidence_bundle_id,
        evidence_bundle_hash=committee.evidence_bundle_hash,
        workflow_config_version=committee.workflow_config_version,
        proposition_id=committee.proposition_id,
        proposition_version=committee.proposition_version,
        committee_status=committee.status,
        requested_disposition=str(disposition),
        executive_summary_statement_ids=categories["executive_summary_statement_ids"],
        statements=statements,
        common_ground_statement_ids=categories["common_ground_statement_ids"],
        disagreement_records=disagreements,
        disputed_assumption_statement_ids=categories[
            "disputed_assumption_statement_ids"
        ],
        evidence_gap_statement_ids=categories["evidence_gap_statement_ids"],
        invalidation_statement_ids=categories["invalidation_statement_ids"],
        required_next_evidence_statement_ids=categories[
            "required_next_evidence_statement_ids"
        ],
        review_trigger=MemoReviewTrigger(
            trigger_type=str(raw_trigger["trigger_type"]),
            review_at=(
                str(raw_trigger["review_at"])
                if raw_trigger["review_at"] is not None
                else None
            ),
            statement_id=str(raw_trigger["statement_id"]),
        ),
        state_disclosure=disclosures,
        prompt_version=request.prompt.prompt_version,
        model_config_id=request.model.config_id,
        provider=request.model.provider,
        model=request.model.model,
        attempt_count=len(attempts),
        provider_request_ids=tuple(item.provider_request_id for item in attempts),
        attempts=attempts,
        usage=usage,
        estimated_cost_usd=format(
            sum(
                (Decimal(item.estimated_cost_usd) for item in attempts),
                Decimal("0"),
            ),
            "f",
        ),
        price_card_version=request.price_card.price_card_id,
        retry_policy_version=request.policy.retry_policy_version,
        started_at=started_at,
        created_at=finished_at,
    )


def _validate_statement(
    value: object,
    allowed_evidence: set[str],
    allowed_opinions: set[str],
    allowed_calculations: set[str],
) -> MemoStatement:
    if not isinstance(value, dict) or set(value) != {
        "statement_id",
        "text",
        "provenance_type",
        "evidence_ids",
        "opinion_ids",
        "calculation_ids",
    }:
        raise CommitteeMemoError("invalid memo statement")
    statement_id = value.get("statement_id")
    text = value.get("text")
    provenance = value.get("provenance_type")
    if not isinstance(statement_id, str) or not statement_id:
        raise CommitteeMemoError("invalid memo statement")
    if not isinstance(text, str) or not text:
        raise CommitteeMemoError("invalid memo statement")
    if re.search(
        r"\b(target price|trade action|position size|share quantity|"
        r"buy recommendation|sell recommendation|universal score|"
        r"weighted score|majority vote|confidence average)\b",
        text,
        flags=re.IGNORECASE,
    ):
        raise CommitteeMemoError("prohibited memo output")
    if provenance not in {
        "fact",
        "grader_interpretation",
        "synthesis_interpretation",
        "assumption",
        "gap",
    }:
        raise CommitteeMemoError("invalid memo provenance")
    references: list[tuple[str, tuple[str, ...], set[str]]] = []
    for field, allowed in (
        ("evidence_ids", allowed_evidence),
        ("opinion_ids", allowed_opinions),
        ("calculation_ids", allowed_calculations),
    ):
        raw = value.get(field)
        if not isinstance(raw, list) or any(
            not isinstance(item, str) or item not in allowed for item in raw
        ):
            raise CommitteeMemoError("invalid memo provenance reference")
        references.append((field, tuple(raw), allowed))
    evidence_ids = references[0][1]
    opinion_ids = references[1][1]
    calculation_ids = references[2][1]
    if provenance == "fact" and not evidence_ids:
        raise CommitteeMemoError("fact missing evidence")
    if provenance == "grader_interpretation" and len(opinion_ids) != 1:
        raise CommitteeMemoError("grader interpretation provenance invalid")
    if provenance == "synthesis_interpretation" and len(opinion_ids) < 2:
        raise CommitteeMemoError("synthesis provenance invalid")
    if provenance in {"assumption", "gap"} and not (
        evidence_ids or opinion_ids or calculation_ids
    ):
        raise CommitteeMemoError("memo statement missing provenance")
    return MemoStatement(
        statement_id=statement_id,
        text=text,
        provenance_type=str(provenance),
        evidence_ids=evidence_ids,
        opinion_ids=opinion_ids,
        calculation_ids=calculation_ids,
    )


def _validate_disagreements(
    values: list[object],
    statements: Mapping[str, MemoStatement],
    allowed_opinions: set[str],
) -> tuple[Mapping[str, object], ...]:
    expected_keys = {
        "disagreement_id",
        "disputed_question_statement_id",
        "position_statement_ids",
        "contributing_opinion_ids",
        "affects_disposition",
        "resolving_evidence_statement_ids",
    }
    records: list[Mapping[str, object]] = []
    ids: set[str] = set()
    for value in values:
        if not isinstance(value, dict) or set(value) != expected_keys:
            raise CommitteeMemoError("invalid memo disagreement")
        disagreement_id = value.get("disagreement_id")
        if (
            not isinstance(disagreement_id, str)
            or not disagreement_id
            or disagreement_id in ids
        ):
            raise CommitteeMemoError("invalid memo disagreement")
        ids.add(disagreement_id)
        question_id = value.get("disputed_question_statement_id")
        question = statements.get(str(question_id))
        if question is None or question.provenance_type != "synthesis_interpretation":
            raise CommitteeMemoError("invalid disagreement question")
        position_ids = value.get("position_statement_ids")
        if not isinstance(position_ids, list) or len(position_ids) < 2:
            raise CommitteeMemoError("invalid disagreement positions")
        positions = [statements.get(str(item)) for item in position_ids]
        if any(
            item is None or item.provenance_type != "grader_interpretation"
            for item in positions
        ):
            raise CommitteeMemoError("invalid disagreement positions")
        opinion_ids = value.get("contributing_opinion_ids")
        if not isinstance(opinion_ids, list) or any(
            not isinstance(item, str) or item not in allowed_opinions
            for item in opinion_ids
        ):
            raise CommitteeMemoError("invalid disagreement opinion reference")
        expected_opinions = {
            opinion_id
            for position in positions
            if position is not None
            for opinion_id in position.opinion_ids
        }
        if set(opinion_ids) != expected_opinions:
            raise CommitteeMemoError("invalid disagreement opinion reference")
        resolving_ids = value.get("resolving_evidence_statement_ids")
        if not isinstance(resolving_ids, list) or not resolving_ids:
            raise CommitteeMemoError("invalid disagreement resolution")
        resolving = [statements.get(str(item)) for item in resolving_ids]
        if any(item is None or item.provenance_type != "gap" for item in resolving):
            raise CommitteeMemoError("invalid disagreement resolution")
        if not isinstance(value.get("affects_disposition"), bool):
            raise CommitteeMemoError("invalid memo disagreement")
        records.append(dict(value))
    return tuple(records)


def _validate_state_disclosure(
    committee: ResearchCommitteeResult,
    value: object,
) -> tuple[MemoStateDisclosure, ...]:
    if not isinstance(value, list) or len(value) != 5:
        raise CommitteeMemoError("invalid committee state disclosure")
    expected = [
        {
            "grader_id": item.grader_id,
            "execution_state": item.execution_state,
            "opinion_id": (
                item.opinion.opinion_id if item.opinion is not None else None
            ),
            "stance": item.stance,
        }
        for item in committee.grader_results
    ]
    if value != expected:
        raise CommitteeMemoError("committee state disclosure mismatch")
    return tuple(MemoStateDisclosure(**item) for item in expected)


def _execution_key(
    committee: ResearchCommitteeResult,
    request: SynthesisRequest,
) -> str:
    payload = {
        "committee_id": committee.committee_id,
        "bundle_hash": committee.evidence_bundle_hash,
        "workflow_config_version": committee.workflow_config_version,
        "prompt_version": request.prompt.prompt_version,
        "prompt_content_sha256": request.prompt.content_sha256,
        "evaluation_corpus_sha256": (request.prompt.evaluation_corpus_sha256),
        "evaluation_corpus_id": request.prompt.evaluation_corpus_id,
        "evaluation_corpus_version": (request.prompt.evaluation_corpus_version),
        "evaluation_identity_sha256": (request.prompt.evaluation_identity_sha256),
        "model_config_version": request.model.config_version,
        "provider": request.model.provider,
        "model": request.model.model,
        "calculation_ids": list(request.calculation_ids),
    }
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()


def _memo_validation_code(error: CommitteeMemoError) -> str:
    return {
        "invalid memo provenance reference": ("invalid_memo_provenance_reference"),
        "fact missing evidence": "fact_missing_evidence",
        "committee state disclosure mismatch": "state_disclosure_mismatch",
        "invalid committee state disclosure": "state_disclosure_mismatch",
        "prohibited memo output": "prohibited_memo_output",
        "invalid disagreement opinion reference": ("invalid_memo_opinion_reference"),
    }.get(str(error), "memo_contract_validation_failed")


def _maximum_cost(
    model: ModelConfiguration,
    price_card: ModelPriceCard,
) -> Decimal:
    maximum_input_rate = max(
        price_card.input_per_million,
        price_card.cached_input_per_million,
        price_card.cache_write_per_million,
    )
    return (
        Decimal(model.input_token_cap) * maximum_input_rate
        + Decimal(model.output_token_cap) * price_card.output_per_million
    ) / Decimal(1_000_000)


def _price_card_is_valid(
    request: SynthesisRequest,
    checked_at: datetime,
) -> bool:
    card = request.price_card
    if (
        card.provider != request.model.provider
        or card.model != request.model.model
        or card.currency != "USD"
        or card.effective_from > checked_at
        or card.verified_at > checked_at
        or (card.effective_to is not None and card.effective_to <= checked_at)
    ):
        return False
    if request.policy.required_environment != "production":
        return True
    return (
        card.effective_to is not None
        and checked_at < card.verified_at + PRODUCTION_PRICE_CARD_MAX_AGE
    )


def _price_card_rates_are_valid(price_card: ModelPriceCard) -> bool:
    return all(
        rate >= 0
        for rate in (
            price_card.input_per_million,
            price_card.cached_input_per_million,
            price_card.cache_write_per_million,
            price_card.output_per_million,
        )
    )


def _actual_cost(
    usage: ProviderUsage,
    price_card: ModelPriceCard,
) -> Decimal:
    uncached = usage.input_tokens - usage.cached_input_tokens - usage.cache_write_tokens
    return (
        Decimal(uncached) * price_card.input_per_million
        + Decimal(usage.cached_input_tokens) * price_card.cached_input_per_million
        + Decimal(usage.cache_write_tokens) * price_card.cache_write_per_million
        + Decimal(usage.output_tokens) * price_card.output_per_million
    ) / Decimal(1_000_000)


def _provider_usage_error(usage: ProviderUsage) -> str | None:
    counts = (
        usage.input_tokens,
        usage.cached_input_tokens,
        usage.cache_write_tokens,
        usage.output_tokens,
        usage.reasoning_tokens,
        usage.total_tokens,
        usage.tool_call_count,
    )
    if any(value < 0 for value in counts):
        return "invalid_provider_usage"
    if usage.cached_input_tokens + usage.cache_write_tokens > usage.input_tokens:
        return "invalid_provider_usage"
    if usage.reasoning_tokens > usage.output_tokens:
        return "invalid_provider_usage"
    if usage.total_tokens != usage.input_tokens + usage.output_tokens:
        return "invalid_provider_usage"
    if not usage.usage_complete:
        return "invalid_provider_usage"
    return None


def _sum_usage(attempts: tuple[SynthesisAttempt, ...]) -> ProviderUsage:
    return ProviderUsage(
        input_tokens=sum(item.usage.input_tokens for item in attempts),
        cached_input_tokens=sum(item.usage.cached_input_tokens for item in attempts),
        cache_write_tokens=sum(item.usage.cache_write_tokens for item in attempts),
        output_tokens=sum(item.usage.output_tokens for item in attempts),
        reasoning_tokens=sum(item.usage.reasoning_tokens for item in attempts),
        total_tokens=sum(item.usage.total_tokens for item in attempts),
        tool_call_count=sum(item.usage.tool_call_count for item in attempts),
        usage_complete=all(item.usage.usage_complete for item in attempts),
    )


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


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


__all__ = [
    "CommitteeMemo",
    "CommitteeMemoError",
    "CommitteeMemoExecution",
    "CommitteeMemoRepository",
    "CommitteeMemoWorkflow",
    "InMemoryCommitteeMemoRepository",
    "MemoStatement",
    "SynthesisAttemptStartReceipt",
    "SynthesisRequest",
]

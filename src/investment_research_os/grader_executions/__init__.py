from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
import re
from typing import Callable, Mapping, Protocol, runtime_checkable

from investment_research_os.evidence_bundles import (
    EvidenceBundle,
    EvidenceBundleError,
    EvidenceBundleRepository,
    validate_evidence_source_url,
)
from investment_research_os.ids import stable_id
from investment_research_os.production_execution import (
    evaluation_execution_identity_sha256,
)
from investment_research_os.research_runs import AuthenticatedOperator
from investment_research_os.valuation_snapshots import ValuationSnapshotRepository


class GraderExecutionError(ValueError):
    """Raised when an isolated grader execution violates its contract."""


class ProviderTransportError(RuntimeError):
    """Raised by provider boundary with explicit retry and category policy."""

    def __init__(
        self,
        code: str,
        *,
        retryable: bool = True,
        category: str = "transport",
    ) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.category = category


PRODUCTION_PRICE_CARD_MAX_AGE = timedelta(days=30)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class GraderContract:
    grader_id: str
    grader_version: str
    grader_contract_version: str
    owned_decision_question: str
    eligibility_rule_version: str
    rubric_version: str
    output_schema_version: str
    abstention_rule_version: str
    required: bool
    eligible: bool


@dataclass(frozen=True, slots=True)
class PromptContract:
    prompt_id: str
    prompt_version: str
    input_schema_version: str
    output_schema_version: str
    active: bool
    evaluation_passed: bool
    content_sha256: str = ""
    evaluation_corpus_id: str = ""
    evaluation_corpus_version: str = ""
    evaluation_corpus_sha256: str = ""
    evaluation_identity_sha256: str = ""


@dataclass(frozen=True, slots=True)
class ModelConfiguration:
    config_id: str
    config_version: str
    provider: str
    model: str
    reasoning_effort: str
    thinking_enabled: bool
    temperature: str
    input_token_cap: int
    output_token_cap: int
    active: bool
    evaluation_passed: bool
    retention_approved: bool
    source_processing_approved: bool
    environment: str


@dataclass(frozen=True, slots=True)
class ModelPriceCard:
    price_card_id: str
    provider: str
    model: str
    currency: str
    input_per_million: Decimal
    cached_input_per_million: Decimal
    cache_write_per_million: Decimal
    output_per_million: Decimal
    effective_from: datetime
    effective_to: datetime | None
    verified_at: datetime


@dataclass(frozen=True, slots=True)
class ExecutionPolicy:
    policy_version: str
    retry_policy_version: str
    budget_policy_version: str
    max_attempts: int
    required_environment: str


@dataclass(frozen=True, slots=True)
class GraderExecutionRequest:
    evidence_bundle_id: str
    question_type_id: str
    question_type_version: str
    workflow_config_version: str
    proposition_id: str
    proposition_version: str
    rendered_proposition: str
    grader: GraderContract
    prompt: PromptContract
    model: ModelConfiguration
    price_card: ModelPriceCard
    policy: ExecutionPolicy


@dataclass(frozen=True, slots=True)
class ProviderUsage:
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    total_tokens: int
    tool_call_count: int = 0
    usage_complete: bool = True
    cache_write_tokens: int = 0


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    provider_request_id: str
    raw_output: Mapping[str, object]
    usage: ProviderUsage
    resolved_model: str
    system_fingerprint: str | None
    raw_provider_response: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    execution_identity: str
    request_hash: str
    provider: str
    model: str
    logical_input: Mapping[str, object]
    reasoning_effort: str
    thinking_enabled: bool
    temperature: str
    input_token_cap: int
    output_token_cap: int
    execution_role: str
    prompt_id: str
    prompt_version: str
    prompt_content_sha256: str
    input_schema_version: str
    output_schema_version: str
    attempt_number: int
    validation_errors: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "execution_identity": self.execution_identity,
            "request_hash": self.request_hash,
            "provider": self.provider,
            "model": self.model,
            "logical_input": dict(self.logical_input),
            "reasoning_effort": self.reasoning_effort,
            "thinking_enabled": self.thinking_enabled,
            "temperature": self.temperature,
            "input_token_cap": self.input_token_cap,
            "output_token_cap": self.output_token_cap,
            "execution_role": self.execution_role,
            "prompt_id": self.prompt_id,
            "prompt_version": self.prompt_version,
            "prompt_content_sha256": self.prompt_content_sha256,
            "input_schema_version": self.input_schema_version,
            "output_schema_version": self.output_schema_version,
            "attempt_number": self.attempt_number,
            "validation_errors": list(self.validation_errors),
        }


class GraderProvider(Protocol):
    def audit_request(self, request: ProviderRequest) -> Mapping[str, object]: ...

    def execute(self, request: ProviderRequest) -> ProviderResponse: ...


@dataclass(frozen=True, slots=True)
class MaterialClaim:
    claim_id: str
    claim: str
    materiality: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AbstentionResult:
    reason_code: str
    reason: str
    missing_or_inadequate_evidence: tuple[str, ...]
    evidence_required: tuple[str, ...]
    confidence: str

    def as_dict(self) -> dict[str, object]:
        return {
            "reason_code": self.reason_code,
            "reason": self.reason,
            "missing_or_inadequate_evidence": list(self.missing_or_inadequate_evidence),
            "evidence_required": list(self.evidence_required),
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class ContradictingEvidence:
    evidence_id: str
    explanation: str


@dataclass(frozen=True, slots=True)
class EvidenceGap:
    gap_id: str
    description: str
    required_evidence: str


@dataclass(frozen=True, slots=True)
class GraderOpinion:
    opinion_id: str
    execution_state: str
    grader_id: str
    grader_version: str
    owned_decision_question: str
    proposition_id: str
    proposition_version: str
    rendered_proposition_text: str
    grader_stance: str | None
    stance_rationale: str
    confidence: str
    summary: str
    material_claims: tuple[MaterialClaim, ...]
    assumptions: tuple[str, ...]
    contradicting_evidence: tuple[ContradictingEvidence, ...]
    evidence_gaps: tuple[EvidenceGap, ...]
    invalidation_signals: tuple[str, ...]
    abstention: AbstentionResult | None
    domain_payload: Mapping[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "opinion_id": self.opinion_id,
            "execution_state": self.execution_state,
            "grader_id": self.grader_id,
            "grader_version": self.grader_version,
            "owned_decision_question": self.owned_decision_question,
            "proposition_id": self.proposition_id,
            "proposition_version": self.proposition_version,
            "rendered_proposition_text": self.rendered_proposition_text,
            "grader_stance": self.grader_stance,
            "stance_rationale": self.stance_rationale,
            "confidence": self.confidence,
            "summary": self.summary,
            "material_claims": [
                {
                    "claim_id": claim.claim_id,
                    "claim": claim.claim,
                    "materiality": claim.materiality,
                    "evidence_ids": list(claim.evidence_ids),
                }
                for claim in self.material_claims
            ],
            "assumptions": list(self.assumptions),
            "contradicting_evidence": [
                {
                    "evidence_id": item.evidence_id,
                    "explanation": item.explanation,
                }
                for item in self.contradicting_evidence
            ],
            "evidence_gaps": [
                {
                    "gap_id": item.gap_id,
                    "description": item.description,
                    "required_evidence": item.required_evidence,
                }
                for item in self.evidence_gaps
            ],
            "invalidation_signals": list(self.invalidation_signals),
            "abstention": (self.abstention.as_dict() if self.abstention else None),
            "domain_payload": dict(self.domain_payload),
        }


@dataclass(frozen=True, slots=True)
class GraderAttempt:
    attempt_id: str
    attempt_number: int
    request_hash: str
    provider_request_id: str | None
    raw_payload_id: str | None
    raw_payload_sha256: str | None
    provider: str
    requested_model: str
    resolved_model: str
    system_fingerprint: str | None
    validation_state: str
    validation_errors: tuple[str, ...]
    retry_reason: str | None
    usage: ProviderUsage
    estimated_cost_usd: str
    price_card_id: str
    started_at: datetime
    finished_at: datetime

    def as_dict(self) -> dict[str, object]:
        return {
            "attempt_id": self.attempt_id,
            "attempt_number": self.attempt_number,
            "request_hash": self.request_hash,
            "provider_request_id": self.provider_request_id,
            "provider": self.provider,
            "requested_model": self.requested_model,
            "resolved_model": self.resolved_model,
            "system_fingerprint": self.system_fingerprint,
            "validation_state": self.validation_state,
            "validation_errors": list(self.validation_errors),
            "retry_reason": self.retry_reason,
            "usage": {
                "input_tokens": self.usage.input_tokens,
                "cached_input_tokens": self.usage.cached_input_tokens,
                "output_tokens": self.usage.output_tokens,
                "reasoning_tokens": self.usage.reasoning_tokens,
                "total_tokens": self.usage.total_tokens,
            },
            "estimated_cost_usd": self.estimated_cost_usd,
            "price_card_id": self.price_card_id,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class ExecutionFailure:
    category: str
    attempt_count: int
    validation_errors: tuple[str, ...]
    final_reason: str
    retry_policy_version: str

    def as_dict(self) -> dict[str, object]:
        return {
            "category": self.category,
            "attempt_count": self.attempt_count,
            "validation_errors": list(self.validation_errors),
            "final_reason": self.final_reason,
            "retry_policy_version": self.retry_policy_version,
        }


@dataclass(frozen=True, slots=True)
class GraderExecution:
    execution_id: str
    execution_identity: str
    operator_id: str
    research_run_id: str
    evidence_bundle_id: str
    bundle_hash: str
    question_type_id: str
    question_type_version: str
    workflow_config_version: str
    grader_id: str
    grader_version: str
    prompt_version: str
    model_config_version: str
    execution_state: str
    attempts: tuple[GraderAttempt, ...]
    opinion: GraderOpinion | None
    blocking_reasons: tuple[str, ...]
    policy_version: str
    retry_policy_version: str
    created_at: datetime
    failure: ExecutionFailure | None = None
    request: GraderExecutionRequest | None = None

    def as_dict(self) -> dict[str, object]:
        if self.request is None:
            raise GraderExecutionError("execution contract metadata missing")
        request = self.request
        started_at = self.attempts[0].started_at if self.attempts else self.created_at
        serialized_attempts = [
            _attempt_contract(self, attempt) for attempt in self.attempts
        ]
        total_usage = _sum_usage(self.attempts)
        reserved_cost = format(_maximum_cost(request.model, request.price_card), "f")
        estimated_total = sum(
            (Decimal(attempt.estimated_cost_usd) for attempt in self.attempts),
            Decimal("0"),
        )
        all_usage_complete = all(
            attempt.usage.usage_complete for attempt in self.attempts
        )
        billed_total = (
            format(estimated_total, "f")
            if self.attempts and all_usage_complete
            else None
        )
        gate = _gate_contract(self)
        reservation_id = (
            None
            if self.execution_state == "not_executed"
            else stable_id(
                self.operator_id,
                "grader-budget-reservation",
                self.execution_identity,
            )
        )
        budget_status = (
            "not_reserved"
            if self.execution_state == "not_executed"
            else (
                "reconciled"
                if any(attempt.usage.usage_complete for attempt in self.attempts)
                else "released"
            )
        )
        opinion = (
            _opinion_contract(self, self.opinion) if self.opinion is not None else None
        )
        return {
            "contract_version": "grader_execution.v1",
            "id": self.execution_id,
            "operator_id": self.operator_id,
            "research_run_id": self.research_run_id,
            "evidence_bundle_id": self.evidence_bundle_id,
            "evidence_bundle_hash": self.bundle_hash,
            "execution_key": self.execution_identity,
            "question_type_id": self.question_type_id,
            "question_type_version": self.question_type_version,
            "workflow_config_version": self.workflow_config_version,
            "thesis_contract_id": self.question_type_id,
            "grader_id": self.grader_id,
            "grader_version": self.grader_version,
            "grader_contract_version": (request.grader.grader_contract_version),
            "eligibility_rule_version": (request.grader.eligibility_rule_version),
            "rubric_version": request.grader.rubric_version,
            "output_schema_version": request.grader.output_schema_version,
            "abstention_rules_version": (request.grader.abstention_rule_version),
            "prompt_version": self.prompt_version,
            "model_config_id": request.model.config_id,
            "provider": request.model.provider,
            "model": request.model.model,
            "inference_parameter_hash": _inference_parameter_hash(request.model),
            "retry_policy_version": self.retry_policy_version,
            "required": request.grader.required,
            "execution_state": self.execution_state,
            "pre_call_gate": gate,
            "budget": {
                "reservation_id": reservation_id,
                "budget_policy_version": (request.policy.budget_policy_version),
                "currency": "USD",
                "reserved_cost_usd": ("0" if reservation_id is None else reserved_cost),
                "reconciled_cost_usd": (
                    billed_total if budget_status == "reconciled" else None
                ),
                "status": budget_status,
            },
            "attempts": serialized_attempts,
            "total_usage": _usage_contract(total_usage),
            "total_cost": {
                "reserved_cost_usd": ("0" if reservation_id is None else reserved_cost),
                "estimated_cost_usd": format(estimated_total, "f"),
                "billed_cost_usd": billed_total,
                "currency": "USD",
                "price_card_version": request.price_card.price_card_id,
            },
            "not_executed": (
                {
                    "reason_code": self.blocking_reasons[0],
                    "reason": self.blocking_reasons[0].replace("_", " "),
                    "gate_policy_version": self.policy_version,
                    "failed_gate_checks": [
                        check["check_id"]
                        for check in gate["checks"]
                        if not check["passed"]
                    ],
                }
                if self.execution_state == "not_executed"
                else None
            ),
            "failure": (
                _failure_contract(self.failure) if self.failure is not None else None
            ),
            "opinion": opinion,
            "started_at": started_at.isoformat(),
            "finished_at": self.created_at.isoformat(),
        }


def _usage_contract(usage: ProviderUsage) -> dict[str, object]:
    return {
        "input_tokens": usage.input_tokens,
        "cached_input_tokens": usage.cached_input_tokens,
        "cache_write_tokens": usage.cache_write_tokens,
        "uncached_input_tokens": (usage.input_tokens - usage.cached_input_tokens),
        "output_tokens": usage.output_tokens,
        "reasoning_tokens": usage.reasoning_tokens,
        "total_tokens": usage.total_tokens,
        "tool_call_count": usage.tool_call_count,
        "usage_complete": usage.usage_complete,
    }


def _sum_usage(attempts: tuple[GraderAttempt, ...]) -> ProviderUsage:
    return ProviderUsage(
        input_tokens=sum(item.usage.input_tokens for item in attempts),
        cached_input_tokens=sum(item.usage.cached_input_tokens for item in attempts),
        output_tokens=sum(item.usage.output_tokens for item in attempts),
        reasoning_tokens=sum(item.usage.reasoning_tokens for item in attempts),
        total_tokens=sum(item.usage.total_tokens for item in attempts),
        tool_call_count=sum(item.usage.tool_call_count for item in attempts),
        usage_complete=all(item.usage.usage_complete for item in attempts),
        cache_write_tokens=sum(item.usage.cache_write_tokens for item in attempts),
    )


def _attempt_contract(
    execution: GraderExecution,
    attempt: GraderAttempt,
) -> dict[str, object]:
    if execution.request is None:
        raise GraderExecutionError("execution contract metadata missing")
    if attempt.validation_state == "transport_error":
        result = "transport_error"
        validation = {
            "status": "not_run",
            "schema_valid": None,
            "citations_valid": None,
            "errors": [],
        }
    elif attempt.validation_state == "rejected":
        result = "validation_error"
        citation_error = "invalid_opinion_citation" in (attempt.validation_errors)
        validation = {
            "status": "failed",
            "schema_valid": citation_error,
            "citations_valid": False if citation_error else None,
            "errors": list(attempt.validation_errors),
        }
    else:
        result = "abstained" if execution.execution_state == "abstained" else "accepted"
        validation = {
            "status": "passed",
            "schema_valid": True,
            "citations_valid": True,
            "errors": [],
        }
    reserved_cost = format(
        _maximum_cost(
            execution.request.model,
            execution.request.price_card,
        ),
        "f",
    )
    billed_cost = attempt.estimated_cost_usd if attempt.usage.usage_complete else None
    return {
        "attempt_id": attempt.attempt_id,
        "attempt_number": attempt.attempt_number,
        "request_sha256": attempt.request_hash,
        "provider": execution.request.model.provider,
        "model": execution.request.model.model,
        "model_config_id": execution.request.model.config_id,
        "prompt_version": execution.request.prompt.prompt_version,
        "started_at": attempt.started_at.isoformat(),
        "finished_at": attempt.finished_at.isoformat(),
        "duration_ms": max(
            0,
            int((attempt.finished_at - attempt.started_at).total_seconds() * 1000),
        ),
        "result": result,
        "provider_request_id": attempt.provider_request_id,
        "raw_payload_id": attempt.raw_payload_id,
        "raw_payload_sha256": attempt.raw_payload_sha256,
        "usage": _usage_contract(attempt.usage),
        "cost": {
            "reserved_cost_usd": reserved_cost,
            "estimated_cost_usd": attempt.estimated_cost_usd,
            "billed_cost_usd": billed_cost,
            "currency": "USD",
            "price_card_version": (execution.request.price_card.price_card_id),
        },
        "validation": validation,
        "retry_reason": attempt.retry_reason,
    }


def _gate_contract(execution: GraderExecution) -> dict[str, object]:
    failed = set(execution.blocking_reasons)
    reason_by_check = {
        "config_approved": {
            "model_config_inactive",
            "source_processing_not_approved",
            "unapproved_evidence_source",
            "prompt_inactive",
            "output_schema_mismatch",
            "retry_policy_invalid",
            "evidence_bundle_not_grader_ready",
            "evidence_passage_content_unavailable",
            "evidence_passage_hash_mismatch",
            "grader_not_eligible",
        },
        "retention_policy_approved": {"provider_retention_not_approved"},
        "evaluation_release_approved": {
            "model_evaluation_missing",
            "prompt_evaluation_missing",
        },
        "price_card_available": {"price_card_invalid"},
        "budget_available": {"hard_budget_unavailable"},
        "token_caps_valid": {"token_cap_invalid"},
        "operator_environment_allowed": {"execution_environment_mismatch"},
    }
    checks = []
    for check_id, reasons in reason_by_check.items():
        matched = sorted(failed.intersection(reasons))
        checks.append(
            {
                "check_id": check_id,
                "passed": not matched,
                "reason_code": matched[0] if matched else "approved",
            }
        )
    return {
        "policy_version": execution.policy_version,
        "status": "passed" if all(c["passed"] for c in checks) else "blocked",
        "checked_at": (
            execution.attempts[0].started_at.isoformat()
            if execution.attempts
            else execution.created_at.isoformat()
        ),
        "checks": checks,
    }


def _opinion_contract(
    execution: GraderExecution,
    opinion: GraderOpinion,
) -> dict[str, object]:
    payload_key = f"{opinion.grader_id}_payload"
    return {
        "opinion_id": opinion.opinion_id,
        "execution_id": execution.execution_id,
        "grader_id": opinion.grader_id,
        "grader_version": opinion.grader_version,
        "execution_state": opinion.execution_state,
        "owned_decision_question": opinion.owned_decision_question,
        "stance": opinion.grader_stance,
        "confidence": opinion.confidence,
        "summary": opinion.summary,
        "material_claims": [
            {
                "claim_id": claim.claim_id,
                "claim": claim.claim,
                "materiality": claim.materiality,
                "evidence_ids": list(claim.evidence_ids),
            }
            for claim in opinion.material_claims
        ],
        "assumptions": list(opinion.assumptions),
        "contradicting_evidence": [
            {
                "evidence_id": item.evidence_id,
                "explanation": item.explanation,
            }
            for item in opinion.contradicting_evidence
        ],
        "evidence_gaps": [
            {
                "gap_id": item.gap_id,
                "description": item.description,
                "required_evidence": item.required_evidence,
            }
            for item in opinion.evidence_gaps
        ],
        "invalidation_signals": list(opinion.invalidation_signals),
        "proposition": {
            "proposition_id": opinion.proposition_id,
            "proposition_version": opinion.proposition_version,
            "rendered_proposition_text": (opinion.rendered_proposition_text),
            "grader_stance": opinion.grader_stance,
            "stance_rationale": (
                opinion.stance_rationale
                if opinion.execution_state == "accepted"
                else None
            ),
        },
        payload_key: dict(opinion.domain_payload),
        "abstention": (opinion.abstention.as_dict() if opinion.abstention else None),
        "created_at": execution.created_at.isoformat(),
    }


def _failure_contract(failure: ExecutionFailure) -> dict[str, object]:
    if failure.final_reason == "transport_retry_exhausted":
        category = "timeout"
    elif "invalid_opinion_citation" in failure.validation_errors:
        category = "citation_validation"
    elif failure.validation_errors:
        category = "schema_validation"
    else:
        category = "execution_failure"
    return {
        "category": category,
        "attempt_count": failure.attempt_count,
        "validation_errors": list(failure.validation_errors),
        "final_reason": failure.final_reason,
        "retry_policy_version": failure.retry_policy_version,
    }


def _inference_parameter_hash(model: ModelConfiguration) -> str:
    payload = {
        "reasoning_effort": model.reasoning_effort,
        "thinking_enabled": model.thinking_enabled,
        "temperature": model.temperature,
        "input_token_cap": model.input_token_cap,
        "output_token_cap": model.output_token_cap,
    }
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()


def _raw_attempt_identity(
    operator_id: str,
    attempt_id: str,
    audit: Mapping[str, object],
) -> tuple[str, str]:
    return (
        stable_id(operator_id, "grader-raw-payload", attempt_id),
        hashlib.sha256(_canonical_json(audit).encode()).hexdigest(),
    )


@runtime_checkable
class GraderExecutionRepository(Protocol):
    def begin_raw_attempt(
        self,
        operator_id: str,
        attempt_id: str,
        request_payload: Mapping[str, object],
    ) -> tuple[str, str]: ...

    def finish_raw_attempt(
        self,
        operator_id: str,
        attempt_id: str,
        response_payload: Mapping[str, object],
    ) -> tuple[str, str]: ...

    def save(self, execution: GraderExecution) -> GraderExecution: ...

    def get_for_identity(
        self,
        operator_id: str,
        execution_identity: str,
    ) -> GraderExecution | None: ...


@runtime_checkable
class BudgetLedger(Protocol):
    def reserve(self, amount: Decimal) -> str: ...

    def reconcile(self, reservation_id: str, actual: Decimal) -> None: ...

    def release(self, reservation_id: str) -> None: ...


class InMemoryGraderExecutionRepository:
    def __init__(self) -> None:
        self._executions: dict[tuple[str, str], GraderExecution] = {}
        self._raw_attempts: dict[tuple[str, str], Mapping[str, object]] = {}

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
                raise GraderExecutionError("conflicting immutable raw attempt request")
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
            raise GraderExecutionError("raw attempt request is unavailable")
        current_response = existing.get("response")
        if current_response is not None and current_response != safe_response:
            raise GraderExecutionError("conflicting immutable raw attempt response")
        if current_response is None:
            existing = {
                "request": existing["request"],
                "response": safe_response,
            }
            self._raw_attempts[key] = existing
        return _raw_attempt_identity(operator_id, attempt_id, existing)

    def save(self, execution: GraderExecution) -> GraderExecution:
        key = (execution.operator_id, execution.execution_identity)
        existing = self._executions.get(key)
        if existing is not None:
            if existing != execution:
                raise GraderExecutionError("conflicting immutable execution")
            return existing
        self._executions[key] = execution
        return execution

    def read_raw_attempt(
        self,
        operator_id: str,
        attempt_id: str,
        *,
        audit_authorized: bool,
    ) -> Mapping[str, object] | None:
        if not audit_authorized:
            raise GraderExecutionError("raw provider payload audit denied")
        return self._raw_attempts.get((operator_id, attempt_id))

    def get_for_identity(
        self,
        operator_id: str,
        execution_identity: str,
    ) -> GraderExecution | None:
        return self._executions.get((operator_id, execution_identity))


class InMemoryBudgetLedger:
    def __init__(self, *, hard_limit_usd: Decimal) -> None:
        self.hard_limit_usd = hard_limit_usd
        self.reserved_usd = Decimal("0")
        self.reconciled_usd = Decimal("0")

    def reserve(self, amount: Decimal) -> str:
        if (
            amount <= 0
            or self.reserved_usd + self.reconciled_usd + amount > self.hard_limit_usd
        ):
            raise GraderExecutionError("hard budget unavailable")
        self.reserved_usd += amount
        return "offline-budget-reservation"

    def reconcile(self, reservation_id: str, actual: Decimal) -> None:
        if reservation_id != "offline-budget-reservation":
            raise GraderExecutionError("budget reservation not found")
        self.reserved_usd = Decimal("0")
        self.reconciled_usd += actual

    def release(self, reservation_id: str) -> None:
        if reservation_id != "offline-budget-reservation":
            raise GraderExecutionError("budget reservation not found")
        self.reserved_usd = Decimal("0")


class GraderExecutionWorkflow:
    def __init__(
        self,
        *,
        evidence_bundle_repository: EvidenceBundleRepository,
        execution_repository: GraderExecutionRepository,
        budget_ledger: BudgetLedger,
        provider: GraderProvider,
        clock: Callable[[], datetime],
        valuation_snapshot_repository: ValuationSnapshotRepository | None = None,
    ) -> None:
        self._evidence_bundle_repository = evidence_bundle_repository
        self._execution_repository = execution_repository
        self._budget_ledger = budget_ledger
        self._provider = provider
        self._clock = clock
        self._valuation_snapshot_repository = valuation_snapshot_repository

    def execute(
        self,
        operator: AuthenticatedOperator,
        request: GraderExecutionRequest,
    ) -> GraderExecution:
        bundle = self._evidence_bundle_repository.get(
            operator.id,
            request.evidence_bundle_id,
        )
        if bundle is None:
            raise GraderExecutionError("evidence bundle not found")
        valuation_snapshot = (
            None
            if self._valuation_snapshot_repository is None
            else self._valuation_snapshot_repository.get_for_run(
                operator.id,
                bundle.research_run_id,
            )
        )
        if valuation_snapshot is not None and (
            valuation_snapshot.evidence_bundle_id != bundle.id
            or valuation_snapshot.evidence_bundle_hash != bundle.content_hash
            or valuation_snapshot.security_id != bundle.security_id
        ):
            raise GraderExecutionError("valuation snapshot evidence mismatch")
        identity_payload = {
            "bundle_hash": bundle.content_hash,
            "valuation_snapshot_id": (
                None if valuation_snapshot is None else valuation_snapshot.id
            ),
            "question_type_id": request.question_type_id,
            "question_type_version": request.question_type_version,
            "workflow_config_version": request.workflow_config_version,
            "grader_id": request.grader.grader_id,
            "grader_version": request.grader.grader_version,
            "rubric_version": request.grader.rubric_version,
            "schema_version": request.grader.output_schema_version,
            "prompt_version": request.prompt.prompt_version,
            "prompt_input_schema_version": (request.prompt.input_schema_version),
            "prompt_content_sha256": request.prompt.content_sha256,
            "evaluation_corpus_sha256": (request.prompt.evaluation_corpus_sha256),
            "evaluation_corpus_id": request.prompt.evaluation_corpus_id,
            "evaluation_corpus_version": (request.prompt.evaluation_corpus_version),
            "evaluation_identity_sha256": (request.prompt.evaluation_identity_sha256),
            "model_config_version": request.model.config_version,
            "provider": request.model.provider,
            "model": request.model.model,
            "reasoning_effort": request.model.reasoning_effort,
            "thinking_enabled": request.model.thinking_enabled,
            "temperature": request.model.temperature,
            "input_token_cap": request.model.input_token_cap,
            "output_token_cap": request.model.output_token_cap,
        }
        identity_json = _canonical_json(identity_payload)
        execution_identity = hashlib.sha256(identity_json.encode()).hexdigest()
        existing = self._execution_repository.get_for_identity(
            operator.id,
            execution_identity,
        )
        if existing is not None:
            return existing

        gate_time = self._clock()
        bundle_sources_approved = True
        try:
            for item in bundle.manifest:
                validate_evidence_source_url(item.canonical_url)
        except EvidenceBundleError:
            bundle_sources_approved = False
        blocking_reasons = _pre_call_blocking_reasons(
            bundle.grader_ready,
            bundle_sources_approved,
            request,
            gate_time,
        )
        blocking_reasons = tuple(
            dict.fromkeys(
                (
                    *blocking_reasons,
                    *_evidence_passage_blocking_reasons(bundle),
                )
            )
        )
        if blocking_reasons:
            return self._execution_repository.save(
                _not_executed_execution(
                    operator.id,
                    bundle,
                    request,
                    execution_identity,
                    blocking_reasons,
                    gate_time,
                )
            )

        logical_input = {
            "bundle": bundle.as_dict(),
            "evidence_passages": [
                {
                    "evidence_id": item.evidence_id,
                    "evidence_version_id": item.evidence_version_id,
                    "passage_id": item.passage_id,
                    "source_locator": item.source_locator,
                    "passage_sha256": item.passage_hash,
                    "passage_text": item.passage_text,
                }
                for item in bundle.manifest
                if item.item_kind == "passage"
            ],
            "valuation_snapshot": (
                None if valuation_snapshot is None else valuation_snapshot.as_dict()
            ),
            "question_type_id": request.question_type_id,
            "question_type_version": request.question_type_version,
            "workflow_config_version": request.workflow_config_version,
            "proposition_id": request.proposition_id,
            "proposition_version": request.proposition_version,
            "rendered_proposition": request.rendered_proposition,
            "grader": identity_payload,
        }
        request_hash = hashlib.sha256(
            _canonical_json(logical_input).encode()
        ).hexdigest()
        attempts: list[GraderAttempt] = []
        validation_errors: tuple[str, ...] = ()
        previous_retry_reason: str | None = None
        exhausted_reason = "validation_retry_exhausted"
        allowed_evidence_ids = {item.evidence_id for item in bundle.manifest}
        allowed_calculation_ids = {item.snapshot_id for item in bundle.metrics}
        if valuation_snapshot is not None:
            allowed_calculation_ids.update(valuation_snapshot.calculation_ids)
        for attempt_number in range(1, request.policy.max_attempts + 1):
            try:
                reservation = self._budget_ledger.reserve(
                    _maximum_cost(request.model, request.price_card)
                )
            except GraderExecutionError as error:
                if str(error) != "hard budget unavailable":
                    raise
                if not attempts:
                    execution = _not_executed_execution(
                        operator.id,
                        bundle,
                        request,
                        execution_identity,
                        ("hard_budget_unavailable",),
                        gate_time,
                    )
                else:
                    execution = _terminal_execution(
                        operator.id,
                        bundle,
                        request,
                        execution_identity,
                        "failed",
                        tuple(attempts),
                        None,
                        ("retry_budget_unavailable",),
                        self._clock(),
                    )
                return self._execution_repository.save(execution)

            provider_request = ProviderRequest(
                execution_identity=execution_identity,
                request_hash=request_hash,
                provider=request.model.provider,
                model=request.model.model,
                logical_input=logical_input,
                reasoning_effort=request.model.reasoning_effort,
                thinking_enabled=request.model.thinking_enabled,
                temperature=request.model.temperature,
                input_token_cap=request.model.input_token_cap,
                output_token_cap=request.model.output_token_cap,
                execution_role=f"grader:{request.grader.grader_id}",
                prompt_id=request.prompt.prompt_id,
                prompt_version=request.prompt.prompt_version,
                prompt_content_sha256=request.prompt.content_sha256,
                input_schema_version=request.prompt.input_schema_version,
                output_schema_version=request.prompt.output_schema_version,
                attempt_number=attempt_number,
                validation_errors=validation_errors,
            )
            started_at = self._clock()
            attempt_id = stable_id(
                operator.id,
                "grader-attempt",
                f"{execution_identity}:{attempt_number}",
            )
            raw_payload_id, raw_payload_sha256 = (
                self._execution_repository.begin_raw_attempt(
                    operator.id,
                    attempt_id,
                    self._provider.audit_request(provider_request),
                )
            )
            try:
                response = self._provider.execute(provider_request)
            except ProviderTransportError as error:
                self._budget_ledger.release(reservation)
                finished_at = self._clock()
                attempts.append(
                    GraderAttempt(
                        attempt_id=attempt_id,
                        attempt_number=attempt_number,
                        request_hash=request_hash,
                        provider_request_id=None,
                        raw_payload_id=raw_payload_id,
                        raw_payload_sha256=raw_payload_sha256,
                        provider=request.model.provider,
                        requested_model=request.model.model,
                        resolved_model=request.model.model,
                        system_fingerprint=None,
                        validation_state="transport_error",
                        validation_errors=(),
                        retry_reason=error.code,
                        usage=ProviderUsage(0, 0, 0, 0, 0),
                        estimated_cost_usd="0",
                        price_card_id=request.price_card.price_card_id,
                        started_at=started_at,
                        finished_at=finished_at,
                    )
                )
                previous_retry_reason = error.code
                if not error.retryable:
                    return self._execution_repository.save(
                        _terminal_execution(
                            operator.id,
                            bundle,
                            request,
                            execution_identity,
                            "failed",
                            tuple(attempts),
                            None,
                            (error.code,),
                            finished_at,
                        )
                    )
                exhausted_reason = "transport_retry_exhausted"
                continue
            raw_payload_id, raw_payload_sha256 = (
                self._execution_repository.finish_raw_attempt(
                    operator.id,
                    attempt_id,
                    response.raw_provider_response or response.raw_output,
                )
            )
            usage_error = _provider_usage_error(response.usage)
            if usage_error is not None:
                self._budget_ledger.release(reservation)
                finished_at = self._clock()
                attempts.append(
                    GraderAttempt(
                        attempt_id=attempt_id,
                        attempt_number=attempt_number,
                        request_hash=request_hash,
                        provider_request_id=response.provider_request_id,
                        raw_payload_id=raw_payload_id,
                        raw_payload_sha256=raw_payload_sha256,
                        provider=request.model.provider,
                        requested_model=request.model.model,
                        resolved_model=response.resolved_model,
                        system_fingerprint=response.system_fingerprint,
                        validation_state="rejected",
                        validation_errors=(usage_error,),
                        retry_reason=usage_error,
                        usage=ProviderUsage(0, 0, 0, 0, 0, 0, False),
                        estimated_cost_usd="0",
                        price_card_id=request.price_card.price_card_id,
                        started_at=started_at,
                        finished_at=finished_at,
                    )
                )
                validation_errors = (usage_error,)
                previous_retry_reason = usage_error
                exhausted_reason = "validation_retry_exhausted"
                continue
            actual_cost = _actual_cost(response.usage, request.price_card)
            self._budget_ledger.reconcile(reservation, actual_cost)
            finished_at = self._clock()
            if response.resolved_model != request.model.model:
                error_code = "provider_model_mismatch"
                attempts.append(
                    GraderAttempt(
                        attempt_id=attempt_id,
                        attempt_number=attempt_number,
                        request_hash=request_hash,
                        provider_request_id=response.provider_request_id,
                        raw_payload_id=raw_payload_id,
                        raw_payload_sha256=raw_payload_sha256,
                        provider=request.model.provider,
                        requested_model=request.model.model,
                        resolved_model=response.resolved_model,
                        system_fingerprint=response.system_fingerprint,
                        validation_state="rejected",
                        validation_errors=(error_code,),
                        retry_reason=error_code,
                        usage=response.usage,
                        estimated_cost_usd=format(actual_cost, "f"),
                        price_card_id=request.price_card.price_card_id,
                        started_at=started_at,
                        finished_at=finished_at,
                    )
                )
                validation_errors = (error_code,)
                previous_retry_reason = error_code
                exhausted_reason = "validation_retry_exhausted"
                continue
            try:
                opinion = _validate_opinion(
                    operator.id,
                    execution_identity,
                    request,
                    response.raw_output,
                    allowed_evidence_ids,
                    allowed_calculation_ids,
                )
            except GraderExecutionError as error:
                error_code = _validation_error_code(error)
                attempts.append(
                    GraderAttempt(
                        attempt_id=attempt_id,
                        attempt_number=attempt_number,
                        request_hash=request_hash,
                        provider_request_id=response.provider_request_id,
                        raw_payload_id=raw_payload_id,
                        raw_payload_sha256=raw_payload_sha256,
                        provider=request.model.provider,
                        requested_model=request.model.model,
                        resolved_model=response.resolved_model,
                        system_fingerprint=response.system_fingerprint,
                        validation_state="rejected",
                        validation_errors=(error_code,),
                        retry_reason=error_code,
                        usage=response.usage,
                        estimated_cost_usd=format(actual_cost, "f"),
                        price_card_id=request.price_card.price_card_id,
                        started_at=started_at,
                        finished_at=finished_at,
                    )
                )
                validation_errors = (error_code,)
                previous_retry_reason = error_code
                exhausted_reason = "validation_retry_exhausted"
                continue

            attempts.append(
                GraderAttempt(
                    attempt_id=attempt_id,
                    attempt_number=attempt_number,
                    request_hash=request_hash,
                    provider_request_id=response.provider_request_id,
                    raw_payload_id=raw_payload_id,
                    raw_payload_sha256=raw_payload_sha256,
                    provider=request.model.provider,
                    requested_model=request.model.model,
                    resolved_model=response.resolved_model,
                    system_fingerprint=response.system_fingerprint,
                    validation_state="accepted",
                    validation_errors=(),
                    retry_reason=(previous_retry_reason),
                    usage=response.usage,
                    estimated_cost_usd=format(actual_cost, "f"),
                    price_card_id=request.price_card.price_card_id,
                    started_at=started_at,
                    finished_at=finished_at,
                )
            )
            return self._execution_repository.save(
                _terminal_execution(
                    operator.id,
                    bundle,
                    request,
                    execution_identity,
                    opinion.execution_state,
                    tuple(attempts),
                    opinion,
                    (),
                    finished_at,
                )
            )

        return self._execution_repository.save(
            _terminal_execution(
                operator.id,
                bundle,
                request,
                execution_identity,
                "failed",
                tuple(attempts),
                None,
                (exhausted_reason, *validation_errors),
                self._clock(),
            )
        )


def _validate_opinion(
    operator_id: str,
    execution_identity: str,
    request: GraderExecutionRequest,
    raw_output: Mapping[str, object],
    allowed_evidence_ids: set[str],
    allowed_calculation_ids: set[str],
) -> GraderOpinion:
    payload_key = f"{request.grader.grader_id}_payload"
    expected_keys = {
        "execution_state",
        "grader_id",
        "grader_version",
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
        payload_key,
        "abstention",
    }
    if set(raw_output) != expected_keys:
        raise GraderExecutionError("invalid provider output fields")
    execution_state = raw_output.get("execution_state")
    if execution_state not in {"accepted", "abstained"}:
        raise GraderExecutionError("provider output is not accepted opinion")
    expected = {
        "grader_id": request.grader.grader_id,
        "grader_version": request.grader.grader_version,
        "owned_decision_question": request.grader.owned_decision_question,
    }
    if any(raw_output.get(key) != value for key, value in expected.items()):
        raise GraderExecutionError("provider output identity mismatch")
    if raw_output.get("confidence") not in {"high", "medium", "low"}:
        raise GraderExecutionError("invalid confidence")
    if not _nonempty_text(raw_output.get("summary")):
        raise GraderExecutionError("invalid summary")
    if not _text_list(raw_output.get("assumptions")):
        raise GraderExecutionError("invalid assumptions")
    if not _text_list(raw_output.get("invalidation_signals")):
        raise GraderExecutionError("invalid invalidation signals")
    stance = raw_output.get("stance")
    if execution_state == "accepted" and stance not in {
        "supports",
        "mixed",
        "challenges",
    }:
        raise GraderExecutionError("invalid grader stance")
    if execution_state == "abstained" and stance is not None:
        raise GraderExecutionError("abstention cannot include stance")
    raw_claims = raw_output.get("material_claims")
    if not isinstance(raw_claims, list):
        raise GraderExecutionError("invalid material claims")
    claims: list[MaterialClaim] = []
    for item in raw_claims:
        if (
            not isinstance(item, dict)
            or set(item) != {"claim_id", "claim", "materiality", "evidence_ids"}
            or not _nonempty_text(item.get("claim_id"))
            or not _nonempty_text(item.get("claim"))
            or item.get("materiality") not in {"high", "medium", "low"}
            or not _text_list(item.get("evidence_ids"), require_item=True)
        ):
            raise GraderExecutionError("invalid material claim")
        evidence_ids = tuple(str(value) for value in item["evidence_ids"])
        if not evidence_ids or any(
            evidence_id not in allowed_evidence_ids for evidence_id in evidence_ids
        ):
            raise GraderExecutionError("invalid opinion citation")
        claims.append(
            MaterialClaim(
                claim_id=str(item["claim_id"]),
                claim=str(item["claim"]),
                materiality=str(item["materiality"]),
                evidence_ids=evidence_ids,
            )
        )
    proposition = raw_output.get("proposition")
    if not isinstance(proposition, dict) or set(proposition) != {
        "proposition_id",
        "proposition_version",
        "rendered_proposition_text",
        "grader_stance",
        "stance_rationale",
    }:
        raise GraderExecutionError("invalid proposition")
    if (
        proposition.get("proposition_id") != request.proposition_id
        or proposition.get("proposition_version") != request.proposition_version
        or proposition.get("rendered_proposition_text") != request.rendered_proposition
        or proposition.get("grader_stance") != stance
    ):
        raise GraderExecutionError("provider output identity mismatch")
    if execution_state == "accepted" and not isinstance(
        proposition.get("stance_rationale"), str
    ):
        raise GraderExecutionError("invalid grader stance")
    if (
        execution_state == "abstained"
        and proposition.get("stance_rationale") is not None
    ):
        raise GraderExecutionError("abstention cannot include stance")
    domain_payload = raw_output.get(payload_key)
    if not isinstance(domain_payload, dict):
        raise GraderExecutionError("invalid domain payload")
    if not _valid_domain_payload(
        request.grader.grader_id,
        request.grader.output_schema_version,
        domain_payload,
        allowed_evidence_ids,
        allowed_calculation_ids,
    ):
        raise GraderExecutionError("invalid domain payload")
    raw_contradictions = raw_output.get("contradicting_evidence")
    if not isinstance(raw_contradictions, list):
        raise GraderExecutionError("invalid contradicting evidence")
    contradictions: list[ContradictingEvidence] = []
    for item in raw_contradictions:
        if not isinstance(item, dict) or set(item) != {
            "evidence_id",
            "explanation",
        }:
            raise GraderExecutionError("invalid contradicting evidence")
        evidence_id = str(item["evidence_id"])
        if evidence_id not in allowed_evidence_ids:
            raise GraderExecutionError("invalid opinion citation")
        contradictions.append(
            ContradictingEvidence(evidence_id, str(item["explanation"]))
        )
    raw_gaps = raw_output.get("evidence_gaps")
    if not isinstance(raw_gaps, list):
        raise GraderExecutionError("invalid evidence gaps")
    gaps: list[EvidenceGap] = []
    for item in raw_gaps:
        if not isinstance(item, dict) or set(item) != {
            "gap_id",
            "description",
            "required_evidence",
        }:
            raise GraderExecutionError("invalid evidence gaps")
        gaps.append(
            EvidenceGap(
                gap_id=str(item["gap_id"]),
                description=str(item["description"]),
                required_evidence=str(item["required_evidence"]),
            )
        )
    abstention_payload = raw_output.get("abstention")
    abstention = None
    if execution_state == "abstained":
        if not isinstance(abstention_payload, dict):
            raise GraderExecutionError("invalid abstention")
        missing_evidence = abstention_payload.get("missing_or_inadequate_evidence")
        evidence_required = abstention_payload.get("evidence_required")
        if not isinstance(missing_evidence, list) or not isinstance(
            evidence_required,
            list,
        ):
            raise GraderExecutionError("invalid abstention")
        abstention = AbstentionResult(
            reason_code=str(abstention_payload["reason_code"]),
            reason=str(abstention_payload["reason"]),
            missing_or_inadequate_evidence=tuple(
                str(value) for value in missing_evidence
            ),
            evidence_required=tuple(str(value) for value in evidence_required),
            confidence=str(abstention_payload["confidence"]),
        )
    elif abstention_payload is not None:
        raise GraderExecutionError("accepted opinion cannot include abstention")
    return GraderOpinion(
        opinion_id=stable_id(
            operator_id,
            "grader-opinion",
            execution_identity,
        ),
        execution_state=str(execution_state),
        grader_id=request.grader.grader_id,
        grader_version=request.grader.grader_version,
        owned_decision_question=request.grader.owned_decision_question,
        proposition_id=request.proposition_id,
        proposition_version=request.proposition_version,
        rendered_proposition_text=request.rendered_proposition,
        grader_stance=str(stance) if stance is not None else None,
        stance_rationale=(
            str(proposition["stance_rationale"])
            if proposition["stance_rationale"] is not None
            else ""
        ),
        confidence=str(raw_output["confidence"]),
        summary=str(raw_output["summary"]),
        material_claims=tuple(claims),
        assumptions=tuple(str(value) for value in raw_output["assumptions"]),
        contradicting_evidence=tuple(contradictions),
        evidence_gaps=tuple(gaps),
        invalidation_signals=tuple(
            str(value) for value in raw_output["invalidation_signals"]
        ),
        abstention=abstention,
        domain_payload=dict(domain_payload),
    )


def _valid_domain_payload(
    grader_id: str,
    schema_version: str,
    payload: Mapping[str, object],
    allowed_evidence_ids: set[str],
    allowed_calculation_ids: set[str],
) -> bool:
    fields_by_grader = {
        "moonshot": {
            "contract_version",
            "mission_relevance",
            "asymmetry_assessment",
            "evidence_maturity",
            "strategic_or_societal_value",
            "asymmetry_drivers",
            "limiting_factors",
        },
        "catalyst": {
            "contract_version",
            "catalyst_definition",
            "programme",
            "probability",
            "timing_window",
            "date_confidence",
            "success_outcome",
            "delay_outcome",
            "partial_success_outcome",
            "failure_outcome",
        },
        "biotech": {
            "contract_version",
            "mechanism_plausibility",
            "preclinical_evidence_quality",
            "clinical_evidence_quality",
            "trial_design_assessment",
            "endpoint_relevance",
            "regulatory_credibility",
            "claims_exceed_evidence",
            "limitations",
        },
        "risk_dilution": {
            "contract_version",
            "cash_runway",
            "burn_rate",
            "going_concern_risk",
            "dilution_mechanisms",
            "financing_required_before_catalyst",
            "downside_mechanisms",
            "permanent_capital_loss_mechanisms",
        },
        "valuation": {
            "contract_version",
            "valuation_method",
            "current_market_value",
            "fully_diluted_shares",
            "scenarios",
            "sensitivities",
        },
    }
    expected_fields = fields_by_grader.get(grader_id)
    if expected_fields is None or set(payload) != expected_fields:
        return False
    if payload.get("contract_version") != schema_version:
        return False
    if grader_id == "moonshot":
        return (
            payload.get("mission_relevance")
            in {"material", "limited", "none", "indeterminate"}
            and payload.get("asymmetry_assessment")
            in {"credible", "conditional", "not_supported", "indeterminate"}
            and payload.get("evidence_maturity")
            in {"clinical", "preclinical", "mixed", "insufficient"}
            and payload.get("strategic_or_societal_value")
            in {"material", "limited", "not_supported", "indeterminate"}
            and _text_list(payload.get("asymmetry_drivers"))
            and _text_list(payload.get("limiting_factors"))
        )
    if grader_id == "catalyst":
        text_fields = (
            "catalyst_definition",
            "programme",
            "timing_window",
            "success_outcome",
            "delay_outcome",
            "partial_success_outcome",
            "failure_outcome",
        )
        return (
            all(_nonempty_text(payload.get(field)) for field in text_fields)
            and payload.get("date_confidence") in {"high", "medium", "low"}
            and _valid_numeric_value(
                payload.get("probability"),
                allowed_evidence_ids,
                allowed_calculation_ids,
            )
        )
    if grader_id == "biotech":
        return (
            payload.get("mechanism_plausibility")
            in {"credible", "mixed", "not_supported", "indeterminate"}
            and payload.get("preclinical_evidence_quality")
            in {"strong", "moderate", "weak", "absent"}
            and payload.get("clinical_evidence_quality")
            in {"strong", "moderate", "weak", "absent"}
            and _nonempty_text(payload.get("trial_design_assessment"))
            and payload.get("endpoint_relevance")
            in {"clinically_meaningful", "surrogate", "weak", "indeterminate"}
            and payload.get("regulatory_credibility")
            in {"credible", "mixed", "weak", "indeterminate"}
            and isinstance(payload.get("claims_exceed_evidence"), bool)
            and _text_list(payload.get("limitations"))
        )
    if grader_id == "risk_dilution" and any(
        not _valid_numeric_value(
            payload.get(field),
            allowed_evidence_ids,
            allowed_calculation_ids,
        )
        for field in ("cash_runway", "burn_rate")
    ):
        return False
    if grader_id == "risk_dilution":
        return (
            payload.get("going_concern_risk")
            in {"low", "moderate", "high", "indeterminate"}
            and payload.get("financing_required_before_catalyst")
            in {"no", "possible", "yes", "indeterminate"}
            and all(
                _text_list(payload.get(field))
                for field in (
                    "dilution_mechanisms",
                    "downside_mechanisms",
                    "permanent_capital_loss_mechanisms",
                )
            )
        )
    if grader_id == "valuation":
        if not _nonempty_text(payload.get("valuation_method")) or not _text_list(
            payload.get("sensitivities")
        ):
            return False
        if any(
            not _valid_numeric_value(
                payload.get(field),
                allowed_evidence_ids,
                allowed_calculation_ids,
            )
            for field in ("current_market_value", "fully_diluted_shares")
        ):
            return False
        scenarios = payload.get("scenarios")
        if not isinstance(scenarios, list) or len(scenarios) != 4:
            return False
        cases: set[str] = set()
        for scenario in scenarios:
            if not isinstance(scenario, Mapping) or set(scenario) != {
                "scenario_id",
                "case",
                "probability",
                "equity_value",
                "implied_value_per_diluted_share",
                "assumptions",
            }:
                return False
            case = str(scenario.get("case"))
            cases.add(case)
            if any(
                not _valid_numeric_value(
                    scenario.get(field),
                    allowed_evidence_ids,
                    allowed_calculation_ids,
                )
                for field in (
                    "probability",
                    "equity_value",
                    "implied_value_per_diluted_share",
                )
            ):
                return False
            if not _nonempty_text(scenario.get("scenario_id")) or not _text_list(
                scenario.get("assumptions")
            ):
                return False
        if cases != {"conservative", "base", "bull", "failure"}:
            return False
    return True


def _nonempty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _text_list(value: object, *, require_item: bool = False) -> bool:
    return (
        isinstance(value, list)
        and (not require_item or bool(value))
        and all(_nonempty_text(item) for item in value)
    )


def _valid_numeric_value(
    value: object,
    allowed_evidence_ids: set[str],
    allowed_calculation_ids: set[str],
) -> bool:
    if not isinstance(value, Mapping) or set(value) != {
        "value",
        "unit",
        "calculation_method",
        "assumptions",
        "evidence_ids",
        "calculation_ids",
    }:
        return False
    evidence_ids = value.get("evidence_ids")
    assumptions = value.get("assumptions")
    calculation_ids = value.get("calculation_ids")
    if not _nonempty_text(value.get("value")):
        return False
    try:
        parsed_value = Decimal(str(value.get("value")))
    except Exception:
        return False
    if not parsed_value.is_finite():
        return False
    if not _nonempty_text(value.get("unit")) or not _nonempty_text(
        value.get("calculation_method")
    ):
        return False
    if not _text_list(evidence_ids) or not _text_list(calculation_ids):
        return False
    if not evidence_ids and not calculation_ids:
        return False
    if any(str(item) not in allowed_evidence_ids for item in evidence_ids):
        return False
    if any(str(item) not in allowed_calculation_ids for item in calculation_ids):
        return False
    return _text_list(assumptions)


def _not_executed_execution(
    operator_id: str,
    bundle: EvidenceBundle,
    request: GraderExecutionRequest,
    execution_identity: str,
    blocking_reasons: tuple[str, ...],
    created_at: datetime,
) -> GraderExecution:
    return GraderExecution(
        execution_id=stable_id(
            operator_id,
            "grader-execution",
            execution_identity,
        ),
        execution_identity=execution_identity,
        operator_id=operator_id,
        research_run_id=bundle.research_run_id,
        evidence_bundle_id=bundle.id,
        bundle_hash=bundle.content_hash,
        question_type_id=request.question_type_id,
        question_type_version=request.question_type_version,
        workflow_config_version=request.workflow_config_version,
        grader_id=request.grader.grader_id,
        grader_version=request.grader.grader_version,
        prompt_version=request.prompt.prompt_version,
        model_config_version=request.model.config_version,
        execution_state="not_executed",
        attempts=(),
        opinion=None,
        blocking_reasons=blocking_reasons,
        policy_version=request.policy.policy_version,
        retry_policy_version=request.policy.retry_policy_version,
        created_at=created_at,
        request=request,
    )


def _terminal_execution(
    operator_id: str,
    bundle: EvidenceBundle,
    request: GraderExecutionRequest,
    execution_identity: str,
    execution_state: str,
    attempts: tuple[GraderAttempt, ...],
    opinion: GraderOpinion | None,
    blocking_reasons: tuple[str, ...],
    created_at: datetime,
) -> GraderExecution:
    failure = None
    if execution_state == "failed":
        validation_errors = tuple(
            dict.fromkeys(
                error for attempt in attempts for error in attempt.validation_errors
            )
        )
        final_reason = blocking_reasons[0]
        failure = ExecutionFailure(
            category=(
                "transport_failure"
                if any(
                    attempt.validation_state == "transport_error"
                    for attempt in attempts
                )
                else ("validation_failure" if validation_errors else "budget_failure")
            ),
            attempt_count=len(attempts),
            validation_errors=validation_errors,
            final_reason=final_reason,
            retry_policy_version=request.policy.retry_policy_version,
        )
    return GraderExecution(
        execution_id=stable_id(
            operator_id,
            "grader-execution",
            execution_identity,
        ),
        execution_identity=execution_identity,
        operator_id=operator_id,
        research_run_id=bundle.research_run_id,
        evidence_bundle_id=bundle.id,
        bundle_hash=bundle.content_hash,
        question_type_id=request.question_type_id,
        question_type_version=request.question_type_version,
        workflow_config_version=request.workflow_config_version,
        grader_id=request.grader.grader_id,
        grader_version=request.grader.grader_version,
        prompt_version=request.prompt.prompt_version,
        model_config_version=request.model.config_version,
        execution_state=execution_state,
        attempts=attempts,
        opinion=opinion,
        blocking_reasons=blocking_reasons,
        policy_version=request.policy.policy_version,
        retry_policy_version=request.policy.retry_policy_version,
        created_at=created_at,
        failure=failure,
        request=request,
    )


def _validation_error_code(error: GraderExecutionError) -> str:
    return {
        "invalid opinion citation": "invalid_opinion_citation",
        "provider output identity mismatch": "output_identity_mismatch",
        "provider output is not accepted opinion": "unsupported_output_state",
        "invalid grader stance": "invalid_grader_stance",
        "invalid material claims": "malformed_schema",
        "invalid material claim": "malformed_schema",
        "invalid domain payload": "malformed_schema",
        "invalid abstention": "malformed_abstention",
        "abstention cannot include stance": "abstention_has_stance",
        "accepted opinion cannot include abstention": "accepted_has_abstention",
    }.get(str(error), "contract_validation_failed")


def _pre_call_blocking_reasons(
    bundle_grader_ready: bool,
    bundle_sources_approved: bool,
    request: GraderExecutionRequest,
    checked_at: datetime,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not bundle_grader_ready:
        reasons.append("evidence_bundle_not_grader_ready")
    if not bundle_sources_approved:
        reasons.append("unapproved_evidence_source")
    if not request.grader.eligible:
        reasons.append("grader_not_eligible")
    if not request.model.active:
        reasons.append("model_config_inactive")
    if not request.model.evaluation_passed:
        reasons.append("model_evaluation_missing")
    if not request.model.retention_approved:
        reasons.append("provider_retention_not_approved")
    if not request.model.source_processing_approved:
        reasons.append("source_processing_not_approved")
    if request.model.environment != request.policy.required_environment:
        reasons.append("execution_environment_mismatch")
    if not request.prompt.active:
        reasons.append("prompt_inactive")
    if not request.prompt.evaluation_passed:
        reasons.append("prompt_evaluation_missing")
    if (
        request.policy.required_environment == "production"
        and not SHA256_PATTERN.fullmatch(request.prompt.content_sha256)
    ):
        reasons.append("prompt_content_hash_invalid")
    if (
        request.policy.required_environment == "production"
        and SHA256_PATTERN.fullmatch(request.prompt.content_sha256)
        and (
            not request.prompt.evaluation_corpus_id
            or not request.prompt.evaluation_corpus_version
            or not SHA256_PATTERN.fullmatch(request.prompt.evaluation_corpus_sha256)
            or not SHA256_PATTERN.fullmatch(request.prompt.evaluation_identity_sha256)
        )
    ):
        reasons.append("prompt_evaluation_identity_invalid")
    elif (
        request.policy.required_environment == "production"
        and SHA256_PATTERN.fullmatch(request.prompt.content_sha256)
        and evaluation_execution_identity_sha256(
            execution_role=f"grader:{request.grader.grader_id}",
            execution_contract_version=(request.grader.grader_contract_version),
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
        reasons.append("prompt_evaluation_identity_mismatch")
    if request.prompt.output_schema_version != request.grader.output_schema_version:
        reasons.append("output_schema_mismatch")
    if (
        request.price_card.provider != request.model.provider
        or request.price_card.model != request.model.model
        or request.price_card.currency != "USD"
        or request.price_card.effective_from > checked_at
        or request.price_card.verified_at > checked_at
        or any(
            rate < 0
            for rate in (
                request.price_card.input_per_million,
                request.price_card.cached_input_per_million,
                request.price_card.cache_write_per_million,
                request.price_card.output_per_million,
            )
        )
        or (
            request.policy.required_environment == "production"
            and request.price_card.effective_to is None
        )
        or (
            request.policy.required_environment == "production"
            and checked_at
            >= request.price_card.verified_at + PRODUCTION_PRICE_CARD_MAX_AGE
        )
        or (
            request.price_card.effective_to is not None
            and request.price_card.effective_to <= checked_at
        )
    ):
        reasons.append("price_card_invalid")
    if request.model.input_token_cap <= 0 or request.model.output_token_cap <= 0:
        reasons.append("token_cap_invalid")
    if request.policy.max_attempts != 2:
        reasons.append("retry_policy_invalid")
    return tuple(reasons)


def _evidence_passage_blocking_reasons(
    bundle: EvidenceBundle,
) -> tuple[str, ...]:
    reasons: list[str] = []
    for item in bundle.manifest:
        if item.item_kind != "passage":
            continue
        if not item.passage_id or not item.passage_hash or not item.passage_text:
            reasons.append("evidence_passage_content_unavailable")
            continue
        if hashlib.sha256(item.passage_text.encode()).hexdigest() != item.passage_hash:
            reasons.append("evidence_passage_hash_mismatch")
    return tuple(dict.fromkeys(reasons))


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
        usage.output_tokens,
        usage.reasoning_tokens,
        usage.total_tokens,
        usage.tool_call_count,
        usage.cache_write_tokens,
    )
    if any(value < 0 for value in counts):
        return "invalid_provider_usage"
    if usage.cached_input_tokens > usage.input_tokens:
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
    "BudgetLedger",
    "ExecutionPolicy",
    "GraderContract",
    "GraderExecution",
    "GraderExecutionError",
    "GraderExecutionRepository",
    "GraderExecutionRequest",
    "GraderExecutionWorkflow",
    "InMemoryBudgetLedger",
    "InMemoryGraderExecutionRepository",
    "ModelConfiguration",
    "ModelPriceCard",
    "PromptContract",
    "ProviderRequest",
    "ProviderResponse",
    "ProviderTransportError",
    "ProviderUsage",
]

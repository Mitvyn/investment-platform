from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import hashlib
from typing import Callable, Mapping, Protocol, cast, runtime_checkable

from investment_research_os.evidence_bundles import (
    EvidenceBundle,
    EvidenceBundleError,
    validate_evidence_source_url,
)
from investment_research_os.grader_executions import (
    GraderExecution,
    GraderExecutionError,
    GraderExecutionRequest,
    GraderProvider,
    ProviderRequest,
    ProviderTransportError,
    ProviderUsage,
    _actual_cost,
    _canonical_json,
    _evidence_passage_blocking_reasons,
    _inference_parameter_hash,
    _maximum_cost,
    _opinion_contract,
    _provider_usage_error,
    _pre_call_blocking_reasons,
    _terminal_execution,
    _validate_opinion,
    _validation_error_code,
    _without_reasoning_content,
)
from investment_research_os.grader_executions.runtime import (
    AttemptCompletion,
    AttemptStart,
    ExecutionFinalization,
    ExecutionStart,
    GraderExecutionLifecycle,
    RestartAction,
    RuntimeExecutionSnapshot,
    decide_restart,
)
from investment_research_os.ids import stable_id
from investment_research_os.provider_input_token_preflight import (
    InputTokenCountingProvider,
    PersistentInputTokenPreflightGate,
)
from investment_research_os.valuation_snapshots import ValuationSnapshot


class PersistentGraderExecutionError(RuntimeError):
    """Raised when persistent grader execution cannot continue safely."""


@runtime_checkable
class PersistentAttemptDriver(Protocol):
    def prepare_attempt(
        self,
        start: ExecutionStart,
        snapshot: RuntimeExecutionSnapshot,
        attempt_number: int,
    ) -> AttemptStart: ...

    def invoke_provider(self, start: AttemptStart) -> AttemptCompletion: ...


@runtime_checkable
class PersistentExecutionReadModel(Protocol):
    def reconstruct_terminal(
        self,
        start: ExecutionStart,
        snapshot: RuntimeExecutionSnapshot,
    ) -> GraderExecution: ...


@runtime_checkable
class PersistentExecutionContract(Protocol):
    def logical_input_contract(self) -> dict[str, object]: ...

    def validate_logical_input(
        self,
        logical_input: Mapping[str, object],
    ) -> None: ...


def persistent_grader_execution_identity(
    *,
    bundle: EvidenceBundle,
    request: GraderExecutionRequest,
    execution_contract: PersistentExecutionContract,
    valuation_snapshot: ValuationSnapshot | None = None,
) -> str:
    payload = {
        **_grader_identity_payload(
            bundle=bundle,
            request=request,
            valuation_snapshot=valuation_snapshot,
        ),
        "execution_contract": execution_contract.logical_input_contract(),
    }
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()


def _grader_identity_payload(
    *,
    bundle: EvidenceBundle,
    request: GraderExecutionRequest,
    valuation_snapshot: ValuationSnapshot | None,
) -> dict[str, object]:
    return {
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
        "prompt_input_schema_version": request.prompt.input_schema_version,
        "prompt_content_sha256": request.prompt.content_sha256,
        "evaluation_corpus_sha256": request.prompt.evaluation_corpus_sha256,
        "evaluation_corpus_id": request.prompt.evaluation_corpus_id,
        "evaluation_corpus_version": request.prompt.evaluation_corpus_version,
        "evaluation_identity_sha256": request.prompt.evaluation_identity_sha256,
        "model_config_version": request.model.config_version,
        "provider": request.model.provider,
        "model": request.model.model,
        "reasoning_effort": request.model.reasoning_effort,
        "thinking_enabled": request.model.thinking_enabled,
        "temperature": request.model.temperature,
        "input_token_cap": request.model.input_token_cap,
        "output_token_cap": request.model.output_token_cap,
    }


def build_persistent_grader_execution_start(
    *,
    operator_id: str,
    bundle: EvidenceBundle,
    request: GraderExecutionRequest,
    execution_contract: PersistentExecutionContract,
    budget_id: str,
    budget_snapshot: Mapping[str, object],
    started_at: datetime,
    valuation_snapshot: ValuationSnapshot | None = None,
) -> ExecutionStart:
    bundle_sources_approved = True
    try:
        for item in bundle.manifest:
            validate_evidence_source_url(item.canonical_url)
    except EvidenceBundleError:
        bundle_sources_approved = False
    blocking_reasons = tuple(
        dict.fromkeys(
            (
                *_pre_call_blocking_reasons(
                    bundle.grader_ready,
                    bundle_sources_approved,
                    request,
                    started_at,
                ),
                *_evidence_passage_blocking_reasons(bundle),
            )
        )
    )
    if blocking_reasons:
        raise PersistentGraderExecutionError(
            "grader_pre_call_gate_blocked:" + ",".join(blocking_reasons)
        )
    execution_identity = persistent_grader_execution_identity(
        bundle=bundle,
        request=request,
        execution_contract=execution_contract,
        valuation_snapshot=valuation_snapshot,
    )
    draft = GraderExecution(
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
        execution_state="accepted",
        attempts=(),
        opinion=None,
        blocking_reasons=(),
        policy_version=request.policy.policy_version,
        retry_policy_version=request.policy.retry_policy_version,
        created_at=started_at,
        request=request,
    )
    canonical = draft.as_dict()
    canonical["execution_state"] = None
    return ExecutionStart.from_payload(
        operator_id,
        {
            "id": draft.execution_id,
            "research_run_id": bundle.research_run_id,
            "security_id": bundle.security_id,
            "evidence_bundle_id": bundle.id,
            "evidence_bundle_hash": bundle.content_hash,
            "execution_key": execution_identity,
            "question_type_id": request.question_type_id,
            "question_type_version": request.question_type_version,
            "workflow_config_version": request.workflow_config_version,
            "thesis_contract_id": request.question_type_id,
            "grader_id": request.grader.grader_id,
            "grader_version": request.grader.grader_version,
            "grader_contract_version": (request.grader.grader_contract_version),
            "eligibility_rule_version": (request.grader.eligibility_rule_version),
            "rubric_version": request.grader.rubric_version,
            "output_schema_version": request.grader.output_schema_version,
            "abstention_rules_version": (request.grader.abstention_rule_version),
            "prompt_version": request.prompt.prompt_version,
            "model_config_id": request.model.config_id,
            "price_card_id": request.price_card.price_card_id,
            "budget_id": budget_id,
            "provider": request.model.provider,
            "model": request.model.model,
            "inference_parameter_hash": _inference_parameter_hash(request.model),
            "retry_policy_version": request.policy.retry_policy_version,
            "max_attempts": request.policy.max_attempts,
            "required": request.grader.required,
            "pre_call_gate": canonical["pre_call_gate"],
            "budget_snapshot": dict(budget_snapshot),
            "started_at": started_at.isoformat(),
            "canonical_execution": canonical,
        },
    )


class DomainPersistentAttemptDriver:
    """Build and validate one isolated grader call against frozen domain inputs."""

    def __init__(
        self,
        *,
        operator_id: str,
        bundle: EvidenceBundle,
        request: GraderExecutionRequest,
        execution_contract: PersistentExecutionContract,
        provider: GraderProvider,
        input_token_preflight_gate: PersistentInputTokenPreflightGate | None = None,
        clock: Callable[[], datetime],
        valuation_snapshot: ValuationSnapshot | None = None,
    ) -> None:
        if bundle.operator_id != operator_id or bundle.id != request.evidence_bundle_id:
            raise PersistentGraderExecutionError("grader execution input mismatch")
        if valuation_snapshot is not None and (
            valuation_snapshot.operator_id != operator_id
            or valuation_snapshot.evidence_bundle_id != bundle.id
            or valuation_snapshot.evidence_bundle_hash != bundle.content_hash
            or valuation_snapshot.security_id != bundle.security_id
        ):
            raise PersistentGraderExecutionError("valuation snapshot evidence mismatch")
        self._operator_id = operator_id
        self._bundle = bundle
        self._request = request
        self._execution_contract = execution_contract
        self._provider = provider
        self._input_token_preflight_gate = input_token_preflight_gate
        self._clock = clock
        self._valuation_snapshot = valuation_snapshot
        self._provider_requests: dict[str, ProviderRequest] = {}

    def prepare_attempt(
        self,
        start: ExecutionStart,
        snapshot: RuntimeExecutionSnapshot,
        attempt_number: int,
    ) -> AttemptStart:
        self._validate_start(start, snapshot, attempt_number)
        logical_input = self._logical_input()
        self._execution_contract.validate_logical_input(logical_input)
        request_hash = hashlib.sha256(
            _canonical_json(logical_input).encode()
        ).hexdigest()
        previous_result = (
            None if not snapshot.attempts else snapshot.attempts[-1].result
        )
        provider_request = ProviderRequest(
            execution_identity=start.execution_key,
            request_hash=request_hash,
            provider=self._request.model.provider,
            model=self._request.model.model,
            logical_input=logical_input,
            reasoning_effort=self._request.model.reasoning_effort,
            thinking_enabled=self._request.model.thinking_enabled,
            temperature=self._request.model.temperature,
            input_token_cap=self._request.model.input_token_cap,
            output_token_cap=self._request.model.output_token_cap,
            execution_role=f"grader:{self._request.grader.grader_id}",
            prompt_id=self._request.prompt.prompt_id,
            prompt_version=self._request.prompt.prompt_version,
            prompt_content_sha256=self._request.prompt.content_sha256,
            input_schema_version=self._request.prompt.input_schema_version,
            output_schema_version=self._request.prompt.output_schema_version,
            attempt_number=attempt_number,
            validation_errors=(() if previous_result is None else (previous_result,)),
        )
        sanitized_request = _without_reasoning_content(
            self._provider.audit_request(provider_request)
        )
        if not isinstance(sanitized_request, Mapping):
            raise PersistentGraderExecutionError(
                "provider audit request is not an object"
            )
        attempt_id = stable_id(
            self._operator_id,
            "grader-attempt",
            f"{start.execution_key}:{attempt_number}",
        )
        attempt = AttemptStart.create(
            operator_id=self._operator_id,
            execution_id=start.execution_id,
            attempt_id=attempt_id,
            attempt_number=attempt_number,
            request_sha256=request_hash,
            provider=self._request.model.provider,
            model=self._request.model.model,
            model_config_id=self._request.model.config_id,
            prompt_version=self._request.prompt.prompt_version,
            started_at=self._clock(),
            raw_payload_id=stable_id(
                self._operator_id,
                "grader-raw-payload",
                attempt_id,
            ),
            price_card_id=self._request.price_card.price_card_id,
            reserved_cost_usd=_maximum_cost(
                self._request.model,
                self._request.price_card,
            ),
            retry_reason=previous_result,
            sanitized_request=sanitized_request,
            reservation_id=stable_id(
                self._operator_id,
                "grader-budget-reservation",
                attempt_id,
            ),
            budget_id=str(start.storage_payload()["budget_id"]),
            reserved_tokens=(
                self._request.model.input_token_cap
                + self._request.model.output_token_cap
            ),
        )
        self._provider_requests[attempt.attempt_id] = provider_request
        return attempt

    def invoke_provider(self, start: AttemptStart) -> AttemptCompletion:
        provider_request = self._provider_requests.pop(start.attempt_id, None)
        if provider_request is None:
            raise PersistentGraderExecutionError("persistent attempt was not prepared")
        try:
            if self._input_token_preflight_gate is not None:
                self._input_token_preflight_gate.authorize(
                    operator_id=self._operator_id,
                    research_run_id=self._bundle.research_run_id,
                    attempt_kind="grader",
                    attempt_id=start.attempt_id,
                    request=provider_request,
                    provider=cast(InputTokenCountingProvider, self._provider),
                )
            response = self._provider.execute(provider_request)
        except ProviderTransportError as error:
            return self._completion(
                start,
                result="transport_error",
                provider_request_id=None,
                sanitized_response=None,
                validated_opinion=None,
                retry_reason=(
                    error.code if error.retryable else f"nonretryable:{error.code}"
                ),
            )
        usage_error = _provider_usage_error(response.usage)
        if usage_error is not None:
            raise PersistentGraderExecutionError(
                "invalid provider usage cannot be settled safely"
            )
        safe_response = _without_reasoning_content(
            response.raw_provider_response or response.raw_output
        )
        if not isinstance(safe_response, Mapping):
            raise PersistentGraderExecutionError("provider response is not an object")
        error_code: str | None = None
        opinion = None
        if response.resolved_model != self._request.model.model:
            error_code = "provider_model_mismatch"
        else:
            try:
                opinion = _validate_opinion(
                    self._operator_id,
                    provider_request.execution_identity,
                    self._request,
                    response.raw_output,
                    {item.evidence_id for item in self._bundle.manifest},
                    self._allowed_calculation_ids(),
                )
            except GraderExecutionError as error:
                error_code = _validation_error_code(error)
        actual_cost = _actual_cost(response.usage, self._request.price_card)
        if error_code is not None:
            return self._completion(
                start,
                result="validation_error",
                provider_request_id=response.provider_request_id,
                sanitized_response=safe_response,
                validated_opinion=None,
                retry_reason=error_code,
                usage=response.usage,
                actual_cost=actual_cost,
                validation_errors=(error_code,),
            )
        if opinion is None:
            raise PersistentGraderExecutionError("validated opinion is unavailable")
        provisional = _terminal_execution(
            self._operator_id,
            self._bundle,
            self._request,
            provider_request.execution_identity,
            opinion.execution_state,
            (),
            opinion,
            (),
            self._clock(),
        )
        canonical_opinion = _opinion_contract(provisional, opinion)
        if canonical_opinion["execution_id"] != start.execution_id:
            raise PersistentGraderExecutionError("execution identity mismatch")
        return self._completion(
            start,
            result=opinion.execution_state,
            provider_request_id=response.provider_request_id,
            sanitized_response=safe_response,
            validated_opinion=canonical_opinion,
            retry_reason=start.retry_reason,
            usage=response.usage,
            actual_cost=actual_cost,
        )

    def _completion(
        self,
        start: AttemptStart,
        *,
        result: str,
        provider_request_id: str | None,
        sanitized_response: Mapping[str, object] | None,
        validated_opinion: Mapping[str, object] | None,
        retry_reason: str | None,
        usage: ProviderUsage | None = None,
        actual_cost: Decimal = Decimal("0"),
        validation_errors: tuple[str, ...] = (),
    ) -> AttemptCompletion:
        finished_at = self._clock()
        if usage is None:
            usage = ProviderUsage(0, 0, 0, 0, 0)
        is_transport = result == "transport_error"
        is_validated = result in {"accepted", "abstained"}
        return AttemptCompletion.create(
            operator_id=self._operator_id,
            execution_id=start.execution_id,
            attempt_id=start.attempt_id,
            attempt_number=start.attempt_number,
            reservation_id=start.reservation_id,
            result=result,
            finished_at=finished_at,
            duration_ms=max(
                0,
                int((finished_at - start.started_at).total_seconds() * 1000),
            ),
            provider_request_id=provider_request_id,
            raw_payload_id=start.raw_payload_id,
            input_tokens=usage.input_tokens,
            cached_input_tokens=usage.cached_input_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            output_tokens=usage.output_tokens,
            reasoning_tokens=usage.reasoning_tokens,
            tool_call_count=usage.tool_call_count,
            estimated_cost_usd=actual_cost,
            billed_cost_usd=None,
            usage_complete=usage.usage_complete,
            validation_status=(
                "not_run" if is_transport else ("passed" if is_validated else "failed")
            ),
            schema_valid=None if is_transport else is_validated,
            citations_valid=None if is_transport else is_validated,
            validation_errors=validation_errors,
            retry_reason=retry_reason,
            reservation_state="released" if is_transport else "reconciled",
            actual_cost_usd=actual_cost,
            sanitized_request=start.sanitized_request,
            sanitized_response=sanitized_response,
            validated_opinion=validated_opinion,
        )

    def _validate_start(
        self,
        start: ExecutionStart,
        snapshot: RuntimeExecutionSnapshot,
        attempt_number: int,
    ) -> None:
        payload = start.storage_payload()
        if (
            start.operator_id != self._operator_id
            or payload["research_run_id"] != self._bundle.research_run_id
            or payload["security_id"] != self._bundle.security_id
            or payload["evidence_bundle_id"] != self._bundle.id
            or payload["evidence_bundle_hash"] != self._bundle.content_hash
            or payload["grader_id"] != self._request.grader.grader_id
            or payload["prompt_version"] != self._request.prompt.prompt_version
            or payload["model_config_id"] != self._request.model.config_id
            or attempt_number != len(snapshot.attempts) + 1
        ):
            raise PersistentGraderExecutionError("grader execution start mismatch")

    def _allowed_calculation_ids(self) -> set[str]:
        allowed = {item.snapshot_id for item in self._bundle.metrics}
        if self._valuation_snapshot is not None:
            allowed.update(self._valuation_snapshot.calculation_ids)
        return allowed

    def _logical_input(self) -> dict[str, object]:
        return {
            "bundle": self._bundle.as_dict(),
            "evidence_passages": [
                {
                    "evidence_id": item.evidence_id,
                    "evidence_version_id": item.evidence_version_id,
                    "passage_id": item.passage_id,
                    "source_locator": item.source_locator,
                    "passage_sha256": item.passage_hash,
                    "passage_text": item.passage_text,
                }
                for item in self._bundle.manifest
                if item.item_kind == "passage"
            ],
            "valuation_snapshot": (
                None
                if self._valuation_snapshot is None
                else self._valuation_snapshot.as_dict()
            ),
            "question_type_id": self._request.question_type_id,
            "question_type_version": self._request.question_type_version,
            "workflow_config_version": self._request.workflow_config_version,
            "proposition_id": self._request.proposition_id,
            "proposition_version": self._request.proposition_version,
            "rendered_proposition": self._request.rendered_proposition,
            "grader": _grader_identity_payload(
                bundle=self._bundle,
                request=self._request,
                valuation_snapshot=self._valuation_snapshot,
            ),
            "execution_contract": (self._execution_contract.logical_input_contract()),
        }


class PersistentGraderExecutionWorkflow:
    def __init__(
        self,
        *,
        lifecycle: GraderExecutionLifecycle,
        attempt_driver: PersistentAttemptDriver,
        read_model: PersistentExecutionReadModel,
    ) -> None:
        self._lifecycle = lifecycle
        self._attempt_driver = attempt_driver
        self._read_model = read_model

    def execute(self, start: ExecutionStart) -> GraderExecution:
        snapshot = self._lifecycle.load(start.operator_id, start.execution_key)
        if snapshot is None:
            snapshot = self._lifecycle.begin_execution(start)
        decision = decide_restart(snapshot)
        if decision.action is RestartAction.MANUAL_RECOVERY:
            raise PersistentGraderExecutionError(decision.reason_code)
        if decision.action in {RestartAction.REUSE, RestartAction.FINALIZE}:
            return self._reuse_or_finalize(start, snapshot, decision.action)

        attempt_number = len(snapshot.attempts) + 1
        attempt = self._attempt_driver.prepare_attempt(
            start,
            snapshot,
            attempt_number,
        )
        begun = self._lifecycle.begin_attempt(attempt)
        if (
            begun.persistence_state != "draft"
            or not begun.attempts
            or begun.attempts[-1].attempt_id != attempt.attempt_id
            or begun.attempts[-1].persistence_state != "draft"
        ):
            raise PersistentGraderExecutionError("attempt_start_not_persisted")
        completion = self._attempt_driver.invoke_provider(attempt)
        finished = self._lifecycle.finish_attempt(completion)
        decision = decide_restart(finished)
        if decision.action is RestartAction.CONTINUE:
            return self.execute(start)
        if decision.action is not RestartAction.FINALIZE:
            raise PersistentGraderExecutionError("attempt_finish_not_terminal")
        return self._reuse_or_finalize(start, finished, decision.action)

    def _reuse_or_finalize(
        self,
        start: ExecutionStart,
        snapshot: RuntimeExecutionSnapshot,
        action: RestartAction,
    ) -> GraderExecution:
        terminal = self._read_model.reconstruct_terminal(start, snapshot)
        self._validate_terminal(start, snapshot, terminal)
        if action is RestartAction.REUSE:
            return terminal
        finalized = self._lifecycle.finalize_execution(
            ExecutionFinalization.from_canonical(
                start.operator_id,
                terminal.as_dict(),
            )
        )
        if finalized.persistence_state != "complete":
            raise PersistentGraderExecutionError("execution_finalization_not_persisted")
        return terminal

    @staticmethod
    def _validate_terminal(
        start: ExecutionStart,
        snapshot: RuntimeExecutionSnapshot,
        terminal: GraderExecution,
    ) -> None:
        if (
            terminal.operator_id != start.operator_id
            or terminal.execution_id != start.execution_id
            or terminal.execution_identity != start.execution_key
            or terminal.execution_state
            not in {"not_executed", "failed", "abstained", "accepted"}
        ):
            raise PersistentGraderExecutionError(
                "reconstructed_terminal_execution_mismatch"
            )
        canonical = terminal.as_dict()
        if (
            snapshot.persistence_state == "complete"
            and canonical != snapshot.canonical_execution
        ):
            raise PersistentGraderExecutionError(
                "reconstructed_terminal_execution_mismatch"
            )
        if not snapshot.attempts:
            return
        latest = snapshot.attempts[-1]
        opinion = canonical.get("opinion")
        if latest.result in {"accepted", "abstained"}:
            if (
                terminal.execution_state != latest.result
                or not isinstance(opinion, dict)
                or opinion.get("opinion_id") != latest.opinion_id
            ):
                raise PersistentGraderExecutionError(
                    "reconstructed_terminal_execution_mismatch"
                )
        elif latest.attempt_number == 2 and (
            terminal.execution_state != "failed" or opinion is not None
        ):
            raise PersistentGraderExecutionError(
                "reconstructed_terminal_execution_mismatch"
            )


__all__ = [
    "DomainPersistentAttemptDriver",
    "PersistentAttemptDriver",
    "PersistentExecutionReadModel",
    "PersistentGraderExecutionError",
    "PersistentGraderExecutionWorkflow",
]

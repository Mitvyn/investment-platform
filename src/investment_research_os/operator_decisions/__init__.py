from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Callable

from investment_research_os.ids import stable_id
from investment_research_os.readiness_and_theses import (
    InMemoryReadinessAndThesisRepository,
    ReadinessGateResult,
    ThesisVersion,
)
from investment_research_os.research_runs import AuthenticatedOperator


class OperatorDecisionError(ValueError):
    """Raised when an operator event or guarded side effect is invalid."""


ACTIONS = {
    "dismiss",
    "monitor",
    "request_deep_research",
    "mark_for_future_portfolio_review",
    "no_action",
}


@dataclass(frozen=True, slots=True)
class OperatorDecisionRequest:
    thesis_version_id: str
    operator_action: str
    rationale: str
    supersedes_operator_decision_id: str | None
    idempotency_key: str
    decision_policy_version: str


@dataclass(frozen=True, slots=True)
class OperatorDecisionEvent:
    operator_decision_id: str
    operator_id: str
    security_id: str
    thesis_contract_id: str
    thesis_version_id: str
    committee_result_id: str
    readiness_gate_result_id: str
    system_disposition: str
    operator_action: str
    relationship: str
    rationale: str
    supersedes_operator_decision_id: str | None
    decision_policy_version: str
    idempotency_key: str
    created_at: datetime

    @property
    def ownership_key(self) -> tuple[str, str, str]:
        return self.operator_id, self.security_id, self.thesis_contract_id

    def as_dict(self) -> dict[str, object]:
        return {
            "contract_version": "operator_decision_event.v1",
            "operator_decision_id": self.operator_decision_id,
            "operator_id": self.operator_id,
            "security_id": self.security_id,
            "thesis_contract_id": self.thesis_contract_id,
            "thesis_version_id": self.thesis_version_id,
            "committee_result_id": self.committee_result_id,
            "readiness_gate_result_id": self.readiness_gate_result_id,
            "system_disposition": self.system_disposition,
            "operator_action": self.operator_action,
            "relationship": self.relationship,
            "rationale": self.rationale,
            "supersedes_operator_decision_id": (
                self.supersedes_operator_decision_id
            ),
            "decision_policy_version": self.decision_policy_version,
            "idempotency_key": self.idempotency_key,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class OperatorWorkflowCommand:
    workflow_command_id: str
    operator_id: str
    operator_decision_id: str
    security_id: str
    thesis_contract_id: str
    thesis_version_id: str
    committee_result_id: str
    readiness_gate_result_id: str
    command_type: str
    command_policy_version: str
    idempotency_key: str
    command_state: str
    created_at: datetime

    def as_dict(self) -> dict[str, object]:
        return {
            "contract_version": "operator_workflow_command.v1",
            "workflow_command_id": self.workflow_command_id,
            "operator_id": self.operator_id,
            "operator_decision_id": self.operator_decision_id,
            "security_id": self.security_id,
            "thesis_contract_id": self.thesis_contract_id,
            "thesis_version_id": self.thesis_version_id,
            "committee_result_id": self.committee_result_id,
            "readiness_gate_result_id": self.readiness_gate_result_id,
            "command_type": self.command_type,
            "command_policy_version": self.command_policy_version,
            "idempotency_key": self.idempotency_key,
            "command_state": self.command_state,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class PortfolioReviewHandoffMarker:
    portfolio_review_handoff_marker_id: str
    operator_id: str
    operator_decision_id: str
    security_id: str
    thesis_contract_id: str
    thesis_version_id: str
    committee_result_id: str
    readiness_gate_result_id: str
    thesis_status: str
    final_system_disposition: str
    readiness_status: str
    handoff_policy_version: str
    idempotency_key: str
    created_at: datetime

    def as_dict(self) -> dict[str, object]:
        return {
            "contract_version": "portfolio_review_handoff_marker.v1",
            "portfolio_review_handoff_marker_id": (
                self.portfolio_review_handoff_marker_id
            ),
            "operator_id": self.operator_id,
            "operator_decision_id": self.operator_decision_id,
            "security_id": self.security_id,
            "thesis_contract_id": self.thesis_contract_id,
            "thesis_version_id": self.thesis_version_id,
            "committee_result_id": self.committee_result_id,
            "readiness_gate_result_id": self.readiness_gate_result_id,
            "thesis_status": self.thesis_status,
            "final_system_disposition": self.final_system_disposition,
            "readiness_status": self.readiness_status,
            "handoff_policy_version": self.handoff_policy_version,
            "idempotency_key": self.idempotency_key,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class OperatorDecisionOutcome:
    event: OperatorDecisionEvent
    workflow_command: OperatorWorkflowCommand | None
    portfolio_handoff_marker: PortfolioReviewHandoffMarker | None


@dataclass(frozen=True, slots=True)
class OperatorDecisionHistory:
    operator_id: str
    security_id: str
    thesis_contract_id: str
    events: tuple[OperatorDecisionEvent, ...]
    generated_at: datetime

    def as_dict(self) -> dict[str, object]:
        return {
            "contract_version": "operator_decision_history.v1",
            "operator_id": self.operator_id,
            "security_id": self.security_id,
            "thesis_contract_id": self.thesis_contract_id,
            "events": [item.as_dict() for item in self.events],
            "generated_at": self.generated_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class OperatorDecisionCurrentState:
    operator_id: str
    security_id: str
    thesis_contract_id: str
    current_operator_decision_id: str | None
    current_operator_action: str | None
    current_relationship: str | None
    supersession_depth: int
    derived_at: datetime

    def as_dict(self) -> dict[str, object]:
        return {
            "contract_version": "operator_decision_current_state.v1",
            "operator_id": self.operator_id,
            "security_id": self.security_id,
            "thesis_contract_id": self.thesis_contract_id,
            "current_operator_decision_id": self.current_operator_decision_id,
            "current_operator_action": self.current_operator_action,
            "current_relationship": self.current_relationship,
            "supersession_depth": self.supersession_depth,
            "derived_at": self.derived_at.isoformat(),
        }


def derive_operator_decision_relationship(
    system_disposition: str,
    operator_action: str,
) -> str:
    if operator_action == "no_action":
        return "defer"
    accepted = {
        "reject": "dismiss",
        "monitor": "monitor",
        "deep_research": "request_deep_research",
        "decision_ready": "mark_for_future_portfolio_review",
    }
    return "accept" if accepted.get(system_disposition) == operator_action else "override"


class InMemoryOperatorDecisionRepository:
    def __init__(self) -> None:
        self._outcomes: dict[tuple[str, str], OperatorDecisionOutcome] = {}
        self._request_hashes: dict[tuple[str, str], str] = {}
        self._events_by_id: dict[tuple[str, str], OperatorDecisionEvent] = {}
        self._history: dict[
            tuple[str, str, str], tuple[OperatorDecisionEvent, ...]
        ] = {}

    def get_replay(
        self,
        operator_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> OperatorDecisionOutcome | None:
        key = (operator_id, idempotency_key)
        existing_hash = self._request_hashes.get(key)
        if existing_hash is not None and existing_hash != request_hash:
            raise OperatorDecisionError("idempotency key payload conflict")
        return self._outcomes.get(key)

    def save(
        self,
        outcome: OperatorDecisionOutcome,
        request_hash: str,
    ) -> OperatorDecisionOutcome:
        event = outcome.event
        replay = self.get_replay(
            event.operator_id,
            event.idempotency_key,
            request_hash,
        )
        if replay is not None:
            if replay != outcome:
                raise OperatorDecisionError("conflicting immutable decision")
            return replay
        history = self._history.get(event.ownership_key, ())
        current = history[-1] if history else None
        if event.supersedes_operator_decision_id is None:
            if current is not None:
                raise OperatorDecisionError(
                    "new decision must supersede current decision"
                )
        elif (
            current is None
            or event.supersedes_operator_decision_id
            != current.operator_decision_id
        ):
            raise OperatorDecisionError("invalid decision supersession")
        self._history[event.ownership_key] = (*history, event)
        self._events_by_id[(event.operator_id, event.operator_decision_id)] = event
        key = (event.operator_id, event.idempotency_key)
        self._request_hashes[key] = request_hash
        self._outcomes[key] = outcome
        return outcome

    def history(
        self,
        operator_id: str,
        security_id: str,
        thesis_contract_id: str,
    ) -> tuple[OperatorDecisionEvent, ...]:
        return self._history.get(
            (operator_id, security_id, thesis_contract_id),
            (),
        )

    def current(
        self,
        operator_id: str,
        security_id: str,
        thesis_contract_id: str,
    ) -> OperatorDecisionEvent | None:
        history = self.history(operator_id, security_id, thesis_contract_id)
        return history[-1] if history else None

    def commands_for_event(
        self,
        operator_decision_id: str,
    ) -> tuple[OperatorWorkflowCommand, ...]:
        return tuple(
            outcome.workflow_command
            for outcome in self._outcomes.values()
            if outcome.event.operator_decision_id == operator_decision_id
            and outcome.workflow_command is not None
        )

    def public_history(
        self,
        operator_id: str,
        security_id: str,
        thesis_contract_id: str,
        generated_at: datetime,
    ) -> OperatorDecisionHistory:
        return OperatorDecisionHistory(
            operator_id=operator_id,
            security_id=security_id,
            thesis_contract_id=thesis_contract_id,
            events=self.history(operator_id, security_id, thesis_contract_id),
            generated_at=generated_at,
        )

    def current_state(
        self,
        operator_id: str,
        security_id: str,
        thesis_contract_id: str,
        derived_at: datetime,
    ) -> OperatorDecisionCurrentState:
        history = self.history(operator_id, security_id, thesis_contract_id)
        current = history[-1] if history else None
        return OperatorDecisionCurrentState(
            operator_id=operator_id,
            security_id=security_id,
            thesis_contract_id=thesis_contract_id,
            current_operator_decision_id=(
                current.operator_decision_id if current else None
            ),
            current_operator_action=(current.operator_action if current else None),
            current_relationship=(current.relationship if current else None),
            supersession_depth=max(0, len(history) - 1),
            derived_at=derived_at,
        )


class OperatorDecisionWorkflow:
    def __init__(
        self,
        *,
        readiness_repository: InMemoryReadinessAndThesisRepository,
        repository: InMemoryOperatorDecisionRepository,
        clock: Callable[[], datetime],
    ) -> None:
        self._readiness_repository = readiness_repository
        self._repository = repository
        self._clock = clock

    def execute(
        self,
        operator: AuthenticatedOperator,
        request: OperatorDecisionRequest,
    ) -> OperatorDecisionOutcome:
        if request.decision_policy_version != "operator_decision_policy.v1":
            raise OperatorDecisionError("unsupported decision policy")
        if request.operator_action not in ACTIONS:
            raise OperatorDecisionError("unsupported operator action")
        if not request.idempotency_key:
            raise OperatorDecisionError("idempotency key required")
        request_hash = _request_hash(request)
        replay = self._repository.get_replay(
            operator.id,
            request.idempotency_key,
            request_hash,
        )
        if replay is not None:
            return replay
        thesis = self._readiness_repository.get_thesis_by_id(
            operator.id,
            request.thesis_version_id,
        )
        if thesis is None:
            raise OperatorDecisionError("thesis version not found")
        readiness = self._readiness_repository.get_readiness_by_id(
            operator.id,
            thesis.readiness_gate_result_id,
        )
        if readiness is None:
            raise OperatorDecisionError("readiness result not found")
        relationship = derive_operator_decision_relationship(
            thesis.final_disposition,
            request.operator_action,
        )
        if relationship == "override" and not request.rationale.strip():
            raise OperatorDecisionError("override rationale required")
        if request.operator_action == "mark_for_future_portfolio_review":
            _validate_portfolio_handoff(thesis, readiness, relationship)
        created_at = self._clock()
        event_id = stable_id(
            operator.id,
            "operator-decision",
            request.idempotency_key,
        )
        event = OperatorDecisionEvent(
            operator_decision_id=event_id,
            operator_id=operator.id,
            security_id=thesis.security_id,
            thesis_contract_id=thesis.thesis_contract_id,
            thesis_version_id=thesis.thesis_version_id,
            committee_result_id=thesis.committee_result_id,
            readiness_gate_result_id=thesis.readiness_gate_result_id,
            system_disposition=thesis.final_disposition,
            operator_action=request.operator_action,
            relationship=relationship,
            rationale=request.rationale,
            supersedes_operator_decision_id=(
                request.supersedes_operator_decision_id
            ),
            decision_policy_version=request.decision_policy_version,
            idempotency_key=request.idempotency_key,
            created_at=created_at,
        )
        command = (
            _deep_research_command(event)
            if request.operator_action == "request_deep_research"
            else None
        )
        marker = (
            _portfolio_marker(event)
            if request.operator_action
            == "mark_for_future_portfolio_review"
            else None
        )
        return self._repository.save(
            OperatorDecisionOutcome(
                event=event,
                workflow_command=command,
                portfolio_handoff_marker=marker,
            ),
            request_hash,
        )


def _validate_portfolio_handoff(
    thesis: ThesisVersion,
    readiness: ReadinessGateResult,
    relationship: str,
) -> None:
    if not (
        thesis.thesis_status == "canonical"
        and thesis.final_disposition == "decision_ready"
        and readiness.final_disposition == "decision_ready"
        and readiness.readiness_status == "passed"
        and relationship == "accept"
    ):
        raise OperatorDecisionError(
            "portfolio handoff requires canonical decision ready thesis"
        )


def _deep_research_command(
    event: OperatorDecisionEvent,
) -> OperatorWorkflowCommand:
    return OperatorWorkflowCommand(
        workflow_command_id=stable_id(
            event.operator_id,
            "operator-workflow-command",
            event.operator_decision_id,
        ),
        operator_id=event.operator_id,
        operator_decision_id=event.operator_decision_id,
        security_id=event.security_id,
        thesis_contract_id=event.thesis_contract_id,
        thesis_version_id=event.thesis_version_id,
        committee_result_id=event.committee_result_id,
        readiness_gate_result_id=event.readiness_gate_result_id,
        command_type="create_research_request",
        command_policy_version="operator_workflow_command_policy.v1",
        idempotency_key=f"command:{event.idempotency_key}",
        command_state="pending",
        created_at=event.created_at,
    )


def _portfolio_marker(
    event: OperatorDecisionEvent,
) -> PortfolioReviewHandoffMarker:
    return PortfolioReviewHandoffMarker(
        portfolio_review_handoff_marker_id=stable_id(
            event.operator_id,
            "portfolio-review-handoff",
            event.operator_decision_id,
        ),
        operator_id=event.operator_id,
        operator_decision_id=event.operator_decision_id,
        security_id=event.security_id,
        thesis_contract_id=event.thesis_contract_id,
        thesis_version_id=event.thesis_version_id,
        committee_result_id=event.committee_result_id,
        readiness_gate_result_id=event.readiness_gate_result_id,
        thesis_status="canonical",
        final_system_disposition="decision_ready",
        readiness_status="passed",
        handoff_policy_version="portfolio_review_handoff_policy.v1",
        idempotency_key=f"handoff:{event.idempotency_key}",
        created_at=event.created_at,
    )


def _request_hash(request: OperatorDecisionRequest) -> str:
    payload = {
        "thesis_version_id": request.thesis_version_id,
        "operator_action": request.operator_action,
        "rationale": request.rationale,
        "supersedes_operator_decision_id": (
            request.supersedes_operator_decision_id
        ),
        "idempotency_key": request.idempotency_key,
        "decision_policy_version": request.decision_policy_version,
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


__all__ = [
    "InMemoryOperatorDecisionRepository",
    "OperatorDecisionCurrentState",
    "OperatorDecisionError",
    "OperatorDecisionEvent",
    "OperatorDecisionHistory",
    "OperatorDecisionOutcome",
    "OperatorDecisionRequest",
    "OperatorDecisionWorkflow",
    "OperatorWorkflowCommand",
    "PortfolioReviewHandoffMarker",
    "derive_operator_decision_relationship",
]

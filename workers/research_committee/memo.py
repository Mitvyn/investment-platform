from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from investment_research_os.committee_memos import (
    CommitteeMemoError,
    CommitteeMemoExecution,
    CommitteeMemoRepository,
    CommitteeMemoWorkflow,
)
from investment_research_os.research_committees import (
    ResearchCommitteeResult,
)
from investment_research_os.research_runs import (
    AuthenticatedOperator,
    ResearchRunRepository,
)
from investment_research_os.research_workflows import (
    BiotechResearchCommitteeConfig,
)
from investment_research_os.valuation_snapshots import (
    ValuationSnapshot,
    ValuationSnapshotRepository,
)

from .worker import PersistentCommitteeMemoArtifact


class ResearchCommitteeReadModel(Protocol):
    def get_for_run(
        self,
        operator_id: str,
        research_run_id: str,
    ) -> ResearchCommitteeResult | None: ...

    def get_by_id(
        self,
        operator_id: str,
        committee_id: str,
    ) -> ResearchCommitteeResult | None: ...


class PersistentCommitteeMemoWorkflowAdapter:
    """Executes synthesis only from exact persisted committee inputs."""

    def __init__(
        self,
        *,
        research_run_repository: ResearchRunRepository,
        committee_read_model: ResearchCommitteeReadModel,
        valuation_snapshot_repository: ValuationSnapshotRepository,
        config: BiotechResearchCommitteeConfig,
        workflow: CommitteeMemoWorkflow,
        memo_repository: CommitteeMemoRepository,
    ) -> None:
        self._research_runs = research_run_repository
        self._committees = committee_read_model
        self._valuations = valuation_snapshot_repository
        self._config = config
        self._workflow = workflow
        self._memos = memo_repository

    def execute(
        self,
        operator: AuthenticatedOperator,
        research_run_id: str,
    ) -> PersistentCommitteeMemoArtifact:
        run = self._research_runs.get(operator.id, research_run_id)
        if run is None:
            raise CommitteeMemoError("persisted research run not found")
        committee = self._committees.get_for_run(
            operator.id,
            research_run_id,
        )
        if committee is None:
            raise CommitteeMemoError(
                "persisted committee not found for research run"
            )
        valuation = self._valuations.get_for_run(
            operator.id,
            research_run_id,
        )
        if valuation is None:
            raise CommitteeMemoError(
                "persisted valuation snapshot not found for research run"
            )
        if not _input_identity_matches(
            operator,
            research_run_id,
            run,
            committee,
            valuation,
            self._config,
        ):
            raise CommitteeMemoError(
                "persistent memo input identity mismatch"
            )
        _validate_input_identifiers(run, committee, valuation)

        execution = self._workflow.execute(
            operator,
            self._config.synthesis_request(
                committee.committee_id,
                valuation.calculation_ids,
            ),
        )
        reloaded_committee = self._committees.get_by_id(
            operator.id,
            committee.committee_id,
        )
        if reloaded_committee != committee:
            raise CommitteeMemoError(
                "reloaded committee does not match run committee"
            )
        persisted = self._memos.get_for_committee(
            operator.id,
            committee.committee_id,
        )
        if persisted is None or persisted != execution:
            raise CommitteeMemoError(
                "reloaded committee memo execution does not match"
            )
        if execution.execution_state != "accepted" or execution.memo is None:
            raise CommitteeMemoError(
                "accepted persisted committee memo required"
            )
        _validate_execution_identifiers(execution)
        if not _execution_identity_matches(
            run,
            committee,
            valuation,
            execution,
            self._config,
        ):
            raise CommitteeMemoError(
                "persisted committee memo identity mismatch"
            )

        memo = execution.memo
        return PersistentCommitteeMemoArtifact(
            id=memo.memo_id,
            operator_id=run.operator_id,
            research_run_id=run.id,
            security_id=run.security_id,
            as_of_cutoff=run.as_of_cutoff,
            question_type_version=run.question_type_version,
            workflow_config_version=run.workflow_config_version,
            committee_id=committee.committee_id,
        )


def _input_identity_matches(
    operator: AuthenticatedOperator,
    research_run_id: str,
    run,
    committee: ResearchCommitteeResult,
    valuation: ValuationSnapshot,
    config: BiotechResearchCommitteeConfig,
) -> bool:
    return (
        run.id == research_run_id
        and run.operator_id == operator.id
        and isinstance(run.as_of_cutoff, datetime)
        and run.as_of_cutoff.tzinfo is not None
        and run.as_of_cutoff.utcoffset() is not None
        and run.question_type == config.question_type
        and run.question_type_version == config.question_type_version
        and run.workflow_config_version == config.workflow_config_version
        and committee.operator_id == run.operator_id
        and committee.research_run_id == run.id
        and committee.question_type_id == config.question_type
        and committee.question_type_version == config.question_type_version
        and committee.workflow_config_version
        == config.workflow_config_version
        and committee.proposition_id == config.proposition_id
        and committee.proposition_version == config.proposition_version
        and committee.rendered_proposition_text == config.proposition_text
        and valuation.operator_id == run.operator_id
        and valuation.research_run_id == run.id
        and valuation.security_id == run.security_id
        and valuation.as_of_cutoff == run.as_of_cutoff
        and valuation.evidence_bundle_id == committee.evidence_bundle_id
        and valuation.evidence_bundle_hash
        == committee.evidence_bundle_hash
    )


def _execution_identity_matches(
    run,
    committee: ResearchCommitteeResult,
    valuation: ValuationSnapshot,
    execution: CommitteeMemoExecution,
    config: BiotechResearchCommitteeConfig,
) -> bool:
    memo = execution.memo
    if memo is None:
        return False
    synthesizer = config.synthesizer
    return (
        execution.operator_id == run.operator_id
        and execution.committee_id == committee.committee_id
        and memo.synthesis_execution_id == execution.execution_id
        and memo.committee_id == committee.committee_id
        and memo.research_run_id == run.id
        and memo.evidence_bundle_id == valuation.evidence_bundle_id
        and memo.evidence_bundle_hash == valuation.evidence_bundle_hash
        and memo.workflow_config_version
        == config.workflow_config_version
        and memo.proposition_id == config.proposition_id
        and memo.proposition_version == config.proposition_version
        and memo.committee_status == committee.status
        and memo.prompt_version == synthesizer.prompt.prompt_version
        and memo.model_config_id == synthesizer.model.config_id
        and memo.provider == synthesizer.model.provider
        and memo.model == synthesizer.model.model
        and memo.price_card_version
        == synthesizer.price_card.price_card_id
        and memo.retry_policy_version
        == synthesizer.policy.retry_policy_version
        and memo.attempts == execution.attempts
        and memo.attempt_count == len(execution.attempts)
        and memo.created_at == execution.created_at
    )


def _validate_input_identifiers(
    run,
    committee: ResearchCommitteeResult,
    valuation: ValuationSnapshot,
) -> None:
    values = [
        run.id,
        run.operator_id,
        run.security_id,
        committee.committee_id,
        committee.evidence_bundle_id,
        valuation.id,
        valuation.evidence_bundle_id,
        *valuation.calculation_ids,
    ]
    _uuid_values(values, "persistent memo input identifier invalid")


def _validate_execution_identifiers(
    execution: CommitteeMemoExecution,
) -> None:
    memo = execution.memo
    if memo is None:
        raise CommitteeMemoError(
            "accepted persisted committee memo required"
        )
    values = [
        execution.execution_id,
        execution.operator_id,
        execution.committee_id,
        memo.memo_id,
        memo.synthesis_execution_id,
        memo.committee_id,
        memo.research_run_id,
        memo.evidence_bundle_id,
    ]
    _uuid_values(values, "persisted committee memo identifier invalid")


def _uuid_values(values: list[str], message: str) -> None:
    try:
        for value in values:
            UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise CommitteeMemoError(message) from error


__all__ = [
    "PersistentCommitteeMemoWorkflowAdapter",
    "ResearchCommitteeReadModel",
]

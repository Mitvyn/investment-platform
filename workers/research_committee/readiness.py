from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from investment_research_os.readiness_and_theses import (
    ReadinessAndThesisError,
    ReadinessAndThesisResult,
    ReadinessAndThesisWorkflow,
    ReadinessRequest,
)
from investment_research_os.research_committees import (
    ResearchCommitteeResult,
)
from investment_research_os.research_runs import (
    AuthenticatedOperator,
    PERSONAL_RESEARCH_QUESTION_TYPE_VERSION,
    PERSONAL_RESEARCH_THESIS_CONTRACT_ID,
    PERSONAL_RESEARCH_WORKFLOW_CONFIG_VERSION,
    QUESTION_TYPE_VERSION,
    ResearchRunRepository,
    THESIS_CONTRACT_ID,
    WORKFLOW_CONFIG_VERSION,
)

from .worker import PersistentReadinessThesisArtifact


READINESS_POLICY_VERSION = "biotech-readiness.v1"
PERSONAL_RESEARCH_READINESS_POLICY_VERSION = "biotech-personal-readiness.v1"
READINESS_POLICY_BY_WORKFLOW_IDENTITY = {
    (
        QUESTION_TYPE_VERSION,
        WORKFLOW_CONFIG_VERSION,
        THESIS_CONTRACT_ID,
    ): READINESS_POLICY_VERSION,
    (
        PERSONAL_RESEARCH_QUESTION_TYPE_VERSION,
        PERSONAL_RESEARCH_WORKFLOW_CONFIG_VERSION,
        PERSONAL_RESEARCH_THESIS_CONTRACT_ID,
    ): PERSONAL_RESEARCH_READINESS_POLICY_VERSION,
}


class PersistentResearchCommitteeReadModel(Protocol):
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


class PersistentReadinessThesisWorkflowAdapter:
    """Binds the worker boundary to exact persisted readiness state."""

    def __init__(
        self,
        *,
        research_run_repository: ResearchRunRepository,
        committee_read_model: PersistentResearchCommitteeReadModel,
        workflow: ReadinessAndThesisWorkflow,
    ) -> None:
        self._research_runs = research_run_repository
        self._committees = committee_read_model
        self._workflow = workflow

    def execute(
        self,
        operator: AuthenticatedOperator,
        research_run_id: str,
    ) -> PersistentReadinessThesisArtifact:
        run = self._research_runs.get(operator.id, research_run_id)
        if run is None:
            raise ReadinessAndThesisError("persisted research run not found")
        if (
            run.id != research_run_id
            or run.operator_id != operator.id
            or not isinstance(run.as_of_cutoff, datetime)
            or run.as_of_cutoff.tzinfo is None
            or run.as_of_cutoff.utcoffset() is None
        ):
            raise ReadinessAndThesisError("persisted readiness input identity mismatch")
        committee = self._committees.get_for_run(
            operator.id,
            research_run_id,
        )
        if committee is None:
            raise ReadinessAndThesisError(
                "persisted committee not found for research run"
            )
        if not _input_identity_matches(run, committee):
            raise ReadinessAndThesisError("persisted readiness input identity mismatch")
        gate_policy_version = READINESS_POLICY_BY_WORKFLOW_IDENTITY.get(
            (
                run.question_type_version,
                run.workflow_config_version,
                run.thesis_contract_id,
            )
        )
        if gate_policy_version is None:
            raise ReadinessAndThesisError("persisted readiness workflow unsupported")

        result = self._workflow.execute(
            operator,
            ReadinessRequest(
                committee_id=committee.committee_id,
                gate_policy_version=gate_policy_version,
            ),
        )
        reloaded_committee = self._committees.get_by_id(
            operator.id,
            committee.committee_id,
        )
        if reloaded_committee != committee:
            raise ReadinessAndThesisError(
                "reloaded committee does not match run committee"
            )

        _validate_link_identifiers(committee, result)
        if not _result_identity_matches(
            run,
            committee,
            result,
            gate_policy_version=gate_policy_version,
        ):
            raise ReadinessAndThesisError(
                "persisted readiness thesis identity mismatch"
            )

        readiness = result.readiness
        return PersistentReadinessThesisArtifact(
            id=result.thesis_creation.thesis_creation_result_id,
            operator_id=run.operator_id,
            research_run_id=run.id,
            security_id=run.security_id,
            as_of_cutoff=run.as_of_cutoff,
            question_type_version=run.question_type_version,
            workflow_config_version=run.workflow_config_version,
            committee_id=committee.committee_id,
            committee_memo_id=readiness.committee_memo_id,
            readiness_gate_result_id=readiness.readiness_gate_result_id,
        )


def _input_identity_matches(run, committee: ResearchCommitteeResult) -> bool:
    return (
        committee.operator_id == run.operator_id
        and committee.research_run_id == run.id
        and committee.question_type_id == run.question_type
        and committee.question_type_version == run.question_type_version
        and committee.workflow_config_version == run.workflow_config_version
    )


def _result_identity_matches(
    run,
    committee: ResearchCommitteeResult,
    result: ReadinessAndThesisResult,
    *,
    gate_policy_version: str,
) -> bool:
    readiness = result.readiness
    creation = result.thesis_creation
    shared_identity_matches = (
        readiness.operator_id == run.operator_id
        and readiness.research_run_id == run.id
        and readiness.security_id == run.security_id
        and readiness.thesis_contract_id == run.thesis_contract_id
        and readiness.committee_result_id == committee.committee_id
        and readiness.committee_status == committee.status
        and readiness.gate_policy_version == gate_policy_version
        and creation.operator_id == readiness.operator_id
        and creation.research_run_id == readiness.research_run_id
        and creation.security_id == readiness.security_id
        and creation.thesis_contract_id == readiness.thesis_contract_id
        and creation.committee_result_id == readiness.committee_result_id
        and creation.readiness_gate_result_id == readiness.readiness_gate_result_id
        and creation.committee_status == readiness.committee_status
    )
    if not shared_identity_matches:
        return False

    thesis = result.thesis
    if thesis is None:
        return (
            creation.creation_outcome == "no_thesis"
            and creation.thesis_version_id is None
        )
    return (
        creation.creation_outcome in {"canonical_created", "provisional_created"}
        and creation.thesis_version_id == thesis.thesis_version_id
        and thesis.operator_id == readiness.operator_id
        and thesis.research_run_id == readiness.research_run_id
        and thesis.security_id == readiness.security_id
        and thesis.thesis_contract_id == readiness.thesis_contract_id
        and thesis.question_type_version == run.question_type_version
        and thesis.workflow_config_version == run.workflow_config_version
        and thesis.committee_result_id == readiness.committee_result_id
        and thesis.committee_memo_id == readiness.committee_memo_id
        and thesis.committee_status == readiness.committee_status
        and thesis.readiness_gate_result_id == readiness.readiness_gate_result_id
    )


def _validate_link_identifiers(
    committee: ResearchCommitteeResult,
    result: ReadinessAndThesisResult,
) -> None:
    readiness = result.readiness
    creation = result.thesis_creation
    values = [
        committee.committee_id,
        creation.thesis_creation_result_id,
        readiness.committee_result_id,
        readiness.committee_memo_id,
        readiness.readiness_gate_result_id,
        creation.committee_result_id,
        creation.readiness_gate_result_id,
    ]
    if creation.thesis_version_id is not None:
        values.append(creation.thesis_version_id)
    if result.thesis is not None:
        values.extend(
            (
                result.thesis.thesis_version_id,
                result.thesis.committee_result_id,
                result.thesis.committee_memo_id,
                result.thesis.readiness_gate_result_id,
            )
        )
    try:
        for value in values:
            UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise ReadinessAndThesisError(
            "persisted readiness thesis identifier invalid"
        ) from error


__all__ = [
    "PERSONAL_RESEARCH_READINESS_POLICY_VERSION",
    "PersistentReadinessThesisWorkflowAdapter",
    "PersistentResearchCommitteeReadModel",
    "READINESS_POLICY_VERSION",
]

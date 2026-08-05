from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

from investment_research_os.readiness_and_theses import (
    InMemoryReadinessAndThesisRepository,
    ReadinessAndThesisError,
    ReadinessAndThesisWorkflow,
    ReadinessRequest,
)
from investment_research_os.research_runs import AuthenticatedOperator
from tests.test_readiness_and_thesis import (
    synthesized_fixture,
    synthesized_terminal_fixture,
)
from workers.research_committee.readiness import (
    PersistentReadinessThesisWorkflowAdapter,
)


class ResearchRunRepositoryFake:
    def __init__(self, run) -> None:
        self.run = run
        self.reads: list[tuple[str, str]] = []

    def get(self, operator_id: str, research_run_id: str):
        self.reads.append((operator_id, research_run_id))
        return self.run


class CommitteeReadModelFake:
    def __init__(self, committee, *, reloaded=None) -> None:
        self.committee = committee
        self.reloaded = committee if reloaded is None else reloaded
        self.run_reads: list[tuple[str, str]] = []
        self.id_reads: list[tuple[str, str]] = []

    def get_for_run(self, operator_id: str, research_run_id: str):
        self.run_reads.append((operator_id, research_run_id))
        return self.committee

    def get_by_id(self, operator_id: str, committee_id: str):
        self.id_reads.append((operator_id, committee_id))
        return self.reloaded


class WorkflowFake:
    def __init__(self, result) -> None:
        self.result = result
        self.calls: list[tuple[AuthenticatedOperator, ReadinessRequest]] = []

    def execute(
        self,
        operator: AuthenticatedOperator,
        request: ReadinessRequest,
    ):
        self.calls.append((operator, request))
        return self.result


def fixture(*, terminal_state: str | None = None):
    raw = (
        synthesized_fixture(requested_disposition="monitor")
        if terminal_state is None
        else synthesized_terminal_fixture(terminal_state=terminal_state)
    )
    (
        bundle,
        committee,
        bundle_repository,
        committee_repository,
        memo_repository,
        _,
    ) = raw
    result = ReadinessAndThesisWorkflow(
        committee_repository=committee_repository,
        evidence_bundle_repository=bundle_repository,
        memo_repository=memo_repository,
        repository=InMemoryReadinessAndThesisRepository(),
        clock=lambda: datetime(2026, 7, 22, 5, 0, tzinfo=UTC),
    ).execute(
        AuthenticatedOperator(bundle.operator_id),
        ReadinessRequest(
            committee_id=committee.committee_id,
            gate_policy_version="biotech-readiness.v1",
        ),
    )
    run = SimpleNamespace(
        id=bundle.research_run_id,
        operator_id=bundle.operator_id,
        security_id=bundle.security_id,
        question_type=committee.question_type_id,
        question_type_version=committee.question_type_version,
        workflow_config_version=committee.workflow_config_version,
        thesis_contract_id=committee.question_type_id,
        as_of_cutoff=bundle.as_of_cutoff,
    )
    return run, committee, result


def adapter(run, committee, result, *, reloaded=None):
    runs = ResearchRunRepositoryFake(run)
    committees = CommitteeReadModelFake(committee, reloaded=reloaded)
    workflow = WorkflowFake(result)
    return (
        PersistentReadinessThesisWorkflowAdapter(
            research_run_repository=runs,
            committee_read_model=committees,
            workflow=workflow,
        ),
        runs,
        committees,
        workflow,
    )


class PersistentReadinessThesisWorkflowAdapterTests(unittest.TestCase):
    def test_executes_exact_run_committee_and_returns_creation_artifact(
        self,
    ) -> None:
        run, committee, result = fixture()
        boundary, runs, committees, workflow = adapter(
            run,
            committee,
            result,
        )

        artifact = boundary.execute(
            AuthenticatedOperator(run.operator_id),
            run.id,
        )

        self.assertEqual(
            artifact.id,
            result.thesis_creation.thesis_creation_result_id,
        )
        self.assertEqual(artifact.operator_id, run.operator_id)
        self.assertEqual(artifact.research_run_id, run.id)
        self.assertEqual(artifact.security_id, run.security_id)
        self.assertEqual(artifact.as_of_cutoff, run.as_of_cutoff)
        self.assertEqual(
            artifact.question_type_version,
            run.question_type_version,
        )
        self.assertEqual(
            artifact.workflow_config_version,
            run.workflow_config_version,
        )
        self.assertEqual(artifact.committee_id, committee.committee_id)
        self.assertEqual(
            artifact.committee_memo_id,
            result.readiness.committee_memo_id,
        )
        self.assertEqual(
            artifact.readiness_gate_result_id,
            result.readiness.readiness_gate_result_id,
        )
        self.assertEqual(runs.reads, [(run.operator_id, run.id)])
        self.assertEqual(
            committees.run_reads,
            [(run.operator_id, run.id)],
        )
        self.assertEqual(
            committees.id_reads,
            [(run.operator_id, committee.committee_id)],
        )
        self.assertEqual(
            workflow.calls,
            [
                (
                    AuthenticatedOperator(run.operator_id),
                    ReadinessRequest(
                        committee_id=committee.committee_id,
                        gate_policy_version="biotech-readiness.v1",
                    ),
                )
            ],
        )

    def test_personal_research_run_selects_personal_readiness_policy(self) -> None:
        run, committee, result = fixture()
        personal_question_type = (
            "biotech_moonshot_catalyst_personal_research_assessment"
        )
        personal_question_version = f"{personal_question_type}.v1"
        personal_workflow = "biotech-moonshot-catalyst-personal-research-v1"
        personal_thesis_contract = (
            "biotech_moonshot_catalyst_personal_research_v1"
        )
        committee = replace(
            committee,
            question_type_id=personal_question_type,
            question_type_version=personal_question_version,
            workflow_config_version=personal_workflow,
        )
        personal_readiness = replace(
            result.readiness,
            thesis_contract_id=personal_thesis_contract,
            gate_policy_version="biotech-personal-readiness.v1",
        )
        personal_thesis = replace(
            result.thesis,
            thesis_contract_id=personal_thesis_contract,
            question_type_version=personal_question_version,
            workflow_config_version=personal_workflow,
            readiness_gate_policy_version="biotech-personal-readiness.v1",
        )
        personal_result = replace(
            result,
            readiness=personal_readiness,
            thesis_creation=replace(
                result.thesis_creation,
                thesis_contract_id=personal_thesis_contract,
            ),
            thesis=personal_thesis,
        )
        run = replace_namespace(
            run,
            question_type=personal_question_type,
            question_type_version=personal_question_version,
            workflow_config_version=personal_workflow,
            thesis_contract_id=personal_thesis_contract,
        )
        boundary, _, _, workflow = adapter(run, committee, personal_result)

        artifact = boundary.execute(
            AuthenticatedOperator(run.operator_id),
            run.id,
        )

        self.assertEqual(artifact.question_type_version, personal_question_version)
        self.assertEqual(
            workflow.calls[0][1].gate_policy_version,
            "biotech-personal-readiness.v1",
        )

    def test_rejects_cross_paired_personal_research_workflow(self) -> None:
        run, committee, result = fixture()
        personal_question_type = (
            "biotech_moonshot_catalyst_personal_research_assessment"
        )
        personal_question_version = f"{personal_question_type}.v1"
        personal_thesis_contract = (
            "biotech_moonshot_catalyst_personal_research_v1"
        )
        run = replace_namespace(
            run,
            question_type=personal_question_type,
            question_type_version=personal_question_version,
            thesis_contract_id=personal_thesis_contract,
        )
        committee = replace(
            committee,
            question_type_id=personal_question_type,
            question_type_version=personal_question_version,
        )
        boundary, _, _, workflow = adapter(run, committee, result)

        with self.assertRaisesRegex(
            ReadinessAndThesisError,
            "persisted readiness workflow unsupported",
        ):
            boundary.execute(
                AuthenticatedOperator(run.operator_id),
                run.id,
            )

        self.assertEqual(workflow.calls, [])

    def test_no_thesis_uses_creation_result_id_as_checkpoint_artifact(
        self,
    ) -> None:
        run, committee, result = fixture(terminal_state="failed")
        boundary, *_ = adapter(run, committee, result)

        artifact = boundary.execute(
            AuthenticatedOperator(run.operator_id),
            run.id,
        )

        self.assertEqual(result.thesis_creation.creation_outcome, "no_thesis")
        self.assertIsNone(result.thesis)
        self.assertEqual(
            artifact.id,
            result.thesis_creation.thesis_creation_result_id,
        )

    def test_rejects_missing_persisted_run_before_committee_lookup(self) -> None:
        run, committee, result = fixture()
        boundary, _, committees, workflow = adapter(
            None,
            committee,
            result,
        )

        with self.assertRaisesRegex(
            ReadinessAndThesisError,
            "persisted research run not found",
        ):
            boundary.execute(
                AuthenticatedOperator(run.operator_id),
                run.id,
            )

        self.assertEqual(committees.run_reads, [])
        self.assertEqual(workflow.calls, [])

    def test_rejects_missing_exact_run_committee_before_workflow(self) -> None:
        run, _, result = fixture()
        boundary, _, _, workflow = adapter(run, None, result)

        with self.assertRaisesRegex(
            ReadinessAndThesisError,
            "persisted committee not found for research run",
        ):
            boundary.execute(
                AuthenticatedOperator(run.operator_id),
                run.id,
            )

        self.assertEqual(workflow.calls, [])

    def test_rejects_drifted_run_or_committee_identity(self) -> None:
        run, committee, result = fixture()
        drifted_values = {
            "run owner": (
                replace_namespace(run, operator_id=other_uuid(run.operator_id)),
                committee,
            ),
            "run id": (
                replace_namespace(run, id=other_uuid(run.id)),
                committee,
            ),
            "committee run": (
                run,
                replace(committee, research_run_id=other_uuid(run.id)),
            ),
            "committee question": (
                run,
                replace(committee, question_type_version="other-question.v1"),
            ),
            "committee workflow": (
                run,
                replace(committee, workflow_config_version="other-workflow.v1"),
            ),
        }
        for label, (candidate_run, candidate_committee) in drifted_values.items():
            with self.subTest(label=label):
                boundary, *_ = adapter(
                    candidate_run,
                    candidate_committee,
                    result,
                )
                with self.assertRaisesRegex(
                    ReadinessAndThesisError,
                    "persisted readiness input identity mismatch",
                ):
                    boundary.execute(
                        AuthenticatedOperator(run.operator_id),
                        run.id,
                    )

    def test_rejects_committee_reloaded_by_id_with_different_state(self) -> None:
        run, committee, result = fixture()
        reloaded = replace(committee, status="complete_with_abstentions")
        boundary, *_ = adapter(
            run,
            committee,
            result,
            reloaded=reloaded,
        )

        with self.assertRaisesRegex(
            ReadinessAndThesisError,
            "reloaded committee does not match",
        ):
            boundary.execute(
                AuthenticatedOperator(run.operator_id),
                run.id,
            )

    def test_rejects_cross_linked_readiness_and_creation_identity(self) -> None:
        run, committee, result = fixture()
        mismatches = {
            "readiness owner": replace(
                result,
                readiness=replace(
                    result.readiness,
                    operator_id=other_uuid(run.operator_id),
                ),
            ),
            "readiness security": replace(
                result,
                readiness=replace(
                    result.readiness,
                    security_id=other_uuid(run.security_id),
                ),
            ),
            "readiness committee": replace(
                result,
                readiness=replace(
                    result.readiness,
                    committee_result_id=other_uuid(committee.committee_id),
                ),
            ),
            "creation run": replace(
                result,
                thesis_creation=replace(
                    result.thesis_creation,
                    research_run_id=other_uuid(run.id),
                ),
            ),
            "creation readiness": replace(
                result,
                thesis_creation=replace(
                    result.thesis_creation,
                    readiness_gate_result_id=other_uuid(
                        result.readiness.readiness_gate_result_id
                    ),
                ),
            ),
        }
        for label, candidate in mismatches.items():
            with self.subTest(label=label):
                boundary, *_ = adapter(run, committee, candidate)
                with self.assertRaisesRegex(
                    ReadinessAndThesisError,
                    "persisted readiness thesis identity mismatch",
                ):
                    boundary.execute(
                        AuthenticatedOperator(run.operator_id),
                        run.id,
                    )

    def test_rejects_non_uuid_artifact_and_link_ids(self) -> None:
        run, committee, result = fixture()
        invalid_ids = {
            "creation": replace(
                result,
                thesis_creation=replace(
                    result.thesis_creation,
                    thesis_creation_result_id="not-a-uuid",
                ),
            ),
            "committee": replace(
                result,
                readiness=replace(
                    result.readiness,
                    committee_result_id="not-a-uuid",
                ),
                thesis_creation=replace(
                    result.thesis_creation,
                    committee_result_id="not-a-uuid",
                ),
                thesis=replace(
                    result.thesis,
                    committee_result_id="not-a-uuid",
                ),
            ),
            "memo": replace(
                result,
                readiness=replace(
                    result.readiness,
                    committee_memo_id="not-a-uuid",
                ),
                thesis=replace(
                    result.thesis,
                    committee_memo_id="not-a-uuid",
                ),
            ),
            "readiness": replace(
                result,
                readiness=replace(
                    result.readiness,
                    readiness_gate_result_id="not-a-uuid",
                ),
                thesis_creation=replace(
                    result.thesis_creation,
                    readiness_gate_result_id="not-a-uuid",
                ),
                thesis=replace(
                    result.thesis,
                    readiness_gate_result_id="not-a-uuid",
                ),
            ),
        }
        for label, candidate in invalid_ids.items():
            with self.subTest(label=label):
                boundary, *_ = adapter(run, committee, candidate)
                with self.assertRaisesRegex(
                    ReadinessAndThesisError,
                    "persisted readiness thesis identifier invalid",
                ):
                    boundary.execute(
                        AuthenticatedOperator(run.operator_id),
                        run.id,
                    )


def replace_namespace(value, **changes):
    return SimpleNamespace(**{**vars(value), **changes})


def other_uuid(value: str) -> str:
    return "ffffffff-ffff-4fff-8fff-ffffffffffff" if value != (
        "ffffffff-ffff-4fff-8fff-ffffffffffff"
    ) else "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"


if __name__ == "__main__":
    unittest.main()

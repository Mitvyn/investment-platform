from __future__ import annotations

import unittest
from dataclasses import replace

from investment_research_os.committee_memos import CommitteeMemoError
from investment_research_os.research_runs import AuthenticatedOperator
from investment_research_os.research_workflows import (
    build_offline_mvp_config,
)
from tests.test_evidence_bundle_workflow import eligible_run
from tests.test_grader_execution_workflow import (
    aligned_valuation_repository,
)
from tests.test_readiness_and_thesis import synthesized_fixture
from workers.research_committee.memo import (
    PersistentCommitteeMemoWorkflowAdapter,
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


class ValuationRepositoryFake:
    def __init__(self, snapshot) -> None:
        self.snapshot = snapshot
        self.reads: list[tuple[str, str]] = []

    def get_for_run(self, operator_id: str, research_run_id: str):
        self.reads.append((operator_id, research_run_id))
        return self.snapshot


class MemoWorkflowFake:
    def __init__(self, execution) -> None:
        self.execution = execution
        self.calls = []

    def execute(self, operator, request):
        self.calls.append((operator, request))
        return self.execution


class MemoRepositoryFake:
    def __init__(self, execution) -> None:
        self.execution = execution
        self.reads: list[tuple[str, str]] = []

    def get_for_committee(self, operator_id: str, committee_id: str):
        self.reads.append((operator_id, committee_id))
        return self.execution


def fixture():
    (
        bundle,
        committee,
        _,
        _,
        _,
        memo_execution,
    ) = synthesized_fixture(requested_disposition="monitor")
    _, valuation = aligned_valuation_repository(bundle)
    config = build_offline_mvp_config()
    return (
        eligible_run(),
        committee,
        valuation,
        replace(
            memo_execution,
            memo=replace(
                memo_execution.memo,
                model_config_id=config.synthesizer.model.config_id,
            ),
        ),
    )


def adapter(
    run,
    committee,
    valuation,
    execution,
    *,
    reloaded_committee=None,
    reloaded_execution=...,
):
    runs = ResearchRunRepositoryFake(run)
    committees = CommitteeReadModelFake(
        committee,
        reloaded=reloaded_committee,
    )
    valuations = ValuationRepositoryFake(valuation)
    workflow = MemoWorkflowFake(execution)
    repository = MemoRepositoryFake(
        execution if reloaded_execution is ... else reloaded_execution
    )
    boundary = PersistentCommitteeMemoWorkflowAdapter(
        research_run_repository=runs,
        committee_read_model=committees,
        valuation_snapshot_repository=valuations,
        config=build_offline_mvp_config(),
        workflow=workflow,
        memo_repository=repository,
    )
    return boundary, runs, committees, valuations, workflow, repository


class PersistentCommitteeMemoWorkflowAdapterTests(unittest.TestCase):
    def test_executes_versioned_synthesis_and_returns_reloaded_memo(
        self,
    ) -> None:
        run, committee, valuation, execution = fixture()
        (
            boundary,
            runs,
            committees,
            valuations,
            workflow,
            repository,
        ) = adapter(run, committee, valuation, execution)

        artifact = boundary.execute(
            AuthenticatedOperator(run.operator_id),
            run.id,
        )

        self.assertEqual(artifact.id, execution.memo.memo_id)
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
            valuations.reads,
            [(run.operator_id, run.id)],
        )
        self.assertEqual(
            repository.reads,
            [(run.operator_id, committee.committee_id)],
        )
        self.assertEqual(len(workflow.calls), 1)
        operator, request = workflow.calls[0]
        self.assertEqual(operator, AuthenticatedOperator(run.operator_id))
        self.assertEqual(request.committee_id, committee.committee_id)
        self.assertEqual(
            request.calculation_ids,
            valuation.calculation_ids,
        )

    def test_rejects_missing_persisted_dependencies_before_synthesis(
        self,
    ) -> None:
        run, committee, valuation, execution = fixture()
        cases = {
            "run": (None, committee, valuation),
            "committee": (run, None, valuation),
            "valuation": (run, committee, None),
        }
        for label, (
            candidate_run,
            candidate_committee,
            candidate_value,
        ) in cases.items():
            with self.subTest(label=label):
                boundary, *_, workflow, _ = adapter(
                    candidate_run,
                    candidate_committee,
                    candidate_value,
                    execution,
                )
                with self.assertRaises(CommitteeMemoError):
                    boundary.execute(
                        AuthenticatedOperator(run.operator_id),
                        run.id,
                    )
                self.assertEqual(workflow.calls, [])

    def test_rejects_drifted_run_committee_or_valuation_identity(
        self,
    ) -> None:
        run, committee, valuation, execution = fixture()
        other = "ffffffff-ffff-4fff-8fff-ffffffffffff"
        cases = {
            "run owner": (
                replace(run, operator_id=other),
                committee,
                valuation,
            ),
            "committee run": (
                run,
                replace(committee, research_run_id=other),
                valuation,
            ),
            "committee question": (
                run,
                replace(committee, question_type_version="other.v1"),
                valuation,
            ),
            "committee workflow": (
                run,
                replace(committee, workflow_config_version="other.v1"),
                valuation,
            ),
            "valuation security": (
                run,
                committee,
                replace(valuation, security_id=other),
            ),
            "valuation cutoff": (
                run,
                committee,
                replace(
                    valuation,
                    as_of_cutoff=run.as_of_cutoff.replace(year=2025),
                ),
            ),
            "valuation bundle": (
                run,
                committee,
                replace(valuation, evidence_bundle_id=other),
            ),
        }
        for label, candidates in cases.items():
            with self.subTest(label=label):
                boundary, *_ = adapter(*candidates, execution)
                with self.assertRaisesRegex(
                    CommitteeMemoError,
                    "persistent memo input identity mismatch",
                ):
                    boundary.execute(
                        AuthenticatedOperator(run.operator_id),
                        run.id,
                    )

    def test_rejects_failed_or_memo_less_execution(self) -> None:
        run, committee, valuation, execution = fixture()
        cases = {
            "failed": replace(
                execution,
                execution_state="failed",
                memo=None,
            ),
            "memo-less": replace(execution, memo=None),
        }
        for label, candidate in cases.items():
            with self.subTest(label=label):
                boundary, *_ = adapter(
                    run,
                    committee,
                    valuation,
                    candidate,
                )
                with self.assertRaisesRegex(
                    CommitteeMemoError,
                    "accepted persisted committee memo required",
                ):
                    boundary.execute(
                        AuthenticatedOperator(run.operator_id),
                        run.id,
                    )

    def test_rejects_missing_or_drifted_mandatory_reload(self) -> None:
        run, committee, valuation, execution = fixture()
        drifted = replace(
            execution,
            execution_key="f" * 64,
        )
        for label, reloaded in {
            "missing": None,
            "drifted": drifted,
        }.items():
            with self.subTest(label=label):
                boundary, *_ = adapter(
                    run,
                    committee,
                    valuation,
                    execution,
                    reloaded_execution=reloaded,
                )
                with self.assertRaisesRegex(
                    CommitteeMemoError,
                    "reloaded committee memo execution does not match",
                ):
                    boundary.execute(
                        AuthenticatedOperator(run.operator_id),
                        run.id,
                    )

    def test_rejects_drifted_mandatory_committee_reload(self) -> None:
        run, committee, valuation, execution = fixture()
        boundary, *_ = adapter(
            run,
            committee,
            valuation,
            execution,
            reloaded_committee=replace(
                committee,
                status="complete_with_abstentions",
            ),
        )

        with self.assertRaisesRegex(
            CommitteeMemoError,
            "reloaded committee does not match",
        ):
            boundary.execute(
                AuthenticatedOperator(run.operator_id),
                run.id,
            )

    def test_rejects_memo_identity_and_uuid_link_drift(self) -> None:
        run, committee, valuation, execution = fixture()
        other = "ffffffff-ffff-4fff-8fff-ffffffffffff"
        cases = {
            "execution owner": replace(execution, operator_id=other),
            "memo run": replace(
                execution,
                memo=replace(execution.memo, research_run_id=other),
            ),
            "memo bundle hash": replace(
                execution,
                memo=replace(execution.memo, evidence_bundle_hash="f" * 64),
            ),
            "memo execution link": replace(
                execution,
                memo=replace(
                    execution.memo,
                    synthesis_execution_id=other,
                ),
            ),
            "memo invalid id": replace(
                execution,
                memo=replace(execution.memo, memo_id="not-a-uuid"),
            ),
        }
        for label, candidate in cases.items():
            with self.subTest(label=label):
                boundary, *_ = adapter(
                    run,
                    committee,
                    valuation,
                    candidate,
                )
                with self.assertRaises(CommitteeMemoError):
                    boundary.execute(
                        AuthenticatedOperator(run.operator_id),
                        run.id,
                    )


if __name__ == "__main__":
    unittest.main()

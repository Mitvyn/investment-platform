from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import json
import subprocess
import unittest

from investment_research_os.evidence_bundles import AuthenticatedOperator
from investment_research_os.operator_decisions import (
    InMemoryOperatorDecisionRepository,
    OperatorDecisionError,
    OperatorDecisionRequest,
    OperatorDecisionWorkflow,
)
from investment_research_os.readiness_and_theses import (
    InMemoryReadinessAndThesisRepository,
    ReadinessAndThesisWorkflow,
    ReadinessRequest,
)
from investment_research_os.research_runs import (
    PERSONAL_RESEARCH_QUESTION_TYPE,
    PERSONAL_RESEARCH_QUESTION_TYPE_VERSION,
    PERSONAL_RESEARCH_THESIS_CONTRACT_ID,
    PERSONAL_RESEARCH_WORKFLOW_CONFIG_VERSION,
)
from investment_research_os.valuation_snapshots import (
    InMemoryValuationSnapshotRepository,
    PersonalResearchValuationSnapshotWorkflow,
)
from tests.test_readiness_and_thesis import (
    FixedCommitteeRepository,
    synthesized_fixture,
    synthesized_terminal_fixture,
)
from tests.test_grader_execution_workflow import aligned_valuation_repository
from tests.test_valuation_snapshot_workflow import (
    FixedCalendar,
    FixedValuationSource,
    personal_input_candidate,
)


def thesis_fixture(
    disposition: str,
    *,
    provisional: bool = False,
):
    fixture = (
        synthesized_terminal_fixture(terminal_state="abstained")
        if provisional
        else synthesized_fixture(requested_disposition=disposition)
    )
    bundle, committee, bundle_repository, committee_repository, memo_repository, _ = (
        fixture
    )
    readiness_repository = InMemoryReadinessAndThesisRepository()
    valuation_repository, _ = aligned_valuation_repository(bundle)
    result = ReadinessAndThesisWorkflow(
        committee_repository=committee_repository,
        evidence_bundle_repository=bundle_repository,
        memo_repository=memo_repository,
        repository=readiness_repository,
        valuation_snapshot_repository=valuation_repository,
        clock=lambda: datetime(2026, 7, 22, 5, 0, tzinfo=UTC),
    ).execute(
        AuthenticatedOperator(bundle.operator_id),
        ReadinessRequest(
            committee_id=committee.committee_id,
            gate_policy_version="biotech-readiness.v1",
        ),
    )
    return bundle, result, readiness_repository


def personal_thesis_fixture(
    disposition: str,
    *,
    provisional: bool = False,
):
    fixture = (
        synthesized_terminal_fixture(terminal_state="abstained")
        if provisional
        else synthesized_fixture(requested_disposition=disposition)
    )
    bundle, committee, bundle_repository, _, memo_repository, _ = fixture
    personal_committee = replace(
        committee,
        question_type_id=PERSONAL_RESEARCH_QUESTION_TYPE,
        question_type_version=PERSONAL_RESEARCH_QUESTION_TYPE_VERSION,
        workflow_config_version=PERSONAL_RESEARCH_WORKFLOW_CONFIG_VERSION,
    )
    valuation_repository = InMemoryValuationSnapshotRepository()
    PersonalResearchValuationSnapshotWorkflow(
        evidence_bundle_repository=bundle_repository,
        valuation_snapshot_repository=valuation_repository,
        market_calendar=FixedCalendar(),
        input_source=FixedValuationSource(personal_input_candidate()),
        clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
    ).materialize(AuthenticatedOperator(bundle.operator_id), bundle.id)
    readiness_repository = InMemoryReadinessAndThesisRepository()
    result = ReadinessAndThesisWorkflow(
        committee_repository=FixedCommitteeRepository(personal_committee),
        evidence_bundle_repository=bundle_repository,
        memo_repository=memo_repository,
        repository=readiness_repository,
        valuation_snapshot_repository=valuation_repository,
        clock=lambda: datetime(2026, 7, 22, 5, 0, tzinfo=UTC),
    ).execute(
        AuthenticatedOperator(bundle.operator_id),
        ReadinessRequest(
            committee_id=personal_committee.committee_id,
            gate_policy_version="biotech-personal-readiness.v1",
        ),
    )
    return bundle, result, readiness_repository


class OperatorDecisionWorkflowTests(unittest.TestCase):
    def _workflow(self, readiness_repository, decision_repository=None):
        return OperatorDecisionWorkflow(
            readiness_repository=readiness_repository,
            repository=(decision_repository or InMemoryOperatorDecisionRepository()),
            clock=lambda: datetime(2026, 7, 22, 6, 0, tzinfo=UTC),
        )

    def test_matching_action_creates_immutable_accepted_decision_event(self) -> None:
        bundle, research, readiness_repository = thesis_fixture("monitor")
        repository = InMemoryOperatorDecisionRepository()
        workflow = self._workflow(readiness_repository, repository)
        thesis_before = research.thesis

        outcome = workflow.execute(
            AuthenticatedOperator(bundle.operator_id),
            OperatorDecisionRequest(
                thesis_version_id=research.thesis.thesis_version_id,
                operator_action="monitor",
                rationale="Retain for the next primary-source catalyst update.",
                supersedes_operator_decision_id=None,
                idempotency_key="decision-monitor-run-1",
                decision_policy_version="operator_decision_policy.v1",
            ),
        )

        self.assertEqual(outcome.event.relationship, "accept")
        self.assertEqual(outcome.event.system_disposition, "monitor")
        self.assertEqual(outcome.event.operator_action, "monitor")
        self.assertEqual(research.thesis, thesis_before)
        self.assertEqual(
            repository.current(
                bundle.operator_id,
                bundle.security_id,
                research.thesis.thesis_contract_id,
            ),
            outcome.event,
        )
        self.assertEqual(
            repository.history(
                bundle.operator_id,
                bundle.security_id,
                research.thesis.thesis_contract_id,
            ),
            (outcome.event,),
        )

    def test_override_requires_rationale(self) -> None:
        bundle, research, readiness_repository = thesis_fixture("monitor")
        workflow = self._workflow(readiness_repository)

        with self.assertRaisesRegex(
            OperatorDecisionError,
            "override rationale required",
        ):
            workflow.execute(
                AuthenticatedOperator(bundle.operator_id),
                OperatorDecisionRequest(
                    thesis_version_id=research.thesis.thesis_version_id,
                    operator_action="dismiss",
                    rationale="",
                    supersedes_operator_decision_id=None,
                    idempotency_key="decision-dismiss-run-1",
                    decision_policy_version="operator_decision_policy.v1",
                ),
            )

    def test_supersession_preserves_history_and_changes_current_state(self) -> None:
        bundle, research, readiness_repository = thesis_fixture("monitor")
        repository = InMemoryOperatorDecisionRepository()
        workflow = self._workflow(readiness_repository, repository)
        first = workflow.execute(
            AuthenticatedOperator(bundle.operator_id),
            OperatorDecisionRequest(
                thesis_version_id=research.thesis.thesis_version_id,
                operator_action="monitor",
                rationale="Monitor initial evidence.",
                supersedes_operator_decision_id=None,
                idempotency_key="decision-monitor-first",
                decision_policy_version="operator_decision_policy.v1",
            ),
        )
        second = workflow.execute(
            AuthenticatedOperator(bundle.operator_id),
            OperatorDecisionRequest(
                thesis_version_id=research.thesis.thesis_version_id,
                operator_action="request_deep_research",
                rationale="New uncertainty warrants deeper research.",
                supersedes_operator_decision_id=first.event.operator_decision_id,
                idempotency_key="decision-research-second",
                decision_policy_version="operator_decision_policy.v1",
            ),
        )

        history = repository.history(
            bundle.operator_id,
            bundle.security_id,
            research.thesis.thesis_contract_id,
        )
        self.assertEqual(history, (first.event, second.event))
        self.assertEqual(repository.current(*history[0].ownership_key), second.event)
        self.assertEqual(second.event.relationship, "override")

    def test_deep_research_command_is_separate_and_idempotent(self) -> None:
        bundle, research, readiness_repository = thesis_fixture("deep_research")
        repository = InMemoryOperatorDecisionRepository()
        workflow = self._workflow(readiness_repository, repository)
        request = OperatorDecisionRequest(
            thesis_version_id=research.thesis.thesis_version_id,
            operator_action="request_deep_research",
            rationale="Resolve the blocking valuation evidence.",
            supersedes_operator_decision_id=None,
            idempotency_key="decision-deep-research-run-1",
            decision_policy_version="operator_decision_policy.v1",
        )

        first = workflow.execute(AuthenticatedOperator(bundle.operator_id), request)
        second = workflow.execute(AuthenticatedOperator(bundle.operator_id), request)

        self.assertIs(second, first)
        self.assertIsNotNone(first.workflow_command)
        self.assertEqual(first.workflow_command.command_type, "create_research_request")
        self.assertIsNone(first.portfolio_handoff_marker)
        self.assertEqual(
            repository.commands_for_event(first.event.operator_decision_id),
            (first.workflow_command,),
        )

        conflicting = OperatorDecisionRequest(
            thesis_version_id=research.thesis.thesis_version_id,
            operator_action="no_action",
            rationale="Conflicting replay payload.",
            supersedes_operator_decision_id=None,
            idempotency_key=request.idempotency_key,
            decision_policy_version="operator_decision_policy.v1",
        )
        with self.assertRaisesRegex(
            OperatorDecisionError,
            "idempotency key payload conflict",
        ):
            workflow.execute(
                AuthenticatedOperator(bundle.operator_id),
                conflicting,
            )

    def test_public_history_and_current_state_are_separate_contracts(self) -> None:
        bundle, research, readiness_repository = thesis_fixture("monitor")
        repository = InMemoryOperatorDecisionRepository()
        workflow = self._workflow(readiness_repository, repository)
        event = workflow.execute(
            AuthenticatedOperator(bundle.operator_id),
            OperatorDecisionRequest(
                thesis_version_id=research.thesis.thesis_version_id,
                operator_action="monitor",
                rationale="Monitor the next primary-source update.",
                supersedes_operator_decision_id=None,
                idempotency_key="decision-public-state",
                decision_policy_version="operator_decision_policy.v1",
            ),
        ).event
        derived_at = datetime(2026, 7, 22, 6, 5, tzinfo=UTC)

        history = repository.public_history(
            bundle.operator_id,
            bundle.security_id,
            research.thesis.thesis_contract_id,
            derived_at,
        )
        current = repository.current_state(
            bundle.operator_id,
            bundle.security_id,
            research.thesis.thesis_contract_id,
            derived_at,
        )

        self.assertEqual(history.events, (event,))
        self.assertEqual(
            current.current_operator_decision_id, event.operator_decision_id
        )
        self.assertEqual(current.supersession_depth, 0)
        self.assertNotIn("current_operator_decision_id", history.as_dict())
        self.assertNotIn("events", current.as_dict())

    def test_portfolio_handoff_requires_canonical_passed_decision_ready(self) -> None:
        bundle, ready, readiness_repository = thesis_fixture("decision_ready")
        workflow = self._workflow(readiness_repository)

        allowed = workflow.execute(
            AuthenticatedOperator(bundle.operator_id),
            OperatorDecisionRequest(
                thesis_version_id=ready.thesis.thesis_version_id,
                operator_action="mark_for_future_portfolio_review",
                rationale="Research is complete for downstream fit review.",
                supersedes_operator_decision_id=None,
                idempotency_key="decision-portfolio-ready",
                decision_policy_version="operator_decision_policy.v1",
            ),
        )

        self.assertIsNotNone(allowed.portfolio_handoff_marker)
        self.assertIsNone(allowed.workflow_command)
        self.assertEqual(
            allowed.portfolio_handoff_marker.final_system_disposition,
            "decision_ready",
        )

        monitor_bundle, monitor, monitor_repository = thesis_fixture("monitor")
        with self.assertRaisesRegex(
            OperatorDecisionError,
            "portfolio handoff requires canonical decision ready thesis",
        ):
            self._workflow(monitor_repository).execute(
                AuthenticatedOperator(monitor_bundle.operator_id),
                OperatorDecisionRequest(
                    thesis_version_id=monitor.thesis.thesis_version_id,
                    operator_action="mark_for_future_portfolio_review",
                    rationale="Operator override attempt.",
                    supersedes_operator_decision_id=None,
                    idempotency_key="decision-portfolio-monitor",
                    decision_policy_version="operator_decision_policy.v1",
                ),
            )

        provisional_bundle, provisional, provisional_repository = thesis_fixture(
            "deep_research",
            provisional=True,
        )
        with self.assertRaisesRegex(
            OperatorDecisionError,
            "portfolio handoff requires canonical decision ready thesis",
        ):
            self._workflow(provisional_repository).execute(
                AuthenticatedOperator(provisional_bundle.operator_id),
                OperatorDecisionRequest(
                    thesis_version_id=provisional.thesis.thesis_version_id,
                    operator_action="mark_for_future_portfolio_review",
                    rationale="Provisional override attempt.",
                    supersedes_operator_decision_id=None,
                    idempotency_key="decision-portfolio-provisional",
                    decision_policy_version="operator_decision_policy.v1",
                ),
            )

    def test_personal_research_thesis_can_never_create_portfolio_handoff(self) -> None:
        bundle, ready, readiness_repository = personal_thesis_fixture("decision_ready")
        self.assertEqual(
            ready.thesis.thesis_contract_id,
            PERSONAL_RESEARCH_THESIS_CONTRACT_ID,
        )

        with self.assertRaisesRegex(
            OperatorDecisionError,
            "personal research thesis cannot create portfolio handoff",
        ):
            self._workflow(readiness_repository).execute(
                AuthenticatedOperator(bundle.operator_id),
                OperatorDecisionRequest(
                    thesis_version_id=ready.thesis.thesis_version_id,
                    operator_action="mark_for_future_portfolio_review",
                    rationale="Lower-assurance research cannot cross handoff boundary.",
                    supersedes_operator_decision_id=None,
                    idempotency_key="personal-decision-no-handoff",
                    decision_policy_version="operator_decision_policy.v1",
                ),
            )

    def test_personal_research_canonical_and_provisional_theses_record_actions(
        self,
    ) -> None:
        canonical_bundle, canonical, canonical_readiness = personal_thesis_fixture(
            "monitor"
        )
        canonical_outcome = self._workflow(canonical_readiness).execute(
            AuthenticatedOperator(canonical_bundle.operator_id),
            OperatorDecisionRequest(
                thesis_version_id=canonical.thesis.thesis_version_id,
                operator_action="monitor",
                rationale="Monitor within lower-assurance research boundary.",
                supersedes_operator_decision_id=None,
                idempotency_key="personal-canonical-monitor",
                decision_policy_version="operator_decision_policy.v1",
            ),
        )
        self.assertEqual(canonical_outcome.event.relationship, "accept")
        self.assertIsNone(canonical_outcome.workflow_command)
        self.assertIsNone(canonical_outcome.portfolio_handoff_marker)

        provisional_bundle, provisional, provisional_readiness = (
            personal_thesis_fixture("deep_research", provisional=True)
        )
        self.assertEqual(provisional.thesis.thesis_status, "provisional")
        provisional_outcome = self._workflow(provisional_readiness).execute(
            AuthenticatedOperator(provisional_bundle.operator_id),
            OperatorDecisionRequest(
                thesis_version_id=provisional.thesis.thesis_version_id,
                operator_action="request_deep_research",
                rationale="Resolve evidence gaps before another personal run.",
                supersedes_operator_decision_id=None,
                idempotency_key="personal-provisional-deep-research",
                decision_policy_version="operator_decision_policy.v1",
            ),
        )
        self.assertEqual(provisional_outcome.event.relationship, "accept")
        self.assertIsNotNone(provisional_outcome.workflow_command)
        self.assertIsNone(provisional_outcome.portfolio_handoff_marker)

    def test_python_outputs_cross_parse_with_shared_contracts(self) -> None:
        ready_bundle, ready_research, ready_readiness_repository = thesis_fixture(
            "decision_ready"
        )
        ready_decision_repository = InMemoryOperatorDecisionRepository()
        ready = self._workflow(
            ready_readiness_repository,
            ready_decision_repository,
        ).execute(
            AuthenticatedOperator(ready_bundle.operator_id),
            OperatorDecisionRequest(
                thesis_version_id=ready_research.thesis.thesis_version_id,
                operator_action="mark_for_future_portfolio_review",
                rationale="Research is ready for portfolio fit review.",
                supersedes_operator_decision_id=None,
                idempotency_key="decision-cross-parse-ready",
                decision_policy_version="operator_decision_policy.v1",
            ),
        )
        derived_at = datetime(2026, 7, 22, 6, 5, tzinfo=UTC)

        deep_bundle, deep_research, deep_readiness_repository = thesis_fixture(
            "deep_research"
        )
        deep = self._workflow(deep_readiness_repository).execute(
            AuthenticatedOperator(deep_bundle.operator_id),
            OperatorDecisionRequest(
                thesis_version_id=deep_research.thesis.thesis_version_id,
                operator_action="request_deep_research",
                rationale="Resolve the remaining evidence gaps.",
                supersedes_operator_decision_id=None,
                idempotency_key="decision-cross-parse-deep",
                decision_policy_version="operator_decision_policy.v1",
            ),
        )

        payload = {
            "ready": {
                "event": ready.event.as_dict(),
                "history": ready_decision_repository.public_history(
                    ready_bundle.operator_id,
                    ready_bundle.security_id,
                    ready_research.thesis.thesis_contract_id,
                    derived_at,
                ).as_dict(),
                "current": ready_decision_repository.current_state(
                    ready_bundle.operator_id,
                    ready_bundle.security_id,
                    ready_research.thesis.thesis_contract_id,
                    derived_at,
                ).as_dict(),
                "marker": ready.portfolio_handoff_marker.as_dict(),
                "thesis": ready_research.thesis.as_dict(),
                "readiness": ready_research.readiness.as_dict(),
            },
            "deep": {
                "event": deep.event.as_dict(),
                "command": deep.workflow_command.as_dict(),
                "thesis": deep_research.thesis.as_dict(),
                "readiness": deep_research.readiness.as_dict(),
            },
        }
        parsed = subprocess.run(
            [
                "node",
                "--experimental-strip-types",
                "--input-type=module",
                "--eval",
                (
                    "import {parseOperatorDecisionEvent,"
                    "parseOperatorDecisionHistory,"
                    "deriveOperatorDecisionCurrentState,"
                    "parseOperatorWorkflowCommand,"
                    "parsePortfolioReviewHandoffMarker} from "
                    "'./packages/types/operator-decision.ts';"
                    "let input=''; for await (const chunk of process.stdin) "
                    "input+=chunk; const p=JSON.parse(input);"
                    "const rc={thesisVersion:p.ready.thesis,"
                    "readinessResult:p.ready.readiness};"
                    "const re=parseOperatorDecisionEvent(p.ready.event,rc);"
                    "const rh=parseOperatorDecisionHistory(p.ready.history,rc);"
                    "const current=deriveOperatorDecisionCurrentState("
                    "rh,p.ready.current.derived_at);"
                    "if(JSON.stringify(current)!==JSON.stringify(p.ready.current))"
                    "throw new Error('current state mismatch');"
                    "parsePortfolioReviewHandoffMarker(p.ready.marker,{"
                    "decision:re,...rc});"
                    "const dc={thesisVersion:p.deep.thesis,"
                    "readinessResult:p.deep.readiness};"
                    "const de=parseOperatorDecisionEvent(p.deep.event,dc);"
                    "parseOperatorWorkflowCommand(p.deep.command,{decision:de});"
                ),
            ],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(parsed.returncode, 0, parsed.stderr)


if __name__ == "__main__":
    unittest.main()

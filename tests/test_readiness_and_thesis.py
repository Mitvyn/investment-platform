from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
import subprocess
import unittest

from investment_research_os.committee_memos import (
    CommitteeMemoWorkflow,
    InMemoryCommitteeMemoRepository,
)
from investment_research_os.evidence_bundles import AuthenticatedOperator
from investment_research_os.evidence_bundles import (
    InMemoryEvidenceBundleRepository,
)
from investment_research_os.grader_executions import (
    GraderExecutionWorkflow,
    InMemoryBudgetLedger,
    InMemoryGraderExecutionRepository,
    ProviderResponse,
    ProviderUsage,
)
from investment_research_os.research_committees import (
    InMemoryResearchCommitteeRepository,
    ResearchCommitteeWorkflow,
)
from investment_research_os.readiness_and_theses import (
    InMemoryReadinessAndThesisRepository,
    ReadinessAndThesisResult,
    ReadinessAndThesisWorkflow,
    ReadinessRequest,
)
from investment_research_os.valuation_snapshots import (
    InMemoryValuationSnapshotRepository,
    ValuationSnapshotWorkflow,
)
from tests.test_committee_memo_workflow import (
    approved_synthesis_request,
    valid_memo_output,
)
from tests.test_evidence_bundle_storage import materialized_bundle
from tests import test_five_grader_committee as committee_fixtures
from tests.test_five_grader_committee import completed_committee_fixture
from tests.test_grader_execution_workflow import FakeProvider
from tests.test_valuation_snapshot_workflow import (
    FixedCalendar,
    FixedValuationSource,
    input_candidate,
)


def synthesized_fixture(
    *,
    requested_disposition: str,
    include_invalidation: bool = True,
):
    bundle, committee, bundle_repository, committee_repository = (
        completed_committee_fixture()
    )
    synthesis_request = approved_synthesis_request(committee)
    output = deepcopy(valid_memo_output(committee))
    output["requested_disposition"] = requested_disposition
    if not include_invalidation:
        output["invalidation_statement_ids"] = []
    provider = FakeProvider(
        (
            ProviderResponse(
                provider_request_id="fake-readiness-synthesis",
                raw_output=output,
                usage=ProviderUsage(2000, 500, 500, 100, 2500),
                resolved_model=synthesis_request.model.model,
                system_fingerprint="offline-synthesis-fingerprint-v1",
            ),
        )
    )
    memo_repository = InMemoryCommitteeMemoRepository()
    times = iter(
        (
            datetime(2026, 7, 22, 4, 0, tzinfo=UTC),
            datetime(2026, 7, 22, 4, 1, tzinfo=UTC),
        )
    )
    memo_execution = CommitteeMemoWorkflow(
        committee_repository=committee_repository,
        evidence_bundle_repository=bundle_repository,
        memo_repository=memo_repository,
        budget_ledger=InMemoryBudgetLedger(
            hard_limit_usd=Decimal("2.00")
        ),
        provider=provider,
        clock=lambda: next(times),
    ).execute(
        AuthenticatedOperator(bundle.operator_id),
        synthesis_request,
    )
    return (
        bundle,
        committee,
        bundle_repository,
        committee_repository,
        memo_repository,
        memo_execution,
    )


def synthesized_terminal_fixture(*, terminal_state: str):
    helper = committee_fixtures.FiveGraderDomainContractTests()
    bundle = materialized_bundle()
    requests = helper._committee_requests(bundle.id)
    responses = []
    for index, request in enumerate(requests, start=1):
        output = helper._output_for_request(bundle, request)
        if index == len(requests) and terminal_state == "abstained":
            output["execution_state"] = "abstained"
            output["stance"] = None
            output["proposition"]["grader_stance"] = None
            output["proposition"]["stance_rationale"] = None
            output["material_claims"] = []
            output["abstention"] = {
                "reason_code": "insufficient_valuation_evidence",
                "reason": "Valuation evidence is insufficient.",
                "missing_or_inadequate_evidence": ["Licensed official close"],
                "evidence_required": ["Aligned licensed valuation snapshot"],
                "confidence": "high",
            }
        elif index == len(requests) and terminal_state == "failed":
            output = {"unsupported": True}
        responses.append(
            ProviderResponse(
                provider_request_id=f"fake-terminal-{index}-1",
                raw_output=output,
                usage=ProviderUsage(1000, 200, 300, 100, 1300),
                resolved_model=request.model.model,
                system_fingerprint="offline-fingerprint-v1",
            )
        )
        if index == len(requests) and terminal_state == "failed":
            responses.append(
                ProviderResponse(
                    provider_request_id=f"fake-terminal-{index}-2",
                    raw_output=output,
                    usage=ProviderUsage(1000, 200, 300, 100, 1300),
                    resolved_model=request.model.model,
                    system_fingerprint="offline-fingerprint-v1",
                )
            )
    bundle_repository = InMemoryEvidenceBundleRepository()
    bundle_repository.save(bundle)
    committee_repository = InMemoryResearchCommitteeRepository()
    committee = ResearchCommitteeWorkflow(
        grader_workflow=GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=InMemoryGraderExecutionRepository(),
            budget_ledger=InMemoryBudgetLedger(
                hard_limit_usd=Decimal("5.00")
            ),
            provider=FakeProvider(tuple(responses)),
            clock=lambda: datetime(2026, 7, 22, 3, 0, tzinfo=UTC),
        ),
        evidence_bundle_repository=bundle_repository,
        repository=committee_repository,
        clock=helper._committee_clock(),
    ).execute(AuthenticatedOperator(bundle.operator_id), requests)
    synthesis_request = approved_synthesis_request(committee)
    output = valid_memo_output(committee)
    output["requested_disposition"] = "decision_ready"
    memo_repository = InMemoryCommitteeMemoRepository()
    times = iter(
        (
            datetime(2026, 7, 22, 4, 0, tzinfo=UTC),
            datetime(2026, 7, 22, 4, 1, tzinfo=UTC),
        )
    )
    memo_execution = CommitteeMemoWorkflow(
        committee_repository=committee_repository,
        evidence_bundle_repository=bundle_repository,
        memo_repository=memo_repository,
        budget_ledger=InMemoryBudgetLedger(
            hard_limit_usd=Decimal("2.00")
        ),
        provider=FakeProvider(
            (
                ProviderResponse(
                    provider_request_id="fake-terminal-synthesis",
                    raw_output=output,
                    usage=ProviderUsage(2000, 500, 500, 100, 2500),
                    resolved_model=synthesis_request.model.model,
                    system_fingerprint="offline-synthesis-fingerprint-v1",
                ),
            )
        ),
        clock=lambda: next(times),
    ).execute(
        AuthenticatedOperator(bundle.operator_id),
        synthesis_request,
    )
    return (
        bundle,
        committee,
        bundle_repository,
        committee_repository,
        memo_repository,
        memo_execution,
    )


class ReadinessAndThesisWorkflowTests(unittest.TestCase):
    def _workflow(self, fixture, repository, *, include_valuation=True):
        (
            _,
            _,
            bundle_repository,
            committee_repository,
            memo_repository,
            _,
        ) = fixture
        valuation_repository = InMemoryValuationSnapshotRepository()
        if include_valuation:
            ValuationSnapshotWorkflow(
                evidence_bundle_repository=bundle_repository,
                valuation_snapshot_repository=valuation_repository,
                market_calendar=FixedCalendar(),
                input_source=FixedValuationSource(input_candidate()),
                clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
            ).materialize(AuthenticatedOperator(fixture[0].operator_id), fixture[0].id)
        return ReadinessAndThesisWorkflow(
            committee_repository=committee_repository,
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=valuation_repository,
            memo_repository=memo_repository,
            repository=repository,
            clock=lambda: datetime(2026, 7, 22, 5, 0, tzinfo=UTC),
        )

    def test_decision_ready_is_blocked_without_aligned_valuation_snapshot(
        self,
    ) -> None:
        fixture = synthesized_fixture(requested_disposition="decision_ready")
        bundle, committee, *_ = fixture

        result = self._workflow(
            fixture,
            InMemoryReadinessAndThesisRepository(),
            include_valuation=False,
        ).execute(
            AuthenticatedOperator(bundle.operator_id),
            ReadinessRequest(
                committee_id=committee.committee_id,
                gate_policy_version="biotech-readiness.v1",
            ),
        )

        self.assertEqual(result.readiness.readiness_status, "blocked")
        self.assertEqual(result.readiness.final_disposition, "deep_research")
        self.assertIn(
            "aligned_valuation_snapshot_required_failed",
            {item.reason_code for item in result.readiness.failed_checks},
        )

    def test_complete_passing_run_preserves_decision_ready_and_creates_canonical(
        self,
    ) -> None:
        fixture = synthesized_fixture(requested_disposition="decision_ready")
        bundle, committee, *_, memo_execution = fixture
        repository = InMemoryReadinessAndThesisRepository()

        result = self._workflow(fixture, repository).execute(
            AuthenticatedOperator(bundle.operator_id),
            ReadinessRequest(
                committee_id=committee.committee_id,
                gate_policy_version="biotech-readiness.v1",
            ),
        )

        self.assertEqual(result.readiness.readiness_status, "passed")
        self.assertEqual(result.readiness.final_disposition, "decision_ready")
        self.assertEqual(len(result.readiness.passed_checks), 11)
        self.assertEqual(
            result.thesis_creation.creation_outcome,
            "canonical_created",
        )
        self.assertEqual(result.thesis.thesis_status, "canonical")
        self.assertEqual(result.thesis.committee_memo_id, memo_execution.memo.memo_id)
        self.assertEqual(
            repository.get_chain(
                bundle.operator_id,
                bundle.security_id,
                committee.question_type_id,
            ).active_canonical_thesis_version_id,
            result.thesis.thesis_version_id,
        )
        memo = memo_execution.memo
        chain = repository.get_chain(
            bundle.operator_id,
            bundle.security_id,
            committee.question_type_id,
        )
        payload = {
            "readiness": result.readiness.as_dict(),
            "readinessContext": {
                "operatorId": bundle.operator_id,
                "securityId": bundle.security_id,
                "thesisContractId": committee.question_type_id,
                "researchRunId": committee.research_run_id,
                "evidenceBundleId": bundle.id,
                "evidenceBundleHash": bundle.content_hash,
                "validatedGraderOpinionIds": [
                    item.opinion.opinion_id
                    for item in committee.grader_results
                    if item.opinion is not None
                ],
                "committeeResultId": committee.committee_id,
                "committeeMemoId": memo.memo_id,
                "committeeStatus": committee.status,
                "requestedDisposition": memo.requested_disposition,
                "allowedReferenceIds": [
                    reference_id
                    for check in (
                        *result.readiness.passed_checks,
                        *result.readiness.failed_checks,
                    )
                    for reference_id in check.reference_ids
                ],
            },
            "thesis": result.thesis.as_dict(),
            "thesisContext": {
                "questionTypeVersion": committee.question_type_version,
                "workflowConfigVersion": committee.workflow_config_version,
                "propositionId": committee.proposition_id,
                "propositionVersion": committee.proposition_version,
                "memoStatementIds": [
                    item.statement_id for item in memo.statements
                ],
                "memoDisagreementIds": [
                    item["disagreement_id"]
                    for item in memo.disagreement_records
                ],
                "expectedPreviousCanonicalThesisVersionId": None,
                "expectedBasedOnThesisVersionId": None,
            },
            "creation": result.thesis_creation.as_dict(),
            "chain": chain.as_dict(),
        }
        parsed = subprocess.run(
            [
                "node",
                "--experimental-strip-types",
                "--input-type=module",
                "--eval",
                (
                    "import {parseReadinessGateResult,parseThesisVersion,"
                    "parseThesisCreationResult,parseThesisChain} from "
                    "'./packages/types/readiness-thesis.ts';"
                    "let input=''; for await (const chunk of process.stdin) "
                    "input+=chunk; const p=JSON.parse(input);"
                    "const r=parseReadinessGateResult(p.readiness,"
                    "p.readinessContext);"
                    "const t=parseThesisVersion(p.thesis,{"
                    "readinessResult:r,...p.thesisContext});"
                    "parseThesisCreationResult(p.creation,{"
                    "readinessResult:r,thesisVersion:t});"
                    "parseThesisChain(p.chain,{operatorId:r.operator_id,"
                    "securityId:r.security_id,"
                    "thesisContractId:r.thesis_contract_id});"
                ),
            ],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(parsed.returncode, 0, parsed.stderr)

    def test_failed_required_content_downgrades_decision_ready(self) -> None:
        fixture = synthesized_fixture(
            requested_disposition="decision_ready",
            include_invalidation=False,
        )
        bundle, committee, *_ = fixture
        repository = InMemoryReadinessAndThesisRepository()

        result = self._workflow(fixture, repository).execute(
            AuthenticatedOperator(bundle.operator_id),
            ReadinessRequest(
                committee_id=committee.committee_id,
                gate_policy_version="biotech-readiness.v1",
            ),
        )

        self.assertEqual(result.readiness.readiness_status, "blocked")
        self.assertEqual(result.readiness.final_disposition, "deep_research")
        self.assertIn(
            "thesis_required_contents_present",
            [item.check_id for item in result.readiness.failed_checks],
        )
        self.assertEqual(result.thesis.thesis_status, "canonical")

    def test_gate_never_upgrades_non_ready_disposition(self) -> None:
        fixture = synthesized_fixture(requested_disposition="monitor")
        bundle, committee, *_ = fixture
        repository = InMemoryReadinessAndThesisRepository()

        result = self._workflow(fixture, repository).execute(
            AuthenticatedOperator(bundle.operator_id),
            ReadinessRequest(
                committee_id=committee.committee_id,
                gate_policy_version="biotech-readiness.v1",
            ),
        )

        self.assertEqual(result.readiness.readiness_status, "not_requested")
        self.assertEqual(result.readiness.final_disposition, "monitor")
        self.assertEqual(result.thesis.thesis_status, "canonical")

    def test_replay_creates_at_most_one_readiness_and_thesis_version(self) -> None:
        fixture = synthesized_fixture(requested_disposition="monitor")
        bundle, committee, *_ = fixture
        repository = InMemoryReadinessAndThesisRepository()
        workflow = self._workflow(fixture, repository)
        request = ReadinessRequest(
            committee_id=committee.committee_id,
            gate_policy_version="biotech-readiness.v1",
        )

        first = workflow.execute(AuthenticatedOperator(bundle.operator_id), request)
        second = workflow.execute(AuthenticatedOperator(bundle.operator_id), request)

        self.assertIs(second, first)
        self.assertEqual(
            len(
                repository.get_chain(
                    bundle.operator_id,
                    bundle.security_id,
                    committee.question_type_id,
                ).canonical_versions
            ),
            1,
        )

    def test_abstention_creates_non_superseding_provisional_thesis(self) -> None:
        fixture = synthesized_terminal_fixture(terminal_state="abstained")
        bundle, committee, *_ = fixture
        repository = InMemoryReadinessAndThesisRepository()

        result = self._workflow(fixture, repository).execute(
            AuthenticatedOperator(bundle.operator_id),
            ReadinessRequest(
                committee_id=committee.committee_id,
                gate_policy_version="biotech-readiness.v1",
            ),
        )

        self.assertEqual(committee.status, "complete_with_abstentions")
        self.assertEqual(result.readiness.final_disposition, "deep_research")
        self.assertEqual(
            result.thesis_creation.creation_outcome,
            "provisional_created",
        )
        self.assertEqual(result.thesis.thesis_status, "provisional")
        chain = repository.get_chain(
            bundle.operator_id,
            bundle.security_id,
            committee.question_type_id,
        )
        self.assertIsNone(chain.active_canonical_thesis_version_id)
        self.assertEqual(chain.provisional_branches, (result.thesis,))

    def test_required_grader_failure_creates_no_thesis(self) -> None:
        fixture = synthesized_terminal_fixture(terminal_state="failed")
        bundle, committee, *_ = fixture
        repository = InMemoryReadinessAndThesisRepository()

        result = self._workflow(fixture, repository).execute(
            AuthenticatedOperator(bundle.operator_id),
            ReadinessRequest(
                committee_id=committee.committee_id,
                gate_policy_version="biotech-readiness.v1",
            ),
        )

        self.assertEqual(
            committee.status,
            "incomplete_required_grader_failed",
        )
        self.assertIsNone(result.thesis)
        self.assertEqual(
            result.thesis_creation.creation_outcome,
            "no_thesis",
        )
        chain = repository.get_chain(
            bundle.operator_id,
            bundle.security_id,
            committee.question_type_id,
        )
        self.assertEqual(chain.canonical_versions, ())
        self.assertEqual(chain.provisional_branches, ())

    def test_later_canonical_preserves_pre_canonical_provisional_branch(
        self,
    ) -> None:
        provisional_fixture = synthesized_terminal_fixture(
            terminal_state="abstained"
        )
        bundle, committee, *_ = provisional_fixture
        repository = InMemoryReadinessAndThesisRepository()
        provisional = self._workflow(
            provisional_fixture,
            repository,
        ).execute(
            AuthenticatedOperator(bundle.operator_id),
            ReadinessRequest(
                committee_id=committee.committee_id,
                gate_policy_version="biotech-readiness.v1",
            ),
        )
        canonical_fixture = synthesized_fixture(requested_disposition="monitor")
        isolated_repository = InMemoryReadinessAndThesisRepository()
        canonical = self._workflow(
            canonical_fixture,
            isolated_repository,
        ).execute(
            AuthenticatedOperator(bundle.operator_id),
            ReadinessRequest(
                committee_id=canonical_fixture[1].committee_id,
                gate_policy_version="biotech-readiness.v1",
            ),
        )
        later = provisional.readiness.evaluated_at + timedelta(minutes=5)
        later_run_id = "33000000-0000-4000-8000-000000000099"
        later_committee_id = "32000000-0000-4000-8000-000000000099"
        later_memo_id = "30000000-0000-4000-8000-000000000099"
        later_readiness_id = "40000000-0000-4000-8000-000000000099"
        later_thesis_id = "41000000-0000-4000-8000-000000000099"
        later_readiness = replace(
            canonical.readiness,
            readiness_gate_result_id=later_readiness_id,
            research_run_id=later_run_id,
            committee_result_id=later_committee_id,
            committee_memo_id=later_memo_id,
            evaluated_at=later,
        )
        later_thesis = replace(
            canonical.thesis,
            thesis_version_id=later_thesis_id,
            research_run_id=later_run_id,
            committee_result_id=later_committee_id,
            committee_memo_id=later_memo_id,
            readiness_gate_result_id=later_readiness_id,
            created_at=later,
        )
        later_creation = replace(
            canonical.thesis_creation,
            thesis_creation_result_id=(
                "42000000-0000-4000-8000-000000000099"
            ),
            research_run_id=later_run_id,
            committee_result_id=later_committee_id,
            readiness_gate_result_id=later_readiness_id,
            thesis_version_id=later_thesis_id,
            created_at=later,
        )

        repository.save(
            ReadinessAndThesisResult(
                readiness=later_readiness,
                thesis_creation=later_creation,
                thesis=later_thesis,
            )
        )

        chain = repository.get_chain(
            bundle.operator_id,
            bundle.security_id,
            committee.question_type_id,
        )
        self.assertEqual(
            chain.active_canonical_thesis_version_id,
            later_thesis_id,
        )
        self.assertEqual(chain.canonical_versions, (later_thesis,))
        self.assertEqual(chain.provisional_branches, (provisional.thesis,))


if __name__ == "__main__":
    unittest.main()

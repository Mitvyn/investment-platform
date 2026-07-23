from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
import json
import subprocess
import unittest

from investment_research_os.evidence_bundles import (
    AuthenticatedOperator,
    InMemoryEvidenceBundleRepository,
)
from investment_research_os.grader_executions import (
    GraderContract,
    GraderExecutionWorkflow,
    InMemoryBudgetLedger,
    InMemoryGraderExecutionRepository,
    PromptContract,
    ProviderTransportError,
    ProviderResponse,
    ProviderUsage,
)
from investment_research_os.research_committees import (
    InMemoryResearchCommitteeRepository,
    MVP_GRADER_ROSTER,
    ResearchCommitteeWorkflow,
)
from tests.test_evidence_bundle_storage import materialized_bundle
from tests.test_grader_execution_workflow import (
    FakeProvider,
    accepted_output,
    aligned_valuation_repository,
    abstained_output,
    approved_request,
)


class FiveGraderDomainContractTests(unittest.TestCase):
    def test_valuation_payload_may_reference_frozen_snapshot_calculation(
        self,
    ) -> None:
        bundle = materialized_bundle()
        request = self._request_for(
            bundle.id,
            grader_id="valuation",
            owned_question=(
                "What outcomes and assumptions justify the current or implied value?"
            ),
        )
        output = self._output_for_request(bundle, request)
        valuation_repository, snapshot = aligned_valuation_repository(bundle)
        current_market_value = output["valuation_payload"]["current_market_value"]
        current_market_value["evidence_ids"] = []
        current_market_value["calculation_ids"] = [
            snapshot.market_capitalization.calculation_id
        ]

        execution = self._execute(
            bundle,
            request,
            output,
            valuation_repository=valuation_repository,
        )

        self.assertEqual(execution.execution_state, "accepted")

    def test_catalyst_grader_accepts_its_versioned_domain_payload(self) -> None:
        bundle = materialized_bundle()
        request = approved_request(bundle.id)
        request = replace(
            request,
            grader=GraderContract(
                grader_id="catalyst",
                grader_version="catalyst-grader-v1",
                grader_contract_version="catalyst-grader-contract-v1",
                owned_decision_question=(
                    "What event resolves uncertainty, when, and with what outcomes?"
                ),
                eligibility_rule_version="catalyst-eligibility-v1",
                rubric_version="catalyst-rubric-v1",
                output_schema_version="catalyst_grader_payload.v1",
                abstention_rule_version="catalyst-abstention-v1",
                required=True,
                eligible=True,
            ),
            prompt=PromptContract(
                prompt_id="catalyst_grader_v1",
                prompt_version="catalyst_grader_v1",
                input_schema_version="grader-input-v1",
                output_schema_version="catalyst_grader_payload.v1",
                active=True,
                evaluation_passed=True,
            ),
        )
        output = deepcopy(accepted_output(bundle.manifest[0].evidence_id))
        output.update(
            {
                "grader_id": request.grader.grader_id,
                "grader_version": request.grader.grader_version,
                "owned_decision_question": (
                    request.grader.owned_decision_question
                ),
            }
        )
        output.pop("moonshot_payload")
        output["catalyst_payload"] = {
            "contract_version": "catalyst_grader_payload.v1",
            "catalyst_definition": "REC-4881 regulatory update",
            "programme": "REC-4881",
            "probability": {
                "value": "0.55",
                "unit": "probability",
                "calculation_method": "scenario_assessment_v1",
                "assumptions": ["Regulatory interaction occurs on schedule."],
                "evidence_ids": [bundle.manifest[0].evidence_id],
                "calculation_ids": [],
            },
            "timing_window": "2026-H2",
            "date_confidence": "medium",
            "success_outcome": "Regulatory path becomes clearer.",
            "delay_outcome": "Update moves beyond stated window.",
            "partial_success_outcome": "Agency requests more evidence.",
            "failure_outcome": "Programme cannot advance as planned.",
        }
        output["proposition"]["stance_rationale"] = (
            "Defined catalyst can resolve programme uncertainty."
        )

        execution = self._execute(bundle, request, output)

        self.assertEqual(execution.execution_state, "accepted")
        self.assertEqual(execution.opinion.grader_id, "catalyst")
        self.assertEqual(
            execution.opinion.domain_payload["contract_version"],
            "catalyst_grader_payload.v1",
        )

    def test_biotech_grader_accepts_its_versioned_domain_payload(self) -> None:
        bundle = materialized_bundle()
        request = self._request_for(
            bundle.id,
            grader_id="biotech",
            owned_question=(
                "Is the scientific and clinical evidence credible?"
            ),
        )
        output = self._base_output(bundle, request)
        output["biotech_payload"] = {
            "contract_version": "biotech_grader_payload.v1",
            "mechanism_plausibility": "credible",
            "preclinical_evidence_quality": "moderate",
            "clinical_evidence_quality": "moderate",
            "trial_design_assessment": "Fit for current phase.",
            "endpoint_relevance": "clinically_meaningful",
            "regulatory_credibility": "credible",
            "claims_exceed_evidence": False,
            "limitations": ["Controlled efficacy evidence remains limited."],
        }

        execution = self._execute(bundle, request, output)

        self.assertEqual(execution.execution_state, "accepted")
        self.assertEqual(execution.opinion.grader_id, "biotech")

    def test_risk_dilution_grader_requires_supported_numeric_values(self) -> None:
        bundle = materialized_bundle()
        request = self._request_for(
            bundle.id,
            grader_id="risk_dilution",
            owned_question=(
                "Can shareholders survive financially until the thesis resolves?"
            ),
        )
        output = self._base_output(bundle, request)
        numeric = self._numeric_value(
            bundle.manifest[0].evidence_id,
            value="24",
            unit="months",
        )
        output["risk_dilution_payload"] = {
            "contract_version": "risk_dilution_grader_payload.v1",
            "cash_runway": numeric,
            "burn_rate": self._numeric_value(
                bundle.manifest[0].evidence_id,
                value="75",
                unit="USD_millions_per_quarter",
            ),
            "going_concern_risk": "moderate",
            "dilution_mechanisms": ["ATM facility"],
            "financing_required_before_catalyst": "possible",
            "downside_mechanisms": ["Catalyst delay increases funding need."],
            "permanent_capital_loss_mechanisms": [
                "Repeated dilution without clinical validation."
            ],
        }

        execution = self._execute(bundle, request, output)

        self.assertEqual(execution.execution_state, "accepted")
        self.assertEqual(execution.opinion.grader_id, "risk_dilution")

    def test_valuation_grader_accepts_four_supported_scenarios(self) -> None:
        bundle = materialized_bundle()
        request = self._request_for(
            bundle.id,
            grader_id="valuation",
            owned_question=(
                "What outcomes and assumptions justify the current or implied value?"
            ),
        )
        output = self._base_output(bundle, request)
        evidence_id = bundle.manifest[0].evidence_id
        scenarios = []
        for index, case in enumerate(
            ("conservative", "base", "bull", "failure"),
            start=1,
        ):
            scenarios.append(
                {
                    "scenario_id": f"valuation-{case}-v1",
                    "case": case,
                    "probability": self._numeric_value(
                        evidence_id,
                        value="0.25",
                        unit="probability",
                    ),
                    "equity_value": self._numeric_value(
                        evidence_id,
                        value=str(index * 500),
                        unit="USD_millions",
                    ),
                    "implied_value_per_diluted_share": self._numeric_value(
                        evidence_id,
                        value=str(index * 2),
                        unit="USD_per_share",
                    ),
                    "assumptions": [f"{case} case programme outcome."],
                }
            )
        output["valuation_payload"] = {
            "contract_version": "valuation_grader_payload.v1",
            "valuation_method": "probability_weighted_scenarios",
            "current_market_value": self._numeric_value(
                evidence_id,
                value="1200",
                unit="USD_millions",
            ),
            "fully_diluted_shares": self._numeric_value(
                evidence_id,
                value="250",
                unit="millions_of_shares",
            ),
            "scenarios": scenarios,
            "sensitivities": ["Catalyst probability", "Future dilution"],
        }

        execution = self._execute(bundle, request, output)

        self.assertEqual(execution.execution_state, "accepted")
        self.assertEqual(len(execution.opinion.domain_payload["scenarios"]), 4)

    def test_committee_runs_exactly_five_isolated_graders_on_same_bundle(
        self,
    ) -> None:
        bundle = materialized_bundle()
        requests = tuple(
            self._request_for(
                bundle.id,
                grader_id=definition.grader_id,
                owned_question=definition.owned_decision_question,
            )
            if definition.grader_id != "moonshot"
            else approved_request(bundle.id)
            for definition in MVP_GRADER_ROSTER
        )
        outputs = tuple(
            self._output_for_request(bundle, request)
            for request in requests
        )
        provider = FakeProvider(
            tuple(
                ProviderResponse(
                    provider_request_id=f"fake-request-{index}",
                    raw_output=output,
                    usage=ProviderUsage(1000, 200, 300, 100, 1300),
                    resolved_model=request.model.model,
                    system_fingerprint="offline-fingerprint-v1",
                )
                for index, (request, output) in enumerate(
                    zip(requests, outputs, strict=True),
                    start=1,
                )
            )
        )
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        execution_repository = InMemoryGraderExecutionRepository()
        grader_workflow = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=execution_repository,
            budget_ledger=InMemoryBudgetLedger(
                hard_limit_usd=Decimal("5.00")
            ),
            provider=provider,
            clock=lambda: datetime(2026, 7, 22, 3, 0, tzinfo=UTC),
        )
        committee_repository = InMemoryResearchCommitteeRepository()
        workflow = ResearchCommitteeWorkflow(
            grader_workflow=grader_workflow,
            evidence_bundle_repository=bundle_repository,
            repository=committee_repository,
            clock=self._committee_clock(),
        )

        committee = workflow.execute(
            AuthenticatedOperator(bundle.operator_id),
            requests,
        )

        self.assertEqual(
            tuple(item.grader_id for item in committee.grader_results),
            tuple(item.grader_id for item in MVP_GRADER_ROSTER),
        )
        self.assertEqual(committee.status, "complete")
        self.assertEqual(committee.accounting.accepted_count, 5)
        self.assertEqual(len(provider.requests), 5)
        bundle_inputs = [
            request.logical_input["bundle"] for request in provider.requests
        ]
        self.assertTrue(all(item == bundle_inputs[0] for item in bundle_inputs))
        for request in provider.requests:
            self.assertNotIn("opinions", request.logical_input)
            self.assertNotIn("grader_results", request.logical_input)
            self.assertNotIn("committee", request.logical_input)
        self.assertEqual(
            committee_repository.persistence_order,
            (
                "moonshot",
                "catalyst",
                "biotech",
                "risk_dilution",
                "valuation",
                "committee",
            ),
        )
        payload = {
            "value": committee.as_dict(),
            "context": {
                "evidenceBundleId": bundle.id,
                "evidenceBundleHash": bundle.content_hash,
                "evidenceIds": [
                    item.evidence_id for item in bundle.manifest
                ],
                "calculationIds": [
                    item.snapshot_id for item in bundle.metrics
                ],
            },
        }
        result = subprocess.run(
            [
                "node",
                "--experimental-strip-types",
                "--input-type=module",
                "--eval",
                (
                    "import { parseCommitteeState } from "
                    "'./packages/types/committee.ts';"
                    "let input=''; for await (const chunk of process.stdin) "
                    "input += chunk; const payload=JSON.parse(input); "
                    "parseCommitteeState(payload.value,payload.context);"
                ),
            ],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_not_eligible_is_stored_without_provider_execution_or_stance(
        self,
    ) -> None:
        bundle = materialized_bundle()
        requests = list(self._committee_requests(bundle.id))
        requests[1] = replace(
            requests[1],
            grader=replace(requests[1].grader, eligible=False),
        )
        eligible_requests = [
            request for request in requests if request.grader.eligible
        ]
        provider = FakeProvider(
            tuple(
                ProviderResponse(
                    provider_request_id=f"fake-request-{index}",
                    raw_output=self._output_for_request(bundle, request),
                    usage=ProviderUsage(1000, 200, 300, 100, 1300),
                    resolved_model=request.model.model,
                    system_fingerprint="offline-fingerprint-v1",
                )
                for index, request in enumerate(
                    eligible_requests,
                    start=1,
                )
            )
        )

        committee = self._committee_workflow(bundle, provider).execute(
            AuthenticatedOperator(bundle.operator_id),
            tuple(requests),
        )

        catalyst = committee.grader_results[1]
        self.assertEqual(catalyst.execution_state, "not_eligible")
        self.assertIsNone(catalyst.execution)
        self.assertIsNone(catalyst.opinion)
        self.assertIsNone(catalyst.stance)
        self.assertEqual(catalyst.reason_code, "grader_not_eligible")
        self.assertEqual(committee.accounting.not_eligible_count, 1)
        self.assertEqual(committee.accounting.eligible_count, 4)
        self.assertEqual(committee.status, "complete")
        self.assertEqual(len(provider.requests), 4)

    def test_all_not_eligible_derives_insufficient_without_model_calls(
        self,
    ) -> None:
        bundle = materialized_bundle()
        requests = tuple(
            replace(request, grader=replace(request.grader, eligible=False))
            for request in self._committee_requests(bundle.id)
        )
        provider = FakeProvider(())

        committee = self._committee_workflow(bundle, provider).execute(
            AuthenticatedOperator(bundle.operator_id),
            requests,
        )

        self.assertEqual(
            committee.status,
            "insufficient_accepted_opinions",
        )
        self.assertEqual(committee.accounting.eligible_count, 0)
        self.assertEqual(committee.accounting.not_eligible_count, 5)
        self.assertEqual(len(provider.requests), 0)

    def test_abstention_is_separate_from_directional_agreement(self) -> None:
        bundle = materialized_bundle()
        requests = self._committee_requests(bundle.id)
        responses = []
        for index, request in enumerate(requests, start=1):
            output = self._output_for_request(bundle, request)
            if request.grader.grader_id == "moonshot":
                output = abstained_output(bundle.manifest[0].evidence_id)
            responses.append(
                ProviderResponse(
                    provider_request_id=f"fake-request-{index}",
                    raw_output=output,
                    usage=ProviderUsage(1000, 200, 300, 100, 1300),
                    resolved_model=request.model.model,
                    system_fingerprint="offline-fingerprint-v1",
                )
            )

        committee = self._committee_workflow(
            bundle,
            FakeProvider(tuple(responses)),
        ).execute(
            AuthenticatedOperator(bundle.operator_id),
            requests,
        )

        self.assertEqual(committee.status, "complete_with_abstentions")
        self.assertEqual(committee.accounting.accepted_count, 4)
        self.assertEqual(committee.accounting.abstained_count, 1)
        self.assertEqual(committee.accounting.supports_count, 4)
        self.assertIsNone(committee.grader_results[0].stance)

    def test_required_grader_failure_degrades_committee_without_opinion(
        self,
    ) -> None:
        bundle = materialized_bundle()
        requests = self._committee_requests(bundle.id)
        responses = []
        for index, request in enumerate(requests, start=1):
            if request.grader.grader_id == "catalyst":
                responses.extend(
                    (
                        ProviderTransportError("timeout"),
                        ProviderTransportError("timeout"),
                    )
                )
                continue
            responses.append(
                ProviderResponse(
                    provider_request_id=f"fake-request-{index}",
                    raw_output=self._output_for_request(bundle, request),
                    usage=ProviderUsage(1000, 200, 300, 100, 1300),
                    resolved_model=request.model.model,
                    system_fingerprint="offline-fingerprint-v1",
                )
            )

        committee = self._committee_workflow(
            bundle,
            FakeProvider(tuple(responses)),
        ).execute(
            AuthenticatedOperator(bundle.operator_id),
            requests,
        )

        catalyst = committee.grader_results[1]
        self.assertEqual(catalyst.execution_state, "failed")
        self.assertIsNone(catalyst.opinion)
        self.assertIsNone(catalyst.stance)
        self.assertEqual(
            committee.status,
            "incomplete_required_grader_failed",
        )
        self.assertEqual(committee.accounting.failed_count, 1)
        self.assertEqual(committee.accounting.accepted_count, 4)

    def test_pre_call_block_remains_not_executed_and_insufficient(self) -> None:
        bundle = materialized_bundle()
        requests = list(self._committee_requests(bundle.id))
        requests[2] = replace(
            requests[2],
            model=replace(requests[2].model, active=False),
        )
        executable_requests = [
            request for request in requests if request.model.active
        ]
        provider = FakeProvider(
            tuple(
                ProviderResponse(
                    provider_request_id=f"fake-request-{index}",
                    raw_output=self._output_for_request(bundle, request),
                    usage=ProviderUsage(1000, 200, 300, 100, 1300),
                    resolved_model=request.model.model,
                    system_fingerprint="offline-fingerprint-v1",
                )
                for index, request in enumerate(
                    executable_requests,
                    start=1,
                )
            )
        )

        committee = self._committee_workflow(bundle, provider).execute(
            AuthenticatedOperator(bundle.operator_id),
            tuple(requests),
        )

        biotech = committee.grader_results[2]
        self.assertEqual(biotech.execution_state, "not_executed")
        self.assertEqual(biotech.reason_code, "model_config_inactive")
        self.assertIsNone(biotech.stance)
        self.assertEqual(
            committee.status,
            "insufficient_accepted_opinions",
        )
        self.assertEqual(committee.accounting.not_executed_count, 1)
        self.assertEqual(len(provider.requests), 4)

    def test_common_envelope_rejects_unknown_confidence(self) -> None:
        bundle = materialized_bundle()
        request = approved_request(bundle.id)
        output = accepted_output(bundle.manifest[0].evidence_id)
        output["confidence"] = "very_high"
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        response = ProviderResponse(
            provider_request_id="fake-invalid-confidence",
            raw_output=output,
            usage=ProviderUsage(1000, 200, 300, 100, 1300),
            resolved_model=request.model.model,
            system_fingerprint="offline-fingerprint-v1",
        )
        workflow = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=InMemoryGraderExecutionRepository(),
            budget_ledger=InMemoryBudgetLedger(
                hard_limit_usd=Decimal("1.00")
            ),
            provider=FakeProvider((response, response)),
            clock=lambda: datetime(2026, 7, 22, 3, 0, tzinfo=UTC),
        )

        execution = workflow.execute(
            AuthenticatedOperator(bundle.operator_id),
            request,
        )

        self.assertEqual(execution.execution_state, "failed")
        self.assertIn(
            "contract_validation_failed",
            execution.failure.validation_errors,
        )

    def test_common_envelope_rejects_non_list_assumptions(self) -> None:
        bundle = materialized_bundle()
        request = approved_request(bundle.id)
        output = accepted_output(bundle.manifest[0].evidence_id)
        output["assumptions"] = "Clinical translation remains uncertain."
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        response = ProviderResponse(
            provider_request_id="fake-invalid-assumptions",
            raw_output=output,
            usage=ProviderUsage(1000, 200, 300, 100, 1300),
            resolved_model=request.model.model,
            system_fingerprint="offline-fingerprint-v1",
        )
        workflow = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=InMemoryGraderExecutionRepository(),
            budget_ledger=InMemoryBudgetLedger(
                hard_limit_usd=Decimal("1.00")
            ),
            provider=FakeProvider((response, response)),
            clock=lambda: datetime(2026, 7, 22, 3, 0, tzinfo=UTC),
        )

        execution = workflow.execute(
            AuthenticatedOperator(bundle.operator_id),
            request,
        )

        self.assertEqual(execution.execution_state, "failed")

    def test_common_envelope_rejects_claim_contract_extensions(self) -> None:
        bundle = materialized_bundle()
        request = approved_request(bundle.id)
        output = accepted_output(bundle.manifest[0].evidence_id)
        output["material_claims"][0]["universal_score"] = 90
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        response = ProviderResponse(
            provider_request_id="fake-invalid-claim",
            raw_output=output,
            usage=ProviderUsage(1000, 200, 300, 100, 1300),
            resolved_model=request.model.model,
            system_fingerprint="offline-fingerprint-v1",
        )
        workflow = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=InMemoryGraderExecutionRepository(),
            budget_ledger=InMemoryBudgetLedger(
                hard_limit_usd=Decimal("1.00")
            ),
            provider=FakeProvider((response, response)),
            clock=lambda: datetime(2026, 7, 22, 3, 0, tzinfo=UTC),
        )

        execution = workflow.execute(
            AuthenticatedOperator(bundle.operator_id),
            request,
        )

        self.assertEqual(execution.execution_state, "failed")

    def test_agreement_counts_only_accepted_proposition_stances(self) -> None:
        bundle = materialized_bundle()
        requests = self._committee_requests(bundle.id)
        stances = {
            "moonshot": "supports",
            "catalyst": "mixed",
            "biotech": "supports",
            "risk_dilution": "challenges",
            "valuation": "challenges",
        }
        responses = []
        for index, request in enumerate(requests, start=1):
            output = self._output_for_request(bundle, request)
            stance = stances[request.grader.grader_id]
            output["stance"] = stance
            output["proposition"]["grader_stance"] = stance
            responses.append(
                ProviderResponse(
                    provider_request_id=f"fake-request-{index}",
                    raw_output=output,
                    usage=ProviderUsage(1000, 200, 300, 100, 1300),
                    resolved_model=request.model.model,
                    system_fingerprint="offline-fingerprint-v1",
                )
            )

        committee = self._committee_workflow(
            bundle,
            FakeProvider(tuple(responses)),
        ).execute(
            AuthenticatedOperator(bundle.operator_id),
            requests,
        )

        self.assertEqual(committee.accounting.supports_count, 2)
        self.assertEqual(committee.accounting.mixed_count, 1)
        self.assertEqual(committee.accounting.challenges_count, 2)
        self.assertEqual(committee.accounting.accepted_count, 5)

    def test_identical_committee_request_reuses_persisted_result(self) -> None:
        bundle = materialized_bundle()
        requests = self._committee_requests(bundle.id)
        provider = FakeProvider(
            tuple(
                ProviderResponse(
                    provider_request_id=f"fake-request-{index}",
                    raw_output=self._output_for_request(bundle, request),
                    usage=ProviderUsage(1000, 200, 300, 100, 1300),
                    resolved_model=request.model.model,
                    system_fingerprint="offline-fingerprint-v1",
                )
                for index, request in enumerate(requests, start=1)
            )
        )
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        grader_repository = InMemoryGraderExecutionRepository()
        committee_repository = InMemoryResearchCommitteeRepository()
        workflow = ResearchCommitteeWorkflow(
            grader_workflow=GraderExecutionWorkflow(
                evidence_bundle_repository=bundle_repository,
                execution_repository=grader_repository,
                budget_ledger=InMemoryBudgetLedger(
                    hard_limit_usd=Decimal("5.00")
                ),
                provider=provider,
                clock=lambda: datetime(2026, 7, 22, 3, 0, tzinfo=UTC),
            ),
            evidence_bundle_repository=bundle_repository,
            repository=committee_repository,
            clock=self._committee_clock(),
        )

        first = workflow.execute(
            AuthenticatedOperator(bundle.operator_id),
            requests,
        )
        second = workflow.execute(
            AuthenticatedOperator(bundle.operator_id),
            requests,
        )

        self.assertIs(second, first)
        self.assertEqual(len(provider.requests), 5)
        self.assertEqual(len(committee_repository.persistence_order), 6)

    def _request_for(self, bundle_id, *, grader_id, owned_question):
        request = approved_request(bundle_id)
        schema_version = f"{grader_id}_grader_payload.v1"
        return replace(
            request,
            grader=GraderContract(
                grader_id=grader_id,
                grader_version=f"{grader_id}-grader-v1",
                grader_contract_version=f"{grader_id}-grader-contract-v1",
                owned_decision_question=owned_question,
                eligibility_rule_version=f"{grader_id}-eligibility-v1",
                rubric_version=f"{grader_id}-rubric-v1",
                output_schema_version=schema_version,
                abstention_rule_version=f"{grader_id}-abstention-v1",
                required=True,
                eligible=True,
            ),
            prompt=PromptContract(
                prompt_id=f"{grader_id}_grader_v1",
                prompt_version=f"{grader_id}_grader_v1",
                input_schema_version="grader-input-v1",
                output_schema_version=schema_version,
                active=True,
                evaluation_passed=True,
            ),
        )

    def _base_output(self, bundle, request):
        output = deepcopy(accepted_output(bundle.manifest[0].evidence_id))
        output.update(
            {
                "grader_id": request.grader.grader_id,
                "grader_version": request.grader.grader_version,
                "owned_decision_question": (
                    request.grader.owned_decision_question
                ),
            }
        )
        output.pop("moonshot_payload")
        output["proposition"]["stance_rationale"] = (
            "Domain evidence supports continued research."
        )
        return output

    def _committee_requests(self, bundle_id):
        return tuple(
            self._request_for(
                bundle_id,
                grader_id=definition.grader_id,
                owned_question=definition.owned_decision_question,
            )
            if definition.grader_id != "moonshot"
            else approved_request(bundle_id)
            for definition in MVP_GRADER_ROSTER
        )

    def _committee_workflow(self, bundle, provider):
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        grader_workflow = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=InMemoryGraderExecutionRepository(),
            budget_ledger=InMemoryBudgetLedger(
                hard_limit_usd=Decimal("5.00")
            ),
            provider=provider,
            clock=lambda: datetime(2026, 7, 22, 3, 0, tzinfo=UTC),
        )
        return ResearchCommitteeWorkflow(
            grader_workflow=grader_workflow,
            evidence_bundle_repository=bundle_repository,
            repository=InMemoryResearchCommitteeRepository(),
            clock=self._committee_clock(),
        )

    def _committee_clock(self):
        times = iter(
            (
                datetime(2026, 7, 22, 3, 1, tzinfo=UTC),
                datetime(2026, 7, 22, 3, 2, tzinfo=UTC),
            )
        )
        return lambda: next(times)

    def _numeric_value(self, evidence_id, *, value, unit):
        return {
            "value": value,
            "unit": unit,
            "calculation_method": "deterministic_snapshot_v1",
            "assumptions": ["Reported balance remains available."],
            "evidence_ids": [evidence_id],
            "calculation_ids": [],
        }

    def _output_for_request(self, bundle, request):
        if request.grader.grader_id == "moonshot":
            return accepted_output(bundle.manifest[0].evidence_id)
        output = self._base_output(bundle, request)
        evidence_id = bundle.manifest[0].evidence_id
        if request.grader.grader_id == "catalyst":
            output["catalyst_payload"] = {
                "contract_version": "catalyst_grader_payload.v1",
                "catalyst_definition": "REC-4881 regulatory update",
                "programme": "REC-4881",
                "probability": self._numeric_value(
                    evidence_id,
                    value="0.55",
                    unit="probability",
                ),
                "timing_window": "2026-H2",
                "date_confidence": "medium",
                "success_outcome": "Regulatory path becomes clearer.",
                "delay_outcome": "Update moves beyond stated window.",
                "partial_success_outcome": "Agency requests more evidence.",
                "failure_outcome": "Programme cannot advance as planned.",
            }
        elif request.grader.grader_id == "biotech":
            output["biotech_payload"] = {
                "contract_version": "biotech_grader_payload.v1",
                "mechanism_plausibility": "credible",
                "preclinical_evidence_quality": "moderate",
                "clinical_evidence_quality": "moderate",
                "trial_design_assessment": "Fit for current phase.",
                "endpoint_relevance": "clinically_meaningful",
                "regulatory_credibility": "credible",
                "claims_exceed_evidence": False,
                "limitations": ["Controlled efficacy evidence is limited."],
            }
        elif request.grader.grader_id == "risk_dilution":
            output["risk_dilution_payload"] = {
                "contract_version": "risk_dilution_grader_payload.v1",
                "cash_runway": self._numeric_value(
                    evidence_id,
                    value="24",
                    unit="months",
                ),
                "burn_rate": self._numeric_value(
                    evidence_id,
                    value="75",
                    unit="USD_millions_per_quarter",
                ),
                "going_concern_risk": "moderate",
                "dilution_mechanisms": ["ATM facility"],
                "financing_required_before_catalyst": "possible",
                "downside_mechanisms": ["Catalyst delay"],
                "permanent_capital_loss_mechanisms": ["Repeated dilution"],
            }
        else:
            output["valuation_payload"] = {
                "contract_version": "valuation_grader_payload.v1",
                "valuation_method": "probability_weighted_scenarios",
                "current_market_value": self._numeric_value(
                    evidence_id,
                    value="1200",
                    unit="USD_millions",
                ),
                "fully_diluted_shares": self._numeric_value(
                    evidence_id,
                    value="250",
                    unit="millions_of_shares",
                ),
                "scenarios": [
                    {
                        "scenario_id": f"valuation-{case}-v1",
                        "case": case,
                        "probability": self._numeric_value(
                            evidence_id,
                            value="0.25",
                            unit="probability",
                        ),
                        "equity_value": self._numeric_value(
                            evidence_id,
                            value=str(index * 500),
                            unit="USD_millions",
                        ),
                        "implied_value_per_diluted_share": (
                            self._numeric_value(
                                evidence_id,
                                value=str(index * 2),
                                unit="USD_per_share",
                            )
                        ),
                        "assumptions": [f"{case} outcome."],
                    }
                    for index, case in enumerate(
                        ("conservative", "base", "bull", "failure"),
                        start=1,
                    )
                ],
                "sensitivities": ["Catalyst probability"],
            }
        return output

    def _execute(
        self,
        bundle,
        request,
        output,
        *,
        valuation_repository=None,
    ):
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        provider = FakeProvider(
            (
                ProviderResponse(
                    provider_request_id="fake-request-1",
                    raw_output=output,
                    usage=ProviderUsage(
                        input_tokens=1000,
                        cached_input_tokens=200,
                        output_tokens=300,
                        reasoning_tokens=100,
                        total_tokens=1300,
                    ),
                    resolved_model=request.model.model,
                    system_fingerprint="offline-fingerprint-v1",
                ),
            )
        )
        workflow = GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=valuation_repository,
            execution_repository=InMemoryGraderExecutionRepository(),
            budget_ledger=InMemoryBudgetLedger(
                hard_limit_usd=Decimal("1.00")
            ),
            provider=provider,
            clock=lambda: datetime(2026, 7, 22, 3, 0, tzinfo=UTC),
        )
        return workflow.execute(
            AuthenticatedOperator(bundle.operator_id),
            request,
        )


def completed_committee_fixture():
    helper = FiveGraderDomainContractTests()
    bundle = materialized_bundle()
    requests = helper._committee_requests(bundle.id)
    provider = FakeProvider(
        tuple(
            ProviderResponse(
                provider_request_id=f"fake-request-{index}",
                raw_output=helper._output_for_request(bundle, request),
                usage=ProviderUsage(1000, 200, 300, 100, 1300),
                resolved_model=request.model.model,
                system_fingerprint="offline-fingerprint-v1",
            )
            for index, request in enumerate(requests, start=1)
        )
    )
    bundle_repository = InMemoryEvidenceBundleRepository()
    bundle_repository.save(bundle)
    committee_repository = InMemoryResearchCommitteeRepository()
    workflow = ResearchCommitteeWorkflow(
        grader_workflow=GraderExecutionWorkflow(
            evidence_bundle_repository=bundle_repository,
            execution_repository=InMemoryGraderExecutionRepository(),
            budget_ledger=InMemoryBudgetLedger(
                hard_limit_usd=Decimal("5.00")
            ),
            provider=provider,
            clock=lambda: datetime(2026, 7, 22, 3, 0, tzinfo=UTC),
        ),
        evidence_bundle_repository=bundle_repository,
        repository=committee_repository,
        clock=helper._committee_clock(),
    )
    committee = workflow.execute(
        AuthenticatedOperator(bundle.operator_id),
        requests,
    )
    return bundle, committee, bundle_repository, committee_repository


if __name__ == "__main__":
    unittest.main()

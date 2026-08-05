from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from threading import Barrier
import time
from typing import Mapping
import unittest
from uuid import NAMESPACE_URL, uuid5

from investment_research_os.evidence_bundles import (
    EvidenceBundleCandidate,
    EvidenceItem,
)
from investment_research_os.grader_executions import (
    ProviderTransportError,
    ProviderResponse,
    ProviderUsage,
)
from investment_research_os.research_runs import (
    AuthenticatedOperator,
    CatalystCandidate,
    EvidenceReference,
    SecurityEligibilitySnapshot,
)
from investment_research_os.research_workflows import (
    BiotechResearchCommitteeWorkflow,
    BiotechResearchRequest,
    BiotechResearchWorkflowError,
    build_offline_mvp_config,
)
from investment_research_os.valuation_snapshots import (
    CapitalStructureInput,
    CorporateActionReconciliation,
    DilutionInstrument,
    MarketSession,
    MaterialityAssessment,
    PriceObservation,
    ValuationInputCandidate,
    ValuationSourceReference,
)


FIXTURE_ROOT = Path("tests/fixtures/offline_workflow")
OPERATOR_ID = "8ed47ebc-d5cf-40ad-80ce-d4d803f7c735"
RULE_IDS = (
    "security_identity_verified",
    "us_listing",
    "cik_match",
    "common_equity",
    "operating_company",
    "therapeutics_classification",
    "active_therapeutic_program",
    "defined_clinical_or_regulatory_catalyst",
    "required_primary_source_coverage",
)
SOURCE_CLASSES = ("sec", "issuer", "clinical", "regulatory", "financing")


def _fixture(name: str) -> dict[str, object]:
    value = json.loads((FIXTURE_ROOT / name).read_text())
    if value.get("fixture_contract") != "offline_biotech_fixture.v1":
        raise AssertionError("unsupported offline fixture")
    return value


def _stable_uuid(case_id: str, value: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"iros-offline:{case_id}:{value}"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _shape(value: object) -> object:
    if isinstance(value, dict):
        return {key: _shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [_shape(value[0])] if value else []
    return type(value).__name__


class IncrementingClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 7, 22, 1, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        value = self.current
        self.current += timedelta(seconds=1)
        return value


class FixtureEligibilitySource:
    def __init__(self, value: Mapping[str, object]) -> None:
        self.value = value

    def load(
        self,
        operator_id: str,
        security_id: str,
        as_of_cutoff: datetime,
    ):
        security = self.value["security"]
        case_id = str(self.value["case_id"])
        evidence = {
            rule_id: EvidenceReference(
                evidence_id=_stable_uuid(case_id, f"eligibility:{rule_id}"),
                available_at=as_of_cutoff - timedelta(days=1),
            )
            for rule_id in RULE_IDS
        }
        return SecurityEligibilitySnapshot(
            security_id=security_id,
            as_of_cutoff=as_of_cutoff,
            issuer_name=str(security["issuer_name"]),
            display_symbol=str(security["symbol"]),
            security_identity_verified=True,
            primary_listing_country="US",
            primary_listing_exchange=str(security["exchange"]),
            cik=str(security["cik"]),
            cik_matches_issuer=True,
            security_type="common_equity",
            issuer_status="operating",
            therapeutics_classification="therapeutics_biotech",
            active_therapeutic_programs=(str(self.value["program"]),),
            catalysts=(
                CatalystCandidate(
                    event=str(self.value["catalyst"]),
                    program=str(self.value["program"]),
                    basis=str(self.value["catalyst_basis"]),
                    window_start="2026-10-01",
                    window_end="2026-12-31",
                ),
            ),
            primary_source_coverage=frozenset(
                {
                    "sec_issuer_security",
                    "required_sec_filings",
                    "issuer_pipeline",
                    "authoritative_trial",
                    "us_regulatory",
                    "financing_share_capital",
                }
            ),
            evidence_by_rule=evidence,
        )


def _evidence_items(value: Mapping[str, object]) -> tuple[EvidenceItem, ...]:
    case_id = str(value["case_id"])
    cutoff = datetime.fromisoformat(str(value["cutoff"]))
    seed = str(value["evidence_seed"])
    return tuple(
        EvidenceItem(
            evidence_id=_stable_uuid(case_id, f"evidence:{source_class}"),
            evidence_version_id=_stable_uuid(
                case_id,
                f"evidence-version:{source_class}",
            ),
            provenance_type="primary_source",
            item_kind="passage",
            source_class=source_class,
            source_locator=f"{source_class} primary record",
            canonical_url=f"https://example.com/{case_id}/{source_class}",
            publication_at=cutoff - timedelta(days=1),
            retrieved_at=cutoff + timedelta(hours=1),
            effective_at=cutoff - timedelta(days=1),
            filing_period_start=None,
            filing_period_end=None,
            content_hash=_sha256(f"{seed}:{source_class}:document"),
            passage_id=_stable_uuid(case_id, f"passage:{source_class}"),
            passage_hash=_sha256(f"{seed}:{source_class}:passage"),
            freshness="current",
            passage_text=f"{seed}:{source_class}:passage",
        )
        for source_class in SOURCE_CLASSES
    )


class FixtureEvidenceSource:
    def __init__(self, value: Mapping[str, object]) -> None:
        self.value = value

    def load(
        self,
        operator_id: str,
        security_id: str,
        as_of_cutoff: datetime,
    ):
        return EvidenceBundleCandidate(
            security_id=security_id,
            as_of_cutoff=as_of_cutoff,
            evidence_policy_version="biotech-primary-evidence-v1",
            freshness_policy_version="biotech-evidence-freshness-v1",
            items=_evidence_items(self.value),
        )


class FixtureMarketCalendar:
    def __init__(self, value: Mapping[str, object]) -> None:
        cutoff = datetime.fromisoformat(str(value["cutoff"]))
        security = value["security"]
        self.session = MarketSession(
            session_date=cutoff.date(),
            opens_at=cutoff.replace(hour=13, minute=30, second=0),
            closes_at=cutoff.replace(hour=20, minute=0, second=0),
            session_type="regular_us_trading_session",
            primary_listing_exchange=str(security["exchange"]),
            early_close=False,
            calendar_version="us-equities-calendar-v1",
        )

    def latest_completed_session(self, primary_listing_exchange: str, cutoff: datetime):
        return self.session


class FixtureValuationSource:
    def __init__(
        self,
        value: Mapping[str, object],
        session: MarketSession,
    ) -> None:
        self.value = value
        self.session = session

    def load(self, bundle, session: MarketSession):
        case_id = str(self.value["case_id"])
        security = self.value["security"]
        valuation = self.value["valuation"]
        items = _evidence_items(self.value)
        evidence_ids = {item.source_class: item.evidence_id for item in items}
        basic = Decimal(str(valuation["basic_shares"]))
        diluted = Decimal(str(valuation["fully_diluted_shares"]))
        increment = diluted - basic
        capital_effective_at = datetime(2026, 3, 31, 23, 59, 59, tzinfo=UTC)
        return ValuationInputCandidate(
            security_id=bundle.security_id,
            evidence_bundle_id=bundle.id,
            evidence_bundle_hash=bundle.content_hash,
            market_session=session,
            prices=(
                PriceObservation(
                    price_type="official_unadjusted_close",
                    session_type="regular_us_trading_session",
                    session_date=session.session_date,
                    primary_listing_exchange=str(security["exchange"]),
                    price=str(valuation["price"]),
                    currency="USD",
                    official_close_timestamp=session.closes_at,
                    market_status="closed",
                    corporate_action_adjustment_status="unadjusted",
                    provider="licensed-market-fake",
                    source_reference="market-close-source",
                ),
            ),
            capital=CapitalStructureInput(
                basic_shares_outstanding=str(valuation["basic_shares"]),
                fully_diluted_shares=str(valuation["fully_diluted_shares"]),
                cash=str(valuation["cash"]),
                restricted_cash="0",
                restricted_cash_treatment="none",
                debt=str(valuation["debt"]),
                other_included_claims="0",
                included_cash=str(valuation["cash"]),
                currency="USD",
                basic_shares_effective_at=capital_effective_at,
                fully_diluted_shares_effective_at=capital_effective_at,
                cash_effective_at=capital_effective_at,
                restricted_cash_effective_at=capital_effective_at,
                included_cash_effective_at=capital_effective_at,
                debt_effective_at=capital_effective_at,
                other_included_claims_effective_at=capital_effective_at,
                basic_shares_evidence_ids=(evidence_ids["sec"],),
                diluted_shares_evidence_ids=(evidence_ids["financing"],),
                cash_evidence_ids=(evidence_ids["financing"],),
                restricted_cash_evidence_ids=(evidence_ids["financing"],),
                debt_evidence_ids=(evidence_ids["financing"],),
                other_included_claims_evidence_ids=(evidence_ids["financing"],),
                dilution_instruments=(
                    DilutionInstrument(
                        instrument_id="fixture-dilution",
                        instrument_type="options",
                        diluted_share_increment=format(increment, "f"),
                        effective_at=datetime(2026, 3, 31, 23, 59, tzinfo=UTC),
                        supporting_evidence_ids=(evidence_ids["financing"],),
                    ),
                ),
            ),
            corporate_action=CorporateActionReconciliation(
                event_id=None,
                action_type="none",
                effective_at=None,
                price_adjustment_status="unadjusted",
                share_count_adjustment_status="unadjusted",
                reconciliation_result="not_required",
            ),
            materiality_assessments=tuple(
                MaterialityAssessment(
                    evidence_id=item.evidence_id,
                    publication_at=session.closes_at - timedelta(hours=1),
                    market_materiality="material",
                    materiality_reason_code="available_before_close",
                    affected_domains=("valuation",),
                    policy_version="biotech-market-materiality-v1",
                )
                for item in items
            ),
            valuation_policy_version="biotech-valuation-snapshot-v1",
            materiality_policy_version="biotech-market-materiality-v1",
            source_references=(
                ValuationSourceReference(
                    source_reference_id="market-close-source",
                    source_type="licensed_market_data",
                    provider="licensed-market-fake",
                    locator=f"{case_id} official close",
                    published_at=session.closes_at,
                    retrieved_at=bundle.as_of_cutoff + timedelta(hours=1),
                    effective_at=session.closes_at,
                ),
            ),
        )


def _numeric(
    value: str,
    unit: str,
    evidence_id: str,
    calculation_id: str | None = None,
) -> dict[str, object]:
    return {
        "value": value,
        "unit": unit,
        "calculation_method": "deterministic_snapshot_v1",
        "assumptions": ["Fixture primary evidence remains valid at cutoff."],
        "evidence_ids": [evidence_id],
        "calculation_ids": [] if calculation_id is None else [calculation_id],
    }


class FixtureGraderProvider:
    def __init__(
        self,
        value: Mapping[str, object],
        execution_states: Mapping[str, str] | None = None,
        delay_seconds: float = 0,
    ) -> None:
        self.value = value
        self.execution_states = dict(execution_states or {})
        self.delay_seconds = delay_seconds
        self.requests = []

    def audit_request(self, request):
        return request.as_dict()

    def execute(self, request):
        self.requests.append(request)
        grader_id = str(request.logical_input["grader"]["grader_id"])
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        if self.execution_states.get(grader_id) == "failed":
            raise ProviderTransportError("offline_timeout")
        bundle = request.logical_input["bundle"]
        evidence_id = str(bundle["manifest"][0]["item_id"])
        analysis = self.value["analysis"]
        output = self._common_output(grader_id, evidence_id, analysis)
        if self.execution_states.get(grader_id) == "abstained":
            output["execution_state"] = "abstained"
            output["stance"] = None
            output["material_claims"] = []
            output["proposition"]["grader_stance"] = None
            output["proposition"]["stance_rationale"] = None
            output["abstention"] = {
                "reason_code": "insufficient_primary_evidence",
                "reason": "Frozen evidence cannot support a defensible verdict.",
                "missing_or_inadequate_evidence": ["Mature primary results"],
                "evidence_required": ["Primary results with defined endpoints"],
                "confidence": "high",
            }
        output[f"{grader_id}_payload"] = self._domain_payload(
            grader_id,
            evidence_id,
            analysis,
            request.logical_input["valuation_snapshot"],
        )
        return ProviderResponse(
            provider_request_id=f"offline-{self.value['case_id']}-{grader_id}",
            raw_output=output,
            usage=ProviderUsage(1000, 200, 300, 100, 1300),
            resolved_model=request.model,
            system_fingerprint="offline-fixture-provider-v1",
        )

    def _common_output(self, grader_id, evidence_id, analysis):
        questions = {
            "moonshot": "Is the opportunity meaningfully asymmetric?",
            "catalyst": (
                "What event resolves uncertainty, when, and with what outcomes?"
            ),
            "biotech": "Is the scientific and clinical evidence credible?",
            "risk_dilution": (
                "Can shareholders survive financially until the thesis resolves?"
            ),
            "valuation": (
                "What outcomes and assumptions justify the current or implied value?"
            ),
        }
        stance = str(analysis["stance"])
        return {
            "execution_state": "accepted",
            "grader_id": grader_id,
            "grader_version": f"{grader_id}-grader-v1",
            "owned_decision_question": questions[grader_id],
            "stance": stance,
            "confidence": str(analysis["confidence"]),
            "summary": str(analysis["claim"]),
            "material_claims": [
                {
                    "claim_id": f"{grader_id}-claim-1",
                    "claim": str(analysis["claim"]),
                    "materiality": "high",
                    "evidence_ids": [evidence_id],
                }
            ],
            "assumptions": ["Primary evidence remains valid at cutoff."],
            "contradicting_evidence": [],
            "evidence_gaps": [
                {
                    "gap_id": f"{grader_id}-gap-1",
                    "description": "Further primary evidence can reduce uncertainty.",
                    "required_evidence": "Next primary-source catalyst update.",
                }
            ],
            "invalidation_signals": ["Thesis-critical catalyst fails."],
            "proposition": {
                "proposition_id": "biotech_moonshot_catalyst_case",
                "proposition_version": "biotech_moonshot_catalyst_case.v1",
                "rendered_proposition_text": (
                    "As of the cutoff, the available evidence supports a credible "
                    "Moonshot research case with an identifiable catalyst capable of "
                    "materially resolving uncertainty."
                ),
                "grader_stance": stance,
                "stance_rationale": str(analysis["stance_rationale"]),
            },
            "abstention": None,
        }

    def _domain_payload(self, grader_id, evidence_id, analysis, valuation):
        domain = analysis[grader_id]
        if grader_id == "moonshot":
            return {"contract_version": "moonshot_grader_payload.v1", **domain}
        if grader_id == "catalyst":
            return {
                "contract_version": "catalyst_grader_payload.v1",
                "catalyst_definition": str(self.value["catalyst"]),
                "programme": str(self.value["program"]),
                "probability": _numeric(
                    str(domain["probability"]), "probability", evidence_id
                ),
                "timing_window": str(domain["timing_window"]),
                "date_confidence": str(domain["date_confidence"]),
                "success_outcome": "Catalyst supports programme advancement.",
                "delay_outcome": "Catalyst moves beyond the stated window.",
                "partial_success_outcome": (
                    "Catalyst resolves only part of uncertainty."
                ),
                "failure_outcome": "Programme cannot advance as planned.",
            }
        if grader_id == "biotech":
            return {
                "contract_version": "biotech_grader_payload.v1",
                **domain,
                "trial_design_assessment": "Design is assessed for its current phase.",
                "limitations": ["Controlled efficacy evidence remains limited."],
            }
        if grader_id == "risk_dilution":
            return {
                "contract_version": "risk_dilution_grader_payload.v1",
                "cash_runway": _numeric(
                    str(domain["runway_months"]), "months", evidence_id
                ),
                "burn_rate": _numeric(
                    str(domain["burn_rate"]),
                    "USD_millions_per_quarter",
                    evidence_id,
                ),
                "going_concern_risk": str(domain["going_concern_risk"]),
                "dilution_mechanisms": ["Equity financing"],
                "financing_required_before_catalyst": str(
                    domain["financing_required_before_catalyst"]
                ),
                "downside_mechanisms": ["Catalyst delay"],
                "permanent_capital_loss_mechanisms": ["Repeated dilution"],
            }
        calculation_ids = valuation["calculation_ids"]
        market_cap = valuation["market_capitalization"]
        diluted = valuation["fully_diluted_shares"]
        cases = ("conservative", "base", "bull", "failure")
        return {
            "contract_version": "valuation_grader_payload.v1",
            "valuation_method": str(domain["method"]),
            "current_market_value": _numeric(
                str(market_cap["value"]),
                str(market_cap["unit"]),
                evidence_id,
                str(market_cap["calculation_id"]),
            ),
            "fully_diluted_shares": _numeric(
                str(diluted["value"]),
                str(diluted["unit"]),
                evidence_id,
                str(calculation_ids[0]),
            ),
            "scenarios": [
                {
                    "scenario_id": f"valuation-{case}-v1",
                    "case": case,
                    "probability": _numeric("0.25", "probability", evidence_id),
                    "equity_value": _numeric(
                        str((index + 1) * 100000000), "USD", evidence_id
                    ),
                    "implied_value_per_diluted_share": _numeric(
                        str(index + 1), "USD_per_share", evidence_id
                    ),
                    "assumptions": [f"{case} outcome."],
                }
                for index, case in enumerate(cases)
            ],
            "sensitivities": list(domain["sensitivities"]),
        }


class FixtureSynthesisProvider:
    def __init__(
        self,
        value: Mapping[str, object],
        delay_seconds: float = 0,
    ) -> None:
        self.value = value
        self.delay_seconds = delay_seconds
        self.requests = []

    def audit_request(self, request):
        return request.as_dict()

    def execute(self, request):
        self.requests.append(request)
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        committee = request.logical_input["committee"]
        results = committee["grader_results"]
        opinions = [item["opinion"] for item in results if item["opinion"]]
        opinion_ids = [item["opinion_id"] for item in opinions]
        evidence_id = opinions[0]["material_claims"][0]["evidence_ids"][0]
        output = {
            "requested_disposition": str(self.value["requested_disposition"]),
            "executive_summary_statement_ids": ["common-ground"],
            "statements": [
                {
                    "statement_id": "fact",
                    "text": (
                        "Frozen evidence identifies an active therapeutic programme."
                    ),
                    "provenance_type": "fact",
                    "evidence_ids": [evidence_id],
                    "opinion_ids": [],
                    "calculation_ids": [],
                },
                {
                    "statement_id": "common-ground",
                    "text": (
                        "Specialist opinions share one directional assessment of the "
                        "proposition."
                    ),
                    "provenance_type": "synthesis_interpretation",
                    "evidence_ids": [],
                    "opinion_ids": opinion_ids,
                    "calculation_ids": [],
                },
                {
                    "statement_id": "gap",
                    "text": "Further primary evidence can reduce uncertainty.",
                    "provenance_type": "gap",
                    "evidence_ids": [],
                    "opinion_ids": [opinion_ids[0]],
                    "calculation_ids": [],
                },
                {
                    "statement_id": "invalidation",
                    "text": (
                        "Thesis-critical catalyst failure invalidates the current "
                        "research case."
                    ),
                    "provenance_type": "grader_interpretation",
                    "evidence_ids": [],
                    "opinion_ids": [opinion_ids[0]],
                    "calculation_ids": [],
                },
                {
                    "statement_id": "next-evidence",
                    "text": "Obtain the next primary-source catalyst update.",
                    "provenance_type": "gap",
                    "evidence_ids": [],
                    "opinion_ids": [opinion_ids[1]],
                    "calculation_ids": [],
                },
                {
                    "statement_id": "review-trigger",
                    "text": "Review when the catalyst update becomes public.",
                    "provenance_type": "gap",
                    "evidence_ids": [],
                    "opinion_ids": [opinion_ids[1]],
                    "calculation_ids": [],
                },
            ],
            "common_ground_statement_ids": ["common-ground"],
            "disagreement_records": [],
            "disputed_assumption_statement_ids": [],
            "evidence_gap_statement_ids": ["gap"],
            "invalidation_statement_ids": ["invalidation"],
            "required_next_evidence_statement_ids": ["next-evidence"],
            "review_trigger": {
                "trigger_type": "evidence_event",
                "review_at": None,
                "statement_id": "review-trigger",
            },
            "state_disclosure": [
                {
                    "grader_id": item["grader_id"],
                    "execution_state": item["execution_state"],
                    "opinion_id": (
                        None
                        if item["opinion"] is None
                        else item["opinion"]["opinion_id"]
                    ),
                    "stance": (
                        None if item["opinion"] is None else item["opinion"]["stance"]
                    ),
                }
                for item in results
            ],
        }
        return ProviderResponse(
            provider_request_id=f"offline-{self.value['case_id']}-synthesis",
            raw_output=output,
            usage=ProviderUsage(2000, 500, 500, 100, 2500),
            resolved_model=request.model,
            system_fingerprint="offline-fixture-provider-v1",
        )


class FixtureGraderRouter:
    def __init__(self, execution_states: Mapping[str, str]) -> None:
        self.execution_states = dict(execution_states)

    def route(self, bundle, grader_ids):
        return {
            grader_id: self.execution_states.get(grader_id) != "not_eligible"
            for grader_id in grader_ids
        }


def _workflow(
    value: Mapping[str, object],
    *,
    execution_states: Mapping[str, str] | None = None,
    delay_seconds: float = 0,
):
    states = dict(execution_states or {})
    calendar = FixtureMarketCalendar(value)
    grader_provider = FixtureGraderProvider(value, states, delay_seconds)
    synthesis_provider = FixtureSynthesisProvider(value, delay_seconds)
    config = build_offline_mvp_config()
    if "not_executed" in states.values():
        config = replace(
            config,
            graders=tuple(
                replace(
                    item,
                    model=replace(
                        item.model,
                        active=(states.get(item.contract.grader_id) != "not_executed"),
                    ),
                )
                for item in config.graders
            ),
        )
    workflow_arguments = {}
    if "not_eligible" in states.values():
        workflow_arguments["grader_router"] = FixtureGraderRouter(states)
    return (
        BiotechResearchCommitteeWorkflow(
            config=config,
            eligibility_source=FixtureEligibilitySource(value),
            evidence_source=FixtureEvidenceSource(value),
            market_calendar=calendar,
            valuation_input_source=FixtureValuationSource(value, calendar.session),
            grader_provider=grader_provider,
            synthesis_provider=synthesis_provider,
            clock=IncrementingClock(),
            **workflow_arguments,
        ),
        grader_provider,
        synthesis_provider,
    )


class GenericOfflineWorkflowTests(unittest.TestCase):
    def test_rxrx_traverses_public_workflow_into_canonical_thesis(self) -> None:
        value = _fixture("rxrx-platform.json")
        workflow, grader_provider, synthesis_provider = _workflow(value)

        result = workflow.execute(
            AuthenticatedOperator(OPERATOR_ID),
            BiotechResearchRequest(
                security_id=str(value["security"]["id"]),
                as_of_cutoff=datetime.fromisoformat(str(value["cutoff"])),
                operator_focus="Review financing through the catalyst.",
            ),
        )

        self.assertTrue(result.run.eligibility.eligible)
        self.assertTrue(result.evidence_bundle.grader_ready)
        self.assertEqual(result.valuation_snapshot.snapshot_status, "valid")
        self.assertEqual(result.committee.status, "complete")
        self.assertEqual(result.committee.accounting.accepted_count, 5)
        self.assertEqual(result.memo_execution.execution_state, "accepted")
        self.assertEqual(
            result.readiness_and_thesis.thesis_creation.creation_outcome,
            "canonical_created",
        )
        self.assertEqual(len(grader_provider.requests), 5)
        self.assertEqual(len(synthesis_provider.requests), 1)

    def test_two_materially_different_securities_use_identical_contracts(
        self,
    ) -> None:
        platform = _fixture("rxrx-platform.json")
        single_asset = _fixture("single-asset-biotech.json")

        platform_workflow, _, _ = _workflow(platform)
        single_asset_workflow, _, _ = _workflow(single_asset)
        platform_result = platform_workflow.execute(
            AuthenticatedOperator(OPERATOR_ID),
            BiotechResearchRequest(
                security_id=str(platform["security"]["id"]),
                as_of_cutoff=datetime.fromisoformat(str(platform["cutoff"])),
            ),
        )
        single_asset_result = single_asset_workflow.execute(
            AuthenticatedOperator(OPERATOR_ID),
            BiotechResearchRequest(
                security_id=str(single_asset["security"]["id"]),
                as_of_cutoff=datetime.fromisoformat(str(single_asset["cutoff"])),
            ),
        )

        self.assertEqual(_shape(platform), _shape(single_asset))
        self.assertNotEqual(
            platform["program"],
            single_asset["program"],
        )
        self.assertNotEqual(
            platform["analysis"]["risk_dilution"]["runway_months"],
            single_asset["analysis"]["risk_dilution"]["runway_months"],
        )
        self.assertEqual(
            platform_result.contract_fingerprint,
            single_asset_result.contract_fingerprint,
        )
        self.assertEqual(platform_result.committee.status, "complete")
        self.assertEqual(single_asset_result.committee.status, "complete")
        self.assertEqual(platform_result.committee.accounting.supports_count, 5)
        self.assertEqual(
            single_asset_result.committee.accounting.challenges_count,
            5,
        )
        self.assertNotEqual(
            platform_result.evidence_bundle.content_hash,
            single_asset_result.evidence_bundle.content_hash,
        )
        self.assertEqual(
            platform_result.readiness_and_thesis.readiness.final_disposition,
            "deep_research",
        )
        self.assertEqual(
            single_asset_result.readiness_and_thesis.readiness.final_disposition,
            "monitor",
        )

    def test_identical_sequential_request_reuses_all_persisted_results(
        self,
    ) -> None:
        value = _fixture("rxrx-platform.json")
        workflow, grader_provider, synthesis_provider = _workflow(value)
        operator = AuthenticatedOperator(OPERATOR_ID)
        request = BiotechResearchRequest(
            security_id=str(value["security"]["id"]),
            as_of_cutoff=datetime.fromisoformat(str(value["cutoff"])),
        )

        first = workflow.execute(operator, request)
        second = workflow.execute(operator, request)

        self.assertEqual(first.run.id, second.run.id)
        self.assertEqual(first.evidence_bundle.id, second.evidence_bundle.id)
        self.assertEqual(
            first.valuation_snapshot.id,
            second.valuation_snapshot.id,
        )
        self.assertEqual(first.committee.committee_id, second.committee.committee_id)
        self.assertEqual(
            first.memo_execution.execution_id,
            second.memo_execution.execution_id,
        )
        self.assertEqual(
            first.readiness_and_thesis.readiness.readiness_gate_result_id,
            second.readiness_and_thesis.readiness.readiness_gate_result_id,
        )
        self.assertEqual(
            first.readiness_and_thesis.thesis_creation.thesis_version_id,
            second.readiness_and_thesis.thesis_creation.thesis_version_id,
        )
        self.assertEqual(len(grader_provider.requests), 5)
        self.assertEqual(len(synthesis_provider.requests), 1)

    def test_public_orchestrator_contains_no_fixture_or_ticker_branch(self) -> None:
        source_path = Path("src/investment_research_os/research_workflows/__init__.py")
        source = source_path.read_text()
        tree = ast.parse(source)
        forbidden_fixture_values = (
            "RXRX",
            "SATX",
            "rxrx-platform",
            "single-asset-biotech",
        )

        for value in forbidden_fixture_values:
            self.assertNotIn(value, source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.If, ast.IfExp, ast.Match)):
                branch_source = ast.get_source_segment(source, node) or ""
                self.assertNotIn("ticker", branch_source.lower())
                self.assertNotIn("symbol", branch_source.lower())

    def test_terminal_grader_states_have_distinct_workflow_consequences(
        self,
    ) -> None:
        expected = {
            "accepted": ("complete", "canonical_created", 1),
            "abstained": (
                "complete_with_abstentions",
                "provisional_created",
                1,
            ),
            "failed": (
                "incomplete_required_grader_failed",
                "no_thesis",
                2,
            ),
            "not_eligible": ("complete", "canonical_created", 0),
            "not_executed": (
                "insufficient_accepted_opinions",
                "no_thesis",
                0,
            ),
        }
        for execution_state, consequence in expected.items():
            with self.subTest(execution_state=execution_state):
                value = deepcopy(_fixture("rxrx-platform.json"))
                workflow, grader_provider, _ = _workflow(
                    value,
                    execution_states={"valuation": execution_state},
                )

                result = workflow.execute(
                    AuthenticatedOperator(OPERATOR_ID),
                    BiotechResearchRequest(
                        security_id=str(value["security"]["id"]),
                        as_of_cutoff=datetime.fromisoformat(str(value["cutoff"])),
                    ),
                )

                valuation = next(
                    item
                    for item in result.committee.grader_results
                    if item.grader_id == "valuation"
                )
                self.assertEqual(valuation.execution_state, execution_state)
                self.assertEqual(result.committee.status, consequence[0])
                self.assertEqual(
                    result.readiness_and_thesis.thesis_creation.creation_outcome,
                    consequence[1],
                )
                self.assertEqual(
                    sum(
                        request.logical_input["grader"]["grader_id"] == "valuation"
                        for request in grader_provider.requests
                    ),
                    consequence[2],
                )

    def test_concurrent_identical_requests_share_one_execution_chain(self) -> None:
        value = _fixture("rxrx-platform.json")
        workflow, grader_provider, synthesis_provider = _workflow(
            value,
            delay_seconds=0.01,
        )
        operator = AuthenticatedOperator(OPERATOR_ID)
        request = BiotechResearchRequest(
            security_id=str(value["security"]["id"]),
            as_of_cutoff=datetime.fromisoformat(str(value["cutoff"])),
        )
        start = Barrier(3)

        def execute():
            start.wait()
            return workflow.execute(operator, request)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(execute) for _ in range(2)]
            start.wait()
            first, second = (future.result() for future in futures)

        self.assertEqual(first.run.id, second.run.id)
        self.assertEqual(first.committee.committee_id, second.committee.committee_id)
        self.assertEqual(
            first.readiness_and_thesis.thesis_creation.thesis_version_id,
            second.readiness_and_thesis.thesis_creation.thesis_version_id,
        )
        self.assertEqual(len(grader_provider.requests), 5)
        self.assertEqual(len(synthesis_provider.requests), 1)

    def test_grader_router_must_cover_exact_versioned_roster(self) -> None:
        config = build_offline_mvp_config()

        with self.assertRaisesRegex(
            BiotechResearchWorkflowError,
            "exact versioned roster",
        ):
            config.grader_requests(
                "00000000-0000-4000-8000-000000000000",
                {"moonshot": True},
            )


if __name__ == "__main__":
    unittest.main()

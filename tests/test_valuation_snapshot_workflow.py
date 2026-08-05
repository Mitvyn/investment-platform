from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, date, datetime

from investment_research_os.evidence_bundles import (
    AuthenticatedOperator,
    InMemoryEvidenceBundleRepository,
)
from investment_research_os.valuation_snapshots import (
    CapitalStructureInput,
    CorporateActionReconciliation,
    DilutionInstrument,
    InMemoryValuationSnapshotRepository,
    MarketSession,
    MaterialityAssessment,
    PriceObservation,
    PersonalResearchValuationSnapshotWorkflow,
    ValuationInputCandidate,
    ValuationSourceReference,
    ValuationSnapshotWorkflow,
    ValuationSnapshotError,
)
from tests.test_evidence_bundle_storage import materialized_bundle


SESSION = MarketSession(
    session_date=date(2026, 5, 6),
    opens_at=datetime(2026, 5, 6, 13, 30, tzinfo=UTC),
    closes_at=datetime(2026, 5, 6, 20, 0, tzinfo=UTC),
    session_type="regular_us_trading_session",
    primary_listing_exchange="NASDAQ",
    early_close=False,
    calendar_version="us-equities-calendar-v1",
)


class FixedCalendar:
    def __init__(self, session: MarketSession = SESSION) -> None:
        self.session = session
        self.requests: list[tuple[str, datetime]] = []

    def latest_completed_session(
        self,
        primary_listing_exchange: str,
        cutoff: datetime,
    ) -> MarketSession:
        self.requests.append((primary_listing_exchange, cutoff))
        return self.session


def input_candidate() -> ValuationInputCandidate:
    bundle = materialized_bundle()
    return ValuationInputCandidate(
        security_id=bundle.security_id,
        evidence_bundle_id=bundle.id,
        evidence_bundle_hash=bundle.content_hash,
        market_session=SESSION,
        prices=(
            PriceObservation(
                price_type="official_unadjusted_close",
                session_type="regular_us_trading_session",
                session_date=SESSION.session_date,
                primary_listing_exchange="NASDAQ",
                price="6.25",
                currency="USD",
                official_close_timestamp=SESSION.closes_at,
                market_status="closed",
                corporate_action_adjustment_status="unadjusted",
                provider="licensed-market-fake",
                source_reference="market-close-source",
            ),
        ),
        capital=CapitalStructureInput(
            basic_shares_outstanding="286000000",
            fully_diluted_shares="318000000",
            cash="474300000",
            restricted_cash="4300000",
            restricted_cash_treatment="excluded",
            debt="128000000",
            other_included_claims="12000000",
            included_cash="470000000",
            currency="USD",
            basic_shares_effective_at=datetime(2026, 3, 31, 23, 59, 59, tzinfo=UTC),
            fully_diluted_shares_effective_at=datetime(
                2026, 3, 31, 23, 59, 59, tzinfo=UTC
            ),
            cash_effective_at=datetime(2026, 3, 31, 23, 59, 59, tzinfo=UTC),
            restricted_cash_effective_at=datetime(2026, 3, 31, 23, 59, 59, tzinfo=UTC),
            included_cash_effective_at=datetime(2026, 3, 31, 23, 59, 59, tzinfo=UTC),
            debt_effective_at=datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC),
            other_included_claims_effective_at=datetime(
                2026, 2, 28, 23, 59, 59, tzinfo=UTC
            ),
            basic_shares_evidence_ids=("c72e8a02-c5a6-5b05-af51-d6bd2d08ce55",),
            diluted_shares_evidence_ids=("635e63a1-ed42-540c-99cd-114aacb0ef51",),
            cash_evidence_ids=("635e63a1-ed42-540c-99cd-114aacb0ef51",),
            restricted_cash_evidence_ids=("635e63a1-ed42-540c-99cd-114aacb0ef51",),
            debt_evidence_ids=("635e63a1-ed42-540c-99cd-114aacb0ef51",),
            other_included_claims_evidence_ids=(
                "635e63a1-ed42-540c-99cd-114aacb0ef51",
            ),
            dilution_instruments=(
                DilutionInstrument(
                    instrument_id="equity-awards",
                    instrument_type="options",
                    diluted_share_increment="32000000",
                    effective_at=datetime(2026, 3, 31, 23, 59, 59, tzinfo=UTC),
                    supporting_evidence_ids=("635e63a1-ed42-540c-99cd-114aacb0ef51",),
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
        materiality_assessments=(
            MaterialityAssessment(
                evidence_id="c72e8a02-c5a6-5b05-af51-d6bd2d08ce55",
                publication_at=datetime(2026, 5, 6, 20, 0, tzinfo=UTC),
                market_materiality="material",
                materiality_reason_code="filing_available_at_close",
                affected_domains=("financing", "dilution", "valuation"),
                policy_version="biotech-market-materiality-v1",
            ),
            MaterialityAssessment(
                evidence_id="635e63a1-ed42-540c-99cd-114aacb0ef51",
                publication_at=datetime(2026, 5, 6, 19, 0, tzinfo=UTC),
                market_materiality="material",
                materiality_reason_code="capital_inputs_available_before_close",
                affected_domains=("financing", "dilution", "valuation"),
                policy_version="biotech-market-materiality-v1",
            ),
            MaterialityAssessment(
                evidence_id="5d4f281d-a86b-5299-a44d-528be11ac9aa",
                publication_at=datetime(2026, 5, 6, 18, 0, tzinfo=UTC),
                market_materiality="non_material",
                materiality_reason_code="programme_context_already_public",
                affected_domains=("clinical",),
                policy_version="biotech-market-materiality-v1",
            ),
            MaterialityAssessment(
                evidence_id="cd8fd063-1062-50cf-afae-990646ca4ff9",
                publication_at=datetime(2026, 5, 6, 18, 30, tzinfo=UTC),
                market_materiality="non_material",
                materiality_reason_code="trial_context_already_public",
                affected_domains=("catalyst", "clinical"),
                policy_version="biotech-market-materiality-v1",
            ),
            MaterialityAssessment(
                evidence_id="5a39958e-9739-5f23-9bee-91b710114997",
                publication_at=datetime(2026, 5, 6, 18, 45, tzinfo=UTC),
                market_materiality="non_material",
                materiality_reason_code="regulatory_context_already_public",
                affected_domains=("regulatory",),
                policy_version="biotech-market-materiality-v1",
            ),
        ),
        valuation_policy_version="biotech-valuation-snapshot-v1",
        materiality_policy_version="biotech-market-materiality-v1",
        source_references=(
            ValuationSourceReference(
                source_reference_id="market-close-source",
                source_type="licensed_market_data",
                provider="licensed-market-fake",
                locator="RXRX official close 2026-05-06",
                published_at=SESSION.closes_at,
                retrieved_at=datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
                effective_at=SESSION.closes_at,
            ),
            ValuationSourceReference(
                source_reference_id="primary-filing-source",
                source_type="primary_filing",
                provider="SEC",
                locator="Form 10-Q capital structure and balance sheet",
                published_at=datetime(2026, 5, 6, 19, 0, tzinfo=UTC),
                retrieved_at=datetime(2026, 5, 7, 0, 20, tzinfo=UTC),
                effective_at=datetime(2026, 3, 31, 23, 59, 59, tzinfo=UTC),
            ),
        ),
    )


def personal_input_candidate() -> ValuationInputCandidate:
    candidate = input_candidate()
    return replace(
        candidate,
        prices=(
            replace(
                candidate.prices[0],
                price_type="verified_consolidated_end_of_day_close",
                provider="massive",
            ),
        ),
        valuation_policy_version="personal_research_valuation_v1",
        source_references=(
            replace(
                candidate.source_references[0],
                source_type="personal_market_data",
                provider="massive",
                locator="NASDAQ:RXRX consolidated end-of-day 2026-05-06",
                provider_plan_id="massive-personal-free",
                response_sha256="a" * 64,
                provider_contract_status="candidate_unapproved",
                provider_limitation_codes=(
                    "official_close_provenance_unconfirmed",
                    "persistence_rights_unconfirmed",
                ),
            ),
            *candidate.source_references[1:],
        ),
    )


class FixedValuationSource:
    def __init__(self, candidate: ValuationInputCandidate) -> None:
        self.candidate = candidate
        self.requests: list[tuple[object, MarketSession]] = []

    def load(
        self,
        bundle: object,
        session: MarketSession,
    ) -> ValuationInputCandidate:
        self.requests.append((bundle, session))
        return self.candidate


class ValuationSnapshotWorkflowTests(unittest.TestCase):
    def test_personal_research_snapshot_uses_lower_assurance_contract(self) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        candidate = personal_input_candidate()
        snapshot = PersonalResearchValuationSnapshotWorkflow(
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=InMemoryValuationSnapshotRepository(),
            market_calendar=FixedCalendar(),
            input_source=FixedValuationSource(candidate),
            clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
        ).materialize(AuthenticatedOperator(bundle.operator_id), bundle.id)

        wire = snapshot.as_dict()
        self.assertEqual(
            wire["contract_version"],
            "valuation_snapshot.personal_research.v1",
        )
        self.assertEqual(wire["snapshot_status"], "valid")
        self.assertEqual(
            wire["price_basis"]["price_type"],
            "verified_consolidated_end_of_day_close",
        )
        self.assertEqual(
            wire["price_basis"]["price_timestamp"],
            SESSION.closes_at.isoformat(),
        )
        self.assertNotIn("official_close_timestamp", wire["price_basis"])
        self.assertEqual(wire["valuation_assurance"]["level"], "personal_research")
        self.assertEqual(
            wire["valuation_assurance"]["rights_assurance"],
            "not_independently_verified",
        )
        self.assertIn(
            "not_primary_venue_official_close",
            wire["valuation_assurance"]["limitation_codes"],
        )
        self.assertEqual(
            wire["source_references"][0]["response_sha256"],
            "a" * 64,
        )

    def test_personal_research_indeterminate_halt_status_invalidates_snapshot(
        self,
    ) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        candidate = personal_input_candidate()
        price = replace(
            candidate.prices[0],
            halt_verification_status="indeterminate",
        )
        snapshot = PersonalResearchValuationSnapshotWorkflow(
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=InMemoryValuationSnapshotRepository(),
            market_calendar=FixedCalendar(),
            input_source=FixedValuationSource(
                replace(
                    candidate,
                    prices=(price,),
                )
            ),
            clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
        ).materialize(AuthenticatedOperator(bundle.operator_id), bundle.id)

        self.assertEqual(snapshot.snapshot_status, "invalid")
        self.assertEqual(
            snapshot.invalid_reason_codes,
            ("market_halt_status_indeterminate",),
        )
        self.assertFalse(snapshot.market_relative_analysis_permitted)

    def test_personal_research_market_provenance_is_required(self) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        candidate = input_candidate()
        price = replace(
            candidate.prices[0],
            price_type="verified_consolidated_end_of_day_close",
        )
        incomplete_source = replace(
            candidate.source_references[0],
            source_type="personal_market_data",
        )
        workflow = PersonalResearchValuationSnapshotWorkflow(
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=InMemoryValuationSnapshotRepository(),
            market_calendar=FixedCalendar(),
            input_source=FixedValuationSource(
                replace(
                    candidate,
                    prices=(price,),
                    valuation_policy_version="personal_research_valuation_v1",
                    source_references=(
                        incomplete_source,
                        *candidate.source_references[1:],
                    ),
                )
            ),
            clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
        )

        with self.assertRaisesRegex(
            ValuationSnapshotError,
            "personal market source provenance is incomplete",
        ):
            workflow.materialize(AuthenticatedOperator(bundle.operator_id), bundle.id)

    def test_selects_official_close_for_latest_completed_session(self) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        valuation_repository = InMemoryValuationSnapshotRepository()
        calendar = FixedCalendar()
        source = FixedValuationSource(input_candidate())
        workflow = ValuationSnapshotWorkflow(
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=valuation_repository,
            market_calendar=calendar,
            input_source=source,
            clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
        )

        snapshot = workflow.materialize(
            AuthenticatedOperator(bundle.operator_id),
            bundle.id,
        )

        self.assertEqual(snapshot.research_run_id, bundle.research_run_id)
        self.assertEqual(snapshot.evidence_bundle_id, bundle.id)
        self.assertEqual(snapshot.price.price, "6.25")
        self.assertEqual(snapshot.price.session_date, SESSION.session_date)
        self.assertEqual(snapshot.price.price_type, "official_unadjusted_close")
        self.assertEqual(
            calendar.requests,
            [(bundle.security_identity.primary_listing_exchange, bundle.as_of_cutoff)],
        )
        self.assertEqual(source.requests, [(bundle, SESSION)])
        self.assertEqual(
            valuation_repository.get_for_run(
                bundle.operator_id,
                bundle.research_run_id,
            ),
            snapshot,
        )

    def test_derives_market_cap_and_enterprise_value_from_explicit_inputs(
        self,
    ) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        workflow = ValuationSnapshotWorkflow(
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=InMemoryValuationSnapshotRepository(),
            market_calendar=FixedCalendar(),
            input_source=FixedValuationSource(input_candidate()),
            clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
        )

        snapshot = workflow.materialize(
            AuthenticatedOperator(bundle.operator_id),
            bundle.id,
        )

        self.assertEqual(snapshot.market_capitalization.value, "1987500000.00")
        self.assertEqual(
            snapshot.market_capitalization.formula,
            "share_price * fully_diluted_shares",
        )
        self.assertEqual(snapshot.enterprise_value.value, "1657500000.00")
        self.assertEqual(
            snapshot.enterprise_value.formula,
            ("market_capitalization + debt + other_included_claims - included_cash"),
        )
        self.assertEqual(snapshot.market_capitalization.unit, "USD")
        self.assertEqual(snapshot.enterprise_value.unit, "USD")
        self.assertEqual(len(snapshot.calculation_ids), 3)
        wire = snapshot.as_dict()
        self.assertEqual(
            wire["basic_shares_outstanding"]["effective_at"],
            "2026-03-31T23:59:59+00:00",
        )
        self.assertEqual(
            wire["debt"]["effective_at"],
            "2025-12-31T23:59:59+00:00",
        )
        self.assertEqual(
            wire["cash_treatment"]["reported_cash"]["value"],
            "474300000",
        )
        self.assertEqual(
            wire["cash_treatment"]["restricted_cash"]["value"],
            "4300000",
        )
        self.assertEqual(
            wire["cash_treatment"]["restricted_cash_treatment"],
            "excluded",
        )
        self.assertEqual(
            wire["cash_treatment"]["restricted_cash"]["effective_at"],
            "2026-03-31T23:59:59+00:00",
        )
        self.assertEqual(
            wire["other_included_claims"]["value"],
            "12000000",
        )

    def test_valid_snapshot_exposes_language_neutral_wire_contract(self) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        snapshot = ValuationSnapshotWorkflow(
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=InMemoryValuationSnapshotRepository(),
            market_calendar=FixedCalendar(),
            input_source=FixedValuationSource(input_candidate()),
            clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
        ).materialize(AuthenticatedOperator(bundle.operator_id), bundle.id)

        wire = snapshot.as_dict()

        self.assertEqual(wire["contract_version"], "valuation_snapshot.v1")
        self.assertEqual(wire["price_basis"]["share_price"], "6.25")
        self.assertEqual(
            wire["market_capitalization"]["formula"],
            "share_price * fully_diluted_shares",
        )
        self.assertEqual(
            wire["fully_diluted_shares"]["calculation_method"],
            "calculated",
        )
        self.assertEqual(
            wire["fully_diluted_shares"]["freshness_state"],
            "current",
        )
        self.assertEqual(
            set(wire["evidence_ids"]),
            {
                "c72e8a02-c5a6-5b05-af51-d6bd2d08ce55",
                "635e63a1-ed42-540c-99cd-114aacb0ef51",
                "5d4f281d-a86b-5299-a44d-528be11ac9aa",
                "cd8fd063-1062-50cf-afae-990646ca4ff9",
                "5a39958e-9739-5f23-9bee-91b710114997",
            },
        )
        self.assertNotIn("portfolio", wire)
        self.assertNotIn("position_size", wire)
        self.assertNotIn("trade_action", wire)

    def test_missing_required_close_persists_invalid_snapshot(self) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        valuation_repository = InMemoryValuationSnapshotRepository()
        workflow = ValuationSnapshotWorkflow(
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=valuation_repository,
            market_calendar=FixedCalendar(),
            input_source=FixedValuationSource(replace(input_candidate(), prices=())),
            clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
        )

        snapshot = workflow.materialize(
            AuthenticatedOperator(bundle.operator_id),
            bundle.id,
        )

        self.assertEqual(snapshot.snapshot_status, "invalid")
        self.assertEqual(
            snapshot.invalid_reason_codes,
            ("official_close_unavailable",),
        )
        self.assertIsNone(snapshot.price)
        self.assertIsNone(snapshot.market_capitalization)
        self.assertIsNone(snapshot.enterprise_value)
        self.assertEqual(snapshot.price_information_state, "indeterminate")
        self.assertFalse(snapshot.market_relative_analysis_permitted)
        self.assertEqual(
            valuation_repository.get_for_run(
                bundle.operator_id,
                bundle.research_run_id,
            ),
            snapshot,
        )

    def test_corporate_action_mismatch_invalidates_snapshot(self) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        candidate = replace(
            input_candidate(),
            corporate_action=CorporateActionReconciliation(
                event_id="reverse-split-2026",
                action_type="reverse_split",
                effective_at=datetime(2026, 5, 6, 13, 30, tzinfo=UTC),
                price_adjustment_status="unadjusted",
                share_count_adjustment_status="adjusted",
                reconciliation_result="mismatch",
            ),
        )
        workflow = ValuationSnapshotWorkflow(
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=InMemoryValuationSnapshotRepository(),
            market_calendar=FixedCalendar(),
            input_source=FixedValuationSource(candidate),
            clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
        )

        snapshot = workflow.materialize(
            AuthenticatedOperator(bundle.operator_id),
            bundle.id,
        )

        self.assertEqual(snapshot.snapshot_status, "invalid")
        self.assertEqual(
            snapshot.invalid_reason_codes,
            ("corporate_action_mismatch",),
        )
        self.assertFalse(snapshot.market_relative_analysis_permitted)
        self.assertIsNone(snapshot.market_capitalization)
        self.assertIsNone(snapshot.enterprise_value)

    def test_halted_market_invalidates_historical_close_basis(self) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        candidate = input_candidate()
        halted_price = replace(candidate.prices[0], market_status="halted")
        workflow = ValuationSnapshotWorkflow(
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=InMemoryValuationSnapshotRepository(),
            market_calendar=FixedCalendar(),
            input_source=FixedValuationSource(
                replace(candidate, prices=(halted_price,))
            ),
            clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
        )

        snapshot = workflow.materialize(
            AuthenticatedOperator(bundle.operator_id),
            bundle.id,
        )

        self.assertEqual(snapshot.snapshot_status, "invalid")
        self.assertEqual(snapshot.invalid_reason_codes, ("market_halted",))
        self.assertIsNotNone(snapshot.price)
        self.assertFalse(snapshot.market_relative_analysis_permitted)

    def test_post_close_material_evidence_blocks_market_relative_analysis(
        self,
    ) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        candidate = input_candidate()
        materiality = replace(
            candidate.materiality_assessments[0],
            publication_at=datetime(2026, 5, 6, 21, 0, tzinfo=UTC),
            market_materiality="material",
            materiality_reason_code="material_financing_update_after_close",
        )
        workflow = ValuationSnapshotWorkflow(
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=InMemoryValuationSnapshotRepository(),
            market_calendar=FixedCalendar(),
            input_source=FixedValuationSource(
                replace(
                    candidate,
                    materiality_assessments=(
                        materiality,
                        *candidate.materiality_assessments[1:],
                    ),
                )
            ),
            clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
        )

        snapshot = workflow.materialize(
            AuthenticatedOperator(bundle.operator_id),
            bundle.id,
        )

        self.assertEqual(snapshot.snapshot_status, "valid")
        self.assertEqual(
            snapshot.price_information_state,
            "pre_material_evidence",
        )
        self.assertFalse(snapshot.market_relative_analysis_permitted)
        self.assertEqual(
            snapshot.materiality_assessments[0].timing_state,
            "after_close_before_or_at_cutoff",
        )
        self.assertIsNotNone(snapshot.market_capitalization)
        self.assertIsNotNone(snapshot.enterprise_value)

    def test_stale_capital_input_invalidates_snapshot(self) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        candidate = input_candidate()
        stale_capital = replace(
            candidate.capital,
            cash_freshness_state="stale",
            cash_freshness_reason_code="cash_period_stale_at_cutoff",
        )
        workflow = ValuationSnapshotWorkflow(
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=InMemoryValuationSnapshotRepository(),
            market_calendar=FixedCalendar(),
            input_source=FixedValuationSource(
                replace(candidate, capital=stale_capital)
            ),
            clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
        )

        snapshot = workflow.materialize(
            AuthenticatedOperator(bundle.operator_id),
            bundle.id,
        )

        self.assertEqual(snapshot.snapshot_status, "invalid")
        self.assertEqual(
            snapshot.invalid_reason_codes,
            ("stale_capital_input",),
        )
        self.assertFalse(snapshot.market_relative_analysis_permitted)
        self.assertIsNone(snapshot.market_capitalization)

    def test_calendar_cannot_return_session_closing_after_cutoff(self) -> None:
        bundle = replace(
            materialized_bundle(),
            as_of_cutoff=datetime(2026, 5, 6, 15, 0, tzinfo=UTC),
        )
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        workflow = ValuationSnapshotWorkflow(
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=InMemoryValuationSnapshotRepository(),
            market_calendar=FixedCalendar(),
            input_source=FixedValuationSource(input_candidate()),
            clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
        )

        with self.assertRaisesRegex(
            ValueError,
            "calendar returned incomplete session",
        ):
            workflow.materialize(
                AuthenticatedOperator(bundle.operator_id),
                bundle.id,
            )

    def test_diluted_share_reconstruction_mismatch_invalidates_snapshot(
        self,
    ) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        candidate = input_candidate()
        mismatched_capital = replace(
            candidate.capital,
            fully_diluted_shares="317000000",
        )
        workflow = ValuationSnapshotWorkflow(
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=InMemoryValuationSnapshotRepository(),
            market_calendar=FixedCalendar(),
            input_source=FixedValuationSource(
                replace(candidate, capital=mismatched_capital)
            ),
            clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
        )

        snapshot = workflow.materialize(
            AuthenticatedOperator(bundle.operator_id),
            bundle.id,
        )

        self.assertEqual(snapshot.snapshot_status, "invalid")
        self.assertEqual(
            snapshot.invalid_reason_codes,
            ("diluted_share_reconciliation_mismatch",),
        )
        self.assertIsNone(snapshot.market_capitalization)
        self.assertEqual(snapshot.calculation_ids, ())
        self.assertEqual(
            snapshot.as_dict()["fully_diluted_shares"]["calculation_method"],
            "reported",
        )

    def test_adjusted_close_invalidates_snapshot(self) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        candidate = input_candidate()
        adjusted_price = replace(
            candidate.prices[0],
            corporate_action_adjustment_status="adjusted",
        )
        adjusted_action = replace(
            candidate.corporate_action,
            price_adjustment_status="adjusted",
        )

        snapshot = ValuationSnapshotWorkflow(
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=InMemoryValuationSnapshotRepository(),
            market_calendar=FixedCalendar(),
            input_source=FixedValuationSource(
                replace(
                    candidate,
                    prices=(adjusted_price,),
                    corporate_action=adjusted_action,
                )
            ),
            clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
        ).materialize(AuthenticatedOperator(bundle.operator_id), bundle.id)

        self.assertEqual(snapshot.snapshot_status, "invalid")
        self.assertEqual(
            snapshot.invalid_reason_codes,
            ("price_adjustment_status_invalid",),
        )

    def test_rejects_noncanonical_decimal_input(self) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        candidate = input_candidate()
        invalid_capital = replace(
            candidate.capital,
            basic_shares_outstanding="0286000000",
        )

        workflow = ValuationSnapshotWorkflow(
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=InMemoryValuationSnapshotRepository(),
            market_calendar=FixedCalendar(),
            input_source=FixedValuationSource(
                replace(candidate, capital=invalid_capital)
            ),
            clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
        )

        with self.assertRaisesRegex(
            ValuationSnapshotError,
            "invalid basic shares outstanding",
        ):
            workflow.materialize(
                AuthenticatedOperator(bundle.operator_id),
                bundle.id,
            )

    def test_rejects_price_and_action_adjustment_mismatch(self) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        candidate = input_candidate()
        adjusted_price = replace(
            candidate.prices[0],
            corporate_action_adjustment_status="adjusted",
        )

        workflow = ValuationSnapshotWorkflow(
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=InMemoryValuationSnapshotRepository(),
            market_calendar=FixedCalendar(),
            input_source=FixedValuationSource(
                replace(candidate, prices=(adjusted_price,))
            ),
            clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
        )

        with self.assertRaisesRegex(
            ValuationSnapshotError,
            "price and corporate action adjustment mismatch",
        ):
            workflow.materialize(
                AuthenticatedOperator(bundle.operator_id),
                bundle.id,
            )

    def test_currency_mismatch_invalidates_snapshot(self) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        candidate = input_candidate()
        mismatched_price = replace(candidate.prices[0], currency="EUR")

        snapshot = ValuationSnapshotWorkflow(
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=InMemoryValuationSnapshotRepository(),
            market_calendar=FixedCalendar(),
            input_source=FixedValuationSource(
                replace(candidate, prices=(mismatched_price,))
            ),
            clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
        ).materialize(AuthenticatedOperator(bundle.operator_id), bundle.id)

        self.assertEqual(snapshot.snapshot_status, "invalid")
        self.assertEqual(
            snapshot.invalid_reason_codes,
            ("currency_mismatch",),
        )

    def test_rejects_materiality_that_does_not_cover_bundle_evidence(self) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        candidate = input_candidate()

        workflow = ValuationSnapshotWorkflow(
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=InMemoryValuationSnapshotRepository(),
            market_calendar=FixedCalendar(),
            input_source=FixedValuationSource(
                replace(
                    candidate,
                    materiality_assessments=(candidate.materiality_assessments[0],),
                )
            ),
            clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
        )

        with self.assertRaisesRegex(
            ValuationSnapshotError,
            "materiality assessments must cover bundle evidence exactly",
        ):
            workflow.materialize(
                AuthenticatedOperator(bundle.operator_id),
                bundle.id,
            )

    def test_missing_required_capital_provenance_fails_closed(self) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        candidate = input_candidate()
        incomplete_capital = replace(
            candidate.capital,
            other_included_claims_evidence_ids=(),
        )
        workflow = ValuationSnapshotWorkflow(
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=InMemoryValuationSnapshotRepository(),
            market_calendar=FixedCalendar(),
            input_source=FixedValuationSource(
                replace(candidate, capital=incomplete_capital)
            ),
            clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
        )

        with self.assertRaisesRegex(
            ValuationSnapshotError,
            "capital input evidence is incomplete",
        ):
            workflow.materialize(
                AuthenticatedOperator(bundle.operator_id),
                bundle.id,
            )

    def test_mismatched_candidate_identity_fails_closed(self) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        mismatched = replace(
            input_candidate(),
            evidence_bundle_hash="0" * 64,
        )
        workflow = ValuationSnapshotWorkflow(
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=InMemoryValuationSnapshotRepository(),
            market_calendar=FixedCalendar(),
            input_source=FixedValuationSource(mismatched),
            clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
        )

        with self.assertRaisesRegex(
            ValuationSnapshotError,
            "valuation candidate identity mismatch",
        ):
            workflow.materialize(
                AuthenticatedOperator(bundle.operator_id),
                bundle.id,
            )

    def test_mismatched_cash_basis_fails_closed(self) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        candidate = input_candidate()
        mismatched_capital = replace(
            candidate.capital,
            included_cash_effective_at=datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC),
        )
        workflow = ValuationSnapshotWorkflow(
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=InMemoryValuationSnapshotRepository(),
            market_calendar=FixedCalendar(),
            input_source=FixedValuationSource(
                replace(candidate, capital=mismatched_capital)
            ),
            clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
        )

        with self.assertRaisesRegex(
            ValuationSnapshotError,
            "restricted cash effective time mismatch",
        ):
            workflow.materialize(
                AuthenticatedOperator(bundle.operator_id),
                bundle.id,
            )


if __name__ == "__main__":
    unittest.main()

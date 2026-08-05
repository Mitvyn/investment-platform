from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import inspect
import unittest

from investment_research_os.second_fixture_selection import (
    REQUIRED_ELIGIBILITY_RULE_IDS,
    REQUIRED_SOURCE_COVERAGE_IDS,
    ScreeningCheck,
    SecondFixtureScreeningRecord,
    select_second_live_fixture,
)
import investment_research_os.second_fixture_selection as selection_module
from workers.primary_sources.eligibility import ELIGIBILITY_RULE_IDS


CUTOFF = datetime(2026, 5, 6, 23, 59, 59, tzinfo=UTC)
REFERENCE_ID = "11111111-1111-4111-8111-111111111111"
CANDIDATE_A_ID = "22222222-2222-4222-8222-222222222222"
CANDIDATE_B_ID = "33333333-3333-4333-8333-333333333333"


def checks(ids: tuple[str, ...], *, failed: str | None = None):
    return tuple(ScreeningCheck(item, item != failed) for item in ids)


def record(
    security_id: str,
    *,
    clinical_phase_bucket: str = "phase_2",
    catalyst_basis: str = "clinical_readout",
    catalyst_horizon_bucket: str = "within_6_months",
    active_study_count: int = 4,
    financing_before_catalyst: str = "funded_through_catalyst",
    dilution_mechanisms: tuple[str, ...] = ("atm", "options", "rsus"),
    valuation_scale_bucket: str = "small",
) -> SecondFixtureScreeningRecord:
    return SecondFixtureScreeningRecord(
        security_id=security_id,
        as_of_cutoff=CUTOFF,
        question_type="biotech_moonshot_catalyst_personal_research_assessment",
        workflow_config_version="biotech-moonshot-catalyst-personal-research-v1",
        eligibility_policy_version="biotech-eligibility-sources-v1",
        eligibility_checks=checks(REQUIRED_ELIGIBILITY_RULE_IDS),
        source_coverage=checks(REQUIRED_SOURCE_COVERAGE_IDS),
        source_plan_contract_version="primary_source_plan.v3",
        source_plan_hash="a" * 64,
        evidence_bundle_id=f"bundle-{security_id}",
        evidence_bundle_hash="b" * 64,
        evidence_bundle_ready=True,
        blocking_gap_codes=(),
        valuation_snapshot_id=f"valuation-{security_id}",
        valuation_contract_version="valuation_snapshot.personal_research.v1",
        valuation_status="valid",
        price_information_state="aligned",
        corporate_action_reconciliation_result="reconciled",
        clinical_phase_bucket=clinical_phase_bucket,
        catalyst_basis=catalyst_basis,
        catalyst_horizon_bucket=catalyst_horizon_bucket,
        active_study_count=active_study_count,
        financing_before_catalyst=financing_before_catalyst,
        dilution_mechanisms=dilution_mechanisms,
        valuation_scale_bucket=valuation_scale_bucket,
    )


class SecondLiveFixtureSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reference = record(REFERENCE_ID)
        self.candidate_a = record(
            CANDIDATE_A_ID,
            clinical_phase_bucket="phase_1",
            catalyst_basis="clinical_start",
            active_study_count=1,
            financing_before_catalyst="financing_required_before_catalyst",
            dilution_mechanisms=("shelf", "warrants"),
            valuation_scale_bucket="micro",
        )
        self.candidate_b = record(
            CANDIDATE_B_ID,
            clinical_phase_bucket="phase_1",
            financing_before_catalyst="financing_likely_before_catalyst",
        )

    def test_selects_highest_cross_domain_difference_independent_of_input_order(
        self,
    ) -> None:
        first = select_second_live_fixture(
            reference=self.reference,
            candidates=(self.candidate_b, self.candidate_a),
        )
        second = select_second_live_fixture(
            reference=self.reference,
            candidates=(self.candidate_a, self.candidate_b),
        )

        self.assertEqual(first, second)
        self.assertEqual(first.selected_security_id, CANDIDATE_A_ID)
        self.assertEqual(len(first.pool_hash), 64)
        self.assertEqual(len(first.receipt_hash), 64)
        selected = next(
            outcome
            for outcome in first.outcomes
            if outcome.security_id == CANDIDATE_A_ID
        )
        self.assertTrue(selected.eligible_for_selection)
        self.assertEqual(selected.reason_codes, ())
        self.assertIn("clinical_phase", selected.difference_dimensions)
        self.assertIn("financing_before_catalyst", selected.difference_dimensions)

    def test_rejects_reference_security_by_stable_identity(self) -> None:
        result = select_second_live_fixture(
            reference=self.reference,
            candidates=(replace(self.candidate_a, security_id=REFERENCE_ID),),
        )

        self.assertIsNone(result.selected_security_id)
        self.assertEqual(result.outcomes[0].reason_codes, ("reference_security",))

    def test_preserves_each_deterministic_screening_failure(self) -> None:
        failed = replace(
            self.candidate_a,
            eligibility_checks=checks(
                REQUIRED_ELIGIBILITY_RULE_IDS,
                failed="active_therapeutic_program",
            ),
            source_coverage=checks(
                REQUIRED_SOURCE_COVERAGE_IDS,
                failed="financing_share_capital",
            ),
            evidence_bundle_ready=False,
            blocking_gap_codes=("financing_field_warrants_unresolved",),
            valuation_status="invalid",
            price_information_state="indeterminate",
            corporate_action_reconciliation_result="unresolved",
        )

        result = select_second_live_fixture(
            reference=self.reference,
            candidates=(failed,),
        )

        self.assertEqual(
            result.outcomes[0].reason_codes,
            (
                "eligibility_failed:active_therapeutic_program",
                "coverage_failed:financing_share_capital",
                "evidence_bundle_not_ready",
                "blocking_evidence_gaps",
                "valuation_snapshot_invalid",
                "price_information_not_aligned",
                "corporate_action_not_reconciled",
            ),
        )

    def test_requires_one_clinical_and_one_financing_or_valuation_difference(
        self,
    ) -> None:
        clinical_only = replace(
            self.reference,
            security_id=CANDIDATE_A_ID,
            evidence_bundle_id="bundle-clinical-only",
            valuation_snapshot_id="valuation-clinical-only",
            clinical_phase_bucket="phase_1",
            active_study_count=1,
        )
        capital_only = replace(
            self.reference,
            security_id=CANDIDATE_B_ID,
            evidence_bundle_id="bundle-capital-only",
            valuation_snapshot_id="valuation-capital-only",
            financing_before_catalyst="financing_required_before_catalyst",
            valuation_scale_bucket="micro",
        )

        result = select_second_live_fixture(
            reference=self.reference,
            candidates=(clinical_only, capital_only),
        )

        self.assertIsNone(result.selected_security_id)
        reasons = {
            outcome.security_id: outcome.reason_codes for outcome in result.outcomes
        }
        self.assertIn(
            "insufficient_financing_valuation_difference",
            reasons[CANDIDATE_A_ID],
        )
        self.assertIn(
            "insufficient_clinical_catalyst_difference",
            reasons[CANDIDATE_B_ID],
        )

    def test_tie_breaks_by_canonical_stable_security_id(self) -> None:
        tied = replace(
            self.candidate_a,
            security_id=CANDIDATE_B_ID,
            evidence_bundle_id="bundle-tied",
            valuation_snapshot_id="valuation-tied",
        )

        result = select_second_live_fixture(
            reference=self.reference,
            candidates=(tied, self.candidate_a),
        )

        self.assertEqual(result.selected_security_id, CANDIDATE_A_ID)

    def test_receipt_binds_reference_artifacts_not_only_candidate_pool(self) -> None:
        first = select_second_live_fixture(
            reference=self.reference,
            candidates=(self.candidate_a,),
        )
        second = select_second_live_fixture(
            reference=replace(self.reference, source_plan_hash="c" * 64),
            candidates=(self.candidate_a,),
        )

        self.assertEqual(first.pool_hash, second.pool_hash)
        self.assertNotEqual(first.reference_record_hash, second.reference_record_hash)
        self.assertNotEqual(first.receipt_hash, second.receipt_hash)

    def test_reference_requires_current_personal_valuation_and_v3_source_plan(
        self,
    ) -> None:
        for reference in (
            replace(
                self.reference,
                valuation_contract_version="valuation_snapshot.v1",
            ),
            replace(
                self.reference,
                source_plan_contract_version="primary_source_plan.v2",
            ),
        ):
            with self.subTest(reference=reference):
                with self.assertRaisesRegex(
                    ValueError,
                    "reference fixture is not selection ready",
                ):
                    select_second_live_fixture(
                        reference=reference,
                        candidates=(self.candidate_a,),
                    )

    def test_selection_eligibility_contract_matches_source_policy(self) -> None:
        self.assertEqual(REQUIRED_ELIGIBILITY_RULE_IDS, ELIGIBILITY_RULE_IDS)

    def test_selector_source_cannot_route_on_display_identity_or_fixture_literals(
        self,
    ) -> None:
        source = inspect.getsource(selection_module).casefold()

        for forbidden in ("ticker", "symbol", "issuer_name", "rxrx", "snga"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()

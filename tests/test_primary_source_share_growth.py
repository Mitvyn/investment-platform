from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
import unittest

from workers.primary_sources.share_growth import (
    BasicShareObservation,
    CorporateActionReconciliation,
    calculate_basic_share_growth,
)


SECURITY_ID = "a657d245-6bda-5476-930a-911667ea6c64"
CIK = "0001601830"
CUTOFF = datetime(2026, 5, 6, 23, 59, 59, tzinfo=UTC)
BASIS = "issuer_reported_total_basic_common_equity"
CONCEPT = "us-gaap:CommonStockSharesOutstanding"


def observation(
    *,
    value: str,
    period_end: date,
    accession_number: str,
    accepted_at: datetime,
    reference_key: str,
    measurement_basis: str = "point_in_time",
    concept: str = CONCEPT,
    unit: str = "shares",
    economic_basis: str = BASIS,
    is_amendment: bool = False,
) -> BasicShareObservation:
    return BasicShareObservation(
        security_id=SECURITY_ID,
        cik=CIK,
        period_end=period_end,
        accession_number=accession_number,
        accepted_at=accepted_at,
        reference_key=reference_key,
        value=value,
        unit=unit,
        concept=concept,
        measurement_basis=measurement_basis,
        economic_basis=economic_basis,
        is_amendment=is_amendment,
    )


def verified_no_action_reconciliation() -> CorporateActionReconciliation:
    return CorporateActionReconciliation(
        security_id=SECURITY_ID,
        cik=CIK,
        from_period_end=date(2025, 12, 31),
        to_period_end=date(2026, 3, 31),
        state="verified",
        prior_to_current_factor="1",
        evidence_reference_keys=("corporate-action:none-verified",),
    )


class BasicShareGrowthTests(unittest.TestCase):
    def test_rxrx_uses_adjacent_period_end_outstanding_shares(self) -> None:
        result = calculate_basic_share_growth(
            observations=(
                observation(
                    value="528182693",
                    period_end=date(2025, 12, 31),
                    accession_number="0001601830-26-000039",
                    accepted_at=datetime(2026, 2, 25, 11, 33, 18, tzinfo=UTC),
                    reference_key=(
                        "sec-companyfacts:basic_shares_outstanding:"
                        "2025-12-31:0001601830-26-000039"
                    ),
                ),
                observation(
                    value="530628653",
                    period_end=date(2026, 3, 31),
                    accession_number="0001601830-26-000078",
                    accepted_at=datetime(2026, 5, 6, 10, 32, 40, tzinfo=UTC),
                    reference_key=(
                        "sec-companyfacts:basic_shares_outstanding:"
                        "2026-03-31:0001601830-26-000078"
                    ),
                ),
            ),
            as_of_cutoff=CUTOFF,
            corporate_action_reconciliation=(verified_no_action_reconciliation()),
        )

        self.assertEqual(result.state, "complete")
        self.assertEqual(
            result.policy_version,
            "financing-basic-share-growth-v1",
        )
        self.assertEqual(result.security_id, SECURITY_ID)
        self.assertEqual(result.cik, CIK)
        self.assertEqual(
            result.current_accession_number,
            "0001601830-26-000078",
        )
        self.assertEqual(
            result.prior_accession_number,
            "0001601830-26-000039",
        )
        self.assertEqual(result.current_shares, "530628653")
        self.assertEqual(result.prior_shares, "528182693")
        self.assertEqual(result.adjusted_prior_shares, "528182693")
        self.assertEqual(result.delta_shares, "2445960")
        self.assertEqual(result.growth_percent, "0.463090")
        self.assertEqual(result.unit, "percent")
        self.assertEqual(result.period_start, date(2025, 12, 31))
        self.assertEqual(result.period_end, date(2026, 3, 31))
        self.assertEqual(
            result.reason_codes,
            ("basic_share_growth_complete",),
        )

    def test_missing_prior_period_returns_incomplete_without_exception(
        self,
    ) -> None:
        result = calculate_basic_share_growth(
            observations=(
                observation(
                    value="530628653",
                    period_end=date(2026, 3, 31),
                    accession_number="0001601830-26-000078",
                    accepted_at=datetime(2026, 5, 6, 10, 32, 40, tzinfo=UTC),
                    reference_key="current",
                ),
            ),
            as_of_cutoff=CUTOFF,
            corporate_action_reconciliation=(verified_no_action_reconciliation()),
        )

        self.assertEqual(result.state, "incomplete")
        self.assertEqual(
            result.reason_codes,
            ("basic_share_growth_prior_fact_missing",),
        )
        self.assertIsNone(result.growth_percent)

    def test_filters_post_cutoff_fact_before_selecting_adjacent_periods(
        self,
    ) -> None:
        result = calculate_basic_share_growth(
            observations=(
                observation(
                    value="100",
                    period_end=date(2025, 12, 31),
                    accession_number="0001601830-26-000039",
                    accepted_at=datetime(2026, 2, 25, 11, 33, 18, tzinfo=UTC),
                    reference_key="prior",
                ),
                observation(
                    value="110",
                    period_end=date(2026, 3, 31),
                    accession_number="0001601830-26-000078",
                    accepted_at=datetime(2026, 5, 6, 10, 32, 40, tzinfo=UTC),
                    reference_key="current",
                ),
                observation(
                    value="999",
                    period_end=date(2026, 6, 30),
                    accession_number="0001601830-26-000099",
                    accepted_at=datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
                    reference_key="post-cutoff",
                ),
            ),
            as_of_cutoff=CUTOFF,
            corporate_action_reconciliation=(verified_no_action_reconciliation()),
        )

        self.assertEqual(result.state, "complete")
        self.assertEqual(result.current_reference_key, "current")
        self.assertEqual(result.prior_reference_key, "prior")
        self.assertEqual(result.growth_percent, "10.000000")

    def test_rejects_mixed_security_identity_as_indeterminate(self) -> None:
        mismatched = observation(
            value="110",
            period_end=date(2026, 3, 31),
            accession_number="0001601830-26-000078",
            accepted_at=datetime(2026, 5, 6, 10, 32, 40, tzinfo=UTC),
            reference_key="current",
        )
        mismatched = replace(mismatched, security_id="other-security")

        result = calculate_basic_share_growth(
            observations=(
                observation(
                    value="100",
                    period_end=date(2025, 12, 31),
                    accession_number="0001601830-26-000039",
                    accepted_at=datetime(2026, 2, 25, 11, 33, 18, tzinfo=UTC),
                    reference_key="prior",
                ),
                mismatched,
            ),
            as_of_cutoff=CUTOFF,
            corporate_action_reconciliation=(verified_no_action_reconciliation()),
        )

        self.assertEqual(result.state, "indeterminate")
        self.assertEqual(
            result.reason_codes,
            ("basic_share_growth_identity_mismatch",),
        )

    def test_rejects_weighted_average_eps_share_input(self) -> None:
        result = calculate_basic_share_growth(
            observations=(
                observation(
                    value="100",
                    period_end=date(2025, 12, 31),
                    accession_number="0001601830-26-000039",
                    accepted_at=datetime(2026, 2, 25, 11, 33, 18, tzinfo=UTC),
                    reference_key="prior",
                ),
                observation(
                    value="110",
                    period_end=date(2026, 3, 31),
                    accession_number="0001601830-26-000078",
                    accepted_at=datetime(2026, 5, 6, 10, 32, 40, tzinfo=UTC),
                    reference_key="current",
                    measurement_basis="weighted_average",
                ),
            ),
            as_of_cutoff=CUTOFF,
            corporate_action_reconciliation=(verified_no_action_reconciliation()),
        )

        self.assertEqual(result.state, "indeterminate")
        self.assertEqual(
            result.reason_codes,
            ("basic_share_growth_weighted_average_input_rejected",),
        )

    def test_requires_matching_concept_unit_and_economic_basis(self) -> None:
        mismatch_cases = (
            (
                {"unit": "USD"},
                "basic_share_growth_unit_mismatch",
            ),
            (
                {"concept": "dei:EntityCommonStockSharesOutstanding"},
                "basic_share_growth_concept_mismatch",
            ),
            (
                {"economic_basis": "class_a_only"},
                "basic_share_growth_basis_mismatch",
            ),
        )
        for changes, expected_reason in mismatch_cases:
            with self.subTest(expected_reason=expected_reason):
                result = calculate_basic_share_growth(
                    observations=(
                        observation(
                            value="100",
                            period_end=date(2025, 12, 31),
                            accession_number="0001601830-26-000039",
                            accepted_at=datetime(2026, 2, 25, 11, 33, 18, tzinfo=UTC),
                            reference_key="prior",
                        ),
                        observation(
                            value="110",
                            period_end=date(2026, 3, 31),
                            accession_number="0001601830-26-000078",
                            accepted_at=datetime(2026, 5, 6, 10, 32, 40, tzinfo=UTC),
                            reference_key="current",
                            **changes,
                        ),
                    ),
                    as_of_cutoff=CUTOFF,
                )

                self.assertEqual(result.state, "indeterminate")
                self.assertEqual(
                    result.reason_codes,
                    (expected_reason,),
                )

    def test_cutoff_valid_amendment_supersedes_original_period_fact(
        self,
    ) -> None:
        result = calculate_basic_share_growth(
            observations=(
                observation(
                    value="100",
                    period_end=date(2025, 12, 31),
                    accession_number="0001601830-26-000039",
                    accepted_at=datetime(2026, 2, 25, 11, 33, 18, tzinfo=UTC),
                    reference_key="prior",
                ),
                observation(
                    value="110",
                    period_end=date(2026, 3, 31),
                    accession_number="0001601830-26-000078",
                    accepted_at=datetime(2026, 5, 6, 9, 0, tzinfo=UTC),
                    reference_key="current-original",
                ),
                observation(
                    value="105",
                    period_end=date(2026, 3, 31),
                    accession_number="0001601830-26-000079",
                    accepted_at=datetime(2026, 5, 6, 12, 0, tzinfo=UTC),
                    reference_key="current-amendment",
                    is_amendment=True,
                ),
            ),
            as_of_cutoff=CUTOFF,
            corporate_action_reconciliation=(verified_no_action_reconciliation()),
        )

        self.assertEqual(result.state, "complete")
        self.assertEqual(
            result.current_reference_key,
            "current-amendment",
        )
        self.assertEqual(result.growth_percent, "5.000000")

    def test_conflicting_same_period_facts_are_indeterminate(self) -> None:
        result = calculate_basic_share_growth(
            observations=(
                observation(
                    value="100",
                    period_end=date(2025, 12, 31),
                    accession_number="0001601830-26-000039",
                    accepted_at=datetime(2026, 2, 25, 11, 33, 18, tzinfo=UTC),
                    reference_key="prior",
                ),
                observation(
                    value="110",
                    period_end=date(2026, 3, 31),
                    accession_number="0001601830-26-000078",
                    accepted_at=datetime(2026, 5, 6, 9, 0, tzinfo=UTC),
                    reference_key="current-a",
                ),
                observation(
                    value="111",
                    period_end=date(2026, 3, 31),
                    accession_number="0001601830-26-000080",
                    accepted_at=datetime(2026, 5, 6, 10, 0, tzinfo=UTC),
                    reference_key="current-b",
                ),
            ),
            as_of_cutoff=CUTOFF,
            corporate_action_reconciliation=(verified_no_action_reconciliation()),
        )

        self.assertEqual(result.state, "indeterminate")
        self.assertEqual(
            result.reason_codes,
            ("basic_share_growth_conflicting_fact",),
        )

    def test_identical_duplicate_period_fact_is_deduplicated(self) -> None:
        result = calculate_basic_share_growth(
            observations=(
                observation(
                    value="100",
                    period_end=date(2025, 12, 31),
                    accession_number="0001601830-26-000039",
                    accepted_at=datetime(2026, 2, 25, 11, 33, 18, tzinfo=UTC),
                    reference_key="prior",
                ),
                observation(
                    value="110",
                    period_end=date(2026, 3, 31),
                    accession_number="0001601830-26-000078",
                    accepted_at=datetime(2026, 5, 6, 9, 0, tzinfo=UTC),
                    reference_key="current-a",
                ),
                observation(
                    value="110",
                    period_end=date(2026, 3, 31),
                    accession_number="0001601830-26-000080",
                    accepted_at=datetime(2026, 5, 6, 10, 0, tzinfo=UTC),
                    reference_key="current-b",
                ),
            ),
            as_of_cutoff=CUTOFF,
            corporate_action_reconciliation=(verified_no_action_reconciliation()),
        )

        self.assertEqual(result.state, "complete")
        self.assertEqual(result.current_reference_key, "current-b")
        self.assertEqual(result.growth_percent, "10.000000")

    def test_invalid_value_and_zero_prior_are_analytical_gaps(self) -> None:
        cases = (
            ("not-a-number", "100", "basic_share_growth_value_invalid"),
            ("0", "100", "basic_share_growth_prior_denominator_zero"),
        )
        for prior_value, current_value, expected_reason in cases:
            with self.subTest(expected_reason=expected_reason):
                result = calculate_basic_share_growth(
                    observations=(
                        observation(
                            value=prior_value,
                            period_end=date(2025, 12, 31),
                            accession_number="0001601830-26-000039",
                            accepted_at=datetime(2026, 2, 25, 11, 33, 18, tzinfo=UTC),
                            reference_key="prior",
                        ),
                        observation(
                            value=current_value,
                            period_end=date(2026, 3, 31),
                            accession_number="0001601830-26-000078",
                            accepted_at=datetime(2026, 5, 6, 10, 32, 40, tzinfo=UTC),
                            reference_key="current",
                        ),
                    ),
                    as_of_cutoff=CUTOFF,
                    corporate_action_reconciliation=(
                        verified_no_action_reconciliation()
                    ),
                )

                self.assertEqual(result.state, "indeterminate")
                self.assertEqual(
                    result.reason_codes,
                    (expected_reason,),
                )

    def test_unresolved_corporate_action_is_indeterminate(self) -> None:
        result = calculate_basic_share_growth(
            observations=(
                observation(
                    value="100",
                    period_end=date(2025, 12, 31),
                    accession_number="0001601830-26-000039",
                    accepted_at=datetime(2026, 2, 25, 11, 33, 18, tzinfo=UTC),
                    reference_key="prior",
                ),
                observation(
                    value="200",
                    period_end=date(2026, 3, 31),
                    accession_number="0001601830-26-000078",
                    accepted_at=datetime(2026, 5, 6, 10, 32, 40, tzinfo=UTC),
                    reference_key="current",
                ),
            ),
            as_of_cutoff=CUTOFF,
            corporate_action_reconciliation=CorporateActionReconciliation(
                security_id=SECURITY_ID,
                cik=CIK,
                from_period_end=date(2025, 12, 31),
                to_period_end=date(2026, 3, 31),
                state="unresolved",
                prior_to_current_factor="",
                evidence_reference_keys=("corporate-action",),
            ),
        )

        self.assertEqual(result.state, "indeterminate")
        self.assertEqual(
            result.reason_codes,
            ("basic_share_growth_corporate_action_unresolved",),
        )

    def test_missing_corporate_action_reconciliation_is_indeterminate(
        self,
    ) -> None:
        result = calculate_basic_share_growth(
            observations=(
                observation(
                    value="100",
                    period_end=date(2025, 12, 31),
                    accession_number="0001601830-26-000039",
                    accepted_at=datetime(2026, 2, 25, 11, 33, 18, tzinfo=UTC),
                    reference_key="prior",
                ),
                observation(
                    value="110",
                    period_end=date(2026, 3, 31),
                    accession_number="0001601830-26-000078",
                    accepted_at=datetime(2026, 5, 6, 10, 32, 40, tzinfo=UTC),
                    reference_key="current",
                ),
            ),
            as_of_cutoff=CUTOFF,
        )

        self.assertEqual(result.state, "indeterminate")
        self.assertEqual(
            result.reason_codes,
            ("basic_share_growth_corporate_action_reconciliation_missing",),
        )

    def test_verified_corporate_action_adjusts_prior_share_basis(self) -> None:
        result = calculate_basic_share_growth(
            observations=(
                observation(
                    value="100",
                    period_end=date(2025, 12, 31),
                    accession_number="0001601830-26-000039",
                    accepted_at=datetime(2026, 2, 25, 11, 33, 18, tzinfo=UTC),
                    reference_key="prior",
                ),
                observation(
                    value="200",
                    period_end=date(2026, 3, 31),
                    accession_number="0001601830-26-000078",
                    accepted_at=datetime(2026, 5, 6, 10, 32, 40, tzinfo=UTC),
                    reference_key="current",
                ),
            ),
            as_of_cutoff=CUTOFF,
            corporate_action_reconciliation=CorporateActionReconciliation(
                security_id=SECURITY_ID,
                cik=CIK,
                from_period_end=date(2025, 12, 31),
                to_period_end=date(2026, 3, 31),
                state="verified",
                prior_to_current_factor="2",
                evidence_reference_keys=("corporate-action",),
            ),
        )

        self.assertEqual(result.state, "complete")
        self.assertEqual(result.prior_shares, "100")
        self.assertEqual(result.adjusted_prior_shares, "200")
        self.assertEqual(result.delta_shares, "0")
        self.assertEqual(result.growth_percent, "0.000000")
        self.assertEqual(
            result.evidence_reference_keys,
            ("prior", "current", "corporate-action"),
        )

    def test_mismatched_corporate_action_scope_is_indeterminate(
        self,
    ) -> None:
        result = calculate_basic_share_growth(
            observations=(
                observation(
                    value="100",
                    period_end=date(2025, 12, 31),
                    accession_number="0001601830-26-000039",
                    accepted_at=datetime(2026, 2, 25, 11, 33, 18, tzinfo=UTC),
                    reference_key="prior",
                ),
                observation(
                    value="200",
                    period_end=date(2026, 3, 31),
                    accession_number="0001601830-26-000078",
                    accepted_at=datetime(2026, 5, 6, 10, 32, 40, tzinfo=UTC),
                    reference_key="current",
                ),
            ),
            as_of_cutoff=CUTOFF,
            corporate_action_reconciliation=CorporateActionReconciliation(
                security_id="other-security",
                cik=CIK,
                from_period_end=date(2025, 12, 31),
                to_period_end=date(2026, 3, 31),
                state="verified",
                prior_to_current_factor="2",
                evidence_reference_keys=("corporate-action",),
            ),
        )

        self.assertEqual(result.state, "indeterminate")
        self.assertEqual(
            result.reason_codes,
            ("basic_share_growth_corporate_action_mismatch",),
        )

    def test_verified_corporate_action_requires_provenance(self) -> None:
        result = calculate_basic_share_growth(
            observations=(
                observation(
                    value="100",
                    period_end=date(2025, 12, 31),
                    accession_number="0001601830-26-000039",
                    accepted_at=datetime(2026, 2, 25, 11, 33, 18, tzinfo=UTC),
                    reference_key="prior",
                ),
                observation(
                    value="110",
                    period_end=date(2026, 3, 31),
                    accession_number="0001601830-26-000078",
                    accepted_at=datetime(2026, 5, 6, 10, 32, 40, tzinfo=UTC),
                    reference_key="current",
                ),
            ),
            as_of_cutoff=CUTOFF,
            corporate_action_reconciliation=CorporateActionReconciliation(
                security_id=SECURITY_ID,
                cik=CIK,
                from_period_end=date(2025, 12, 31),
                to_period_end=date(2026, 3, 31),
                state="verified",
                prior_to_current_factor="1",
                evidence_reference_keys=(),
            ),
        )

        self.assertEqual(result.state, "indeterminate")
        self.assertEqual(
            result.reason_codes,
            ("basic_share_growth_corporate_action_invalid",),
        )

    def test_ambiguous_publication_time_is_indeterminate(self) -> None:
        naive_current = observation(
            value="110",
            period_end=date(2026, 3, 31),
            accession_number="0001601830-26-000078",
            accepted_at=datetime(2026, 5, 6, 10, 32, 40),
            reference_key="current",
        )
        result = calculate_basic_share_growth(
            observations=(
                observation(
                    value="100",
                    period_end=date(2025, 12, 31),
                    accession_number="0001601830-26-000039",
                    accepted_at=datetime(2026, 2, 25, 11, 33, 18, tzinfo=UTC),
                    reference_key="prior",
                ),
                naive_current,
            ),
            as_of_cutoff=CUTOFF,
            corporate_action_reconciliation=(verified_no_action_reconciliation()),
        )

        self.assertEqual(result.state, "indeterminate")
        self.assertEqual(
            result.reason_codes,
            ("basic_share_growth_publication_time_indeterminate",),
        )

    def test_rejects_missing_period_accession_reference(self) -> None:
        result = calculate_basic_share_growth(
            observations=(
                observation(
                    value="100",
                    period_end=date(2025, 12, 31),
                    accession_number="",
                    accepted_at=datetime(2026, 2, 25, 11, 33, 18, tzinfo=UTC),
                    reference_key="prior",
                ),
                observation(
                    value="110",
                    period_end=date(2026, 3, 31),
                    accession_number="0001601830-26-000078",
                    accepted_at=datetime(2026, 5, 6, 10, 32, 40, tzinfo=UTC),
                    reference_key="current",
                ),
            ),
            as_of_cutoff=CUTOFF,
        )

        self.assertEqual(result.state, "indeterminate")
        self.assertEqual(
            result.reason_codes,
            ("basic_share_growth_reference_invalid",),
        )

    def test_requires_same_point_in_time_measurement_basis(self) -> None:
        cases = (
            (
                "period_average",
                "point_in_time",
                "basic_share_growth_measurement_basis_mismatch",
            ),
            (
                "period_average",
                "period_average",
                "basic_share_growth_measurement_basis_invalid",
            ),
        )
        for prior_basis, current_basis, reason in cases:
            with self.subTest(reason=reason):
                result = calculate_basic_share_growth(
                    observations=(
                        observation(
                            value="100",
                            period_end=date(2025, 12, 31),
                            accession_number="0001601830-26-000039",
                            accepted_at=datetime(2026, 2, 25, 11, 33, 18, tzinfo=UTC),
                            reference_key="prior",
                            measurement_basis=prior_basis,
                        ),
                        observation(
                            value="110",
                            period_end=date(2026, 3, 31),
                            accession_number="0001601830-26-000078",
                            accepted_at=datetime(2026, 5, 6, 10, 32, 40, tzinfo=UTC),
                            reference_key="current",
                            measurement_basis=current_basis,
                        ),
                    ),
                    as_of_cutoff=CUTOFF,
                )

                self.assertEqual(result.state, "indeterminate")
                self.assertEqual(result.reason_codes, (reason,))

    def test_rounds_percent_half_even_to_six_decimal_places(self) -> None:
        result = calculate_basic_share_growth(
            observations=(
                observation(
                    value="200000000",
                    period_end=date(2025, 12, 31),
                    accession_number="0001601830-26-000039",
                    accepted_at=datetime(2026, 2, 25, 11, 33, 18, tzinfo=UTC),
                    reference_key="prior",
                ),
                observation(
                    value="200000001",
                    period_end=date(2026, 3, 31),
                    accession_number="0001601830-26-000078",
                    accepted_at=datetime(2026, 5, 6, 10, 32, 40, tzinfo=UTC),
                    reference_key="current",
                ),
            ),
            as_of_cutoff=CUTOFF,
            corporate_action_reconciliation=(verified_no_action_reconciliation()),
        )

        self.assertEqual(result.state, "complete")
        self.assertEqual(result.growth_percent, "0.000000")


if __name__ == "__main__":
    unittest.main()

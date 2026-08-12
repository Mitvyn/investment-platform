from __future__ import annotations

from datetime import UTC, date, datetime
from dataclasses import replace
from types import SimpleNamespace
import unittest

from workers.primary_sources.other_enterprise_claims import (
    COMPONENT_IDS,
    ClaimDisclosure,
    ClaimObservation,
    ExplicitClaimNegation,
    OtherEnterpriseClaimsContext,
    OtherEnterpriseClaimsError,
    ReconciledBalanceSheet,
    extract_reconciled_balance_sheet,
    resolve_other_enterprise_claims,
)


PERIOD_END = date(2026, 3, 31)
CUTOFF = datetime(2026, 5, 6, 23, 59, 59, tzinfo=UTC)


def context() -> OtherEnterpriseClaimsContext:
    return OtherEnterpriseClaimsContext(
        as_of_cutoff=CUTOFF,
        balance_sheet_period_end=PERIOD_END,
        debt_concept="DebtLongtermAndShorttermCombinedAmount",
        debt_includes_finance_leases=False,
        debt_includes_convertible_principal=False,
        convertible_share_equivalents="0",
        preferred_share_equivalents="0",
    )


def zero_observations() -> tuple[ClaimObservation, ...]:
    return tuple(
        ClaimObservation(
            component_id=component_id,
            value="0",
            unit="USD",
            period_end=PERIOD_END,
            source_concept=f"Concept{index}",
            supporting_evidence_ids=(f"evidence-{index}",),
        )
        for index, component_id in enumerate(COMPONENT_IDS)
    )


def filing_document(
    statement_heading: str,
    statement_body: str,
    *,
    notes_body: str = "",
) -> SimpleNamespace:
    return SimpleNamespace(
        report_date=PERIOD_END,
        source_url="https://www.sec.gov/Archives/example.htm",
        accession_number="0000000000-26-000001",
        primary_document="example.htm",
        published_at=CUTOFF,
        retrieved_at=CUTOFF,
        content_sha256="a" * 64,
        content_text=(
            f"<html><body><h2>{statement_heading}</h2>"
            f"<p>(in thousands)</p>{statement_body}"
            "<p>Total assets $100</p>"
            "<p>Total liabilities and stockholders' equity $100</p>"
            f"<p>See the accompanying notes</p>{notes_body}</body></html>"
        ),
    )


class OtherEnterpriseClaimsTests(unittest.TestCase):
    def test_extracts_annual_consolidated_balance_sheets_heading(self) -> None:
        proof = extract_reconciled_balance_sheet(
            (filing_document("Consolidated Balance Sheets", ""),),
            period_end=PERIOD_END,
            present_component_ids=(),
        )

        self.assertEqual(proof.balance_sheet.period_end, PERIOD_END)

    def test_extracts_condensed_consolidated_balance_sheets_heading(self) -> None:
        proof = extract_reconciled_balance_sheet(
            (filing_document("Condensed Consolidated Balance Sheets", ""),),
            period_end=PERIOD_END,
            present_component_ids=(),
        )

        self.assertEqual(proof.balance_sheet.period_end, PERIOD_END)

    def test_balance_sheet_coverage_is_derived_from_component_line_items(
        self,
    ) -> None:
        proof = extract_reconciled_balance_sheet(
            (
                filing_document(
                    "Condensed Consolidated Balance Sheets",
                    "<p>Finance lease liabilities $1</p>",
                ),
            ),
            period_end=PERIOD_END,
            present_component_ids=(),
        )

        self.assertEqual(
            proof.balance_sheet.covered_component_ids,
            ("finance_lease_claim",),
        )
        self.assertFalse(proof.balance_sheet.complete)

    def test_balance_sheet_is_complete_only_with_exact_six_component_line_items(
        self,
    ) -> None:
        statement_body = "".join(
            (
                "<p>Redeemable preferred stock $0</p>",
                "<p>Noncontrolling interests $0</p>",
                "<p>Royalty monetization liability $0</p>",
                "<p>Contingent consideration $0</p>",
                "<p>Pension liabilities $0</p>",
                "<p>Finance lease liabilities $0</p>",
            )
        )

        proof = extract_reconciled_balance_sheet(
            (
                filing_document(
                    "Condensed Consolidated Balance Sheets",
                    statement_body,
                ),
            ),
            period_end=PERIOD_END,
            present_component_ids=(),
        )

        self.assertEqual(proof.balance_sheet.covered_component_ids, COMPONENT_IDS)
        self.assertEqual(proof.balance_sheet.present_component_ids, ())
        self.assertTrue(proof.balance_sheet.complete)

    def test_reconciled_face_with_notes_only_claim_fails_closed(self) -> None:
        face_line_items = "".join(
            (
                "<p>Redeemable preferred stock $0</p>",
                "<p>Noncontrolling interests $0</p>",
                "<p>Contingent consideration $0</p>",
                "<p>Pension liabilities $0</p>",
                "<p>Finance lease liabilities $0</p>",
            )
        )
        proof = extract_reconciled_balance_sheet(
            (
                filing_document(
                    "Condensed Consolidated Balance Sheets",
                    face_line_items,
                    notes_body="<p>Royalty monetization liability $7</p>",
                ),
            ),
            period_end=PERIOD_END,
            present_component_ids=(),
        )
        negations = tuple(
            ExplicitClaimNegation(
                component_id=component_id,
                period_end=PERIOD_END,
                supporting_evidence_ids=(f"negation-{component_id}",),
            )
            for component_id in COMPONENT_IDS
            if component_id != "royalty_monetization_liability"
        )

        self.assertNotIn(
            "royalty_monetization_liability",
            proof.balance_sheet.covered_component_ids,
        )
        self.assertFalse(proof.balance_sheet.complete)
        with self.assertRaisesRegex(
            OtherEnterpriseClaimsError,
            "other_claims_component_unevidenced:royalty_monetization_liability",
        ):
            resolve_other_enterprise_claims(
                context(),
                explicit_negations=negations,
                balance_sheet=proof.balance_sheet,
            )

    def test_positive_face_line_without_companyfacts_observation_fails_closed(
        self,
    ) -> None:
        statement_body = "".join(
            (
                "<p>Redeemable preferred stock $0</p>",
                "<p>Noncontrolling interests $0</p>",
                "<p>Royalty monetization liability $7</p>",
                "<p>Contingent consideration $0</p>",
                "<p>Pension liabilities $0</p>",
                "<p>Finance lease liabilities $0</p>",
            )
        )
        proof = extract_reconciled_balance_sheet(
            (
                filing_document(
                    "Condensed Consolidated Balance Sheets",
                    statement_body,
                ),
            ),
            period_end=PERIOD_END,
            present_component_ids=(),
        )
        negations = tuple(
            ExplicitClaimNegation(
                component_id=component_id,
                period_end=PERIOD_END,
                supporting_evidence_ids=(f"negation-{component_id}",),
            )
            for component_id in COMPONENT_IDS
            if component_id != "royalty_monetization_liability"
        )

        self.assertIn(
            "royalty_monetization_liability",
            proof.balance_sheet.present_component_ids,
        )
        with self.assertRaisesRegex(
            OtherEnterpriseClaimsError,
            "other_claims_component_unevidenced:royalty_monetization_liability",
        ):
            resolve_other_enterprise_claims(
                context(),
                explicit_negations=negations,
                balance_sheet=proof.balance_sheet,
            )

    def test_balance_sheet_period_after_cutoff_fails_before_resolution(self) -> None:
        after_cutoff_context = replace(
            context(),
            balance_sheet_period_end=date(2026, 5, 7),
        )

        with self.assertRaisesRegex(
            OtherEnterpriseClaimsError,
            "other_claims_balance_sheet_period_after_cutoff",
        ):
            resolve_other_enterprise_claims(
                after_cutoff_context,
                observations=zero_observations(),
            )

    def test_current_tagged_zero_resolves_component(self) -> None:
        result = resolve_other_enterprise_claims(
            context(),
            observations=zero_observations(),
        )

        self.assertEqual(result.value, "0")
        self.assertTrue(
            all(
                component.resolution == "tagged_zero" for component in result.components
            )
        )

    def test_earlier_tagged_zero_is_stale_not_zero(self) -> None:
        observations = (
            ClaimObservation(
                component_id="redeemable_preferred_claim",
                value="0",
                unit="USD",
                period_end=date(2023, 12, 31),
                source_concept="TemporaryEquityCarryingAmountAttributableToParent",
                supporting_evidence_ids=("evidence-stale",),
            ),
        )

        with self.assertRaisesRegex(
            OtherEnterpriseClaimsError,
            "other_claims_component_stale:redeemable_preferred_claim",
        ):
            resolve_other_enterprise_claims(context(), observations=observations)

    def test_reconciled_complete_statement_can_prove_structural_zero(self) -> None:
        balance_sheet = ReconciledBalanceSheet(
            period_end=PERIOD_END,
            unit="USD",
            total_assets="100000000",
            total_liabilities_and_equity="100000000",
            covered_component_ids=COMPONENT_IDS,
            present_component_ids=(),
            supporting_evidence_ids=("balance-sheet",),
            complete=True,
        )

        result = resolve_other_enterprise_claims(
            context(),
            balance_sheet=balance_sheet,
        )

        self.assertEqual(result.value, "0")
        self.assertTrue(
            all(
                component.resolution == "structural_absence"
                for component in result.components
            )
        )

    def test_explicit_current_negations_produce_supported_zeroes(self) -> None:
        negations = tuple(
            ExplicitClaimNegation(
                component_id=component_id,
                period_end=PERIOD_END,
                supporting_evidence_ids=(f"negation-{index}",),
            )
            for index, component_id in enumerate(COMPONENT_IDS)
        )

        result = resolve_other_enterprise_claims(
            context(),
            explicit_negations=negations,
        )

        self.assertEqual(result.value, "0")
        self.assertTrue(
            all(
                component.resolution == "explicit_negation"
                for component in result.components
            )
        )

    def test_finance_lease_cannot_be_counted_inside_debt_and_claims(self) -> None:
        observations = tuple(
            ClaimObservation(
                component_id=observation.component_id,
                value=(
                    "16200000"
                    if observation.component_id == "finance_lease_claim"
                    else observation.value
                ),
                unit=observation.unit,
                period_end=observation.period_end,
                source_concept=observation.source_concept,
                supporting_evidence_ids=observation.supporting_evidence_ids,
            )
            for observation in zero_observations()
        )
        debt_context = OtherEnterpriseClaimsContext(
            as_of_cutoff=CUTOFF,
            balance_sheet_period_end=PERIOD_END,
            debt_concept="LongTermDebtAndCapitalLeaseObligations",
            debt_includes_finance_leases=True,
            debt_includes_convertible_principal=False,
            convertible_share_equivalents="0",
            preferred_share_equivalents="0",
        )

        with self.assertRaisesRegex(
            OtherEnterpriseClaimsError,
            "other_claims_double_count_finance_lease",
        ):
            resolve_other_enterprise_claims(
                debt_context,
                observations=observations,
            )

    def test_convertible_principal_cannot_remain_in_debt_under_if_converted_policy(
        self,
    ) -> None:
        convertible_context = replace(
            context(),
            debt_includes_convertible_principal=True,
            convertible_share_equivalents="1500000",
        )

        with self.assertRaisesRegex(
            OtherEnterpriseClaimsError,
            "other_claims_double_count_convertible",
        ):
            resolve_other_enterprise_claims(
                convertible_context,
                observations=zero_observations(),
            )

    def test_same_period_conflicting_values_are_ambiguous(self) -> None:
        observations = (
            *zero_observations(),
            ClaimObservation(
                component_id="royalty_monetization_liability",
                value="5000000",
                unit="USD",
                period_end=PERIOD_END,
                source_concept="AlternateRoyaltyLiability",
                supporting_evidence_ids=("conflict",),
            ),
        )

        with self.assertRaisesRegex(
            OtherEnterpriseClaimsError,
            "other_claims_component_ambiguous:royalty_monetization_liability",
        ):
            resolve_other_enterprise_claims(
                context(),
                observations=observations,
            )

    def test_same_value_observation_in_non_usd_fails_closed(self) -> None:
        observations = (
            *zero_observations(),
            ClaimObservation(
                component_id="royalty_monetization_liability",
                value="0",
                unit="EUR",
                period_end=PERIOD_END,
                source_concept="RoyaltyLiability",
                supporting_evidence_ids=("evidence-eur",),
            ),
        )

        with self.assertRaisesRegex(
            OtherEnterpriseClaimsError,
            "other_claims_component_unit_invalid:royalty_monetization_liability",
        ):
            resolve_other_enterprise_claims(
                context(),
                observations=observations,
            )

    def test_agreeing_observations_union_corroborating_evidence(self) -> None:
        observations = (
            *zero_observations(),
            ClaimObservation(
                component_id="royalty_monetization_liability",
                value="0.00",
                unit="USD",
                period_end=PERIOD_END,
                source_concept="Concept2",
                supporting_evidence_ids=("evidence-corroborating", "evidence-2"),
            ),
        )

        result = resolve_other_enterprise_claims(
            context(),
            observations=observations,
        )

        component = next(
            component
            for component in result.components
            if component.component_id == "royalty_monetization_liability"
        )
        self.assertEqual(component.source_concept, "Concept2")
        self.assertEqual(
            component.supporting_evidence_ids,
            ("evidence-2", "evidence-corroborating"),
        )

    def test_agreeing_values_with_conflicting_source_concepts_fail_closed(
        self,
    ) -> None:
        observations = (
            *zero_observations(),
            ClaimObservation(
                component_id="royalty_monetization_liability",
                value="0",
                unit="USD",
                period_end=PERIOD_END,
                source_concept="AlternateRoyaltyLiability",
                supporting_evidence_ids=("evidence-alternate",),
            ),
        )

        with self.assertRaisesRegex(
            OtherEnterpriseClaimsError,
            "other_claims_component_source_concept_conflict:"
            "royalty_monetization_liability",
        ):
            resolve_other_enterprise_claims(
                context(),
                observations=observations,
            )

    def test_negative_and_non_usd_claims_fail_closed(self) -> None:
        for value, unit, reason in (
            ("-1", "USD", "other_claims_component_negative"),
            ("1", "EUR", "other_claims_component_unit_invalid"),
        ):
            with self.subTest(value=value, unit=unit):
                observations = tuple(
                    replace(
                        observation,
                        value=value,
                        unit=unit,
                    )
                    if observation.component_id == "contingent_consideration_claim"
                    else observation
                    for observation in zero_observations()
                )
                with self.assertRaisesRegex(
                    OtherEnterpriseClaimsError,
                    f"{reason}:contingent_consideration_claim",
                ):
                    resolve_other_enterprise_claims(
                        context(),
                        observations=observations,
                    )

    def test_partial_or_unreconciled_statement_cannot_prove_zero(self) -> None:
        for complete, liabilities_and_equity in (
            (False, "100000000"),
            (True, "99999999"),
        ):
            with self.subTest(
                complete=complete,
                liabilities_and_equity=liabilities_and_equity,
            ):
                balance_sheet = ReconciledBalanceSheet(
                    period_end=PERIOD_END,
                    unit="USD",
                    total_assets="100000000",
                    total_liabilities_and_equity=liabilities_and_equity,
                    covered_component_ids=COMPONENT_IDS,
                    present_component_ids=(),
                    supporting_evidence_ids=("balance-sheet",),
                    complete=complete,
                )
                with self.assertRaisesRegex(
                    OtherEnterpriseClaimsError,
                    "other_claims_component_unevidenced:redeemable_preferred_claim",
                ):
                    resolve_other_enterprise_claims(
                        context(),
                        balance_sheet=balance_sheet,
                    )

    def test_unrecognized_contingency_blocks_even_with_structural_absence(self) -> None:
        balance_sheet = ReconciledBalanceSheet(
            period_end=PERIOD_END,
            unit="USD",
            total_assets="100000000",
            total_liabilities_and_equity="100000000",
            covered_component_ids=COMPONENT_IDS,
            present_component_ids=(),
            supporting_evidence_ids=("balance-sheet",),
            complete=True,
        )

        with self.assertRaisesRegex(
            OtherEnterpriseClaimsError,
            "other_claims_component_contingent:contingent_consideration_claim",
        ):
            resolve_other_enterprise_claims(
                context(),
                balance_sheet=balance_sheet,
                disclosures=(
                    ClaimDisclosure(
                        component_id="contingent_consideration_claim",
                        period_end=PERIOD_END,
                        state="contingent",
                        supporting_evidence_ids=("contingency-note",),
                    ),
                ),
            )

    def test_preferred_claim_requires_disjointness_from_share_equivalents(self) -> None:
        preferred_context = replace(context(), preferred_share_equivalents="200000")
        observations = tuple(
            replace(observation, value="3000000")
            if observation.component_id == "redeemable_preferred_claim"
            else observation
            for observation in zero_observations()
        )

        with self.assertRaisesRegex(
            OtherEnterpriseClaimsError,
            "other_claims_double_count_preferred",
        ):
            resolve_other_enterprise_claims(
                preferred_context,
                observations=observations,
            )


if __name__ == "__main__":
    unittest.main()

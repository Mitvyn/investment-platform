from __future__ import annotations

import hashlib
import unittest
from dataclasses import replace
from datetime import UTC, datetime

from workers.primary_sources.financing import (
    FINANCING_FIELD_IDS,
    FINANCING_METRIC_KEYS_BY_FIELD,
    FINANCING_SEMANTIC_POLICY_VERSION,
    FinancingFieldEvidence,
    FinancingSemanticError,
    build_financing_semantic_matrix,
    derive_financing_field_evidence,
    financing_missing_field_reason_codes,
    financing_matrix_to_normalized_facts,
)
from workers.primary_sources.pipeline import (
    NormalizedMetricFact,
    PrimaryEvidencePassage,
)


FIELD_PHRASES = {
    "basic_shares": "basic shares outstanding",
    "options": "stock options outstanding",
    "warrants": "warrants outstanding",
    "convertibles": "convertible notes",
    "rsus": "restricted stock units",
    "preferreds": "preferred shares",
    "atm_shelf_capacity": "at-the-market program capacity of $100 million",
    "share_growth": "share count growth",
}


def financing_passage(
    reference_key: str,
    *,
    passage_text: str | None = None,
) -> PrimaryEvidencePassage:
    field_id = reference_key.rsplit(":", 1)[-1]
    passage_text = passage_text or (f"The filing reports {FIELD_PHRASES[field_id]}.")
    return PrimaryEvidencePassage(
        reference_key=reference_key,
        source_class="financing",
        coverage_keys=frozenset(),
        source_locator=f"0000000000-26-000001/report.htm#{reference_key}",
        canonical_url=(
            "https://www.sec.gov/Archives/edgar/data/1/000000000026000001/report.htm"
        ),
        publication_at=datetime(2026, 1, 15, 21, tzinfo=UTC),
        retrieved_at=datetime(2026, 1, 16, 9, tzinfo=UTC),
        effective_at=None,
        filing_period_start=None,
        filing_period_end=None,
        document_content_hash=hashlib.sha256(passage_text.encode("utf-8")).hexdigest(),
        passage_text=passage_text,
        freshness="current",
        origin_policy_version="sec-origin-v1",
    )


def absent_financing_passage(
    reference_key: str,
) -> PrimaryEvidencePassage:
    field_id = reference_key.rsplit(":", 1)[-1]
    return financing_passage(
        reference_key,
        passage_text=(f"The filing reports no {FIELD_PHRASES[field_id]}."),
    )


def financing_metric(
    reference_key: str,
    metric_key: str,
    supporting_passage_key: str,
) -> NormalizedMetricFact:
    return NormalizedMetricFact(
        reference_key=reference_key,
        source_class="financing",
        metric_key=metric_key,
        value="100",
        unit="shares",
        period_start=None,
        period_end=None,
        calculation_method="reported",
        formula=None,
        supporting_passage_keys=(supporting_passage_key,),
    )


class FinancingSemanticMatrixTests(unittest.TestCase):
    def test_derives_only_exact_complete_or_absent_field_evidence(self) -> None:
        passages = tuple(
            (
                financing_passage("financing:basic_shares")
                if field_id == "basic_shares"
                else absent_financing_passage(f"financing:{field_id}")
            )
            for field_id in FINANCING_FIELD_IDS
        )
        basic_metric = financing_metric(
            "metric:basic_shares",
            "basic_shares_outstanding",
            "financing:basic_shares",
        )

        evidence = derive_financing_field_evidence(
            passages=passages,
            metrics=(basic_metric,),
        )

        self.assertEqual(
            tuple((item.field_id, item.outcome) for item in evidence),
            (
                ("basic_shares", "complete"),
                ("options", "absent"),
                ("warrants", "absent"),
                ("convertibles", "absent"),
                ("rsus", "absent"),
                ("preferreds", "absent"),
                ("atm_shelf_capacity", "absent"),
                ("share_growth", "absent"),
            ),
        )

    def test_derivation_omits_conflicting_absent_and_positive_passages(self) -> None:
        evidence = derive_financing_field_evidence(
            passages=(
                financing_passage(
                    "financing:options-absent",
                    passage_text="The filing reports no stock options outstanding.",
                ),
                financing_passage(
                    "financing:options-positive",
                    passage_text="The filing reports stock options outstanding.",
                ),
            ),
            metrics=(),
        )

        self.assertNotIn(
            "options",
            {item.field_id for item in evidence},
        )

    def test_sales_agreement_prospectus_supplement_resolves_atm_capacity(
        self,
    ) -> None:
        passage = financing_passage(
            "financing:atm_shelf_capacity",
            passage_text=(
                "a sales agreement prospectus supplement covering the offering, "
                "issuance and sale by the registrant of up to a maximum aggregate "
                "offering price of $150,000,000 of the registrant's common stock "
                "that may be issued and sold from time to time under a sales "
                "agreement with TD Securities (USA) LLC, or TD Cowen."
            ),
        )

        evidence = derive_financing_field_evidence(
            passages=(passage,),
            metrics=(),
        )

        self.assertEqual(
            evidence,
            (
                FinancingFieldEvidence(
                    field_id="atm_shelf_capacity",
                    outcome="complete",
                    evidence_reference_keys=(passage.reference_key,),
                ),
            ),
        )

    def test_sales_agreement_prospectus_title_alone_cannot_resolve_atm_capacity(
        self,
    ) -> None:
        passage = financing_passage(
            "financing:atm_shelf_capacity",
            passage_text=(
                "The registrant filed a sales agreement prospectus supplement "
                "for its common stock offering."
            ),
        )

        evidence = derive_financing_field_evidence(
            passages=(passage,),
            metrics=(),
        )

        self.assertNotIn(
            "atm_shelf_capacity",
            {item.field_id for item in evidence},
        )

        passages = tuple(
            (
                passage
                if field_id == "atm_shelf_capacity"
                else financing_passage(f"financing:{field_id}")
            )
            for field_id in FINANCING_FIELD_IDS
        )
        with self.assertRaisesRegex(
            FinancingSemanticError,
            "atm_shelf_capacity complete outcome conflicts with evidence",
        ):
            build_financing_semantic_matrix(
                field_evidence=tuple(
                    FinancingFieldEvidence(
                        field_id=field_id,
                        outcome="complete",
                        evidence_reference_keys=(f"financing:{field_id}",),
                    )
                    for field_id in FINANCING_FIELD_IDS
                ),
                passages=passages,
                metrics=(),
            )

    def test_hypothetical_shelf_enumeration_cannot_resolve_atm_capacity(
        self,
    ) -> None:
        passage = financing_passage(
            "financing:atm_shelf_capacity",
            passage_text=(
                "This sales agreement prospectus supplement describes securities "
                "we may offer in future offerings, including common stock, "
                "preferred stock, debt securities, and warrants."
            ),
        )

        evidence = derive_financing_field_evidence(
            passages=(passage,),
            metrics=(),
        )

        self.assertNotIn(
            "atm_shelf_capacity",
            {item.field_id for item in evidence},
        )

    def test_preferred_absence_accepts_no_shares_outstanding_phrase(
        self,
    ) -> None:
        passages = tuple(
            (
                financing_passage(
                    "financing:preferreds",
                    passage_text=(
                        "There are no shares of preferred stock outstanding."
                    ),
                )
                if field_id == "preferreds"
                else financing_passage(f"financing:{field_id}")
            )
            for field_id in FINANCING_FIELD_IDS
        )
        preferred_metric = replace(
            financing_metric(
                "metric:preferreds",
                "preferred_shares_outstanding",
                "financing:preferreds",
            ),
            value="0",
        )

        matrix = build_financing_semantic_matrix(
            field_evidence=tuple(
                FinancingFieldEvidence(
                    field_id=field_id,
                    outcome=("absent" if field_id == "preferreds" else "complete"),
                    evidence_reference_keys=(
                        ("metric:preferreds",)
                        if field_id == "preferreds"
                        else (f"financing:{field_id}",)
                    ),
                )
                for field_id in FINANCING_FIELD_IDS
            ),
            passages=passages,
            metrics=(preferred_metric,),
        )

        self.assertEqual(matrix.coverage_state, "complete")

    def test_zero_derived_share_growth_remains_complete_with_exact_support(
        self,
    ) -> None:
        prior = financing_passage(
            "sec-companyfacts:basic_shares_outstanding:2025-12-31:0000000000-26-000001",
            passage_text='{"concept":"EntityCommonStockSharesOutstanding"}',
        )
        current = replace(
            prior,
            reference_key=(
                "sec-companyfacts:basic_shares_outstanding:2026-03-31:"
                "0000000000-26-000002"
            ),
        )
        corporate_action = financing_passage(
            "corporate-action:basis-reconciliation",
            passage_text=(
                "From 2025-12-31 through 2026-03-31, no stock split, reverse "
                "stock split, recapitalization, share class conversion, merger "
                "conversion, or other corporate action changed the basic common "
                "share economic basis."
            ),
        )
        growth = replace(
            financing_metric(
                "financing-metric:share_growth",
                "basic_share_growth",
                prior.reference_key,
            ),
            value="0.000000",
            unit="percent",
            calculation_method="derived",
            supporting_passage_keys=(
                prior.reference_key,
                current.reference_key,
                corporate_action.reference_key,
            ),
        )
        other_passages = tuple(
            financing_passage(f"financing:{field_id}")
            for field_id in FINANCING_FIELD_IDS
            if field_id != "share_growth"
        )
        passages = (*other_passages, prior, current, corporate_action)
        evidence = derive_financing_field_evidence(
            passages=passages,
            metrics=(growth,),
        )

        matrix = build_financing_semantic_matrix(
            field_evidence=evidence,
            passages=passages,
            metrics=(growth,),
        )

        self.assertEqual(matrix.coverage_state, "complete")
        self.assertEqual(
            next(
                outcome.outcome
                for outcome in matrix.outcomes
                if outcome.field_id == "share_growth"
            ),
            "complete",
        )

    def test_future_shelf_authority_cannot_prove_complete_warrants(
        self,
    ) -> None:
        passages = tuple(
            (
                financing_passage(
                    "financing:warrants",
                    passage_text=(
                        "We may offer warrants for the purchase of Class A "
                        "common stock in one or more future offerings."
                    ),
                )
                if field_id == "warrants"
                else financing_passage(f"financing:{field_id}")
            )
            for field_id in FINANCING_FIELD_IDS
        )

        with self.assertRaisesRegex(
            FinancingSemanticError,
            "warrants complete outcome conflicts with evidence",
        ):
            build_financing_semantic_matrix(
                field_evidence=tuple(
                    FinancingFieldEvidence(
                        field_id=field_id,
                        outcome="complete",
                        evidence_reference_keys=(f"financing:{field_id}",),
                    )
                    for field_id in FINANCING_FIELD_IDS
                ),
                passages=passages,
                metrics=(),
            )

    def test_missing_field_reason_codes_preserve_each_gap(self) -> None:
        field_evidence = tuple(
            FinancingFieldEvidence(
                field_id=field_id,
                outcome="complete",
                evidence_reference_keys=(f"financing:{field_id}",),
            )
            for field_id in FINANCING_FIELD_IDS
            if field_id not in {"warrants", "convertibles", "preferreds"}
        )

        self.assertEqual(
            financing_missing_field_reason_codes(field_evidence),
            (
                "financing_field_warrants_unresolved",
                "financing_field_convertibles_unresolved",
                "financing_field_preferreds_unresolved",
            ),
        )

    def test_complete_matrix_addresses_every_field_with_exact_evidence(
        self,
    ) -> None:
        passages = tuple(
            financing_passage(f"financing:{field_id}")
            for field_id in FINANCING_FIELD_IDS
        )
        matrix = build_financing_semantic_matrix(
            field_evidence=tuple(
                FinancingFieldEvidence(
                    field_id=field_id,
                    outcome="complete",
                    evidence_reference_keys=(f"financing:{field_id}",),
                )
                for field_id in FINANCING_FIELD_IDS
            ),
            passages=passages,
            metrics=(),
        )

        self.assertEqual(
            matrix.policy_version,
            FINANCING_SEMANTIC_POLICY_VERSION,
        )
        self.assertEqual(matrix.coverage_state, "complete")
        self.assertEqual(
            tuple(outcome.field_id for outcome in matrix.outcomes),
            FINANCING_FIELD_IDS,
        )
        self.assertEqual(matrix.reason_codes, ())

    def test_matrix_rejects_a_missing_required_field(self) -> None:
        field_evidence = tuple(
            FinancingFieldEvidence(
                field_id=field_id,
                outcome="complete",
                evidence_reference_keys=(f"financing:{field_id}",),
            )
            for field_id in FINANCING_FIELD_IDS[:-1]
        )

        with self.assertRaisesRegex(
            FinancingSemanticError,
            "missing required fields: share_growth",
        ):
            build_financing_semantic_matrix(
                field_evidence=field_evidence,
                passages=tuple(
                    financing_passage(reference_key)
                    for outcome in field_evidence
                    for reference_key in outcome.evidence_reference_keys
                ),
                metrics=(),
            )

    def test_matrix_rejects_an_unsupported_field_outcome(self) -> None:
        field_evidence = tuple(
            FinancingFieldEvidence(
                field_id=field_id,
                outcome=("unknown" if field_id == "convertibles" else "not_applicable"),
                evidence_reference_keys=(f"financing:{field_id}",),
            )
            for field_id in FINANCING_FIELD_IDS
        )

        with self.assertRaisesRegex(
            FinancingSemanticError,
            "convertibles outcome is invalid",
        ):
            build_financing_semantic_matrix(
                field_evidence=field_evidence,
                passages=tuple(
                    absent_financing_passage(f"financing:{field_id}")
                    for field_id in FINANCING_FIELD_IDS
                ),
                metrics=(),
            )

    def test_each_field_outcome_requires_resolved_evidence(self) -> None:
        field_evidence = tuple(
            FinancingFieldEvidence(
                field_id=field_id,
                outcome="absent",
                evidence_reference_keys=(
                    (
                        "financing:missing"
                        if field_id == "warrants"
                        else f"financing:{field_id}"
                    ),
                ),
            )
            for field_id in FINANCING_FIELD_IDS
        )

        with self.assertRaisesRegex(
            FinancingSemanticError,
            "warrants evidence reference is unresolved",
        ):
            build_financing_semantic_matrix(
                field_evidence=field_evidence,
                passages=tuple(
                    absent_financing_passage(f"financing:{field_id}")
                    for field_id in FINANCING_FIELD_IDS
                ),
                metrics=(),
            )

    def test_non_financing_passage_cannot_back_a_field_outcome(self) -> None:
        passages = tuple(
            (
                replace(
                    financing_passage(f"financing:{field_id}"),
                    source_class="sec",
                )
                if field_id == "options"
                else financing_passage(f"financing:{field_id}")
            )
            for field_id in FINANCING_FIELD_IDS
        )

        with self.assertRaisesRegex(
            FinancingSemanticError,
            "options passage evidence is not financing evidence",
        ):
            build_financing_semantic_matrix(
                field_evidence=tuple(
                    FinancingFieldEvidence(
                        field_id=field_id,
                        outcome="complete",
                        evidence_reference_keys=(f"financing:{field_id}",),
                    )
                    for field_id in FINANCING_FIELD_IDS
                ),
                passages=passages,
                metrics=(),
            )

    def test_generic_dilution_passage_cannot_prove_a_specific_field(
        self,
    ) -> None:
        passages = tuple(
            (
                financing_passage(
                    f"financing:{field_id}",
                    passage_text=(
                        "The company reported outstanding dilution instruments."
                    ),
                )
                if field_id == "warrants"
                else financing_passage(f"financing:{field_id}")
            )
            for field_id in FINANCING_FIELD_IDS
        )

        with self.assertRaisesRegex(
            FinancingSemanticError,
            "warrants passage is not semantically field-specific",
        ):
            build_financing_semantic_matrix(
                field_evidence=tuple(
                    FinancingFieldEvidence(
                        field_id=field_id,
                        outcome="complete",
                        evidence_reference_keys=(f"financing:{field_id}",),
                    )
                    for field_id in FINANCING_FIELD_IDS
                ),
                passages=passages,
                metrics=(),
            )

    def test_absent_outcome_rejects_positive_disclosure_and_nonzero_metric(
        self,
    ) -> None:
        passages = tuple(
            (
                financing_passage(f"financing:{field_id}")
                if field_id == "basic_shares"
                else absent_financing_passage(f"financing:{field_id}")
            )
            for field_id in FINANCING_FIELD_IDS
        )
        metrics = tuple(
            financing_metric(
                f"metric:{field_id}",
                next(iter(FINANCING_METRIC_KEYS_BY_FIELD[field_id])),
                f"financing:{field_id}",
            )
            for field_id in FINANCING_FIELD_IDS
        )

        with self.assertRaisesRegex(
            FinancingSemanticError,
            "basic_shares absent outcome conflicts with evidence",
        ):
            build_financing_semantic_matrix(
                field_evidence=tuple(
                    FinancingFieldEvidence(
                        field_id=field_id,
                        outcome="absent",
                        evidence_reference_keys=(f"metric:{field_id}",),
                    )
                    for field_id in FINANCING_FIELD_IDS
                ),
                passages=passages,
                metrics=metrics,
            )

    def test_complete_outcome_rejects_not_applicable_disclosure(
        self,
    ) -> None:
        passages = tuple(
            (
                financing_passage(
                    "financing:basic_shares",
                    passage_text="Basic shares are not applicable.",
                )
                if field_id == "basic_shares"
                else financing_passage(f"financing:{field_id}")
            )
            for field_id in FINANCING_FIELD_IDS
        )

        with self.assertRaisesRegex(
            FinancingSemanticError,
            "basic_shares complete outcome conflicts with evidence",
        ):
            build_financing_semantic_matrix(
                field_evidence=tuple(
                    FinancingFieldEvidence(
                        field_id=field_id,
                        outcome="complete",
                        evidence_reference_keys=(f"financing:{field_id}",),
                    )
                    for field_id in FINANCING_FIELD_IDS
                ),
                passages=passages,
                metrics=(),
            )

    def test_not_applicable_outcome_rejects_even_zero_metric(
        self,
    ) -> None:
        passages = tuple(
            (
                financing_passage(
                    "financing:basic_shares",
                    passage_text="Basic shares are not applicable.",
                )
                if field_id == "basic_shares"
                else financing_passage(f"financing:{field_id}")
            )
            for field_id in FINANCING_FIELD_IDS
        )
        metric = replace(
            financing_metric(
                "metric:basic-shares",
                "basic_shares_outstanding",
                "financing:basic_shares",
            ),
            value="0",
        )

        with self.assertRaisesRegex(
            FinancingSemanticError,
            "basic_shares not_applicable outcome conflicts with evidence",
        ):
            build_financing_semantic_matrix(
                field_evidence=tuple(
                    FinancingFieldEvidence(
                        field_id=field_id,
                        outcome=(
                            "not_applicable"
                            if field_id == "basic_shares"
                            else "complete"
                        ),
                        evidence_reference_keys=(
                            (metric.reference_key,)
                            if field_id == "basic_shares"
                            else (f"financing:{field_id}",)
                        ),
                    )
                    for field_id in FINANCING_FIELD_IDS
                ),
                passages=passages,
                metrics=(metric,),
            )

    def test_duplicate_field_outcome_is_rejected(self) -> None:
        field_evidence = tuple(
            FinancingFieldEvidence(
                field_id=field_id,
                outcome="complete",
                evidence_reference_keys=(f"financing:{field_id}",),
            )
            for field_id in FINANCING_FIELD_IDS
        )

        with self.assertRaisesRegex(
            FinancingSemanticError,
            "duplicate field outcome: basic_shares",
        ):
            build_financing_semantic_matrix(
                field_evidence=(
                    *field_evidence,
                    field_evidence[0],
                ),
                passages=tuple(
                    financing_passage(f"financing:{field_id}")
                    for field_id in FINANCING_FIELD_IDS
                ),
                metrics=(),
            )

    def test_unknown_field_outcome_is_rejected(self) -> None:
        field_evidence = tuple(
            FinancingFieldEvidence(
                field_id=field_id,
                outcome="complete",
                evidence_reference_keys=(f"financing:{field_id}",),
            )
            for field_id in FINANCING_FIELD_IDS
        )

        with self.assertRaisesRegex(
            FinancingSemanticError,
            "unknown financing fields: target_price",
        ):
            build_financing_semantic_matrix(
                field_evidence=(
                    *field_evidence,
                    FinancingFieldEvidence(
                        field_id="target_price",
                        outcome="complete",
                        evidence_reference_keys=("financing:basic_shares",),
                    ),
                ),
                passages=tuple(
                    financing_passage(f"financing:{field_id}")
                    for field_id in FINANCING_FIELD_IDS
                ),
                metrics=(),
            )

    def test_normalized_metric_must_belong_to_the_financing_field(
        self,
    ) -> None:
        field_evidence = tuple(
            FinancingFieldEvidence(
                field_id=field_id,
                outcome="complete",
                evidence_reference_keys=(
                    (
                        "metric:basic-shares"
                        if field_id == "options"
                        else f"financing:{field_id}"
                    ),
                ),
            )
            for field_id in FINANCING_FIELD_IDS
        )

        with self.assertRaisesRegex(
            FinancingSemanticError,
            "options metric key is not field-specific",
        ):
            build_financing_semantic_matrix(
                field_evidence=field_evidence,
                passages=tuple(
                    financing_passage(f"financing:{field_id}")
                    for field_id in FINANCING_FIELD_IDS
                ),
                metrics=(
                    financing_metric(
                        "metric:basic-shares",
                        "basic_shares_outstanding",
                        "financing:basic_shares",
                    ),
                ),
            )

    def test_non_financing_metric_cannot_back_a_field_outcome(self) -> None:
        field_evidence = tuple(
            FinancingFieldEvidence(
                field_id=field_id,
                outcome="complete",
                evidence_reference_keys=(
                    (
                        "metric:basic-shares"
                        if field_id == "basic_shares"
                        else f"financing:{field_id}"
                    ),
                ),
            )
            for field_id in FINANCING_FIELD_IDS
        )
        metric = replace(
            financing_metric(
                "metric:basic-shares",
                "basic_shares_outstanding",
                "financing:basic_shares",
            ),
            source_class="issuer",
        )

        with self.assertRaisesRegex(
            FinancingSemanticError,
            "basic_shares metric evidence is not financing evidence",
        ):
            build_financing_semantic_matrix(
                field_evidence=field_evidence,
                passages=tuple(
                    financing_passage(f"financing:{field_id}")
                    for field_id in FINANCING_FIELD_IDS
                ),
                metrics=(metric,),
            )

    def test_normalized_metric_requires_exact_financing_passage_support(
        self,
    ) -> None:
        field_evidence = tuple(
            FinancingFieldEvidence(
                field_id=field_id,
                outcome="complete",
                evidence_reference_keys=(
                    (
                        "metric:basic-shares"
                        if field_id == "basic_shares"
                        else f"financing:{field_id}"
                    ),
                ),
            )
            for field_id in FINANCING_FIELD_IDS
        )

        with self.assertRaisesRegex(
            FinancingSemanticError,
            "basic_shares metric support is unresolved",
        ):
            build_financing_semantic_matrix(
                field_evidence=field_evidence,
                passages=tuple(
                    financing_passage(f"financing:{field_id}")
                    for field_id in FINANCING_FIELD_IDS
                    if field_id != "basic_shares"
                ),
                metrics=(
                    financing_metric(
                        "metric:basic-shares",
                        "basic_shares_outstanding",
                        "financing:missing",
                    ),
                ),
            )

    def test_metric_support_passage_must_be_semantically_field_specific(
        self,
    ) -> None:
        field_evidence = tuple(
            FinancingFieldEvidence(
                field_id=field_id,
                outcome="complete",
                evidence_reference_keys=(
                    (
                        "metric:basic-shares"
                        if field_id == "basic_shares"
                        else f"financing:{field_id}"
                    ),
                ),
            )
            for field_id in FINANCING_FIELD_IDS
        )
        passages = tuple(
            (
                financing_passage(
                    "financing:basic_shares",
                    passage_text=(
                        "The company reported outstanding dilution instruments."
                    ),
                )
                if field_id == "basic_shares"
                else financing_passage(f"financing:{field_id}")
            )
            for field_id in FINANCING_FIELD_IDS
        )

        with self.assertRaisesRegex(
            FinancingSemanticError,
            "basic_shares metric support is not semantically field-specific",
        ):
            build_financing_semantic_matrix(
                field_evidence=field_evidence,
                passages=passages,
                metrics=(
                    financing_metric(
                        "metric:basic-shares",
                        "basic_shares_outstanding",
                        "financing:basic_shares",
                    ),
                ),
            )

    def test_companyfacts_basic_share_tag_is_field_specific(self) -> None:
        passages = tuple(
            (
                financing_passage(
                    "financing:basic_shares",
                    passage_text=('{"metric":"EntityCommonStockSharesOutstanding"}'),
                )
                if field_id == "basic_shares"
                else financing_passage(f"financing:{field_id}")
            )
            for field_id in FINANCING_FIELD_IDS
        )

        matrix = build_financing_semantic_matrix(
            field_evidence=tuple(
                FinancingFieldEvidence(
                    field_id=field_id,
                    outcome="complete",
                    evidence_reference_keys=(
                        ("metric:basic-shares",)
                        if field_id == "basic_shares"
                        else (f"financing:{field_id}",)
                    ),
                )
                for field_id in FINANCING_FIELD_IDS
            ),
            passages=passages,
            metrics=(
                financing_metric(
                    "metric:basic-shares",
                    "basic_shares_outstanding",
                    "financing:basic_shares",
                ),
            ),
        )

        self.assertEqual(matrix.coverage_state, "complete")

    def test_us_gaap_common_stock_shares_tag_is_field_specific(self) -> None:
        passages = tuple(
            (
                financing_passage(
                    "financing:basic_shares",
                    passage_text=('{"metric":"us-gaap:CommonStockSharesOutstanding"}'),
                )
                if field_id == "basic_shares"
                else financing_passage(f"financing:{field_id}")
            )
            for field_id in FINANCING_FIELD_IDS
        )

        matrix = build_financing_semantic_matrix(
            field_evidence=tuple(
                FinancingFieldEvidence(
                    field_id=field_id,
                    outcome="complete",
                    evidence_reference_keys=(
                        ("metric:basic-shares",)
                        if field_id == "basic_shares"
                        else (f"financing:{field_id}",)
                    ),
                )
                for field_id in FINANCING_FIELD_IDS
            ),
            passages=passages,
            metrics=(
                financing_metric(
                    "metric:basic-shares",
                    "basic_shares_outstanding",
                    "financing:basic_shares",
                ),
            ),
        )

        self.assertEqual(matrix.coverage_state, "complete")

    def test_complete_matrix_converts_to_deterministic_normalized_facts(
        self,
    ) -> None:
        passages = tuple(
            (
                financing_passage(f"financing:{field_id}")
                if field_id == "basic_shares"
                else absent_financing_passage(f"financing:{field_id}")
            )
            for field_id in FINANCING_FIELD_IDS
        )
        metric = replace(
            financing_metric(
                "metric:basic-shares",
                "basic_shares_outstanding",
                "financing:basic_shares",
            ),
            value="125000000",
            period_start=datetime(2025, 12, 31, tzinfo=UTC).date(),
            period_end=datetime(2026, 3, 31, tzinfo=UTC).date(),
            calculation_method="reported_period_end",
            formula="issuer_reported_basic_shares",
        )
        matrix = build_financing_semantic_matrix(
            field_evidence=tuple(
                FinancingFieldEvidence(
                    field_id=field_id,
                    outcome=("complete" if field_id == "basic_shares" else "absent"),
                    evidence_reference_keys=(
                        (
                            metric.reference_key,
                            f"financing:{field_id}",
                        )
                        if field_id == "basic_shares"
                        else (f"financing:{field_id}",)
                    ),
                )
                for field_id in FINANCING_FIELD_IDS
            ),
            passages=passages,
            metrics=(metric,),
        )

        facts = financing_matrix_to_normalized_facts(matrix)

        self.assertEqual(
            tuple(fact.field_id for fact in facts),
            FINANCING_FIELD_IDS,
        )
        basic = facts[0]
        self.assertEqual(basic.outcome, "complete")
        self.assertEqual(basic.metric_key, "basic_shares_outstanding")
        self.assertEqual(basic.value, "125000000")
        self.assertEqual(basic.unit, "shares")
        self.assertEqual(
            basic.period_start.isoformat(),
            "2025-12-31",
        )
        self.assertEqual(
            basic.period_end.isoformat(),
            "2026-03-31",
        )
        self.assertEqual(
            basic.calculation_method,
            "reported_period_end",
        )
        self.assertEqual(
            basic.formula,
            "issuer_reported_basic_shares",
        )
        self.assertEqual(
            basic.evidence_reference_keys,
            (
                "metric:basic-shares",
                "financing:basic_shares",
            ),
        )
        warrants = facts[2]
        self.assertEqual(warrants.outcome, "absent")
        self.assertIsNone(warrants.metric_key)
        self.assertIsNone(warrants.value)
        self.assertEqual(
            warrants.evidence_reference_keys,
            ("financing:warrants",),
        )

    def test_only_complete_validated_matrix_converts_to_facts(self) -> None:
        passages = tuple(
            absent_financing_passage(f"financing:{field_id}")
            for field_id in FINANCING_FIELD_IDS
        )
        matrix = build_financing_semantic_matrix(
            field_evidence=tuple(
                FinancingFieldEvidence(
                    field_id=field_id,
                    outcome="absent",
                    evidence_reference_keys=(f"financing:{field_id}",),
                )
                for field_id in FINANCING_FIELD_IDS
            ),
            passages=passages,
            metrics=(),
        )

        with self.assertRaisesRegex(
            FinancingSemanticError,
            "matrix is not complete",
        ):
            financing_matrix_to_normalized_facts(
                replace(matrix, coverage_state="incomplete")
            )


if __name__ == "__main__":
    unittest.main()

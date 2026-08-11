from __future__ import annotations

import hashlib
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime

from workers.primary_sources.eligibility import (
    ELIGIBILITY_RULE_IDS,
    ELIGIBILITY_SOURCE_POLICY_VERSION,
    DerivedEligibilityProfile,
    EligibilityRuleSourceOutcome,
)
from workers.primary_sources.models import PrimarySourceRequest
from workers.primary_sources.pipeline import (
    NormalizedCatalystFact,
    NormalizedMetricFact,
    NormalizedRiskFact,
    PrimaryEvidencePassage,
    PrimarySourceCoverageProof,
    PrimarySourcePipeline,
    PrimarySourcePipelineError,
)


OPERATOR_ID = "8ed47ebc-d5cf-40ad-80ce-d4d803f7c735"
SECURITY_ID = "f594edb2-7fff-4e40-9c26-2c06bcbecb91"
CUTOFF = datetime(2026, 5, 6, 23, 59, 59, tzinfo=UTC)
RETRIEVED_AT = datetime(2026, 5, 7, 1, 0, tzinfo=UTC)


def source_request() -> PrimarySourceRequest:
    return PrimarySourceRequest(
        operator_id=OPERATOR_ID,
        security_id=SECURITY_ID,
        cik="0001601830",
        issuer_name="Example Therapeutics, Inc.",
        primary_listing_exchange="NASDAQ",
        as_of_cutoff=CUTOFF,
    )


def passage(
    reference_key: str,
    source_class: str,
    coverage_key: str,
) -> PrimaryEvidencePassage:
    text = (
        "FDA ORPHAN DRUG designation for EX-101."
        if source_class == "regulatory"
        else f"Exact primary-source text for {reference_key}."
    )
    document = f"Primary document containing {text}"
    hosts = {
        "sec": "www.sec.gov",
        "issuer": "investors.example-biotech.com",
        "clinical": "clinicaltrials.gov",
        "regulatory": "www.fda.gov",
        "financing": "data.sec.gov",
    }
    origin_policies = {
        "sec": "sec-origin-v1",
        "issuer": "official-issuer-origin-v1",
        "clinical": "clinical-trials-origin-v1",
        "regulatory": "fda-origin-v1",
        "financing": "sec-origin-v1",
    }
    return PrimaryEvidencePassage(
        reference_key=reference_key,
        source_class=source_class,
        coverage_keys=frozenset({coverage_key}),
        source_locator=f"{reference_key} section",
        canonical_url=f"https://{hosts[source_class]}/{reference_key}",
        publication_at=datetime(2026, 5, 5, 20, 0, tzinfo=UTC),
        retrieved_at=RETRIEVED_AT,
        effective_at=datetime(2026, 5, 5, 20, 0, tzinfo=UTC),
        filing_period_start=None,
        filing_period_end=None,
        document_content_hash=hashlib.sha256(document.encode()).hexdigest(),
        passage_text=text,
        freshness="current",
        origin_policy_version=origin_policies[source_class],
    )


def required_passages() -> tuple[PrimaryEvidencePassage, ...]:
    return (
        passage("sec-identity", "sec", "sec_issuer_security"),
        passage("sec-filings", "sec", "required_sec_filings"),
        passage("issuer-pipeline", "issuer", "issuer_pipeline"),
        passage("trial-record", "clinical", "authoritative_trial"),
        passage("regulatory-record", "regulatory", "us_regulatory"),
        passage(
            "financing-record",
            "financing",
            "financing_share_capital",
        ),
    )


def required_coverage_proofs() -> tuple[PrimarySourceCoverageProof, ...]:
    return (
        PrimarySourceCoverageProof(
            "sec_issuer_security",
            "sec",
            "sec-issuer-identity-v1",
            "complete",
            ("sec_identity_verified",),
            ("sec-identity",),
        ),
        PrimarySourceCoverageProof(
            "required_sec_filings",
            "sec",
            "biotech-required-sec-filings-v1",
            "complete",
            ("sec_required_filings_complete",),
            ("sec-filings",),
        ),
        PrimarySourceCoverageProof(
            "issuer_pipeline",
            "issuer",
            "official-issuer-source-v1",
            "complete",
            ("issuer_pipeline_complete",),
            ("issuer-pipeline",),
        ),
        PrimarySourceCoverageProof(
            "authoritative_trial",
            "clinical",
            "clinical-trials-source-v2",
            "complete",
            ("clinical_trials_source_covered",),
            ("trial-record",),
        ),
        PrimarySourceCoverageProof(
            "us_regulatory",
            "regulatory",
            "fda-regulatory-source-v2",
            "complete",
            ("us_regulatory_complete",),
            ("regulatory-record",),
        ),
        PrimarySourceCoverageProof(
            "financing_share_capital",
            "financing",
            "biotech-financing-share-capital-v1",
            "complete",
            ("sec_companyfacts_financing_complete",),
            ("financing-record",),
        ),
    )


def security_profile(
    *,
    catalyst: bool = False,
) -> DerivedEligibilityProfile:
    references = {
        "security_identity_verified": ("sec-identity",),
        "us_listing": ("sec-identity",),
        "cik_match": ("sec-identity",),
        "common_equity": ("sec-identity",),
        "operating_company": ("sec-filings",),
        "therapeutics_classification": ("issuer-pipeline",),
        "active_therapeutic_program": ("trial-record",),
        "defined_clinical_or_regulatory_catalyst": ("trial-record",),
        "required_primary_source_coverage": ("regulatory-record",),
    }
    values = {
        "security_identity_verified": ("true",),
        "us_listing": ("US", "NASDAQ"),
        "cik_match": ("0001601830",),
        "common_equity": ("common_equity",),
        "operating_company": ("operating",),
        "therapeutics_classification": ("therapeutics_biotech",),
        "active_therapeutic_program": ("EX-101",),
        "defined_clinical_or_regulatory_catalyst": (
            "NCT00000001:primary_completion:2026-12",
        ),
        "required_primary_source_coverage": (
            "authoritative_trial",
            "financing_share_capital",
            "issuer_pipeline",
            "required_sec_filings",
            "sec_issuer_security",
            "us_regulatory",
        ),
    }
    return DerivedEligibilityProfile(
        policy_version=ELIGIBILITY_SOURCE_POLICY_VERSION,
        display_symbol="EXMP",
        primary_listing_country="US",
        security_type="common_equity",
        issuer_status="operating",
        therapeutics_classification="therapeutics_biotech",
        active_therapeutic_programs=("EX-101",),
        outcomes=tuple(
            EligibilityRuleSourceOutcome(
                rule_id=rule_id,
                rule_version=f"{rule_id}.source.v1",
                state=(
                    "pass"
                    if rule_id != "defined_clinical_or_regulatory_catalyst" or catalyst
                    else "fail"
                ),
                reason_code=(
                    f"{rule_id}_verified"
                    if rule_id != "defined_clinical_or_regulatory_catalyst" or catalyst
                    else f"{rule_id}_not_verified"
                ),
                evidence_reference_keys=references[rule_id],
                normalized_values=values[rule_id],
            )
            for rule_id in ELIGIBILITY_RULE_IDS
        ),
    )


def replace_outcome(
    profile: DerivedEligibilityProfile,
    rule_id: str,
    *,
    evidence_reference_keys: tuple[str, ...],
    state: str = "pass",
) -> DerivedEligibilityProfile:
    return replace(
        profile,
        outcomes=tuple(
            (
                replace(
                    outcome,
                    state=state,
                    reason_code=(
                        f"{rule_id}_verified"
                        if state == "pass"
                        else f"{rule_id}_not_verified"
                    ),
                    evidence_reference_keys=evidence_reference_keys,
                )
                if outcome.rule_id == rule_id
                else outcome
            )
            for outcome in profile.outcomes
        ),
    )


class PrimarySourcePipelineTests(unittest.TestCase):
    def test_pipeline_rejects_self_attested_profile_object(self) -> None:
        with self.assertRaisesRegex(
            PrimarySourcePipelineError,
            "must be deterministically derived",
        ):
            PrimarySourcePipeline().assemble(
                request=source_request(),
                profile=object(),  # type: ignore[arg-type]
                passages=required_passages(),
                coverage_proofs=required_coverage_proofs(),
            )

    def test_failed_rule_outcome_cannot_be_reconstructed_as_passed(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            PrimarySourcePipelineError,
            "conflicts with normalized evidence: us_listing",
        ):
            PrimarySourcePipeline().assemble(
                request=source_request(),
                profile=replace_outcome(
                    security_profile(),
                    "us_listing",
                    evidence_reference_keys=("sec-identity",),
                    state="fail",
                ),
                passages=required_passages(),
                coverage_proofs=required_coverage_proofs(),
            )

    def test_complete_primary_sources_build_shared_eligibility_and_bundle_inputs(
        self,
    ) -> None:
        result = PrimarySourcePipeline().assemble(
            request=source_request(),
            profile=security_profile(),
            passages=required_passages(),
            coverage_proofs=required_coverage_proofs(),
        )

        self.assertEqual(
            result.eligibility_snapshot.primary_source_coverage,
            frozenset(
                {
                    "sec_issuer_security",
                    "required_sec_filings",
                    "issuer_pipeline",
                    "authoritative_trial",
                    "us_regulatory",
                    "financing_share_capital",
                }
            ),
        )
        self.assertEqual(
            [item.source_class for item in result.bundle_candidate.items],
            ["sec", "sec", "issuer", "clinical", "regulatory", "financing"],
        )
        self.assertEqual(
            {
                reference.evidence_id
                for reference in result.eligibility_snapshot.evidence_by_rule.values()
            }
            <= {item.evidence_id for item in result.bundle_candidate.items},
            True,
        )
        self.assertEqual(
            result.bundle_candidate.evidence_policy_version,
            "biotech-primary-evidence-v2",
        )
        self.assertEqual(result.reason_codes, ("primary_source_coverage_complete",))

    def test_coverage_policy_version_must_match_requirement_contract(
        self,
    ) -> None:
        invalid = replace(
            required_coverage_proofs()[0],
            policy_version="wrong-policy-v1",
        )

        with self.assertRaisesRegex(
            PrimarySourcePipelineError,
            "primary source coverage policy is invalid",
        ):
            PrimarySourcePipeline().assemble(
                request=source_request(),
                profile=security_profile(),
                passages=required_passages(),
                coverage_proofs=(
                    invalid,
                    *required_coverage_proofs()[1:],
                ),
            )

    def test_verified_date_only_source_uses_conservative_availability_time(
        self,
    ) -> None:
        date_only = replace(
            required_passages()[2],
            publication_at=None,
            available_at=datetime(2026, 5, 5, 23, 59, 59, 999999, tzinfo=UTC),
        )
        result = PrimarySourcePipeline().assemble(
            request=source_request(),
            profile=security_profile(),
            passages=(
                *required_passages()[:2],
                date_only,
                *required_passages()[3:],
            ),
            coverage_proofs=required_coverage_proofs(),
        )

        issuer = next(
            item
            for item in result.bundle_candidate.items
            if item.source_class == "issuer"
        )
        self.assertIsNone(issuer.publication_at)
        self.assertEqual(
            result.eligibility_snapshot.evidence_by_rule[
                "therapeutics_classification"
            ].available_at,
            date_only.available_at,
        )

    def test_retrieval_cannot_predate_source_availability(self) -> None:
        invalid = replace(
            required_passages()[2],
            retrieved_at=datetime(2026, 5, 4, 20, 0, tzinfo=UTC),
        )
        with self.assertRaisesRegex(
            PrimarySourcePipelineError,
            "retrieval predates availability",
        ):
            PrimarySourcePipeline().assemble(
                request=source_request(),
                profile=security_profile(),
                passages=(
                    *required_passages()[:2],
                    invalid,
                    *required_passages()[3:],
                ),
                coverage_proofs=required_coverage_proofs(),
            )

    def test_authoritative_source_class_rejects_arbitrary_origin(
        self,
    ) -> None:
        invalid = replace(
            required_passages()[0],
            canonical_url="https://example.com/sec-identity",
        )

        with self.assertRaisesRegex(
            PrimarySourcePipelineError,
            "origin is not authoritative",
        ):
            PrimarySourcePipeline().assemble(
                request=source_request(),
                profile=security_profile(),
                passages=(invalid, *required_passages()[1:]),
                coverage_proofs=required_coverage_proofs(),
            )

    def test_accepts_explicit_accessdata_fda_regulatory_origin(self) -> None:
        regulatory = replace(
            required_passages()[4],
            canonical_url=(
                "https://www.accessdata.fda.gov/scripts/opdlisting/oopd/"
                "detailedIndex.cfm?cfgridkey=817621"
            ),
        )

        result = PrimarySourcePipeline().assemble(
            request=source_request(),
            profile=security_profile(),
            passages=(
                *required_passages()[:4],
                regulatory,
                required_passages()[5],
            ),
            coverage_proofs=required_coverage_proofs(),
        )

        self.assertEqual(
            result.reason_codes,
            ("primary_source_coverage_complete",),
        )

    def test_complete_regulatory_proof_requires_programme_designation_bridge(
        self,
    ) -> None:
        regulatory = replace(
            required_passages()[4],
            passage_text=(
                "Designation Date 10/10/2023. Sponsor Example Therapeutics, Inc."
            ),
        )

        with self.assertRaisesRegex(
            PrimarySourcePipelineError,
            "regulatory programme linkage is unresolved",
        ):
            PrimarySourcePipeline().assemble(
                request=source_request(),
                profile=security_profile(),
                passages=(
                    *required_passages()[:4],
                    regulatory,
                    required_passages()[5],
                ),
                coverage_proofs=required_coverage_proofs(),
            )

    def test_regulatory_proof_cannot_borrow_uncited_programme_passage(self) -> None:
        regulatory = replace(
            required_passages()[4],
            passage_text="FDA ORPHAN DRUG designation record.",
        )
        uncited_programme = replace(
            regulatory,
            reference_key="uncited-regulatory-programme",
            coverage_keys=frozenset(),
            passage_text="EX-101",
        )

        with self.assertRaisesRegex(
            PrimarySourcePipelineError,
            "regulatory programme linkage is unresolved",
        ):
            PrimarySourcePipeline().assemble(
                request=source_request(),
                profile=security_profile(),
                passages=(
                    *required_passages()[:4],
                    regulatory,
                    uncited_programme,
                    required_passages()[5],
                ),
                coverage_proofs=required_coverage_proofs(),
            )

    def test_eligibility_rule_requires_owned_source_class(
        self,
    ) -> None:
        profile = security_profile()

        with self.assertRaisesRegex(
            PrimarySourcePipelineError,
            "eligibility rule evidence source is invalid",
        ):
            PrimarySourcePipeline().assemble(
                request=source_request(),
                profile=replace_outcome(
                    profile,
                    "therapeutics_classification",
                    evidence_reference_keys=("sec-identity",),
                ),
                passages=required_passages(),
                coverage_proofs=required_coverage_proofs(),
            )

    def test_missing_rule_evidence_remains_reason_coded_for_eligibility(
        self,
    ) -> None:
        profile = security_profile()
        incomplete_profile = replace_outcome(
            profile,
            "operating_company",
            evidence_reference_keys=(),
            state="fail",
        )
        result = PrimarySourcePipeline().assemble(
            request=source_request(),
            profile=replace(incomplete_profile, issuer_status="unknown"),
            passages=required_passages(),
            coverage_proofs=required_coverage_proofs(),
        )

        self.assertNotIn(
            "operating_company",
            result.eligibility_snapshot.evidence_by_rule,
        )

    def test_missing_blocking_source_is_reason_coded_before_eligibility(self) -> None:
        profile = security_profile()

        result = PrimarySourcePipeline().assemble(
            request=source_request(),
            profile=replace_outcome(
                profile,
                "required_primary_source_coverage",
                evidence_reference_keys=("financing-record",),
                state="fail",
            ),
            passages=tuple(
                item
                for item in required_passages()
                if item.reference_key != "regulatory-record"
            ),
            coverage_proofs=tuple(
                proof
                if proof.requirement_id != "us_regulatory"
                else PrimarySourceCoverageProof(
                    "us_regulatory",
                    "regulatory",
                    "fda-regulatory-source-v2",
                    "incomplete",
                    ("us_regulatory_unavailable",),
                    (),
                )
                for proof in required_coverage_proofs()
            ),
        )

        self.assertNotIn(
            "us_regulatory",
            result.eligibility_snapshot.primary_source_coverage,
        )
        self.assertEqual(
            result.reason_codes,
            (
                "us_regulatory_unavailable",
                "missing_us_regulatory",
                "primary_source_coverage_incomplete",
            ),
        )

    def test_missing_requirement_inside_present_source_declares_blocking_gap(
        self,
    ) -> None:
        profile = security_profile()
        incomplete_profile = replace_outcome(
            replace_outcome(
                profile,
                "operating_company",
                evidence_reference_keys=("sec-identity",),
            ),
            "required_primary_source_coverage",
            evidence_reference_keys=("regulatory-record",),
            state="fail",
        )
        result = PrimarySourcePipeline().assemble(
            request=source_request(),
            profile=incomplete_profile,
            passages=tuple(
                item
                for item in required_passages()
                if item.reference_key != "sec-filings"
            ),
            coverage_proofs=tuple(
                proof
                if proof.requirement_id != "required_sec_filings"
                else PrimarySourceCoverageProof(
                    "required_sec_filings",
                    "sec",
                    "biotech-required-sec-filings-v1",
                    "incomplete",
                    ("sec_required_filings_incomplete",),
                    ("sec-identity",),
                )
                for proof in required_coverage_proofs()
            ),
        )

        self.assertEqual(
            [gap.code for gap in result.bundle_candidate.declared_gaps],
            ["missing_blocking_required_sec_filings_evidence"],
        )
        self.assertEqual(
            result.bundle_candidate.declared_gaps[0].source_class,
            "sec",
        )

    def test_incomplete_source_evidence_is_preserved_without_claiming_coverage(
        self,
    ) -> None:
        incomplete_financing = replace(
            required_passages()[-1],
            coverage_keys=frozenset(),
        )
        result = PrimarySourcePipeline().assemble(
            request=source_request(),
            profile=replace_outcome(
                security_profile(),
                "required_primary_source_coverage",
                evidence_reference_keys=("regulatory-record",),
                state="fail",
            ),
            passages=(*required_passages()[:-1], incomplete_financing),
            coverage_proofs=tuple(
                proof
                if proof.requirement_id != "financing_share_capital"
                else PrimarySourceCoverageProof(
                    "financing_share_capital",
                    "financing",
                    "biotech-financing-share-capital-v1",
                    "incomplete",
                    ("sec_companyfacts_financing_incomplete",),
                    ("financing-record",),
                )
                for proof in required_coverage_proofs()
            ),
        )

        self.assertEqual(
            [
                item.source_class
                for item in result.bundle_candidate.items
                if item.source_class == "financing"
            ],
            ["financing"],
        )
        self.assertIn(
            "missing_financing_share_capital",
            result.reason_codes,
        )

    def test_complete_proof_requires_passage_requirement_declaration(
        self,
    ) -> None:
        incomplete_financing = replace(
            required_passages()[-1],
            coverage_keys=frozenset(),
        )
        with self.assertRaisesRegex(
            PrimarySourcePipelineError,
            "evidence lacks requirement",
        ):
            PrimarySourcePipeline().assemble(
                request=source_request(),
                profile=security_profile(),
                passages=(
                    *required_passages()[:-1],
                    incomplete_financing,
                ),
                coverage_proofs=required_coverage_proofs(),
            )

    def test_normalized_facts_freeze_metrics_catalysts_and_risks(self) -> None:
        result = PrimarySourcePipeline().assemble(
            request=source_request(),
            profile=security_profile(catalyst=True),
            passages=required_passages(),
            coverage_proofs=required_coverage_proofs(),
            metrics=(
                NormalizedMetricFact(
                    reference_key="cash-balance",
                    source_class="financing",
                    metric_key="cash_and_cash_equivalents",
                    value="474.3",
                    unit="USD_millions",
                    period_start=date(2026, 1, 1),
                    period_end=date(2026, 3, 31),
                    calculation_method="reported",
                    formula=None,
                    supporting_passage_keys=("financing-record",),
                ),
            ),
            catalysts=(
                NormalizedCatalystFact(
                    reference_key="phase-2-topline",
                    source_class="clinical",
                    event="EX-101 Phase 2 top-line data",
                    program="EX-101",
                    basis="clinical",
                    status="expected",
                    window_start=date(2026, 10, 1),
                    window_end=date(2026, 12, 31),
                    supporting_passage_keys=(
                        "trial-record",
                        "issuer-pipeline",
                    ),
                ),
            ),
            risks=(
                NormalizedRiskFact(
                    reference_key="financing-before-catalyst",
                    source_class="financing",
                    title="Additional financing required before catalyst",
                    risk_type="dilution",
                    severity="high",
                    status="active",
                    supporting_passage_keys=("financing-record",),
                ),
            ),
        )

        candidate = result.bundle_candidate
        self.assertEqual(candidate.metrics[0].value, "474.3")
        self.assertEqual(candidate.catalysts[0].program, "EX-101")
        self.assertEqual(candidate.risks[0].risk_type, "dilution")
        self.assertEqual(
            [item.item_kind for item in candidate.items],
            [
                "passage",
                "passage",
                "passage",
                "passage",
                "catalyst",
                "passage",
                "passage",
                "metric",
                "risk",
            ],
        )
        self.assertEqual(
            result.eligibility_snapshot.catalysts[0].event,
            "EX-101 Phase 2 top-line data",
        )

    def test_contradictory_reported_metric_is_blocking_and_reason_coded(
        self,
    ) -> None:
        def cash(reference_key: str, value: str) -> NormalizedMetricFact:
            return NormalizedMetricFact(
                reference_key=reference_key,
                source_class="financing",
                metric_key="cash_and_cash_equivalents",
                value=value,
                unit="USD_millions",
                period_start=date(2026, 1, 1),
                period_end=date(2026, 3, 31),
                calculation_method="reported",
                formula=None,
                supporting_passage_keys=("financing-record",),
            )

        result = PrimarySourcePipeline().assemble(
            request=source_request(),
            profile=security_profile(),
            passages=required_passages(),
            coverage_proofs=required_coverage_proofs(),
            metrics=(cash("cash-filing", "474.3"), cash("cash-release", "470.0")),
        )

        self.assertIn(
            "contradictory_metric_cash_and_cash_equivalents",
            result.reason_codes,
        )
        self.assertIn(
            "contradictory_metric_cash_and_cash_equivalents",
            [gap.code for gap in result.bundle_candidate.declared_gaps],
        )

    def test_multiple_conflicting_periods_share_one_metric_gap(
        self,
    ) -> None:
        def cash(
            reference_key: str,
            value: str,
            period_end: date,
        ) -> NormalizedMetricFact:
            return NormalizedMetricFact(
                reference_key=reference_key,
                source_class="financing",
                metric_key="cash_and_cash_equivalents",
                value=value,
                unit="USD",
                period_start=None,
                period_end=period_end,
                calculation_method="reported",
                formula=None,
                supporting_passage_keys=("financing-record",),
            )

        result = PrimarySourcePipeline().assemble(
            request=source_request(),
            profile=security_profile(),
            passages=required_passages(),
            coverage_proofs=required_coverage_proofs(),
            metrics=(
                cash("cash-q1-a", "100", date(2026, 3, 31)),
                cash("cash-q1-b", "90", date(2026, 3, 31)),
                cash("cash-q4-a", "80", date(2025, 12, 31)),
                cash("cash-q4-b", "70", date(2025, 12, 31)),
            ),
        )

        self.assertEqual(
            [
                gap.code
                for gap in result.bundle_candidate.declared_gaps
                if gap.reason_code == "contradictory_reported_metric"
            ],
            ["contradictory_metric_cash_and_cash_equivalents"],
        )

    def test_metric_period_after_cutoff_is_rejected(self) -> None:
        future_metric = NormalizedMetricFact(
            reference_key="future-cash",
            source_class="financing",
            metric_key="cash_and_cash_equivalents",
            value="999.0",
            unit="USD_millions",
            period_start=date(2027, 1, 1),
            period_end=date(2027, 3, 31),
            calculation_method="reported",
            formula=None,
            supporting_passage_keys=("financing-record",),
        )

        with self.assertRaisesRegex(
            PrimarySourcePipelineError,
            "metric period is after cutoff",
        ):
            PrimarySourcePipeline().assemble(
                request=source_request(),
                profile=security_profile(),
                passages=required_passages(),
                coverage_proofs=required_coverage_proofs(),
                metrics=(future_metric,),
            )


if __name__ == "__main__":
    unittest.main()

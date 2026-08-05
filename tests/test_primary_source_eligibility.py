from __future__ import annotations

import hashlib
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime

from workers.clinical_trials.collector import (
    ClinicalTrialIntervention,
    ClinicalTrialSponsor,
    ClinicalTrialStudy,
    ClinicalTrialsCoverageResult,
    ClinicalTrialsSnapshot,
)
from workers.official_sources.models import OfficialSourceSnapshot
from workers.primary_sources.companyfacts import (
    SecCompanyFact,
    SecCompanyFactsSnapshot,
)
from workers.primary_sources.eligibility import (
    ELIGIBILITY_SOURCE_POLICY_VERSION,
    EligibilitySourceError,
    derive_biotech_eligibility_profile,
)
from workers.primary_sources.models import PrimarySourceRequest
from workers.primary_sources.pipeline import PrimaryEvidencePassage
from workers.security_registry.models import RegisteredSecurity
from tests.test_sec_filing_selection import collected_snapshot


OPERATOR_ID = "8ed47ebc-d5cf-40ad-80ce-d4d803f7c735"
SECURITY_ID = "f594edb2-7fff-4e40-9c26-2c06bcbecb91"
CUTOFF = datetime(2026, 5, 6, 23, 59, 59, tzinfo=UTC)
ISSUER_NAME = "Recursion Pharmaceuticals, Inc."


def request() -> PrimarySourceRequest:
    return PrimarySourceRequest(
        operator_id=OPERATOR_ID,
        security_id=SECURITY_ID,
        cik="0001601830",
        issuer_name=ISSUER_NAME,
        primary_listing_exchange="NASDAQ",
        as_of_cutoff=CUTOFF,
    )


def registered_security() -> RegisteredSecurity:
    return RegisteredSecurity(
        operator_id=OPERATOR_ID,
        security_id=SECURITY_ID,
        cik="0001601830",
        issuer_name=ISSUER_NAME,
        ticker="RXRX",
        primary_listing_exchange="Nasdaq",
        source_url=("https://www.sec.gov/files/company_tickers_exchange.json"),
        retrieved_at="2026-05-07T01:00:00+00:00",
        response_sha256="a" * 64,
    )


def passage(
    reference_key: str,
    source_class: str,
    coverage_keys: frozenset[str],
    passage_text: str,
) -> PrimaryEvidencePassage:
    return PrimaryEvidencePassage(
        reference_key=reference_key,
        source_class=source_class,
        coverage_keys=coverage_keys,
        source_locator=f"document#{reference_key}",
        canonical_url=(
            "https://www.sec.gov/Archives/edgar/data/1601830/report.htm"
            if source_class in {"sec", "financing"}
            else f"https://example.com/{source_class}"
        ),
        publication_at=datetime(2026, 5, 5, 20, tzinfo=UTC),
        retrieved_at=datetime(2026, 5, 7, 1, tzinfo=UTC),
        effective_at=None,
        filing_period_start=None,
        filing_period_end=None,
        document_content_hash=hashlib.sha256(passage_text.encode("utf-8")).hexdigest(),
        passage_text=passage_text,
        freshness="current",
        origin_policy_version=f"{source_class}-origin-v1",
    )


def source_passages() -> tuple[PrimaryEvidencePassage, ...]:
    return (
        passage(
            "sec:identity-and-listing",
            "sec",
            frozenset({"sec_issuer_security", "required_sec_filings"}),
            "Our common stock is listed on the Nasdaq Global Select Market.",
        ),
        passage(
            "issuer:pipeline",
            "issuer",
            frozenset({"issuer_pipeline"}),
            "We develop clinical-stage therapeutic medicines.",
        ),
        passage(
            "clinical-trial:NCT06000001",
            "clinical",
            frozenset({"authoritative_trial"}),
            "The active Phase 2 study has a primary completion in 2026.",
        ),
        passage(
            "regulatory:programme",
            "regulatory",
            frozenset({"us_regulatory"}),
            "FDA granted the programme Fast Track designation.",
        ),
        passage(
            "financing:basic-shares",
            "financing",
            frozenset({"financing_share_capital"}),
            "The issuer reported its basic shares outstanding.",
        ),
    )


def issuer_snapshot() -> OfficialSourceSnapshot:
    return OfficialSourceSnapshot(
        operator_id=OPERATOR_ID,
        security_id=SECURITY_ID,
        cik="0001601830",
        issuer_name=ISSUER_NAME,
        as_of_cutoff=CUTOFF,
        source_class="issuer",
        source_results=(),
        coverage_state="complete",
        coverage_results=(),
    )


def clinical_snapshot() -> ClinicalTrialsSnapshot:
    study = ClinicalTrialStudy(
        nct_id="NCT06000001",
        program_name="REC-4881",
        brief_title="REC-4881 Phase 2",
        official_title=None,
        status="RECRUITING",
        phases=("PHASE2",),
        interventions=(
            ClinicalTrialIntervention(
                intervention_type="DRUG",
                name="REC-4881",
            ),
        ),
        sponsor=ClinicalTrialSponsor(
            name=ISSUER_NAME,
            agency_class="INDUSTRY",
        ),
        start_date="2025-01",
        primary_completion_date="2026-12",
        completion_date=None,
        first_post_date_raw="2025-01-10",
        last_update_post_date_raw="2026-05-01",
        publication_state="exact",
        publication_reason_code="publication_time_exact",
        update_state="exact",
        update_reason_code="publication_time_exact",
        program_associated=True,
        issuer_associated=True,
        association_reason_code=("clinical_trial_program_association_verified"),
        valid_at_cutoff=True,
        source_class="clinical_trial_registry",
        source_locator="https://clinicaltrials.gov/study/NCT06000001",
        retrieved_at=datetime(2026, 5, 7, 1, tzinfo=UTC),
        source_payload="{}",
        content_sha256="b" * 64,
    )
    return ClinicalTrialsSnapshot(
        operator_id=OPERATOR_ID,
        security_id=SECURITY_ID,
        cik="0001601830",
        issuer_name=ISSUER_NAME,
        program_name="REC-4881",
        search_terms=("REC-4881",),
        allowed_sponsor_names=(),
        as_of_cutoff=CUTOFF,
        policy_version="clinical-trials-source-v2",
        pages=(),
        included_studies=(study,),
        excluded_studies=(),
        coverage=ClinicalTrialsCoverageResult(
            requirement_id="authoritative_trial",
            policy_version="clinical-trials-source-v2",
            status="covered",
            reason_codes=("clinical_trials_programme_covered",),
            included_nct_ids=("NCT06000001",),
        ),
    )


def companyfacts_snapshot() -> SecCompanyFactsSnapshot:
    facts = tuple(
        SecCompanyFact(
            metric_key=metric_key,
            taxonomy=taxonomy,
            concept=concept,
            value="100",
            unit=unit,
            period_start=None,
            period_end=date(2026, 3, 31),
            filed_date=date(2026, 5, 1),
            accession_number="0001601830-26-000040",
            form="10-Q",
            source_locator=f"facts:{taxonomy}:{concept}",
            source_payload="{}",
            freshness="current",
        )
        for metric_key, taxonomy, concept, unit in (
            (
                "basic_shares_outstanding",
                "dei",
                "EntityCommonStockSharesOutstanding",
                "shares",
            ),
            (
                "cash_and_cash_equivalents",
                "us-gaap",
                "CashAndCashEquivalentsAtCarryingValue",
                "USD",
            ),
            (
                "debt_current",
                "us-gaap",
                "LongTermDebtCurrent",
                "USD",
            ),
            (
                "operating_cash_used",
                "us-gaap",
                "NetCashUsedInOperatingActivities",
                "USD",
            ),
        )
    )
    return SecCompanyFactsSnapshot(
        operator_id=OPERATOR_ID,
        security_id=SECURITY_ID,
        cik="0001601830",
        issuer_name=ISSUER_NAME,
        as_of_cutoff=CUTOFF,
        policy_version="sec-companyfacts-core-metrics-v1",
        coverage_state="complete",
        reason_codes=("sec_companyfacts_core_metrics_complete",),
        source_url=("https://data.sec.gov/api/xbrl/companyfacts/CIK0001601830.json"),
        retrieved_at=datetime(2026, 5, 7, 1, tzinfo=UTC),
        source_payload="{}",
        content_sha256="c" * 64,
        facts=facts,
    )


class EligibilitySourceAdapterTests(unittest.TestCase):
    def test_coherent_primary_sources_derive_all_eligibility_values(
        self,
    ) -> None:
        profile = derive_biotech_eligibility_profile(
            request=request(),
            registered_security=registered_security(),
            submissions=collected_snapshot(
                fixture="rxrx-submissions.json",
                security_id=SECURITY_ID,
                cik="0001601830",
                issuer_name=ISSUER_NAME,
            ),
            issuer=issuer_snapshot(),
            clinical_trials=clinical_snapshot(),
            companyfacts=companyfacts_snapshot(),
            passages=source_passages(),
        )

        self.assertEqual(
            profile.policy_version,
            ELIGIBILITY_SOURCE_POLICY_VERSION,
        )

    def test_sec_registry_display_case_does_not_break_stable_identity(self) -> None:
        profile = derive_biotech_eligibility_profile(
            request=request(),
            registered_security=replace(
                registered_security(),
                issuer_name="RECURSION PHARMACEUTICALS, INC.",
            ),
            submissions=collected_snapshot(
                fixture="rxrx-submissions.json",
                security_id=SECURITY_ID,
                cik="0001601830",
                issuer_name=ISSUER_NAME,
            ),
            issuer=issuer_snapshot(),
            clinical_trials=clinical_snapshot(),
            companyfacts=companyfacts_snapshot(),
            passages=source_passages(),
        )

        self.assertTrue(profile.security_identity_verified)
        self.assertTrue(profile.eligible)
        self.assertEqual(profile.display_symbol, "RXRX")
        self.assertEqual(profile.primary_listing_country, "US")
        self.assertEqual(profile.security_type, "common_equity")
        self.assertEqual(profile.issuer_status, "operating")
        self.assertEqual(
            profile.therapeutics_classification,
            "therapeutics_biotech",
        )
        self.assertEqual(
            profile.active_therapeutic_programs,
            ("REC-4881",),
        )
        self.assertTrue(profile.security_identity_verified)
        self.assertTrue(profile.cik_matches_issuer)
        self.assertTrue(all(outcome.state == "pass" for outcome in profile.outcomes))
        values_by_rule = {
            outcome.rule_id: outcome.normalized_values for outcome in profile.outcomes
        }
        self.assertEqual(
            values_by_rule,
            {
                "security_identity_verified": ("true",),
                "us_listing": ("US", "NASDAQ"),
                "cik_match": ("0001601830",),
                "common_equity": ("common_equity",),
                "operating_company": ("operating",),
                "therapeutics_classification": ("therapeutics_biotech",),
                "active_therapeutic_program": ("REC-4881",),
                "defined_clinical_or_regulatory_catalyst": (
                    "NCT06000001:primary_completion:2026-12",
                ),
                "required_primary_source_coverage": (
                    "authoritative_trial",
                    "financing_share_capital",
                    "issuer_pipeline",
                    "required_sec_filings",
                    "sec_issuer_security",
                    "us_regulatory",
                ),
            },
        )

    def test_unversioned_clinical_source_cannot_create_rule_outcomes(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            EligibilitySourceError,
            "clinical eligibility source policy is invalid",
        ):
            derive_biotech_eligibility_profile(
                request=request(),
                registered_security=registered_security(),
                submissions=collected_snapshot(
                    fixture="rxrx-submissions.json",
                    security_id=SECURITY_ID,
                    cik="0001601830",
                    issuer_name=ISSUER_NAME,
                ),
                issuer=issuer_snapshot(),
                clinical_trials=replace(
                    clinical_snapshot(),
                    policy_version="unversioned",
                ),
                companyfacts=companyfacts_snapshot(),
                passages=source_passages(),
            )

    def test_common_equity_cannot_be_self_attested_without_exact_passage(
        self,
    ) -> None:
        passages = tuple(
            (
                replace(
                    item,
                    passage_text="The issuer filed its quarterly report.",
                )
                if item.reference_key == "sec:identity-and-listing"
                else item
            )
            for item in source_passages()
        )

        profile = derive_biotech_eligibility_profile(
            request=request(),
            registered_security=registered_security(),
            submissions=collected_snapshot(
                fixture="rxrx-submissions.json",
                security_id=SECURITY_ID,
                cik="0001601830",
                issuer_name=ISSUER_NAME,
            ),
            issuer=issuer_snapshot(),
            clinical_trials=clinical_snapshot(),
            companyfacts=companyfacts_snapshot(),
            passages=passages,
        )

        common_equity = next(
            outcome
            for outcome in profile.outcomes
            if outcome.rule_id == "common_equity"
        )
        self.assertEqual(common_equity.state, "fail")
        self.assertEqual(common_equity.evidence_reference_keys, ())
        self.assertEqual(common_equity.normalized_values, ("unknown",))
        self.assertEqual(profile.security_type, "unknown")
        self.assertFalse(profile.eligible)

    def test_incidental_common_stock_text_does_not_prove_security_type(
        self,
    ) -> None:
        passages = tuple(
            (
                replace(
                    item,
                    passage_text=("Preferred stock may convert into common stock."),
                )
                if item.reference_key == "sec:identity-and-listing"
                else item
            )
            for item in source_passages()
        )

        profile = derive_biotech_eligibility_profile(
            request=request(),
            registered_security=registered_security(),
            submissions=collected_snapshot(
                fixture="rxrx-submissions.json",
                security_id=SECURITY_ID,
                cik="0001601830",
                issuer_name=ISSUER_NAME,
            ),
            issuer=issuer_snapshot(),
            clinical_trials=clinical_snapshot(),
            companyfacts=companyfacts_snapshot(),
            passages=passages,
        )

        common_equity = next(
            outcome
            for outcome in profile.outcomes
            if outcome.rule_id == "common_equity"
        )
        self.assertEqual(common_equity.state, "fail")

    def test_companyfacts_complete_flag_cannot_replace_required_facts(
        self,
    ) -> None:
        profile = derive_biotech_eligibility_profile(
            request=request(),
            registered_security=registered_security(),
            submissions=collected_snapshot(
                fixture="rxrx-submissions.json",
                security_id=SECURITY_ID,
                cik="0001601830",
                issuer_name=ISSUER_NAME,
            ),
            issuer=issuer_snapshot(),
            clinical_trials=clinical_snapshot(),
            companyfacts=replace(companyfacts_snapshot(), facts=()),
            passages=source_passages(),
        )

        outcomes = {item.rule_id: item for item in profile.outcomes}
        self.assertEqual(outcomes["operating_company"].state, "fail")
        self.assertEqual(
            outcomes["required_primary_source_coverage"].state,
            "fail",
        )
        self.assertFalse(profile.eligible)

    def test_incomplete_clinical_coverage_blocks_required_coverage_rule(
        self,
    ) -> None:
        clinical = clinical_snapshot()
        clinical = replace(
            clinical,
            coverage=replace(
                clinical.coverage,
                status="incomplete",
                reason_codes=("clinical_trials_programme_incomplete",),
            ),
        )

        profile = derive_biotech_eligibility_profile(
            request=request(),
            registered_security=registered_security(),
            submissions=collected_snapshot(
                fixture="rxrx-submissions.json",
                security_id=SECURITY_ID,
                cik="0001601830",
                issuer_name=ISSUER_NAME,
            ),
            issuer=issuer_snapshot(),
            clinical_trials=clinical,
            companyfacts=companyfacts_snapshot(),
            passages=source_passages(),
        )

        required_coverage = next(
            outcome
            for outcome in profile.outcomes
            if outcome.rule_id == "required_primary_source_coverage"
        )
        self.assertEqual(required_coverage.state, "fail")
        self.assertFalse(profile.eligible)


if __name__ == "__main__":
    unittest.main()

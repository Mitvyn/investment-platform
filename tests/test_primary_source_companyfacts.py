from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
import unittest

from workers.primary_sources.companyfacts import (
    SecCompanyFactsCollector,
    SecCompanyFactsCollectorError,
    SecCompanyFactsSettings,
    companyfacts_other_enterprise_claim_inputs,
)
from workers.primary_sources.other_enterprise_claims import OtherEnterpriseClaimsError
from workers.primary_sources.models import PrimarySourceRequest
from workers.primary_sources.pipeline import NormalizedMetricFact
from workers.sec.collector import BytesResponse


SOURCE_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK0001601830.json"
CORE_FIXTURE = Path("tests/fixtures/primary_sources/sec-companyfacts.json")


class FixtureTransport:
    def __init__(self, payload: dict[str, object]) -> None:
        self.body = json.dumps(payload).encode()

    def request(self, url: str, *, headers):
        return BytesResponse(
            body=self.body,
            status=200,
            headers={"Content-Type": "application/json"},
            final_url=url,
        )


def request() -> PrimarySourceRequest:
    return PrimarySourceRequest(
        operator_id="8ed47ebc-d5cf-40ad-80ce-d4d803f7c735",
        security_id="f594edb2-7fff-4e40-9c26-2c06bcbecb91",
        cik="0001601830",
        issuer_name="Example Therapeutics, Inc.",
        primary_listing_exchange="NASDAQ",
        as_of_cutoff=datetime(2026, 5, 6, 23, 59, 59, tzinfo=UTC),
    )


def payload_with(concept: str | None, value: int = 0) -> dict[str, object]:
    us_gaap = {}
    if concept is not None:
        us_gaap[concept] = {
            "units": {
                "USD": [
                    {
                        "end": "2026-03-31",
                        "val": value,
                        "accn": "0001601830-26-000040",
                        "fy": 2026,
                        "fp": "Q1",
                        "form": "10-Q",
                        "filed": "2026-05-05",
                    }
                ]
            }
        }
    return {
        "cik": 1601830,
        "entityName": "Example Therapeutics, Inc.",
        "facts": {"us-gaap": us_gaap},
    }


def collect(payload: dict[str, object]):
    return SecCompanyFactsCollector(
        SecCompanyFactsSettings(
            user_agent="Investment Research OS research@example.com"
        ),
        transport=FixtureTransport(payload),
        clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
    ).collect(request())


def dilution_context(
    *,
    convertibles: str = "0",
    preferreds: str = "0",
) -> tuple[NormalizedMetricFact, ...]:
    return tuple(
        NormalizedMetricFact(
            reference_key=f"financing-metric:{metric_key}",
            source_class="financing",
            metric_key=metric_key,
            value=value,
            unit="shares",
            period_start=None,
            period_end=date(2026, 3, 31),
            calculation_method="reported",
            formula=None,
            supporting_passage_keys=(f"financing:{metric_key}",),
        )
        for metric_key, value in (
            ("convertible_share_equivalents", convertibles),
            ("preferred_shares_outstanding", preferreds),
        )
    )


class PrimarySourceCompanyFactsTests(unittest.TestCase):
    def test_companyfacts_produces_complete_enterprise_claim_vector(self) -> None:
        payload = json.loads(CORE_FIXTURE.read_text())
        concepts = {
            "DebtLongtermAndShorttermCombinedAmount": 20_000_000,
            "TemporaryEquityCarryingAmountAttributableToParent": 1_000_000,
            "MinorityInterest": 2_000_000,
            "LiabilityForSaleOfFutureRevenue": 3_000_000,
            "BusinessCombinationContingentConsiderationLiability": 4_000_000,
            "DefinedBenefitPlanFundedStatusOfPlan": 5_000_000,
            "FinanceLeaseLiability": 0,
        }
        for concept, value in concepts.items():
            payload["facts"]["us-gaap"][concept] = payload_with(concept, value)[
                "facts"
            ]["us-gaap"][concept]

        snapshot = collect(payload)
        metrics = companyfacts_other_enterprise_claim_inputs(
            snapshot,
            financing_metrics=dilution_context(),
        )

        self.assertEqual(len(metrics), 7)
        self.assertEqual(metrics[-1].metric_key, "other_enterprise_claims")
        self.assertEqual(metrics[-1].value, "15000000")
        self.assertEqual(
            {metric.metric_key for metric in metrics[:-1]},
            {
                "other_enterprise_claim:redeemable_preferred_claim",
                "other_enterprise_claim:noncontrolling_interest_claim",
                "other_enterprise_claim:royalty_monetization_liability",
                "other_enterprise_claim:contingent_consideration_claim",
                "other_enterprise_claim:pension_underfunded_claim",
                "other_enterprise_claim:finance_lease_claim",
            },
        )

    def test_generic_debt_with_finance_lease_claim_fails_closed(self) -> None:
        payload = json.loads(CORE_FIXTURE.read_text())
        for concept, value in (
            ("DebtLongtermAndShorttermCombinedAmount", 20_000_000),
            ("TemporaryEquityCarryingAmountAttributableToParent", 0),
            ("MinorityInterest", 0),
            ("LiabilityForSaleOfFutureRevenue", 0),
            ("BusinessCombinationContingentConsiderationLiability", 0),
            ("DefinedBenefitPlanFundedStatusOfPlan", 0),
            ("FinanceLeaseLiability", 6_000_000),
        ):
            payload["facts"]["us-gaap"][concept] = payload_with(concept, value)[
                "facts"
            ]["us-gaap"][concept]

        with self.assertRaisesRegex(
            OtherEnterpriseClaimsError,
            "other_claims_double_count_finance_lease",
        ):
            companyfacts_other_enterprise_claim_inputs(
                collect(payload),
                financing_metrics=dilution_context(),
            )

    def test_finance_lease_claim_rejects_debt_fallback_double_count(self) -> None:
        payload = json.loads(CORE_FIXTURE.read_text())
        for concept, value in (
            ("LongTermDebtAndCapitalLeaseObligationsCurrent", 10_000_000),
            ("LongTermDebtAndCapitalLeaseObligations", 20_000_000),
            ("TemporaryEquityCarryingAmountAttributableToParent", 0),
            ("MinorityInterest", 0),
            ("LiabilityForSaleOfFutureRevenue", 0),
            ("BusinessCombinationContingentConsiderationLiability", 0),
            ("DefinedBenefitPlanFundedStatusOfPlan", 0),
            ("FinanceLeaseLiability", 6_000_000),
        ):
            payload["facts"]["us-gaap"][concept] = payload_with(concept, value)[
                "facts"
            ]["us-gaap"][concept]

        snapshot = collect(payload)

        debt = next(fact for fact in snapshot.facts if fact.metric_key == "debt_total")
        self.assertEqual(debt.value, "24000000")
        self.assertEqual(
            debt.formula,
            "debt_and_capital_lease_total-finance_lease_liability",
        )
        metrics = companyfacts_other_enterprise_claim_inputs(
            snapshot,
            financing_metrics=dilution_context(),
        )
        self.assertEqual(metrics[-1].value, "6000000")

    def test_claim_vector_requires_dilution_double_count_context(self) -> None:
        payload = json.loads(CORE_FIXTURE.read_text())
        payload["facts"]["us-gaap"]["DebtLongtermAndShorttermCombinedAmount"] = (
            payload_with("DebtLongtermAndShorttermCombinedAmount", 20_000_000)["facts"][
                "us-gaap"
            ]["DebtLongtermAndShorttermCombinedAmount"]
        )
        for concept in (
            "TemporaryEquityCarryingAmountAttributableToParent",
            "MinorityInterest",
            "LiabilityForSaleOfFutureRevenue",
            "BusinessCombinationContingentConsiderationLiability",
            "DefinedBenefitPlanFundedStatusOfPlan",
            "FinanceLeaseLiability",
        ):
            payload["facts"]["us-gaap"][concept] = payload_with(concept, 0)["facts"][
                "us-gaap"
            ][concept]

        with self.assertRaisesRegex(
            SecCompanyFactsCollectorError,
            "other_claims_dilution_context_unavailable",
        ):
            companyfacts_other_enterprise_claim_inputs(collect(payload))

    def test_convertible_shares_with_nonzero_debt_fail_closed(self) -> None:
        payload = json.loads(CORE_FIXTURE.read_text())
        for concept in (
            "TemporaryEquityCarryingAmountAttributableToParent",
            "MinorityInterest",
            "LiabilityForSaleOfFutureRevenue",
            "BusinessCombinationContingentConsiderationLiability",
            "DefinedBenefitPlanFundedStatusOfPlan",
            "FinanceLeaseLiability",
        ):
            payload["facts"]["us-gaap"][concept] = payload_with(concept, 0)["facts"][
                "us-gaap"
            ][concept]
        payload["facts"]["us-gaap"]["DebtLongtermAndShorttermCombinedAmount"] = (
            payload_with("DebtLongtermAndShorttermCombinedAmount", 20_000_000)["facts"][
                "us-gaap"
            ]["DebtLongtermAndShorttermCombinedAmount"]
        )

        with self.assertRaisesRegex(
            OtherEnterpriseClaimsError,
            "other_claims_double_count_convertible",
        ):
            companyfacts_other_enterprise_claim_inputs(
                collect(payload),
                financing_metrics=dilution_context(convertibles="1000"),
            )

    def test_restricted_cash_combines_current_and_noncurrent_balances(self) -> None:
        payload = payload_with("RestrictedCashCurrent", 5_511_000)
        payload["facts"]["us-gaap"]["RestrictedCashNoncurrent"] = {
            "units": {
                "USD": [
                    {
                        "end": "2026-03-31",
                        "val": 5_196_000,
                        "accn": "0001601830-26-000040",
                        "fy": 2026,
                        "fp": "Q1",
                        "form": "10-Q",
                        "filed": "2026-05-05",
                    }
                ]
            }
        }

        snapshot = collect(payload)

        restricted_cash = next(
            fact for fact in snapshot.facts if fact.metric_key == "restricted_cash"
        )
        self.assertEqual(restricted_cash.value, "10707000")
        self.assertEqual(restricted_cash.calculation_method, "derived")
        self.assertEqual(
            restricted_cash.formula,
            "restricted_cash_current+restricted_cash_noncurrent",
        )

    def test_restricted_cash_does_not_treat_current_portion_as_total(self) -> None:
        snapshot = collect(payload_with("RestrictedCashCurrent", 5_511_000))

        self.assertNotIn(
            "restricted_cash",
            {fact.metric_key for fact in snapshot.facts},
        )
        self.assertIn(
            "sec_companyfacts_missing_restricted_cash",
            snapshot.reason_codes,
        )

    def test_total_debt_combines_current_and_noncurrent_balances(self) -> None:
        payload = payload_with(
            "LongTermDebtAndCapitalLeaseObligationsCurrent",
            9_265_000,
        )
        payload["facts"]["us-gaap"]["LongTermDebtAndCapitalLeaseObligations"] = {
            "units": {
                "USD": [
                    {
                        "end": "2026-03-31",
                        "val": 7_181_000,
                        "accn": "0001601830-26-000040",
                        "fy": 2026,
                        "fp": "Q1",
                        "form": "10-Q",
                        "filed": "2026-05-05",
                    }
                ]
            }
        }

        snapshot = collect(payload)

        debt_total = next(
            fact for fact in snapshot.facts if fact.metric_key == "debt_total"
        )
        self.assertEqual(debt_total.value, "16446000")
        self.assertEqual(debt_total.calculation_method, "derived")
        self.assertEqual(
            debt_total.formula,
            "debt_and_capital_lease_current+debt_and_capital_lease_noncurrent",
        )

    def test_restricted_cash_normalizes_or_reports_missing_without_zero(self) -> None:
        snapshot = collect(payload_with("RestrictedCashAndCashEquivalents", 4300000))

        restricted_cash = next(
            fact for fact in snapshot.facts if fact.metric_key == "restricted_cash"
        )
        self.assertEqual(restricted_cash.concept, "RestrictedCashAndCashEquivalents")
        self.assertEqual(restricted_cash.value, "4300000")
        self.assertEqual(restricted_cash.unit, "USD")
        self.assertEqual(restricted_cash.period_end, date(2026, 3, 31))
        self.assertEqual(restricted_cash.calculation_method, "reported")
        self.assertEqual(snapshot.policy_version, "sec-companyfacts-core-metrics-v3")

        missing = collect(payload_with(None))
        self.assertNotIn(
            "restricted_cash",
            {fact.metric_key for fact in missing.facts},
        )
        self.assertIn(
            "sec_companyfacts_missing_restricted_cash",
            missing.reason_codes,
        )

    def test_total_debt_normalizes_or_reports_missing_without_zero(self) -> None:
        snapshot = collect(
            payload_with("DebtLongtermAndShorttermCombinedAmount", 21750000)
        )

        debt_total = next(
            fact for fact in snapshot.facts if fact.metric_key == "debt_total"
        )
        self.assertEqual(
            debt_total.concept,
            "DebtLongtermAndShorttermCombinedAmount",
        )
        self.assertEqual(debt_total.value, "21750000")
        self.assertEqual(debt_total.unit, "USD")
        self.assertEqual(debt_total.period_end, date(2026, 3, 31))
        self.assertEqual(debt_total.calculation_method, "reported")

        missing = collect(payload_with(None))
        self.assertNotIn(
            "debt_total",
            {fact.metric_key for fact in missing.facts},
        )
        self.assertIn(
            "sec_companyfacts_missing_debt_total",
            missing.reason_codes,
        )

    def test_missing_valuation_metrics_do_not_reclassify_core_coverage(self) -> None:
        snapshot = collect(json.loads(CORE_FIXTURE.read_text()))

        self.assertEqual(snapshot.coverage_state, "complete")
        self.assertEqual(
            snapshot.reason_codes,
            (
                "sec_companyfacts_missing_restricted_cash",
                "sec_companyfacts_missing_debt_total",
                "sec_companyfacts_core_metrics_complete",
            ),
        )
        self.assertFalse(
            {"restricted_cash", "debt_total"}
            & {fact.metric_key for fact in snapshot.facts}
        )


if __name__ == "__main__":
    unittest.main()

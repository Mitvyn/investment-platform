from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
import unittest

from workers.primary_sources.companyfacts import (
    SecCompanyFactsCollector,
    SecCompanyFactsSettings,
)
from workers.primary_sources.models import PrimarySourceRequest
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


class PrimarySourceCompanyFactsTests(unittest.TestCase):
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
        self.assertEqual(snapshot.policy_version, "sec-companyfacts-core-metrics-v2")

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

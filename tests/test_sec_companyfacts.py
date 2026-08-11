from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
import unittest

from workers.primary_sources.companyfacts import (
    SecCompanyFactsCollector,
    SecCompanyFactsCollectorError,
    SecCompanyFactsSettings,
    companyfacts_basic_share_growth_passages,
    companyfacts_basic_share_growth_observations,
    companyfacts_coverage_proof,
    companyfacts_pipeline_inputs,
)
from workers.primary_sources.models import PrimarySourceRequest
from workers.sec.collector import BytesResponse, SecSettings
from workers.sec.submissions import SecSubmissionsCollector


FIXTURE = Path("tests/fixtures/primary_sources/sec-companyfacts.json")
OPERATOR_ID = "8ed47ebc-d5cf-40ad-80ce-d4d803f7c735"
SECURITY_ID = "f594edb2-7fff-4e40-9c26-2c06bcbecb91"
CUTOFF = datetime(2026, 5, 6, 23, 59, 59, tzinfo=UTC)
SOURCE_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK0001601830.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK0001601830.json"


class FixtureTransport:
    def __init__(
        self,
        body: bytes,
        *,
        final_url: str = SOURCE_URL,
        content_type: str = "application/json",
    ) -> None:
        self.body = body
        self.final_url = final_url
        self.content_type = content_type
        self.requests: list[tuple[str, dict[str, str]]] = []

    def request(self, url: str, *, headers):
        self.requests.append((url, dict(headers)))
        return BytesResponse(
            body=self.body,
            status=200,
            headers={"Content-Type": self.content_type},
            final_url=self.final_url,
        )


def request() -> PrimarySourceRequest:
    return PrimarySourceRequest(
        operator_id=OPERATOR_ID,
        security_id=SECURITY_ID,
        cik="0001601830",
        issuer_name="Example Therapeutics, Inc.",
        primary_listing_exchange="NASDAQ",
        as_of_cutoff=CUTOFF,
    )


def _fixture_payload() -> dict[str, object]:
    payload = json.loads(FIXTURE.read_text())
    payload["facts"]["us-gaap"]["RestrictedCashAndCashEquivalents"] = {
        "label": "Restricted Cash and Cash Equivalents",
        "units": {
            "USD": [
                {
                    "end": "2026-03-31",
                    "val": 4300000,
                    "accn": "0001601830-26-000040",
                    "fy": 2026,
                    "fp": "Q1",
                    "form": "10-Q",
                    "filed": "2026-05-05",
                }
            ]
        },
    }
    payload["facts"]["us-gaap"]["DebtLongtermAndShorttermCombinedAmount"] = {
        "label": "Long-term and Short-term Debt",
        "units": {
            "USD": [
                {
                    "end": "2026-03-31",
                    "val": 21750000,
                    "accn": "0001601830-26-000040",
                    "fy": 2026,
                    "fp": "Q1",
                    "form": "10-Q",
                    "filed": "2026-05-05",
                }
            ]
        },
    }
    return payload


def _fixture_body() -> bytes:
    return json.dumps(_fixture_payload(), sort_keys=True).encode()


class SecCompanyFactsCollectorTests(unittest.TestCase):
    def test_resolves_live_concept_aliases_and_exact_acceptance_time(self) -> None:
        payload = _fixture_payload()
        payload["facts"]["us-gaap"]["CommonStockSharesOutstanding"] = {
            "label": "Common Stock Shares Outstanding",
            "units": {
                "shares": [
                    {
                        "end": "2025-12-31",
                        "val": 528182693,
                        "accn": "0001601830-26-000039",
                        "fy": 2025,
                        "fp": "FY",
                        "form": "10-K",
                        "filed": "2026-02-25",
                    },
                    {
                        "end": "2026-03-31",
                        "val": 530628653,
                        "accn": "0001601830-26-000078",
                        "fy": 2026,
                        "fp": "Q1",
                        "form": "10-Q",
                        "filed": "2026-05-06",
                    },
                ]
            },
        }
        del payload["facts"]["dei"]["EntityCommonStockSharesOutstanding"]
        payload["facts"]["us-gaap"]["LongTermDebtAndCapitalLeaseObligationsCurrent"] = {
            "label": "Current Debt and Capital Lease Obligations",
            "units": {
                "USD": [
                    {
                        "end": "2026-03-31",
                        "val": 9265000,
                        "accn": "0001601830-26-000078",
                        "fy": 2026,
                        "fp": "Q1",
                        "form": "10-Q",
                        "filed": "2026-05-06",
                    }
                ]
            },
        }
        del payload["facts"]["us-gaap"]["LongTermDebtCurrent"]
        payload["facts"]["us-gaap"]["NetCashProvidedByUsedInOperatingActivities"] = {
            "label": "Net Cash Provided by Used in Operating Activities",
            "units": {
                "USD": [
                    {
                        "start": "2026-01-01",
                        "end": "2026-03-31",
                        "val": -81101000,
                        "accn": "0001601830-26-000078",
                        "fy": 2026,
                        "fp": "Q1",
                        "form": "10-Q",
                        "filed": "2026-05-06",
                    }
                ]
            },
        }
        del payload["facts"]["us-gaap"]["NetCashUsedInOperatingActivities"]
        payload["facts"]["us-gaap"]["CashAndCashEquivalentsAtCarryingValue"]["units"][
            "USD"
        ][-1].update(
            {
                "val": 654473000,
                "accn": "0001601830-26-000078",
                "filed": "2026-05-06",
            }
        )
        for concept in (
            "RestrictedCashAndCashEquivalents",
            "DebtLongtermAndShorttermCombinedAmount",
        ):
            payload["facts"]["us-gaap"][concept]["units"]["USD"][-1].update(
                {
                    "accn": "0001601830-26-000078",
                    "filed": "2026-05-06",
                }
            )
        submissions_payload = {
            "cik": "0001601830",
            "name": "Example Therapeutics, Inc.",
            "filings": {
                "recent": {
                    "accessionNumber": [
                        "0001601830-26-000078",
                        "0001601830-26-000039",
                    ],
                    "acceptanceDateTime": [
                        "2026-05-06T10:32:40Z",
                        "2026-02-25T11:33:18Z",
                    ],
                    "filingDate": ["2026-05-06", "2026-02-25"],
                    "reportDate": ["2026-03-31", "2025-12-31"],
                    "form": ["10-Q", "10-K"],
                    "primaryDocument": [
                        "issuer-20260331.htm",
                        "issuer-20251231.htm",
                    ],
                },
                "files": [],
            },
        }
        submissions = SecSubmissionsCollector(
            SecSettings(
                user_agent="Investment Research OS research@example.com",
                base_url="https://data.sec.gov",
            ),
            transport=FixtureTransport(
                json.dumps(submissions_payload).encode(),
                final_url=SUBMISSIONS_URL,
            ),
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        ).discover(request())

        snapshot = SecCompanyFactsCollector(
            SecCompanyFactsSettings(
                user_agent="Investment Research OS research@example.com"
            ),
            transport=FixtureTransport(json.dumps(payload).encode()),
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        ).collect(request(), submissions=submissions)

        self.assertEqual(snapshot.coverage_state, "complete")
        self.assertEqual(
            [
                (
                    fact.metric_key,
                    fact.concept,
                    fact.value,
                    fact.reported_value,
                    fact.published_at,
                )
                for fact in snapshot.facts
            ],
            [
                (
                    "basic_shares_outstanding",
                    "CommonStockSharesOutstanding",
                    "530628653",
                    "530628653",
                    datetime(2026, 5, 6, 10, 32, 40, tzinfo=UTC),
                ),
                (
                    "cash_and_cash_equivalents",
                    "CashAndCashEquivalentsAtCarryingValue",
                    "654473000",
                    "654473000",
                    datetime(2026, 5, 6, 10, 32, 40, tzinfo=UTC),
                ),
                (
                    "restricted_cash",
                    "RestrictedCashAndCashEquivalents",
                    "4300000",
                    "4300000",
                    datetime(2026, 5, 6, 10, 32, 40, tzinfo=UTC),
                ),
                (
                    "debt_current",
                    "LongTermDebtAndCapitalLeaseObligationsCurrent",
                    "9265000",
                    "9265000",
                    datetime(2026, 5, 6, 10, 32, 40, tzinfo=UTC),
                ),
                (
                    "debt_total",
                    "DebtLongtermAndShorttermCombinedAmount",
                    "21750000",
                    "21750000",
                    datetime(2026, 5, 6, 10, 32, 40, tzinfo=UTC),
                ),
                (
                    "operating_cash_used",
                    "NetCashProvidedByUsedInOperatingActivities",
                    "81101000",
                    "-81101000",
                    datetime(2026, 5, 6, 10, 32, 40, tzinfo=UTC),
                ),
            ],
        )
        _passages, metrics = companyfacts_pipeline_inputs(snapshot)
        self.assertEqual(metrics[-1].calculation_method, "derived")
        self.assertEqual(metrics[-1].formula, "max(-reported_value,0)")
        observations = companyfacts_basic_share_growth_observations(snapshot)
        self.assertEqual(
            [
                (
                    item.value,
                    item.period_end,
                    item.accession_number,
                    item.accepted_at,
                    item.reference_key,
                )
                for item in observations
            ],
            [
                (
                    "528182693",
                    date(2025, 12, 31),
                    "0001601830-26-000039",
                    datetime(2026, 2, 25, 11, 33, 18, tzinfo=UTC),
                    (
                        "sec-companyfacts:basic_shares_outstanding:"
                        "2025-12-31:0001601830-26-000039"
                    ),
                ),
                (
                    "530628653",
                    date(2026, 3, 31),
                    "0001601830-26-000078",
                    datetime(2026, 5, 6, 10, 32, 40, tzinfo=UTC),
                    (
                        "sec-companyfacts:basic_shares_outstanding:"
                        "2026-03-31:0001601830-26-000078"
                    ),
                ),
            ],
        )
        growth_passages = companyfacts_basic_share_growth_passages(snapshot)
        self.assertEqual(
            tuple(item.reference_key for item in growth_passages),
            tuple(item.reference_key for item in observations),
        )
        self.assertEqual(
            tuple(item.filing_period_end for item in growth_passages),
            tuple(item.period_end for item in observations),
        )
        self.assertEqual(
            tuple(item.available_at for item in growth_passages),
            tuple(item.accepted_at for item in observations),
        )
        self.assertTrue(
            all("#observation=" in item.source_locator for item in growth_passages)
        )
        self.assertTrue(
            all(
                item.document_content_hash
                == hashlib.sha256(item.passage_text.encode()).hexdigest()
                for item in growth_passages
            )
        )

    def test_same_day_date_only_fact_requires_exact_submission_time(self) -> None:
        payload = _fixture_payload()
        for taxonomy in payload["facts"].values():
            for concept in taxonomy.values():
                for observations in concept["units"].values():
                    for observation in observations:
                        observation["filed"] = "2026-05-06"

        snapshot = SecCompanyFactsCollector(
            SecCompanyFactsSettings(
                user_agent="Investment Research OS research@example.com"
            ),
            transport=FixtureTransport(json.dumps(payload).encode()),
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        ).collect(request())

        self.assertEqual(snapshot.coverage_state, "incomplete")
        self.assertEqual(snapshot.facts, ())

    def test_collects_latest_cutoff_safe_financing_facts(self) -> None:
        body = _fixture_body()
        transport = FixtureTransport(body)
        snapshot = SecCompanyFactsCollector(
            SecCompanyFactsSettings(
                user_agent="Investment Research OS research@example.com"
            ),
            transport=transport,
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        ).collect(request())

        self.assertEqual(snapshot.operator_id, OPERATOR_ID)
        self.assertEqual(snapshot.security_id, SECURITY_ID)
        self.assertEqual(snapshot.cik, "0001601830")
        self.assertEqual(snapshot.coverage_state, "complete")
        self.assertEqual(
            [
                (fact.metric_key, fact.value, fact.unit, fact.period_end)
                for fact in snapshot.facts
            ],
            [
                (
                    "basic_shares_outstanding",
                    "312500000",
                    "shares",
                    date(2026, 3, 31),
                ),
                (
                    "cash_and_cash_equivalents",
                    "474300000",
                    "USD",
                    date(2026, 3, 31),
                ),
                (
                    "restricted_cash",
                    "4300000",
                    "USD",
                    date(2026, 3, 31),
                ),
                (
                    "debt_current",
                    "12500000",
                    "USD",
                    date(2026, 3, 31),
                ),
                (
                    "debt_total",
                    "21750000",
                    "USD",
                    date(2026, 3, 31),
                ),
                (
                    "operating_cash_used",
                    "118700000",
                    "USD",
                    date(2026, 3, 31),
                ),
            ],
        )
        self.assertEqual(
            snapshot.facts[-1].period_start,
            date(2026, 1, 1),
        )
        self.assertEqual(
            snapshot.content_sha256,
            hashlib.sha256(body).hexdigest(),
        )
        self.assertEqual(
            transport.requests,
            [
                (
                    SOURCE_URL,
                    {
                        "Accept": "application/json",
                        "User-Agent": ("Investment Research OS research@example.com"),
                    },
                )
            ],
        )

    def test_converts_structured_facts_to_exact_financing_evidence(self) -> None:
        body = _fixture_body()
        snapshot = SecCompanyFactsCollector(
            SecCompanyFactsSettings(
                user_agent="Investment Research OS research@example.com"
            ),
            transport=FixtureTransport(body),
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        ).collect(request())

        passages, metrics = companyfacts_pipeline_inputs(snapshot)
        proof = companyfacts_coverage_proof(snapshot)

        self.assertEqual(len(passages), 6)
        self.assertTrue(all(item.source_class == "financing" for item in passages))
        self.assertEqual(
            frozenset(coverage for item in passages for coverage in item.coverage_keys),
            frozenset(),
        )
        self.assertTrue(all(item.publication_at is None for item in passages))
        self.assertEqual(
            [item.metric_key for item in metrics],
            [
                "basic_shares_outstanding",
                "cash_and_cash_equivalents",
                "restricted_cash",
                "debt_current",
                "debt_total",
                "operating_cash_used",
            ],
        )
        self.assertEqual(
            metrics[0].supporting_passage_keys,
            ("sec-companyfacts:basic_shares_outstanding",),
        )
        cash_metric = next(
            metric
            for metric in metrics
            if metric.metric_key == "cash_and_cash_equivalents"
        )
        self.assertEqual(cash_metric.value, "478600000")
        self.assertEqual(cash_metric.calculation_method, "derived")
        self.assertEqual(
            cash_metric.formula,
            "unrestricted_cash_and_cash_equivalents+restricted_cash",
        )
        self.assertEqual(
            cash_metric.supporting_passage_keys,
            (
                "sec-companyfacts:cash_and_cash_equivalents",
                "sec-companyfacts:restricted_cash",
            ),
        )
        self.assertEqual(
            proof.evidence_reference_keys,
            tuple(item.reference_key for item in passages),
        )
        self.assertEqual(
            proof.policy_version,
            "biotech-financing-share-capital-v1",
        )
        self.assertEqual(proof.state, "incomplete")
        self.assertIn(
            "financing_capital_structure_scan_missing",
            proof.reason_codes,
        )

    def test_missing_required_fact_is_explicitly_incomplete(self) -> None:
        payload = _fixture_payload()
        del payload["facts"]["us-gaap"]["LongTermDebtCurrent"]
        snapshot = SecCompanyFactsCollector(
            SecCompanyFactsSettings(
                user_agent="Investment Research OS research@example.com"
            ),
            transport=FixtureTransport(json.dumps(payload).encode()),
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        ).collect(request())

        self.assertEqual(snapshot.coverage_state, "incomplete")
        self.assertEqual(
            snapshot.reason_codes,
            (
                "sec_companyfacts_missing_debt_current",
                "sec_companyfacts_core_metrics_incomplete",
            ),
        )
        passages, _metrics = companyfacts_pipeline_inputs(snapshot)
        self.assertTrue(all(not item.coverage_keys for item in passages))
        self.assertEqual(
            companyfacts_coverage_proof(snapshot).state,
            "incomplete",
        )

    def test_future_unselected_observation_does_not_reversion_selected_facts(
        self,
    ) -> None:
        base_payload = _fixture_payload()
        changed_payload = _fixture_payload()
        changed_payload["facts"]["us-gaap"]["CashAndCashEquivalentsAtCarryingValue"][
            "units"
        ]["USD"].append(
            {
                "end": "2027-03-31",
                "val": 900000000,
                "accn": "0001601830-27-000042",
                "fy": 2027,
                "fp": "Q1",
                "form": "10-Q",
                "filed": "2027-05-05",
            }
        )

        def collect(payload):
            return SecCompanyFactsCollector(
                SecCompanyFactsSettings(
                    user_agent="Investment Research OS research@example.com"
                ),
                transport=FixtureTransport(json.dumps(payload).encode()),
                clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
            ).collect(request())

        base_passages, _ = companyfacts_pipeline_inputs(collect(base_payload))
        changed_passages, _ = companyfacts_pipeline_inputs(collect(changed_payload))

        self.assertEqual(
            [item.document_content_hash for item in base_passages],
            [item.document_content_hash for item in changed_passages],
        )

    def test_rejects_redirected_or_mismatched_company_facts(self) -> None:
        body = _fixture_body()
        with self.assertRaisesRegex(
            SecCompanyFactsCollectorError,
            "response redirected",
        ):
            SecCompanyFactsCollector(
                SecCompanyFactsSettings(
                    user_agent="Investment Research OS research@example.com"
                ),
                transport=FixtureTransport(
                    body,
                    final_url="https://example.com/companyfacts.json",
                ),
            ).collect(request())

        payload = json.loads(body)
        payload["cik"] = 9999999
        with self.assertRaisesRegex(
            SecCompanyFactsCollectorError,
            "CIK does not match",
        ):
            SecCompanyFactsCollector(
                SecCompanyFactsSettings(
                    user_agent="Investment Research OS research@example.com"
                ),
                transport=FixtureTransport(json.dumps(payload).encode()),
            ).collect(request())


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
import unittest

from workers.primary_sources.models import PrimarySourceRequest
from workers.sec.collector import BytesResponse, SecSettings
from workers.sec.selection import RequiredSecFilingSelector
from workers.sec.submissions import SecSubmissionsCollector


FIXTURE_ROOT = Path("tests/fixtures/primary_sources")
OPERATOR_ID = "8ed47ebc-d5cf-40ad-80ce-d4d803f7c735"
CUTOFF = datetime(2026, 5, 6, 23, 59, 59, tzinfo=UTC)


class FixtureTransport:
    def __init__(self, url: str, body: bytes) -> None:
        self.url = url
        self.body = body

    def request(self, url: str, *, headers):
        if url != self.url:
            raise AssertionError(f"unexpected URL: {url}")
        return BytesResponse(
            body=self.body,
            status=200,
            headers={"Content-Type": "application/json"},
            final_url=url,
        )


def collected_snapshot(
    *,
    fixture: str,
    security_id: str,
    cik: str,
    issuer_name: str,
):
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    return SecSubmissionsCollector(
        SecSettings(
            user_agent="Investment Research OS operator@example.com",
            base_url="https://data.sec.gov",
        ),
        transport=FixtureTransport(
            url,
            (FIXTURE_ROOT / fixture).read_bytes(),
        ),
        clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
    ).discover(
        PrimarySourceRequest(
            operator_id=OPERATOR_ID,
            security_id=security_id,
            cik=cik,
            issuer_name=issuer_name,
            primary_listing_exchange="NASDAQ",
            as_of_cutoff=CUTOFF,
        )
    )


class RequiredSecFilingSelectorTests(unittest.TestCase):
    def test_two_fixtures_use_identical_complete_requirement_contract(
        self,
    ) -> None:
        cases = (
            (
                "rxrx-submissions.json",
                "f594edb2-7fff-4e40-9c26-2c06bcbecb91",
                "0001601830",
                "Recursion Pharmaceuticals, Inc.",
            ),
            (
                "single-asset-submissions.json",
                "8f121435-e5af-4df5-8328-d191463a50ae",
                "0001900001",
                "Single Asset Therapeutics, Inc.",
            ),
        )
        results = tuple(
            RequiredSecFilingSelector().select(
                collected_snapshot(
                    fixture=fixture,
                    security_id=security_id,
                    cik=cik,
                    issuer_name=issuer_name,
                )
            )
            for fixture, security_id, cik, issuer_name in cases
        )

        for result in results:
            self.assertEqual(result.operator_id, OPERATOR_ID)
            self.assertEqual(result.coverage_state, "complete")
            self.assertEqual(
                tuple(
                    requirement.requirement_id
                    for requirement in result.requirement_results
                ),
                (
                    "sec_latest_annual_report",
                    "sec_latest_periodic_report",
                    "sec_post_periodic_current_reports",
                    "sec_financing_filing_scan",
                ),
            )
            self.assertTrue(
                all(
                    requirement.state == "satisfied"
                    for requirement in result.requirement_results
                )
            )
            self.assertEqual(
                [filing.form for filing in result.selected_filings[:2]],
                ["10-K", "10-Q"],
            )
            self.assertIn(
                "sec_required_filings_complete",
                result.reason_codes,
            )
            self.assertEqual(
                result.eligibility_coverage,
                frozenset({"required_sec_filings"}),
            )

        self.assertEqual(
            tuple(
                requirement.requirement_id
                for requirement in results[0].requirement_results
            ),
            tuple(
                requirement.requirement_id
                for requirement in results[1].requirement_results
            ),
        )

    def test_unfetched_submission_history_is_indeterminate(self) -> None:
        snapshot = collected_snapshot(
            fixture="rxrx-submissions.json",
            security_id="f594edb2-7fff-4e40-9c26-2c06bcbecb91",
            cik="0001601830",
            issuer_name="Recursion Pharmaceuticals, Inc.",
        )

        result = RequiredSecFilingSelector().select(
            replace(snapshot, submission_history_complete=False)
        )

        self.assertEqual(result.coverage_state, "indeterminate")
        self.assertEqual(
            result.reason_codes,
            ("sec_submission_history_incomplete",),
        )
        self.assertEqual(result.selected_filings, ())
        self.assertEqual(result.eligibility_coverage, frozenset())
        self.assertTrue(
            all(
                requirement.state == "indeterminate"
                for requirement in result.requirement_results
            )
        )

    def test_ambiguous_required_filing_does_not_fall_back_silently(
        self,
    ) -> None:
        snapshot = collected_snapshot(
            fixture="rxrx-submissions.json",
            security_id="f594edb2-7fff-4e40-9c26-2c06bcbecb91",
            cik="0001601830",
            issuer_name="Recursion Pharmaceuticals, Inc.",
        )
        periodic = next(
            filing
            for filing in snapshot.included_filings
            if filing.form == "10-Q"
        )
        ambiguous = replace(
            periodic,
            accession_number="0001601830-26-000044",
            filing_date=CUTOFF.date(),
            report_date=CUTOFF.date(),
            primary_document="rxrx-20260506-ambiguous.htm",
            archive_url=(
                "https://www.sec.gov/Archives/edgar/data/1601830/"
                "000160183026000044/rxrx-20260506-ambiguous.htm"
            ),
            acceptance_time_raw="2026-05-06T22:00:00",
            publication_state="timezone_ambiguous",
            publication_reason_code="publication_timezone_unresolved",
            valid_at_cutoff=False,
            published_at=None,
            publication_date=CUTOFF.date(),
        )

        result = RequiredSecFilingSelector().select(
            replace(
                snapshot,
                excluded_filings=(
                    *snapshot.excluded_filings,
                    ambiguous,
                ),
            )
        )

        self.assertEqual(result.coverage_state, "indeterminate")
        self.assertEqual(
            result.reason_codes,
            ("sec_required_filing_publication_indeterminate",),
        )
        self.assertEqual(result.selected_filings, ())

    def test_amendment_without_base_filing_is_indeterminate(self) -> None:
        snapshot = collected_snapshot(
            fixture="rxrx-submissions.json",
            security_id="f594edb2-7fff-4e40-9c26-2c06bcbecb91",
            cik="0001601830",
            issuer_name="Recursion Pharmaceuticals, Inc.",
        )
        without_annual_base = tuple(
            replace(filing, form="10-K/A")
            if filing.form == "10-K"
            else filing
            for filing in snapshot.included_filings
        )

        result = RequiredSecFilingSelector().select(
            replace(snapshot, included_filings=without_annual_base)
        )

        self.assertEqual(result.coverage_state, "indeterminate")
        self.assertEqual(
            result.reason_codes,
            ("sec_amendment_base_missing",),
        )
        self.assertEqual(result.selected_filings, ())

    def test_stale_periodic_filing_preserves_annual_result_but_blocks_coverage(
        self,
    ) -> None:
        snapshot = collected_snapshot(
            fixture="rxrx-submissions.json",
            security_id="f594edb2-7fff-4e40-9c26-2c06bcbecb91",
            cik="0001601830",
            issuer_name="Recursion Pharmaceuticals, Inc.",
        )

        result = RequiredSecFilingSelector().select(
            replace(
                snapshot,
                as_of_cutoff=datetime(2027, 1, 30, tzinfo=UTC),
            )
        )

        annual, periodic, *_ = result.requirement_results
        self.assertEqual(result.coverage_state, "incomplete")
        self.assertEqual(annual.state, "satisfied")
        self.assertEqual(
            annual.reason_code,
            "sec_annual_report_selected",
        )
        self.assertEqual(periodic.state, "missing")
        self.assertEqual(
            periodic.reason_code,
            "sec_periodic_report_stale",
        )
        self.assertEqual(
            [filing.form for filing in result.selected_filings],
            ["10-K"],
        )
        self.assertEqual(result.eligibility_coverage, frozenset())


if __name__ == "__main__":
    unittest.main()

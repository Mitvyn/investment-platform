from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
import hashlib
import unittest

from workers.sec.collector import BytesResponse, SecSettings
from workers.sec.documents import (
    SecFilingDocumentCollector,
    SecFilingDocumentError,
)
from workers.sec.selection import SecFilingSelection
from workers.sec.submissions import SecSubmissionFiling


OPERATOR_ID = "8ed47ebc-d5cf-40ad-80ce-d4d803f7c735"
SECURITY_ID = "f594edb2-7fff-4e40-9c26-2c06bcbecb91"
CIK = "0001601830"
CUTOFF = datetime(2026, 5, 6, 23, 59, 59, tzinfo=UTC)


class FixtureTransport:
    def __init__(
        self,
        payloads: dict[str, bytes],
        *,
        content_type: str = "text/html; charset=utf-8",
        final_url: str | None = None,
    ) -> None:
        self.payloads = payloads
        self.content_type = content_type
        self.final_url = final_url
        self.requests: list[tuple[str, dict[str, str]]] = []

    def request(self, url: str, *, headers):
        self.requests.append((url, dict(headers)))
        return BytesResponse(
            body=self.payloads[url],
            status=200,
            headers={"Content-Type": self.content_type},
            final_url=self.final_url or url,
        )


def filing(
    *,
    accession_number: str,
    form: str,
    filing_date: date,
    report_date: date,
    primary_document: str,
) -> SecSubmissionFiling:
    archive_cik = CIK.lstrip("0")
    archive_url = (
        "https://www.sec.gov/Archives/edgar/data/"
        f"{archive_cik}/{accession_number.replace('-', '')}/"
        f"{primary_document}"
    )
    published_at = datetime.combine(
        filing_date,
        datetime.min.time(),
        tzinfo=UTC,
    )
    return SecSubmissionFiling(
        accession_number=accession_number,
        form=form,
        filing_date=filing_date,
        report_date=report_date,
        primary_document=primary_document,
        archive_url=archive_url,
        acceptance_time_raw=published_at.isoformat(),
        publication_state="exact",
        publication_reason_code="publication_at_or_before_cutoff",
        valid_at_cutoff=True,
        published_at=published_at,
        publication_date=filing_date,
    )


def complete_selection(
    *selected_filings: SecSubmissionFiling,
) -> SecFilingSelection:
    return SecFilingSelection(
        policy_version="biotech-required-sec-filings-v1",
        operator_id=OPERATOR_ID,
        security_id=SECURITY_ID,
        cik=CIK,
        as_of_cutoff=CUTOFF,
        coverage_state="complete",
        selected_filings=tuple(selected_filings),
        requirement_results=(),
        reason_codes=("sec_required_filings_complete",),
        eligibility_coverage=frozenset({"required_sec_filings"}),
    )


class SecFilingDocumentCollectorTests(unittest.TestCase):
    def test_collects_every_selected_primary_document_with_source_hashes(
        self,
    ) -> None:
        annual = filing(
            accession_number="0001193125-25-025185",
            form="10-K",
            filing_date=date(2026, 2, 20),
            report_date=date(2025, 12, 31),
            primary_document="issuer-20251231.htm",
        )
        quarterly = filing(
            accession_number="0001601830-26-000040",
            form="10-Q",
            filing_date=date(2026, 5, 6),
            report_date=date(2026, 3, 31),
            primary_document="issuer-20260331.htm",
        )
        selection = complete_selection(annual, quarterly)
        annual_body = b"<html><body>annual filing</body></html>"
        quarterly_body = b"<html><body>quarterly filing</body></html>"
        transport = FixtureTransport(
            {
                annual.archive_url: annual_body,
                quarterly.archive_url: quarterly_body,
            }
        )
        collector = SecFilingDocumentCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
            ),
            transport=transport,
            clock=lambda: datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        )

        snapshot = collector.collect(selection)

        self.assertEqual(snapshot.operator_id, OPERATOR_ID)
        self.assertEqual(snapshot.security_id, SECURITY_ID)
        self.assertEqual(snapshot.cik, CIK)
        self.assertEqual(snapshot.as_of_cutoff, CUTOFF)
        self.assertEqual(
            [document.accession_number for document in snapshot.documents],
            [
                "0001193125-25-025185",
                "0001601830-26-000040",
            ],
        )
        self.assertEqual(
            [document.source_class for document in snapshot.documents],
            ["sec_filing", "sec_filing"],
        )
        self.assertEqual(
            [document.content_sha256 for document in snapshot.documents],
            [
                hashlib.sha256(annual_body).hexdigest(),
                hashlib.sha256(quarterly_body).hexdigest(),
            ],
        )
        self.assertEqual(
            [request[0] for request in transport.requests],
            [annual.archive_url, quarterly.archive_url],
        )

    def test_incomplete_selection_is_rejected_before_document_requests(
        self,
    ) -> None:
        annual = filing(
            accession_number="0001601830-26-000030",
            form="10-K",
            filing_date=date(2026, 2, 20),
            report_date=date(2025, 12, 31),
            primary_document="issuer-20251231.htm",
        )
        selection = replace(
            complete_selection(annual),
            coverage_state="incomplete",
            eligibility_coverage=frozenset(),
        )
        transport = FixtureTransport({})
        collector = SecFilingDocumentCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
            ),
            transport=transport,
        )

        with self.assertRaisesRegex(
            SecFilingDocumentError,
            "filing selection is not complete",
        ):
            collector.collect(selection)

        self.assertEqual(transport.requests, [])

    def test_complete_selection_cannot_be_empty(self) -> None:
        transport = FixtureTransport({})
        collector = SecFilingDocumentCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
            ),
            transport=transport,
        )

        with self.assertRaisesRegex(
            SecFilingDocumentError,
            "filing selection has no documents",
        ):
            collector.collect(complete_selection())

        self.assertEqual(transport.requests, [])

    def test_document_url_is_derived_from_selected_filing_identity(self) -> None:
        annual = filing(
            accession_number="0001601830-26-000030",
            form="10-K",
            filing_date=date(2026, 2, 20),
            report_date=date(2025, 12, 31),
            primary_document="issuer-20251231.htm",
        )
        selection = complete_selection(
            replace(
                annual,
                archive_url="https://example.com/untrusted-document.htm",
            )
        )
        transport = FixtureTransport({})
        collector = SecFilingDocumentCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
            ),
            transport=transport,
        )

        with self.assertRaisesRegex(
            SecFilingDocumentError,
            "filing document URL mismatch",
        ):
            collector.collect(selection)

        self.assertEqual(transport.requests, [])

    def test_post_cutoff_selected_filing_is_rejected_before_request(
        self,
    ) -> None:
        annual = filing(
            accession_number="0001601830-26-000030",
            form="10-K",
            filing_date=date(2026, 2, 20),
            report_date=date(2025, 12, 31),
            primary_document="issuer-20251231.htm",
        )
        selection = complete_selection(
            replace(
                annual,
                valid_at_cutoff=False,
                publication_state="after_cutoff",
                publication_reason_code="publication_after_cutoff",
                published_at=datetime(2026, 5, 7, tzinfo=UTC),
                publication_date=date(2026, 5, 7),
            )
        )
        transport = FixtureTransport({})
        collector = SecFilingDocumentCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
            ),
            transport=transport,
        )

        with self.assertRaisesRegex(
            SecFilingDocumentError,
            "filing is not valid at cutoff",
        ):
            collector.collect(selection)

        self.assertEqual(transport.requests, [])

    def test_claimed_cutoff_validity_cannot_hide_post_cutoff_publication(
        self,
    ) -> None:
        annual = filing(
            accession_number="0001601830-26-000030",
            form="10-K",
            filing_date=date(2026, 2, 20),
            report_date=date(2025, 12, 31),
            primary_document="issuer-20251231.htm",
        )
        selection = complete_selection(
            replace(
                annual,
                acceptance_time_raw="2026-05-07T00:00:00Z",
                valid_at_cutoff=True,
                published_at=datetime(2026, 5, 7, tzinfo=UTC),
                publication_date=date(2026, 5, 7),
            )
        )
        transport = FixtureTransport({})
        collector = SecFilingDocumentCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
            ),
            transport=transport,
        )

        with self.assertRaisesRegex(
            SecFilingDocumentError,
            "filing publication metadata is invalid at cutoff",
        ):
            collector.collect(selection)

        self.assertEqual(transport.requests, [])

    def test_non_html_filing_response_is_rejected(self) -> None:
        annual = filing(
            accession_number="0001601830-26-000030",
            form="10-K",
            filing_date=date(2026, 2, 20),
            report_date=date(2025, 12, 31),
            primary_document="issuer-20251231.htm",
        )
        transport = FixtureTransport(
            {annual.archive_url: b'{"error":"not a filing"}'},
            content_type="application/json",
        )
        collector = SecFilingDocumentCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
            ),
            transport=transport,
        )

        with self.assertRaisesRegex(
            SecFilingDocumentError,
            "filing document content type is invalid",
        ):
            collector.collect(complete_selection(annual))

    def test_empty_html_filing_response_is_rejected(self) -> None:
        annual = filing(
            accession_number="0001601830-26-000030",
            form="10-K",
            filing_date=date(2026, 2, 20),
            report_date=date(2025, 12, 31),
            primary_document="issuer-20251231.htm",
        )
        transport = FixtureTransport({annual.archive_url: b" \n\t"})
        collector = SecFilingDocumentCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
            ),
            transport=transport,
        )

        with self.assertRaisesRegex(
            SecFilingDocumentError,
            "filing document is empty",
        ):
            collector.collect(complete_selection(annual))

    def test_redirected_filing_response_is_rejected(self) -> None:
        annual = filing(
            accession_number="0001601830-26-000030",
            form="10-K",
            filing_date=date(2026, 2, 20),
            report_date=date(2025, 12, 31),
            primary_document="issuer-20251231.htm",
        )
        transport = FixtureTransport(
            {annual.archive_url: b"<html><body>redirected</body></html>"},
            final_url="https://example.com/redirected.htm",
        )
        collector = SecFilingDocumentCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
            ),
            transport=transport,
        )

        with self.assertRaisesRegex(
            SecFilingDocumentError,
            "filing document redirected",
        ):
            collector.collect(complete_selection(annual))


if __name__ == "__main__":
    unittest.main()

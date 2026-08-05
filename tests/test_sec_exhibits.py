from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
import hashlib
from pathlib import Path
import unittest

from workers.sec.collector import BytesResponse, SecSettings
from workers.sec.documents import (
    SecFilingDocument,
    SecFilingDocumentSnapshot,
)
from workers.sec.exhibits import SecFilingExhibitCollector
from workers.sec.exhibits import SecFilingExhibitError


OPERATOR_ID = "8ed47ebc-d5cf-40ad-80ce-d4d803f7c735"
SECURITY_ID = "f594edb2-7fff-4e40-9c26-2c06bcbecb91"
CIK = "0001601830"
ACCESSION = "0001193125-25-025185"
CUTOFF = datetime(2026, 5, 6, 23, 59, 59, tzinfo=UTC)
RETRIEVED_AT = datetime(2026, 5, 7, 1, 0, tzinfo=UTC)
FIXTURES = Path(__file__).parent / "fixtures" / "primary_sources"
INDEX_URL = (
    "https://www.sec.gov/Archives/edgar/data/1601830/"
    "000119312525025185/0001193125-25-025185-index.html"
)
EXHIBIT_URL = (
    "https://www.sec.gov/Archives/edgar/data/1601830/000119312525025185/exhibit991.htm"
)
SECOND_EXHIBIT_URL = (
    "https://www.sec.gov/Archives/edgar/data/1601830/000119312525025185/exhibit992.htm"
)


class FixtureTransport:
    def __init__(
        self,
        payloads: dict[str, tuple[bytes, str]],
        *,
        final_urls: dict[str, str] | None = None,
    ) -> None:
        self.payloads = payloads
        self.final_urls = final_urls or {}
        self.requests: list[tuple[str, dict[str, str]]] = []

    def request(self, url: str, *, headers):
        self.requests.append((url, dict(headers)))
        body, content_type = self.payloads[url]
        return BytesResponse(
            body=body,
            status=200,
            headers={"Content-Type": content_type},
            final_url=self.final_urls.get(url, url),
        )


def primary_document_snapshot() -> SecFilingDocumentSnapshot:
    content = "<html><body>quarterly report</body></html>"
    published_at = datetime(2026, 5, 6, 20, 30, tzinfo=UTC)
    return SecFilingDocumentSnapshot(
        operator_id=OPERATOR_ID,
        security_id=SECURITY_ID,
        cik=CIK,
        as_of_cutoff=CUTOFF,
        policy_version="biotech-required-sec-filings-v1",
        documents=(
            SecFilingDocument(
                operator_id=OPERATOR_ID,
                security_id=SECURITY_ID,
                cik=CIK,
                accession_number=ACCESSION,
                form="10-Q",
                filing_date=date(2026, 5, 6),
                report_date=date(2026, 3, 31),
                primary_document="issuer-20260331.htm",
                source_class="sec_filing",
                source_url=(
                    "https://www.sec.gov/Archives/edgar/data/1601830/"
                    "000119312525025185/issuer-20260331.htm"
                ),
                published_at=published_at,
                publication_date=published_at.date(),
                retrieved_at=RETRIEVED_AT,
                content_sha256=hashlib.sha256(content.encode()).hexdigest(),
                content_text=content,
            ),
        ),
    )


class SecFilingExhibitCollectorTests(unittest.TestCase):
    def test_discovers_and_collects_html_exhibit_from_canonical_index(
        self,
    ) -> None:
        index_body = (FIXTURES / "generic-filing-index.html").read_bytes()
        exhibit_body = (FIXTURES / "generic-exhibit-991.html").read_bytes()
        transport = FixtureTransport(
            {
                INDEX_URL: (index_body, "text/html; charset=utf-8"),
                EXHIBIT_URL: (exhibit_body, "text/html; charset=utf-8"),
            }
        )
        collector = SecFilingExhibitCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
            ),
            transport=transport,
            clock=lambda: RETRIEVED_AT,
        )

        snapshot = collector.collect(primary_document_snapshot())

        self.assertEqual(snapshot.operator_id, OPERATOR_ID)
        self.assertEqual(snapshot.security_id, SECURITY_ID)
        self.assertEqual(snapshot.cik, CIK)
        self.assertEqual(snapshot.as_of_cutoff, CUTOFF)
        self.assertEqual(snapshot.policy_version, "sec-html-exhibits-v1")
        self.assertEqual(len(snapshot.indexes), 1)
        self.assertEqual(snapshot.indexes[0].source_url, INDEX_URL)
        self.assertEqual(
            snapshot.indexes[0].content_sha256,
            hashlib.sha256(index_body).hexdigest(),
        )
        self.assertEqual(len(snapshot.exhibits), 1)
        exhibit = snapshot.exhibits[0]
        self.assertEqual(exhibit.accession_number, ACCESSION)
        self.assertEqual(exhibit.sequence, "2")
        self.assertEqual(exhibit.description, "Clinical programme update")
        self.assertEqual(exhibit.exhibit_type, "EX-99.1")
        self.assertEqual(exhibit.document_name, "exhibit991.htm")
        self.assertEqual(exhibit.source_class, "sec_filing_exhibit")
        self.assertEqual(exhibit.source_url, EXHIBIT_URL)
        self.assertEqual(
            exhibit.content_sha256,
            hashlib.sha256(exhibit_body).hexdigest(),
        )
        self.assertEqual(
            [request[0] for request in transport.requests],
            [INDEX_URL, EXHIBIT_URL],
        )

    def test_collects_exhibit_from_exact_sec_ixviewer_link(self) -> None:
        index_body = (
            "<html><body>"
            '<table summary="Document Format Files">'
            "<tr>"
            "<td>2</td><td>Clinical programme update</td>"
            '<td><a href="/ix?doc=/Archives/edgar/data/1601830/'
            '000119312525025185/exhibit991.htm">exhibit991.htm</a> '
            "iXBRL</td>"
            "<td>EX-99.1</td><td>1000</td>"
            "</tr></table></body></html>"
        ).encode()
        exhibit_body = (FIXTURES / "generic-exhibit-991.html").read_bytes()
        transport = FixtureTransport(
            {
                INDEX_URL: (index_body, "text/html"),
                EXHIBIT_URL: (exhibit_body, "text/html"),
            }
        )

        snapshot = SecFilingExhibitCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
            ),
            transport=transport,
            clock=lambda: RETRIEVED_AT,
        ).collect(primary_document_snapshot())

        self.assertEqual(snapshot.exhibits[0].document_name, "exhibit991.htm")
        self.assertEqual(snapshot.exhibits[0].source_url, EXHIBIT_URL)

    def test_exhibits_are_deduplicated_and_sorted_deterministically(
        self,
    ) -> None:
        index_body = (FIXTURES / "generic-filing-index-duplicates.html").read_bytes()
        exhibit_body = (FIXTURES / "generic-exhibit-991.html").read_bytes()
        transport = FixtureTransport(
            {
                INDEX_URL: (index_body, "text/html"),
                EXHIBIT_URL: (exhibit_body, "text/html"),
                SECOND_EXHIBIT_URL: (exhibit_body, "text/html"),
            }
        )
        collector = SecFilingExhibitCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
            ),
            transport=transport,
            clock=lambda: RETRIEVED_AT,
        )

        snapshot = collector.collect(primary_document_snapshot())

        self.assertEqual(
            [
                (exhibit.sequence, exhibit.document_name)
                for exhibit in snapshot.exhibits
            ],
            [
                ("2", "exhibit991.htm"),
                ("10", "exhibit992.htm"),
            ],
        )
        self.assertEqual(
            [request[0] for request in transport.requests],
            [INDEX_URL, EXHIBIT_URL, SECOND_EXHIBIT_URL],
        )

    def test_conflicting_duplicate_exhibit_identity_is_rejected(
        self,
    ) -> None:
        index_body = b"""
        <html><body>
          <table summary="Document Format Files">
            <tr>
              <td>2</td><td>Clinical update</td>
              <td><a href="exhibit991.htm">exhibit991.htm</a></td>
              <td>EX-99.1</td><td>100</td>
            </tr>
            <tr>
              <td>3</td><td>Conflicting description</td>
              <td><a href="exhibit991.htm">exhibit991.htm</a></td>
              <td>EX-99.2</td><td>100</td>
            </tr>
          </table>
        </body></html>
        """
        transport = FixtureTransport(
            {
                INDEX_URL: (index_body, "text/html"),
                EXHIBIT_URL: (
                    b"<html><body>must not fetch</body></html>",
                    "text/html",
                ),
            }
        )
        collector = SecFilingExhibitCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
            ),
            transport=transport,
            clock=lambda: RETRIEVED_AT,
        )

        with self.assertRaisesRegex(
            SecFilingExhibitError,
            "conflicting duplicate exhibit",
        ):
            collector.collect(primary_document_snapshot())

        self.assertEqual(
            [request[0] for request in transport.requests],
            [INDEX_URL],
        )

    def test_timezone_unresolved_publication_is_rejected_before_request(
        self,
    ) -> None:
        snapshot = primary_document_snapshot()
        snapshot = replace(
            snapshot,
            documents=(
                replace(
                    snapshot.documents[0],
                    published_at=datetime(2026, 5, 6, 20, 30),
                ),
            ),
        )
        transport = FixtureTransport({})
        collector = SecFilingExhibitCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
            ),
            transport=transport,
            clock=lambda: RETRIEVED_AT,
        )

        with self.assertRaisesRegex(
            SecFilingExhibitError,
            "publication timestamp must include timezone",
        ):
            collector.collect(snapshot)

        self.assertEqual(transport.requests, [])

    def test_post_cutoff_publication_is_rejected_before_request(
        self,
    ) -> None:
        snapshot = primary_document_snapshot()
        published_at = datetime(2026, 5, 7, 0, 0, tzinfo=UTC)
        snapshot = replace(
            snapshot,
            documents=(
                replace(
                    snapshot.documents[0],
                    published_at=published_at,
                    publication_date=published_at.date(),
                ),
            ),
        )
        transport = FixtureTransport({})
        collector = SecFilingExhibitCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
            ),
            transport=transport,
            clock=lambda: RETRIEVED_AT,
        )

        with self.assertRaisesRegex(
            SecFilingExhibitError,
            "filing document is after cutoff",
        ):
            collector.collect(snapshot)

        self.assertEqual(transport.requests, [])

    def test_primary_document_locator_mismatch_is_rejected_before_request(
        self,
    ) -> None:
        snapshot = primary_document_snapshot()
        snapshot = replace(
            snapshot,
            documents=(
                replace(
                    snapshot.documents[0],
                    source_url="https://example.com/untrusted.htm",
                ),
            ),
        )
        transport = FixtureTransport({})
        collector = SecFilingExhibitCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
            ),
            transport=transport,
            clock=lambda: RETRIEVED_AT,
        )

        with self.assertRaisesRegex(
            SecFilingExhibitError,
            "primary document URL mismatch",
        ):
            collector.collect(snapshot)

        self.assertEqual(transport.requests, [])

    def test_redirected_filing_index_is_rejected(self) -> None:
        transport = FixtureTransport(
            {INDEX_URL: (b"<html>redirected</html>", "text/html")},
            final_urls={
                INDEX_URL: "https://www.sec.gov/Archives/redirected.html",
            },
        )
        collector = SecFilingExhibitCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
            ),
            transport=transport,
            clock=lambda: RETRIEVED_AT,
        )

        with self.assertRaisesRegex(
            SecFilingExhibitError,
            "filing index redirected",
        ):
            collector.collect(primary_document_snapshot())

    def test_non_html_exhibit_response_is_rejected(self) -> None:
        index_body = (FIXTURES / "generic-filing-index.html").read_bytes()
        transport = FixtureTransport(
            {
                INDEX_URL: (index_body, "text/html"),
                EXHIBIT_URL: (b'{"unexpected":true}', "application/json"),
            }
        )
        collector = SecFilingExhibitCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
            ),
            transport=transport,
            clock=lambda: RETRIEVED_AT,
        )

        with self.assertRaisesRegex(
            SecFilingExhibitError,
            "filing exhibit content type is invalid",
        ):
            collector.collect(primary_document_snapshot())

    def test_empty_filing_index_is_rejected(self) -> None:
        transport = FixtureTransport({INDEX_URL: (b" \n\t", "text/html")})
        collector = SecFilingExhibitCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
            ),
            transport=transport,
            clock=lambda: RETRIEVED_AT,
        )

        with self.assertRaisesRegex(
            SecFilingExhibitError,
            "filing index is empty",
        ):
            collector.collect(primary_document_snapshot())

    def test_non_utf8_exhibit_response_is_rejected(self) -> None:
        index_body = (FIXTURES / "generic-filing-index.html").read_bytes()
        transport = FixtureTransport(
            {
                INDEX_URL: (index_body, "text/html"),
                EXHIBIT_URL: (b"\xff\xfe", "text/html"),
            }
        )
        collector = SecFilingExhibitCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
            ),
            transport=transport,
            clock=lambda: RETRIEVED_AT,
        )

        with self.assertRaisesRegex(
            SecFilingExhibitError,
            "filing exhibit is not valid UTF-8",
        ):
            collector.collect(primary_document_snapshot())

    def test_missing_document_manifest_is_rejected(self) -> None:
        transport = FixtureTransport(
            {
                INDEX_URL: (
                    b"<html><body>unexpected index layout</body></html>",
                    "text/html",
                ),
            }
        )
        collector = SecFilingExhibitCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
            ),
            transport=transport,
            clock=lambda: RETRIEVED_AT,
        )

        with self.assertRaisesRegex(
            SecFilingExhibitError,
            "document manifest is missing",
        ):
            collector.collect(primary_document_snapshot())

    def test_non_html_exhibit_is_discovered_but_not_collected_as_html(
        self,
    ) -> None:
        index_body = b"""
        <html><body>
          <table summary="Document Format Files">
            <tr>
              <td>2</td><td>Material agreement</td>
              <td><a href="agreement.pdf">agreement.pdf</a></td>
              <td>EX-10.1</td><td>1000</td>
            </tr>
            <tr>
              <td>3</td><td>Clinical update</td>
              <td><a href="exhibit991.htm">exhibit991.htm</a></td>
              <td>EX-99.1</td><td>2000</td>
            </tr>
          </table>
        </body></html>
        """
        exhibit_body = (FIXTURES / "generic-exhibit-991.html").read_bytes()
        transport = FixtureTransport(
            {
                INDEX_URL: (index_body, "text/html"),
                EXHIBIT_URL: (exhibit_body, "text/html"),
            }
        )
        collector = SecFilingExhibitCollector(
            SecSettings(
                user_agent="Investment Research OS operator@example.com",
            ),
            transport=transport,
            clock=lambda: RETRIEVED_AT,
        )

        snapshot = collector.collect(primary_document_snapshot())

        self.assertEqual(
            [
                (
                    reference.document_name,
                    reference.collection_state,
                )
                for reference in snapshot.references
            ],
            [
                ("agreement.pdf", "unsupported_media"),
                ("exhibit991.htm", "collected_html"),
            ],
        )
        self.assertEqual(
            [exhibit.document_name for exhibit in snapshot.exhibits],
            ["exhibit991.htm"],
        )
        self.assertEqual(
            [request[0] for request in transport.requests],
            [INDEX_URL, EXHIBIT_URL],
        )


if __name__ == "__main__":
    unittest.main()

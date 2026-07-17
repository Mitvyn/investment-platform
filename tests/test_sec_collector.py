from __future__ import annotations

import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping

from workers.sec import (
    BytesResponse,
    FilingRequest,
    SecCollector,
    SecSettings,
    build_evidence_trace,
)

OPERATOR_ID = "8ed47ebc-d5cf-40ad-80ce-d4d803f7c735"
PASSAGE = (
    "Cash and cash equivalents totaled $525.1 million and $594.3 million "
    "as of June 30, 2025 and December 31, 2024, respectively."
)


def filing_request() -> FilingRequest:
    return FilingRequest(
        ticker="RXRX",
        company_name="Recursion Pharmaceuticals, Inc.",
        cik="1601830",
        accession_number="0001601830-25-000127",
        primary_document="rxrx-20250630.htm",
        filing_form="10-Q",
        filed_at="2025-08-05",
        period_end="2025-06-30",
        passage_locator=(
            "Part I, Item 2, Liquidity and Capital Resources, "
            "Sources of Liquidity"
        ),
        expected_passage=PASSAGE,
        claim_text=(
            "RXRX reported $525.1 million in cash and cash equivalents "
            "as of June 30, 2025."
        ),
    )


class FakeTransport:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.requests: list[tuple[str, Mapping[str, str]]] = []

    def request(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
    ) -> BytesResponse:
        self.requests.append((url, dict(headers)))
        return BytesResponse(body=self.body, status=200, headers={})


class SecCollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        fixture = Path("tests/fixtures/sec/rxrx-20250630.html")
        self.body = fixture.read_bytes()

    def test_collects_exact_sec_filing_with_required_identity_header(self) -> None:
        transport = FakeTransport(self.body)
        collector = SecCollector(
            SecSettings(user_agent="Investment Research OS ops@example.com"),
            transport=transport,
            clock=lambda: datetime(2026, 7, 16, 8, 0, tzinfo=UTC),
        )

        filing = collector.fetch_filing(filing_request())

        self.assertEqual(
            filing.source_url,
            "https://www.sec.gov/Archives/edgar/data/1601830/"
            "000160183025000127/rxrx-20250630.htm",
        )
        self.assertEqual(len(transport.requests), 1)
        self.assertEqual(
            transport.requests[0][1]["User-Agent"],
            "Investment Research OS ops@example.com",
        )
        self.assertEqual(filing.retrieved_at, "2026-07-16T08:00:00+00:00")

    def test_builds_supported_claim_with_stable_idempotent_ids(self) -> None:
        collector = SecCollector(
            SecSettings(user_agent="Investment Research OS ops@example.com"),
            transport=FakeTransport(self.body),
            clock=lambda: datetime(2026, 7, 16, 8, 0, tzinfo=UTC),
        )
        filing = collector.fetch_filing(filing_request())

        first = build_evidence_trace(filing, operator_id=OPERATOR_ID)
        second = build_evidence_trace(filing, operator_id=OPERATOR_ID)

        self.assertEqual(first, second)
        self.assertEqual(first.verification_state, "supported")
        self.assertEqual(first.relationship, "supports")
        self.assertEqual(first.passage_text, PASSAGE)
        self.assertEqual(
            first.idempotency_key,
            "sec:RXRX:0001601830-25-000127:v1",
        )

    def test_rejects_missing_or_ambiguous_expected_passage(self) -> None:
        collector = SecCollector(
            SecSettings(user_agent="Investment Research OS ops@example.com"),
            transport=FakeTransport(b"<html><body>different text</body></html>"),
        )
        filing = collector.fetch_filing(filing_request())

        with self.assertRaisesRegex(ValueError, "exactly once"):
            build_evidence_trace(filing, operator_id=OPERATOR_ID)

    def test_rejects_sec_user_agent_without_email(self) -> None:
        with self.assertRaisesRegex(ValueError, "email"):
            SecSettings(user_agent="Investment Research OS")


if __name__ == "__main__":
    unittest.main()

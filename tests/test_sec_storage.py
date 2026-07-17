from __future__ import annotations

import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from workers.sec import FilingRequest, SecCollector, SecSettings, build_evidence_trace
from workers.sec.collector import BytesResponse
from workers.sec.storage import (
    EvidenceStorageError,
    JsonResponse,
    SupabaseEvidenceStore,
    SupabaseStorageSettings,
)

OPERATOR_ID = "8ed47ebc-d5cf-40ad-80ce-d4d803f7c735"


class FilingTransport:
    def request(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
    ) -> BytesResponse:
        return BytesResponse(
            body=Path("tests/fixtures/sec/rxrx-20250630.html").read_bytes(),
            status=200,
            headers={},
        )


class RecordingJsonTransport:
    def __init__(self, responses: list[JsonResponse] | None = None) -> None:
        self.requests: list[dict[str, Any]] = []
        self.responses = iter(responses or [])

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any] | None = None,
    ) -> JsonResponse:
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "payload": dict(payload) if payload is not None else None,
            }
        )
        return next(
            self.responses,
            JsonResponse(payload=None, status=201, headers={}),
        )


def trace():
    request = FilingRequest(
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
        expected_passage=(
            "Cash and cash equivalents totaled $525.1 million and $594.3 "
            "million as of June 30, 2025 and December 31, 2024, respectively."
        ),
        claim_text=(
            "RXRX reported $525.1 million in cash and cash equivalents "
            "as of June 30, 2025."
        ),
    )
    collector = SecCollector(
        SecSettings(user_agent="Investment Research OS ops@example.com"),
        transport=FilingTransport(),
        clock=lambda: datetime(2026, 7, 16, 8, 0, tzinfo=UTC),
    )
    return build_evidence_trace(
        collector.fetch_filing(request),
        operator_id=OPERATOR_ID,
    )


class SupabaseEvidenceStoreTests(unittest.TestCase):
    def test_persists_dependency_order_with_idempotent_inserts(self) -> None:
        transport = RecordingJsonTransport()
        store = SupabaseEvidenceStore(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
        )
        evidence = trace()

        store.persist(evidence)
        store.persist(evidence)

        expected_tables = [
            "iros_research_runs",
            "iros_sources",
            "iros_source_documents",
            "iros_source_passages",
            "iros_claims",
            "iros_claim_evidence",
        ]
        actual_tables = [
            request["url"].split("/rest/v1/")[1].split("?")[0]
            for request in transport.requests[:6]
        ]
        self.assertEqual(actual_tables, expected_tables)
        self.assertEqual(
            transport.requests[:6],
            transport.requests[6:],
        )
        self.assertTrue(
            all(
                request["headers"]["Prefer"]
                == "resolution=ignore-duplicates,return=minimal"
                for request in transport.requests
            )
        )
        self.assertTrue(
            all("on_conflict=id" in request["url"] for request in transport.requests)
        )
        self.assertTrue(
            all(
                request["headers"]["apikey"] == "sb_secret_test"
                for request in transport.requests
            )
        )
        self.assertTrue(
            all(
                "Authorization" not in request["headers"]
                for request in transport.requests
            )
        )

    def test_verifies_exactly_one_matching_hosted_row_per_table(self) -> None:
        evidence = trace()
        records = SupabaseEvidenceStore._records(evidence)
        responses = []
        for _, record in records:
            expected = {
                key: value
                for key, value in record.items()
                if key
                not in {
                    "finished_at",
                    "retrieved_at",
                    "started_at",
                    "verified_at",
                }
            }
            responses.append(JsonResponse(payload=[expected], status=200, headers={}))

        transport = RecordingJsonTransport(responses)
        store = SupabaseEvidenceStore(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
        )

        verified = store.verify(evidence)

        self.assertEqual(
            verified,
            {table: record["id"] for table, record in records},
        )
        self.assertTrue(
            all(request["method"] == "GET" for request in transport.requests)
        )
        self.assertTrue(
            all(request["payload"] is None for request in transport.requests)
        )
        self.assertTrue(
            all(
                request["headers"] == {"apikey": "sb_secret_test"}
                for request in transport.requests
            )
        )

    def test_rejects_missing_or_duplicate_hosted_rows(self) -> None:
        evidence = trace()
        store = SupabaseEvidenceStore(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=RecordingJsonTransport(
                [JsonResponse(payload=[], status=200, headers={})]
            ),
        )

        with self.assertRaisesRegex(EvidenceStorageError, "exactly one"):
            store.verify(evidence)


if __name__ == "__main__":
    unittest.main()

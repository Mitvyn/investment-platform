from __future__ import annotations

import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from workers.issuer.__main__ import RXRX_Q1_2026
from workers.issuer.collector import BytesResponse, IssuerCollector
from workers.issuer.storage import SupabaseIssuerStore
from workers.issuer.tracer import build_issuer_context
from workers.sec.storage import (
    EvidenceStorageError,
    JsonResponse,
    SupabaseStorageSettings,
)


class BytesFake:
    def request(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
    ) -> BytesResponse:
        return BytesResponse(
            body=Path("tests/fixtures/issuer/rxrx-q1-2026.html").read_bytes(),
            status=200,
            headers={},
        )


class JsonFake:
    def __init__(
        self,
        responses: list[JsonResponse] | None = None,
    ) -> None:
        self.posts: list[
            tuple[str, Mapping[str, str], Mapping[str, Any]]
        ] = []
        self.responses = iter(responses or [])

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any] | None = None,
    ) -> JsonResponse:
        if method == "POST":
            assert payload is not None
            self.posts.append((url, headers, payload))
            return JsonResponse(payload=None, status=201, headers={})
        if method == "GET":
            return next(self.responses)
        raise AssertionError(f"unexpected method: {method}")


class IssuerStorageTests(unittest.TestCase):
    def context(self):
        return build_issuer_context(
            IssuerCollector(
                transport=BytesFake(),
                clock=lambda: datetime(2026, 7, 17, tzinfo=UTC),
            ).fetch_release(RXRX_Q1_2026),
            operator_id="11111111-1111-4111-8111-111111111111",
        )

    def test_persists_dependency_order_with_id_conflict_protection(self) -> None:
        context = self.context()
        transport = JsonFake()
        store = SupabaseIssuerStore(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
        )

        store.persist(context)

        tables = [
            url.split("/rest/v1/")[1].split("?")[0]
            for url, _, _ in transport.posts
        ]
        self.assertEqual(tables[0:2], ["iros_research_runs", "iros_issuer_releases"])
        self.assertEqual(tables.count("iros_issuer_passages"), 4)
        self.assertEqual(tables.count("iros_financial_metrics"), 5)
        self.assertEqual(tables.count("iros_catalysts"), 1)
        self.assertEqual(tables.count("iros_risks"), 1)
        self.assertTrue(
            all("on_conflict=id" in url for url, _, _ in transport.posts)
        )
        self.assertTrue(
            all(
                headers["apikey"] == "sb_secret_test"
                and "Authorization" not in headers
                for _, headers, _ in transport.posts
            )
        )

    def test_verify_names_mismatched_fields_without_logging_values(self) -> None:
        context = self.context()
        records = SupabaseIssuerStore._records(context)
        responses: list[JsonResponse] = []

        for _, record in records[:2]:
            expected = {
                key: value
                for key, value in record.items()
                if key not in {"finished_at", "retrieved_at", "started_at"}
            }
            responses.append(
                JsonResponse(payload=[expected], status=200, headers={})
            )

        hosted_release = responses[1].payload[0]
        hosted_release["content_sha256"] = "0" * 64
        store = SupabaseIssuerStore(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=JsonFake(responses),
        )

        with self.assertRaisesRegex(
            EvidenceStorageError,
            "mismatched fields: content_sha256",
        ) as raised:
            store.verify(context)

        self.assertNotIn("0" * 64, str(raised.exception))

    def test_verify_treats_equivalent_timestamp_offsets_as_equal(self) -> None:
        context = self.context()
        records = SupabaseIssuerStore._records(context)
        responses: list[JsonResponse] = []

        for _, record in records:
            hosted = {
                key: value
                for key, value in record.items()
                if key not in {"finished_at", "retrieved_at", "started_at"}
            }
            if "published_at" in hosted:
                hosted["published_at"] = "2026-05-06T11:05:00+00:00"
            responses.append(
                JsonResponse(payload=[hosted], status=200, headers={})
            )

        store = SupabaseIssuerStore(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=JsonFake(responses),
        )

        verified = store.verify(context)

        self.assertEqual(
            sum(len(ids) for ids in verified.values()),
            len(records),
        )


if __name__ == "__main__":
    unittest.main()

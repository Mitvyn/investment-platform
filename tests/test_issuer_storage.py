from __future__ import annotations

import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from workers.issuer.__main__ import RXRX_Q1_2026
from workers.issuer.collector import BytesResponse, IssuerCollector
from workers.issuer.storage import SupabaseIssuerStore
from workers.issuer.tracer import build_issuer_context
from workers.sec.storage import JsonResponse, SupabaseStorageSettings


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
    def __init__(self) -> None:
        self.posts: list[
            tuple[str, Mapping[str, str], Mapping[str, Any]]
        ] = []

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
        raise AssertionError("unexpected GET")


class IssuerStorageTests(unittest.TestCase):
    def test_persists_dependency_order_with_id_conflict_protection(self) -> None:
        context = build_issuer_context(
            IssuerCollector(
                transport=BytesFake(),
                clock=lambda: datetime(2026, 7, 17, tzinfo=UTC),
            ).fetch_release(RXRX_Q1_2026),
            operator_id="11111111-1111-4111-8111-111111111111",
        )
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


if __name__ == "__main__":
    unittest.main()

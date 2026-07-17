from __future__ import annotations

import unittest
from datetime import UTC, datetime
from typing import Any, Mapping

from workers.market.client import (
    JsonResponse as QuoteResponse,
    TwelveDataClient,
    TwelveDataSettings,
)
from workers.market.storage import SupabaseMarketStore
from workers.sec.storage import JsonResponse, SupabaseStorageSettings

from tests.test_market_client import QUOTE


class QuoteFake:
    def request_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
    ) -> QuoteResponse:
        return QuoteResponse(payload=QUOTE, status=200, raw_body=b"{}")


class StoreFake:
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
        assert method == "POST"
        assert payload is not None
        self.posts.append((url, headers, payload))
        return JsonResponse(payload=None, status=201, headers={})


class MarketStorageTests(unittest.TestCase):
    def test_persists_run_before_snapshot_idempotently(self) -> None:
        snapshot = TwelveDataClient(
            TwelveDataSettings(api_key="provider-secret"),
            transport=QuoteFake(),
            clock=lambda: datetime(2026, 7, 17, 3, 0, tzinfo=UTC),
        ).fetch_quote(
            "RXRX",
            operator_id="11111111-1111-4111-8111-111111111111",
        )
        transport = StoreFake()
        store = SupabaseMarketStore(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
        )

        store.persist(snapshot)

        tables = [
            url.split("/rest/v1/")[1].split("?")[0]
            for url, _, _ in transport.posts
        ]
        self.assertEqual(tables, ["iros_research_runs", "iros_market_snapshots"])
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

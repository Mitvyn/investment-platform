from __future__ import annotations

import unittest
from datetime import UTC, datetime
from typing import Any, Mapping

from workers.market.client import (
    YFinanceClient,
    YFinanceQuote,
    YFinanceSettings,
)
from workers.market.storage import SupabaseMarketStore
from workers.sec.storage import JsonResponse, SupabaseStorageSettings

from tests.test_market_client import QUOTE, SERIES_QUOTE


class QuoteFake:
    def fetch_quote(
        self,
        ticker: str,
        *,
        settings: YFinanceSettings,
    ) -> YFinanceQuote:
        return QUOTE


class SeriesQuoteFake:
    def fetch_quote(
        self,
        ticker: str,
        *,
        settings: YFinanceSettings,
    ) -> YFinanceQuote:
        return SERIES_QUOTE


class StoreFake:
    def __init__(self) -> None:
        self.posts: list[tuple[str, Mapping[str, str], Mapping[str, Any]]] = []

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
    def test_persists_content_addressed_daily_bars_after_snapshot(self) -> None:
        snapshot = YFinanceClient(
            YFinanceSettings(),
            provider=SeriesQuoteFake(),
            clock=lambda: datetime(2026, 7, 17, 3, 0, tzinfo=UTC),
        ).fetch_quote(
            "RXRX",
            operator_id="11111111-1111-4111-8111-111111111111",
            security_id="22222222-2222-4222-8222-222222222222",
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
            url.split("/rest/v1/")[1].split("?")[0] for url, _, _ in transport.posts
        ]
        self.assertEqual(
            tables,
            [
                "iros_research_runs",
                "iros_market_snapshots",
                "iros_market_series",
                "iros_market_bars",
                "iros_market_bars",
                "rpc/iros_finalize_market_series",
            ],
        )
        self.assertEqual(transport.posts[0][2]["status"], "running")
        self.assertEqual(transport.posts[0][2]["persistence_state"], "draft")
        self.assertEqual(transport.posts[2][2]["persistence_state"], "draft")
        self.assertIn("on_conflict=operator_id%2Cid", transport.posts[2][0])
        self.assertTrue(
            all(
                "on_conflict=operator_id%2Cid" in url
                for url, _, _ in transport.posts[3:-1]
            )
        )
        self.assertEqual(transport.posts[2][2]["expected_bar_count"], 2)
        latest_bar = transport.posts[-2][2]
        self.assertEqual(latest_bar["security_id"], snapshot.security_id)
        self.assertEqual(latest_bar["session_date"], "2026-07-16")
        self.assertEqual(latest_bar["high"], 5.50)
        self.assertEqual(len(str(latest_bar["bar_sha256"])), 64)
        self.assertEqual(
            transport.posts[-1][2],
            {
                "selected_operator_id": snapshot.operator_id,
                "selected_series_id": snapshot.series_id,
            },
        )

    def test_persists_run_before_snapshot_idempotently(self) -> None:
        snapshot = YFinanceClient(
            YFinanceSettings(),
            provider=QuoteFake(),
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
            url.split("/rest/v1/")[1].split("?")[0] for url, _, _ in transport.posts
        ]
        self.assertEqual(tables, ["iros_research_runs", "iros_market_snapshots"])
        self.assertTrue(
            all(
                "on_conflict=operator_id%2Cid" in url
                for url, _, _ in transport.posts
            )
        )
        self.assertTrue(
            all(
                headers["apikey"] == "sb_secret_test" and "Authorization" not in headers
                for _, headers, _ in transport.posts
            )
        )


if __name__ == "__main__":
    unittest.main()

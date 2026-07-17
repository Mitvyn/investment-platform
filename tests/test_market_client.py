from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stderr
from datetime import UTC, datetime
from typing import Any, Mapping
from unittest.mock import patch

from workers.market.__main__ import run
from workers.market.client import (
    JsonResponse,
    MarketDataError,
    TwelveDataClient,
    TwelveDataSettings,
)


QUOTE = {
    "symbol": "RXRX",
    "exchange": "NASDAQ",
    "currency": "USD",
    "timestamp": 1784232000,
    "close": "5.42",
    "previous_close": "5.20",
    "change": "0.22",
    "percent_change": "4.23077",
    "volume": "1234567",
    "is_market_open": False,
}


class FakeTransport:
    def __init__(self, payload: Any, status: int = 200) -> None:
        self.payload = payload
        self.status = status
        self.calls: list[tuple[str, Mapping[str, str]]] = []

    def request_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
    ) -> JsonResponse:
        self.calls.append((url, headers))
        return JsonResponse(payload=self.payload, status=self.status, raw_body=b"{}")


class MarketClientTests(unittest.TestCase):
    def test_maps_quote_and_keeps_key_out_of_url(self) -> None:
        transport = FakeTransport(QUOTE)
        client = TwelveDataClient(
            TwelveDataSettings(api_key="provider-secret"),
            transport=transport,
            clock=lambda: datetime(2026, 7, 17, 3, 0, tzinfo=UTC),
        )

        snapshot = client.fetch_quote(
            "rxrx",
            operator_id="11111111-1111-4111-8111-111111111111",
        )

        url, headers = transport.calls[0]
        self.assertEqual(url, "https://api.twelvedata.com/quote?symbol=RXRX")
        self.assertNotIn("provider-secret", url)
        self.assertEqual(headers["Authorization"], "apikey provider-secret")
        self.assertEqual(snapshot.ticker, "RXRX")
        self.assertEqual(snapshot.close, 5.42)
        self.assertEqual(snapshot.volume, 1234567)
        self.assertFalse(snapshot.is_market_open)
        self.assertEqual(len(snapshot.response_sha256), 64)

    def test_rejects_provider_error_payload(self) -> None:
        client = TwelveDataClient(
            TwelveDataSettings(api_key="provider-secret"),
            transport=FakeTransport(
                {"status": "error", "message": "API credits exhausted"}
            ),
        )

        with self.assertRaisesRegex(MarketDataError, "credits exhausted"):
            client.fetch_quote(
                "RXRX",
                operator_id="11111111-1111-4111-8111-111111111111",
            )

    def test_cli_fails_before_network_when_key_is_missing(self) -> None:
        environment = {
            "IROS_OPERATOR_ID": "11111111-1111-4111-8111-111111111111",
            "IROS_SUPABASE_URL": "https://example.supabase.co",
            "IROS_SUPABASE_SECRET_KEY": "sb_secret_test",
        }
        stderr = io.StringIO()
        with patch.dict(os.environ, environment, clear=True), redirect_stderr(stderr):
            result = run()

        self.assertEqual(result, 2)
        self.assertIn("TWELVE_DATA_API_KEY", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()

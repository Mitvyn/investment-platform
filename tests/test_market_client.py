from __future__ import annotations

import io
import os
import sys
import unittest
from contextlib import redirect_stderr
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

from workers.market.__main__ import run
from workers.market.client import (
    MarketDataError,
    YFinanceBar,
    YFinanceClient,
    YFinanceLibraryProvider,
    YFinanceQuote,
    YFinanceSettings,
)


QUOTE = YFinanceQuote(
    symbol="RXRX",
    exchange="NASDAQ",
    currency="USD",
    market_timestamp=1784232000,
    close=5.42,
    previous_close=5.20,
    volume=1234567,
    is_market_open=False,
    source_url="https://finance.yahoo.com/quote/RXRX/history",
    canonical_payload={"symbol": "RXRX", "close": 5.42},
)

SERIES_QUOTE = YFinanceQuote(
    symbol="RXRX",
    exchange="NASDAQ",
    currency="USD",
    market_timestamp=1784232000,
    close=5.42,
    previous_close=5.20,
    volume=1234567,
    is_market_open=False,
    source_url="https://finance.yahoo.com/quote/RXRX/history",
    canonical_payload={"symbol": "RXRX", "close": 5.42, "series": "1y"},
    bars=(
        YFinanceBar("2026-07-15", 5.00, 5.30, 4.95, 5.20, 100, 0.0, 0.0),
        YFinanceBar("2026-07-16", 5.25, 5.50, 5.10, 5.42, 200, 0.0, 0.0),
    ),
)


class FakeProvider:
    def __init__(self, quote: YFinanceQuote) -> None:
        self.quote = quote
        self.calls: list[tuple[str, YFinanceSettings]] = []

    def fetch_quote(
        self,
        ticker: str,
        *,
        settings: YFinanceSettings,
    ) -> YFinanceQuote:
        self.calls.append((ticker, settings))
        return self.quote


class MarketClientTests(unittest.TestCase):
    def test_provider_correction_creates_new_snapshot_and_research_run(self) -> None:
        original = YFinanceClient(
            YFinanceSettings(), provider=FakeProvider(SERIES_QUOTE)
        ).fetch_quote(
            "RXRX",
            operator_id="11111111-1111-4111-8111-111111111111",
            security_id="22222222-2222-4222-8222-222222222222",
        )
        corrected_quote = YFinanceQuote(
            symbol=SERIES_QUOTE.symbol,
            exchange=SERIES_QUOTE.exchange,
            currency=SERIES_QUOTE.currency,
            market_timestamp=SERIES_QUOTE.market_timestamp,
            close=SERIES_QUOTE.close,
            previous_close=SERIES_QUOTE.previous_close,
            volume=SERIES_QUOTE.volume,
            is_market_open=SERIES_QUOTE.is_market_open,
            source_url=SERIES_QUOTE.source_url,
            canonical_payload={**SERIES_QUOTE.canonical_payload, "revision": 2},
            bars=SERIES_QUOTE.bars,
        )
        corrected = YFinanceClient(
            YFinanceSettings(), provider=FakeProvider(corrected_quote)
        ).fetch_quote(
            "RXRX",
            operator_id="11111111-1111-4111-8111-111111111111",
            security_id="22222222-2222-4222-8222-222222222222",
        )

        self.assertNotEqual(original.response_sha256, corrected.response_sha256)
        self.assertNotEqual(original.snapshot_id, corrected.snapshot_id)
        self.assertNotEqual(original.research_run_id, corrected.research_run_id)

    def test_rejects_duplicate_or_unsorted_history_sessions(self) -> None:
        invalid_quote = YFinanceQuote(
            symbol=SERIES_QUOTE.symbol,
            exchange=SERIES_QUOTE.exchange,
            currency=SERIES_QUOTE.currency,
            market_timestamp=SERIES_QUOTE.market_timestamp,
            close=SERIES_QUOTE.close,
            previous_close=SERIES_QUOTE.previous_close,
            volume=SERIES_QUOTE.volume,
            is_market_open=SERIES_QUOTE.is_market_open,
            source_url=SERIES_QUOTE.source_url,
            canonical_payload=SERIES_QUOTE.canonical_payload,
            bars=(SERIES_QUOTE.bars[1], SERIES_QUOTE.bars[1]),
        )
        client = YFinanceClient(
            YFinanceSettings(), provider=FakeProvider(invalid_quote)
        )

        with self.assertRaisesRegex(MarketDataError, "strictly ordered"):
            client.fetch_quote(
                "RXRX",
                operator_id="11111111-1111-4111-8111-111111111111",
                security_id="22222222-2222-4222-8222-222222222222",
            )

    def test_cli_accepts_arbitrary_ticker_and_stable_security_id(self) -> None:
        environment = {
            "IROS_OPERATOR_ID": "11111111-1111-4111-8111-111111111111",
            "IROS_SUPABASE_URL": "https://example.supabase.co",
            "IROS_SUPABASE_SECRET_KEY": "sb_secret_test",
        }
        fake_client = SimpleNamespace(
            fetch_quote=lambda *args, **kwargs: SimpleNamespace(as_dict=lambda: {})
        )
        fake_store = SimpleNamespace(persist=lambda snapshot: None)

        with (
            patch.dict(os.environ, environment, clear=True),
            patch("workers.market.__main__.YFinanceClient", return_value=fake_client),
            patch(
                "workers.market.__main__.SupabaseMarketStore", return_value=fake_store
            ),
            patch.object(
                fake_client, "fetch_quote", wraps=fake_client.fetch_quote
            ) as fetch,
        ):
            result = run(["CRSP", "22222222-2222-4222-8222-222222222222"])

        self.assertEqual(result, 0)
        fetch.assert_called_once_with(
            "CRSP",
            operator_id=environment["IROS_OPERATOR_ID"],
            security_id="22222222-2222-4222-8222-222222222222",
        )

    def test_library_boundary_excludes_active_session_partial_bar(self) -> None:
        class Rows:
            def __init__(self) -> None:
                self.index = [
                    datetime(2026, 7, 14, tzinfo=UTC),
                    datetime(2026, 7, 15, tzinfo=UTC),
                    datetime(2026, 7, 16, tzinfo=UTC),
                ]
                self.iloc = self
                self.rows = [
                    {"Open": 4.9, "High": 5.1, "Low": 4.8, "Close": 5.0, "Volume": 90},
                    {"Open": 5.0, "High": 5.3, "Low": 4.9, "Close": 5.2, "Volume": 100},
                    {"Open": 5.3, "High": 5.8, "Low": 5.2, "Close": 5.7, "Volume": 10},
                ]

            def __getitem__(self, index):
                return self.rows[index]

        class Instrument:
            def history(self, **kwargs):
                return Rows()

            def get_history_metadata(self):
                return {
                    "exchangeName": "NASDAQ",
                    "currency": "USD",
                    "marketState": "REGULAR",
                }

        fake_module = SimpleNamespace(
            __version__="1.5.1",
            Ticker=lambda ticker: Instrument(),
        )

        with patch.dict(sys.modules, {"yfinance": fake_module}):
            quote = YFinanceLibraryProvider().fetch_quote(
                "RXRX",
                settings=YFinanceSettings(),
            )

        self.assertTrue(quote.is_market_open)
        self.assertEqual(len(quote.bars), 2)
        self.assertEqual(quote.close, 5.2)
        self.assertEqual(quote.previous_close, 5.0)
        self.assertEqual(quote.market_timestamp, int(Rows().index[1].timestamp()))

    def test_market_snapshot_contains_content_addressed_daily_bars(self) -> None:
        snapshot = YFinanceClient(
            YFinanceSettings(),
            provider=FakeProvider(SERIES_QUOTE),
            clock=lambda: datetime(2026, 7, 17, 3, 0, tzinfo=UTC),
        ).fetch_quote(
            "RXRX",
            operator_id="11111111-1111-4111-8111-111111111111",
            security_id="22222222-2222-4222-8222-222222222222",
        )

        self.assertEqual(len(snapshot.bars), 2)
        self.assertEqual(snapshot.bars[-1].session_date, "2026-07-16")
        self.assertEqual(snapshot.bars[-1].close, snapshot.close)
        self.assertEqual(snapshot.bars[-1].snapshot_id, snapshot.snapshot_id)
        self.assertEqual(len(snapshot.bars[-1].bar_sha256), 64)

    def test_library_boundary_returns_unadjusted_daily_ohlcv_bars(self) -> None:
        class Rows:
            def __init__(self) -> None:
                self.index = [
                    datetime(2026, 7, 15, tzinfo=UTC),
                    datetime(2026, 7, 16, tzinfo=UTC),
                ]
                self.iloc = self
                self.rows = [
                    {
                        "Open": 5.00,
                        "High": 5.30,
                        "Low": 4.95,
                        "Close": 5.20,
                        "Volume": 100,
                        "Dividends": 0.0,
                        "Stock Splits": 0.0,
                    },
                    {
                        "Open": 5.25,
                        "High": 5.50,
                        "Low": 5.10,
                        "Close": 5.42,
                        "Volume": 200,
                        "Dividends": 0.0,
                        "Stock Splits": 0.0,
                    },
                ]

            def __getitem__(self, index):
                return self.rows[index]

        class Instrument:
            def history(self, **kwargs):
                return Rows()

            def get_history_metadata(self):
                return {
                    "exchangeName": "NASDAQ",
                    "currency": "USD",
                    "marketState": "CLOSED",
                }

        fake_module = SimpleNamespace(
            __version__="1.5.1",
            Ticker=lambda ticker: Instrument(),
        )

        with patch.dict(sys.modules, {"yfinance": fake_module}):
            quote = YFinanceLibraryProvider().fetch_quote(
                "RXRX",
                settings=YFinanceSettings(),
            )

        self.assertEqual(len(quote.bars), 2)
        self.assertEqual(quote.bars[-1].session_date, "2026-07-16")
        self.assertEqual(quote.bars[-1].open, 5.25)
        self.assertEqual(quote.bars[-1].high, 5.50)
        self.assertEqual(quote.bars[-1].low, 5.10)
        self.assertEqual(quote.bars[-1].close, 5.42)
        self.assertEqual(quote.bars[-1].volume, 200)

    def test_maps_personal_use_quote_without_api_key_or_adjustment(self) -> None:
        provider = FakeProvider(QUOTE)
        client = YFinanceClient(
            YFinanceSettings(),
            provider=provider,
            clock=lambda: datetime(2026, 7, 17, 3, 0, tzinfo=UTC),
        )

        snapshot = client.fetch_quote(
            "rxrx",
            operator_id="11111111-1111-4111-8111-111111111111",
        )

        requested_ticker, settings = provider.calls[0]
        self.assertEqual(requested_ticker, "RXRX")
        self.assertEqual(settings.interval, "1d")
        self.assertFalse(settings.auto_adjust)
        self.assertFalse(settings.prepost)
        self.assertTrue(settings.actions)
        self.assertFalse(settings.repair)
        self.assertEqual(snapshot.ticker, "RXRX")
        self.assertEqual(snapshot.provider, "yahoo_finance_via_yfinance")
        self.assertEqual(snapshot.close, 5.42)
        self.assertEqual(snapshot.volume, 1234567)
        self.assertFalse(snapshot.is_market_open)
        self.assertEqual(len(snapshot.response_sha256), 64)

    def test_library_boundary_forwards_unadjusted_daily_contract(self) -> None:
        calls = []

        class Rows:
            def __init__(self) -> None:
                self.index = [
                    datetime(2026, 7, 15, tzinfo=UTC),
                    datetime(2026, 7, 16, tzinfo=UTC),
                ]
                self.iloc = self
                self.rows = [
                    {
                        "Open": 5.00,
                        "High": 5.30,
                        "Low": 4.95,
                        "Close": 5.20,
                        "Volume": 100,
                    },
                    {
                        "Open": 5.25,
                        "High": 5.50,
                        "Low": 5.10,
                        "Close": 5.42,
                        "Volume": 200,
                    },
                ]

            def __getitem__(self, index):
                return self.rows[index]

        class Instrument:
            def history(self, **kwargs):
                calls.append(kwargs)
                return Rows()

            def get_history_metadata(self):
                return {
                    "exchangeName": "NASDAQ",
                    "currency": "USD",
                    "marketState": "CLOSED",
                }

        fake_module = SimpleNamespace(
            __version__="1.5.1",
            Ticker=lambda ticker: Instrument(),
        )

        with patch.dict(sys.modules, {"yfinance": fake_module}):
            quote = YFinanceLibraryProvider().fetch_quote(
                "RXRX",
                settings=YFinanceSettings(),
            )

        self.assertEqual(quote.close, 5.42)
        self.assertEqual(quote.previous_close, 5.20)
        self.assertEqual(calls[0]["interval"], "1d")
        self.assertFalse(calls[0]["auto_adjust"])
        self.assertFalse(calls[0]["prepost"])
        self.assertTrue(calls[0]["actions"])
        self.assertFalse(calls[0]["repair"])

    def test_rejects_quote_for_different_symbol(self) -> None:
        client = YFinanceClient(
            YFinanceSettings(),
            provider=FakeProvider(
                YFinanceQuote(
                    symbol="NOTRXRX",
                    exchange=QUOTE.exchange,
                    currency=QUOTE.currency,
                    market_timestamp=QUOTE.market_timestamp,
                    close=QUOTE.close,
                    previous_close=QUOTE.previous_close,
                    volume=QUOTE.volume,
                    is_market_open=QUOTE.is_market_open,
                    source_url=QUOTE.source_url,
                    canonical_payload=QUOTE.canonical_payload,
                )
            ),
        )

        with self.assertRaisesRegex(MarketDataError, "different symbol"):
            client.fetch_quote(
                "RXRX",
                operator_id="11111111-1111-4111-8111-111111111111",
            )

    def test_cli_requires_only_operator_and_supabase_configuration(self) -> None:
        environment = {
            "IROS_SUPABASE_URL": "https://example.supabase.co",
            "IROS_SUPABASE_SECRET_KEY": "sb_secret_test",
        }
        stderr = io.StringIO()
        with patch.dict(os.environ, environment, clear=True), redirect_stderr(stderr):
            result = run()

        self.assertEqual(result, 2)
        self.assertIn("IROS_OPERATOR_ID", stderr.getvalue())
        self.assertNotIn("API_KEY", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()

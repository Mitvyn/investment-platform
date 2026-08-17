from __future__ import annotations

import unittest
from datetime import date
from dataclasses import replace

from workers.market.client import YFinanceBar, YFinanceQuote, YFinanceSettings
from workers.quant_sources.providers import (
    MoomooHistoryBar,
    MoomooHistoryPayload,
    MoomooQuantSource,
    QuantSourceProviderError,
    YFinanceQuantSource,
)


SECURITY_ID = "3f1b0c2e-9d4a-4c7f-b1e2-8a5d6c7f0912"


class FakeYFinanceProvider:
    def fetch_quote(self, ticker: str, *, settings: YFinanceSettings) -> YFinanceQuote:
        return YFinanceQuote(
            symbol=ticker,
            exchange="NasdaqGS",
            currency="USD",
            market_timestamp=1_768_000_000,
            close=102.0,
            previous_close=101.0,
            volume=1200,
            is_market_open=False,
            source_url=f"https://finance.yahoo.com/quote/{ticker}/history",
            canonical_payload={"fixture": ticker, "revision": "2026-01-07"},
            bars=(
                YFinanceBar("2026-01-05", 100.0, 101.0, 99.0, 100.0, 1000, 0.0, 0.0),
                YFinanceBar("2026-01-06", 50.0, 51.0, 49.0, 50.0, 1100, 0.0, 2.0),
                YFinanceBar("2026-01-07", 51.0, 52.0, 50.0, 51.0, 1200, 0.0, 0.0),
            ),
        )


class FakeMoomooProvider:
    def fetch_daily_history(
        self, ticker: str, *, as_of_cutoff: date
    ) -> MoomooHistoryPayload:
        return MoomooHistoryPayload(
            symbol=ticker,
            source_revision="2026-01-07T00:00:00Z/rev-1",
            currency="USD",
            bars=(
                MoomooHistoryBar("2026-01-05", "100", "101", "99", "100", 1000),
                MoomooHistoryBar(
                    "2026-01-06", "50", "51", "49", "50", 1100, "2"
                ),
                MoomooHistoryBar("2026-01-07", "51", "52", "50", "51", 1200),
            ),
        )


class YFinanceQuantSourceTests(unittest.TestCase):
    def test_converts_existing_yfinance_history_into_quant_receipt(self) -> None:
        dataset = YFinanceQuantSource(
            YFinanceSettings(), provider=FakeYFinanceProvider()
        ).acquire(
            ticker="RXRX",
            security_id=SECURITY_ID,
            as_of_cutoff=date(2026, 1, 7),
            currency="USD",
        )

        self.assertEqual(dataset.security_id, SECURITY_ID)
        self.assertEqual(dataset.series.source, "yahoo_finance_via_yfinance")
        self.assertEqual(len(dataset.series.bars), 3)
        self.assertEqual(len(dataset.corporate_actions.actions), 1)
        self.assertEqual(dataset.corporate_actions.actions[0].new_shares, 2)
        self.assertEqual(dataset.corporate_actions.actions[0].old_shares, 1)

    def test_rejects_post_cutoff_history_instead_of_truncating(self) -> None:
        with self.assertRaisesRegex(QuantSourceProviderError, "after the cutoff"):
            YFinanceQuantSource(
                YFinanceSettings(), provider=FakeYFinanceProvider()
            ).acquire(
                ticker="RXRX",
                security_id=SECURITY_ID,
                as_of_cutoff=date(2026, 1, 6),
                currency="USD",
            )

    def test_rejects_missing_volume(self) -> None:
        class MissingVolume(FakeYFinanceProvider):
            def fetch_quote(
                self, ticker: str, *, settings: YFinanceSettings
            ) -> YFinanceQuote:
                quote = super().fetch_quote(ticker, settings=settings)
                return replace(
                    quote,
                    bars=(
                        YFinanceBar(
                            "2026-01-05",
                            100.0,
                            101.0,
                            99.0,
                            100.0,
                            None,
                            0.0,
                            0.0,
                        ),
                    ),
                )

        with self.assertRaisesRegex(QuantSourceProviderError, "no volume"):
            YFinanceQuantSource(
                YFinanceSettings(), provider=MissingVolume()
            ).acquire(
                ticker="RXRX",
                security_id=SECURITY_ID,
                as_of_cutoff=date(2026, 1, 7),
                currency="USD",
            )


class MoomooQuantSourceTests(unittest.TestCase):
    def test_converts_injected_moomoo_history_into_quant_receipt(self) -> None:
        dataset = MoomooQuantSource(FakeMoomooProvider()).acquire(
            ticker="US.RXRX",
            security_id=SECURITY_ID,
            as_of_cutoff=date(2026, 1, 7),
            currency="USD",
        )

        self.assertEqual(dataset.security_id, SECURITY_ID)
        self.assertEqual(dataset.series.source, "moomoo_openapi")
        self.assertEqual(len(dataset.series.bars), 3)
        self.assertEqual(len(dataset.corporate_actions.actions), 1)

    def test_rejects_currency_mismatch(self) -> None:
        class Hkd(FakeMoomooProvider):
            def fetch_daily_history(
                self, ticker: str, *, as_of_cutoff: date
            ) -> MoomooHistoryPayload:
                payload = super().fetch_daily_history(
                    ticker, as_of_cutoff=as_of_cutoff
                )
                return MoomooHistoryPayload(
                    symbol=payload.symbol,
                    source_revision=payload.source_revision,
                    currency="HKD",
                    bars=payload.bars,
                )

        with self.assertRaisesRegex(QuantSourceProviderError, "currency"):
            MoomooQuantSource(Hkd()).acquire(
                ticker="US.RXRX",
                security_id=SECURITY_ID,
                as_of_cutoff=date(2026, 1, 7),
                currency="USD",
            )

    def test_rejects_moving_source_revision(self) -> None:
        class Moving(FakeMoomooProvider):
            def fetch_daily_history(
                self, ticker: str, *, as_of_cutoff: date
            ) -> MoomooHistoryPayload:
                payload = super().fetch_daily_history(
                    ticker, as_of_cutoff=as_of_cutoff
                )
                return MoomooHistoryPayload(
                    symbol=payload.symbol,
                    source_revision="latest",
                    currency=payload.currency,
                    bars=payload.bars,
                )

        with self.assertRaisesRegex(QuantSourceProviderError, "moving target"):
            MoomooQuantSource(Moving()).acquire(
                ticker="US.RXRX",
                security_id=SECURITY_ID,
                as_of_cutoff=date(2026, 1, 7),
                currency="USD",
            )

    def test_rejects_a_mismatched_symbol(self) -> None:
        class WrongSymbol(FakeMoomooProvider):
            def fetch_daily_history(
                self, ticker: str, *, as_of_cutoff: date
            ) -> MoomooHistoryPayload:
                payload = super().fetch_daily_history(
                    ticker, as_of_cutoff=as_of_cutoff
                )
                return replace(payload, symbol="US.OTHER")

        with self.assertRaisesRegex(QuantSourceProviderError, "different symbol"):
            MoomooQuantSource(WrongSymbol()).acquire(
                ticker="US.RXRX",
                security_id=SECURITY_ID,
                as_of_cutoff=date(2026, 1, 7),
                currency="USD",
            )


if __name__ == "__main__":
    unittest.main()

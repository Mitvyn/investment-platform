from __future__ import annotations

import unittest
from datetime import date, datetime
from decimal import Decimal, localcontext

from investment_research_os.quant import BarSeries, OhlcvBar, QuantContractError

SECURITY_ID = "3f1b0c2e-9d4a-4c7f-b1e2-8a5d6c7f0912"


def bar(
    session: str,
    *,
    open_: str = "100",
    high: str = "101",
    low: str = "99",
    close: str = "100.5",
    volume: int = 1_000,
) -> OhlcvBar:
    return OhlcvBar(
        session=date.fromisoformat(session),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=volume,
    )


def series(*bars: OhlcvBar, source: str = "fixture") -> BarSeries:
    return BarSeries(
        security_id=SECURITY_ID,
        currency="USD",
        interval="1d",
        price_basis="unadjusted",
        source=source,
        bars=bars,
    )


class OhlcvBarTests(unittest.TestCase):
    def test_rejects_datetime_for_daily_session(self) -> None:
        with self.assertRaisesRegex(QuantContractError, "session must be a date"):
            OhlcvBar(
                session=datetime(2026, 1, 5, 16, 0),  # type: ignore[arg-type]
                open="100",
                high="101",
                low="99",
                close="100",
                volume=1,
            )

    def test_accepts_decimal_strings_and_integers(self) -> None:
        subject = OhlcvBar(
            session=date(2026, 1, 5),
            open="100.25",
            high="101",
            low=99,
            close=Decimal("100.75"),
            volume=42,
        )
        self.assertEqual(subject.open, Decimal("100.25"))
        self.assertEqual(subject.low, Decimal(99))

    def test_rejects_float_prices(self) -> None:
        with self.assertRaises(QuantContractError) as caught:
            OhlcvBar(
                session=date(2026, 1, 5),
                open=100.25,
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100"),
                volume=1,
            )
        self.assertIn("float", str(caught.exception))

    def test_rejects_non_positive_price(self) -> None:
        with self.assertRaises(QuantContractError):
            OhlcvBar(
                session=date(2026, 1, 5),
                open=Decimal("0"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100"),
                volume=1,
            )

    def test_rejects_price_below_engine_price_quantum(self) -> None:
        with self.assertRaisesRegex(QuantContractError, "price quantum"):
            OhlcvBar(
                session=date(2026, 1, 5),
                open="0.0000004",
                high="0.0000004",
                low="0.0000004",
                close="0.0000004",
                volume=1,
            )

    def test_rejects_high_below_other_prices(self) -> None:
        with self.assertRaises(QuantContractError) as caught:
            OhlcvBar(
                session=date(2026, 1, 5),
                open=Decimal("100"),
                high=Decimal("99"),
                low=Decimal("98"),
                close=Decimal("100"),
                volume=1,
            )
        self.assertIn("high", str(caught.exception))

    def test_rejects_low_above_other_prices(self) -> None:
        with self.assertRaises(QuantContractError) as caught:
            OhlcvBar(
                session=date(2026, 1, 5),
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("100.5"),
                close=Decimal("100"),
                volume=1,
            )
        self.assertIn("low", str(caught.exception))

    def test_rejects_negative_volume(self) -> None:
        with self.assertRaises(QuantContractError):
            OhlcvBar(
                session=date(2026, 1, 5),
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100"),
                volume=-1,
            )


class BarSeriesTests(unittest.TestCase):
    def test_requires_strictly_increasing_sessions(self) -> None:
        with self.assertRaises(QuantContractError) as caught:
            series(bar("2026-01-06"), bar("2026-01-05"))
        self.assertIn("strictly increasing", str(caught.exception))

    def test_rejects_duplicate_sessions(self) -> None:
        with self.assertRaises(QuantContractError):
            series(bar("2026-01-05"), bar("2026-01-05"))

    def test_requires_at_least_two_sessions(self) -> None:
        with self.assertRaises(QuantContractError):
            series(bar("2026-01-05"))

    def test_rejects_non_canonical_security_id(self) -> None:
        with self.assertRaises(QuantContractError) as caught:
            BarSeries(
                security_id="AAPL",
                currency="USD",
                interval="1d",
                price_basis="unadjusted",
                source="fixture",
                bars=(bar("2026-01-05"), bar("2026-01-06")),
            )
        self.assertIn("canonical security UUID", str(caught.exception))

    def test_rejects_noncanonical_spellings_of_same_security_uuid(self) -> None:
        for security_id in (
            SECURITY_ID.upper(),
            SECURITY_ID.replace("-", ""),
            f"{{{SECURITY_ID}}}",
        ):
            with self.subTest(security_id=security_id):
                with self.assertRaises(QuantContractError):
                    BarSeries(
                        security_id=security_id,
                        currency="USD",
                        interval="1d",
                        price_basis="unadjusted",
                        source="fixture",
                        bars=(bar("2026-01-05"), bar("2026-01-06")),
                    )

    def test_rejects_unknown_currency_and_interval(self) -> None:
        with self.assertRaises(QuantContractError):
            BarSeries(
                security_id=SECURITY_ID,
                currency="usd",
                interval="1d",
                price_basis="unadjusted",
                source="fixture",
                bars=(bar("2026-01-05"), bar("2026-01-06")),
            )

    def test_rejects_adjusted_prices_to_prevent_split_double_counting(self) -> None:
        with self.assertRaisesRegex(QuantContractError, "unadjusted"):
            BarSeries(
                security_id=SECURITY_ID,
                currency="USD",
                interval="1d",
                price_basis="split_adjusted",  # type: ignore[arg-type]
                source="fixture",
                bars=(bar("2026-01-05"), bar("2026-01-06")),
            )
        with self.assertRaises(QuantContractError):
            BarSeries(
                security_id=SECURITY_ID,
                currency="USD",
                interval="5m",  # type: ignore[arg-type]
                price_basis="unadjusted",
                source="fixture",
                bars=(bar("2026-01-05"), bar("2026-01-06")),
            )

    def test_from_rows_accepts_provider_shaped_rows_without_a_provider(self) -> None:
        subject = BarSeries.from_rows(
            security_id=SECURITY_ID,
            currency="USD",
            price_basis="unadjusted",
            source="csv-import",
            rows=[
                {
                    "session": "2026-01-05",
                    "open": "100",
                    "high": "101",
                    "low": "99",
                    "close": "100.5",
                    "volume": 10,
                },
                {
                    "session": date(2026, 1, 6),
                    "open": "100.5",
                    "high": "102",
                    "low": "100",
                    "close": "101",
                    "volume": 11,
                },
            ],
        )
        self.assertEqual(len(subject.bars), 2)
        self.assertEqual(subject.bars[0].session, date(2026, 1, 5))

    def test_from_rows_reports_missing_fields(self) -> None:
        with self.assertRaises(QuantContractError) as caught:
            BarSeries.from_rows(
                security_id=SECURITY_ID,
                currency="USD",
                price_basis="unadjusted",
                source="csv-import",
                rows=[{"session": "2026-01-05", "open": "100"}],
            )
        self.assertIn("close", str(caught.exception))


class ContentHashTests(unittest.TestCase):
    def test_hash_does_not_depend_on_ambient_decimal_precision(self) -> None:
        subject = series(
            bar(
                "2026-01-05",
                open_="1.23456789",
                high="1.3",
                low="1.2",
                close="1.25",
            ),
            bar(
                "2026-01-06",
                open_="1.23456789",
                high="1.3",
                low="1.2",
                close="1.25",
            ),
        )
        with localcontext() as context:
            context.prec = 6
            low_precision_hash = subject.content_sha256
        with localcontext() as context:
            context.prec = 28
            normal_precision_hash = subject.content_sha256

        self.assertEqual(low_precision_hash, normal_precision_hash)

    def test_hash_is_stable_across_equal_decimal_scales(self) -> None:
        left = series(
            bar("2026-01-05", close="100.50"),
            bar("2026-01-06", close="101.00"),
        )
        right = series(
            bar("2026-01-05", close="100.5"),
            bar("2026-01-06", close="101"),
        )
        self.assertEqual(left.content_sha256, right.content_sha256)

    def test_hash_changes_when_any_price_changes(self) -> None:
        left = series(bar("2026-01-05"), bar("2026-01-06", close="101"))
        right = series(bar("2026-01-05"), bar("2026-01-06", high="102", close="101.01"))
        self.assertNotEqual(left.content_sha256, right.content_sha256)

    def test_hash_is_repeatable(self) -> None:
        subject = series(bar("2026-01-05"), bar("2026-01-06"))
        self.assertEqual(subject.content_sha256, subject.content_sha256)
        self.assertEqual(len(subject.content_sha256), 64)


if __name__ == "__main__":
    unittest.main()

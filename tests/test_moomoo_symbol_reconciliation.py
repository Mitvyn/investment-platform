from __future__ import annotations

import unittest
from dataclasses import dataclass

from workers.portfolio.symbols import (
    MoomooSymbolReconciliationError,
    reconcile_moomoo_symbol,
)


@dataclass(frozen=True)
class Candidate:
    security_id: str
    ticker: str
    primary_listing_exchange: str


class MoomooSymbolReconciliationTests(unittest.TestCase):
    def test_reconciles_us_symbol_to_one_canonical_security(self) -> None:
        result = reconcile_moomoo_symbol(
            "US.RXRX",
            candidates=(
                Candidate(
                    security_id="11111111-1111-4111-8111-111111111111",
                    ticker="RXRX",
                    primary_listing_exchange="Nasdaq",
                ),
            ),
        )

        self.assertEqual(result.mapping_state, "mapped")
        self.assertEqual(result.provider_market, "US")
        self.assertEqual(result.provider_symbol, "US.RXRX")
        self.assertEqual(result.canonical_ticker, "RXRX")
        self.assertEqual(result.security_id, "11111111-1111-4111-8111-111111111111")

    def test_fails_closed_for_non_us_or_malformed_symbols(self) -> None:
        for symbol in ("HK.00700", "RXRX", "US.", "US.RX RX"):
            with self.subTest(symbol=symbol):
                with self.assertRaisesRegex(
                    MoomooSymbolReconciliationError, "unsupported Moomoo symbol"
                ):
                    reconcile_moomoo_symbol(symbol, candidates=())

    def test_preserves_unmatched_symbol_as_visible_unmapped_result(self) -> None:
        result = reconcile_moomoo_symbol("US.RXRX", candidates=())

        self.assertEqual(result.mapping_state, "unmapped")
        self.assertEqual(result.provider_market, "US")
        self.assertEqual(result.provider_symbol, "US.RXRX")
        self.assertEqual(result.canonical_ticker, "RXRX")
        self.assertIsNone(result.security_id)
        self.assertIsNone(result.primary_listing_exchange)

    def test_preserves_ambiguous_symbol_without_guessing(self) -> None:
        candidate = Candidate(
            security_id="11111111-1111-4111-8111-111111111111",
            ticker="RXRX",
            primary_listing_exchange="Nasdaq",
        )
        result = reconcile_moomoo_symbol(
            "US.RXRX",
            candidates=(candidate, candidate),
        )

        self.assertEqual(result.mapping_state, "ambiguous")
        self.assertEqual(result.provider_symbol, "US.RXRX")
        self.assertEqual(result.canonical_ticker, "RXRX")
        self.assertIsNone(result.security_id)
        self.assertIsNone(result.primary_listing_exchange)

    def test_does_not_guess_from_company_name_or_exchange(self) -> None:
        result = reconcile_moomoo_symbol(
            "US.RXRX",
            candidates=(
                Candidate(
                    security_id="22222222-2222-4222-8222-222222222222",
                    ticker="OTHER",
                    primary_listing_exchange="Nasdaq",
                ),
            ),
        )

        self.assertEqual(result.mapping_state, "unmapped")
        self.assertIsNone(result.security_id)

    def test_rejects_invalid_canonical_identity_on_mapped_path(self) -> None:
        cases = (
            (
                Candidate(
                    security_id="not-a-uuid",
                    ticker="RXRX",
                    primary_listing_exchange="Nasdaq",
                ),
                "canonical security ID is invalid",
            ),
            (
                Candidate(
                    security_id="11111111-1111-4111-8111-111111111111",
                    ticker="RXRX",
                    primary_listing_exchange=" ",
                ),
                "canonical listing exchange is unavailable",
            ),
        )
        for candidate, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(
                    MoomooSymbolReconciliationError,
                    message,
                ):
                    reconcile_moomoo_symbol("US.RXRX", candidates=(candidate,))


if __name__ == "__main__":
    unittest.main()

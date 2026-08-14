from __future__ import annotations

import unittest

from workers.portfolio.quote_limits import (
    MoomooQuoteLimitError,
    MoomooQuoteSubscriptionBook,
    bounded_retry_delay_seconds,
)


class MoomooQuoteSubscriptionBookTests(unittest.TestCase):
    def test_normalizes_and_batches_only_changed_symbols(self) -> None:
        book = MoomooQuoteSubscriptionBook(app_symbol_limit=5)

        first = book.replace(["US.RXRX", "us.ganx", "US.RXRX"])
        repeated = book.replace(["US.GANX", "US.RXRX"])
        switched = book.replace(["US.RXRX", "US.SLS"])

        self.assertEqual(first.subscribe, ("US.GANX", "US.RXRX"))
        self.assertEqual(first.unsubscribe, ())
        self.assertEqual(repeated.subscribe, ())
        self.assertEqual(repeated.unsubscribe, ())
        self.assertEqual(switched.subscribe, ("US.SLS",))
        self.assertEqual(switched.unsubscribe, ("US.GANX",))

    def test_rejects_invalid_or_excess_symbols_before_transport(self) -> None:
        book = MoomooQuoteSubscriptionBook(app_symbol_limit=2)

        with self.assertRaisesRegex(MoomooQuoteLimitError, "symbol is invalid"):
            book.replace(["RXRX"])
        with self.assertRaisesRegex(MoomooQuoteLimitError, "app symbol limit"):
            book.replace(["US.RXRX", "US.GANX", "US.SLS"])

    def test_internal_wire_batch_safety_limit_is_bounded(self) -> None:
        symbols = [f"US.T{i:03d}" for i in range(400)]
        book = MoomooQuoteSubscriptionBook(app_symbol_limit=400)

        mutation = book.replace(symbols)

        self.assertEqual(len(mutation.subscribe), 400)
        with self.assertRaisesRegex(MoomooQuoteLimitError, "app symbol limit"):
            book.replace([*symbols, "US.EXTRA"])


class MoomooQuoteBackoffTests(unittest.TestCase):
    def test_uses_retry_after_then_bounded_exponential_delay(self) -> None:
        self.assertEqual(bounded_retry_delay_seconds(0), 1)
        self.assertEqual(bounded_retry_delay_seconds(1), 2)
        self.assertEqual(bounded_retry_delay_seconds(20), 60)
        self.assertEqual(
            bounded_retry_delay_seconds(4, retry_after_seconds=17),
            17,
        )
        self.assertEqual(
            bounded_retry_delay_seconds(4, retry_after_seconds=600),
            60,
        )

    def test_rejects_invalid_retry_inputs(self) -> None:
        with self.assertRaises(ValueError):
            bounded_retry_delay_seconds(-1)
        with self.assertRaises(ValueError):
            bounded_retry_delay_seconds(0, retry_after_seconds=-1)


if __name__ == "__main__":
    unittest.main()

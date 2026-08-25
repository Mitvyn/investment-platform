from __future__ import annotations

import unittest
from datetime import datetime, timezone

from workers.moomoo_mcp.market_evidence import (
    MARKET_QUOTE_TOOL_NAME,
    MarketEvidenceError,
    build_market_quote_evidence,
)

RETRIEVED_AT = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)


class BuildMarketQuoteEvidenceTests(unittest.TestCase):
    def test_builds_evidence_from_official_quote_list_contract(self) -> None:
        evidence = build_market_quote_evidence(
            {
                "isError": False,
                "structuredContent": {
                    "quote_list": [
                        {
                            "code": "US.FRVO",
                            "data_time": 1_777_000_000_000,
                            "last_price": 8.25,
                            "name": "FRVO",
                            "prev_close_price": 8.1,
                            "sec_status": "NORMAL",
                            "suspension": False,
                            "volume": 1234,
                        }
                    ]
                },
            },
            ticker="US.FRVO",
            security_id="11111111-1111-1111-1111-111111111111",
            retrieved_at=RETRIEVED_AT,
        )

        self.assertEqual(evidence.summary["code"], "US.FRVO")
        self.assertEqual(evidence.summary["last_price"], "8.25")
        self.assertIsNotNone(evidence.provider_reported_at)

    def test_official_quote_list_must_contain_exactly_one_requested_quote(self) -> None:
        for quote_list in ([], [{"code": "US.FRVO"}, {"code": "US.AAPL"}]):
            with self.assertRaises(MarketEvidenceError):
                build_market_quote_evidence(
                    {
                        "isError": False,
                        "structuredContent": {"quote_list": quote_list},
                    },
                    ticker="US.FRVO",
                    security_id="11111111-1111-1111-1111-111111111111",
                    retrieved_at=RETRIEVED_AT,
                )

    def test_builds_typed_evidence_from_structured_content(self) -> None:
        evidence = build_market_quote_evidence(
            {
                "isError": False,
                "structuredContent": {
                    "code": "US.AAPL",
                    "time": 1_700_000_000,
                    "last_price": "150.25",
                },
            },
            ticker="US.AAPL",
            security_id="11111111-1111-1111-1111-111111111111",
            retrieved_at=RETRIEVED_AT,
        )
        self.assertEqual(evidence.ticker, "US.AAPL")
        self.assertEqual(evidence.tool_name, MARKET_QUOTE_TOOL_NAME)
        self.assertEqual(evidence.source, "moomoo_mcp")
        self.assertFalse(evidence.is_error)
        self.assertIsNone(evidence.failure_reason)
        self.assertEqual(evidence.summary["code"], "US.AAPL")
        self.assertIn(evidence.freshness, {"fresh", "stale"})
        self.assertIsNotNone(evidence.provider_reported_at)

    def test_accepts_one_outer_object_around_official_quote_wrapper(self) -> None:
        evidence = build_market_quote_evidence(
            {
                "isError": False,
                "structuredContent": {
                    "data": {
                        "quote_list": [
                            {
                                "code": "US.FRVO",
                                "data_time": 1_777_000_000_000,
                                "last_price": 27.9,
                            }
                        ]
                    }
                },
            },
            ticker="US.FRVO",
            security_id="11111111-1111-1111-1111-111111111111",
            retrieved_at=RETRIEVED_AT,
        )

        self.assertEqual(evidence.ticker, "US.FRVO")

    def test_rejects_unverified_deep_nested_objects(self) -> None:
        with self.assertRaises(MarketEvidenceError):
            build_market_quote_evidence(
                {
                    "isError": False,
                    "structuredContent": {
                        "result": {
                            "data": {
                                "quote_list": [
                                    {
                                        "code": "US.FRVO",
                                        "data_time": 1_777_000_000_000,
                                        "last_price": 27.9,
                                    }
                                ]
                            }
                        }
                    },
                },
                ticker="US.FRVO",
                security_id="11111111-1111-1111-1111-111111111111",
                retrieved_at=RETRIEVED_AT,
            )

    def test_missing_provider_timestamp_fails_closed(self) -> None:
        with self.assertRaises(MarketEvidenceError) as context:
            build_market_quote_evidence(
                {
                    "isError": False,
                    "structuredContent": {"code": "US.AAPL", "last_price": "150.25"},
                },
                ticker="US.AAPL",
                security_id="11111111-1111-1111-1111-111111111111",
                retrieved_at=RETRIEVED_AT,
            )
        self.assertEqual(context.exception.code, "quote_result_invalid")

    def test_missing_price_field_fails_closed(self) -> None:
        with self.assertRaises(MarketEvidenceError):
            build_market_quote_evidence(
                {
                    "isError": False,
                    "structuredContent": {"code": "US.AAPL", "time": 1_700_000_000},
                },
                ticker="US.AAPL",
                security_id="11111111-1111-1111-1111-111111111111",
                retrieved_at=RETRIEVED_AT,
            )

    def test_non_finite_price_field_fails_closed(self) -> None:
        for bad_price in ("nan", "inf", "-inf", "not-a-number"):
            with self.assertRaises(MarketEvidenceError):
                build_market_quote_evidence(
                    {
                        "isError": False,
                        "structuredContent": {
                            "code": "US.AAPL",
                            "time": 1_700_000_000,
                            "last_price": bad_price,
                        },
                    },
                    ticker="US.AAPL",
                    security_id="11111111-1111-1111-1111-111111111111",
                    retrieved_at=RETRIEVED_AT,
                )

    def test_negative_price_field_fails_closed(self) -> None:
        with self.assertRaises(MarketEvidenceError):
            build_market_quote_evidence(
                {
                    "isError": False,
                    "structuredContent": {
                        "code": "US.AAPL",
                        "time": 1_700_000_000,
                        "last_price": "-1.00",
                    },
                },
                ticker="US.AAPL",
                security_id="11111111-1111-1111-1111-111111111111",
                retrieved_at=RETRIEVED_AT,
            )

    def test_stale_provider_timestamp_is_labeled_stale_not_fresh(self) -> None:
        evidence = build_market_quote_evidence(
            {
                "isError": False,
                "structuredContent": {
                    "code": "US.AAPL",
                    "time": 1_700_000_000,
                    "last_price": "150.25",
                },
            },
            ticker="US.AAPL",
            security_id="11111111-1111-1111-1111-111111111111",
            retrieved_at=datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(evidence.freshness, "stale")
        self.assertFalse(evidence.is_error)

    def test_provider_error_result_fails_closed_with_reason(self) -> None:
        evidence = build_market_quote_evidence(
            {"isError": True, "structuredContent": {"code": "US.AAPL"}},
            ticker="US.AAPL",
            security_id="11111111-1111-1111-1111-111111111111",
            retrieved_at=RETRIEVED_AT,
        )
        self.assertTrue(evidence.is_error)
        self.assertEqual(evidence.failure_reason, "provider_reported_error")
        self.assertEqual(evidence.summary, {})
        self.assertEqual(evidence.freshness, "unknown")

    def test_malformed_result_raises(self) -> None:
        with self.assertRaises(MarketEvidenceError):
            build_market_quote_evidence(
                "not-a-mapping",
                ticker="US.AAPL",
                security_id="11111111-1111-1111-1111-111111111111",
                retrieved_at=RETRIEVED_AT,
            )

    def test_ticker_mismatch_in_response_fails_closed(self) -> None:
        with self.assertRaises(MarketEvidenceError):
            build_market_quote_evidence(
                {
                    "isError": False,
                    "structuredContent": {"code": "US.MSFT", "time": 1_700_000_000},
                },
                ticker="US.AAPL",
                security_id="11111111-1111-1111-1111-111111111111",
                retrieved_at=RETRIEVED_AT,
            )

    def test_oversized_summary_field_is_truncated_not_dropped(self) -> None:
        evidence = build_market_quote_evidence(
            {
                "isError": False,
                "structuredContent": {
                    "code": "US.AAPL",
                    "time": 1_700_000_000,
                    "last_price": "150.25",
                    "security_status": "x" * 5_000,
                },
            },
            ticker="US.AAPL",
            security_id="11111111-1111-1111-1111-111111111111",
            retrieved_at=RETRIEVED_AT,
        )
        self.assertLessEqual(len(evidence.summary["security_status"]), 200)

    def test_unrecognized_field_is_rejected_as_schema_drift(self) -> None:
        with self.assertRaises(MarketEvidenceError):
            build_market_quote_evidence(
                {
                    "isError": False,
                    "structuredContent": {
                        "code": "US.AAPL",
                        "time": 1_700_000_000,
                        "last_price": "150.25",
                        "totally_new_undocumented_field": "1",
                    },
                },
                ticker="US.AAPL",
                security_id="11111111-1111-1111-1111-111111111111",
                retrieved_at=RETRIEVED_AT,
            )

    def test_invalid_ticker_is_rejected_before_use(self) -> None:
        with self.assertRaises(MarketEvidenceError):
            build_market_quote_evidence(
                {"isError": False, "structuredContent": {"code": "not-a-ticker"}},
                ticker="not-a-ticker",
                security_id="11111111-1111-1111-1111-111111111111",
                retrieved_at=RETRIEVED_AT,
            )


if __name__ == "__main__":
    unittest.main()

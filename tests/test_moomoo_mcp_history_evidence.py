from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from workers.moomoo_mcp.history_evidence import (
    HistoryEvidenceError,
    build_daily_history_arguments,
    build_market_history_evidence,
)


class MoomooHistoryEvidenceTests(unittest.TestCase):
    def test_builds_bounded_official_daily_history_arguments(self) -> None:
        self.assertEqual(
            build_daily_history_arguments(
                ticker="US.FRVO",
                start=date(2026, 8, 1),
                end=date(2026, 8, 21),
                max_bars=50,
            ),
            {
                "autype": 1,
                "end": "2026-08-21",
                "extended_time": 0,
                "ktype": 2,
                "num": 50,
                "start": "2026-08-01",
                "symbol": "US.FRVO",
            },
        )

    def test_rejects_invalid_or_unbounded_history_request(self) -> None:
        for ticker, start, end, max_bars in (
            ("FRVO", date(2026, 8, 1), date(2026, 8, 21), 50),
            ("US.FRVO", date(2026, 8, 22), date(2026, 8, 21), 50),
            ("US.FRVO", date(2026, 8, 1), date(2026, 8, 21), 371),
        ):
            with self.assertRaises(HistoryEvidenceError):
                build_daily_history_arguments(
                    ticker=ticker, start=start, end=end, max_bars=max_bars
                )

    def test_normalizes_official_kline_list_and_preserves_source_time(self) -> None:
        evidence = build_market_history_evidence(
            {
                "isError": False,
                "structuredContent": {
                    "kline_list": [
                        {
                            "changeRate": 1.25,
                            "close": 8.5,
                            "date": 20260821,
                            "high": 8.75,
                            "lastClose": 8.4,
                            "low": 8.1,
                            "open": 8.2,
                            "timeKey": 1_777_000_000_000,
                            "timeZone": -240,
                            "turnover": 100_000,
                            "turnoverRate": 0.5,
                            "volume": 12_000,
                        }
                    ]
                },
            },
            ticker="US.FRVO",
            security_id="11111111-1111-1111-1111-111111111111",
            retrieved_at=datetime(2026, 8, 21, 23, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(evidence.bar_count, 1)
        self.assertEqual(evidence.bars[0]["close"], "8.5")
        self.assertEqual(evidence.bars[0]["date"], "20260821")
        self.assertEqual(evidence.tool_name, "quote_history_kline")

    def test_accepts_one_outer_object_around_official_history_wrapper(self) -> None:
        evidence = build_market_history_evidence(
            {
                "isError": False,
                "structuredContent": {
                    "data": {
                        "kline_list": [
                            {
                                "close": 8.5,
                                "high": 8.75,
                                "low": 8.1,
                                "open": 8.2,
                                "timeKey": 1_777_000_000_000,
                            }
                        ]
                    }
                },
            },
            ticker="US.FRVO",
            security_id="11111111-1111-1111-1111-111111111111",
            retrieved_at=datetime(2026, 8, 21, tzinfo=timezone.utc),
        )

        self.assertEqual(evidence.bar_count, 1)

    def test_normalizes_published_rest_history_field_names(self) -> None:
        evidence = build_market_history_evidence(
            {
                "isError": False,
                "structuredContent": {
                    "kline_list": [
                        {
                            "change_rate": 1.2,
                            "close": 28.0,
                            "date": 20260821,
                            "high": 29.0,
                            "last_close": 27.0,
                            "low": 26.0,
                            "name": "Fervo Energy",
                            "open": 27.0,
                            "pe_ratio": 0,
                            "time_key": 1787260800000,
                            "time_zone": -240,
                            "turnover": 1000,
                            "turnover_rate": 0.5,
                            "volume": 100,
                        }
                    ]
                },
            },
            ticker="US.FRVO",
            security_id="11111111-1111-1111-1111-111111111111",
            retrieved_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
        )

        self.assertEqual(evidence.bar_count, 1)
        self.assertEqual(evidence.bars[0]["timeKey"], "1787260800000")

    def test_fails_closed_on_unknown_field_bad_price_or_wrong_envelope(self) -> None:
        base = {
            "changeRate": 1.25,
            "close": 8.5,
            "date": 20260821,
            "high": 8.75,
            "lastClose": 8.4,
            "low": 8.1,
            "open": 8.2,
            "timeKey": 1_777_000_000_000,
            "timeZone": -240,
            "turnover": 100_000,
            "turnoverRate": 0.5,
            "volume": 12_000,
        }
        bad_rows = ({**base, "unknown": 1}, {**base, "close": "nan"})
        for row in bad_rows:
            with self.assertRaises(HistoryEvidenceError):
                build_market_history_evidence(
                    {
                        "isError": False,
                        "structuredContent": {"kline_list": [row]},
                    },
                    ticker="US.FRVO",
                    security_id="11111111-1111-1111-1111-111111111111",
                    retrieved_at=datetime.now(timezone.utc),
                )
        with self.assertRaises(HistoryEvidenceError) as context:
            build_market_history_evidence(
                {"isError": False, "structuredContent": {"bars": [base]}},
                ticker="US.FRVO",
                security_id="11111111-1111-1111-1111-111111111111",
                retrieved_at=datetime.now(timezone.utc),
            )
        self.assertEqual(context.exception.code, "history_envelope_invalid")


if __name__ == "__main__":
    unittest.main()

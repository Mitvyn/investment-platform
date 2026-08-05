from __future__ import annotations

import unittest
from datetime import UTC, date, datetime

from investment_research_os.valuation_snapshots.market_calendar import (
    PACKAGED_US_EQUITIES_CALENDAR_VERSION,
    load_packaged_us_equities_calendar,
)
from investment_research_os.valuation_snapshots import ValuationSnapshotError


class PackagedUsEquitiesMarketCalendarTests(unittest.TestCase):
    def test_supported_exchanges_share_holiday_and_early_close_schedule(self) -> None:
        calendar = load_packaged_us_equities_calendar()

        for exchange in ("NASDAQ", "NYSE", "NYSE AMERICAN"):
            before_early_close = calendar.latest_completed_session(
                exchange,
                datetime(2026, 11, 27, 17, 59, tzinfo=UTC),
            )
            at_early_close = calendar.latest_completed_session(
                exchange,
                datetime(2026, 11, 27, 18, 0, tzinfo=UTC),
            )

            self.assertEqual(before_early_close.session_date, date(2026, 11, 25))
            self.assertEqual(at_early_close.session_date, date(2026, 11, 27))
            self.assertTrue(at_early_close.early_close)
            self.assertEqual(
                at_early_close.calendar_version,
                PACKAGED_US_EQUITIES_CALENDAR_VERSION,
            )

    def test_regular_session_uses_new_york_daylight_saving_time(self) -> None:
        calendar = load_packaged_us_equities_calendar()

        session = calendar.latest_completed_session(
            "NYSE",
            datetime(2026, 7, 6, 20, 0, tzinfo=UTC),
        )

        self.assertEqual(session.session_date, date(2026, 7, 6))
        self.assertEqual(session.opens_at.astimezone(UTC).hour, 13)
        self.assertEqual(session.opens_at.astimezone(UTC).minute, 30)
        self.assertEqual(session.closes_at.astimezone(UTC).hour, 20)
        self.assertFalse(session.early_close)

    def test_cutoff_outside_packaged_coverage_fails_closed(self) -> None:
        calendar = load_packaged_us_equities_calendar()

        with self.assertRaisesRegex(
            ValuationSnapshotError,
            "market calendar cutoff is outside coverage",
        ):
            calendar.latest_completed_session(
                "NASDAQ",
                datetime(2027, 1, 2, tzinfo=UTC),
            )


if __name__ == "__main__":
    unittest.main()

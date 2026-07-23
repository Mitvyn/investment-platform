from __future__ import annotations

from datetime import UTC, datetime
import unittest

from workers.primary_sources.temporal import assess_publication_time


CUTOFF = datetime(2026, 5, 6, 23, 59, 59, tzinfo=UTC)


class PrimarySourceTemporalTests(unittest.TestCase):
    def test_exact_timestamp_is_valid_only_on_or_before_cutoff(self) -> None:
        before = assess_publication_time("2026-05-06T20:00:00Z", CUTOFF)
        after = assess_publication_time("2026-05-07T00:00:00Z", CUTOFF)

        self.assertEqual(before.state, "exact")
        self.assertEqual(before.reason_code, "publication_time_verified_at_cutoff")
        self.assertTrue(before.valid_at_cutoff)
        self.assertEqual(
            before.published_at,
            datetime(2026, 5, 6, 20, 0, tzinfo=UTC),
        )
        self.assertEqual(after.state, "after_cutoff")
        self.assertEqual(after.reason_code, "publication_after_cutoff")
        self.assertFalse(after.valid_at_cutoff)

    def test_date_only_is_valid_only_when_whole_day_precedes_cutoff(self) -> None:
        prior_day = assess_publication_time("2026-05-05", CUTOFF)
        cutoff_day = assess_publication_time("2026-05-06", CUTOFF)

        self.assertEqual(prior_day.state, "date_only")
        self.assertEqual(
            prior_day.reason_code,
            "publication_date_verified_before_cutoff",
        )
        self.assertTrue(prior_day.valid_at_cutoff)
        self.assertIsNone(prior_day.published_at)
        self.assertEqual(cutoff_day.state, "date_only")
        self.assertEqual(
            cutoff_day.reason_code,
            "publication_time_date_only_at_cutoff",
        )
        self.assertFalse(cutoff_day.valid_at_cutoff)

    def test_naive_and_missing_times_are_explicitly_indeterminate(
        self,
    ) -> None:
        cases = (
            (
                "2026-05-06T20:00:00",
                "timezone_ambiguous",
                "publication_timezone_unresolved",
            ),
            (None, "unavailable", "publication_time_unavailable"),
        )

        for value, state, reason_code in cases:
            with self.subTest(value=value):
                result = assess_publication_time(value, CUTOFF)
                self.assertEqual(result.state, state)
                self.assertEqual(result.reason_code, reason_code)
                self.assertFalse(result.valid_at_cutoff)
                self.assertIsNone(result.published_at)

    def test_invalid_values_fail_closed(self) -> None:
        for value in ("not-a-date", "2026-02-30T10:00:00Z", 123):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    ValueError,
                    "publication time is invalid",
                ):
                    assess_publication_time(value, CUTOFF)

        with self.assertRaisesRegex(ValueError, "cutoff must include timezone"):
            assess_publication_time(
                "2026-05-06T20:00:00Z",
                datetime(2026, 5, 6, 23, 59, 59),
            )


if __name__ == "__main__":
    unittest.main()

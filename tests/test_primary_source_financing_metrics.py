from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import unittest

from workers.primary_sources.financing_metrics import (
    FilingFinancingMetricError,
    normalize_filing_financing_metrics,
)
from workers.primary_sources.pipeline import PrimaryEvidencePassage


def passage(reference_key: str, text: str) -> PrimaryEvidencePassage:
    return PrimaryEvidencePassage(
        reference_key=reference_key,
        source_class="financing",
        coverage_keys=frozenset(),
        source_locator=(f"0001601830-26-000078/rxrx-20260331.htm#{reference_key}"),
        canonical_url=(
            "https://www.sec.gov/Archives/edgar/data/1601830/"
            "000160183026000078/rxrx-20260331.htm"
        ),
        publication_at=datetime(2026, 5, 6, 10, 32, 40, tzinfo=UTC),
        retrieved_at=datetime(2026, 7, 28, 2, tzinfo=UTC),
        effective_at=None,
        filing_period_start=None,
        filing_period_end=None,
        document_content_hash="a" * 64,
        passage_text=text,
        freshness="current",
        origin_policy_version="sec-origin-v1",
        available_at=datetime(2026, 5, 6, 10, 32, 40, tzinfo=UTC),
    )


class FilingFinancingMetricTests(unittest.TestCase):
    def test_normalizes_warrants_from_scaled_reserved_shares_table(self) -> None:
        metrics = normalize_filing_financing_metrics(
            (
                passage(
                    "financing:options",
                    (
                        "Stock options Shares Weighted-Average Exercise Price. "
                        "Outstanding as of December 31, 2025 "
                        "17,315,721 $ 6.53."
                    ),
                ),
                passage(
                    "financing:rsus",
                    (
                        "Restricted stock units Stock units Weighted-average "
                        "grant date fair value. Outstanding as of March 31, "
                        "2026 28,565,398 $ 5.99."
                    ),
                ),
                passage(
                    "financing:atm",
                    (
                        "At-The-Market Offerings. As of March 31, 2026, "
                        "an amount of $300 million remained available for "
                        "future sales."
                    ),
                ),
                passage(
                    "financing:warrants",
                    (
                        "Shares of common stock reserved for future issuance "
                        "are as follows (in thousands): December 31, 2025 "
                        "Warrants outstanding 58,482."
                    ),
                ),
            )
        )

        warrant = next(
            metric
            for metric in metrics
            if metric.metric_key == "warrant_shares_outstanding"
        )
        self.assertEqual(warrant.value, "58482000")
        self.assertEqual(warrant.period_end.isoformat(), "2025-12-31")
        self.assertEqual(warrant.calculation_method, "derived")
        self.assertEqual(warrant.formula, "reported_amount*1000")

    def test_preserves_literal_warrant_value_without_scale_marker(self) -> None:
        metrics = normalize_filing_financing_metrics(
            (
                passage(
                    "financing:options",
                    (
                        "Stock options Shares Weighted-Average Exercise Price. "
                        "Outstanding as of December 31, 2025 "
                        "17,315,721 $ 6.53."
                    ),
                ),
                passage(
                    "financing:rsus",
                    (
                        "Restricted stock units Stock units Weighted-average "
                        "grant date fair value. Outstanding as of March 31, "
                        "2026 28,565,398 $ 5.99."
                    ),
                ),
                passage(
                    "financing:atm",
                    (
                        "At-The-Market Offerings. As of March 31, 2026, "
                        "an amount of $300 million remained available for "
                        "future sales."
                    ),
                ),
                passage(
                    "financing:warrants",
                    ("December 31, 2025 Warrants outstanding 58,482 shares."),
                ),
            )
        )

        warrant = next(
            metric
            for metric in metrics
            if metric.metric_key == "warrant_shares_outstanding"
        )
        self.assertEqual(warrant.value, "58482")
        self.assertEqual(warrant.calculation_method, "reported")
        self.assertIsNone(warrant.formula)

    def test_does_not_apply_completed_unrelated_table_scale_to_warrants(self) -> None:
        metrics = normalize_filing_financing_metrics(
            (
                passage(
                    "financing:options",
                    (
                        "Stock options Shares Weighted-Average Exercise Price. "
                        "Outstanding as of December 31, 2025 "
                        "17,315,721 $ 6.53."
                    ),
                ),
                passage(
                    "financing:rsus",
                    (
                        "Restricted stock units Stock units Weighted-average "
                        "grant date fair value. Outstanding as of March 31, "
                        "2026 28,565,398 $ 5.99."
                    ),
                ),
                passage(
                    "financing:atm",
                    (
                        "At-The-Market Offerings. As of March 31, 2026, "
                        "an amount of $300 million remained available for "
                        "future sales."
                    ),
                ),
                passage(
                    "financing:warrants",
                    (
                        "Operating expenses (in thousands): 2025 15,000. "
                        "Warrants table: December 31, 2025 Warrants "
                        "outstanding 58,482 shares."
                    ),
                ),
            )
        )

        warrant = next(
            metric
            for metric in metrics
            if metric.metric_key == "warrant_shares_outstanding"
        )
        self.assertEqual(warrant.value, "58482")
        self.assertEqual(warrant.calculation_method, "reported")
        self.assertIsNone(warrant.formula)

    def test_named_warrant_table_resets_flattened_prior_table_scale(self) -> None:
        metrics = normalize_filing_financing_metrics(
            (
                passage(
                    "financing:options",
                    (
                        "Stock options Shares Weighted-Average Exercise Price. "
                        "Outstanding as of December 31, 2025 "
                        "17,315,721 $ 6.53."
                    ),
                ),
                passage(
                    "financing:rsus",
                    (
                        "Restricted stock units Stock units Weighted-average "
                        "grant date fair value. Outstanding as of March 31, "
                        "2026 28,565,398 $ 5.99."
                    ),
                ),
                passage(
                    "financing:atm",
                    (
                        "At-The-Market Offerings. As of March 31, 2026, "
                        "an amount of $300 million remained available for "
                        "future sales."
                    ),
                ),
                passage(
                    "financing:warrants",
                    (
                        "Operating expenses (in thousands) 2025 15,000 "
                        "Warrants table: December 31, 2025 Warrants "
                        "outstanding 58,482 shares."
                    ),
                ),
            )
        )

        warrant = next(
            metric
            for metric in metrics
            if metric.metric_key == "warrant_shares_outstanding"
        )
        self.assertEqual(warrant.value, "58482")
        self.assertEqual(warrant.calculation_method, "reported")
        self.assertIsNone(warrant.formula)

    def test_does_not_reuse_scale_across_unlabelled_numeric_table(self) -> None:
        metrics = normalize_filing_financing_metrics(
            (
                passage(
                    "financing:options",
                    (
                        "Stock options Shares Weighted-Average Exercise Price. "
                        "Outstanding as of December 31, 2025 "
                        "17,315,721 $ 6.53."
                    ),
                ),
                passage(
                    "financing:rsus",
                    (
                        "Restricted stock units Stock units Weighted-average "
                        "grant date fair value. Outstanding as of March 31, "
                        "2026 28,565,398 $ 5.99."
                    ),
                ),
                passage(
                    "financing:atm",
                    (
                        "At-The-Market Offerings. As of March 31, 2026, "
                        "an amount of $300 million remained available for "
                        "future sales."
                    ),
                ),
                passage(
                    "financing:warrants",
                    (
                        "Operating expenses (in thousands) 2025 15,000 "
                        "December 31, 2025 Warrants outstanding 58,482 shares."
                    ),
                ),
            )
        )

        warrant = next(
            metric
            for metric in metrics
            if metric.metric_key == "warrant_shares_outstanding"
        )
        self.assertEqual(warrant.value, "58482")
        self.assertEqual(warrant.calculation_method, "reported")
        self.assertIsNone(warrant.formula)

    def test_normalizes_adjacent_warrant_scale(self) -> None:
        metrics = normalize_filing_financing_metrics(
            (
                passage(
                    "financing:options",
                    (
                        "Stock options Shares Weighted-Average Exercise Price. "
                        "Outstanding as of December 31, 2025 "
                        "17,315,721 $ 6.53."
                    ),
                ),
                passage(
                    "financing:rsus",
                    (
                        "Restricted stock units Stock units Weighted-average "
                        "grant date fair value. Outstanding as of March 31, "
                        "2026 28,565,398 $ 5.99."
                    ),
                ),
                passage(
                    "financing:atm",
                    (
                        "At-The-Market Offerings. As of March 31, 2026, "
                        "an amount of $300 million remained available for "
                        "future sales."
                    ),
                ),
                passage(
                    "financing:warrants",
                    ("December 31, 2025 Warrants outstanding 58.482 million shares."),
                ),
            )
        )

        warrant = next(
            metric
            for metric in metrics
            if metric.metric_key == "warrant_shares_outstanding"
        )
        self.assertEqual(warrant.value, "58482000")
        self.assertEqual(warrant.formula, "reported_amount*1000000")

    def test_rejects_unrecognized_table_scale_marker(self) -> None:
        with self.assertRaisesRegex(
            FilingFinancingMetricError,
            "filing financing table scale is unrecognized",
        ):
            normalize_filing_financing_metrics(
                (
                    passage(
                        "financing:options",
                        (
                            "Stock options Shares Weighted-Average Exercise "
                            "Price. Outstanding as of December 31, 2025 "
                            "17,315,721 $ 6.53."
                        ),
                    ),
                    passage(
                        "financing:rsus",
                        (
                            "Restricted stock units Stock units Weighted-average "
                            "grant date fair value. Outstanding as of March 31, "
                            "2026 28,565,398 $ 5.99."
                        ),
                    ),
                    passage(
                        "financing:atm",
                        (
                            "At-The-Market Offerings. As of March 31, 2026, "
                            "an amount of $300 million remained available for "
                            "future sales."
                        ),
                    ),
                    passage(
                        "financing:warrants",
                        (
                            "Shares reserved for future issuance (in hundreds): "
                            "December 31, 2025 Warrants outstanding 58,482."
                        ),
                    ),
                )
            )

    def test_rejects_ambiguous_table_scale_markers(self) -> None:
        with self.assertRaisesRegex(
            FilingFinancingMetricError,
            "filing financing table scale is ambiguous",
        ):
            normalize_filing_financing_metrics(
                (
                    passage(
                        "financing:options",
                        (
                            "Stock options Shares Weighted-Average Exercise "
                            "Price. Outstanding as of December 31, 2025 "
                            "17,315,721 $ 6.53."
                        ),
                    ),
                    passage(
                        "financing:rsus",
                        (
                            "Restricted stock units Stock units Weighted-average "
                            "grant date fair value. Outstanding as of March 31, "
                            "2026 28,565,398 $ 5.99."
                        ),
                    ),
                    passage(
                        "financing:atm",
                        (
                            "At-The-Market Offerings. As of March 31, 2026, "
                            "an amount of $300 million remained available for "
                            "future sales."
                        ),
                    ),
                    passage(
                        "financing:warrants",
                        (
                            "Summary (in thousands), detail (in millions): "
                            "December 31, 2025 Warrants outstanding 58,482."
                        ),
                    ),
                )
            )

    def test_normalizes_convertible_share_equivalents(self) -> None:
        metrics = normalize_filing_financing_metrics(
            (
                passage(
                    "financing:options",
                    (
                        "Stock options Shares Weighted-Average Exercise Price. "
                        "Outstanding as of December 31, 2025 "
                        "17,315,721 $ 6.53."
                    ),
                ),
                passage(
                    "financing:rsus",
                    (
                        "Restricted stock units Stock units Weighted-average "
                        "grant date fair value. Outstanding as of March 31, "
                        "2026 28,565,398 $ 5.99."
                    ),
                ),
                passage(
                    "financing:atm",
                    (
                        "At-The-Market Offerings. As of March 31, 2026, "
                        "an amount of $300 million remained available for "
                        "future sales."
                    ),
                ),
                passage(
                    "financing:convertibles",
                    (
                        "As of December 31, 2025, convertible notes were "
                        "convertible into 1,250,000 shares of common stock."
                    ),
                ),
            )
        )

        convertible = next(
            metric
            for metric in metrics
            if metric.metric_key == "convertible_share_equivalents"
        )
        self.assertEqual(convertible.value, "1250000")
        self.assertEqual(convertible.unit, "shares")
        self.assertEqual(convertible.period_end.isoformat(), "2025-12-31")

    def test_normalizes_explicit_zero_preferred_shares(self) -> None:
        metrics = normalize_filing_financing_metrics(
            (
                passage(
                    "financing:options",
                    (
                        "Stock options Shares Weighted-Average Exercise Price. "
                        "Outstanding as of December 31, 2025 "
                        "17,315,721 $ 6.53."
                    ),
                ),
                passage(
                    "financing:rsus",
                    (
                        "Restricted stock units Stock units Weighted-average "
                        "grant date fair value. Outstanding as of March 31, "
                        "2026 28,565,398 $ 5.99."
                    ),
                ),
                passage(
                    "financing:atm",
                    (
                        "At-The-Market Offerings. As of March 31, 2026, "
                        "an amount of $300 million remained available for "
                        "future sales."
                    ),
                ),
                passage(
                    "financing:preferreds",
                    (
                        "There were no preferred shares outstanding as of "
                        "December 31, 2025 and 2024."
                    ),
                ),
            )
        )

        preferred = next(
            metric
            for metric in metrics
            if metric.metric_key == "preferred_shares_outstanding"
        )
        self.assertEqual(preferred.value, "0")
        self.assertEqual(preferred.unit, "shares")
        self.assertEqual(preferred.period_end.isoformat(), "2025-12-31")
        self.assertEqual(preferred.calculation_method, "reported")

    def test_normalizes_positive_preferred_share_balance(self) -> None:
        metrics = normalize_filing_financing_metrics(
            (
                passage(
                    "financing:options",
                    (
                        "Stock options Shares Weighted-Average Exercise Price. "
                        "Outstanding as of December 31, 2025 "
                        "17,315,721 $ 6.53."
                    ),
                ),
                passage(
                    "financing:rsus",
                    (
                        "Restricted stock units Stock units Weighted-average "
                        "grant date fair value. Outstanding as of March 31, "
                        "2026 28,565,398 $ 5.99."
                    ),
                ),
                passage(
                    "financing:atm",
                    (
                        "At-The-Market Offerings. As of March 31, 2026, "
                        "an amount of $300 million remained available for "
                        "future sales."
                    ),
                ),
                passage(
                    "financing:preferreds",
                    (
                        "Preferred shares outstanding as of December 31, "
                        "2025 125,000 shares."
                    ),
                ),
            )
        )

        preferred = next(
            metric
            for metric in metrics
            if metric.metric_key == "preferred_shares_outstanding"
        )
        self.assertEqual(preferred.value, "125000")
        self.assertEqual(preferred.period_end.isoformat(), "2025-12-31")

    def test_does_not_treat_common_share_balance_as_preferred_balance(self) -> None:
        metrics = normalize_filing_financing_metrics(
            (
                passage(
                    "financing:options",
                    (
                        "Stock options Shares Weighted-Average Exercise Price. "
                        "Outstanding as of December 31, 2025 "
                        "17,315,721 $ 6.53."
                    ),
                ),
                passage(
                    "financing:rsus",
                    (
                        "Restricted stock units Stock units Weighted-average "
                        "grant date fair value. Outstanding as of March 31, "
                        "2026 28,565,398 $ 5.99."
                    ),
                ),
                passage(
                    "financing:atm",
                    (
                        "At-The-Market Offerings. As of March 31, 2026, "
                        "an amount of $300 million remained available for "
                        "future sales."
                    ),
                ),
                passage(
                    "financing:preferreds",
                    (
                        "Preferred stock has been authorized. Common stock "
                        "outstanding as of December 31, 2025 125,000 shares."
                    ),
                ),
            )
        )

        self.assertNotIn(
            "preferred_shares_outstanding",
            {metric.metric_key for metric in metrics},
        )

    def test_normalizes_literal_rxrx_filing_tables(self) -> None:
        source_plan = json.loads(
            Path(
                "tests/fixtures/primary_sources/rxrx-primary-source-plan-v2.json"
            ).read_text()
        )
        texts = {
            item["reference_key"]: item["exact_text"]
            for item in source_plan["sec_passages"]
        }

        metrics = normalize_filing_financing_metrics(
            (
                passage("financing:options", texts["financing:options"]),
                passage("financing:rsus", texts["financing:rsus"]),
                passage(
                    "financing:atm_shelf_capacity",
                    texts["financing:atm_shelf_capacity"],
                ),
            )
        )

        self.assertEqual(
            tuple(metric.value for metric in metrics),
            ("17315721", "28565398", "300000000"),
        )
        self.assertEqual(
            tuple(metric.period_end.isoformat() for metric in metrics),
            ("2025-12-31", "2026-03-31", "2026-03-31"),
        )

    def test_normalizes_three_supported_filing_metrics(self) -> None:
        metrics = normalize_filing_financing_metrics(
            (
                passage(
                    "financing:options",
                    (
                        "Stock options Shares Weighted-Average Exercise Price. "
                        "Outstanding as of December 31, 2025 "
                        "17,315,721 $ 6.53."
                    ),
                ),
                passage(
                    "financing:rsus",
                    (
                        "Restricted stock units Stock units Weighted-average "
                        "grant date fair value. Outstanding as of March 31, "
                        "2026 28,565,398 $ 5.99."
                    ),
                ),
                passage(
                    "financing:atm",
                    (
                        "At-The-Market Offerings. As of March 31, 2026, "
                        "an amount of $ 300.0 million remained available for "
                        "future sales under the Sales Agreement."
                    ),
                ),
            )
        )

        self.assertEqual(
            tuple(
                (
                    metric.reference_key,
                    metric.metric_key,
                    metric.value,
                    metric.unit,
                    metric.period_end.isoformat(),
                    metric.calculation_method,
                    metric.formula,
                    metric.supporting_passage_keys,
                )
                for metric in metrics
            ),
            (
                (
                    "financing-metric:options",
                    "option_shares_outstanding",
                    "17315721",
                    "shares",
                    "2025-12-31",
                    "reported",
                    None,
                    ("financing:options",),
                ),
                (
                    "financing-metric:rsus",
                    "rsu_shares_outstanding",
                    "28565398",
                    "shares",
                    "2026-03-31",
                    "reported",
                    None,
                    ("financing:rsus",),
                ),
                (
                    "financing-metric:atm_shelf_capacity",
                    "atm_capacity",
                    "300000000",
                    "USD",
                    "2026-03-31",
                    "derived",
                    "reported_amount*1000000",
                    ("financing:atm",),
                ),
            ),
        )

    def test_rejects_missing_supported_metric(self) -> None:
        with self.assertRaisesRegex(
            FilingFinancingMetricError,
            "rsus filing financing passage is missing",
        ):
            normalize_filing_financing_metrics(
                (
                    passage(
                        "financing:options",
                        (
                            "Stock options Shares Weighted-Average Exercise "
                            "Price. Outstanding as of December 31, 2025 "
                            "17,315,721 $ 6.53."
                        ),
                    ),
                    passage(
                        "financing:atm",
                        (
                            "At-The-Market Offerings. As of March 31, 2026, "
                            "an amount of $300 million remained available for "
                            "future sales."
                        ),
                    ),
                )
            )

    def test_rejects_ambiguous_duplicate_observation(self) -> None:
        options_text = (
            "Stock options Shares Weighted-Average Exercise Price. "
            "Outstanding as of December 31, 2025 17,315,721 $ 6.53."
        )
        with self.assertRaisesRegex(
            FilingFinancingMetricError,
            "options filing financing passage is ambiguous",
        ):
            normalize_filing_financing_metrics(
                (
                    passage("financing:options-a", options_text),
                    passage("financing:options-b", options_text),
                    passage(
                        "financing:rsus",
                        (
                            "Restricted stock units Stock units "
                            "Weighted-average grant date fair value. "
                            "Outstanding as of March 31, 2026 "
                            "28,565,398 $ 5.99."
                        ),
                    ),
                    passage(
                        "financing:atm",
                        (
                            "At-The-Market Offerings. As of March 31, 2026, "
                            "an amount of $300 million remained available for "
                            "future sales."
                        ),
                    ),
                )
            )

    def test_rejects_conflicting_observations(self) -> None:
        with self.assertRaisesRegex(
            FilingFinancingMetricError,
            "atm_shelf_capacity filing financing passages conflict",
        ):
            normalize_filing_financing_metrics(
                (
                    passage(
                        "financing:options",
                        (
                            "Stock options Shares Weighted-Average Exercise "
                            "Price. Outstanding as of December 31, 2025 "
                            "17,315,721 $ 6.53."
                        ),
                    ),
                    passage(
                        "financing:rsus",
                        (
                            "Restricted stock units Stock units "
                            "Weighted-average grant date fair value. "
                            "Outstanding as of March 31, 2026 "
                            "28,565,398 $ 5.99."
                        ),
                    ),
                    passage(
                        "financing:atm-a",
                        (
                            "At-The-Market Offerings. As of March 31, 2026, "
                            "an amount of $300 million remained available for "
                            "future sales."
                        ),
                    ),
                    passage(
                        "financing:atm-b",
                        (
                            "ATM program. As of March 31, 2026, an amount of "
                            "$250 million remained available for future sales."
                        ),
                    ),
                )
            )


if __name__ == "__main__":
    unittest.main()

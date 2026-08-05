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

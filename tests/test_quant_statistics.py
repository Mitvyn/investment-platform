from __future__ import annotations

import unittest
from decimal import Decimal

from investment_research_os.quant.bars import QuantContractError
from investment_research_os.quant.statistics import (
    ALPHA_LABELS,
    DEGREES_OF_FREEDOM_BUCKETS,
    critical_value,
    resolve_alpha_label,
    resolve_degrees_of_freedom_bucket,
    simple_returns,
    summarise_returns,
)


class SimpleReturnTests(unittest.TestCase):
    def test_returns_are_exact_decimals(self) -> None:
        equity = [Decimal("100"), Decimal("110"), Decimal("99")]
        self.assertEqual(
            simple_returns(equity),
            (Decimal("0.1"), Decimal("-0.1")),
        )

    def test_a_single_point_yields_no_returns(self) -> None:
        self.assertEqual(simple_returns([Decimal("100")]), ())

    def test_zero_equity_is_rejected(self) -> None:
        with self.assertRaises(QuantContractError):
            simple_returns([Decimal("0"), Decimal("100")])

    def test_float_equity_is_rejected(self) -> None:
        with self.assertRaises(QuantContractError):
            simple_returns([100.0, 110.0])  # type: ignore[list-item]


class SummaryStatisticTests(unittest.TestCase):
    def test_statistics_match_hand_computed_values(self) -> None:
        # mean = 0.02; deviations = -0.01, 0.01, -0.02, 0.02, 0.00
        # sum of squares = 0.0001+0.0001+0.0004+0.0004+0 = 0.001
        # sample variance = 0.001 / 4 = 0.00025; stdev = 0.0158113883...
        # t = 0.02 / (stdev / sqrt(5)) = 0.02 / 0.00707106781 = 2.828427...
        returns = [
            Decimal("0.01"),
            Decimal("0.03"),
            Decimal("0.00"),
            Decimal("0.04"),
            Decimal("0.02"),
        ]
        stats = summarise_returns(returns, annualisation_periods=1)
        self.assertEqual(stats.count, 5)
        self.assertEqual(stats.mean, Decimal("0.020000"))
        self.assertEqual(stats.stdev, Decimal("0.015811"))
        assert stats.t_statistic is not None
        self.assertEqual(stats.t_statistic, Decimal("2.828427"))
        self.assertEqual(stats.degrees_of_freedom, 4)

    def test_annualisation_scales_the_sharpe_ratio(self) -> None:
        returns = [Decimal("0.01"), Decimal("0.03"), Decimal("0.00"), Decimal("0.04")]
        plain = summarise_returns(returns, annualisation_periods=1)
        annual = summarise_returns(returns, annualisation_periods=4)
        assert plain.sharpe_ratio is not None
        assert annual.sharpe_ratio is not None
        self.assertEqual(annual.sharpe_ratio, (plain.sharpe_ratio * 2).quantize(
            Decimal("0.000001")
        ))

    def test_fewer_than_two_observations_has_no_dispersion(self) -> None:
        stats = summarise_returns([Decimal("0.01")], annualisation_periods=1)
        self.assertEqual(stats.count, 1)
        self.assertIsNone(stats.stdev)
        self.assertIsNone(stats.t_statistic)
        self.assertIsNone(stats.sharpe_ratio)

    def test_zero_variance_yields_no_ratio_rather_than_infinity(self) -> None:
        stats = summarise_returns(
            [Decimal("0.01"), Decimal("0.01"), Decimal("0.01")],
            annualisation_periods=1,
        )
        self.assertEqual(stats.stdev, Decimal("0"))
        self.assertIsNone(stats.t_statistic)
        self.assertIsNone(stats.sharpe_ratio)

    def test_empty_series_is_rejected(self) -> None:
        with self.assertRaises(QuantContractError):
            summarise_returns([], annualisation_periods=1)

    def test_annualisation_periods_must_be_positive(self) -> None:
        with self.assertRaises(QuantContractError):
            summarise_returns([Decimal("0.01")], annualisation_periods=0)

    def test_record_carries_no_floats(self) -> None:
        stats = summarise_returns(
            [Decimal("0.01"), Decimal("0.02")], annualisation_periods=1
        )
        for value in stats.to_record().values():
            self.assertNotIsInstance(value, float)


class CriticalValueTests(unittest.TestCase):
    def test_degrees_of_freedom_round_down_to_the_conservative_bucket(self) -> None:
        self.assertEqual(resolve_degrees_of_freedom_bucket(119), 60)
        self.assertEqual(resolve_degrees_of_freedom_bucket(120), 120)
        self.assertEqual(resolve_degrees_of_freedom_bucket(5000), 1000)

    def test_degrees_of_freedom_below_the_table_has_no_bucket(self) -> None:
        self.assertIsNone(resolve_degrees_of_freedom_bucket(9))
        self.assertIsNone(resolve_degrees_of_freedom_bucket(0))

    def test_alpha_rounds_down_to_the_conservative_label(self) -> None:
        self.assertEqual(resolve_alpha_label(Decimal("0.05")), "0.05")
        self.assertEqual(resolve_alpha_label(Decimal("0.04")), "0.01")
        self.assertEqual(resolve_alpha_label(Decimal("0.0025")), "0.001")

    def test_alpha_below_the_table_has_no_label(self) -> None:
        self.assertIsNone(resolve_alpha_label(Decimal("0.0005")))

    def test_a_stricter_alpha_demands_a_larger_statistic(self) -> None:
        loose = critical_value(degrees_of_freedom=30, alpha=Decimal("0.05"))
        strict = critical_value(degrees_of_freedom=30, alpha=Decimal("0.001"))
        assert loose is not None and strict is not None
        self.assertGreater(strict, loose)

    def test_more_data_demands_a_smaller_statistic(self) -> None:
        few = critical_value(degrees_of_freedom=10, alpha=Decimal("0.05"))
        many = critical_value(degrees_of_freedom=1000, alpha=Decimal("0.05"))
        assert few is not None and many is not None
        self.assertGreater(few, many)

    def test_out_of_table_lookups_return_none(self) -> None:
        self.assertIsNone(critical_value(degrees_of_freedom=4, alpha=Decimal("0.05")))
        self.assertIsNone(
            critical_value(degrees_of_freedom=30, alpha=Decimal("0.0001"))
        )

    def test_table_is_complete_and_decimal(self) -> None:
        for bucket in DEGREES_OF_FREEDOM_BUCKETS:
            for label in ALPHA_LABELS:
                value = critical_value(
                    degrees_of_freedom=bucket, alpha=Decimal(label)
                )
                self.assertIsInstance(value, Decimal)


if __name__ == "__main__":
    unittest.main()

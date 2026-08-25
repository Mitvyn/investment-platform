from __future__ import annotations

import json
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from investment_research_os.quant import (
    BarSeries,
    CorporateActionSet,
    OhlcvBar,
    PointInTimeDataset,
)
from workers.quant_workspace.intake import QuantWorkspaceError
from workers.quant_workspace.runner import (
    QUANT_RESULT_CONTRACT_VERSION,
    QuantRunAssumptions,
    assumptions_from_mapping,
    run_key,
    run_quant_analysis,
)
from workers.quant_workspace.strategies import (
    BENCHMARK_STRATEGY_ID,
    TREND_STRATEGY_ID,
    TrendFollowingFactory,
)

SECURITY_ID = "6f1d2c3b-4a5e-4f6a-8b9c-0d1e2f3a4b5c"


def sessions(count: int) -> list[date]:
    start = date(2025, 1, 6)
    return [start + timedelta(days=index) for index in range(count)]


def dataset_for(
    closes: list[str], *, volume: int = 1_000_000, cutoff: date | None = None
) -> PointInTimeDataset:
    days = sessions(len(closes))
    bars = tuple(
        OhlcvBar(
            session=day,
            open=Decimal(close),
            high=Decimal(close) + Decimal("1"),
            low=Decimal(close) - Decimal("1"),
            close=Decimal(close),
            volume=volume,
        )
        for day, close in zip(days, closes)
    )
    series = BarSeries(
        security_id=SECURITY_ID,
        currency="USD",
        interval="1d",
        price_basis="unadjusted",
        source="operator_local_csv",
        bars=bars,
    )
    return PointInTimeDataset(
        series=series,
        corporate_actions=CorporateActionSet(
            security_id=SECURITY_ID, source="operator_local_csv", actions=()
        ),
        as_of_cutoff=cutoff or days[-1],
        source_id="operator_local_csv",
        source_revision="2026-01-20-eod",
        source_content_sha256="a" * 64,
        coverage_scope="single_security",
    )


def rising(count: int) -> list[str]:
    return [str(100 + index) for index in range(count)]


def choppy(count: int) -> list[str]:
    return [str(100 + (index % 7)) for index in range(count)]


def assumptions(**overrides: object) -> QuantRunAssumptions:
    values: dict[str, object] = {
        "alpha": "0.05",
        "annualisation_periods": 252,
        "commission_bps": "0",
        "commission_minimum": "1.00",
        "commission_per_share": "0.01",
        "cost_stress_multiplier": "3",
        "embargo_sessions": 1,
        "lookback_sessions": 5,
        "max_participation_bps": "500",
        "min_fill_shares": 1,
        "min_total_trades": 1,
        "min_trades_per_window": 0,
        "min_windows": 3,
        "slippage_bps": "5",
        "starting_cash": "100000.00",
        "step_sessions": 10,
        "test_sessions": 10,
        "train_sessions": 20,
        "transaction_cost_bps": "2",
        "trials_declared": 2,
    }
    values.update(overrides)
    return assumptions_from_mapping(values)


class QuantRunTests(unittest.TestCase):
    def test_result_carries_the_sanitized_local_contract(self) -> None:
        result = run_quant_analysis(
            dataset=dataset_for(rising(80)), assumptions=assumptions()
        )

        self.assertEqual(
            result["contract_version"], QUANT_RESULT_CONTRACT_VERSION
        )
        self.assertEqual(result["security_id"], SECURITY_ID)
        self.assertEqual(result["strategy"]["strategy_id"], TREND_STRATEGY_ID)
        self.assertEqual(result["benchmark"]["strategy_id"], BENCHMARK_STRATEGY_ID)
        self.assertEqual(len(result["content_sha256"]), 64)
        for field in (
            "total_return",
            "max_drawdown",
            "volatility",
            "trade_count",
            "unfilled_shares",
            "cost_total",
        ):
            self.assertIn(field, result["strategy"])
        for field in ("outcome", "window_count", "windows_beating_benchmark", "gaps"):
            self.assertIn(field, result["validation"])

    def test_result_never_carries_bars_holdings_or_provider_payloads(self) -> None:
        result = run_quant_analysis(
            dataset=dataset_for(rising(80)), assumptions=assumptions()
        )
        serialized = json.dumps(result)

        for forbidden in (
            "bars",
            "holding",
            "position",
            "portfolio",
            "evidence",
            "thesis",
            "committee",
            "account",
            "order",
            "broker",
            "open",
            "high",
            "low",
        ):
            self.assertNotIn(f'"{forbidden}"', serialized)

    def test_same_inputs_produce_the_same_result_identity(self) -> None:
        first = run_quant_analysis(
            dataset=dataset_for(rising(80)), assumptions=assumptions()
        )
        second = run_quant_analysis(
            dataset=dataset_for(rising(80)), assumptions=assumptions()
        )

        self.assertEqual(first["content_sha256"], second["content_sha256"])
        self.assertEqual(first, second)

    def test_changed_assumptions_change_result_identity_and_run_key(self) -> None:
        dataset = dataset_for(rising(80))
        base = assumptions()
        stressed = assumptions(slippage_bps="250")

        self.assertNotEqual(
            run_quant_analysis(dataset=dataset, assumptions=base)["content_sha256"],
            run_quant_analysis(dataset=dataset, assumptions=stressed)[
                "content_sha256"
            ],
        )
        self.assertNotEqual(
            run_key(dataset_sha256=dataset.content_sha256, assumptions=base),
            run_key(dataset_sha256=dataset.content_sha256, assumptions=stressed),
        )

    def test_benchmark_is_reported_alongside_the_strategy(self) -> None:
        result = run_quant_analysis(
            dataset=dataset_for(rising(80)), assumptions=assumptions()
        )

        self.assertIn("total_return", result["benchmark"])
        self.assertEqual(
            Decimal(result["excess_return"]),
            Decimal(result["strategy"]["total_return"])
            - Decimal(result["benchmark"]["total_return"]),
        )

    def test_higher_costs_reduce_the_reported_strategy_return(self) -> None:
        dataset = dataset_for(choppy(80))
        cheap = run_quant_analysis(
            dataset=dataset, assumptions=assumptions(slippage_bps="0")
        )
        expensive = run_quant_analysis(
            dataset=dataset, assumptions=assumptions(slippage_bps="300")
        )

        self.assertGreater(
            Decimal(cheap["strategy"]["total_return"]),
            Decimal(expensive["strategy"]["total_return"]),
        )
        self.assertGreater(
            Decimal(expensive["strategy"]["cost_total"]),
            Decimal(cheap["strategy"]["cost_total"]),
        )

    def test_short_history_reports_insufficient_data_rather_than_a_verdict(
        self,
    ) -> None:
        result = run_quant_analysis(
            dataset=dataset_for(rising(25)), assumptions=assumptions()
        )

        self.assertEqual(result["validation"]["outcome"], "insufficient_data")
        self.assertIn(
            result["validation"]["reason_codes"][0],
            {"series_too_short", "too_few_windows"},
        )
        self.assertIn("insufficient_windows", result["validation"]["gaps"])

    def test_overlapping_test_windows_are_reported_as_a_validation_gap(self) -> None:
        result = run_quant_analysis(
            dataset=dataset_for(rising(120)),
            assumptions=assumptions(step_sessions=5, test_sessions=10),
        )

        self.assertIn("overlapping_test_windows", result["validation"]["gaps"])

    def test_unreachable_benchmark_is_reported_as_a_gap(self) -> None:
        result = run_quant_analysis(
            dataset=dataset_for(rising(80), volume=10),
            assumptions=assumptions(max_participation_bps="1"),
        )

        self.assertIn("benchmark_unreachable", result["validation"]["gaps"])
        self.assertGreater(int(result["strategy"]["unfilled_shares"]), 0)

    def test_strategy_decisions_never_see_a_future_session(self) -> None:
        window_sessions: list[date] = []
        factory = TrendFollowingFactory(lookback_sessions=5)

        dataset = dataset_for(rising(40))
        strategy, config_sha256 = factory.build(
            _bar_window(dataset, end_index=20, sink=window_sessions)
        )

        self.assertEqual(len(config_sha256), 64)
        self.assertTrue(
            all(session <= dataset.series.bars[20].session for session in window_sessions)
            or not window_sessions
        )
        self.assertIsInstance(strategy.target_exposure, object)

    def test_assumptions_are_revalidated_at_the_boundary(self) -> None:
        for field, value in (
            ("starting_cash", "0"),
            ("starting_cash", 100000.0),
            ("lookback_sessions", 0),
            ("train_sessions", 0),
            ("max_participation_bps", "20000"),
            ("annualisation_periods", 0),
            ("alpha", "-0.5"),
            ("trials_declared", 0),
            ("cost_stress_multiplier", "0.5"),
            ("min_fill_shares", -1),
        ):
            with self.subTest(field=field, value=value):
                with self.assertRaises(QuantWorkspaceError) as caught:
                    assumptions(**{field: value})
                self.assertEqual(caught.exception.code, "run_assumptions_invalid")

    def test_unknown_or_missing_assumption_fields_are_refused(self) -> None:
        with self.assertRaises(QuantWorkspaceError) as caught:
            assumptions_from_mapping({"starting_cash": "1000"})
        self.assertEqual(caught.exception.code, "run_assumptions_invalid")

        with self.assertRaises(QuantWorkspaceError) as extra:
            assumptions(holdings_value="500")
        self.assertEqual(extra.exception.code, "run_assumptions_invalid")

    def test_tampered_dataset_is_refused_at_the_execution_boundary(self) -> None:
        dataset = dataset_for(rising(80))
        object.__setattr__(dataset.series, "bars", list(dataset.series.bars))

        with self.assertRaises(QuantWorkspaceError) as caught:
            run_quant_analysis(dataset=dataset, assumptions=assumptions())
        self.assertEqual(caught.exception.code, "run_dataset_invalid")


def _bar_window(dataset: PointInTimeDataset, *, end_index: int, sink: list[date]):
    from investment_research_os.quant import BarWindow

    window = BarWindow(
        security_id=dataset.security_id,
        currency=dataset.series.currency,
        bars=dataset.series.bars[: end_index + 1],
        corporate_actions=(),
    )
    sink.extend(bar.session for bar in window.bars)
    return window


if __name__ == "__main__":
    unittest.main()

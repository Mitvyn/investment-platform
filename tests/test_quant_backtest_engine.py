from __future__ import annotations

import unittest
from datetime import date, timedelta
from decimal import Decimal

from investment_research_os.quant import (
    BacktestConfig,
    BarSeries,
    BarWindow,
    CostModel,
    LookAheadError,
    OhlcvBar,
    QuantContractError,
    run_backtest,
)

SECURITY_ID = "3f1b0c2e-9d4a-4c7f-b1e2-8a5d6c7f0912"

FREE = CostModel(
    commission_per_share=Decimal("0"),
    commission_bps=Decimal("0"),
    commission_minimum=Decimal("0"),
    transaction_cost_bps=Decimal("0"),
    slippage_bps=Decimal("0"),
)

RETAIL = CostModel(
    commission_per_share=Decimal("0.01"),
    commission_bps=Decimal("0"),
    commission_minimum=Decimal("1.00"),
    transaction_cost_bps=Decimal("5"),
    slippage_bps=Decimal("10"),
)


def flat_series(closes: list[str], *, opens: list[str] | None = None) -> BarSeries:
    opens = opens or closes
    start = date(2026, 1, 5)
    bars = []
    for index, (open_, close) in enumerate(zip(opens, closes)):
        high = max(Decimal(open_), Decimal(close))
        low = min(Decimal(open_), Decimal(close))
        bars.append(
            OhlcvBar(
                session=start + timedelta(days=index),
                open=Decimal(open_),
                high=high,
                low=low,
                close=close,
                volume=1_000,
            )
        )
    return BarSeries(
        security_id=SECURITY_ID,
        currency="USD",
        interval="1d",
        source="fixture",
        bars=tuple(bars),
    )


class AlwaysLong:
    def target_exposure(self, window: BarWindow) -> Decimal:
        return Decimal(1)


class AlwaysFlat:
    def target_exposure(self, window: BarWindow) -> Decimal:
        return Decimal(0)


class RecordingStrategy:
    def __init__(self) -> None:
        self.cutoffs: list[date] = []
        self.window_lengths: list[int] = []

    def target_exposure(self, window: BarWindow) -> Decimal:
        self.cutoffs.append(window.cutoff)
        self.window_lengths.append(len(window.bars))
        return Decimal(1)


class PeekingStrategy:
    def target_exposure(self, window: BarWindow) -> Decimal:
        window.at(window.cutoff + timedelta(days=1))
        return Decimal(1)


class ShortingStrategy:
    def target_exposure(self, window: BarWindow) -> Decimal:
        return Decimal("-1")


class LeveredStrategy:
    def target_exposure(self, window: BarWindow) -> Decimal:
        return Decimal("1.5")


class FloatStrategy:
    def target_exposure(self, window: BarWindow) -> Decimal:
        return 0.5  # type: ignore[return-value]


def run(series: BarSeries, strategy: object, costs: CostModel = FREE, cash: str = "10000"):
    return run_backtest(
        series=series,
        strategy=strategy,  # type: ignore[arg-type]
        costs=costs,
        config=BacktestConfig(starting_cash=Decimal(cash)),
        strategy_id="test-strategy",
    )


class LookAheadTests(unittest.TestCase):
    def test_window_only_reaches_the_decision_session(self) -> None:
        series = flat_series(["100", "101", "102", "103"])
        strategy = RecordingStrategy()
        run(series, strategy)
        self.assertEqual(
            strategy.cutoffs,
            [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)],
            "the final bar must not produce a decision; nothing could fill it",
        )
        self.assertEqual(strategy.window_lengths, [1, 2, 3])

    def test_asking_for_a_future_bar_raises(self) -> None:
        series = flat_series(["100", "101", "102"])
        with self.assertRaises(LookAheadError):
            run(series, PeekingStrategy())

    def test_window_serves_past_sessions(self) -> None:
        series = flat_series(["100", "101", "102"])
        window = BarWindow(
            security_id=SECURITY_ID,
            currency="USD",
            bars=series.bars[:2],
        )
        self.assertEqual(window.at(date(2026, 1, 5)).close, Decimal("100"))
        self.assertEqual(window.mean_close(2), Decimal("100.5"))
        self.assertIsNone(window.mean_close(5))

    def test_fills_use_the_next_open_not_the_decision_close(self) -> None:
        # Decision on 05 close (100); 06 opens at 200. A look-ahead engine would
        # buy at 100 and book an instant gain.
        series = flat_series(["100", "150"], opens=["100", "200"])
        result = run(series, AlwaysLong())
        self.assertEqual(result.trades[0].fill_price, Decimal("200"))
        self.assertEqual(result.trades[0].quantity, 50)


class LongOnlyTests(unittest.TestCase):
    def test_short_target_is_rejected(self) -> None:
        with self.assertRaises(QuantContractError) as caught:
            run(flat_series(["100", "101"]), ShortingStrategy())
        self.assertIn("long-only", str(caught.exception))

    def test_leverage_is_rejected(self) -> None:
        with self.assertRaises(QuantContractError) as caught:
            run(flat_series(["100", "101"]), LeveredStrategy())
        self.assertIn("leverage", str(caught.exception))

    def test_float_target_is_rejected(self) -> None:
        with self.assertRaises(QuantContractError):
            run(flat_series(["100", "101"]), FloatStrategy())


class CostTests(unittest.TestCase):
    def test_costs_are_applied_exactly(self) -> None:
        series = flat_series(["100", "100"], opens=["100", "100"])
        result = run(series, AlwaysLong(), costs=RETAIL)
        trade = result.trades[0]
        self.assertEqual(trade.side, "buy")
        self.assertEqual(trade.fill_price, Decimal("100.100000"))
        self.assertEqual(trade.quantity, 99)
        self.assertEqual(trade.charges.commission, Decimal("1.00"))
        self.assertEqual(trade.charges.transaction_cost, Decimal("4.95"))
        self.assertEqual(trade.cash_after, Decimal("84.15"))
        self.assertEqual(trade.slippage_cost, Decimal("9.900000"))
        self.assertEqual(result.final_equity, Decimal("9984.15"))

    def test_zero_cost_run_beats_the_costed_run(self) -> None:
        series = flat_series(["100", "100", "110"])
        free = run(series, AlwaysLong(), costs=FREE)
        costed = run(series, AlwaysLong(), costs=RETAIL)
        self.assertGreater(free.final_equity, costed.final_equity)
        self.assertGreater(costed.total_commission, Decimal(0))
        self.assertGreater(costed.total_transaction_cost, Decimal(0))
        self.assertGreater(costed.total_slippage_cost, Decimal(0))

    def test_slippage_moves_the_price_against_the_trader(self) -> None:
        self.assertEqual(RETAIL.fill_price(Decimal("100"), "buy"), Decimal("100.100000"))
        self.assertEqual(RETAIL.fill_price(Decimal("100"), "sell"), Decimal("99.900000"))

    def test_cost_inputs_reject_negative_values(self) -> None:
        with self.assertRaises(QuantContractError):
            CostModel(
                commission_per_share=Decimal("-0.01"),
                commission_bps=Decimal("0"),
                commission_minimum=Decimal("0"),
                transaction_cost_bps=Decimal("0"),
                slippage_bps=Decimal("0"),
            )

    def test_charges_require_a_positive_share_count(self) -> None:
        with self.assertRaises(QuantContractError):
            RETAIL.charges(quantity=0, fill_price=Decimal("100"))


class ExecutionTests(unittest.TestCase):
    def test_buy_and_hold_arithmetic_is_exact(self) -> None:
        series = flat_series(["100", "100", "110"])
        result = run(series, AlwaysLong())
        self.assertEqual([trade.side for trade in result.trades], ["buy"])
        self.assertEqual(result.trades[0].quantity, 100)
        self.assertEqual(result.final_equity, Decimal("11000.00"))
        self.assertEqual(result.total_return, Decimal("0.100000"))

    def test_exiting_sells_the_whole_position(self) -> None:
        class ExitOnSecondDecision:
            def __init__(self) -> None:
                self.calls = 0

            def target_exposure(self, window: BarWindow) -> Decimal:
                self.calls += 1
                return Decimal(1) if self.calls == 1 else Decimal(0)

        series = flat_series(["100", "100", "120"])
        result = run(series, ExitOnSecondDecision())
        self.assertEqual([trade.side for trade in result.trades], ["buy", "sell"])
        self.assertEqual(result.trades[1].quantity, 100)
        self.assertEqual(result.equity_curve[-1].shares, 0)

    def test_flat_strategy_never_trades(self) -> None:
        result = run(flat_series(["100", "150", "200"]), AlwaysFlat())
        self.assertEqual(result.trades, ())
        self.assertEqual(result.final_equity, Decimal("10000.00"))
        self.assertEqual(result.total_return, Decimal("0"))

    def test_position_never_exceeds_available_cash(self) -> None:
        series = flat_series(["100", "100"])
        result = run(series, AlwaysLong(), costs=RETAIL, cash="150")
        self.assertEqual(result.trades[0].quantity, 1)
        self.assertGreaterEqual(result.equity_curve[-1].cash, Decimal(0))

    def test_cash_too_small_for_one_share_trades_nothing(self) -> None:
        series = flat_series(["100", "100"])
        result = run(series, AlwaysLong(), costs=RETAIL, cash="50")
        self.assertEqual(result.trades, ())

    def test_max_drawdown_is_measured_on_the_equity_curve(self) -> None:
        series = flat_series(["100", "100", "50", "100"])
        result = run(series, AlwaysLong())
        self.assertEqual(result.max_drawdown, Decimal("0.500000"))


class ReproducibilityTests(unittest.TestCase):
    def test_identical_inputs_produce_an_identical_hash(self) -> None:
        series = flat_series(["100", "101", "102", "99", "105"])
        first = run(series, AlwaysLong(), costs=RETAIL)
        second = run(series, AlwaysLong(), costs=RETAIL)
        self.assertEqual(first.content_sha256, second.content_sha256)
        self.assertEqual(first.to_record(), second.to_record())

    def test_changing_costs_changes_the_hash(self) -> None:
        series = flat_series(["100", "101", "102"])
        self.assertNotEqual(
            run(series, AlwaysLong(), costs=FREE).content_sha256,
            run(series, AlwaysLong(), costs=RETAIL).content_sha256,
        )

    def test_the_record_pins_the_inputs_that_produced_it(self) -> None:
        series = flat_series(["100", "101", "102"])
        record = run(series, AlwaysLong(), costs=RETAIL).to_record()
        self.assertEqual(record["series_sha256"], series.content_sha256)
        self.assertEqual(record["security_id"], SECURITY_ID)
        self.assertEqual(record["strategy_id"], "test-strategy")
        self.assertEqual(record["config"]["engine_version"], "quant-backtest-1")

    def test_starting_cash_must_be_positive(self) -> None:
        with self.assertRaises(QuantContractError):
            BacktestConfig(starting_cash=Decimal("0"))

    def test_strategy_id_is_required(self) -> None:
        with self.assertRaises(QuantContractError):
            run_backtest(
                series=flat_series(["100", "101"]),
                strategy=AlwaysLong(),
                costs=FREE,
                config=BacktestConfig(starting_cash=Decimal("1000")),
                strategy_id="  ",
            )


class IsolationTests(unittest.TestCase):
    def test_quant_imports_no_other_bounded_context(self) -> None:
        import pathlib

        package = (
            pathlib.Path(__file__).resolve().parents[1]
            / "src"
            / "investment_research_os"
            / "quant"
        )
        forbidden = (
            "moomoo",
            "portfolio",
            "research_runs",
            "evidence_bundles",
            "committee",
            "readiness",
            "workers.",
            "supabase",
        )
        for path in package.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            for line in source.splitlines():
                stripped = line.strip()
                if not (stripped.startswith("import ") or stripped.startswith("from ")):
                    continue
                for term in forbidden:
                    self.assertNotIn(
                        term,
                        stripped,
                        f"{path.name} imports {term}; Quant shares only security_id",
                    )


if __name__ == "__main__":
    unittest.main()

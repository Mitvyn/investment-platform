from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext

from investment_research_os.quant import (
    BacktestConfig,
    BarSeries,
    BarWindow,
    CorporateActionSet,
    CostModel,
    LookAheadError,
    OhlcvBar,
    ParticipationLimit,
    PointInTimeDataset,
    QuantContractError,
    StockSplit,
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

NO_ACTIONS = CorporateActionSet(
    security_id=SECURITY_ID,
    source="fixture-none",
    actions=(),
)
STRATEGY_CONFIG_SHA256 = "a" * 64
FULL_SESSION_LIQUIDITY = ParticipationLimit(
    max_participation_bps=Decimal("10000"),
    volume_basis="execution_bar",
    zero_volume_policy="block",
    unfilled_policy="cancel",
    min_fill_shares=0,
)


def flat_series(
    closes: list[str],
    *,
    opens: list[str] | None = None,
    volumes: list[int] | None = None,
) -> BarSeries:
    opens = opens or closes
    volumes = volumes or [1_000] * len(closes)
    start = date(2026, 1, 5)
    bars = []
    for index, (open_, close, volume) in enumerate(zip(opens, closes, volumes)):
        high = max(Decimal(open_), Decimal(close))
        low = min(Decimal(open_), Decimal(close))
        bars.append(
            OhlcvBar(
                session=start + timedelta(days=index),
                open=Decimal(open_),
                high=high,
                low=low,
                close=close,
                volume=volume,
            )
        )
    return BarSeries(
        security_id=SECURITY_ID,
        currency="USD",
        interval="1d",
        price_basis="unadjusted",
        source="fixture",
        bars=tuple(bars),
    )


class AlwaysLong:
    def target_exposure(self, window: BarWindow) -> Decimal:
        return Decimal(1)


class AlwaysFlat:
    def target_exposure(self, window: BarWindow) -> Decimal:
        return Decimal(0)


class HalfLong:
    def target_exposure(self, window: BarWindow) -> Decimal:
        return Decimal("0.5")


class LongThenFlat:
    def target_exposure(self, window: BarWindow) -> Decimal:
        return Decimal(1) if len(window.bars) == 1 else Decimal(0)


class LongThenHalf:
    def target_exposure(self, window: BarWindow) -> Decimal:
        return Decimal(1) if len(window.bars) == 1 else Decimal("0.5")


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


class RecordingActionStrategy:
    def __init__(self) -> None:
        self.visible_action_sessions: list[tuple[date, ...]] = []

    def target_exposure(self, window: BarWindow) -> Decimal:
        self.visible_action_sessions.append(
            tuple(action.effective_session for action in window.corporate_actions)
        )
        return Decimal(0)


class ShortingStrategy:
    def target_exposure(self, window: BarWindow) -> Decimal:
        return Decimal("-1")


class LeveredStrategy:
    def target_exposure(self, window: BarWindow) -> Decimal:
        return Decimal("1.5")


class FloatStrategy:
    def target_exposure(self, window: BarWindow) -> Decimal:
        return 0.5  # type: ignore[return-value]


def run(
    source: object,
    strategy: object,
    costs: CostModel = FREE,
    cash: str = "10000",
    corporate_actions: CorporateActionSet = NO_ACTIONS,
    liquidity: ParticipationLimit = FULL_SESSION_LIQUIDITY,
):
    dataset = (
        source
        if isinstance(source, PointInTimeDataset)
        else make_dataset(source, corporate_actions)  # type: ignore[arg-type]
    )
    return run_backtest(
        dataset=dataset,  # type: ignore[arg-type]
        strategy=strategy,  # type: ignore[arg-type]
        costs=costs,
        liquidity=liquidity,
        config=BacktestConfig(
            starting_cash=Decimal(cash),
            fractional_share_policy="error",
        ),
        strategy_id="test-strategy",
        strategy_config_sha256=STRATEGY_CONFIG_SHA256,
    )


class LookAheadTests(unittest.TestCase):
    def test_window_never_exposes_future_corporate_actions(self) -> None:
        series = flat_series(["100", "50", "10"])
        actions = CorporateActionSet(
            security_id=SECURITY_ID,
            source="fixture-actions",
            actions=(
                StockSplit(date(2026, 1, 6), 2, 1),
                StockSplit(date(2026, 1, 7), 5, 1),
            ),
        )
        strategy = RecordingActionStrategy()

        run(series, strategy, corporate_actions=actions)

        self.assertEqual(
            strategy.visible_action_sessions,
            [(), (date(2026, 1, 6),)],
        )

    def test_window_adjusts_historical_closes_for_effective_splits_only(self) -> None:
        series = flat_series(["100", "50", "10"])
        first_split = StockSplit(date(2026, 1, 6), 2, 1)
        future_split = StockSplit(date(2026, 1, 7), 5, 1)
        window = BarWindow(
            security_id=SECURITY_ID,
            currency="USD",
            bars=series.bars[:2],
            corporate_actions=(first_split,),
        )

        with self.assertRaises(TypeError):
            window.closes()
        self.assertEqual(
            window.closes(basis="split_adjusted"),
            (Decimal("50"), Decimal("50")),
        )
        self.assertEqual(
            window.unadjusted_closes(),
            (Decimal("100"), Decimal("50")),
        )
        self.assertEqual(window.mean_close(2, basis="split_adjusted"), Decimal("50"))
        self.assertEqual(window.mean_close(2, basis="unadjusted"), Decimal("75"))
        self.assertNotIn(future_split, window.corporate_actions)

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
        self.assertEqual(window.mean_close(2, basis="unadjusted"), Decimal("100.5"))
        self.assertIsNone(window.mean_close(5, basis="split_adjusted"))

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
        self.assertEqual(
            RETAIL.fill_price(Decimal("100"), "buy"), Decimal("100.100000")
        )
        self.assertEqual(
            RETAIL.fill_price(Decimal("100"), "sell"), Decimal("99.900000")
        )

    def test_slippage_cannot_quantize_a_sell_fill_to_zero(self) -> None:
        costs = CostModel(
            commission_per_share="0",
            commission_bps="0",
            commission_minimum="0",
            transaction_cost_bps="0",
            slippage_bps="9999",
        )

        with self.assertRaisesRegex(QuantContractError, "below price quantum"):
            costs.fill_price(Decimal("0.000001"), "sell")

        series = flat_series(["0.000001", "0.000001", "0.000001"])
        with self.assertRaisesRegex(QuantContractError, "below price quantum"):
            run(series, LongThenFlat(), costs=costs, cash="0.01")

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
    def test_cash_limited_buy_records_shortfall(self) -> None:
        result = run(flat_series(["100", "100"]), AlwaysLong(), costs=RETAIL)

        attempt = result.fill_attempts[0]
        self.assertEqual(attempt.requested_quantity, 100)
        self.assertEqual(attempt.participation_cap, 1_000)
        self.assertEqual(attempt.affordable_quantity, 99)
        self.assertEqual(attempt.filled_quantity, 99)
        self.assertEqual(attempt.unfilled_quantity, 1)
        self.assertEqual(attempt.limit_reason, "cash_capped")

    def test_participation_cap_limits_buy_and_records_cancelled_residual(self) -> None:
        limit = ParticipationLimit(
            max_participation_bps=Decimal("100"),
            volume_basis="execution_bar",
            zero_volume_policy="block",
            unfilled_policy="cancel",
            min_fill_shares=0,
        )
        result = run(
            flat_series(["100", "100"], volumes=[1_000, 1_000]),
            AlwaysLong(),
            liquidity=limit,
        )

        attempt = result.fill_attempts[0]
        self.assertEqual(attempt.participation_cap, 10)
        self.assertEqual(attempt.requested_quantity, 100)
        self.assertEqual(attempt.filled_quantity, 10)
        self.assertEqual(attempt.unfilled_quantity, 90)
        self.assertEqual(attempt.limit_reason, "participation_capped")
        self.assertEqual(result.trades[0].quantity, 10)

    def test_zero_volume_policy_records_blocked_attempt_or_fails_closed(self) -> None:
        blocked = ParticipationLimit(
            max_participation_bps=Decimal("10000"),
            volume_basis="execution_bar",
            zero_volume_policy="block",
            unfilled_policy="cancel",
            min_fill_shares=0,
        )
        result = run(
            flat_series(["100", "100"], volumes=[1_000, 0]),
            AlwaysLong(),
            liquidity=blocked,
        )
        attempt = result.fill_attempts[0]
        self.assertEqual(attempt.filled_quantity, 0)
        self.assertEqual(attempt.limit_reason, "zero_volume_blocked")
        self.assertEqual(result.trades, ())

        rejected = ParticipationLimit(
            max_participation_bps=Decimal("10000"),
            volume_basis="execution_bar",
            zero_volume_policy="error",
            unfilled_policy="cancel",
            min_fill_shares=0,
        )
        with self.assertRaisesRegex(QuantContractError, "zero-volume"):
            run(
                flat_series(["100", "100"], volumes=[1_000, 0]),
                AlwaysLong(),
                liquidity=rejected,
            )

    def test_zero_volume_block_does_not_price_an_order_that_cannot_fill(self) -> None:
        adverse_slippage = CostModel(
            commission_per_share="0",
            commission_bps="0",
            commission_minimum="0",
            transaction_cost_bps="0",
            slippage_bps="9999",
        )
        result = run(
            flat_series(
                ["0.000001", "0.000001", "0.000001"],
                volumes=[1_000, 1_000, 0],
            ),
            LongThenFlat(),
            costs=adverse_slippage,
            cash="0.01",
        )

        self.assertEqual(result.fill_attempts[1].limit_reason, "zero_volume_blocked")
        self.assertEqual(result.fill_attempts[1].filled_quantity, 0)

    def test_nonzero_volume_that_rounds_to_zero_is_participation_capped(self) -> None:
        limit = ParticipationLimit(
            max_participation_bps=Decimal("1"),
            volume_basis="execution_bar",
            zero_volume_policy="block",
            unfilled_policy="cancel",
            min_fill_shares=0,
        )
        result = run(
            flat_series(["100", "100"], volumes=[1_000, 100]),
            AlwaysLong(),
            liquidity=limit,
        )

        attempt = result.fill_attempts[0]
        self.assertEqual(attempt.participation_cap, 0)
        self.assertEqual(attempt.limit_reason, "participation_capped")
        self.assertEqual(attempt.filled_quantity, 0)

    def test_participation_cap_applies_to_sell_and_keeps_residual_position(
        self,
    ) -> None:
        limit = ParticipationLimit(
            max_participation_bps=Decimal("1000"),
            volume_basis="execution_bar",
            zero_volume_policy="block",
            unfilled_policy="cancel",
            min_fill_shares=0,
        )
        result = run(
            flat_series(["100", "100", "100"], volumes=[1_000, 1_000, 10]),
            LongThenFlat(),
            liquidity=limit,
        )

        attempt = result.fill_attempts[1]
        self.assertEqual(attempt.side, "sell")
        self.assertEqual(attempt.filled_quantity, 1)
        self.assertEqual(attempt.limit_reason, "participation_capped")
        self.assertEqual(result.equity_curve[-1].shares, 99)

    def test_minimum_fill_prevents_uneconomic_partial_fill(self) -> None:
        limit = ParticipationLimit(
            max_participation_bps=Decimal("100"),
            volume_basis="execution_bar",
            zero_volume_policy="block",
            unfilled_policy="cancel",
            min_fill_shares=10,
        )
        result = run(
            flat_series(["100", "100"], volumes=[1_000, 500]),
            AlwaysLong(),
            liquidity=limit,
        )

        attempt = result.fill_attempts[0]
        self.assertEqual(attempt.participation_cap, 5)
        self.assertEqual(attempt.filled_quantity, 0)
        self.assertEqual(attempt.unfilled_quantity, 100)
        self.assertEqual(attempt.limit_reason, "participation_capped")

    def test_split_applies_before_capping_post_split_rebalance(self) -> None:
        limit = ParticipationLimit(
            max_participation_bps=Decimal("1000"),
            volume_basis="execution_bar",
            zero_volume_policy="block",
            unfilled_policy="cancel",
            min_fill_shares=0,
        )
        actions = CorporateActionSet(
            security_id=SECURITY_ID,
            source="fixture-actions",
            actions=(StockSplit(date(2026, 1, 7), 2, 1),),
        )
        result = run(
            flat_series(
                ["100", "100", "50"],
                opens=["100", "100", "50"],
                volumes=[1_000, 1_000, 100],
            ),
            LongThenHalf(),
            corporate_actions=actions,
            liquidity=limit,
        )

        attempt = result.fill_attempts[1]
        self.assertEqual(attempt.requested_quantity, 100)
        self.assertEqual(attempt.participation_cap, 10)
        self.assertEqual(attempt.filled_quantity, 10)
        self.assertEqual(result.equity_curve[-1].shares, 190)

    def test_residual_is_cancelled_and_next_decision_is_rederived(self) -> None:
        limit = ParticipationLimit(
            max_participation_bps=Decimal("100"),
            volume_basis="execution_bar",
            zero_volume_policy="block",
            unfilled_policy="cancel",
            min_fill_shares=0,
        )
        result = run(
            flat_series(
                ["100", "100", "100"],
                volumes=[1_000, 1_000, 10_000],
            ),
            LongThenHalf(),
            liquidity=limit,
        )

        self.assertEqual(result.fill_attempts[0].requested_quantity, 100)
        self.assertEqual(result.fill_attempts[0].filled_quantity, 10)
        self.assertEqual(result.fill_attempts[1].requested_quantity, 40)
        self.assertEqual(result.fill_attempts[1].filled_quantity, 40)

    def test_corporate_actions_must_match_security_and_transition_session(self) -> None:
        series = flat_series(["100", "100"])
        foreign = CorporateActionSet(
            security_id="6f9e2186-cff9-4af8-8720-283fedcf4abc",
            source="fixture-actions",
            actions=(),
        )
        with self.assertRaisesRegex(QuantContractError, "security_id"):
            run(series, AlwaysLong(), corporate_actions=foreign)

        first_session = CorporateActionSet(
            security_id=SECURITY_ID,
            source="fixture-actions",
            actions=(StockSplit(date(2026, 1, 5), 2, 1),),
        )
        with self.assertRaisesRegex(QuantContractError, "transition session"):
            run(series, AlwaysLong(), corporate_actions=first_session)

        # An action dated after the last bar can no longer reach the engine at
        # all: the dataset receipt refuses it first, which is the stricter and
        # earlier of the two guards.
        outside = CorporateActionSet(
            security_id=SECURITY_ID,
            source="fixture-actions",
            actions=(StockSplit(date(2026, 1, 9), 2, 1),),
        )
        with self.assertRaisesRegex(QuantContractError, "cutoff"):
            run(series, AlwaysLong(), corporate_actions=outside)

    def test_split_adjusts_held_shares_before_next_open_rebalance(self) -> None:
        series = flat_series(
            ["100", "100", "50"],
            opens=["100", "100", "50"],
        )
        actions = CorporateActionSet(
            security_id=SECURITY_ID,
            source="fixture-actions",
            actions=(StockSplit(date(2026, 1, 7), 2, 1),),
        )

        result = run(series, AlwaysLong(), corporate_actions=actions)

        self.assertEqual([trade.side for trade in result.trades], ["buy"])
        self.assertEqual(result.equity_curve[-1].shares, 200)
        self.assertEqual(result.final_equity, Decimal("10000.00"))
        self.assertEqual(result.corporate_action_applications[0].shares_before, 100)
        self.assertEqual(result.corporate_action_applications[0].shares_after, 200)

    def test_reverse_split_requires_integral_whole_share_entitlement(self) -> None:
        series = flat_series(
            ["100", "100", "300"],
            opens=["100", "100", "300"],
        )
        actions = CorporateActionSet(
            security_id=SECURITY_ID,
            source="fixture-actions",
            actions=(StockSplit(date(2026, 1, 7), 1, 3),),
        )

        with self.assertRaisesRegex(QuantContractError, "fractional shares"):
            run(series, AlwaysLong(), corporate_actions=actions)

        exact = run(
            series,
            AlwaysLong(),
            cash="9900",
            corporate_actions=actions,
        )
        self.assertEqual(exact.corporate_action_applications[0].shares_after, 33)
        self.assertEqual(exact.final_equity, Decimal("9900.00"))

    def test_fractional_share_policy_is_explicit_and_fail_closed(self) -> None:
        with self.assertRaisesRegex(QuantContractError, "fractional_share_policy"):
            BacktestConfig(
                starting_cash=Decimal("1000"),
                fractional_share_policy="round_down_forfeit",  # type: ignore[arg-type]
            )

    def test_full_exposure_target_does_not_sell_because_of_buy_slippage(self) -> None:
        high_slippage = CostModel(
            commission_per_share="0",
            commission_bps="0",
            commission_minimum="0",
            transaction_cost_bps="0",
            slippage_bps="5000",
        )
        series = flat_series(
            ["100", "100", "200"],
            opens=["100", "100", "200"],
        )

        result = run(series, AlwaysLong(), costs=high_slippage)

        self.assertEqual([trade.side for trade in result.trades], ["buy"])

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
    def test_corporate_action_input_and_zero_position_application_are_pinned(
        self,
    ) -> None:
        series = flat_series(["100", "50"])
        actions = CorporateActionSet(
            security_id=SECURITY_ID,
            source="fixture-actions",
            actions=(StockSplit(date(2026, 1, 6), 2, 1),),
        )
        with_action = run(
            series,
            AlwaysFlat(),
            corporate_actions=actions,
        )
        without_action = run(series, AlwaysFlat())

        self.assertEqual(
            with_action.to_record()["corporate_actions_sha256"],
            actions.content_sha256,
        )
        self.assertEqual(
            with_action.corporate_action_applications[0].shares_before,
            0,
        )
        self.assertEqual(
            with_action.corporate_action_applications[0].shares_after,
            0,
        )
        self.assertNotEqual(with_action.content_sha256, without_action.content_sha256)

    def test_liquidity_and_provenance_are_pinned(self) -> None:
        constrained = ParticipationLimit(
            max_participation_bps=Decimal("100"),
            volume_basis="execution_bar",
            zero_volume_policy="block",
            unfilled_policy="cancel",
            min_fill_shares=0,
        )
        series = flat_series(
            ["100", "100", "100"],
            volumes=[1_000, 1_000, 1_000],
        )
        constrained_result = run(series, LongThenFlat(), liquidity=constrained)
        unlimited_result = run(series, LongThenFlat())

        self.assertEqual(
            constrained_result.to_record()["liquidity_sha256"],
            constrained.content_sha256,
        )
        self.assertNotEqual(
            constrained_result.content_sha256,
            unlimited_result.content_sha256,
        )
        self.assertEqual(
            [decision.decision_index for decision in constrained_result.decisions],
            [0, 1],
        )
        self.assertEqual(
            [attempt.decision_index for attempt in constrained_result.fill_attempts],
            [0, 1],
        )
        self.assertEqual(
            [trade.decision_index for trade in constrained_result.trades],
            [0, 1],
        )
        self.assertEqual(
            constrained_result.total_unfilled_shares,
            sum(
                attempt.unfilled_quantity
                for attempt in constrained_result.fill_attempts
            ),
        )
        self.assertEqual(constrained_result.constrained_decision_count, 1)

    def test_target_trace_distinguishes_strategies_without_fills(self) -> None:
        series = flat_series(["100", "100"])
        flat = run(series, AlwaysFlat(), cash="50")
        half = run(series, HalfLong(), cash="50")

        self.assertEqual(flat.trades, ())
        self.assertEqual(half.trades, ())
        self.assertNotEqual(flat.to_record(), half.to_record())
        self.assertNotEqual(flat.content_sha256, half.content_sha256)

    def test_result_does_not_depend_on_ambient_decimal_precision(self) -> None:
        series = flat_series(
            ["1.23456789", "1.34567891", "1.45678912"],
        )
        with localcontext() as context:
            context.prec = 6
            low_precision = run(series, AlwaysLong(), costs=RETAIL)
        with localcontext() as context:
            context.prec = 28
            normal_precision = run(series, AlwaysLong(), costs=RETAIL)

        self.assertEqual(low_precision.to_record(), normal_precision.to_record())
        self.assertEqual(low_precision.content_sha256, normal_precision.content_sha256)

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
        self.assertEqual(record["strategy_config_sha256"], STRATEGY_CONFIG_SHA256)
        self.assertEqual(record["config"]["engine_version"], "quant-backtest-4")
        self.assertEqual(record["config"]["fractional_share_policy"], "error")

    def test_starting_cash_must_be_positive(self) -> None:
        with self.assertRaises(QuantContractError):
            BacktestConfig(
                starting_cash=Decimal("0"),
                fractional_share_policy="error",
            )

    def test_strategy_id_is_required(self) -> None:
        with self.assertRaises(QuantContractError):
            run_backtest(
                dataset=make_dataset(flat_series(["100", "101"])),
                strategy=AlwaysLong(),
                costs=FREE,
                liquidity=FULL_SESSION_LIQUIDITY,
                config=BacktestConfig(
                    starting_cash=Decimal("1000"),
                    fractional_share_policy="error",
                ),
                strategy_id="  ",
                strategy_config_sha256=STRATEGY_CONFIG_SHA256,
            )

    def test_strategy_configuration_hash_is_required(self) -> None:
        with self.assertRaisesRegex(
            QuantContractError, "strategy_config_sha256 must be"
        ):
            run_backtest(
                dataset=make_dataset(flat_series(["100", "101"])),
                strategy=AlwaysLong(),
                costs=FREE,
                liquidity=FULL_SESSION_LIQUIDITY,
                config=BacktestConfig(
                    starting_cash=Decimal("1000"),
                    fractional_share_policy="error",
                ),
                strategy_id="always-long.v1",
                strategy_config_sha256="A" * 64,
            )


SOURCE_HASH = "b" * 64


def make_dataset(
    series: BarSeries,
    corporate_actions: CorporateActionSet = NO_ACTIONS,
    **overrides: object,
) -> PointInTimeDataset:
    """Wrap fixtures in the receipt the engine now requires."""

    base: dict[str, object] = {
        "series": series,
        "corporate_actions": corporate_actions,
        "as_of_cutoff": series.bars[-1].session,
        "source_id": "fixture-source",
        "source_revision": "rev-1",
        "source_content_sha256": SOURCE_HASH,
        "coverage_scope": "single_security",
    }
    base.update(overrides)
    return PointInTimeDataset(**base)  # type: ignore[arg-type]


class DatasetBoundaryTests(unittest.TestCase):
    def test_raw_series_and_actions_are_no_longer_accepted(self) -> None:
        with self.assertRaises(TypeError):
            run_backtest(  # type: ignore[call-arg]
                series=flat_series(["100", "101"]),
                strategy=AlwaysLong(),
                costs=FREE,
                corporate_actions=NO_ACTIONS,
                liquidity=FULL_SESSION_LIQUIDITY,
                config=BacktestConfig(
                    starting_cash=Decimal("1000"),
                    fractional_share_policy="error",
                ),
                strategy_id="always-long.v1",
                strategy_config_sha256=STRATEGY_CONFIG_SHA256,
            )

    def test_the_result_pins_the_dataset_hash(self) -> None:
        dataset = make_dataset(flat_series(["100", "101"]))
        result = run(dataset, AlwaysLong())
        self.assertEqual(result.dataset_sha256, dataset.content_sha256)
        self.assertEqual(
            result.to_record()["dataset_sha256"], dataset.content_sha256
        )
        self.assertEqual(result.to_record()["engine_version"], "quant-backtest-4")

    def test_source_revision_alone_changes_the_result_hash(self) -> None:
        series = flat_series(["100", "101"])
        first = run(make_dataset(series), AlwaysLong())
        second = run(make_dataset(series, source_revision="rev-2"), AlwaysLong())
        self.assertEqual(first.series_sha256, second.series_sha256)
        self.assertNotEqual(first.content_sha256, second.content_sha256)

    def test_source_content_hash_alone_changes_the_result_hash(self) -> None:
        series = flat_series(["100", "101"])
        first = run(make_dataset(series), AlwaysLong())
        second = run(
            make_dataset(series, source_content_sha256="c" * 64), AlwaysLong()
        )
        self.assertNotEqual(first.content_sha256, second.content_sha256)

    def test_a_bar_after_the_cutoff_is_refused_before_the_strategy_runs(self) -> None:
        # The dataclass would have refused this at construction, so the only
        # way to reach the engine guard is to mutate a valid dataset. The
        # engine must not trust an upstream check it cannot see.
        dataset = make_dataset(flat_series(["100", "101", "102"]))
        object.__setattr__(dataset, "as_of_cutoff", dataset.series.bars[0].session)
        strategy = RecordingStrategy()
        with self.assertRaisesRegex(QuantContractError, "cutoff"):
            run(dataset, strategy)
        self.assertEqual(strategy.cutoffs, [])

    def test_an_action_after_the_cutoff_is_refused_before_the_strategy_runs(
        self,
    ) -> None:
        series = flat_series(["100", "101", "102"])
        actions = CorporateActionSet(
            security_id=SECURITY_ID,
            source="fixture-actions",
            actions=(StockSplit(date(2026, 1, 7), 2, 1),),
        )
        dataset = make_dataset(series, actions)
        object.__setattr__(dataset, "as_of_cutoff", date(2026, 1, 6))
        strategy = RecordingStrategy()
        with self.assertRaisesRegex(QuantContractError, "cutoff"):
            run(dataset, strategy)
        self.assertEqual(strategy.cutoffs, [])

    def test_a_non_dataset_input_is_refused(self) -> None:
        with self.assertRaisesRegex(QuantContractError, "PointInTimeDataset"):
            run_backtest(
                dataset=flat_series(["100", "101"]),  # type: ignore[arg-type]
                strategy=AlwaysLong(),
                costs=FREE,
                liquidity=FULL_SESSION_LIQUIDITY,
                config=BacktestConfig(
                    starting_cash=Decimal("1000"),
                    fractional_share_policy="error",
                ),
                strategy_id="always-long.v1",
                strategy_config_sha256=STRATEGY_CONFIG_SHA256,
            )

    def test_the_result_hash_ignores_the_ambient_decimal_context(self) -> None:
        dataset = make_dataset(flat_series(["100", "104", "99"]))
        baseline = run(dataset, AlwaysLong()).content_sha256
        for precision in (5, 60):
            with localcontext() as ctx:
                ctx.prec = precision
                self.assertEqual(run(dataset, AlwaysLong()).content_sha256, baseline)

    def test_a_split_still_applies_through_the_dataset(self) -> None:
        series = flat_series(["100", "50", "50"])
        actions = CorporateActionSet(
            security_id=SECURITY_ID,
            source="fixture-actions",
            actions=(StockSplit(date(2026, 1, 6), 2, 1),),
        )
        result = run(make_dataset(series, actions), AlwaysLong())
        applications = result.corporate_action_applications
        self.assertEqual(len(applications), 1)
        self.assertEqual(applications[0].shares_before * 2, applications[0].shares_after)

    def test_the_participation_cap_still_applies_through_the_dataset(self) -> None:
        capped = ParticipationLimit(
            max_participation_bps=Decimal("1"),
            volume_basis="execution_bar",
            zero_volume_policy="block",
            unfilled_policy="cancel",
            min_fill_shares=0,
        )
        result = run(
            make_dataset(flat_series(["100", "100"])),
            AlwaysLong(),
            liquidity=capped,
        )
        self.assertEqual(result.fill_attempts[0].limit_reason, "participation_capped")
        self.assertGreater(result.total_unfilled_shares, 0)

    def test_a_forged_receipt_field_is_refused_before_the_strategy_runs(self) -> None:
        # Frozen is not sealed. Every mutation below produces a dataset that
        # could never have been constructed, and each must be refused at the
        # boundary rather than silently hashed into a result.
        mutations: tuple[tuple[str, object], ...] = (
            ("source_content_sha256", "forged"),
            ("source_id", "   "),
            ("source_revision", ""),
            ("coverage_scope", "universe"),
            ("as_of_cutoff", datetime(2026, 1, 6, 20, 0)),
            ("series", object()),
            ("corporate_actions", object()),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                dataset = make_dataset(flat_series(["100", "101"]))
                object.__setattr__(dataset, field, value)
                strategy = RecordingStrategy()
                with self.assertRaises(QuantContractError):
                    run(dataset, strategy)
                self.assertEqual(strategy.cutoffs, [])

    def test_a_valid_receipt_still_runs_after_the_recheck(self) -> None:
        dataset = make_dataset(flat_series(["100", "104", "99"]))
        baseline = run(dataset, AlwaysLong())
        self.assertEqual(baseline.dataset_sha256, dataset.content_sha256)
        for precision in (5, 60):
            with localcontext() as ctx:
                ctx.prec = precision
                self.assertEqual(
                    run(dataset, AlwaysLong()).content_sha256, baseline.content_sha256
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

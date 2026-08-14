"""Deterministic long-only backtest engine.

The engine supplies each strategy a :class:`BarWindow` containing only data
available through the decision session. Python cannot prevent a strategy from
capturing external or future state, so callers must use audited deterministic
strategies. The recorded strategy-configuration hash and complete decision
trace make such drift visible; they do not sandbox arbitrary strategy code.

The engine itself uses no clock, network, or randomness. Given deterministic
strategy behavior, the same declared inputs produce the same content hash.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
import re
from typing import Protocol

from investment_research_os.quant.bars import (
    BarSeries,
    OhlcvBar,
    QuantContractError,
    canonical_sha256,
    decimal_text,
    quant_decimal_context,
    to_decimal,
)
from investment_research_os.quant.costs import CASH_QUANTUM, CostModel, TradeCharges
from investment_research_os.quant.corporate_actions import (
    CorporateActionSet,
    StockSplit,
)

ENGINE_VERSION = "quant-backtest-2"
RATIO_QUANTUM = Decimal("0.000001")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class LookAheadError(QuantContractError):
    """Raised when a strategy asks for data it could not have had."""


@dataclass(frozen=True, slots=True)
class BarWindow:
    """The only view of history a strategy is given.

    ``bars`` ends at the decision session. There is no handle on later bars,
    and :meth:`at` refuses future sessions explicitly so that a strategy which
    tries to peek fails loudly instead of quietly scoring well.
    """

    security_id: str
    currency: str
    bars: tuple[OhlcvBar, ...]
    corporate_actions: tuple[StockSplit, ...] = ()

    @property
    def cutoff(self) -> date:
        return self.bars[-1].session

    @property
    def latest(self) -> OhlcvBar:
        return self.bars[-1]

    def closes(self) -> tuple[Decimal, ...]:
        return tuple(bar.close for bar in self.bars)

    def split_adjusted_closes(self) -> tuple[Decimal, ...]:
        """Historical closes expressed on latest visible share basis."""

        with quant_decimal_context():
            adjusted: list[Decimal] = []
            for bar in self.bars:
                close = bar.close
                for split in self.corporate_actions:
                    if split.effective_session > bar.session:
                        close = close * split.old_shares / split.new_shares
                adjusted.append(close)
            return tuple(adjusted)

    def at(self, session: date) -> OhlcvBar:
        if session > self.cutoff:
            raise LookAheadError(
                f"{session.isoformat()} is after the decision session "
                f"{self.cutoff.isoformat()}"
            )
        for bar in reversed(self.bars):
            if bar.session == session:
                return bar
        raise QuantContractError(f"no bar for {session.isoformat()}")

    def mean_close(self, periods: int) -> Decimal | None:
        """Trailing mean close, or None until enough history exists."""

        if isinstance(periods, bool) or not isinstance(periods, int) or periods <= 0:
            raise QuantContractError("periods must be a positive integer")
        if len(self.bars) < periods:
            return None
        window = self.bars[-periods:]
        return sum((bar.close for bar in window), Decimal(0)) / Decimal(periods)


class Strategy(Protocol):
    """Long-only target exposure as a fraction of equity, in [0, 1]."""

    def target_exposure(self, window: BarWindow) -> Decimal: ...


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    starting_cash: Decimal

    def __post_init__(self) -> None:
        value = to_decimal(self.starting_cash, field="starting_cash")
        if value <= 0:
            raise QuantContractError(f"starting_cash must be positive, got {value}")
        object.__setattr__(self, "starting_cash", value)

    def to_record(self) -> dict[str, str]:
        return {
            "engine_version": ENGINE_VERSION,
            "starting_cash": decimal_text(self.starting_cash),
        }


@dataclass(frozen=True, slots=True)
class Trade:
    session: date
    side: str
    quantity: int
    reference_price: Decimal
    fill_price: Decimal
    charges: TradeCharges
    slippage_cost: Decimal
    cash_after: Decimal
    shares_after: int

    def to_record(self) -> dict[str, object]:
        return {
            "cash_after": decimal_text(self.cash_after),
            "charges": self.charges.to_record(),
            "fill_price": decimal_text(self.fill_price),
            "quantity": self.quantity,
            "reference_price": decimal_text(self.reference_price),
            "session": self.session.isoformat(),
            "shares_after": self.shares_after,
            "side": self.side,
            "slippage_cost": decimal_text(self.slippage_cost),
        }


@dataclass(frozen=True, slots=True)
class StrategyDecision:
    decision_session: date
    execution_session: date
    target_exposure: Decimal

    def to_record(self) -> dict[str, str]:
        return {
            "decision_session": self.decision_session.isoformat(),
            "execution_session": self.execution_session.isoformat(),
            "target_exposure": decimal_text(self.target_exposure),
        }


@dataclass(frozen=True, slots=True)
class SplitApplication:
    session: date
    new_shares: int
    old_shares: int
    shares_before: int
    shares_after: int

    def to_record(self) -> dict[str, object]:
        return {
            "new_shares": self.new_shares,
            "old_shares": self.old_shares,
            "session": self.session.isoformat(),
            "shares_after": self.shares_after,
            "shares_before": self.shares_before,
            "type": "stock_split",
        }


@dataclass(frozen=True, slots=True)
class EquityPoint:
    session: date
    cash: Decimal
    shares: int
    equity: Decimal

    def to_record(self) -> dict[str, object]:
        return {
            "cash": decimal_text(self.cash),
            "equity": decimal_text(self.equity),
            "session": self.session.isoformat(),
            "shares": self.shares,
        }


@dataclass(frozen=True, slots=True)
class BacktestResult:
    security_id: str
    currency: str
    series_sha256: str
    config: BacktestConfig
    costs: CostModel
    corporate_actions: CorporateActionSet
    strategy_id: str
    strategy_config_sha256: str
    decisions: tuple[StrategyDecision, ...]
    corporate_action_applications: tuple[SplitApplication, ...]
    trades: tuple[Trade, ...]
    equity_curve: tuple[EquityPoint, ...]

    @property
    def final_equity(self) -> Decimal:
        return self.equity_curve[-1].equity

    @property
    def total_return(self) -> Decimal:
        with quant_decimal_context():
            start = self.config.starting_cash
            return ((self.final_equity - start) / start).quantize(
                RATIO_QUANTUM, rounding=ROUND_HALF_UP
            )

    @property
    def max_drawdown(self) -> Decimal:
        with quant_decimal_context():
            peak = self.equity_curve[0].equity
            worst = Decimal(0)
            for point in self.equity_curve:
                peak = max(peak, point.equity)
                if peak > 0:
                    worst = max(worst, (peak - point.equity) / peak)
            return worst.quantize(RATIO_QUANTUM, rounding=ROUND_HALF_UP)

    @property
    def total_commission(self) -> Decimal:
        with quant_decimal_context():
            return sum((trade.charges.commission for trade in self.trades), Decimal(0))

    @property
    def total_transaction_cost(self) -> Decimal:
        with quant_decimal_context():
            return sum(
                (trade.charges.transaction_cost for trade in self.trades), Decimal(0)
            )

    @property
    def total_slippage_cost(self) -> Decimal:
        with quant_decimal_context():
            return sum((trade.slippage_cost for trade in self.trades), Decimal(0))

    def to_record(self) -> dict[str, object]:
        """Canonical, reproducible output record."""

        return {
            "config": self.config.to_record(),
            "corporate_actions": self.corporate_actions.to_record(),
            "corporate_actions_sha256": self.corporate_actions.content_sha256,
            "costs": self.costs.to_record(),
            "currency": self.currency,
            "decisions": [decision.to_record() for decision in self.decisions],
            "equity_curve": [point.to_record() for point in self.equity_curve],
            "outcome": {
                "final_equity": decimal_text(self.final_equity),
                "max_drawdown": decimal_text(self.max_drawdown),
                "total_commission": decimal_text(self.total_commission),
                "total_return": decimal_text(self.total_return),
                "total_slippage_cost": decimal_text(self.total_slippage_cost),
                "total_transaction_cost": decimal_text(self.total_transaction_cost),
            },
            "security_id": self.security_id,
            "series_sha256": self.series_sha256,
            "strategy_id": self.strategy_id,
            "strategy_config_sha256": self.strategy_config_sha256,
            "corporate_action_applications": [
                application.to_record()
                for application in self.corporate_action_applications
            ],
            "trades": [trade.to_record() for trade in self.trades],
        }

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.to_record())


def _validated_target(value: object) -> Decimal:
    target = to_decimal(value, field="target_exposure")
    if target < 0:
        raise QuantContractError(
            f"target_exposure {target} is short; this engine is long-only"
        )
    if target > 1:
        raise QuantContractError(
            f"target_exposure {target} exceeds 1; this engine does not use leverage"
        )
    return target


def _affordable_quantity(
    *, wanted: int, price: Decimal, cash: Decimal, costs: CostModel
) -> int:
    """Largest quantity up to ``wanted`` whose gross plus charges fits in cash."""

    quantity = wanted
    while quantity > 0:
        charges = costs.charges(quantity=quantity, fill_price=price)
        total = price * quantity + charges.total
        if total <= cash:
            return quantity
        scaled = int(cash / total * quantity)
        quantity = min(quantity - 1, scaled)
    return 0


def run_backtest(
    *,
    series: BarSeries,
    strategy: Strategy,
    costs: CostModel,
    corporate_actions: CorporateActionSet,
    config: BacktestConfig,
    strategy_id: str,
    strategy_config_sha256: str,
) -> BacktestResult:
    """Run one deterministic long-only backtest.

    Decisions are taken on each bar's close and filled on the next bar's open.
    The final bar produces no decision, because there is no later bar to fill
    it — acting on the last close would be look-ahead.
    """

    with quant_decimal_context():
        return _run_backtest(
            series=series,
            strategy=strategy,
            costs=costs,
            corporate_actions=corporate_actions,
            config=config,
            strategy_id=strategy_id,
            strategy_config_sha256=strategy_config_sha256,
        )


def _run_backtest(
    *,
    series: BarSeries,
    strategy: Strategy,
    costs: CostModel,
    corporate_actions: CorporateActionSet,
    config: BacktestConfig,
    strategy_id: str,
    strategy_config_sha256: str,
) -> BacktestResult:
    if not isinstance(strategy_id, str) or not strategy_id.strip():
        raise QuantContractError("strategy_id must name the strategy under test")
    if not isinstance(strategy_config_sha256, str) or not _SHA256_PATTERN.fullmatch(
        strategy_config_sha256
    ):
        raise QuantContractError(
            "strategy_config_sha256 must be a lowercase SHA-256 digest"
        )
    if corporate_actions.security_id != series.security_id:
        raise QuantContractError(
            "corporate actions must match the bar-series security_id"
        )
    covered_action_sessions = {bar.session for bar in series.bars[1:]}
    if any(
        action.effective_session not in covered_action_sessions
        for action in corporate_actions.actions
    ):
        raise QuantContractError(
            "corporate action must match a covered transition session"
        )
    actions_by_session = {
        action.effective_session: action for action in corporate_actions.actions
    }

    cash = config.starting_cash
    shares = 0
    decisions: list[StrategyDecision] = []
    corporate_action_applications: list[SplitApplication] = []
    trades: list[Trade] = []
    equity_curve = [
        EquityPoint(
            session=series.bars[0].session,
            cash=cash,
            shares=0,
            equity=cash,
        )
    ]

    for index in range(len(series.bars) - 1):
        window = BarWindow(
            security_id=series.security_id,
            currency=series.currency,
            bars=series.bars[: index + 1],
            corporate_actions=tuple(
                action
                for action in corporate_actions.actions
                if action.effective_session <= series.bars[index].session
            ),
        )
        target = _validated_target(strategy.target_exposure(window))
        execution_bar = series.bars[index + 1]
        decisions.append(
            StrategyDecision(
                decision_session=window.cutoff,
                execution_session=execution_bar.session,
                target_exposure=target,
            )
        )
        reference = execution_bar.open

        split = actions_by_session.get(execution_bar.session)
        if split is not None:
            shares_before = shares
            split_numerator = shares * split.new_shares
            if split_numerator % split.old_shares != 0:
                raise QuantContractError(
                    "stock split creates fractional shares; cash-in-lieu is unsupported"
                )
            shares = split_numerator // split.old_shares
            corporate_action_applications.append(
                SplitApplication(
                    session=execution_bar.session,
                    new_shares=split.new_shares,
                    old_shares=split.old_shares,
                    shares_before=shares_before,
                    shares_after=shares,
                )
            )

        pre_trade_equity = cash + reference * shares
        buy_price = costs.fill_price(reference, "buy")
        desired = int(target * pre_trade_equity / reference)
        delta = desired - shares

        if delta > 0:
            quantity = _affordable_quantity(
                wanted=delta, price=buy_price, cash=cash, costs=costs
            )
            if quantity > 0:
                charges = costs.charges(quantity=quantity, fill_price=buy_price)
                cash = (cash - buy_price * quantity - charges.total).quantize(
                    CASH_QUANTUM, rounding=ROUND_HALF_UP
                )
                shares += quantity
                trades.append(
                    Trade(
                        session=execution_bar.session,
                        side="buy",
                        quantity=quantity,
                        reference_price=reference,
                        fill_price=buy_price,
                        charges=charges,
                        slippage_cost=(buy_price - reference) * quantity,
                        cash_after=cash,
                        shares_after=shares,
                    )
                )
        elif delta < 0:
            quantity = -delta
            sell_price = costs.fill_price(reference, "sell")
            charges = costs.charges(quantity=quantity, fill_price=sell_price)
            cash = (cash + sell_price * quantity - charges.total).quantize(
                CASH_QUANTUM, rounding=ROUND_HALF_UP
            )
            shares -= quantity
            trades.append(
                Trade(
                    session=execution_bar.session,
                    side="sell",
                    quantity=quantity,
                    reference_price=reference,
                    fill_price=sell_price,
                    charges=charges,
                    slippage_cost=(reference - sell_price) * quantity,
                    cash_after=cash,
                    shares_after=shares,
                )
            )

        equity = (cash + execution_bar.close * shares).quantize(
            CASH_QUANTUM, rounding=ROUND_HALF_UP
        )
        equity_curve.append(
            EquityPoint(
                session=execution_bar.session,
                cash=cash,
                shares=shares,
                equity=equity,
            )
        )

    return BacktestResult(
        security_id=series.security_id,
        currency=series.currency,
        series_sha256=series.content_sha256,
        config=config,
        costs=costs,
        corporate_actions=corporate_actions,
        strategy_id=strategy_id,
        strategy_config_sha256=strategy_config_sha256,
        decisions=tuple(decisions),
        corporate_action_applications=tuple(corporate_action_applications),
        trades=tuple(trades),
        equity_curve=tuple(equity_curve),
    )

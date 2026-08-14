"""Deterministic long-only backtest engine.

Look-ahead is prevented structurally rather than by convention. A strategy
never receives the :class:`BarSeries`; it receives a :class:`BarWindow` that
contains only sessions up to and including the decision bar, and that raises
:class:`LookAheadError` if asked for anything later. The order produced on bar
``i`` fills on bar ``i + 1``'s open, so a decision can never be executed at a
price it was allowed to see.

The engine is pure: no clock, no network, no randomness. The same inputs
always produce the same ``content_sha256``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from investment_research_os.quant.bars import (
    BarSeries,
    OhlcvBar,
    QuantContractError,
    canonical_sha256,
    decimal_text,
    to_decimal,
)
from investment_research_os.quant.costs import CASH_QUANTUM, CostModel, TradeCharges

ENGINE_VERSION = "quant-backtest-1"
RATIO_QUANTUM = Decimal("0.000001")


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

    @property
    def cutoff(self) -> date:
        return self.bars[-1].session

    @property
    def latest(self) -> OhlcvBar:
        return self.bars[-1]

    def closes(self) -> tuple[Decimal, ...]:
        return tuple(bar.close for bar in self.bars)

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
    strategy_id: str
    trades: tuple[Trade, ...]
    equity_curve: tuple[EquityPoint, ...]

    @property
    def final_equity(self) -> Decimal:
        return self.equity_curve[-1].equity

    @property
    def total_return(self) -> Decimal:
        start = self.config.starting_cash
        return ((self.final_equity - start) / start).quantize(
            RATIO_QUANTUM, rounding=ROUND_HALF_UP
        )

    @property
    def max_drawdown(self) -> Decimal:
        peak = self.equity_curve[0].equity
        worst = Decimal(0)
        for point in self.equity_curve:
            peak = max(peak, point.equity)
            if peak > 0:
                worst = max(worst, (peak - point.equity) / peak)
        return worst.quantize(RATIO_QUANTUM, rounding=ROUND_HALF_UP)

    @property
    def total_commission(self) -> Decimal:
        return sum((trade.charges.commission for trade in self.trades), Decimal(0))

    @property
    def total_transaction_cost(self) -> Decimal:
        return sum((trade.charges.transaction_cost for trade in self.trades), Decimal(0))

    @property
    def total_slippage_cost(self) -> Decimal:
        return sum((trade.slippage_cost for trade in self.trades), Decimal(0))

    def to_record(self) -> dict[str, object]:
        """Canonical, reproducible output record."""

        return {
            "config": self.config.to_record(),
            "costs": self.costs.to_record(),
            "currency": self.currency,
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
    config: BacktestConfig,
    strategy_id: str,
) -> BacktestResult:
    """Run one deterministic long-only backtest.

    Decisions are taken on each bar's close and filled on the next bar's open.
    The final bar produces no decision, because there is no later bar to fill
    it — acting on the last close would be look-ahead.
    """

    if not isinstance(strategy_id, str) or not strategy_id.strip():
        raise QuantContractError("strategy_id must name the strategy under test")

    cash = config.starting_cash
    shares = 0
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
        )
        target = _validated_target(strategy.target_exposure(window))
        execution_bar = series.bars[index + 1]
        reference = execution_bar.open

        pre_trade_equity = cash + reference * shares
        buy_price = costs.fill_price(reference, "buy")
        desired = int(target * pre_trade_equity / buy_price)
        delta = desired - shares

        if delta > 0:
            quantity = _affordable_quantity(
                wanted=delta, price=buy_price, cash=cash, costs=costs
            )
            if quantity > 0:
                charges = costs.charges(quantity=quantity, fill_price=buy_price)
                cash = (
                    cash - buy_price * quantity - charges.total
                ).quantize(CASH_QUANTUM, rounding=ROUND_HALF_UP)
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
            cash = (
                cash + sell_price * quantity - charges.total
            ).quantize(CASH_QUANTUM, rounding=ROUND_HALF_UP)
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
        strategy_id=strategy_id,
        trades=tuple(trades),
        equity_curve=tuple(equity_curve),
    )

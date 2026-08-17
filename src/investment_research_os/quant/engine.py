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
from typing import Literal, Protocol

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
from investment_research_os.quant.liquidity import ParticipationLimit

ENGINE_VERSION = "quant-backtest-3"
RATIO_QUANTUM = Decimal("0.000001")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
CloseBasis = Literal["split_adjusted", "unadjusted"]
FractionalSharePolicy = Literal["error"]


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

    def unadjusted_closes(self) -> tuple[Decimal, ...]:
        """Raw closes as supplied by the unadjusted BarSeries contract."""

        return tuple(bar.close for bar in self.bars)

    def closes(self, *, basis: CloseBasis) -> tuple[Decimal, ...]:
        """Closes with an explicit corporate-action basis."""

        if basis == "unadjusted":
            return self.unadjusted_closes()
        if basis == "split_adjusted":
            return self.split_adjusted_closes()
        raise QuantContractError(f"unsupported close basis: {basis!r}")

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

    def mean_close(self, periods: int, *, basis: CloseBasis) -> Decimal | None:
        """Trailing mean with an explicit corporate-action basis."""

        if isinstance(periods, bool) or not isinstance(periods, int) or periods <= 0:
            raise QuantContractError("periods must be a positive integer")
        if len(self.bars) < periods:
            return None
        closes = self.closes(basis=basis)
        with quant_decimal_context():
            return sum(closes[-periods:], Decimal(0)) / Decimal(periods)


class Strategy(Protocol):
    """Long-only target exposure as a fraction of equity, in [0, 1]."""

    def target_exposure(self, window: BarWindow) -> Decimal: ...


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    starting_cash: Decimal
    fractional_share_policy: FractionalSharePolicy

    def __post_init__(self) -> None:
        value = to_decimal(self.starting_cash, field="starting_cash")
        if value <= 0:
            raise QuantContractError(f"starting_cash must be positive, got {value}")
        object.__setattr__(self, "starting_cash", value)
        if self.fractional_share_policy != "error":
            raise QuantContractError(
                "fractional_share_policy must be error; cash-in-lieu is unsupported"
            )

    def to_record(self) -> dict[str, str]:
        return {
            "engine_version": ENGINE_VERSION,
            "fractional_share_policy": self.fractional_share_policy,
            "starting_cash": decimal_text(self.starting_cash),
        }


@dataclass(frozen=True, slots=True)
class Trade:
    decision_index: int
    session: date
    side: str
    requested_quantity: int
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
            "decision_index": self.decision_index,
            "fill_price": decimal_text(self.fill_price),
            "quantity": self.quantity,
            "reference_price": decimal_text(self.reference_price),
            "requested_quantity": self.requested_quantity,
            "session": self.session.isoformat(),
            "shares_after": self.shares_after,
            "side": self.side,
            "slippage_cost": decimal_text(self.slippage_cost),
        }


@dataclass(frozen=True, slots=True)
class StrategyDecision:
    decision_index: int
    decision_session: date
    execution_session: date
    target_exposure: Decimal

    def to_record(self) -> dict[str, str]:
        return {
            "decision_index": self.decision_index,
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
class FillAttempt:
    """One non-zero rebalance request after deterministic fill constraints."""

    decision_index: int
    session: date
    side: str
    bar_volume: int
    participation_cap: int
    requested_quantity: int
    affordable_quantity: int
    filled_quantity: int
    unfilled_quantity: int
    limit_reason: str

    def to_record(self) -> dict[str, object]:
        return {
            "affordable_quantity": self.affordable_quantity,
            "bar_volume": self.bar_volume,
            "decision_index": self.decision_index,
            "filled_quantity": self.filled_quantity,
            "limit_reason": self.limit_reason,
            "participation_cap": self.participation_cap,
            "requested_quantity": self.requested_quantity,
            "session": self.session.isoformat(),
            "side": self.side,
            "unfilled_quantity": self.unfilled_quantity,
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
    liquidity: ParticipationLimit
    strategy_id: str
    strategy_config_sha256: str
    decisions: tuple[StrategyDecision, ...]
    corporate_action_applications: tuple[SplitApplication, ...]
    fill_attempts: tuple[FillAttempt, ...]
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

    @property
    def total_unfilled_shares(self) -> int:
        return sum(attempt.unfilled_quantity for attempt in self.fill_attempts)

    @property
    def constrained_decision_count(self) -> int:
        return sum(attempt.limit_reason != "filled" for attempt in self.fill_attempts)

    @property
    def zero_fill_count(self) -> int:
        return sum(attempt.filled_quantity == 0 for attempt in self.fill_attempts)

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
            "fill_attempts": [attempt.to_record() for attempt in self.fill_attempts],
            "liquidity": self.liquidity.to_record(),
            "liquidity_sha256": self.liquidity.content_sha256,
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
    liquidity: ParticipationLimit,
    config: BacktestConfig,
    strategy_id: str,
    strategy_config_sha256: str,
) -> BacktestResult:
    """Run one deterministic long-only backtest.

    Decisions are taken on each bar's close and filled on the next bar's open.
    The final bar produces no decision, because there is no later bar to fill
    it — acting on the last close would be look-ahead. Split actions must be
    dated on a later covered session that the engine transitions into.
    """

    with quant_decimal_context():
        return _run_backtest(
            series=series,
            strategy=strategy,
            costs=costs,
            corporate_actions=corporate_actions,
            liquidity=liquidity,
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
    liquidity: ParticipationLimit,
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
    fill_attempts: list[FillAttempt] = []
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
                decision_index=index,
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
        desired = int(target * pre_trade_equity / reference)
        delta = desired - shares

        if delta != 0:
            side = "buy" if delta > 0 else "sell"
            requested_quantity = abs(delta)
            participation_cap = liquidity.cap_for_volume(execution_bar.volume)
            if execution_bar.volume == 0 and liquidity.zero_volume_policy == "error":
                raise QuantContractError("zero-volume execution bar is not permitted")
            capped_quantity = min(requested_quantity, participation_cap)
            affordable_quantity = capped_quantity
            fill_price: Decimal | None = None
            if capped_quantity > 0:
                fill_price = costs.fill_price(reference, side)
            if side == "buy" and fill_price is not None:
                affordable_quantity = _affordable_quantity(
                    wanted=capped_quantity,
                    price=fill_price,
                    cash=cash,
                    costs=costs,
                )
            filled_quantity = affordable_quantity
            if execution_bar.volume == 0:
                limit_reason = "zero_volume_blocked"
            elif capped_quantity < requested_quantity:
                limit_reason = "participation_capped"
            elif affordable_quantity < capped_quantity:
                limit_reason = "cash_capped"
            else:
                limit_reason = "filled"
            if 0 < filled_quantity < liquidity.min_fill_shares:
                filled_quantity = 0
                if limit_reason == "filled":
                    limit_reason = "below_min_fill"
            fill_attempts.append(
                FillAttempt(
                    decision_index=index,
                    session=execution_bar.session,
                    side=side,
                    bar_volume=execution_bar.volume,
                    participation_cap=participation_cap,
                    requested_quantity=requested_quantity,
                    affordable_quantity=affordable_quantity,
                    filled_quantity=filled_quantity,
                    unfilled_quantity=requested_quantity - filled_quantity,
                    limit_reason=limit_reason,
                )
            )
            if filled_quantity > 0:
                if fill_price is None:
                    raise QuantContractError("filled quantity requires a fill price")
                charges = costs.charges(
                    quantity=filled_quantity,
                    fill_price=fill_price,
                )
                if side == "buy":
                    cash = (
                        cash - fill_price * filled_quantity - charges.total
                    ).quantize(CASH_QUANTUM, rounding=ROUND_HALF_UP)
                    shares += filled_quantity
                    slippage_cost = (fill_price - reference) * filled_quantity
                else:
                    cash = (
                        cash + fill_price * filled_quantity - charges.total
                    ).quantize(CASH_QUANTUM, rounding=ROUND_HALF_UP)
                    shares -= filled_quantity
                    slippage_cost = (reference - fill_price) * filled_quantity
                trades.append(
                    Trade(
                        decision_index=index,
                        session=execution_bar.session,
                        side=side,
                        requested_quantity=requested_quantity,
                        quantity=filled_quantity,
                        reference_price=reference,
                        fill_price=fill_price,
                        charges=charges,
                        slippage_cost=slippage_cost,
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
        liquidity=liquidity,
        strategy_id=strategy_id,
        strategy_config_sha256=strategy_config_sha256,
        decisions=tuple(decisions),
        corporate_action_applications=tuple(corporate_action_applications),
        fill_attempts=tuple(fill_attempts),
        trades=tuple(trades),
        equity_curve=tuple(equity_curve),
    )

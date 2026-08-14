"""Quant bounded context.

Architecture decision 0001 keeps Quant isolated from Research and Portfolio.
This package shares the canonical ``security_id`` with other bounded contexts
and nothing else: it imports no Research OS internal model, no portfolio
sizing, and no broker adapter. Market data enters through the provider-neutral
:class:`BarSeries` contract, so Moomoo (or any other provider) can later be
added as an optional adapter that constructs bars without this package
learning anything about it.

Everything here is offline and deterministic. The same inputs always produce
the same ``content_sha256``.
"""

from investment_research_os.quant.bars import (
    BarInterval,
    BarSeries,
    OhlcvBar,
    PriceBasis,
    QuantContractError,
)
from investment_research_os.quant.costs import CostModel, TradeCharges
from investment_research_os.quant.corporate_actions import (
    CorporateActionSet,
    StockSplit,
)
from investment_research_os.quant.engine import (
    BacktestConfig,
    BacktestResult,
    BarWindow,
    EquityPoint,
    LookAheadError,
    SplitApplication,
    StrategyDecision,
    Strategy,
    Trade,
    run_backtest,
)

__all__ = [
    "BacktestConfig",
    "BacktestResult",
    "BarInterval",
    "BarSeries",
    "BarWindow",
    "CostModel",
    "CorporateActionSet",
    "EquityPoint",
    "LookAheadError",
    "OhlcvBar",
    "PriceBasis",
    "QuantContractError",
    "Strategy",
    "StrategyDecision",
    "SplitApplication",
    "StockSplit",
    "Trade",
    "TradeCharges",
    "run_backtest",
]

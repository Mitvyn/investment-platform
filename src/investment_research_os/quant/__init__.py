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
from investment_research_os.quant.dataset import (
    DATASET_VERSION,
    CoverageScope,
    PointInTimeDataset,
)
from investment_research_os.quant.corporate_actions import (
    CorporateActionSet,
    StockSplit,
)
from investment_research_os.quant.liquidity import ParticipationLimit
from investment_research_os.quant.statistics import (
    ReturnStatistics,
    critical_value,
    simple_returns,
    summarise_returns,
)
from investment_research_os.quant.validation import (
    CostScenario,
    CostSensitivityConfig,
    MultipleTestingDisclosure,
    ScenarioSummary,
    StrategyFactory,
    ValidationReport,
    WalkForwardConfig,
    WalkForwardWindow,
    WindowScenarioResult,
    build_walk_forward_windows,
    validate_walk_forward,
)
from investment_research_os.quant.engine import (
    BacktestConfig,
    BacktestResult,
    BarWindow,
    EquityPoint,
    FillAttempt,
    LookAheadError,
    SplitApplication,
    StrategyDecision,
    Strategy,
    Trade,
    run_backtest,
)

__all__ = [
    "BacktestConfig",
    "CoverageScope",
    "DATASET_VERSION",
    "PointInTimeDataset",
    "CostScenario",
    "CostSensitivityConfig",
    "MultipleTestingDisclosure",
    "ReturnStatistics",
    "ScenarioSummary",
    "StrategyFactory",
    "ValidationReport",
    "WalkForwardConfig",
    "WalkForwardWindow",
    "WindowScenarioResult",
    "build_walk_forward_windows",
    "critical_value",
    "simple_returns",
    "summarise_returns",
    "validate_walk_forward",
    "BacktestResult",
    "BarInterval",
    "BarSeries",
    "BarWindow",
    "CostModel",
    "CorporateActionSet",
    "EquityPoint",
    "FillAttempt",
    "LookAheadError",
    "OhlcvBar",
    "ParticipationLimit",
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

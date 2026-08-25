"""The one deterministic educational strategy offered by the workspace.

This is a teaching object, not a strategy marketplace. Exactly one rule ships:
hold the security while its latest close sits above its own trailing mean, and
hold cash otherwise. It exists so an operator can see how costs, liquidity, and
walk-forward windows change a result, not because the rule is expected to work.

**Nothing is fit.** The lookback is declared by the operator and never learned
from training data. The factory still takes a training window, because
``validate_walk_forward`` requires one and because the day a rule does learn a
parameter, the honest path must already be the one in place. The factory reads
no future bar, because a ``BarWindow`` has no handle on one.

Closes are read on the split-adjusted basis so a share-count change does not
read as a price collapse and manufacture a signal that never existed.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from investment_research_os.quant import BarWindow, QuantContractError
from investment_research_os.quant.bars import canonical_sha256
from investment_research_os.quant.validation import (
    BENCHMARK_CONFIG_SHA256,
    BENCHMARK_STRATEGY_ID,
)

STRATEGY_VERSION = "quant-workspace-strategy-1"
TREND_STRATEGY_ID = "trend_following_sma.v1"

#: The close basis every workspace strategy reads. Stated once, hashed into the
#: strategy configuration, and never selectable per run.
CLOSE_BASIS = "split_adjusted"

__all__ = [
    "BENCHMARK_CONFIG_SHA256",
    "BENCHMARK_STRATEGY_ID",
    "CLOSE_BASIS",
    "STRATEGY_VERSION",
    "TREND_STRATEGY_ID",
    "BuyAndHoldStrategy",
    "TrendFollowingConfig",
    "TrendFollowingFactory",
    "TrendFollowingStrategy",
]


@dataclass(frozen=True, slots=True)
class TrendFollowingConfig:
    """The declared, hashable configuration of one trend rule."""

    lookback_sessions: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.lookback_sessions, bool)
            or not isinstance(self.lookback_sessions, int)
            or self.lookback_sessions < 2
        ):
            raise QuantContractError(
                "lookback_sessions must be an integer of at least two"
            )

    def to_record(self) -> dict[str, object]:
        return {
            "close_basis": CLOSE_BASIS,
            "lookback_sessions": self.lookback_sessions,
            "strategy_id": TREND_STRATEGY_ID,
            "strategy_version": STRATEGY_VERSION,
        }

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.to_record())


@dataclass(frozen=True, slots=True)
class TrendFollowingStrategy:
    """Fully invested above the trailing mean, in cash otherwise.

    Before the lookback is covered the trailing mean does not exist. That case
    holds cash rather than assuming a direction, so the first sessions of a
    history never carry a signal the data could not support.
    """

    config: TrendFollowingConfig

    def target_exposure(self, window: BarWindow) -> Decimal:
        mean = window.mean_close(self.config.lookback_sessions, basis=CLOSE_BASIS)
        if mean is None:
            return Decimal(0)
        closes = window.closes(basis=CLOSE_BASIS)
        return Decimal(1) if closes[-1] > mean else Decimal(0)


@dataclass(frozen=True, slots=True)
class TrendFollowingFactory:
    """Builds one trend strategy per walk-forward window.

    A new instance per window is the point: reusing one fitted object across
    windows is the commonest way state leaks forward, and this rule holds no
    state to leak in the first place.
    """

    lookback_sessions: int

    def build(self, train_window: BarWindow) -> tuple[TrendFollowingStrategy, str]:
        del train_window  # No parameter is learned from training data.
        config = TrendFollowingConfig(lookback_sessions=self.lookback_sessions)
        return TrendFollowingStrategy(config=config), config.content_sha256


class BuyAndHoldStrategy:
    """The transparent benchmark: fully invested from the first fillable bar.

    Its identity and configuration hash are the ones ``validate_walk_forward``
    already uses internally, so the full-period benchmark reported next to the
    strategy is the same rule the per-window comparison uses.
    """

    def target_exposure(self, window: BarWindow) -> Decimal:
        del window
        return Decimal(1)

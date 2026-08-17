"""Walk-forward statistical validation for Quant backtests.

A backtest produces a number. It never produces evidence that the number means
anything. This module answers — or explicitly refuses to answer — whether a
strategy's excess return over buy-and-hold survives out-of-sample testing,
realistic costs, and the number of configurations the operator declares having
tried.

Refusing is a first-class outcome. ``insufficient_data`` and ``rejected`` are
the easy paths and ``validated`` is the narrow one, because a layer that always
emits a verdict launders a small sample into a confident-looking report.

**Honest limit.** This module cannot verify that a strategy was fit on training
data alone. Python cannot sandbox arbitrary strategy code, so a factory is free
to capture state the engine never handed it. What the design does is make the
honest path the convenient one — the factory receives a bounded
:class:`BarWindow` that raises on future sessions, and a pre-built strategy
cannot be passed at all — and put the evidence of which path was taken into the
hashed record. It does not prove anything about code it did not write.

Everything is offline: no clock, no network, no randomness, no provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal, Protocol, Sequence

from investment_research_os.quant.bars import (
    BarSeries,
    QuantContractError,
    canonical_sha256,
    decimal_text,
    quant_decimal_context,
    to_decimal,
)
from investment_research_os.quant.corporate_actions import CorporateActionSet
from investment_research_os.quant.dataset import PointInTimeDataset
from investment_research_os.quant.costs import CostModel
from investment_research_os.quant.engine import (
    _enforced_inputs,
    ENGINE_VERSION,
    BacktestConfig,
    BacktestResult,
    BarWindow,
    Strategy,
    run_backtest,
)
from investment_research_os.quant.liquidity import ParticipationLimit
from investment_research_os.quant.statistics import (
    ReturnStatistics,
    critical_value,
    resolve_alpha_label,
    resolve_degrees_of_freedom_bucket,
    summarise_returns,
)

VALIDATION_VERSION = "quant-validation-2"

WindowMode = Literal["rolling", "anchored"]
Adjustment = Literal["bonferroni", "none"]
ValidationOutcome = Literal[
    "validated",
    "rejected",
    "insufficient_data",
    "inconclusive",
]

#: Fill constraints that mean the market could not absorb the order. A
#: ``cash_capped`` attempt is a capital constraint, not a capacity one, and
#: says nothing about whether the benchmark was reachable.
LIQUIDITY_LIMIT_REASONS = frozenset(
    {"participation_capped", "zero_volume_blocked", "below_min_fill"}
)

BENCHMARK_STRATEGY_ID = "buy-and-hold"
_BENCHMARK_CONFIG_RECORD = {"strategy": "buy_and_hold", "target_exposure": "1"}
BENCHMARK_CONFIG_SHA256 = canonical_sha256(_BENCHMARK_CONFIG_RECORD)


class _BuyAndHold:
    """The benchmark. Fixed internally so it cannot be tuned into a straw man."""

    def target_exposure(self, window: BarWindow) -> Decimal:
        return Decimal(1)


# ---------------------------------------------------------------- schedule


@dataclass(frozen=True, slots=True)
class WalkForwardConfig:
    """Window geometry, in session counts. Never in calendar days.

    Calendar arithmetic would silently produce empty windows across holidays
    and would make the schedule depend on a market calendar this package does
    not have.
    """

    train_sessions: int
    test_sessions: int
    step_sessions: int
    embargo_sessions: int
    window_mode: WindowMode
    min_windows: int
    min_trades_per_window: int
    min_total_trades: int

    def __post_init__(self) -> None:
        def integer(field: str, minimum: int) -> int:
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int):
                raise QuantContractError(f"{field} must be an integer")
            if value < minimum:
                raise QuantContractError(f"{field} must be at least {minimum}")
            return value

        # A BarSeries needs two bars, so a one-session window cannot exist.
        integer("train_sessions", 2)
        integer("test_sessions", 2)
        integer("step_sessions", 1)
        integer("embargo_sessions", 0)
        integer("min_windows", 1)
        integer("min_trades_per_window", 0)
        integer("min_total_trades", 0)
        if self.window_mode not in ("rolling", "anchored"):
            raise QuantContractError("window_mode must be rolling or anchored")

    @property
    def test_windows_overlap(self) -> bool:
        """Overlapping test periods are not independent observations."""

        return self.step_sessions < self.test_sessions

    def to_record(self) -> dict[str, object]:
        return {
            "embargo_sessions": self.embargo_sessions,
            "min_total_trades": self.min_total_trades,
            "min_trades_per_window": self.min_trades_per_window,
            "min_windows": self.min_windows,
            "step_sessions": self.step_sessions,
            "test_sessions": self.test_sessions,
            "test_windows_overlap": self.test_windows_overlap,
            "train_sessions": self.train_sessions,
            "window_mode": self.window_mode,
        }


@dataclass(frozen=True, slots=True)
class WalkForwardWindow:
    """One train/embargo/test period, keyed by session index."""

    window_index: int
    train_start_index: int
    train_end_index: int
    embargo_end_index: int
    test_start_index: int
    test_end_index: int
    train_start_session: date
    train_end_session: date
    test_start_session: date
    test_end_session: date

    def to_record(self) -> dict[str, object]:
        return {
            "embargo_end_index": self.embargo_end_index,
            "test_end_index": self.test_end_index,
            "test_end_session": self.test_end_session.isoformat(),
            "test_start_index": self.test_start_index,
            "test_start_session": self.test_start_session.isoformat(),
            "train_end_index": self.train_end_index,
            "train_end_session": self.train_end_session.isoformat(),
            "train_start_index": self.train_start_index,
            "train_start_session": self.train_start_session.isoformat(),
            "window_index": self.window_index,
        }


def build_walk_forward_windows(
    *,
    session_count: int,
    config: WalkForwardConfig,
    sessions: Sequence[date] | None = None,
) -> tuple[WalkForwardWindow, ...]:
    """Generate windows over session indices.

    A trailing window that does not fit whole is discarded rather than
    truncated: a short test period carries different statistical weight, and
    averaging it in unweighted is a quiet error.
    """

    if isinstance(session_count, bool) or not isinstance(session_count, int):
        raise QuantContractError("session_count must be an integer")
    placeholder = sessions is None
    dates: Sequence[date] = sessions if sessions is not None else ()

    windows: list[WalkForwardWindow] = []
    index = 0
    while True:
        offset = index * config.step_sessions
        if config.window_mode == "rolling":
            train_start = offset
            train_end = offset + config.train_sessions - 1
        else:
            train_start = 0
            train_end = config.train_sessions - 1 + offset
        embargo_end = train_end + config.embargo_sessions
        test_start = embargo_end + 1
        test_end = test_start + config.test_sessions - 1
        if test_end > session_count - 1:
            break
        windows.append(
            WalkForwardWindow(
                window_index=index,
                train_start_index=train_start,
                train_end_index=train_end,
                embargo_end_index=embargo_end,
                test_start_index=test_start,
                test_end_index=test_end,
                train_start_session=date.min if placeholder else dates[train_start],
                train_end_session=date.min if placeholder else dates[train_end],
                test_start_session=date.min if placeholder else dates[test_start],
                test_end_session=date.min if placeholder else dates[test_end],
            )
        )
        index += 1
    return tuple(windows)


# ------------------------------------------------------------ cost scenarios


@dataclass(frozen=True, slots=True)
class CostScenario:
    label: str
    costs: CostModel

    def __post_init__(self) -> None:
        if not isinstance(self.label, str) or not self.label.strip():
            raise QuantContractError("cost scenario label must be non-empty")

    def to_record(self) -> dict[str, object]:
        return {"costs": self.costs.to_record(), "label": self.label}


@dataclass(frozen=True, slots=True)
class CostSensitivityConfig:
    """Cost scenarios in caller order, cheapest first by convention.

    The baseline is the operator's realistic estimate and is the scenario the
    verdict is taken from. The others show the shape of the degradation.
    """

    scenarios: tuple[CostScenario, ...]
    baseline_label: str

    def __post_init__(self) -> None:
        scenarios = tuple(self.scenarios)
        object.__setattr__(self, "scenarios", scenarios)
        if len(scenarios) < 2:
            raise QuantContractError(
                "cost sensitivity needs at least two scenarios to show sensitivity"
            )
        labels = [scenario.label for scenario in scenarios]
        if len(set(labels)) != len(labels):
            raise QuantContractError("cost scenario labels must be unique")
        if self.baseline_label not in labels:
            raise QuantContractError("baseline_label must name a declared scenario")

    @property
    def baseline(self) -> CostScenario:
        for scenario in self.scenarios:
            if scenario.label == self.baseline_label:
                return scenario
        raise QuantContractError("baseline_label must name a declared scenario")

    def to_record(self) -> dict[str, object]:
        return {
            "baseline_label": self.baseline_label,
            "scenarios": [scenario.to_record() for scenario in self.scenarios],
        }


# --------------------------------------------------------------- disclosure


@dataclass(frozen=True, slots=True)
class MultipleTestingDisclosure:
    """How many configurations were tried, and how the threshold accounts for it.

    ``trials_declared`` is operator-declared and **unverifiable** — this package
    cannot see prior runs. It is disclosed and cross-checked against what this
    run itself did, which is a genuine consistency check, but it is not proof.
    """

    trials_declared: int
    family_label: str
    adjustment: Adjustment
    alpha: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.trials_declared, bool)
            or not isinstance(self.trials_declared, int)
            or self.trials_declared < 1
        ):
            raise QuantContractError("trials_declared must be a positive integer")
        if not isinstance(self.family_label, str) or not self.family_label.strip():
            raise QuantContractError("family_label must be non-empty")
        if self.adjustment not in ("bonferroni", "none"):
            raise QuantContractError("adjustment must be bonferroni or none")
        if self.adjustment == "none" and self.trials_declared > 1:
            raise QuantContractError(
                "adjustment none is only honest for a single declared trial"
            )
        alpha = to_decimal(self.alpha, field="alpha")
        if alpha <= 0 or alpha >= 1:
            raise QuantContractError("alpha must lie between 0 and 1")

    @property
    def alpha_effective(self) -> Decimal:
        with quant_decimal_context():
            alpha = Decimal(self.alpha)
            if self.adjustment == "none":
                return alpha
            return alpha / Decimal(self.trials_declared)

    def to_record(self) -> dict[str, object]:
        return {
            "adjustment": self.adjustment,
            "alpha": self.alpha,
            "alpha_effective": decimal_text(self.alpha_effective),
            "family_label": self.family_label,
            "trials_declared": self.trials_declared,
        }


class StrategyFactory(Protocol):
    """Builds a strategy from training data alone, returning its config hash.

    Taking a factory rather than a strategy is deliberate: reusing one fitted
    instance across windows is the commonest way state leaks forward, and this
    signature makes that impossible to do by accident.
    """

    def build(self, train_window: BarWindow) -> tuple[Strategy, str]: ...


# ------------------------------------------------------------------ results


@dataclass(frozen=True, slots=True)
class WindowScenarioResult:
    window_index: int
    scenario_label: str
    strategy_config_sha256: str
    strategy_backtest_sha256: str
    benchmark_backtest_sha256: str
    trade_count: int
    benchmark_entry_shortfall: int
    benchmark_end_shares: int
    benchmark_reachable: bool
    strategy_return: Decimal
    benchmark_return: Decimal
    excess_return: Decimal

    def to_record(self) -> dict[str, object]:
        return {
            "benchmark_backtest_sha256": self.benchmark_backtest_sha256,
            "benchmark_end_shares": self.benchmark_end_shares,
            "benchmark_entry_shortfall": self.benchmark_entry_shortfall,
            "benchmark_reachable": self.benchmark_reachable,
            "benchmark_return": decimal_text(self.benchmark_return),
            "excess_return": decimal_text(self.excess_return),
            "scenario_label": self.scenario_label,
            "strategy_backtest_sha256": self.strategy_backtest_sha256,
            "strategy_config_sha256": self.strategy_config_sha256,
            "strategy_return": decimal_text(self.strategy_return),
            "trade_count": self.trade_count,
            "window_index": self.window_index,
        }


@dataclass(frozen=True, slots=True)
class ScenarioSummary:
    label: str
    aggregate_excess: Decimal
    statistics: ReturnStatistics
    critical_value: Decimal | None
    passed: bool
    windows_beating_benchmark: int

    def to_record(self) -> dict[str, object]:
        return {
            "aggregate_excess": decimal_text(self.aggregate_excess),
            "critical_value": (
                None if self.critical_value is None else decimal_text(self.critical_value)
            ),
            "label": self.label,
            "passed": self.passed,
            "statistics": self.statistics.to_record(),
            "windows_beating_benchmark": self.windows_beating_benchmark,
        }


@dataclass(frozen=True, slots=True)
class ValidationReport:
    security_id: str
    dataset_sha256: str
    series_sha256: str
    corporate_actions_sha256: str
    liquidity: ParticipationLimit
    config: BacktestConfig
    schedule: WalkForwardConfig
    disclosure: MultipleTestingDisclosure
    cost_sensitivity: CostSensitivityConfig
    strategy_id: str
    windows: tuple[WalkForwardWindow, ...]
    window_results: tuple[WindowScenarioResult, ...]
    scenario_summaries: tuple[ScenarioSummary, ...]
    outcome: ValidationOutcome
    reason_codes: tuple[str, ...]
    degrees_of_freedom: int
    degrees_of_freedom_bucket: int | None
    alpha_label: str | None
    highest_passing_scenario_label: str | None
    first_failing_scenario_label: str | None

    @property
    def window_count(self) -> int:
        return len(self.windows)

    @property
    def test_windows_overlap(self) -> bool:
        return self.schedule.test_windows_overlap

    @property
    def windows_beating_benchmark(self) -> int:
        for summary in self.scenario_summaries:
            if summary.label == self.cost_sensitivity.baseline_label:
                return summary.windows_beating_benchmark
        return 0

    def to_record(self) -> dict[str, object]:
        return {
            "alpha_effective": decimal_text(self.disclosure.alpha_effective),
            "alpha_label": self.alpha_label,
            "benchmark_config_sha256": BENCHMARK_CONFIG_SHA256,
            "benchmark_strategy_id": BENCHMARK_STRATEGY_ID,
            "config": self.config.to_record(),
            "corporate_actions_sha256": self.corporate_actions_sha256,
            "cost_sensitivity": self.cost_sensitivity.to_record(),
            "dataset_sha256": self.dataset_sha256,
            "degrees_of_freedom": self.degrees_of_freedom,
            "degrees_of_freedom_bucket": self.degrees_of_freedom_bucket,
            "disclosure": self.disclosure.to_record(),
            "engine_version": ENGINE_VERSION,
            "first_failing_scenario_label": self.first_failing_scenario_label,
            "highest_passing_scenario_label": self.highest_passing_scenario_label,
            "liquidity": self.liquidity.to_record(),
            "liquidity_sha256": self.liquidity.content_sha256,
            "outcome": self.outcome,
            "reason_codes": list(self.reason_codes),
            "scenario_summaries": [
                summary.to_record() for summary in self.scenario_summaries
            ],
            "schedule": self.schedule.to_record(),
            "security_id": self.security_id,
            "series_sha256": self.series_sha256,
            "strategy_id": self.strategy_id,
            "validation_version": VALIDATION_VERSION,
            "window_count": self.window_count,
            "window_results": [result.to_record() for result in self.window_results],
            "windows": [window.to_record() for window in self.windows],
            "windows_beating_benchmark": self.windows_beating_benchmark,
        }

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.to_record())


# ------------------------------------------------------------------- runner


def _slice_series(series: BarSeries, start: int, end: int) -> BarSeries:
    """Inclusive index slice preserving every series-level declaration."""

    return BarSeries(
        security_id=series.security_id,
        currency=series.currency,
        interval=series.interval,
        price_basis=series.price_basis,
        source=series.source,
        bars=series.bars[start : end + 1],
    )


def _slice_dataset(
    dataset: PointInTimeDataset, start: int, end: int
) -> PointInTimeDataset:
    """A window's inputs, derived only from the parent receipt.

    The parent cutoff and every source declaration carry over unchanged: a
    window is a view of one dataset, not a dataset of its own, and inventing a
    tighter cutoff per window would assert an availability claim nobody made.
    Only the parent's own bars and actions can appear, so no external market
    data can enter at a window boundary.
    """

    sliced = _slice_series(dataset.series, start, end)
    covered = frozenset(bar.session for bar in sliced.bars[1:])
    return PointInTimeDataset(
        series=sliced,
        corporate_actions=_filter_actions(dataset.corporate_actions, covered),
        as_of_cutoff=dataset.as_of_cutoff,
        source_id=dataset.source_id,
        source_revision=dataset.source_revision,
        source_content_sha256=dataset.source_content_sha256,
        coverage_scope=dataset.coverage_scope,
    )


def _filter_actions(
    actions: CorporateActionSet, sessions: frozenset[date]
) -> CorporateActionSet:
    """Actions the sliced series actually covers.

    The engine rejects an action dated outside the sessions it transitions
    into, so passing the full set to a slice would abort the run.
    """

    return CorporateActionSet(
        security_id=actions.security_id,
        source=actions.source,
        actions=tuple(
            action
            for action in actions.actions
            if action.effective_session in sessions
        ),
    )


def _benchmark_entry_shortfall(result: BacktestResult) -> int:
    """Buy-side shares the market refused the benchmark over one test window.

    Only capacity constraints count. A benchmark trimmed by cash still reached
    the position its capital allowed, whereas one trimmed by the participation
    cap, a halted session, or a minimum-fill floor holds exposure it wanted and
    could not get.
    """

    return sum(
        attempt.unfilled_quantity
        for attempt in result.fill_attempts
        if attempt.side == "buy" and attempt.limit_reason in LIQUIDITY_LIMIT_REASONS
    )


def validate_walk_forward(
    *,
    dataset: PointInTimeDataset,
    liquidity: ParticipationLimit,
    config: BacktestConfig,
    schedule: WalkForwardConfig,
    factory: StrategyFactory,
    strategy_id: str,
    cost_sensitivity: CostSensitivityConfig,
    disclosure: MultipleTestingDisclosure,
    annualisation_periods: int,
) -> ValidationReport:
    """Run a walk-forward validation and return a hashable verdict."""

    if not isinstance(strategy_id, str) or not strategy_id.strip():
        raise QuantContractError("strategy_id must name the strategy under test")
    if not hasattr(factory, "build") or not callable(factory.build):
        raise QuantContractError(
            "factory must expose build(train_window); a pre-built strategy "
            "would carry fitted state across windows"
        )
    # Fail closed here, before a single window is fitted. Train windows never
    # run through the engine, so a leaked future bar or a forged provenance
    # field would otherwise reach a factory without ever meeting the engine's
    # own recheck.
    series, corporate_actions = _enforced_inputs(dataset)

    trials_observed = len(cost_sensitivity.scenarios)
    if disclosure.trials_declared < trials_observed:
        raise QuantContractError(
            f"trials_declared {disclosure.trials_declared} is below the "
            f"{trials_observed} configurations this run evaluated"
        )

    sessions = [bar.session for bar in series.bars]
    windows = build_walk_forward_windows(
        session_count=len(sessions),
        config=schedule,
        sessions=sessions,
    )

    insufficient: list[str] = []
    if not windows:
        insufficient.append("series_too_short")
    elif len(windows) < schedule.min_windows:
        insufficient.append("too_few_windows")

    degrees_of_freedom = max(len(windows) - 1, 0)
    bucket = (
        resolve_degrees_of_freedom_bucket(degrees_of_freedom)
        if degrees_of_freedom > 0
        else None
    )
    alpha_label = resolve_alpha_label(disclosure.alpha_effective)

    if insufficient:
        return ValidationReport(
            security_id=series.security_id,
            dataset_sha256=dataset.content_sha256,
            series_sha256=series.content_sha256,
            corporate_actions_sha256=corporate_actions.content_sha256,
            liquidity=liquidity,
            config=config,
            schedule=schedule,
            disclosure=disclosure,
            cost_sensitivity=cost_sensitivity,
            strategy_id=strategy_id,
            windows=windows,
            window_results=(),
            scenario_summaries=(),
            outcome="insufficient_data",
            reason_codes=tuple(insufficient),
            degrees_of_freedom=degrees_of_freedom,
            degrees_of_freedom_bucket=bucket,
            alpha_label=alpha_label,
            highest_passing_scenario_label=None,
            first_failing_scenario_label=None,
        )

    # One fit per window, reused across every cost scenario. Refitting per
    # scenario would confound cost sensitivity with fitting instability.
    fitted: dict[int, tuple[Strategy, str]] = {}
    for window in windows:
        train_window = BarWindow(
            security_id=series.security_id,
            currency=series.currency,
            bars=series.bars[window.train_start_index : window.train_end_index + 1],
            corporate_actions=tuple(
                action
                for action in corporate_actions.actions
                if action.effective_session <= window.train_end_session
            ),
        )
        strategy, config_hash = factory.build(train_window)
        fitted[window.window_index] = (strategy, config_hash)

    benchmark = _BuyAndHold()
    results: list[WindowScenarioResult] = []

    for window in windows:
        # The lead-in bar is the decision bar for the first test fill. Without
        # it the test period's opening session is one the engine never
        # transitions into, so it can be neither traded into nor carry a split.
        window_dataset = _slice_dataset(
            dataset, window.test_start_index - 1, window.test_end_index
        )
        strategy, config_hash = fitted[window.window_index]

        for scenario in cost_sensitivity.scenarios:
            strategy_result = run_backtest(
                dataset=window_dataset,
                strategy=strategy,
                costs=scenario.costs,
                liquidity=liquidity,
                config=config,
                strategy_id=strategy_id,
                strategy_config_sha256=config_hash,
            )
            benchmark_result = run_backtest(
                dataset=window_dataset,
                strategy=benchmark,
                costs=scenario.costs,
                liquidity=liquidity,
                config=config,
                strategy_id=BENCHMARK_STRATEGY_ID,
                strategy_config_sha256=BENCHMARK_CONFIG_SHA256,
            )
            with quant_decimal_context():
                excess = strategy_result.total_return - benchmark_result.total_return
            shortfall = _benchmark_entry_shortfall(benchmark_result)
            benchmark_end_shares = benchmark_result.equity_curve[-1].shares
            results.append(
                WindowScenarioResult(
                    window_index=window.window_index,
                    scenario_label=scenario.label,
                    strategy_config_sha256=config_hash,
                    strategy_backtest_sha256=strategy_result.content_sha256,
                    benchmark_backtest_sha256=benchmark_result.content_sha256,
                    trade_count=len(strategy_result.trades),
                    benchmark_entry_shortfall=shortfall,
                    benchmark_end_shares=benchmark_end_shares,
                    # Reachable means the benchmark actually held the position
                    # it is meant to represent: it ends the window invested and
                    # never had entry exposure the market refused. A benchmark
                    # that bought a token quantity under a tight cap sits mostly
                    # in cash, and a flat strategy would beat that capacity
                    # artefact rather than the security.
                    benchmark_reachable=shortfall == 0 and benchmark_end_shares > 0,
                    strategy_return=strategy_result.total_return,
                    benchmark_return=benchmark_result.total_return,
                    excess_return=excess,
                )
            )

    summaries: list[ScenarioSummary] = []
    for scenario in cost_sensitivity.scenarios:
        scoped = [
            result for result in results if result.scenario_label == scenario.label
        ]
        scoped.sort(key=lambda result: result.window_index)
        excesses = [result.excess_return for result in scoped]
        statistics = summarise_returns(
            excesses, annualisation_periods=annualisation_periods
        )
        with quant_decimal_context():
            aggregate = sum(excesses, Decimal(0))
        threshold = critical_value(
            degrees_of_freedom=degrees_of_freedom,
            alpha=disclosure.alpha_effective,
        )
        passed = bool(
            statistics.t_statistic is not None
            and threshold is not None
            and statistics.t_statistic >= threshold
            and aggregate > 0
        )
        summaries.append(
            ScenarioSummary(
                label=scenario.label,
                aggregate_excess=aggregate,
                statistics=statistics,
                critical_value=threshold,
                passed=passed,
                windows_beating_benchmark=sum(
                    1 for value in excesses if value > 0
                ),
            )
        )

    by_label = {summary.label: summary for summary in summaries}
    baseline = by_label[cost_sensitivity.baseline_label]
    baseline_results = [
        result
        for result in results
        if result.scenario_label == cost_sensitivity.baseline_label
    ]

    passing = [summary.label for summary in summaries if summary.passed]
    failing = [summary.label for summary in summaries if not summary.passed]
    highest_passing = passing[-1] if passing else None
    first_failing = failing[0] if failing else None

    # Sample adequacy, checked before any verdict: every other conclusion
    # presupposes a measurable sample.
    if any(
        result.trade_count < schedule.min_trades_per_window
        for result in baseline_results
    ):
        insufficient.append("too_few_trades_in_window")
    if sum(result.trade_count for result in baseline_results) < schedule.min_total_trades:
        insufficient.append("too_few_total_trades")
    if not all(result.benchmark_reachable for result in baseline_results):
        insufficient.append("benchmark_unfillable")
    if baseline.statistics.stdev == 0:
        insufficient.append("zero_variance")
    if bucket is None:
        insufficient.append("degrees_of_freedom_below_table")
    if alpha_label is None:
        insufficient.append("adjusted_alpha_below_table")

    rejected: list[str] = []
    if not insufficient:
        if baseline.aggregate_excess <= 0:
            rejected.append("no_excess_return")
        elif not baseline.passed:
            rejected.append("below_critical_value")
        if not baseline.passed and any(summary.passed for summary in summaries):
            rejected.append("fails_at_baseline_costs")

    if insufficient:
        outcome: ValidationOutcome = "insufficient_data"
        reasons = tuple(insufficient)
    elif rejected:
        outcome = "rejected"
        reasons = tuple(rejected)
    elif baseline.windows_beating_benchmark * 2 < len(windows):
        # Clears on aggregate while losing most windows: one dominant window is
        # carrying the average. Neither a pass nor a rejection.
        outcome = "inconclusive"
        reasons = ("aggregate_carried_by_few_windows",)
    else:
        outcome = "validated"
        reasons = ()

    return ValidationReport(
        security_id=series.security_id,
        dataset_sha256=dataset.content_sha256,
        series_sha256=series.content_sha256,
        corporate_actions_sha256=corporate_actions.content_sha256,
        liquidity=liquidity,
        config=config,
        schedule=schedule,
        disclosure=disclosure,
        cost_sensitivity=cost_sensitivity,
        strategy_id=strategy_id,
        windows=windows,
        window_results=tuple(results),
        scenario_summaries=tuple(summaries),
        outcome=outcome,
        reason_codes=reasons,
        degrees_of_freedom=degrees_of_freedom,
        degrees_of_freedom_bucket=bucket,
        alpha_label=alpha_label,
        highest_passing_scenario_label=highest_passing,
        first_failing_scenario_label=first_failing,
    )

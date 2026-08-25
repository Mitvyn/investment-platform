"""One historical analysis run, from declared assumptions to a sealed record.

A run does three things and reports all three: it backtests the declared
strategy over the whole dataset, it backtests a transparent buy-and-hold
benchmark over the same dataset under the same costs and capacity, and it runs
a walk-forward validation with a cost-sensitivity pair so the operator can see
whether the difference survived out-of-sample testing at all.

**Every assumption is stated, never defaulted.** Starting cash, each cost
component, slippage, participation capacity, the walk-forward geometry, the
significance level, and the declared number of trials all arrive from the
caller and are revalidated here before anything runs. A run that quietly
assumed zero costs would report a return the operator could never have had.

**The output is a sanitized record, not a view of the inputs.** No bar, no
price, no row, and no fragment of the source document appears in it. It carries
identity hashes, declared assumptions, aggregate outcome numbers, and codes.
That is what makes it safe to send to a browser and to store.

**The output is historical analysis.** It is not a prediction, not a
recommendation, and not evidence for a Research thesis. Nothing here sizes a
position, allocates capital, or reaches a broker.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Mapping

from investment_research_os.quant import (
    BacktestConfig,
    BacktestResult,
    CostModel,
    ParticipationLimit,
    PointInTimeDataset,
    QuantContractError,
    ValidationReport,
    simple_returns,
    summarise_returns,
    validate_walk_forward,
    run_backtest,
)
from investment_research_os.quant.bars import canonical_sha256, decimal_text
from investment_research_os.quant.validation import (
    CostScenario,
    CostSensitivityConfig,
    MultipleTestingDisclosure,
    WalkForwardConfig,
)
from workers.quant_workspace.intake import QuantWorkspaceError
from workers.quant_workspace.strategies import (
    BENCHMARK_CONFIG_SHA256,
    BENCHMARK_STRATEGY_ID,
    BuyAndHoldStrategy,
    TrendFollowingConfig,
    TrendFollowingFactory,
    TrendFollowingStrategy,
)

QUANT_RESULT_CONTRACT_VERSION = "quant_local_result.v1"
RUNNER_VERSION = "quant-workspace-runner-1"

#: The interval this workspace supports. Declared rather than inferred, and
#: pinned into the assumptions record so a future widening is a visible change.
BAR_INTERVAL = "1d"
BASELINE_SCENARIO_LABEL = "declared"
STRESSED_SCENARIO_LABEL = "stressed"

#: Limitations that hold for every run this workspace produces. They are codes,
#: not sentences, so the browser owns the wording and no free text travels.
STANDING_LIMITATIONS = (
    "historical_analysis_not_prediction",
    "single_security_no_universe",
    "operator_declared_provenance",
    "split_adjusted_closes_only",
    "no_dividends_modelled",
    "declared_trials_unverifiable",
)

_DECIMAL_FIELDS = (
    "alpha",
    "commission_bps",
    "commission_minimum",
    "commission_per_share",
    "cost_stress_multiplier",
    "max_participation_bps",
    "slippage_bps",
    "starting_cash",
    "transaction_cost_bps",
)
_INTEGER_FIELDS = (
    "annualisation_periods",
    "embargo_sessions",
    "lookback_sessions",
    "min_fill_shares",
    "min_total_trades",
    "min_trades_per_window",
    "min_windows",
    "step_sessions",
    "test_sessions",
    "train_sessions",
    "trials_declared",
)


@dataclass(frozen=True, slots=True)
class QuantRunAssumptions:
    """Every declared input a run needs, and nothing it could infer.

    Held as text for the decimal fields. Text is what the operator typed, what
    the record stores, and what hashes stably; converting early and formatting
    late would put a rounding decision between the two.
    """

    alpha: str
    annualisation_periods: int
    commission_bps: str
    commission_minimum: str
    commission_per_share: str
    cost_stress_multiplier: str
    embargo_sessions: int
    lookback_sessions: int
    max_participation_bps: str
    min_fill_shares: int
    min_total_trades: int
    min_trades_per_window: int
    min_windows: int
    slippage_bps: str
    starting_cash: str
    step_sessions: int
    test_sessions: int
    train_sessions: int
    transaction_cost_bps: str
    trials_declared: int

    def to_record(self) -> dict[str, object]:
        record: dict[str, object] = dict(asdict(self))
        record["bar_interval"] = BAR_INTERVAL
        record["baseline_scenario_label"] = BASELINE_SCENARIO_LABEL
        record["fractional_share_policy"] = "error"
        record["multiple_testing_adjustment"] = "bonferroni"
        record["runner_version"] = RUNNER_VERSION
        record["stressed_scenario_label"] = STRESSED_SCENARIO_LABEL
        record["unfilled_policy"] = "cancel"
        record["window_mode"] = "rolling"
        record["zero_volume_policy"] = "block"
        return record

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.to_record())


def _invalid(message: str) -> QuantWorkspaceError:
    return QuantWorkspaceError("run_assumptions_invalid", message)


def assumptions_from_mapping(values: Mapping[str, object]) -> QuantRunAssumptions:
    """Build assumptions from untrusted input, or refuse.

    Exact field set, no defaults, no extras. A missing field is not filled in
    because a silent default is exactly the assumption an operator would never
    have agreed to, and an unexpected field is refused because it may be an
    attempt to reach something this contract does not offer.
    """

    if not isinstance(values, Mapping):
        raise _invalid("assumptions must be an object")
    expected = set(_DECIMAL_FIELDS) | set(_INTEGER_FIELDS)
    if set(values) != expected:
        raise _invalid("assumption fields do not match the supported contract")

    parsed: dict[str, object] = {}
    for field in _DECIMAL_FIELDS:
        raw = values[field]
        # A float here would make the run irreproducible, so decimal text is
        # required rather than accepted-and-converted.
        if not isinstance(raw, str) or not raw.strip():
            raise _invalid(f"{field} must be decimal text")
        try:
            number = Decimal(raw)
        except ArithmeticError as error:
            raise _invalid(f"{field} is not a decimal") from error
        if not number.is_finite() or number < 0:
            raise _invalid(f"{field} must be a finite non-negative decimal")
        parsed[field] = raw
    for field in _INTEGER_FIELDS:
        raw = values[field]
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise _invalid(f"{field} must be a non-negative integer")
        parsed[field] = raw

    assumptions = QuantRunAssumptions(**parsed)  # type: ignore[arg-type]
    _check_ranges(assumptions)
    return assumptions


def _check_ranges(assumptions: QuantRunAssumptions) -> None:
    """The rules a per-field type check cannot express."""

    if Decimal(assumptions.starting_cash) <= 0:
        raise _invalid("starting_cash must be positive")
    if Decimal(assumptions.max_participation_bps) > Decimal(10_000):
        raise _invalid("max_participation_bps must not exceed 10000")
    if Decimal(assumptions.alpha) <= 0 or Decimal(assumptions.alpha) >= 1:
        raise _invalid("alpha must sit between 0 and 1")
    if Decimal(assumptions.cost_stress_multiplier) < 1:
        raise _invalid("cost_stress_multiplier must be at least 1")
    if assumptions.lookback_sessions < 2:
        raise _invalid("lookback_sessions must be at least 2")
    for field in ("train_sessions", "test_sessions", "step_sessions"):
        if getattr(assumptions, field) < 1:
            raise _invalid(f"{field} must be at least 1")
    if assumptions.min_windows < 1:
        raise _invalid("min_windows must be at least 1")
    if assumptions.annualisation_periods < 1:
        raise _invalid("annualisation_periods must be at least 1")
    # Two scenarios always run, so a declaration below two would understate the
    # family this run itself evaluated.
    if assumptions.trials_declared < 2:
        raise _invalid("trials_declared must be at least 2")


def run_key(*, dataset_sha256: str, assumptions: QuantRunAssumptions) -> str:
    """Stable identity of one request: this dataset under these assumptions."""

    return canonical_sha256(
        {
            "assumptions_sha256": assumptions.content_sha256,
            "contract_version": QUANT_RESULT_CONTRACT_VERSION,
            "dataset_sha256": dataset_sha256,
        }
    )


def _cost_model(assumptions: QuantRunAssumptions, *, multiplier: Decimal) -> CostModel:
    return CostModel(
        commission_per_share=Decimal(assumptions.commission_per_share) * multiplier,
        commission_bps=Decimal(assumptions.commission_bps) * multiplier,
        commission_minimum=Decimal(assumptions.commission_minimum) * multiplier,
        transaction_cost_bps=Decimal(assumptions.transaction_cost_bps) * multiplier,
        slippage_bps=Decimal(assumptions.slippage_bps) * multiplier,
    )


def _liquidity(assumptions: QuantRunAssumptions) -> ParticipationLimit:
    return ParticipationLimit(
        max_participation_bps=Decimal(assumptions.max_participation_bps),
        volume_basis="execution_bar",
        zero_volume_policy="block",
        unfilled_policy="cancel",
        min_fill_shares=assumptions.min_fill_shares,
    )


def _schedule(assumptions: QuantRunAssumptions) -> WalkForwardConfig:
    return WalkForwardConfig(
        train_sessions=assumptions.train_sessions,
        test_sessions=assumptions.test_sessions,
        step_sessions=assumptions.step_sessions,
        embargo_sessions=assumptions.embargo_sessions,
        window_mode="rolling",
        min_windows=assumptions.min_windows,
        min_trades_per_window=assumptions.min_trades_per_window,
        min_total_trades=assumptions.min_total_trades,
    )


def _statistics_record(result: BacktestResult, *, periods: int) -> dict[str, object]:
    """Dispersion of the equity curve, or an explicit absence of it.

    A curve with one point has no return series and a flat curve has no
    dispersion. Both report ``null`` rather than zero: a zero would read as a
    measurement of no risk, which is a different claim entirely.
    """

    equity = [point.equity for point in result.equity_curve]
    if len(equity) < 2:
        return {"return_observations": 0, "sharpe_ratio": None, "volatility": None}
    statistics = summarise_returns(
        simple_returns(equity), annualisation_periods=periods
    )
    return {
        "return_observations": statistics.count,
        "sharpe_ratio": (
            None
            if statistics.sharpe_ratio is None
            else decimal_text(statistics.sharpe_ratio)
        ),
        "volatility": (
            None if statistics.stdev is None else decimal_text(statistics.stdev)
        ),
    }


def _outcome_record(
    result: BacktestResult, *, strategy_id: str, config_sha256: str, periods: int
) -> dict[str, object]:
    """One backtest reduced to declared identity plus aggregate outcome.

    Deliberately no equity curve, no trade list, and no decision trace: those
    restate the dataset, and the dataset never leaves this process.
    """

    cost_total = (
        result.total_commission
        + result.total_transaction_cost
        + result.total_slippage_cost
    )
    record: dict[str, object] = {
        "backtest_sha256": result.content_sha256,
        "commission": decimal_text(result.total_commission),
        "constrained_decisions": result.constrained_decision_count,
        "cost_total": decimal_text(cost_total),
        "final_equity": decimal_text(result.final_equity),
        "max_drawdown": decimal_text(result.max_drawdown),
        "slippage": decimal_text(result.total_slippage_cost),
        "strategy_config_sha256": config_sha256,
        "strategy_id": strategy_id,
        "total_return": decimal_text(result.total_return),
        "trade_count": len(result.trades),
        "transaction_cost": decimal_text(result.total_transaction_cost),
        "unfilled_shares": result.total_unfilled_shares,
        "zero_fill_decisions": result.zero_fill_count,
    }
    record.update(_statistics_record(result, periods=periods))
    return record


def _validation_gaps(report: ValidationReport) -> tuple[str, ...]:
    """What this validation could not establish, as codes.

    Separate from ``reason_codes``: those say why the verdict came out as it
    did, while these say which parts of the question the run left unanswered.
    An operator reading only the verdict would otherwise miss that the windows
    overlapped or that the benchmark was never reachable.
    """

    gaps: list[str] = []
    if report.outcome == "insufficient_data":
        gaps.append("insufficient_windows")
    if report.test_windows_overlap:
        gaps.append("overlapping_test_windows")
    if any(not result.benchmark_reachable for result in report.window_results):
        gaps.append("benchmark_unreachable")
    if report.degrees_of_freedom_bucket is None:
        gaps.append("below_smallest_significance_sample")
    if report.alpha_label is None:
        gaps.append("alpha_outside_critical_value_table")
    if any(
        summary.statistics.stdev is None or summary.statistics.t_statistic is None
        for summary in report.scenario_summaries
    ):
        gaps.append("dispersion_unmeasurable")
    if report.first_failing_scenario_label is not None:
        gaps.append("fails_under_higher_costs")
    return tuple(gaps)


def _validation_record(report: ValidationReport) -> dict[str, object]:
    return {
        "alpha_effective": decimal_text(report.disclosure.alpha_effective),
        "alpha_label": report.alpha_label,
        "baseline_scenario_label": report.cost_sensitivity.baseline_label,
        "degrees_of_freedom": report.degrees_of_freedom,
        "degrees_of_freedom_bucket": report.degrees_of_freedom_bucket,
        "first_failing_scenario_label": report.first_failing_scenario_label,
        "gaps": list(_validation_gaps(report)),
        "highest_passing_scenario_label": report.highest_passing_scenario_label,
        "outcome": report.outcome,
        "reason_codes": list(report.reason_codes),
        "report_sha256": report.content_sha256,
        "scenarios": [
            {
                "aggregate_excess": decimal_text(summary.aggregate_excess),
                "critical_value": (
                    None
                    if summary.critical_value is None
                    else decimal_text(summary.critical_value)
                ),
                "label": summary.label,
                "mean_excess": decimal_text(summary.statistics.mean),
                "passed": summary.passed,
                "t_statistic": (
                    None
                    if summary.statistics.t_statistic is None
                    else decimal_text(summary.statistics.t_statistic)
                ),
                "windows_beating_benchmark": summary.windows_beating_benchmark,
            }
            for summary in report.scenario_summaries
        ],
        "test_windows_overlap": report.test_windows_overlap,
        "window_count": report.window_count,
        "windows_beating_benchmark": report.windows_beating_benchmark,
    }


def run_quant_analysis(
    *,
    dataset: PointInTimeDataset,
    assumptions: QuantRunAssumptions,
) -> dict[str, object]:
    """Backtest, benchmark, and validate one dataset under declared assumptions.

    Deterministic: no clock, no network, no randomness, and no timestamp in the
    record. The same dataset and the same assumptions produce byte-identical
    output, which is what lets a restart reload a result instead of recomputing
    a different one.
    """

    if not isinstance(assumptions, QuantRunAssumptions):
        raise _invalid("assumptions must be a validated QuantRunAssumptions")
    _check_ranges(assumptions)

    periods = assumptions.annualisation_periods
    baseline_costs = _cost_model(assumptions, multiplier=Decimal(1))
    stressed_costs = _cost_model(
        assumptions, multiplier=Decimal(assumptions.cost_stress_multiplier)
    )
    liquidity = _liquidity(assumptions)
    config = BacktestConfig(
        starting_cash=Decimal(assumptions.starting_cash),
        fractional_share_policy="error",
    )
    strategy_config = TrendFollowingConfig(
        lookback_sessions=assumptions.lookback_sessions
    )

    try:
        strategy_result = run_backtest(
            dataset=dataset,
            strategy=TrendFollowingStrategy(config=strategy_config),
            costs=baseline_costs,
            liquidity=liquidity,
            config=config,
            strategy_id=strategy_config.to_record()["strategy_id"],  # type: ignore[arg-type]
            strategy_config_sha256=strategy_config.content_sha256,
        )
        benchmark_result = run_backtest(
            dataset=dataset,
            strategy=BuyAndHoldStrategy(),
            costs=baseline_costs,
            liquidity=liquidity,
            config=config,
            strategy_id=BENCHMARK_STRATEGY_ID,
            strategy_config_sha256=BENCHMARK_CONFIG_SHA256,
        )
        report = validate_walk_forward(
            dataset=dataset,
            liquidity=liquidity,
            config=config,
            schedule=_schedule(assumptions),
            factory=TrendFollowingFactory(
                lookback_sessions=assumptions.lookback_sessions
            ),
            strategy_id=str(strategy_config.to_record()["strategy_id"]),
            cost_sensitivity=CostSensitivityConfig(
                scenarios=(
                    CostScenario(label=BASELINE_SCENARIO_LABEL, costs=baseline_costs),
                    CostScenario(label=STRESSED_SCENARIO_LABEL, costs=stressed_costs),
                ),
                baseline_label=BASELINE_SCENARIO_LABEL,
            ),
            disclosure=MultipleTestingDisclosure(
                trials_declared=assumptions.trials_declared,
                family_label="quant_workspace_local_run",
                adjustment="bonferroni",
                alpha=assumptions.alpha,
            ),
            annualisation_periods=periods,
        )
    except QuantContractError as error:
        # The dataset receipt and the execution inputs are rechecked inside the
        # engine. A refusal there means the receipt reaching this run no longer
        # holds the guarantees its type implies, which is a hard stop rather
        # than something to report as a poor result.
        raise QuantWorkspaceError(
            "run_dataset_invalid", "dataset or execution inputs failed revalidation"
        ) from error

    strategy_record = _outcome_record(
        strategy_result,
        strategy_id=str(strategy_config.to_record()["strategy_id"]),
        config_sha256=strategy_config.content_sha256,
        periods=periods,
    )
    benchmark_record = _outcome_record(
        benchmark_result,
        strategy_id=BENCHMARK_STRATEGY_ID,
        config_sha256=BENCHMARK_CONFIG_SHA256,
        periods=periods,
    )
    excess = strategy_result.total_return - benchmark_result.total_return

    record: dict[str, object] = {
        "as_of_cutoff": dataset.as_of_cutoff.isoformat(),
        "assumptions": assumptions.to_record(),
        "benchmark": benchmark_record,
        "contract_version": QUANT_RESULT_CONTRACT_VERSION,
        "corporate_actions_sha256": dataset.corporate_actions.content_sha256,
        "currency": dataset.series.currency,
        "dataset_sha256": dataset.content_sha256,
        "excess_return": decimal_text(excess),
        "first_session": dataset.series.bars[0].session.isoformat(),
        "last_session": dataset.series.bars[-1].session.isoformat(),
        "limitations": list(STANDING_LIMITATIONS),
        "security_id": dataset.security_id,
        "series_sha256": dataset.series.content_sha256,
        "session_count": len(dataset.series.bars),
        "source_content_sha256": dataset.source_content_sha256,
        "source_id": dataset.source_id,
        "source_revision": dataset.source_revision,
        "split_count": len(dataset.corporate_actions.actions),
        "strategy": strategy_record,
        "validation": _validation_record(report),
    }
    # The identity is computed over everything above and then added, so a
    # record can be rehashed on read to prove it was not edited in place.
    record["content_sha256"] = canonical_sha256(record)
    return record

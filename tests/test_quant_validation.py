from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal

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
from investment_research_os.quant.validation import (
    CostScenario,
    _slice_dataset,
    CostSensitivityConfig,
    MultipleTestingDisclosure,
    VALIDATION_VERSION,
    WalkForwardConfig,
    build_walk_forward_windows,
    validate_walk_forward,
)

SECURITY_ID = "3f1b0c2e-9d4a-4c7f-b1e2-8a5d6c7f0912"
START = date(2026, 1, 5)

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

OPEN_LIQUIDITY = ParticipationLimit(
    max_participation_bps=Decimal("10000"),
    volume_basis="execution_bar",
    zero_volume_policy="block",
    unfilled_policy="cancel",
    min_fill_shares=0,
)

CLOSED_LIQUIDITY = ParticipationLimit(
    max_participation_bps=Decimal("0"),
    volume_basis="execution_bar",
    zero_volume_policy="block",
    unfilled_policy="cancel",
    min_fill_shares=0,
)

# One basis point of a 1,000,000-share session is a 100-share cap, well under
# the ~200 shares buy-and-hold needs. It trades, but never reaches exposure.
TIGHT_LIQUIDITY = ParticipationLimit(
    max_participation_bps=Decimal("1"),
    volume_basis="execution_bar",
    zero_volume_policy="block",
    unfilled_policy="cancel",
    min_fill_shares=0,
)

CONFIG = BacktestConfig(
    starting_cash=Decimal("100000"),
    fractional_share_policy="error",
)


def make_series(prices: list[str], *, volume: int = 1_000_000) -> BarSeries:
    bars = []
    for index, price in enumerate(prices):
        value = Decimal(price)
        bars.append(
            OhlcvBar(
                session=START + timedelta(days=index),
                open=value,
                high=value,
                low=value,
                close=value,
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


def rising_prices(count: int) -> list[str]:
    """Irregular uptrend, so buy-and-hold is the thing to beat."""

    prices: list[str] = []
    value = Decimal("300")
    for index in range(count):
        value = value + Decimal("1") + Decimal(index % 7) / Decimal("10")
        prices.append(format(value, "f"))
    return prices


def declining_prices(count: int) -> list[str]:
    """Irregular downtrend. Deterministic, no RNG, non-zero dispersion."""

    prices: list[str] = []
    value = Decimal("500")
    for index in range(count):
        step = Decimal("1") + Decimal(index % 7) / Decimal("10")
        value = value - step
        prices.append(format(value, "f"))
    return prices


def no_actions() -> CorporateActionSet:
    return CorporateActionSet(security_id=SECURITY_ID, source="fixture", actions=())


class AlwaysFlat:
    def target_exposure(self, window: BarWindow) -> Decimal:
        return Decimal(0)


class AlwaysLong:
    def target_exposure(self, window: BarWindow) -> Decimal:
        return Decimal(1)


class FlatFactory:
    """Fits nothing. Deterministic by construction."""

    def __init__(self) -> None:
        self.calls = 0
        self.cutoffs: list[date] = []
        self.window_lengths: list[int] = []

    def build(self, train_window: BarWindow) -> tuple[AlwaysFlat, str]:
        self.calls += 1
        self.cutoffs.append(train_window.cutoff)
        self.window_lengths.append(len(train_window.bars))
        return AlwaysFlat(), "a" * 64


class LongFactory:
    def build(self, train_window: BarWindow) -> tuple[AlwaysLong, str]:
        return AlwaysLong(), "b" * 64


class PeekingFactory:
    def build(self, train_window: BarWindow) -> tuple[AlwaysFlat, str]:
        train_window.at(train_window.cutoff + timedelta(days=1))
        return AlwaysFlat(), "c" * 64


class DriftingFactory:
    def __init__(self) -> None:
        self.calls = 0

    def build(self, train_window: BarWindow) -> tuple[AlwaysFlat, str]:
        self.calls += 1
        return AlwaysFlat(), format(self.calls, "064d")


def schedule(**overrides: object) -> WalkForwardConfig:
    base: dict[str, object] = {
        "train_sessions": 20,
        "test_sessions": 5,
        "step_sessions": 5,
        "embargo_sessions": 2,
        "window_mode": "rolling",
        "min_windows": 11,
        "min_trades_per_window": 0,
        "min_total_trades": 0,
    }
    base.update(overrides)
    return WalkForwardConfig(**base)  # type: ignore[arg-type]


def sensitivity(*labels_and_costs: tuple[str, CostModel]) -> CostSensitivityConfig:
    scenarios = tuple(
        CostScenario(label=label, costs=costs) for label, costs in labels_and_costs
    )
    return CostSensitivityConfig(scenarios=scenarios, baseline_label=scenarios[-1].label)


def disclosure(**overrides: object) -> MultipleTestingDisclosure:
    base: dict[str, object] = {
        "trials_declared": 2,
        "family_label": "fixture-family",
        "adjustment": "bonferroni",
        "alpha": "0.05",
    }
    base.update(overrides)
    return MultipleTestingDisclosure(**base)  # type: ignore[arg-type]


SOURCE_HASH = "b" * 64


def make_dataset(
    series: BarSeries,
    corporate_actions: CorporateActionSet | None = None,
    **overrides: object,
) -> PointInTimeDataset:
    base: dict[str, object] = {
        "series": series,
        "corporate_actions": corporate_actions or no_actions(),
        "as_of_cutoff": series.bars[-1].session,
        "source_id": "fixture-source",
        "source_revision": "rev-1",
        "source_content_sha256": SOURCE_HASH,
        "coverage_scope": "single_security",
    }
    base.update(overrides)
    return PointInTimeDataset(**base)  # type: ignore[arg-type]


def validate(
    *,
    dataset: PointInTimeDataset | None = None,
    series: BarSeries | None = None,
    factory: object | None = None,
    liquidity: ParticipationLimit = OPEN_LIQUIDITY,
    corporate_actions: CorporateActionSet | None = None,
    walk_forward: WalkForwardConfig | None = None,
    costs: CostSensitivityConfig | None = None,
    testing: MultipleTestingDisclosure | None = None,
):
    return validate_walk_forward(
        dataset=dataset
        or make_dataset(
            series or make_series(declining_prices(120)),
            corporate_actions,
        ),
        liquidity=liquidity,
        config=CONFIG,
        schedule=walk_forward or schedule(),
        factory=factory or FlatFactory(),
        strategy_id="fixture-strategy",
        cost_sensitivity=costs or sensitivity(("free", FREE), ("retail", RETAIL)),
        disclosure=testing or disclosure(),
        annualisation_periods=1,
    )


class ScheduleTests(unittest.TestCase):
    def test_chronology_invariant_holds_across_a_parameter_grid(self) -> None:
        for train in (5, 20):
            for test in (2, 5):
                for step in (1, 5):
                    for embargo in (0, 3):
                        windows = build_walk_forward_windows(
                            session_count=200,
                            config=schedule(
                                train_sessions=train,
                                test_sessions=test,
                                step_sessions=step,
                                embargo_sessions=embargo,
                                min_windows=1,
                            ),
                        )
                        self.assertTrue(windows)
                        for window in windows:
                            self.assertLess(
                                window.train_start_index, window.train_end_index
                            )
                            if embargo:
                                self.assertLess(
                                    window.train_end_index, window.embargo_end_index
                                )
                            self.assertLess(
                                window.embargo_end_index, window.test_start_index
                            )
                            self.assertLessEqual(
                                window.test_start_index, window.test_end_index
                            )
                            self.assertEqual(
                                window.embargo_end_index,
                                window.train_end_index + embargo,
                            )

    def test_embargoed_sessions_belong_to_neither_period(self) -> None:
        windows = build_walk_forward_windows(
            session_count=100,
            config=schedule(embargo_sessions=5, min_windows=1),
        )
        for window in windows:
            embargoed = set(
                range(window.train_end_index + 1, window.test_start_index)
            )
            self.assertEqual(len(embargoed), 5)
            train = set(range(window.train_start_index, window.train_end_index + 1))
            test = set(range(window.test_start_index, window.test_end_index + 1))
            self.assertFalse(embargoed & train)
            self.assertFalse(embargoed & test)

    def test_zero_embargo_is_legal(self) -> None:
        windows = build_walk_forward_windows(
            session_count=100,
            config=schedule(embargo_sessions=0, min_windows=1),
        )
        self.assertTrue(windows)
        self.assertEqual(windows[0].embargo_end_index, windows[0].train_end_index)

    def test_partial_trailing_window_is_discarded(self) -> None:
        # train 20 + embargo 2 + test 5 -> window w ends at index 26 + 5w.
        # 43 sessions (last index 42) fits w = 0..3 ending at 41. Session 42 is
        # left unused rather than becoming a stunted fifth window.
        windows = build_walk_forward_windows(
            session_count=43,
            config=schedule(min_windows=1),
        )
        self.assertEqual(len(windows), 4)
        self.assertEqual(windows[-1].test_end_index, 41)

    def test_anchored_mode_grows_the_training_period(self) -> None:
        windows = build_walk_forward_windows(
            session_count=100,
            config=schedule(window_mode="anchored", min_windows=1),
        )
        self.assertTrue(all(window.train_start_index == 0 for window in windows))
        self.assertLess(windows[0].train_end_index, windows[1].train_end_index)

    def test_schedule_rejects_windows_shorter_than_a_series(self) -> None:
        with self.assertRaises(QuantContractError):
            schedule(train_sessions=1)
        with self.assertRaises(QuantContractError):
            schedule(test_sessions=1)
        with self.assertRaises(QuantContractError):
            schedule(step_sessions=0)
        with self.assertRaises(QuantContractError):
            schedule(embargo_sessions=-1)


class LeakageTests(unittest.TestCase):
    def test_the_factory_only_ever_sees_training_sessions(self) -> None:
        factory = FlatFactory()
        report = validate(factory=factory)
        self.assertEqual(factory.calls, len(report.windows))
        for window, cutoff in zip(report.windows, factory.cutoffs):
            self.assertEqual(cutoff, window.train_end_session)
            self.assertLess(cutoff, window.test_start_session)

    def test_a_factory_reaching_past_its_window_raises(self) -> None:
        with self.assertRaises(LookAheadError):
            validate(factory=PeekingFactory())

    def test_a_prebuilt_strategy_cannot_be_passed(self) -> None:
        with self.assertRaises(QuantContractError):
            validate(factory=AlwaysFlat())


class CorporateActionTests(unittest.TestCase):
    def test_a_split_on_a_test_windows_first_session_is_handled(self) -> None:
        series = make_series([format(Decimal(200 - index), "f") for index in range(12)])
        split_session = series.bars[2].session
        actions = CorporateActionSet(
            security_id=SECURITY_ID,
            source="fixture",
            actions=(
                StockSplit(
                    effective_session=split_session,
                    new_shares=2,
                    old_shares=1,
                ),
            ),
        )

        # Without a lead-in bar the split lands on the slice's first session,
        # which the engine never transitions into, and the run dies.
        naked_slice = BarSeries(
            security_id=SECURITY_ID,
            currency="USD",
            interval="1d",
            price_basis="unadjusted",
            source="fixture",
            bars=series.bars[2:4],
        )
        with self.assertRaises(QuantContractError):
            run_backtest(
                dataset=make_dataset(naked_slice, actions),
                strategy=AlwaysLong(),
                costs=FREE,
                liquidity=OPEN_LIQUIDITY,
                config=CONFIG,
                strategy_id="probe",
                strategy_config_sha256="d" * 64,
            )

        report = validate(
            series=series,
            corporate_actions=actions,
            walk_forward=schedule(
                train_sessions=2,
                test_sessions=2,
                step_sessions=2,
                embargo_sessions=0,
                min_windows=1,
            ),
            testing=disclosure(trials_declared=2),
        )
        self.assertTrue(report.windows)
        self.assertEqual(report.windows[0].test_start_session, split_session)

    def test_actions_outside_a_window_do_not_reach_the_engine(self) -> None:
        series = make_series(declining_prices(120))
        actions = CorporateActionSet(
            security_id=SECURITY_ID,
            source="fixture",
            actions=(
                StockSplit(
                    effective_session=series.bars[100].session,
                    new_shares=2,
                    old_shares=1,
                ),
            ),
        )
        report = validate(series=series, corporate_actions=actions)
        self.assertTrue(report.windows)


class DatasetBoundaryTests(unittest.TestCase):
    def test_raw_series_and_actions_are_no_longer_accepted(self) -> None:
        with self.assertRaises(TypeError):
            validate_walk_forward(  # type: ignore[call-arg]
                series=make_series(declining_prices(120)),
                corporate_actions=no_actions(),
                liquidity=OPEN_LIQUIDITY,
                config=CONFIG,
                schedule=schedule(),
                factory=FlatFactory(),
                strategy_id="fixture-strategy",
                cost_sensitivity=sensitivity(("free", FREE), ("retail", RETAIL)),
                disclosure=disclosure(),
                annualisation_periods=1,
            )

    def test_the_report_pins_the_parent_dataset_hash(self) -> None:
        dataset = make_dataset(make_series(declining_prices(120)))
        report = validate(dataset=dataset)
        record = report.to_record()
        self.assertEqual(report.dataset_sha256, dataset.content_sha256)
        self.assertEqual(record["dataset_sha256"], dataset.content_sha256)
        self.assertEqual(record["validation_version"], "quant-validation-2")
        self.assertEqual(record["engine_version"], "quant-backtest-4")

    def test_source_revision_alone_changes_the_report_hash(self) -> None:
        series = make_series(declining_prices(120))
        first = validate(dataset=make_dataset(series))
        second = validate(dataset=make_dataset(series, source_revision="rev-2"))
        self.assertEqual(first.series_sha256, second.series_sha256)
        self.assertNotEqual(first.content_sha256, second.content_sha256)

    def test_source_content_hash_alone_changes_the_report_hash(self) -> None:
        series = make_series(declining_prices(120))
        first = validate(dataset=make_dataset(series))
        second = validate(
            dataset=make_dataset(series, source_content_sha256="c" * 64)
        )
        self.assertNotEqual(first.content_sha256, second.content_sha256)

    def test_a_bar_after_the_cutoff_is_refused_before_any_fitting(self) -> None:
        dataset = make_dataset(make_series(declining_prices(120)))
        object.__setattr__(dataset, "as_of_cutoff", dataset.series.bars[0].session)
        factory = FlatFactory()
        with self.assertRaisesRegex(QuantContractError, "cutoff"):
            validate(dataset=dataset, factory=factory)
        self.assertEqual(factory.calls, 0)

    def test_an_action_after_the_cutoff_is_refused_before_any_fitting(self) -> None:
        series = make_series(declining_prices(120))
        actions = CorporateActionSet(
            security_id=SECURITY_ID,
            source="fixture",
            actions=(
                StockSplit(
                    effective_session=series.bars[100].session,
                    new_shares=2,
                    old_shares=1,
                ),
            ),
        )
        dataset = make_dataset(series, actions)
        object.__setattr__(dataset, "as_of_cutoff", series.bars[50].session)
        factory = FlatFactory()
        with self.assertRaisesRegex(QuantContractError, "cutoff"):
            validate(dataset=dataset, factory=factory)
        self.assertEqual(factory.calls, 0)

    def test_a_window_slice_keeps_the_parent_declarations_and_no_future_bars(
        self,
    ) -> None:
        series = make_series(declining_prices(120))
        parent = make_dataset(series)
        sliced = _slice_dataset(parent, 10, 20)
        self.assertEqual(sliced.source_id, parent.source_id)
        self.assertEqual(sliced.source_revision, parent.source_revision)
        self.assertEqual(
            sliced.source_content_sha256, parent.source_content_sha256
        )
        self.assertEqual(sliced.as_of_cutoff, parent.as_of_cutoff)
        self.assertEqual(sliced.coverage_scope, parent.coverage_scope)
        self.assertEqual(sliced.security_id, parent.security_id)
        self.assertEqual(sliced.series.bars, series.bars[10:21])
        self.assertEqual(sliced.series.bars[-1].session, series.bars[20].session)

    def test_the_report_hash_ignores_the_ambient_decimal_context(self) -> None:
        from decimal import Context, localcontext

        dataset = make_dataset(make_series(declining_prices(120)))
        baseline = validate(dataset=dataset).content_sha256
        for precision in (5, 60):
            with localcontext(Context(prec=precision)):
                self.assertEqual(validate(dataset=dataset).content_sha256, baseline)

    def test_a_forged_receipt_field_is_refused_before_any_fitting(self) -> None:
        mutations: tuple[tuple[str, object], ...] = (
            ("source_content_sha256", "forged"),
            ("source_id", "   "),
            ("source_revision", ""),
            ("coverage_scope", "universe"),
            ("as_of_cutoff", datetime(2026, 5, 4, 20, 0)),
            ("series", object()),
            ("corporate_actions", object()),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                dataset = make_dataset(make_series(declining_prices(120)))
                object.__setattr__(dataset, field, value)
                factory = FlatFactory()
                with self.assertRaises(QuantContractError):
                    validate(dataset=dataset, factory=factory)
                self.assertEqual(factory.calls, 0)


def _split_receipt() -> PointInTimeDataset:
    series = make_series(declining_prices(120))
    actions = CorporateActionSet(
        security_id=SECURITY_ID,
        source="fixture",
        actions=(
            StockSplit(series.bars[100].session, 2, 1),
            StockSplit(series.bars[101].session, 2, 1),
        ),
    )
    return make_dataset(series, actions)


def _plain_receipt() -> PointInTimeDataset:
    return make_dataset(make_series(declining_prices(120)))


CHILD_MUTATIONS = (
    (
        "bar_open_negative",
        _plain_receipt,
        lambda d: object.__setattr__(d.series.bars[0], "open", Decimal("-1")),
    ),
    (
        "bar_session_datetime",
        _plain_receipt,
        lambda d: object.__setattr__(
            d.series.bars[0], "session", datetime(2026, 1, 5, 16, 0)
        ),
    ),
    (
        "bar_session_duplicate",
        _plain_receipt,
        lambda d: object.__setattr__(
            d.series.bars[1], "session", d.series.bars[0].session
        ),
    ),
    (
        "bar_high_below_open",
        _plain_receipt,
        lambda d: object.__setattr__(d.series.bars[0], "high", Decimal("1")),
    ),
    (
        "bars_to_list",
        _plain_receipt,
        lambda d: object.__setattr__(d.series, "bars", list(d.series.bars)),
    ),
    (
        "bars_contain_object",
        _plain_receipt,
        lambda d: object.__setattr__(d.series, "bars", d.series.bars + (object(),)),
    ),
    (
        "split_ratio_zero",
        _split_receipt,
        lambda d: object.__setattr__(d.corporate_actions.actions[0], "new_shares", 0),
    ),
    (
        "split_ratio_bool",
        _split_receipt,
        lambda d: object.__setattr__(
            d.corporate_actions.actions[0], "new_shares", True
        ),
    ),
    (
        "split_ratio_unreduced",
        _split_receipt,
        lambda d: [
            object.__setattr__(d.corporate_actions.actions[0], "new_shares", 4),
            object.__setattr__(d.corporate_actions.actions[0], "old_shares", 2),
        ],
    ),
    (
        "split_session_datetime",
        _split_receipt,
        lambda d: object.__setattr__(
            d.corporate_actions.actions[0],
            "effective_session",
            datetime(2026, 4, 15, 9, 30),
        ),
    ),
    (
        "actions_unordered",
        _split_receipt,
        lambda d: object.__setattr__(
            d.corporate_actions, "actions", tuple(reversed(d.corporate_actions.actions))
        ),
    ),
    (
        "actions_duplicate_session",
        _split_receipt,
        lambda d: object.__setattr__(
            d.corporate_actions.actions[1],
            "effective_session",
            d.corporate_actions.actions[0].effective_session,
        ),
    ),
    (
        "actions_to_list",
        _split_receipt,
        lambda d: object.__setattr__(
            d.corporate_actions, "actions", list(d.corporate_actions.actions)
        ),
    ),
    (
        "actions_contain_object",
        _split_receipt,
        lambda d: object.__setattr__(d.corporate_actions, "actions", (object(),)),
    ),
)


class ChildContractRevalidationTests(unittest.TestCase):
    def test_a_mutated_child_contract_is_refused_before_any_fitting(self) -> None:
        for label, build, mutate in CHILD_MUTATIONS:
            with self.subTest(mutation=label):
                dataset = build()
                mutate(dataset)
                factory = FlatFactory()
                with self.assertRaises(QuantContractError):
                    validate(dataset=dataset, factory=factory)
                self.assertEqual(factory.calls, 0)

    def test_a_valid_receipt_with_splits_still_reports_and_hashes_stably(self) -> None:
        from decimal import Context, localcontext

        dataset = _split_receipt()
        baseline = validate(dataset=dataset)
        self.assertEqual(baseline.dataset_sha256, dataset.content_sha256)
        for precision in (5, 60):
            with localcontext(Context(prec=precision)):
                self.assertEqual(
                    validate(dataset=dataset).content_sha256, baseline.content_sha256
                )


def _fresh(model: CostModel) -> CostModel:
    return CostModel(
        commission_per_share=model.commission_per_share,
        commission_bps=model.commission_bps,
        commission_minimum=model.commission_minimum,
        transaction_cost_bps=model.transaction_cost_bps,
        slippage_bps=model.slippage_bps,
    )


EXECUTION_MUTATIONS = (
    ("config", "starting_cash", Decimal("-1")),
    ("config", "starting_cash", "10000"),
    ("config", "starting_cash", 10000.0),
    ("config", "fractional_share_policy", "cash_in_lieu"),
    ("costs", "slippage_bps", Decimal("-1")),
    ("costs", "slippage_bps", "10"),
    ("costs", "slippage_bps", 10.0),
    ("costs", "commission_minimum", Decimal("-1")),
    ("liquidity", "max_participation_bps", Decimal("20000")),
    ("liquidity", "max_participation_bps", Decimal("-1")),
    ("liquidity", "max_participation_bps", "500"),
    ("liquidity", "zero_volume_policy", "ignore"),
    ("liquidity", "unfilled_policy", "queue"),
    ("liquidity", "volume_basis", "session"),
    ("liquidity", "min_fill_shares", -1),
    ("liquidity", "min_fill_shares", True),
)


class ExecutionInputRevalidationTests(unittest.TestCase):
    def test_a_mutated_execution_input_is_refused_before_any_fitting(self) -> None:
        for owner, field, value in EXECUTION_MUTATIONS:
            with self.subTest(input=owner, field=field, value=repr(value)):
                config = BacktestConfig(
                    starting_cash=Decimal("10000"),
                    fractional_share_policy="error",
                )
                liquidity = ParticipationLimit(
                    max_participation_bps=Decimal("10000"),
                    volume_basis="execution_bar",
                    zero_volume_policy="block",
                    unfilled_policy="cancel",
                    min_fill_shares=0,
                )
                # Fresh cost models per case: the module-level FREE and RETAIL
                # fixtures are shared, and mutating one would poison every
                # later test in the file.
                scenarios = sensitivity(
                    ("free", _fresh(FREE)), ("retail", _fresh(RETAIL))
                )
                targets = {
                    "config": config,
                    "liquidity": liquidity,
                    # The second scenario's costs: a nested execution input,
                    # mutated after the parent objects were assembled.
                    "costs": scenarios.scenarios[1].costs,
                }
                object.__setattr__(targets[owner], field, value)
                factory = FlatFactory()
                with self.assertRaises(QuantContractError):
                    validate_walk_forward(
                        dataset=make_dataset(make_series(declining_prices(120))),
                        liquidity=liquidity,
                        config=config,
                        schedule=schedule(),
                        factory=factory,
                        strategy_id="fixture-strategy",
                        cost_sensitivity=scenarios,
                        disclosure=disclosure(),
                        annualisation_periods=1,
                    )
                self.assertEqual(factory.calls, 0)

    def test_a_mutated_scenario_collection_is_refused_before_any_fitting(self) -> None:
        for mutation in ("list", "object"):
            with self.subTest(mutation=mutation):
                scenarios = sensitivity(("free", FREE), ("retail", RETAIL))
                replacement = (
                    list(scenarios.scenarios)
                    if mutation == "list"
                    else (object(), object())
                )
                object.__setattr__(scenarios, "scenarios", replacement)
                factory = FlatFactory()
                with self.assertRaises(QuantContractError):
                    validate(factory=factory, costs=scenarios)
                self.assertEqual(factory.calls, 0)

    def test_valid_execution_inputs_still_report_and_hash_stably(self) -> None:
        from decimal import Context, localcontext

        baseline = validate()
        for precision in (5, 60):
            with localcontext(Context(prec=precision)):
                self.assertEqual(
                    validate().content_sha256, baseline.content_sha256
                )


SCHEDULE_MUTATIONS = (
    ("train_sessions_zero", "train_sessions", 0),
    ("train_sessions_negative", "train_sessions", -5),
    ("test_sessions_one", "test_sessions", 1),
    ("step_sessions_zero", "step_sessions", 0),
    ("embargo_negative", "embargo_sessions", -1),
    ("embargo_boolean", "embargo_sessions", True),
    ("min_windows_zero", "min_windows", 0),
    ("min_trades_negative", "min_trades_per_window", -1),
    ("min_total_trades_negative", "min_total_trades", -1),
    ("min_total_trades_string", "min_total_trades", "0"),
    ("window_mode_invalid", "window_mode", "expanding"),
)

DISCLOSURE_MUTATIONS = (
    ("trials_zero", "trials_declared", 0),
    ("trials_negative", "trials_declared", -3),
    ("trials_boolean", "trials_declared", True),
    ("trials_string", "trials_declared", "2"),
    ("adjustment_invalid", "adjustment", "holm"),
    ("adjustment_none_with_many_trials", "adjustment", "none"),
    ("alpha_zero", "alpha", "0"),
    ("alpha_one", "alpha", "1"),
    ("alpha_negative", "alpha", "-0.05"),
    ("alpha_not_a_number", "alpha", "forged"),
    ("alpha_float", "alpha", 0.05),
    ("family_label_blank", "family_label", "   "),
    ("family_label_non_string", "family_label", 7),
)


class PolicyRevalidationTests(unittest.TestCase):
    def _validate(self, *, factory, schedule_config=None, testing=None, costs=None):
        return validate_walk_forward(
            dataset=make_dataset(make_series(declining_prices(120))),
            liquidity=OPEN_LIQUIDITY,
            config=CONFIG,
            schedule=schedule_config or schedule(),
            factory=factory,
            strategy_id="fixture-strategy",
            cost_sensitivity=costs
            or sensitivity(("free", _fresh(FREE)), ("retail", _fresh(RETAIL))),
            disclosure=testing or disclosure(),
            annualisation_periods=1,
        )

    def test_a_mutated_schedule_is_refused_before_any_fitting(self) -> None:
        for label, field, value in SCHEDULE_MUTATIONS:
            with self.subTest(mutation=label):
                mutated = schedule()
                object.__setattr__(mutated, field, value)
                factory = FlatFactory()
                with self.assertRaises(QuantContractError):
                    self._validate(factory=factory, schedule_config=mutated)
                self.assertEqual(factory.calls, 0)

    def test_a_mutated_disclosure_is_refused_before_any_fitting(self) -> None:
        for label, field, value in DISCLOSURE_MUTATIONS:
            with self.subTest(mutation=label):
                mutated = disclosure(trials_declared=4)
                object.__setattr__(mutated, field, value)
                factory = FlatFactory()
                with self.assertRaises(QuantContractError):
                    self._validate(factory=factory, testing=mutated)
                self.assertEqual(factory.calls, 0)

    def test_declaring_no_adjustment_cannot_dodge_the_correction(self) -> None:
        # The constructor refuses adjustment="none" with several trials, so the
        # only way to reach it is mutation. If it crossed, alpha_effective would
        # be the raw alpha and the run would clear a threshold it never met.
        mutated = disclosure(trials_declared=4, alpha="0.05")
        object.__setattr__(mutated, "adjustment", "none")
        self.assertEqual(mutated.alpha_effective, Decimal("0.05"))
        factory = FlatFactory()
        with self.assertRaises(QuantContractError):
            self._validate(factory=factory, testing=mutated)
        self.assertEqual(factory.calls, 0)

    def test_a_mutated_cost_sensitivity_is_refused_before_any_fitting(self) -> None:
        def to_list(config: CostSensitivityConfig) -> None:
            object.__setattr__(config, "scenarios", list(config.scenarios))

        def to_empty(config: CostSensitivityConfig) -> None:
            object.__setattr__(config, "scenarios", ())

        def to_single(config: CostSensitivityConfig) -> None:
            object.__setattr__(config, "scenarios", config.scenarios[:1])

        def to_objects(config: CostSensitivityConfig) -> None:
            object.__setattr__(config, "scenarios", (object(), object()))

        def duplicate_labels(config: CostSensitivityConfig) -> None:
            object.__setattr__(config.scenarios[1], "label", "free")

        def blank_label(config: CostSensitivityConfig) -> None:
            object.__setattr__(config.scenarios[0], "label", "  ")

        def non_string_label(config: CostSensitivityConfig) -> None:
            object.__setattr__(config.scenarios[0], "label", 3)

        def unknown_baseline(config: CostSensitivityConfig) -> None:
            object.__setattr__(config, "baseline_label", "forged")

        def non_string_baseline(config: CostSensitivityConfig) -> None:
            object.__setattr__(config, "baseline_label", None)

        def scenario_costs_negative(config: CostSensitivityConfig) -> None:
            object.__setattr__(
                config.scenarios[1].costs, "slippage_bps", Decimal("-1")
            )

        mutations = (
            ("scenarios_to_list", to_list),
            ("scenarios_empty", to_empty),
            ("scenarios_single", to_single),
            ("scenarios_are_objects", to_objects),
            ("duplicate_labels", duplicate_labels),
            ("blank_label", blank_label),
            ("non_string_label", non_string_label),
            ("unknown_baseline", unknown_baseline),
            ("non_string_baseline", non_string_baseline),
            ("scenario_costs_negative", scenario_costs_negative),
        )
        for label, mutate in mutations:
            with self.subTest(mutation=label):
                mutated = sensitivity(
                    ("free", _fresh(FREE)), ("retail", _fresh(RETAIL))
                )
                mutate(mutated)
                factory = FlatFactory()
                with self.assertRaises(QuantContractError):
                    self._validate(factory=factory, costs=mutated)
                self.assertEqual(factory.calls, 0)

    def test_a_non_contract_policy_input_is_refused(self) -> None:
        for field in ("schedule_config", "testing", "costs"):
            with self.subTest(input=field):
                factory = FlatFactory()
                with self.assertRaises(QuantContractError):
                    self._validate(factory=factory, **{field: object()})
                self.assertEqual(factory.calls, 0)

    def test_valid_policy_inputs_still_report_and_hash_stably(self) -> None:
        from decimal import Context, localcontext

        factory_report = self._validate(factory=FlatFactory())
        for precision in (5, 60):
            with localcontext(Context(prec=precision)):
                self.assertEqual(
                    self._validate(factory=FlatFactory()).content_sha256,
                    factory_report.content_sha256,
                )

    def test_policy_constructors_still_accept_their_declared_input(self) -> None:
        self.assertEqual(disclosure(alpha="0.05").alpha_effective, Decimal("0.025"))
        self.assertEqual(
            sensitivity(("free", FREE), ("retail", RETAIL)).baseline.label, "retail"
        )
        self.assertTrue(schedule(window_mode="anchored").window_mode == "anchored")


ANNUALISATION_MUTATIONS = (
    ("zero", 0),
    ("negative", -4),
    ("boolean", True),
    ("string", "252"),
    ("float", 252.0),
    ("none", None),
)


class AlphaCompatibilityTests(unittest.TestCase):
    def test_previously_accepted_alpha_inputs_still_construct(self) -> None:
        # to_decimal accepted str, Decimal, and int before AC-028. All three
        # must keep constructing, and all three must land on the same stored
        # canonical text so the report hash does not depend on call style.
        for value in ("0.05", Decimal("0.05"), Decimal("0.0500")):
            with self.subTest(alpha=repr(value)):
                subject = disclosure(alpha=value)
                self.assertEqual(subject.alpha, "0.05")
                self.assertEqual(subject.alpha_effective, Decimal("0.025"))
                self.assertEqual(subject.to_record()["alpha"], "0.05")

    def test_a_decimal_alpha_hashes_identically_to_its_text_form(self) -> None:
        from_text = validate(testing=disclosure(alpha="0.05"))
        from_decimal = validate(testing=disclosure(alpha=Decimal("0.05")))
        self.assertEqual(from_text.content_sha256, from_decimal.content_sha256)

    def test_a_float_alpha_is_still_rejected(self) -> None:
        with self.assertRaises(QuantContractError):
            disclosure(alpha=0.05)

    def test_an_out_of_range_alpha_is_still_rejected(self) -> None:
        for value in ("0", "1", Decimal("-0.05"), 1):
            with self.subTest(alpha=repr(value)):
                with self.assertRaises(QuantContractError):
                    disclosure(alpha=value)

    def test_a_noncanonical_stored_alpha_is_refused_before_any_fitting(self) -> None:
        # Construction canonicalises; runtime must not. Each of these is a
        # value the constructor would have normalised, written back after the
        # fact, and revalidation has to reject rather than re-normalise it.
        for value in (Decimal("0.05"), "0.050", " 0.05", "5E-2", 0.05, None):
            with self.subTest(alpha=repr(value)):
                mutated = disclosure(alpha="0.05")
                object.__setattr__(mutated, "alpha", value)
                factory = FlatFactory()
                with self.assertRaises(QuantContractError):
                    validate(factory=factory, testing=mutated)
                self.assertEqual(factory.calls, 0)


class AnnualisationPeriodsTests(unittest.TestCase):
    def _validate(self, *, factory, periods):
        return validate_walk_forward(
            dataset=make_dataset(make_series(declining_prices(120))),
            liquidity=OPEN_LIQUIDITY,
            config=CONFIG,
            schedule=schedule(),
            factory=factory,
            strategy_id="fixture-strategy",
            cost_sensitivity=sensitivity(
                ("free", _fresh(FREE)), ("retail", _fresh(RETAIL))
            ),
            disclosure=disclosure(),
            annualisation_periods=periods,
        )

    def test_an_invalid_period_count_is_refused_before_any_fitting(self) -> None:
        for label, value in ANNUALISATION_MUTATIONS:
            with self.subTest(periods=label):
                factory = FlatFactory()
                with self.assertRaises(QuantContractError):
                    self._validate(factory=factory, periods=value)
                self.assertEqual(factory.calls, 0)

    def test_a_positive_period_count_still_runs(self) -> None:
        factory = FlatFactory()
        report = self._validate(factory=factory, periods=252)
        self.assertGreater(factory.calls, 0)
        self.assertTrue(report.windows)


class WindowBuilderGuardTests(unittest.TestCase):
    def test_a_zero_step_is_refused_instead_of_looping_forever(self) -> None:
        # A zero step never advances the offset, so every iteration computes
        # the same window and the loop appends until memory runs out. The
        # failure mode is a hang, not a wrong answer, which is why the public
        # helper cannot leave this to its caller.
        mutated = schedule()
        object.__setattr__(mutated, "step_sessions", 0)
        with self.assertRaises(QuantContractError):
            build_walk_forward_windows(session_count=120, config=mutated)

    def test_another_mutated_schedule_field_is_refused(self) -> None:
        for field, value in (
            ("train_sessions", 0),
            ("embargo_sessions", -1),
            ("window_mode", "expanding"),
            ("test_sessions", True),
        ):
            with self.subTest(field=field):
                mutated = schedule()
                object.__setattr__(mutated, field, value)
                with self.assertRaises(QuantContractError):
                    build_walk_forward_windows(session_count=120, config=mutated)

    def test_a_non_contract_config_is_refused(self) -> None:
        with self.assertRaises(QuantContractError):
            build_walk_forward_windows(
                session_count=120,
                config=object(),  # type: ignore[arg-type]
            )

    def test_valid_schedules_still_produce_their_windows(self) -> None:
        for mode in ("rolling", "anchored"):
            with self.subTest(window_mode=mode):
                config = schedule(window_mode=mode, min_windows=1)
                windows = build_walk_forward_windows(
                    session_count=120, config=config
                )
                self.assertTrue(windows)
                self.assertEqual(
                    [window.window_index for window in windows],
                    list(range(len(windows))),
                )
                for earlier, later in zip(windows, windows[1:]):
                    self.assertLess(
                        earlier.test_start_index, later.test_start_index
                    )
                for window in windows:
                    self.assertLess(
                        window.train_end_index, window.test_start_index
                    )
                    self.assertLessEqual(window.test_end_index, 119)


class LiquidityTests(unittest.TestCase):
    def test_the_liquidity_limit_is_pinned_in_the_record(self) -> None:
        report = validate()
        record = report.to_record()
        self.assertEqual(record["liquidity"], OPEN_LIQUIDITY.to_record())
        self.assertEqual(record["liquidity_sha256"], OPEN_LIQUIDITY.content_sha256)

    def test_an_unfillable_benchmark_is_insufficient_not_a_win(self) -> None:
        report = validate(liquidity=CLOSED_LIQUIDITY)
        self.assertEqual(report.outcome, "insufficient_data")
        self.assertIn("benchmark_unfillable", report.reason_codes)

    def test_a_partially_filled_benchmark_does_not_count_as_reachable(self) -> None:
        # The benchmark buys some shares under a 1 bp cap but never reaches
        # full exposure, so it sits mostly in cash. A flat strategy would
        # "beat" that capacity artefact rather than the security.
        report = validate(liquidity=TIGHT_LIQUIDITY)
        self.assertNotEqual(report.outcome, "validated")
        self.assertEqual(report.outcome, "insufficient_data")
        self.assertIn("benchmark_unfillable", report.reason_codes)
        traded = [
            result
            for result in report.window_results
            if result.benchmark_entry_shortfall > 0
        ]
        self.assertTrue(traded, "the benchmark must have traded and still fallen short")
        self.assertTrue(all(not result.benchmark_reachable for result in traded))

    def test_a_fully_filled_benchmark_is_reachable_despite_cash_trimming(self) -> None:
        # Whole-share rounding and commission leave an unfilled remainder under
        # retail costs. That is a capital constraint, not a capacity one, and
        # must not be mistaken for an unreachable benchmark.
        report = validate()
        self.assertTrue(
            all(result.benchmark_reachable for result in report.window_results)
        )
        self.assertTrue(
            all(
                result.benchmark_entry_shortfall == 0
                for result in report.window_results
            )
        )

    def test_changing_the_limit_changes_the_hash(self) -> None:
        tight = ParticipationLimit(
            max_participation_bps=Decimal("1"),
            volume_basis="execution_bar",
            zero_volume_policy="block",
            unfilled_policy="cancel",
            min_fill_shares=0,
        )
        self.assertNotEqual(
            validate().content_sha256,
            validate(liquidity=tight).content_sha256,
        )


class SampleAdequacyTests(unittest.TestCase):
    def test_too_few_windows_produces_no_statistics(self) -> None:
        report = validate(
            series=make_series(declining_prices(40)),
            walk_forward=schedule(min_windows=11),
        )
        self.assertEqual(report.outcome, "insufficient_data")
        self.assertIn("too_few_windows", report.reason_codes)
        self.assertEqual(report.scenario_summaries, ())

    def test_a_series_shorter_than_one_window_is_insufficient(self) -> None:
        report = validate(
            series=make_series(declining_prices(10)),
            walk_forward=schedule(min_windows=1),
        )
        self.assertEqual(report.outcome, "insufficient_data")
        self.assertIn("series_too_short", report.reason_codes)

    def test_too_few_trades_is_reported(self) -> None:
        report = validate(walk_forward=schedule(min_trades_per_window=5))
        self.assertEqual(report.outcome, "insufficient_data")
        self.assertIn("too_few_trades_in_window", report.reason_codes)

    def test_multiple_unmet_minimums_are_all_reported(self) -> None:
        report = validate(
            walk_forward=schedule(min_trades_per_window=5, min_total_trades=50),
        )
        self.assertIn("too_few_trades_in_window", report.reason_codes)
        self.assertIn("too_few_total_trades", report.reason_codes)

    def test_degrees_of_freedom_below_the_table_is_insufficient(self) -> None:
        # 60 sessions yields 7 windows -> 6 degrees of freedom, below the
        # smallest tabulated bucket.
        report = validate(
            series=make_series(declining_prices(60)),
            walk_forward=schedule(min_windows=3),
        )
        self.assertEqual(report.outcome, "insufficient_data")
        self.assertIn("degrees_of_freedom_below_table", report.reason_codes)


class DisclosureTests(unittest.TestCase):
    def test_declared_trials_below_observed_is_rejected(self) -> None:
        with self.assertRaises(QuantContractError):
            validate(testing=disclosure(trials_declared=1))

    def test_no_adjustment_with_many_trials_is_rejected(self) -> None:
        with self.assertRaises(QuantContractError):
            validate(testing=disclosure(adjustment="none", trials_declared=2))

    def test_bonferroni_actually_binds(self) -> None:
        lenient = validate(testing=disclosure(trials_declared=2))
        strict = validate(testing=disclosure(trials_declared=100))
        self.assertEqual(lenient.outcome, "validated")
        self.assertEqual(strict.outcome, "insufficient_data")
        self.assertIn("adjusted_alpha_below_table", strict.reason_codes)

    def test_overlapping_test_windows_are_disclosed(self) -> None:
        report = validate(walk_forward=schedule(step_sessions=2))
        self.assertTrue(report.test_windows_overlap)
        self.assertTrue(validate().test_windows_overlap is False)


class OutcomeTests(unittest.TestCase):
    def test_a_consistent_edge_over_a_falling_benchmark_validates(self) -> None:
        report = validate()
        self.assertEqual(report.outcome, "validated")
        self.assertEqual(report.reason_codes, ())
        self.assertEqual(report.windows_beating_benchmark, report.window_count)

    def test_a_strategy_indistinguishable_from_the_benchmark_is_unmeasurable(
        self,
    ) -> None:
        # Excess is exactly zero in every window, so there is no dispersion to
        # test. That is insufficient evidence, not a rejection on the merits.
        report = validate(factory=LongFactory())
        self.assertEqual(report.outcome, "insufficient_data")
        self.assertIn("zero_variance", report.reason_codes)

    def test_losing_to_the_benchmark_is_rejected(self) -> None:
        report = validate(series=make_series(rising_prices(120)))
        self.assertEqual(report.outcome, "rejected")
        self.assertIn("no_excess_return", report.reason_codes)

    def test_the_benchmark_carries_the_same_costs(self) -> None:
        report = validate(
            factory=LongFactory(),
        )
        for result in report.window_results:
            self.assertEqual(result.excess_return, Decimal(0))


class ScenarioTests(unittest.TestCase):
    def test_one_fit_is_reused_across_cost_scenarios(self) -> None:
        factory = FlatFactory()
        report = validate(
            factory=factory,
            costs=sensitivity(("free", FREE), ("retail", RETAIL)),
        )
        self.assertEqual(factory.calls, len(report.windows))
        for window in report.windows:
            hashes = {
                result.strategy_config_sha256
                for result in report.window_results
                if result.window_index == window.window_index
            }
            self.assertEqual(len(hashes), 1)

    def test_baseline_must_name_a_declared_scenario(self) -> None:
        with self.assertRaises(QuantContractError):
            CostSensitivityConfig(
                scenarios=(
                    CostScenario(label="free", costs=FREE),
                    CostScenario(label="retail", costs=RETAIL),
                ),
                baseline_label="absent",
            )

    def test_duplicate_scenario_labels_are_rejected(self) -> None:
        with self.assertRaises(QuantContractError):
            CostSensitivityConfig(
                scenarios=(
                    CostScenario(label="free", costs=FREE),
                    CostScenario(label="free", costs=RETAIL),
                ),
                baseline_label="free",
            )

    def test_a_single_scenario_is_rejected(self) -> None:
        with self.assertRaises(QuantContractError):
            CostSensitivityConfig(
                scenarios=(CostScenario(label="free", costs=FREE),),
                baseline_label="free",
            )


class RecordTests(unittest.TestCase):
    def test_identical_runs_hash_identically(self) -> None:
        first = validate()
        second = validate()
        self.assertEqual(first.to_record(), second.to_record())
        self.assertEqual(first.content_sha256, second.content_sha256)
        self.assertEqual(len(first.content_sha256), 64)

    def test_changing_the_embargo_changes_the_hash(self) -> None:
        self.assertNotEqual(
            validate().content_sha256,
            validate(walk_forward=schedule(embargo_sessions=4)).content_sha256,
        )

    def test_changing_declared_trials_changes_the_hash(self) -> None:
        self.assertNotEqual(
            validate().content_sha256,
            validate(testing=disclosure(trials_declared=3)).content_sha256,
        )

    def test_a_nondeterministic_factory_is_visible_in_the_hash(self) -> None:
        # One factory whose fit changes between runs. The drift surfaces as a
        # different report hash instead of being averaged away.
        drifting = DriftingFactory()
        self.assertNotEqual(
            validate(factory=drifting).content_sha256,
            validate(factory=drifting).content_sha256,
        )

    def test_the_record_pins_its_inputs_and_versions(self) -> None:
        series = make_series(declining_prices(120))
        report = validate(series=series)
        record = report.to_record()
        self.assertEqual(record["series_sha256"], series.content_sha256)
        self.assertEqual(record["security_id"], SECURITY_ID)
        self.assertEqual(record["validation_version"], VALIDATION_VERSION)
        self.assertEqual(record["engine_version"], "quant-backtest-4")
        self.assertIn("benchmark_config_sha256", record)

    def test_the_record_contains_no_floats(self) -> None:
        def walk(value: object) -> None:
            self.assertNotIsInstance(value, float)
            if isinstance(value, dict):
                for item in value.values():
                    walk(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    walk(item)

        walk(validate().to_record())


class IsolationTests(unittest.TestCase):
    def test_validation_modules_import_no_other_bounded_context(self) -> None:
        import pathlib

        package = (
            pathlib.Path(__file__).resolve().parents[1]
            / "src"
            / "investment_research_os"
            / "quant"
        )
        names = {path.name for path in package.glob("*.py")}
        self.assertIn("validation.py", names)
        self.assertIn("statistics.py", names)

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
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not (stripped.startswith("import ") or stripped.startswith("from ")):
                    continue
                for term in forbidden:
                    self.assertNotIn(term, stripped, f"{path.name} imports {term}")


if __name__ == "__main__":
    unittest.main()

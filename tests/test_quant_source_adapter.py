from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta
from decimal import Context, Decimal, localcontext

from investment_research_os.quant import PointInTimeDataset, QuantContractError
from investment_research_os.quant_sources import (
    ADAPTER_VERSION,
    SourceSnapshot,
    acquire_point_in_time_dataset,
    payload_sha256,
    revalidate_source_snapshot,
)

SECURITY_ID = "3f1b0c2e-9d4a-4c7f-b1e2-8a5d6c7f0912"
OTHER_SECURITY_ID = "9c2f4e18-5b7a-4d31-8e60-1a2b3c4d5e6f"
START = date(2026, 1, 5)
CUTOFF = date(2026, 1, 8)


def bar_rows(count: int = 4, **overrides: object) -> tuple[dict[str, object], ...]:
    rows = []
    for index in range(count):
        price = str(100 + index)
        row: dict[str, object] = {
            "session": (START + timedelta(days=index)).isoformat(),
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": 1_000,
        }
        rows.append(row)
    if overrides:
        rows[-1].update(overrides)
    return tuple(rows)


def split_rows(*sessions: date) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "effective_session": session.isoformat(),
            "new_shares": 2,
            "old_shares": 1,
        }
        for session in sessions
    )


def snapshot(**overrides: object) -> SourceSnapshot:
    base: dict[str, object] = {
        "source_id": "fixture-vendor",
        "source_revision": "2026-01-08T00:00:00Z/rev-1",
        "bar_rows": bar_rows(),
        "split_rows": (),
    }
    base.update(overrides)
    if "content_sha256" not in base:
        base["content_sha256"] = payload_sha256(
            bar_rows=base["bar_rows"],  # type: ignore[arg-type]
            split_rows=base["split_rows"],  # type: ignore[arg-type]
        )
    return SourceSnapshot(**base)  # type: ignore[arg-type]


def acquire(**overrides: object) -> PointInTimeDataset:
    base: dict[str, object] = {
        "security_id": SECURITY_ID,
        "as_of_cutoff": CUTOFF,
        "currency": "USD",
        "snapshot": snapshot(),
    }
    base.update(overrides)
    return acquire_point_in_time_dataset(**base)  # type: ignore[arg-type]


class ReceiptContractTests(unittest.TestCase):
    def test_a_valid_snapshot_produces_a_dataset_receipt(self) -> None:
        dataset = acquire()
        self.assertIsInstance(dataset, PointInTimeDataset)
        self.assertEqual(dataset.security_id, SECURITY_ID)
        self.assertEqual(dataset.as_of_cutoff, CUTOFF)
        self.assertEqual(dataset.series.interval, "1d")
        self.assertEqual(dataset.series.price_basis, "unadjusted")
        self.assertEqual(len(dataset.series.bars), 4)
        self.assertEqual(dataset.coverage_scope, "single_security")

    def test_the_receipt_carries_the_declared_source_identity(self) -> None:
        dataset = acquire()
        self.assertEqual(dataset.source_id, "fixture-vendor")
        self.assertEqual(dataset.source_revision, "2026-01-08T00:00:00Z/rev-1")
        self.assertEqual(
            dataset.source_content_sha256,
            payload_sha256(bar_rows=bar_rows(), split_rows=()),
        )

    def test_rows_are_normalised_to_decimals_not_floats(self) -> None:
        dataset = acquire()
        for bar in dataset.series.bars:
            for field in ("open", "high", "low", "close"):
                self.assertIsInstance(getattr(bar, field), Decimal)
            self.assertIsInstance(bar.volume, int)

    def test_splits_become_a_validated_corporate_action_set(self) -> None:
        rows = split_rows(START + timedelta(days=1), START + timedelta(days=2))
        dataset = acquire(snapshot=snapshot(split_rows=rows))
        self.assertEqual(dataset.corporate_actions.security_id, SECURITY_ID)
        self.assertEqual(len(dataset.corporate_actions.actions), 2)
        self.assertEqual(
            dataset.corporate_actions.actions[0].effective_session,
            START + timedelta(days=1),
        )

    def test_the_adapter_version_is_declared(self) -> None:
        self.assertEqual(ADAPTER_VERSION, "quant-source-adapter-1")


class CutoffEnforcementTests(unittest.TestCase):
    def test_a_bar_after_the_cutoff_is_refused(self) -> None:
        # The receipt contract would also refuse this, but only as "the cutoff
        # precedes the last session". The adapter names the offending source
        # row, which is the difference between a rejected payload and a
        # debuggable one, so the message is asserted, not just the type.
        with self.assertRaisesRegex(
            QuantContractError, r"bar row 3 session 2026-01-08 is after the cutoff"
        ):
            acquire(as_of_cutoff=START + timedelta(days=2))

    def test_a_post_cutoff_bar_is_never_silently_truncated(self) -> None:
        # Dropping the offending row would produce a valid-looking receipt for
        # a window the caller did not ask for. Refusing is the only honest
        # outcome, because the adapter cannot know which one was intended.
        with self.assertRaises(QuantContractError):
            acquire(as_of_cutoff=START)

    def test_a_split_after_the_cutoff_is_refused(self) -> None:
        rows = split_rows(START + timedelta(days=30))
        with self.assertRaisesRegex(
            QuantContractError, r"split row 0 effective_session 2026-02-04 is after the cutoff"
        ):
            acquire(snapshot=snapshot(split_rows=rows))

    def test_a_cutoff_on_the_last_session_is_accepted(self) -> None:
        dataset = acquire(as_of_cutoff=START + timedelta(days=3))
        self.assertEqual(dataset.as_of_cutoff, START + timedelta(days=3))

    def test_a_datetime_cutoff_is_refused(self) -> None:
        with self.assertRaises(QuantContractError):
            acquire(as_of_cutoff=datetime(2026, 1, 8, 21, 0))

    def test_a_missing_cutoff_is_never_inferred_from_the_rows(self) -> None:
        with self.assertRaises(TypeError):
            acquire_point_in_time_dataset(  # type: ignore[call-arg]
                security_id=SECURITY_ID,
                snapshot=snapshot(),
            )


class SourceDeclarationTests(unittest.TestCase):
    def test_a_blank_source_id_or_revision_is_refused(self) -> None:
        for field in ("source_id", "source_revision"):
            with self.subTest(field=field):
                with self.assertRaises(QuantContractError):
                    snapshot(**{field: "   "})

    def test_an_implicit_latest_revision_is_refused(self) -> None:
        # "latest" is not a revision, it is a promise to return something
        # different tomorrow. A receipt naming it could never be reproduced.
        for value in ("latest", "LATEST", "current", "head", "newest", "now"):
            with self.subTest(revision=value):
                with self.assertRaisesRegex(QuantContractError, "revision"):
                    snapshot(source_revision=value)

    def test_a_malformed_content_hash_is_refused(self) -> None:
        for value in ("", "abc", "B" * 64, "b" * 63, "g" * 64, None, 7):
            with self.subTest(value=repr(value)):
                with self.assertRaises(QuantContractError):
                    snapshot(content_sha256=value)


class PayloadIntegrityTests(unittest.TestCase):
    def test_an_altered_payload_no_longer_matches_its_declared_hash(self) -> None:
        # The snapshot declares a hash; the adapter recomputes it. This is the
        # one provenance claim in the whole chain that is actually checkable.
        tampered = snapshot(
            bar_rows=bar_rows(), content_sha256=payload_sha256(
                bar_rows=bar_rows(close="999"), split_rows=()
            )
        )
        with self.assertRaisesRegex(QuantContractError, "content hash"):
            acquire(snapshot=tampered)

    def test_a_replayed_hash_from_another_payload_is_refused(self) -> None:
        original = payload_sha256(bar_rows=bar_rows(), split_rows=())
        replayed = snapshot(
            bar_rows=bar_rows(count=3), content_sha256=original
        )
        with self.assertRaises(QuantContractError):
            acquire(snapshot=replayed)

    def test_adding_a_split_changes_the_payload_hash(self) -> None:
        without = payload_sha256(bar_rows=bar_rows(), split_rows=())
        with_split = payload_sha256(
            bar_rows=bar_rows(), split_rows=split_rows(START + timedelta(days=1))
        )
        self.assertNotEqual(without, with_split)

    def test_the_payload_hash_ignores_row_key_order(self) -> None:
        reordered = tuple(
            {key: row[key] for key in reversed(list(row))} for row in bar_rows()
        )
        self.assertEqual(
            payload_sha256(bar_rows=bar_rows(), split_rows=()),
            payload_sha256(bar_rows=reordered, split_rows=()),
        )

    def test_the_payload_hash_is_sensitive_to_numeric_text(self) -> None:
        # "100" and "100.0" are the same number and a different declaration.
        # The payload hash covers what the source sent, not what it meant.
        self.assertNotEqual(
            payload_sha256(bar_rows=bar_rows(), split_rows=()),
            payload_sha256(bar_rows=bar_rows(close="103.0"), split_rows=()),
        )


class RowValidationTests(unittest.TestCase):
    def test_a_float_price_is_refused(self) -> None:
        for field in ("open", "high", "low", "close"):
            with self.subTest(field=field):
                rows = bar_rows(**{field: 103.0})
                with self.assertRaisesRegex(QuantContractError, "float"):
                    acquire(snapshot=snapshot(bar_rows=rows))

    def test_a_float_volume_is_refused(self) -> None:
        rows = bar_rows(volume=1000.0)
        with self.assertRaises(QuantContractError):
            acquire(snapshot=snapshot(bar_rows=rows))

    def test_a_missing_field_is_refused(self) -> None:
        rows = list(bar_rows())
        del rows[1]["close"]
        with self.assertRaisesRegex(QuantContractError, "close"):
            acquire(snapshot=snapshot(bar_rows=tuple(rows)))

    def test_an_unknown_field_is_refused(self) -> None:
        rows = bar_rows(adjusted_close="103")
        with self.assertRaises(QuantContractError):
            acquire(snapshot=snapshot(bar_rows=rows))

    def test_a_duplicate_session_is_refused(self) -> None:
        rows = bar_rows(session=(START + timedelta(days=2)).isoformat())
        with self.assertRaises(QuantContractError):
            acquire(snapshot=snapshot(bar_rows=rows))

    def test_a_non_monotonic_session_is_refused_not_sorted(self) -> None:
        # Sorting would hide that the source returned rows out of order, which
        # is exactly the kind of defect worth knowing about before it becomes
        # a backtest.
        rows = bar_rows(session=START.isoformat())
        with self.assertRaises(QuantContractError):
            acquire(snapshot=snapshot(bar_rows=rows))

    def test_a_malformed_session_is_refused(self) -> None:
        for value in ("2026-13-40", "not-a-date", 20260105, None):
            with self.subTest(session=repr(value)):
                rows = bar_rows(session=value)
                with self.assertRaises(QuantContractError):
                    acquire(snapshot=snapshot(bar_rows=rows))

    def test_too_few_rows_are_refused(self) -> None:
        with self.assertRaises(QuantContractError):
            acquire(snapshot=snapshot(bar_rows=bar_rows(count=1)))

    def test_an_ohlc_violation_is_refused(self) -> None:
        rows = bar_rows(high="1")
        with self.assertRaises(QuantContractError):
            acquire(snapshot=snapshot(bar_rows=rows))


class IdentityTests(unittest.TestCase):
    def test_a_non_canonical_security_id_is_refused(self) -> None:
        for value in (SECURITY_ID.upper(), "not-a-uuid", None, 7):
            with self.subTest(security_id=repr(value)):
                with self.assertRaises(QuantContractError):
                    acquire(security_id=value)

    def test_a_row_declaring_another_security_is_refused(self) -> None:
        rows = bar_rows(security_id=OTHER_SECURITY_ID)
        with self.assertRaises(QuantContractError):
            acquire(snapshot=snapshot(bar_rows=rows))

    def test_a_split_declaring_another_security_is_refused(self) -> None:
        rows = [dict(row) for row in split_rows(START + timedelta(days=1))]
        rows[0]["security_id"] = OTHER_SECURITY_ID
        with self.assertRaisesRegex(QuantContractError, "security"):
            acquire(snapshot=snapshot(split_rows=tuple(rows)))

    def test_a_matching_declared_security_is_accepted(self) -> None:
        rows = tuple(dict(row, security_id=SECURITY_ID) for row in bar_rows())
        dataset = acquire(snapshot=snapshot(bar_rows=rows))
        self.assertEqual(dataset.security_id, SECURITY_ID)


class CorporateActionValidationTests(unittest.TestCase):
    def test_a_duplicate_split_session_is_refused(self) -> None:
        session = START + timedelta(days=1)
        with self.assertRaises(QuantContractError):
            acquire(snapshot=snapshot(split_rows=split_rows(session, session)))

    def test_an_unordered_split_set_is_refused(self) -> None:
        rows = split_rows(START + timedelta(days=2), START + timedelta(days=1))
        with self.assertRaises(QuantContractError):
            acquire(snapshot=snapshot(split_rows=rows))

    def test_a_float_split_ratio_is_refused(self) -> None:
        rows = [dict(row) for row in split_rows(START + timedelta(days=1))]
        rows[0]["new_shares"] = 2.0
        with self.assertRaises(QuantContractError):
            acquire(snapshot=snapshot(split_rows=tuple(rows)))

    def test_a_split_ratio_that_changes_nothing_is_refused(self) -> None:
        rows = [dict(row) for row in split_rows(START + timedelta(days=1))]
        rows[0]["new_shares"] = 1
        with self.assertRaises(QuantContractError):
            acquire(snapshot=snapshot(split_rows=tuple(rows)))


class DeterminismTests(unittest.TestCase):
    def test_the_same_snapshot_yields_the_same_receipt_hash(self) -> None:
        self.assertEqual(acquire().content_sha256, acquire().content_sha256)

    def test_acquisition_is_idempotent_across_decimal_contexts(self) -> None:
        baseline = acquire().content_sha256
        for precision in (5, 60):
            with localcontext(Context(prec=precision)):
                self.assertEqual(acquire().content_sha256, baseline)

    def test_a_different_revision_changes_the_receipt_hash(self) -> None:
        other = snapshot(source_revision="2026-01-08T00:00:00Z/rev-2")
        self.assertNotEqual(
            acquire().content_sha256,
            acquire(snapshot=other).content_sha256,
        )

    def test_a_different_cutoff_changes_the_receipt_hash(self) -> None:
        self.assertNotEqual(
            acquire().content_sha256,
            acquire(as_of_cutoff=CUTOFF + timedelta(days=5)).content_sha256,
        )

    def test_the_snapshot_is_frozen(self) -> None:
        subject = snapshot()
        with self.assertRaises(Exception):
            subject.source_revision = "rev-2"  # type: ignore[misc]


class TamperAfterAcquisitionTests(unittest.TestCase):
    def test_a_snapshot_mutated_after_construction_is_refused(self) -> None:
        # Frozen is not sealed, and the payload hash is recomputed at
        # acquisition, so a row written back after the snapshot was built no
        # longer matches its own declaration.
        subject = snapshot()
        object.__setattr__(subject, "bar_rows", bar_rows(close="999"))
        with self.assertRaisesRegex(QuantContractError, "content hash"):
            acquire(snapshot=subject)

    def test_a_revision_swapped_after_construction_is_still_carried(self) -> None:
        # The revision is not covered by the payload hash, by design: it names
        # where the payload came from, not what it contains. Swapping it
        # therefore produces a different receipt rather than an error, and the
        # receipt hash records the difference.
        subject = snapshot()
        first = acquire(snapshot=subject).content_sha256
        object.__setattr__(subject, "source_revision", "2026-01-08T00:00:00Z/rev-9")
        self.assertNotEqual(acquire(snapshot=subject).content_sha256, first)


class QuantCoreRoundTripTests(unittest.TestCase):
    def test_an_acquired_receipt_is_accepted_by_the_backtest_boundary(self) -> None:
        from decimal import Decimal as _Decimal

        from investment_research_os.quant import (
            BacktestConfig,
            CostModel,
            ParticipationLimit,
            run_backtest,
        )

        class AlwaysLong:
            def target_exposure(self, window: object) -> _Decimal:
                return _Decimal(1)

        dataset = acquire()
        result = run_backtest(
            dataset=dataset,
            strategy=AlwaysLong(),
            costs=CostModel(
                commission_per_share=_Decimal("0"),
                commission_bps=_Decimal("0"),
                commission_minimum=_Decimal("0"),
                transaction_cost_bps=_Decimal("0"),
                slippage_bps=_Decimal("0"),
            ),
            liquidity=ParticipationLimit(
                max_participation_bps=_Decimal("10000"),
                volume_basis="execution_bar",
                zero_volume_policy="block",
                unfilled_policy="cancel",
                min_fill_shares=0,
            ),
            config=BacktestConfig(
                starting_cash=_Decimal("10000"),
                fractional_share_policy="error",
            ),
            strategy_id="round-trip",
            strategy_config_sha256="a" * 64,
        )
        self.assertEqual(result.dataset_sha256, dataset.content_sha256)
        self.assertTrue(result.trades)


class CoveredTransitionTests(unittest.TestCase):
    def test_a_split_on_the_first_session_is_refused(self) -> None:
        # The engine transitions into bars[1:] only. A split dated on the first
        # bar is a session the engine never enters, so it would abort the whole
        # backtest later for a reason that has nothing to do with the strategy.
        with self.assertRaisesRegex(QuantContractError, "transition session"):
            acquire(snapshot=snapshot(split_rows=split_rows(START)))

    def test_a_split_on_an_uncovered_session_is_refused(self) -> None:
        # 2026-01-10 is a Saturday: inside the cutoff, outside the bars.
        uncovered = date(2026, 1, 10)
        with self.assertRaisesRegex(QuantContractError, "transition session"):
            acquire(
                as_of_cutoff=uncovered,
                snapshot=snapshot(split_rows=split_rows(uncovered)),
            )

    def test_a_split_on_a_covered_transition_session_is_accepted(self) -> None:
        for offset in (1, 2, 3):
            with self.subTest(offset=offset):
                rows = split_rows(START + timedelta(days=offset))
                dataset = acquire(snapshot=snapshot(split_rows=rows))
                self.assertEqual(len(dataset.corporate_actions.actions), 1)

    def test_the_covered_rule_matches_the_engine(self) -> None:
        # Belt and braces: a receipt this adapter accepts must not be one the
        # engine then refuses for a covered-session reason.
        from decimal import Decimal as _Decimal

        from investment_research_os.quant import (
            BacktestConfig,
            CostModel,
            ParticipationLimit,
            run_backtest,
        )

        class AlwaysLong:
            def target_exposure(self, window: object) -> _Decimal:
                return _Decimal(1)

        dataset = acquire(
            snapshot=snapshot(split_rows=split_rows(START + timedelta(days=1)))
        )
        result = run_backtest(
            dataset=dataset,
            strategy=AlwaysLong(),
            costs=CostModel(
                commission_per_share=_Decimal("0"),
                commission_bps=_Decimal("0"),
                commission_minimum=_Decimal("0"),
                transaction_cost_bps=_Decimal("0"),
                slippage_bps=_Decimal("0"),
            ),
            liquidity=ParticipationLimit(
                max_participation_bps=_Decimal("10000"),
                volume_basis="execution_bar",
                zero_volume_policy="block",
                unfilled_policy="cancel",
                min_fill_shares=0,
            ),
            config=BacktestConfig(
                starting_cash=_Decimal("10000"),
                fractional_share_policy="error",
            ),
            strategy_id="covered-transition",
            strategy_config_sha256="a" * 64,
        )
        self.assertEqual(len(result.corporate_action_applications), 1)


class SnapshotRevalidationTests(unittest.TestCase):
    def test_a_valid_snapshot_revalidates_and_is_returned(self) -> None:
        subject = snapshot()
        self.assertIs(revalidate_source_snapshot(subject), subject)

    def test_a_non_snapshot_is_refused(self) -> None:
        for value in (object(), None, {"source_id": "x"}):
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(QuantContractError):
                    revalidate_source_snapshot(value)

    def test_every_mutated_declaration_is_refused(self) -> None:
        mutations: tuple[tuple[str, str, object], ...] = (
            ("blank_source_id", "source_id", "   "),
            ("non_string_source_id", "source_id", 7),
            ("blank_revision", "source_revision", ""),
            ("moving_revision", "source_revision", "latest"),
            ("moving_revision_cased", "source_revision", "Current"),
            ("short_hash", "content_sha256", "abc"),
            ("upper_hash", "content_sha256", "B" * 64),
            ("non_string_hash", "content_sha256", None),
            ("rows_to_list", "bar_rows", [dict(row) for row in bar_rows()]),
            ("rows_not_a_sequence", "bar_rows", object()),
            ("rows_hold_objects", "bar_rows", (object(), object())),
            ("splits_not_a_sequence", "split_rows", object()),
        )
        for label, field, value in mutations:
            with self.subTest(mutation=label):
                subject = snapshot()
                object.__setattr__(subject, field, value)
                with self.assertRaises(QuantContractError):
                    revalidate_source_snapshot(subject)

    def test_a_mutated_row_is_caught_by_the_recomputed_hash(self) -> None:
        subject = snapshot()
        object.__setattr__(subject, "bar_rows", bar_rows(close="999"))
        with self.assertRaisesRegex(QuantContractError, "content hash"):
            revalidate_source_snapshot(subject)

    def test_post_cutoff_rows_are_refused_when_a_cutoff_is_supplied(self) -> None:
        subject = snapshot()
        self.assertIs(revalidate_source_snapshot(subject, as_of_cutoff=CUTOFF), subject)
        with self.assertRaisesRegex(QuantContractError, "cutoff"):
            revalidate_source_snapshot(subject, as_of_cutoff=START)
        with_split = snapshot(split_rows=split_rows(START + timedelta(days=2)))
        with self.assertRaisesRegex(QuantContractError, "cutoff"):
            revalidate_source_snapshot(with_split, as_of_cutoff=START)

    def test_acquisition_refuses_a_snapshot_mutated_after_construction(self) -> None:
        # The gap named as a known limitation in the previous response. A
        # moving revision written back after construction must no longer reach
        # the receipt.
        subject = snapshot()
        object.__setattr__(subject, "source_revision", "latest")
        with self.assertRaisesRegex(QuantContractError, "revision"):
            acquire(snapshot=subject)


class RowImmutabilityTests(unittest.TestCase):
    def test_mutating_the_callers_dict_cannot_change_a_stored_row(self) -> None:
        rows = [dict(row) for row in bar_rows()]
        subject = SourceSnapshot(
            source_id="fixture-vendor",
            source_revision="2026-01-08T00:00:00Z/rev-1",
            content_sha256=payload_sha256(bar_rows=rows, split_rows=()),
            bar_rows=rows,
            split_rows=(),
        )
        rows[0]["close"] = "999"
        rows.append({"session": "2026-02-01"})
        self.assertEqual(subject.bar_rows[0]["close"], "100")
        self.assertEqual(len(subject.bar_rows), 4)
        self.assertIsNotNone(revalidate_source_snapshot(subject))

    def test_a_stored_row_cannot_be_written_to(self) -> None:
        subject = snapshot()
        with self.assertRaises(TypeError):
            subject.bar_rows[0]["close"] = "999"  # type: ignore[index]

    def test_a_stored_row_holding_an_unhashable_value_is_refused(self) -> None:
        rows = [dict(row) for row in bar_rows()]
        rows[0]["close"] = ["100"]
        with self.assertRaises(QuantContractError):
            SourceSnapshot(
                source_id="fixture-vendor",
                source_revision="2026-01-08T00:00:00Z/rev-1",
                content_sha256="b" * 64,
                bar_rows=rows,
                split_rows=(),
            )


class CurrencyTests(unittest.TestCase):
    def test_currency_must_be_stated_explicitly(self) -> None:
        with self.assertRaises(TypeError):
            acquire_point_in_time_dataset(  # type: ignore[call-arg]
                security_id=SECURITY_ID,
                as_of_cutoff=CUTOFF,
                snapshot=snapshot(),
            )

    def test_a_declared_currency_reaches_the_series(self) -> None:
        self.assertEqual(acquire(currency="HKD").series.currency, "HKD")

    def test_a_malformed_currency_is_refused(self) -> None:
        # BarSeries also rejects a lower-case code, so the message is asserted
        # rather than the type: this has to fail at the adapter, where the
        # error can say the code was never stated properly, not deep inside a
        # contract the caller did not call.
        for value in ("usd", "US", "USDX", "US1", "", "   ", None, 7):
            with self.subTest(currency=repr(value)):
                with self.assertRaisesRegex(
                    QuantContractError, "there is no default"
                ):
                    acquire(currency=value)


class BoundaryIsolationTests(unittest.TestCase):
    def test_quant_core_never_imports_the_adapter_or_a_provider(self) -> None:
        import pathlib

        package = (
            pathlib.Path(__file__).resolve().parents[1]
            / "src"
            / "investment_research_os"
            / "quant"
        )
        forbidden = (
            "quant_sources",
            "providers",
            "adapter",
            "moomoo",
            "yfinance",
            "portfolio",
            "research_runs",
            "workers.",
            "supabase",
            "requests",
            "httpx",
            "urllib",
            "socket",
        )
        for path in package.glob("*.py"):
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not (stripped.startswith("import ") or stripped.startswith("from ")):
                    continue
                for term in forbidden:
                    self.assertNotIn(
                        term,
                        stripped,
                        f"quant/{path.name} imports {term}; Quant core stays neutral",
                    )

    def test_the_adapter_performs_no_io_and_reads_no_clock(self) -> None:
        import pathlib

        package = (
            pathlib.Path(__file__).resolve().parents[1]
            / "src"
            / "investment_research_os"
            / "quant_sources"
        )
        for path in package.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            for term in (
                "open(",
                "Path(",
                "datetime.now",
                "date.today",
                "time.time",
                "requests",
                "httpx",
                "urllib",
                "socket",
                "psycopg",
                "sqlite3",
                "supabase",
                "moomoo",
            ):
                self.assertNotIn(term, source, f"{path.name} must not use {term}")

    def test_the_adapter_depends_on_quant_and_nothing_else_internal(self) -> None:
        import pathlib

        package = (
            pathlib.Path(__file__).resolve().parents[1]
            / "src"
            / "investment_research_os"
            / "quant_sources"
        )
        for path in package.glob("*.py"):
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped.startswith("from investment_research_os"):
                    continue
                self.assertTrue(
                    stripped.startswith("from investment_research_os.quant"),
                    f"{path.name} may only reach into quant, found: {stripped}",
                )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta
from decimal import Context, Decimal, localcontext

from investment_research_os.quant import (
    BarSeries,
    CorporateActionSet,
    OhlcvBar,
    QuantContractError,
    StockSplit,
)
from investment_research_os.quant.dataset import (
    DATASET_VERSION,
    PointInTimeDataset,
)

SECURITY_ID = "3f1b0c2e-9d4a-4c7f-b1e2-8a5d6c7f0912"
OTHER_SECURITY_ID = "9c2f4e18-5b7a-4d31-8e60-1a2b3c4d5e6f"
START = date(2026, 1, 5)
SOURCE_HASH = "b" * 64


def bars(count: int = 4) -> tuple[OhlcvBar, ...]:
    built = []
    for index in range(count):
        price = Decimal(100 + index)
        built.append(
            OhlcvBar(
                session=START + timedelta(days=index),
                open=price,
                high=price,
                low=price,
                close=price,
                volume=1_000,
            )
        )
    return tuple(built)


def series(**overrides: object) -> BarSeries:
    base: dict[str, object] = {
        "security_id": SECURITY_ID,
        "currency": "USD",
        "interval": "1d",
        "price_basis": "unadjusted",
        "source": "fixture",
        "bars": bars(),
    }
    base.update(overrides)
    return BarSeries(**base)  # type: ignore[arg-type]


def actions(*splits: StockSplit, security_id: str = SECURITY_ID) -> CorporateActionSet:
    return CorporateActionSet(
        security_id=security_id,
        source="fixture-actions",
        actions=splits,
    )


def split(offset: int) -> StockSplit:
    return StockSplit(
        effective_session=START + timedelta(days=offset),
        new_shares=2,
        old_shares=1,
    )


def dataset(**overrides: object) -> PointInTimeDataset:
    base: dict[str, object] = {
        "series": series(),
        "corporate_actions": actions(),
        "as_of_cutoff": START + timedelta(days=3),
        "source_id": "fixture-source",
        "source_revision": "rev-1",
        "source_content_sha256": SOURCE_HASH,
        "coverage_scope": "single_security",
    }
    base.update(overrides)
    return PointInTimeDataset(**base)  # type: ignore[arg-type]


class RecordTests(unittest.TestCase):
    def test_the_record_pins_every_declared_input(self) -> None:
        subject = dataset()
        record = subject.to_record()
        self.assertEqual(record["as_of_cutoff"], "2026-01-08")
        self.assertEqual(record["coverage_scope"], "single_security")
        self.assertEqual(record["dataset_version"], DATASET_VERSION)
        self.assertEqual(record["security_id"], SECURITY_ID)
        self.assertEqual(record["source_id"], "fixture-source")
        self.assertEqual(record["source_revision"], "rev-1")
        self.assertEqual(record["source_content_sha256"], SOURCE_HASH)
        self.assertEqual(record["series"], subject.series.to_record())
        self.assertEqual(record["series_sha256"], subject.series.content_sha256)
        self.assertEqual(
            record["corporate_actions"], subject.corporate_actions.to_record()
        )
        self.assertEqual(
            record["corporate_actions_sha256"],
            subject.corporate_actions.content_sha256,
        )

    def test_the_hash_is_repeatable(self) -> None:
        self.assertEqual(dataset().content_sha256, dataset().content_sha256)
        self.assertEqual(len(dataset().content_sha256), 64)


class HashSensitivityTests(unittest.TestCase):
    def test_source_revision_changes_the_hash(self) -> None:
        self.assertNotEqual(
            dataset().content_sha256,
            dataset(source_revision="rev-2").content_sha256,
        )

    def test_source_id_changes_the_hash(self) -> None:
        self.assertNotEqual(
            dataset().content_sha256,
            dataset(source_id="other-source").content_sha256,
        )

    def test_source_content_hash_changes_the_hash(self) -> None:
        self.assertNotEqual(
            dataset().content_sha256,
            dataset(source_content_sha256="c" * 64).content_sha256,
        )

    def test_cutoff_changes_the_hash(self) -> None:
        self.assertNotEqual(
            dataset().content_sha256,
            dataset(as_of_cutoff=START + timedelta(days=9)).content_sha256,
        )

    def test_a_bar_change_changes_the_hash(self) -> None:
        moved = list(bars())
        moved[-1] = OhlcvBar(
            session=moved[-1].session,
            open=Decimal("500"),
            high=Decimal("500"),
            low=Decimal("500"),
            close=Decimal("500"),
            volume=moved[-1].volume,
        )
        self.assertNotEqual(
            dataset().content_sha256,
            dataset(series=series(bars=tuple(moved))).content_sha256,
        )

    def test_a_corporate_action_change_changes_the_hash(self) -> None:
        self.assertNotEqual(
            dataset().content_sha256,
            dataset(corporate_actions=actions(split(2))).content_sha256,
        )


class IdentityTests(unittest.TestCase):
    def test_action_set_for_another_security_is_rejected(self) -> None:
        with self.assertRaises(QuantContractError) as caught:
            dataset(corporate_actions=actions(security_id=OTHER_SECURITY_ID))
        self.assertIn("security_id", str(caught.exception))

    def test_security_identity_is_never_inferred_from_the_action_set(self) -> None:
        subject = dataset()
        self.assertEqual(subject.security_id, subject.series.security_id)


class SeriesShapeTests(unittest.TestCase):
    def test_a_non_daily_series_is_rejected(self) -> None:
        # BarSeries already refuses another interval at construction, so the
        # only way to reach the dataset guard is to bypass that check. The
        # guard has to exist independently: a future widened BarInterval must
        # not silently admit intraday bars to a daily point-in-time dataset.
        smuggled = series()
        object.__setattr__(smuggled, "interval", "5m")
        with self.assertRaises(QuantContractError) as caught:
            dataset(series=smuggled)
        self.assertIn("daily", str(caught.exception))

    def test_an_adjusted_series_is_rejected(self) -> None:
        smuggled = series()
        object.__setattr__(smuggled, "price_basis", "split_adjusted")
        with self.assertRaises(QuantContractError) as caught:
            dataset(series=smuggled)
        self.assertIn("unadjusted", str(caught.exception))


class CutoffTests(unittest.TestCase):
    def test_a_cutoff_before_the_last_bar_is_rejected(self) -> None:
        with self.assertRaises(QuantContractError) as caught:
            dataset(as_of_cutoff=START + timedelta(days=2))
        self.assertIn("cutoff", str(caught.exception))

    def test_a_cutoff_on_the_last_bar_is_accepted(self) -> None:
        self.assertEqual(
            dataset(as_of_cutoff=START + timedelta(days=3)).as_of_cutoff,
            START + timedelta(days=3),
        )

    def test_a_corporate_action_after_the_cutoff_is_rejected(self) -> None:
        with self.assertRaises(QuantContractError) as caught:
            dataset(
                corporate_actions=actions(split(9)),
                as_of_cutoff=START + timedelta(days=3),
            )
        self.assertIn("cutoff", str(caught.exception))

    def test_a_corporate_action_on_the_cutoff_is_accepted(self) -> None:
        subject = dataset(
            corporate_actions=actions(split(3)),
            as_of_cutoff=START + timedelta(days=3),
        )
        self.assertEqual(len(subject.corporate_actions.actions), 1)

    def test_a_datetime_cutoff_is_rejected(self) -> None:
        with self.assertRaises(QuantContractError):
            dataset(as_of_cutoff=datetime(2026, 1, 8, 20, 0))

    def test_no_cutoff_is_inferred_from_the_bars(self) -> None:
        with self.assertRaises(TypeError):
            PointInTimeDataset(  # type: ignore[call-arg]
                series=series(),
                corporate_actions=actions(),
                source_id="fixture-source",
                source_revision="rev-1",
                source_content_sha256=SOURCE_HASH,
                coverage_scope="single_security",
            )


class SourceDeclarationTests(unittest.TestCase):
    def test_a_malformed_source_hash_is_rejected(self) -> None:
        for value in ("", "abc", "B" * 64, "g" * 64, "b" * 63, "b" * 65):
            with self.subTest(value=value):
                with self.assertRaises(QuantContractError):
                    dataset(source_content_sha256=value)

    def test_a_non_string_source_hash_is_rejected(self) -> None:
        with self.assertRaises(QuantContractError):
            dataset(source_content_sha256=None)

    def test_blank_source_fields_are_rejected(self) -> None:
        with self.assertRaises(QuantContractError):
            dataset(source_id="   ")
        with self.assertRaises(QuantContractError):
            dataset(source_revision="")

    def test_no_source_revision_is_inferred(self) -> None:
        with self.assertRaises(TypeError):
            PointInTimeDataset(  # type: ignore[call-arg]
                series=series(),
                corporate_actions=actions(),
                as_of_cutoff=START + timedelta(days=3),
                source_id="fixture-source",
                source_content_sha256=SOURCE_HASH,
                coverage_scope="single_security",
            )

    def test_an_unknown_coverage_scope_is_rejected(self) -> None:
        with self.assertRaises(QuantContractError) as caught:
            dataset(coverage_scope="universe")
        self.assertIn("single_security", str(caught.exception))


class DeterminismTests(unittest.TestCase):
    def test_the_record_contains_no_floats(self) -> None:
        def walk(value: object) -> None:
            self.assertNotIsInstance(value, float)
            if isinstance(value, dict):
                for item in value.values():
                    walk(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    walk(item)

        walk(dataset().to_record())

    def test_the_hash_ignores_the_ambient_decimal_context(self) -> None:
        subject = dataset()
        baseline = subject.content_sha256
        baseline_record = subject.to_record()
        with localcontext(Context(prec=5)):
            self.assertEqual(subject.content_sha256, baseline)
            self.assertEqual(subject.to_record(), baseline_record)
        with localcontext(Context(prec=60)):
            self.assertEqual(subject.content_sha256, baseline)
            self.assertEqual(subject.to_record(), baseline_record)

    def test_the_dataset_is_frozen(self) -> None:
        subject = dataset()
        with self.assertRaises(Exception):
            subject.as_of_cutoff = START  # type: ignore[misc]


class IsolationTests(unittest.TestCase):
    def test_quant_imports_no_other_context_and_no_io(self) -> None:
        import pathlib

        package = (
            pathlib.Path(__file__).resolve().parents[1]
            / "src"
            / "investment_research_os"
            / "quant"
        )
        names = {path.name for path in package.glob("*.py")}
        self.assertIn("dataset.py", names)

        forbidden = (
            "moomoo",
            "portfolio",
            "research_runs",
            "evidence_bundles",
            "committee",
            "readiness",
            "workers.",
            "supabase",
            "psycopg",
            "sqlite3",
            "sqlalchemy",
            "asyncpg",
            "requests",
            "httpx",
            "urllib",
            "http.client",
            "socket",
            "aiohttp",
            "curl_cffi",
            "yfinance",
            "openai",
            "anthropic",
            "providers",
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
                        f"{path.name} imports {term}; Quant stays offline and isolated",
                    )

    def test_the_dataset_module_opens_no_resources(self) -> None:
        import pathlib

        source = (
            pathlib.Path(__file__).resolve().parents[1]
            / "src"
            / "investment_research_os"
            / "quant"
            / "dataset.py"
        ).read_text(encoding="utf-8")
        for term in ("open(", "Path(", "datetime.now", "date.today", "time.time"):
            self.assertNotIn(term, source, f"dataset.py must not use {term}")


if __name__ == "__main__":
    unittest.main()

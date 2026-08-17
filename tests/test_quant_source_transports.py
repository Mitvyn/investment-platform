from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from investment_research_os.quant_sources import ADAPTER_VERSION  # noqa: F401

try:  # pandas and numpy ship with the market dependency, not with Quant
    import numpy
except ImportError:  # pragma: no cover - exercised by the skip
    numpy = None  # type: ignore[assignment]
try:
    import pandas
except ImportError:  # pragma: no cover - exercised by the skip
    pandas = None  # type: ignore[assignment]
from workers.market.client import YFinanceSettings
from workers.quant_sources.live import (
    MOOMOO_HISTORY_BLOCKER,
    TEST_WINDOW_SEMANTICS_EVIDENCE_SHA256,
    TEST_WINDOW_SEMANTICS_POLICY_ID,
    WINDOW_SEMANTICS_REGISTRY,
    YFINANCE_END_EXCLUSIVE_EVIDENCE_SHA256,
    YFINANCE_END_EXCLUSIVE_POLICY_ID,
    YFINANCE_END_EXCLUSIVE_VERIFIED_ON,
    YFINANCE_WINDOW_BLOCKER,
    LiveQuantSource,
    MoomooHistoryTransport,
    WindowSemanticsPolicy,
    YFinanceHistoryTransport,
    authorize_window_semantics,
    test_window_semantics_policy,
    yfinance_end_exclusive_policy,
)
from workers.quant_sources.transports import (
    BoundedCaller,
    HistoryBar,
    HistoryPayload,
    RateLimit,
    RetryPolicy,
    TransientTransportError,
    TransportBlockedError,
    TransportError,
)


SECURITY_ID = "3f1b0c2e-9d4a-4c7f-b1e2-8a5d6c7f0912"
CUTOFF = date(2026, 1, 7)
START = date(2026, 1, 5)

#: The only policy offline tests may use. It is registered as test-scoped, so
#: it is refused on any path that could reach a provider, and it must be paired
#: with an explicit test opt-in.
TEST_POLICY = test_window_semantics_policy()


class FakeClock:
    """Deterministic monotonic clock that only advances when told to sleep."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def payload(
    *,
    provider_id: str = "fixture",
    symbol: str = "RXRX",
    currency: str = "USD",
    revision: str = "rev-1",
    bars: tuple[HistoryBar, ...] | None = None,
) -> HistoryPayload:
    return HistoryPayload(
        provider_id=provider_id,
        symbol=symbol,
        currency=currency,
        source_revision=revision,
        bars=bars
        if bars is not None
        else (
            HistoryBar("2026-01-05", "100", "101", "99", "100", 1000),
            HistoryBar("2026-01-06", "50", "51", "49", "50", 1100, "2"),
            HistoryBar("2026-01-07", "51", "52", "50", "51", 1200),
        ),
    )


class FakeTransport:
    provider_id = "fixture"

    def __init__(self, result: HistoryPayload | Exception | None = None) -> None:
        self.result = result if result is not None else payload()
        self.calls: list[tuple[str, date, date]] = []

    def fetch_daily_history(
        self, ticker: str, *, start: date, end: date
    ) -> HistoryPayload:
        self.calls.append((ticker, start, end))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


# --------------------------------------------------------------------------
# 1. Transport contract
# --------------------------------------------------------------------------


class HistoryContractTests(unittest.TestCase):
    def test_a_float_price_is_refused_at_the_transport_boundary(self) -> None:
        # Asserting the type alone would pass even with this guard removed,
        # because the value would then fall through to the general type check
        # whose message also contains the word float.
        with self.assertRaisesRegex(TransportError, "binary floats"):
            HistoryBar("2026-01-05", 100.0, "101", "99", "100", 1000)

    def test_a_non_numeric_price_is_refused(self) -> None:
        with self.assertRaisesRegex(TransportError, "decimal"):
            HistoryBar("2026-01-05", "abc", "101", "99", "100", 1000)

    def test_a_non_iso_session_is_refused(self) -> None:
        with self.assertRaisesRegex(TransportError, "ISO date"):
            HistoryBar("05/01/2026", "100", "101", "99", "100", 1000)

    def test_a_boolean_volume_is_refused(self) -> None:
        with self.assertRaisesRegex(TransportError, "volume"):
            HistoryBar("2026-01-05", "100", "101", "99", "100", True)

    def test_a_negative_volume_is_refused(self) -> None:
        with self.assertRaisesRegex(TransportError, "volume"):
            HistoryBar("2026-01-05", "100", "101", "99", "100", -1)

    def test_currency_must_be_an_iso_code(self) -> None:
        with self.assertRaisesRegex(TransportError, "currency"):
            payload(currency="usd")

    def test_a_moving_source_revision_is_refused(self) -> None:
        with self.assertRaisesRegex(TransportError, "moving target"):
            payload(revision="latest")

    def test_a_blank_source_revision_is_refused(self) -> None:
        with self.assertRaisesRegex(TransportError, "source_revision"):
            payload(revision="  ")

    def test_bars_are_stored_as_a_tuple(self) -> None:
        self.assertIsInstance(payload().bars, tuple)


# --------------------------------------------------------------------------
# 2. Retry and rate limit
# --------------------------------------------------------------------------


class BoundedCallerTests(unittest.TestCase):
    def caller(
        self, *, attempts: int = 3, max_calls: int = 100, per_seconds: float = 60.0
    ) -> tuple[BoundedCaller, FakeClock]:
        clock = FakeClock()
        return (
            BoundedCaller(
                policy=RetryPolicy(
                    max_attempts=attempts,
                    backoff_seconds=1.0,
                    backoff_multiplier=2.0,
                    max_backoff_seconds=4.0,
                ),
                rate_limit=RateLimit(max_calls=max_calls, per_seconds=per_seconds),
                sleep=clock.sleep,
                monotonic=clock.monotonic,
            ),
            clock,
        )

    def test_a_transient_failure_is_retried_with_bounded_backoff(self) -> None:
        caller, clock = self.caller()
        seen: list[int] = []

        def flaky() -> str:
            seen.append(1)
            if len(seen) < 3:
                raise TransientTransportError("temporary")
            return "ok"

        self.assertEqual(caller.call(flaky), "ok")
        self.assertEqual(len(seen), 3)
        self.assertEqual(clock.sleeps, [1.0, 2.0])

    def test_retries_stop_at_max_attempts(self) -> None:
        caller, clock = self.caller(attempts=2)

        def always() -> str:
            raise TransientTransportError("temporary")

        with self.assertRaisesRegex(TransportError, "2 attempts"):
            caller.call(always)
        self.assertEqual(clock.sleeps, [1.0])

    def test_backoff_is_capped(self) -> None:
        caller, clock = self.caller(attempts=5)

        def always() -> str:
            raise TransientTransportError("temporary")

        with self.assertRaises(TransportError):
            caller.call(always)
        self.assertEqual(clock.sleeps, [1.0, 2.0, 4.0, 4.0])

    def test_a_permanent_failure_is_not_retried(self) -> None:
        caller, clock = self.caller()
        seen: list[int] = []

        def broken() -> str:
            seen.append(1)
            raise TransportError("permanent")

        with self.assertRaisesRegex(TransportError, "permanent"):
            caller.call(broken)
        self.assertEqual(len(seen), 1)
        self.assertEqual(clock.sleeps, [])

    def test_a_blocked_transport_is_not_retried(self) -> None:
        caller, _ = self.caller()
        seen: list[int] = []

        def blocked() -> str:
            seen.append(1)
            raise TransportBlockedError("blocked")

        with self.assertRaises(TransportBlockedError):
            caller.call(blocked)
        self.assertEqual(len(seen), 1)

    def test_the_rate_limit_delays_the_call_past_the_window(self) -> None:
        caller, clock = self.caller(max_calls=2, per_seconds=60.0)
        for _ in range(2):
            caller.call(lambda: "ok")
        self.assertEqual(clock.sleeps, [])
        caller.call(lambda: "ok")
        self.assertEqual(clock.sleeps, [60.0])

    def test_the_rate_limit_counts_failed_attempts(self) -> None:
        caller, clock = self.caller(attempts=3, max_calls=2, per_seconds=60.0)

        def always() -> str:
            raise TransientTransportError("temporary")

        with self.assertRaises(TransportError):
            caller.call(always)
        # Two retry backoffs at t=0 and t=1, then the third attempt waits out
        # the remainder of the window opened by the first attempt.
        self.assertEqual(clock.sleeps, [1.0, 2.0, 57.0])

    def test_an_invalid_policy_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            RetryPolicy(max_attempts=0)
        with self.assertRaises(ValueError):
            RetryPolicy(backoff_seconds=-1.0)
        with self.assertRaises(ValueError):
            RetryPolicy(backoff_multiplier=0.5)

    def test_an_invalid_rate_limit_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            RateLimit(max_calls=0, per_seconds=60.0)
        with self.assertRaises(ValueError):
            RateLimit(max_calls=1, per_seconds=0.0)


# --------------------------------------------------------------------------
# 3. Live acquisition
# --------------------------------------------------------------------------


class LiveQuantSourceTests(unittest.TestCase):
    def acquire(self, transport: FakeTransport, **overrides: object):
        kwargs: dict[str, object] = {
            "ticker": "RXRX",
            "security_id": SECURITY_ID,
            "as_of_cutoff": CUTOFF,
            "currency": "USD",
            "start": START,
        }
        kwargs.update(overrides)
        return LiveQuantSource(transport).acquire(**kwargs)  # type: ignore[arg-type]

    def test_a_history_payload_becomes_a_quant_receipt(self) -> None:
        transport = FakeTransport()
        dataset = self.acquire(transport)

        self.assertEqual(dataset.security_id, SECURITY_ID)
        self.assertEqual(dataset.as_of_cutoff, CUTOFF)
        self.assertEqual(dataset.series.price_basis, "unadjusted")
        self.assertEqual(len(dataset.series.bars), 3)
        self.assertEqual(len(dataset.corporate_actions.actions), 1)
        self.assertEqual(dataset.corporate_actions.actions[0].new_shares, 2)
        self.assertEqual(dataset.corporate_actions.actions[0].old_shares, 1)
        self.assertEqual(transport.calls, [("RXRX", START, CUTOFF)])

    def test_quant_inputs_are_decimal_not_float(self) -> None:
        dataset = self.acquire(FakeTransport())
        for bar in dataset.series.bars:
            for value in (bar.open, bar.high, bar.low, bar.close):
                self.assertNotIsInstance(value, float)
        self.assertEqual(Decimal(str(dataset.series.bars[0].close)), Decimal("100"))

    def test_the_receipt_pins_the_transport_revision_and_payload_hash(self) -> None:
        dataset = self.acquire(FakeTransport())
        self.assertEqual(dataset.source_id, "fixture")
        self.assertEqual(dataset.source_revision, "rev-1")
        self.assertEqual(len(dataset.source_content_sha256), 64)

    def test_the_same_payload_produces_the_same_receipt_hash(self) -> None:
        first = self.acquire(FakeTransport())
        second = self.acquire(FakeTransport())
        self.assertEqual(first.content_sha256, second.content_sha256)

    def test_a_post_cutoff_bar_is_refused_not_truncated(self) -> None:
        # The Quant adapter refuses this too, with a message that also says
        # cutoff. Asserting the transport-named row is what proves the check
        # fired here, where the error can name the provider and the session.
        with self.assertRaisesRegex(
            TransportError, r"fixture bar 2 session 2026-01-07 is after the cutoff"
        ):
            self.acquire(FakeTransport(), as_of_cutoff=date(2026, 1, 6))

    def test_a_mismatched_symbol_is_refused(self) -> None:
        with self.assertRaisesRegex(TransportError, "different symbol"):
            self.acquire(FakeTransport(payload(symbol="OTHER")))

    def test_a_mismatched_currency_is_refused(self) -> None:
        with self.assertRaisesRegex(TransportError, "currency"):
            self.acquire(FakeTransport(payload(currency="HKD")))

    def test_an_empty_history_is_refused(self) -> None:
        with self.assertRaisesRegex(TransportError, "no daily bars"):
            self.acquire(FakeTransport(payload(bars=())))

    def test_a_start_after_the_cutoff_is_refused(self) -> None:
        with self.assertRaisesRegex(TransportError, "start"):
            self.acquire(FakeTransport(), start=date(2026, 2, 1))

    def test_a_foreign_payload_type_is_refused(self) -> None:
        class Wrong:
            provider_id = "fixture"

            def fetch_daily_history(self, ticker, *, start, end):
                return {"bars": []}

        with self.assertRaisesRegex(TransportError, "HistoryPayload"):
            LiveQuantSource(Wrong()).acquire(  # type: ignore[arg-type]
                ticker="RXRX",
                security_id=SECURITY_ID,
                as_of_cutoff=CUTOFF,
                currency="USD",
                start=START,
            )

    def test_a_duplicate_session_is_refused(self) -> None:
        bars = (
            HistoryBar("2026-01-05", "100", "101", "99", "100", 1000),
            HistoryBar("2026-01-05", "100", "101", "99", "100", 1000),
        )
        with self.assertRaises(TransportError):
            self.acquire(FakeTransport(payload(bars=bars)))


# --------------------------------------------------------------------------
# 4. yfinance live boundary
# --------------------------------------------------------------------------


class FakeRow(dict):
    def get(self, key, default=None):  # noqa: D102
        return super().get(key, default)


class FakeIndexEntry:
    def __init__(self, value: date) -> None:
        self._value = value

    def date(self) -> date:
        return self._value


class FakeHistory:
    def __init__(self, rows: list[FakeRow], sessions: list[date]) -> None:
        self._rows = rows
        self.index = [FakeIndexEntry(session) for session in sessions]

    class _Iloc:
        def __init__(self, rows: list[FakeRow]) -> None:
            self._rows = rows

        def __getitem__(self, index: int) -> FakeRow:
            return self._rows[index]

    @property
    def iloc(self) -> "FakeHistory._Iloc":
        return FakeHistory._Iloc(self._rows)


def fake_history() -> FakeHistory:
    rows = [
        FakeRow(
            {
                "Open": 100.0,
                "High": 101.0,
                "Low": 99.0,
                "Close": 100.0,
                "Volume": 1000,
                "Dividends": 0.0,
                "Stock Splits": 0.0,
            }
        ),
        FakeRow(
            {
                "Open": 50.0,
                "High": 51.0,
                "Low": 49.0,
                "Close": 50.0,
                "Volume": 1100,
                "Dividends": 0.0,
                "Stock Splits": 2.0,
            }
        ),
        FakeRow(
            {
                "Open": 51.0,
                "High": 52.0,
                "Low": 50.0,
                "Close": 51.0,
                "Volume": 1200,
                "Dividends": 0.0,
                "Stock Splits": 0.0,
            }
        ),
    ]
    sessions = [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)]
    return FakeHistory(rows, sessions)


class FakeTicker:
    def __init__(self, module: "FakeYFinanceModule", ticker: str) -> None:
        self._module = module
        self._ticker = ticker

    def history(self, **kwargs: object) -> FakeHistory:
        self._module.history_calls.append(kwargs)
        if self._module.failures:
            raise self._module.failures.pop(0)
        return self._module.history

    def get_history_metadata(self) -> dict[str, object]:
        return {"currency": self._module.currency, "exchangeName": "NasdaqGS"}


class FakeYFinanceModule:
    def __init__(
        self,
        *,
        version: str = "1.5.1",
        currency: str = "USD",
        failures: list[Exception] | None = None,
    ) -> None:
        self.__version__ = version
        self.currency = currency
        self.history = fake_history()
        self.history_calls: list[dict[str, object]] = []
        self.failures = failures or []

    def Ticker(self, ticker: str) -> FakeTicker:  # noqa: N802
        return FakeTicker(self, ticker)


class YFinanceTransportTests(unittest.TestCase):
    def transport(self, module: FakeYFinanceModule) -> YFinanceHistoryTransport:
        clock = FakeClock()
        return YFinanceHistoryTransport(
            YFinanceSettings(),
            module=module,
            window_semantics=TEST_POLICY,
            allow_test_scope=True,
            caller=BoundedCaller(
                policy=RetryPolicy(max_attempts=3, backoff_seconds=1.0),
                rate_limit=RateLimit(max_calls=5, per_seconds=60.0),
                sleep=clock.sleep,
                monotonic=clock.monotonic,
            ),
        )

    def test_it_requests_an_unadjusted_window_bounded_by_the_cutoff(self) -> None:
        module = FakeYFinanceModule()
        self.transport(module).fetch_daily_history("RXRX", start=START, end=CUTOFF)

        call = module.history_calls[0]
        self.assertEqual(call["interval"], "1d")
        self.assertIs(call["auto_adjust"], False)
        self.assertIs(call["back_adjust"], False)
        self.assertIs(call["prepost"], False)
        self.assertIs(call["repair"], False)
        self.assertIs(call["actions"], True)
        self.assertEqual(call["start"], "2026-01-05")
        # yfinance treats end as exclusive, so the cutoff session is included
        # only when the window ends the day after it.
        self.assertEqual(call["end"], "2026-01-08")
        self.assertEqual(call["timeout"], 10.0)

    def test_it_returns_decimal_text_never_floats(self) -> None:
        result = self.transport(FakeYFinanceModule()).fetch_daily_history(
            "RXRX", start=START, end=CUTOFF
        )
        self.assertEqual(result.provider_id, "yahoo_finance_via_yfinance")
        self.assertEqual(result.currency, "USD")
        self.assertEqual(len(result.bars), 3)
        for bar in result.bars:
            for value in (bar.open, bar.high, bar.low, bar.close):
                self.assertIsInstance(value, str)
        self.assertEqual(Decimal(result.bars[1].stock_split), Decimal(2))

    def test_the_revision_is_deterministic_and_not_moving(self) -> None:
        first = self.transport(FakeYFinanceModule()).fetch_daily_history(
            "RXRX", start=START, end=CUTOFF
        )
        second = self.transport(FakeYFinanceModule()).fetch_daily_history(
            "RXRX", start=START, end=CUTOFF
        )
        self.assertEqual(first.source_revision, second.source_revision)
        self.assertNotIn("latest", first.source_revision)

    def test_an_unapproved_library_version_is_refused_and_not_retried(self) -> None:
        module = FakeYFinanceModule(version="0.9.0")
        with self.assertRaisesRegex(TransportError, "version"):
            self.transport(module).fetch_daily_history(
                "RXRX", start=START, end=CUTOFF
            )
        self.assertEqual(module.history_calls, [])

    def test_a_transient_provider_failure_is_retried(self) -> None:
        module = FakeYFinanceModule(failures=[RuntimeError("connection reset")])
        result = self.transport(module).fetch_daily_history(
            "RXRX", start=START, end=CUTOFF
        )
        self.assertEqual(len(module.history_calls), 2)
        self.assertEqual(len(result.bars), 3)

    def test_repeated_failures_surface_as_a_bounded_transport_error(self) -> None:
        module = FakeYFinanceModule(
            failures=[RuntimeError("boom"), RuntimeError("boom"), RuntimeError("boom")]
        )
        with self.assertRaisesRegex(TransportError, "3 attempts"):
            self.transport(module).fetch_daily_history(
                "RXRX", start=START, end=CUTOFF
            )

    def test_adjusted_settings_cannot_be_configured(self) -> None:
        with self.assertRaises(ValueError):
            YFinanceSettings(auto_adjust=True)

    def test_the_live_source_round_trips_into_a_quant_receipt(self) -> None:
        dataset = LiveQuantSource(
            self.transport(FakeYFinanceModule())
        ).acquire(
            ticker="RXRX",
            security_id=SECURITY_ID,
            as_of_cutoff=CUTOFF,
            currency="USD",
            start=START,
        )
        self.assertEqual(dataset.series.source, "yahoo_finance_via_yfinance")
        self.assertEqual(len(dataset.series.bars), 3)
        self.assertEqual(len(dataset.corporate_actions.actions), 1)


# --------------------------------------------------------------------------
# 5. Moomoo blocker
# --------------------------------------------------------------------------


class MoomooTransportTests(unittest.TestCase):
    def test_the_transport_is_blocked_pending_documented_endpoint_semantics(
        self,
    ) -> None:
        with self.assertRaises(TransportBlockedError) as caught:
            MoomooHistoryTransport().fetch_daily_history(
                "US.RXRX", start=START, end=CUTOFF
            )
        self.assertIn("historical", str(caught.exception).lower())

    def test_the_blocker_is_stated_and_names_verification_as_the_gate(self) -> None:
        self.assertIn("official documentation", MOOMOO_HISTORY_BLOCKER)

    def test_the_live_source_surfaces_the_blocker_rather_than_guessing(self) -> None:
        with self.assertRaises(TransportBlockedError):
            LiveQuantSource(MoomooHistoryTransport()).acquire(
                ticker="US.RXRX",
                security_id=SECURITY_ID,
                as_of_cutoff=CUTOFF,
                currency="USD",
                start=START,
            )

    def test_the_transport_declares_the_moomoo_provider_id(self) -> None:
        self.assertEqual(MoomooHistoryTransport().provider_id, "moomoo_openapi")


# --------------------------------------------------------------------------
# 6. Isolation
# --------------------------------------------------------------------------


class BoundaryIsolationTests(unittest.TestCase):
    def test_quant_core_never_imports_a_provider_or_transport(self) -> None:
        import pathlib

        root = pathlib.Path("src/investment_research_os/quant")
        forbidden = (
            "quant_sources",
            "workers",
            "yfinance",
            "moomoo",
            "urllib",
            "socket",
            "requests",
        )
        for module in sorted(root.glob("*.py")):
            text = module.read_text(encoding="utf-8")
            for line in text.splitlines():
                stripped = line.strip()
                if not stripped.startswith(("import ", "from ")):
                    continue
                for term in forbidden:
                    self.assertNotIn(
                        term,
                        stripped,
                        f"{module.name} imports {term!r}: {stripped}",
                    )

    def test_the_quant_source_adapter_never_imports_a_transport(self) -> None:
        import pathlib

        root = pathlib.Path("src/investment_research_os/quant_sources")
        for module in sorted(root.glob("*.py")):
            text = module.read_text(encoding="utf-8")
            for line in text.splitlines():
                stripped = line.strip()
                if not stripped.startswith(("import ", "from ")):
                    continue
                self.assertNotIn("workers", stripped)
                self.assertNotIn("yfinance", stripped)
                self.assertNotIn("moomoo", stripped)

    def test_no_secret_or_token_reaches_the_transport_layer(self) -> None:
        import pathlib

        for name in ("transports.py", "live.py"):
            text = pathlib.Path("workers/quant_sources", name).read_text(
                encoding="utf-8"
            )
            for term in ("access_token", "Authorization", "Bearer", "password"):
                self.assertNotIn(term, text, f"{name} mentions {term}")


# --------------------------------------------------------------------------
# 7. Real pandas/numpy scalars at the yfinance boundary
# --------------------------------------------------------------------------


def numpy_row(**overrides: object) -> FakeRow:
    row = {
        "Open": numpy.float64(100.5),
        "High": numpy.float64(101.0),
        "Low": numpy.float64(99.0),
        "Close": numpy.float64(100.0),
        "Volume": numpy.int64(1000),
        "Dividends": numpy.float64(0.0),
        "Stock Splits": numpy.float64(0.0),
    }
    row.update(overrides)
    return FakeRow(row)


@unittest.skipUnless(numpy is not None, "numpy is not installed")
class NumpyScalarTests(unittest.TestCase):
    def fetch(self, **overrides: object):
        module = FakeYFinanceModule()
        module.history = FakeHistory([numpy_row(**overrides)], [date(2026, 1, 5)])
        clock = FakeClock()
        transport = YFinanceHistoryTransport(
            YFinanceSettings(),
            module=module,
            window_semantics=TEST_POLICY,
            allow_test_scope=True,
            caller=BoundedCaller(
                policy=RetryPolicy(max_attempts=1),
                rate_limit=RateLimit(max_calls=5, per_seconds=60.0),
                sleep=clock.sleep,
                monotonic=clock.monotonic,
            ),
        )
        return transport.fetch_daily_history("RXRX", start=START, end=CUTOFF)

    def test_numpy_scalars_normalize_to_decimal_text_and_plain_ints(self) -> None:
        result = self.fetch()
        bar = result.bars[0]
        self.assertEqual(bar.open, "100.5")
        self.assertEqual(Decimal(bar.close), Decimal("100"))
        for value in (bar.open, bar.high, bar.low, bar.close, bar.stock_split):
            self.assertIs(type(value), str)
        self.assertIs(type(bar.volume), int)
        self.assertEqual(bar.volume, 1000)

    def test_a_numpy_split_ratio_survives_as_a_decimal(self) -> None:
        result = self.fetch(**{"Stock Splits": numpy.float64(2.0)})
        self.assertEqual(Decimal(result.bars[0].stock_split), Decimal(2))

    def test_a_nan_price_is_refused(self) -> None:
        # HistoryBar refuses a non-finite Decimal too, with a message that also
        # says finite. Naming the bar and the field proves the transport caught
        # it, where the error can still say which source cell was empty.
        with self.assertRaisesRegex(
            TransportError, r"bar 0 close must be a finite number"
        ):
            self.fetch(Close=numpy.float64("nan"))

    def test_an_infinite_price_is_refused(self) -> None:
        with self.assertRaisesRegex(
            TransportError, r"bar 0 open must be a finite number"
        ):
            self.fetch(Open=numpy.float64("inf"))

    def test_a_numpy_boolean_price_is_refused(self) -> None:
        with self.assertRaisesRegex(TransportError, "boolean"):
            self.fetch(Open=numpy.bool_(True))

    def test_an_integral_float_volume_is_accepted(self) -> None:
        self.assertEqual(self.fetch(Volume=numpy.float64(1000.0)).bars[0].volume, 1000)

    def test_a_fractional_volume_is_refused(self) -> None:
        with self.assertRaisesRegex(TransportError, "whole number"):
            self.fetch(Volume=numpy.float64(1000.5))

    def test_a_nan_volume_is_refused(self) -> None:
        with self.assertRaisesRegex(
            TransportError, r"bar 0 volume must be a finite whole number"
        ):
            self.fetch(Volume=numpy.float64("nan"))

    def test_a_numpy_boolean_volume_is_refused(self) -> None:
        with self.assertRaisesRegex(TransportError, "volume"):
            self.fetch(Volume=numpy.bool_(True))

    def test_a_negative_numpy_volume_is_refused(self) -> None:
        with self.assertRaisesRegex(TransportError, "negative"):
            self.fetch(Volume=numpy.int64(-1))


@unittest.skipUnless(pandas is not None, "pandas is not installed")
class PandasFrameTests(unittest.TestCase):
    def test_a_real_pandas_frame_maps_to_decimal_text(self) -> None:
        frame = pandas.DataFrame(
            {
                "Open": [100.5, 50.0],
                "High": [101.0, 51.0],
                "Low": [99.0, 49.0],
                "Close": [100.0, 50.0],
                "Volume": [1000, 1100],
                "Dividends": [0.0, 0.0],
                "Stock Splits": [0.0, 2.0],
            },
            index=pandas.to_datetime(["2026-01-05", "2026-01-06"]),
        )
        module = FakeYFinanceModule()
        module.history = frame
        result = YFinanceHistoryTransport(
            YFinanceSettings(),
            module=module,
            window_semantics=TEST_POLICY,
            allow_test_scope=True,
        ).fetch_daily_history("RXRX", start=START, end=date(2026, 1, 6))

        self.assertEqual([bar.session for bar in result.bars], ["2026-01-05", "2026-01-06"])
        self.assertEqual(result.bars[0].open, "100.5")
        self.assertIs(type(result.bars[0].volume), int)
        self.assertEqual(Decimal(result.bars[1].stock_split), Decimal(2))


# --------------------------------------------------------------------------
# 8. Requested window lower bound
# --------------------------------------------------------------------------


class WindowLowerBoundTests(unittest.TestCase):
    def test_a_bar_before_the_requested_start_is_refused_not_trimmed(self) -> None:
        # The Quant adapter accepts this bar happily: it is inside the cutoff
        # and well formed. Only the requested window makes it wrong, so the
        # assertion names the provider and the session to prove this layer
        # raised.
        with self.assertRaisesRegex(
            TransportError,
            r"fixture bar 0 session 2026-01-05 is before the requested start "
            r"2026-01-06",
        ):
            LiveQuantSource(FakeTransport()).acquire(
                ticker="RXRX",
                security_id=SECURITY_ID,
                as_of_cutoff=CUTOFF,
                currency="USD",
                start=date(2026, 1, 6),
            )

    def test_a_bar_exactly_on_the_start_is_kept(self) -> None:
        dataset = LiveQuantSource(FakeTransport()).acquire(
            ticker="RXRX",
            security_id=SECURITY_ID,
            as_of_cutoff=CUTOFF,
            currency="USD",
            start=START,
        )
        self.assertEqual(len(dataset.series.bars), 3)


# --------------------------------------------------------------------------
# 9. Provider identity binding
# --------------------------------------------------------------------------


class ProviderIdentityTests(unittest.TestCase):
    def test_a_forged_provider_id_is_refused(self) -> None:
        transport = FakeTransport(payload(provider_id="moomoo_openapi"))
        with self.assertRaisesRegex(
            TransportError,
            r"payload provider 'moomoo_openapi' does not match the transport "
            r"provider 'fixture'",
        ):
            LiveQuantSource(transport).acquire(
                ticker="RXRX",
                security_id=SECURITY_ID,
                as_of_cutoff=CUTOFF,
                currency="USD",
                start=START,
            )

    def test_a_transport_without_a_provider_id_is_refused(self) -> None:
        class Anonymous:
            def fetch_daily_history(self, ticker, *, start, end):
                return payload()

        with self.assertRaisesRegex(TransportError, "provider_id"):
            LiveQuantSource(Anonymous()).acquire(  # type: ignore[arg-type]
                ticker="RXRX",
                security_id=SECURITY_ID,
                as_of_cutoff=CUTOFF,
                currency="USD",
                start=START,
            )

    def test_the_receipt_source_is_the_bound_provider(self) -> None:
        dataset = LiveQuantSource(FakeTransport()).acquire(
            ticker="RXRX",
            security_id=SECURITY_ID,
            as_of_cutoff=CUTOFF,
            currency="USD",
            start=START,
        )
        self.assertEqual(dataset.source_id, "fixture")


# --------------------------------------------------------------------------
# 10. Unverified yfinance window semantics
# --------------------------------------------------------------------------


class WindowSemanticsAuthorizationTests(unittest.TestCase):
    """Nothing but a registered, digest-matching, correctly scoped policy passes."""

    def transport(self, **overrides: object) -> YFinanceHistoryTransport:
        kwargs: dict[str, object] = {"module": FakeYFinanceModule()}
        kwargs.update(overrides)
        return YFinanceHistoryTransport(
            YFinanceSettings(),
            **kwargs,  # type: ignore[arg-type]
        )

    def fetch(self, transport: YFinanceHistoryTransport):
        return transport.fetch_daily_history("RXRX", start=START, end=CUTOFF)

    # --- the gate itself -------------------------------------------------

    def test_no_policy_blocks_the_fetch(self) -> None:
        with self.assertRaises(TransportBlockedError):
            self.fetch(self.transport())

    def test_the_blocker_names_official_documentation_and_the_registry(self) -> None:
        self.assertIn("official documentation", YFINANCE_WINDOW_BLOCKER)
        self.assertIn("exclusive", YFINANCE_WINDOW_BLOCKER)
        self.assertIn("WINDOW_SEMANTICS_REGISTRY", YFINANCE_WINDOW_BLOCKER)

    def test_the_registered_test_policy_authorizes_an_injected_module(self) -> None:
        result = self.fetch(
            self.transport(window_semantics=TEST_POLICY, allow_test_scope=True)
        )
        self.assertEqual(len(result.bars), 3)

    # --- adversarial: fabricated authorization ---------------------------

    def test_a_free_form_string_cannot_unblock_the_fetch(self) -> None:
        for fake in (
            "https://ranchero.com/yfinance/docs",
            "verified",
            TEST_WINDOW_SEMANTICS_POLICY_ID,
            TEST_WINDOW_SEMANTICS_EVIDENCE_SHA256,
        ):
            with self.subTest(fake=fake):
                with self.assertRaises(TransportBlockedError):
                    self.fetch(
                        self.transport(
                            window_semantics=fake, allow_test_scope=True
                        )
                    )

    def test_an_unregistered_policy_id_cannot_unblock_the_fetch(self) -> None:
        forged = WindowSemanticsPolicy(
            policy_id="yfinance-end-exclusive-verified",
            end_is_exclusive=True,
            evidence_sha256=TEST_WINDOW_SEMANTICS_EVIDENCE_SHA256,
            verified_on=date(2026, 8, 17),
        )
        with self.assertRaisesRegex(TransportBlockedError, "is not registered"):
            self.fetch(
                self.transport(window_semantics=forged, allow_test_scope=True)
            )

    def test_a_tampered_evidence_digest_cannot_unblock_the_fetch(self) -> None:
        tampered = WindowSemanticsPolicy(
            policy_id=TEST_WINDOW_SEMANTICS_POLICY_ID,
            end_is_exclusive=True,
            evidence_sha256="0" * 64,
            verified_on=date(2026, 8, 17),
        )
        with self.assertRaisesRegex(TransportBlockedError, "pinned evidence digest"):
            self.fetch(
                self.transport(window_semantics=tampered, allow_test_scope=True)
            )

    def test_a_flipped_boundary_claim_cannot_unblock_the_fetch(self) -> None:
        flipped = WindowSemanticsPolicy(
            policy_id=TEST_WINDOW_SEMANTICS_POLICY_ID,
            end_is_exclusive=False,
            evidence_sha256=TEST_WINDOW_SEMANTICS_EVIDENCE_SHA256,
            verified_on=date(2026, 8, 17),
        )
        with self.assertRaisesRegex(TransportBlockedError, "different end boundary"):
            self.fetch(
                self.transport(window_semantics=flipped, allow_test_scope=True)
            )

    def test_a_malformed_policy_cannot_be_constructed(self) -> None:
        with self.assertRaises(TransportError):
            WindowSemanticsPolicy(
                policy_id="  ",
                end_is_exclusive=True,
                evidence_sha256=TEST_WINDOW_SEMANTICS_EVIDENCE_SHA256,
                verified_on=date(2026, 8, 17),
            )
        with self.assertRaises(TransportError):
            WindowSemanticsPolicy(
                policy_id=TEST_WINDOW_SEMANTICS_POLICY_ID,
                end_is_exclusive=True,
                evidence_sha256="not-a-digest",
                verified_on=date(2026, 8, 17),
            )
        with self.assertRaises(TransportError):
            WindowSemanticsPolicy(
                policy_id=TEST_WINDOW_SEMANTICS_POLICY_ID,
                end_is_exclusive=True,
                evidence_sha256=TEST_WINDOW_SEMANTICS_EVIDENCE_SHA256,
                verified_on="2026-08-17",  # type: ignore[arg-type]
            )

    def test_the_registry_cannot_be_extended_at_runtime(self) -> None:
        with self.assertRaises(TypeError):
            WINDOW_SEMANTICS_REGISTRY["forged"] = object()  # type: ignore[index]

    # --- adversarial: test scope may not reach production ----------------

    def test_the_test_policy_requires_the_explicit_test_opt_in(self) -> None:
        with self.assertRaisesRegex(TransportBlockedError, "explicit"):
            self.fetch(self.transport(window_semantics=TEST_POLICY))

    def test_the_test_policy_can_never_authorize_a_live_fetch(self) -> None:
        # No injected module means the real library would be imported and
        # called. The importer is a tripwire: reaching it is the failure.
        def forbidden() -> object:
            raise AssertionError("the live import path must not be reached")

        transport = YFinanceHistoryTransport(
            YFinanceSettings(),
            window_semantics=TEST_POLICY,
            allow_test_scope=True,
            importer=forbidden,
        )
        with self.assertRaisesRegex(
            TransportBlockedError, "may never authorize a live fetch"
        ):
            self.fetch(transport)

    def test_the_test_opt_in_alone_authorizes_nothing(self) -> None:
        with self.assertRaises(TransportBlockedError):
            self.fetch(self.transport(allow_test_scope=True))

    # --- the production path stays blocked by an absent record -----------

    def test_exactly_one_verified_policy_is_registered(self) -> None:
        # Still a tripwire, now with a known-good set rather than an empty one.
        # It fails the moment a second verified record appears, which is when a
        # new claim needs the same human review this one got.
        self.assertEqual(
            [
                policy_id
                for policy_id, entry in WINDOW_SEMANTICS_REGISTRY.items()
                if entry.scope != "test"
            ],
            [YFINANCE_END_EXCLUSIVE_POLICY_ID],
        )

    def test_the_registry_holds_exactly_the_expected_policies(self) -> None:
        self.assertEqual(
            sorted(WINDOW_SEMANTICS_REGISTRY),
            sorted(
                [TEST_WINDOW_SEMANTICS_POLICY_ID, YFINANCE_END_EXCLUSIVE_POLICY_ID]
            ),
        )

    def test_authorization_is_reusable_outside_the_transport(self) -> None:
        registered = authorize_window_semantics(
            TEST_POLICY, allow_test_scope=True, live_path=False
        )
        self.assertEqual(registered.scope, "test")
        self.assertIn("Fixture only", registered.note)


class VerifiedYFinancePolicyTests(unittest.TestCase):
    """The verified record authorizes a live path, and only on its own terms."""

    def record(self):
        return WINDOW_SEMANTICS_REGISTRY[YFINANCE_END_EXCLUSIVE_POLICY_ID]

    def live_transport(self, **overrides: object) -> YFinanceHistoryTransport:
        """A transport with no injected module, so live_path is True.

        The importer returns the fake module rather than importing yfinance, so
        the authorization path is exercised without a network call and without
        the library installed.
        """

        kwargs: dict[str, object] = {
            "window_semantics": yfinance_end_exclusive_policy(),
            "importer": FakeYFinanceModule,
        }
        kwargs.update(overrides)
        return YFinanceHistoryTransport(
            YFinanceSettings(),
            **kwargs,  # type: ignore[arg-type]
        )

    # --- the record itself ------------------------------------------------

    def test_the_pinned_digest_is_the_one_recorded_in_the_response(self) -> None:
        # The digest is the whole authorization. If it drifts from the value
        # published in response 2026-08-18-030, the record no longer attests to
        # anything a reviewer can recompute.
        self.assertEqual(
            YFINANCE_END_EXCLUSIVE_EVIDENCE_SHA256,
            "acd3af838820bcfd3ebf8bda972712c32868577c3494f58151cd6ae0a5ac665c",
        )
        self.assertEqual(
            self.record().evidence_sha256, YFINANCE_END_EXCLUSIVE_EVIDENCE_SHA256
        )

    def test_the_record_pins_its_metadata(self) -> None:
        record = self.record()
        self.assertEqual(record.scope, "verified")
        self.assertIs(record.end_is_exclusive, True)
        self.assertEqual(record.verified_on, date(2026, 8, 17))
        self.assertEqual(record.verified_on, YFINANCE_END_EXCLUSIVE_VERIFIED_ON)
        self.assertEqual(record.library_version, "1.5.1")
        self.assertEqual(record.library_version, YFinanceSettings().library_version)

    def test_the_record_cites_its_evidence_and_states_its_limit(self) -> None:
        record = self.record()
        self.assertEqual(len(record.evidence_urls), 3)
        for url in record.evidence_urls:
            self.assertTrue(url.startswith("https://"), url)
        self.assertIn("1.5.1", record.evidence_urls[0])
        # The note must not let a reader mistake documentary verification for a
        # live provider proof.
        self.assertIn("no live yfinance call was made", record.note.lower())
        self.assertIn("2026-08-18-030", record.note)

    # --- what it authorizes ----------------------------------------------

    def test_the_verified_policy_authorizes_a_live_path(self) -> None:
        result = self.live_transport().fetch_daily_history(
            "RXRX", start=START, end=CUTOFF
        )
        self.assertEqual(len(result.bars), 3)

    def test_it_needs_no_test_opt_in(self) -> None:
        registered = authorize_window_semantics(
            yfinance_end_exclusive_policy(),
            allow_test_scope=False,
            live_path=True,
            library_version="1.5.1",
        )
        self.assertEqual(registered.scope, "verified")

    def test_the_window_it_authorizes_still_includes_the_cutoff(self) -> None:
        module = FakeYFinanceModule()
        self.live_transport(module=module).fetch_daily_history(
            "RXRX", start=START, end=CUTOFF
        )
        # end is exclusive per the verified record, so the request must reach
        # the day after the cutoff for the cutoff session to be returned.
        self.assertEqual(module.history_calls[0]["end"], "2026-01-08")
        self.assertEqual(module.history_calls[0]["start"], "2026-01-05")

    # --- what it does not authorize --------------------------------------

    def test_a_different_library_version_is_refused(self) -> None:
        with self.assertRaisesRegex(
            TransportBlockedError, r"verified against library version '1\.5\.1'"
        ):
            authorize_window_semantics(
                yfinance_end_exclusive_policy(),
                allow_test_scope=False,
                live_path=True,
                library_version="1.6.0",
            )

    def test_the_transport_binds_its_own_pinned_library_version(self) -> None:
        # Asserting this through authorize_window_semantics alone would pass
        # even if the transport never forwarded its version, so the check has
        # to run through the transport.
        with self.assertRaisesRegex(
            TransportBlockedError, r"verified against library version '1\.5\.1'"
        ):
            YFinanceHistoryTransport(
                YFinanceSettings(library_version="1.6.0"),
                window_semantics=yfinance_end_exclusive_policy(),
                importer=FakeYFinanceModule,
            ).fetch_daily_history("RXRX", start=START, end=CUTOFF)

    def test_a_restated_verification_date_is_refused(self) -> None:
        forged = WindowSemanticsPolicy(
            policy_id=YFINANCE_END_EXCLUSIVE_POLICY_ID,
            end_is_exclusive=True,
            evidence_sha256=YFINANCE_END_EXCLUSIVE_EVIDENCE_SHA256,
            verified_on=date(2026, 8, 18),
        )
        with self.assertRaisesRegex(TransportBlockedError, "claims verification on"):
            self.live_transport(window_semantics=forged).fetch_daily_history(
                "RXRX", start=START, end=CUTOFF
            )

    def test_a_flipped_boundary_claim_is_still_refused(self) -> None:
        forged = WindowSemanticsPolicy(
            policy_id=YFINANCE_END_EXCLUSIVE_POLICY_ID,
            end_is_exclusive=False,
            evidence_sha256=YFINANCE_END_EXCLUSIVE_EVIDENCE_SHA256,
            verified_on=YFINANCE_END_EXCLUSIVE_VERIFIED_ON,
        )
        with self.assertRaisesRegex(TransportBlockedError, "different end boundary"):
            self.live_transport(window_semantics=forged).fetch_daily_history(
                "RXRX", start=START, end=CUTOFF
            )

    def test_a_tampered_digest_is_still_refused(self) -> None:
        forged = WindowSemanticsPolicy(
            policy_id=YFINANCE_END_EXCLUSIVE_POLICY_ID,
            end_is_exclusive=True,
            evidence_sha256="f" * 64,
            verified_on=YFINANCE_END_EXCLUSIVE_VERIFIED_ON,
        )
        with self.assertRaisesRegex(TransportBlockedError, "pinned evidence digest"):
            self.live_transport(window_semantics=forged).fetch_daily_history(
                "RXRX", start=START, end=CUTOFF
            )

    def test_the_verified_policy_does_not_unblock_moomoo(self) -> None:
        # Authorization is per finding, not a global unlock. Nothing about the
        # yfinance window boundary says anything about a Moomoo endpoint.
        with self.assertRaises(TransportBlockedError):
            MoomooHistoryTransport().fetch_daily_history(
                "US.RXRX", start=START, end=CUTOFF
            )
        self.assertIn("pagination", MOOMOO_HISTORY_BLOCKER)
        self.assertIn("adjustment", MOOMOO_HISTORY_BLOCKER)
        self.assertIn("corporate-action", MOOMOO_HISTORY_BLOCKER)


if __name__ == "__main__":
    unittest.main()

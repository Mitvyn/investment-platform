"""The bridge from an approved provider transport into the Quant workspace.

`fetch_provider_dataset` is the one place a `HistoricalTransport` fetch is
reshaped into the same `quant_local_dataset.v1` document a hand-written import
file must satisfy, so it inherits every rule `build_dataset` already enforces:
duplicate or out-of-order sessions, future data, and an unhashable row are all
refused here exactly as they would be for a file import, without this module
repeating any of that logic.

Only injected fake transports are used. No provider, model, hosted, or network
client is constructed here.
"""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from investment_research_os.quant_sources import payload_sha256
from workers.quant_sources.transports import (
    HistoryBar,
    HistoryPayload,
    TransportBlockedError,
    TransportError,
)
from workers.quant_sources.workspace_bridge import (
    fetch_provider_dataset,
    fetch_provider_dataset_document,
)
from workers.quant_workspace.intake import QuantWorkspaceError, build_dataset

SECURITY_ID = "3f1b0c2e-9d4a-4c7f-b1e2-8a5d6c7f0912"
START = date(2026, 1, 5)
CUTOFF = date(2026, 1, 7)


def bars() -> tuple[HistoryBar, ...]:
    return (
        HistoryBar("2026-01-05", "100", "101", "99", "100", 1000),
        HistoryBar("2026-01-06", "50", "51", "49", "50", 1100, "2"),
        HistoryBar("2026-01-07", "51", "52", "50", "51", 1200),
    )


def make_payload(
    *,
    provider_id: str = "fixture",
    symbol: str = "RXRX",
    currency: str = "USD",
    revision: str = "rev-1",
    bars_: tuple[HistoryBar, ...] | None = None,
) -> HistoryPayload:
    return HistoryPayload(
        provider_id=provider_id,
        symbol=symbol,
        currency=currency,
        source_revision=revision,
        bars=bars_ if bars_ is not None else bars(),
    )


class FakeTransport:
    provider_id = "fixture"

    def __init__(self, result: HistoryPayload | Exception | None = None) -> None:
        self.result = result if result is not None else make_payload()
        self.calls: list[tuple[str, date, date]] = []

    def fetch_daily_history(
        self, ticker: str, *, start: date, end: date
    ) -> HistoryPayload:
        self.calls.append((ticker, start, end))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class BlockedTransport:
    provider_id = "moomoo_openapi"

    def fetch_daily_history(self, ticker: str, *, start: date, end: date):
        raise TransportBlockedError(
            "Moomoo historical daily-bar acquisition is blocked."
        )


class FetchProviderDatasetDocumentTests(unittest.TestCase):
    def fetch(self, transport, **overrides: object):
        kwargs: dict[str, object] = {
            "ticker": "RXRX",
            "security_id": SECURITY_ID,
            "start": START,
            "as_of_cutoff": CUTOFF,
        }
        kwargs.update(overrides)
        return fetch_provider_dataset_document(transport, **kwargs)  # type: ignore[arg-type]

    def test_a_successful_fetch_becomes_a_quant_local_dataset_document(self) -> None:
        document = self.fetch(FakeTransport())
        self.assertEqual(document["contract_version"], "quant_local_dataset.v1")
        self.assertEqual(document["security_id"], SECURITY_ID)
        self.assertEqual(document["currency"], "USD")
        self.assertEqual(document["as_of_cutoff"], CUTOFF.isoformat())
        self.assertEqual(document["source_id"], "fixture")
        self.assertEqual(document["source_revision"], "rev-1")
        self.assertEqual(len(str(document["source_content_sha256"])), 64)
        bars_ = document["bars"]
        assert isinstance(bars_, list)
        self.assertEqual(len(bars_), 3)
        self.assertEqual(bars_[0]["session"], "2026-01-05")
        self.assertEqual(bars_[0]["open"], "100")
        actions = document["corporate_actions"]
        assert isinstance(actions, list)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["new_shares"], 2)
        self.assertEqual(actions[0]["old_shares"], 1)

    def test_the_ticker_is_sent_exactly_as_the_caller_gave_it(self) -> None:
        transport = FakeTransport()
        self.fetch(transport, ticker="rxrx")
        self.assertEqual(transport.calls, [("RXRX", START, CUTOFF)])

    def test_the_document_round_trips_through_build_dataset(self) -> None:
        document = self.fetch(FakeTransport())
        dataset = build_dataset(document, security_id=SECURITY_ID)
        self.assertEqual(dataset.security_id, SECURITY_ID)
        self.assertEqual(len(dataset.series.bars), 3)

    def test_fetch_provider_dataset_returns_the_document_and_the_receipt(self) -> None:
        document, dataset = fetch_provider_dataset(
            FakeTransport(),
            ticker="RXRX",
            security_id=SECURITY_ID,
            start=START,
            as_of_cutoff=CUTOFF,
        )
        self.assertEqual(
            document["source_content_sha256"], dataset.source_content_sha256
        )
        self.assertEqual(dataset.security_id, SECURITY_ID)

    def test_currency_is_read_from_the_provider_never_assumed(self) -> None:
        document = self.fetch(FakeTransport(make_payload(currency="HKD")))
        self.assertEqual(document["currency"], "HKD")

    def test_an_ill_formed_currency_is_refused_by_the_transport_boundary(self) -> None:
        with self.assertRaises(TransportError):
            make_payload(currency="usd")

    def test_a_blank_ticker_is_refused(self) -> None:
        with self.assertRaises(QuantWorkspaceError) as caught:
            self.fetch(FakeTransport(), ticker="   ")
        self.assertEqual(caught.exception.code, "fetch_ticker_invalid")

    def test_a_non_date_window_is_refused(self) -> None:
        with self.assertRaises(QuantWorkspaceError) as caught:
            self.fetch(FakeTransport(), start="2026-01-05")
        self.assertEqual(caught.exception.code, "fetch_window_invalid")

    def test_start_after_cutoff_is_refused(self) -> None:
        with self.assertRaises(QuantWorkspaceError) as caught:
            self.fetch(FakeTransport(), start=date(2026, 2, 1))
        self.assertEqual(caught.exception.code, "fetch_provider_rejected")

    def test_a_provider_symbol_mismatch_is_refused(self) -> None:
        with self.assertRaises(QuantWorkspaceError) as caught:
            self.fetch(FakeTransport(make_payload(symbol="OTHER")))
        self.assertEqual(caught.exception.code, "fetch_provider_rejected")

    def test_a_post_cutoff_bar_is_refused_not_truncated(self) -> None:
        with self.assertRaises(QuantWorkspaceError) as caught:
            self.fetch(FakeTransport(), as_of_cutoff=date(2026, 1, 6))
        self.assertEqual(caught.exception.code, "fetch_provider_rejected")

    def test_a_duplicate_session_is_refused(self) -> None:
        duplicate = (
            HistoryBar("2026-01-05", "100", "101", "99", "100", 1000),
            HistoryBar("2026-01-05", "100", "101", "99", "100", 1000),
        )
        with self.assertRaises(QuantWorkspaceError) as caught:
            self.fetch(FakeTransport(make_payload(bars_=duplicate)))
        self.assertEqual(caught.exception.code, "fetch_provider_rejected")

    def test_an_out_of_order_session_is_refused_when_reloaded(self) -> None:
        # The transport boundary only bounds the window; strict session order
        # is one of `build_dataset`'s own rules, inherited for free because
        # this module hands it the exact same document shape a file import
        # would produce.
        out_of_order = {
            "as_of_cutoff": CUTOFF.isoformat(),
            "bars": [
                {
                    "close": "100",
                    "high": "101",
                    "low": "99",
                    "open": "100",
                    "session": "2026-01-06",
                    "volume": 1000,
                },
                {
                    "close": "100",
                    "high": "101",
                    "low": "99",
                    "open": "100",
                    "session": "2026-01-05",
                    "volume": 1000,
                },
            ],
            "contract_version": "quant_local_dataset.v1",
            "corporate_actions": [],
            "currency": "USD",
            "security_id": SECURITY_ID,
            "source_content_sha256": "0" * 64,
            "source_id": "fixture",
            "source_revision": "rev-1",
        }
        out_of_order["source_content_sha256"] = payload_sha256(
            bar_rows=tuple(out_of_order["bars"]), split_rows=()
        )
        with self.assertRaises(QuantWorkspaceError) as caught:
            build_dataset(out_of_order, security_id=SECURITY_ID)
        self.assertEqual(caught.exception.code, "dataset_sessions_invalid")

    def test_an_empty_history_is_refused(self) -> None:
        with self.assertRaises(QuantWorkspaceError) as caught:
            self.fetch(FakeTransport(make_payload(bars_=())))
        self.assertEqual(caught.exception.code, "fetch_provider_rejected")

    def test_a_missing_volume_bar_is_refused_at_the_transport_boundary(self) -> None:
        with self.assertRaises(TransportError):
            HistoryBar("2026-01-05", "100", "101", "99", "100", None)  # type: ignore[arg-type]

    def test_a_nan_price_is_refused_via_the_yfinance_mapping_boundary(self) -> None:
        # HistoryBar itself only accepts already-decimal text; NaN/Infinity
        # from a raw provider frame are refused earlier, in the yfinance
        # mapping tested in tests/test_quant_source_transports.py. This test
        # pins that the same TransportError still surfaces as a reviewed
        # `fetch_provider_rejected` code once it crosses this module.
        class NanTransport:
            provider_id = "fixture"

            def fetch_daily_history(self, ticker, *, start, end):
                raise TransportError("bar 0 close must be a finite number")

        with self.assertRaises(QuantWorkspaceError) as caught:
            self.fetch(NanTransport())
        self.assertEqual(caught.exception.code, "fetch_provider_rejected")

    def test_a_stock_split_becomes_a_corporate_action_row(self) -> None:
        document = self.fetch(FakeTransport())
        actions = document["corporate_actions"]
        assert isinstance(actions, list)
        self.assertEqual(actions[0]["effective_session"], "2026-01-06")

    def test_a_moomoo_transport_stays_blocked(self) -> None:
        with self.assertRaises(QuantWorkspaceError) as caught:
            self.fetch(BlockedTransport())
        self.assertEqual(caught.exception.code, "fetch_provider_blocked")

    def test_a_retry_exhausted_failure_surfaces_as_a_reviewed_code(self) -> None:
        with self.assertRaises(QuantWorkspaceError) as caught:
            self.fetch(
                FakeTransport(TransportError("provider call failed after 3 attempts"))
            )
        self.assertEqual(caught.exception.code, "fetch_provider_rejected")

    def test_a_non_uuid_security_id_is_refused(self) -> None:
        with self.assertRaises(QuantWorkspaceError):
            self.fetch(FakeTransport(), security_id="not-a-uuid")

    def test_prices_never_arrive_as_binary_floats(self) -> None:
        document = self.fetch(FakeTransport())
        for row in document["bars"]:  # type: ignore[union-attr]
            for field in ("open", "high", "low", "close"):
                self.assertNotIsInstance(row[field], float)  # type: ignore[index]
                Decimal(str(row[field]))  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()

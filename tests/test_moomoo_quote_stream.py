from __future__ import annotations

import json
import threading
import time
import unittest
from collections import deque
from contextlib import AbstractContextManager
from typing import Self

from workers.portfolio.quote_stream import (
    MoomooQuoteAccess,
    MoomooLiveQuote,
    MoomooQuoteProtocolError,
    MoomooQuoteSubscriptionRejected,
    MoomooQuoteStream,
    build_auth_frame,
    build_subscription_frame,
    parse_quote_message,
)


class FakeConnection(AbstractContextManager["FakeConnection"]):
    def __init__(self, messages: list[str]) -> None:
        self.messages = deque(messages)
        self.sent: list[str] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def send(self, message: str) -> None:
        self.sent.append(message)

    def recv(self, *, timeout: float) -> str:
        del timeout
        if self.messages:
            return self.messages.popleft()
        time.sleep(0.001)
        raise TimeoutError


class BlockingAuthConnection(AbstractContextManager["BlockingAuthConnection"]):
    def __init__(self) -> None:
        self.entered_recv = threading.Event()
        self.release_recv = threading.Event()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def send(self, message: str) -> None:
        del message

    def recv(self, *, timeout: float) -> str:
        del timeout
        self.entered_recv.set()
        self.release_recv.wait(timeout=1)
        return '{"id":"auth-1","session_id":"session-1"}'


class MoomooQuoteProtocolTests(unittest.TestCase):
    def test_builds_exact_oauth_auth_and_quote_only_subscription_frames(self) -> None:
        auth = json.loads(build_auth_frame("access-secret"))
        subscribe = json.loads(
            build_subscription_frame(
                action="subscribe",
                request_id="subscribe-1",
                symbols=("US.GANX", "US.RXRX"),
            )
        )

        self.assertEqual(
            auth,
            {
                "action": "auth",
                "data": {
                    "auth_type": "oauth2",
                    "authorization": "Bearer access-secret",
                },
            },
        )
        self.assertEqual(
            subscribe,
            {
                "action": "subscribe",
                "id": "subscribe-1",
                "quote": ["US.GANX", "US.RXRX"],
            },
        )

    def test_rejects_empty_or_oversized_subscription_before_transport(self) -> None:
        with self.assertRaises(MoomooQuoteProtocolError):
            build_subscription_frame(
                action="subscribe",
                request_id="subscribe-1",
                symbols=(),
            )
        with self.assertRaises(MoomooQuoteProtocolError):
            build_subscription_frame(
                action="subscribe",
                request_id="subscribe-1",
                symbols=tuple(f"US.T{i:03d}" for i in range(401)),
            )

    def test_parses_quote_with_decimal_strings_and_provider_timestamp(self) -> None:
        quote = parse_quote_message(
            json.dumps(
                {
                    "type": "QUOTE",
                    "symbol": "US.RXRX",
                    "data": {
                        "data_time_ms": 1786590000123,
                        "last_price": 3.07,
                        "open_price": 3,
                        "high_price": 3.12,
                        "low_price": 2.95,
                        "prev_close_price": 3.01,
                        "volume": 123456,
                        "turnover": 378901.25,
                        "suspension": False,
                        "sec_status": "NORMAL",
                        "new_provider_field": "ignored",
                    },
                }
            )
        )

        self.assertEqual(
            quote,
            MoomooLiveQuote(
                symbol="US.RXRX",
                data_time_ms=1786590000123,
                last_price="3.07",
                open_price="3",
                high_price="3.12",
                low_price="2.95",
                previous_close_price="3.01",
                volume="123456",
                turnover="378901.25",
                suspension=False,
                security_status="NORMAL",
            ),
        )

    def test_ignores_unknown_message_and_rejects_unsafe_quote_numbers(self) -> None:
        self.assertIsNone(parse_quote_message('{"type":"MARKET_STATE","data":{}}'))
        with self.assertRaises(MoomooQuoteProtocolError):
            parse_quote_message(
                '{"type":"QUOTE","symbol":"US.RXRX",'
                '"data":{"data_time_ms":1,"last_price":true}}'
            )
        with self.assertRaises(MoomooQuoteProtocolError):
            parse_quote_message("not-json")

    def test_surfaces_account_quota_rejection_without_treating_it_as_push(self) -> None:
        with self.assertRaisesRegex(MoomooQuoteSubscriptionRejected, "quota"):
            parse_quote_message(
                '{"id":"subscribe-1","code":4,"message":"sub quota exceeded, max=1"}'
            )


class MoomooQuoteStreamTests(unittest.TestCase):
    def test_stop_timeout_keeps_live_thread_owned_and_refuses_restart(self) -> None:
        connection = BlockingAuthConnection()
        stream = MoomooQuoteStream(
            access_supplier=lambda: MoomooQuoteAccess("unused", 7200),
            connector=lambda: connection,
            stop_timeout_seconds=0.01,
        )
        stream.start(MoomooQuoteAccess("access-secret", 7200))
        self.assertTrue(connection.entered_recv.wait(timeout=1))

        with self.assertRaisesRegex(MoomooQuoteProtocolError, "did not stop"):
            stream.stop()
        self.assertEqual(stream.snapshot().state, "stopping")
        with self.assertRaisesRegex(MoomooQuoteProtocolError, "already started"):
            stream.start(MoomooQuoteAccess("second-secret", 7200))

        connection.release_recv.set()
        self.assertTrue(_wait_until(lambda: stream.snapshot().state == "stopping"))
        stream.stop()
        self.assertEqual(stream.snapshot().state, "disconnected")

    def test_stream_sends_one_changed_subscription_and_caches_push(self) -> None:
        connection = FakeConnection(
            [
                '{"id":"auth-1","session_id":"session-1"}',
                json.dumps(
                    {
                        "type": "QUOTE",
                        "symbol": "US.RXRX",
                        "data": {
                            "data_time_ms": 1786590000123,
                            "last_price": 3.07,
                        },
                    }
                ),
            ]
        )
        stream = MoomooQuoteStream(
            access_supplier=lambda: MoomooQuoteAccess("unused", 7200),
            connector=lambda: connection,
        )
        self.addCleanup(stream.stop)

        stream.start(MoomooQuoteAccess("access-secret", 7200))
        stream.replace_symbols(("US.RXRX",))
        self.assertTrue(
            _wait_until(lambda: stream.snapshot().quotes != ()),
            stream.snapshot(),
        )
        sent_count = len(connection.sent)
        stream.replace_symbols(("US.RXRX",))
        time.sleep(0.02)

        self.assertEqual(len(connection.sent), sent_count)
        self.assertEqual(stream.snapshot().state, "connected")
        self.assertEqual(stream.snapshot().symbols, ("US.RXRX",))
        self.assertEqual(stream.snapshot().quotes[0].last_price, "3.07")
        self.assertEqual(
            json.loads(connection.sent[1]),
            {"action": "subscribe", "id": "subscribe-1", "quote": ["US.RXRX"]},
        )

        stream.stop()
        self.assertEqual(
            json.loads(connection.sent[-1]),
            {
                "action": "unsubscribe",
                "id": "unsubscribe-2",
                "quote": ["US.RXRX"],
            },
        )

    def test_stream_rejects_excess_symbols_without_starting_transport(self) -> None:
        connection_calls = 0

        def connector() -> FakeConnection:
            nonlocal connection_calls
            connection_calls += 1
            return FakeConnection([])

        stream = MoomooQuoteStream(
            access_supplier=lambda: MoomooQuoteAccess("unused", 7200),
            connector=connector,
            app_symbol_limit=2,
        )

        with self.assertRaisesRegex(MoomooQuoteProtocolError, "symbol limit"):
            stream.replace_symbols(("US.RXRX", "US.GANX", "US.SLS"))

        self.assertEqual(connection_calls, 0)

    def test_stream_stops_reconnecting_when_account_quota_rejects_subscription(
        self,
    ) -> None:
        connection_calls = 0

        def connector() -> FakeConnection:
            nonlocal connection_calls
            connection_calls += 1
            return FakeConnection(
                [
                    '{"id":"auth-1","session_id":"session-1"}',
                    '{"id":"subscribe-1","code":4,'
                    '"message":"sub quota exceeded, max=0"}',
                ]
            )

        stream = MoomooQuoteStream(
            access_supplier=lambda: MoomooQuoteAccess("unused", 7200),
            connector=connector,
        )
        self.addCleanup(stream.stop)

        stream.start(MoomooQuoteAccess("access-secret", 7200))
        stream.replace_symbols(("US.RXRX",))

        self.assertTrue(
            _wait_until(lambda: stream.snapshot().state == "quota_blocked"),
            stream.snapshot(),
        )
        stream.replace_symbols(("US.GANX",))
        time.sleep(0.02)
        self.assertEqual(connection_calls, 1)


def _wait_until(predicate: object, *, timeout: float = 1) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if callable(predicate) and predicate():
            return True
        time.sleep(0.005)
    return False


if __name__ == "__main__":
    unittest.main()

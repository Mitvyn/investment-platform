from __future__ import annotations

import json
import math
import threading
import time
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Callable, Mapping, Protocol

from workers.portfolio.quote_limits import (
    DEFAULT_APP_SYMBOL_LIMIT,
    MAX_WIRE_BATCH_SYMBOLS,
    MoomooQuoteLimitError,
    MoomooQuoteSubscriptionBook,
    bounded_retry_delay_seconds,
)


MAX_QUOTE_MESSAGE_BYTES = 1_048_576
QUOTE_PUSH_URL = "wss://webapi-quote.moomoo.com"
AUTH_RESPONSE_TIMEOUT_SECONDS = 2


class MoomooQuoteProtocolError(RuntimeError):
    """Raised when quote-push input violates the bounded wire contract."""


class MoomooQuoteSubscriptionRejected(MoomooQuoteProtocolError):
    """Raised when provider rejects a subscription that must not auto-retry."""

    def __init__(self, *, quota_exceeded: bool) -> None:
        self.quota_exceeded = quota_exceeded
        message = (
            "Moomoo quote subscription quota exceeded"
            if quota_exceeded
            else "Moomoo quote subscription rejected"
        )
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class MoomooQuoteAccess:
    access_token: str = field(repr=False)
    expires_in: int

    def __post_init__(self) -> None:
        if not self.access_token or self.access_token.strip() != self.access_token:
            raise ValueError("Moomoo quote access token is invalid")
        if self.expires_in <= 300:
            raise ValueError("Moomoo quote access lifetime is too short")


class MoomooQuoteConnection(Protocol):
    def send(self, message: str) -> None: ...

    def recv(self, *, timeout: float) -> str | bytes: ...


class MoomooQuoteConnectionContext(
    AbstractContextManager[MoomooQuoteConnection],
    Protocol,
):
    pass


@dataclass(frozen=True, slots=True)
class MoomooQuoteStreamSnapshot:
    state: str
    symbols: tuple[str, ...]
    quotes: tuple[MoomooLiveQuote, ...]
    error_code: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "error_code": self.error_code,
            "quotes": [quote.as_dict() for quote in self.quotes],
            "state": self.state,
            "symbols": list(self.symbols),
        }


@dataclass(frozen=True, slots=True)
class MoomooLiveQuote:
    symbol: str
    data_time_ms: int
    last_price: str | None
    open_price: str | None
    high_price: str | None
    low_price: str | None
    previous_close_price: str | None
    volume: str | None
    turnover: str | None
    suspension: bool | None
    security_status: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "data_time_ms": self.data_time_ms,
            "high_price": self.high_price,
            "last_price": self.last_price,
            "low_price": self.low_price,
            "open_price": self.open_price,
            "previous_close_price": self.previous_close_price,
            "security_status": self.security_status,
            "suspension": self.suspension,
            "symbol": self.symbol,
            "turnover": self.turnover,
            "volume": self.volume,
        }


class MoomooQuoteStream:
    """Owns one bounded quote-only WebSocket and local latest-value cache."""

    def __init__(
        self,
        *,
        access_supplier: Callable[[], MoomooQuoteAccess],
        connector: Callable[[], MoomooQuoteConnectionContext] | None = None,
        app_symbol_limit: int = DEFAULT_APP_SYMBOL_LIMIT,
        clock: Callable[[], float] = time.monotonic,
        stop_timeout_seconds: float = 3,
    ) -> None:
        if stop_timeout_seconds <= 0:
            raise ValueError("Moomoo quote stop timeout must be positive")
        self._access_supplier = access_supplier
        self._app_symbol_limit = app_symbol_limit
        self._clock = clock
        self._connector = connector or _connect_quote_socket
        self._stop_timeout_seconds = stop_timeout_seconds
        self._desired_symbols: tuple[str, ...] = ()
        self._error_code: str | None = None
        self._quotes: dict[str, MoomooLiveQuote] = {}
        self._state = "disconnected"
        self._lock = threading.Lock()
        self._changed = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._initial_access: MoomooQuoteAccess | None = None

    def start(self, initial_access: MoomooQuoteAccess) -> None:
        with self._lock:
            if self._thread is not None:
                raise MoomooQuoteProtocolError("Moomoo quote stream already started")
            self._initial_access = initial_access
            self._state = "connecting"
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run,
                daemon=True,
                name="iros-moomoo-quote-stream",
            )
            self._thread.start()

    def replace_symbols(self, symbols: tuple[str, ...]) -> None:
        try:
            validator = MoomooQuoteSubscriptionBook(
                app_symbol_limit=self._app_symbol_limit
            )
            validator.replace(symbols)
        except (MoomooQuoteLimitError, ValueError) as error:
            raise MoomooQuoteProtocolError(str(error)) from error
        with self._lock:
            self._desired_symbols = validator.symbols
            self._quotes = {
                symbol: quote
                for symbol, quote in self._quotes.items()
                if symbol in self._desired_symbols
            }
        self._changed.set()

    def snapshot(self) -> MoomooQuoteStreamSnapshot:
        with self._lock:
            symbols = self._desired_symbols
            return MoomooQuoteStreamSnapshot(
                state=self._state,
                symbols=symbols,
                quotes=tuple(
                    self._quotes[symbol] for symbol in symbols if symbol in self._quotes
                ),
                error_code=self._error_code,
            )

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
        if thread is None:
            return
        self._stop.set()
        self._changed.set()
        thread.join(timeout=self._stop_timeout_seconds)
        with self._lock:
            if thread.is_alive():
                self._state = "stopping"
                self._error_code = "moomoo_quote_stream_stop_timeout"
                raise MoomooQuoteProtocolError("Moomoo quote stream did not stop")
            self._thread = None
            self._initial_access = None
            self._state = "disconnected"

    def _run(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            try:
                access = self._take_access()
                self._run_connection(access)
                attempt = 0
            except MoomooQuoteSubscriptionRejected as error:
                state = "quota_blocked" if error.quota_exceeded else "blocked"
                code = (
                    "moomoo_quote_subscription_quota_exceeded"
                    if error.quota_exceeded
                    else "moomoo_quote_subscription_rejected"
                )
                self._set_state(state, code)
                self._stop.wait()
                break
            except (OSError, RuntimeError, TimeoutError, ValueError):
                if self._stop.is_set():
                    break
                self._set_state("reconnecting", "moomoo_quote_stream_unavailable")
                delay = bounded_retry_delay_seconds(attempt)
                attempt += 1
                self._stop.wait(delay)

    def _run_connection(self, access: MoomooQuoteAccess) -> None:
        subscription_book = MoomooQuoteSubscriptionBook(
            app_symbol_limit=self._app_symbol_limit
        )
        request_sequence = 0
        refresh_after = self._clock() + max(
            60,
            min(access.expires_in / 2, access.expires_in - 300),
        )
        with self._connector() as connection:
            connection.send(build_auth_frame(access.access_token))
            _validate_auth_response(
                connection.recv(timeout=AUTH_RESPONSE_TIMEOUT_SECONDS)
            )
            self._set_state("connected", None)
            while not self._stop.is_set() and self._clock() < refresh_after:
                with self._lock:
                    desired = self._desired_symbols
                mutation = subscription_book.replace(desired)
                for action, symbols in (
                    ("unsubscribe", mutation.unsubscribe),
                    ("subscribe", mutation.subscribe),
                ):
                    if not symbols:
                        continue
                    request_sequence += 1
                    connection.send(
                        build_subscription_frame(
                            action=action,
                            request_id=f"{action}-{request_sequence}",
                            symbols=symbols,
                        )
                    )
                self._changed.clear()
                try:
                    raw = connection.recv(timeout=0.5)
                except TimeoutError:
                    self._changed.wait(timeout=0.5)
                    continue
                quote = parse_quote_message(raw)
                if quote is not None:
                    with self._lock:
                        if quote.symbol in self._desired_symbols:
                            self._quotes[quote.symbol] = quote
            if self._stop.is_set() and subscription_book.symbols:
                request_sequence += 1
                connection.send(
                    build_subscription_frame(
                        action="unsubscribe",
                        request_id=f"unsubscribe-{request_sequence}",
                        symbols=subscription_book.symbols,
                    )
                )

    def _take_access(self) -> MoomooQuoteAccess:
        with self._lock:
            initial_access = self._initial_access
            self._initial_access = None
        if initial_access is not None:
            return initial_access
        return self._access_supplier()

    def _set_state(self, state: str, error_code: str | None) -> None:
        with self._lock:
            self._state = state
            self._error_code = error_code


def build_auth_frame(access_token: str) -> str:
    if not access_token or access_token.strip() != access_token:
        raise MoomooQuoteProtocolError("Moomoo quote access token is invalid")
    return _canonical_json(
        {
            "action": "auth",
            "data": {
                "auth_type": "oauth2",
                "authorization": f"Bearer {access_token}",
            },
        }
    )


def build_subscription_frame(
    *,
    action: str,
    request_id: str,
    symbols: tuple[str, ...],
) -> str:
    if action not in {"subscribe", "unsubscribe"}:
        raise MoomooQuoteProtocolError("Moomoo quote action is invalid")
    if not request_id or request_id.strip() != request_id:
        raise MoomooQuoteProtocolError("Moomoo quote request ID is invalid")
    if not 1 <= len(symbols) <= MAX_WIRE_BATCH_SYMBOLS:
        raise MoomooQuoteProtocolError("Moomoo quote subscription size is invalid")
    if tuple(sorted(set(symbols))) != symbols:
        raise MoomooQuoteProtocolError("Moomoo quote symbols are not canonical")
    return _canonical_json(
        {
            "action": action,
            "id": request_id,
            "quote": list(symbols),
        }
    )


def parse_quote_message(raw: str | bytes) -> MoomooLiveQuote | None:
    encoded_size = len(raw) if isinstance(raw, bytes) else len(raw.encode("utf-8"))
    if encoded_size > MAX_QUOTE_MESSAGE_BYTES:
        raise MoomooQuoteProtocolError("Moomoo quote message is too large")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MoomooQuoteProtocolError("Moomoo quote message is invalid") from error
    if not isinstance(payload, Mapping):
        raise MoomooQuoteProtocolError("Moomoo quote message is invalid")
    response_code = payload.get("code")
    if response_code is not None:
        if isinstance(response_code, bool) or not isinstance(response_code, int):
            raise MoomooQuoteProtocolError("Moomoo quote response code is invalid")
        if response_code != 0:
            raise MoomooQuoteSubscriptionRejected(quota_exceeded=response_code == 4)
        return None
    if payload.get("type") != "QUOTE":
        return None
    symbol = payload.get("symbol")
    data = payload.get("data")
    if not isinstance(symbol, str) or not isinstance(data, Mapping):
        raise MoomooQuoteProtocolError("Moomoo quote message is invalid")
    timestamp = data.get("data_time_ms")
    if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp <= 0:
        raise MoomooQuoteProtocolError("Moomoo quote timestamp is invalid")
    suspension = data.get("suspension")
    if suspension is not None and not isinstance(suspension, bool):
        raise MoomooQuoteProtocolError("Moomoo quote suspension state is invalid")
    status = data.get("sec_status")
    if status is not None and (not isinstance(status, str) or not status.strip()):
        raise MoomooQuoteProtocolError("Moomoo quote security status is invalid")
    return MoomooLiveQuote(
        symbol=symbol,
        data_time_ms=timestamp,
        last_price=_decimal_string(data.get("last_price")),
        open_price=_decimal_string(data.get("open_price")),
        high_price=_decimal_string(data.get("high_price")),
        low_price=_decimal_string(data.get("low_price")),
        previous_close_price=_decimal_string(data.get("prev_close_price")),
        volume=_decimal_string(data.get("volume")),
        turnover=_decimal_string(data.get("turnover")),
        suspension=suspension,
        security_status=status,
    )


def _validate_auth_response(raw: str | bytes) -> None:
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MoomooQuoteProtocolError("Moomoo quote authentication failed") from error
    if not isinstance(payload, Mapping):
        raise MoomooQuoteProtocolError("Moomoo quote authentication failed")
    code = payload.get("code")
    if code is not None and code != 0:
        raise MoomooQuoteProtocolError("Moomoo quote authentication failed")
    if not isinstance(payload.get("session_id"), str) or not payload["session_id"]:
        raise MoomooQuoteProtocolError("Moomoo quote authentication failed")


def _connect_quote_socket() -> MoomooQuoteConnectionContext:
    from websockets.sync.client import connect

    return connect(
        QUOTE_PUSH_URL,
        open_timeout=10,
        ping_interval=20,
        ping_timeout=20,
        close_timeout=5,
        max_size=MAX_QUOTE_MESSAGE_BYTES,
        max_queue=16,
    )


def _decimal_string(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise MoomooQuoteProtocolError("Moomoo quote numeric value is invalid")
    if isinstance(value, float) and not math.isfinite(value):
        raise MoomooQuoteProtocolError("Moomoo quote numeric value is invalid")
    try:
        decimal_value = Decimal(str(value))
    except InvalidOperation as error:
        raise MoomooQuoteProtocolError(
            "Moomoo quote numeric value is invalid"
        ) from error
    if not decimal_value.is_finite():
        raise MoomooQuoteProtocolError("Moomoo quote numeric value is invalid")
    return format(decimal_value, "f")


def _canonical_json(value: Mapping[str, object]) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)

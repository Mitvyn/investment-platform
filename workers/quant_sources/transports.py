"""Provider-neutral historical transport contract, retries, and rate limits.

A transport is the only part of the acquisition path that talks to a provider.
Everything above it works on :class:`HistoryPayload`, a decimal-only,
already-retrieved daily history that names its own source revision. Nothing in
``investment_research_os.quant`` or ``investment_research_os.quant_sources``
imports this module; the dependency runs one way, which is what keeps Quant
core provider-neutral.

Numeric values cross this boundary as decimal text or whole integers, never as
binary floats. A float price makes fills irreproducible, and a provider that
sends one is refused here rather than deeper in, where the error would name an
anonymous bar instead of the offending source row.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Callable, Protocol, TypeVar

T = TypeVar("T")


class TransportError(RuntimeError):
    """Raised when a provider transport cannot produce usable history."""


class TransientTransportError(TransportError):
    """A failure worth retrying once, within the bounded attempt budget."""


class TransportBlockedError(TransportError):
    """A transport that is deliberately not implemented, with a stated reason.

    This is never retried. A blocked transport is a documentation gap, not a
    network condition, and retrying it would only turn a clear blocker into a
    slow one.
    """


#: Revision strings that name a moving target rather than a fixed snapshot.
#: Mirrors the Quant adapter rule so a payload cannot reach the receipt
#: boundary carrying one and fail there instead of here.
_MOVING_REVISIONS = frozenset(
    {"latest", "current", "head", "newest", "now", "live", "today"}
)


def _decimal_text(value: object, *, field: str) -> str:
    """One numeric field, as decimal text, with floats refused outright."""

    if isinstance(value, float):
        raise TransportError(
            f"{field} is a float; binary floats make fills irreproducible, so a "
            "transport must emit decimal text"
        )
    if isinstance(value, bool):
        raise TransportError(f"{field} must be a decimal, not a boolean")
    if not isinstance(value, (str, int, Decimal)):
        raise TransportError(
            f"{field} must be decimal text, got {type(value).__name__}"
        )
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as error:
        raise TransportError(f"{field} must be a decimal, got {value!r}") from error
    if not parsed.is_finite() or parsed < 0:
        raise TransportError(f"{field} must be finite and non-negative")
    return str(parsed)


def _session_text(value: object, *, field: str) -> str:
    if isinstance(value, date) and type(value) is date:
        return value.isoformat()
    if not isinstance(value, str):
        raise TransportError(
            f"{field} must be an ISO date string or a date, got "
            f"{type(value).__name__}"
        )
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise TransportError(f"{field} is not an ISO date: {value!r}") from error
    return parsed.isoformat()


@dataclass(frozen=True, slots=True)
class HistoryBar:
    """One unadjusted daily session, as the transport received it."""

    session: str
    open: str
    high: str
    low: str
    close: str
    volume: int
    stock_split: str = "0"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "session", _session_text(self.session, field="session")
        )
        for field in ("open", "high", "low", "close", "stock_split"):
            object.__setattr__(
                self,
                field,
                _decimal_text(getattr(self, field), field=field),
            )
        if isinstance(self.volume, bool) or not isinstance(self.volume, int):
            raise TransportError(
                f"volume must be a whole number of shares, got "
                f"{type(self.volume).__name__}"
            )
        if self.volume < 0:
            raise TransportError("volume must not be negative")

    @property
    def session_date(self) -> date:
        return date.fromisoformat(self.session)


@dataclass(frozen=True, slots=True)
class HistoryPayload:
    """One provider's daily history for one symbol at one named revision."""

    provider_id: str
    symbol: str
    currency: str
    source_revision: str
    bars: tuple[HistoryBar, ...]

    def __post_init__(self) -> None:
        for field in ("provider_id", "symbol", "source_revision"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise TransportError(f"{field} must be a non-empty string")
        if self.source_revision.strip().lower() in _MOVING_REVISIONS:
            raise TransportError(
                f"source_revision {self.source_revision!r} names a moving "
                "target, not a revision; an implicit latest selection cannot "
                "be reproduced"
            )
        currency = self.currency
        if (
            not isinstance(currency, str)
            or len(currency) != 3
            or not currency.isalpha()
            or not currency.isupper()
        ):
            raise TransportError(
                "currency must be an upper-case three-letter ISO 4217 code, "
                "stated explicitly; there is no default"
            )
        bars = tuple(self.bars)
        for index, bar in enumerate(bars):
            if not isinstance(bar, HistoryBar):
                raise TransportError(
                    f"bar {index} must be a HistoryBar, got {type(bar).__name__}"
                )
        object.__setattr__(self, "bars", bars)


class HistoricalTransport(Protocol):
    """A source of unadjusted daily history for one symbol and one window."""

    provider_id: str

    def fetch_daily_history(
        self, ticker: str, *, start: date, end: date
    ) -> HistoryPayload: ...


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """A bounded attempt budget with capped exponential backoff."""

    max_attempts: int = 3
    backoff_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    max_backoff_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.backoff_seconds < 0:
            raise ValueError("backoff_seconds must not be negative")
        if self.backoff_multiplier < 1:
            raise ValueError("backoff_multiplier must be at least 1")
        if self.max_backoff_seconds < self.backoff_seconds:
            raise ValueError("max_backoff_seconds must not be below backoff_seconds")

    def delay_for(self, attempt: int) -> float:
        """Backoff before attempt ``attempt`` + 1, counting attempts from 1."""

        delay = self.backoff_seconds * (self.backoff_multiplier ** (attempt - 1))
        return min(delay, self.max_backoff_seconds)


@dataclass(frozen=True, slots=True)
class RateLimit:
    """At most ``max_calls`` provider calls in any ``per_seconds`` window."""

    max_calls: int
    per_seconds: float

    def __post_init__(self) -> None:
        if self.max_calls < 1:
            raise ValueError("max_calls must be at least 1")
        if self.per_seconds <= 0:
            raise ValueError("per_seconds must be positive")


class BoundedCaller:
    """Rate-limited, bounded-retry wrapper around one provider call.

    The clock and the sleep function are injected so the policy is testable
    without waiting. Only :class:`TransientTransportError` is retried; a
    permanent error or a blocked transport surfaces on the first attempt,
    because retrying a contract failure only delays the same answer.

    Attempts are counted against the rate limit whether they succeed or fail.
    A provider that rejected a call still received it, and a retry storm is
    exactly the case the limit exists to bound.
    """

    def __init__(
        self,
        *,
        policy: RetryPolicy,
        rate_limit: RateLimit,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._policy = policy
        self._rate_limit = rate_limit
        self._sleep = sleep
        self._monotonic = monotonic
        self._calls: deque[float] = deque()

    def call(self, operation: Callable[[], T]) -> T:
        last: TransientTransportError | None = None
        for attempt in range(1, self._policy.max_attempts + 1):
            self._await_slot()
            try:
                return operation()
            except TransientTransportError as error:
                last = error
                if attempt == self._policy.max_attempts:
                    break
                self._sleep(self._policy.delay_for(attempt))
        raise TransportError(
            f"provider call failed after {self._policy.max_attempts} attempts: "
            f"{last}"
        ) from last

    def _await_slot(self) -> None:
        window = self._rate_limit.per_seconds
        now = self._monotonic()
        while self._calls and now - self._calls[0] >= window:
            self._calls.popleft()
        if len(self._calls) >= self._rate_limit.max_calls:
            wait = window - (now - self._calls[0])
            if wait > 0:
                self._sleep(wait)
            now = self._monotonic()
            while self._calls and now - self._calls[0] >= window:
                self._calls.popleft()
        self._calls.append(self._monotonic())


__all__ = [
    "BoundedCaller",
    "HistoricalTransport",
    "HistoryBar",
    "HistoryPayload",
    "RateLimit",
    "RetryPolicy",
    "TransientTransportError",
    "TransportBlockedError",
    "TransportError",
]

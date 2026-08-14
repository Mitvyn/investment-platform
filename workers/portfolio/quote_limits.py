from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable


MAX_WIRE_BATCH_SYMBOLS = 400
DEFAULT_APP_SYMBOL_LIMIT = 25
MAX_RETRY_DELAY_SECONDS = 60
_SYMBOL_PATTERN = re.compile(r"^[A-Z]{2,3}\.[A-Z0-9][A-Z0-9.\-]{0,31}$")


class MoomooQuoteLimitError(ValueError):
    """Raised before transport when a quote request exceeds local bounds."""


@dataclass(frozen=True, slots=True)
class MoomooQuoteSubscriptionMutation:
    subscribe: tuple[str, ...]
    unsubscribe: tuple[str, ...]


class MoomooQuoteSubscriptionBook:
    """Tracks exact subscription intent and emits provider-minimal mutations."""

    def __init__(self, *, app_symbol_limit: int = DEFAULT_APP_SYMBOL_LIMIT) -> None:
        if not 1 <= app_symbol_limit <= MAX_WIRE_BATCH_SYMBOLS:
            raise ValueError("Moomoo app symbol limit is invalid")
        self._app_symbol_limit = app_symbol_limit
        self._symbols: tuple[str, ...] = ()

    @property
    def symbols(self) -> tuple[str, ...]:
        return self._symbols

    def replace(self, symbols: Iterable[str]) -> MoomooQuoteSubscriptionMutation:
        normalized = tuple(sorted({_normalize_symbol(symbol) for symbol in symbols}))
        if len(normalized) > self._app_symbol_limit:
            raise MoomooQuoteLimitError("Moomoo app symbol limit exceeded")
        previous = set(self._symbols)
        desired = set(normalized)
        mutation = MoomooQuoteSubscriptionMutation(
            subscribe=tuple(sorted(desired - previous)),
            unsubscribe=tuple(sorted(previous - desired)),
        )
        self._symbols = normalized
        return mutation


def bounded_retry_delay_seconds(
    attempt: int,
    *,
    retry_after_seconds: float | None = None,
) -> float:
    if attempt < 0:
        raise ValueError("Moomoo retry attempt is invalid")
    if retry_after_seconds is not None:
        if not math.isfinite(retry_after_seconds) or retry_after_seconds < 0:
            raise ValueError("Moomoo Retry-After is invalid")
        return min(retry_after_seconds, MAX_RETRY_DELAY_SECONDS)
    return min(2**attempt, MAX_RETRY_DELAY_SECONDS)


def _normalize_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if not _SYMBOL_PATTERN.fullmatch(normalized):
        raise MoomooQuoteLimitError("Moomoo quote symbol is invalid")
    return normalized

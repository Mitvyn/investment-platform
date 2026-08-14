from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Literal, Protocol, Sequence


MOOMOO_US_SYMBOL_PATTERN = re.compile(r"^US\.([A-Z][A-Z0-9.-]{0,9})$")


class CanonicalSecurityCandidate(Protocol):
    security_id: str
    ticker: str
    primary_listing_exchange: str


class MoomooSymbolReconciliationError(ValueError):
    """Raised when a provider symbol cannot bind to one canonical security."""


@dataclass(frozen=True, slots=True)
class MoomooSymbolReconciliationResult:
    mapping_state: Literal["mapped", "unmapped", "ambiguous"]
    provider_market: str
    provider_symbol: str
    canonical_ticker: str
    security_id: str | None
    primary_listing_exchange: str | None


def reconcile_moomoo_symbol(
    provider_symbol: str,
    *,
    candidates: Sequence[CanonicalSecurityCandidate],
) -> MoomooSymbolReconciliationResult:
    normalized = provider_symbol.strip().upper()
    match = MOOMOO_US_SYMBOL_PATTERN.fullmatch(normalized)
    if match is None:
        raise MoomooSymbolReconciliationError("unsupported Moomoo symbol")
    ticker = match.group(1)
    matches = tuple(
        candidate
        for candidate in candidates
        if candidate.ticker.strip().upper() == ticker
    )
    if not matches:
        return MoomooSymbolReconciliationResult(
            mapping_state="unmapped",
            provider_market="US",
            provider_symbol=normalized,
            canonical_ticker=ticker,
            security_id=None,
            primary_listing_exchange=None,
        )
    if len(matches) > 1:
        return MoomooSymbolReconciliationResult(
            mapping_state="ambiguous",
            provider_market="US",
            provider_symbol=normalized,
            canonical_ticker=ticker,
            security_id=None,
            primary_listing_exchange=None,
        )
    candidate = matches[0]
    try:
        uuid.UUID(candidate.security_id)
    except (AttributeError, TypeError, ValueError) as error:
        raise MoomooSymbolReconciliationError(
            "canonical security ID is invalid"
        ) from error
    exchange = candidate.primary_listing_exchange.strip()
    if not exchange:
        raise MoomooSymbolReconciliationError(
            "canonical listing exchange is unavailable"
        )
    return MoomooSymbolReconciliationResult(
        mapping_state="mapped",
        provider_market="US",
        provider_symbol=normalized,
        canonical_ticker=ticker,
        security_id=candidate.security_id,
        primary_listing_exchange=exchange,
    )

"""Typed, fail-closed normalization of one MCP read-only market-quote tool result.

Moomoo's MCP `tools/call` response shape is protocol-guaranteed
(`isError` / `structuredContent` / `content`), but this module does not
assert knowledge of the provider's exact quote field semantics beyond what
its own request bound (the requested ticker). It never labels a value as an
official close, valuation, or trading signal — it only carries a bounded,
sanitized preview of whatever scalar fields the provider returned, alongside
explicit freshness and failure state.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Mapping

MARKET_QUOTE_TOOL_NAME = "quote_stock_quote"
TICKER_PATTERN = re.compile(r"^[A-Z]{2,3}\.[A-Z0-9][A-Z0-9.\-]{0,31}$")
MAX_SUMMARY_FIELDS = 10
MAX_SUMMARY_FIELD_LENGTH = 200
STALE_AFTER_SECONDS = 15 * 60
REQUIRED_ANY_PRICE_FIELDS = ("last_price", "price", "cur_price", "close_price")

# Known-safe top-level `structuredContent` fields for one quote read. Sourced
# from this codebase's already-verified Moomoo quote vocabulary
# (`workers/portfolio/quote_stream.py`'s typed push-quote fields) plus the
# request-bound ticker/timestamp fields this module itself understands. Any
# other top-level key is treated as schema drift and rejected rather than
# silently passed through.
ALLOWED_STRUCTURED_FIELDS = frozenset(
    {
        "code",
        "symbol",
        "time",
        "timestamp",
        "data_time_ms",
        "last_price",
        "price",
        "cur_price",
        "close_price",
        "open_price",
        "high_price",
        "low_price",
        "previous_close_price",
        "volume",
        "turnover",
        "suspension",
        "security_status",
    }
)


class MarketEvidenceError(ValueError):
    """Raised when a market-evidence tool result cannot be trusted."""


@dataclass(frozen=True, slots=True)
class MarketQuoteEvidence:
    ticker: str
    security_id: str
    tool_name: str
    source: str
    retrieved_at: datetime
    provider_reported_at: datetime | None
    freshness: str
    is_error: bool
    failure_reason: str | None
    summary: Mapping[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "failure_reason": self.failure_reason,
            "freshness": self.freshness,
            "is_error": self.is_error,
            "provider_reported_at": (
                self.provider_reported_at.isoformat()
                if self.provider_reported_at is not None
                else None
            ),
            "retrieved_at": self.retrieved_at.isoformat(),
            "security_id": self.security_id,
            "source": self.source,
            "summary": dict(self.summary),
            "ticker": self.ticker,
            "tool_name": self.tool_name,
        }


def build_market_quote_evidence(
    raw_result: object,
    *,
    ticker: str,
    security_id: str,
    retrieved_at: datetime,
) -> MarketQuoteEvidence:
    if not isinstance(ticker, str) or not TICKER_PATTERN.match(ticker):
        raise MarketEvidenceError("market evidence ticker is invalid")
    if not isinstance(security_id, str) or not security_id.strip():
        raise MarketEvidenceError("market evidence security id is invalid")
    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise MarketEvidenceError("market evidence retrieval time must be timezone-aware")
    if not isinstance(raw_result, Mapping):
        raise MarketEvidenceError("market evidence tool result is invalid")

    is_error = raw_result.get("isError", False)
    if not isinstance(is_error, bool):
        raise MarketEvidenceError("market evidence tool result isError flag is invalid")
    if is_error:
        return MarketQuoteEvidence(
            ticker=ticker,
            security_id=security_id,
            tool_name=MARKET_QUOTE_TOOL_NAME,
            source="moomoo_mcp",
            retrieved_at=retrieved_at,
            provider_reported_at=None,
            freshness="unknown",
            is_error=True,
            failure_reason="provider_reported_error",
            summary={},
        )

    structured = raw_result.get("structuredContent")
    if not isinstance(structured, Mapping) or not structured:
        raise MarketEvidenceError("market evidence structured content is invalid")
    unknown_fields = set(structured) - ALLOWED_STRUCTURED_FIELDS
    if unknown_fields:
        raise MarketEvidenceError(
            "market evidence tool result contains unrecognized fields "
            "(possible schema drift)"
        )

    reported_code = structured.get("code")
    if isinstance(reported_code, str) and reported_code.strip() != ticker:
        raise MarketEvidenceError(
            "market evidence tool result ticker does not match requested ticker"
        )
    _reject_non_finite_numeric_fields(structured)

    provider_reported_at = _extract_provider_time(structured)
    if provider_reported_at is None:
        raise MarketEvidenceError(
            "market evidence tool result is missing a provider timestamp"
        )
    _require_finite_positive_price(structured)

    summary = _sanitize_summary(structured)
    freshness = _classify_freshness(provider_reported_at, retrieved_at)

    return MarketQuoteEvidence(
        ticker=ticker,
        security_id=security_id,
        tool_name=MARKET_QUOTE_TOOL_NAME,
        source="moomoo_mcp",
        retrieved_at=retrieved_at,
        provider_reported_at=provider_reported_at,
        freshness=freshness,
        is_error=False,
        failure_reason=None,
        summary=summary,
    )


def _sanitize_summary(structured: Mapping[str, object]) -> dict[str, str]:
    summary: dict[str, str] = {}
    for key in sorted(structured)[:MAX_SUMMARY_FIELDS]:
        value = structured[key]
        if isinstance(value, (str, int, float, bool)) and not isinstance(value, Mapping):
            text = str(value)
            summary[key] = text[:MAX_SUMMARY_FIELD_LENGTH]
    return summary


def _reject_non_finite_numeric_fields(structured: Mapping[str, object]) -> None:
    for value in structured.values():
        if isinstance(value, bool):
            continue
        if isinstance(value, float) and not math.isfinite(value):
            raise MarketEvidenceError("market evidence tool result contains a non-finite value")


def _require_finite_positive_price(structured: Mapping[str, object]) -> None:
    for key in REQUIRED_ANY_PRICE_FIELDS:
        if key not in structured:
            continue
        value = structured[key]
        if isinstance(value, bool):
            raise MarketEvidenceError("market evidence price field is invalid")
        try:
            price = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise MarketEvidenceError("market evidence price field is invalid") from None
        if not price.is_finite() or price <= 0:
            raise MarketEvidenceError("market evidence price field is invalid")
        return
    raise MarketEvidenceError("market evidence tool result is missing a price field")


def _extract_provider_time(structured: Mapping[str, object]) -> datetime | None:
    for key in ("time", "timestamp"):
        value = structured.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and value > 0:
            seconds = value / 1000 if value > 10_000_000_000 else value
            try:
                return datetime.fromtimestamp(seconds, tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                return None
    return None


def classify_freshness(
    provider_reported_at: datetime | None, retrieved_at: datetime
) -> str:
    """Classify freshness of a provider timestamp as of `retrieved_at`.

    Exposed publicly so a cache reader can re-classify a stored evidence
    record against the *current* clock, rather than trusting the freshness
    label computed at fetch time forever.
    """
    return _classify_freshness(provider_reported_at, retrieved_at)


def _classify_freshness(
    provider_reported_at: datetime | None, retrieved_at: datetime
) -> str:
    if provider_reported_at is None:
        return "unknown"
    age_seconds = (retrieved_at - provider_reported_at).total_seconds()
    if age_seconds < 0 or age_seconds > STALE_AFTER_SECONDS:
        return "stale"
    return "fresh"


__all__ = [
    "MARKET_QUOTE_TOOL_NAME",
    "MarketEvidenceError",
    "MarketQuoteEvidence",
    "build_market_quote_evidence",
    "classify_freshness",
]

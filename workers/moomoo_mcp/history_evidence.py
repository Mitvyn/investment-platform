"""Fail-closed daily K-line evidence from Moomoo MCP's published contract."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Mapping

from workers.moomoo_mcp.market_evidence import TICKER_PATTERN
from workers.moomoo_mcp.envelope import unwrap_expected_mapping

HISTORY_TOOL_NAME = "quote_history_kline"
MAX_HISTORY_BARS = 370
ALLOWED_BAR_FIELDS = frozenset(
    {
        "changeRate",
        "close",
        "date",
        "high",
        "impliedVolatility",
        "lastClose",
        "low",
        "name",
        "open",
        "openInterest",
        "peRatio",
        "settlePrice",
        "timeKey",
        "timeZone",
        "turnover",
        "turnoverRate",
        "volume",
    }
)
REST_BAR_FIELD_MAP = {
    "change_rate": "changeRate",
    "close": "close",
    "date": "date",
    "high": "high",
    "implied_volatility": "impliedVolatility",
    "last_close": "lastClose",
    "low": "low",
    "name": "name",
    "open": "open",
    "open_interest": "openInterest",
    "pe_ratio": "peRatio",
    "settle_price": "settlePrice",
    "time_key": "timeKey",
    "time_zone": "timeZone",
    "turnover": "turnover",
    "turnover_rate": "turnoverRate",
    "volume": "volume",
}
REQUIRED_PRICE_FIELDS = ("open", "high", "low", "close")


class HistoryEvidenceError(ValueError):
    def __init__(self, message: str, *, code: str = "history_invalid") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class MarketHistoryEvidence:
    ticker: str
    security_id: str
    tool_name: str
    source: str
    retrieved_at: datetime
    bars: tuple[Mapping[str, str], ...]

    @property
    def bar_count(self) -> int:
        return len(self.bars)

    def as_dict(self) -> dict[str, object]:
        return {
            "bar_count": self.bar_count,
            "bars": [dict(bar) for bar in self.bars],
            "retrieved_at": self.retrieved_at.isoformat(),
            "security_id": self.security_id,
            "source": self.source,
            "ticker": self.ticker,
            "tool_name": self.tool_name,
        }


def build_daily_history_arguments(
    *, ticker: str, start: date, end: date, max_bars: int
) -> dict[str, object]:
    if not isinstance(ticker, str) or not TICKER_PATTERN.fullmatch(ticker):
        raise HistoryEvidenceError("history ticker is invalid")
    if not isinstance(start, date) or not isinstance(end, date) or start > end:
        raise HistoryEvidenceError("history date range is invalid")
    if isinstance(max_bars, bool) or not 1 <= max_bars <= MAX_HISTORY_BARS:
        raise HistoryEvidenceError("history bar limit is invalid")
    return {
        "autype": 1,
        "end": end.isoformat(),
        "extended_time": 0,
        "ktype": 2,
        "num": max_bars,
        "start": start.isoformat(),
        "symbol": ticker,
    }


def build_market_history_evidence(
    raw_result: object,
    *,
    ticker: str,
    security_id: str,
    retrieved_at: datetime,
) -> MarketHistoryEvidence:
    if not TICKER_PATTERN.fullmatch(ticker):
        raise HistoryEvidenceError("history ticker is invalid")
    if not security_id.strip():
        raise HistoryEvidenceError("history security id is invalid")
    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise HistoryEvidenceError("history retrieval time must be timezone-aware")
    if not isinstance(raw_result, Mapping) or raw_result.get("isError", False) is not False:
        raise HistoryEvidenceError("history tool result is invalid", code="history_result_invalid")
    structured = unwrap_expected_mapping(
        raw_result.get("structuredContent"), "kline_list"
    )
    if structured is None:
        raise HistoryEvidenceError("history structured content is invalid", code="history_envelope_invalid")
    rows = structured["kline_list"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_HISTORY_BARS:
        raise HistoryEvidenceError("history bar list is invalid", code="history_list_invalid")
    bars = tuple(_normalize_bar(row) for row in rows)
    return MarketHistoryEvidence(
        ticker=ticker,
        security_id=security_id,
        tool_name=HISTORY_TOOL_NAME,
        source="moomoo_mcp",
        retrieved_at=retrieved_at,
        bars=bars,
    )


def _normalize_bar(raw: object) -> Mapping[str, str]:
    if not isinstance(raw, Mapping):
        raise HistoryEvidenceError("history bar schema drift detected", code="history_bar_schema_invalid")
    fields = set(raw)
    if fields <= set(REST_BAR_FIELD_MAP):
        raw = {REST_BAR_FIELD_MAP[key]: value for key, value in raw.items()}
    elif fields - ALLOWED_BAR_FIELDS:
        raise HistoryEvidenceError("history bar schema drift detected", code="history_bar_schema_invalid")
    if not {"timeKey", *REQUIRED_PRICE_FIELDS}.issubset(raw):
        raise HistoryEvidenceError("history bar required field is missing", code="history_bar_required_missing")
    for field_name in REQUIRED_PRICE_FIELDS:
        _finite_decimal(raw[field_name], positive=True)
    for value in raw.values():
        if isinstance(value, float) and not math.isfinite(value):
            raise HistoryEvidenceError("history bar contains non-finite value")
    return {
        key: str(value)[:200]
        for key, value in sorted(raw.items())
        if isinstance(value, (str, int, float)) and not isinstance(value, bool)
    }


def _finite_decimal(value: object, *, positive: bool) -> Decimal:
    if isinstance(value, bool):
        raise HistoryEvidenceError("history price is invalid")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise HistoryEvidenceError("history price is invalid") from None
    if not parsed.is_finite() or (positive and parsed <= 0):
        raise HistoryEvidenceError("history price is invalid")
    return parsed


__all__ = [
    "HISTORY_TOOL_NAME",
    "HistoryEvidenceError",
    "MarketHistoryEvidence",
    "build_daily_history_arguments",
    "build_market_history_evidence",
]

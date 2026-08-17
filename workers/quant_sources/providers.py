from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Protocol

from investment_research_os.quant import PointInTimeDataset, QuantContractError
from investment_research_os.quant_sources import (
    SourceSnapshot,
    acquire_point_in_time_dataset,
    payload_sha256,
)
from workers.market.client import (
    YFinanceBar,
    YFinanceProvider,
    YFinanceQuote,
    YFinanceSettings,
)


YFINANCE_SOURCE_ID = "yahoo_finance_via_yfinance"
MOOMOO_SOURCE_ID = "moomoo_openapi"


class QuantSourceProviderError(RuntimeError):
    """Raised when provider data cannot become a Quant receipt."""


class MoomooHistoryProvider(Protocol):
    def fetch_daily_history(
        self, ticker: str, *, as_of_cutoff: date
    ) -> "MoomooHistoryPayload": ...


@dataclass(frozen=True, slots=True)
class MoomooHistoryBar:
    session: str | date
    open: str | int | Decimal
    high: str | int | Decimal
    low: str | int | Decimal
    close: str | int | Decimal
    volume: int
    stock_split: str | int | Decimal = "0"


@dataclass(frozen=True, slots=True)
class MoomooHistoryPayload:
    symbol: str
    source_revision: str
    currency: str
    bars: tuple[MoomooHistoryBar, ...]


class YFinanceQuantSource:
    """Convert existing yfinance history into a Quant point-in-time receipt.

    The provider is injected. This class performs no network call itself.
    """

    def __init__(
        self,
        settings: YFinanceSettings,
        *,
        provider: YFinanceProvider,
    ) -> None:
        self.settings = settings
        self.provider = provider

    def acquire(
        self,
        *,
        ticker: str,
        security_id: str,
        as_of_cutoff: date,
        currency: str,
    ) -> PointInTimeDataset:
        normalized_ticker = ticker.strip().upper()
        if not normalized_ticker:
            raise QuantSourceProviderError("yfinance ticker is required")
        quote = self.provider.fetch_quote(
            normalized_ticker,
            settings=self.settings,
        )
        if quote.symbol.strip().upper() != normalized_ticker:
            raise QuantSourceProviderError("yfinance returned a different symbol")
        if quote.currency.upper() != currency:
            raise QuantSourceProviderError(
                "yfinance currency does not match the requested currency"
            )
        if not quote.bars:
            raise QuantSourceProviderError("yfinance returned no daily bars")
        bar_rows, split_rows = _yfinance_rows(quote.bars)
        revision = _yfinance_revision(quote, self.settings)
        snapshot = _make_snapshot(
            source_id=YFINANCE_SOURCE_ID,
            source_revision=revision,
            bar_rows=bar_rows,
            split_rows=split_rows,
        )
        try:
            return acquire_point_in_time_dataset(
                security_id=security_id,
                as_of_cutoff=as_of_cutoff,
                currency=currency,
                snapshot=snapshot,
            )
        except QuantContractError as error:
            raise QuantSourceProviderError(
                f"yfinance history cannot form a Quant receipt: {error}"
            ) from error


class MoomooQuantSource:
    """Convert an injected Moomoo daily-history payload into a Quant receipt.

    Moomoo's historical-bar transport remains separate. This adapter owns only
    mapping and contract enforcement; it does not guess an OpenAPI endpoint.
    """

    def __init__(self, provider: MoomooHistoryProvider) -> None:
        self.provider = provider

    def acquire(
        self,
        *,
        ticker: str,
        security_id: str,
        as_of_cutoff: date,
        currency: str,
    ) -> PointInTimeDataset:
        normalized_ticker = ticker.strip().upper()
        if not normalized_ticker:
            raise QuantSourceProviderError("Moomoo ticker is required")
        payload = self.provider.fetch_daily_history(
            normalized_ticker,
            as_of_cutoff=as_of_cutoff,
        )
        if not isinstance(payload, MoomooHistoryPayload):
            raise QuantSourceProviderError("Moomoo history payload is invalid")
        if payload.symbol.strip().upper() != normalized_ticker:
            raise QuantSourceProviderError("Moomoo returned a different symbol")
        if payload.currency.upper() != currency:
            raise QuantSourceProviderError(
                "Moomoo currency does not match the requested currency"
            )
        if not payload.bars:
            raise QuantSourceProviderError("Moomoo returned no daily bars")
        bar_rows, split_rows = _moomoo_rows(payload.bars)
        snapshot = _make_snapshot(
            source_id=MOOMOO_SOURCE_ID,
            source_revision=payload.source_revision,
            bar_rows=bar_rows,
            split_rows=split_rows,
        )
        try:
            return acquire_point_in_time_dataset(
                security_id=security_id,
                as_of_cutoff=as_of_cutoff,
                currency=currency,
                snapshot=snapshot,
            )
        except QuantContractError as error:
            raise QuantSourceProviderError(
                f"Moomoo history cannot form a Quant receipt: {error}"
            ) from error


def _yfinance_rows(
    bars: tuple[YFinanceBar, ...],
) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    rows: list[dict[str, object]] = []
    splits: list[dict[str, object]] = []
    for index, bar in enumerate(bars):
        if bar.volume is None:
            raise QuantSourceProviderError(
                f"yfinance bar {index} has no volume; Quant requires volume"
            )
        rows.append(
            {
                "session": bar.session_date,
                "open": _decimal_text(bar.open, field=f"yfinance bar {index} open"),
                "high": _decimal_text(bar.high, field=f"yfinance bar {index} high"),
                "low": _decimal_text(bar.low, field=f"yfinance bar {index} low"),
                "close": _decimal_text(bar.close, field=f"yfinance bar {index} close"),
                "volume": bar.volume,
            }
        )
        ratio = _decimal_value(
            bar.stock_splits,
            field=f"yfinance bar {index} stock_splits",
        )
        if ratio == 0:
            continue
        new_shares, old_shares = ratio.as_integer_ratio()
        splits.append(
            {
                "effective_session": bar.session_date,
                "new_shares": new_shares,
                "old_shares": old_shares,
            }
        )
    return tuple(rows), tuple(splits)


def _make_snapshot(
    *,
    source_id: str,
    source_revision: str,
    bar_rows: tuple[dict[str, object], ...],
    split_rows: tuple[dict[str, object], ...],
) -> SourceSnapshot:
    try:
        return SourceSnapshot(
            source_id=source_id,
            source_revision=source_revision,
            content_sha256=payload_sha256(
                bar_rows=bar_rows,
                split_rows=split_rows,
            ),
            bar_rows=bar_rows,
            split_rows=split_rows,
        )
    except QuantContractError as error:
        raise QuantSourceProviderError(
            f"provider provenance cannot form a Quant snapshot: {error}"
        ) from error


def _moomoo_rows(
    bars: tuple[MoomooHistoryBar, ...],
) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    rows: list[dict[str, object]] = []
    splits: list[dict[str, object]] = []
    for index, bar in enumerate(bars):
        rows.append(
            {
                "session": bar.session,
                "open": _decimal_text(bar.open, field=f"Moomoo bar {index} open"),
                "high": _decimal_text(bar.high, field=f"Moomoo bar {index} high"),
                "low": _decimal_text(bar.low, field=f"Moomoo bar {index} low"),
                "close": _decimal_text(bar.close, field=f"Moomoo bar {index} close"),
                "volume": bar.volume,
            }
        )
        ratio = _decimal_value(
            bar.stock_split,
            field=f"Moomoo bar {index} stock_split",
        )
        if ratio == 0:
            continue
        new_shares, old_shares = ratio.as_integer_ratio()
        splits.append(
            {
                "effective_session": bar.session,
                "new_shares": new_shares,
                "old_shares": old_shares,
            }
        )
    return tuple(rows), tuple(splits)


def _decimal_value(value: object, *, field: str) -> Decimal:
    if isinstance(value, bool):
        raise QuantSourceProviderError(f"{field} must be numeric")
    try:
        candidate = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise QuantSourceProviderError(f"{field} must be numeric") from error
    if not candidate.is_finite() or candidate < 0:
        raise QuantSourceProviderError(f"{field} must be finite and non-negative")
    return candidate


def _decimal_text(value: object, *, field: str) -> str:
    return str(_decimal_value(value, field=field))


def _yfinance_revision(quote: YFinanceQuote, settings: YFinanceSettings) -> str:
    try:
        body = json.dumps(
            quote.canonical_payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise QuantSourceProviderError(
            "yfinance canonical payload is not deterministic"
        ) from error
    payload_hash = hashlib.sha256(body).hexdigest()
    return f"yfinance-{settings.library_version}-{quote.market_timestamp}-{payload_hash}"


__all__ = [
    "MoomooHistoryBar",
    "MoomooHistoryPayload",
    "MoomooHistoryProvider",
    "MoomooQuantSource",
    "QuantSourceProviderError",
    "YFinanceQuantSource",
]

from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Mapping, Protocol

from workers.ids import stable_id

from .models import MarketBar, MarketSnapshot


class MarketDataError(RuntimeError):
    """Raised when personal-use market data is unavailable or invalid."""


@dataclass(frozen=True, slots=True)
class YFinanceSettings:
    library_version: str = "1.5.1"
    period: str = "1y"
    interval: str = "1d"
    auto_adjust: bool = False
    back_adjust: bool = False
    prepost: bool = False
    actions: bool = True
    repair: bool = False
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if self.interval != "1d":
            raise ValueError("yfinance market context requires daily bars")
        if self.auto_adjust or self.back_adjust:
            raise ValueError("yfinance adjusted prices are not permitted")
        if self.prepost:
            raise ValueError("yfinance extended-hours prices are not permitted")
        if not self.actions:
            raise ValueError("yfinance corporate actions must be requested")
        if self.repair:
            raise ValueError("yfinance automatic price repair is not permitted")
        if self.timeout_seconds <= 0:
            raise ValueError("yfinance timeout must be positive")


@dataclass(frozen=True, slots=True)
class YFinanceBar:
    session_date: str
    open: float
    high: float
    low: float
    close: float
    volume: int | None
    dividends: float
    stock_splits: float


@dataclass(frozen=True, slots=True)
class YFinanceQuote:
    symbol: str
    exchange: str
    currency: str
    market_timestamp: int
    close: float
    previous_close: float
    volume: int | None
    is_market_open: bool
    source_url: str
    canonical_payload: Mapping[str, object]
    bars: tuple[YFinanceBar, ...] = ()


class YFinanceProvider(Protocol):
    def fetch_quote(
        self,
        ticker: str,
        *,
        settings: YFinanceSettings,
    ) -> YFinanceQuote: ...


class YFinanceLibraryProvider:
    """Thin boundary around the unofficial personal-use yfinance package."""

    def fetch_quote(
        self,
        ticker: str,
        *,
        settings: YFinanceSettings,
    ) -> YFinanceQuote:
        try:
            import yfinance as yf
        except ImportError as error:
            raise MarketDataError(
                "yfinance is not installed; install the market dependency"
            ) from error
        if getattr(yf, "__version__", None) != settings.library_version:
            raise MarketDataError("installed yfinance version is not approved")

        try:
            instrument = yf.Ticker(ticker)
            history = instrument.history(
                period=settings.period,
                interval=settings.interval,
                auto_adjust=settings.auto_adjust,
                back_adjust=settings.back_adjust,
                prepost=settings.prepost,
                actions=settings.actions,
                repair=settings.repair,
                timeout=settings.timeout_seconds,
                raise_errors=True,
            )
            metadata = instrument.get_history_metadata()
        except Exception as error:
            raise MarketDataError("could not read Yahoo Finance history") from error

        if history is None or len(history.index) < 2:
            raise MarketDataError("Yahoo Finance did not return two daily observations")
        try:
            market_state = str(metadata.get("marketState", "CLOSED")).upper()
            completed_count = len(history.index) - (
                1 if market_state == "REGULAR" else 0
            )
            if completed_count < 2:
                raise MarketDataError(
                    "Yahoo Finance did not return two completed daily sessions"
                )
            bars = tuple(
                _map_history_bar(history.index[index], history.iloc[index])
                for index in range(completed_count)
            )
            latest = history.iloc[completed_count - 1]
            previous = history.iloc[completed_count - 2]
            latest_index = history.index[completed_count - 1]
            market_timestamp = int(latest_index.timestamp())
            close = float(latest["Close"])
            previous_close = float(previous["Close"])
            raw_volume = latest.get("Volume")
            volume = (
                None
                if raw_volume is None or _is_missing_number(raw_volume)
                else int(raw_volume)
            )
            exchange = str(
                metadata.get("exchangeName") or metadata.get("fullExchangeName") or ""
            )
            currency = str(metadata["currency"]).upper()
        except MarketDataError:
            raise
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            raise MarketDataError("Yahoo Finance history is incomplete") from error
        payload = {
            "adapter": "yfinance",
            "adapter_version": settings.library_version,
            "symbol": ticker,
            "exchange": exchange,
            "currency": currency,
            "session": str(latest_index),
            "close": close,
            "previous_close": previous_close,
            "volume": volume,
            "market_state": market_state,
            "auto_adjust": settings.auto_adjust,
            "back_adjust": settings.back_adjust,
            "prepost": settings.prepost,
            "actions": settings.actions,
            "repair": settings.repair,
            "bars": [
                {
                    "session_date": bar.session_date,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                    "dividends": bar.dividends,
                    "stock_splits": bar.stock_splits,
                }
                for bar in bars
            ],
        }
        return YFinanceQuote(
            symbol=ticker,
            exchange=exchange,
            currency=currency,
            market_timestamp=market_timestamp,
            close=close,
            previous_close=previous_close,
            volume=volume,
            is_market_open=market_state == "REGULAR",
            source_url=(f"https://finance.yahoo.com/quote/{ticker}/history"),
            canonical_payload=payload,
            bars=bars,
        )


class YFinanceClient:
    def __init__(
        self,
        settings: YFinanceSettings,
        *,
        provider: YFinanceProvider | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self.provider = provider or YFinanceLibraryProvider()
        self.clock = clock or (lambda: datetime.now(UTC))

    def fetch_quote(
        self,
        ticker: str,
        *,
        operator_id: str,
        security_id: str | None = None,
    ) -> MarketSnapshot:
        uuid.UUID(operator_id)
        if security_id is not None:
            uuid.UUID(security_id)
        normalized_ticker = ticker.strip().upper()
        if not normalized_ticker or len(normalized_ticker) > 10:
            raise ValueError("ticker has invalid format")

        quote = self.provider.fetch_quote(
            normalized_ticker,
            settings=self.settings,
        )
        if quote.symbol.strip().upper() != normalized_ticker:
            raise MarketDataError("Yahoo Finance returned a different symbol")
        if not quote.exchange.strip() or not quote.currency.strip():
            raise MarketDataError("Yahoo Finance venue or currency is missing")
        if quote.market_timestamp <= 0:
            raise MarketDataError("Yahoo Finance market timestamp is invalid")
        if not _valid_price(quote.close) or not _valid_price(quote.previous_close):
            raise MarketDataError("Yahoo Finance close is invalid")
        if quote.volume is not None and quote.volume < 0:
            raise MarketDataError("Yahoo Finance volume is invalid")
        for index in range(1, len(quote.bars)):
            if quote.bars[index - 1].session_date >= quote.bars[index].session_date:
                raise MarketDataError("Yahoo Finance sessions must be strictly ordered")

        change = quote.close - quote.previous_close
        percent_change = change / quote.previous_close * 100
        market_time = datetime.fromtimestamp(
            quote.market_timestamp,
            tz=UTC,
        ).isoformat()
        retrieved_at = self.clock().astimezone(UTC).isoformat()
        provider_id = "yahoo_finance_via_yfinance"
        canonical_body = json.dumps(
            quote.canonical_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        response_sha256 = hashlib.sha256(canonical_body).hexdigest()
        identity = (
            f"{provider_id}:{self.settings.library_version}:"
            f"{normalized_ticker}:{quote.market_timestamp}:{response_sha256}"
        )
        idempotency_key = f"market-snapshot:{identity}:v1"
        snapshot_id = stable_id(operator_id, "market-snapshot", identity)
        if quote.bars and security_id is None:
            raise ValueError("security_id is required for OHLCV history")
        series_id = (
            stable_id(
                operator_id,
                "market-series",
                f"{security_id}:{provider_id}:{response_sha256}",
            )
            if security_id is not None
            else None
        )
        bars = tuple(
            _build_market_bar(
                bar,
                operator_id=operator_id,
                security_id=security_id or "",
                research_run_id=stable_id(
                    operator_id,
                    "research-run",
                    idempotency_key,
                ),
                snapshot_id=snapshot_id,
                series_id=series_id or "",
                ticker=normalized_ticker,
                provider=provider_id,
                exchange=quote.exchange,
                currency=quote.currency.upper(),
                source_url=quote.source_url,
                retrieved_at=retrieved_at,
            )
            for bar in quote.bars
        )
        return MarketSnapshot(
            operator_id=operator_id,
            research_run_id=stable_id(
                operator_id,
                "research-run",
                idempotency_key,
            ),
            snapshot_id=snapshot_id,
            idempotency_key=idempotency_key,
            ticker=normalized_ticker,
            provider=provider_id,
            exchange=quote.exchange,
            currency=quote.currency.upper(),
            market_time=market_time,
            close=quote.close,
            previous_close=quote.previous_close,
            change=change,
            percent_change=percent_change,
            volume=quote.volume,
            is_market_open=quote.is_market_open,
            source_url=quote.source_url,
            retrieved_at=retrieved_at,
            response_sha256=response_sha256,
            security_id=security_id,
            series_id=series_id,
            bars=bars,
        )


def _valid_price(value: float) -> bool:
    return math.isfinite(value) and value > 0


def _is_missing_number(value: Any) -> bool:
    try:
        return math.isnan(float(value))
    except (TypeError, ValueError):
        return False


def _map_history_bar(index: Any, row: Any) -> YFinanceBar:
    try:
        raw_volume = row.get("Volume")
        volume = (
            None
            if raw_volume is None or _is_missing_number(raw_volume)
            else int(raw_volume)
        )
        bar = YFinanceBar(
            session_date=index.date().isoformat(),
            open=float(row["Open"]),
            high=float(row["High"]),
            low=float(row["Low"]),
            close=float(row["Close"]),
            volume=volume,
            dividends=float(row.get("Dividends", 0.0)),
            stock_splits=float(row.get("Stock Splits", 0.0)),
        )
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError) as error:
        raise MarketDataError("Yahoo Finance OHLCV history is incomplete") from error
    if not all(
        _valid_price(value) for value in (bar.open, bar.high, bar.low, bar.close)
    ):
        raise MarketDataError("Yahoo Finance OHLCV price is invalid")
    if bar.high < max(bar.open, bar.low, bar.close):
        raise MarketDataError("Yahoo Finance OHLCV high is inconsistent")
    if bar.low > min(bar.open, bar.high, bar.close):
        raise MarketDataError("Yahoo Finance OHLCV low is inconsistent")
    if bar.volume is not None and bar.volume < 0:
        raise MarketDataError("Yahoo Finance OHLCV volume is invalid")
    return bar


def _build_market_bar(
    bar: YFinanceBar,
    *,
    operator_id: str,
    security_id: str,
    research_run_id: str,
    snapshot_id: str,
    series_id: str,
    ticker: str,
    provider: str,
    exchange: str,
    currency: str,
    source_url: str,
    retrieved_at: str,
) -> MarketBar:
    payload = {
        "session_date": bar.session_date,
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
        "dividends": bar.dividends,
        "stock_splits": bar.stock_splits,
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    bar_sha256 = hashlib.sha256(body).hexdigest()
    identity = f"{series_id}:{provider}:{ticker}:{bar.session_date}:{bar_sha256}"
    return MarketBar(
        operator_id=operator_id,
        security_id=security_id,
        research_run_id=research_run_id,
        snapshot_id=snapshot_id,
        series_id=series_id,
        bar_id=stable_id(operator_id, "market-bar", identity),
        ticker=ticker,
        provider=provider,
        exchange=exchange,
        currency=currency,
        session_date=bar.session_date,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
        dividends=bar.dividends,
        stock_splits=bar.stock_splits,
        source_url=source_url,
        retrieved_at=retrieved_at,
        bar_sha256=bar_sha256,
    )


__all__ = [
    "MarketDataError",
    "YFinanceClient",
    "YFinanceLibraryProvider",
    "YFinanceBar",
    "YFinanceProvider",
    "YFinanceQuote",
    "YFinanceSettings",
]

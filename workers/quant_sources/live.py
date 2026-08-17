"""Live historical transports and the acquisition path that consumes them.

``LiveQuantSource`` is provider-agnostic: it accepts any
:class:`~workers.quant_sources.transports.HistoricalTransport`, checks what the
transport returned against what the caller asked for, and hands the result to
the offline Quant acquisition boundary. It never fetches anything itself.

Two transports live here. The yfinance one is real, bounded, and unadjusted.
The Moomoo one is a typed stub that fails with a stated blocker, because the
historical-bar endpoint and response semantics have not been verified against
official documentation and a guessed endpoint would produce a receipt that
looks authoritative and is not.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Callable, Sequence

from investment_research_os.quant import PointInTimeDataset, QuantContractError
from investment_research_os.quant_sources import (
    SourceSnapshot,
    acquire_point_in_time_dataset,
    payload_sha256,
)
from workers.market.client import YFinanceSettings
from workers.quant_sources.transports import (
    BoundedCaller,
    HistoricalTransport,
    HistoryBar,
    HistoryPayload,
    RateLimit,
    RetryPolicy,
    TransientTransportError,
    TransportBlockedError,
    TransportError,
)

YFINANCE_PROVIDER_ID = "yahoo_finance_via_yfinance"
MOOMOO_PROVIDER_ID = "moomoo_openapi"

#: Yahoo publishes no personal-use quota, so this is a self-imposed ceiling
#: chosen to stay far below any plausible throttle rather than to match one.
YFINANCE_RATE_LIMIT = RateLimit(max_calls=5, per_seconds=60.0)
YFINANCE_RETRY_POLICY = RetryPolicy(
    max_attempts=3,
    backoff_seconds=2.0,
    backoff_multiplier=2.0,
    max_backoff_seconds=16.0,
)

MOOMOO_HISTORY_BLOCKER = (
    "Moomoo historical daily-bar acquisition is blocked. The Web API "
    "historical-bar route, request parameters, pagination behaviour, "
    "adjustment semantics, and corporate-action representation have not been "
    "verified against official documentation, and this repository holds no "
    "evidence of a verified historical endpoint. Implementing a guessed route "
    "would produce point-in-time receipts that look authoritative while "
    "resting on an unverified price basis, which is the one failure this "
    "boundary exists to prevent. Verify the endpoint and response semantics "
    "against official documentation first, then implement fetch_daily_history "
    "to return a HistoryPayload; nothing above this transport changes."
)


class LiveQuantSource:
    """Turn one transport's daily history into one Quant point-in-time receipt.

    The transport is injected, so every rule below is testable without a
    provider. What arrives is checked against what was requested rather than
    trusted: a payload naming another symbol, another currency, or a session
    after the cutoff is refused, never reconciled or truncated.
    """

    def __init__(self, transport: HistoricalTransport) -> None:
        self.transport = transport

    def acquire(
        self,
        *,
        ticker: str,
        security_id: str,
        as_of_cutoff: date,
        currency: str,
        start: date,
    ) -> PointInTimeDataset:
        normalized_ticker = ticker.strip().upper()
        if not normalized_ticker:
            raise TransportError("ticker is required")
        if type(as_of_cutoff) is not date or type(start) is not date:
            raise TransportError("start and as_of_cutoff must be dates")
        if start > as_of_cutoff:
            raise TransportError(
                f"start {start.isoformat()} is after the cutoff "
                f"{as_of_cutoff.isoformat()}"
            )

        payload = self.transport.fetch_daily_history(
            normalized_ticker,
            start=start,
            end=as_of_cutoff,
        )
        if not isinstance(payload, HistoryPayload):
            raise TransportError(
                f"transport must return a HistoryPayload, got "
                f"{type(payload).__name__}"
            )
        if payload.symbol.strip().upper() != normalized_ticker:
            raise TransportError(
                f"transport returned a different symbol {payload.symbol!r}"
            )
        if payload.currency != currency:
            raise TransportError(
                f"transport currency {payload.currency!r} does not match the "
                f"requested currency {currency!r}"
            )
        if not payload.bars:
            raise TransportError("transport returned no daily bars")

        bar_rows, split_rows = _rows(payload, as_of_cutoff=as_of_cutoff)
        try:
            snapshot = SourceSnapshot(
                source_id=payload.provider_id,
                source_revision=payload.source_revision,
                content_sha256=payload_sha256(
                    bar_rows=bar_rows, split_rows=split_rows
                ),
                bar_rows=bar_rows,
                split_rows=split_rows,
            )
            return acquire_point_in_time_dataset(
                security_id=security_id,
                as_of_cutoff=as_of_cutoff,
                currency=currency,
                snapshot=snapshot,
            )
        except QuantContractError as error:
            raise TransportError(
                f"{payload.provider_id} history cannot form a Quant receipt: "
                f"{error}"
            ) from error


def _rows(
    payload: HistoryPayload, *, as_of_cutoff: date
) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    """Transport bars mapped to adapter rows, with the cutoff enforced here too.

    The Quant adapter refuses a post-cutoff row as well. Repeating the check is
    not redundancy for its own sake: the error raised here names the transport
    and the session, which is the difference between a debuggable rejection and
    a contract error about an anonymous bar.
    """

    bar_rows: list[dict[str, object]] = []
    split_rows: list[dict[str, object]] = []
    for index, bar in enumerate(payload.bars):
        session = bar.session_date
        if session > as_of_cutoff:
            raise TransportError(
                f"{payload.provider_id} bar {index} session "
                f"{bar.session} is after the cutoff {as_of_cutoff.isoformat()}; "
                "the boundary refuses rather than truncating, because it "
                "cannot know which window was meant"
            )
        bar_rows.append(
            {
                "session": bar.session,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
            }
        )
        ratio = Decimal(bar.stock_split)
        if ratio == 0:
            continue
        new_shares, old_shares = ratio.as_integer_ratio()
        split_rows.append(
            {
                "effective_session": bar.session,
                "new_shares": new_shares,
                "old_shares": old_shares,
            }
        )
    return tuple(bar_rows), tuple(split_rows)


class YFinanceHistoryTransport:
    """Bounded live boundary around the unofficial personal-use yfinance package.

    The library module is injected so the mapping and the policy are testable
    with no network. The window is explicit: a start date and a cutoff, never a
    rolling period, because a period selected relative to now is an implicit
    latest selection and cannot be reproduced.

    Adjustment is off in every form the settings expose, and the settings
    object refuses to be constructed otherwise. Unadjusted prices are the whole
    point: an adjusted series silently rewrites history around a split and
    makes a point-in-time receipt a fiction.
    """

    provider_id = YFINANCE_PROVIDER_ID

    def __init__(
        self,
        settings: YFinanceSettings,
        *,
        module: object | None = None,
        caller: BoundedCaller | None = None,
        importer: Callable[[], object] | None = None,
    ) -> None:
        self.settings = settings
        self._module = module
        self._importer = importer or _import_yfinance
        self._caller = caller or BoundedCaller(
            policy=YFINANCE_RETRY_POLICY,
            rate_limit=YFINANCE_RATE_LIMIT,
        )

    def fetch_daily_history(
        self, ticker: str, *, start: date, end: date
    ) -> HistoryPayload:
        module = self._module if self._module is not None else self._importer()
        version = getattr(module, "__version__", None)
        if version != self.settings.library_version:
            raise TransportError(
                f"installed yfinance version {version!r} is not the approved "
                f"{self.settings.library_version!r}"
            )
        if start > end:
            raise TransportError("start must not be after end")

        # yfinance treats ``end`` as exclusive, so the cutoff session is only
        # included when the window ends the day after it.
        window = {
            "start": start.isoformat(),
            "end": (end + timedelta(days=1)).isoformat(),
            "interval": self.settings.interval,
            "auto_adjust": self.settings.auto_adjust,
            "back_adjust": self.settings.back_adjust,
            "prepost": self.settings.prepost,
            "actions": self.settings.actions,
            "repair": self.settings.repair,
            "timeout": self.settings.timeout_seconds,
            "raise_errors": True,
        }

        instrument = module.Ticker(ticker)  # type: ignore[attr-defined]

        def fetch() -> tuple[object, object]:
            try:
                history = instrument.history(**window)
                metadata = instrument.get_history_metadata()
            except Exception as error:  # provider failures are opaque
                raise TransientTransportError(
                    f"could not read Yahoo Finance history: {error}"
                ) from error
            return history, metadata

        history, metadata = self._caller.call(fetch)
        return _yfinance_payload(
            history,
            metadata,
            ticker=ticker,
            settings=self.settings,
            start=start,
            end=end,
        )


def _import_yfinance() -> object:
    try:
        import yfinance as yf
    except ImportError as error:
        raise TransportError(
            "yfinance is not installed; install the market dependency"
        ) from error
    return yf


def _yfinance_payload(
    history: object,
    metadata: object,
    *,
    ticker: str,
    settings: YFinanceSettings,
    start: date,
    end: date,
) -> HistoryPayload:
    index = getattr(history, "index", None)
    if index is None:
        raise TransportError("Yahoo Finance history is missing its index")
    if not isinstance(metadata, dict) or "currency" not in metadata:
        raise TransportError("Yahoo Finance history metadata is incomplete")
    currency = str(metadata["currency"]).upper()

    bars: list[HistoryBar] = []
    for position in range(len(index)):
        row = history.iloc[position]  # type: ignore[attr-defined]
        session = index[position].date()
        try:
            bars.append(
                HistoryBar(
                    session=session,
                    open=_text(row["Open"], field=f"bar {position} open"),
                    high=_text(row["High"], field=f"bar {position} high"),
                    low=_text(row["Low"], field=f"bar {position} low"),
                    close=_text(row["Close"], field=f"bar {position} close"),
                    volume=_whole(row.get("Volume"), field=f"bar {position} volume"),
                    stock_split=_text(
                        row.get("Stock Splits", 0),
                        field=f"bar {position} stock split",
                    ),
                )
            )
        except (KeyError, TypeError) as error:
            raise TransportError(
                f"Yahoo Finance bar {position} is incomplete"
            ) from error

    return HistoryPayload(
        provider_id=YFINANCE_PROVIDER_ID,
        symbol=ticker,
        currency=currency,
        source_revision=_yfinance_revision(
            bars, settings=settings, ticker=ticker, start=start, end=end
        ),
        bars=tuple(bars),
    )


def _text(value: object, *, field: str) -> str:
    """A yfinance number, carried across as decimal text.

    yfinance returns binary floats. The shortest repr is the closest decimal
    the library itself would print, and it is the only decimal available: the
    precision the vendor actually held is gone before this code runs. That
    limitation belongs to the source, and is stated rather than hidden.
    """

    if isinstance(value, bool):
        raise TransportError(f"{field} must be numeric")
    if isinstance(value, float):
        return str(Decimal(str(value)))
    if isinstance(value, (int, str, Decimal)):
        return str(value)
    raise TransportError(f"{field} must be numeric, got {type(value).__name__}")


def _whole(value: object, *, field: str) -> int:
    if isinstance(value, bool) or value is None:
        raise TransportError(f"{field} is missing; Quant requires volume")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise TransportError(f"{field} must be a whole number of shares")


def _yfinance_revision(
    bars: Sequence[HistoryBar],
    *,
    settings: YFinanceSettings,
    ticker: str,
    start: date,
    end: date,
) -> str:
    """A revision derived from the payload itself.

    Yahoo publishes no snapshot identifier, so there is nothing authoritative
    to pin. Hashing the returned window is the honest substitute: it is stable
    for the same data and different for different data, which is what makes a
    receipt reproducible. It is not a vendor vintage and does not prove the
    rows were the rows visible on the cutoff date.
    """

    body = json.dumps(
        {
            "library_version": settings.library_version,
            "ticker": ticker,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "bars": [
                [bar.session, bar.open, bar.high, bar.low, bar.close, bar.volume,
                 bar.stock_split]
                for bar in bars
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"yfinance-{settings.library_version}-{hashlib.sha256(body).hexdigest()}"


class MoomooHistoryTransport:
    """Typed placeholder for Moomoo daily history, blocked by design.

    The shape is fixed so the rest of the path is already written against it.
    The behaviour is a stated blocker, because the endpoint has not been
    verified. See ``MOOMOO_HISTORY_BLOCKER``.
    """

    provider_id = MOOMOO_PROVIDER_ID

    def fetch_daily_history(
        self, ticker: str, *, start: date, end: date
    ) -> HistoryPayload:
        raise TransportBlockedError(MOOMOO_HISTORY_BLOCKER)


__all__ = [
    "MOOMOO_HISTORY_BLOCKER",
    "MOOMOO_PROVIDER_ID",
    "LiveQuantSource",
    "MoomooHistoryTransport",
    "YFINANCE_PROVIDER_ID",
    "YFINANCE_RATE_LIMIT",
    "YFINANCE_RETRY_POLICY",
    "YFinanceHistoryTransport",
]

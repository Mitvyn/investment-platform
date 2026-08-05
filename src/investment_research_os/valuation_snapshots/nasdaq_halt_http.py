from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
from zoneinfo import ZoneInfo

from workers.http import trusted_ssl_context

from .market_proofs import (
    NasdaqTraderHaltSearchResult,
    NasdaqTraderHaltTransportError,
)


_SOURCE_URL = "https://www.nasdaqtrader.com/Trader.aspx?id=TradingHaltSearch"
_RPC_URL = "https://www.nasdaqtrader.com/RPCHandler.axd"
_SOURCE_VERSION = "nasdaq-trader-halt-search.v2"
_RPC_METHOD = "BL_TradeHalt.SearchTradeHaltsNEW"
_RPC_VERSION = "1.1"
_RPC_REQUEST_ID = 1
_HALT_RESULT_HEADERS = (
    "halt date",
    "halt time",
    "issue symbol",
    "issue name",
    "market",
    "reason code",
    "pause threshold price",
    "resumption date",
    "resumption quote time",
    "resumption trade time",
)
_SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")
_MAX_RESPONSE_BYTES = 2_000_000
_NEW_YORK = ZoneInfo("America/New_York")


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True, slots=True)
class NasdaqTraderHaltHttpSettings:
    user_agent: str
    timeout_seconds: float = 10.0
    source_url: str = _SOURCE_URL
    rpc_url: str = _RPC_URL
    source_version: str = _SOURCE_VERSION

    def __post_init__(self) -> None:
        if (
            not self.user_agent.strip()
            or len(self.user_agent) > 256
            or "\r" in self.user_agent
            or "\n" in self.user_agent
        ):
            raise ValueError("Nasdaq Trader user agent is invalid")
        if not 0 < self.timeout_seconds <= 30:
            raise ValueError(
                "Nasdaq Trader timeout must be between zero and thirty seconds"
            )
        if self.source_url != _SOURCE_URL:
            raise ValueError("Nasdaq Trader halt source URL is not approved")
        if self.rpc_url != _RPC_URL:
            raise ValueError("Nasdaq Trader halt RPC URL is not approved")
        if self.source_version != _SOURCE_VERSION:
            raise ValueError("Nasdaq Trader halt source version is not approved")


@dataclass(frozen=True, slots=True)
class _ParsedPage:
    inputs: tuple[tuple[str, str, str], ...]
    tables: tuple[tuple[tuple[str, ...], ...], ...]


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.inputs: list[tuple[str, str, str]] = []
        self.tables: list[list[tuple[str, ...]]] = []
        self._table: list[tuple[str, ...]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "input":
            name = attributes.get("name", "").strip()
            if name:
                self.inputs.append(
                    (
                        name,
                        attributes.get("type", "text").strip().lower(),
                        attributes.get("value", ""),
                    )
                )
        elif tag.lower() == "table":
            self._table = []
        elif tag.lower() == "tr" and self._table is not None:
            self._row = []
        elif tag.lower() in {"th", "td"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"th", "td"} and self._cell is not None:
            assert self._row is not None
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag.lower() == "tr" and self._row is not None:
            assert self._table is not None
            if self._row:
                self._table.append(tuple(self._row))
            self._row = None
        elif tag.lower() == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None

    def result(self) -> _ParsedPage:
        return _ParsedPage(
            inputs=tuple(self.inputs),
            tables=tuple(tuple(table) for table in self.tables),
        )


class NasdaqTraderHaltHttpTransport:
    """Bounded two-step client for Nasdaq Trader historical halt search."""

    def __init__(
        self,
        settings: NasdaqTraderHaltHttpSettings,
        *,
        request_executor: Callable[..., Any] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self.request_executor = request_executor
        self.clock = clock or (lambda: datetime.now(UTC))
        self.ssl_context = trusted_ssl_context()
        self.opener = build_opener(
            HTTPSHandler(context=self.ssl_context),
            _NoRedirectHandler(),
        )

    def search_halts(
        self,
        *,
        symbol: str,
        session_date: date,
    ) -> NasdaqTraderHaltSearchResult:
        if not _SYMBOL_PATTERN.fullmatch(symbol):
            raise ValueError("Nasdaq Trader halt symbol is invalid")
        bootstrap_body = self._request(
            Request(
                self.settings.source_url,
                headers=self._headers(),
                method="GET",
            ),
            expected_url=self.settings.source_url,
            permitted_media_types={"text/html", "application/xhtml+xml"},
        )
        _validate_search_page(bootstrap_body)
        request_payload = {
            "id": _RPC_REQUEST_ID,
            "method": _RPC_METHOD,
            "params": [
                symbol,
                "",
                "",
                session_date.strftime("%m/%d/%Y"),
                session_date.strftime("%m/%d/%Y"),
                "",
                "",
            ],
            "version": _RPC_VERSION,
        }
        search_body = self._request(
            Request(
                self.settings.rpc_url,
                data=json.dumps(
                    request_payload,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("ascii"),
                headers={
                    **self._headers(),
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Referer": self.settings.source_url,
                },
                method="POST",
            ),
            expected_url=self.settings.rpc_url,
            permitted_media_types={"application/json"},
        )
        result = _parse_rpc_response(
            search_body,
            request_id=_RPC_REQUEST_ID,
        )
        records = (
            ()
            if result == "No Data Found"
            else _parse_halt_records(
                _parse_page(result.encode("utf-8")),
                symbol=symbol,
                session_date=session_date,
            )
        )
        retrieved_at = self.clock()
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise NasdaqTraderHaltTransportError(
                "Nasdaq Trader retrieval clock must include timezone"
            )
        return NasdaqTraderHaltSearchResult(
            query_symbol=symbol,
            query_session_date=session_date,
            records=records,
            complete=True,
            source_version=self.settings.source_version,
            source_locator=self.settings.source_url,
            retrieved_at=retrieved_at.astimezone(UTC),
            response_sha256=hashlib.sha256(search_body).hexdigest(),
        )

    def _headers(self) -> Mapping[str, str]:
        return {
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": self.settings.user_agent,
        }

    def _request(
        self,
        request: Request,
        *,
        expected_url: str,
        permitted_media_types: set[str],
    ) -> bytes:
        try:
            with self._execute(request) as response:
                status = int(response.status)
                final_url = response.geturl()
                headers = dict(response.headers.items())
                body = response.read(_MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            raise NasdaqTraderHaltTransportError(
                f"Nasdaq Trader returned HTTP {error.code}"
            ) from error
        except (TimeoutError, URLError, OSError) as error:
            raise NasdaqTraderHaltTransportError(
                "Nasdaq Trader halt search request failed"
            ) from error
        if not 200 <= status < 300:
            raise NasdaqTraderHaltTransportError(
                f"Nasdaq Trader returned HTTP {status}"
            )
        if final_url != expected_url:
            raise NasdaqTraderHaltTransportError("Nasdaq Trader halt search redirected")
        media_type = _header(headers, "content-type").partition(";")[0].strip().lower()
        if media_type not in permitted_media_types:
            raise NasdaqTraderHaltTransportError(
                "Nasdaq Trader halt search content type is invalid"
            )
        if not body or len(body) > _MAX_RESPONSE_BYTES:
            raise NasdaqTraderHaltTransportError(
                "Nasdaq Trader halt search body is invalid"
            )
        return body

    def _execute(self, request: Request) -> Any:
        if self.request_executor is not None:
            return self.request_executor(
                request,
                timeout=self.settings.timeout_seconds,
                context=self.ssl_context,
            )
        return self.opener.open(request, timeout=self.settings.timeout_seconds)


def _parse_page(body: bytes) -> _ParsedPage:
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise NasdaqTraderHaltTransportError(
            "Nasdaq Trader halt search body is not UTF-8"
        ) from error
    parser = _PageParser()
    try:
        parser.feed(text)
        parser.close()
    except (AssertionError, ValueError) as error:
        raise NasdaqTraderHaltTransportError(
            "Nasdaq Trader halt search HTML is malformed"
        ) from error
    return parser.result()


def _validate_search_page(body: bytes) -> None:
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise NasdaqTraderHaltTransportError(
            "Nasdaq Trader halt search body is not UTF-8"
        ) from error
    page = _parse_page(body)
    input_names = {name for name, input_type, _ in page.inputs if input_type == "text"}
    required_inputs = {"txtSymbol", "txtDateStart", "txtDateStartTo"}
    if (
        not required_inputs.issubset(input_names)
        or _RPC_METHOD not in text
        or "rpcclient.axd" not in text
        or "Trading Halt Search" not in text
    ):
        raise NasdaqTraderHaltTransportError(
            "Nasdaq Trader halt search page contract is unsupported"
        )


def _parse_rpc_response(body: bytes, *, request_id: int) -> str:
    try:
        payload = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NasdaqTraderHaltTransportError(
            "Nasdaq Trader halt response envelope is invalid"
        ) from error
    if (
        not isinstance(payload, dict)
        or set(payload) != {"result", "id", "version"}
        or str(payload["id"]) != str(request_id)
        or payload["version"] != _RPC_VERSION
        or not isinstance(payload["result"], str)
        or not payload["result"].strip()
    ):
        raise NasdaqTraderHaltTransportError(
            "Nasdaq Trader halt response envelope is invalid"
        )
    return payload["result"]


def _parse_halt_records(
    page: _ParsedPage,
    *,
    symbol: str,
    session_date: date,
) -> tuple[Mapping[str, object], ...]:
    matches = tuple(
        table
        for table in page.tables
        if table
        and tuple(_normalize_header(value) for value in table[0])
        == _HALT_RESULT_HEADERS
    )
    if len(matches) != 1:
        raise NasdaqTraderHaltTransportError(
            "Nasdaq Trader halt result table is unsupported"
        )
    table = matches[0]
    if any(len(row) != len(table[0]) for row in table[1:]):
        raise NasdaqTraderHaltTransportError(
            "Nasdaq Trader halt result row is malformed"
        )
    header_indexes = {
        _normalize_header(value): index for index, value in enumerate(table[0])
    }
    records: list[Mapping[str, object]] = []
    for row in table[1:]:
        row_symbol = row[header_indexes["issue symbol"]].strip().upper()
        halt_date = _parse_market_date(row[header_indexes["halt date"]])
        if row_symbol != symbol or halt_date != session_date:
            raise NasdaqTraderHaltTransportError(
                "Nasdaq Trader halt result row does not match requested query"
            )
        market = _normalize_market(row[header_indexes["market"]])
        halted_at = _market_timestamp(
            row[header_indexes["halt date"]],
            row[header_indexes["halt time"]],
            required=True,
        )
        resumed_at = _market_timestamp(
            row[header_indexes["resumption date"]],
            row[header_indexes["resumption trade time"]],
            required=False,
        )
        reason_code = row[header_indexes["reason code"]].strip()
        if not reason_code:
            raise NasdaqTraderHaltTransportError(
                "Nasdaq Trader halt reason code is missing"
            )
        canonical_record = "|".join(
            (
                row_symbol,
                market,
                halted_at.isoformat(),
                "" if resumed_at is None else resumed_at.isoformat(),
                reason_code,
            )
        )
        records.append(
            {
                "record_id": hashlib.sha256(canonical_record.encode()).hexdigest(),
                "symbol": row_symbol,
                "market": market,
                "halted_at": halted_at.isoformat(),
                "resumed_at": None if resumed_at is None else resumed_at.isoformat(),
                "reason_code": reason_code,
            }
        )
    record_ids = tuple(str(record["record_id"]) for record in records)
    if len(record_ids) != len(set(record_ids)):
        raise NasdaqTraderHaltTransportError(
            "Nasdaq Trader halt result contains duplicate rows"
        )
    return tuple(records)


def _parse_market_date(value: str) -> date:
    try:
        return datetime.strptime(value.strip(), "%m/%d/%Y").date()
    except ValueError as error:
        raise NasdaqTraderHaltTransportError(
            "Nasdaq Trader halt date is invalid"
        ) from error


def _market_timestamp(
    date_value: str,
    time_value: str,
    *,
    required: bool,
) -> datetime | None:
    normalized_date = date_value.strip()
    normalized_time = time_value.strip()
    if not normalized_date and not normalized_time and not required:
        return None
    if not normalized_date or not normalized_time:
        raise NasdaqTraderHaltTransportError(
            "Nasdaq Trader halt timestamp is incomplete"
        )
    market_date = _parse_market_date(normalized_date)
    parsed_time = None
    for pattern in (
        "%I:%M:%S %p",
        "%I:%M %p",
        "%H:%M:%S.%f",
        "%H:%M:%S",
        "%H:%M",
    ):
        try:
            parsed_time = datetime.strptime(normalized_time.upper(), pattern).time()
            break
        except ValueError:
            continue
    if parsed_time is None:
        raise NasdaqTraderHaltTransportError("Nasdaq Trader halt time is invalid")
    return datetime.combine(market_date, parsed_time, tzinfo=_NEW_YORK)


def _normalize_market(value: str) -> str:
    normalized = " ".join(value.upper().split())
    mapping = {
        "Q": "NASDAQ",
        "NASDAQ": "NASDAQ",
        "N": "NYSE",
        "NYSE": "NYSE",
        "A": "NYSE AMERICAN",
        "NYSE AMERICAN": "NYSE AMERICAN",
        "NYSE MKT": "NYSE AMERICAN",
    }
    try:
        return mapping[normalized]
    except KeyError as error:
        raise NasdaqTraderHaltTransportError(
            "Nasdaq Trader halt market is unsupported"
        ) from error


def _normalize_header(value: str) -> str:
    return " ".join(value.lower().split())


def _header(headers: Mapping[str, str], name: str) -> str:
    return next(
        (value for key, value in headers.items() if key.lower() == name),
        "",
    )


__all__ = [
    "NasdaqTraderHaltHttpSettings",
    "NasdaqTraderHaltHttpTransport",
    "NasdaqTraderHaltTransportError",
]

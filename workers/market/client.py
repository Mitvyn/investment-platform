from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from workers.http import trusted_ssl_context
from workers.ids import stable_id

from .models import MarketSnapshot


class MarketDataError(RuntimeError):
    """Raised when quote configuration, transport, or payload is invalid."""


@dataclass(frozen=True, slots=True)
class TwelveDataSettings:
    api_key: str
    base_url: str = "https://api.twelvedata.com"
    timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ValueError("Twelve Data API key cannot be blank")


@dataclass(frozen=True, slots=True)
class JsonResponse:
    payload: Any
    status: int
    raw_body: bytes


class JsonTransport(Protocol):
    def request_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
    ) -> JsonResponse: ...


class UrllibJsonTransport:
    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds
        self.ssl_context = trusted_ssl_context()

    def request_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
    ) -> JsonResponse:
        request = Request(url, headers=dict(headers), method="GET")
        try:
            with urlopen(
                request,
                timeout=self.timeout_seconds,
                context=self.ssl_context,
            ) as response:
                raw_body = response.read()
                return JsonResponse(
                    payload=json.loads(raw_body.decode()),
                    status=response.status,
                    raw_body=raw_body,
                )
        except HTTPError as error:
            raise MarketDataError(
                f"Twelve Data returned HTTP {error.code}"
            ) from error
        except (URLError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise MarketDataError("could not read Twelve Data quote") from error


class TwelveDataClient:
    def __init__(
        self,
        settings: TwelveDataSettings,
        *,
        transport: JsonTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport or UrllibJsonTransport(settings.timeout_seconds)
        self.clock = clock or (lambda: datetime.now(UTC))

    def fetch_quote(self, ticker: str, *, operator_id: str) -> MarketSnapshot:
        uuid.UUID(operator_id)
        normalized_ticker = ticker.strip().upper()
        if not normalized_ticker or len(normalized_ticker) > 10:
            raise ValueError("ticker has invalid format")

        query = urlencode({"symbol": normalized_ticker})
        source_url = f"{self.settings.base_url.rstrip('/')}/quote?{query}"
        response = self.transport.request_json(
            source_url,
            headers={
                "Accept": "application/json",
                "Authorization": f"apikey {self.settings.api_key}",
            },
        )
        if response.status != 200:
            raise MarketDataError(
                f"Twelve Data returned HTTP {response.status}"
            )
        payload = response.payload
        if not isinstance(payload, dict):
            raise MarketDataError("Twelve Data quote payload must be an object")
        if payload.get("status") == "error":
            message = str(payload.get("message", "unknown provider error"))
            raise MarketDataError(f"Twelve Data rejected quote: {message}")

        try:
            returned_symbol = str(payload["symbol"]).upper()
            market_timestamp = int(payload["timestamp"])
            market_time = datetime.fromtimestamp(
                market_timestamp,
                tz=UTC,
            ).isoformat()
            close = float(payload["close"])
            previous_close = float(payload["previous_close"])
            change = float(payload["change"])
            percent_change = float(payload["percent_change"])
            exchange = str(payload["exchange"])
            currency = str(payload["currency"]).upper()
            is_market_open = payload["is_market_open"]
            if not isinstance(is_market_open, bool):
                raise TypeError("is_market_open must be boolean")
            raw_volume = payload.get("volume")
            volume = int(raw_volume) if raw_volume not in (None, "") else None
        except (KeyError, TypeError, ValueError) as error:
            raise MarketDataError("Twelve Data quote payload is incomplete") from error
        if returned_symbol != normalized_ticker:
            raise MarketDataError("Twelve Data returned a different symbol")

        retrieved_at = self.clock().astimezone(UTC).isoformat()
        identity = f"twelve_data:{normalized_ticker}:{market_timestamp}"
        idempotency_key = f"market-snapshot:{identity}:v1"
        canonical_body = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return MarketSnapshot(
            operator_id=operator_id,
            research_run_id=stable_id(operator_id, "research-run", idempotency_key),
            snapshot_id=stable_id(operator_id, "market-snapshot", identity),
            idempotency_key=idempotency_key,
            ticker=normalized_ticker,
            provider="twelve_data",
            exchange=exchange,
            currency=currency,
            market_time=market_time,
            close=close,
            previous_close=previous_close,
            change=change,
            percent_change=percent_change,
            volume=volume,
            is_market_open=is_market_open,
            source_url=source_url,
            retrieved_at=retrieved_at,
            response_sha256=hashlib.sha256(canonical_body).hexdigest(),
        )

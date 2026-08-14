from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import Request, urlopen

from workers.http import trusted_ssl_context


READ_ONLY_SCOPES = ("quote:read", "trade:read")
MAX_RESPONSE_BYTES = 1_048_576


@dataclass(frozen=True, slots=True)
class MoomooSettings:
    scopes: tuple[str, ...]
    base_url: str = "https://webapi.moomoo.com"
    success_indicator: str | int | None = "ok"

    def __post_init__(self) -> None:
        normalized = tuple(sorted(set(self.scopes)))
        if normalized != READ_ONLY_SCOPES:
            raise ValueError("Moomoo requires exact read-only scopes")
        parsed_url = urlsplit(self.base_url)
        if parsed_url.scheme != "https" or not parsed_url.netloc:
            raise ValueError("Moomoo base URL must use HTTPS")
        object.__setattr__(self, "scopes", normalized)


@dataclass(frozen=True, slots=True)
class MoomooResponse:
    """HTTP metadata plus transport-normalized provider body."""

    status: int
    headers: Mapping[str, str]
    payload: Mapping[str, Any]


class MoomooTransport(Protocol):
    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
    ) -> MoomooResponse: ...


class UrllibMoomooTransport:
    def __init__(
        self,
        *,
        opener: Callable[..., object] = urlopen,
        timeout_seconds: float = 15,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Moomoo timeout must be positive")
        self._opener = opener
        self._timeout_seconds = timeout_seconds
        self._ssl_context = trusted_ssl_context()

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
    ) -> MoomooResponse:
        if method != "GET" or urlsplit(url).scheme != "https":
            raise MoomooProtocolError("Moomoo request is invalid")
        request = Request(url, headers=dict(headers), method=method)
        try:
            with self._opener(
                request,
                timeout=self._timeout_seconds,
                context=self._ssl_context,
            ) as response:
                return _decode_url_response(response, requested_url=url)
        except HTTPError as error:
            return _decode_url_response(error, requested_url=url)
        except (URLError, TimeoutError, OSError) as error:
            raise MoomooProtocolError("Moomoo request failed") from error


@dataclass(frozen=True, slots=True)
class MoomooAccount:
    account_id: str
    security_firm: str
    enable_market: tuple[int, ...]
    univs_account_card_number: str
    acc_type: str
    account_card_number: str


@dataclass(frozen=True, slots=True)
class MoomooPosition:
    account_id: str
    position_side: str
    code: str
    stock_name: str
    currency: str
    qty: str
    can_sell_qty: str
    nominal_price: str
    cost_price: str | None
    cost_price_valid: bool
    cost_price_unavailable_reason: str | None
    market_val: str
    pl_ratio: str | None
    pl_ratio_valid: bool
    pl_ratio_unavailable_reason: str | None
    pl_val: str | None
    pl_val_valid: bool
    pl_val_unavailable_reason: str | None
    today_pl_val: str
    unrealized_pl: str
    realized_pl: str
    precision_risk_fields: tuple[str, ...]


class MoomooProtocolError(RuntimeError):
    """Raised when Moomoo returns an invalid or unsuccessful response."""


class MoomooRateLimitError(MoomooProtocolError):
    """Raised when Moomoo rejects a request due to quota limits."""

    def __init__(self, retry_after_seconds: int | None) -> None:
        super().__init__("Moomoo rate limit exceeded")
        self.retry_after_seconds = retry_after_seconds


def _decode_url_response(response: object, *, requested_url: str) -> MoomooResponse:
    geturl = getattr(response, "geturl", None)
    if callable(geturl) and geturl() != requested_url:
        raise MoomooProtocolError("Moomoo redirect is not allowed")
    raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise MoomooProtocolError("Moomoo response is too large")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MoomooProtocolError("Moomoo response is invalid") from error
    if not isinstance(payload, Mapping):
        raise MoomooProtocolError("Moomoo response is invalid")
    raw_headers = getattr(response, "headers", {})
    headers = dict(raw_headers.items()) if hasattr(raw_headers, "items") else {}
    return MoomooResponse(
        status=int(getattr(response, "status", getattr(response, "code", 0))),
        headers=headers,
        payload=payload,
    )


class MoomooClient:
    def __init__(
        self,
        settings: MoomooSettings,
        *,
        access_token: str,
        transport: MoomooTransport,
    ) -> None:
        if not access_token.strip():
            raise ValueError("Moomoo access token is required")
        self.settings = settings
        self._access_token = access_token
        self.transport = transport

    def list_accounts(self) -> tuple[MoomooAccount, ...]:
        response = self.transport.request_json(
            "GET",
            urljoin(
                self.settings.base_url.rstrip("/") + "/",
                "api/v1.0/accounts/authorized_trd_accs",
            ),
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._access_token}",
            },
        )
        data = _successful_data(
            response,
            success_indicator=self.settings.success_indicator,
        )
        if not isinstance(data, Mapping) or set(data) != {"accounts"}:
            raise MoomooProtocolError("Moomoo accounts payload is invalid")
        accounts = data["accounts"]
        if not isinstance(accounts, list):
            raise MoomooProtocolError("Moomoo accounts payload is invalid")
        return tuple(_map_account(item) for item in accounts)

    def list_positions(self, account_id: str) -> tuple[MoomooPosition, ...]:
        normalized_account_id = account_id.strip()
        if not normalized_account_id:
            raise ValueError("Moomoo account ID is required")
        endpoint = urljoin(
            self.settings.base_url.rstrip("/") + "/",
            f"api/v1.0/accounts/{quote(normalized_account_id, safe='')}/positions",
        )
        response = self.transport.request_json(
            "GET",
            endpoint,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._access_token}",
            },
        )
        data = _successful_data(
            response,
            success_indicator=self.settings.success_indicator,
        )
        if not isinstance(data, list):
            raise MoomooProtocolError("Moomoo positions payload is invalid")
        return tuple(
            _map_position(item, account_id=normalized_account_id) for item in data
        )


def _successful_data(
    response: MoomooResponse,
    *,
    success_indicator: str | int | None,
) -> object:
    if response.status == 429:
        retry_after = next(
            (
                value
                for key, value in response.headers.items()
                if key.lower() == "retry-after"
            ),
            None,
        )
        retry_after_seconds = None
        if retry_after is not None:
            try:
                parsed_retry_after = int(retry_after)
            except (TypeError, ValueError):
                pass
            else:
                if parsed_retry_after >= 0:
                    retry_after_seconds = parsed_retry_after
        raise MoomooRateLimitError(retry_after_seconds)
    if response.status < 200 or response.status >= 300:
        raise MoomooProtocolError(f"Moomoo HTTP status {response.status}")
    if success_indicator is None:
        raise MoomooProtocolError("Moomoo success indicator is not configured")
    status_indicator = response.payload.get("s")
    recognized = (
        type(status_indicator) is type(success_indicator)
        and status_indicator == success_indicator
    )
    if not recognized:
        error_code = response.payload.get("errcode")
        error_message = response.payload.get("errmsg")
        raise MoomooProtocolError(
            "Moomoo API returned an error "
            f"(s={status_indicator!r}, errcode={error_code!r}, "
            f"errmsg={error_message!r})"
        )
    if "d" not in response.payload:
        raise MoomooProtocolError("Moomoo response data is missing")
    return response.payload["d"]


def _map_account(raw: object) -> MoomooAccount:
    if not isinstance(raw, Mapping):
        raise MoomooProtocolError("Moomoo account is invalid")
    fields = (
        "account_id",
        "security_firm",
        "univs_account_card_number",
        "acc_type",
        "account_card_number",
    )
    values = {field: str(raw.get(field, "")).strip() for field in fields}
    if not all(values.values()):
        raise MoomooProtocolError("Moomoo account fields are incomplete")
    raw_markets = raw.get("enable_market")
    if not isinstance(raw_markets, list) or not raw_markets:
        raise MoomooProtocolError("Moomoo account enable_market is invalid")
    if any(isinstance(item, bool) or not isinstance(item, int) for item in raw_markets):
        raise MoomooProtocolError("Moomoo account enable_market is invalid")
    markets = tuple(raw_markets)
    return MoomooAccount(
        account_id=values["account_id"],
        security_firm=values["security_firm"],
        enable_market=markets,
        univs_account_card_number=values["univs_account_card_number"],
        acc_type=values["acc_type"],
        account_card_number=values["account_card_number"],
    )


def _map_position(raw: object, *, account_id: str) -> MoomooPosition:
    if not isinstance(raw, Mapping):
        raise MoomooProtocolError("Moomoo position is invalid")
    text_fields = {
        field: str(raw.get(field, "")).strip()
        for field in ("position_side", "code", "stock_name", "currency")
    }
    if not all(text_fields.values()):
        raise MoomooProtocolError("Moomoo position fields are incomplete")
    precision_risks: list[str] = []
    decimals: dict[str, str] = {}
    for field in (
        "qty",
        "can_sell_qty",
        "nominal_price",
        "market_val",
        "today_pl_val",
        "unrealized_pl",
        "realized_pl",
    ):
        decimals[field], arrived_as_float = _decimal_string(raw.get(field), field=field)
        if arrived_as_float:
            precision_risks.append(field)
    optional_decimals: dict[str, str | bool | None] = {}
    for field, validity_field in (
        ("cost_price", "cost_price_valid"),
        ("pl_ratio", "pl_ratio_valid"),
        ("pl_val", "pl_val_valid"),
    ):
        value, is_valid, reason, arrived_as_float = _validity_gated_decimal(
            raw,
            field=field,
            validity_field=validity_field,
        )
        optional_decimals[field] = value
        optional_decimals[validity_field] = is_valid
        optional_decimals[f"{field}_unavailable_reason"] = reason
        if arrived_as_float:
            precision_risks.append(field)
    return MoomooPosition(
        account_id=account_id,
        position_side=text_fields["position_side"].upper(),
        code=text_fields["code"].upper(),
        stock_name=text_fields["stock_name"],
        currency=text_fields["currency"].upper(),
        **decimals,
        **optional_decimals,
        precision_risk_fields=tuple(precision_risks),
    )


def _decimal_string(value: object, *, field: str) -> tuple[str, bool]:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise MoomooProtocolError(f"Moomoo {field} must be numeric")
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            raise MoomooProtocolError(f"Moomoo {field} must be numeric")
    else:
        normalized = str(value)
    try:
        parsed = Decimal(normalized)
    except InvalidOperation as error:
        raise MoomooProtocolError(f"Moomoo {field} must be numeric") from error
    if not parsed.is_finite():
        raise MoomooProtocolError(f"Moomoo {field} must be finite")
    return normalized, isinstance(value, float)


def _validity_gated_decimal(
    raw: Mapping[str, Any],
    *,
    field: str,
    validity_field: str,
) -> tuple[str | None, bool, str | None, bool]:
    validity = raw.get(validity_field)
    if not isinstance(validity, bool):
        raise MoomooProtocolError(f"Moomoo {validity_field} must be boolean")
    if not validity:
        return None, False, f"provider_{field}_invalid", False
    value, arrived_as_float = _decimal_string(raw.get(field), field=field)
    return value, True, None, arrived_as_float

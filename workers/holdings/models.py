from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from workers.ids import stable_id

PORTFOLIO_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class HoldingPosition:
    position_id: str
    operator_id: str
    snapshot_id: str
    security_id: str
    ordinal: int
    ticker: str
    quantity: str
    average_cost: str
    observed_price: str
    observed_market_value: str
    cost_basis: str
    unrealized_pnl: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class HoldingSnapshot:
    snapshot_id: str
    operator_id: str
    portfolio_key: str
    account_label: str
    currency: str | None
    currency_state: str
    observed_at: str | None
    timing_state: str
    observation_time_text: str
    source_type: str
    source_sha256: str
    captured_at: str
    content_sha256: str
    position_count: int
    total_market_value: str
    total_cost_basis: str
    total_unrealized_pnl: str
    positions: tuple[HoldingPosition, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _decimal(value: object, *, field: str, positive: bool = True) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{field} must be an exact decimal") from error
    if not parsed.is_finite() or (positive and parsed <= 0):
        raise ValueError(f"{field} must be positive")
    return parsed


def _canonical_decimal(value: Decimal) -> str:
    return format(value, "f")


def build_holding_snapshot(
    payload: Mapping[str, Any],
    *,
    operator_id: str,
    captured_at: datetime,
) -> HoldingSnapshot:
    uuid.UUID(operator_id)
    if captured_at.tzinfo is None:
        raise ValueError("captured_at must include timezone")
    portfolio_key = str(payload.get("portfolio_key", "")).strip().lower()
    if not PORTFOLIO_KEY_PATTERN.fullmatch(portfolio_key):
        raise ValueError("portfolio_key has invalid format")
    account_label = str(payload.get("account_label", "")).strip()
    if not account_label or len(account_label) > 100:
        raise ValueError("account_label is invalid")

    raw_currency = payload.get("currency")
    currency = None if raw_currency is None else str(raw_currency).strip().upper()
    if currency is not None and not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("currency must be an ISO 4217 code")
    currency_state = "declared" if currency is not None else "indeterminate"
    timing_state = str(payload.get("timing_state", "")).strip()
    if timing_state not in {"declared", "indeterminate"}:
        raise ValueError("timing_state is invalid")
    observed_at_raw = payload.get("observed_at")
    observed_at = None
    if observed_at_raw is not None:
        parsed_observed_at = datetime.fromisoformat(str(observed_at_raw))
        if parsed_observed_at.tzinfo is None:
            raise ValueError("observed_at must include timezone")
        observed_at = parsed_observed_at.astimezone(UTC).isoformat()
    if timing_state == "declared" and observed_at is None:
        raise ValueError("declared timing requires observed_at")
    if timing_state == "indeterminate" and observed_at is not None:
        raise ValueError("indeterminate timing cannot claim observed_at")
    observation_time_text = str(payload.get("observation_time_text", "")).strip()
    if not observation_time_text or len(observation_time_text) > 200:
        raise ValueError("observation_time_text is invalid")
    source_type = str(payload.get("source_type", "")).strip()
    if source_type != "user_supplied_screenshot":
        raise ValueError("source_type is unsupported")
    source_sha256 = str(payload.get("source_sha256", "")).strip().lower()
    if not SHA256_PATTERN.fullmatch(source_sha256):
        raise ValueError("source_sha256 is invalid")

    raw_positions = payload.get("positions")
    if not isinstance(raw_positions, list) or not raw_positions:
        raise ValueError("positions must be a non-empty list")
    normalized: list[dict[str, str]] = []
    seen_security_ids: set[str] = set()
    for raw in raw_positions:
        if not isinstance(raw, Mapping):
            raise ValueError("position must be an object")
        security_id = str(raw.get("security_id", ""))
        uuid.UUID(security_id)
        if security_id in seen_security_ids:
            raise ValueError("security_id must be unique within snapshot")
        seen_security_ids.add(security_id)
        ticker = str(raw.get("ticker", "")).strip().upper()
        if not TICKER_PATTERN.fullmatch(ticker):
            raise ValueError("ticker has invalid format")
        quantity = _decimal(raw.get("quantity"), field="quantity")
        average_cost = _decimal(raw.get("average_cost"), field="average_cost")
        observed_price = _decimal(raw.get("observed_price"), field="observed_price")
        market_value = _decimal(
            raw.get("observed_market_value"), field="observed_market_value"
        )
        if abs(market_value - (quantity * observed_price)) > Decimal("0.01"):
            raise ValueError("observed_market_value does not reconcile")
        normalized.append(
            {
                "security_id": security_id,
                "ticker": ticker,
                "quantity": _canonical_decimal(quantity),
                "average_cost": _canonical_decimal(average_cost),
                "observed_price": _canonical_decimal(observed_price),
                "observed_market_value": _canonical_decimal(market_value),
            }
        )
    normalized.sort(key=lambda item: (item["ticker"], item["security_id"]))

    canonical_payload = {
        "portfolio_key": portfolio_key,
        "account_label": account_label,
        "currency": currency,
        "currency_state": currency_state,
        "observed_at": observed_at,
        "timing_state": timing_state,
        "observation_time_text": observation_time_text,
        "source_type": source_type,
        "source_sha256": source_sha256,
        "positions": normalized,
    }
    canonical_body = json.dumps(
        canonical_payload, sort_keys=True, separators=(",", ":")
    ).encode()
    content_sha256 = hashlib.sha256(canonical_body).hexdigest()
    snapshot_id = stable_id(
        operator_id,
        "holding-snapshot",
        f"{portfolio_key}:{content_sha256}",
    )
    positions: list[HoldingPosition] = []
    total_market_value = Decimal("0")
    total_cost_basis = Decimal("0")
    for ordinal, item in enumerate(normalized, start=1):
        quantity = Decimal(item["quantity"])
        average_cost = Decimal(item["average_cost"])
        market_value = Decimal(item["observed_market_value"])
        cost_basis = quantity * average_cost
        unrealized_pnl = market_value - cost_basis
        total_market_value += market_value
        total_cost_basis += cost_basis
        positions.append(
            HoldingPosition(
                position_id=stable_id(
                    operator_id,
                    "holding-position",
                    f"{snapshot_id}:{item['security_id']}",
                ),
                operator_id=operator_id,
                snapshot_id=snapshot_id,
                security_id=item["security_id"],
                ordinal=ordinal,
                ticker=item["ticker"],
                quantity=item["quantity"],
                average_cost=item["average_cost"],
                observed_price=item["observed_price"],
                observed_market_value=item["observed_market_value"],
                cost_basis=_canonical_decimal(cost_basis),
                unrealized_pnl=_canonical_decimal(unrealized_pnl),
            )
        )
    return HoldingSnapshot(
        snapshot_id=snapshot_id,
        operator_id=operator_id,
        portfolio_key=portfolio_key,
        account_label=account_label,
        currency=currency,
        currency_state=currency_state,
        observed_at=observed_at,
        timing_state=timing_state,
        observation_time_text=observation_time_text,
        source_type=source_type,
        source_sha256=source_sha256,
        captured_at=captured_at.astimezone(UTC).isoformat(),
        content_sha256=content_sha256,
        position_count=len(positions),
        total_market_value=_canonical_decimal(total_market_value),
        total_cost_basis=_canonical_decimal(total_cost_basis),
        total_unrealized_pnl=_canonical_decimal(total_market_value - total_cost_basis),
        positions=tuple(positions),
    )

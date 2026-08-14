from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Sequence

from workers.ids import stable_id

from .moomoo import MoomooPosition
from .symbols import CanonicalSecurityCandidate, reconcile_moomoo_symbol


SUPPORTED_PROVIDERS = {"moomoo_opend", "moomoo_rest"}
SUPPORTED_TRANSPORTS = {"opend_local_tcp", "web_rest_oauth"}
CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True, slots=True)
class PortfolioPosition:
    position_id: str
    snapshot_id: str
    ordinal: int
    provider_symbol: str
    display_name: str
    canonical_ticker: str
    security_id: str | None
    mapping_state: Literal["mapped", "unmapped", "ambiguous"]
    primary_listing_exchange: str | None
    position_side: str
    quantity: str
    available_quantity: str
    average_cost: str | None
    average_cost_state: Literal["reported", "provider_invalid"]
    last_price: str
    market_value: str
    currency: str
    unrealized_pnl: str | None
    unrealized_pnl_state: Literal["reported", "provider_invalid"]
    precision_risk_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    contract_version: str
    snapshot_id: str
    operator_id: str
    provider: str
    provider_transport: str
    account_ref: str
    captured_at: str
    content_sha256: str
    position_count: int
    unmapped_count: int
    ambiguous_count: int
    precision_risk_count: int
    read_only_assurance: str
    positions: tuple[PortfolioPosition, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_portfolio_snapshot(
    *,
    operator_id: str,
    provider: str,
    provider_transport: str,
    provider_account_id: str,
    positions: Sequence[MoomooPosition],
    candidates: Sequence[CanonicalSecurityCandidate],
    captured_at: datetime,
) -> PortfolioSnapshot:
    normalized_operator_id = str(uuid.UUID(operator_id))
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError("portfolio provider is unsupported")
    if provider_transport not in SUPPORTED_TRANSPORTS:
        raise ValueError("portfolio provider transport is unsupported")
    if captured_at.tzinfo is None:
        raise ValueError("portfolio capture time must include timezone")
    normalized_account_id = provider_account_id.strip()
    if not normalized_account_id:
        raise ValueError("portfolio provider account ID is required")
    account_ref = stable_id(
        normalized_operator_id,
        "portfolio-account",
        f"{provider}:{normalized_account_id}",
    )

    normalized_positions: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    for source in positions:
        if source.account_id != normalized_account_id:
            raise ValueError("portfolio position account does not match snapshot")
        reconciliation = reconcile_moomoo_symbol(
            source.code,
            candidates=candidates,
        )
        position_side = source.position_side.strip().upper()
        if position_side not in {"LONG", "SHORT"}:
            raise ValueError("portfolio position side is unsupported")
        position_key = (reconciliation.provider_symbol, position_side)
        if position_key in seen_keys:
            raise ValueError("portfolio position identity is duplicated")
        seen_keys.add(position_key)
        currency = source.currency.strip().upper()
        if not CURRENCY_PATTERN.fullmatch(currency):
            raise ValueError("portfolio position currency is invalid")
        display_name = source.stock_name.strip()
        if (
            not display_name
            or len(display_name) > 200
            or any("\ud800" <= character <= "\udfff" for character in display_name)
        ):
            raise ValueError("portfolio position display name is invalid")
        normalized_positions.append(
            {
                "provider_symbol": reconciliation.provider_symbol,
                "display_name": display_name,
                "canonical_ticker": reconciliation.canonical_ticker,
                "security_id": reconciliation.security_id,
                "mapping_state": reconciliation.mapping_state,
                "primary_listing_exchange": reconciliation.primary_listing_exchange,
                "position_side": position_side,
                "quantity": _canonical_decimal(
                    source.qty, field="quantity", positive=True
                ),
                "available_quantity": _canonical_decimal(
                    source.can_sell_qty,
                    field="available_quantity",
                    positive=False,
                ),
                "average_cost": (
                    _canonical_decimal(
                        source.cost_price,
                        field="average_cost",
                        positive=False,
                    )
                    if source.cost_price_valid and source.cost_price is not None
                    else None
                ),
                "average_cost_state": (
                    "reported" if source.cost_price_valid else "provider_invalid"
                ),
                "last_price": _canonical_decimal(
                    source.nominal_price,
                    field="last_price",
                    positive=True,
                ),
                "market_value": _canonical_decimal(
                    source.market_val,
                    field="market_value",
                    positive=False,
                ),
                "currency": currency,
                "unrealized_pnl": (
                    _canonical_decimal(
                        source.pl_val,
                        field="unrealized_pnl",
                        positive=False,
                        allow_negative=True,
                    )
                    if source.pl_val_valid and source.pl_val is not None
                    else None
                ),
                "unrealized_pnl_state": (
                    "reported" if source.pl_val_valid else "provider_invalid"
                ),
                "precision_risk_fields": tuple(sorted(source.precision_risk_fields)),
            }
        )
    normalized_positions.sort(
        key=lambda item: (item["provider_symbol"], item["position_side"])
    )
    canonical_payload = {
        "account_ref": account_ref,
        "contract_version": "portfolio_snapshot.v1",
        "positions": normalized_positions,
        "provider": provider,
        "provider_transport": provider_transport,
        "read_only_assurance": "read_only_scopes_no_order_surface",
    }
    content_sha256 = hashlib.sha256(
        json.dumps(
            canonical_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    snapshot_id = stable_id(
        normalized_operator_id,
        "portfolio-snapshot",
        f"{account_ref}:{content_sha256}",
    )
    materialized = tuple(
        PortfolioPosition(
            position_id=stable_id(
                normalized_operator_id,
                "portfolio-position",
                (f"{snapshot_id}:{item['provider_symbol']}:{item['position_side']}"),
            ),
            snapshot_id=snapshot_id,
            ordinal=ordinal,
            **item,
        )
        for ordinal, item in enumerate(normalized_positions, start=1)
    )
    return PortfolioSnapshot(
        contract_version="portfolio_snapshot.v1",
        snapshot_id=snapshot_id,
        operator_id=normalized_operator_id,
        provider=provider,
        provider_transport=provider_transport,
        account_ref=account_ref,
        captured_at=captured_at.astimezone(UTC).isoformat(),
        content_sha256=content_sha256,
        position_count=len(materialized),
        unmapped_count=sum(
            position.mapping_state == "unmapped" for position in materialized
        ),
        ambiguous_count=sum(
            position.mapping_state == "ambiguous" for position in materialized
        ),
        precision_risk_count=sum(
            len(position.precision_risk_fields) for position in materialized
        ),
        read_only_assurance="read_only_scopes_no_order_surface",
        positions=materialized,
    )


def _canonical_decimal(
    value: object,
    *,
    field: str,
    positive: bool,
    allow_negative: bool = False,
) -> str:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{field} must be an exact decimal") from error
    if not parsed.is_finite():
        raise ValueError(f"{field} must be finite")
    if positive and parsed <= 0:
        raise ValueError(f"{field} must be positive")
    if not positive and not allow_negative and parsed < 0:
        raise ValueError(f"{field} must be nonnegative")
    normalized = format(parsed, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return "0" if normalized in {"-0", ""} else normalized

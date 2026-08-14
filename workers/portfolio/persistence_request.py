from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from workers.ids import stable_id

from .snapshot import PortfolioPosition, PortfolioSnapshot


RPC_NAME = "iros_persist_portfolio_broker_snapshot"


@dataclass(frozen=True, slots=True)
class PortfolioPersistenceRequest:
    rpc_name: str
    parameters: dict[str, Any]
    idempotency_key: str
    request_sha256: str
    canonical_json: str


def build_portfolio_persistence_request(
    snapshot: PortfolioSnapshot,
    *,
    checked_at: datetime,
    account_label: str | None = None,
    account_type: str | None = None,
    security_firm: str | None = None,
) -> PortfolioPersistenceRequest:
    if checked_at.tzinfo is None:
        raise ValueError("portfolio persistence check time must include timezone")
    operator_id = str(uuid.UUID(snapshot.operator_id))
    account_ref = str(uuid.UUID(snapshot.account_ref))
    snapshot_id = str(uuid.UUID(snapshot.snapshot_id))
    try:
        captured_at = datetime.fromisoformat(snapshot.captured_at)
    except ValueError as error:
        raise ValueError("portfolio snapshot capture time is invalid") from error
    if captured_at.tzinfo is None:
        raise ValueError("portfolio snapshot capture time must include timezone")
    if captured_at > checked_at:
        raise ValueError("portfolio snapshot capture follows persistence check")

    positions = [_canonical_position(position) for position in snapshot.positions]
    canonical_snapshot_payload = {
        "account_ref": account_ref,
        "contract_version": snapshot.contract_version,
        "positions": positions,
        "provider": snapshot.provider,
        "provider_transport": snapshot.provider_transport,
        "read_only_assurance": snapshot.read_only_assurance,
    }
    content_sha256 = _sha256(canonical_snapshot_payload)
    if content_sha256 != snapshot.content_sha256:
        raise ValueError("portfolio snapshot content hash does not match")
    expected_snapshot_id = stable_id(
        operator_id,
        "portfolio-snapshot",
        f"{account_ref}:{content_sha256}",
    )
    if snapshot_id != expected_snapshot_id:
        raise ValueError("portfolio snapshot identity does not match content")

    account = {
        "account_label": _optional_text(account_label),
        "account_ref": account_ref,
        "account_type": _optional_text(account_type),
        "provider": snapshot.provider,
        "provider_transport": snapshot.provider_transport,
        "security_firm": _optional_text(security_firm),
    }
    snapshot_payload = {
        "ambiguous_count": snapshot.ambiguous_count,
        "captured_at": snapshot.captured_at,
        "content_sha256": content_sha256,
        "contract_version": snapshot.contract_version,
        "expected_position_count": snapshot.position_count,
        "precision_risk_count": snapshot.precision_risk_count,
        "read_only_assurance": snapshot.read_only_assurance,
        "snapshot_id": snapshot_id,
        "unmapped_count": snapshot.unmapped_count,
    }
    idempotency_key = f"portfolio-save:{content_sha256}:{account_ref}"
    request_payload = {
        "account": account,
        "idempotency_key": idempotency_key,
        "operator_id": operator_id,
        "positions": positions,
        "snapshot": snapshot_payload,
    }
    canonical_json = _canonical_json(request_payload)
    request_sha256 = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    return PortfolioPersistenceRequest(
        rpc_name=RPC_NAME,
        parameters={
            "p_account": account,
            "p_checked_at": checked_at.astimezone(UTC).isoformat(),
            "p_idempotency_key": idempotency_key,
            "p_operator_id": operator_id,
            "p_positions": positions,
            "p_request_sha256": request_sha256,
            "p_snapshot": snapshot_payload,
        },
        idempotency_key=idempotency_key,
        request_sha256=request_sha256,
        canonical_json=canonical_json,
    )


def _canonical_position(position: PortfolioPosition) -> dict[str, Any]:
    return {
        "available_quantity": position.available_quantity,
        "average_cost": position.average_cost,
        "average_cost_state": position.average_cost_state,
        "canonical_ticker": position.canonical_ticker,
        "currency": position.currency,
        "display_name": position.display_name,
        "last_price": position.last_price,
        "mapping_state": position.mapping_state,
        "market_value": position.market_value,
        "position_side": position.position_side,
        "precision_risk_fields": list(position.precision_risk_fields),
        "primary_listing_exchange": position.primary_listing_exchange,
        "provider_symbol": position.provider_symbol,
        "quantity": position.quantity,
        "security_id": position.security_id,
        "unrealized_pnl": position.unrealized_pnl,
        "unrealized_pnl_state": position.unrealized_pnl_state,
    }


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        raise ValueError("portfolio account metadata must not be blank")
    return normalized

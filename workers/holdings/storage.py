from __future__ import annotations

from typing import Any, Mapping, Protocol
from urllib.parse import urlencode

from workers.sec.storage import (
    EvidenceStorageError,
    JsonResponse,
    SupabaseStorageSettings,
    UrllibJsonTransport,
)

from .models import HoldingSnapshot


class BatchJsonTransport(Protocol):
    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Any = None,
    ) -> JsonResponse: ...


class SupabaseHoldingsStore:
    def __init__(
        self,
        settings: SupabaseStorageSettings,
        *,
        transport: BatchJsonTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport or UrllibJsonTransport(settings.timeout_seconds)

    def persist(self, snapshot: HoldingSnapshot) -> None:
        records: tuple[tuple[str, Any], ...] = (
            (
                "iros_holding_snapshots",
                {
                    "id": snapshot.snapshot_id,
                    "operator_id": snapshot.operator_id,
                    "portfolio_key": snapshot.portfolio_key,
                    "account_label": snapshot.account_label,
                    "currency": snapshot.currency,
                    "currency_state": snapshot.currency_state,
                    "observed_at": snapshot.observed_at,
                    "timing_state": snapshot.timing_state,
                    "observation_time_text": snapshot.observation_time_text,
                    "source_type": snapshot.source_type,
                    "source_sha256": snapshot.source_sha256,
                    "captured_at": snapshot.captured_at,
                    "content_sha256": snapshot.content_sha256,
                    "expected_position_count": snapshot.position_count,
                    "total_market_value": snapshot.total_market_value,
                    "total_cost_basis": snapshot.total_cost_basis,
                    "total_unrealized_pnl": snapshot.total_unrealized_pnl,
                },
            ),
            (
                "iros_holding_positions",
                [
                    {
                        "id": position.position_id,
                        "operator_id": position.operator_id,
                        "snapshot_id": position.snapshot_id,
                        "security_id": position.security_id,
                        "ordinal": position.ordinal,
                        "symbol_observed": position.ticker,
                        "quantity": position.quantity,
                        "average_cost": position.average_cost,
                        "observed_price": position.observed_price,
                        "observed_market_value": position.observed_market_value,
                    }
                    for position in snapshot.positions
                ],
            ),
        )
        for table, payload in records:
            query = urlencode({"on_conflict": "operator_id,id"})
            response = self.transport.request_json(
                "POST",
                f"{self.settings.url.rstrip('/')}/rest/v1/{table}?{query}",
                headers={
                    "Content-Type": "application/json",
                    "Prefer": "resolution=ignore-duplicates,return=minimal",
                    "apikey": self.settings.secret_key,
                },
                payload=payload,
            )
            if response.status not in (200, 201, 204):
                raise EvidenceStorageError(
                    f"holdings store returned HTTP {response.status} for {table}"
                )

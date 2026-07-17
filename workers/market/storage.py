from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from workers.sec.storage import (
    EvidenceStorageError,
    JsonTransport,
    SupabaseStorageSettings,
    UrllibJsonTransport,
)

from .models import MarketSnapshot


class SupabaseMarketStore:
    def __init__(
        self,
        settings: SupabaseStorageSettings,
        *,
        transport: JsonTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport or UrllibJsonTransport(settings.timeout_seconds)

    def persist(self, snapshot: MarketSnapshot) -> None:
        for table, record in self._records(snapshot):
            query = urlencode({"on_conflict": "id"})
            url = f"{self.settings.url.rstrip('/')}/rest/v1/{table}?{query}"
            response = self.transport.request_json(
                "POST",
                url,
                headers={
                    "Content-Type": "application/json",
                    "Prefer": "resolution=ignore-duplicates,return=minimal",
                    "apikey": self.settings.secret_key,
                },
                payload=record,
            )
            if response.status not in (200, 201, 204):
                raise EvidenceStorageError(
                    f"market store returned HTTP {response.status} for {table}"
                )

    @staticmethod
    def _records(snapshot: MarketSnapshot) -> list[tuple[str, dict[str, Any]]]:
        return [
            (
                "iros_research_runs",
                {
                    "id": snapshot.research_run_id,
                    "operator_id": snapshot.operator_id,
                    "ticker": snapshot.ticker,
                    "run_type": "market_snapshot",
                    "trigger_type": "manual",
                    "status": "completed",
                    "idempotency_key": snapshot.idempotency_key,
                    "started_at": snapshot.retrieved_at,
                    "finished_at": snapshot.retrieved_at,
                },
            ),
            (
                "iros_market_snapshots",
                {
                    "id": snapshot.snapshot_id,
                    "operator_id": snapshot.operator_id,
                    "research_run_id": snapshot.research_run_id,
                    "ticker": snapshot.ticker,
                    "provider": snapshot.provider,
                    "exchange": snapshot.exchange,
                    "currency": snapshot.currency,
                    "market_time": snapshot.market_time,
                    "close": snapshot.close,
                    "previous_close": snapshot.previous_close,
                    "change": snapshot.change,
                    "percent_change": snapshot.percent_change,
                    "volume": snapshot.volume,
                    "is_market_open": snapshot.is_market_open,
                    "source_url": snapshot.source_url,
                    "retrieved_at": snapshot.retrieved_at,
                    "response_sha256": snapshot.response_sha256,
                },
            ),
        ]

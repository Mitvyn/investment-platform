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
            query = urlencode({"on_conflict": "operator_id,id"})
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
        if snapshot.bars:
            self._finalize_series(snapshot)

    def _finalize_series(self, snapshot: MarketSnapshot) -> None:
        response = self.transport.request_json(
            "POST",
            (
                f"{self.settings.url.rstrip('/')}/rest/v1/"
                "rpc/iros_finalize_market_series"
            ),
            headers={
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
                "apikey": self.settings.secret_key,
            },
            payload={
                "selected_operator_id": snapshot.operator_id,
                "selected_series_id": snapshot.series_id,
            },
        )
        if response.status not in (200, 201, 204):
            raise EvidenceStorageError(
                "market store returned HTTP "
                f"{response.status} for iros_finalize_market_series"
            )

    @staticmethod
    def _records(snapshot: MarketSnapshot) -> list[tuple[str, dict[str, Any]]]:
        is_series = bool(snapshot.bars)
        records: list[tuple[str, dict[str, Any]]] = [
            (
                "iros_research_runs",
                {
                    "id": snapshot.research_run_id,
                    "operator_id": snapshot.operator_id,
                    "ticker": snapshot.ticker,
                    "run_type": "market_snapshot",
                    "trigger_type": "manual",
                    "status": "running" if is_series else "completed",
                    "persistence_state": "draft" if is_series else "complete",
                    "idempotency_key": snapshot.idempotency_key,
                    "started_at": snapshot.retrieved_at,
                    "finished_at": None if is_series else snapshot.retrieved_at,
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
        if snapshot.bars:
            if snapshot.security_id is None or snapshot.series_id is None:
                raise EvidenceStorageError(
                    "OHLCV history requires security and series identity"
                )
            records.append(
                (
                    "iros_market_series",
                    {
                        "id": snapshot.series_id,
                        "operator_id": snapshot.operator_id,
                        "security_id": snapshot.security_id,
                        "research_run_id": snapshot.research_run_id,
                        "snapshot_id": snapshot.snapshot_id,
                        "ticker": snapshot.ticker,
                        "provider": snapshot.provider,
                        "provider_config_version": "yfinance-1.5.1-unadjusted-daily-v1",
                        "exchange": snapshot.exchange,
                        "currency": snapshot.currency,
                        "interval": "1d",
                        "adjustment_status": "unadjusted",
                        "session_start": snapshot.bars[0].session_date,
                        "session_end": snapshot.bars[-1].session_date,
                        "expected_bar_count": len(snapshot.bars),
                        "persistence_state": "draft",
                        "source_url": snapshot.source_url,
                        "retrieved_at": snapshot.retrieved_at,
                        "response_sha256": snapshot.response_sha256,
                    },
                )
            )
        records.extend(
            (
                "iros_market_bars",
                {
                    "id": bar.bar_id,
                    "operator_id": bar.operator_id,
                    "security_id": bar.security_id,
                    "research_run_id": bar.research_run_id,
                    "snapshot_id": bar.snapshot_id,
                    "series_id": bar.series_id,
                    "ticker": bar.ticker,
                    "provider": bar.provider,
                    "exchange": bar.exchange,
                    "currency": bar.currency,
                    "session_date": bar.session_date,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                    "dividends": bar.dividends,
                    "stock_splits": bar.stock_splits,
                    "adjustment_status": "unadjusted",
                    "session_status": "completed",
                    "source_url": bar.source_url,
                    "retrieved_at": bar.retrieved_at,
                    "bar_sha256": bar.bar_sha256,
                },
            )
            for bar in snapshot.bars
        )
        return records

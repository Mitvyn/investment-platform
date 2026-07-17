from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    operator_id: str
    research_run_id: str
    snapshot_id: str
    idempotency_key: str
    ticker: str
    provider: str
    exchange: str
    currency: str
    market_time: str
    close: float
    previous_close: float
    change: float
    percent_change: float
    volume: int | None
    is_market_open: bool
    source_url: str
    retrieved_at: str
    response_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

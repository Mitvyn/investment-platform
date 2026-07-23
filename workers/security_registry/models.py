from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RegisteredSecurity:
    operator_id: str
    security_id: str
    cik: str
    issuer_name: str
    ticker: str
    primary_listing_exchange: str
    source_url: str
    retrieved_at: str
    response_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

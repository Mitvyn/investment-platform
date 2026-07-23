from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import re
from uuid import UUID


_CIK_PATTERN = re.compile(r"^\d{10}$")


@dataclass(frozen=True, slots=True)
class PrimarySourceRequest:
    operator_id: str
    security_id: str
    cik: str
    issuer_name: str
    primary_listing_exchange: str
    as_of_cutoff: datetime

    def __post_init__(self) -> None:
        for field_name in ("operator_id", "security_id"):
            value = getattr(self, field_name)
            try:
                canonical = str(UUID(value))
            except (AttributeError, TypeError, ValueError) as error:
                raise ValueError(f"{field_name} must be a UUID") from error
            object.__setattr__(self, field_name, canonical)
        if _CIK_PATTERN.fullmatch(self.cik) is None:
            raise ValueError("CIK must contain exactly 10 digits")
        if not self.issuer_name.strip():
            raise ValueError("issuer name is required")
        if not self.primary_listing_exchange.strip():
            raise ValueError("primary listing exchange is required")
        if (
            self.as_of_cutoff.tzinfo is None
            or self.as_of_cutoff.utcoffset() is None
        ):
            raise ValueError("source cutoff must include timezone")
        object.__setattr__(
            self,
            "as_of_cutoff",
            self.as_of_cutoff.astimezone(UTC),
        )


__all__ = ["PrimarySourceRequest"]

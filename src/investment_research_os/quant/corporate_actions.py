"""Provider-neutral immutable stock-split inputs for Quant.

This first corporate-action contract supports effective-session stock splits
only. Cash dividends stay unsupported until entitlement and payment timing can
be represented without inventing cash on the ex-date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import gcd

from investment_research_os.quant.bars import (
    QuantContractError,
    canonical_security_id,
    canonical_sha256,
)


@dataclass(frozen=True, slots=True)
class StockSplit:
    """One share-count conversion effective before a session opens."""

    effective_session: date
    new_shares: int
    old_shares: int

    def __post_init__(self) -> None:
        if type(self.effective_session) is not date:
            raise QuantContractError("split effective_session must be a date")
        for field in ("new_shares", "old_shares"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise QuantContractError(f"split {field} must be a positive integer")
        divisor = gcd(self.new_shares, self.old_shares)
        new_shares = self.new_shares // divisor
        old_shares = self.old_shares // divisor
        if new_shares == old_shares:
            raise QuantContractError("split ratio must change the share count")
        object.__setattr__(self, "new_shares", new_shares)
        object.__setattr__(self, "old_shares", old_shares)

    def to_record(self) -> dict[str, object]:
        return {
            "effective_session": self.effective_session.isoformat(),
            "new_shares": self.new_shares,
            "old_shares": self.old_shares,
            "type": "stock_split",
        }


@dataclass(frozen=True, slots=True)
class CorporateActionSet:
    """Explicit immutable corporate actions for one canonical security."""

    security_id: str
    source: str
    actions: tuple[StockSplit, ...]

    def __post_init__(self) -> None:
        canonical_security_id(self.security_id)
        if not isinstance(self.source, str) or not self.source.strip():
            raise QuantContractError("corporate-action source must be non-empty")
        actions = tuple(self.actions)
        object.__setattr__(self, "actions", actions)
        for action in actions:
            if not isinstance(action, StockSplit):
                raise QuantContractError("unsupported corporate action")
        for earlier, later in zip(actions, actions[1:]):
            if later.effective_session <= earlier.effective_session:
                raise QuantContractError(
                    "corporate actions must have strictly increasing sessions"
                )

    def to_record(self) -> dict[str, object]:
        return {
            "actions": [action.to_record() for action in self.actions],
            "security_id": self.security_id,
            "source": self.source,
        }

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.to_record())

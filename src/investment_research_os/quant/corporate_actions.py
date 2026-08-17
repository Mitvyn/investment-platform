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
        _check_split(self, coerce=True)

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
        _check_action_set(self, coerce=True)

    def to_record(self) -> dict[str, object]:
        return {
            "actions": [action.to_record() for action in self.actions],
            "security_id": self.security_id,
            "source": self.source,
        }

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.to_record())


def _check_split(split: "StockSplit", *, coerce: bool) -> None:
    """Every ``StockSplit`` invariant, shared by construction and revalidation.

    At construction a caller may pass 4:2 and have it stored reduced as 2:1. At
    runtime the stored form must already be canonical: reducing a tampered
    ratio would turn an invalid object back into a valid one, which is exactly
    the laundering this check exists to stop.
    """

    if type(split.effective_session) is not date:
        raise QuantContractError("split effective_session must be a date")
    for field in ("new_shares", "old_shares"):
        value = getattr(split, field)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise QuantContractError(f"split {field} must be a positive integer")
    divisor = gcd(split.new_shares, split.old_shares)
    new_shares = split.new_shares // divisor
    old_shares = split.old_shares // divisor
    if new_shares == old_shares:
        raise QuantContractError("split ratio must change the share count")
    if coerce:
        object.__setattr__(split, "new_shares", new_shares)
        object.__setattr__(split, "old_shares", old_shares)
    elif divisor != 1:
        raise QuantContractError(
            f"split ratio {split.new_shares}:{split.old_shares} is not stored in "
            f"lowest terms; a valid split would hold {new_shares}:{old_shares}"
        )


def _check_action_set(action_set: "CorporateActionSet", *, coerce: bool) -> None:
    """Every ``CorporateActionSet`` invariant, including each action it holds."""

    canonical_security_id(action_set.security_id)
    if not isinstance(action_set.source, str) or not action_set.source.strip():
        raise QuantContractError("corporate-action source must be non-empty")
    if coerce:
        actions = tuple(action_set.actions)
        object.__setattr__(action_set, "actions", actions)
    else:
        if type(action_set.actions) is not tuple:
            raise QuantContractError(
                f"actions must be a stored tuple, got "
                f"{type(action_set.actions).__name__}"
            )
        actions = action_set.actions
    for action in actions:
        if not isinstance(action, StockSplit):
            raise QuantContractError("unsupported corporate action")
        if not coerce:
            _check_split(action, coerce=False)
    for earlier, later in zip(actions, actions[1:]):
        if later.effective_session <= earlier.effective_session:
            raise QuantContractError(
                "corporate actions must have strictly increasing sessions"
            )


def revalidate_corporate_action_set(action_set: object) -> "CorporateActionSet":
    """Re-check an action set and every action in it, returning it unchanged.

    Raises ``QuantContractError`` and nothing else. No coercion, no repair, no
    I/O.
    """

    if not isinstance(action_set, CorporateActionSet):
        raise QuantContractError(
            f"expected a CorporateActionSet, got {type(action_set).__name__}"
        )
    _check_action_set(action_set, coerce=False)
    return action_set

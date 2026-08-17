"""Deterministic liquidity limits for offline Quant fills.

The engine applies an execution-session volume cap only after a strategy has
made its decision. The strategy never receives that session's volume, so this
models fill capacity without changing the signal's information set.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Literal

from investment_research_os.quant.bars import (
    QuantContractError,
    canonical_sha256,
    decimal_text,
    quant_decimal_context,
    to_decimal,
)

ParticipationBasis = Literal["execution_bar"]
UnfilledPolicy = Literal["cancel"]
ZeroVolumePolicy = Literal["block", "error"]

_BASIS_POINTS = Decimal("10000")


@dataclass(frozen=True, slots=True)
class ParticipationLimit:
    """Explicit maximum share participation for one execution session."""

    max_participation_bps: Decimal
    volume_basis: ParticipationBasis
    zero_volume_policy: ZeroVolumePolicy
    unfilled_policy: UnfilledPolicy
    min_fill_shares: int

    def __post_init__(self) -> None:
        _check_participation_limit(self, coerce=True)

    def cap_for_volume(self, volume: int) -> int:
        """Conservative whole-share cap for one execution bar's volume."""

        if isinstance(volume, bool) or not isinstance(volume, int) or volume < 0:
            raise QuantContractError("volume must be a non-negative integer")
        with quant_decimal_context():
            cap = Decimal(volume) * self.max_participation_bps / _BASIS_POINTS
            return int(cap.to_integral_value(rounding=ROUND_DOWN))

    def to_record(self) -> dict[str, object]:
        return {
            "max_participation_bps": decimal_text(self.max_participation_bps),
            "min_fill_shares": self.min_fill_shares,
            "unfilled_policy": self.unfilled_policy,
            "volume_basis": self.volume_basis,
            "zero_volume_policy": self.zero_volume_policy,
        }

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.to_record())


def _check_participation_limit(
    limit: "ParticipationLimit", *, coerce: bool
) -> None:
    """Every ``ParticipationLimit`` invariant, shared by both callers.

    A mutated cap is the one that matters most here: above 10000 bps the engine
    would fill more shares than the session traded, which is capacity the market
    never offered.
    """

    raw = limit.max_participation_bps
    if coerce:
        rate = to_decimal(raw, field="max_participation_bps")
    else:
        if type(raw) is not Decimal:
            raise QuantContractError(
                "max_participation_bps must be a stored Decimal, got "
                f"{type(raw).__name__}"
            )
        if not raw.is_finite():
            raise QuantContractError(
                f"max_participation_bps must be finite, got {raw}"
            )
        rate = raw
    if rate < 0 or rate > _BASIS_POINTS:
        raise QuantContractError("max_participation_bps must be between 0 and 10000")
    if coerce:
        object.__setattr__(limit, "max_participation_bps", rate)
    if limit.volume_basis != "execution_bar":
        raise QuantContractError("volume_basis must be execution_bar")
    if limit.zero_volume_policy not in ("block", "error"):
        raise QuantContractError("zero_volume_policy must be block or error")
    if limit.unfilled_policy != "cancel":
        raise QuantContractError("unfilled_policy must be cancel")
    if (
        isinstance(limit.min_fill_shares, bool)
        or not isinstance(limit.min_fill_shares, int)
        or limit.min_fill_shares < 0
    ):
        raise QuantContractError("min_fill_shares must be a non-negative integer")


def revalidate_participation_limit(limit: object) -> "ParticipationLimit":
    """Re-check a participation limit at an execution boundary, unchanged.

    Raises ``QuantContractError`` and nothing else. No coercion, no repair.
    """

    if not isinstance(limit, ParticipationLimit):
        raise QuantContractError(
            f"expected a ParticipationLimit, got {type(limit).__name__}"
        )
    _check_participation_limit(limit, coerce=False)
    return limit

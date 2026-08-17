"""Explicit commission, transaction-cost, and slippage inputs.

Every field is required. A backtest that silently defaults costs to zero
reports a return the operator can never achieve, so the contract forces the
caller to state each one — including stating zero deliberately.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from investment_research_os.quant.bars import (
    QuantContractError,
    PRICE_QUANTUM,
    decimal_text,
    quant_decimal_context,
    to_decimal,
)

Side = Literal["buy", "sell"]

BASIS_POINT = Decimal("0.0001")
CASH_QUANTUM = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class TradeCharges:
    """Cash deducted for one fill, split by cause."""

    commission: Decimal
    transaction_cost: Decimal

    @property
    def total(self) -> Decimal:
        with quant_decimal_context():
            return self.commission + self.transaction_cost

    def to_record(self) -> dict[str, str]:
        return {
            "commission": decimal_text(self.commission),
            "total": decimal_text(self.total),
            "transaction_cost": decimal_text(self.transaction_cost),
        }


@dataclass(frozen=True, slots=True)
class CostModel:
    """Deterministic cost inputs applied to every fill.

    Slippage moves the fill price against the trader: buys fill above the
    reference price, sells below it. Commission is the broker charge;
    ``transaction_cost_bps`` covers exchange, clearing, and regulatory fees
    charged on notional.
    """

    commission_per_share: Decimal
    commission_bps: Decimal
    commission_minimum: Decimal
    transaction_cost_bps: Decimal
    slippage_bps: Decimal

    def __post_init__(self) -> None:
        _check_cost_model(self, coerce=True)

    def fill_price(self, reference: Decimal, side: Side) -> Decimal:
        """Reference price moved against the trader by slippage."""

        if side not in ("buy", "sell"):
            raise QuantContractError(f"unknown side: {side!r}")
        with quant_decimal_context():
            drift = self.slippage_bps * BASIS_POINT
            multiplier = Decimal(1) + drift if side == "buy" else Decimal(1) - drift
            if multiplier <= 0:
                raise QuantContractError(
                    f"slippage_bps {self.slippage_bps} would drive the sell price to zero"
                )
            fill_price = (reference * multiplier).quantize(
                PRICE_QUANTUM, rounding=ROUND_HALF_UP
            )
            if fill_price < PRICE_QUANTUM:
                raise QuantContractError(
                    f"slippage-adjusted fill {fill_price} is below price quantum "
                    f"{PRICE_QUANTUM}"
                )
            return fill_price

    def charges(self, *, quantity: int, fill_price: Decimal) -> TradeCharges:
        """Cash charged for a fill of ``quantity`` shares at ``fill_price``."""

        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise QuantContractError("quantity must be an integer number of shares")
        if quantity <= 0:
            raise QuantContractError(f"quantity must be positive, got {quantity}")
        with quant_decimal_context():
            notional = fill_price * quantity
            commission = max(
                self.commission_per_share * quantity
                + self.commission_bps * BASIS_POINT * notional,
                self.commission_minimum,
            ).quantize(CASH_QUANTUM, rounding=ROUND_HALF_UP)
            transaction_cost = (
                self.transaction_cost_bps * BASIS_POINT * notional
            ).quantize(CASH_QUANTUM, rounding=ROUND_HALF_UP)
            return TradeCharges(
                commission=commission,
                transaction_cost=transaction_cost,
            )

    def to_record(self) -> dict[str, str]:
        return {
            "commission_bps": decimal_text(self.commission_bps),
            "commission_minimum": decimal_text(self.commission_minimum),
            "commission_per_share": decimal_text(self.commission_per_share),
            "slippage_bps": decimal_text(self.slippage_bps),
            "transaction_cost_bps": decimal_text(self.transaction_cost_bps),
        }


_COST_FIELDS = (
    "commission_per_share",
    "commission_bps",
    "commission_minimum",
    "transaction_cost_bps",
    "slippage_bps",
)


def _check_cost_model(costs: "CostModel", *, coerce: bool) -> None:
    """Every ``CostModel`` invariant, shared by construction and revalidation.

    Construction still accepts decimal strings and integers. Runtime
    revalidation requires the stored ``Decimal``: a string or float in a field
    the engine multiplies is tampering, and coercing it would hide that.
    """

    for field in _COST_FIELDS:
        raw = getattr(costs, field)
        if coerce:
            value = to_decimal(raw, field=field)
        else:
            if type(raw) is not Decimal:
                raise QuantContractError(
                    f"{field} must be a stored Decimal, got {type(raw).__name__}"
                )
            if not raw.is_finite():
                raise QuantContractError(f"{field} must be finite, got {raw}")
            value = raw
        if value < 0:
            raise QuantContractError(f"{field} must not be negative, got {value}")
        if coerce:
            object.__setattr__(costs, field, value)


def revalidate_cost_model(costs: object) -> "CostModel":
    """Re-check a cost model at an execution boundary, returning it unchanged.

    Raises ``QuantContractError`` and nothing else. No coercion, no repair.
    """

    if not isinstance(costs, CostModel):
        raise QuantContractError(
            f"expected a CostModel, got {type(costs).__name__}"
        )
    _check_cost_model(costs, coerce=False)
    return costs

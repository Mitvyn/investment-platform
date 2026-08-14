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
    decimal_text,
    to_decimal,
)

Side = Literal["buy", "sell"]

BASIS_POINT = Decimal("0.0001")
CASH_QUANTUM = Decimal("0.01")
PRICE_QUANTUM = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class TradeCharges:
    """Cash deducted for one fill, split by cause."""

    commission: Decimal
    transaction_cost: Decimal

    @property
    def total(self) -> Decimal:
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
        for field in (
            "commission_per_share",
            "commission_bps",
            "commission_minimum",
            "transaction_cost_bps",
            "slippage_bps",
        ):
            value = to_decimal(getattr(self, field), field=field)
            if value < 0:
                raise QuantContractError(f"{field} must not be negative, got {value}")
            object.__setattr__(self, field, value)

    def fill_price(self, reference: Decimal, side: Side) -> Decimal:
        """Reference price moved against the trader by slippage."""

        if side not in ("buy", "sell"):
            raise QuantContractError(f"unknown side: {side!r}")
        drift = self.slippage_bps * BASIS_POINT
        multiplier = Decimal(1) + drift if side == "buy" else Decimal(1) - drift
        if multiplier <= 0:
            raise QuantContractError(
                f"slippage_bps {self.slippage_bps} would drive the sell price to zero"
            )
        return (reference * multiplier).quantize(PRICE_QUANTUM, rounding=ROUND_HALF_UP)

    def charges(self, *, quantity: int, fill_price: Decimal) -> TradeCharges:
        """Cash charged for a fill of ``quantity`` shares at ``fill_price``."""

        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise QuantContractError("quantity must be an integer number of shares")
        if quantity <= 0:
            raise QuantContractError(f"quantity must be positive, got {quantity}")
        notional = fill_price * quantity
        commission = max(
            self.commission_per_share * quantity + self.commission_bps * BASIS_POINT * notional,
            self.commission_minimum,
        ).quantize(CASH_QUANTUM, rounding=ROUND_HALF_UP)
        transaction_cost = (
            self.transaction_cost_bps * BASIS_POINT * notional
        ).quantize(CASH_QUANTUM, rounding=ROUND_HALF_UP)
        return TradeCharges(commission=commission, transaction_cost=transaction_cost)

    def to_record(self) -> dict[str, str]:
        return {
            "commission_bps": decimal_text(self.commission_bps),
            "commission_minimum": decimal_text(self.commission_minimum),
            "commission_per_share": decimal_text(self.commission_per_share),
            "slippage_bps": decimal_text(self.slippage_bps),
            "transaction_cost_bps": decimal_text(self.transaction_cost_bps),
        }

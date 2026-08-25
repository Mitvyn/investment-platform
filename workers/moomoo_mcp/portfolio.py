"""Typed adapters for Moomoo MCP's two published read-only portfolio tools."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Mapping

from workers.portfolio.moomoo import MoomooAccount, MoomooPosition
from workers.moomoo_mcp.envelope import unwrap_expected_mapping

ACCOUNT_TOOL_NAME = "account_authorized_trd_accs"
POSITIONS_TOOL_NAME = "account_positions"
ACCOUNT_FIELDS = frozenset(
    {
        "acc_id",
        "security_firm",
        "enable_market",
        "univs_account_card_number",
        "acc_type",
        "account_card_number",
    }
)
POSITION_FIELDS = frozenset(
    {
        "position_side",
        "code",
        "stock_name",
        "qty",
        "can_sell_qty",
        "currency",
        "nominal_price",
        "cost_price",
        "market_val",
        "pl_ratio",
        "pl_val",
        "today_pl_val",
        "today_buy_qty",
        "today_buy_val",
        "today_sell_qty",
        "today_sell_val",
        "unrealized_pl",
        "realized_pl",
    }
)


class MoomooMcpPortfolioError(ValueError):
    def __init__(self, message: str, *, code: str = "portfolio_invalid") -> None:
        super().__init__(message)
        self.code = code


def normalize_mcp_accounts(raw_result: object) -> tuple[MoomooAccount, ...]:
    rows = _rows(raw_result, "accounts")
    accounts: list[MoomooAccount] = []
    for raw in rows:
        if set(raw) != ACCOUNT_FIELDS:
            raise MoomooMcpPortfolioError("MCP account schema drift detected", code="account_schema_invalid")
        markets = raw["enable_market"]
        if (
            not isinstance(markets, list)
            or not markets
            or any(
                not isinstance(value, str) or not value.isdigit()
                for value in markets
            )
        ):
            raise MoomooMcpPortfolioError("MCP account markets are invalid", code="account_markets_invalid")
        text = {field: str(raw[field]).strip() for field in ACCOUNT_FIELDS - {"enable_market"}}
        if not all(text.values()):
            raise MoomooMcpPortfolioError("MCP account fields are incomplete", code="account_fields_incomplete")
        accounts.append(
            MoomooAccount(
                account_id=text["acc_id"],
                security_firm=text["security_firm"],
                enable_market=tuple(int(value) for value in markets),
                univs_account_card_number=text["univs_account_card_number"],
                acc_type=text["acc_type"],
                account_card_number=text["account_card_number"],
            )
        )
    return tuple(accounts)


def normalize_mcp_positions(
    raw_result: object, *, account_id: str
) -> tuple[MoomooPosition, ...]:
    rows = _rows(raw_result, "positions")
    positions: list[MoomooPosition] = []
    required = {
        "position_side", "code", "stock_name", "currency", "qty",
        "can_sell_qty", "nominal_price", "cost_price", "market_val",
        "pl_ratio", "pl_val", "today_pl_val", "unrealized_pl", "realized_pl",
    }
    for raw in rows:
        if set(raw) - POSITION_FIELDS or not required <= set(raw):
            raise MoomooMcpPortfolioError("MCP position schema drift detected", code="position_schema_invalid")
        text = {
            field: str(raw[field]).strip()
            for field in ("position_side", "code", "stock_name", "currency")
        }
        if not all(text.values()):
            raise MoomooMcpPortfolioError("MCP position fields are incomplete", code="position_fields_incomplete")
        numbers = {
            field: _decimal(raw[field], field)
            for field in required - set(text)
        }
        positions.append(
            MoomooPosition(
                account_id=account_id,
                position_side=text["position_side"].upper(),
                code=text["code"].upper(),
                stock_name=text["stock_name"],
                currency=text["currency"].upper(),
                qty=numbers["qty"],
                can_sell_qty=numbers["can_sell_qty"],
                nominal_price=numbers["nominal_price"],
                cost_price=numbers["cost_price"],
                cost_price_valid=True,
                cost_price_unavailable_reason=None,
                market_val=numbers["market_val"],
                pl_ratio=numbers["pl_ratio"],
                pl_ratio_valid=True,
                pl_ratio_unavailable_reason=None,
                pl_val=numbers["pl_val"],
                pl_val_valid=True,
                pl_val_unavailable_reason=None,
                today_pl_val=numbers["today_pl_val"],
                unrealized_pl=numbers["unrealized_pl"],
                realized_pl=numbers["realized_pl"],
                precision_risk_fields=(),
            )
        )
    return tuple(positions)


def _rows(raw_result: object, key: str) -> list[Mapping[str, object]]:
    if not isinstance(raw_result, Mapping) or raw_result.get("isError", False) is not False:
        raise MoomooMcpPortfolioError("MCP portfolio result is invalid", code="portfolio_result_invalid")
    structured = unwrap_expected_mapping(raw_result.get("structuredContent"), key)
    if structured is None:
        raise MoomooMcpPortfolioError("MCP portfolio envelope is invalid", code=f"{key}_envelope_invalid")
    rows = structured[key]
    if not isinstance(rows, list) or len(rows) > 1_000 or any(not isinstance(row, Mapping) for row in rows):
        raise MoomooMcpPortfolioError("MCP portfolio list is invalid", code=f"{key}_list_invalid")
    return rows


def _decimal(value: object, field: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise MoomooMcpPortfolioError(f"MCP {field} is invalid")
    normalized = str(value).strip()
    try:
        parsed = Decimal(normalized)
    except InvalidOperation:
        raise MoomooMcpPortfolioError(f"MCP {field} is invalid") from None
    if not parsed.is_finite():
        raise MoomooMcpPortfolioError(f"MCP {field} is invalid")
    return normalized


__all__ = [
    "ACCOUNT_TOOL_NAME",
    "POSITIONS_TOOL_NAME",
    "MoomooMcpPortfolioError",
    "normalize_mcp_accounts",
    "normalize_mcp_positions",
]

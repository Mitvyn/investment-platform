from __future__ import annotations

import unittest

from workers.moomoo_mcp.portfolio import (
    MoomooMcpPortfolioError,
    normalize_mcp_accounts,
    normalize_mcp_positions,
)


class MoomooMcpPortfolioTests(unittest.TestCase):
    def test_normalizes_official_account_and_position_contracts(self) -> None:
        accounts = normalize_mcp_accounts(
            {
                "isError": False,
                "structuredContent": {
                    "accounts": [
                        {
                            "acc_id": "account-private-1",
                            "acc_type": "SECURITIES",
                            "account_card_number": "card-private-1",
                            "enable_market": ["2"],
                            "security_firm": "Moomoo",
                            "univs_account_card_number": "universal-private-1",
                        }
                    ]
                },
            }
        )
        positions = normalize_mcp_positions(
            {
                "isError": False,
                "structuredContent": {
                    "positions": [
                        {
                            "can_sell_qty": "5",
                            "code": "US.FRVO",
                            "cost_price": "8.00",
                            "currency": "USD",
                            "market_val": "42.50",
                            "nominal_price": "8.50",
                            "pl_ratio": "0.0625",
                            "pl_val": "2.50",
                            "position_side": "LONG",
                            "qty": "5",
                            "realized_pl": "0",
                            "stock_name": "FRVO",
                            "today_pl_val": "0.50",
                            "unrealized_pl": "2.50",
                        }
                    ]
                },
            },
            account_id=accounts[0].account_id,
        )
        self.assertEqual(accounts[0].account_id, "account-private-1")
        self.assertEqual(positions[0].code, "US.FRVO")
        self.assertEqual(positions[0].cost_price, "8.00")

    def test_rejects_unknown_fields_and_non_finite_values(self) -> None:
        with self.assertRaises(MoomooMcpPortfolioError) as context:
            normalize_mcp_accounts(
                {
                    "isError": False,
                    "structuredContent": {"accounts": [{"acc_id": "x", "unknown": 1}]},
                }
            )
        self.assertEqual(context.exception.code, "account_schema_invalid")
        with self.assertRaises(MoomooMcpPortfolioError):
            normalize_mcp_positions(
                {
                    "isError": False,
                    "structuredContent": {
                        "positions": [
                            {
                                "position_side": "LONG",
                                "code": "US.FRVO",
                                "stock_name": "FRVO",
                                "currency": "USD",
                                "qty": "nan",
                            }
                        ]
                    },
                },
                account_id="private",
            )

    def test_accepts_one_outer_object_around_account_wrapper(self) -> None:
        accounts = normalize_mcp_accounts(
            {
                "isError": False,
                "structuredContent": {
                    "data": {
                        "accounts": [
                            {
                                "acc_id": "account-private-1",
                                "acc_type": "SECURITIES",
                                "account_card_number": "card-private-1",
                                "enable_market": ["2"],
                                "security_firm": "Moomoo",
                                "univs_account_card_number": "universal-private-1",
                            }
                        ]
                    }
                },
            }
        )

        self.assertEqual(accounts[0].account_id, "account-private-1")


if __name__ == "__main__":
    unittest.main()

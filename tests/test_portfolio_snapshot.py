from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import UTC, datetime

from workers.portfolio.moomoo import MoomooPosition
from workers.portfolio.snapshot import build_portfolio_snapshot


@dataclass(frozen=True, slots=True)
class Security:
    security_id: str
    ticker: str
    primary_listing_exchange: str


def _position(code: str, **overrides: object) -> MoomooPosition:
    values: dict[str, object] = {
        "account_id": "private-account-2638",
        "position_side": "LONG",
        "code": code,
        "stock_name": code.removeprefix("US."),
        "currency": "USD",
        "qty": "100.0000",
        "can_sell_qty": "100.0000",
        "nominal_price": "1.8400",
        "cost_price": "1.7200",
        "cost_price_valid": True,
        "cost_price_unavailable_reason": None,
        "market_val": "184.0000",
        "pl_ratio": "6.9767",
        "pl_ratio_valid": True,
        "pl_ratio_unavailable_reason": None,
        "pl_val": "12.0000",
        "pl_val_valid": True,
        "pl_val_unavailable_reason": None,
        "today_pl_val": "0.0000",
        "unrealized_pl": "12.0000",
        "realized_pl": "0.0000",
        "precision_risk_fields": (),
    }
    values.update(overrides)
    return MoomooPosition(**values)  # type: ignore[arg-type]


class PortfolioSnapshotTests(unittest.TestCase):
    def test_rejects_unpaired_surrogate_in_display_name_before_hashing(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "portfolio position display name is invalid",
        ):
            build_portfolio_snapshot(
                operator_id="11111111-1111-4111-8111-111111111111",
                provider="moomoo_rest",
                provider_transport="web_rest_oauth",
                provider_account_id="private-account-2638",
                positions=(_position("US.GANX", stock_name="broken\ud800name"),),
                candidates=(),
                captured_at=datetime(2026, 8, 13, 9, 30, tzinfo=UTC),
            )

    def test_freezes_mapped_and_unmapped_positions_without_raw_account_id(self) -> None:
        operator_id = "11111111-1111-4111-8111-111111111111"
        candidates = (
            Security(
                security_id="22222222-2222-4222-8222-222222222222",
                ticker="GANX",
                primary_listing_exchange="NASDAQ",
            ),
        )
        captured_at = datetime(2026, 8, 12, 9, 30, tzinfo=UTC)

        first = build_portfolio_snapshot(
            operator_id=operator_id,
            provider="moomoo_rest",
            provider_transport="web_rest_oauth",
            provider_account_id="private-account-2638",
            positions=(_position("US.GANX"), _position("US.UNKNOWN")),
            candidates=candidates,
            captured_at=captured_at,
        )
        replay = build_portfolio_snapshot(
            operator_id=operator_id,
            provider="moomoo_rest",
            provider_transport="web_rest_oauth",
            provider_account_id="private-account-2638",
            positions=(_position("US.UNKNOWN"), _position("US.GANX")),
            candidates=candidates,
            captured_at=datetime(2026, 8, 12, 10, 30, tzinfo=UTC),
        )

        self.assertEqual(first.content_sha256, replay.content_sha256)
        self.assertEqual(first.snapshot_id, replay.snapshot_id)
        self.assertEqual(first.position_count, 2)
        self.assertEqual(first.unmapped_count, 1)
        self.assertEqual(
            [position.mapping_state for position in first.positions],
            ["mapped", "unmapped"],
        )
        self.assertEqual(first.positions[0].security_id, candidates[0].security_id)
        self.assertIsNone(first.positions[1].security_id)
        serialized = str(first.as_dict())
        self.assertNotIn("private-account-2638", serialized)
        self.assertEqual(first.positions[0].quantity, "100")
        self.assertEqual(first.positions[0].market_value, "184")
        self.assertEqual(first.positions[0].display_name, "GANX")


if __name__ == "__main__":
    unittest.main()

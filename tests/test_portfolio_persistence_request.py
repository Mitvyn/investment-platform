from __future__ import annotations

import unittest
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from workers.portfolio.moomoo import MoomooPosition
from workers.portfolio.persistence_request import build_portfolio_persistence_request
from workers.portfolio.snapshot import build_portfolio_snapshot


@dataclass(frozen=True, slots=True)
class Security:
    security_id: str
    ticker: str
    primary_listing_exchange: str


def _snapshot(
    *,
    quantity: str = "100.000000000",
    stock_name: str = "Gain Therapeutics",
):
    position = MoomooPosition(
        account_id="private-account-2638",
        position_side="LONG",
        code="US.GANX",
        stock_name=stock_name,
        currency="USD",
        qty=quantity,
        can_sell_qty=quantity,
        nominal_price="1.8400",
        cost_price="1.7200",
        cost_price_valid=True,
        cost_price_unavailable_reason=None,
        market_val="184.0000",
        pl_ratio="6.9767",
        pl_ratio_valid=True,
        pl_ratio_unavailable_reason=None,
        pl_val="12.0000",
        pl_val_valid=True,
        pl_val_unavailable_reason=None,
        today_pl_val="0.0000",
        unrealized_pl="12.0000",
        realized_pl="0.0000",
        precision_risk_fields=(),
    )
    return build_portfolio_snapshot(
        operator_id="11111111-1111-4111-8111-111111111111",
        provider="moomoo_rest",
        provider_transport="web_rest_oauth",
        provider_account_id="private-account-2638",
        positions=(position,),
        candidates=(
            Security(
                security_id="22222222-2222-4222-8222-222222222222",
                ticker="GANX",
                primary_listing_exchange="NASDAQ",
            ),
        ),
        captured_at=datetime(2026, 8, 13, 9, 30, tzinfo=UTC),
    )


class PortfolioPersistenceRequestTests(unittest.TestCase):
    def test_preserves_non_ascii_names_in_canonical_request(self) -> None:
        snapshot = _snapshot(stock_name="Moody’s 制 😀")

        self.assertEqual(
            snapshot.content_sha256,
            "16f943387473e83d30737eba29e45fc80a3dddc6d1ecd1cef1a4b87ef7355b62",
        )
        self.assertEqual(snapshot.snapshot_id, "a9c921ef-83ec-587c-946c-ebc22b4d4906")

        request = build_portfolio_persistence_request(
            snapshot,
            checked_at=datetime(2026, 8, 13, 9, 31, tzinfo=UTC),
        )

        self.assertIn("Moody’s 制 😀", request.canonical_json)
        self.assertNotIn(r"\u2019", request.canonical_json)
        self.assertNotIn(r"\u5236", request.canonical_json)

    def test_builds_content_addressed_single_account_rpc_request(self) -> None:
        snapshot = _snapshot()
        checked_at = datetime(2026, 8, 13, 9, 31, tzinfo=UTC)

        request = build_portfolio_persistence_request(
            snapshot,
            checked_at=checked_at,
            account_label="Moomoo account 1",
            account_type="MARGIN",
            security_firm="Moomoo Financial Singapore",
        )

        self.assertEqual(
            request.idempotency_key,
            f"portfolio-save:{snapshot.content_sha256}:{snapshot.account_ref}",
        )
        self.assertEqual(request.rpc_name, "iros_persist_portfolio_broker_snapshot")
        self.assertEqual(request.parameters["p_operator_id"], snapshot.operator_id)
        self.assertEqual(request.parameters["p_checked_at"], checked_at.isoformat())
        self.assertEqual(
            request.parameters["p_account"]["account_ref"], snapshot.account_ref
        )
        self.assertEqual(
            request.parameters["p_snapshot"]["snapshot_id"], snapshot.snapshot_id
        )
        self.assertEqual(request.parameters["p_positions"][0]["quantity"], "100")
        self.assertEqual(request.parameters["p_positions"][0]["average_cost"], "1.72")
        serialized = request.canonical_json
        self.assertNotIn("private-account-2638", serialized)
        self.assertNotIn("provider_account_id", serialized)

    def test_checked_at_does_not_change_identity(self) -> None:
        snapshot = _snapshot(quantity="0.000000001")
        first = build_portfolio_persistence_request(
            snapshot,
            checked_at=datetime(2026, 8, 13, 9, 31, tzinfo=UTC),
        )
        second = build_portfolio_persistence_request(
            snapshot,
            checked_at=datetime(2026, 8, 13, 10, 31, tzinfo=UTC),
        )

        self.assertEqual(first.idempotency_key, second.idempotency_key)
        self.assertEqual(first.request_sha256, second.request_sha256)
        self.assertEqual(first.parameters["p_positions"][0]["quantity"], "0.000000001")

    def test_changed_positions_change_idempotency_key(self) -> None:
        first = build_portfolio_persistence_request(
            _snapshot(quantity="100"),
            checked_at=datetime(2026, 8, 13, 9, 31, tzinfo=UTC),
        )
        second = build_portfolio_persistence_request(
            _snapshot(quantity="101"),
            checked_at=datetime(2026, 8, 13, 9, 31, tzinfo=UTC),
        )

        self.assertNotEqual(first.idempotency_key, second.idempotency_key)

    def test_rejects_noncanonical_decimal_in_prebuilt_snapshot(self) -> None:
        snapshot = _snapshot()
        forged = replace(
            snapshot,
            positions=(replace(snapshot.positions[0], average_cost="1.50"),),
        )

        with self.assertRaisesRegex(ValueError, "content hash does not match"):
            build_portfolio_persistence_request(
                forged,
                checked_at=datetime(2026, 8, 13, 9, 31, tzinfo=UTC),
            )


if __name__ == "__main__":
    unittest.main()

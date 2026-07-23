from __future__ import annotations

import unittest
import io
import json
import os
import tempfile
from contextlib import redirect_stdout
from datetime import UTC, datetime
from typing import Any, Mapping
from unittest.mock import patch

from workers.holdings.models import build_holding_snapshot
from workers.holdings.__main__ import run
from workers.holdings.storage import SupabaseHoldingsStore
from workers.sec.storage import JsonResponse, SupabaseStorageSettings


class StoreFake:
    def __init__(self) -> None:
        self.requests: list[
            tuple[
                str, str, Mapping[str, str], Mapping[str, Any] | list[Mapping[str, Any]]
            ]
        ] = []

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any] | list[Mapping[str, Any]] | None = None,
    ) -> JsonResponse:
        assert payload is not None
        self.requests.append((method, url, headers, payload))
        return JsonResponse(payload=None, status=201, headers={})


class HoldingSnapshotTests(unittest.TestCase):
    def test_builds_immutable_snapshot_from_exact_operator_observations(self) -> None:
        snapshot = build_holding_snapshot(
            {
                "portfolio_key": "primary-brokerage",
                "account_label": "Primary brokerage",
                "currency": "USD",
                "timing_state": "indeterminate",
                "observation_time_text": "16:00; date and timezone absent",
                "source_type": "user_supplied_screenshot",
                "source_sha256": "a" * 64,
                "positions": [
                    {
                        "security_id": "22222222-2222-4222-8222-222222222222",
                        "ticker": "BETA",
                        "quantity": "10",
                        "average_cost": "2.125",
                        "observed_price": "2.50",
                        "observed_market_value": "25.00",
                    },
                    {
                        "security_id": "11111111-1111-4111-8111-111111111111",
                        "ticker": "ALFA",
                        "quantity": "2",
                        "average_cost": "10.00",
                        "observed_price": "9.50",
                        "observed_market_value": "19.00",
                    },
                ],
            },
            operator_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            captured_at=datetime(2026, 7, 22, 8, 0, tzinfo=UTC),
        )

        self.assertEqual([item.ticker for item in snapshot.positions], ["ALFA", "BETA"])
        self.assertEqual(snapshot.position_count, 2)
        self.assertEqual(snapshot.total_market_value, "44.00")
        self.assertEqual(snapshot.total_cost_basis, "41.250")
        self.assertEqual(snapshot.total_unrealized_pnl, "2.750")
        self.assertEqual(len(snapshot.content_sha256), 64)
        self.assertEqual(snapshot.observed_at, None)

    def test_persists_snapshot_then_positions_as_idempotent_owner_batches(self) -> None:
        snapshot = build_holding_snapshot(
            {
                "portfolio_key": "primary-brokerage",
                "account_label": "Primary brokerage",
                "currency": None,
                "timing_state": "indeterminate",
                "observation_time_text": "16:00; date and timezone absent",
                "source_type": "user_supplied_screenshot",
                "source_sha256": "b" * 64,
                "positions": [
                    {
                        "security_id": "11111111-1111-4111-8111-111111111111",
                        "ticker": "ALFA",
                        "quantity": "2",
                        "average_cost": "10.00",
                        "observed_price": "9.50",
                        "observed_market_value": "19.00",
                    }
                ],
            },
            operator_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            captured_at=datetime(2026, 7, 22, 8, 0, tzinfo=UTC),
        )
        transport = StoreFake()
        store = SupabaseHoldingsStore(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
        )

        store.persist(snapshot)

        self.assertEqual(len(transport.requests), 2)
        self.assertIn(
            "/iros_holding_snapshots?on_conflict=operator_id%2Cid",
            transport.requests[0][1],
        )
        self.assertIn(
            "/iros_holding_positions?on_conflict=operator_id%2Cid",
            transport.requests[1][1],
        )
        self.assertIsInstance(transport.requests[1][3], list)
        self.assertNotIn("Authorization", transport.requests[0][2])

    def test_cli_imports_private_json_without_echoing_position_values(self) -> None:
        payload = {
            "portfolio_key": "primary-brokerage",
            "account_label": "Primary brokerage",
            "currency": None,
            "timing_state": "indeterminate",
            "observation_time_text": "time unavailable",
            "source_type": "user_supplied_screenshot",
            "source_sha256": "c" * 64,
            "positions": [
                {
                    "security_id": "11111111-1111-4111-8111-111111111111",
                    "ticker": "ALFA",
                    "quantity": "777",
                    "average_cost": "10.00",
                    "observed_price": "9.50",
                    "observed_market_value": "7381.50",
                }
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(payload, handle)
            handle.flush()
            output = io.StringIO()
            environment = {
                "IROS_OPERATOR_ID": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "IROS_SUPABASE_URL": "https://example.supabase.co",
                "IROS_SUPABASE_SECRET_KEY": "sb_secret_test",
            }
            with (
                patch.dict(os.environ, environment, clear=True),
                patch("workers.holdings.__main__.SupabaseHoldingsStore") as store,
                redirect_stdout(output),
            ):
                result = run(["import-json", handle.name])

        self.assertEqual(result, 0)
        store.return_value.persist.assert_called_once()
        self.assertNotIn("777", output.getvalue())
        self.assertNotIn("7381.50", output.getvalue())


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from typing import Mapping

from workers.portfolio.moomoo import (
    MoomooClient,
    MoomooRateLimitError,
    MoomooResponse,
    MoomooSettings,
    UrllibMoomooTransport,
)


class FakeTransport:
    def __init__(self, responses: list[MoomooResponse]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, str, Mapping[str, str]]] = []

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
    ) -> MoomooResponse:
        self.requests.append((method, url, headers))
        return self.responses.pop(0)


class MoomooPortfolioAdapterTests(unittest.TestCase):
    """Wire fields from official Web API docs, retrieved 2026-08-12.

    Accounts: https://open.moomoo.com/api/trading/account/get-accounts
    Positions: https://open.moomoo.com/api/trading/account/get-positions
    """

    def _settings_for_assumed_success_fixture(self) -> MoomooSettings:
        return MoomooSettings(scopes=("quote:read", "trade:read"))

    def _position(self, **overrides: object) -> dict[str, object]:
        position: dict[str, object] = {
            "position_side": "LONG",
            "code": "US.GANX",
            "stock_name": "Gain Therapeutics",
            "qty": "100.0000",
            "can_sell_qty": "100.0000",
            "currency": "USD",
            "nominal_price": "1.8400",
            "cost_price": "1.7200",
            "cost_price_valid": True,
            "market_val": "184.0000",
            "pl_ratio": "6.9767",
            "pl_ratio_valid": True,
            "pl_val": "12.0000",
            "pl_val_valid": True,
            "today_pl_val": "0.0000",
            "unrealized_pl": "12.0000",
            "realized_pl": "0.0000",
        }
        position.update(overrides)
        return position

    def _client_for_positions(self, *positions: object) -> MoomooClient:
        return MoomooClient(
            self._settings_for_assumed_success_fixture(),
            access_token="access-token",
            transport=FakeTransport(
                [
                    MoomooResponse(
                        status=200,
                        headers={},
                        payload={"s": "ok", "d": list(positions)},
                    )
                ]
            ),
        )

    def test_settings_require_exact_read_only_scopes(self) -> None:
        settings = MoomooSettings(
            scopes=("trade:read", "quote:read"),
        )

        self.assertEqual(settings.scopes, ("quote:read", "trade:read"))
        with self.assertRaisesRegex(ValueError, "exact read-only scopes"):
            MoomooSettings(scopes=("quote:read", "trade:write"))

    def test_maps_accounts_through_injected_transport(self) -> None:
        transport = FakeTransport(
            [
                MoomooResponse(
                    status=200,
                    headers={},
                    payload={
                        "s": "ok",
                        "d": {
                            "accounts": [
                                {
                                    "account_id": "2638",
                                    "security_firm": "Moomoo Financial Singapore",
                                    "enable_market": [2],
                                    "univs_account_card_number": "****2638",
                                    "acc_type": "margin",
                                    "account_card_number": "****2638",
                                }
                            ]
                        },
                    },
                )
            ]
        )
        client = MoomooClient(
            self._settings_for_assumed_success_fixture(),
            access_token="access-token",
            transport=transport,
        )

        accounts = client.list_accounts()

        self.assertEqual(accounts[0].account_id, "2638")
        self.assertEqual(accounts[0].security_firm, "Moomoo Financial Singapore")
        self.assertEqual(accounts[0].enable_market, (2,))
        self.assertEqual(accounts[0].univs_account_card_number, "****2638")
        self.assertEqual(accounts[0].acc_type, "margin")
        self.assertEqual(accounts[0].account_card_number, "****2638")
        self.assertEqual(transport.requests[0][0], "GET")
        self.assertEqual(
            transport.requests[0][1],
            "https://webapi.moomoo.com/api/v1.0/accounts/authorized_trd_accs",
        )
        self.assertEqual(
            transport.requests[0][2]["Authorization"], "Bearer access-token"
        )

    def test_url_transport_returns_bounded_json_without_logging_bearer(self) -> None:
        calls: list[object] = []

        class Response:
            status = 200
            headers = {"Content-Type": "application/json"}

            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self, limit: int) -> bytes:
                calls.append(limit)
                return b'{"s":"ok","d":[]}'

        def opener(request: object, *, timeout: float, context: object) -> Response:
            calls.extend((request, timeout, context))
            return Response()

        transport = UrllibMoomooTransport(opener=opener, timeout_seconds=7)
        response = transport.request_json(
            "GET",
            "https://webapi.moomoo.com/api/v1.0/accounts/2638/positions",
            headers={"Authorization": "Bearer access-secret"},
        )

        request = calls[0]
        self.assertEqual(response.payload, {"s": "ok", "d": []})
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.headers["Authorization"], "Bearer access-secret")
        self.assertEqual(calls[1], 7)
        self.assertEqual(calls[3], 1_048_577)
        self.assertNotIn("access-secret", repr(transport))

    def test_maps_position_decimal_fields_without_float_conversion(self) -> None:
        transport = FakeTransport(
            [
                MoomooResponse(
                    status=200,
                    headers={},
                    payload={
                        "s": "ok",
                        "d": [self._position()],
                    },
                )
            ]
        )
        client = MoomooClient(
            self._settings_for_assumed_success_fixture(),
            access_token="access-token",
            transport=transport,
        )

        positions = client.list_positions("2638")

        self.assertEqual(positions[0].account_id, "2638")
        self.assertEqual(positions[0].position_side, "LONG")
        self.assertEqual(positions[0].code, "US.GANX")
        self.assertEqual(positions[0].stock_name, "Gain Therapeutics")
        self.assertEqual(positions[0].qty, "100.0000")
        self.assertEqual(positions[0].cost_price, "1.7200")
        self.assertEqual(positions[0].market_val, "184.0000")
        self.assertEqual(positions[0].pl_val, "12.0000")
        self.assertEqual(positions[0].precision_risk_fields, ())
        self.assertEqual(
            transport.requests[0][1],
            "https://webapi.moomoo.com/api/v1.0/accounts/2638/positions",
        )

    def test_surfaces_rate_limit_without_retrying(self) -> None:
        transport = FakeTransport(
            [
                MoomooResponse(
                    status=429,
                    headers={"Retry-After": "12"},
                    payload={"code": 429, "message": "too many requests"},
                )
            ]
        )
        client = MoomooClient(
            MoomooSettings(scopes=("quote:read", "trade:read")),
            access_token="access-token",
            transport=transport,
        )

        with self.assertRaises(MoomooRateLimitError) as raised:
            client.list_accounts()

        self.assertEqual(raised.exception.retry_after_seconds, 12)
        self.assertEqual(len(transport.requests), 1)

    def test_fails_closed_without_confirmed_success_indicator(self) -> None:
        transport = FakeTransport(
            [MoomooResponse(status=200, headers={}, payload={"s": "ok", "d": []})]
        )
        client = MoomooClient(
            MoomooSettings(
                scopes=("quote:read", "trade:read"),
                success_indicator=None,
            ),
            access_token="access-token",
            transport=transport,
        )

        with self.assertRaisesRegex(
            RuntimeError, "success indicator is not configured"
        ):
            client.list_accounts()

    def test_surfaces_provider_error_envelope(self) -> None:
        transport = FakeTransport(
            [
                MoomooResponse(
                    status=200,
                    headers={},
                    payload={"s": "Failed", "errcode": "1001", "errmsg": "denied"},
                )
            ]
        )
        client = MoomooClient(
            self._settings_for_assumed_success_fixture(),
            access_token="access-token",
            transport=transport,
        )

        with self.assertRaisesRegex(RuntimeError, "1001.*denied"):
            client.list_accounts()

    def test_accepts_json_numbers_and_discloses_float_precision_risk(self) -> None:
        position = self._client_for_positions(
            self._position(qty=100, nominal_price=1.84, market_val=184.0)
        ).list_positions("2638")[0]

        self.assertEqual(position.qty, "100")
        self.assertEqual(position.nominal_price, "1.84")
        self.assertEqual(position.market_val, "184.0")
        self.assertEqual(
            position.precision_risk_fields, ("nominal_price", "market_val")
        )

    def test_nulls_values_when_provider_marks_them_invalid(self) -> None:
        position = self._client_for_positions(
            self._position(
                cost_price="999",
                cost_price_valid=False,
                pl_ratio=None,
                pl_ratio_valid=False,
                pl_val=True,
                pl_val_valid=False,
            )
        ).list_positions("2638")[0]

        self.assertIsNone(position.cost_price)
        self.assertEqual(
            position.cost_price_unavailable_reason, "provider_cost_price_invalid"
        )
        self.assertIsNone(position.pl_ratio)
        self.assertEqual(
            position.pl_ratio_unavailable_reason, "provider_pl_ratio_invalid"
        )
        self.assertIsNone(position.pl_val)
        self.assertEqual(position.pl_val_unavailable_reason, "provider_pl_val_invalid")

    def test_rejects_boolean_none_and_nonfinite_numeric_values(self) -> None:
        for value in (True, None, float("nan"), float("inf"), "-Infinity"):
            with self.subTest(value=value):
                client = self._client_for_positions(self._position(qty=value))
                with self.assertRaisesRegex(RuntimeError, "qty must"):
                    client.list_positions("2638")

    def test_rejects_nonboolean_validity_flag(self) -> None:
        client = self._client_for_positions(self._position(cost_price_valid=1))

        with self.assertRaisesRegex(RuntimeError, "cost_price_valid must be boolean"):
            client.list_positions("2638")

    def test_does_not_invent_pagination_for_positions(self) -> None:
        transport = FakeTransport(
            [
                MoomooResponse(
                    status=200,
                    headers={},
                    payload={
                        "s": "ok",
                        "d": {"positions": [self._position()], "has_more": True},
                    },
                )
            ]
        )
        client = MoomooClient(
            self._settings_for_assumed_success_fixture(),
            access_token="access-token",
            transport=transport,
        )

        with self.assertRaisesRegex(RuntimeError, "positions payload is invalid"):
            client.list_positions("2638")

        self.assertEqual(len(transport.requests), 1)


if __name__ == "__main__":
    unittest.main()

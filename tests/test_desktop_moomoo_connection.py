from __future__ import annotations

import json
import unittest
from dataclasses import dataclass
from datetime import UTC, datetime
from http.client import HTTPConnection
from typing import Mapping
from urllib.parse import parse_qs, urlsplit

from workers.desktop.control import (
    DesktopControlError,
    DesktopControlServer,
    MoomooConnectionService,
)
from workers.portfolio.keychain import MoomooTokenKeychain
from workers.portfolio.moomoo import MoomooAccount, MoomooPosition
from workers.portfolio.oauth import MoomooOAuthError, MoomooOAuthTransport
from workers.portfolio.quote_stream import (
    MoomooQuoteAccess,
    MoomooQuoteStreamSnapshot,
)


@dataclass(frozen=True, slots=True)
class Security:
    security_id: str
    ticker: str
    primary_listing_exchange: str


class FakeKeychainBackend:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], str] = {}

    def store(self, *, service: str, account: str, secret: str) -> None:
        self.items[(service, account)] = secret

    def read(self, *, service: str, account: str) -> str | None:
        return self.items.get((service, account))

    def delete(self, *, service: str, account: str) -> None:
        self.items.pop((service, account), None)


class FakeOAuthTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, str]]] = []

    def post_form(self, url: str, *, form: Mapping[str, str]) -> Mapping[str, object]:
        self.calls.append((url, form))
        return {
            "access_token": "access-secret",
            "expires_in": 7200,
            "refresh_token": "refresh-secret",
            "scope": "quote:read trade:read accid:2638",
            "token_type": "Bearer",
        }


class RefreshingOAuthTransport(FakeOAuthTransport):
    def post_form(self, url: str, *, form: Mapping[str, str]) -> Mapping[str, object]:
        if form.get("grant_type") == "refresh_token":
            self.calls.append((url, form))
            return {
                "access_token": "refreshed-access-secret",
                "expires_in": 7200,
                "scope": "quote:read trade:read accid:2638",
                "token_type": "Bearer",
            }
        return super().post_form(url, form=form)


class RotatingRefreshingOAuthTransport(RefreshingOAuthTransport):
    def post_form(self, url: str, *, form: Mapping[str, str]) -> Mapping[str, object]:
        payload = dict(super().post_form(url, form=form))
        if form.get("grant_type") == "refresh_token":
            payload["refresh_token"] = "rotated-refresh-secret"
        return payload


class DowngradingOAuthTransport(FakeOAuthTransport):
    def post_form(self, url: str, *, form: Mapping[str, str]) -> Mapping[str, object]:
        payload = dict(super().post_form(url, form=form))
        if form.get("grant_type") == "refresh_token":
            payload.pop("refresh_token", None)
            payload["scope"] = "quote:read"
        return payload


class FailingOAuthTransport:
    def post_form(self, url: str, *, form: Mapping[str, str]) -> Mapping[str, object]:
        del url, form
        raise MoomooOAuthError("Moomoo OAuth token response is invalid")


class WriteScopeOAuthTransport(FakeOAuthTransport):
    def post_form(self, url: str, *, form: Mapping[str, str]) -> Mapping[str, object]:
        payload = dict(super().post_form(url, form=form))
        payload["scope"] = "quote:read trade:read trade:write accid:2638"
        return payload


class MarketDataOnlyOAuthTransport(FakeOAuthTransport):
    def post_form(self, url: str, *, form: Mapping[str, str]) -> Mapping[str, object]:
        payload = dict(super().post_form(url, form=form))
        payload["scope"] = "quote:read"
        return payload


class NoSupportedReadScopeOAuthTransport(FakeOAuthTransport):
    def post_form(self, url: str, *, form: Mapping[str, str]) -> Mapping[str, object]:
        payload = dict(super().post_form(url, form=form))
        payload["scope"] = ""
        return payload


class AccountSelectorEchoOAuthTransport(FakeOAuthTransport):
    def post_form(self, url: str, *, form: Mapping[str, str]) -> Mapping[str, object]:
        payload = dict(super().post_form(url, form=form))
        payload["scope"] = "quote:read trade:read accid:*"
        return payload


class FailingKeychainBackend(FakeKeychainBackend):
    def store(self, *, service: str, account: str, secret: str) -> None:
        del service, account, secret
        raise OSError("hidden")


class FakePortfolioClient:
    def list_accounts(self) -> tuple[MoomooAccount, ...]:
        return (
            MoomooAccount(
                account_id="2638",
                security_firm="FUTUSG",
                enable_market=(2,),
                univs_account_card_number="0000000000002638",
                acc_type="margin",
                account_card_number="0000000000002638",
            ),
        )

    def list_positions(self, account_id: str) -> tuple[MoomooPosition, ...]:
        return (
            MoomooPosition(
                account_id=account_id,
                position_side="LONG",
                code="US.GANX",
                stock_name="Gain Therapeutics",
                currency="USD",
                qty="100",
                can_sell_qty="100",
                nominal_price="1.84",
                cost_price="1.72",
                cost_price_valid=True,
                cost_price_unavailable_reason=None,
                market_val="184.00",
                pl_ratio="6.98",
                pl_ratio_valid=True,
                pl_ratio_unavailable_reason=None,
                pl_val="12.00",
                pl_val_valid=True,
                pl_val_unavailable_reason=None,
                today_pl_val="0.00",
                unrealized_pl="12.00",
                realized_pl="0.00",
                precision_risk_fields=(),
            ),
        )


class FakeQuoteStream:
    def __init__(self) -> None:
        self.access: MoomooQuoteAccess | None = None
        self.symbols: tuple[str, ...] = ()
        self.stopped = False

    def start(self, initial_access: MoomooQuoteAccess) -> None:
        self.access = initial_access

    def replace_symbols(self, symbols: tuple[str, ...]) -> None:
        self.symbols = symbols

    def snapshot(self) -> MoomooQuoteStreamSnapshot:
        return MoomooQuoteStreamSnapshot(
            state="connected",
            symbols=self.symbols,
            quotes=(),
            error_code=None,
        )

    def stop(self) -> None:
        self.stopped = True


class DesktopMoomooConnectionTests(unittest.TestCase):
    def test_resumes_saved_connection_without_browser_authorization(self) -> None:
        backend = FakeKeychainBackend()
        operator_id = "11111111-1111-4111-8111-111111111111"
        client_id = "4a8bcd69-e915-4778-9583-17ad0e9e6a80"
        MoomooTokenKeychain(
            operator_id=operator_id,
            backend=backend,
        ).store_refresh_token("refresh-secret")
        transport = RefreshingOAuthTransport()
        quote_stream = FakeQuoteStream()
        service, opened_urls = _service_for_completion(
            oauth_transport=transport,
            keychain_backend=backend,
            portfolio_client_factory=lambda _access_token: FakePortfolioClient(),
            quote_stream_factory=lambda _supplier: quote_stream,
        )

        status = service.resume_connection(
            client_id=client_id,
            operator_id=operator_id,
        )

        self.assertEqual(status.state, "connected")
        self.assertEqual(status.sync_state, "ready")
        self.assertEqual(status.position_count, 1)
        self.assertEqual(opened_urls, [])
        self.assertEqual(transport.calls[-1][1]["grant_type"], "refresh_token")
        self.assertEqual(quote_stream.access.access_token, "refreshed-access-secret")

    def test_resume_persists_rotated_refresh_token(self) -> None:
        backend = FakeKeychainBackend()
        operator_id = "11111111-1111-4111-8111-111111111111"
        client_id = "4a8bcd69-e915-4778-9583-17ad0e9e6a80"
        keychain = MoomooTokenKeychain(operator_id=operator_id, backend=backend)
        keychain.store_refresh_token("refresh-secret")
        service, _ = _service_for_completion(
            oauth_transport=RotatingRefreshingOAuthTransport(),
            keychain_backend=backend,
            portfolio_client_factory=lambda _access_token: FakePortfolioClient(),
        )

        status = service.resume_connection(
            client_id=client_id,
            operator_id=operator_id,
        )

        self.assertEqual(status.state, "connected")
        self.assertEqual(keychain.read_refresh_token(), "rotated-refresh-secret")

    def test_control_server_resumes_saved_connection_without_browser(self) -> None:
        backend = FakeKeychainBackend()
        operator_id = "11111111-1111-4111-8111-111111111111"
        client_id = "4a8bcd69-e915-4778-9583-17ad0e9e6a80"
        MoomooTokenKeychain(
            operator_id=operator_id,
            backend=backend,
        ).store_refresh_token("refresh-secret")
        service, opened_urls = _service_for_completion(
            oauth_transport=RefreshingOAuthTransport(),
            keychain_backend=backend,
            portfolio_client_factory=lambda _access_token: FakePortfolioClient(),
        )
        server = DesktopControlServer(service=service, control_token="control-secret")
        server.start()
        self.addCleanup(server.stop)

        status, payload = _request(
            server.origin,
            "POST",
            "/v1/moomoo/resume",
            token="control-secret",
            payload={"client_id": client_id, "operator_id": operator_id},
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["state"], "connected")
        self.assertEqual(payload["sync_state"], "ready")
        self.assertEqual(opened_urls, [])

    def test_resume_without_saved_token_fails_without_opening_browser(self) -> None:
        transport = RefreshingOAuthTransport()
        service, opened_urls = _service_for_completion(
            oauth_transport=transport,
            keychain_backend=FakeKeychainBackend(),
        )

        with self.assertRaisesRegex(
            DesktopControlError,
            "moomoo_saved_authorization_unavailable",
        ):
            service.resume_connection(
                client_id="4a8bcd69-e915-4778-9583-17ad0e9e6a80",
                operator_id="11111111-1111-4111-8111-111111111111",
            )

        self.assertEqual(opened_urls, [])
        self.assertEqual(transport.calls, [])
        self.assertEqual(service.status().state, "failed")
        self.assertEqual(
            service.status().error_code,
            "moomoo_saved_authorization_unavailable",
        )

    def test_control_server_exposes_bounded_compose_command(self) -> None:
        service, opened_urls = _service_for_completion(
            oauth_transport=FakeOAuthTransport(),
            portfolio_client_factory=lambda _access_token: FakePortfolioClient(),
        )
        _complete_browser_callback(service, opened_urls)
        self.assertTrue(_wait_until(lambda: service.status().sync_state == "ready"))
        server = DesktopControlServer(service=service, control_token="control-secret")
        server.start()
        self.addCleanup(server.stop)

        status, payload = _request(
            server.origin,
            "POST",
            "/v1/moomoo/compose",
            token="control-secret",
            payload={
                "operator_id": "11111111-1111-4111-8111-111111111111",
                "checked_at": "2026-08-13T09:30:00+00:00",
                "candidates": [
                    {
                        "security_id": "22222222-2222-4222-8222-222222222222",
                        "ticker": "GANX",
                        "primary_listing_exchange": "NASDAQ",
                    }
                ],
            },
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["snapshot_count"], 1)
        self.assertNotIn("2638", json.dumps(payload))

    def test_compose_returns_pseudonymous_snapshots_without_database_transport(
        self,
    ) -> None:
        service, opened_urls = _service_for_completion(
            oauth_transport=FakeOAuthTransport(),
            portfolio_client_factory=lambda _access_token: FakePortfolioClient(),
        )
        _complete_browser_callback(service, opened_urls)
        self.assertTrue(_wait_until(lambda: service.status().sync_state == "ready"))

        composition = service.compose_holdings(
            operator_id="11111111-1111-4111-8111-111111111111",
            candidates=(
                Security(
                    security_id="22222222-2222-4222-8222-222222222222",
                    ticker="GANX",
                    primary_listing_exchange="NASDAQ",
                ),
            ),
            checked_at=datetime(2026, 8, 13, 9, 30, tzinfo=UTC),
        )

        payload = composition.as_dict()
        self.assertEqual(payload["snapshot_count"], 1)
        self.assertEqual(payload["snapshots"][0]["snapshot"]["position_count"], 1)
        self.assertNotIn("2638", json.dumps(payload))
        self.assertNotIn("0000000000002638", json.dumps(payload))
        self.assertEqual(
            payload["snapshots"][0]["snapshot"]["positions"][0]["mapping_state"],
            "mapped",
        )

    def test_control_server_exposes_local_disconnect_command(self) -> None:
        backend = FakeKeychainBackend()
        service, opened_urls = _service_for_completion(
            keychain_backend=backend,
            oauth_transport=FakeOAuthTransport(),
            portfolio_client_factory=lambda _access_token: FakePortfolioClient(),
        )
        _complete_browser_callback(service, opened_urls)
        self.assertTrue(_wait_until(lambda: service.status().sync_state == "ready"))
        server = DesktopControlServer(service=service, control_token="control-secret")
        server.start()
        self.addCleanup(server.stop)

        status, payload = _request(
            server.origin,
            "POST",
            "/v1/moomoo/disconnect",
            token="control-secret",
            payload={"operator_id": "11111111-1111-4111-8111-111111111111"},
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["state"], "disconnected")
        self.assertEqual(backend.items, {})

    def test_disconnect_clears_local_mirror_and_keychain_refresh_token(self) -> None:
        backend = FakeKeychainBackend()
        service, opened_urls = _service_for_completion(
            keychain_backend=backend,
            oauth_transport=FakeOAuthTransport(),
            portfolio_client_factory=lambda _access_token: FakePortfolioClient(),
        )
        _complete_browser_callback(service, opened_urls)
        self.assertTrue(_wait_until(lambda: service.status().sync_state == "ready"))
        self.assertTrue(backend.items)

        status = service.disconnect(operator_id="11111111-1111-4111-8111-111111111111")

        self.assertEqual(status.state, "disconnected")
        self.assertEqual(service.holdings().positions, ())
        self.assertEqual(backend.items, {})

    def test_control_server_exposes_bounded_manual_refresh_command(self) -> None:
        service, opened_urls = _service_for_completion(
            oauth_transport=RefreshingOAuthTransport(),
            portfolio_client_factory=lambda _access_token: FakePortfolioClient(),
        )
        _complete_browser_callback(service, opened_urls)
        self.assertTrue(_wait_until(lambda: service.status().sync_state == "ready"))
        server = DesktopControlServer(service=service, control_token="control-secret")
        server.start()
        self.addCleanup(server.stop)

        status, payload = _request(
            server.origin,
            "POST",
            "/v1/moomoo/refresh",
            token="control-secret",
            payload={
                "operator_id": "11111111-1111-4111-8111-111111111111",
            },
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["sync_state"], "ready")
        self.assertEqual(payload["position_count"], 1)

    def test_manual_refresh_uses_keychain_token_and_replaces_live_mirror(self) -> None:
        backend = FakeKeychainBackend()
        transport = RefreshingOAuthTransport()
        access_tokens: list[str] = []
        service, opened_urls = _service_for_completion(
            keychain_backend=backend,
            oauth_transport=transport,
            portfolio_client_factory=lambda access_token: (
                access_tokens.append(access_token) or FakePortfolioClient()
            ),
        )
        _complete_browser_callback(service, opened_urls)
        self.assertTrue(_wait_until(lambda: service.status().sync_state == "ready"))

        status = service.refresh_holdings(
            operator_id="11111111-1111-4111-8111-111111111111"
        )

        self.assertEqual(status.sync_state, "ready")
        self.assertEqual(access_tokens, ["access-secret", "refreshed-access-secret"])
        self.assertEqual(transport.calls[-1][1]["grant_type"], "refresh_token")
        self.assertEqual(service.holdings().positions[0].qty, "100")

    def test_refresh_downgrades_capabilities_and_clears_unavailable_holdings(
        self,
    ) -> None:
        service, opened_urls = _service_for_completion(
            oauth_transport=DowngradingOAuthTransport(),
            portfolio_client_factory=lambda _access_token: FakePortfolioClient(),
        )
        _complete_browser_callback(service, opened_urls)
        self.assertTrue(_wait_until(lambda: service.status().sync_state == "ready"))

        status = service.refresh_holdings(
            operator_id="11111111-1111-4111-8111-111111111111"
        )

        self.assertEqual(status.state, "connected")
        self.assertEqual(status.capabilities, ("market_data",))
        self.assertEqual(status.sync_state, "unavailable")
        self.assertEqual(service.holdings().positions, ())

    def test_connection_syncs_authorized_accounts_into_string_native_mirror(
        self,
    ) -> None:
        clients: list[str] = []
        service, opened_urls = _service_for_completion(
            oauth_transport=FakeOAuthTransport(),
            portfolio_client_factory=lambda access_token: (
                clients.append(access_token) or FakePortfolioClient()
            ),
        )

        _complete_browser_callback(service, opened_urls)

        self.assertTrue(_wait_until(lambda: service.status().sync_state == "ready"))
        status = service.status()
        self.assertEqual(status.state, "connected")
        self.assertEqual(status.account_count, 1)
        self.assertEqual(status.position_count, 1)
        self.assertEqual(clients, ["access-secret"])
        self.assertEqual(
            service.holdings().as_dict(),
            {
                "account_count": 1,
                "position_count": 1,
                "positions": [
                    {
                        "account_index": 1,
                        "code": "US.GANX",
                        "cost_price": "1.72",
                        "cost_price_valid": True,
                        "currency": "USD",
                        "market_val": "184.00",
                        "nominal_price": "1.84",
                        "pl_val": "12.00",
                        "pl_val_valid": True,
                        "position_side": "LONG",
                        "qty": "100",
                        "stock_name": "Gain Therapeutics",
                    }
                ],
                "sync_state": "ready",
            },
        )

        server = DesktopControlServer(service=service, control_token="control-secret")
        server.start()
        self.addCleanup(server.stop)
        http_status, payload = _request(
            server.origin,
            "GET",
            "/v1/moomoo/holdings",
            token="control-secret",
        )
        self.assertEqual(http_status, 200)
        self.assertEqual(payload["position_count"], 1)
        self.assertEqual(payload["positions"][0]["qty"], "100")

    def test_reports_redacted_token_response_failure_stage(self) -> None:
        service, opened_urls = _service_for_completion(
            oauth_transport=FailingOAuthTransport(),
        )

        _complete_browser_callback(service, opened_urls)

        self.assertTrue(
            _wait_until(
                lambda: service.status().error_code == "moomoo_token_response_invalid"
            )
        )

    def test_connects_with_operator_granted_write_scope_but_uses_read_only_surface(
        self,
    ) -> None:
        service, opened_urls = _service_for_completion(
            oauth_transport=WriteScopeOAuthTransport(),
            portfolio_client_factory=lambda _access_token: FakePortfolioClient(),
        )

        _complete_browser_callback(service, opened_urls)

        self.assertTrue(_wait_until(lambda: service.status().state == "connected"))
        self.assertEqual(service.status().error_code, None)
        self.assertEqual(service.status().capabilities, ("market_data", "portfolio_holdings"))
        self.assertNotIn("trade:write", json.dumps(service.status().as_dict()))

    def test_connects_with_market_data_only_and_blocks_holdings_sync(self) -> None:
        clients: list[str] = []
        service, opened_urls = _service_for_completion(
            oauth_transport=MarketDataOnlyOAuthTransport(),
            portfolio_client_factory=lambda access_token: (
                clients.append(access_token) or FakePortfolioClient()
            ),
        )

        _complete_browser_callback(service, opened_urls)

        self.assertTrue(_wait_until(lambda: service.status().state == "connected"))
        self.assertEqual(
            service.status().as_dict(),
            {
                "account_count": 0,
                "capabilities": ["market_data"],
                "error_code": None,
                "position_count": 0,
                "state": "connected",
                "sync_state": "unavailable",
            },
        )
        self.assertEqual(clients, [])

    def test_connects_without_supported_read_capability_and_explains_limits(self) -> None:
        clients: list[str] = []
        service, opened_urls = _service_for_completion(
            oauth_transport=NoSupportedReadScopeOAuthTransport(),
            portfolio_client_factory=lambda access_token: (
                clients.append(access_token) or FakePortfolioClient()
            ),
        )

        _complete_browser_callback(service, opened_urls)

        self.assertTrue(_wait_until(lambda: service.status().state == "connected"))
        self.assertEqual(
            service.status().as_dict(),
            {
                "account_count": 0,
                "capabilities": [],
                "error_code": None,
                "position_count": 0,
                "state": "connected",
                "sync_state": "unavailable",
            },
        )
        self.assertEqual(clients, [])

    def test_connects_when_moomoo_echoes_account_selector_without_granting_account(
        self,
    ) -> None:
        clients: list[str] = []
        service, opened_urls = _service_for_completion(
            oauth_transport=AccountSelectorEchoOAuthTransport(),
            portfolio_client_factory=lambda access_token: (
                clients.append(access_token) or FakePortfolioClient()
            ),
        )

        _complete_browser_callback(service, opened_urls)

        self.assertTrue(_wait_until(lambda: service.status().state == "connected"))
        self.assertEqual(
            service.status().as_dict(),
            {
                "account_count": 0,
                "capabilities": ["market_data"],
                "error_code": None,
                "position_count": 0,
                "state": "connected",
                "sync_state": "unavailable",
            },
        )
        self.assertEqual(clients, [])

    def test_control_server_bounds_quote_subscriptions_for_connected_operator(
        self,
    ) -> None:
        quote_stream = FakeQuoteStream()
        service, opened_urls = _service_for_completion(
            oauth_transport=MarketDataOnlyOAuthTransport(),
            quote_stream_factory=lambda _supplier: quote_stream,
        )
        _complete_browser_callback(service, opened_urls)
        self.assertTrue(_wait_until(lambda: service.status().state == "connected"))
        server = DesktopControlServer(service=service, control_token="control-secret")
        server.start()
        self.addCleanup(server.stop)

        status, payload = _request(
            server.origin,
            "POST",
            "/v1/moomoo/quotes/subscriptions",
            token="control-secret",
            payload={
                "operator_id": "11111111-1111-4111-8111-111111111111",
                "symbols": ["US.RXRX", "US.GANX"],
            },
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["symbols"], ["US.GANX", "US.RXRX"])
        self.assertIsNotNone(quote_stream.access)
        self.assertEqual(quote_stream.access.access_token, "access-secret")
        quote_status, quote_payload = _request(
            server.origin,
            "GET",
            "/v1/moomoo/quotes",
            token="control-secret",
        )
        self.assertEqual(quote_status, 200)
        self.assertEqual(quote_payload["symbols"], ["US.GANX", "US.RXRX"])

        service.disconnect(operator_id="11111111-1111-4111-8111-111111111111")
        self.assertTrue(quote_stream.stopped)

    def test_reports_redacted_keychain_failure_stage(self) -> None:
        service, opened_urls = _service_for_completion(
            keychain_backend=FailingKeychainBackend(),
            oauth_transport=FakeOAuthTransport(),
        )

        _complete_browser_callback(service, opened_urls)

        self.assertTrue(
            _wait_until(
                lambda: service.status().error_code == "moomoo_keychain_store_failed"
            )
        )

    def test_browser_launch_failure_closes_callback_and_records_failure(self) -> None:
        service = MoomooConnectionService(
            browser_opener=lambda _url: (_ for _ in ()).throw(OSError("hidden")),
            callback_timeout_seconds=1,
            keychain_factory=lambda _operator_id: self.fail("Keychain must not open"),
            oauth_transport=FakeOAuthTransport(),
        )
        callback_port = _unused_loopback_port()

        with self.assertRaisesRegex(
            DesktopControlError,
            "moomoo_system_browser_unavailable",
        ):
            service.start_connection(
                client_id="4a8bcd69-e915-4778-9583-17ad0e9e6a80",
                operator_id="11111111-1111-4111-8111-111111111111",
                redirect_uri=f"http://127.0.0.1:{callback_port}/callback",
            )

        self.assertEqual(service.status().state, "failed")

    def test_control_server_completes_loopback_oauth_and_keeps_secrets_out_of_status(
        self,
    ) -> None:
        backend = FakeKeychainBackend()
        transport = FakeOAuthTransport()
        opened_urls: list[str] = []
        service = MoomooConnectionService(
            browser_opener=lambda url: opened_urls.append(url) or True,
            callback_timeout_seconds=2,
            keychain_factory=lambda operator_id: MoomooTokenKeychain(
                operator_id=operator_id,
                backend=backend,
            ),
            oauth_transport=transport,
        )
        server = DesktopControlServer(service=service, control_token="control-secret")
        server.start()
        self.addCleanup(server.stop)

        callback_port = _unused_loopback_port()
        response = _request(
            server.origin,
            "POST",
            "/v1/moomoo/connect",
            token="control-secret",
            payload={
                "client_id": "4a8bcd69-e915-4778-9583-17ad0e9e6a80",
                "operator_id": "11111111-1111-4111-8111-111111111111",
                "redirect_uri": f"http://127.0.0.1:{callback_port}/callback",
            },
        )

        self.assertEqual(response[0], 202)
        self.assertEqual(response[1]["state"], "pending")
        self.assertTrue(_wait_until(lambda: bool(opened_urls)))
        authorization_query = parse_qs(urlsplit(opened_urls[0]).query)
        callback = HTTPConnection("127.0.0.1", callback_port, timeout=2)
        callback.request(
            "GET",
            "/callback?code=one-use-code&state=" + authorization_query["state"][0],
        )
        callback_response = callback.getresponse()
        self.assertEqual(callback_response.status, 200)
        self.assertNotIn("one-use-code", callback_response.read().decode())

        self.assertTrue(
            _wait_until(
                lambda: _request(
                    server.origin,
                    "GET",
                    "/v1/moomoo/status",
                    token="control-secret",
                )[1]["state"]
                == "connected"
            )
        )
        status, payload = _request(
            server.origin,
            "GET",
            "/v1/moomoo/status",
            token="control-secret",
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["account_count"], 1)
        self.assertNotIn("access-secret", json.dumps(payload))
        self.assertNotIn("refresh-secret", json.dumps(payload))
        self.assertEqual(len(transport.calls), 1)
        self.assertIn("refresh-secret", backend.items.values())

    def test_control_server_rejects_missing_capability_before_service_dispatch(
        self,
    ) -> None:
        service = MoomooConnectionService(
            browser_opener=lambda _url: self.fail("browser must not open"),
            callback_timeout_seconds=1,
            keychain_factory=lambda _operator_id: self.fail("Keychain must not open"),
            oauth_transport=FakeOAuthTransport(),
        )
        server = DesktopControlServer(service=service, control_token="control-secret")
        server.start()
        self.addCleanup(server.stop)

        status, payload = _request(
            server.origin,
            "POST",
            "/v1/moomoo/connect",
            token="wrong-secret",
            payload={},
        )

        self.assertEqual(status, 401)
        self.assertEqual(payload, {"error": "desktop_control_unauthorized"})


def _unused_loopback_port() -> int:
    import socket

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _service_for_completion(
    *,
    oauth_transport: MoomooOAuthTransport,
    keychain_backend: FakeKeychainBackend | None = None,
    portfolio_client_factory: object | None = None,
    quote_stream_factory: object | None = None,
) -> tuple[MoomooConnectionService, list[str]]:
    backend = keychain_backend or FakeKeychainBackend()
    opened_urls: list[str] = []
    service = MoomooConnectionService(
        browser_opener=lambda url: opened_urls.append(url) or True,
        callback_timeout_seconds=2,
        keychain_factory=lambda operator_id: MoomooTokenKeychain(
            operator_id=operator_id,
            backend=backend,
        ),
        oauth_transport=oauth_transport,
        portfolio_client_factory=portfolio_client_factory,
        quote_stream_factory=quote_stream_factory,
    )
    return service, opened_urls


def _complete_browser_callback(
    service: MoomooConnectionService,
    opened_urls: list[str],
) -> None:
    callback_port = _unused_loopback_port()
    service.start_connection(
        client_id="4a8bcd69-e915-4778-9583-17ad0e9e6a80",
        operator_id="11111111-1111-4111-8111-111111111111",
        redirect_uri=f"http://127.0.0.1:{callback_port}/callback",
    )
    callback_state = parse_qs(urlsplit(opened_urls[0]).query)["state"][0]
    callback = HTTPConnection("127.0.0.1", callback_port, timeout=2)
    callback.request("GET", f"/callback?code=one-use-code&state={callback_state}")
    callback.getresponse().read()


def _wait_until(predicate: object, *, attempts: int = 100) -> bool:
    import time

    for _ in range(attempts):
        if predicate():  # type: ignore[operator]
            return True
        time.sleep(0.01)
    return False


def _request(
    origin: str,
    method: str,
    path: str,
    *,
    token: str,
    payload: Mapping[str, object] | None = None,
) -> tuple[int, dict[str, object]]:
    parsed = urlsplit(origin)
    connection = HTTPConnection(parsed.hostname, parsed.port, timeout=2)
    body = None if payload is None else json.dumps(payload)
    connection.request(
        method,
        path,
        body=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    response = connection.getresponse()
    response_payload = json.loads(response.read())
    return response.status, response_payload


if __name__ == "__main__":
    unittest.main()

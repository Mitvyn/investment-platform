from __future__ import annotations

import json
import socket
import unittest
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
from typing import Mapping
from urllib.parse import urlsplit

from workers.desktop.control import (
    DesktopControlError,
    DesktopControlServer,
    MoomooConnectionService,
)
from workers.portfolio.keychain import MoomooTokenKeychain

OPERATOR_ID = "11111111-1111-4111-8111-111111111111"
CLIENT_ID = "4a8bcd69-e915-4778-9583-17ad0e9e6a80"
SECURITY_ID = "22222222-2222-4222-8222-222222222222"


class KeychainBackend:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], str] = {}

    def store(self, *, service: str, account: str, secret: str) -> None:
        self.items[(service, account)] = secret

    def read(self, *, service: str, account: str) -> str | None:
        return self.items.get((service, account))

    def delete(self, *, service: str, account: str) -> None:
        self.items.pop((service, account), None)


class OAuthTransport:
    def post_form(self, url: str, *, form: Mapping[str, str]) -> Mapping[str, object]:
        del url
        response: dict[str, object] = {
            "access_token": "access-secret",
            "expires_in": 7200,
            "scope": "quote:read trade:read accid:2638",
            "token_type": "Bearer",
        }
        if form.get("grant_type") == "authorization_code":
            response["refresh_token"] = "refresh-secret"
        return response


class FakeMarketClient:
    def __init__(self, access_token: str) -> None:
        self.access_token = access_token
        self.calls: list[tuple[str, Mapping[str, object]]] = []

    def list_tools(self) -> list[Mapping[str, object]]:
        return [
            {
                "name": "quote_stock_quote",
                "description": "Quote read",
                "inputSchema": {"type": "object"},
            }
        ]

    def call_tool(self, name: str, arguments: Mapping[str, object]) -> Mapping[str, object]:
        self.calls.append((name, arguments))
        return {
            "isError": False,
            "structuredContent": {
                "code": "US.AAPL",
                "time": 1_787_227_140,
                "last_price": "150.25",
            },
        }


class StaleMarketClient(FakeMarketClient):
    def call_tool(self, name: str, arguments: Mapping[str, object]) -> Mapping[str, object]:
        self.calls.append((name, arguments))
        return {
            "isError": False,
            "structuredContent": {
                "code": "US.AAPL",
                "time": 1_700_000_000,
                "last_price": "150.25",
            },
        }


class FakeWriteAttemptClient(FakeMarketClient):
    def call_tool(self, name: str, arguments: Mapping[str, object]) -> Mapping[str, object]:
        raise AssertionError("write/trade tool must never be dispatched")


def unused_loopback_port() -> int:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def fixed_clock() -> datetime:
    return datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)


class MutableClock:
    def __init__(self, initial: datetime) -> None:
        self.value = initial

    def __call__(self) -> datetime:
        return self.value


class DesktopMoomooMarketEvidenceTests(unittest.TestCase):
    def _service(self, factory: object, *, clock: object = fixed_clock) -> MoomooConnectionService:
        backend = KeychainBackend()
        MoomooTokenKeychain(operator_id=OPERATOR_ID, backend=backend).store_refresh_token(
            "refresh-secret"
        )
        service = MoomooConnectionService(
            keychain_factory=lambda operator_id: MoomooTokenKeychain(
                operator_id=operator_id,
                backend=backend,
            ),
            oauth_transport=OAuthTransport(),
            mcp_client_factory=factory,
            clock=clock,
        )
        service.resume_connection(client_id=CLIENT_ID, operator_id=OPERATOR_ID)
        if factory is not None:
            service._mcp_access_token = "mcp-access-secret"  # type: ignore[attr-defined]
        return service

    def test_fetch_market_quote_requires_prior_discovery(self) -> None:
        service = self._service(lambda token: FakeMarketClient(token))

        with self.assertRaises(DesktopControlError) as context:
            service.fetch_market_quote(
                operator_id=OPERATOR_ID, security_id=SECURITY_ID, ticker="US.AAPL"
            )
        self.assertEqual(context.exception.code, "moomoo_mcp_discovery_required")

    def test_fetch_market_quote_returns_typed_evidence_after_discovery(self) -> None:
        service = self._service(lambda token: FakeMarketClient(token))
        service.discover_mcp_tools(operator_id=OPERATOR_ID)

        status = service.fetch_market_quote(
            operator_id=OPERATOR_ID, security_id=SECURITY_ID, ticker="US.AAPL"
        )

        payload = status.as_dict()
        self.assertEqual(payload["state"], "ready")
        self.assertEqual(payload["evidence"]["ticker"], "US.AAPL")
        self.assertEqual(payload["evidence"]["security_id"], SECURITY_ID)
        self.assertEqual(payload["evidence"]["tool_name"], "quote_stock_quote")
        self.assertNotIn("access-secret", json.dumps(payload))

    def test_fetch_market_quote_rejects_non_allowlisted_tool_name_shape(self) -> None:
        service = self._service(lambda token: FakeMarketClient(token))
        service.discover_mcp_tools(operator_id=OPERATOR_ID)

        with self.assertRaises(DesktopControlError) as context:
            service.fetch_market_quote(
                operator_id=OPERATOR_ID,
                security_id=SECURITY_ID,
                ticker="'; DROP TABLE",
            )
        self.assertEqual(context.exception.code, "moomoo_market_evidence_ticker_invalid")

    def test_loopback_market_quote_route_requires_auth_and_discovery(self) -> None:
        service = self._service(lambda token: FakeMarketClient(token))
        server = DesktopControlServer(service=service, control_token="control-secret")
        server.start()
        self.addCleanup(server.stop)
        parsed = urlsplit(server.origin)

        connection = HTTPConnection(parsed.hostname, parsed.port, timeout=2)
        connection.request(
            "POST",
            "/v1/research/market-evidence/quote",
            body=json.dumps(
                {"operator_id": OPERATOR_ID, "security_id": SECURITY_ID, "ticker": "US.AAPL"}
            ),
        )
        self.assertEqual(connection.getresponse().status, 401)

        connection.request(
            "POST",
            "/v1/research/market-evidence/quote",
            body=json.dumps(
                {"operator_id": OPERATOR_ID, "security_id": SECURITY_ID, "ticker": "US.AAPL"}
            ),
            headers={
                "Authorization": "Bearer control-secret",
                "Content-Type": "application/json",
            },
        )
        response = connection.getresponse()
        payload = json.loads(response.read())
        self.assertEqual(response.status, 409)
        self.assertEqual(payload["error"], "moomoo_mcp_discovery_required")

        service.discover_mcp_tools(operator_id=OPERATOR_ID)
        connection.request(
            "POST",
            "/v1/research/market-evidence/quote",
            body=json.dumps(
                {"operator_id": OPERATOR_ID, "security_id": SECURITY_ID, "ticker": "US.AAPL"}
            ),
            headers={
                "Authorization": "Bearer control-secret",
                "Content-Type": "application/json",
            },
        )
        response = connection.getresponse()
        payload = json.loads(response.read())
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["evidence"]["ticker"], "US.AAPL")
        self.assertNotIn("access-secret", json.dumps(payload))

    def test_stale_provider_data_is_reported_as_stale_not_ready(self) -> None:
        service = self._service(lambda token: StaleMarketClient(token))
        service.discover_mcp_tools(operator_id=OPERATOR_ID)

        status = service.fetch_market_quote(
            operator_id=OPERATOR_ID, security_id=SECURITY_ID, ticker="US.AAPL"
        )

        self.assertEqual(status.state, "stale")
        self.assertNotEqual(status.state, "ready")

    def test_get_route_reports_cached_flag_and_survives_only_until_disconnect(self) -> None:
        service = self._service(lambda token: FakeMarketClient(token))
        service.discover_mcp_tools(operator_id=OPERATOR_ID)
        service.fetch_market_quote(
            operator_id=OPERATOR_ID, security_id=SECURITY_ID, ticker="US.AAPL"
        )

        fresh = service.fetch_market_quote(
            operator_id=OPERATOR_ID, security_id=SECURITY_ID, ticker="US.AAPL"
        )
        self.assertFalse(fresh.cached)

        cached = service.last_market_quote(security_id=SECURITY_ID)
        self.assertTrue(cached.cached)
        self.assertEqual(cached.state, "ready")

        service.disconnect(operator_id=OPERATOR_ID)

        cleared = service.last_market_quote(security_id=SECURITY_ID)
        self.assertEqual(cleared.state, "unavailable")
        self.assertFalse(cleared.cached)

    def test_cached_quote_ages_into_stale_under_a_later_clock_read(self) -> None:
        clock = MutableClock(fixed_clock())
        service = self._service(lambda token: FakeMarketClient(token), clock=clock)
        service.discover_mcp_tools(operator_id=OPERATOR_ID)

        fresh = service.fetch_market_quote(
            operator_id=OPERATOR_ID, security_id=SECURITY_ID, ticker="US.AAPL"
        )
        self.assertEqual(fresh.state, "ready")

        clock.value = fixed_clock() + timedelta(hours=2)
        aged = service.last_market_quote(security_id=SECURITY_ID)

        self.assertEqual(aged.state, "stale")
        self.assertTrue(aged.cached)
        self.assertEqual(aged.evidence["freshness"], "stale")

    def test_resume_connection_clears_stale_market_quote_cache(self) -> None:
        backend = KeychainBackend()
        MoomooTokenKeychain(operator_id=OPERATOR_ID, backend=backend).store_refresh_token(
            "refresh-secret"
        )
        service = MoomooConnectionService(
            keychain_factory=lambda operator_id: MoomooTokenKeychain(
                operator_id=operator_id,
                backend=backend,
            ),
            oauth_transport=OAuthTransport(),
            mcp_client_factory=lambda token: FakeMarketClient(token),
            clock=fixed_clock,
        )
        service.resume_connection(client_id=CLIENT_ID, operator_id=OPERATOR_ID)
        service._mcp_access_token = "mcp-access-secret"  # type: ignore[attr-defined]
        service.discover_mcp_tools(operator_id=OPERATOR_ID)
        service.fetch_market_quote(
            operator_id=OPERATOR_ID, security_id=SECURITY_ID, ticker="US.AAPL"
        )
        self.assertEqual(
            service.last_market_quote(security_id=SECURITY_ID).state, "ready"
        )

        service.disconnect(operator_id=OPERATOR_ID)
        MoomooTokenKeychain(operator_id=OPERATOR_ID, backend=backend).store_refresh_token(
            "refresh-secret"
        )
        service.resume_connection(client_id=CLIENT_ID, operator_id=OPERATOR_ID)

        self.assertEqual(
            service.last_market_quote(security_id=SECURITY_ID).state, "unavailable"
        )

    def test_start_connection_clears_stale_market_quote_cache_directly(self) -> None:
        backend = KeychainBackend()
        MoomooTokenKeychain(operator_id=OPERATOR_ID, backend=backend).store_refresh_token(
            "refresh-secret"
        )
        service = MoomooConnectionService(
            keychain_factory=lambda operator_id: MoomooTokenKeychain(
                operator_id=operator_id,
                backend=backend,
            ),
            oauth_transport=OAuthTransport(),
            mcp_client_factory=lambda token: FakeMarketClient(token),
            browser_opener=lambda _url: True,
            clock=fixed_clock,
        )
        service.resume_connection(client_id=CLIENT_ID, operator_id=OPERATOR_ID)
        service._mcp_access_token = "mcp-access-secret"  # type: ignore[attr-defined]
        service.discover_mcp_tools(operator_id=OPERATOR_ID)
        service.fetch_market_quote(
            operator_id=OPERATOR_ID, security_id=SECURITY_ID, ticker="US.AAPL"
        )
        self.assertEqual(
            service.last_market_quote(security_id=SECURITY_ID).state, "ready"
        )

        callback_port = unused_loopback_port()
        service.start_connection(
            client_id=CLIENT_ID,
            operator_id=OPERATOR_ID,
            redirect_uri=f"http://127.0.0.1:{callback_port}/callback",
        )

        self.assertEqual(
            service.last_market_quote(security_id=SECURITY_ID).state, "unavailable"
        )

    def test_last_market_quote_is_cached_and_readable_via_get_route(self) -> None:
        service = self._service(lambda token: FakeMarketClient(token))
        service.discover_mcp_tools(operator_id=OPERATOR_ID)
        self.assertEqual(
            service.last_market_quote(security_id=SECURITY_ID).state, "unavailable"
        )

        service.fetch_market_quote(
            operator_id=OPERATOR_ID, security_id=SECURITY_ID, ticker="US.AAPL"
        )

        cached = service.last_market_quote(security_id=SECURITY_ID)
        self.assertEqual(cached.state, "ready")
        self.assertEqual(cached.evidence["ticker"], "US.AAPL")

        server = DesktopControlServer(service=service, control_token="control-secret")
        server.start()
        self.addCleanup(server.stop)
        parsed = urlsplit(server.origin)
        connection = HTTPConnection(parsed.hostname, parsed.port, timeout=2)
        connection.request(
            "GET",
            f"/v1/research/market-evidence/quote?security_id={SECURITY_ID}",
            headers={"Authorization": "Bearer control-secret"},
        )
        response = connection.getresponse()
        payload = json.loads(response.read())
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["state"], "ready")
        self.assertEqual(payload["evidence"]["ticker"], "US.AAPL")

    def test_write_tool_is_never_dispatched_even_if_requested(self) -> None:
        service = self._service(lambda token: FakeWriteAttemptClient(token))
        service.discover_mcp_tools(operator_id=OPERATOR_ID)

        with self.assertRaises(DesktopControlError) as context:
            service.fetch_market_quote(
                operator_id=OPERATOR_ID,
                security_id=SECURITY_ID,
                ticker="US.AAPL",
                tool_name="trading_order_place",
            )
        self.assertEqual(context.exception.code, "moomoo_market_evidence_tool_not_allowlisted")


if __name__ == "__main__":
    unittest.main()

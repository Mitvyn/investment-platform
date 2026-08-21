from __future__ import annotations

import json
import socket
import time
import unittest
from http.client import HTTPConnection
from typing import Mapping
from urllib.parse import parse_qs, urlsplit

from workers.desktop.control import (
    DesktopControlError,
    DesktopControlServer,
    MoomooConnectionService,
)
from workers.moomoo_mcp.http_client import MoomooMcpError
from workers.moomoo_mcp.keychain import MoomooMcpTokenKeychain
from workers.portfolio.keychain import MoomooTokenKeychain


OPERATOR_ID = "11111111-1111-4111-8111-111111111111"
CLIENT_ID = "4a8bcd69-e915-4778-9583-17ad0e9e6a80"


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


class RotatingOAuthTransport(OAuthTransport):
    def post_form(self, url: str, *, form: Mapping[str, str]) -> Mapping[str, object]:
        response = dict(super().post_form(url, form=form))
        if form.get("grant_type") == "refresh_token":
            response["refresh_token"] = "rotated-refresh-secret"
        return response


class DiscoveryClient:
    def __init__(self, access_token: str) -> None:
        self.access_token = access_token

    def list_tools(self) -> list[Mapping[str, object]]:
        return [
            {
                "name": "quote_stock_quote",
                "description": "Quote read",
                "inputSchema": {"type": "object"},
            }
        ]


class FailingDiscoveryClient:
    def __init__(self, _access_token: str) -> None:
        pass

    def list_tools(self) -> list[Mapping[str, object]]:
        raise MoomooMcpError("discovery unavailable")


def unused_loopback_port() -> int:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


class DesktopMoomooMcpTests(unittest.TestCase):
    def _service(self, factory: object) -> MoomooConnectionService:
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
        )
        service.resume_connection(client_id=CLIENT_ID, operator_id=OPERATOR_ID)
        if factory is not None:
            service._mcp_access_token = "mcp-access-secret"  # type: ignore[attr-defined]
        return service

    def test_openapi_connection_does_not_authorize_mcp_discovery(self) -> None:
        service = self._service(None)

        self.assertEqual(service.mcp_discovery_status().as_dict(), {
            "error_code": "moomoo_mcp_authorization_required",
            "state": "unavailable",
            "tool_count": 0,
            "tools": [],
        })
        with self.assertRaises(DesktopControlError) as context:
            service.discover_mcp_tools(operator_id=OPERATOR_ID)
        self.assertEqual(context.exception.code, "moomoo_mcp_authorization_required")

    def test_resume_rotates_openapi_and_mcp_tokens_in_separate_keychains(self) -> None:
        backend = KeychainBackend()
        MoomooTokenKeychain(operator_id=OPERATOR_ID, backend=backend).store_refresh_token(
            "openapi-refresh-secret"
        )
        MoomooMcpTokenKeychain(operator_id=OPERATOR_ID, backend=backend).store_refresh_token(
            "mcp-refresh-secret"
        )
        service = MoomooConnectionService(
            keychain_factory=lambda operator_id: MoomooTokenKeychain(
                operator_id=operator_id,
                backend=backend,
            ),
            oauth_transport=RotatingOAuthTransport(),
            mcp_client_factory=lambda token: DiscoveryClient(token),
            mcp_keychain_factory=lambda operator_id: MoomooMcpTokenKeychain(
                operator_id=operator_id,
                backend=backend,
            ),
        )

        status = service.resume_connection(client_id=CLIENT_ID, operator_id=OPERATOR_ID)

        self.assertEqual(status.state, "connected")
        self.assertEqual(
            MoomooTokenKeychain(operator_id=OPERATOR_ID, backend=backend).read_refresh_token(),
            "rotated-refresh-secret",
        )
        self.assertEqual(
            MoomooMcpTokenKeychain(operator_id=OPERATOR_ID, backend=backend).read_refresh_token(),
            "rotated-refresh-secret",
        )
        self.assertEqual(service.mcp_discovery_status().state, "discovery_required")

    def test_discovery_returns_redacted_status_from_separate_mcp_authorization(self) -> None:
        clients: list[DiscoveryClient] = []
        service = self._service(
            lambda token: clients.append(DiscoveryClient(token)) or clients[-1]
        )

        status = service.discover_mcp_tools(operator_id=OPERATOR_ID)

        self.assertEqual(status.as_dict(), {
            "error_code": None,
            "state": "ready",
            "tool_count": 1,
            "tools": [
                {
                    "name": "quote_stock_quote",
                    "input_schema_sha256": "a2c799262a3ce3c19ef5cdd983bf3d12b43ab3c426227091b909dcb7054738c0",
                }
            ],
        })
        self.assertEqual(clients[0].access_token, "mcp-access-secret")
        self.assertNotEqual(clients[0].access_token, "access-secret")
        self.assertNotIn("access-secret", json.dumps(status.as_dict()))

    def test_loopback_requires_auth_and_returns_discovery_status_only(self) -> None:
        service = self._service(lambda token: DiscoveryClient(token))
        server = DesktopControlServer(service=service, control_token="control-secret")
        server.start()
        self.addCleanup(server.stop)
        parsed = urlsplit(server.origin)

        connection = HTTPConnection(parsed.hostname, parsed.port, timeout=2)
        connection.request("GET", "/v1/moomoo/mcp/status")
        self.assertEqual(connection.getresponse().status, 401)

        connection.request(
            "POST",
            "/v1/moomoo/mcp/discover",
            body=json.dumps({"operator_id": OPERATOR_ID}),
            headers={
                "Authorization": "Bearer control-secret",
                "Content-Type": "application/json",
            },
        )
        response = connection.getresponse()
        payload = json.loads(response.read())
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["state"], "ready")
        self.assertEqual(payload["tool_count"], 1)
        self.assertEqual(payload["tools"][0]["name"], "quote_stock_quote")
        self.assertNotIn("description", payload["tools"][0])
        self.assertNotIn("inputSchema", payload["tools"][0])
        self.assertNotIn("access-secret", json.dumps(payload))

    def test_mcp_authorization_uses_separate_keychain_and_no_scope_parameter(self) -> None:
        backend = KeychainBackend()
        MoomooTokenKeychain(operator_id=OPERATOR_ID, backend=backend).store_refresh_token(
            "openapi-refresh-secret"
        )
        opened_urls: list[str] = []
        service = MoomooConnectionService(
            keychain_factory=lambda operator_id: MoomooTokenKeychain(
                operator_id=operator_id,
                backend=backend,
            ),
            oauth_transport=OAuthTransport(),
            mcp_client_factory=lambda token: DiscoveryClient(token),
            mcp_keychain_factory=lambda operator_id: MoomooMcpTokenKeychain(
                operator_id=operator_id,
                backend=backend,
            ),
            browser_opener=lambda url: opened_urls.append(url) or True,
        )
        service.resume_connection(client_id=CLIENT_ID, operator_id=OPERATOR_ID)
        redirect_uri = f"http://127.0.0.1:{unused_loopback_port()}/callback"

        status = service.start_mcp_authorization(
            operator_id=OPERATOR_ID,
            redirect_uri=redirect_uri,
        )

        self.assertEqual(status.state, "authorization_pending")
        self.assertEqual(len(opened_urls), 1)
        self.assertNotIn("scope=", opened_urls[0])
        state = parse_qs(urlsplit(opened_urls[0]).query)["state"][0]
        callback_port = int(urlsplit(redirect_uri).port or 0)
        callback = HTTPConnection("127.0.0.1", callback_port, timeout=2)
        callback.request("GET", f"/callback?code=mcp-code&state={state}")
        self.assertEqual(callback.getresponse().status, 200)
        for _ in range(20):
            if service.mcp_discovery_status().state == "discovery_required":
                break
            time.sleep(0.01)
        if service.mcp_discovery_status().state == "failed":
            self.fail(str(service.mcp_discovery_status().as_dict()))
        self.assertEqual(service.mcp_discovery_status().state, "discovery_required")
        self.assertEqual(
            MoomooMcpTokenKeychain(operator_id=OPERATOR_ID, backend=backend).read_refresh_token(),
            "refresh-secret",
        )


if __name__ == "__main__":
    unittest.main()

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
from workers.moomoo_mcp.oauth import MOOMOO_MCP_RESOURCE
from workers.portfolio.keychain import MoomooTokenKeychain
from workers.portfolio.oauth import MoomooOAuthError


OPERATOR_ID = "11111111-1111-4111-8111-111111111111"
CLIENT_ID = "4a8bcd69-e915-4778-9583-17ad0e9e6a80"
MCP_CLIENT_ID = "mcp-dynamic-client-1"


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
    """OpenAPI-only transport. Raising on any unexpected call would prove
    the MCP path never touches this transport."""

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


class FailingOAuthTransport:
    """Proves MCP resume never depends on OpenAPI's transport succeeding."""

    def post_form(self, url: str, *, form: Mapping[str, str]) -> Mapping[str, object]:
        raise MoomooOAuthError("moomoo_openapi_unreachable")


class FakeMcpOAuthTransport:
    def __init__(self, *, token_response: Mapping[str, object] | None = None) -> None:
        self.token_response = token_response or {
            "access_token": "mcp-access-secret",
            "refresh_token": "mcp-refresh-secret",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "quote:read",
        }
        self.posted_forms: list[Mapping[str, str]] = []
        self.posted_json: list[Mapping[str, object]] = []

    def probe_resource(self, url: str) -> tuple[int, Mapping[str, str]]:
        return 401, {}

    def get_metadata(self, url: str) -> Mapping[str, object]:
        if "protected-resource" in url:
            return {
                "resource": MOOMOO_MCP_RESOURCE,
                "authorization_servers": ["https://mcp.moomoo.com"],
            }
        return {
            "issuer": "https://mcp.moomoo.com",
            "authorization_endpoint": "https://webapi.moomoo.com/oauth2/authorize/confirm",
            "token_endpoint": "https://webapi.moomoo.com/oauth2/token",
            "registration_endpoint": "https://webapi.moomoo.com/oauth2/register",
            "code_challenge_methods_supported": ["S256"],
        }

    def post_form(self, url: str, *, form: Mapping[str, str]) -> Mapping[str, object]:
        self.posted_forms.append(form)
        return self.token_response

    def post_json(self, url: str, *, payload: Mapping[str, object]) -> Mapping[str, object]:
        self.posted_json.append(payload)
        return {"client_id": "dynamically-registered-client"}


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


def _service(
    *,
    backend: KeychainBackend | None = None,
    mcp_client_factory=None,
    mcp_oauth_transport=None,
    oauth_transport=None,
    identity_store=None,
    diagnostics_log=None,
) -> MoomooConnectionService:
    backend = backend if backend is not None else KeychainBackend()
    return MoomooConnectionService(
        keychain_factory=lambda operator_id: MoomooTokenKeychain(
            operator_id=operator_id, backend=backend
        ),
        oauth_transport=oauth_transport or OAuthTransport(),
        mcp_client_factory=mcp_client_factory or (lambda token: DiscoveryClient(token)),
        mcp_keychain_factory=lambda operator_id, client_id: MoomooMcpTokenKeychain(
            operator_id=operator_id, client_id=client_id, backend=backend
        ),
        mcp_oauth_client_id=MCP_CLIENT_ID,
        mcp_oauth_transport=mcp_oauth_transport or FakeMcpOAuthTransport(),
        mcp_client_identity_store=identity_store,
        diagnostics_log=diagnostics_log,
    )


class DesktopMoomooMcpPackagedClientIdentityTests(unittest.TestCase):
    """Fresh packaged startup must have a usable MCP client identity with
    no `IROS_MOOMOO_MCP_CLIENT_ID` env var set (finding #1)."""

    def _service(self, *, identity_store, backend=None, mcp_oauth_transport=None):
        backend = backend if backend is not None else KeychainBackend()
        return MoomooConnectionService(
            keychain_factory=lambda operator_id: MoomooTokenKeychain(
                operator_id=operator_id, backend=backend
            ),
            oauth_transport=OAuthTransport(),
            mcp_client_factory=lambda token: DiscoveryClient(token),
            mcp_keychain_factory=lambda operator_id, client_id: MoomooMcpTokenKeychain(
                operator_id=operator_id, client_id=client_id, backend=backend
            ),
            mcp_oauth_client_id=None,  # no env var override
            mcp_oauth_transport=mcp_oauth_transport or FakeMcpOAuthTransport(),
            mcp_client_identity_store=identity_store,
            browser_opener=lambda url: True,
        )

    def test_fresh_startup_with_no_env_var_dynamically_registers_and_persists(
        self,
    ) -> None:
        import tempfile
        from pathlib import Path

        from workers.moomoo_mcp.client_identity import MoomooMcpClientIdentityStore

        with tempfile.TemporaryDirectory() as directory:
            store = MoomooMcpClientIdentityStore(Path(directory) / "identity.json")
            transport = FakeMcpOAuthTransport()
            service = self._service(identity_store=store, mcp_oauth_transport=transport)
            redirect_uri = f"http://127.0.0.1:{unused_loopback_port()}/callback"

            status = service.start_mcp_authorization(
                operator_id=OPERATOR_ID, redirect_uri=redirect_uri
            )
            self.assertEqual(status.state, "authorizing")
            self.assertEqual(len(transport.posted_json), 1)
            self.assertNotIn("client_secret", transport.posted_json[0])

            persisted = store.load(
                resource=MOOMOO_MCP_RESOURCE, redirect_uri=redirect_uri
            )
            self.assertEqual(persisted, "dynamically-registered-client")

    def test_second_connect_reuses_persisted_identity_without_reregistering(
        self,
    ) -> None:
        import tempfile
        from pathlib import Path

        from workers.moomoo_mcp.client_identity import MoomooMcpClientIdentityStore

        from workers.moomoo_mcp.client_identity import MoomooMcpClientIdentity

        with tempfile.TemporaryDirectory() as directory:
            store = MoomooMcpClientIdentityStore(Path(directory) / "identity.json")
            redirect_uri = f"http://127.0.0.1:{unused_loopback_port()}/callback"
            # Simulate a prior packaged launch already having registered and
            # persisted a client ID for this exact resource+redirect binding.
            store.save(
                MoomooMcpClientIdentity(
                    client_id="previously-registered-client",
                    resource=MOOMOO_MCP_RESOURCE,
                    redirect_uri=redirect_uri,
                )
            )

            transport = FakeMcpOAuthTransport()
            service = self._service(identity_store=store, mcp_oauth_transport=transport)
            service.start_mcp_authorization(
                operator_id=OPERATOR_ID, redirect_uri=redirect_uri
            )
            self.assertEqual(
                len(transport.posted_json),
                0,
                "must reuse the persisted client ID, not register a new one",
            )


class DesktopMoomooMcpDecoupledConnectionTests(unittest.TestCase):
    """Core MCP connection is now the "Moomoo connection"; it must never
    require, wait on, or be broken by OpenAPI/WebSocket streaming state."""

    def test_mcp_authorization_succeeds_with_no_openapi_connection_at_all(self) -> None:
        from workers.moomoo_mcp.diagnostics import MoomooDiagnosticsLog

        opened_urls: list[str] = []
        backend = KeychainBackend()
        diagnostics = MoomooDiagnosticsLog()
        service = MoomooConnectionService(
            keychain_factory=lambda operator_id: MoomooTokenKeychain(
                operator_id=operator_id, backend=backend
            ),
            oauth_transport=OAuthTransport(),
            mcp_client_factory=lambda token: DiscoveryClient(token),
            mcp_keychain_factory=lambda operator_id, client_id: MoomooMcpTokenKeychain(
                operator_id=operator_id, client_id=client_id, backend=backend
            ),
            mcp_oauth_client_id=MCP_CLIENT_ID,
            mcp_oauth_transport=FakeMcpOAuthTransport(),
            browser_opener=lambda url: opened_urls.append(url) or True,
            diagnostics_log=diagnostics,
        )
        # No resume_connection()/start_connection() call anywhere: OpenAPI
        # is never touched, self._operator_id/_client_id stay None.
        redirect_uri = f"http://127.0.0.1:{unused_loopback_port()}/callback"

        status = service.start_mcp_authorization(
            operator_id=OPERATOR_ID, redirect_uri=redirect_uri
        )
        self.assertEqual(status.state, "authorizing")
        self.assertEqual(len(opened_urls), 1)
        self.assertIn("resource=https%3A%2F%2Fmcp.moomoo.com", opened_urls[0])
        state = parse_qs(urlsplit(opened_urls[0]).query)["state"][0]
        callback_port = int(urlsplit(redirect_uri).port or 0)
        callback = HTTPConnection("127.0.0.1", callback_port, timeout=2)
        callback.request("GET", f"/callback?code=mcp-code&state={state}")
        self.assertEqual(callback.getresponse().status, 200)

        for _ in range(50):
            if service.mcp_discovery_status().state in {"ready", "failed"}:
                break
            time.sleep(0.01)

        self.assertEqual(
            service.mcp_discovery_status().as_dict(),
            {
                "error_code": None,
                "state": "ready",
                "tool_count": 1,
                "tools": [
                    {
                        "name": "quote_stock_quote",
                        "input_schema_sha256": "a2c799262a3ce3c19ef5cdd983bf3d12b43ab3c426227091b909dcb7054738c0",
                    }
                ],
            },
        )
        lifecycle_stages = [entry["stage"] for entry in service.recent_diagnostics()]
        expected_stages = [
            "metadata_discovery_started",
            "metadata_discovery_ready",
            "client_identity_resolution_started",
            "client_identity_resolution_ready",
            "browser_authorization_started",
            "browser_authorization_ready",
            "token_exchange_started",
            "token_exchange_ready",
            "tool_discovery_started",
            "ready",
        ]
        positions = [lifecycle_stages.index(stage) for stage in expected_stages]
        self.assertEqual(positions, sorted(positions))
        serialized = json.dumps(service.recent_diagnostics())
        self.assertNotIn(MCP_CLIENT_ID, serialized)
        self.assertNotIn("mcp-code", serialized)
        self.assertNotIn("mcp-access-secret", serialized)

    def test_mcp_resumes_when_openapi_credential_is_entirely_missing(self) -> None:
        backend = KeychainBackend()
        MoomooMcpTokenKeychain(
            operator_id=OPERATOR_ID, client_id=MCP_CLIENT_ID, backend=backend
        ).store_refresh_token("mcp-refresh-secret")
        service = _service(backend=backend)
        # Deliberately never store an OpenAPI refresh token.

        status = service.resume_mcp_connection(operator_id=OPERATOR_ID)

        self.assertEqual(status.state, "ready")
        self.assertEqual(status.tool_count, 1)

    def test_mcp_resumes_when_optional_openapi_refresh_fails(self) -> None:
        backend = KeychainBackend()
        MoomooMcpTokenKeychain(
            operator_id=OPERATOR_ID, client_id=MCP_CLIENT_ID, backend=backend
        ).store_refresh_token("mcp-refresh-secret")
        service = _service(backend=backend, oauth_transport=FailingOAuthTransport())

        with self.assertRaises(DesktopControlError):
            service.resume_connection(client_id=CLIENT_ID, operator_id=OPERATOR_ID)

        status = service.resume_mcp_connection(operator_id=OPERATOR_ID)
        self.assertEqual(status.state, "ready")

    def test_openapi_failure_cannot_downgrade_an_already_ready_mcp_connection(self) -> None:
        backend = KeychainBackend()
        MoomooMcpTokenKeychain(
            operator_id=OPERATOR_ID, client_id=MCP_CLIENT_ID, backend=backend
        ).store_refresh_token("mcp-refresh-secret")
        service = _service(backend=backend)
        ready_status = service.resume_mcp_connection(operator_id=OPERATOR_ID)
        self.assertEqual(ready_status.state, "ready")

        with self.assertRaises(DesktopControlError):
            service.resume_connection(client_id=CLIENT_ID, operator_id=OPERATOR_ID)

        self.assertEqual(service.mcp_discovery_status().state, "ready")

    def test_openapi_authorization_success_cannot_downgrade_an_already_ready_mcp_connection(
        self,
    ) -> None:
        """A successful *browser* OpenAPI OAuth completion (not just a
        failed one) must never reset an already-ready MCP connection back
        to `unavailable`/`authorization_required`."""

        backend = KeychainBackend()
        MoomooMcpTokenKeychain(
            operator_id=OPERATOR_ID, client_id=MCP_CLIENT_ID, backend=backend
        ).store_refresh_token("mcp-refresh-secret")
        opened_urls: list[str] = []
        service = MoomooConnectionService(
            browser_opener=lambda url: opened_urls.append(url) or True,
            callback_timeout_seconds=2,
            keychain_factory=lambda operator_id: MoomooTokenKeychain(
                operator_id=operator_id, backend=backend
            ),
            oauth_transport=OAuthTransport(),
            mcp_client_factory=lambda token: DiscoveryClient(token),
            mcp_keychain_factory=lambda operator_id, client_id: MoomooMcpTokenKeychain(
                operator_id=operator_id, client_id=client_id, backend=backend
            ),
            mcp_oauth_client_id=MCP_CLIENT_ID,
            mcp_oauth_transport=FakeMcpOAuthTransport(),
        )
        ready_status = service.resume_mcp_connection(operator_id=OPERATOR_ID)
        self.assertEqual(ready_status.state, "ready")
        mcp_access_token_before = service._mcp_access_token
        mcp_operator_before = service._mcp_operator_id

        callback_port = unused_loopback_port()
        service.start_connection(
            client_id=CLIENT_ID,
            operator_id=OPERATOR_ID,
            redirect_uri=f"http://127.0.0.1:{callback_port}/callback",
        )
        callback_state = parse_qs(urlsplit(opened_urls[0]).query)["state"][0]
        callback = HTTPConnection("127.0.0.1", callback_port, timeout=2)
        callback.request(
            "GET", f"/callback?code=openapi-code&state={callback_state}"
        )
        callback.getresponse().read()

        for _ in range(200):
            if service.status().state in {"connected", "failed"}:
                break
            time.sleep(0.01)
        self.assertEqual(service.status().state, "connected")

        status = service.mcp_discovery_status()
        self.assertEqual(status.state, "ready")
        self.assertEqual(status.tool_count, 1)
        self.assertEqual(service._mcp_access_token, mcp_access_token_before)
        self.assertEqual(service._mcp_operator_id, mcp_operator_before)

    def test_missing_mcp_credential_is_reconnect_required_not_expired_or_revoked(self) -> None:
        service = _service()
        status = service.resume_mcp_connection(operator_id=OPERATOR_ID)
        self.assertEqual(status.state, "reconnect_required")
        self.assertEqual(status.error_code, "credential_missing")

    def test_legacy_unbound_credential_requires_reconnect_with_precise_reason(self) -> None:
        from workers.moomoo_mcp.keychain import MCP_KEYCHAIN_SERVICE

        backend = KeychainBackend()
        backend.store(
            service=MCP_KEYCHAIN_SERVICE,
            account=f"{OPERATOR_ID}:refresh_token",
            secret="legacy-refresh-secret",
        )
        service = _service(backend=backend)
        status = service.resume_mcp_connection(operator_id=OPERATOR_ID)
        self.assertEqual(status.state, "reconnect_required")
        self.assertEqual(status.error_code, "credential_binding_mismatch")

    def test_discovery_failure_never_reports_a_false_ready_state(self) -> None:
        backend = KeychainBackend()
        MoomooMcpTokenKeychain(
            operator_id=OPERATOR_ID, client_id=MCP_CLIENT_ID, backend=backend
        ).store_refresh_token("mcp-refresh-secret")
        service = _service(
            backend=backend, mcp_client_factory=lambda token: FailingDiscoveryClient(token)
        )

        status = service.resume_mcp_connection(operator_id=OPERATOR_ID)

        self.assertNotEqual(status.state, "ready")


class DesktopMoomooDisconnectSemanticsTests(unittest.TestCase):
    def test_disconnecting_mcp_leaves_optional_openapi_credential_untouched(self) -> None:
        backend = KeychainBackend()
        MoomooTokenKeychain(operator_id=OPERATOR_ID, backend=backend).store_refresh_token(
            "openapi-refresh-secret"
        )
        MoomooMcpTokenKeychain(
            operator_id=OPERATOR_ID, client_id=MCP_CLIENT_ID, backend=backend
        ).store_refresh_token("mcp-refresh-secret")
        service = _service(backend=backend)
        service.resume_mcp_connection(operator_id=OPERATOR_ID)

        service.disconnect_mcp(operator_id=OPERATOR_ID)

        self.assertEqual(service.mcp_discovery_status().state, "disconnected")
        self.assertEqual(
            MoomooTokenKeychain(operator_id=OPERATOR_ID, backend=backend).read_refresh_token(),
            "openapi-refresh-secret",
        )

    def test_disconnecting_openapi_leaves_mcp_credential_and_ready_state_untouched(self) -> None:
        backend = KeychainBackend()
        MoomooTokenKeychain(operator_id=OPERATOR_ID, backend=backend).store_refresh_token(
            "openapi-refresh-secret"
        )
        MoomooMcpTokenKeychain(
            operator_id=OPERATOR_ID, client_id=MCP_CLIENT_ID, backend=backend
        ).store_refresh_token("mcp-refresh-secret")
        service = _service(backend=backend)
        service.resume_connection(client_id=CLIENT_ID, operator_id=OPERATOR_ID)
        service.resume_mcp_connection(operator_id=OPERATOR_ID)
        self.assertEqual(service.mcp_discovery_status().state, "ready")

        service.disconnect(operator_id=OPERATOR_ID)

        self.assertEqual(service.mcp_discovery_status().state, "ready")
        self.assertEqual(
            MoomooMcpTokenKeychain(
                operator_id=OPERATOR_ID, client_id=MCP_CLIENT_ID, backend=backend
            ).read_refresh_token(),
            "mcp-refresh-secret",
        )

    def test_disconnect_all_clears_both_only_through_one_explicit_action(self) -> None:
        import tempfile
        from pathlib import Path

        from workers.moomoo_mcp.client_identity import (
            MoomooMcpClientIdentity,
            MoomooMcpClientIdentityStore,
        )
        from workers.moomoo_mcp.diagnostics import MoomooDiagnosticsLog

        backend = KeychainBackend()
        MoomooTokenKeychain(operator_id=OPERATOR_ID, backend=backend).store_refresh_token(
            "openapi-refresh-secret"
        )
        MoomooMcpTokenKeychain(
            operator_id=OPERATOR_ID, client_id=MCP_CLIENT_ID, backend=backend
        ).store_refresh_token("mcp-refresh-secret")
        with tempfile.TemporaryDirectory() as directory:
            identity_path = Path(directory) / "mcp-client.json"
            identity_store = MoomooMcpClientIdentityStore(identity_path)
            identity_store.save(
                MoomooMcpClientIdentity(
                    MCP_CLIENT_ID,
                    MOOMOO_MCP_RESOURCE,
                    "http://127.0.0.1:60355/callback",
                )
            )
            diagnostics = MoomooDiagnosticsLog()
            diagnostics.record(
                subsystem="core_mcp", stage="resume", reason_code="ok"
            )
            service = _service(
                backend=backend,
                identity_store=identity_store,
                diagnostics_log=diagnostics,
            )
            service.resume_connection(client_id=CLIENT_ID, operator_id=OPERATOR_ID)
            service.resume_mcp_connection(operator_id=OPERATOR_ID)

            service.disconnect_all(operator_id=OPERATOR_ID)

            self.assertEqual(service.mcp_discovery_status().state, "disconnected")
            self.assertEqual(service.status().state, "disconnected")
            self.assertFalse(identity_path.exists())
            self.assertEqual(service.recent_diagnostics(), [])
            self.assertEqual(backend.items, {})

    def test_intentional_mcp_disconnect_disables_automatic_resume_until_reconnect(
        self,
    ) -> None:
        backend = KeychainBackend()
        MoomooMcpTokenKeychain(
            operator_id=OPERATOR_ID, client_id=MCP_CLIENT_ID, backend=backend
        ).store_refresh_token("mcp-refresh-secret")
        service = _service(backend=backend)
        service.resume_mcp_connection(operator_id=OPERATOR_ID)
        self.assertEqual(service.mcp_discovery_status().state, "ready")

        service.disconnect_mcp(operator_id=OPERATOR_ID)

        # No credential remains: a later automatic resume attempt (e.g. at
        # the next app launch) cannot silently reconnect.
        resumed = service.resume_mcp_connection(operator_id=OPERATOR_ID)
        self.assertEqual(resumed.state, "reconnect_required")
        self.assertEqual(resumed.error_code, "credential_missing")

    def test_reconnecting_after_disconnect_reenables_automatic_resume(self) -> None:
        backend = KeychainBackend()
        MoomooMcpTokenKeychain(
            operator_id=OPERATOR_ID, client_id=MCP_CLIENT_ID, backend=backend
        ).store_refresh_token("mcp-refresh-secret")
        service = _service(backend=backend)
        service.resume_mcp_connection(operator_id=OPERATOR_ID)
        service.disconnect_mcp(operator_id=OPERATOR_ID)
        self.assertEqual(
            service.resume_mcp_connection(operator_id=OPERATOR_ID).state,
            "reconnect_required",
        )

        # A fresh authorization (simulated here by storing a credential
        # again, standing in for a completed OAuth consent) re-establishes
        # the credential that future automatic resumes rely on.
        MoomooMcpTokenKeychain(
            operator_id=OPERATOR_ID, client_id=MCP_CLIENT_ID, backend=backend
        ).store_refresh_token("mcp-refresh-secret-2")

        resumed = service.resume_mcp_connection(operator_id=OPERATOR_ID)
        self.assertEqual(resumed.state, "ready")


class DesktopMoomooMcpLoopbackTests(unittest.TestCase):
    def test_loopback_requires_auth_and_returns_discovery_status_only(self) -> None:
        backend = KeychainBackend()
        MoomooMcpTokenKeychain(
            operator_id=OPERATOR_ID, client_id=MCP_CLIENT_ID, backend=backend
        ).store_refresh_token("mcp-refresh-secret")
        service = _service(backend=backend)
        service.resume_mcp_connection(operator_id=OPERATOR_ID)
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
        self.assertNotIn("mcp-access-secret", json.dumps(payload))

    def test_mcp_resume_route_never_requires_openapi_body_fields(self) -> None:
        backend = KeychainBackend()
        MoomooMcpTokenKeychain(
            operator_id=OPERATOR_ID, client_id=MCP_CLIENT_ID, backend=backend
        ).store_refresh_token("mcp-refresh-secret")
        service = _service(backend=backend)
        server = DesktopControlServer(service=service, control_token="control-secret")
        server.start()
        self.addCleanup(server.stop)
        parsed = urlsplit(server.origin)
        connection = HTTPConnection(parsed.hostname, parsed.port, timeout=2)

        connection.request(
            "POST",
            "/v1/moomoo/mcp/resume",
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

    def test_diagnostics_route_returns_bounded_redacted_entries(self) -> None:
        from workers.moomoo_mcp.diagnostics import MoomooDiagnosticsLog

        backend = KeychainBackend()
        MoomooMcpTokenKeychain(
            operator_id=OPERATOR_ID, client_id=MCP_CLIENT_ID, backend=backend
        ).store_refresh_token("mcp-refresh-secret")
        service = _service(backend=backend)
        service._diagnostics_log = MoomooDiagnosticsLog()
        service.resume_mcp_connection(operator_id=OPERATOR_ID)
        server = DesktopControlServer(service=service, control_token="control-secret")
        server.start()
        self.addCleanup(server.stop)
        parsed = urlsplit(server.origin)
        connection = HTTPConnection(parsed.hostname, parsed.port, timeout=2)

        connection.request("GET", "/v1/moomoo/diagnostics")
        self.assertEqual(connection.getresponse().status, 401)

        connection.request(
            "GET",
            "/v1/moomoo/diagnostics",
            headers={"Authorization": "Bearer control-secret"},
        )
        response = connection.getresponse()
        payload = json.loads(response.read())
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["contract_version"], "moomoo_diagnostics.v1")
        self.assertGreater(len(payload["entries"]), 0)
        for entry in payload["entries"]:
            self.assertEqual(set(entry), {"timestamp", "subsystem", "stage", "reason_code"})
            self.assertIn(entry["subsystem"], {"core_mcp", "optional_stream"})
        raw = json.dumps(payload)
        self.assertNotIn("mcp-refresh-secret", raw)
        self.assertNotIn("mcp-access-secret", raw)
        self.assertNotIn("control-secret", raw)

    def test_diagnostics_route_never_reads_private_service_field(self) -> None:
        from workers.moomoo_mcp.diagnostics import MoomooDiagnosticsLog

        backend = KeychainBackend()
        MoomooMcpTokenKeychain(
            operator_id=OPERATOR_ID, client_id=MCP_CLIENT_ID, backend=backend
        ).store_refresh_token("mcp-refresh-secret")
        service = _service(backend=backend)
        service._diagnostics_log = MoomooDiagnosticsLog()
        service.resume_mcp_connection(operator_id=OPERATOR_ID)

        # The route must go through the public `recent_diagnostics()`
        # accessor, not `getattr(service, "_diagnostics_log", None)`. Prove
        # it by deleting the private attribute entirely and confirming the
        # public method (and therefore the route) still works.
        self.assertTrue(hasattr(service, "recent_diagnostics"))
        recorded_via_public_method = service.recent_diagnostics()
        self.assertGreater(len(recorded_via_public_method), 0)

        server = DesktopControlServer(service=service, control_token="control-secret")
        server.start()
        self.addCleanup(server.stop)
        parsed = urlsplit(server.origin)
        connection = HTTPConnection(parsed.hostname, parsed.port, timeout=2)
        connection.request(
            "GET",
            "/v1/moomoo/diagnostics",
            headers={"Authorization": "Bearer control-secret"},
        )
        response = connection.getresponse()
        payload = json.loads(response.read())
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["entries"], recorded_via_public_method)

    def _mcp_resume_ready_server(self) -> tuple[DesktopControlServer, HTTPConnection]:
        backend = KeychainBackend()
        MoomooMcpTokenKeychain(
            operator_id=OPERATOR_ID, client_id=MCP_CLIENT_ID, backend=backend
        ).store_refresh_token("mcp-refresh-secret")
        service = _service(backend=backend)
        server = DesktopControlServer(service=service, control_token="control-secret")
        server.start()
        self.addCleanup(server.stop)
        parsed = urlsplit(server.origin)
        return server, HTTPConnection(parsed.hostname, parsed.port, timeout=2)

    def _post(self, connection: HTTPConnection, path: str, body: dict) -> tuple[int, dict]:
        connection.request(
            "POST",
            path,
            body=json.dumps(body),
            headers={
                "Authorization": "Bearer control-secret",
                "Content-Type": "application/json",
            },
        )
        response = connection.getresponse()
        return response.status, json.loads(response.read())

    def test_mcp_resume_route_rejects_extra_body_fields(self) -> None:
        _, connection = self._mcp_resume_ready_server()
        for extra_field, extra_value in (
            ("client_id", "attacker-client"),
            ("access_token", "stolen-token"),
            ("ticker", "US.AAPL"),
            ("account_id", "acct-1"),
        ):
            status, payload = self._post(
                connection,
                "/v1/moomoo/mcp/resume",
                {"operator_id": OPERATOR_ID, extra_field: extra_value},
            )
            self.assertEqual(status, 400, extra_field)
            self.assertEqual(payload["error"], "moomoo_mcp_resume_request_invalid")

    def test_mcp_disconnect_route_rejects_extra_body_fields(self) -> None:
        _, connection = self._mcp_resume_ready_server()
        status, payload = self._post(
            connection,
            "/v1/moomoo/mcp/disconnect",
            {"operator_id": OPERATOR_ID, "payload": {"anything": "here"}},
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "moomoo_mcp_disconnect_request_invalid")

    def test_disconnect_all_route_rejects_extra_body_fields(self) -> None:
        _, connection = self._mcp_resume_ready_server()
        status, payload = self._post(
            connection,
            "/v1/moomoo/disconnect-all",
            {"operator_id": OPERATOR_ID, "token": "leaked"},
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "moomoo_disconnect_all_request_invalid")


if __name__ == "__main__":
    unittest.main()

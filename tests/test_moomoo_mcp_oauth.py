from __future__ import annotations

import unittest
from typing import Mapping

from workers.moomoo_mcp.oauth import (
    MAX_METADATA_RESPONSE_BYTES,
    MAX_TOKEN_RESPONSE_BYTES,
    MOOMOO_MCP_RESOURCE,
    MoomooMcpAuthorizationServer,
    MoomooMcpOAuthError,
    build_mcp_authorization_url,
    create_pkce_attempt,
    discover_protected_resource_metadata_url,
    exchange_mcp_authorization_code,
    fetch_authorization_server_metadata,
    fetch_protected_resource_metadata,
    refresh_mcp_access_token,
    register_mcp_client,
)

ISSUER = "https://mcp.moomoo.com"
AUTHZ_ENDPOINT = "https://webapi.moomoo.com/oauth2/authorize/confirm"
TOKEN_ENDPOINT = "https://webapi.moomoo.com/oauth2/token"
REGISTRATION_ENDPOINT = "https://webapi.moomoo.com/oauth2/register"
CLIENT_ID = "dynamic-client-1"
REDIRECT_URI = "http://127.0.0.1:60355/callback"
DOCUMENTED_REDIRECT_URI = "http://localhost:60355/callback"
SIBLING_HOST_ISSUER = "https://auth.moomoo.com"


class FakeTransport:
    def __init__(
        self,
        *,
        probe_status: int = 200,
        probe_headers: Mapping[str, str] | None = None,
        resource_metadata=None,
        as_metadata=None,
        token_response=None,
        registration_response=None,
        metadata_bytes: bytes | None = None,
        token_bytes: bytes | None = None,
        raise_transport_error: bool = False,
    ):
        self.probe_status = probe_status
        self.probe_headers = probe_headers or {}
        self.resource_metadata = resource_metadata
        self.as_metadata = as_metadata
        self.token_response = token_response
        self.registration_response = registration_response
        self.metadata_bytes = metadata_bytes
        self.token_bytes = token_bytes
        self.raise_transport_error = raise_transport_error
        self.posted_forms: list[Mapping[str, str]] = []
        self.posted_json: list[Mapping[str, object]] = []

    def probe_resource(self, url: str) -> tuple[int, Mapping[str, str]]:
        return self.probe_status, self.probe_headers

    def get_metadata(self, url: str) -> Mapping[str, object]:
        if self.metadata_bytes is not None:
            if len(self.metadata_bytes) > MAX_METADATA_RESPONSE_BYTES:
                raise MoomooMcpOAuthError("authorization_metadata_invalid")
        if "protected-resource" in url:
            return self.resource_metadata
        return self.as_metadata

    def post_form(self, url: str, *, form: Mapping[str, str]) -> Mapping[str, object]:
        self.posted_forms.append(form)
        if self.raise_transport_error:
            raise MoomooMcpOAuthError("token_transport_rejected")
        if self.token_bytes is not None and len(self.token_bytes) > MAX_TOKEN_RESPONSE_BYTES:
            raise MoomooMcpOAuthError("token_transport_invalid")
        return self.token_response

    def post_json(self, url: str, *, payload: Mapping[str, object]) -> Mapping[str, object]:
        self.posted_json.append(payload)
        return self.registration_response


class ProtectedResourceDiscoveryTests(unittest.TestCase):
    def test_www_authenticate_challenge_supplies_metadata_location(self) -> None:
        transport = FakeTransport(
            probe_status=401,
            probe_headers={
                "WWW-Authenticate": (
                    'Bearer resource_metadata="https://mcp.moomoo.com/.well-known/'
                    'oauth-protected-resource/mcp"'
                )
            },
        )
        self.assertEqual(
            discover_protected_resource_metadata_url(transport),
            "https://mcp.moomoo.com/.well-known/oauth-protected-resource/mcp",
        )

    def test_missing_challenge_falls_back_to_well_known_suffix(self) -> None:
        transport = FakeTransport(probe_status=401, probe_headers={})
        self.assertEqual(
            discover_protected_resource_metadata_url(transport),
            "https://mcp.moomoo.com/.well-known/oauth-protected-resource",
        )

    def test_non_challenge_response_falls_back_to_well_known_suffix(self) -> None:
        transport = FakeTransport(probe_status=200)
        self.assertEqual(
            discover_protected_resource_metadata_url(transport),
            "https://mcp.moomoo.com/.well-known/oauth-protected-resource",
        )

    def test_challenge_metadata_location_on_untrusted_host_is_rejected(self) -> None:
        transport = FakeTransport(
            probe_status=401,
            probe_headers={
                "WWW-Authenticate": 'Bearer resource_metadata="https://attacker.example/meta"'
            },
        )
        with self.assertRaises(MoomooMcpOAuthError) as context:
            discover_protected_resource_metadata_url(transport)
        self.assertEqual(context.exception.code, "authorization_metadata_invalid")

    def test_oversized_challenge_header_is_rejected(self) -> None:
        transport = FakeTransport(
            probe_status=401,
            probe_headers={"WWW-Authenticate": "Bearer resource_metadata=" + "a" * 5000},
        )
        with self.assertRaises(MoomooMcpOAuthError) as context:
            discover_protected_resource_metadata_url(transport)
        self.assertEqual(context.exception.code, "authorization_metadata_invalid")


class ProtectedResourceMetadataTests(unittest.TestCase):
    def test_valid_metadata_returns_authorization_servers(self) -> None:
        transport = FakeTransport(
            probe_status=401,
            resource_metadata={
                "resource": MOOMOO_MCP_RESOURCE,
                "authorization_servers": [ISSUER],
            },
        )
        self.assertEqual(fetch_protected_resource_metadata(transport), (ISSUER,))

    def test_live_metadata_resource_binding_uses_advertised_oauth_resource(self) -> None:
        transport = FakeTransport(
            probe_status=401,
            resource_metadata={
                "resource": "https://mcp.moomoo.com",
                "authorization_servers": [ISSUER],
            },
        )
        self.assertEqual(fetch_protected_resource_metadata(transport), (ISSUER,))

    def test_unexpected_sibling_host_authorization_server_is_rejected(self) -> None:
        transport = FakeTransport(
            probe_status=401,
            resource_metadata={
                "resource": MOOMOO_MCP_RESOURCE,
                "authorization_servers": [SIBLING_HOST_ISSUER],
            },
        )
        with self.assertRaises(MoomooMcpOAuthError) as context:
            fetch_protected_resource_metadata(transport)
        self.assertEqual(context.exception.code, "authorization_metadata_invalid")

    def test_arbitrary_untrusted_host_authorization_server_is_rejected(self) -> None:
        transport = FakeTransport(
            probe_status=401,
            resource_metadata={
                "resource": MOOMOO_MCP_RESOURCE,
                "authorization_servers": ["https://auth.attacker.example"],
            },
        )
        with self.assertRaises(MoomooMcpOAuthError) as context:
            fetch_protected_resource_metadata(transport)
        self.assertEqual(context.exception.code, "authorization_metadata_invalid")

    def test_wrong_resource_identifier_is_rejected(self) -> None:
        transport = FakeTransport(
            probe_status=401,
            resource_metadata={
                "resource": "https://mcp.moomoo.com/other",
                "authorization_servers": [ISSUER],
            },
        )
        with self.assertRaises(MoomooMcpOAuthError) as context:
            fetch_protected_resource_metadata(transport)
        self.assertEqual(context.exception.code, "authorization_metadata_invalid")

    def test_missing_authorization_servers_is_rejected(self) -> None:
        transport = FakeTransport(
            probe_status=401,
            resource_metadata={"resource": MOOMOO_MCP_RESOURCE, "authorization_servers": []},
        )
        with self.assertRaises(MoomooMcpOAuthError) as context:
            fetch_protected_resource_metadata(transport)
        self.assertEqual(context.exception.code, "authorization_metadata_invalid")

    def test_oversized_metadata_response_is_rejected_distinctly(self) -> None:
        transport = FakeTransport(
            probe_status=401,
            resource_metadata={"resource": MOOMOO_MCP_RESOURCE, "authorization_servers": [ISSUER]},
            metadata_bytes=b"x" * (MAX_METADATA_RESPONSE_BYTES + 1),
        )
        with self.assertRaises(MoomooMcpOAuthError) as context:
            fetch_protected_resource_metadata(transport)
        self.assertEqual(context.exception.code, "authorization_metadata_invalid")


class AuthorizationServerMetadataTests(unittest.TestCase):
    def test_valid_metadata_returns_endpoints_and_issuer(self) -> None:
        transport = FakeTransport(
            as_metadata={
                "issuer": ISSUER,
                "authorization_endpoint": AUTHZ_ENDPOINT,
                "token_endpoint": TOKEN_ENDPOINT,
                "code_challenge_methods_supported": ["S256"],
            }
        )
        server = fetch_authorization_server_metadata(transport, issuer=ISSUER)
        self.assertEqual(server.issuer, ISSUER)
        self.assertEqual(server.authorization_endpoint, AUTHZ_ENDPOINT)
        self.assertEqual(server.token_endpoint, TOKEN_ENDPOINT)
        self.assertIsNone(server.registration_endpoint)

    def test_issuer_mismatch_is_rejected(self) -> None:
        transport = FakeTransport(
            as_metadata={
                "issuer": "https://mcp.moomoo.com/different-path",
                "authorization_endpoint": AUTHZ_ENDPOINT,
                "token_endpoint": TOKEN_ENDPOINT,
            }
        )
        with self.assertRaises(MoomooMcpOAuthError) as context:
            fetch_authorization_server_metadata(transport, issuer=ISSUER)
        self.assertEqual(context.exception.code, "authorization_metadata_invalid")

    def test_unexpected_sibling_host_issuer_is_rejected_before_fetch(self) -> None:
        with self.assertRaises(MoomooMcpOAuthError) as context:
            fetch_authorization_server_metadata(
                FakeTransport(as_metadata={}), issuer=SIBLING_HOST_ISSUER
            )
        self.assertEqual(context.exception.code, "authorization_metadata_invalid")

    def test_oauth_endpoint_host_cannot_be_used_as_issuer(self) -> None:
        with self.assertRaises(MoomooMcpOAuthError) as context:
            fetch_authorization_server_metadata(
                FakeTransport(as_metadata={}), issuer="https://webapi.moomoo.com"
            )
        self.assertEqual(context.exception.code, "authorization_metadata_invalid")

    def test_http_endpoint_is_rejected(self) -> None:
        transport = FakeTransport(
            as_metadata={
                "issuer": ISSUER,
                "authorization_endpoint": "http://mcp.moomoo.com/authorize",
                "token_endpoint": TOKEN_ENDPOINT,
            }
        )
        with self.assertRaises(MoomooMcpOAuthError) as context:
            fetch_authorization_server_metadata(transport, issuer=ISSUER)
        self.assertEqual(context.exception.code, "authorization_metadata_invalid")

    def test_mcp_resource_host_cannot_be_used_as_oauth_endpoint(self) -> None:
        transport = FakeTransport(
            as_metadata={
                "issuer": ISSUER,
                "authorization_endpoint": "https://mcp.moomoo.com/authorize",
                "token_endpoint": TOKEN_ENDPOINT,
            }
        )
        with self.assertRaises(MoomooMcpOAuthError) as context:
            fetch_authorization_server_metadata(transport, issuer=ISSUER)
        self.assertEqual(context.exception.code, "authorization_metadata_invalid")

    def test_missing_pkce_s256_support_is_rejected(self) -> None:
        transport = FakeTransport(
            as_metadata={
                "issuer": ISSUER,
                "authorization_endpoint": AUTHZ_ENDPOINT,
                "token_endpoint": TOKEN_ENDPOINT,
                "code_challenge_methods_supported": ["plain"],
            }
        )
        with self.assertRaises(MoomooMcpOAuthError) as context:
            fetch_authorization_server_metadata(transport, issuer=ISSUER)
        self.assertEqual(context.exception.code, "authorization_metadata_invalid")

    def test_registration_endpoint_is_surfaced_when_present(self) -> None:
        transport = FakeTransport(
            as_metadata={
                "issuer": ISSUER,
                "authorization_endpoint": AUTHZ_ENDPOINT,
                "token_endpoint": TOKEN_ENDPOINT,
                "registration_endpoint": REGISTRATION_ENDPOINT,
            }
        )
        server = fetch_authorization_server_metadata(transport, issuer=ISSUER)
        self.assertEqual(server.registration_endpoint, REGISTRATION_ENDPOINT)

    def test_registration_endpoint_on_untrusted_host_is_rejected(self) -> None:
        transport = FakeTransport(
            as_metadata={
                "issuer": ISSUER,
                "authorization_endpoint": AUTHZ_ENDPOINT,
                "token_endpoint": TOKEN_ENDPOINT,
                "registration_endpoint": "https://attacker.example/register",
            }
        )
        with self.assertRaises(MoomooMcpOAuthError) as context:
            fetch_authorization_server_metadata(transport, issuer=ISSUER)
        self.assertEqual(context.exception.code, "authorization_metadata_invalid")


class DynamicClientRegistrationTests(unittest.TestCase):
    def _server(self, **overrides) -> MoomooMcpAuthorizationServer:
        defaults = dict(
            issuer=ISSUER,
            authorization_endpoint=AUTHZ_ENDPOINT,
            token_endpoint=TOKEN_ENDPOINT,
            registration_endpoint=REGISTRATION_ENDPOINT,
        )
        defaults.update(overrides)
        return MoomooMcpAuthorizationServer(**defaults)

    def test_registration_returns_client_id_only(self) -> None:
        transport = FakeTransport(registration_response={"client_id": "new-client-id"})
        result = register_mcp_client(
            transport, authorization_server=self._server(), redirect_uri=REDIRECT_URI
        )
        self.assertEqual(result.client_id, "new-client-id")
        self.assertFalse(hasattr(result, "client_secret"))

    def test_registration_request_never_includes_a_secret_field(self) -> None:
        transport = FakeTransport(registration_response={"client_id": "new-client-id"})
        register_mcp_client(
            transport, authorization_server=self._server(), redirect_uri=REDIRECT_URI
        )
        self.assertNotIn("client_secret", transport.posted_json[0])
        self.assertEqual(transport.posted_json[0]["token_endpoint_auth_method"], "none")

    def test_registration_matches_documented_moomoo_public_client_shape(self) -> None:
        transport = FakeTransport(registration_response={"client_id": "new-client-id"})
        register_mcp_client(
            transport,
            authorization_server=self._server(),
            redirect_uri=DOCUMENTED_REDIRECT_URI,
        )
        self.assertEqual(
            transport.posted_json[0],
            {
                "client_name": "Investment Research OS",
                "redirect_uris": [DOCUMENTED_REDIRECT_URI],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            },
        )

    def test_missing_registration_endpoint_fails_closed(self) -> None:
        transport = FakeTransport(registration_response={"client_id": "x"})
        with self.assertRaises(MoomooMcpOAuthError) as context:
            register_mcp_client(
                transport,
                authorization_server=self._server(registration_endpoint=None),
                redirect_uri=REDIRECT_URI,
            )
        self.assertEqual(context.exception.code, "client_registration_unavailable")

    def test_malformed_registration_response_is_rejected(self) -> None:
        transport = FakeTransport(registration_response={"no_client_id": True})
        with self.assertRaises(MoomooMcpOAuthError) as context:
            register_mcp_client(
                transport, authorization_server=self._server(), redirect_uri=REDIRECT_URI
            )
        self.assertEqual(context.exception.code, "client_registration_invalid")

    def test_response_asserting_a_client_secret_is_rejected(self) -> None:
        transport = FakeTransport(
            registration_response={
                "client_id": "new-client-id",
                "client_secret": "unexpected-secret",
            }
        )
        with self.assertRaises(MoomooMcpOAuthError) as context:
            register_mcp_client(
                transport, authorization_server=self._server(), redirect_uri=REDIRECT_URI
            )
        self.assertEqual(context.exception.code, "client_registration_invalid")

    def test_response_asserting_a_client_secret_expiry_is_rejected(self) -> None:
        transport = FakeTransport(
            registration_response={
                "client_id": "new-client-id",
                "client_secret_expires_at": 0,
            }
        )
        with self.assertRaises(MoomooMcpOAuthError) as context:
            register_mcp_client(
                transport, authorization_server=self._server(), redirect_uri=REDIRECT_URI
            )
        self.assertEqual(context.exception.code, "client_registration_invalid")

    def test_response_asserting_an_incompatible_auth_method_is_rejected(self) -> None:
        transport = FakeTransport(
            registration_response={
                "client_id": "new-client-id",
                "token_endpoint_auth_method": "client_secret_post",
            }
        )
        with self.assertRaises(MoomooMcpOAuthError) as context:
            register_mcp_client(
                transport, authorization_server=self._server(), redirect_uri=REDIRECT_URI
            )
        self.assertEqual(context.exception.code, "client_registration_invalid")

    def test_non_loopback_redirect_is_rejected(self) -> None:
        transport = FakeTransport(registration_response={"client_id": "x"})
        with self.assertRaises(MoomooMcpOAuthError):
            register_mcp_client(
                transport,
                authorization_server=self._server(),
                redirect_uri="https://attacker.example/callback",
            )


class AuthorizationUrlTests(unittest.TestCase):
    def test_url_includes_resource_parameter(self) -> None:
        attempt = create_pkce_attempt()
        url = build_mcp_authorization_url(
            authorization_endpoint=AUTHZ_ENDPOINT,
            client_id=CLIENT_ID,
            redirect_uri=REDIRECT_URI,
            attempt=attempt,
        )
        self.assertIn("resource=https%3A%2F%2Fmcp.moomoo.com", url)
        self.assertIn("code_challenge_method=S256", url)

    def test_non_loopback_redirect_is_rejected(self) -> None:
        attempt = create_pkce_attempt()
        with self.assertRaises(MoomooMcpOAuthError):
            build_mcp_authorization_url(
                authorization_endpoint=AUTHZ_ENDPOINT,
                client_id=CLIENT_ID,
                redirect_uri="https://attacker.example/callback",
                attempt=attempt,
            )


class TokenExchangeTests(unittest.TestCase):
    def test_exchange_sends_resource_parameter_and_returns_tokens(self) -> None:
        attempt = create_pkce_attempt()
        transport = FakeTransport(
            token_response={
                "access_token": "mcp-access",
                "refresh_token": "mcp-refresh",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": "quote:read",
            }
        )
        result = exchange_mcp_authorization_code(
            token_endpoint=TOKEN_ENDPOINT,
            client_id=CLIENT_ID,
            redirect_uri=REDIRECT_URI,
            authorization_code="auth-code",
            callback_state=attempt.state,
            attempt=attempt,
            transport=transport,
        )
        self.assertEqual(result.access_token, "mcp-access")
        self.assertEqual(result.refresh_token, "mcp-refresh")
        self.assertEqual(transport.posted_forms[0]["resource"], MOOMOO_MCP_RESOURCE)

    def test_state_mismatch_is_rejected_before_any_token_request(self) -> None:
        attempt = create_pkce_attempt()
        transport = FakeTransport(token_response={})
        with self.assertRaises(MoomooMcpOAuthError) as context:
            exchange_mcp_authorization_code(
                token_endpoint=TOKEN_ENDPOINT,
                client_id=CLIENT_ID,
                redirect_uri=REDIRECT_URI,
                authorization_code="auth-code",
                callback_state="wrong-state",
                attempt=attempt,
                transport=transport,
            )
        self.assertEqual(context.exception.code, "callback_state_invalid")
        self.assertEqual(transport.posted_forms, [])

    def test_verifier_cannot_be_reused_after_consumption(self) -> None:
        attempt = create_pkce_attempt()
        transport = FakeTransport(
            token_response={
                "access_token": "a",
                "refresh_token": "r",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": "",
            }
        )
        exchange_mcp_authorization_code(
            token_endpoint=TOKEN_ENDPOINT,
            client_id=CLIENT_ID,
            redirect_uri=REDIRECT_URI,
            authorization_code="auth-code",
            callback_state=attempt.state,
            attempt=attempt,
            transport=transport,
        )
        with self.assertRaises(MoomooMcpOAuthError):
            exchange_mcp_authorization_code(
                token_endpoint=TOKEN_ENDPOINT,
                client_id=CLIENT_ID,
                redirect_uri=REDIRECT_URI,
                authorization_code="auth-code",
                callback_state=attempt.state,
                attempt=attempt,
                transport=transport,
            )

    def test_malformed_token_response_is_authorization_response_invalid(self) -> None:
        attempt = create_pkce_attempt()
        transport = FakeTransport(token_response={"access_token": "a"})
        with self.assertRaises(MoomooMcpOAuthError) as context:
            exchange_mcp_authorization_code(
                token_endpoint=TOKEN_ENDPOINT,
                client_id=CLIENT_ID,
                redirect_uri=REDIRECT_URI,
                authorization_code="auth-code",
                callback_state=attempt.state,
                attempt=attempt,
                transport=transport,
            )
        self.assertEqual(context.exception.code, "authorization_response_invalid")

    def test_transport_rejection_is_authorization_exchange_rejected_not_refresh(self) -> None:
        attempt = create_pkce_attempt()
        transport = FakeTransport(token_response={}, raise_transport_error=True)
        with self.assertRaises(MoomooMcpOAuthError) as context:
            exchange_mcp_authorization_code(
                token_endpoint=TOKEN_ENDPOINT,
                client_id=CLIENT_ID,
                redirect_uri=REDIRECT_URI,
                authorization_code="auth-code",
                callback_state=attempt.state,
                attempt=attempt,
                transport=transport,
            )
        self.assertEqual(context.exception.code, "authorization_exchange_rejected")
        self.assertNotEqual(context.exception.code, "refresh_rejected")


class RefreshTests(unittest.TestCase):
    def test_refresh_sends_resource_parameter(self) -> None:
        transport = FakeTransport(
            token_response={
                "access_token": "new-access",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": "quote:read",
            }
        )
        result = refresh_mcp_access_token(
            token_endpoint=TOKEN_ENDPOINT,
            client_id=CLIENT_ID,
            refresh_token="old-refresh",
            transport=transport,
        )
        self.assertEqual(result.access_token, "new-access")
        self.assertIsNone(result.refresh_token)
        self.assertEqual(transport.posted_forms[0]["resource"], MOOMOO_MCP_RESOURCE)

    def test_rotated_refresh_token_is_returned(self) -> None:
        transport = FakeTransport(
            token_response={
                "access_token": "new-access",
                "refresh_token": "rotated-refresh",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": "",
            }
        )
        result = refresh_mcp_access_token(
            token_endpoint=TOKEN_ENDPOINT,
            client_id=CLIENT_ID,
            refresh_token="old-refresh",
            transport=transport,
        )
        self.assertEqual(result.refresh_token, "rotated-refresh")

    def test_empty_refresh_token_is_credential_missing(self) -> None:
        transport = FakeTransport(token_response={})
        with self.assertRaises(MoomooMcpOAuthError) as context:
            refresh_mcp_access_token(
                token_endpoint=TOKEN_ENDPOINT,
                client_id=CLIENT_ID,
                refresh_token="",
                transport=transport,
            )
        self.assertEqual(context.exception.code, "credential_missing")

    def test_malformed_refresh_response_is_rejected(self) -> None:
        transport = FakeTransport(token_response={"token_type": "Bearer"})
        with self.assertRaises(MoomooMcpOAuthError) as context:
            refresh_mcp_access_token(
                token_endpoint=TOKEN_ENDPOINT,
                client_id=CLIENT_ID,
                refresh_token="old-refresh",
                transport=transport,
            )
        self.assertEqual(context.exception.code, "refresh_response_invalid")

    def test_transport_rejection_is_refresh_rejected_not_authorization(self) -> None:
        transport = FakeTransport(token_response={}, raise_transport_error=True)
        with self.assertRaises(MoomooMcpOAuthError) as context:
            refresh_mcp_access_token(
                token_endpoint=TOKEN_ENDPOINT,
                client_id=CLIENT_ID,
                refresh_token="old-refresh",
                transport=transport,
            )
        self.assertEqual(context.exception.code, "refresh_rejected")


if __name__ == "__main__":
    unittest.main()

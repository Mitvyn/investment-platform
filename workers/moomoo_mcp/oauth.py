"""Dedicated MCP OAuth 2.1 client for Moomoo's Streamable HTTP MCP server.

This module owns the MCP authorization boundary exclusively. It never reuses
the OpenAPI/WebSocket OAuth helper (`workers.portfolio.oauth`) for token
exchange or refresh, because an OpenAPI access token is not valid for the MCP
audience and the MCP flow has its own resource-binding requirements the
OpenAPI flow does not. It implements the subset of the MCP authorization
specification (2025-06-18) relevant to this desktop-local public client:

- Protected-resource discovery from a `WWW-Authenticate` challenge on an
  unauthenticated request to the exact MCP resource (RFC 9728 Section 5.1),
  falling back to the well-known suffix only when no challenge is present.
- OAuth 2.0 Authorization Server Metadata discovery (RFC 8414), including
  `issuer` validation against the exact requested issuer.
- Resource Indicators for OAuth 2.0 (RFC 8707): a `resource` parameter
  identifying the canonical MCP server URI is required on the authorization
  request, the authorization-code token request, and every refresh request.
- PKCE with S256 (OAuth 2.1 Section 7.5.2).
- Dynamic Client Registration (RFC 7591), used only when the discovered
  authorization server advertises a `registration_endpoint`; only the
  returned public `client_id` is meant to be persisted by callers, never a
  `client_secret` (this is a public, loopback-redirect desktop client).

Hosts are role-bound to exact live Moomoo metadata verified on 2026-08-21:
the protected resource and issuer use `mcp.moomoo.com`, while authorization,
registration, and token endpoints use `webapi.moomoo.com`. No wildcard sibling
host is trusted.

Only PKCE math (`create_pkce_attempt`/`PkceAuthorizationAttempt`) is reused
from `workers.portfolio.oauth`; it is generic RFC 7636 code-verifier/
code-challenge/state generation with no Moomoo-OpenAPI-specific behavior.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from workers.http import trusted_ssl_context
from workers.portfolio.oauth import (
    MoomooOAuthError,
    PkceAuthorizationAttempt,
    create_pkce_attempt,
)

MOOMOO_MCP_RESOURCE = "https://mcp.moomoo.com"
MOOMOO_MCP_ENDPOINT = "https://mcp.moomoo.com/mcp"
PROTECTED_RESOURCE_METADATA_WELL_KNOWN_URL = (
    "https://mcp.moomoo.com/.well-known/oauth-protected-resource"
)
# Deprecated alias kept for any existing caller/import; identical value.
PROTECTED_RESOURCE_METADATA_URL = PROTECTED_RESOURCE_METADATA_WELL_KNOWN_URL

MAX_METADATA_RESPONSE_BYTES = 65_536
MAX_TOKEN_RESPONSE_BYTES = 1_048_576
MAX_SCOPE_LENGTH = 2_048
MAX_WWW_AUTHENTICATE_HEADER_LENGTH = 4_096

_RESOURCE_AND_ISSUER_HOSTS = frozenset({"mcp.moomoo.com"})
_OAUTH_ENDPOINT_HOSTS = frozenset({"webapi.moomoo.com"})
_LOOPBACK_REDIRECT_HOSTS = frozenset({"127.0.0.1", "localhost"})


class MoomooMcpOAuthError(RuntimeError):
    """Raised when the MCP OAuth boundary is violated.

    Carries one bounded, safe reason code from the set documented in
    IRO-070 rather than a generic "expired or revoked" message.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class MoomooMcpAuthorizationServer:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str | None = None


@dataclass(frozen=True, slots=True)
class MoomooMcpOAuthTokenResponse:
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_in: int
    scope: str


@dataclass(frozen=True, slots=True)
class MoomooMcpOAuthRefreshedAccess:
    access_token: str = field(repr=False)
    expires_in: int
    scope: str
    refresh_token: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class MoomooMcpDynamicClientRegistration:
    client_id: str = field(repr=False)


class MoomooMcpOAuthTransport:
    def probe_resource(self, url: str) -> tuple[int, Mapping[str, str]]: ...

    def get_metadata(self, url: str) -> Mapping[str, object]: ...

    def post_form(self, url: str, *, form: Mapping[str, str]) -> Mapping[str, object]: ...

    def post_json(self, url: str, *, payload: Mapping[str, object]) -> Mapping[str, object]: ...


class UrllibMoomooMcpOAuthTransport:
    def __init__(
        self,
        *,
        opener: Callable[..., object] = urlopen,
        timeout_seconds: float = 15,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Moomoo MCP OAuth timeout must be positive")
        self._opener = opener
        self._timeout_seconds = timeout_seconds
        self._ssl_context = trusted_ssl_context()

    def probe_resource(self, url: str) -> tuple[int, Mapping[str, str]]:
        request = Request(url, headers={"Accept": "application/json"}, method="GET")
        try:
            with self._opener(
                request, timeout=self._timeout_seconds, context=self._ssl_context
            ) as response:
                response.read(MAX_METADATA_RESPONSE_BYTES + 1)
                return response.status, dict(response.headers)
        except HTTPError as error:
            return error.code, dict(error.headers or {})
        except (URLError, TimeoutError, OSError) as error:
            raise MoomooMcpOAuthError("authorization_metadata_unavailable") from error

    def get_metadata(self, url: str) -> Mapping[str, object]:
        request = Request(url, headers={"Accept": "application/json"}, method="GET")
        return self._send(
            request,
            max_bytes=MAX_METADATA_RESPONSE_BYTES,
            unavailable_code="authorization_metadata_unavailable",
            invalid_code="authorization_metadata_invalid",
        )

    def post_form(self, url: str, *, form: Mapping[str, str]) -> Mapping[str, object]:
        request = Request(
            url,
            data=urlencode(form).encode("ascii"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        return self._send(
            request,
            max_bytes=MAX_TOKEN_RESPONSE_BYTES,
            unavailable_code="token_transport_rejected",
            invalid_code="token_transport_invalid",
        )

    def post_json(self, url: str, *, payload: Mapping[str, object]) -> Mapping[str, object]:
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method="POST",
        )
        return self._send(
            request,
            max_bytes=MAX_METADATA_RESPONSE_BYTES,
            unavailable_code="client_registration_unavailable",
            invalid_code="client_registration_invalid",
        )

    def _send(
        self,
        request: Request,
        *,
        max_bytes: int,
        unavailable_code: str,
        invalid_code: str,
    ) -> Mapping[str, object]:
        try:
            with self._opener(
                request, timeout=self._timeout_seconds, context=self._ssl_context
            ) as response:
                raw = response.read(max_bytes + 1)
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            raise MoomooMcpOAuthError(unavailable_code) from error
        if len(raw) > max_bytes:
            raise MoomooMcpOAuthError(invalid_code)
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise MoomooMcpOAuthError(invalid_code) from error
        if not isinstance(payload, Mapping):
            raise MoomooMcpOAuthError(invalid_code)
        return payload


def _require_https_allowed_host(
    url: object,
    *,
    invalid_code: str,
    allowed_hosts: frozenset[str] = _RESOURCE_AND_ISSUER_HOSTS,
) -> str:
    if not isinstance(url, str) or not url:
        raise MoomooMcpOAuthError(invalid_code)
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise MoomooMcpOAuthError(invalid_code)
    if parsed.hostname.lower() not in allowed_hosts:
        raise MoomooMcpOAuthError(invalid_code)
    return url


def _parse_resource_metadata_url_from_challenge(header_value: str) -> str | None:
    """Extract `resource_metadata` from a `WWW-Authenticate` header value.

    Bounded: refuses to scan an oversized header (defense against a
    malicious/broken server sending an unbounded challenge string).
    """

    if len(header_value) > MAX_WWW_AUTHENTICATE_HEADER_LENGTH:
        raise MoomooMcpOAuthError("authorization_metadata_invalid")
    marker = "resource_metadata="
    lowered = header_value.lower()
    index = lowered.find(marker)
    if index == -1:
        return None
    start = index + len(marker)
    if start >= len(header_value):
        return None
    remainder = header_value[start:]
    if remainder.startswith('"'):
        end = remainder.find('"', 1)
        if end == -1:
            raise MoomooMcpOAuthError("authorization_metadata_invalid")
        return remainder[1:end]
    end = min(
        (index for index in (remainder.find(","), remainder.find(" ")) if index != -1),
        default=len(remainder),
    )
    return remainder[:end]


def discover_protected_resource_metadata_url(
    transport: MoomooMcpOAuthTransport,
    *,
    resource: str = MOOMOO_MCP_RESOURCE,
) -> str:
    """Resolve the protected-resource metadata URL per RFC 9728 Section 5.1.

    Makes one bounded, unauthenticated request to the exact MCP resource,
    reads any `WWW-Authenticate` challenge for a `resource_metadata`
    location, validates its host, and falls back to the standards-defined
    well-known suffix only when no challenge metadata is present.
    """

    _require_https_allowed_host(resource, invalid_code="authorization_metadata_invalid")
    status, headers = transport.probe_resource(resource)
    if status not in (401, 403):
        return PROTECTED_RESOURCE_METADATA_WELL_KNOWN_URL
    challenge = headers.get("WWW-Authenticate") or headers.get("Www-Authenticate")
    if not isinstance(challenge, str) or not challenge:
        return PROTECTED_RESOURCE_METADATA_WELL_KNOWN_URL
    metadata_url = _parse_resource_metadata_url_from_challenge(challenge)
    if metadata_url is None:
        return PROTECTED_RESOURCE_METADATA_WELL_KNOWN_URL
    return _require_https_allowed_host(
        metadata_url, invalid_code="authorization_metadata_invalid"
    )


def fetch_protected_resource_metadata(
    transport: MoomooMcpOAuthTransport,
    *,
    metadata_url: str | None = None,
    resource: str = MOOMOO_MCP_RESOURCE,
) -> tuple[str, ...]:
    """Return the resource's advertised authorization-server issuer URLs."""

    resolved_metadata_url = (
        metadata_url
        if metadata_url is not None
        else discover_protected_resource_metadata_url(transport, resource=resource)
    )
    _require_https_allowed_host(
        resolved_metadata_url, invalid_code="authorization_metadata_invalid"
    )
    try:
        payload = transport.get_metadata(resolved_metadata_url)
    except MoomooMcpOAuthError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise MoomooMcpOAuthError("authorization_metadata_unavailable") from error
    metadata_resource = payload.get("resource")
    authorization_servers = payload.get("authorization_servers")
    if metadata_resource != resource:
        raise MoomooMcpOAuthError("authorization_metadata_invalid")
    if (
        not isinstance(authorization_servers, list)
        or not authorization_servers
        or len(authorization_servers) > 8
    ):
        raise MoomooMcpOAuthError("authorization_metadata_invalid")
    issuers = tuple(
        _require_https_allowed_host(
            issuer, invalid_code="authorization_metadata_invalid"
        )
        for issuer in authorization_servers
    )
    return issuers


def _normalize_issuer(issuer: str) -> str:
    return issuer.rstrip("/")


def fetch_authorization_server_metadata(
    transport: MoomooMcpOAuthTransport,
    *,
    issuer: str,
) -> MoomooMcpAuthorizationServer:
    _require_https_allowed_host(issuer, invalid_code="authorization_metadata_invalid")
    metadata_url = _normalize_issuer(issuer) + "/.well-known/oauth-authorization-server"
    try:
        payload = transport.get_metadata(metadata_url)
    except MoomooMcpOAuthError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise MoomooMcpOAuthError("authorization_metadata_unavailable") from error
    returned_issuer = payload.get("issuer")
    if (
        not isinstance(returned_issuer, str)
        or _normalize_issuer(returned_issuer) != _normalize_issuer(issuer)
    ):
        raise MoomooMcpOAuthError("authorization_metadata_invalid")
    authorization_endpoint = _require_https_allowed_host(
        payload.get("authorization_endpoint"),
        invalid_code="authorization_metadata_invalid",
        allowed_hosts=_OAUTH_ENDPOINT_HOSTS,
    )
    token_endpoint = _require_https_allowed_host(
        payload.get("token_endpoint"),
        invalid_code="authorization_metadata_invalid",
        allowed_hosts=_OAUTH_ENDPOINT_HOSTS,
    )
    code_challenge_methods = payload.get("code_challenge_methods_supported")
    if code_challenge_methods is not None and (
        not isinstance(code_challenge_methods, list)
        or "S256" not in code_challenge_methods
    ):
        raise MoomooMcpOAuthError("authorization_metadata_invalid")
    registration_endpoint_raw = payload.get("registration_endpoint")
    registration_endpoint = (
        _require_https_allowed_host(
            registration_endpoint_raw,
            invalid_code="authorization_metadata_invalid",
            allowed_hosts=_OAUTH_ENDPOINT_HOSTS,
        )
        if registration_endpoint_raw is not None
        else None
    )
    return MoomooMcpAuthorizationServer(
        issuer=returned_issuer,
        authorization_endpoint=authorization_endpoint,
        token_endpoint=token_endpoint,
        registration_endpoint=registration_endpoint,
    )


def register_mcp_client(
    transport: MoomooMcpOAuthTransport,
    *,
    authorization_server: MoomooMcpAuthorizationServer,
    redirect_uri: str,
) -> MoomooMcpDynamicClientRegistration:
    """Dynamically register this desktop app as a public MCP OAuth client.

    Implements the relevant subset of RFC 7591 for a public, loopback-
    redirect, PKCE-only client. Only the returned `client_id` is meant to be
    persisted by the caller; a `client_secret` in the response (unexpected
    for a public client) is deliberately never read or returned.
    """

    if authorization_server.registration_endpoint is None:
        raise MoomooMcpOAuthError("client_registration_unavailable")
    parsed_redirect = urlsplit(redirect_uri)
    if (
        parsed_redirect.scheme != "http"
        or parsed_redirect.hostname not in _LOOPBACK_REDIRECT_HOSTS
    ):
        raise MoomooMcpOAuthError("authorization_metadata_invalid")
    payload = transport.post_json(
        authorization_server.registration_endpoint,
        payload={
            "client_name": "Investment Research OS",
            "redirect_uris": [redirect_uri],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        },
    )
    client_id = payload.get("client_id")
    if not isinstance(client_id, str) or not client_id.strip():
        raise MoomooMcpOAuthError("client_registration_invalid")
    if "client_secret" in payload or "client_secret_expires_at" in payload:
        raise MoomooMcpOAuthError("client_registration_invalid")
    auth_method = payload.get("token_endpoint_auth_method")
    if auth_method is not None and auth_method != "none":
        raise MoomooMcpOAuthError("client_registration_invalid")
    return MoomooMcpDynamicClientRegistration(client_id=client_id.strip())


def build_mcp_authorization_url(
    *,
    authorization_endpoint: str,
    client_id: str,
    redirect_uri: str,
    attempt: PkceAuthorizationAttempt,
    resource: str = MOOMOO_MCP_RESOURCE,
) -> str:
    if not isinstance(client_id, str) or not client_id.strip():
        raise MoomooMcpOAuthError("authorization_metadata_invalid")
    parsed_redirect = urlsplit(redirect_uri)
    if (
        parsed_redirect.scheme != "http"
        or parsed_redirect.hostname not in _LOOPBACK_REDIRECT_HOSTS
        or parsed_redirect.port is None
        or parsed_redirect.path != "/callback"
        or parsed_redirect.query
        or parsed_redirect.fragment
    ):
        raise MoomooMcpOAuthError("authorization_metadata_invalid")
    _require_https_allowed_host(
        authorization_endpoint,
        invalid_code="authorization_metadata_invalid",
        allowed_hosts=_OAUTH_ENDPOINT_HOSTS,
    )
    query = urlencode(
        {
            "client_id": client_id,
            "code_challenge": attempt.code_challenge,
            "code_challenge_method": attempt.code_challenge_method,
            "redirect_uri": redirect_uri,
            "resource": resource,
            "response_type": "code",
            "state": attempt.state,
        }
    )
    return f"{authorization_endpoint}?{query}"


def _validate_token_response(payload: Mapping[str, object], *, invalid_code: str) -> None:
    scope = payload.get("scope", "")
    if not isinstance(scope, str) or len(scope) > MAX_SCOPE_LENGTH:
        raise MoomooMcpOAuthError(invalid_code)


def exchange_mcp_authorization_code(
    *,
    token_endpoint: str,
    client_id: str,
    redirect_uri: str,
    resource: str = MOOMOO_MCP_RESOURCE,
    authorization_code: str,
    callback_state: str,
    attempt: PkceAuthorizationAttempt,
    transport: MoomooMcpOAuthTransport,
) -> MoomooMcpOAuthTokenResponse:
    if not authorization_code:
        raise MoomooMcpOAuthError("callback_state_invalid")
    _require_https_allowed_host(
        token_endpoint,
        invalid_code="authorization_metadata_invalid",
        allowed_hosts=_OAUTH_ENDPOINT_HOSTS,
    )
    try:
        verifier = attempt.consume_verifier(callback_state)
    except MoomooOAuthError as error:
        raise MoomooMcpOAuthError("callback_state_invalid") from error
    try:
        payload = transport.post_form(
            token_endpoint,
            form={
                "grant_type": "authorization_code",
                "code": authorization_code,
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "code_verifier": verifier,
                "resource": resource,
            },
        )
    except MoomooMcpOAuthError as error:
        if error.code == "token_transport_invalid":
            raise MoomooMcpOAuthError("authorization_response_invalid") from error
        raise MoomooMcpOAuthError("authorization_exchange_rejected") from error
    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    token_type = payload.get("token_type")
    expires_in = payload.get("expires_in")
    if (
        not isinstance(access_token, str)
        or not access_token
        or not isinstance(refresh_token, str)
        or not refresh_token
        or token_type != "Bearer"
        or isinstance(expires_in, bool)
        or not isinstance(expires_in, int)
        or expires_in <= 0
    ):
        raise MoomooMcpOAuthError("authorization_response_invalid")
    _validate_token_response(payload, invalid_code="authorization_response_invalid")
    return MoomooMcpOAuthTokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
        scope=str(payload.get("scope", "")),
    )


def refresh_mcp_access_token(
    *,
    token_endpoint: str,
    client_id: str,
    resource: str = MOOMOO_MCP_RESOURCE,
    refresh_token: str,
    transport: MoomooMcpOAuthTransport,
) -> MoomooMcpOAuthRefreshedAccess:
    if not refresh_token or "\n" in refresh_token or "\r" in refresh_token:
        raise MoomooMcpOAuthError("credential_missing")
    _require_https_allowed_host(
        token_endpoint,
        invalid_code="authorization_metadata_invalid",
        allowed_hosts=_OAUTH_ENDPOINT_HOSTS,
    )
    try:
        payload = transport.post_form(
            token_endpoint,
            form={
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "resource": resource,
            },
        )
    except MoomooMcpOAuthError as error:
        if error.code == "token_transport_invalid":
            raise MoomooMcpOAuthError("refresh_response_invalid") from error
        raise MoomooMcpOAuthError("refresh_rejected") from error
    access_token = payload.get("access_token")
    token_type = payload.get("token_type")
    expires_in = payload.get("expires_in")
    rotated_refresh_token = payload.get("refresh_token")
    if (
        not isinstance(access_token, str)
        or not access_token
        or token_type != "Bearer"
        or isinstance(expires_in, bool)
        or not isinstance(expires_in, int)
        or expires_in <= 0
        or (
            rotated_refresh_token is not None
            and (
                not isinstance(rotated_refresh_token, str)
                or not rotated_refresh_token
                or "\n" in rotated_refresh_token
                or "\r" in rotated_refresh_token
            )
        )
    ):
        raise MoomooMcpOAuthError("refresh_response_invalid")
    _validate_token_response(payload, invalid_code="refresh_response_invalid")
    return MoomooMcpOAuthRefreshedAccess(
        access_token=access_token,
        expires_in=expires_in,
        scope=str(payload.get("scope", "")),
        refresh_token=rotated_refresh_token,
    )


__all__ = [
    "MOOMOO_MCP_RESOURCE",
    "PROTECTED_RESOURCE_METADATA_URL",
    "PROTECTED_RESOURCE_METADATA_WELL_KNOWN_URL",
    "MAX_METADATA_RESPONSE_BYTES",
    "MAX_TOKEN_RESPONSE_BYTES",
    "MoomooMcpAuthorizationServer",
    "MoomooMcpDynamicClientRegistration",
    "MoomooMcpOAuthError",
    "MoomooMcpOAuthRefreshedAccess",
    "MoomooMcpOAuthTokenResponse",
    "MoomooMcpOAuthTransport",
    "UrllibMoomooMcpOAuthTransport",
    "build_mcp_authorization_url",
    "create_pkce_attempt",
    "discover_protected_resource_metadata_url",
    "exchange_mcp_authorization_code",
    "fetch_authorization_server_metadata",
    "fetch_protected_resource_metadata",
    "refresh_mcp_access_token",
    "register_mcp_client",
]

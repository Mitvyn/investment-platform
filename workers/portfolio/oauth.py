from __future__ import annotations

import base64
import hmac
import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass, field
from typing import Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


AUTHORIZATION_ENDPOINT = "https://webapi.moomoo.com/oauth2/authorize/confirm"
TOKEN_ENDPOINT = "https://webapi.moomoo.com/oauth2/token"
MAX_TOKEN_RESPONSE_BYTES = 1_048_576

class MoomooOAuthError(RuntimeError):
    """Raised when a Moomoo authorization attempt violates its contract."""


@dataclass(slots=True)
class PkceAuthorizationAttempt:
    code_challenge: str
    state: str
    _code_verifier: str = field(repr=False)
    code_challenge_method: str = "S256"
    _consumed: bool = field(default=False, init=False, repr=False)

    def consume_verifier(self, callback_state: str) -> str:
        if self._consumed:
            raise MoomooOAuthError("Moomoo OAuth attempt already consumed")
        self._consumed = True
        verifier = self._code_verifier
        self._code_verifier = ""
        if not hmac.compare_digest(self.state, callback_state):
            raise MoomooOAuthError("Moomoo OAuth state mismatch")
        return verifier


@dataclass(frozen=True, slots=True)
class MoomooGrantedScopes:
    read_scopes: tuple[str, ...]
    account_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MoomooOAuthTokenResponse:
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_in: int
    read_scopes: tuple[str, ...]
    account_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MoomooOAuthRefreshedAccess:
    access_token: str = field(repr=False)
    expires_in: int
    read_scopes: tuple[str, ...]
    account_ids: tuple[str, ...]
    refresh_token: str | None = field(default=None, repr=False)


class MoomooOAuthTransport(Protocol):
    def post_form(
        self,
        url: str,
        *,
        form: Mapping[str, str],
    ) -> Mapping[str, object]: ...


class UrllibMoomooOAuthTransport:
    def __init__(
        self,
        *,
        opener: Callable[..., object] = urlopen,
        timeout_seconds: float = 15,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Moomoo OAuth timeout must be positive")
        self._opener = opener
        self._timeout_seconds = timeout_seconds

    def post_form(
        self,
        url: str,
        *,
        form: Mapping[str, str],
    ) -> Mapping[str, object]:
        if url != TOKEN_ENDPOINT:
            raise MoomooOAuthError("Moomoo OAuth token endpoint is invalid")
        request = Request(
            url,
            data=urlencode(form).encode("ascii"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            with self._opener(request, timeout=self._timeout_seconds) as response:
                raw = response.read(MAX_TOKEN_RESPONSE_BYTES + 1)
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            raise MoomooOAuthError("Moomoo OAuth token exchange failed") from error
        if len(raw) > MAX_TOKEN_RESPONSE_BYTES:
            raise MoomooOAuthError("Moomoo OAuth token response is too large")
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise MoomooOAuthError("Moomoo OAuth token response is invalid") from error
        if not isinstance(payload, Mapping):
            raise MoomooOAuthError("Moomoo OAuth token response is invalid")
        return payload


def create_pkce_attempt(
    *,
    token_factory: Callable[[int], str] = secrets.token_urlsafe,
) -> PkceAuthorizationAttempt:
    verifier = token_factory(64)
    state = token_factory(32)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    return PkceAuthorizationAttempt(
        code_challenge=challenge,
        state=state,
        _code_verifier=verifier,
    )


def validate_granted_scopes(
    granted_scope: str,
    *,
    required_read_scopes: tuple[str, ...],
) -> MoomooGrantedScopes:
    granted = set(granted_scope.split())
    required = set(required_read_scopes)
    account_scopes = {
        scope
        for scope in granted
        if scope.startswith("accid:") and scope != "accid:*"
    }
    account_ids = tuple(
        sorted(scope.removeprefix("accid:") for scope in account_scopes)
    )
    if any(not account_id for account_id in account_ids):
        raise MoomooOAuthError(
            "Moomoo OAuth granted scope mismatch:concrete_account_scope_missing"
        )
    return MoomooGrantedScopes(
        read_scopes=tuple(sorted(granted & required)),
        account_ids=account_ids,
    )


def build_authorization_url(
    *,
    client_id: str,
    redirect_uri: str,
    attempt: PkceAuthorizationAttempt,
) -> str:
    try:
        uuid.UUID(client_id)
    except ValueError as error:
        raise MoomooOAuthError("Moomoo OAuth client ID is invalid") from error
    parsed_redirect = urlsplit(redirect_uri)
    if (
        parsed_redirect.scheme != "http"
        or parsed_redirect.hostname != "127.0.0.1"
        or parsed_redirect.port is None
        or parsed_redirect.path != "/callback"
        or parsed_redirect.query
        or parsed_redirect.fragment
    ):
        raise MoomooOAuthError("Moomoo OAuth requires an exact loopback redirect")
    return f"{AUTHORIZATION_ENDPOINT}?{
        urlencode(
            {
                'client_id': client_id,
                'code_challenge': attempt.code_challenge,
                'code_challenge_method': attempt.code_challenge_method,
                'redirect_uri': redirect_uri,
                'response_type': 'code',
                'state': attempt.state,
            }
        )
    }"


def exchange_authorization_code(
    *,
    client_id: str,
    redirect_uri: str,
    authorization_code: str,
    callback_state: str,
    attempt: PkceAuthorizationAttempt,
    required_read_scopes: tuple[str, ...],
    transport: MoomooOAuthTransport,
) -> MoomooOAuthTokenResponse:
    if not authorization_code:
        raise MoomooOAuthError("Moomoo authorization code is missing")
    verifier = attempt.consume_verifier(callback_state)
    payload = transport.post_form(
        TOKEN_ENDPOINT,
        form={
            "grant_type": "authorization_code",
            "code": authorization_code,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        },
    )
    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    token_type = payload.get("token_type")
    expires_in = payload.get("expires_in")
    scope = payload.get("scope")
    if (
        not isinstance(access_token, str)
        or not access_token
        or not isinstance(refresh_token, str)
        or not refresh_token
        or token_type != "Bearer"
        or isinstance(expires_in, bool)
        or not isinstance(expires_in, int)
        or expires_in <= 0
        or not isinstance(scope, str)
    ):
        raise MoomooOAuthError("Moomoo OAuth token response is invalid")
    grant = validate_granted_scopes(
        scope,
        required_read_scopes=required_read_scopes,
    )
    return MoomooOAuthTokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
        read_scopes=grant.read_scopes,
        account_ids=grant.account_ids,
    )


def refresh_access_token(
    *,
    client_id: str,
    refresh_token: str,
    required_read_scopes: tuple[str, ...],
    transport: MoomooOAuthTransport,
) -> MoomooOAuthRefreshedAccess:
    try:
        uuid.UUID(client_id)
    except ValueError as error:
        raise MoomooOAuthError("Moomoo OAuth client ID is invalid") from error
    if not refresh_token or "\n" in refresh_token or "\r" in refresh_token:
        raise MoomooOAuthError("Moomoo OAuth refresh token is invalid")
    payload = transport.post_form(
        TOKEN_ENDPOINT,
        form={
            "client_id": client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
    )
    access_token = payload.get("access_token")
    token_type = payload.get("token_type")
    expires_in = payload.get("expires_in")
    scope = payload.get("scope")
    rotated_refresh_token = payload.get("refresh_token")
    if (
        not isinstance(access_token, str)
        or not access_token
        or token_type != "Bearer"
        or isinstance(expires_in, bool)
        or not isinstance(expires_in, int)
        or expires_in <= 0
        or not isinstance(scope, str)
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
        raise MoomooOAuthError("Moomoo OAuth token response is invalid")
    grant = validate_granted_scopes(
        scope,
        required_read_scopes=required_read_scopes,
    )
    return MoomooOAuthRefreshedAccess(
        access_token=access_token,
        expires_in=expires_in,
        read_scopes=grant.read_scopes,
        account_ids=grant.account_ids,
        refresh_token=rotated_refresh_token,
    )

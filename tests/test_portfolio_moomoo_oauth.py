from __future__ import annotations

import base64
import hashlib
import json
import unittest
from typing import Mapping
from urllib.parse import parse_qs, urlsplit

from workers.portfolio.oauth import (
    MoomooOAuthTokenResponse,
    MoomooOAuthError,
    build_authorization_url,
    create_pkce_attempt,
    exchange_authorization_code,
    refresh_access_token,
    UrllibMoomooOAuthTransport,
    validate_granted_scopes,
)


class FakeOAuthTransport:
    def __init__(self, response: Mapping[str, object]) -> None:
        self.response = response
        self.calls: list[tuple[str, Mapping[str, str]]] = []

    def post_form(self, url: str, *, form: Mapping[str, str]) -> Mapping[str, object]:
        self.calls.append((url, form))
        return self.response


class MoomooOAuthTests(unittest.TestCase):
    def test_refreshes_access_token_without_rotating_keychain_secret(self) -> None:
        transport = FakeOAuthTransport(
            {
                "access_token": "replacement-access-secret",
                "token_type": "Bearer",
                "expires_in": 7200,
                "scope": "quote:read trade:read accid:2638",
            }
        )

        refreshed = refresh_access_token(
            client_id="4a8bcd69-e915-4778-9583-17ad0e9e6a80",
            refresh_token="keychain-refresh-secret",
            required_read_scopes=("quote:read", "trade:read"),
            transport=transport,
        )

        self.assertEqual(refreshed.access_token, "replacement-access-secret")
        self.assertEqual(refreshed.account_ids, ("2638",))
        self.assertNotIn("replacement-access-secret", repr(refreshed))
        _, form = transport.calls[0]
        self.assertEqual(
            form,
            {
                "client_id": "4a8bcd69-e915-4778-9583-17ad0e9e6a80",
                "grant_type": "refresh_token",
                "refresh_token": "keychain-refresh-secret",
            },
        )

    def test_refresh_accepts_optional_rotated_refresh_token(self) -> None:
        transport = FakeOAuthTransport(
            {
                "access_token": "replacement-access-secret",
                "refresh_token": "rotated-refresh-secret",
                "token_type": "Bearer",
                "expires_in": 7200,
                "scope": "quote:read trade:read accid:2638",
            }
        )

        refreshed = refresh_access_token(
            client_id="4a8bcd69-e915-4778-9583-17ad0e9e6a80",
            refresh_token="keychain-refresh-secret",
            required_read_scopes=("quote:read", "trade:read"),
            transport=transport,
        )

        self.assertEqual(refreshed.refresh_token, "rotated-refresh-secret")
        self.assertNotIn("rotated-refresh-secret", repr(refreshed))

    def test_url_transport_posts_bounded_form_without_secret_logging(self) -> None:
        calls: list[object] = []

        class Response:
            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self, limit: int) -> bytes:
                self.limit = limit
                return json.dumps({"token_type": "Bearer"}).encode()

        response = Response()

        def opener(request: object, *, timeout: float) -> Response:
            calls.extend((request, timeout))
            return response

        transport = UrllibMoomooOAuthTransport(opener=opener, timeout_seconds=7)

        payload = transport.post_form(
            "https://webapi.moomoo.com/oauth2/token",
            form={"code": "secret-code", "grant_type": "authorization_code"},
        )

        request = calls[0]
        self.assertEqual(payload, {"token_type": "Bearer"})
        self.assertEqual(calls[1], 7)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(
            request.headers["Content-type"],
            "application/x-www-form-urlencoded",
        )
        self.assertIn(b"code=secret-code", request.data)
        self.assertEqual(response.limit, 1_048_577)

    def test_creates_s256_pkce_attempt_from_independent_entropy(self) -> None:
        calls: list[int] = []

        def token_factory(byte_count: int) -> str:
            calls.append(byte_count)
            return "verifier-value" if byte_count == 64 else "state-value"

        attempt = create_pkce_attempt(token_factory=token_factory)

        expected = (
            base64.urlsafe_b64encode(hashlib.sha256(b"verifier-value").digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        self.assertEqual(attempt.code_challenge_method, "S256")
        self.assertEqual(attempt.code_challenge, expected)
        self.assertEqual(attempt.state, "state-value")
        self.assertEqual(calls, [64, 32])

    def test_state_is_single_use_and_mismatch_discards_verifier(self) -> None:
        attempt = create_pkce_attempt(
            token_factory=lambda byte_count: (
                "verifier-secret" if byte_count == 64 else "expected-state"
            )
        )

        with self.assertRaisesRegex(MoomooOAuthError, "state mismatch"):
            attempt.consume_verifier("wrong-state")
        with self.assertRaisesRegex(MoomooOAuthError, "already consumed"):
            attempt.consume_verifier("expected-state")

        successful = create_pkce_attempt(
            token_factory=lambda byte_count: (
                "second-verifier" if byte_count == 64 else "second-state"
            )
        )
        self.assertEqual(successful.consume_verifier("second-state"), "second-verifier")
        with self.assertRaisesRegex(MoomooOAuthError, "already consumed"):
            successful.consume_verifier("second-state")

    def test_granted_scopes_preserve_partial_read_capabilities(self) -> None:
        grant = validate_granted_scopes(
            "trade:read accid:2638 quote:read",
            required_read_scopes=("quote:read", "trade:read"),
        )

        self.assertEqual(grant.read_scopes, ("quote:read", "trade:read"))
        self.assertEqual(grant.account_ids, ("2638",))

        market_only = validate_granted_scopes(
            "quote:read",
            required_read_scopes=("quote:read", "trade:read"),
        )
        self.assertEqual(market_only.read_scopes, ("quote:read",))
        self.assertEqual(market_only.account_ids, ())

        holdings_only = validate_granted_scopes(
            "trade:read accid:2638",
            required_read_scopes=("quote:read", "trade:read"),
        )
        self.assertEqual(holdings_only.read_scopes, ("trade:read",))
        self.assertEqual(holdings_only.account_ids, ("2638",))

    def test_granted_scope_failures_identify_safe_remediation(self) -> None:
        cases = (
            (
                "quote:read trade:read trade:write accid:2638",
                "write_scope_not_permitted",
            ),
            (
                "quote:read trade:read unknown:read accid:2638",
                "unknown_scope_not_permitted",
            ),
        )

        for granted, reason_code in cases:
            with self.subTest(granted=granted):
                with self.assertRaisesRegex(MoomooOAuthError, reason_code):
                    validate_granted_scopes(
                        granted,
                        required_read_scopes=("quote:read", "trade:read"),
                    )

    def test_accepts_echoed_account_selector_without_treating_it_as_account_grant(
        self,
    ) -> None:
        grant = validate_granted_scopes(
            "quote:read trade:read accid:*",
            required_read_scopes=("quote:read", "trade:read"),
        )

        self.assertEqual(grant.read_scopes, ("quote:read", "trade:read"))
        self.assertEqual(grant.account_ids, ())

    def test_builds_exact_loopback_authorization_url(self) -> None:
        attempt = create_pkce_attempt(
            token_factory=lambda byte_count: (
                "verifier-value" if byte_count == 64 else "state-value"
            )
        )

        url = build_authorization_url(
            client_id="4a8bcd69-e915-4778-9583-17ad0e9e6a80",
            redirect_uri="http://127.0.0.1:60355/callback",
            attempt=attempt,
        )

        self.assertTrue(
            url.startswith("https://webapi.moomoo.com/oauth2/authorize/confirm?")
        )
        self.assertIn("client_id=4a8bcd69-e915-4778-9583-17ad0e9e6a80", url)
        self.assertIn("code_challenge_method=S256", url)
        self.assertIn(
            "redirect_uri=http%3A%2F%2F127.0.0.1%3A60355%2Fcallback",
            url,
        )
        self.assertIn("response_type=code", url)
        self.assertIn("state=state-value", url)
        query = parse_qs(urlsplit(url).query, strict_parsing=True)
        self.assertEqual(
            query["scope"], ["quote:read trade:read accid:*"]
        )
        self.assertNotIn("quote:write", query["scope"][0])
        self.assertNotIn("trade:write", query["scope"][0])

        with self.assertRaisesRegex(MoomooOAuthError, "loopback redirect"):
            build_authorization_url(
                client_id="4a8bcd69-e915-4778-9583-17ad0e9e6a80",
                redirect_uri="http://localhost:60355/callback",
                attempt=attempt,
            )

    def test_exchanges_single_use_code_and_validates_account_bound_scope(self) -> None:
        attempt = create_pkce_attempt(
            token_factory=lambda byte_count: (
                "verifier-secret" if byte_count == 64 else "expected-state"
            )
        )
        transport = FakeOAuthTransport(
            {
                "access_token": "access-secret",
                "token_type": "Bearer",
                "expires_in": 7200,
                "refresh_token": "refresh-secret",
                "scope": "quote:read trade:read accid:2638",
            }
        )

        tokens = exchange_authorization_code(
            client_id="4a8bcd69-e915-4778-9583-17ad0e9e6a80",
            redirect_uri="http://127.0.0.1:60355/callback",
            authorization_code="single-use-code",
            callback_state="expected-state",
            attempt=attempt,
            required_read_scopes=("quote:read", "trade:read"),
            transport=transport,
        )

        self.assertIsInstance(tokens, MoomooOAuthTokenResponse)
        self.assertEqual(tokens.access_token, "access-secret")
        self.assertEqual(tokens.refresh_token, "refresh-secret")
        self.assertEqual(tokens.account_ids, ("2638",))
        self.assertNotIn("access-secret", repr(tokens))
        self.assertNotIn("refresh-secret", repr(tokens))
        url, form = transport.calls[0]
        self.assertEqual(url, "https://webapi.moomoo.com/oauth2/token")
        self.assertEqual(form["code_verifier"], "verifier-secret")
        self.assertEqual(form["grant_type"], "authorization_code")

        with self.assertRaisesRegex(MoomooOAuthError, "already consumed"):
            exchange_authorization_code(
                client_id="4a8bcd69-e915-4778-9583-17ad0e9e6a80",
                redirect_uri="http://127.0.0.1:60355/callback",
                authorization_code="replayed-code",
                callback_state="expected-state",
                attempt=attempt,
                required_read_scopes=("quote:read", "trade:read"),
                transport=transport,
            )


if __name__ == "__main__":
    unittest.main()

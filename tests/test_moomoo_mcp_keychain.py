from __future__ import annotations

import unittest

from workers.moomoo_mcp.keychain import (
    MCP_KEYCHAIN_SERVICE,
    MoomooMcpCredentialError,
    MoomooMcpTokenKeychain,
)

OPERATOR_ID = "11111111-1111-4111-8111-111111111111"
CLIENT_A = "client-a"
CLIENT_B = "client-b"


class FakeBackend:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], str] = {}

    def store(self, *, service: str, account: str, secret: str) -> None:
        self.items[(service, account)] = secret

    def read(self, *, service: str, account: str) -> str | None:
        return self.items.get((service, account))

    def delete(self, *, service: str, account: str) -> None:
        self.items.pop((service, account), None)


class MoomooMcpTokenKeychainTests(unittest.TestCase):
    def test_round_trips_a_resource_bound_token(self) -> None:
        backend = FakeBackend()
        keychain = MoomooMcpTokenKeychain(
            operator_id=OPERATOR_ID, client_id=CLIENT_A, backend=backend
        )
        keychain.store_refresh_token("refresh-secret")
        self.assertEqual(keychain.read_refresh_token(), "refresh-secret")

    def test_token_issued_for_one_client_cannot_be_read_by_another(self) -> None:
        backend = FakeBackend()
        MoomooMcpTokenKeychain(
            operator_id=OPERATOR_ID, client_id=CLIENT_A, backend=backend
        ).store_refresh_token("client-a-refresh")

        other_client_keychain = MoomooMcpTokenKeychain(
            operator_id=OPERATOR_ID, client_id=CLIENT_B, backend=backend
        )
        with self.assertRaises(MoomooMcpCredentialError) as context:
            other_client_keychain.read_refresh_token()
        self.assertEqual(context.exception.code, "credential_missing")

    def test_missing_entry_is_credential_missing(self) -> None:
        backend = FakeBackend()
        keychain = MoomooMcpTokenKeychain(
            operator_id=OPERATOR_ID, client_id=CLIENT_A, backend=backend
        )
        with self.assertRaises(MoomooMcpCredentialError) as context:
            keychain.read_refresh_token()
        self.assertEqual(context.exception.code, "credential_missing")

    def test_legacy_unbound_entry_requires_reconnect_not_silent_use(self) -> None:
        backend = FakeBackend()
        backend.store(
            service=MCP_KEYCHAIN_SERVICE,
            account=f"{OPERATOR_ID}:refresh_token",
            secret="legacy-refresh-secret",
        )
        keychain = MoomooMcpTokenKeychain(
            operator_id=OPERATOR_ID, client_id=CLIENT_A, backend=backend
        )
        with self.assertRaises(MoomooMcpCredentialError) as context:
            keychain.read_refresh_token()
        self.assertEqual(context.exception.code, "credential_binding_mismatch")

    def test_legacy_entry_is_never_deleted_or_overwritten(self) -> None:
        backend = FakeBackend()
        backend.store(
            service=MCP_KEYCHAIN_SERVICE,
            account=f"{OPERATOR_ID}:refresh_token",
            secret="legacy-refresh-secret",
        )
        keychain = MoomooMcpTokenKeychain(
            operator_id=OPERATOR_ID, client_id=CLIENT_A, backend=backend
        )
        with self.assertRaises(MoomooMcpCredentialError):
            keychain.read_refresh_token()
        keychain.store_refresh_token("fresh-consent-refresh")
        self.assertEqual(
            backend.read(
                service=MCP_KEYCHAIN_SERVICE, account=f"{OPERATOR_ID}:refresh_token"
            ),
            "legacy-refresh-secret",
        )
        self.assertEqual(keychain.read_refresh_token(), "fresh-consent-refresh")

    def test_delete_never_touches_legacy_entry(self) -> None:
        backend = FakeBackend()
        backend.store(
            service=MCP_KEYCHAIN_SERVICE,
            account=f"{OPERATOR_ID}:refresh_token",
            secret="legacy-refresh-secret",
        )
        keychain = MoomooMcpTokenKeychain(
            operator_id=OPERATOR_ID, client_id=CLIENT_A, backend=backend
        )
        keychain.store_refresh_token("fresh-consent-refresh")
        keychain.delete_refresh_token()
        self.assertEqual(
            backend.read(
                service=MCP_KEYCHAIN_SERVICE, account=f"{OPERATOR_ID}:refresh_token"
            ),
            "legacy-refresh-secret",
        )

    def test_clear_all_local_tokens_removes_bound_and_legacy_entries(self) -> None:
        backend = FakeBackend()
        backend.store(
            service=MCP_KEYCHAIN_SERVICE,
            account=f"{OPERATOR_ID}:refresh_token",
            secret="legacy-refresh-secret",
        )
        keychain = MoomooMcpTokenKeychain(
            operator_id=OPERATOR_ID, client_id=CLIENT_A, backend=backend
        )
        keychain.store_refresh_token("bound-refresh-secret")

        keychain.clear_all_local_tokens()

        self.assertEqual(backend.items, {})


if __name__ == "__main__":
    unittest.main()

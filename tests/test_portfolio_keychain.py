from __future__ import annotations

import unittest

from workers.portfolio.keychain import MoomooKeychainError, MoomooTokenKeychain


class FakeBackend:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], str] = {}

    def store(self, *, service: str, account: str, secret: str) -> None:
        self.items[(service, account)] = secret

    def read(self, *, service: str, account: str) -> str | None:
        return self.items.get((service, account))

    def delete(self, *, service: str, account: str) -> None:
        self.items.pop((service, account), None)


class FalseyBackend(FakeBackend):
    def __bool__(self) -> bool:
        return False


class MoomooTokenKeychainTests(unittest.TestCase):
    def test_round_trips_refresh_token_through_native_backend_contract(self) -> None:
        backend = FakeBackend()
        keychain = MoomooTokenKeychain(
            operator_id="11111111-1111-4111-8111-111111111111",
            backend=backend,
        )

        keychain.store_refresh_token("refresh-token-secret")

        self.assertEqual(keychain.read_refresh_token(), "refresh-token-secret")
        self.assertEqual(
            backend.items[
                (
                    "dev.slated.iros.moomoo",
                    "11111111-1111-4111-8111-111111111111:refresh_token",
                )
            ],
            "refresh-token-secret",
        )

    def test_rotation_replaces_existing_value(self) -> None:
        backend = FakeBackend()
        keychain = MoomooTokenKeychain(
            operator_id="11111111-1111-4111-8111-111111111111",
            backend=backend,
        )
        keychain.store_refresh_token("first-secret")

        keychain.store_refresh_token("replacement-secret")

        self.assertEqual(keychain.read_refresh_token(), "replacement-secret")

    def test_deletes_refresh_token_idempotently(self) -> None:
        backend = FakeBackend()
        keychain = MoomooTokenKeychain(
            operator_id="11111111-1111-4111-8111-111111111111",
            backend=backend,
        )
        keychain.store_refresh_token("refresh-token-secret")

        keychain.delete_refresh_token()
        keychain.delete_refresh_token()

        with self.assertRaisesRegex(MoomooKeychainError, "unavailable"):
            keychain.read_refresh_token()

    def test_rejects_empty_or_multiline_secret(self) -> None:
        keychain = MoomooTokenKeychain(
            operator_id="11111111-1111-4111-8111-111111111111",
            backend=FakeBackend(),
        )

        for secret in ("", "line-one\nline-two", "line-one\rline-two"):
            with self.subTest(secret=secret):
                with self.assertRaisesRegex(ValueError, "invalid"):
                    keychain.store_refresh_token(secret)

    def test_respects_falsey_injected_backend(self) -> None:
        backend = FalseyBackend()

        keychain = MoomooTokenKeychain(
            operator_id="11111111-1111-4111-8111-111111111111",
            backend=backend,
        )
        keychain.store_refresh_token("refresh-token-secret")

        self.assertEqual(keychain.read_refresh_token(), "refresh-token-secret")

    def test_canonicalizes_equivalent_operator_uuid_spellings(self) -> None:
        backend = FakeBackend()
        keychain = MoomooTokenKeychain(
            operator_id="{11111111-1111-4111-8111-111111111111}",
            backend=backend,
        )

        keychain.store_refresh_token("refresh-token-secret")

        self.assertIn(
            (
                "dev.slated.iros.moomoo",
                "11111111-1111-4111-8111-111111111111:refresh_token",
            ),
            backend.items,
        )


if __name__ == "__main__":
    unittest.main()

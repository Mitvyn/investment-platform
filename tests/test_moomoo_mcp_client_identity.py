from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from workers.moomoo_mcp.client_identity import (
    MoomooMcpClientIdentity,
    MoomooMcpClientIdentityStore,
)

RESOURCE = "https://mcp.moomoo.com/mcp"
REDIRECT_URI = "http://127.0.0.1:60355/callback"


class MoomooMcpClientIdentityStoreTests(unittest.TestCase):
    def test_missing_file_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = MoomooMcpClientIdentityStore(Path(directory) / "identity.json")
            self.assertIsNone(store.load(resource=RESOURCE, redirect_uri=REDIRECT_URI))
            self.assertIsNone(store.load_any(resource=RESOURCE))

    def test_saved_identity_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sub" / "identity.json"
            store = MoomooMcpClientIdentityStore(path)
            store.save(
                MoomooMcpClientIdentity(
                    client_id="registered-client", resource=RESOURCE, redirect_uri=REDIRECT_URI
                )
            )
            self.assertEqual(
                store.load(resource=RESOURCE, redirect_uri=REDIRECT_URI),
                "registered-client",
            )
            self.assertEqual(store.load_any(resource=RESOURCE), "registered-client")

    def test_mismatched_redirect_uri_is_rejected_by_load_but_not_load_any(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity.json"
            store = MoomooMcpClientIdentityStore(path)
            store.save(
                MoomooMcpClientIdentity(
                    client_id="registered-client", resource=RESOURCE, redirect_uri=REDIRECT_URI
                )
            )
            self.assertIsNone(
                store.load(resource=RESOURCE, redirect_uri="http://127.0.0.1:9999/callback")
            )
            self.assertEqual(store.load_any(resource=RESOURCE), "registered-client")

    def test_mismatched_resource_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity.json"
            store = MoomooMcpClientIdentityStore(path)
            store.save(
                MoomooMcpClientIdentity(
                    client_id="registered-client", resource=RESOURCE, redirect_uri=REDIRECT_URI
                )
            )
            self.assertIsNone(
                store.load(resource="https://mcp.moomoo.com/other", redirect_uri=REDIRECT_URI)
            )
            self.assertIsNone(store.load_any(resource="https://mcp.moomoo.com/other"))

    def test_oversized_file_is_rejected_not_trusted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity.json"
            path.write_text("x" * 5000)
            store = MoomooMcpClientIdentityStore(path)
            self.assertIsNone(store.load(resource=RESOURCE, redirect_uri=REDIRECT_URI))

    def test_malformed_json_is_rejected_not_trusted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity.json"
            path.write_text("{not json")
            store = MoomooMcpClientIdentityStore(path)
            self.assertIsNone(store.load(resource=RESOURCE, redirect_uri=REDIRECT_URI))

    def test_saved_payload_never_carries_a_secret_field(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity.json"
            store = MoomooMcpClientIdentityStore(path)
            store.save(
                MoomooMcpClientIdentity(
                    client_id="registered-client", resource=RESOURCE, redirect_uri=REDIRECT_URI
                )
            )
            self.assertNotIn("secret", path.read_text().lower())


if __name__ == "__main__":
    unittest.main()

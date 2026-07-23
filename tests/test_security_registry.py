from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from typing import Any, Mapping

from workers.sec.collector import BytesResponse, SecSettings
from workers.sec.storage import JsonResponse, SupabaseStorageSettings
from workers.security_registry.client import (
    SecurityRegistryClient,
    SecurityRegistryError,
)
from workers.security_registry.storage import SupabaseSecurityRegistryStore


class SecRegistryFake:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = payload
        self.requests: list[tuple[str, Mapping[str, str]]] = []

    def request(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
    ) -> BytesResponse:
        self.requests.append((url, headers))
        return BytesResponse(
            body=json.dumps(self.payload).encode(), status=200, headers={}
        )


class StoreFake:
    def __init__(self) -> None:
        self.posts: list[tuple[str, Mapping[str, str], Mapping[str, Any]]] = []

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any] | None = None,
    ) -> JsonResponse:
        assert method == "POST"
        assert payload is not None
        self.posts.append((url, headers, payload))
        return JsonResponse(payload=None, status=201, headers={})


class SecurityRegistryTests(unittest.TestCase):
    def test_resolves_exact_ticker_to_stable_sec_identity(self) -> None:
        transport = SecRegistryFake(
            {
                "fields": ["cik", "name", "ticker", "exchange"],
                "data": [
                    [1601830, "Recursion Pharmaceuticals, Inc.", "RXRX", "Nasdaq"],
                    [1121404, "CRISPR Therapeutics AG", "CRSP", "Nasdaq"],
                ],
            }
        )
        client = SecurityRegistryClient(
            SecSettings(user_agent="Investment Research OS test@example.com"),
            transport=transport,
            clock=lambda: datetime(2026, 7, 22, 8, 0, tzinfo=UTC),
        )

        security = client.resolve(
            "rxrx", operator_id="11111111-1111-4111-8111-111111111111"
        )

        self.assertEqual(security.cik, "0001601830")
        self.assertEqual(security.ticker, "RXRX")
        self.assertEqual(security.primary_listing_exchange, "Nasdaq")
        self.assertEqual(len(security.security_id), 36)
        self.assertEqual(len(security.response_sha256), 64)
        self.assertEqual(
            transport.requests[0][0],
            "https://www.sec.gov/files/company_tickers_exchange.json",
        )
        self.assertIn("test@example.com", transport.requests[0][1]["User-Agent"])

    def test_rejects_ambiguous_sec_ticker_identity(self) -> None:
        client = SecurityRegistryClient(
            SecSettings(user_agent="Investment Research OS test@example.com"),
            transport=SecRegistryFake(
                {
                    "fields": ["cik", "name", "ticker", "exchange"],
                    "data": [
                        [1, "First", "TEST", "Nasdaq"],
                        [2, "Second", "TEST", "NYSE"],
                    ],
                }
            ),
        )

        with self.assertRaisesRegex(SecurityRegistryError, "exactly one"):
            client.resolve("TEST", operator_id="11111111-1111-4111-8111-111111111111")

    def test_rejects_multiple_listed_classes_for_one_stable_issuer_identity(
        self,
    ) -> None:
        client = SecurityRegistryClient(
            SecSettings(user_agent="Investment Research OS test@example.com"),
            transport=SecRegistryFake(
                {
                    "fields": ["cik", "name", "ticker", "exchange"],
                    "data": [
                        [1067983, "Example Holdings", "EX.A", "NYSE"],
                        [1067983, "Example Holdings", "EX.B", "NYSE"],
                    ],
                }
            ),
        )

        with self.assertRaisesRegex(
            SecurityRegistryError,
            "multiple listed securities",
        ):
            client.resolve(
                "EX.A",
                operator_id="11111111-1111-4111-8111-111111111111",
            )

    def test_persists_canonical_security_by_owner_and_stable_id(self) -> None:
        security = SecurityRegistryClient(
            SecSettings(user_agent="Investment Research OS test@example.com"),
            transport=SecRegistryFake(
                {
                    "fields": ["cik", "name", "ticker", "exchange"],
                    "data": [[1601830, "Recursion", "RXRX", "Nasdaq"]],
                }
            ),
            clock=lambda: datetime(2026, 7, 22, 8, 0, tzinfo=UTC),
        ).resolve("RXRX", operator_id="11111111-1111-4111-8111-111111111111")
        transport = StoreFake()
        store = SupabaseSecurityRegistryStore(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
        )

        store.persist(security)

        url, headers, payload = transport.posts[0]
        self.assertIn("/rest/v1/iros_securities?", url)
        self.assertIn("on_conflict=operator_id%2Cid", url)
        self.assertEqual(payload["id"], security.security_id)
        self.assertEqual(payload["cik"], "0001601830")
        self.assertEqual(headers["apikey"], "sb_secret_test")
        self.assertNotIn("Authorization", headers)


if __name__ == "__main__":
    unittest.main()

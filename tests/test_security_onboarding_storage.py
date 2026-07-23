from __future__ import annotations

import unittest
from typing import Any, Mapping

from workers.sec.storage import JsonResponse, SupabaseStorageSettings
from workers.security_onboarding.storage import SupabaseSecurityJobStore
from workers.security_onboarding.worker import SecurityJobClaim


class TransportFake:
    def __init__(self, response: JsonResponse) -> None:
        self.response = response
        self.requests: list[
            tuple[str, str, Mapping[str, str], Mapping[str, Any] | None]
        ] = []

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any] | None = None,
    ) -> JsonResponse:
        self.requests.append((method, url, headers, payload))
        return self.response


class SecurityOnboardingStorageTests(unittest.TestCase):
    def test_claims_one_fixed_security_job_through_service_rpc(self) -> None:
        transport = TransportFake(
            JsonResponse(
                payload=[
                    {
                        "job_id": "11111111-1111-4111-8111-111111111111",
                        "operator_id": "027d7f1b-d928-48d9-b6c8-f10d3c7ba792",
                        "ticker": "CRSP",
                        "attempt_id": "44444444-4444-4444-8444-444444444444",
                        "attempt_number": 1,
                        "lease_token": "55555555-5555-4555-8555-555555555555",
                    }
                ],
                status=200,
                headers={},
            )
        )
        store = SupabaseSecurityJobStore(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
        )

        claim = store.claim_next("iro-worker-1")

        self.assertIsNotNone(claim)
        assert claim is not None
        self.assertEqual(claim.ticker, "CRSP")
        method, url, headers, payload = transport.requests[0]
        self.assertEqual(method, "POST")
        self.assertTrue(url.endswith("/rest/v1/rpc/iros_claim_security_job"))
        self.assertEqual(payload, {"selected_worker_id": "iro-worker-1"})
        self.assertEqual(headers["apikey"], "sb_secret_test")
        self.assertNotIn("Authorization", headers)

    def test_completes_exact_claim_with_persisted_result_identities(self) -> None:
        transport = TransportFake(
            JsonResponse(payload=None, status=204, headers={})
        )
        store = SupabaseSecurityJobStore(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
        )
        claim = SecurityJobClaim(
            job_id="11111111-1111-4111-8111-111111111111",
            operator_id="027d7f1b-d928-48d9-b6c8-f10d3c7ba792",
            ticker="CRSP",
            attempt_id="44444444-4444-4444-8444-444444444444",
            attempt_number=1,
            lease_token="55555555-5555-4555-8555-555555555555",
        )

        store.complete(
            claim,
            security_id="22222222-2222-4222-8222-222222222222",
            market_series_id="33333333-3333-4333-8333-333333333333",
        )

        self.assertEqual(
            transport.requests[0][3],
            {
                "selected_job_id": claim.job_id,
                "selected_attempt_id": claim.attempt_id,
                "selected_lease_token": claim.lease_token,
                "selected_security_id": "22222222-2222-4222-8222-222222222222",
                "selected_market_series_id": "33333333-3333-4333-8333-333333333333",
            },
        )
        self.assertTrue(
            transport.requests[0][1].endswith(
                "/rest/v1/rpc/iros_complete_security_job"
            )
        )

    def test_records_bounded_failure_classification_for_exact_claim(self) -> None:
        transport = TransportFake(
            JsonResponse(payload=None, status=204, headers={})
        )
        store = SupabaseSecurityJobStore(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
        )
        claim = SecurityJobClaim(
            job_id="11111111-1111-4111-8111-111111111111",
            operator_id="027d7f1b-d928-48d9-b6c8-f10d3c7ba792",
            ticker="CRSP",
            attempt_id="44444444-4444-4444-8444-444444444444",
            attempt_number=1,
            lease_token="55555555-5555-4555-8555-555555555555",
        )

        store.fail(
            claim,
            stage="market_fetch",
            error_code="provider_unavailable",
            retryable=True,
        )

        self.assertEqual(
            transport.requests[0][3],
            {
                "selected_job_id": claim.job_id,
                "selected_attempt_id": claim.attempt_id,
                "selected_lease_token": claim.lease_token,
                "selected_error_stage": "market_fetch",
                "selected_error_code": "provider_unavailable",
                "selected_retryable": True,
            },
        )


if __name__ == "__main__":
    unittest.main()

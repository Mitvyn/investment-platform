from __future__ import annotations

import unittest
from typing import Any, Mapping

from workers.research_committee.storage import (
    SupabaseCommitteeCommandStore,
)
from workers.research_committee.worker import CommitteeCommandClaim
from workers.sec.storage import (
    EvidenceStorageError,
    JsonResponse,
    SupabaseStorageSettings,
)


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


class PersistentCommitteeWorkerStorageTests(unittest.TestCase):
    @staticmethod
    def _claim() -> CommitteeCommandClaim:
        from datetime import UTC, datetime

        return CommitteeCommandClaim(
            command_id="11111111-1111-4111-8111-111111111111",
            operator_id="027d7f1b-d928-48d9-b6c8-f10d3c7ba792",
            security_id="22222222-2222-4222-8222-222222222222",
            question_type_version=("biotech_moonshot_catalyst_assessment.v1"),
            workflow_config_version="biotech-moonshot-catalyst-v1",
            as_of_cutoff=datetime(2026, 5, 6, 23, 59, 59, tzinfo=UTC),
            operator_focus=None,
            attempt_id="44444444-4444-4444-8444-444444444444",
            attempt_number=1,
            lease_token="55555555-5555-4555-8555-555555555555",
            next_stage="research_run",
            completed_stages=(),
            research_run_id=None,
        )

    def test_claims_one_research_run_stage_through_service_rpc(self) -> None:
        transport = TransportFake(
            JsonResponse(
                payload=[
                    {
                        "command_id": ("11111111-1111-4111-8111-111111111111"),
                        "operator_id": ("027d7f1b-d928-48d9-b6c8-f10d3c7ba792"),
                        "security_id": ("22222222-2222-4222-8222-222222222222"),
                        "question_type_version": (
                            "biotech_moonshot_catalyst_assessment.v1"
                        ),
                        "workflow_config_version": ("biotech-moonshot-catalyst-v1"),
                        "as_of_cutoff": "2026-05-06T23:59:59+00:00",
                        "operator_focus_normalized": (
                            "Review financing through catalyst."
                        ),
                        "attempt_id": ("44444444-4444-4444-8444-444444444444"),
                        "attempt_number": 1,
                        "lease_token": ("55555555-5555-4555-8555-555555555555"),
                        "next_stage": "research_run",
                        "completed_stages": [],
                        "research_run_id": None,
                    }
                ],
                status=200,
                headers={},
            )
        )
        store = SupabaseCommitteeCommandStore(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
        )

        claim = store.claim_next("iros-committee-worker-1")

        self.assertIsNotNone(claim)
        assert claim is not None
        self.assertEqual(claim.next_stage, "research_run")
        self.assertEqual(claim.completed_stages, ())
        method, url, headers, payload = transport.requests[0]
        self.assertEqual(method, "POST")
        self.assertTrue(url.endswith("/rest/v1/rpc/iros_claim_research_run_command"))
        self.assertEqual(
            payload,
            {"selected_worker_id": "iros-committee-worker-1"},
        )
        self.assertEqual(headers["apikey"], "sb_secret_test")
        self.assertNotIn("Authorization", headers)

    def test_claims_personal_research_workflow_without_relaxing_identity(self) -> None:
        transport = TransportFake(
            JsonResponse(
                payload=[
                    {
                        "command_id": "11111111-1111-4111-8111-111111111111",
                        "operator_id": "027d7f1b-d928-48d9-b6c8-f10d3c7ba792",
                        "security_id": "22222222-2222-4222-8222-222222222222",
                        "question_type_version": (
                            "biotech_moonshot_catalyst_personal_research_assessment.v1"
                        ),
                        "workflow_config_version": (
                            "biotech-moonshot-catalyst-personal-research-v1"
                        ),
                        "as_of_cutoff": "2026-05-06T23:59:59+00:00",
                        "operator_focus_normalized": None,
                        "attempt_id": "44444444-4444-4444-8444-444444444444",
                        "attempt_number": 1,
                        "lease_token": "55555555-5555-4555-8555-555555555555",
                        "next_stage": "research_run",
                        "completed_stages": [],
                        "research_run_id": None,
                    }
                ],
                status=200,
                headers={},
            )
        )
        store = SupabaseCommitteeCommandStore(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
        )

        claim = store.claim_next("iros-committee-worker-1")

        self.assertIsNotNone(claim)
        assert claim is not None
        self.assertEqual(
            claim.question_type_version,
            "biotech_moonshot_catalyst_personal_research_assessment.v1",
        )
        self.assertEqual(
            claim.workflow_config_version,
            "biotech-moonshot-catalyst-personal-research-v1",
        )

        transport.response = JsonResponse(
            payload=[
                {
                    **transport.response.payload[0],
                    "workflow_config_version": "biotech-moonshot-catalyst-v1",
                }
            ],
            status=200,
            headers={},
        )
        with self.assertRaisesRegex(
            EvidenceStorageError,
            "committee command claim is malformed",
        ):
            store.claim_next("iros-committee-worker-1")

    def test_checkpoints_exact_claim_and_research_run_identity(self) -> None:
        transport = TransportFake(JsonResponse(payload=None, status=204, headers={}))
        store = SupabaseCommitteeCommandStore(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
        )
        claim = self._claim()

        store.checkpoint(
            claim,
            stage="research_run",
            artifact_id="66666666-6666-4666-8666-666666666666",
        )

        self.assertTrue(
            transport.requests[0][1].endswith(
                "/rest/v1/rpc/iros_checkpoint_research_run_command"
            )
        )
        self.assertEqual(
            transport.requests[0][3],
            {
                "selected_command_id": claim.command_id,
                "selected_attempt_id": claim.attempt_id,
                "selected_lease_token": claim.lease_token,
                "selected_stage": "research_run",
                "selected_artifact_id": ("66666666-6666-4666-8666-666666666666"),
            },
        )

    def test_renews_exact_claim_lease_through_service_rpc(self) -> None:
        transport = TransportFake(JsonResponse(payload=None, status=204, headers={}))
        store = SupabaseCommitteeCommandStore(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
        )
        claim = self._claim()

        store.renew_lease(claim)

        self.assertTrue(
            transport.requests[0][1].endswith(
                "/rest/v1/rpc/iros_renew_research_run_command_lease"
            )
        )
        self.assertEqual(
            transport.requests[0][3],
            {
                "selected_command_id": claim.command_id,
                "selected_attempt_id": claim.attempt_id,
                "selected_lease_token": claim.lease_token,
                "selected_stage": claim.next_stage,
            },
        )

    def test_rejects_evidence_bundle_claim_without_research_run_checkpoint(
        self,
    ) -> None:
        transport = TransportFake(
            JsonResponse(
                payload=[
                    {
                        "command_id": ("11111111-1111-4111-8111-111111111111"),
                        "operator_id": ("027d7f1b-d928-48d9-b6c8-f10d3c7ba792"),
                        "security_id": ("22222222-2222-4222-8222-222222222222"),
                        "question_type_version": (
                            "biotech_moonshot_catalyst_assessment.v1"
                        ),
                        "workflow_config_version": ("biotech-moonshot-catalyst-v1"),
                        "as_of_cutoff": "2026-05-06T23:59:59+00:00",
                        "operator_focus_normalized": None,
                        "attempt_id": ("44444444-4444-4444-8444-444444444444"),
                        "attempt_number": 1,
                        "lease_token": ("55555555-5555-4555-8555-555555555555"),
                        "next_stage": "evidence_bundle",
                        "completed_stages": [],
                        "research_run_id": None,
                    }
                ],
                status=200,
                headers={},
            )
        )
        store = SupabaseCommitteeCommandStore(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
        )

        with self.assertRaisesRegex(
            EvidenceStorageError,
            "committee command claim is malformed",
        ):
            store.claim_next("iros-committee-worker-1")


if __name__ == "__main__":
    unittest.main()

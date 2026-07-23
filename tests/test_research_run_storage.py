from __future__ import annotations

import unittest
from dataclasses import replace
from typing import Any, Mapping

from investment_research_os.research_runs import (
    AuthenticatedOperator,
    InMemoryResearchRunRepository,
    ResearchRunWorkflow,
)
from investment_research_os.research_runs.storage import (
    SupabaseResearchRunRepository,
)
from tests.test_research_run_workflow import (
    CUTOFF,
    EVALUATED_AT,
    OPERATOR_ID,
    SECURITY_ID,
    EligibleSecuritySource,
    SnapshotSecuritySource,
    eligible_snapshot,
)
from workers.sec.storage import (
    EvidenceStorageError,
    JsonResponse,
    SupabaseStorageSettings,
)


class RecordingTransport:
    def __init__(self, responses: list[JsonResponse]) -> None:
        self.responses = iter(responses)
        self.requests: list[dict[str, Any]] = []

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any] | None = None,
    ) -> JsonResponse:
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "payload": dict(payload) if payload is not None else None,
            }
        )
        return next(self.responses)


def eligible_run():
    return ResearchRunWorkflow(
        repository=InMemoryResearchRunRepository(),
        eligibility_source=EligibleSecuritySource(),
        clock=lambda: EVALUATED_AT,
    ).create(
        AuthenticatedOperator(OPERATOR_ID),
        {
            "question_type": "biotech_moonshot_catalyst_assessment",
            "security_id": SECURITY_ID,
            "as_of_cutoff": CUTOFF.isoformat(),
            "workflow_config_version": "biotech-moonshot-catalyst-v1",
            "operator_focus": "Review financing through catalyst.",
        },
    )


def view_rows(run) -> list[dict[str, Any]]:
    return [
        {
            "operator_id": run.operator_id,
            "research_run_id": run.id,
            "security_id": run.security_id,
            "security_identity_snapshot": {
                "id": run.security_identity.id,
                "cik": run.security_identity.cik,
                "issuer_name": run.security_identity.issuer_name,
                "symbol": run.security_identity.symbol,
                "primary_listing_exchange": (
                    run.security_identity.primary_listing_exchange
                ),
            },
            "question_type": run.question_type,
            "question_type_version_id": run.question_type_version,
            "workflow_config_version_id": run.workflow_config_version,
            "thesis_contract_id": run.thesis_contract_id,
            "as_of_cutoff": run.as_of_cutoff.isoformat(),
            "operator_focus_original": run.operator_focus_original,
            "operator_focus_normalized": run.operator_focus_normalized,
            "status": run.status,
            "idempotency_key": run.idempotency_key,
            "created_at": run.created_at.isoformat(),
            "eligibility_policy_version": run.eligibility.policy_version,
            "eligible": run.eligibility.eligible,
            "evaluated_at": run.eligibility.evaluated_at.isoformat(),
            "check_ordinal": ordinal,
            "rule_id": check.rule_id,
            "rule_version": check.rule_version,
            "passed": check.passed,
            "evidence_reference": check.evidence_reference,
            "reason_code": check.reason_code,
            "explanation": check.explanation,
            "check_evaluated_at": check.evaluated_at.isoformat(),
        }
        for ordinal, check in enumerate(run.eligibility.checks, start=1)
    ]


class SupabaseResearchRunRepositoryTests(unittest.TestCase):
    def test_invalid_identity_remains_in_run_snapshot_without_canonical_insert(
        self,
    ) -> None:
        snapshot = replace(
            eligible_snapshot(),
            security_identity_verified=False,
            cik="invalid",
            primary_listing_exchange="",
        )
        run = ResearchRunWorkflow(
            repository=InMemoryResearchRunRepository(),
            eligibility_source=SnapshotSecuritySource(snapshot),
            clock=lambda: EVALUATED_AT,
        ).create(
            AuthenticatedOperator(OPERATOR_ID),
            {
                "question_type": "biotech_moonshot_catalyst_assessment",
                "security_id": SECURITY_ID,
                "as_of_cutoff": CUTOFF.isoformat(),
                "workflow_config_version": "biotech-moonshot-catalyst-v1",
            },
        )

        records = SupabaseResearchRunRepository._records(run)

        self.assertFalse(run.eligibility.eligible)
        self.assertNotIn("iros_securities", [record[0] for record in records])
        research_run_record = next(
            record[3] for record in records if record[0] == "iros_research_runs"
        )
        self.assertEqual(
            research_run_record["security_identity_snapshot"]["cik"],
            "invalid",
        )

    def test_verified_identity_insert_never_overwrites_canonical_metadata(self) -> None:
        security_record = SupabaseResearchRunRepository._records(eligible_run())[0]

        self.assertEqual(security_record[0], "iros_securities")
        self.assertFalse(security_record[2])

    def test_rejects_partial_or_contradictory_view_results(self) -> None:
        run = eligible_run()
        partial_rows = view_rows(run)[:-1]
        transport = RecordingTransport(
            [JsonResponse(payload=partial_rows, status=200, headers={})]
        )
        repository = SupabaseResearchRunRepository(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
        )

        with self.assertRaisesRegex(EvidenceStorageError, "eligibility contract"):
            repository.get(run.operator_id, run.id)

    def test_persists_and_retrieves_owner_scoped_research_run(self) -> None:
        run = eligible_run()
        transport = RecordingTransport(
            [
                *[
                    JsonResponse(payload=None, status=201, headers={})
                    for _ in range(12)
                ],
                JsonResponse(payload=None, status=204, headers={}),
                JsonResponse(payload=view_rows(run), status=200, headers={}),
                JsonResponse(payload=view_rows(run), status=200, headers={}),
            ]
        )
        repository = SupabaseResearchRunRepository(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
        )

        saved = repository.save(run)
        retrieved = repository.get(run.operator_id, run.id)

        self.assertEqual(saved, run)
        self.assertEqual(retrieved, run)
        self.assertIn(
            f"operator_id=eq.{run.operator_id}", transport.requests[-1]["url"]
        )
        self.assertIn(f"research_run_id=eq.{run.id}", transport.requests[-1]["url"])
        self.assertTrue(
            all(
                request["headers"]["apikey"] == "sb_secret_test"
                for request in transport.requests
            )
        )
        finalize = transport.requests[12]
        self.assertEqual(finalize["method"], "PATCH")
        self.assertIn("iros_research_runs?", finalize["url"])
        self.assertEqual(finalize["payload"], {"persistence_state": "complete"})

    def test_rejects_conflicting_payload_for_existing_run_identity(self) -> None:
        run = eligible_run()
        conflicting_rows = view_rows(run)
        for row in conflicting_rows:
            row["operator_focus_normalized"] = "Different normalized focus."
        transport = RecordingTransport(
            [
                *[
                    JsonResponse(payload=None, status=201, headers={})
                    for _ in range(12)
                ],
                JsonResponse(payload=None, status=204, headers={}),
                JsonResponse(payload=conflicting_rows, status=200, headers={}),
            ]
        )
        repository = SupabaseResearchRunRepository(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
        )

        with self.assertRaisesRegex(EvidenceStorageError, "does not match"):
            repository.save(run)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from typing import Any, Mapping

from investment_research_os.evidence_bundles import (
    AuthenticatedOperator,
    EvidenceBundleCandidate,
    EvidenceBundleWorkflow,
    InMemoryEvidenceBundleRepository,
)
from investment_research_os.evidence_bundles.storage import (
    SupabaseEvidenceBundleRepository,
)
from investment_research_os.research_runs import InMemoryResearchRunRepository
from tests.test_evidence_bundle_workflow import (
    CREATED_AT,
    CUTOFF,
    OPERATOR_ID,
    RUN_ID,
    SECURITY_ID,
    FixedBundleSource,
    eligible_run,
    required_source_items,
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


def materialized_bundle():
    run_repository = InMemoryResearchRunRepository()
    run_repository.save(eligible_run())
    return EvidenceBundleWorkflow(
        research_run_repository=run_repository,
        bundle_repository=InMemoryEvidenceBundleRepository(),
        evidence_source=FixedBundleSource(
            EvidenceBundleCandidate(
                security_id=SECURITY_ID,
                as_of_cutoff=CUTOFF,
                evidence_policy_version="biotech-primary-evidence-v1",
                freshness_policy_version="biotech-evidence-freshness-v1",
                items=required_source_items(),
            )
        ),
        clock=lambda: CREATED_AT,
    ).materialize(AuthenticatedOperator(OPERATOR_ID), RUN_ID)


def repository(transport: RecordingTransport) -> SupabaseEvidenceBundleRepository:
    return SupabaseEvidenceBundleRepository(
        SupabaseStorageSettings(
            url="https://example.supabase.co",
            secret_key="sb_secret_test",
        ),
        transport=transport,
    )


def persisted_passage_rows(bundle):
    return [
        {
            "ordinal": ordinal,
            "item_id": item.evidence_id,
            "item_version_id": item.evidence_version_id,
            "item_kind": item.item_kind,
            "canonical_payload": {
                "contract_version": "evidence_passage.v1",
                "evidence_id": item.evidence_id,
                "passage_id": item.passage_id,
                "passage_text": item.passage_text,
                "passage_sha256": item.passage_hash,
            },
        }
        for ordinal, item in enumerate(bundle.manifest, start=1)
        if item.item_kind == "passage"
    ]


class SupabaseEvidenceBundleRepositoryTests(unittest.TestCase):
    def test_get_hydrates_exact_passages_from_immutable_manifest_payload(
        self,
    ) -> None:
        bundle = materialized_bundle()
        transport = RecordingTransport(
            [
                JsonResponse(
                    payload=[{"canonical_bundle": bundle.as_dict()}],
                    status=200,
                    headers={},
                ),
                JsonResponse(
                    payload=persisted_passage_rows(bundle),
                    status=200,
                    headers={},
                ),
            ]
        )

        loaded = repository(transport).get(OPERATOR_ID, bundle.id)

        self.assertIsNotNone(loaded)
        self.assertEqual(
            [item.passage_text for item in loaded.manifest],
            [item.passage_text for item in bundle.manifest],
        )
        self.assertIn(
            "iros_v_evidence_bundle_manifest?",
            transport.requests[1]["url"],
        )

    def test_get_keeps_legacy_missing_passage_content_readable(self) -> None:
        bundle = materialized_bundle()
        legacy_rows = persisted_passage_rows(bundle)
        for row in legacy_rows:
            row["canonical_payload"] = {}
        transport = RecordingTransport(
            [
                JsonResponse(
                    payload=[{"canonical_bundle": bundle.as_dict()}],
                    status=200,
                    headers={},
                ),
                JsonResponse(
                    payload=legacy_rows,
                    status=200,
                    headers={},
                ),
            ]
        )

        loaded = repository(transport).get(OPERATOR_ID, bundle.id)

        self.assertIsNotNone(loaded)
        self.assertTrue(
            all(
                item.passage_text is None
                for item in loaded.manifest
                if item.item_kind == "passage"
            )
        )

    def test_persists_dependency_order_finalizes_links_and_verifies_contract(
        self,
    ) -> None:
        bundle = materialized_bundle()
        transport = RecordingTransport(
            [
                JsonResponse(payload=[], status=200, headers={}),
                *[
                    JsonResponse(payload=None, status=201, headers={})
                    for _ in range((2 * len(bundle.manifest)) + 1)
                ],
                JsonResponse(payload=None, status=204, headers={}),
                JsonResponse(payload=None, status=201, headers={}),
                JsonResponse(
                    payload=[{"canonical_bundle": bundle.as_dict()}],
                    status=200,
                    headers={},
                ),
                JsonResponse(
                    payload=persisted_passage_rows(bundle),
                    status=200,
                    headers={},
                ),
            ]
        )

        saved = repository(transport).save(bundle)

        self.assertEqual(saved.as_dict(), bundle.as_dict())
        written_tables = [
            request["url"].split("/rest/v1/")[1].split("?")[0]
            for request in transport.requests
            if request["method"] == "POST"
        ]
        self.assertEqual(
            written_tables,
            [
                *["iros_evidence_versions"] * len(bundle.manifest),
                "iros_evidence_bundles",
                *["iros_evidence_bundle_items"] * len(bundle.manifest),
                "iros_research_run_evidence_bundles",
            ],
        )
        finalize = next(
            request
            for request in transport.requests
            if request["method"] == "PATCH"
        )
        self.assertIn("iros_evidence_bundles?", finalize["url"])
        self.assertEqual(finalize["payload"], {"persistence_state": "complete"})
        self.assertTrue(
            all(
                request["headers"]["apikey"] == "sb_secret_test"
                for request in transport.requests
            )
        )
        passage_write = next(
            request["payload"]
            for request in transport.requests
            if request["method"] == "POST"
            and request["payload"].get("item_kind") == "passage"
        )
        passage = bundle.manifest[0]
        self.assertEqual(
            passage_write["canonical_payload"],
            {
                "contract_version": "evidence_passage.v1",
                "evidence_id": passage.evidence_id,
                "passage_id": passage.passage_id,
                "passage_text": passage.passage_text,
                "passage_sha256": passage.passage_hash,
            },
        )

    def test_existing_identical_run_link_reuses_bundle_without_writes(self) -> None:
        bundle = materialized_bundle()
        transport = RecordingTransport(
            [
                JsonResponse(
                    payload=[{"canonical_bundle": bundle.as_dict()}],
                    status=200,
                    headers={},
                ),
                JsonResponse(
                    payload=persisted_passage_rows(bundle),
                    status=200,
                    headers={},
                ),
            ]
        )

        saved = repository(transport).save(bundle)

        self.assertEqual(saved.as_dict(), bundle.as_dict())
        self.assertEqual(
            [request["method"] for request in transport.requests],
            ["GET", "GET"],
        )

    def test_existing_conflicting_run_link_is_rejected(self) -> None:
        bundle = materialized_bundle()
        conflicting = bundle.as_dict()
        conflicting["bundle_hash"] = "0" * 64
        transport = RecordingTransport(
            [
                JsonResponse(
                    payload=[{"canonical_bundle": conflicting}],
                    status=200,
                    headers={},
                ),
                JsonResponse(
                    payload=persisted_passage_rows(bundle),
                    status=200,
                    headers={},
                ),
            ]
        )

        with self.assertRaisesRegex(EvidenceStorageError, "does not match"):
            repository(transport).save(bundle)

    def test_existing_passage_identity_mismatch_is_rejected(self) -> None:
        bundle = materialized_bundle()
        passage_rows = persisted_passage_rows(bundle)
        passage_rows[0]["canonical_payload"]["passage_id"] = (
            "96cf79ea-ddd2-4ed5-8a4a-3796209b60c9"
        )
        transport = RecordingTransport(
            [
                JsonResponse(
                    payload=[{"canonical_bundle": bundle.as_dict()}],
                    status=200,
                    headers={},
                ),
                JsonResponse(
                    payload=passage_rows,
                    status=200,
                    headers={},
                ),
            ]
        )

        with self.assertRaisesRegex(EvidenceStorageError, "does not match"):
            repository(transport).save(bundle)


if __name__ == "__main__":
    unittest.main()

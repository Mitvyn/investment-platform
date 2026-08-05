from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Mapping

from investment_research_os.evidence_bundles import (
    AuthenticatedOperator,
    InMemoryEvidenceBundleRepository,
)
from investment_research_os.valuation_snapshots import (
    InMemoryValuationSnapshotRepository,
    PersonalResearchValuationSnapshotWorkflow,
    ValuationSnapshotWorkflow,
)
from investment_research_os.valuation_snapshots.storage import (
    SupabaseValuationSnapshotRepository,
)
from tests.test_evidence_bundle_storage import materialized_bundle
from tests.test_valuation_snapshot_workflow import (
    FixedCalendar,
    FixedValuationSource,
    input_candidate,
    personal_input_candidate,
)
from workers.sec.storage import JsonResponse, SupabaseStorageSettings
from workers.sec.storage import EvidenceStorageError


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


def materialized_snapshot():
    bundle = materialized_bundle()
    bundle_repository = InMemoryEvidenceBundleRepository()
    bundle_repository.save(bundle)
    return ValuationSnapshotWorkflow(
        evidence_bundle_repository=bundle_repository,
        valuation_snapshot_repository=InMemoryValuationSnapshotRepository(),
        market_calendar=FixedCalendar(),
        input_source=FixedValuationSource(input_candidate()),
        clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
    ).materialize(AuthenticatedOperator(bundle.operator_id), bundle.id)


def materialized_invalid_snapshot():
    bundle = materialized_bundle()
    bundle_repository = InMemoryEvidenceBundleRepository()
    bundle_repository.save(bundle)
    return ValuationSnapshotWorkflow(
        evidence_bundle_repository=bundle_repository,
        valuation_snapshot_repository=InMemoryValuationSnapshotRepository(),
        market_calendar=FixedCalendar(),
        input_source=FixedValuationSource(replace(input_candidate(), prices=())),
        clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
    ).materialize(AuthenticatedOperator(bundle.operator_id), bundle.id)


def materialized_personal_snapshot():
    bundle = materialized_bundle()
    bundle_repository = InMemoryEvidenceBundleRepository()
    bundle_repository.save(bundle)
    return PersonalResearchValuationSnapshotWorkflow(
        evidence_bundle_repository=bundle_repository,
        valuation_snapshot_repository=InMemoryValuationSnapshotRepository(),
        market_calendar=FixedCalendar(),
        input_source=FixedValuationSource(personal_input_candidate()),
        clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
    ).materialize(AuthenticatedOperator(bundle.operator_id), bundle.id)


def repository(
    transport: RecordingTransport,
) -> SupabaseValuationSnapshotRepository:
    return SupabaseValuationSnapshotRepository(
        SupabaseStorageSettings(
            url="https://example.supabase.co",
            secret_key="sb_secret_test",
        ),
        transport=transport,
    )


class SupabaseValuationSnapshotRepositoryTests(unittest.TestCase):
    def test_personal_research_snapshot_round_trips_separate_contract(self) -> None:
        snapshot = materialized_personal_snapshot()
        wire = snapshot.as_dict()
        transport = RecordingTransport(
            [
                JsonResponse(
                    payload=[{"canonical_snapshot": wire}],
                    status=200,
                    headers={},
                )
            ]
        )

        loaded = repository(transport).get_for_run(
            snapshot.operator_id,
            snapshot.research_run_id,
        )

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.as_dict(), wire)
        self.assertEqual(
            loaded.contract_version,
            "valuation_snapshot.personal_research.v1",
        )
        self.assertEqual(
            loaded.valuation_assurance.level,
            "personal_research",
        )

    def test_personal_research_persistence_keeps_generic_and_legacy_timestamp_columns_aligned(
        self,
    ) -> None:
        snapshot = materialized_personal_snapshot()

        _, _, record = SupabaseValuationSnapshotRepository._records(snapshot)[0]

        self.assertEqual(
            record["price_timestamp"],
            snapshot.as_dict()["price_basis"]["price_timestamp"],
        )
        self.assertEqual(
            record["official_close_timestamp"],
            record["price_timestamp"],
        )
        self.assertNotIn(
            "official_close_timestamp",
            snapshot.as_dict()["price_basis"],
        )

    def test_persists_components_finalizes_and_verifies_contract(self) -> None:
        snapshot = materialized_snapshot()
        wire = snapshot.as_dict()
        component_count = (
            4
            + len(wire["dilution_instruments"])
            + len(wire["calculation_ids"])
            + len(wire["evidence_materiality"])
        )
        transport = RecordingTransport(
            [
                JsonResponse(payload=[], status=200, headers={}),
                *[
                    JsonResponse(payload=None, status=201, headers={})
                    for _ in range(component_count + 1)
                ],
                JsonResponse(payload=None, status=204, headers={}),
                JsonResponse(
                    payload=[{"canonical_snapshot": wire}],
                    status=200,
                    headers={},
                ),
            ]
        )

        saved = repository(transport).save(snapshot)

        self.assertEqual(saved.as_dict(), wire)
        written_tables = [
            request["url"].split("/rest/v1/")[1].split("?")[0]
            for request in transport.requests
            if request["method"] == "POST"
        ]
        self.assertEqual(
            written_tables,
            [
                "iros_valuation_snapshots",
                *["iros_valuation_capital_inputs"]
                * (4 + len(wire["dilution_instruments"])),
                *["iros_valuation_calculation_results"] * len(wire["calculation_ids"]),
                *["iros_valuation_materiality_assessments"]
                * len(wire["evidence_materiality"]),
            ],
        )
        finalize = next(
            request for request in transport.requests if request["method"] == "PATCH"
        )
        self.assertIn("iros_valuation_snapshots?", finalize["url"])
        self.assertEqual(finalize["payload"], {"persistence_state": "complete"})
        initial_get = transport.requests[0]
        self.assertIn(f"operator_id=eq.{snapshot.operator_id}", initial_get["url"])
        self.assertIn(
            f"research_run_id=eq.{snapshot.research_run_id}",
            initial_get["url"],
        )
        self.assertTrue(
            all(
                request["headers"]["apikey"] == "sb_secret_test"
                for request in transport.requests
            )
        )

    def test_existing_identical_run_snapshot_reuses_without_writes(self) -> None:
        snapshot = materialized_snapshot()
        transport = RecordingTransport(
            [
                JsonResponse(
                    payload=[{"canonical_snapshot": snapshot.as_dict()}],
                    status=200,
                    headers={},
                )
            ]
        )

        saved = repository(transport).save(snapshot)

        self.assertEqual(saved.as_dict(), snapshot.as_dict())
        self.assertEqual(
            [request["method"] for request in transport.requests],
            ["GET"],
        )

    def test_existing_conflicting_run_snapshot_is_rejected(self) -> None:
        snapshot = materialized_snapshot()
        conflicting = snapshot.as_dict()
        conflicting["invalid_reason_codes"] = ["conflicting_hosted_value"]
        transport = RecordingTransport(
            [
                JsonResponse(
                    payload=[{"canonical_snapshot": conflicting}],
                    status=200,
                    headers={},
                )
            ]
        )

        with self.assertRaisesRegex(EvidenceStorageError, "does not match"):
            repository(transport).save(snapshot)

        self.assertEqual(
            [request["method"] for request in transport.requests],
            ["GET"],
        )

    def test_invalid_snapshot_round_trips_without_price_or_derived_values(
        self,
    ) -> None:
        snapshot = materialized_invalid_snapshot()
        transport = RecordingTransport(
            [
                JsonResponse(
                    payload=[{"canonical_snapshot": snapshot.as_dict()}],
                    status=200,
                    headers={},
                )
            ]
        )

        loaded = repository(transport).get_for_run(
            snapshot.operator_id,
            snapshot.research_run_id,
        )

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.as_dict(), snapshot.as_dict())
        self.assertIsNone(loaded.price)
        self.assertIsNone(loaded.market_capitalization)
        self.assertIsNone(loaded.enterprise_value)

    def test_unresolved_price_source_reference_is_rejected(self) -> None:
        snapshot = materialized_snapshot()
        invalid = snapshot.as_dict()
        invalid["price_basis"]["provider_source_reference_id"] = "missing-source"
        transport = RecordingTransport(
            [
                JsonResponse(
                    payload=[{"canonical_snapshot": invalid}],
                    status=200,
                    headers={},
                )
            ]
        )

        with self.assertRaisesRegex(EvidenceStorageError, "invalid contract"):
            repository(transport).get_for_run(
                snapshot.operator_id,
                snapshot.research_run_id,
            )


if __name__ == "__main__":
    unittest.main()

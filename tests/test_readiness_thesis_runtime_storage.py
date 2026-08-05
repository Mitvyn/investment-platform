from __future__ import annotations

import unittest
from dataclasses import replace
from typing import Any, Mapping
from datetime import UTC, datetime

from investment_research_os.readiness_and_theses.storage import (
    ReadinessThesisRuntimeStorageError,
    SupabaseReadinessThesisReadModel,
    SupabaseReadinessThesisRuntimeStore,
)
from tests.test_readiness_and_thesis import (
    synthesized_fixture,
    synthesized_terminal_fixture,
)
from workers.sec.storage import JsonResponse, SupabaseStorageSettings
from investment_research_os.readiness_and_theses import (
    InMemoryReadinessAndThesisRepository,
    ReadinessAndThesisWorkflow,
    ReadinessRequest,
)
from investment_research_os.research_runs import AuthenticatedOperator
from investment_research_os.research_runs import (
    PERSONAL_RESEARCH_QUESTION_TYPE,
    PERSONAL_RESEARCH_QUESTION_TYPE_VERSION,
    PERSONAL_RESEARCH_THESIS_CONTRACT_ID,
    PERSONAL_RESEARCH_WORKFLOW_CONFIG_VERSION,
)
from investment_research_os.valuation_snapshots import (
    InMemoryValuationSnapshotRepository,
    PersonalResearchValuationSnapshotWorkflow,
)
from tests.test_readiness_and_thesis import FixedCommitteeRepository
from tests.test_valuation_snapshot_workflow import (
    FixedCalendar,
    FixedValuationSource,
    personal_input_candidate,
)


class TransportFake:
    def __init__(self, response: JsonResponse | list[JsonResponse]) -> None:
        self.responses = response if isinstance(response, list) else [response]
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
        return self.responses.pop(0)


def readiness_result(*, terminal_state: str | None = None):
    fixture = (
        synthesized_fixture(requested_disposition="monitor")
        if terminal_state is None
        else synthesized_terminal_fixture(terminal_state=terminal_state)
    )
    bundle, committee, bundle_repository, committee_repository, memo_repository, _ = (
        fixture
    )
    result = ReadinessAndThesisWorkflow(
        committee_repository=committee_repository,
        evidence_bundle_repository=bundle_repository,
        memo_repository=memo_repository,
        repository=InMemoryReadinessAndThesisRepository(),
        clock=lambda: datetime(2026, 7, 22, 5, 0, tzinfo=UTC),
    ).execute(
        AuthenticatedOperator(bundle.operator_id),
        ReadinessRequest(
            committee_id=committee.committee_id,
            gate_policy_version="biotech-readiness.v1",
        ),
    )
    return result


def personal_readiness_result():
    bundle, committee, bundle_repository, _, memo_repository, _ = synthesized_fixture(
        requested_disposition="decision_ready"
    )
    personal_committee = replace(
        committee,
        question_type_id=PERSONAL_RESEARCH_QUESTION_TYPE,
        question_type_version=PERSONAL_RESEARCH_QUESTION_TYPE_VERSION,
        workflow_config_version=PERSONAL_RESEARCH_WORKFLOW_CONFIG_VERSION,
    )
    valuation_repository = InMemoryValuationSnapshotRepository()
    PersonalResearchValuationSnapshotWorkflow(
        evidence_bundle_repository=bundle_repository,
        valuation_snapshot_repository=valuation_repository,
        market_calendar=FixedCalendar(),
        input_source=FixedValuationSource(personal_input_candidate()),
        clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
    ).materialize(AuthenticatedOperator(bundle.operator_id), bundle.id)
    return ReadinessAndThesisWorkflow(
        committee_repository=FixedCommitteeRepository(personal_committee),
        evidence_bundle_repository=bundle_repository,
        valuation_snapshot_repository=valuation_repository,
        memo_repository=memo_repository,
        repository=InMemoryReadinessAndThesisRepository(),
        clock=lambda: datetime(2026, 7, 22, 5, 0, tzinfo=UTC),
    ).execute(
        AuthenticatedOperator(bundle.operator_id),
        ReadinessRequest(
            committee_id=personal_committee.committee_id,
            gate_policy_version="biotech-personal-readiness.v1",
        ),
    )


class ReadinessThesisRuntimeStorageTests(unittest.TestCase):
    def test_personal_research_result_round_trips_through_runtime_parser(self) -> None:
        result = personal_readiness_result()
        transport = TransportFake(
            [
                JsonResponse(
                    payload=[
                        {
                            "operator_id": result.readiness.operator_id,
                            "research_run_id": result.readiness.research_run_id,
                            "committee_result_id": result.readiness.committee_result_id,
                            "committee_memo_id": result.readiness.committee_memo_id,
                            "canonical_readiness": result.readiness.as_dict(),
                        }
                    ],
                    status=200,
                    headers={},
                ),
                JsonResponse(
                    payload=[
                        {
                            "operator_id": result.thesis_creation.operator_id,
                            "research_run_id": result.thesis_creation.research_run_id,
                            "readiness_gate_result_id": (
                                result.thesis_creation.readiness_gate_result_id
                            ),
                            "creation_outcome": result.thesis_creation.creation_outcome,
                            "thesis_version_id": result.thesis_creation.thesis_version_id,
                            "canonical_creation_result": result.thesis_creation.as_dict(),
                        }
                    ],
                    status=200,
                    headers={},
                ),
                JsonResponse(
                    payload=[
                        {
                            "operator_id": result.thesis.operator_id,
                            "id": result.thesis.thesis_version_id,
                            "canonical_thesis": result.thesis.as_dict(),
                        }
                    ],
                    status=200,
                    headers={},
                ),
            ]
        )
        repository = SupabaseReadinessThesisReadModel(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
        )

        loaded = repository.get_for_run(
            result.readiness.operator_id,
            result.readiness.research_run_id,
        )
        assert loaded is not None
        self.assertEqual(
            loaded.readiness.thesis_contract_id,
            PERSONAL_RESEARCH_THESIS_CONTRACT_ID,
        )
        self.assertEqual(loaded.thesis, result.thesis)

    def test_persists_no_thesis_as_explicit_terminal_outcome(self) -> None:
        result = readiness_result(terminal_state="failed")
        transport = TransportFake(
            JsonResponse(
                payload=[
                    {
                        "operator_id": result.readiness.operator_id,
                        "research_run_id": result.readiness.research_run_id,
                        "readiness_gate_result_id": (
                            result.readiness.readiness_gate_result_id
                        ),
                        "thesis_creation_result_id": (
                            result.thesis_creation.thesis_creation_result_id
                        ),
                        "thesis_version_id": None,
                        "creation_outcome": "no_thesis",
                        "reused": False,
                    }
                ],
                status=200,
                headers={},
            )
        )
        store = SupabaseReadinessThesisRuntimeStore(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
        )

        receipt = store.persist(result)

        self.assertEqual(receipt.creation_outcome, "no_thesis")
        self.assertIsNone(receipt.thesis_version_id)
        self.assertIsNone(transport.requests[0][3]["p_thesis"])

    def test_persists_complete_readiness_and_thesis_in_one_service_rpc(self) -> None:
        result = readiness_result()
        receipt_payload = {
            "operator_id": result.readiness.operator_id,
            "research_run_id": result.readiness.research_run_id,
            "readiness_gate_result_id": (result.readiness.readiness_gate_result_id),
            "thesis_creation_result_id": (
                result.thesis_creation.thesis_creation_result_id
            ),
            "thesis_version_id": result.thesis.thesis_version_id,
            "creation_outcome": "canonical_created",
            "reused": False,
        }
        transport = TransportFake(
            JsonResponse(payload=[receipt_payload], status=200, headers={})
        )
        store = SupabaseReadinessThesisRuntimeStore(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
        )

        receipt = store.persist(result)

        self.assertEqual(receipt.research_run_id, result.readiness.research_run_id)
        method, url, headers, payload = transport.requests[0]
        self.assertEqual(method, "POST")
        self.assertTrue(
            url.endswith("/rest/v1/rpc/iros_persist_readiness_thesis_runtime")
        )
        self.assertEqual(headers["apikey"], "sb_secret_test")
        self.assertNotIn("Authorization", headers)
        assert payload is not None
        self.assertEqual(
            set(payload),
            {
                "p_operator_id",
                "p_readiness",
                "p_thesis_creation",
                "p_thesis",
            },
        )
        self.assertEqual(
            payload["p_readiness"],
            result.readiness.as_dict(),
        )
        self.assertEqual(
            payload["p_thesis_creation"],
            result.thesis_creation.as_dict(),
        )
        self.assertEqual(payload["p_thesis"], result.thesis.as_dict())

    def test_rejects_receipt_that_does_not_match_persisted_result(self) -> None:
        result = readiness_result()
        transport = TransportFake(
            JsonResponse(
                payload=[
                    {
                        "operator_id": result.readiness.operator_id,
                        "research_run_id": ("99999999-9999-4999-8999-999999999999"),
                        "readiness_gate_result_id": (
                            result.readiness.readiness_gate_result_id
                        ),
                        "thesis_creation_result_id": (
                            result.thesis_creation.thesis_creation_result_id
                        ),
                        "thesis_version_id": result.thesis.thesis_version_id,
                        "creation_outcome": "canonical_created",
                        "reused": False,
                    }
                ],
                status=200,
                headers={},
            )
        )
        store = SupabaseReadinessThesisRuntimeStore(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
        )

        with self.assertRaisesRegex(
            ReadinessThesisRuntimeStorageError,
            "receipt does not match",
        ):
            store.persist(result)


if __name__ == "__main__":
    unittest.main()

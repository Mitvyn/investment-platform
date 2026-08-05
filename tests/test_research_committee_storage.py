from __future__ import annotations

import unittest
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from investment_research_os.research_committees.storage import (
    SupabaseResearchCommitteeReadModel,
    SupabaseResearchCommitteeRepository,
)
from tests.test_five_grader_committee import completed_committee_fixture
from tests.test_readiness_and_thesis import synthesized_terminal_fixture
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
                "payload": None if payload is None else dict(payload),
            }
        )
        return next(self.responses)


def _view_rows(bundle, committee):
    committee_row = {
        "operator_id": committee.operator_id,
        "research_run_id": committee.research_run_id,
        "security_id": bundle.security_id,
        "evidence_bundle_id": committee.evidence_bundle_id,
        "evidence_bundle_hash": committee.evidence_bundle_hash,
        "committee_result_id": committee.committee_id,
        "workflow_config_version": committee.workflow_config_version,
        "proposition_id": committee.proposition_id,
        "proposition_version": committee.proposition_version,
        "rendered_proposition_text": committee.rendered_proposition_text,
        "committee_status": committee.status,
        "accounting": committee.as_dict()["accounting"],
        "stance_counts": committee.as_dict()["stance_counts"],
        "idempotency_key": committee.committee_key,
        "canonical_committee": committee.as_dict(),
        "derived_at": committee.created_at.isoformat(),
        "created_at": committee.created_at.isoformat(),
    }
    grader_rows = []
    for position, result in enumerate(committee.grader_results, start=1):
        execution = result.execution.as_dict() if result.execution else None
        grader_rows.append(
            {
                "operator_id": committee.operator_id,
                "research_run_id": committee.research_run_id,
                "committee_result_id": committee.committee_id,
                "grader_execution_id": (
                    None if result.execution is None else result.execution.execution_id
                ),
                "grader_opinion_id": (
                    None if result.opinion is None else result.opinion.opinion_id
                ),
                "grader_id": result.grader_id,
                "grader_version": result.grader_version,
                "roster_position": position,
                "required": result.required,
                "execution_state": result.execution_state,
                "owned_decision_question": result.owned_decision_question,
                "canonical_execution": execution,
                "canonical_opinion": (
                    None if execution is None else execution["opinion"]
                ),
                "not_eligible": committee.as_dict()["grader_results"][position - 1][
                    "not_eligible"
                ],
                "not_executed": committee.as_dict()["grader_results"][position - 1][
                    "not_executed"
                ],
                "failure": committee.as_dict()["grader_results"][position - 1][
                    "failure"
                ],
                "persisted_at": result.persisted_at.isoformat(),
            }
        )
    return committee_row, grader_rows


class SupabaseResearchCommitteeReadModelTests(unittest.TestCase):
    def _read_model(
        self,
        transport: RecordingTransport,
    ) -> SupabaseResearchCommitteeReadModel:
        return SupabaseResearchCommitteeReadModel(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
        )

    def test_reconstructs_exact_owner_run_committee_and_five_grader_states(
        self,
    ) -> None:
        bundle, committee, _, _ = completed_committee_fixture()
        committee_row, grader_rows = _view_rows(bundle, committee)
        transport = RecordingTransport(
            [
                JsonResponse(payload=[committee_row], status=200, headers={}),
                JsonResponse(payload=grader_rows, status=200, headers={}),
            ]
        )
        read_model = self._read_model(transport)

        loaded = read_model.get_for_run(
            committee.operator_id,
            committee.research_run_id,
        )

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.as_dict(), committee.as_dict())
        self.assertEqual(loaded.committee_id, committee.committee_id)
        self.assertEqual(
            tuple(item.grader_id for item in loaded.grader_results),
            ("moonshot", "catalyst", "biotech", "risk_dilution", "valuation"),
        )
        self.assertTrue(all(item.opinion is not None for item in loaded.grader_results))

    def test_rejects_duplicate_owner_run_committees(self) -> None:
        bundle, committee, _, _ = completed_committee_fixture()
        committee_row, _ = _view_rows(bundle, committee)
        transport = RecordingTransport(
            [
                JsonResponse(
                    payload=[committee_row, committee_row],
                    status=200,
                    headers={},
                )
            ]
        )

        with self.assertRaisesRegex(
            EvidenceStorageError,
            "duplicate or malformed",
        ):
            self._read_model(transport).get_for_run(
                committee.operator_id,
                committee.research_run_id,
            )

    def test_rejects_foreign_grader_row(self) -> None:
        bundle, committee, _, _ = completed_committee_fixture()
        committee_row, grader_rows = _view_rows(bundle, committee)
        foreign_rows = deepcopy(grader_rows)
        foreign_rows[2]["operator_id"] = "99999999-9999-4999-8999-999999999999"
        transport = RecordingTransport(
            [
                JsonResponse(payload=[committee_row], status=200, headers={}),
                JsonResponse(payload=foreign_rows, status=200, headers={}),
            ]
        )

        with self.assertRaisesRegex(
            EvidenceStorageError,
            "invalid canonical state",
        ):
            self._read_model(transport).get_for_run(
                committee.operator_id,
                committee.research_run_id,
            )

    def test_rejects_inconsistent_locked_opinion(self) -> None:
        bundle, committee, _, _ = completed_committee_fixture()
        committee_row, grader_rows = _view_rows(bundle, committee)
        inconsistent_rows = deepcopy(grader_rows)
        inconsistent_rows[4]["canonical_opinion"]["summary"] = (
            "Conflicting persisted valuation conclusion."
        )
        transport = RecordingTransport(
            [
                JsonResponse(payload=[committee_row], status=200, headers={}),
                JsonResponse(
                    payload=inconsistent_rows,
                    status=200,
                    headers={},
                ),
            ]
        )

        with self.assertRaisesRegex(
            EvidenceStorageError,
            "invalid canonical state",
        ):
            self._read_model(transport).get_for_run(
                committee.operator_id,
                committee.research_run_id,
            )

    def test_rejects_accounting_that_disagrees_with_locked_grader_rows(
        self,
    ) -> None:
        bundle, committee, _, _ = completed_committee_fixture()
        committee_row, grader_rows = _view_rows(bundle, committee)
        inconsistent_row = deepcopy(committee_row)
        inconsistent_row["accounting"]["accepted_count"] = 4
        inconsistent_row["accounting"]["failed_count"] = 1
        inconsistent_row["canonical_committee"]["accounting"] = deepcopy(
            inconsistent_row["accounting"]
        )
        transport = RecordingTransport(
            [
                JsonResponse(
                    payload=[inconsistent_row],
                    status=200,
                    headers={},
                ),
                JsonResponse(payload=grader_rows, status=200, headers={}),
            ]
        )

        with self.assertRaisesRegex(
            EvidenceStorageError,
            "invalid canonical state",
        ):
            self._read_model(transport).get_for_run(
                committee.operator_id,
                committee.research_run_id,
            )

    def test_preserves_abstained_and_failed_terminal_states_without_stances(
        self,
    ) -> None:
        for state in ("abstained", "failed"):
            with self.subTest(state=state):
                fixture = synthesized_terminal_fixture(terminal_state=state)
                bundle, committee = fixture[:2]
                committee_row, grader_rows = _view_rows(bundle, committee)
                transport = RecordingTransport(
                    [
                        JsonResponse(
                            payload=[committee_row],
                            status=200,
                            headers={},
                        ),
                        JsonResponse(
                            payload=grader_rows,
                            status=200,
                            headers={},
                        ),
                    ]
                )

                loaded = self._read_model(transport).get_for_run(
                    committee.operator_id,
                    committee.research_run_id,
                )

                self.assertEqual(loaded.as_dict(), committee.as_dict())
                terminal = loaded.grader_results[-1]
                self.assertEqual(terminal.execution_state, state)
                self.assertIsNone(terminal.stance)
                self.assertEqual(
                    terminal.opinion is not None,
                    state == "abstained",
                )
        self.assertIn(
            "iros_committee_results?",
            transport.requests[0]["url"],
        )
        self.assertIn(
            f"operator_id=eq.{committee.operator_id}",
            transport.requests[0]["url"],
        )
        self.assertIn(
            f"research_run_id=eq.{committee.research_run_id}",
            transport.requests[0]["url"],
        )
        self.assertTrue(
            all(
                request["headers"]["apikey"] == "sb_secret_test"
                for request in transport.requests
            )
        )


class SupabaseResearchCommitteeRepositoryTests(unittest.TestCase):
    def test_persists_draft_before_five_rows_and_reloads_final_committee(
        self,
    ) -> None:
        bundle, committee, _, _ = completed_committee_fixture()
        committee_row, grader_rows = _view_rows(bundle, committee)
        transport = RecordingTransport(
            [
                JsonResponse(payload=None, status=201, headers={}),
                *(
                    JsonResponse(payload=None, status=201, headers={})
                    for _ in committee.grader_results
                ),
                JsonResponse(payload=None, status=204, headers={}),
                JsonResponse(payload=[committee_row], status=200, headers={}),
                JsonResponse(payload=grader_rows, status=200, headers={}),
            ]
        )
        repository = SupabaseResearchCommitteeRepository(
            SupabaseStorageSettings(
                url="https://example.supabase.co",
                secret_key="sb_secret_test",
            ),
            transport=transport,
        )

        repository.begin_committee(committee)
        for result in committee.grader_results:
            repository.save_grader_state(
                committee,
                result,
            )
        persisted = repository.finalize_committee(committee)

        self.assertEqual(persisted.as_dict(), committee.as_dict())
        self.assertEqual(persisted.committee_id, committee.committee_id)
        self.assertEqual(
            [request["method"] for request in transport.requests],
            [
                "POST",
                "POST",
                "POST",
                "POST",
                "POST",
                "POST",
                "PATCH",
                "GET",
                "GET",
            ],
        )
        self.assertIn(
            "/iros_committee_results?",
            transport.requests[0]["url"],
        )
        self.assertEqual(
            transport.requests[0]["payload"]["persistence_state"],
            "draft",
        )
        self.assertTrue(
            all(
                "/iros_committee_grader_results?" in request["url"]
                for request in transport.requests[1:6]
            )
        )


if __name__ == "__main__":
    unittest.main()

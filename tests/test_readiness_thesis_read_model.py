from __future__ import annotations

import unittest
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

from investment_research_os.readiness_and_theses import ThesisChain
from investment_research_os.readiness_and_theses.storage import (
    ReadinessThesisRuntimeStorageError,
    SupabaseReadinessThesisReadModel,
)
from tests.test_readiness_thesis_runtime_storage import readiness_result
from workers.sec.storage import (
    JsonResponse,
    SupabaseStorageSettings,
)


class TransportFake:
    def __init__(self, *responses: JsonResponse) -> None:
        self.responses = list(responses)
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


def response(rows) -> JsonResponse:
    return JsonResponse(payload=rows, status=200, headers={})


def readiness_row(result) -> dict[str, object]:
    readiness = result.readiness
    return {
        "operator_id": readiness.operator_id,
        "research_run_id": readiness.research_run_id,
        "committee_result_id": readiness.committee_result_id,
        "committee_memo_id": readiness.committee_memo_id,
        "canonical_readiness": readiness.as_dict(),
    }


def creation_row(result) -> dict[str, object]:
    creation = result.thesis_creation
    return {
        "operator_id": creation.operator_id,
        "research_run_id": creation.research_run_id,
        "readiness_gate_result_id": creation.readiness_gate_result_id,
        "creation_outcome": creation.creation_outcome,
        "thesis_version_id": creation.thesis_version_id,
        "canonical_creation_result": creation.as_dict(),
    }


def thesis_row(thesis) -> dict[str, object]:
    return {
        "operator_id": thesis.operator_id,
        "id": thesis.thesis_version_id,
        "canonical_thesis": thesis.as_dict(),
    }


def chain_for(result) -> ThesisChain:
    thesis = result.thesis
    return ThesisChain(
        operator_id=result.readiness.operator_id,
        security_id=result.readiness.security_id,
        thesis_contract_id=result.readiness.thesis_contract_id,
        active_canonical_thesis_version_id=thesis.thesis_version_id,
        canonical_versions=(thesis,),
        provisional_branches=(),
        generated_at=thesis.created_at,
    )


def chain_row(chain: ThesisChain) -> dict[str, object]:
    return {
        "operator_id": chain.operator_id,
        "security_id": chain.security_id,
        "thesis_contract_id": chain.thesis_contract_id,
        "canonical_chain": chain.as_dict(),
    }


def read_model(*responses: JsonResponse):
    transport = TransportFake(*responses)
    model = SupabaseReadinessThesisReadModel(
        SupabaseStorageSettings(
            url="https://example.supabase.co",
            secret_key="sb_secret_test",
        ),
        transport=transport,
    )
    return model, transport


class SupabaseReadinessThesisReadModelTests(unittest.TestCase):
    def test_get_for_run_reconstructs_exact_persisted_result(self) -> None:
        result = readiness_result()
        model, transport = read_model(
            response([readiness_row(result)]),
            response([creation_row(result)]),
            response([thesis_row(result.thesis)]),
        )

        loaded = model.get_for_run(
            result.readiness.operator_id,
            result.readiness.research_run_id,
        )

        self.assertEqual(loaded, result)
        self.assertEqual(len(transport.requests), 3)
        for _, url, headers, payload in transport.requests:
            query = parse_qs(urlparse(url).query)
            self.assertEqual(
                query["operator_id"],
                [f"eq.{result.readiness.operator_id}"],
            )
            self.assertEqual(headers, {"apikey": "sb_secret_test"})
            self.assertIsNone(payload)
        self.assertEqual(
            parse_qs(urlparse(transport.requests[0][1]).query)[
                "research_run_id"
            ],
            [f"eq.{result.readiness.research_run_id}"],
        )

    def test_get_for_run_reconstructs_explicit_no_thesis_result(self) -> None:
        result = readiness_result(terminal_state="failed")
        model, transport = read_model(
            response([readiness_row(result)]),
            response([creation_row(result)]),
        )

        loaded = model.get_for_run(
            result.readiness.operator_id,
            result.readiness.research_run_id,
        )

        self.assertEqual(loaded, result)
        self.assertIsNone(loaded.thesis)
        self.assertEqual(len(transport.requests), 2)

    def test_direct_id_reads_reconstruct_readiness_and_thesis(self) -> None:
        result = readiness_result()
        model, transport = read_model(
            response([readiness_row(result)]),
            response([thesis_row(result.thesis)]),
        )

        readiness = model.get_readiness_by_id(
            result.readiness.operator_id,
            result.readiness.readiness_gate_result_id,
        )
        thesis = model.get_thesis_by_id(
            result.readiness.operator_id,
            result.thesis.thesis_version_id,
        )

        self.assertEqual(readiness, result.readiness)
        self.assertEqual(thesis, result.thesis)
        readiness_query = parse_qs(urlparse(transport.requests[0][1]).query)
        thesis_query = parse_qs(urlparse(transport.requests[1][1]).query)
        self.assertEqual(
            readiness_query["id"],
            [f"eq.{result.readiness.readiness_gate_result_id}"],
        )
        self.assertEqual(
            thesis_query["id"],
            [f"eq.{result.thesis.thesis_version_id}"],
        )

    def test_get_chain_reconstructs_exact_ordered_domain_chain(self) -> None:
        result = readiness_result()
        expected = chain_for(result)
        model, _ = read_model(response([chain_row(expected)]))

        loaded = model.get_chain(
            expected.operator_id,
            expected.security_id,
            expected.thesis_contract_id,
        )

        self.assertEqual(loaded, expected)

    def test_rejects_chain_whose_active_id_does_not_match_order(self) -> None:
        result = readiness_result()
        canonical = chain_for(result).as_dict()
        canonical["active_canonical_thesis_version_id"] = None
        row = {
            **chain_row(chain_for(result)),
            "canonical_chain": canonical,
        }
        model, _ = read_model(response([row]))

        with self.assertRaisesRegex(
            ReadinessThesisRuntimeStorageError,
            "thesis chain read returned invalid canonical state",
        ):
            model.get_chain(
                result.readiness.operator_id,
                result.readiness.security_id,
                result.readiness.thesis_contract_id,
            )

    def test_missing_chain_returns_contract_empty_chain(self) -> None:
        result = readiness_result()
        model, _ = read_model(response([]))

        loaded = model.get_chain(
            result.readiness.operator_id,
            result.readiness.security_id,
            result.readiness.thesis_contract_id,
        )

        self.assertEqual(loaded.operator_id, result.readiness.operator_id)
        self.assertEqual(loaded.security_id, result.readiness.security_id)
        self.assertEqual(
            loaded.thesis_contract_id,
            result.readiness.thesis_contract_id,
        )
        self.assertIsNone(loaded.active_canonical_thesis_version_id)
        self.assertEqual(loaded.canonical_versions, ())
        self.assertEqual(loaded.provisional_branches, ())
        self.assertEqual(
            loaded.generated_at,
            datetime(1970, 1, 1, tzinfo=UTC),
        )

    def test_rejects_duplicate_or_foreign_owner_rows(self) -> None:
        result = readiness_result()
        duplicate = readiness_row(result)
        foreign = {
            **readiness_row(result),
            "operator_id": "ffffffff-ffff-4fff-8fff-ffffffffffff",
        }
        for label, rows in {
            "duplicate": [duplicate, duplicate],
            "foreign": [foreign],
        }.items():
            with self.subTest(label=label):
                model, _ = read_model(response(rows))
                with self.assertRaisesRegex(
                    ReadinessThesisRuntimeStorageError,
                    "readiness read returned invalid canonical state",
                ):
                    model.get_readiness_by_id(
                        result.readiness.operator_id,
                        result.readiness.readiness_gate_result_id,
                    )

    def test_rejects_column_to_canonical_drift_and_unknown_fields(self) -> None:
        result = readiness_result()
        drifted = readiness_row(result)
        drifted["committee_result_id"] = (
            "ffffffff-ffff-4fff-8fff-ffffffffffff"
        )
        unknown = readiness_row(result)
        unknown["raw_provider_response"] = {"secret": "must not be accepted"}
        for label, row in {"drift": drifted, "unknown": unknown}.items():
            with self.subTest(label=label):
                model, _ = read_model(response([row]))
                with self.assertRaisesRegex(
                    ReadinessThesisRuntimeStorageError,
                    "readiness read returned invalid canonical state",
                ):
                    model.get_readiness_by_id(
                        result.readiness.operator_id,
                        result.readiness.readiness_gate_result_id,
                    )

    def test_rejects_nested_contract_drift_and_partial_result(self) -> None:
        result = readiness_result()
        canonical = deepcopy(result.readiness.as_dict())
        canonical["passed_checks"][0]["unknown"] = True
        malformed_readiness = {
            **readiness_row(result),
            "canonical_readiness": canonical,
        }
        cases = {
            "nested": (
                response([malformed_readiness]),
            ),
            "partial": (
                response([readiness_row(result)]),
                response([]),
            ),
        }
        for label, responses in cases.items():
            with self.subTest(label=label):
                model, _ = read_model(*responses)
                with self.assertRaises(
                    ReadinessThesisRuntimeStorageError
                ):
                    model.get_for_run(
                        result.readiness.operator_id,
                        result.readiness.research_run_id,
                    )

    def test_missing_direct_reads_return_none(self) -> None:
        result = readiness_result()
        model, _ = read_model(response([]), response([]))

        self.assertIsNone(
            model.get_readiness_by_id(
                result.readiness.operator_id,
                result.readiness.readiness_gate_result_id,
            )
        )
        self.assertIsNone(
            model.get_thesis_by_id(
                result.readiness.operator_id,
                result.thesis.thesis_version_id,
            )
        )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any, Mapping
import unittest

from investment_research_os.valuation_snapshots.corporate_actions import (
    MassivePersonalResearchCorporateActionAdapter,
)
from investment_research_os.valuation_snapshots.massive import (
    MassiveRequestCoordinator,
    MassiveSettings,
    MassiveValuationClient,
    MassiveValuationError,
)
from tests.test_composite_valuation_source import CapitalPortFake
from tests.test_evidence_bundle_storage import materialized_bundle
from tests.test_valuation_snapshot_workflow import SESSION, input_candidate
from workers.sec.storage import JsonResponse


class SplitTransportFake:
    def __init__(self, results: list[dict[str, object]]) -> None:
        self.results = results
        self.requests: list[tuple[str, str, Mapping[str, str]]] = []

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any] | None = None,
    ) -> JsonResponse:
        self.requests.append((method, url, headers))
        return JsonResponse(
            payload={
                "status": "OK",
                "request_id": "split-request-1",
                "results": self.results,
            },
            status=200,
            headers={},
        )


class NoopRateLimiter:
    def acquire(self) -> None:
        return None


def client(transport: SplitTransportFake) -> MassiveValuationClient:
    return MassiveValuationClient(
        MassiveSettings(api_key="test-key"),
        transport=transport,
        request_coordinator=MassiveRequestCoordinator(NoopRateLimiter()),
        clock=lambda: datetime(2026, 5, 7, 1, tzinfo=UTC),
        cache_clock=lambda: 10.0,
    )


class PersonalCorporateActionPortTests(unittest.TestCase):
    def test_empty_complete_split_window_proves_no_action_with_provenance(self) -> None:
        transport = SplitTransportFake([])
        massive = client(transport)
        adapter = MassivePersonalResearchCorporateActionAdapter(client=massive)
        bundle = materialized_bundle()
        capital = CapitalPortFake().load(bundle, SESSION).capital

        result = adapter.reconcile(
            bundle,
            SESSION,
            input_candidate().prices,
            capital,
        )
        repeated = adapter.reconcile(
            bundle,
            SESSION,
            input_candidate().prices,
            capital,
        )

        self.assertEqual(result.reconciliation.reconciliation_result, "not_required")
        self.assertEqual(result.reconciliation.action_type, "none")
        self.assertEqual(result, repeated)
        self.assertEqual(len(transport.requests), 1)
        method, url, headers = transport.requests[0]
        self.assertEqual(method, "GET")
        self.assertIn("/stocks/v1/splits?", url)
        self.assertIn("ticker=RXRX", url)
        self.assertNotIn("test-key", url)
        self.assertEqual(headers["Authorization"], "Bearer test-key")
        source = result.source_references[0]
        self.assertEqual(source.source_type, "personal_market_data")
        self.assertEqual(source.provider_contract_status, "candidate_unapproved")
        self.assertIn(
            "corporate_action_coverage_candidate",
            source.provider_limitation_codes,
        )
        self.assertEqual(len(source.response_sha256 or ""), 64)

    def test_split_after_filing_share_date_marks_basis_mismatch(self) -> None:
        massive = client(
            SplitTransportFake(
                [
                    {
                        "id": "split-rxrx-20260415",
                        "ticker": "RXRX",
                        "adjustment_type": "reverse_split",
                        "execution_date": "2026-04-15",
                        "split_from": 10,
                        "split_to": 1,
                    }
                ]
            )
        )
        adapter = MassivePersonalResearchCorporateActionAdapter(client=massive)
        bundle = materialized_bundle()
        capital = CapitalPortFake().load(bundle, SESSION).capital

        result = adapter.reconcile(
            bundle,
            SESSION,
            input_candidate().prices,
            capital,
        )

        reconciliation = result.reconciliation
        self.assertEqual(reconciliation.event_id, "split-rxrx-20260415")
        self.assertEqual(reconciliation.action_type, "reverse_split")
        self.assertEqual(reconciliation.reconciliation_result, "mismatch")
        self.assertEqual(reconciliation.share_count_adjustment_status, "indeterminate")

    def test_split_already_reflected_by_all_share_dates_is_reconciled(self) -> None:
        massive = client(
            SplitTransportFake(
                [
                    {
                        "id": "split-rxrx-20260301",
                        "ticker": "RXRX",
                        "adjustment_type": "forward_split",
                        "execution_date": "2026-03-01",
                        "split_from": 1,
                        "split_to": 2,
                    }
                ]
            )
        )
        adapter = MassivePersonalResearchCorporateActionAdapter(client=massive)
        bundle = materialized_bundle()
        capital = CapitalPortFake().load(bundle, SESSION).capital

        result = adapter.reconcile(
            bundle,
            SESSION,
            input_candidate().prices,
            replace(
                capital,
                basic_shares_effective_at=datetime(2026, 3, 31, 23, 59, tzinfo=UTC),
                fully_diluted_shares_effective_at=datetime(
                    2026, 3, 31, 23, 59, tzinfo=UTC
                ),
            ),
        )

        self.assertEqual(result.reconciliation.reconciliation_result, "reconciled")
        self.assertEqual(
            result.reconciliation.share_count_adjustment_status, "adjusted"
        )

    def test_malformed_or_incomplete_split_window_fails_closed(self) -> None:
        for payload in (
            [{"ticker": "OTHER"}],
            [
                {
                    "id": "bad-ratio",
                    "ticker": "RXRX",
                    "adjustment_type": "reverse_split",
                    "execution_date": date(2026, 4, 15).isoformat(),
                    "split_from": 1,
                    "split_to": 10,
                }
            ],
        ):
            with self.subTest(payload=payload):
                adapter = MassivePersonalResearchCorporateActionAdapter(
                    client=client(SplitTransportFake(payload))
                )
                bundle = materialized_bundle()
                capital = CapitalPortFake().load(bundle, SESSION).capital
                with self.assertRaisesRegex(
                    MassiveValuationError,
                    "Massive split",
                ):
                    adapter.reconcile(
                        bundle,
                        SESSION,
                        input_candidate().prices,
                        capital,
                    )


if __name__ == "__main__":
    unittest.main()

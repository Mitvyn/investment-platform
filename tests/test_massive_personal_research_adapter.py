from __future__ import annotations

import unittest
from datetime import UTC, date, datetime

from investment_research_os.evidence_bundles import (
    AuthenticatedOperator,
    InMemoryEvidenceBundleRepository,
)
from investment_research_os.valuation_snapshots import (
    InMemoryValuationSnapshotRepository,
    PersonalResearchValuationSnapshotWorkflow,
)
from investment_research_os.valuation_snapshots.composite import (
    PersonalResearchValuationInputSource,
)
from investment_research_os.valuation_snapshots.massive import (
    MassiveDailyCloseEvidence,
    MassivePersonalResearchCloseAdapter,
)
from tests.test_evidence_bundle_storage import materialized_bundle
from tests.test_composite_valuation_source import (
    CapitalPortFake,
    CorporateActionPortFake,
    FreshnessPortFake,
    MaterialityPortFake,
)
from tests.test_valuation_snapshot_workflow import FixedCalendar, SESSION


class FixedMassiveClient:
    def __init__(self, evidence: MassiveDailyCloseEvidence) -> None:
        self.evidence = evidence
        self.requests: list[tuple[str, date]] = []

    def fetch_daily_close(self, ticker: str, session_date: date):
        self.requests.append((ticker, session_date))
        return self.evidence


class FixedHaltVerifier:
    def __init__(self, status: str) -> None:
        self.status = status

    def verify(self, bundle, session, evidence) -> str:
        return self.status


def daily_close() -> MassiveDailyCloseEvidence:
    return MassiveDailyCloseEvidence(
        ticker="RXRX",
        session_date=SESSION.session_date,
        open="6.1",
        high="6.4",
        low="6.02",
        close="6.25",
        volume=1_234_567,
        adjustment_status="split_unadjusted",
        provider="massive_stocks_basic_candidate",
        plan_id="stocks_basic_personal",
        contract_status="candidate_unapproved",
        blocking_reason_codes=(
            "official_close_provenance_unconfirmed",
            "official_close_timestamp_unavailable",
            "historical_halt_status_unavailable",
            "corporate_action_coverage_incomplete",
            "persistence_rights_unconfirmed",
            "authenticated_display_rights_unconfirmed",
        ),
        source_reference=(
            "https://api.massive.com/v1/open-close/RXRX/2026-05-06?adjusted=false"
        ),
        request_id="massive-request-1",
        retrieved_at=datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        response_sha256="a" * 64,
    )


class MassivePersonalResearchCloseAdapterTests(unittest.TestCase):
    def test_materializes_valid_personal_snapshot_through_composite_source(
        self,
    ) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        close_adapter = MassivePersonalResearchCloseAdapter(
            client=FixedMassiveClient(daily_close()),
            halt_verifier=FixedHaltVerifier("verified_not_halted"),
        )
        source = PersonalResearchValuationInputSource(
            market_calendar=FixedCalendar(),
            close_port=close_adapter,
            capital_port=CapitalPortFake(),
            corporate_action_port=CorporateActionPortFake(),
            materiality_port=MaterialityPortFake(),
            freshness_port=FreshnessPortFake(),
        )

        snapshot = PersonalResearchValuationSnapshotWorkflow(
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=InMemoryValuationSnapshotRepository(),
            market_calendar=FixedCalendar(),
            input_source=source,
            clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
        ).materialize(AuthenticatedOperator(bundle.operator_id), bundle.id)

        self.assertEqual(snapshot.snapshot_status, "valid")
        self.assertEqual(
            snapshot.contract_version,
            "valuation_snapshot.personal_research.v2",
        )
        self.assertTrue(snapshot.market_relative_analysis_permitted)
        market_source = next(
            source
            for source in snapshot.as_dict()["source_references"]
            if source["source_type"] == "personal_market_data"
        )
        self.assertEqual(
            market_source["provider"],
            "massive_stocks_basic_candidate",
        )
        self.assertEqual(
            market_source["provider_contract_status"],
            "candidate_unapproved",
        )
        self.assertEqual(
            market_source["provider_limitation_codes"],
            list(daily_close().blocking_reason_codes),
        )

    def test_maps_candidate_bar_into_explicit_personal_research_provenance(
        self,
    ) -> None:
        bundle = materialized_bundle()
        client = FixedMassiveClient(daily_close())
        adapter = MassivePersonalResearchCloseAdapter(
            client=client,
            halt_verifier=FixedHaltVerifier("verified_not_halted"),
        )

        result = adapter.load(bundle, SESSION)

        self.assertEqual(client.requests, [("RXRX", SESSION.session_date)])
        self.assertEqual(len(result.prices), 1)
        price = result.prices[0]
        self.assertEqual(
            price.price_type,
            "verified_consolidated_end_of_day_close",
        )
        self.assertEqual(price.provider, daily_close().provider)
        market_source = result.source_references[0]
        self.assertEqual(market_source.provider, daily_close().provider)
        self.assertEqual(
            market_source.provider_contract_status,
            daily_close().contract_status,
        )
        self.assertEqual(
            market_source.provider_limitation_codes,
            daily_close().blocking_reason_codes,
        )
        self.assertEqual(price.official_close_timestamp, SESSION.closes_at)
        self.assertEqual(price.halt_verification_status, "verified_not_halted")
        source = result.source_references[0]
        self.assertEqual(source.source_type, "personal_market_data")
        self.assertEqual(source.provider_plan_id, "stocks_basic_personal")
        self.assertEqual(source.response_sha256, "a" * 64)
        self.assertIsNone(source.published_at)

    def test_indeterminate_halt_verification_remains_explicit(self) -> None:
        adapter = MassivePersonalResearchCloseAdapter(
            client=FixedMassiveClient(daily_close()),
            halt_verifier=FixedHaltVerifier("indeterminate"),
        )

        price = adapter.load(materialized_bundle(), SESSION).prices[0]

        self.assertEqual(price.market_status, "closed")
        self.assertEqual(price.halt_verification_status, "indeterminate")


if __name__ == "__main__":
    unittest.main()

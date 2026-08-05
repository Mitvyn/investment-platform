from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, date, datetime

from investment_research_os.valuation_snapshots.market_proofs import (
    NasdaqTraderHaltSearchResult,
    NasdaqTraderHistoricalHaltVerifier,
    UsEquitiesSessionDefinition,
    VersionedUsEquitiesCalendar,
)
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
    HistoricalHaltVerification,
    MassivePersonalResearchCloseAdapter,
)
from tests.test_evidence_bundle_storage import materialized_bundle
from tests.test_composite_valuation_source import (
    CapitalPortFake,
    CorporateActionPortFake,
    FreshnessPortFake,
    MaterialityPortFake,
)
from tests.test_massive_personal_research_adapter import (
    FixedMassiveClient,
    daily_close,
)
from tests.test_valuation_snapshot_workflow import SESSION


SESSIONS = (
    UsEquitiesSessionDefinition(
        session_date=date(2026, 5, 5),
        opens_at=datetime(2026, 5, 5, 13, 30, tzinfo=UTC),
        closes_at=datetime(2026, 5, 5, 20, 0, tzinfo=UTC),
    ),
    UsEquitiesSessionDefinition(
        session_date=date(2026, 5, 6),
        opens_at=datetime(2026, 5, 6, 13, 30, tzinfo=UTC),
        closes_at=datetime(2026, 5, 6, 20, 0, tzinfo=UTC),
    ),
)


class VersionedUsEquitiesCalendarTests(unittest.TestCase):
    def test_selects_latest_completed_session_from_versioned_coverage(self) -> None:
        calendar = VersionedUsEquitiesCalendar(
            calendar_version="us-equities-calendar-2026.v1",
            coverage_start=date(2026, 5, 5),
            coverage_end=date(2026, 5, 6),
            sessions=SESSIONS,
        )

        before_close = calendar.latest_completed_session(
            "NASDAQ",
            datetime(2026, 5, 6, 19, 59, tzinfo=UTC),
        )
        after_close = calendar.latest_completed_session(
            "NASDAQ",
            datetime(2026, 5, 6, 20, 0, tzinfo=UTC),
        )

        self.assertEqual(before_close.session_date, date(2026, 5, 5))
        self.assertEqual(after_close.session_date, date(2026, 5, 6))
        self.assertEqual(after_close.primary_listing_exchange, "NASDAQ")
        self.assertEqual(
            after_close.calendar_version,
            "us-equities-calendar-2026.v1",
        )

    def test_rejects_coverage_with_unclassified_calendar_date(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "market calendar coverage has unclassified dates",
        ):
            VersionedUsEquitiesCalendar(
                calendar_version="us-equities-calendar-2026.v1",
                coverage_start=date(2026, 5, 5),
                coverage_end=date(2026, 5, 7),
                sessions=SESSIONS,
            )


class HaltSearchTransportFake:
    def __init__(self, result: NasdaqTraderHaltSearchResult) -> None:
        self.result = result
        self.requests: list[tuple[str, date]] = []

    def search_halts(
        self,
        *,
        symbol: str,
        session_date: date,
    ) -> NasdaqTraderHaltSearchResult:
        self.requests.append((symbol, session_date))
        return self.result


def halt_search_result(*, rows=()) -> NasdaqTraderHaltSearchResult:
    return NasdaqTraderHaltSearchResult(
        query_symbol="RXRX",
        query_session_date=SESSION.session_date,
        records=rows,
        complete=True,
        source_version="nasdaq-trader-halt-search.v2",
        source_locator="https://www.nasdaqtrader.com/Trader.aspx?id=TradingHaltSearch",
        retrieved_at=datetime(2026, 5, 7, 1, 0, tzinfo=UTC),
        response_sha256="b" * 64,
    )


class NasdaqTraderHistoricalHaltVerifierTests(unittest.TestCase):
    def test_complete_empty_search_verifies_not_halted_and_reuses_query(self) -> None:
        transport = HaltSearchTransportFake(halt_search_result())
        verifier = NasdaqTraderHistoricalHaltVerifier(
            transport=transport,
            source_version="nasdaq-trader-halt-search.v2",
            coverage_start=date(2026, 1, 1),
            coverage_end=date(2026, 12, 31),
        )
        bundle = materialized_bundle()
        evidence = daily_close()

        first = verifier.verify(bundle, SESSION, evidence)
        second = verifier.verify(bundle, SESSION, evidence)

        self.assertIsInstance(first, HistoricalHaltVerification)
        self.assertEqual(first.status, "verified_not_halted")
        self.assertEqual(second, first)
        self.assertEqual(first.source_reference.provider, "nasdaq_trader")
        self.assertEqual(
            first.source_reference.response_sha256,
            "b" * 64,
        )
        self.assertEqual(transport.requests, [("RXRX", SESSION.session_date)])

    def test_active_halt_at_cutoff_is_halted(self) -> None:
        transport = HaltSearchTransportFake(
            halt_search_result(
                rows=(
                    {
                        "record_id": "halt-1",
                        "symbol": "RXRX",
                        "market": "NASDAQ",
                        "halted_at": "2026-05-06T19:30:00+00:00",
                        "resumed_at": None,
                        "reason_code": "T1",
                    },
                )
            )
        )
        verifier = NasdaqTraderHistoricalHaltVerifier(
            transport=transport,
            source_version="nasdaq-trader-halt-search.v2",
            coverage_start=date(2026, 1, 1),
            coverage_end=date(2026, 12, 31),
        )

        status = verifier.verify(materialized_bundle(), SESSION, daily_close())

        self.assertEqual(status.status, "halted")

    def test_resumed_halt_before_cutoff_verifies_not_halted(self) -> None:
        transport = HaltSearchTransportFake(
            halt_search_result(
                rows=(
                    {
                        "record_id": "halt-1",
                        "symbol": "RXRX",
                        "market": "NASDAQ",
                        "halted_at": "2026-05-06T19:30:00+00:00",
                        "resumed_at": "2026-05-06T20:30:00+00:00",
                        "reason_code": "T1",
                    },
                )
            )
        )
        verifier = NasdaqTraderHistoricalHaltVerifier(
            transport=transport,
            source_version="nasdaq-trader-halt-search.v2",
            coverage_start=date(2026, 1, 1),
            coverage_end=date(2026, 12, 31),
        )

        status = verifier.verify(materialized_bundle(), SESSION, daily_close())

        self.assertEqual(status.status, "verified_not_halted")

    def test_malformed_or_incomplete_search_is_indeterminate(self) -> None:
        malformed = halt_search_result(
            rows=(
                {
                    "record_id": "halt-1",
                    "symbol": "RXRX",
                    "market": "NASDAQ",
                    "halted_at": "2026-05-06",
                    "resumed_at": None,
                    "reason_code": "T1",
                },
            )
        )
        incomplete = replace(halt_search_result(), complete=False)

        for result in (malformed, incomplete):
            with self.subTest(result=result):
                status = NasdaqTraderHistoricalHaltVerifier(
                    transport=HaltSearchTransportFake(result),
                    source_version="nasdaq-trader-halt-search.v2",
                    coverage_start=date(2026, 1, 1),
                    coverage_end=date(2026, 12, 31),
                ).verify(materialized_bundle(), SESSION, daily_close())
                self.assertEqual(status.status, "indeterminate")

    def test_outside_proven_market_or_date_is_indeterminate_without_query(
        self,
    ) -> None:
        transport = HaltSearchTransportFake(halt_search_result())
        verifier = NasdaqTraderHistoricalHaltVerifier(
            transport=transport,
            source_version="nasdaq-trader-halt-search.v2",
            coverage_start=date(2026, 5, 6),
            coverage_end=date(2026, 5, 6),
        )

        unsupported_market = verifier.verify(
            materialized_bundle(),
            replace(SESSION, primary_listing_exchange="OTC"),
            daily_close(),
        )
        unsupported_date = verifier.verify(
            materialized_bundle(),
            replace(SESSION, session_date=date(2026, 5, 5)),
            replace(daily_close(), session_date=date(2026, 5, 5)),
        )

        self.assertEqual(unsupported_market, "indeterminate")
        self.assertEqual(unsupported_date, "indeterminate")
        self.assertEqual(transport.requests, [])

    def test_close_adapter_preserves_halt_proof_and_blocks_active_halt(self) -> None:
        transport = HaltSearchTransportFake(
            halt_search_result(
                rows=(
                    {
                        "record_id": "halt-1",
                        "symbol": "RXRX",
                        "market": "NASDAQ",
                        "halted_at": "2026-05-06T19:30:00+00:00",
                        "resumed_at": None,
                        "reason_code": "T1",
                    },
                )
            )
        )
        verifier = NasdaqTraderHistoricalHaltVerifier(
            transport=transport,
            source_version="nasdaq-trader-halt-search.v2",
            coverage_start=date(2026, 1, 1),
            coverage_end=date(2026, 12, 31),
        )

        result = MassivePersonalResearchCloseAdapter(
            client=FixedMassiveClient(daily_close()),
            halt_verifier=verifier,
        ).load(materialized_bundle(), SESSION)

        self.assertEqual(result.prices[0].market_status, "halted")
        self.assertEqual(result.prices[0].halt_verification_status, "halted")
        self.assertEqual(len(result.source_references), 2)
        self.assertEqual(result.source_references[1].provider, "nasdaq_trader")

    def test_cached_search_recomputes_status_for_each_cutoff(self) -> None:
        transport = HaltSearchTransportFake(
            halt_search_result(
                rows=(
                    {
                        "record_id": "halt-1",
                        "symbol": "RXRX",
                        "market": "NASDAQ",
                        "halted_at": "2026-05-06T19:30:00+00:00",
                        "resumed_at": None,
                        "reason_code": "T1",
                    },
                )
            )
        )
        verifier = NasdaqTraderHistoricalHaltVerifier(
            transport=transport,
            source_version="nasdaq-trader-halt-search.v2",
            coverage_start=date(2026, 1, 1),
            coverage_end=date(2026, 12, 31),
        )
        bundle = materialized_bundle()

        before_halt = verifier.verify(
            replace(
                bundle,
                as_of_cutoff=datetime(2026, 5, 6, 19, 0, tzinfo=UTC),
            ),
            SESSION,
            daily_close(),
        )
        during_halt = verifier.verify(bundle, SESSION, daily_close())

        self.assertEqual(before_halt.status, "verified_not_halted")
        self.assertEqual(during_halt.status, "halted")
        self.assertEqual(transport.requests, [("RXRX", SESSION.session_date)])

    def test_active_halt_makes_personal_valuation_snapshot_invalid(self) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        calendar = VersionedUsEquitiesCalendar(
            calendar_version="us-equities-calendar-v1",
            coverage_start=SESSION.session_date,
            coverage_end=SESSION.session_date,
            sessions=(
                UsEquitiesSessionDefinition(
                    session_date=SESSION.session_date,
                    opens_at=SESSION.opens_at,
                    closes_at=SESSION.closes_at,
                ),
            ),
        )
        halt_transport = HaltSearchTransportFake(
            halt_search_result(
                rows=(
                    {
                        "record_id": "halt-1",
                        "symbol": "RXRX",
                        "market": "NASDAQ",
                        "halted_at": "2026-05-06T19:30:00+00:00",
                        "resumed_at": None,
                        "reason_code": "T1",
                    },
                )
            )
        )
        source = PersonalResearchValuationInputSource(
            market_calendar=calendar,
            close_port=MassivePersonalResearchCloseAdapter(
                client=FixedMassiveClient(daily_close()),
                halt_verifier=NasdaqTraderHistoricalHaltVerifier(
                    transport=halt_transport,
                    source_version="nasdaq-trader-halt-search.v2",
                    coverage_start=SESSION.session_date,
                    coverage_end=SESSION.session_date,
                ),
            ),
            capital_port=CapitalPortFake(),
            corporate_action_port=CorporateActionPortFake(),
            materiality_port=MaterialityPortFake(),
            freshness_port=FreshnessPortFake(),
        )

        snapshot = PersonalResearchValuationSnapshotWorkflow(
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=InMemoryValuationSnapshotRepository(),
            market_calendar=calendar,
            input_source=source,
            clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
        ).materialize(AuthenticatedOperator(bundle.operator_id), bundle.id)

        self.assertEqual(snapshot.snapshot_status, "invalid")
        self.assertEqual(snapshot.invalid_reason_codes, ("market_halted",))
        self.assertFalse(snapshot.market_relative_analysis_permitted)
        self.assertEqual(
            {source.provider for source in snapshot.source_references},
            {"massive_stocks_basic_candidate", "nasdaq_trader", "SEC"},
        )


if __name__ == "__main__":
    unittest.main()

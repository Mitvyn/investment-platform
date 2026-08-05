from __future__ import annotations

import unittest
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from investment_research_os.evidence_bundles import (
    AuthenticatedOperator,
    InMemoryEvidenceBundleRepository,
)
from investment_research_os.valuation_snapshots import (
    InMemoryValuationSnapshotRepository,
    ValuationSnapshotError,
    ValuationSnapshotWorkflow,
)
from investment_research_os.valuation_snapshots.composite import (
    ApprovedValuationSource,
    CapitalInput,
    CompositeValuationInputSource,
    FreshnessInput,
    MaterialityInput,
    OfficialCloseInput,
)
from tests.test_evidence_bundle_storage import materialized_bundle
from tests.test_valuation_snapshot_workflow import (
    FixedCalendar,
    SESSION,
    input_candidate,
)


CHECKED_AT = datetime(2026, 5, 7, 1, 30, tzinfo=UTC)


@dataclass
class ApprovalPortFake:
    approval: ApprovedValuationSource

    def current_approval(self, bundle, session):
        return self.approval


class OfficialClosePortFake:
    def __init__(
        self,
        *,
        market_status: str = "closed",
        provider: str = "licensed-market-fake",
    ) -> None:
        self.requests = []
        self.market_status = market_status
        self.provider = provider

    def load(self, bundle, session):
        self.requests.append((bundle, session))
        candidate = input_candidate()
        return OfficialCloseInput(
            prices=(
                replace(
                    candidate.prices[0],
                    market_status=self.market_status,
                    provider=self.provider,
                ),
            ),
            source_references=(candidate.source_references[0],),
        )


class CapitalPortFake:
    def __init__(self) -> None:
        self.requests = []

    def load(self, bundle, session):
        self.requests.append((bundle, session))
        candidate = input_candidate()
        return CapitalInput(
            capital=candidate.capital,
            source_references=(candidate.source_references[1],),
        )


class CorporateActionPortFake:
    def __init__(self, *, reconciliation_result: str = "not_required") -> None:
        self.reconciliation_result = reconciliation_result

    def reconcile(self, bundle, session, prices, capital):
        return replace(
            input_candidate().corporate_action,
            reconciliation_result=self.reconciliation_result,
        )


class MaterialityPortFake:
    def __init__(self) -> None:
        self.requests = []

    def assess(self, bundle, session):
        self.requests.append((bundle, session))
        candidate = input_candidate()
        return MaterialityInput(
            assessments=candidate.materiality_assessments,
            policy_version=candidate.materiality_policy_version,
        )


class FreshnessPortFake:
    def assess(self, bundle, session, capital):
        return FreshnessInput(
            capital=capital,
            policy_version=capital.freshness_policy_version,
        )


def approval() -> ApprovedValuationSource:
    return ApprovedValuationSource(
        approval_id="licensed-market-fake-v1",
        provider_id="licensed-market-fake",
        contract_status="approved",
        active=True,
        effective_from=datetime(2026, 5, 1, tzinfo=UTC),
        expires_at=datetime(2026, 6, 1, tzinfo=UTC),
        granted_rights=(
            "persist_official_close_evidence",
            "authenticated_dashboard_display",
        ),
    )


def approved_source(
    calendar: FixedCalendar,
    *,
    source_approval: ApprovedValuationSource | None = None,
    official_close_port: OfficialClosePortFake | None = None,
    capital_port: CapitalPortFake | None = None,
    corporate_action_port: CorporateActionPortFake | None = None,
    materiality_port: MaterialityPortFake | None = None,
) -> CompositeValuationInputSource:
    return CompositeValuationInputSource(
        provider_id="licensed-market-fake",
        approval_port=ApprovalPortFake(source_approval or approval()),
        market_calendar=calendar,
        official_close_port=official_close_port or OfficialClosePortFake(),
        capital_port=capital_port or CapitalPortFake(),
        corporate_action_port=corporate_action_port or CorporateActionPortFake(),
        materiality_port=materiality_port or MaterialityPortFake(),
        freshness_port=FreshnessPortFake(),
        valuation_policy_version="biotech-valuation-snapshot-v1",
        clock=lambda: CHECKED_AT,
    )


class CompositeValuationInputSourceTests(unittest.TestCase):
    def test_approved_complete_composite_candidate_is_accepted_by_workflow(
        self,
    ) -> None:
        bundle = materialized_bundle()
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle_repository.save(bundle)
        calendar = FixedCalendar()
        workflow = ValuationSnapshotWorkflow(
            evidence_bundle_repository=bundle_repository,
            valuation_snapshot_repository=InMemoryValuationSnapshotRepository(),
            market_calendar=calendar,
            input_source=approved_source(calendar),
            clock=lambda: datetime(2026, 5, 7, 2, 0, tzinfo=UTC),
        )

        snapshot = workflow.materialize(
            AuthenticatedOperator(bundle.operator_id),
            bundle.id,
        )

        self.assertEqual(snapshot.snapshot_status, "valid")
        self.assertEqual(snapshot.evidence_bundle_hash, bundle.content_hash)
        self.assertEqual(snapshot.session, SESSION)
        self.assertEqual(snapshot.price.provider, "licensed-market-fake")
        self.assertEqual(snapshot.capital, input_candidate().capital)

    def test_inactive_approval_fails_before_official_close_boundary(self) -> None:
        bundle = materialized_bundle()
        official_close = OfficialClosePortFake()
        source = approved_source(
            FixedCalendar(),
            source_approval=replace(approval(), active=False),
            official_close_port=official_close,
        )

        with self.assertRaisesRegex(
            ValuationSnapshotError,
            "valuation source approval is inactive",
        ):
            source.load(bundle, SESSION)

        self.assertEqual(official_close.requests, [])

    def test_halted_close_fails_before_capital_boundary(self) -> None:
        bundle = materialized_bundle()
        capital = CapitalPortFake()
        source = approved_source(
            FixedCalendar(),
            official_close_port=OfficialClosePortFake(market_status="halted"),
            capital_port=capital,
        )

        with self.assertRaisesRegex(
            ValuationSnapshotError,
            "official close is not market-clearing",
        ):
            source.load(bundle, SESSION)

        self.assertEqual(capital.requests, [])

    def test_unapproved_close_provider_fails_before_capital_boundary(self) -> None:
        bundle = materialized_bundle()
        capital = CapitalPortFake()
        source = approved_source(
            FixedCalendar(),
            official_close_port=OfficialClosePortFake(
                provider="massive_stocks_basic_candidate",
            ),
            capital_port=capital,
        )

        with self.assertRaisesRegex(
            ValuationSnapshotError,
            "official close provider is not approved",
        ):
            source.load(bundle, SESSION)

        self.assertEqual(capital.requests, [])

    def test_expired_approval_fails_before_official_close_boundary(self) -> None:
        bundle = materialized_bundle()
        official_close = OfficialClosePortFake()
        source = approved_source(
            FixedCalendar(),
            source_approval=replace(approval(), expires_at=CHECKED_AT),
            official_close_port=official_close,
        )

        with self.assertRaisesRegex(
            ValuationSnapshotError,
            "valuation source approval is expired",
        ):
            source.load(bundle, SESSION)

        self.assertEqual(official_close.requests, [])

    def test_future_approval_fails_before_official_close_boundary(self) -> None:
        bundle = materialized_bundle()
        official_close = OfficialClosePortFake()
        source = approved_source(
            FixedCalendar(),
            source_approval=replace(
                approval(),
                effective_from=datetime(2026, 5, 8, tzinfo=UTC),
            ),
            official_close_port=official_close,
        )

        with self.assertRaisesRegex(
            ValuationSnapshotError,
            "valuation source approval is not yet effective",
        ):
            source.load(bundle, SESSION)

        self.assertEqual(official_close.requests, [])

    def test_approval_rejects_invalid_effective_window(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "valuation source approval window is invalid",
        ):
            replace(
                approval(),
                expires_at=datetime(2026, 5, 1, tzinfo=UTC),
            )

    def test_candidate_unapproved_source_fails_before_official_close_boundary(
        self,
    ) -> None:
        bundle = materialized_bundle()
        official_close = OfficialClosePortFake()
        source = approved_source(
            FixedCalendar(),
            source_approval=replace(
                approval(),
                provider_id="massive_stocks_basic_candidate",
                contract_status="candidate_unapproved",
            ),
            official_close_port=official_close,
        )

        with self.assertRaisesRegex(
            ValuationSnapshotError,
            "valuation source contract is not approved",
        ):
            source.load(bundle, SESSION)

        self.assertEqual(official_close.requests, [])

    def test_approval_for_different_provider_fails_before_official_close_boundary(
        self,
    ) -> None:
        bundle = materialized_bundle()
        official_close = OfficialClosePortFake()
        source = approved_source(
            FixedCalendar(),
            source_approval=replace(
                approval(),
                provider_id="different-market-provider",
            ),
            official_close_port=official_close,
        )

        with self.assertRaisesRegex(
            ValuationSnapshotError,
            "valuation source contract is not approved",
        ):
            source.load(bundle, SESSION)

        self.assertEqual(official_close.requests, [])

    def test_missing_usage_rights_fail_before_official_close_boundary(
        self,
    ) -> None:
        bundle = materialized_bundle()
        official_close = OfficialClosePortFake()
        source = approved_source(
            FixedCalendar(),
            source_approval=replace(
                approval(),
                granted_rights=("persist_official_close_evidence",),
            ),
            official_close_port=official_close,
        )

        with self.assertRaisesRegex(
            ValuationSnapshotError,
            "valuation source rights are incomplete",
        ):
            source.load(bundle, SESSION)

        self.assertEqual(official_close.requests, [])

    def test_bundle_session_drift_fails_before_official_close_boundary(
        self,
    ) -> None:
        bundle = materialized_bundle()
        official_close = OfficialClosePortFake()
        source = approved_source(
            FixedCalendar(
                replace(
                    SESSION,
                    closes_at=datetime(2026, 5, 6, 20, 1, tzinfo=UTC),
                )
            ),
            official_close_port=official_close,
        )

        with self.assertRaisesRegex(
            ValuationSnapshotError,
            "valuation source session does not match frozen bundle cutoff",
        ):
            source.load(bundle, SESSION)

        self.assertEqual(official_close.requests, [])

    def test_corporate_action_mismatch_fails_before_materiality_boundary(
        self,
    ) -> None:
        bundle = materialized_bundle()
        materiality = MaterialityPortFake()
        source = approved_source(
            FixedCalendar(),
            corporate_action_port=CorporateActionPortFake(
                reconciliation_result="mismatch",
            ),
            materiality_port=materiality,
        )

        with self.assertRaisesRegex(
            ValuationSnapshotError,
            "corporate action basis is not reconciled",
        ):
            source.load(bundle, SESSION)

        self.assertEqual(materiality.requests, [])


if __name__ == "__main__":
    unittest.main()

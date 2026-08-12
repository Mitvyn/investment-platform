from __future__ import annotations

import json
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime

from investment_research_os.evidence_bundles import (
    AuthenticatedOperator,
    EvidenceGap,
    InMemoryEvidenceBundleRepository,
    VerifiedMetricSnapshot,
)
from investment_research_os.valuation_snapshots import (
    InMemoryValuationSnapshotRepository,
    PersonalResearchValuationSnapshotWorkflow,
    ValuationSnapshotError,
)
from investment_research_os.valuation_snapshots.capital import (
    FrozenEvidenceCapitalPort,
    FrozenEvidenceCapitalFreshnessPort,
)
from investment_research_os.valuation_snapshots.composite import (
    PersonalResearchValuationInputSource,
)
from investment_research_os.valuation_snapshots.massive import (
    MassivePersonalResearchCloseAdapter,
)
from tests.test_composite_valuation_source import (
    CorporateActionPortFake,
    MaterialityPortFake,
)
from tests.test_evidence_bundle_storage import materialized_bundle
from tests.test_massive_personal_research_adapter import (
    FixedHaltVerifier,
    FixedMassiveClient,
    daily_close,
)
from tests.test_valuation_snapshot_workflow import FixedCalendar, SESSION


REPORT_DATE = date(2026, 3, 31)


def metric(
    bundle,
    key: str,
    value: str,
    unit: str,
    calculation_method: str = "reported",
    formula: str | None = None,
) -> VerifiedMetricSnapshot:
    support = bundle.manifest[0]
    return VerifiedMetricSnapshot(
        snapshot_id=f"metric-{key}",
        metric_key=key,
        value=value,
        unit=unit,
        period_start=None,
        period_end=REPORT_DATE,
        calculation_method=calculation_method,
        formula=formula,
        supporting_evidence_ids=(support.evidence_id,),
    )


def complete_bundle():
    bundle = materialized_bundle()
    values = (
        ("basic_shares_outstanding", "100000000", "shares"),
        ("option_shares_outstanding", "10000000", "shares"),
        ("warrant_shares_outstanding", "2000000", "shares"),
        ("convertible_share_equivalents", "3000000", "shares"),
        ("rsu_shares_outstanding", "4000000", "shares"),
        ("preferred_shares_outstanding", "1000000", "shares"),
        ("cash_and_cash_equivalents", "80000000", "USD"),
        ("restricted_cash", "5000000", "USD"),
        ("debt_total", "20000000", "USD"),
        (
            "other_enterprise_claims",
            "7000000",
            "USD",
            "derived",
            "sum(other_enterprise_claim_components)",
        ),
        *tuple(
            (
                f"other_enterprise_claim:{component_id}",
                value,
                "USD",
                "derived",
                json.dumps(
                    {
                        "policy_version": "biotech-other-enterprise-claims-v1",
                        "reason_code": (
                            "other_claims_value_reported"
                            if value != "0"
                            else "other_claims_zero_tagged"
                        ),
                        "resolution": "reported" if value != "0" else "tagged_zero",
                        "source_concept": f"us-gaap:{component_id}",
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
            for component_id, value in (
                ("redeemable_preferred_claim", "0"),
                ("noncontrolling_interest_claim", "7000000"),
                ("royalty_monetization_liability", "0"),
                ("contingent_consideration_claim", "0"),
                ("pension_underfunded_claim", "0"),
                ("finance_lease_claim", "0"),
            )
        ),
    )
    return replace(
        bundle,
        metrics=tuple(metric(bundle, *definition) for definition in values),
        grader_ready=True,
        gaps=(),
    )


class FrozenEvidenceCapitalPortTests(unittest.TestCase):
    def test_rejects_claim_resolution_metadata_not_emitted_by_resolver(self) -> None:
        bundle = complete_bundle()
        target_key = "other_enterprise_claim:redeemable_preferred_claim"
        forged = tuple(
            replace(
                item,
                formula=json.dumps(
                    {
                        "policy_version": "biotech-other-enterprise-claims-v1",
                        "reason_code": "made_up_zero_reason",
                        "resolution": "tagged_zero",
                        "source_concept": None,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
            if item.metric_key == target_key
            else item
            for item in bundle.metrics
        )

        with self.assertRaisesRegex(
            ValuationSnapshotError,
            "other enterprise claim component resolution invalid",
        ):
            FrozenEvidenceCapitalPort().load(
                replace(bundle, metrics=forged),
                SESSION,
            )

    def test_rejects_claim_aggregate_evidence_not_equal_to_component_union(
        self,
    ) -> None:
        bundle = complete_bundle()
        aggregate = next(
            item
            for item in bundle.metrics
            if item.metric_key == "other_enterprise_claims"
        )
        primary_support = bundle.manifest[0]
        secondary_support = replace(
            bundle.manifest[1],
            source_class="sec",
            canonical_url="https://www.sec.gov/Archives/example/rxrx-note.htm",
        )
        bundle = replace(
            bundle,
            manifest=(primary_support, secondary_support, *bundle.manifest[2:]),
        )
        forged = tuple(
            replace(
                aggregate,
                supporting_evidence_ids=(secondary_support.evidence_id,),
            )
            if item is aggregate
            else item
            for item in bundle.metrics
        )

        with self.assertRaisesRegex(
            ValuationSnapshotError,
            "other enterprise claim evidence mismatch",
        ):
            FrozenEvidenceCapitalPort().load(
                replace(bundle, metrics=forged),
                SESSION,
            )

    def test_reconstructs_complete_capital_from_frozen_primary_filing_metrics(
        self,
    ) -> None:
        bundle = complete_bundle()

        loaded = FrozenEvidenceCapitalPort().load(bundle, SESSION)

        capital = loaded.capital
        self.assertEqual(capital.basic_shares_outstanding, "100000000")
        self.assertEqual(capital.fully_diluted_shares, "120000000")
        self.assertEqual(capital.cash, "80000000")
        self.assertEqual(capital.restricted_cash, "5000000")
        self.assertEqual(capital.restricted_cash_treatment, "excluded")
        self.assertEqual(capital.included_cash, "75000000")
        self.assertEqual(capital.debt, "20000000")
        self.assertEqual(capital.other_enterprise_claims, "7000000")
        self.assertEqual(len(capital.other_enterprise_claim_components), 6)
        self.assertEqual(
            tuple(
                (item.instrument_type, item.diluted_share_increment)
                for item in capital.dilution_instruments
            ),
            (
                ("stock_options", "10000000"),
                ("warrants", "2000000"),
                ("convertibles", "3000000"),
                ("restricted_stock_units", "4000000"),
                ("preferred_securities", "1000000"),
            ),
        )
        self.assertEqual(
            capital.fully_diluted_shares_effective_at.isoformat(),
            "2026-03-31T23:59:59+00:00",
        )
        self.assertEqual(
            capital.diluted_shares_evidence_ids,
            (bundle.manifest[0].evidence_id,),
        )
        self.assertEqual(
            capital.freshness_policy_version, "biotech-valuation-freshness-v1"
        )
        self.assertEqual(len(loaded.source_references), 1)
        self.assertEqual(loaded.source_references[0].source_type, "primary_filing")
        self.assertEqual(loaded.source_references[0].provider, "sec")

    def test_rejects_missing_required_capital_metric_with_exact_gap_code(
        self,
    ) -> None:
        bundle = complete_bundle()
        bundle = replace(
            bundle,
            metrics=tuple(
                metric
                for metric in bundle.metrics
                if metric.metric_key != "restricted_cash"
            ),
        )

        with self.assertRaisesRegex(
            ValueError,
            "^capital_metric_missing:restricted_cash$",
        ):
            FrozenEvidenceCapitalPort().load(bundle, SESSION)

    def test_rejects_stale_primary_filing_support(self) -> None:
        bundle = complete_bundle()
        support_id = bundle.manifest[0].evidence_id
        bundle = replace(
            bundle,
            manifest=(
                replace(bundle.manifest[0], freshness="stale"),
                *bundle.manifest[1:],
            ),
        )

        with self.assertRaisesRegex(
            ValueError,
            f"^capital_evidence_stale:{support_id}$",
        ):
            FrozenEvidenceCapitalPort().load(bundle, SESSION)

    def test_rejects_primary_filing_support_effective_after_cutoff(self) -> None:
        bundle = complete_bundle()
        support_id = bundle.manifest[0].evidence_id
        bundle = replace(
            bundle,
            manifest=(
                replace(
                    bundle.manifest[0],
                    effective_at=datetime(2026, 5, 8, tzinfo=UTC),
                ),
                *bundle.manifest[1:],
            ),
        )

        with self.assertRaisesRegex(
            ValueError,
            f"^capital_evidence_effective_after_cutoff:{support_id}$",
        ):
            FrozenEvidenceCapitalPort().load(bundle, SESSION)

    def test_rejects_metric_supported_only_by_non_filing_source(self) -> None:
        bundle = complete_bundle()
        support_id = bundle.manifest[0].evidence_id
        bundle = replace(
            bundle,
            manifest=(
                replace(
                    bundle.manifest[0],
                    source_class="issuer",
                    canonical_url="https://issuer.example.com/release",
                ),
                *bundle.manifest[1:],
            ),
        )

        with self.assertRaisesRegex(
            ValueError,
            f"^capital_evidence_not_primary_filing:{support_id}$",
        ):
            FrozenEvidenceCapitalPort().load(bundle, SESSION)

    def test_rejects_bundle_with_blocking_capital_gap(self) -> None:
        bundle = complete_bundle()
        bundle = replace(
            bundle,
            grader_ready=False,
            gaps=(
                EvidenceGap(
                    code="missing_warrant_semantics",
                    source_class="financing",
                    blocking=True,
                    explanation="Warrant share treatment is unresolved.",
                    requirement_id="warrant_shares_outstanding",
                    reason_code="capital_metric_indeterminate",
                ),
            ),
        )

        with self.assertRaisesRegex(
            ValueError,
            "^capital_evidence_bundle_not_ready$",
        ):
            FrozenEvidenceCapitalPort().load(bundle, SESSION)

    def test_flows_into_personal_snapshot_with_deterministic_formulas(self) -> None:
        bundle = complete_bundle()
        bundles = InMemoryEvidenceBundleRepository()
        bundles.save(bundle)
        source = PersonalResearchValuationInputSource(
            market_calendar=FixedCalendar(),
            close_port=MassivePersonalResearchCloseAdapter(
                client=FixedMassiveClient(daily_close()),
                halt_verifier=FixedHaltVerifier("verified_not_halted"),
            ),
            capital_port=FrozenEvidenceCapitalPort(),
            corporate_action_port=CorporateActionPortFake(),
            materiality_port=MaterialityPortFake(),
            freshness_port=FrozenEvidenceCapitalFreshnessPort(),
        )

        snapshot = PersonalResearchValuationSnapshotWorkflow(
            evidence_bundle_repository=bundles,
            valuation_snapshot_repository=InMemoryValuationSnapshotRepository(),
            market_calendar=FixedCalendar(),
            input_source=source,
            clock=lambda: datetime(2026, 5, 7, 2, tzinfo=UTC),
        ).materialize(AuthenticatedOperator(bundle.operator_id), bundle.id)

        wire = snapshot.as_dict()
        self.assertEqual(wire["snapshot_status"], "valid")
        self.assertEqual(
            wire["fully_diluted_shares"]["formula"],
            "basic shares outstanding + dilution instruments",
        )
        self.assertEqual(
            wire["market_capitalization"]["formula"],
            "share_price * fully_diluted_shares",
        )
        self.assertEqual(
            wire["enterprise_value"]["formula"],
            "market_capitalization + debt + other_enterprise_claims - included_cash",
        )
        self.assertIn(
            bundle.manifest[0].evidence_id,
            wire["enterprise_value"]["supporting_evidence_ids"],
        )

    def test_freshness_port_rejects_downgraded_capital_state(self) -> None:
        bundle = complete_bundle()
        loaded = FrozenEvidenceCapitalPort().load(bundle, SESSION)

        with self.assertRaisesRegex(
            ValueError,
            "^capital_freshness_not_current$",
        ):
            FrozenEvidenceCapitalFreshnessPort().assess(
                bundle,
                SESSION,
                replace(loaded.capital, cash_freshness_state="stale"),
            )


if __name__ == "__main__":
    unittest.main()

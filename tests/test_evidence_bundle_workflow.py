from __future__ import annotations

import hashlib
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime

from investment_research_os.evidence_bundles import (
    CatalystSnapshot,
    EvidenceBundleCandidate,
    EvidenceBundleWorkflow,
    EvidenceItem,
    EvidencePolicyDefinition,
    FixedEvidencePolicyRegistry,
    InMemoryEvidenceBundleRepository,
    RiskSnapshot,
    VerifiedMetricSnapshot,
)
from investment_research_os.research_runs import (
    AuthenticatedOperator,
    EligibilityCheck,
    EligibilityResult,
    InMemoryResearchRunRepository,
    ResearchRun,
    SecurityIdentity,
)


OPERATOR_ID = "8ed47ebc-d5cf-40ad-80ce-d4d803f7c735"
SECURITY_ID = "f594edb2-7fff-4e40-9c26-2c06bcbecb91"
RUN_ID = "23624bca-9352-50c9-b94d-5651877148f7"
CUTOFF = datetime(2026, 5, 6, 23, 59, 59, tzinfo=UTC)
CREATED_AT = datetime(2026, 5, 7, 1, 0, tzinfo=UTC)


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def eligible_run() -> ResearchRun:
    rule_ids = (
        "security_identity_verified",
        "us_listing",
        "cik_match",
        "common_equity",
        "operating_company",
        "therapeutics_classification",
        "active_therapeutic_program",
        "defined_clinical_or_regulatory_catalyst",
        "required_primary_source_coverage",
    )
    checks = tuple(
        EligibilityCheck(
            rule_id=rule_id,
            rule_version=f"{rule_id}.v1",
            passed=True,
            evidence_reference=f"evidence-{rule_id}",
            reason_code="eligible",
            explanation="Rule passed using evidence valid at cutoff.",
            evaluated_at=CREATED_AT,
        )
        for rule_id in rule_ids
    )
    return ResearchRun(
        id=RUN_ID,
        operator_id=OPERATOR_ID,
        security_id=SECURITY_ID,
        security_identity=SecurityIdentity(
            id=SECURITY_ID,
            cik="0001601830",
            issuer_name="Recursion Pharmaceuticals, Inc.",
            symbol="RXRX",
            primary_listing_exchange="NASDAQ",
        ),
        question_type="biotech_moonshot_catalyst_assessment",
        question_type_version="biotech_moonshot_catalyst_assessment.v1",
        workflow_config_version="biotech-moonshot-catalyst-v1",
        thesis_contract_id="biotech_moonshot_catalyst_assessment",
        as_of_cutoff=CUTOFF,
        operator_focus_original=None,
        operator_focus_normalized=None,
        status="eligibility_evaluated",
        idempotency_key=sha256("research-run"),
        eligibility=EligibilityResult(
            policy_version="biotech-security-eligibility-v1",
            eligible=True,
            checks=checks,
            evaluated_at=CREATED_AT,
        ),
        created_at=CREATED_AT,
    )


def sec_item() -> EvidenceItem:
    return EvidenceItem(
        evidence_id="c72e8a02-c5a6-5b05-af51-d6bd2d08ce55",
        evidence_version_id="b8c08fc2-8505-5d71-9926-d15d66302181",
        provenance_type="primary_source",
        item_kind="passage",
        source_class="sec",
        source_locator="2026 Q1 10-Q, liquidity section",
        canonical_url="https://www.sec.gov/Archives/example/rxrx-20260331.htm",
        publication_at=datetime(2026, 5, 6, 20, 0, tzinfo=UTC),
        retrieved_at=datetime(2026, 5, 7, 0, 15, tzinfo=UTC),
        effective_at=datetime(2026, 3, 31, 0, 0, tzinfo=UTC),
        filing_period_start=date(2026, 1, 1),
        filing_period_end=date(2026, 3, 31),
        content_hash=sha256("filing document"),
        passage_id="61a33483-692e-5080-9b58-f3f994c5326f",
        passage_hash=sha256("exact liquidity passage"),
        freshness="current",
    )


def required_source_items() -> tuple[EvidenceItem, ...]:
    source_data = (
        (
            "issuer",
            "5d4f281d-a86b-5299-a44d-528be11ac9aa",
            "2c53103a-8583-5145-9829-5601146a344c",
        ),
        (
            "clinical",
            "cd8fd063-1062-50cf-afae-990646ca4ff9",
            "307e86eb-c24d-5659-aa3b-028eebc03ef1",
        ),
        (
            "regulatory",
            "5a39958e-9739-5f23-9bee-91b710114997",
            "bc2aa277-21b0-5385-a9ae-2558fe3bcd0e",
        ),
        (
            "financing",
            "635e63a1-ed42-540c-99cd-114aacb0ef51",
            "18018743-65e5-5d0f-b0f3-a4b6db2d8e6e",
        ),
    )
    return (
        sec_item(),
        *(
            replace(
                sec_item(),
                evidence_id=evidence_id,
                evidence_version_id=version_id,
                source_class=source_class,
                source_locator=f"{source_class} primary record",
                canonical_url=f"https://example.com/{source_class}/record",
                content_hash=sha256(f"{source_class} document"),
                passage_id=None,
                passage_hash=None,
            )
            for source_class, evidence_id, version_id in source_data
        ),
    )


class FixedBundleSource:
    def __init__(self, candidate: EvidenceBundleCandidate) -> None:
        self.candidate = candidate
        self.requests: list[tuple[str, datetime]] = []

    def load(
        self,
        security_id: str,
        as_of_cutoff: datetime,
    ) -> EvidenceBundleCandidate:
        self.requests.append((security_id, as_of_cutoff))
        return self.candidate


class EvidenceBundleWorkflowTests(unittest.TestCase):
    def test_eligible_run_materializes_persisted_content_addressed_bundle(
        self,
    ) -> None:
        run_repository = InMemoryResearchRunRepository()
        run_repository.save(eligible_run())
        source = FixedBundleSource(
            EvidenceBundleCandidate(
                security_id=SECURITY_ID,
                as_of_cutoff=CUTOFF,
                evidence_policy_version="biotech-primary-evidence-v1",
                freshness_policy_version="biotech-evidence-freshness-v1",
                items=(sec_item(),),
            )
        )
        workflow = EvidenceBundleWorkflow(
            research_run_repository=run_repository,
            bundle_repository=InMemoryEvidenceBundleRepository(),
            evidence_source=source,
            clock=lambda: CREATED_AT,
        )

        materialized = workflow.materialize(
            AuthenticatedOperator(OPERATOR_ID),
            RUN_ID,
        )
        retrieved = workflow.get(
            AuthenticatedOperator(OPERATOR_ID),
            materialized.id,
        )

        self.assertEqual(retrieved, materialized)
        self.assertEqual(materialized.research_run_id, RUN_ID)
        self.assertEqual(materialized.security_id, SECURITY_ID)
        self.assertEqual(len(materialized.content_hash), 64)
        self.assertEqual(materialized.manifest[0].evidence_id, sec_item().evidence_id)
        self.assertEqual(source.requests, [(SECURITY_ID, CUTOFF)])

    def test_retrieval_order_does_not_change_manifest_order_or_hash(self) -> None:
        issuer = replace(
            sec_item(),
            evidence_id="5d4f281d-a86b-5299-a44d-528be11ac9aa",
            evidence_version_id="2c53103a-8583-5145-9829-5601146a344c",
            source_class="issuer",
            source_locator="Q1 2026 results, pipeline section",
            canonical_url="https://ir.example.com/q1-2026-results",
            content_hash=sha256("issuer release"),
            passage_id="296ff9e0-a779-5948-9897-038197bfce44",
            passage_hash=sha256("exact pipeline passage"),
        )
        run_repository = InMemoryResearchRunRepository()
        run_repository.save(eligible_run())

        def materialize(items: tuple[EvidenceItem, ...]):
            return EvidenceBundleWorkflow(
                research_run_repository=run_repository,
                bundle_repository=InMemoryEvidenceBundleRepository(),
                evidence_source=FixedBundleSource(
                    EvidenceBundleCandidate(
                        security_id=SECURITY_ID,
                        as_of_cutoff=CUTOFF,
                        evidence_policy_version="biotech-primary-evidence-v1",
                        freshness_policy_version="biotech-evidence-freshness-v1",
                        items=items,
                    )
                ),
                clock=lambda: CREATED_AT,
            ).materialize(AuthenticatedOperator(OPERATOR_ID), RUN_ID)

        retrieved_first = materialize((issuer, sec_item()))
        sec_first = materialize((sec_item(), issuer))

        self.assertEqual(retrieved_first.content_hash, sec_first.content_hash)
        self.assertEqual(
            [item.source_class for item in retrieved_first.manifest],
            ["sec", "issuer"],
        )

    def test_identical_materialization_reuses_bundle_without_reloading_source(
        self,
    ) -> None:
        run_repository = InMemoryResearchRunRepository()
        run_repository.save(eligible_run())
        source = FixedBundleSource(
            EvidenceBundleCandidate(
                security_id=SECURITY_ID,
                as_of_cutoff=CUTOFF,
                evidence_policy_version="biotech-primary-evidence-v1",
                freshness_policy_version="biotech-evidence-freshness-v1",
                items=required_source_items(),
            )
        )
        workflow = EvidenceBundleWorkflow(
            research_run_repository=run_repository,
            bundle_repository=InMemoryEvidenceBundleRepository(),
            evidence_source=source,
            clock=lambda: CREATED_AT,
        )
        operator = AuthenticatedOperator(OPERATOR_ID)

        first = workflow.materialize(operator, RUN_ID)
        second = workflow.materialize(operator, RUN_ID)

        self.assertEqual(second, first)
        self.assertEqual(source.requests, [(SECURITY_ID, CUTOFF)])

    def test_post_cutoff_evidence_is_excluded_but_later_retrieval_is_retained(
        self,
    ) -> None:
        later_publication = replace(
            sec_item(),
            evidence_id="aa8679cd-03cf-52d6-9fd1-ef753279d466",
            evidence_version_id="68156507-0e53-5506-a303-aa35900d16fc",
            source_class="issuer",
            publication_at=datetime(2026, 5, 7, 0, 1, tzinfo=UTC),
        )
        run_repository = InMemoryResearchRunRepository()
        run_repository.save(eligible_run())
        bundle = EvidenceBundleWorkflow(
            research_run_repository=run_repository,
            bundle_repository=InMemoryEvidenceBundleRepository(),
            evidence_source=FixedBundleSource(
                EvidenceBundleCandidate(
                    security_id=SECURITY_ID,
                    as_of_cutoff=CUTOFF,
                    evidence_policy_version="biotech-primary-evidence-v1",
                    freshness_policy_version="biotech-evidence-freshness-v1",
                    items=(later_publication, sec_item()),
                )
            ),
            clock=lambda: CREATED_AT,
        ).materialize(AuthenticatedOperator(OPERATOR_ID), RUN_ID)

        self.assertEqual(bundle.manifest, (sec_item(),))
        self.assertGreater(bundle.manifest[0].retrieved_at, CUTOFF)

    def test_missing_blocking_primary_sources_prevent_grader_ready_bundle(
        self,
    ) -> None:
        run_repository = InMemoryResearchRunRepository()
        run_repository.save(eligible_run())
        bundle = EvidenceBundleWorkflow(
            research_run_repository=run_repository,
            bundle_repository=InMemoryEvidenceBundleRepository(),
            evidence_source=FixedBundleSource(
                EvidenceBundleCandidate(
                    security_id=SECURITY_ID,
                    as_of_cutoff=CUTOFF,
                    evidence_policy_version="biotech-primary-evidence-v1",
                    freshness_policy_version="biotech-evidence-freshness-v1",
                    items=(sec_item(),),
                )
            ),
            clock=lambda: CREATED_AT,
        ).materialize(AuthenticatedOperator(OPERATOR_ID), RUN_ID)

        self.assertFalse(bundle.grader_ready)
        self.assertEqual(
            [gap.code for gap in bundle.gaps],
            [
                "missing_blocking_issuer_evidence",
                "missing_blocking_clinical_evidence",
                "missing_blocking_regulatory_evidence",
                "missing_blocking_financing_evidence",
            ],
        )

    def test_bundle_freezes_normalized_metric_catalyst_and_risk_snapshots(
        self,
    ) -> None:
        items = required_source_items()
        metric = VerifiedMetricSnapshot(
            snapshot_id="9b4e8b4a-8f28-578c-b106-6be921169188",
            metric_key="cash_and_cash_equivalents",
            value="474.3",
            unit="USD_millions",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 3, 31),
            calculation_method="reported",
            formula=None,
            supporting_evidence_ids=(items[-1].evidence_id,),
        )
        catalyst = CatalystSnapshot(
            snapshot_id="1c1a3bf2-f787-5037-92c0-607e786ee93f",
            event="REC-4881 Phase 2 top-line data",
            program="REC-4881",
            basis="clinical",
            status="expected",
            window_start=date(2026, 10, 1),
            window_end=date(2026, 12, 31),
            supporting_evidence_ids=(items[1].evidence_id, items[2].evidence_id),
        )
        risk = RiskSnapshot(
            snapshot_id="068a17a2-1e11-5f87-be08-25a414469af0",
            title="Additional financing required before catalyst",
            risk_type="dilution",
            severity="high",
            status="active",
            supporting_evidence_ids=(items[-1].evidence_id,),
        )
        snapshot_items = (
            replace(
                items[-1],
                evidence_id=metric.snapshot_id,
                evidence_version_id="7d713824-4b8d-54aa-8935-edbdcc8f4c03",
                item_kind="metric",
            ),
            replace(
                items[2],
                evidence_id=catalyst.snapshot_id,
                evidence_version_id="602b6910-39b7-51f1-bf51-238bf8704c14",
                item_kind="catalyst",
            ),
            replace(
                items[-1],
                evidence_id=risk.snapshot_id,
                evidence_version_id="55484128-d262-5e90-ac53-cd13db737e8e",
                item_kind="risk",
            ),
        )
        run_repository = InMemoryResearchRunRepository()
        run_repository.save(eligible_run())
        bundle = EvidenceBundleWorkflow(
            research_run_repository=run_repository,
            bundle_repository=InMemoryEvidenceBundleRepository(),
            evidence_source=FixedBundleSource(
                EvidenceBundleCandidate(
                    security_id=SECURITY_ID,
                    as_of_cutoff=CUTOFF,
                    evidence_policy_version="biotech-primary-evidence-v1",
                    freshness_policy_version="biotech-evidence-freshness-v1",
                    items=(*items, *snapshot_items),
                    metrics=(metric,),
                    catalysts=(catalyst,),
                    risks=(risk,),
                )
            ),
            clock=lambda: CREATED_AT,
        ).materialize(AuthenticatedOperator(OPERATOR_ID), RUN_ID)

        self.assertTrue(bundle.grader_ready)
        self.assertEqual(bundle.metrics, (metric,))
        self.assertEqual(bundle.catalysts, (catalyst,))
        self.assertEqual(bundle.risks, (risk,))
        wire = bundle.as_dict()
        self.assertEqual(wire["bundle_hash"], bundle.content_hash)
        self.assertEqual(
            [entry["ordinal"] for entry in wire["manifest"]],
            list(range(1, 9)),
        )
        self.assertEqual(
            [entry["item_kind"] for entry in wire["manifest"]],
            [
                "passage",
                "passage",
                "passage",
                "catalyst",
                "passage",
                "passage",
                "metric",
                "risk",
            ],
        )
        self.assertEqual(wire["verified_metrics"][0]["value"], "474.3")

    def test_model_generated_content_is_rejected_as_bundle_evidence(self) -> None:
        run_repository = InMemoryResearchRunRepository()
        run_repository.save(eligible_run())
        generated = replace(sec_item(), provenance_type="model_output")
        workflow = EvidenceBundleWorkflow(
            research_run_repository=run_repository,
            bundle_repository=InMemoryEvidenceBundleRepository(),
            evidence_source=FixedBundleSource(
                EvidenceBundleCandidate(
                    security_id=SECURITY_ID,
                    as_of_cutoff=CUTOFF,
                    evidence_policy_version="biotech-primary-evidence-v1",
                    freshness_policy_version="biotech-evidence-freshness-v1",
                    items=(generated,),
                )
            ),
            clock=lambda: CREATED_AT,
        )

        with self.assertRaisesRegex(
            ValueError,
            "model_output cannot enter evidence bundle",
        ):
            workflow.materialize(AuthenticatedOperator(OPERATOR_ID), RUN_ID)

    def test_duplicate_evidence_identity_is_rejected_before_hashing(self) -> None:
        item = sec_item()
        duplicate = replace(
            item,
            evidence_version_id="c95add03-4257-5841-b1b4-dbd378e62b3d",
        )
        run_repository = InMemoryResearchRunRepository()
        run_repository.save(eligible_run())
        workflow = EvidenceBundleWorkflow(
            research_run_repository=run_repository,
            bundle_repository=InMemoryEvidenceBundleRepository(),
            evidence_source=FixedBundleSource(
                EvidenceBundleCandidate(
                    security_id=SECURITY_ID,
                    as_of_cutoff=CUTOFF,
                    evidence_policy_version="biotech-primary-evidence-v1",
                    freshness_policy_version="biotech-evidence-freshness-v1",
                    items=(item, duplicate),
                )
            ),
            clock=lambda: CREATED_AT,
        )

        with self.assertRaisesRegex(
            ValueError,
            "duplicate evidence manifest identity",
        ):
            workflow.materialize(AuthenticatedOperator(OPERATOR_ID), RUN_ID)

    def test_invalid_freshness_state_is_rejected_before_hashing(self) -> None:
        run_repository = InMemoryResearchRunRepository()
        run_repository.save(eligible_run())
        workflow = EvidenceBundleWorkflow(
            research_run_repository=run_repository,
            bundle_repository=InMemoryEvidenceBundleRepository(),
            evidence_source=FixedBundleSource(
                EvidenceBundleCandidate(
                    security_id=SECURITY_ID,
                    as_of_cutoff=CUTOFF,
                    evidence_policy_version="biotech-primary-evidence-v1",
                    freshness_policy_version="biotech-evidence-freshness-v1",
                    items=(replace(sec_item(), freshness="fresh"),),
                )
            ),
            clock=lambda: CREATED_AT,
        )

        with self.assertRaisesRegex(ValueError, "invalid evidence freshness state"):
            workflow.materialize(AuthenticatedOperator(OPERATOR_ID), RUN_ID)

    def test_metric_snapshot_requires_canonical_decimal_and_valid_formula(
        self,
    ) -> None:
        item = sec_item()
        metric = VerifiedMetricSnapshot(
            snapshot_id="9b4e8b4a-8f28-578c-b106-6be921169188",
            metric_key="cash_and_cash_equivalents",
            value="01.0",
            unit="USD_millions",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 3, 31),
            calculation_method="calculated",
            formula=None,
            supporting_evidence_ids=(item.evidence_id,),
        )
        run_repository = InMemoryResearchRunRepository()
        run_repository.save(eligible_run())
        workflow = EvidenceBundleWorkflow(
            research_run_repository=run_repository,
            bundle_repository=InMemoryEvidenceBundleRepository(),
            evidence_source=FixedBundleSource(
                EvidenceBundleCandidate(
                    security_id=SECURITY_ID,
                    as_of_cutoff=CUTOFF,
                    evidence_policy_version="biotech-primary-evidence-v1",
                    freshness_policy_version="biotech-evidence-freshness-v1",
                    items=(
                        item,
                        replace(
                            item,
                            evidence_id=metric.snapshot_id,
                            evidence_version_id=(
                                "7d713824-4b8d-54aa-8935-edbdcc8f4c03"
                            ),
                            item_kind="metric",
                        ),
                    ),
                    metrics=(metric,),
                )
            ),
            clock=lambda: CREATED_AT,
        )

        with self.assertRaisesRegex(ValueError, "canonical decimal"):
            workflow.materialize(AuthenticatedOperator(OPERATOR_ID), RUN_ID)

    def test_primary_evidence_requires_valid_https_source_identity(self) -> None:
        run_repository = InMemoryResearchRunRepository()
        run_repository.save(eligible_run())
        invalid_source = replace(
            sec_item(),
            canonical_url="http://example.com/generated-source",
        )
        workflow = EvidenceBundleWorkflow(
            research_run_repository=run_repository,
            bundle_repository=InMemoryEvidenceBundleRepository(),
            evidence_source=FixedBundleSource(
                EvidenceBundleCandidate(
                    security_id=SECURITY_ID,
                    as_of_cutoff=CUTOFF,
                    evidence_policy_version="biotech-primary-evidence-v1",
                    freshness_policy_version="biotech-evidence-freshness-v1",
                    items=(invalid_source,),
                )
            ),
            clock=lambda: CREATED_AT,
        )

        with self.assertRaisesRegex(ValueError, "source URL must use HTTPS"):
            workflow.materialize(AuthenticatedOperator(OPERATOR_ID), RUN_ID)

    def test_versioned_evidence_policy_declares_blocking_source_requirements(
        self,
    ) -> None:
        run_repository = InMemoryResearchRunRepository()
        run_repository.save(eligible_run())
        policy = EvidencePolicyDefinition(
            version="sec-tracer-policy-v1",
            freshness_policy_version="sec-tracer-freshness-v1",
            source_class_order=(
                "sec",
                "issuer",
                "clinical",
                "regulatory",
                "financing",
            ),
            blocking_source_classes=("sec",),
        )
        bundle = EvidenceBundleWorkflow(
            research_run_repository=run_repository,
            bundle_repository=InMemoryEvidenceBundleRepository(),
            evidence_source=FixedBundleSource(
                EvidenceBundleCandidate(
                    security_id=SECURITY_ID,
                    as_of_cutoff=CUTOFF,
                    evidence_policy_version=policy.version,
                    freshness_policy_version=policy.freshness_policy_version,
                    items=(sec_item(),),
                )
            ),
            evidence_policy_registry=FixedEvidencePolicyRegistry(policy),
            clock=lambda: CREATED_AT,
        ).materialize(AuthenticatedOperator(OPERATOR_ID), RUN_ID)

        self.assertTrue(bundle.grader_ready)
        self.assertEqual(bundle.gaps, ())

    def test_operational_timestamps_do_not_change_evidence_content_hash(self) -> None:
        base_run = eligible_run()
        later = datetime(2026, 5, 8, 3, 0, tzinfo=UTC)
        later_checks = tuple(
            replace(check, evaluated_at=later)
            for check in base_run.eligibility.checks
        )
        later_run = replace(
            base_run,
            eligibility=replace(
                base_run.eligibility,
                checks=later_checks,
                evaluated_at=later,
            ),
            created_at=later,
        )

        def materialize(run: ResearchRun, created_at: datetime):
            run_repository = InMemoryResearchRunRepository()
            run_repository.save(run)
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
                clock=lambda: created_at,
            ).materialize(AuthenticatedOperator(OPERATOR_ID), RUN_ID)

        first = materialize(base_run, CREATED_AT)
        second = materialize(later_run, later)

        self.assertEqual(first.content_hash, second.content_hash)

    def test_frozen_bundle_rejects_conflicting_same_identity_save(self) -> None:
        run_repository = InMemoryResearchRunRepository()
        run_repository.save(eligible_run())
        bundle_repository = InMemoryEvidenceBundleRepository()
        bundle = EvidenceBundleWorkflow(
            research_run_repository=run_repository,
            bundle_repository=bundle_repository,
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

        with self.assertRaisesRegex(
            ValueError,
            "conflicting immutable evidence bundle",
        ):
            bundle_repository.save(replace(bundle, manifest=()))

    def test_normalized_snapshots_reject_unresolved_evidence_references(self) -> None:
        items = required_source_items()
        metric = VerifiedMetricSnapshot(
            snapshot_id="9b4e8b4a-8f28-578c-b106-6be921169188",
            metric_key="cash_and_cash_equivalents",
            value="474.3",
            unit="USD_millions",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 3, 31),
            calculation_method="reported",
            formula=None,
            supporting_evidence_ids=(
                "686cc18c-fb01-5e3c-ae55-5feb3cdbb674",
            ),
        )
        run_repository = InMemoryResearchRunRepository()
        run_repository.save(eligible_run())
        workflow = EvidenceBundleWorkflow(
            research_run_repository=run_repository,
            bundle_repository=InMemoryEvidenceBundleRepository(),
            evidence_source=FixedBundleSource(
                EvidenceBundleCandidate(
                    security_id=SECURITY_ID,
                    as_of_cutoff=CUTOFF,
                    evidence_policy_version="biotech-primary-evidence-v1",
                    freshness_policy_version="biotech-evidence-freshness-v1",
                    items=items,
                    metrics=(metric,),
                )
            ),
            clock=lambda: CREATED_AT,
        )

        with self.assertRaisesRegex(
            ValueError,
            "snapshot evidence reference is unresolved",
        ):
            workflow.materialize(AuthenticatedOperator(OPERATOR_ID), RUN_ID)

    def test_correction_creates_new_run_and_bundle_without_mutating_prior(
        self,
    ) -> None:
        run_repository = InMemoryResearchRunRepository()
        run_repository.save(eligible_run())
        bundle_repository = InMemoryEvidenceBundleRepository()
        source = FixedBundleSource(
            EvidenceBundleCandidate(
                security_id=SECURITY_ID,
                as_of_cutoff=CUTOFF,
                evidence_policy_version="biotech-primary-evidence-v1",
                freshness_policy_version="biotech-evidence-freshness-v1",
                items=required_source_items(),
            )
        )
        workflow = EvidenceBundleWorkflow(
            research_run_repository=run_repository,
            bundle_repository=bundle_repository,
            evidence_source=source,
            clock=lambda: CREATED_AT,
        )
        operator = AuthenticatedOperator(OPERATOR_ID)
        original = workflow.materialize(operator, RUN_ID)
        corrected_sec = replace(
            sec_item(),
            evidence_version_id="9b596d13-290d-5fe5-801f-e5e143517a74",
            content_hash=sha256("corrected filing document"),
            passage_hash=sha256("corrected exact liquidity passage"),
        )
        source.candidate = replace(
            source.candidate,
            items=(corrected_sec, *source.candidate.items[1:]),
        )

        corrected = workflow.materialize_correction(operator, original.id)

        self.assertNotEqual(corrected.research_run_id, original.research_run_id)
        self.assertNotEqual(corrected.id, original.id)
        self.assertNotEqual(corrected.content_hash, original.content_hash)
        self.assertEqual(workflow.get(operator, original.id), original)
        self.assertEqual(
            run_repository.get(OPERATOR_ID, corrected.research_run_id).id,
            corrected.research_run_id,
        )


if __name__ == "__main__":
    unittest.main()

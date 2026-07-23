from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime
import json
from pathlib import Path

from investment_research_os.research_runs import (
    AuthenticatedOperator,
    CatalystCandidate,
    EvidenceReference,
    FixedWorkflowConfigRegistry,
    InMemoryResearchRunRepository,
    ResearchRunWorkflow,
    ResearchRunNotFound,
    ResearchRunRequestError,
    SecurityEligibilitySnapshot,
)


OPERATOR_ID = "8ed47ebc-d5cf-40ad-80ce-d4d803f7c735"
SECURITY_ID = "f594edb2-7fff-4e40-9c26-2c06bcbecb91"
CUTOFF = datetime(2026, 5, 6, 23, 59, 59, tzinfo=UTC)
EVALUATED_AT = datetime(2026, 5, 7, 1, 0, tzinfo=UTC)


def evidence(evidence_id: str) -> EvidenceReference:
    return EvidenceReference(evidence_id=evidence_id, available_at=CUTOFF)


def eligible_snapshot() -> SecurityEligibilitySnapshot:
    return SecurityEligibilitySnapshot(
        security_id=SECURITY_ID,
        as_of_cutoff=CUTOFF,
        issuer_name="Recursion Pharmaceuticals, Inc.",
        display_symbol="RXRX",
        security_identity_verified=True,
        primary_listing_country="US",
        primary_listing_exchange="NASDAQ",
        cik="0001601830",
        cik_matches_issuer=True,
        security_type="common_equity",
        issuer_status="operating",
        therapeutics_classification="therapeutics_biotech",
        active_therapeutic_programs=("REC-4881",),
        catalysts=(
            CatalystCandidate(
                event="REC-4881 Phase 2 top-line data",
                program="REC-4881",
                basis="clinical",
                window_start="2026-10-01",
                window_end="2026-12-31",
            ),
        ),
        primary_source_coverage=frozenset(
            {
                "sec_issuer_security",
                "required_sec_filings",
                "issuer_pipeline",
                "authoritative_trial",
                "us_regulatory",
                "financing_share_capital",
            }
        ),
        evidence_by_rule={
            rule_id: evidence(f"evidence-{rule_id}")
            for rule_id in (
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
        },
    )


class EligibleSecuritySource:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, datetime]] = []

    def load(
        self,
        operator_id: str,
        security_id: str,
        as_of_cutoff: datetime,
    ):
        self.last_request = (operator_id, security_id, as_of_cutoff)
        self.requests.append(self.last_request)
        return eligible_snapshot()


class SnapshotSecuritySource(EligibleSecuritySource):
    def __init__(self, snapshot: SecurityEligibilitySnapshot) -> None:
        super().__init__()
        self.snapshot = snapshot

    def load(
        self,
        operator_id: str,
        security_id: str,
        as_of_cutoff: datetime,
    ):
        super().load(operator_id, security_id, as_of_cutoff)
        return self.snapshot


class ResearchRunWorkflowTests(unittest.TestCase):
    def test_authenticated_operator_can_create_and_retrieve_eligible_run(self) -> None:
        repository = InMemoryResearchRunRepository()
        source = EligibleSecuritySource()
        workflow = ResearchRunWorkflow(
            repository=repository,
            eligibility_source=source,
            clock=lambda: EVALUATED_AT,
        )

        created = workflow.create(
            AuthenticatedOperator(OPERATOR_ID),
            {
                "question_type": "biotech_moonshot_catalyst_assessment",
                "security_id": SECURITY_ID,
                "as_of_cutoff": CUTOFF.isoformat(),
                "workflow_config_version": "biotech-moonshot-catalyst-v1",
                "operator_focus": "Review financing through catalyst.",
            },
        )
        retrieved = workflow.get(AuthenticatedOperator(OPERATOR_ID), created.id)

        self.assertEqual(retrieved, created)
        self.assertTrue(retrieved.eligibility.eligible)
        self.assertEqual(retrieved.security_id, SECURITY_ID)
        self.assertEqual(
            retrieved.question_type,
            "biotech_moonshot_catalyst_assessment",
        )
        self.assertEqual(
            retrieved.workflow_config_version,
            "biotech-moonshot-catalyst-v1",
        )
        self.assertEqual(
            source.last_request,
            (OPERATOR_ID, SECURITY_ID, CUTOFF),
        )

    def test_identical_request_reuses_run_without_reloading_evidence(self) -> None:
        source = EligibleSecuritySource()
        workflow = ResearchRunWorkflow(
            repository=InMemoryResearchRunRepository(),
            eligibility_source=source,
            clock=lambda: EVALUATED_AT,
        )
        request = {
            "question_type": "biotech_moonshot_catalyst_assessment",
            "security_id": SECURITY_ID,
            "as_of_cutoff": CUTOFF.isoformat(),
            "workflow_config_version": "biotech-moonshot-catalyst-v1",
            "operator_focus": "Review financing through catalyst.",
        }

        first = workflow.create(AuthenticatedOperator(OPERATOR_ID), request)
        second = workflow.create(AuthenticatedOperator(OPERATOR_ID), request)

        self.assertEqual(second, first)
        self.assertEqual(source.requests, [(OPERATOR_ID, SECURITY_ID, CUTOFF)])

    def test_equivalent_cutoff_offsets_reuse_same_run(self) -> None:
        source = EligibleSecuritySource()
        workflow = ResearchRunWorkflow(
            repository=InMemoryResearchRunRepository(),
            eligibility_source=source,
            clock=lambda: EVALUATED_AT,
        )
        base_request = {
            "question_type": "biotech_moonshot_catalyst_assessment",
            "security_id": SECURITY_ID,
            "workflow_config_version": "biotech-moonshot-catalyst-v1",
        }

        first = workflow.create(
            AuthenticatedOperator(OPERATOR_ID),
            {**base_request, "as_of_cutoff": "2026-05-06T23:59:59+00:00"},
        )
        second = workflow.create(
            AuthenticatedOperator(OPERATOR_ID),
            {**base_request, "as_of_cutoff": "2026-05-07T07:59:59+08:00"},
        )

        self.assertEqual(second.id, first.id)
        self.assertEqual(source.requests, [(OPERATOR_ID, SECURITY_ID, CUTOFF)])

    def test_equivalent_uuid_spellings_reuse_canonical_run_identity(self) -> None:
        source = EligibleSecuritySource()
        workflow = ResearchRunWorkflow(
            repository=InMemoryResearchRunRepository(),
            eligibility_source=source,
            clock=lambda: EVALUATED_AT,
        )
        request = {
            "question_type": "biotech_moonshot_catalyst_assessment",
            "security_id": SECURITY_ID,
            "as_of_cutoff": CUTOFF.isoformat(),
            "workflow_config_version": "biotech-moonshot-catalyst-v1",
        }

        first = workflow.create(AuthenticatedOperator(OPERATOR_ID), request)
        second = workflow.create(
            AuthenticatedOperator(OPERATOR_ID.upper()),
            {**request, "security_id": SECURITY_ID.upper()},
        )

        self.assertEqual(second.id, first.id)
        self.assertEqual(second.operator_id, OPERATOR_ID)
        self.assertEqual(second.security_id, SECURITY_ID)
        self.assertEqual(source.requests, [(OPERATOR_ID, SECURITY_ID, CUTOFF)])

    def test_operator_cannot_retrieve_another_operators_run(self) -> None:
        repository = InMemoryResearchRunRepository()
        workflow = ResearchRunWorkflow(
            repository=repository,
            eligibility_source=EligibleSecuritySource(),
            clock=lambda: EVALUATED_AT,
        )
        created = workflow.create(
            AuthenticatedOperator(OPERATOR_ID),
            {
                "question_type": "biotech_moonshot_catalyst_assessment",
                "security_id": SECURITY_ID,
                "as_of_cutoff": CUTOFF.isoformat(),
                "workflow_config_version": "biotech-moonshot-catalyst-v1",
            },
        )

        with self.assertRaises(ResearchRunNotFound):
            workflow.get(
                AuthenticatedOperator("2be5fa99-3a3d-40bc-805c-7c8c29cac7a2"),
                created.id,
            )

    def test_invalid_question_contracts_fail_before_evidence_collection(self) -> None:
        valid = {
            "question_type": "biotech_moonshot_catalyst_assessment",
            "security_id": SECURITY_ID,
            "as_of_cutoff": CUTOFF.isoformat(),
            "workflow_config_version": "biotech-moonshot-catalyst-v1",
            "operator_focus": None,
        }
        invalid_requests = {
            "unknown_field": {**valid, "grader_roster": ["valuation"]},
            "missing_field": {
                key: value for key, value in valid.items() if key != "security_id"
            },
            "unsupported_question": {**valid, "question_type": "compounder"},
            "inactive_workflow": {
                **valid,
                "workflow_config_version": "biotech-moonshot-catalyst-v0",
            },
            "invalid_security": {**valid, "security_id": "RXRX"},
            "invalid_cutoff": {**valid, "as_of_cutoff": "2026-05-06"},
            "future_cutoff": {
                **valid,
                "as_of_cutoff": "2026-05-08T00:00:00+00:00",
            },
        }

        for name, request in invalid_requests.items():
            with self.subTest(name=name):
                source = EligibleSecuritySource()
                workflow = ResearchRunWorkflow(
                    repository=InMemoryResearchRunRepository(),
                    eligibility_source=source,
                    clock=lambda: EVALUATED_AT,
                )

                with self.assertRaises(ResearchRunRequestError):
                    workflow.create(AuthenticatedOperator(OPERATOR_ID), request)

                self.assertEqual(source.requests, [])

    def test_inactive_workflow_config_fails_before_evidence_collection(self) -> None:
        source = EligibleSecuritySource()
        workflow = ResearchRunWorkflow(
            repository=InMemoryResearchRunRepository(),
            eligibility_source=source,
            clock=lambda: EVALUATED_AT,
            workflow_config_registry=FixedWorkflowConfigRegistry(active=False),
        )

        with self.assertRaisesRegex(
            ResearchRunRequestError,
            "workflow configuration is unavailable",
        ):
            workflow.create(
                AuthenticatedOperator(OPERATOR_ID),
                {
                    "question_type": "biotech_moonshot_catalyst_assessment",
                    "security_id": SECURITY_ID,
                    "as_of_cutoff": CUTOFF.isoformat(),
                    "workflow_config_version": "biotech-moonshot-catalyst-v1",
                },
            )

        self.assertEqual(source.requests, [])

    def test_operator_focus_cannot_change_controlled_workflow_behavior(self) -> None:
        source = EligibleSecuritySource()
        workflow = ResearchRunWorkflow(
            repository=InMemoryResearchRunRepository(),
            eligibility_source=source,
            clock=lambda: EVALUATED_AT,
        )

        with self.assertRaisesRegex(
            ResearchRunRequestError,
            "operator_focus cannot alter workflow behavior",
        ):
            workflow.create(
                AuthenticatedOperator(OPERATOR_ID),
                {
                    "question_type": "biotech_moonshot_catalyst_assessment",
                    "security_id": SECURITY_ID,
                    "as_of_cutoff": CUTOFF.isoformat(),
                    "workflow_config_version": "biotech-moonshot-catalyst-v1",
                    "operator_focus": (
                        "Remove the valuation grader and override the readiness gate."
                    ),
                },
            )

        self.assertEqual(source.requests, [])

    def test_operator_focus_raw_input_is_bounded_before_normalization(self) -> None:
        source = EligibleSecuritySource()
        workflow = ResearchRunWorkflow(
            repository=InMemoryResearchRunRepository(),
            eligibility_source=source,
            clock=lambda: EVALUATED_AT,
        )

        with self.assertRaisesRegex(ResearchRunRequestError, "exceeds 2000"):
            workflow.create(
                AuthenticatedOperator(OPERATOR_ID),
                {
                    "question_type": "biotech_moonshot_catalyst_assessment",
                    "security_id": SECURITY_ID,
                    "as_of_cutoff": CUTOFF.isoformat(),
                    "workflow_config_version": "biotech-moonshot-catalyst-v1",
                    "operator_focus": " " * 2_001,
                },
            )

        self.assertEqual(source.requests, [])

    def test_post_cutoff_evidence_cannot_make_historical_run_eligible(self) -> None:
        snapshot = eligible_snapshot()
        evidence_by_rule = dict(snapshot.evidence_by_rule)
        evidence_by_rule["active_therapeutic_program"] = EvidenceReference(
            evidence_id="evidence-published-later",
            available_at=datetime(2026, 5, 7, 0, 30, tzinfo=UTC),
        )
        source = SnapshotSecuritySource(
            replace(snapshot, evidence_by_rule=evidence_by_rule)
        )
        workflow = ResearchRunWorkflow(
            repository=InMemoryResearchRunRepository(),
            eligibility_source=source,
            clock=lambda: EVALUATED_AT,
        )

        run = workflow.create(
            AuthenticatedOperator(OPERATOR_ID),
            {
                "question_type": "biotech_moonshot_catalyst_assessment",
                "security_id": SECURITY_ID,
                "as_of_cutoff": CUTOFF.isoformat(),
                "workflow_config_version": "biotech-moonshot-catalyst-v1",
            },
        )

        check = next(
            item
            for item in run.eligibility.checks
            if item.rule_id == "active_therapeutic_program"
        )
        self.assertFalse(run.eligibility.eligible)
        self.assertFalse(check.passed)
        self.assertEqual(check.reason_code, "evidence_after_cutoff")
        self.assertEqual(check.evidence_reference, "evidence-published-later")
        self.assertEqual(check.evaluated_at, EVALUATED_AT)

    def test_snapshot_must_be_materialized_for_exact_requested_cutoff(self) -> None:
        snapshot = replace(
            eligible_snapshot(),
            as_of_cutoff=datetime(2026, 5, 7, 0, 30, tzinfo=UTC),
        )
        workflow = ResearchRunWorkflow(
            repository=InMemoryResearchRunRepository(),
            eligibility_source=SnapshotSecuritySource(snapshot),
            clock=lambda: EVALUATED_AT,
        )

        with self.assertRaisesRegex(
            ResearchRunRequestError,
            "eligibility snapshot cutoff mismatch",
        ):
            workflow.create(
                AuthenticatedOperator(OPERATOR_ID),
                {
                    "question_type": "biotech_moonshot_catalyst_assessment",
                    "security_id": SECURITY_ID,
                    "as_of_cutoff": CUTOFF.isoformat(),
                    "workflow_config_version": "biotech-moonshot-catalyst-v1",
                },
            )

    def test_catalyst_window_must_be_bounded_ordered_and_unresolved_at_cutoff(
        self,
    ) -> None:
        base = eligible_snapshot().catalysts[0]
        invalid_catalysts = (
            replace(base, window_start="soon"),
            replace(base, window_start="2027-01-01", window_end="2026-12-31"),
            replace(base, window_start="2025-01-01", window_end="2025-12-31"),
        )

        for catalyst in invalid_catalysts:
            snapshot = replace(eligible_snapshot(), catalysts=(catalyst,))
            run = ResearchRunWorkflow(
                repository=InMemoryResearchRunRepository(),
                eligibility_source=SnapshotSecuritySource(snapshot),
                clock=lambda: EVALUATED_AT,
            ).create(
                AuthenticatedOperator(OPERATOR_ID),
                {
                    "question_type": "biotech_moonshot_catalyst_assessment",
                    "security_id": SECURITY_ID,
                    "as_of_cutoff": CUTOFF.isoformat(),
                    "workflow_config_version": "biotech-moonshot-catalyst-v1",
                    "operator_focus": catalyst.window_start,
                },
            )
            check = next(
                item
                for item in run.eligibility.checks
                if item.rule_id == "defined_clinical_or_regulatory_catalyst"
            )
            self.assertFalse(check.passed)

    def test_missing_rule_evidence_is_distinct_from_failed_business_rule(self) -> None:
        snapshot = eligible_snapshot()
        evidence_by_rule = dict(snapshot.evidence_by_rule)
        del evidence_by_rule["cik_match"]
        workflow = ResearchRunWorkflow(
            repository=InMemoryResearchRunRepository(),
            eligibility_source=SnapshotSecuritySource(
                replace(snapshot, evidence_by_rule=evidence_by_rule)
            ),
            clock=lambda: EVALUATED_AT,
        )

        run = workflow.create(
            AuthenticatedOperator(OPERATOR_ID),
            {
                "question_type": "biotech_moonshot_catalyst_assessment",
                "security_id": SECURITY_ID,
                "as_of_cutoff": CUTOFF.isoformat(),
                "workflow_config_version": "biotech-moonshot-catalyst-v1",
            },
        )
        check = next(
            item for item in run.eligibility.checks if item.rule_id == "cik_match"
        )

        self.assertFalse(check.passed)
        self.assertIsNone(check.evidence_reference)
        self.assertEqual(check.reason_code, "missing_rule_evidence")

    def test_excluded_security_classes_produce_reason_coded_results(self) -> None:
        base = eligible_snapshot()
        excluded = {
            "adr": (
                replace(base, security_type="adr"),
                "common_equity",
                "excluded_adr",
            ),
            "etf": (
                replace(base, security_type="etf"),
                "common_equity",
                "excluded_fund",
            ),
            "fund": (
                replace(base, security_type="fund"),
                "common_equity",
                "excluded_fund",
            ),
            "warrant": (
                replace(base, security_type="warrant"),
                "common_equity",
                "excluded_non_common_security",
            ),
            "option": (
                replace(base, security_type="option"),
                "common_equity",
                "excluded_non_common_security",
            ),
            "preferred_share": (
                replace(base, security_type="preferred_share"),
                "common_equity",
                "excluded_non_common_security",
            ),
            "unit": (
                replace(base, security_type="unit"),
                "common_equity",
                "excluded_non_common_security",
            ),
            "right": (
                replace(base, security_type="right"),
                "common_equity",
                "excluded_non_common_security",
            ),
            "private": (
                replace(base, security_type="private_security"),
                "common_equity",
                "excluded_private_security",
            ),
            "shell": (
                replace(base, issuer_status="shell"),
                "operating_company",
                "excluded_non_operating_company",
            ),
            "non_us_listing": (
                replace(base, primary_listing_country="CA"),
                "us_listing",
                "excluded_not_us_listed",
            ),
            "diagnostics_only": (
                replace(base, therapeutics_classification="diagnostics_only"),
                "therapeutics_classification",
                "excluded_diagnostics_only",
            ),
            "medical_device_only": (
                replace(base, therapeutics_classification="medical_device_only"),
                "therapeutics_classification",
                "excluded_medical_device_only",
            ),
            "service_provider": (
                replace(
                    base,
                    therapeutics_classification=(
                        "service_provider_without_proprietary_pipeline"
                    ),
                ),
                "therapeutics_classification",
                "excluded_non_proprietary_service_provider",
            ),
            "preclinical_without_catalyst": (
                replace(base, catalysts=()),
                "defined_clinical_or_regulatory_catalyst",
                "no_identifiable_clinical_or_regulatory_catalyst",
            ),
            "missing_primary_sources": (
                replace(
                    base,
                    primary_source_coverage=frozenset(
                        base.primary_source_coverage - {"financing_share_capital"}
                    ),
                ),
                "required_primary_source_coverage",
                "missing_required_primary_source_coverage",
            ),
            "no_active_program": (
                replace(base, active_therapeutic_programs=()),
                "active_therapeutic_program",
                "no_active_therapeutic_program",
            ),
        }

        for name, (snapshot, rule_id, expected_reason) in excluded.items():
            with self.subTest(name=name):
                workflow = ResearchRunWorkflow(
                    repository=InMemoryResearchRunRepository(),
                    eligibility_source=SnapshotSecuritySource(snapshot),
                    clock=lambda: EVALUATED_AT,
                )
                run = workflow.create(
                    AuthenticatedOperator(OPERATOR_ID),
                    {
                        "question_type": "biotech_moonshot_catalyst_assessment",
                        "security_id": SECURITY_ID,
                        "as_of_cutoff": CUTOFF.isoformat(),
                        "workflow_config_version": "biotech-moonshot-catalyst-v1",
                    },
                )
                check = next(
                    item for item in run.eligibility.checks if item.rule_id == rule_id
                )

                self.assertFalse(run.eligibility.eligible)
                self.assertEqual(check.reason_code, expected_reason)

    def test_symbol_and_name_changes_preserve_stable_security_identity(self) -> None:
        original = eligible_snapshot()
        renamed = replace(
            original,
            issuer_name="Example Therapeutics, Inc.",
            display_symbol="EXTH",
        )
        request = {
            "question_type": "biotech_moonshot_catalyst_assessment",
            "security_id": SECURITY_ID,
            "as_of_cutoff": CUTOFF.isoformat(),
            "workflow_config_version": "biotech-moonshot-catalyst-v1",
        }

        before = ResearchRunWorkflow(
            repository=InMemoryResearchRunRepository(),
            eligibility_source=SnapshotSecuritySource(original),
            clock=lambda: EVALUATED_AT,
        ).create(AuthenticatedOperator(OPERATOR_ID), request)
        after = ResearchRunWorkflow(
            repository=InMemoryResearchRunRepository(),
            eligibility_source=SnapshotSecuritySource(renamed),
            clock=lambda: EVALUATED_AT,
        ).create(AuthenticatedOperator(OPERATOR_ID), request)

        self.assertEqual(after.id, before.id)
        self.assertEqual(after.security_identity.id, before.security_identity.id)
        self.assertEqual(before.security_identity.symbol, "RXRX")
        self.assertEqual(after.security_identity.symbol, "EXTH")

    def test_eligible_run_matches_canonical_wire_fixture(self) -> None:
        workflow = ResearchRunWorkflow(
            repository=InMemoryResearchRunRepository(),
            eligibility_source=EligibleSecuritySource(),
            clock=lambda: EVALUATED_AT,
        )
        run = workflow.create(
            AuthenticatedOperator(OPERATOR_ID),
            {
                "question_type": "biotech_moonshot_catalyst_assessment",
                "security_id": SECURITY_ID,
                "as_of_cutoff": CUTOFF.isoformat(),
                "workflow_config_version": "biotech-moonshot-catalyst-v1",
                "operator_focus": "Review financing through catalyst.",
            },
        )
        fixture = json.loads(
            Path("tests/fixtures/contracts/research_run/v1/eligible.json").read_text()
        )

        self.assertEqual(run.as_dict(), fixture)


if __name__ == "__main__":
    unittest.main()

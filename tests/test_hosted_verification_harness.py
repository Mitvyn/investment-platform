from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from investment_research_os.hosted_verification import (
    HostedVerificationHarness,
    HostedVerificationAuthorization,
    HostedVerificationPlan,
    HostedVerificationProbe,
    HostedVerificationProbeResult,
    HostedVerificationRecord,
    build_default_iros_hosted_verification_plan,
    build_hosted_verification_plan,
    build_matching_offline_probe_results,
)


NOW = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
COMPLIANT_IROS_MIGRATION = """\
create table public.iros_test (id uuid);
alter table public.iros_test enable row level security;
revoke all privileges on table public.iros_test from anon, authenticated;
"""


class PortSpy:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def run_database_probes(self, plan, authorization):
        self.calls.append("database")
        raise AssertionError("database probes must not run")

    def run_advisor_probes(self, plan, authorization):
        self.calls.append("advisor")
        raise AssertionError("advisor probes must not run")


class ResultPort:
    def __init__(
        self,
        *,
        database_results: tuple[HostedVerificationProbeResult, ...] = (),
        advisor_results: tuple[HostedVerificationProbeResult, ...] = (),
    ) -> None:
        self.database_results = database_results
        self.advisor_results = advisor_results

    def run_database_probes(self, plan, authorization):
        return self.database_results

    def run_advisor_probes(self, plan, authorization):
        return self.advisor_results


class FailingDatabasePort(ResultPort):
    def run_database_probes(self, plan, authorization):
        raise RuntimeError("secret-token-and-raw-payload")


def valid_authorization() -> HostedVerificationAuthorization:
    return HostedVerificationAuthorization.freeze(
        authorization_id="authorization-iro-051",
        issue_id="IRO-052",
        database_scope="iros_only",
        operator_id="operator-1",
        owner_subject_id="owner-subject",
        unrelated_subject_id="unrelated-subject",
        audit_subject_id="audit-subject",
        turn_id="turn-iro-051",
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=15),
        authorized_scopes=HostedVerificationPlan.required_scopes(),
    )


class HostedVerificationHarnessTests(unittest.TestCase):
    def test_authorization_is_bound_to_iros_052_and_iros_only_database(self) -> None:
        authorization = HostedVerificationAuthorization.freeze(
            authorization_id="authorization-iro-052",
            issue_id="IRO-052",
            database_scope="iros_only",
            operator_id="operator-1",
            owner_subject_id="owner-subject",
            unrelated_subject_id="unrelated-subject",
            audit_subject_id="audit-subject",
            turn_id="turn-iro-052",
            issued_at=NOW - timedelta(minutes=1),
            expires_at=NOW + timedelta(minutes=15),
            authorized_scopes=HostedVerificationPlan.required_scopes(),
        )

        self.assertEqual(authorization.issue_id, "IRO-052")
        self.assertEqual(authorization.database_scope, "iros_only")
        with self.assertRaisesRegex(
            ValueError,
            "hosted verification issue is invalid",
        ):
            replace(authorization, issue_id="IRO-058").assert_valid_contract()
        with self.assertRaisesRegex(
            ValueError,
            "hosted verification database scope is invalid",
        ):
            replace(
                authorization,
                database_scope="shared_database",
            ).assert_valid_contract()

        with self.assertRaisesRegex(
            ValueError,
            "hosted verification authorization lifetime is invalid",
        ):
            HostedVerificationAuthorization.freeze(
                authorization_id="authorization-too-long",
                issue_id="IRO-052",
                database_scope="iros_only",
                operator_id="operator-1",
                owner_subject_id="owner-subject",
                unrelated_subject_id="unrelated-subject",
                audit_subject_id="audit-subject",
                turn_id="turn-iro-052",
                issued_at=NOW,
                expires_at=NOW + timedelta(hours=24),
                authorized_scopes=HostedVerificationPlan.required_scopes(),
            )

    def test_missing_authorization_fails_closed_before_any_probe(self) -> None:
        database = PortSpy()
        advisor = PortSpy()
        harness = HostedVerificationHarness(database=database, advisor=advisor)

        report = harness.run(
            plan=HostedVerificationPlan.empty(),
            authorization=None,
            current_turn_id="turn-iro-051",
            checked_at=NOW,
        )

        self.assertFalse(report.passed)
        self.assertEqual(
            report.blocking_reason_codes,
            ("authorization_manifest_missing",),
        )
        self.assertEqual(report.probe_results, ())
        self.assertEqual(database.calls, [])
        self.assertEqual(advisor.calls, [])

    def test_naive_verification_time_fails_closed_before_any_probe(self) -> None:
        database = PortSpy()
        advisor = PortSpy()

        report = HostedVerificationHarness(
            database=database,
            advisor=advisor,
        ).run(
            plan=HostedVerificationPlan.empty(),
            authorization=valid_authorization(),
            current_turn_id="turn-iro-051",
            checked_at=NOW.replace(tzinfo=None),
        )

        self.assertEqual(
            report.blocking_reason_codes,
            ("verification_time_invalid",),
        )
        self.assertEqual(database.calls, [])
        self.assertEqual(advisor.calls, [])

    def test_authorization_must_bind_current_turn_and_all_probe_scopes(self) -> None:
        database = PortSpy()
        advisor = PortSpy()
        harness = HostedVerificationHarness(database=database, advisor=advisor)
        authorization = HostedVerificationAuthorization.freeze(
            authorization_id="authorization-iro-051",
            issue_id="IRO-052",
            database_scope="iros_only",
            operator_id="operator-1",
            owner_subject_id="owner-subject",
            unrelated_subject_id="unrelated-subject",
            audit_subject_id="audit-subject",
            turn_id="old-turn",
            issued_at=NOW - timedelta(minutes=1),
            expires_at=NOW + timedelta(minutes=15),
            authorized_scopes=HostedVerificationPlan.required_scopes(),
        )

        report = harness.run(
            plan=HostedVerificationPlan.empty(),
            authorization=authorization,
            current_turn_id="turn-iro-051",
            checked_at=NOW,
        )

        self.assertFalse(report.passed)
        self.assertEqual(
            report.blocking_reason_codes,
            ("authorization_not_current_turn",),
        )
        self.assertEqual(database.calls, [])
        self.assertEqual(advisor.calls, [])

    def test_authorized_run_requires_each_declared_probe_exactly_once(self) -> None:
        plan = HostedVerificationPlan.freeze(
            probes=(
                HostedVerificationProbe(
                    probe_id="migration.reviewed_batch",
                    category="migration_history",
                    required_scope="linked_migration_history_read",
                ),
                HostedVerificationProbe(
                    probe_id="access.owner_view",
                    category="owner_isolation",
                    required_scope="owner_isolation_read",
                ),
                HostedVerificationProbe(
                    probe_id="advisor.iros_findings",
                    category="database_advisor",
                    required_scope="database_advisor_read",
                ),
            ),
        )
        database_results = (
            HostedVerificationProbeResult.passed_result(
                probe_id="migration.reviewed_batch",
                category="migration_history",
                result_code="reviewed_batch_matches",
                count=27,
                artifact_sha256=plan.migration_manifest_sha256,
            ),
            HostedVerificationProbeResult.passed_result(
                probe_id="access.owner_view",
                category="owner_isolation",
                result_code="owner_rows_visible",
                count=1,
                artifact_sha256=plan.target_manifest_sha256,
            ),
        )
        advisor_results = (
            HostedVerificationProbeResult.passed_result(
                probe_id="advisor.iros_findings",
                category="database_advisor",
                result_code="no_unaddressed_findings",
                count=0,
            ),
        )
        database = ResultPort(database_results=database_results)
        advisor = ResultPort(advisor_results=advisor_results)

        report = HostedVerificationHarness(
            database=database,
            advisor=advisor,
        ).run(
            plan=plan,
            authorization=valid_authorization(),
            current_turn_id="turn-iro-051",
            checked_at=NOW,
        )

        self.assertTrue(report.passed)
        self.assertEqual(report.blocking_reason_codes, ())
        self.assertEqual(
            tuple(result.probe_id for result in report.probe_results),
            tuple(probe.probe_id for probe in plan.probes),
        )
        self.assertNotIn("payload", report.as_dict())

    def test_plan_hashes_reviewed_migrations_and_rejects_foreign_targets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            migration = Path(directory) / "20260807000000_iros_test.sql"
            migration.write_text(COMPLIANT_IROS_MIGRATION)
            probe = HostedVerificationProbe(
                probe_id="migration.reviewed_batch",
                category="migration_history",
                required_scope="linked_migration_history_read",
            )

            plan = build_hosted_verification_plan(
                migration_paths=(migration,),
                target_objects=("iros_v_research_run_eligibility",),
                probes=(probe,),
            )

            self.assertEqual(
                tuple(entry.filename for entry in plan.migration_manifest),
                (migration.name,),
            )
            self.assertEqual(len(plan.migration_manifest[0].content_sha256), 64)
            self.assertEqual(len(plan.content_sha256), 64)
            with self.assertRaisesRegex(
                ValueError,
                "hosted verification target is outside iros namespace",
            ):
                build_hosted_verification_plan(
                    migration_paths=(migration,),
                    target_objects=("foreign_table",),
                    probes=(probe,),
                )

    def test_default_plan_covers_every_hosted_verification_domain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            migration = Path(directory) / "20260807000000_iros_test.sql"
            migration.write_text(COMPLIANT_IROS_MIGRATION)

            plan = build_default_iros_hosted_verification_plan(
                migration_paths=(migration,),
            )

        categories = {probe.category for probe in plan.probes}
        self.assertEqual(
            categories,
            {
                "migration_history",
                "owner_isolation",
                "raw_provider_audit",
                "immutable_constraint",
                "duplicate_prevention",
                "valuation_gate",
                "database_advisor",
            },
        )
        self.assertIn("access.owner", {probe.probe_id for probe in plan.probes})
        self.assertIn(
            "access.unrelated_denied",
            {probe.probe_id for probe in plan.probes},
        )
        self.assertIn(
            "access.anonymous_denied",
            {probe.probe_id for probe in plan.probes},
        )
        self.assertIn(
            "raw_audit.access_event",
            {probe.probe_id for probe in plan.probes},
        )
        self.assertTrue(plan.target_objects)
        self.assertTrue(
            all(target.startswith("iros_") for target in plan.target_objects)
        )
        self.assertTrue(all(probe.expected_result_code for probe in plan.probes))
        self.assertTrue(all(probe.expected_count is not None for probe in plan.probes))
        by_id = {probe.probe_id: probe for probe in plan.probes}
        self.assertEqual(
            by_id["migration.linked_history"].expected_count,
            len(plan.migration_manifest),
        )
        self.assertEqual(
            by_id["access.owner"].expected_count,
            len(plan.target_objects),
        )
        self.assertEqual(
            by_id["raw_audit.ordinary_denied"].expected_result_code,
            "ordinary_access_denied",
        )
        self.assertEqual(
            by_id["advisor.iros_findings"].expected_count,
            0,
        )

    def test_transport_failure_is_redacted_and_stops_remaining_probes(self) -> None:
        plan = HostedVerificationPlan.freeze(
            probes=(
                HostedVerificationProbe(
                    probe_id="migration.reviewed_batch",
                    category="migration_history",
                    required_scope="linked_migration_history_read",
                ),
            ),
        )
        advisor = PortSpy()

        report = HostedVerificationHarness(
            database=FailingDatabasePort(),
            advisor=advisor,
        ).run(
            plan=plan,
            authorization=valid_authorization(),
            current_turn_id="turn-iro-051",
            checked_at=NOW,
        )

        self.assertFalse(report.passed)
        self.assertEqual(
            report.blocking_reason_codes,
            ("database_probe_transport_failed",),
        )
        self.assertNotIn("secret-token", str(report.as_dict()))
        self.assertEqual(advisor.calls, [])

    def test_authorization_integrity_and_subject_isolation_fail_closed(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "hosted verification subjects must be distinct",
        ):
            HostedVerificationAuthorization.freeze(
                authorization_id="authorization-iro-051",
                issue_id="IRO-052",
                database_scope="iros_only",
                operator_id="operator-1",
                owner_subject_id="same-subject",
                unrelated_subject_id="same-subject",
                audit_subject_id="audit-subject",
                turn_id="turn-iro-051",
                issued_at=NOW - timedelta(minutes=1),
                expires_at=NOW + timedelta(minutes=15),
                authorized_scopes=HostedVerificationPlan.required_scopes(),
            )

        database = PortSpy()
        advisor = PortSpy()
        report = HostedVerificationHarness(
            database=database,
            advisor=advisor,
        ).run(
            plan=HostedVerificationPlan.empty(),
            authorization=replace(
                valid_authorization(),
                operator_id="tampered-operator",
            ),
            current_turn_id="turn-iro-051",
            checked_at=NOW,
        )

        self.assertFalse(report.passed)
        self.assertEqual(
            report.blocking_reason_codes,
            ("authorization_content_hash_mismatch",),
        )
        self.assertEqual(database.calls, [])
        self.assertEqual(advisor.calls, [])

    def test_unexpected_probe_outcome_is_preserved_as_blocking_result(self) -> None:
        plan = HostedVerificationPlan.freeze(
            probes=(
                HostedVerificationProbe(
                    probe_id="immutable.research_run",
                    category="immutable_constraint",
                    required_scope="negative_constraint_probe",
                ),
                HostedVerificationProbe(
                    probe_id="duplicate.research_run",
                    category="duplicate_prevention",
                    required_scope="negative_constraint_probe",
                ),
            ),
        )
        results = (
            HostedVerificationProbeResult.passed_result(
                probe_id="immutable.research_run",
                category="immutable_constraint",
                result_code="mutation_rejected",
                count=1,
            ),
            HostedVerificationProbeResult.failed_result(
                probe_id="duplicate.research_run",
                category="duplicate_prevention",
                result_code="duplicate_was_accepted",
                count=1,
            ),
        )

        report = HostedVerificationHarness(
            database=ResultPort(database_results=results),
            advisor=ResultPort(),
        ).run(
            plan=plan,
            authorization=valid_authorization(),
            current_turn_id="turn-iro-051",
            checked_at=NOW,
        )

        self.assertFalse(report.passed)
        self.assertEqual(
            report.blocking_reason_codes,
            ("probe_failed:duplicate.research_run",),
        )
        self.assertEqual(report.probe_results, results[::-1])

    def test_migration_and_access_coverage_hashes_must_match_plan(self) -> None:
        plan = HostedVerificationPlan.freeze(
            migration_manifest=(),
            target_objects=("iros_v_research_run_eligibility",),
            probes=(
                HostedVerificationProbe(
                    probe_id="migration.linked_history",
                    category="migration_history",
                    required_scope="linked_migration_history_read",
                ),
                HostedVerificationProbe(
                    probe_id="access.owner",
                    category="owner_isolation",
                    required_scope="owner_isolation_read",
                ),
            ),
        )
        results = (
            HostedVerificationProbeResult.passed_result(
                probe_id="migration.linked_history",
                category="migration_history",
                result_code="reviewed_batch_matches",
                count=0,
                artifact_sha256="f" * 64,
            ),
            HostedVerificationProbeResult.passed_result(
                probe_id="access.owner",
                category="owner_isolation",
                result_code="owner_rows_visible",
                count=1,
                artifact_sha256="e" * 64,
            ),
        )

        report = HostedVerificationHarness(
            database=ResultPort(database_results=results),
            advisor=ResultPort(),
        ).run(
            plan=plan,
            authorization=valid_authorization(),
            current_turn_id="turn-iro-051",
            checked_at=NOW,
        )

        self.assertFalse(report.passed)
        self.assertEqual(
            report.blocking_reason_codes,
            (
                "probe_artifact_hash_mismatch:access.owner",
                "probe_artifact_hash_mismatch:migration.linked_history",
            ),
        )

    def test_probe_result_must_match_plan_semantics_not_self_reported_pass(
        self,
    ) -> None:
        plan = HostedVerificationPlan.freeze(
            probes=(
                HostedVerificationProbe(
                    probe_id="raw_audit.ordinary_denied",
                    category="raw_provider_audit",
                    required_scope="raw_provider_audit_probe",
                    expected_result_code="ordinary_access_denied",
                    expected_count=1,
                ),
            ),
        )
        result = HostedVerificationProbeResult.passed_result(
            probe_id="raw_audit.ordinary_denied",
            category="raw_provider_audit",
            result_code="ordinary_access_allowed",
            count=0,
        )

        report = HostedVerificationHarness(
            database=ResultPort(database_results=(result,)),
            advisor=ResultPort(),
        ).run(
            plan=plan,
            authorization=valid_authorization(),
            current_turn_id="turn-iro-051",
            checked_at=NOW,
        )

        self.assertFalse(report.passed)
        self.assertEqual(
            report.blocking_reason_codes,
            ("probe_contract_mismatch:raw_audit.ordinary_denied",),
        )

    def test_probe_result_rejects_non_machine_safe_result_code(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "hosted verification result code is invalid",
        ):
            HostedVerificationProbeResult.failed_result(
                probe_id="raw_audit.ordinary_denied",
                category="raw_provider_audit",
                result_code="access denied: secret-token-and-raw-payload",
                count=0,
            )

    def test_offline_fixture_proves_complete_default_plan_without_hosted_access(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            migration = Path(directory) / "20260807000000_iros_test.sql"
            migration.write_text(COMPLIANT_IROS_MIGRATION)
            plan = build_default_iros_hosted_verification_plan(
                migration_paths=(migration,),
            )

        results = build_matching_offline_probe_results(plan)
        database_results = tuple(
            result for result in results if result.category != "database_advisor"
        )
        advisor_results = tuple(
            result for result in results if result.category == "database_advisor"
        )
        report = HostedVerificationHarness(
            database=ResultPort(database_results=database_results),
            advisor=ResultPort(advisor_results=advisor_results),
        ).run(
            plan=plan,
            authorization=valid_authorization(),
            current_turn_id="turn-iro-051",
            checked_at=NOW,
        )

        self.assertTrue(report.passed)
        self.assertEqual(
            tuple(result.probe_id for result in results),
            tuple(probe.probe_id for probe in plan.probes),
        )
        self.assertEqual(report.blocking_reason_codes, ())

    def test_tampered_plan_fails_closed_before_any_probe(self) -> None:
        plan = HostedVerificationPlan.freeze(
            probes=(
                HostedVerificationProbe(
                    probe_id="advisor.iros_findings",
                    category="database_advisor",
                    required_scope="database_advisor_read",
                    expected_result_code="no_unaddressed_findings",
                    expected_count=0,
                ),
            ),
        )
        database = PortSpy()
        advisor = PortSpy()

        report = HostedVerificationHarness(
            database=database,
            advisor=advisor,
        ).run(
            plan=replace(plan, content_sha256="0" * 64),
            authorization=valid_authorization(),
            current_turn_id="turn-iro-051",
            checked_at=NOW,
        )

        self.assertFalse(report.passed)
        self.assertEqual(
            report.blocking_reason_codes,
            ("plan_content_hash_mismatch",),
        )
        self.assertEqual(database.calls, [])
        self.assertEqual(advisor.calls, [])

    def test_probe_identifiers_are_redaction_safe_and_module_is_iros_only(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "hosted verification probe ID is invalid",
        ):
            HostedVerificationProbe(
                probe_id="advisor: secret-token",
                category="database_advisor",
                required_scope="database_advisor_read",
            )

        module_source = (
            Path(__file__).parents[1]
            / "src"
            / "investment_research_os"
            / "hosted_verification.py"
        ).read_text()
        self.assertNotIn("well_", module_source.lower())

    def test_unsupported_probe_result_is_redacted_contract_failure(self) -> None:
        plan = HostedVerificationPlan.freeze(
            probes=(
                HostedVerificationProbe(
                    probe_id="advisor.iros_findings",
                    category="database_advisor",
                    required_scope="database_advisor_read",
                    expected_result_code="no_unaddressed_findings",
                    expected_count=0,
                ),
            ),
        )
        report = HostedVerificationHarness(
            database=ResultPort(database_results=(object(),)),  # type: ignore[arg-type]
            advisor=ResultPort(),
        ).run(
            plan=plan,
            authorization=valid_authorization(),
            current_turn_id="turn-iro-051",
            checked_at=NOW,
        )

        self.assertFalse(report.passed)
        self.assertEqual(
            report.blocking_reason_codes,
            ("probe_result_contract_invalid",),
        )
        self.assertEqual(report.probe_results, ())

    def test_invalid_database_result_stops_before_advisor_boundary(self) -> None:
        plan = HostedVerificationPlan.freeze(
            probes=(
                HostedVerificationProbe(
                    probe_id="advisor.iros_findings",
                    category="database_advisor",
                    required_scope="database_advisor_read",
                    expected_result_code="no_unaddressed_findings",
                    expected_count=0,
                ),
            ),
        )
        advisor = PortSpy()

        report = HostedVerificationHarness(
            database=ResultPort(database_results=(object(),)),  # type: ignore[arg-type]
            advisor=advisor,
        ).run(
            plan=plan,
            authorization=valid_authorization(),
            current_turn_id="turn-iro-051",
            checked_at=NOW,
        )

        self.assertEqual(
            report.blocking_reason_codes,
            ("probe_result_contract_invalid",),
        )
        self.assertEqual(report.probe_results, ())
        self.assertEqual(advisor.calls, [])

    def test_authorized_execution_freezes_redacted_content_addressed_record(
        self,
    ) -> None:
        plan = HostedVerificationPlan.freeze(
            probes=(
                HostedVerificationProbe(
                    probe_id="advisor.iros_findings",
                    category="database_advisor",
                    required_scope="database_advisor_read",
                    expected_result_code="no_unaddressed_findings",
                    expected_count=0,
                ),
            ),
            target_objects=("iros_v_research_run_eligibility",),
        )
        authorization = valid_authorization()
        results = build_matching_offline_probe_results(plan)
        report = HostedVerificationHarness(
            database=ResultPort(),
            advisor=ResultPort(advisor_results=results),
        ).run(
            plan=plan,
            authorization=authorization,
            current_turn_id="turn-iro-051",
            checked_at=NOW,
        )

        record = HostedVerificationRecord.freeze(
            plan=plan,
            authorization=authorization,
            report=report,
            checked_at=NOW,
        )

        self.assertTrue(record.has_valid_content_hash())
        self.assertEqual(record.record_version, "hosted-verification-record.v1")
        self.assertEqual(record.issue_id, "IRO-052")
        self.assertEqual(record.database_scope, "iros_only")
        self.assertEqual(report.checked_at, NOW)
        self.assertEqual(record.plan_sha256, plan.content_sha256)
        self.assertEqual(
            record.migration_manifest_sha256,
            plan.migration_manifest_sha256,
        )
        serialized = str(record.as_dict())
        self.assertNotIn("owner-subject", serialized)
        self.assertNotIn("unrelated-subject", serialized)
        self.assertNotIn("audit-subject", serialized)
        self.assertNotIn("payload", serialized)
        self.assertFalse(replace(record, passed=False).has_valid_content_hash())
        with self.assertRaisesRegex(
            ValueError,
            "hosted verification record time does not match report",
        ):
            HostedVerificationRecord.freeze(
                plan=plan,
                authorization=authorization,
                report=report,
                checked_at=NOW + timedelta(seconds=1),
            )

    def test_default_plan_rejects_migration_that_fails_iros_static_audit(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            migration = Path(directory) / "20260807000000_iros_test.sql"
            migration.write_text(
                "alter table public.foreign_profile add column leak text;\n"
            )

            with self.assertRaisesRegex(
                ValueError,
                "hosted verification migration batch failed IROS audit",
            ):
                build_default_iros_hosted_verification_plan(
                    migration_paths=(migration,),
                )


if __name__ == "__main__":
    unittest.main()

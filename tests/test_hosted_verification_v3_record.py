from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import unittest

from investment_research_os.hosted_verification import (
    HostedVerificationAuthorization,
    HostedVerificationPlan,
    HostedVerificationProbe,
)
from investment_research_os.hosted_verification_v3 import (
    HostedProbeDispatch,
    HostedProbeFixture,
    HostedVerificationExecutionAuthorization,
    HostedVerificationExecutionContract,
)
from investment_research_os.hosted_verification_v3_record import (
    HostedProbeOutcome,
    HostedVerificationExecutionRecord,
    HostedVerificationExecutionReport,
)


INVENTORY_SHA256 = "1" * 64
CONSTRAINT_INDEX_SHA256 = "2" * 64


class HostedVerificationV3RecordTests(unittest.TestCase):
    def test_report_refuses_claimed_pass_when_outcome_failed(self) -> None:
        contract, execution_authorization, _ = self._read_contract()
        outcome = HostedProbeOutcome.freeze(
            probe_id="access.owner",
            passed=False,
            result_code="owner_access_failed",
            count=0,
            observed_constraint=None,
            rollback_verified=False,
            artifact_sha256=None,
        )

        with self.assertRaisesRegex(ValueError, "claimed outcome is inconsistent"):
            HostedVerificationExecutionReport.freeze(
                execution_contract=contract,
                execution_authorization=execution_authorization,
                claimed_passed=True,
                blocking_reason_codes=(),
                probe_outcomes=(outcome,),
                residue_suspected=(),
                checked_at=datetime(2026, 8, 11, 12, 0, tzinfo=UTC),
                execution_provenance="hosted_transport",
            )

    def test_failed_hosted_run_freezes_but_unattested_run_does_not(self) -> None:
        contract, execution_authorization, authorization = self._read_contract()
        checked_at = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
        outcome = HostedProbeOutcome.freeze(
            probe_id="access.owner",
            passed=False,
            result_code="owner_access_failed",
            count=0,
            observed_constraint=None,
            rollback_verified=False,
            artifact_sha256=None,
        )
        report = HostedVerificationExecutionReport.freeze(
            execution_contract=contract,
            execution_authorization=execution_authorization,
            claimed_passed=False,
            blocking_reason_codes=("transport_failure",),
            probe_outcomes=(outcome,),
            residue_suspected=(),
            checked_at=checked_at,
            execution_provenance="hosted_transport",
        )

        record = HostedVerificationExecutionRecord.freeze(
            execution_contract=contract,
            authorization=authorization,
            execution_authorization=execution_authorization,
            report=report,
            inventory_sha256=INVENTORY_SHA256,
            constraint_index_sha256=CONSTRAINT_INDEX_SHA256,
        )

        self.assertFalse(record.passed)
        self.assertEqual(record.execution_provenance, "hosted_transport")
        self.assertTrue(record.has_valid_content_hash())
        with self.assertRaisesRegex(ValueError, "provenance is invalid"):
            HostedVerificationExecutionReport.freeze(
                execution_contract=contract,
                execution_authorization=execution_authorization,
                claimed_passed=False,
                blocking_reason_codes=("transport_failure",),
                probe_outcomes=(outcome,),
                residue_suspected=(),
                checked_at=checked_at,
                execution_provenance="unattested",
            )

    def test_missing_mutation_rollback_becomes_blocking_reason(self) -> None:
        contract, execution_authorization, _ = self._mutation_contract()
        outcome = HostedProbeOutcome.freeze(
            probe_id="immutable.research_run",
            passed=False,
            result_code="mutation_rejected",
            count=1,
            observed_constraint="iros_research_runs_contract_immutable",
            rollback_verified=False,
            artifact_sha256=None,
        )

        report = HostedVerificationExecutionReport.freeze(
            execution_contract=contract,
            execution_authorization=execution_authorization,
            claimed_passed=False,
            blocking_reason_codes=(),
            probe_outcomes=(outcome,),
            residue_suspected=(),
            checked_at=datetime(2026, 8, 11, 12, 0, tzinfo=UTC),
            execution_provenance="hosted_transport",
        )

        self.assertIn(
            "rollback_unproven:fixture.immutable_run",
            report.blocking_reason_codes,
        )
        self.assertTrue(report.abort_remaining_mutations)

    def test_suspected_residue_forces_failure_and_aborts_mutations(self) -> None:
        contract, execution_authorization, _ = self._read_contract()
        outcome = HostedProbeOutcome.freeze(
            probe_id="access.owner",
            passed=True,
            result_code="owner_access_verified",
            count=1,
            observed_constraint=None,
            rollback_verified=False,
            artifact_sha256=None,
        )

        report = HostedVerificationExecutionReport.freeze(
            execution_contract=contract,
            execution_authorization=execution_authorization,
            claimed_passed=False,
            blocking_reason_codes=(),
            probe_outcomes=(outcome,),
            residue_suspected=("fixture.owner_job",),
            checked_at=datetime(2026, 8, 11, 12, 0, tzinfo=UTC),
            execution_provenance="hosted_transport",
        )

        self.assertIn(
            "residue_suspected:fixture.owner_job",
            report.blocking_reason_codes,
        )
        self.assertTrue(report.abort_remaining_mutations)

    def test_report_hash_validation_rejects_tampered_nested_outcome(self) -> None:
        contract, execution_authorization, _ = self._read_contract()
        outcome = HostedProbeOutcome.freeze(
            probe_id="access.owner",
            passed=True,
            result_code="owner_access_verified",
            count=1,
            observed_constraint=None,
            rollback_verified=False,
            artifact_sha256=None,
        )
        report = HostedVerificationExecutionReport.freeze(
            execution_contract=contract,
            execution_authorization=execution_authorization,
            claimed_passed=True,
            blocking_reason_codes=(),
            probe_outcomes=(outcome,),
            residue_suspected=(),
            checked_at=datetime(2026, 8, 11, 12, 0, tzinfo=UTC),
            execution_provenance="hosted_transport",
        )

        tampered_outcome = replace(outcome, count=2)
        tampered_report = replace(report, probe_outcomes=(tampered_outcome,))

        self.assertFalse(tampered_report.has_valid_content_hash())

    @staticmethod
    def _read_contract() -> tuple[
        HostedVerificationExecutionContract,
        HostedVerificationExecutionAuthorization,
        HostedVerificationAuthorization,
    ]:
        plan = HostedVerificationPlan.freeze(
            probes=(
                HostedVerificationProbe(
                    probe_id="access.owner",
                    category="owner_isolation",
                    required_scope="owner_isolation_read",
                    expected_result_code="owner_access_verified",
                    expected_count=1,
                ),
            ),
            target_objects=("iros_jobs",),
        )
        fixture = HostedProbeFixture.freeze(
            fixture_id="fixture.owner_job",
            setup_state="owner_graph",
            row_identity="owner_job",
            target_owner_role="owner",
            cleanup_rule="none",
        )
        dispatch = HostedProbeDispatch.freeze(
            probe_id="access.owner",
            transport_owner="database",
            operation="count_rows",
            target_objects=("iros_jobs",),
            subject_role="owner",
            fixture_id=fixture.fixture_id,
            mutation_field=None,
            expected_constraint=None,
            rollback_assertion="not_required",
        )
        contract = HostedVerificationExecutionContract.freeze(
            plan=plan,
            dispatches=(dispatch,),
            fixtures=(fixture,),
            inventory_sha256=INVENTORY_SHA256,
            constraint_index_sha256=CONSTRAINT_INDEX_SHA256,
        )
        now = datetime(2026, 8, 11, 11, 55, tzinfo=UTC)
        authorization = HostedVerificationAuthorization.freeze(
            authorization_id="authorization-iro-052-v3",
            issue_id="IRO-052",
            database_scope="iros_only",
            operator_id="operator-1",
            owner_subject_id="owner-subject",
            unrelated_subject_id="unrelated-subject",
            audit_subject_id="audit-subject",
            turn_id="turn-iro-052-v3",
            issued_at=now,
            expires_at=now + timedelta(minutes=15),
            authorized_scopes=("owner_isolation_read",),
        )
        execution_authorization = HostedVerificationExecutionAuthorization.freeze(
            authorization=authorization,
            execution_contract=contract,
        )
        return contract, execution_authorization, authorization

    @staticmethod
    def _mutation_contract() -> tuple[
        HostedVerificationExecutionContract,
        HostedVerificationExecutionAuthorization,
        HostedVerificationAuthorization,
    ]:
        plan = HostedVerificationPlan.freeze(
            probes=(
                HostedVerificationProbe(
                    probe_id="immutable.research_run",
                    category="immutable_constraint",
                    required_scope="negative_constraint_probe",
                    expected_result_code="mutation_rejected",
                    expected_count=1,
                ),
            ),
            target_objects=("iros_research_runs",),
        )
        fixture = HostedProbeFixture.freeze(
            fixture_id="fixture.immutable_run",
            setup_state="finalized_row",
            row_identity="immutable_run",
            target_owner_role="owner",
            cleanup_rule="transaction_rollback",
        )
        dispatch = HostedProbeDispatch.freeze(
            probe_id="immutable.research_run",
            transport_owner="database",
            operation="attempt_update",
            target_objects=("iros_research_runs",),
            subject_role="audit_permitted",
            fixture_id=fixture.fixture_id,
            mutation_field="status",
            expected_constraint="iros_research_runs_contract_immutable",
            rollback_assertion="required_and_verified",
        )
        contract = HostedVerificationExecutionContract.freeze(
            plan=plan,
            dispatches=(dispatch,),
            fixtures=(fixture,),
            inventory_sha256=INVENTORY_SHA256,
            constraint_index_sha256=CONSTRAINT_INDEX_SHA256,
        )
        now = datetime(2026, 8, 11, 11, 55, tzinfo=UTC)
        authorization = HostedVerificationAuthorization.freeze(
            authorization_id="authorization-iro-052-v3-mutation",
            issue_id="IRO-052",
            database_scope="iros_only",
            operator_id="operator-1",
            owner_subject_id="owner-subject",
            unrelated_subject_id="unrelated-subject",
            audit_subject_id="audit-subject",
            turn_id="turn-iro-052-v3",
            issued_at=now,
            expires_at=now + timedelta(minutes=15),
            authorized_scopes=("negative_constraint_probe",),
        )
        execution_authorization = HostedVerificationExecutionAuthorization.freeze(
            authorization=authorization,
            execution_contract=contract,
        )
        return contract, execution_authorization, authorization


if __name__ == "__main__":
    unittest.main()

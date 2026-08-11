from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from dataclasses import replace

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


INVENTORY_SHA256 = "1" * 64
CONSTRAINT_INDEX_SHA256 = "2" * 64


class HostedVerificationV3ContractTests(unittest.TestCase):
    def test_freezes_plan_dispatch_and_fixture_as_one_content_addressed_contract(
        self,
    ) -> None:
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

        self.assertEqual(
            contract.contract_version,
            "hosted-verification-execution-contract.v3",
        )
        self.assertEqual(contract.plan_sha256, plan.content_sha256)
        self.assertEqual(
            {
                len(contract.migration_manifest_sha256),
                len(contract.target_manifest_sha256),
                len(contract.dispatch_registry_sha256),
                len(contract.fixture_set_sha256),
                len(contract.content_sha256),
            },
            {64},
        )
        self.assertTrue(contract.has_valid_content_hash())

    def test_execution_authorization_binds_all_v3_contract_hashes(self) -> None:
        contract = self._read_contract()
        now = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
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

        bound = HostedVerificationExecutionAuthorization.freeze(
            authorization=authorization,
            execution_contract=contract,
        )

        self.assertEqual(bound.plan_sha256, contract.plan_sha256)
        self.assertEqual(
            bound.execution_contract_sha256,
            contract.content_sha256,
        )
        self.assertEqual(
            bound.dispatch_registry_sha256,
            contract.dispatch_registry_sha256,
        )
        self.assertEqual(bound.fixture_set_sha256, contract.fixture_set_sha256)
        self.assertTrue(bound.has_valid_content_hash())

    def test_execution_authorization_rejects_extra_scope(self) -> None:
        contract = self._read_contract()
        now = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
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
            authorized_scopes=(
                "owner_isolation_read",
                "database_advisor_read",
            ),
        )

        with self.assertRaisesRegex(
            ValueError,
            "authorization scopes do not match execution contract",
        ):
            HostedVerificationExecutionAuthorization.freeze(
                authorization=authorization,
                execution_contract=contract,
            )

    def test_mutating_dispatch_requires_transactional_fixture_and_rollback(
        self,
    ) -> None:
        fixture = HostedProbeFixture.freeze(
            fixture_id="fixture.immutable_run",
            setup_state="finalized_row",
            row_identity="immutable_run",
            target_owner_role="owner",
            cleanup_rule="none",
        )

        with self.assertRaisesRegex(
            ValueError,
            "mutating dispatch requires verified rollback",
        ):
            HostedProbeDispatch.freeze(
                probe_id="immutable.research_run",
                transport_owner="database",
                operation="attempt_update",
                target_objects=("iros_research_runs",),
                subject_role="audit_permitted",
                fixture_id=fixture.fixture_id,
                mutation_field="status",
                expected_constraint="iros_research_run_immutable",
                rollback_assertion="not_required",
            )

    def test_contract_rejects_mutating_fixture_without_transaction_cleanup(
        self,
    ) -> None:
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
            cleanup_rule="none",
        )
        dispatch = HostedProbeDispatch.freeze(
            probe_id="immutable.research_run",
            transport_owner="database",
            operation="attempt_update",
            target_objects=("iros_research_runs",),
            subject_role="audit_permitted",
            fixture_id=fixture.fixture_id,
            mutation_field="status",
            expected_constraint="iros_research_run_immutable",
            rollback_assertion="required_and_verified",
        )

        with self.assertRaisesRegex(
            ValueError,
            "mutating fixture cleanup is invalid",
        ):
            HostedVerificationExecutionContract.freeze(
                plan=plan,
                dispatches=(dispatch,),
                fixtures=(fixture,),
                inventory_sha256=INVENTORY_SHA256,
                constraint_index_sha256=CONSTRAINT_INDEX_SHA256,
            )

    def test_advisor_transport_owns_only_advisor_read_operation(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "advisor dispatch operation is invalid",
        ):
            HostedProbeDispatch.freeze(
                probe_id="advisor.iros_findings",
                transport_owner="advisor",
                operation="count_rows",
                target_objects=("iros_jobs",),
                subject_role="audit_permitted",
                fixture_id="fixture.advisor_findings",
                mutation_field=None,
                expected_constraint=None,
                rollback_assertion="not_required",
            )

    def test_duplicate_insert_requires_conflict_key_not_mutation_field(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "duplicate dispatch is invalid",
        ):
            HostedProbeDispatch.freeze(
                probe_id="duplicate.research_run",
                transport_owner="database",
                operation="attempt_duplicate_insert",
                target_objects=("iros_research_runs",),
                subject_role="audit_permitted",
                fixture_id="fixture.duplicate_run",
                mutation_field="status",
                expected_constraint="iros_research_runs_operator_idempotency_unique",
                rollback_assertion="required_and_verified",
            )

    def test_privileged_rpc_is_bound_to_exact_probe(self) -> None:
        with self.assertRaisesRegex(ValueError, "privileged RPC is invalid"):
            HostedProbeDispatch.freeze(
                probe_id="immutable.memo",
                transport_owner="database",
                operation="attempt_update",
                target_objects=("iros_committee_memos",),
                subject_role="audit_permitted",
                fixture_id="fixture.immutable_memo",
                mutation_field="requested_disposition",
                privileged_rpc="iros_run_hosted_negative_probe",
                expected_constraint="iros_committee_memos_immutable",
                rollback_assertion="required_and_verified",
            )

    def test_raw_access_event_is_residue_assertion_on_rpc_result(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "residue assertion is invalid",
        ):
            HostedProbeDispatch.freeze(
                probe_id="raw_audit.access_event",
                transport_owner="database",
                operation="assert_raw_access_residue",
                target_objects=("iros_read_raw_provider_payload",),
                subject_role="audit_permitted",
                fixture_id="fixture.raw_payload",
                mutation_field=None,
                expected_constraint=None,
                rollback_assertion="not_required",
            )

    def test_raw_access_residue_requires_source_probe_binding(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "residue source is invalid",
        ):
            HostedProbeDispatch.freeze(
                probe_id="raw_audit.access_event",
                transport_owner="database",
                operation="assert_raw_access_residue",
                target_objects=("iros_read_raw_provider_payload",),
                subject_role="audit_permitted",
                fixture_id="fixture.raw_payload",
                mutation_field=None,
                expected_constraint=None,
                residue_assertion="access_audit_event_id_and_accessed_at",
                rollback_assertion="not_required",
            )

    def test_contract_rejects_missing_raw_access_source_dispatch(self) -> None:
        plan = HostedVerificationPlan.freeze(
            probes=(
                HostedVerificationProbe(
                    probe_id="raw_audit.access_event",
                    category="raw_provider_audit",
                    required_scope="raw_provider_audit_probe",
                    expected_result_code="audit_event_recorded",
                    expected_count=1,
                ),
            ),
            target_objects=("iros_read_raw_provider_payload",),
        )
        fixture = HostedProbeFixture.freeze(
            fixture_id="fixture.raw_payload",
            setup_state="raw_provider_payload",
            row_identity="raw_payload",
            target_owner_role="owner",
            cleanup_rule="none",
        )
        dispatch = HostedProbeDispatch.freeze(
            probe_id="raw_audit.access_event",
            transport_owner="database",
            operation="assert_raw_access_residue",
            target_objects=("iros_read_raw_provider_payload",),
            subject_role="audit_permitted",
            fixture_id=fixture.fixture_id,
            mutation_field=None,
            expected_constraint=None,
            residue_assertion="access_audit_event_id_and_accessed_at",
            residue_source_probe_id="raw_audit.owner_permitted",
            rollback_assertion="not_required",
        )

        with self.assertRaisesRegex(ValueError, "source binding is invalid"):
            HostedVerificationExecutionContract.freeze(
                plan=plan,
                dispatches=(dispatch,),
                fixtures=(fixture,),
                inventory_sha256=INVENTORY_SHA256,
                constraint_index_sha256=CONSTRAINT_INDEX_SHA256,
            )

    def test_migration_history_requires_fixed_external_scope_reason(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "external scope reason is invalid",
        ):
            HostedProbeDispatch.freeze(
                probe_id="migration.linked_history",
                transport_owner="database",
                operation="read_migration_history",
                target_objects=(),
                subject_role="audit_permitted",
                fixture_id="fixture.migration_history",
                mutation_field=None,
                expected_constraint=None,
                rollback_assertion="not_required",
            )

    def test_contract_rejects_dispatch_target_count_drift(self) -> None:
        plan = HostedVerificationPlan.freeze(
            probes=(
                HostedVerificationProbe(
                    probe_id="access.owner",
                    category="owner_isolation",
                    required_scope="owner_isolation_read",
                    expected_result_code="owner_access_verified",
                    expected_count=2,
                ),
            ),
            target_objects=("iros_jobs", "iros_watchlist_items"),
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

        with self.assertRaisesRegex(ValueError, "target count is invalid"):
            HostedVerificationExecutionContract.freeze(
                plan=plan,
                dispatches=(dispatch,),
                fixtures=(fixture,),
                inventory_sha256=INVENTORY_SHA256,
                constraint_index_sha256=CONSTRAINT_INDEX_SHA256,
            )

    def test_immutable_probe_requires_finalized_fixture(self) -> None:
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
            setup_state="duplicate_key_row",
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

        with self.assertRaisesRegex(ValueError, "fixture is not finalized"):
            HostedVerificationExecutionContract.freeze(
                plan=plan,
                dispatches=(dispatch,),
                fixtures=(fixture,),
                inventory_sha256=INVENTORY_SHA256,
                constraint_index_sha256=CONSTRAINT_INDEX_SHA256,
            )

    def test_contract_rejects_direct_dispatch_hash_tampering(self) -> None:
        contract = self._read_contract()

        with self.assertRaisesRegex(
            ValueError,
            "dispatch hash is invalid",
        ):
            HostedVerificationExecutionContract.freeze(
                plan=HostedVerificationPlan.freeze(
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
                ),
                dispatches=(replace(contract.dispatches[0], content_sha256="0" * 64),),
                fixtures=contract.fixtures,
                inventory_sha256=INVENTORY_SHA256,
                constraint_index_sha256=CONSTRAINT_INDEX_SHA256,
            )

    def test_contract_rejects_duplicate_dispatch_ids(self) -> None:
        contract = self._read_contract()
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

        with self.assertRaisesRegex(
            ValueError,
            "dispatch IDs must be unique",
        ):
            HostedVerificationExecutionContract.freeze(
                plan=plan,
                dispatches=(contract.dispatches[0], contract.dispatches[0]),
                fixtures=contract.fixtures,
                inventory_sha256=INVENTORY_SHA256,
                constraint_index_sha256=CONSTRAINT_INDEX_SHA256,
            )

    def test_contract_rejects_unused_fixture(self) -> None:
        contract = self._read_contract()
        unused = HostedProbeFixture.freeze(
            fixture_id="fixture.unused_row",
            setup_state="owner_graph",
            row_identity="unused_row",
            target_owner_role="owner",
            cleanup_rule="none",
        )
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

        with self.assertRaisesRegex(
            ValueError,
            "fixture coverage is invalid",
        ):
            HostedVerificationExecutionContract.freeze(
                plan=plan,
                dispatches=contract.dispatches,
                fixtures=(*contract.fixtures, unused),
                inventory_sha256=INVENTORY_SHA256,
                constraint_index_sha256=CONSTRAINT_INDEX_SHA256,
            )

    def test_authorization_rejects_tampered_embedded_dispatch(self) -> None:
        contract = self._read_contract()
        tampered = replace(
            contract,
            dispatches=(replace(contract.dispatches[0], content_sha256="0" * 64),),
        )
        now = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
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

        with self.assertRaisesRegex(
            ValueError,
            "execution contract is invalid",
        ):
            HostedVerificationExecutionAuthorization.freeze(
                authorization=authorization,
                execution_contract=tampered,
            )

    @staticmethod
    def _read_contract() -> HostedVerificationExecutionContract:
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
        return HostedVerificationExecutionContract.freeze(
            plan=plan,
            dispatches=(dispatch,),
            fixtures=(fixture,),
            inventory_sha256=INVENTORY_SHA256,
            constraint_index_sha256=CONSTRAINT_INDEX_SHA256,
        )


if __name__ == "__main__":
    unittest.main()

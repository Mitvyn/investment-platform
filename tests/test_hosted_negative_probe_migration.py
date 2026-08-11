from __future__ import annotations

from pathlib import Path
import re
import unittest

from investment_research_os.migration_audit import audit_iros_migration_batch


MIGRATION = (
    Path(__file__).parents[1]
    / "supabase"
    / "migrations"
    / "20260811030426_iros_hosted_negative_probe_rpc.sql"
)


class HostedNegativeProbeMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sql = MIGRATION.read_text()
        cls.normalized = re.sub(r"\s+", " ", cls.sql.lower())

    def test_exposes_one_fixed_service_role_only_probe_rpc(self) -> None:
        signature = (
            r"public\.iros_run_hosted_negative_probe\(\s*"
            r"text, uuid, uuid, text, text, text\s*\)"
        )

        self.assertIn("security invoker", self.normalized)
        self.assertNotIn("security definer", self.normalized)
        self.assertIn("set search_path = ''", self.normalized)
        for role in ("public", "anon", "authenticated"):
            self.assertRegex(
                self.normalized,
                rf"revoke execute on function {signature} from {role}",
            )
        self.assertRegex(
            self.normalized,
            rf"grant execute on function {signature} to service_role",
        )
        self.assertNotRegex(
            self.normalized,
            r"grant\s+(insert|update|delete|all).*authenticated",
        )

    def test_probe_is_allowlisted_and_operator_scoped_without_dynamic_sql(self) -> None:
        self.assertIn("p_probe_id = 'immutable.research_run'", self.normalized)
        self.assertIn("unsupported hosted negative probe", self.normalized)
        self.assertIn("r.operator_id = p_operator_id", self.normalized)
        self.assertIn("r.id = p_target_id", self.normalized)
        self.assertIn("r.persistence_state = 'complete'", self.normalized)
        self.assertIn("p_fixture_state <> 'finalized_row'", self.normalized)
        self.assertIn("p_fixture_state is null", self.normalized)
        self.assertNotRegex(self.normalized, r"\bexecute\s+(format|p_)")
        self.assertNotIn("well_", self.normalized)

    def test_probe_forces_subtransaction_rollback_and_verifies_original_value(
        self,
    ) -> None:
        self.assertIn("set idempotency_key =", self.normalized)
        self.assertIn("get stacked diagnostics", self.normalized)
        self.assertIn("errcode = 'p9001'", self.normalized)
        self.assertIn("where r.operator_id = p_operator_id", self.normalized)
        self.assertIn("rollback_verified", self.normalized)
        self.assertIn("iros_research_runs_contract_immutable", self.normalized)
        self.assertIn("research run request contract is immutable", self.normalized)

    def test_authorization_hash_and_result_shape_fail_closed(self) -> None:
        self.assertIn("p_authorization_sha256 !~ '^[0-9a-f]{64}$'", self.normalized)
        for field in (
            "contract_version",
            "probe_id",
            "passed",
            "result_code",
            "expected_constraint",
            "observed_constraint",
            "sqlstate",
            "rollback_verified",
            "authorization_sha256",
            "operator_id",
            "target_id",
            "fixture_state",
            "request_sha256",
        ):
            self.assertIn(f"'{field}'", self.normalized)

    def test_migration_remains_iros_only(self) -> None:
        audit = audit_iros_migration_batch((MIGRATION,))

        self.assertTrue(audit.passed, audit.violations)
        self.assertNotRegex(self.normalized, r"public\.(?!iros_)[a-z_][a-z0-9_]*")


if __name__ == "__main__":
    unittest.main()

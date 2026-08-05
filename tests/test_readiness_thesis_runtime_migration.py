from __future__ import annotations

from pathlib import Path
import unittest

from investment_research_os.migration_audit import audit_iros_migration_batch


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260730030443_iros_readiness_thesis_runtime.sql"
)


class ReadinessThesisRuntimeMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sql = MIGRATION.read_text().lower()
        cls.compact = " ".join(cls.sql.split())

    def test_persists_readiness_and_thesis_as_one_idempotent_transaction(
        self,
    ) -> None:
        self.assertIn(
            "create function public.iros_persist_readiness_thesis_runtime",
            self.sql,
        )
        for table in (
            "iros_readiness_gate_results",
            "iros_readiness_checks",
            "iros_thesis_versions",
            "iros_thesis_creation_results",
        ):
            self.assertIn(f"insert into public.{table}", self.sql)
        self.assertIn("pg_advisory_xact_lock", self.sql)
        self.assertIn("'reused', true", self.compact)
        self.assertIn("'reused', false", self.compact)
        self.assertIn("conflicting readiness thesis runtime identity", self.sql)

    def test_exposes_owner_scoped_security_invoker_progress_view(self) -> None:
        self.assertIn(
            "create view public.iros_v_research_run_command_progress",
            self.sql,
        )
        self.assertIn("with (security_invoker = true)", self.sql)
        self.assertIn("'research_run_command_progress.v1'", self.sql)
        self.assertIn("completed_stages", self.sql)
        self.assertIn(
            "grant select on table "
            "public.iros_v_research_run_command_progress to authenticated",
            self.compact,
        )

    def test_runtime_is_service_only_and_iros_isolated(self) -> None:
        self.assertIn("security invoker", self.sql)
        self.assertNotIn("security definer", self.sql)
        self.assertIn(
            "revoke all on function "
            "public.iros_persist_readiness_thesis_runtime",
            self.compact,
        )
        self.assertIn(
            "grant execute on function "
            "public.iros_persist_readiness_thesis_runtime",
            self.compact,
        )
        self.assertNotIn("to anon", self.sql)
        self.assertNotIn("well_", self.sql)
        report = audit_iros_migration_batch((MIGRATION,))
        self.assertTrue(report.passed, report.violations)


if __name__ == "__main__":
    unittest.main()

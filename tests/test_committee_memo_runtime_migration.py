from __future__ import annotations

from pathlib import Path
import unittest

from investment_research_os.migration_audit import audit_iros_migration_batch


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260730030427_iros_committee_memo_runtime.sql"
)


class CommitteeMemoRuntimeMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sql = MIGRATION.read_text().lower()
        cls.compact = " ".join(cls.sql.split())

    def test_exposes_service_only_atomic_synthesis_runtime(self) -> None:
        functions = (
            "iros_begin_synthesis_execution_runtime",
            "iros_begin_synthesis_attempt_runtime",
            "iros_finish_synthesis_attempt_runtime",
            "iros_finalize_synthesis_execution_runtime",
        )

        for function in functions:
            self.assertIn(f"create function public.{function}", self.sql)
            self.assertIn(
                f"revoke all on function public.{function}",
                self.compact,
            )
            self.assertIn(
                f"grant execute on function public.{function}",
                self.compact,
            )

        self.assertGreaterEqual(self.sql.count("security invoker"), len(functions))
        self.assertNotIn("security definer", self.sql)
        self.assertNotIn("to anon", self.sql)
        self.assertNotIn("to authenticated", self.sql)
        self.assertNotIn("well_", self.sql)

    def test_attempt_reservation_payload_and_completion_are_atomic(self) -> None:
        self.assertIn(
            "create table public.iros_synthesis_budget_reservations",
            self.sql,
        )
        begin = self.sql[
            self.sql.index(
                "create function public.iros_begin_synthesis_attempt_runtime"
            ) : self.sql.index(
                "create function public.iros_finish_synthesis_attempt_runtime"
            )
        ]
        finish = self.sql[
            self.sql.index(
                "create function public.iros_finish_synthesis_attempt_runtime"
            ) : self.sql.index(
                "create function public.iros_finalize_synthesis_execution_runtime"
            )
        ]

        self.assertIn("insert into public.iros_synthesis_attempts", begin)
        self.assertIn("insert into public.iros_synthesis_attempt_payloads", begin)
        self.assertIn("public.iros_reserve_synthesis_budget(", begin)
        self.assertIn("public.iros_reconcile_synthesis_budget(", finish)
        self.assertLess(
            finish.index("public.iros_reconcile_synthesis_budget("),
            finish.index("update public.iros_synthesis_attempts"),
        )
        self.assertIn("$.**.reasoning_content", self.sql)
        self.assertIn("$.**.encrypted_content", self.sql)
        self.assertIn('@.type == "reasoning"', self.sql)

    def test_persists_reasoning_usage_and_passes_iros_audit(self) -> None:
        self.assertIn(
            "add column budget_policy_version text",
            self.sql,
        )
        self.assertIn("add column reasoning_tokens integer", self.sql)
        self.assertIn("add column usage_complete boolean", self.sql)
        self.assertIn("add column total_reasoning_tokens integer", self.sql)
        report = audit_iros_migration_batch((MIGRATION,))
        self.assertTrue(report.passed, report.violations)


if __name__ == "__main__":
    unittest.main()

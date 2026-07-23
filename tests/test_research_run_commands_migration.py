from __future__ import annotations

import unittest
from pathlib import Path

from investment_research_os.migration_audit import audit_iros_migration_batch


class ResearchRunCommandsMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        migrations = sorted(
            Path("supabase/migrations").glob("*_iros_research_run_commands.sql")
        )
        if len(migrations) != 1:
            raise AssertionError("expected one Research Run commands migration")
        cls.migration = migrations[0]
        cls.sql = cls.migration.read_text().lower()
        cls.compact_sql = " ".join(cls.sql.split())

    def test_creates_distinct_owner_scoped_blocked_command_receipt(self) -> None:
        self.assertIn(
            "create table public.iros_research_run_commands",
            self.sql,
        )
        self.assertIn(
            "references auth.users(id) on delete restrict",
            self.sql,
        )
        self.assertIn(
            "references public.iros_securities(operator_id, id) on delete restrict",
            self.compact_sql,
        )
        self.assertIn(
            "check (command_state = 'blocked')",
            self.sql,
        )
        self.assertIn(
            "operator_focus_normalized = regexp_replace( "
            "operator_focus_normalized, '[[:space:]]+', ' ', 'g' )",
            self.compact_sql,
        )
        self.assertNotIn("create table public.iros_jobs", self.sql)
        self.assertNotIn("well_", self.sql)

    def test_enqueue_rpc_derives_owner_and_validates_the_fixed_request(self) -> None:
        self.assertIn(
            "create function public.iros_enqueue_research_run_command(\n"
            "  p_security_id uuid,\n"
            "  p_as_of_cutoff timestamptz,\n"
            "  p_operator_focus text default null",
            self.sql,
        )
        self.assertIn("security definer", self.sql)
        self.assertIn("set search_path = ''", self.sql)
        self.assertIn("caller_id := (select auth.uid())", self.sql)
        self.assertNotIn("p_operator_id", self.sql)
        self.assertIn(
            "where s.operator_id = caller_id and s.id = p_security_id",
            self.compact_sql,
        )
        self.assertIn("length(p_operator_focus) > 2000", self.sql)
        self.assertIn(
            "regexp_replace(\n"
            "      btrim(coalesce(p_operator_focus, '')),\n"
            "      '[[:space:]]+',\n"
            "      ' ',\n"
            "      'g'\n"
            "    )",
            self.sql,
        )
        self.assertIn("operator focus cannot alter workflow behavior", self.sql)
        self.assertIn("p_as_of_cutoff > statement_timestamp()", self.sql)
        self.assertIn(
            "'biotech_moonshot_catalyst_assessment.v1'",
            self.sql,
        )
        self.assertIn("'biotech-moonshot-catalyst-v1'", self.sql)
        self.assertIn(
            "grant execute on function "
            "public.iros_enqueue_research_run_command(uuid, timestamptz, text) "
            "to authenticated",
            self.compact_sql,
        )

    def test_identical_request_reuses_server_hashed_blocked_receipt(self) -> None:
        self.assertIn("extensions.digest(", self.sql)
        self.assertIn("'sha256'", self.sql)
        self.assertIn("'hex'", self.sql)
        self.assertIn(
            "check (idempotency_key ~ '^[0-9a-f]{64}$')",
            self.sql,
        )
        self.assertIn(
            "unique (operator_id, idempotency_key)",
            self.sql,
        )
        self.assertIn(
            "on conflict (operator_id, idempotency_key) do nothing",
            self.sql,
        )
        self.assertIn(
            "where c.operator_id = caller_id "
            "and c.idempotency_key = selected_idempotency_key",
            self.compact_sql,
        )
        expected_blockers = (
            "generic_primary_source_pipeline_unavailable",
            "persistent_committee_worker_unavailable",
            "model_execution_inactive",
            "licensed_valuation_unavailable",
            "hosted_isolation_unverified",
        )
        for blocker in expected_blockers:
            self.assertEqual(self.sql.count(f"'{blocker}'"), 2)
        self.assertNotIn("perform public.iros_", self.sql)
        self.assertNotIn("insert into public.iros_research_runs", self.sql)
        self.assertNotIn("insert into public.iros_grader", self.sql)

    def test_authenticated_access_is_owner_select_plus_narrow_rpc_only(self) -> None:
        self.assertIn(
            "alter table public.iros_research_run_commands "
            "enable row level security",
            self.compact_sql,
        )
        self.assertEqual(
            self.sql.count(
                "create policy iros_research_run_commands_operator_select"
            ),
            1,
        )
        self.assertIn(
            "for select to authenticated "
            "using ((select auth.uid()) = operator_id)",
            self.compact_sql,
        )
        self.assertIn(
            "revoke all on table public.iros_research_run_commands "
            "from public, anon, authenticated",
            self.compact_sql,
        )
        self.assertIn(
            "grant select on table public.iros_research_run_commands "
            "to authenticated",
            self.compact_sql,
        )
        self.assertNotIn(
            "grant insert on table public.iros_research_run_commands "
            "to authenticated",
            self.compact_sql,
        )
        self.assertNotIn(
            "grant update on table public.iros_research_run_commands "
            "to authenticated",
            self.compact_sql,
        )
        self.assertNotIn(
            "grant delete on table public.iros_research_run_commands "
            "to authenticated",
            self.compact_sql,
        )

    def test_passes_shared_namespace_and_security_audit(self) -> None:
        report = audit_iros_migration_batch((self.migration,))

        self.assertTrue(report.passed, report.violations)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from investment_research_os.hosted_verification import (
    build_default_iros_hosted_verification_plan,
)
from investment_research_os.iros_constraint_index import (
    build_iros_constraint_index,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATHS = tuple(
    sorted((REPO_ROOT / "supabase" / "migrations").glob("*iros*.sql"))
)


class IrosConstraintIndexTests(unittest.TestCase):
    def test_derives_real_mutation_enforcers_from_current_migrations(self) -> None:
        index = build_iros_constraint_index(migration_paths=MIGRATION_PATHS)
        plan = build_default_iros_hosted_verification_plan(
            migration_paths=MIGRATION_PATHS
        )

        self.assertEqual(index.guarded_table_count, 56)
        self.assertEqual(index.named_unique_constraint_count, 118)
        self.assertEqual(index.unique_index_count, 3)
        self.assertEqual(index.named_unique_enforcer_count, 121)
        self.assertTrue(index.has_valid_content_hash())
        self.assertEqual(
            index.migration_manifest_sha256,
            plan.migration_manifest_sha256,
        )

        expected = {
            "iros_research_runs": (
                "iros_research_runs_contract_immutable",
                "iros_research_runs_operator_idempotency_unique",
            ),
            "iros_grader_executions": (
                "iros_grader_executions_z_immutable",
                "iros_grader_executions_key_unique",
            ),
            "iros_committee_results": (
                "iros_committee_results_z_immutable",
                "iros_committee_results_run_unique",
            ),
            "iros_committee_memos": (
                "iros_committee_memos_immutable",
                "iros_committee_memos_execution_unique",
            ),
            "iros_thesis_versions": (
                "iros_thesis_versions_z_immutable",
                "iros_thesis_versions_run_unique",
            ),
            "iros_operator_decisions": (
                "iros_operator_decisions_z_immutable",
                "iros_operator_decisions_idempotency_unique",
            ),
            "iros_workflow_commands": (
                "iros_workflow_commands_z_immutable",
                "iros_workflow_commands_event_type_unique",
            ),
            "iros_market_series": (
                "iros_market_series_immutable",
                "iros_market_series_content_unique",
            ),
        }
        for table_name, (trigger_name, unique_name) in expected.items():
            with self.subTest(table_name=table_name):
                entry = index.require_table(table_name)
                self.assertIn(trigger_name, entry.trigger_names)
                self.assertIn(unique_name, entry.unique_enforcer_names)
                self.assertTrue(index.contains_name(table_name, trigger_name))
                self.assertTrue(index.contains_name(table_name, unique_name))

        with self.assertRaisesRegex(ValueError, "constraint name is absent"):
            index.require_name(
                "iros_research_runs",
                "immutable_research_run_enforced",
            )

    def test_ignores_names_in_comments_and_literals(self) -> None:
        migration_sql = """\
create table public.iros_jobs (
  id uuid,
  constraint iros_jobs_key_unique unique (id),
  constraint iros_jobs_id_check check (id is not null)
);
create function public.iros_reject_job_change()
returns trigger language plpgsql set search_path = '' as $$
begin return new; end;
$$;
create trigger iros_jobs_immutable
before update on public.iros_jobs
for each row execute function public.iros_reject_job_change();
-- create unique index iros_comment_unique on public.iros_jobs (id);
select 'constraint iros_literal_unique unique (id)';
revoke execute on function public.iros_reject_job_change()
from public, anon, authenticated;
grant execute on function public.iros_reject_job_change() to service_role;
alter table public.iros_jobs enable row level security;
revoke all on table public.iros_jobs from anon, authenticated;
"""
        with tempfile.TemporaryDirectory() as directory:
            migration = Path(directory) / "20260811000000_iros_constraints.sql"
            migration.write_text(migration_sql)
            index = build_iros_constraint_index(migration_paths=(migration,))

        entry = index.require_table("iros_jobs")
        self.assertEqual(entry.trigger_names, ("iros_jobs_immutable",))
        self.assertEqual(entry.unique_enforcer_names, ("iros_jobs_key_unique",))
        self.assertEqual(entry.check_constraint_names, ("iros_jobs_id_check",))
        self.assertFalse(index.contains_name("iros_jobs", "iros_comment_unique"))
        self.assertFalse(index.contains_name("iros_jobs", "iros_literal_unique"))


if __name__ == "__main__":
    unittest.main()

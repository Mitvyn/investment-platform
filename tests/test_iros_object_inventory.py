from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from investment_research_os.hosted_verification import (
    IROS_HOSTED_VERIFICATION_TARGETS,
    build_default_iros_hosted_verification_plan,
)
from investment_research_os.iros_object_inventory import (
    build_iros_object_inventory,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATHS = tuple(
    sorted((REPO_ROOT / "supabase" / "migrations").glob("*iros*.sql"))
)

SYNTHETIC_MIGRATION = """\
create table public.iros_jobs (id uuid);
alter table public.iros_jobs enable row level security;
create policy iros_jobs_owner_select on public.iros_jobs for select
to authenticated using (true);
revoke all on table public.iros_jobs from anon, authenticated;
grant select on table public.iros_jobs to authenticated;
revoke select on table public.iros_jobs from authenticated;
grant select on table public.iros_jobs to service_role;

create view public.iros_v_jobs
with (security_invoker = true)
as select id from public.iros_jobs;
revoke all on table public.iros_v_jobs from anon, authenticated;
grant select on table public.iros_v_jobs to authenticated;

create function public.iros_claim_job()
returns void
language sql
security definer
set search_path = ''
as $$ select null $$;
revoke execute on function public.iros_claim_job()
from public, anon, authenticated;
grant execute on function public.iros_claim_job() to authenticated;
"""


class IrosObjectInventoryTests(unittest.TestCase):
    def test_derives_complete_current_migration_surface(self) -> None:
        inventory = build_iros_object_inventory(migration_paths=MIGRATION_PATHS)
        plan = build_default_iros_hosted_verification_plan(
            migration_paths=MIGRATION_PATHS
        )

        self.assertEqual(inventory.declared_count, 232)
        self.assertEqual(
            inventory.kind_counts, {"table": 67, "view": 38, "function": 127}
        )
        self.assertEqual(inventory.client_exposed_count, 102)
        self.assertEqual(
            inventory.client_exposed_role_counts, {"anon": 0, "authenticated": 102}
        )
        self.assertEqual(inventory.deny_all_probe_count, 6)
        self.assertEqual(inventory.rls_enabled_table_count, 67)
        self.assertEqual(inventory.rls_forced_table_count, 0)
        self.assertEqual(inventory.security_invoker_view_count, 38)
        self.assertEqual(
            {
                entry.object_name
                for entry in inventory.entries
                if entry.security_definer is True
            },
            {
                "iros_enqueue_research_run_command",
                "iros_enqueue_research_run_command_v2",
                "iros_enqueue_security_registration",
                "iros_finalize_market_series",
                "iros_persist_portfolio_broker_snapshot",
                "iros_read_raw_provider_payload",
            },
        )
        self.assertTrue(inventory.has_valid_content_hash())
        self.assertEqual(
            inventory.migration_manifest_sha256,
            plan.migration_manifest_sha256,
        )

        by_name = inventory.entries_by_name
        self.assertTrue(set(IROS_HOSTED_VERIFICATION_TARGETS) <= set(by_name))
        self.assertEqual(
            by_name["iros_run_hosted_negative_probe"].service_role_privileges,
            ("execute",),
        )
        self.assertEqual(
            by_name["iros_run_hosted_negative_probe"].authenticated_privileges,
            (),
        )
        self.assertEqual(
            by_name["iros_persist_portfolio_broker_snapshot"].authenticated_privileges,
            ("execute",),
        )
        self.assertEqual(
            by_name["iros_persist_portfolio_broker_snapshot"].service_role_privileges,
            (),
        )
        self.assertFalse(by_name["iros_run_hosted_negative_probe"].security_definer)
        self.assertEqual(
            by_name["iros_research_runs"].service_role_privileges,
            ("delete", "insert", "select", "update"),
        )
        self.assertEqual(
            {
                entry.object_name
                for entry in inventory.entries
                if entry.reason_code == "deny_all_probe_required"
            },
            {
                "iros_model_attempt_payloads",
                "iros_provider_input_token_preflights",
                "iros_raw_provider_payload_access_events",
                "iros_synthesis_attempt_payloads",
                "iros_valuation_other_claim_components",
                "iros_workflow_configs",
            },
        )
        self.assertIn(
            "explicitly_revoked",
            by_name["iros_model_attempt_payloads"].grant_history_reason_codes,
        )
        for table_name in (
            "iros_research_runs",
            "iros_grader_executions",
            "iros_committee_results",
            "iros_committee_memos",
            "iros_thesis_versions",
            "iros_operator_decisions",
            "iros_workflow_commands",
            "iros_market_series",
            "iros_readiness_gate_results",
        ):
            with self.subTest(table_name=table_name):
                self.assertEqual(
                    by_name[table_name].authenticated_privileges,
                    ("select",),
                )

    def test_replays_grants_and_revokes_in_statement_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            migration = Path(directory) / "20260811000000_iros_inventory.sql"
            migration.write_text(SYNTHETIC_MIGRATION)

            inventory = build_iros_object_inventory(migration_paths=(migration,))

        jobs = inventory.entries_by_name["iros_jobs"]
        self.assertEqual(jobs.exposed_roles, ())
        self.assertEqual(jobs.reason_code, "service_role_only")
        self.assertIn("explicitly_revoked", jobs.grant_history_reason_codes)
        self.assertEqual(
            inventory.entries_by_name["iros_v_jobs"].exposed_roles,
            ("authenticated",),
        )
        function = inventory.entries_by_name["iros_claim_job"]
        self.assertEqual(function.exposed_roles, ("authenticated",))
        self.assertTrue(function.security_definer)

    def test_policy_change_changes_inventory_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            migration = Path(directory) / "20260811000000_iros_inventory.sql"
            migration.write_text(SYNTHETIC_MIGRATION)
            original = build_iros_object_inventory(migration_paths=(migration,))
            migration.write_text(
                SYNTHETIC_MIGRATION.replace(
                    "create policy iros_jobs_owner_select on public.iros_jobs for select\n"
                    "to authenticated using (true);\n",
                    "",
                )
            )
            changed = build_iros_object_inventory(migration_paths=(migration,))

        self.assertNotEqual(original.content_sha256, changed.content_sha256)
        self.assertEqual(changed.entries_by_name["iros_jobs"].policy_count, 0)

    def test_rejects_non_iros_migration_surface(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            migration = Path(directory) / "20260811000000_iros_inventory.sql"
            migration.write_text(
                SYNTHETIC_MIGRATION
                + "\ngrant select on table public.well_sessions to authenticated;\n"
            )

            with self.assertRaisesRegex(ValueError, "migration audit failed"):
                build_iros_object_inventory(migration_paths=(migration,))


if __name__ == "__main__":
    unittest.main()

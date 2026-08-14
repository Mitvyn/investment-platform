from __future__ import annotations

from pathlib import Path
import re
import unittest

from investment_research_os.migration_audit import audit_iros_migration_batch


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "supabase" / "migrations"


def migration_sql() -> str:
    matches = sorted(MIGRATIONS.glob("*_iros_research_run_capture_command_v2.sql"))
    if len(matches) != 1:
        raise AssertionError(
            "expected one iros_research_run_capture_command_v2 migration"
        )
    return matches[0].read_text().lower()


class ResearchRunCaptureCommandV2MigrationTests(unittest.TestCase):
    def test_versions_command_identity_without_rewriting_v1_history(self) -> None:
        sql = migration_sql()
        compact = " ".join(sql.split())

        self.assertIn("add column capture_id uuid", compact)
        self.assertIn("add column capture_revision integer", compact)
        self.assertIn("add column capture_content_hash text", compact)
        self.assertRegex(
            compact,
            r"contract_version = 'research_run_command_receipt\.v1'.{0,240}"
            r"capture_id is null.{0,160}capture_revision is null.{0,160}"
            r"capture_content_hash is null",
        )
        self.assertRegex(
            compact,
            r"contract_version = 'research_run_command_receipt\.v2'.{0,240}"
            r"capture_id is not null.{0,160}capture_revision is not null.{0,160}"
            r"capture_revision > 0.{0,160}capture_content_hash is not null.{0,160}"
            r"capture_content_hash ~ '\^\[0-9a-f\]\{64\}\$'",
        )
        self.assertNotRegex(
            compact,
            r"update public\.iros_research_run_commands\s+set\s+capture_",
        )
        self.assertNotIn("delete from public.iros_research_run_commands", compact)

    def test_authenticated_enqueue_binds_exact_capture_identity(self) -> None:
        sql = migration_sql()
        enqueue = _function_body(sql, "iros_enqueue_research_run_command_v2")
        compact = " ".join(enqueue.split())

        self.assertIn("p_capture_id uuid", compact)
        self.assertIn("p_capture_revision integer", compact)
        self.assertIn("p_capture_content_hash text", compact)
        self.assertIn("caller_id := (select auth.uid())", compact)
        self.assertIn("authenticated operator required", compact)
        self.assertIn("unsupported research workflow identity", compact)
        self.assertIn("registered security is unavailable", compact)
        self.assertIn("as-of cutoff is invalid", compact)
        self.assertIn("capture identity is invalid", compact)
        self.assertRegex(
            compact,
            r"concat_ws\(.{0,700}p_capture_id::text.{0,160}"
            r"p_capture_revision::text.{0,160}p_capture_content_hash",
        )
        self.assertIn("'research_run_command_receipt.v2'", compact)
        self.assertIn("'queued'", compact)
        self.assertIn("'{}'::text[]", compact)
        self.assertIn("on conflict (operator_id, idempotency_key) do nothing", compact)
        for predicate in (
            "selected_command.capture_id is distinct from p_capture_id",
            "selected_command.capture_revision is distinct from p_capture_revision",
            "selected_command.capture_content_hash is distinct from "
            "p_capture_content_hash",
        ):
            self.assertIn(predicate, compact)

        self.assertRegex(
            sql,
            r"revoke all on function\s+public\."
            r"iros_enqueue_research_run_command_v2\([^;]+\)\s+"
            r"from public,\s*anon,\s*authenticated",
        )
        self.assertRegex(
            sql,
            r"grant execute on function\s+public\."
            r"iros_enqueue_research_run_command_v2\([^;]+\)\s+"
            r"to authenticated",
        )

    def test_only_v2_commands_can_enter_or_be_claimed_for_execution(self) -> None:
        sql = migration_sql()
        compact_sql = " ".join(sql.split())
        guard = _function_body(
            sql,
            "iros_guard_research_run_command_v1_activation",
        )
        claim = _function_body(sql, "iros_claim_research_run_command_v2")
        compact_claim = " ".join(claim.split())

        self.assertIn("new.contract_version = 'research_run_command_receipt.v1'", guard)
        self.assertIn("new.command_state in ('queued', 'running')", guard)
        self.assertIn("tg_op = 'insert'", guard)
        self.assertIn("old.command_state is distinct from new.command_state", guard)
        self.assertIn("v1 research run commands cannot be activated", guard)
        self.assertIn(
            "before insert or update on public.iros_research_run_commands",
            compact_sql,
        )

        self.assertGreaterEqual(
            compact_claim.count(
                "command.contract_version = 'research_run_command_receipt.v2'"
            ),
            3,
        )
        for field in (
            "capture_id uuid",
            "capture_revision integer",
            "capture_content_hash text",
            "selected_command.capture_id",
            "selected_command.capture_revision",
            "selected_command.capture_content_hash",
        ):
            self.assertIn(field, compact_claim)
        self.assertIn("for update skip locked", compact_claim)

        self.assertIn(
            "revoke all on function public.iros_claim_research_run_command(text) "
            "from service_role",
            compact_sql,
        )
        self.assertIn(
            "revoke all on function public.iros_enqueue_research_run_command( "
            "uuid, timestamptz, text ) from public, anon, authenticated",
            compact_sql,
        )
        self.assertIn(
            "revoke all on function public.iros_enqueue_research_run_command( "
            "uuid, timestamptz, text, text, text ) "
            "from public, anon, authenticated",
            compact_sql,
        )
        self.assertRegex(
            sql,
            r"revoke all on function\s+public\."
            r"iros_claim_research_run_command_v2\(text\)\s+"
            r"from public,\s*anon,\s*authenticated",
        )
        self.assertRegex(
            sql,
            r"grant execute on function\s+public\."
            r"iros_claim_research_run_command_v2\(text\)\s+"
            r"to service_role",
        )
        self.assertNotRegex(
            sql,
            r"grant execute on function\s+public\."
            r"iros_claim_research_run_command_v2\(text\)\s+"
            r"to (?:anon|authenticated)",
        )

    def test_capture_bound_command_identity_is_immutable_after_enqueue(self) -> None:
        sql = migration_sql()
        compact_sql = " ".join(sql.split())
        guard = _function_body(
            sql,
            "iros_enforce_research_run_command_identity_immutable",
        )
        compact_guard = " ".join(guard.split())

        for field in (
            "operator_id",
            "security_id",
            "contract_version",
            "question_type_version",
            "workflow_config_version",
            "as_of_cutoff",
            "operator_focus_normalized",
            "idempotency_key",
            "capture_id",
            "capture_revision",
            "capture_content_hash",
            "created_at",
        ):
            self.assertIn(
                f"new.{field} is distinct from old.{field}",
                compact_guard,
            )
        self.assertIn("research run command identity is immutable", compact_guard)
        self.assertIn(
            "before update on public.iros_research_run_commands",
            compact_sql,
        )

    def test_existing_v1_attempts_and_checkpoints_are_quarantined(self) -> None:
        sql = migration_sql()
        compact_sql = " ".join(sql.split())
        guard = " ".join(
            _function_body(
                sql,
                "iros_enforce_research_run_command_v2_runtime",
            ).split()
        )

        self.assertIn("if not exists", guard)
        self.assertIn(
            "command.contract_version = 'research_run_command_receipt.v2'",
            guard,
        )
        self.assertIn("v1 research run command runtime is quarantined", guard)
        self.assertIn(
            "before insert or update on public.iros_research_run_command_attempts",
            compact_sql,
        )
        self.assertIn(
            "before insert on public.iros_research_run_command_checkpoints",
            compact_sql,
        )

    def test_passes_shared_namespace_and_security_audit(self) -> None:
        path = next(iter(MIGRATIONS.glob("*_iros_research_run_capture_command_v2.sql")))
        report = audit_iros_migration_batch((path,))

        self.assertTrue(report.passed, report.violations)
        self.assertNotIn("well_", path.read_text().lower())


def _function_body(sql: str, name: str) -> str:
    match = re.search(
        rf"create function public\.{re.escape(name)}\(.*?\n\$\$;\n",
        sql,
        flags=re.DOTALL,
    )
    if match is None:
        raise AssertionError(f"missing function {name}")
    return match.group(0)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from pathlib import Path
import re
import unittest

from investment_research_os.migration_audit import audit_iros_migration_batch


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "supabase" / "migrations"


def migration_sql() -> str:
    matches = sorted(MIGRATIONS.glob("*_iros_research_run_command_runtime.sql"))
    if len(matches) != 1:
        raise AssertionError("expected one iros_research_run_command_runtime migration")
    return matches[0].read_text()


class PersistentCommitteeWorkerMigrationTests(unittest.TestCase):
    def test_adds_bounded_lease_and_checkpoint_state_without_cross_project_sql(
        self,
    ) -> None:
        sql = migration_sql()

        self.assertIn(
            "alter table public.iros_research_run_commands",
            sql,
        )
        self.assertIn(
            "create table public.iros_research_run_command_attempts",
            sql,
        )
        self.assertIn(
            "create table public.iros_research_run_command_checkpoints",
            sql,
        )
        self.assertRegex(
            sql,
            r"command_state\s+in\s*\(\s*"
            r"'blocked',\s*'queued',\s*'running',\s*'completed',\s*'failed'",
        )
        self.assertIn(
            "constraint iros_research_run_commands_chronology",
            sql,
        )
        self.assertRegex(sql, r"attempt_number\s+between\s+1\s+and\s+2")
        self.assertIn("lease_token uuid not null", sql)
        self.assertIn("lease_expires_at timestamptz not null", sql)
        self.assertIn(
            "unique (operator_id, command_id, stage)",
            sql,
        )
        self.assertIn(
            "unique (operator_id, id, command_id)",
            sql,
        )
        self.assertIn(
            "foreign key (operator_id, attempt_id, command_id)",
            sql,
        )
        self.assertNotIn("alter column finished_at drop default", sql)
        self.assertNotIn("well_", sql.lower())

    def test_keeps_launcher_blocked_and_runtime_requeue_receipt_valid(self) -> None:
        sql = migration_sql()
        claim = _function_body(sql, "iros_claim_research_run_command")
        failure = _function_body(sql, "iros_fail_research_run_command")

        self.assertNotIn(
            "create or replace function public.iros_enqueue_research_run_command",
            sql,
        )
        for body in (claim, failure):
            queued_update = re.search(
                r"set\s+command_state = 'queued'.*?"
                r"research_run_id = null,.*?"
                r"started_at = null,.*?"
                r"finished_at = null,",
                body,
                flags=re.DOTALL,
            )
            self.assertIsNotNone(queued_update)

    def test_claim_uses_skip_locked_and_returns_exact_restart_contract(
        self,
    ) -> None:
        sql = migration_sql()
        claim = _function_body(sql, "iros_claim_research_run_command")

        self.assertIn("for update skip locked", claim)
        self.assertIn("'worker_lease_expired'", claim)
        self.assertIn("attempt_number < 2", claim)
        self.assertIn("gen_random_uuid()", claim)
        self.assertIn("lease_expires_at", claim)
        self.assertRegex(
            claim,
            r"array\[\s*'research_run',\s*'evidence_bundle',\s*"
            r"'valuation_snapshot',\s*'grader_committee',\s*"
            r"'committee_memo',\s*'readiness_thesis'\s*\]::text\[\]",
        )
        for field in (
            "command_id",
            "operator_id",
            "security_id",
            "question_type_version",
            "workflow_config_version",
            "as_of_cutoff",
            "operator_focus_normalized",
            "attempt_id",
            "attempt_number",
            "lease_token",
            "next_stage",
            "completed_stages",
            "research_run_id",
        ):
            self.assertIn(field, claim)

    def test_claim_resumes_same_workers_unexpired_attempt_after_checkpoint(
        self,
    ) -> None:
        claim = _function_body(
            migration_sql(),
            "iros_claim_research_run_command",
        )

        resume = re.search(
            r"attempt\.worker_id = selected_worker_id.*?"
            r"attempt\.attempt_state = 'running'.*?"
            r"attempt\.lease_expires_at > statement_timestamp\(\).*?"
            r"return query",
            claim,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(resume)
        self.assertLess(
            claim.index("attempt.worker_id = selected_worker_id"),
            claim.index("where command.command_state = 'queued'"),
        )

    def test_claim_fences_one_active_stage_per_attempt(self) -> None:
        sql = migration_sql()
        claim = _function_body(sql, "iros_claim_research_run_command")

        self.assertIn("active_stage text", sql)
        self.assertIn("active_stage_claimed_at timestamptz", sql)
        self.assertIn("attempt.active_stage is null", claim)
        self.assertIn("active_stage = selected_next_stage", claim)
        self.assertIn("active_stage_claimed_at = statement_timestamp()", claim)
        self.assertIn("active_stage,", claim)
        self.assertIn("active_stage_claimed_at", claim)

    def test_claim_uses_command_then_attempt_lock_order(self) -> None:
        claim = _function_body(
            migration_sql(),
            "iros_claim_research_run_command",
        )

        self.assertNotIn("for update of attempt, command", claim)
        self.assertRegex(
            claim,
            r"(?s)select command\.\* into selected_command.*?"
            r"command\.command_state = 'running'.*?"
            r"for update of command skip locked.*?"
            r"select attempt\.\* into strict selected_attempt.*?"
            r"for update",
        )

    def test_stage_fence_controls_renewal_checkpoint_and_failure(self) -> None:
        sql = migration_sql()
        renewal = _function_body(
            sql,
            "iros_renew_research_run_command_lease",
        )
        checkpoint = _function_body(
            sql,
            "iros_checkpoint_research_run_command",
        )
        failure = _function_body(sql, "iros_fail_research_run_command")

        self.assertIn(
            "selected_attempt.active_stage is distinct from selected_stage",
            renewal,
        )
        for body in (checkpoint, failure):
            self.assertIn(
                "selected_attempt.active_stage is distinct from selected_stage",
                body,
            )
            self.assertIn("active_stage = null", body)
            self.assertIn("active_stage_claimed_at = null", body)

    def test_active_stage_cannot_be_replaced_without_checkpoint_or_failure(
        self,
    ) -> None:
        guard = _function_body(
            migration_sql(),
            "iros_guard_research_run_command_attempt_change",
        )

        self.assertRegex(
            guard,
            r"old\.active_stage is not null\s+"
            r"and new\.active_stage is not null",
        )
        self.assertIn(
            "new.active_stage is distinct from old.active_stage",
            guard,
        )
        self.assertRegex(
            guard,
            r"new\.active_stage_claimed_at\s+"
            r"is distinct from old\.active_stage_claimed_at",
        )

    def test_checkpoint_is_ordered_idempotent_and_binds_research_run(self) -> None:
        sql = migration_sql()
        checkpoint = _function_body(
            sql,
            "iros_checkpoint_research_run_command",
        )

        self.assertIn(
            "expected_ordinal := array_position(stage_order, selected_stage)::smallint",
            checkpoint,
        )
        self.assertIn("conflicting research run checkpoint", checkpoint)
        self.assertIn("conflicting command checkpoint", checkpoint)
        self.assertIn(
            "research_run_id = selected_research_run_id",
            checkpoint,
        )
        self.assertIn("command_state = 'completed'", checkpoint)
        self.assertIn(
            "insert into public.iros_research_run_command_checkpoints",
            checkpoint,
        )
        self.assertIn("for update", checkpoint)
        self.assertLess(
            checkpoint.index("select command.* into strict selected_command"),
            checkpoint.index("select checkpoint.* into existing_checkpoint"),
        )

    def test_every_checkpoint_insert_runs_universal_artifact_validation(
        self,
    ) -> None:
        sql = migration_sql()
        validator = _function_body(
            sql,
            "iros_validate_research_run_command_checkpoint_insert",
        )

        self.assertIn(
            "create trigger iros_research_run_command_checkpoints_validate",
            sql,
        )
        self.assertRegex(
            sql,
            r"revoke all on function\s+public\."
            r"iros_validate_research_run_command_checkpoint_insert\(\)\s+"
            r"from public,\s*anon,\s*authenticated",
        )
        self.assertRegex(
            sql,
            r"before insert on "
            r"public\.iros_research_run_command_checkpoints\s+"
            r"for each row\s+execute function "
            r"public\.iros_validate_research_run_command_checkpoint_insert",
        )
        self.assertIn("for update", validator)
        self.assertIn(
            "selected_attempt.active_stage is distinct from new.stage",
            validator,
        )
        self.assertIn("new.stage is distinct from expected_stage", validator)
        self.assertIn(
            "new.stage_ordinal is distinct from expected_ordinal",
            validator,
        )
        for artifact_table in (
            "iros_research_runs",
            "iros_research_run_evidence_bundles",
            "iros_evidence_bundles",
            "iros_valuation_snapshots",
            "iros_committee_results",
            "iros_committee_memos",
            "iros_thesis_creation_results",
        ):
            self.assertIn(artifact_table, validator)

    def test_checkpoint_validator_preserves_exact_bundle_and_committee_chain(
        self,
    ) -> None:
        validator = _function_body(
            migration_sql(),
            "iros_validate_research_run_command_checkpoint_insert",
        )
        validator = re.sub(r"\s+", " ", validator)

        for predicate in (
            "snapshot.evidence_bundle_id = bundle_checkpoint.artifact_id",
            "snapshot.evidence_bundle_hash = bundle.bundle_hash",
            "committee.evidence_bundle_id = bundle_checkpoint.artifact_id",
            "committee.evidence_bundle_hash = bundle.bundle_hash",
            "committee.workflow_config_version = "
            "selected_command.workflow_config_version",
            "memo.evidence_bundle_id = bundle_checkpoint.artifact_id",
            "memo.evidence_bundle_hash = bundle.bundle_hash",
            "memo.workflow_config_version = selected_command.workflow_config_version",
            "readiness.evidence_bundle_id = bundle_checkpoint.artifact_id",
            "readiness.evidence_bundle_hash = bundle.bundle_hash",
            "readiness.committee_result_id = committee_checkpoint.artifact_id",
            "creation.committee_result_id = readiness.committee_result_id",
        ):
            self.assertIn(predicate, validator)

    def test_failure_requeues_once_then_terminates(self) -> None:
        sql = migration_sql()
        failure = _function_body(sql, "iros_fail_research_run_command")

        self.assertIn("selected_retryable", failure)
        self.assertIn("attempt_number < 2", failure)
        self.assertIn("command_state = 'queued'", failure)
        self.assertIn("command_state = 'failed'", failure)
        self.assertIn("failure_stage", failure)
        self.assertIn("error_code", failure)
        self.assertIn(
            "research_run_id = selected_research_run_id",
            failure,
        )
        self.assertIn("retryable = selected_retryable,", failure)
        self.assertNotIn(
            "retryable = selected_retryable and selected_attempt.attempt_number < 2",
            failure,
        )
        self.assertIn("for update", failure)

    def test_runtime_functions_are_service_only_security_invoker(self) -> None:
        sql = migration_sql()

        for function_name in (
            "iros_claim_research_run_command",
            "iros_renew_research_run_command_lease",
            "iros_checkpoint_research_run_command",
            "iros_fail_research_run_command",
        ):
            body = _function_body(sql, function_name)
            self.assertIn("security invoker", body)
            self.assertIn("set search_path = ''", body)
            self.assertRegex(
                sql,
                rf"revoke all on function\s+public\.{function_name}\([^;]+"
                rf"\)\s+from public,\s*anon,\s*authenticated",
            )
            self.assertRegex(
                sql,
                rf"grant execute on function\s+public\.{function_name}\([^;]+"
                rf"\)\s+to service_role",
            )

        self.assertNotRegex(
            sql,
            r"grant execute on function public\.iros_"
            r"(claim|checkpoint|fail)_research_run_command"
            r"\([^;]+\)\s+to (anon|authenticated)",
        )

    def test_lease_renewal_is_fenced_service_only_and_bounded(self) -> None:
        sql = migration_sql()
        renewal = _function_body(
            sql,
            "iros_renew_research_run_command_lease",
        )

        self.assertIn("selected_command_id", renewal)
        self.assertIn("selected_attempt_id", renewal)
        self.assertIn("selected_lease_token", renewal)
        self.assertIn("selected_stage", renewal)
        self.assertIn("attempt_state <> 'running'", renewal)
        self.assertIn("command_state <> 'running'", renewal)
        self.assertIn(
            "selected_attempt.active_stage is distinct from selected_stage",
            renewal,
        )
        self.assertIn("lease_expires_at <= statement_timestamp()", renewal)
        self.assertIn("lease_started_at + interval '1 hour'", renewal)
        self.assertIn("statement_timestamp() + interval '5 minutes'", renewal)

    def test_passes_shared_namespace_and_security_audit(self) -> None:
        matches = tuple(MIGRATIONS.glob("*_iros_research_run_command_runtime.sql"))

        report = audit_iros_migration_batch(matches)

        self.assertTrue(report.passed, report.violations)


def _function_body(sql: str, name: str) -> str:
    match = re.search(
        rf"create function public\.{re.escape(name)}\("
        rf".*?\n\$\$;\n",
        sql,
        flags=re.DOTALL,
    )
    if match is None:
        raise AssertionError(f"missing function {name}")
    return match.group(0).lower()


if __name__ == "__main__":
    unittest.main()

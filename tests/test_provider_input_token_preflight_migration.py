from __future__ import annotations

from pathlib import Path
import unittest

from investment_research_os.migration_audit import audit_iros_migration_batch


class ProviderInputTokenPreflightMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.path = Path(
            "supabase/migrations/"
            "20260803131124_iros_provider_input_token_preflight.sql"
        )
        cls.sql = cls.path.read_text().lower()
        cls.compact_sql = " ".join(cls.sql.split())

    def test_passes_standalone_iros_migration_audit(self) -> None:
        report = audit_iros_migration_batch((self.path,))

        self.assertTrue(report.passed, report.violations)

    def test_creates_private_owner_and_attempt_scoped_preflight_table(self) -> None:
        self.assertIn(
            "create table public.iros_provider_input_token_preflights",
            self.sql,
        )
        self.assertIn(
            "references public.iros_research_runs(operator_id, id)",
            self.compact_sql,
        )
        self.assertIn(
            "references public.iros_grader_attempts(operator_id, id)",
            self.compact_sql,
        )
        self.assertIn(
            "references public.iros_synthesis_attempts(operator_id, id)",
            self.compact_sql,
        )
        self.assertIn(
            "unique (operator_id, attempt_kind, attempt_id)",
            self.compact_sql,
        )
        self.assertIn(
            "alter table public.iros_provider_input_token_preflights "
            "enable row level security",
            self.compact_sql,
        )
        self.assertNotIn(
            "create policy iros_provider_input_token_preflights",
            self.sql,
        )

    def test_enforces_hash_request_redaction_and_terminal_state_shapes(self) -> None:
        for fragment in (
            "execution_identity ~ '^[0-9a-f]{64}$'",
            "request_hash ~ '^[0-9a-f]{64}$'",
            "input_payload_sha256 ~ '^[0-9a-f]{64}$'",
            "provider = 'openai'",
            "sanitized_request ->> 'url' = 'https://api.openai.com/v1/responses/input_tokens'",
            "input_token_cap > 0",
            "sanitized_request -> 'headers' ->> 'authorization' = '[redacted]'",
            "sanitized_request -> 'payload' ? 'model'",
            "not jsonb_path_exists( sanitized_request, '$.**.reasoning_content' )",
            "not jsonb_path_exists( sanitized_request, '$.**.encrypted_content' )",
            "state = 'pending'",
            "state = 'passed'",
            "state = 'blocked'",
            "state = 'failed'",
            "input_tokens between 0 and input_token_cap",
            "input_tokens > input_token_cap",
        ):
            self.assertIn(fragment, self.compact_sql)

    def test_exposes_two_service_only_security_invoker_rpcs(self) -> None:
        signatures = (
            (
                "public.iros_begin_provider_input_token_preflight( "
                "p_operator_id uuid, p_preflight jsonb, "
                "p_sanitized_request jsonb )",
                "public.iros_begin_provider_input_token_preflight( "
                "uuid, jsonb, jsonb )",
            ),
            (
                "public.iros_complete_provider_input_token_preflight( "
                "p_operator_id uuid, p_preflight_id uuid, p_completion jsonb, "
                "p_sanitized_response jsonb )",
                "public.iros_complete_provider_input_token_preflight( "
                "uuid, uuid, jsonb, jsonb )",
            ),
        )
        for create_signature, privilege_signature in signatures:
            self.assertIn(
                f"create function {create_signature}", self.compact_sql
            )
            self.assertIn(
                f"revoke all on function {privilege_signature}", self.compact_sql
            )
            self.assertIn(
                f"grant execute on function {privilege_signature}",
                self.compact_sql,
            )

        self.assertEqual(self.sql.count("returns table("), 2)
        self.assertGreaterEqual(self.sql.count("security invoker"), 2)
        self.assertGreaterEqual(self.sql.count("set search_path = ''"), 2)
        self.assertNotIn("security definer", self.sql)

    def test_universal_insert_guard_blocks_direct_bypass_and_binds_frozen_config(
        self,
    ) -> None:
        guard = self.sql[
            self.sql.index(
                "create function public.iros_validate_provider_input_token_preflight_insert"
            ) : self.sql.index(
                "create function public.iros_begin_provider_input_token_preflight"
            )
        ]
        compact = " ".join(guard.split())

        self.assertIn("if new.state <> 'pending'", guard)
        self.assertIn("new.input_tokens is not null", guard)
        self.assertIn("new.completed_at is not null", guard)
        self.assertIn("from public.iros_grader_attempts", guard)
        self.assertIn("from public.iros_synthesis_attempts", guard)
        self.assertIn("join public.iros_model_configs", guard)
        self.assertIn("execution.execution_key = new.execution_identity", compact)
        self.assertIn("config.input_token_cap = new.input_token_cap", compact)
        self.assertIn("attempt.persistence_state = 'draft'", compact)
        self.assertIn("attempt.result is null", compact)
        self.assertIn("execution.persistence_state = 'draft'", compact)
        self.assertIn("execution.execution_state is null", compact)
        self.assertIn(
            "create trigger iros_provider_input_token_preflights_validate_insert "
            "before insert on public.iros_provider_input_token_preflights",
            self.compact_sql,
        )

    def test_begin_is_locked_attempt_bound_and_idempotent(self) -> None:
        begin = self.sql[
            self.sql.index(
                "create function public.iros_begin_provider_input_token_preflight"
            ) : self.sql.index(
                "create function public.iros_complete_provider_input_token_preflight"
            )
        ]
        compact = " ".join(begin.split())

        self.assertIn("pg_advisory_xact_lock", begin)
        self.assertIn("for update", compact)
        self.assertIn("from public.iros_grader_attempts", begin)
        self.assertIn("from public.iros_synthesis_attempts", begin)
        self.assertIn("request_sha256", begin)
        self.assertIn("research_run_id", begin)
        self.assertIn("execution.execution_key", begin)
        self.assertIn("config.input_token_cap", begin)
        self.assertIn("attempt.persistence_state = 'draft'", compact)
        self.assertIn("attempt.result is null", compact)
        self.assertIn("execution.persistence_state = 'draft'", compact)
        self.assertIn("execution.execution_state is null", compact)
        self.assertIn("conflicting provider input-token preflight identity", begin)
        self.assertIn("selected_preflight.state, true", compact)
        self.assertIn("selected_preflight.state, false", compact)
        self.assertNotIn("'sanitized_request'", begin[begin.rindex("return") :])

    def test_completion_is_exactly_once_and_terminal_rows_are_immutable(self) -> None:
        complete = self.sql[
            self.sql.index(
                "create function public.iros_complete_provider_input_token_preflight"
            ) : self.sql.index(
                "create function public.iros_guard_provider_input_token_preflight_change"
            )
        ]
        compact = " ".join(complete.split())

        self.assertIn("for update", compact)
        self.assertIn("selected_preflight.state <> 'pending'", complete)
        self.assertIn("conflicting provider input-token preflight completion", complete)
        self.assertIn("update public.iros_provider_input_token_preflights", complete)
        self.assertIn("selected_preflight.state, true", compact)
        self.assertIn("selected_preflight.state, false", compact)
        self.assertNotIn("'sanitized_response'", complete[complete.rindex("return") :])
        self.assertIn(
            "create trigger iros_provider_input_token_preflights_guard_change",
            self.sql,
        )
        self.assertIn("terminal provider input-token preflight is immutable", self.sql)
        self.assertIn("provider input-token preflight cannot be deleted", self.sql)

    def test_grants_only_service_role_and_never_touch_other_namespaces(self) -> None:
        self.assertIn(
            "revoke all on table public.iros_provider_input_token_preflights "
            "from public, anon, authenticated",
            self.compact_sql,
        )
        self.assertIn(
            "grant select, insert, update, delete on table "
            "public.iros_provider_input_token_preflights to service_role",
            self.compact_sql,
        )
        self.assertNotIn("to authenticated", self.sql)
        self.assertNotIn("to anon", self.sql)
        self.assertNotIn("well_", self.sql)
        self.assertNotIn("grant all on schema", self.sql)
        self.assertNotIn("drop table", self.sql)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from pathlib import Path

from investment_research_os.migration_audit import audit_iros_migration_batch


class GraderExecutionRuntimeMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        path = Path(
            "supabase/migrations/20260729053709_iros_grader_execution_runtime.sql"
        )
        cls.sql = path.read_text().lower()
        cls.compact_sql = " ".join(cls.sql.split())
        cls.path = path

    def test_passes_standalone_iros_migration_audit(self) -> None:
        report = audit_iros_migration_batch((self.path,))

        self.assertTrue(report.passed, report.violations)

    def test_exposes_five_service_only_security_invoker_runtime_functions(
        self,
    ) -> None:
        functions = (
            "iros_begin_grader_execution_runtime",
            "iros_begin_grader_attempt_runtime",
            "iros_finish_grader_attempt_runtime",
            "iros_finalize_grader_execution_runtime",
            "iros_load_grader_execution_runtime",
        )
        for function in functions:
            self.assertIn(f"create function public.{function}", self.sql)
            self.assertIn(
                f"revoke all on function public.{function}",
                self.compact_sql,
            )
            self.assertIn(
                f"grant execute on function public.{function}",
                self.compact_sql,
            )

        self.assertGreaterEqual(self.sql.count("security invoker"), len(functions))
        self.assertGreaterEqual(
            self.sql.count("set search_path = ''"),
            len(functions),
        )
        self.assertNotIn("security definer", self.sql)
        self.assertNotIn("to anon", self.sql)
        self.assertNotIn("to authenticated", self.sql)
        self.assertNotIn("well_", self.sql)
        self.assertNotIn(
            "select e.* into selected_execution select e.* into selected_execution",
            self.compact_sql,
        )

    def test_begin_execution_is_locked_idempotent_and_returns_no_payload(
        self,
    ) -> None:
        begin = self.sql[
            self.sql.index(
                "create function public.iros_begin_grader_execution_runtime"
            ) : self.sql.index(
                "create function public.iros_begin_grader_attempt_runtime"
            )
        ]
        compact = " ".join(begin.split())

        self.assertIn("pg_advisory_xact_lock", begin)
        self.assertIn("from public.iros_grader_executions", begin)
        self.assertIn("for update", compact)
        self.assertIn("insert into public.iros_grader_executions", begin)
        self.assertIn("conflicting grader execution runtime identity", begin)
        self.assertIn(
            "pre_call_gate' ->> 'status' is distinct from 'passed'",
            begin,
        )
        self.assertIn(
            "canonical_execution' ->> 'execution_state'",
            begin,
        )
        self.assertIn("'reused', true", compact)
        self.assertIn("'reused', false", compact)
        for field in (
            "'operator_id'",
            "'grader_execution_id'",
            "'execution_key'",
            "'persistence_state'",
            "'evidence_bundle_hash'",
            "'inference_parameter_hash'",
        ):
            self.assertIn(field, begin)
        self.assertNotIn("'canonical_execution'", begin[begin.rindex("return") :])
        self.assertNotIn("'pre_call_gate'", begin[begin.rindex("return") :])

    def test_attempt_lifecycle_persists_audit_and_reservation_atomically(
        self,
    ) -> None:
        begin = self.sql[
            self.sql.index(
                "create function public.iros_begin_grader_attempt_runtime"
            ) : self.sql.index(
                "create function public.iros_finish_grader_attempt_runtime"
            )
        ]
        compact = " ".join(begin.split())

        self.assertIn("for update", compact)
        self.assertIn("insert into public.iros_grader_attempts", begin)
        self.assertIn("insert into public.iros_model_attempt_payloads", begin)
        self.assertIn("public.iros_reserve_grader_budget(", begin)
        self.assertIn("previous.attempt_number = 1", begin)
        self.assertIn(
            "previous.result in ('transport_error', 'validation_error')",
            begin,
        )
        self.assertIn("conflicting grader attempt runtime identity", begin)
        self.assertIn("'reused', true", compact)
        self.assertIn("'reused', false", compact)
        self.assertNotIn("'request_payload'", begin[begin.rindex("return") :])
        self.assertNotIn("'response_payload'", begin[begin.rindex("return") :])

    def test_finish_attempt_is_exactly_once_and_settles_before_completion(
        self,
    ) -> None:
        finish = self.sql[
            self.sql.index(
                "create function public.iros_finish_grader_attempt_runtime"
            ) : self.sql.index(
                "create function public.iros_finalize_grader_execution_runtime"
            )
        ]
        compact = " ".join(finish.split())

        self.assertIn("for update", compact)
        self.assertIn("update public.iros_model_attempt_payloads", finish)
        self.assertIn("public.iros_reconcile_grader_budget(", finish)
        self.assertIn("insert into public.iros_grader_opinions", finish)
        self.assertIn(
            "(p_validated_opinion ->> 'created_at')::timestamptz",
            finish,
        )
        self.assertIn(
            "selected_execution.persistence_state not in ('draft', 'complete')",
            finish,
        )
        self.assertIn("update public.iros_grader_attempts", finish)
        self.assertLess(
            finish.index("public.iros_reconcile_grader_budget("),
            finish.index("update public.iros_grader_attempts"),
        )
        self.assertIn("conflicting grader attempt runtime completion", finish)
        self.assertIn("'reused', true", compact)
        self.assertIn("'reused', false", compact)
        self.assertIn(
            "create or replace function "
            "public.iros_reject_model_attempt_payload_change",
            self.sql,
        )
        self.assertIn("old.response_payload is not null", self.compact_sql)
        self.assertIn("$.**.encrypted_content", self.sql)
        self.assertIn('@.type == "reasoning"', self.sql)
        self.assertIn(
            "new.request_payload is distinct from old.request_payload", self.compact_sql
        )

    def test_finalize_execution_is_terminal_idempotent_and_completes_opinion(
        self,
    ) -> None:
        finalize = self.sql[
            self.sql.index(
                "create function public.iros_finalize_grader_execution_runtime"
            ) : self.sql.index(
                "revoke all on function public.iros_begin_grader_execution_runtime"
            )
        ]
        compact = " ".join(finalize.split())

        self.assertIn("for update", compact)
        self.assertIn("update public.iros_grader_opinions", finalize)
        self.assertIn("update public.iros_grader_executions", finalize)
        self.assertIn("conflicting grader execution runtime completion", finalize)
        self.assertIn("'reused', true", compact)
        self.assertIn("'reused', false", compact)
        self.assertIn(
            "create or replace function public.iros_guard_grader_execution_change",
            self.sql,
        )

    def test_load_execution_returns_restart_snapshot_only_to_service_role(
        self,
    ) -> None:
        load = self.sql[
            self.sql.index(
                "create function public.iros_load_grader_execution_runtime"
            ) : self.sql.index(
                "revoke all on function public.iros_begin_grader_execution_runtime"
            )
        ]
        compact = " ".join(load.split())

        self.assertIn("from public.iros_grader_executions", load)
        self.assertIn("from public.iros_grader_attempts", load)
        self.assertIn("join public.iros_budget_reservations", load)
        self.assertIn("join public.iros_model_attempt_payloads", load)
        self.assertIn("from public.iros_grader_opinions", load)
        self.assertIn("order by a.attempt_number", compact)
        self.assertIn("'canonical_execution'", load)
        self.assertIn("'attempts'", load)
        self.assertIn("'validated_opinion'", load)

    def test_is_additive_and_does_not_touch_unrelated_namespaces(self) -> None:
        self.assertNotIn("drop table", self.sql)
        self.assertNotIn("truncate", self.sql)
        self.assertNotIn("delete from", self.sql)
        self.assertNotIn("alter table", self.sql)
        self.assertNotIn("grant all on schema", self.sql)
        self.assertNotIn("grader execution runtime is not implemented", self.sql)
        for statement in self.sql.split(";"):
            compact = " ".join(statement.split())
            if compact.startswith(
                ("create function public.", "create or replace function public.")
            ):
                name = compact.split("public.", 1)[1].split("(", 1)[0]
                self.assertTrue(name.startswith("iros_"), name)


if __name__ == "__main__":
    unittest.main()

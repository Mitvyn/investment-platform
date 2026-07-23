from __future__ import annotations

import unittest
from pathlib import Path


class CommitteeMemoMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        migrations = sorted(
            Path("supabase/migrations").glob("*_iros_committee_memo.sql")
        )
        if len(migrations) != 1:
            raise AssertionError("expected one committee memo migration")
        cls.sql = migrations[0].read_text().lower()
        cls.compact_sql = " ".join(cls.sql.split())

    def test_persists_synthesis_attempts_and_one_accepted_memo(self) -> None:
        for table in (
            "iros_synthesis_executions",
            "iros_synthesis_attempts",
            "iros_synthesis_attempt_payloads",
            "iros_committee_memos",
        ):
            self.assertIn(f"create table public.{table}", self.sql)

        for invariant in (
            "unique (operator_id, execution_key)",
            "unique (operator_id, synthesis_execution_id, attempt_number)",
            "unique (operator_id, synthesis_execution_id)",
            "unique (operator_id, committee_result_id, synthesis_key)",
        ):
            self.assertIn(invariant, self.compact_sql)

    def test_exact_committee_bundle_and_canonical_memo_are_validated(self) -> None:
        for message in (
            "synthesis execution requires completed committee",
            "synthesis attempt requires draft execution",
            "committee memo finalization failed: invalid committee or bundle",
            "committee memo finalization failed: canonical identity mismatch",
            "committee memo finalization failed: state disclosure mismatch",
            "committee memo finalization failed: unresolved evidence reference",
            "committee memo finalization failed: unresolved opinion reference",
            "committee memo finalization failed: unresolved calculation reference",
        ):
            self.assertIn(message, self.sql)

        for expression in (
            "c.research_run_id = new.research_run_id",
            "c.evidence_bundle_id = new.evidence_bundle_id",
            "c.evidence_bundle_hash = new.evidence_bundle_hash",
            "c.workflow_config_version = new.workflow_config_version",
            "c.proposition_id = new.proposition_id",
            "c.proposition_version = new.proposition_version",
            "c.committee_status = new.committee_status",
        ):
            self.assertIn(expression, self.compact_sql)

        self.assertIn("'committee_memo.v1'", self.sql)
        self.assertIn("new.canonical_memo ->> 'memo_id' = new.id::text", self.compact_sql)
        self.assertIn("before update or delete on public.iros_committee_memos", self.compact_sql)
        self.assertIn("committee memo is immutable", self.sql)

    def test_owner_view_exposes_audit_memo_but_not_raw_payloads(self) -> None:
        self.assertEqual(self.sql.count("enable row level security"), 4)
        self.assertEqual(
            self.sql.count("with (security_invoker = true)"),
            1,
        )
        view = self.sql[
            self.sql.index(
                "create view public.iros_v_research_run_committee_memos"
            ) : self.sql.index(
                ";",
                self.sql.index(
                    "create view public.iros_v_research_run_committee_memos"
                ),
            )
        ]
        for column in (
            "memo.operator_id",
            "memo.research_run_id",
            "memo.committee_result_id",
            "memo.id as memo_id",
            "memo.canonical_memo",
        ):
            self.assertIn(column, view)
        self.assertNotIn("request_payload", view)
        self.assertNotIn("response_payload", view)

        for name in (
            "iros_synthesis_executions",
            "iros_synthesis_attempts",
            "iros_committee_memos",
            "iros_v_research_run_committee_memos",
        ):
            self.assertIn(
                f"grant select on table public.{name} to authenticated",
                self.compact_sql,
            )
        self.assertNotIn(
            "grant select on table public.iros_synthesis_attempt_payloads "
            "to authenticated",
            self.compact_sql,
        )
        self.assertNotIn(
            "policy iros_synthesis_attempt_payloads_operator_select",
            self.sql,
        )
        self.assertIn(
            "grant select, insert, update, delete on table "
            "public.iros_synthesis_executions, "
            "public.iros_synthesis_attempts, "
            "public.iros_synthesis_attempt_payloads, "
            "public.iros_committee_memos to service_role",
            self.compact_sql,
        )

    def test_retry_usage_cost_and_terminal_failure_remain_auditable(self) -> None:
        for field in (
            "prompt_version text not null",
            "model_config_id text not null",
            "provider text not null",
            "model text not null",
            "price_card_version text not null",
            "retry_policy_version text not null",
            "total_input_tokens integer",
            "total_cached_input_tokens integer",
            "total_cache_write_tokens integer",
            "total_uncached_input_tokens integer",
            "total_output_tokens integer",
            "total_tokens integer",
            "total_cost_usd numeric(20, 10)",
            "validation_errors jsonb",
            "retry_reason text",
            "cached_input_tokens integer",
            "cache_write_tokens integer",
            "uncached_input_tokens integer",
        ):
            self.assertIn(field, self.sql)

        for message in (
            "synthesis attempt finalization failed: invalid retry linkage",
            "synthesis attempt finalization failed: accepted output invalid",
            "synthesis attempt finalization failed: errors required",
            "synthesis execution finalization failed: attempt totals mismatch",
            "synthesis execution finalization failed: accepted memo mismatch",
            "synthesis execution finalization failed: failed state mismatch",
        ):
            self.assertIn(message, self.sql)

        self.assertIn(
            "new.canonical_memo -> 'execution_metadata' ->> 'model_config_id'",
            self.compact_sql,
        )
        self.assertIn(
            "new.canonical_memo -> 'execution_metadata' ->> 'retry_policy_version'",
            self.compact_sql,
        )
        self.assertIn("synthesis raw payload is immutable", self.sql)
        self.assertIn("synthesis attempt is immutable", self.sql)
        self.assertIn("synthesis execution is immutable", self.sql)
        self.assertIn(
            "new.cached_input_tokens + new.cache_write_tokens + "
            "new.uncached_input_tokens <> new.input_tokens",
            self.compact_sql,
        )
        self.assertIn(
            "summed_cached_input_tokens <> new.total_cached_input_tokens",
            self.compact_sql,
        )
        self.assertIn(
            "summed_cache_write_tokens <> new.total_cache_write_tokens",
            self.compact_sql,
        )
        self.assertIn(
            "summed_uncached_input_tokens <> new.total_uncached_input_tokens",
            self.compact_sql,
        )

    def test_isolated_iros_namespace_and_explicit_grants_only(self) -> None:
        forbidden_prefix = "we" + "ll_"
        self.assertNotIn(forbidden_prefix, self.sql)
        self.assertNotIn("references public.users", self.sql)
        self.assertNotIn("grant all on schema public", self.compact_sql)
        self.assertNotIn("grant all on all tables", self.compact_sql)
        for statement in self.sql.split(";"):
            compact = " ".join(statement.split())
            if compact.startswith(("create table public.", "create view public.")):
                object_name = compact.split("public.", 1)[1].split()[0]
                self.assertTrue(object_name.startswith("iros_"), object_name)


if __name__ == "__main__":
    unittest.main()

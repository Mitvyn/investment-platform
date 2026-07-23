from __future__ import annotations

import unittest
from pathlib import Path


class GraderExecutionMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        migrations = sorted(
            Path("supabase/migrations").glob("*_iros_grader_execution.sql")
        )
        if len(migrations) != 1:
            raise AssertionError("expected one isolated grader execution migration")
        cls.sql = migrations[0].read_text().lower()
        cls.compact_sql = " ".join(cls.sql.split())

    def test_execution_is_owner_run_and_bundle_scoped(self) -> None:
        self.assertIn("create table public.iros_grader_executions", self.sql)
        for field in (
            "operator_id",
            "research_run_id",
            "security_id",
            "evidence_bundle_id",
            "evidence_bundle_hash",
            "execution_key",
            "grader_id",
            "grader_version",
            "canonical_execution",
        ):
            self.assertIn(field, self.sql)

        self.assertIn(
            "unique (operator_id, execution_key)",
            self.compact_sql,
        )
        self.assertIn(
            "foreign key (operator_id, research_run_id)",
            self.compact_sql,
        )
        self.assertIn(
            "foreign key (operator_id, evidence_bundle_id)",
            self.compact_sql,
        )
        self.assertIn(
            "create view public.iros_v_research_run_grader_executions",
            self.sql,
        )
        self.assertIn("with (security_invoker = true)", self.compact_sql)

    def test_attempts_opinions_and_raw_payloads_are_separate_audit_records(
        self,
    ) -> None:
        for table in (
            "iros_grader_attempts",
            "iros_grader_opinions",
            "iros_model_attempt_payloads",
        ):
            self.assertIn(f"create table public.{table}", self.sql)

        for field in (
            "attempt_number",
            "request_sha256",
            "raw_payload_id",
            "raw_payload_sha256",
            "input_tokens",
            "cached_input_tokens",
            "cache_write_tokens",
            "uncached_input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "total_tokens",
            "estimated_cost_usd",
            "validation_errors",
            "opinion_id",
            "execution_state",
            "canonical_opinion",
            "request_payload",
            "response_payload",
        ):
            self.assertIn(field, self.sql)

        self.assertIn(
            "unique (operator_id, grader_execution_id, attempt_number)",
            self.compact_sql,
        )
        self.assertIn(
            "unique (operator_id, grader_execution_id)",
            self.compact_sql,
        )
        self.assertIn("grader attempt is immutable", self.sql)
        self.assertIn("grader opinion is immutable", self.sql)

        view_start = self.sql.index(
            "create view public.iros_v_grader_attempt_audit"
        )
        view_end = self.sql.index(";", view_start)
        normal_view = self.sql[view_start:view_end]
        self.assertIn("raw_payload_id", normal_view)
        self.assertIn("raw_payload_sha256", normal_view)
        self.assertNotIn("request_payload", normal_view)
        self.assertNotIn("response_payload", normal_view)
        self.assertNotIn("reasoning_content text", self.sql)
        self.assertIn("jsonb_path_exists(request_payload", self.compact_sql)
        self.assertIn("jsonb_path_exists(response_payload", self.compact_sql)

    def test_pinned_config_price_card_and_budget_reservation_precede_calls(
        self,
    ) -> None:
        for table in (
            "iros_model_configs",
            "iros_model_price_catalog",
            "iros_budgets",
            "iros_budget_reservations",
        ):
            self.assertIn(f"create table public.{table}", self.sql)

        for field in (
            "config_version",
            "exact_model_id",
            "inference_parameter_hash",
            "retention_policy_version",
            "evaluation_id",
            "approval_status",
            "input_token_cap",
            "output_token_cap",
            "price_card_version",
            "input_per_million",
            "cached_input_per_million",
            "output_per_million",
            "effective_from",
            "effective_to",
            "hard_cost_limit_usd",
            "hard_token_limit",
            "current_reserved_cost_usd",
            "current_reconciled_cost_usd",
            "reserved_cost_usd",
            "actual_cost_usd",
            "reservation_state",
        ):
            self.assertIn(field, self.sql)

        self.assertIn("create function public.iros_reserve_grader_budget", self.sql)
        self.assertIn("for update", self.compact_sql)
        self.assertIn("hard budget capacity exceeded", self.sql)
        self.assertIn(
            "create function public.iros_reconcile_grader_budget",
            self.sql,
        )
        self.assertIn("model config is immutable", self.sql)
        self.assertIn("model price card is immutable", self.sql)
        self.assertNotIn("double precision", self.sql)
        self.assertNotIn(" real ", f" {self.compact_sql} ")

    def test_price_catalog_requires_cache_write_rate_and_bounded_expiry(
        self,
    ) -> None:
        price_catalog = self.sql[
            self.sql.index("create table public.iros_model_price_catalog") :
            self.sql.index("create table public.iros_budgets")
        ]

        self.assertIn(
            "cache_write_per_million numeric(20, 10) not null",
            price_catalog,
        )
        self.assertIn("effective_to timestamptz not null", price_catalog)
        self.assertIn(
            "effective_to <= verified_at + interval '30 days'",
            " ".join(price_catalog.split()),
        )

    def test_cache_write_tokens_must_fit_inside_uncached_input(self) -> None:
        self.assertIn(
            "new.cache_write_tokens > new.uncached_input_tokens",
            self.compact_sql,
        )

    def test_finalization_enforces_state_attempt_and_opinion_semantics(self) -> None:
        for message in (
            "grader executions must begin as draft",
            "grader attempts must begin as draft",
            "grader opinions must begin as draft",
            "grader execution finalization failed",
            "grader attempt finalization failed",
            "grader opinion finalization failed",
            "grader execution is immutable",
        ):
            self.assertIn(message, self.sql)

        self.assertIn(
            "before update of persistence_state on public.iros_grader_executions",
            self.compact_sql,
        )
        self.assertIn("a.attempt_number between 1 and e.max_attempts", self.compact_sql)
        self.assertIn("into attempt_count,", self.compact_sql)
        self.assertIn("count(*) into opinion_count", self.compact_sql)
        self.assertIn("execution_state = 'not_executed'", self.compact_sql)
        self.assertIn("execution_state = 'failed'", self.compact_sql)
        self.assertIn("execution_state in ('accepted', 'abstained')", self.compact_sql)
        self.assertIn("m.approval_status = 'approved'", self.compact_sql)
        self.assertIn("m.active", self.compact_sql)
        self.assertIn("p.effective_from <= new.started_at", self.compact_sql)
        self.assertIn("b.research_run_id = new.research_run_id", self.compact_sql)
        self.assertIn("r.persistence_state = 'complete'", self.compact_sql)
        self.assertIn("bndl.persistence_state = 'complete'", self.compact_sql)
        self.assertIn("bndl.bundle_hash = new.evidence_bundle_hash", self.compact_sql)
        self.assertIn(
            "new.execution_state <> 'not_executed' and not exists",
            self.compact_sql,
        )
        self.assertIn("persistence_state <> 'complete'", self.compact_sql)

    def test_not_executed_can_record_missing_price_or_budget_without_fake_ids(
        self,
    ) -> None:
        execution_table = self.sql[
            self.sql.index("create table public.iros_grader_executions") :
            self.sql.index("create table public.iros_grader_attempts")
        ]
        self.assertIn("price_card_id text", execution_table)
        self.assertNotIn("price_card_id text not null", execution_table)
        self.assertIn("budget_id uuid", execution_table)
        self.assertNotIn("budget_id uuid not null", execution_table)
        self.assertIn(
            "new.execution_state = 'not_executed'",
            self.compact_sql,
        )
        self.assertIn("new.pre_call_gate ->> 'status'", self.compact_sql)

    def test_budget_reservation_matches_execution_controls_and_never_overruns(
        self,
    ) -> None:
        self.assertIn("e.budget_id = p_budget_id", self.compact_sql)
        self.assertIn("e.price_card_id = p_price_card_id", self.compact_sql)
        self.assertIn(
            "p_actual_cost_usd > selected_reservation.reserved_cost_usd",
            self.compact_sql,
        )
        self.assertIn(
            "p_actual_tokens > selected_reservation.reserved_tokens",
            self.compact_sql,
        )
        self.assertIn("overlapping model price card", self.sql)

    def test_opinion_citations_resolve_only_to_frozen_bundle(self) -> None:
        self.assertIn("iros_evidence_bundle_items", self.sql)
        self.assertIn("iros_evidence_versions", self.sql)
        self.assertIn("evidence_version_id", self.sql)
        self.assertIn("material_claims", self.sql)
        self.assertIn("contradicting_evidence", self.sql)
        self.assertIn("citation outside frozen bundle", self.sql)
        self.assertIn("a.citations_valid", self.compact_sql)

    def test_canonical_attempts_and_opinion_match_relational_records(self) -> None:
        self.assertIn("jsonb_array_elements(", self.sql)
        for expression in (
            "attempt ->> 'attempt_id' = a.id::text",
            "(attempt ->> 'attempt_number')::integer = a.attempt_number",
            "attempt ->> 'request_sha256' = a.request_sha256",
            "attempt ->> 'result' = a.result",
            "attempt -> 'usage' ->> 'total_tokens'",
            "attempt -> 'validation' ->> 'status' = a.validation_status",
            "new.canonical_execution -> 'opinion' = o.canonical_opinion",
        ):
            self.assertIn(expression, self.compact_sql)
        self.assertIn("canonical attempt mismatch", self.sql)
        self.assertIn("canonical opinion mismatch", self.sql)

    def test_canonical_execution_matches_versioned_wire_identity(self) -> None:
        for field in (
            "'grader_execution.v1'",
            "question_type_id",
            "question_type_version",
            "workflow_config_version",
            "thesis_contract_id",
            "grader_contract_version",
            "eligibility_rule_version",
            "rubric_version",
            "output_schema_version",
            "abstention_rules_version",
            "prompt_version",
            "model_config_id",
            "provider",
            "model",
            "inference_parameter_hash",
            "retry_policy_version",
            "required",
            "execution_state",
            "pre_call_gate",
            "budget",
            "attempts",
            "total_usage",
            "total_cost",
            "not_executed",
            "failure",
            "opinion",
            "started_at",
            "finished_at",
        ):
            self.assertIn(field, self.sql)

        for expression in (
            "new.canonical_execution ->> 'id' = new.id::text",
            "new.canonical_execution ->> 'operator_id' = new.operator_id::text",
            "new.canonical_execution ->> 'research_run_id' = new.research_run_id::text",
            "new.canonical_execution ->> 'evidence_bundle_id' = new.evidence_bundle_id::text",
            "new.canonical_execution ->> 'evidence_bundle_hash' = new.evidence_bundle_hash",
            "new.canonical_execution ->> 'execution_key' = new.execution_key",
            "new.canonical_execution ->> 'execution_state' = new.execution_state",
        ):
            self.assertIn(expression, self.compact_sql)

    def test_relational_projection_matches_grader_execution_v1_values(self) -> None:
        execution_table = self.sql[
            self.sql.index("create table public.iros_grader_executions") :
            self.sql.index("create table public.iros_grader_attempts")
        ]
        attempt_table = self.sql[
            self.sql.index("create table public.iros_grader_attempts") :
            self.sql.index("create table public.iros_model_attempt_payloads")
        ]
        opinion_table = self.sql[
            self.sql.index("create table public.iros_grader_opinions") :
            self.sql.index("create table public.iros_model_configs")
        ]

        self.assertIn("model_config_id text not null", execution_table)
        self.assertIn("model_config_id text not null", attempt_table)
        self.assertIn("price_card_id text not null", attempt_table)
        self.assertIn("'transport_error'", attempt_table)
        self.assertIn("'validation_error'", attempt_table)
        self.assertNotIn("'transport_failed'", attempt_table)
        self.assertNotIn("'validation_failed'", attempt_table)
        self.assertIn("validation_status text", attempt_table)
        self.assertIn("tool_call_count integer", attempt_table)
        self.assertIn("usage_complete boolean not null", attempt_table)
        self.assertIn("confidence text not null", opinion_table)
        self.assertIn("'high'", opinion_table)
        self.assertIn("'medium'", opinion_table)
        self.assertIn("'low'", opinion_table)
        self.assertIn("new.pre_call_gate ->> 'status'", self.compact_sql)
        self.assertNotIn("new.pre_call_gate ->> 'passed'", self.compact_sql)

    def test_owner_rls_and_explicit_grants_keep_raw_payload_private(self) -> None:
        tables = (
            "iros_grader_executions",
            "iros_grader_attempts",
            "iros_model_attempt_payloads",
            "iros_grader_opinions",
            "iros_model_configs",
            "iros_model_price_catalog",
            "iros_budgets",
            "iros_budget_reservations",
        )
        views = (
            "iros_v_research_run_grader_executions",
            "iros_v_grader_attempt_audit",
            "iros_v_grader_opinions",
            "iros_v_grader_cost_audit",
        )

        self.assertEqual(self.sql.count("enable row level security"), len(tables))
        self.assertGreaterEqual(
            self.sql.count("using ((select auth.uid()) = operator_id"),
            len(tables) - 1,
        )
        for name in (*tables, *views):
            self.assertIn(
                f"revoke all on table public.{name} from anon, authenticated",
                self.compact_sql,
            )

        for name in (
            "iros_grader_executions",
            "iros_grader_attempts",
            "iros_grader_opinions",
            "iros_model_configs",
            "iros_model_price_catalog",
            "iros_budgets",
            "iros_budget_reservations",
            *views,
        ):
            self.assertIn(
                f"grant select on table public.{name} to authenticated",
                self.compact_sql,
            )

        self.assertNotIn(
            "grant select on table public.iros_model_attempt_payloads "
            "to authenticated",
            self.compact_sql,
        )
        self.assertNotIn(
            "policy iros_model_attempt_payloads_operator_select",
            self.sql,
        )
        self.assertNotIn("iros_v_model_attempt_payload", self.sql)
        self.assertIn(
            "grant select, insert, update, delete on table "
            "public.iros_model_attempt_payloads to service_role",
            self.compact_sql,
        )
        self.assertNotIn("grant all on schema public", self.compact_sql)
        self.assertNotIn("grant all on all tables", self.compact_sql)
        self.assertNotIn("well_", self.sql)

    def test_no_cross_project_foreign_keys_or_unprefixed_objects(self) -> None:
        self.assertNotIn("references public.well_", self.sql)
        self.assertNotIn("references public.users", self.sql)
        for statement in self.sql.split(";"):
            lowered = " ".join(statement.split())
            if lowered.startswith(("create table public.", "create view public.")):
                object_name = lowered.split("public.", 1)[1].split()[0]
                self.assertTrue(object_name.startswith("iros_"), object_name)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from pathlib import Path
import unittest

from investment_research_os.migration_audit import audit_iros_migration_batch


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "supabase" / "migrations"


class ModelCostReadModelMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        matches = sorted(MIGRATIONS.glob("*_iros_model_cost_read_model.sql"))
        if len(matches) != 1:
            raise AssertionError(
                "expected exactly one iros_model_cost_read_model migration"
            )
        cls.path = matches[0]
        cls.sql = cls.path.read_text().lower()
        cls.compact = " ".join(cls.sql.split())

    def test_unifies_terminal_grader_and_synthesis_attempts(self) -> None:
        self.assertIn(
            "create view public.iros_v_model_cost_attempts "
            "with (security_invoker = true)",
            self.compact,
        )
        self.assertIn("from public.iros_grader_attempts", self.sql)
        self.assertIn("from public.iros_synthesis_attempts", self.sql)
        self.assertIn("'grader'::text as execution_kind", self.sql)
        self.assertIn("'synthesizer'::text as execution_kind", self.sql)
        self.assertIn("union all", self.sql)
        self.assertGreaterEqual(
            self.sql.count("persistence_state = 'complete'"),
            4,
        )

    def test_owner_scopes_synthesis_reservations_and_view_access(self) -> None:
        self.assertIn(
            "drop policy iros_budget_reservations_operator_select",
            self.sql,
        )
        self.assertIn(
            "create policy iros_synthesis_budget_reservations_operator_select",
            self.sql,
        )
        self.assertIn("to authenticated using (", self.compact)
        self.assertIn("(select auth.uid()) = operator_id", self.compact)
        reservation_policy_sql = self.sql.split(
            "create view public.iros_v_model_cost_budgets",
            maxsplit=1,
        )[0]
        self.assertNotIn("persistence_state", reservation_policy_sql)
        self.assertIn(
            "grant select on table public.iros_synthesis_budget_reservations "
            "to authenticated",
            self.compact,
        )
        self.assertIn(
            "revoke all on table public.iros_v_model_cost_attempts "
            "from public, anon, authenticated",
            self.compact,
        )
        self.assertIn(
            "grant select on table public.iros_v_model_cost_attempts "
            "to authenticated, service_role",
            self.compact,
        )
        self.assertNotIn("security definer", self.sql)

    def test_exposes_empty_and_partial_budget_accounting_separately(self) -> None:
        for view_name in (
            "iros_v_model_cost_budgets",
            "iros_v_model_cost_reservations",
        ):
            self.assertIn(
                f"create view public.{view_name} "
                "with (security_invoker = true)",
                self.compact,
            )
            self.assertIn(
                f"grant select on table public.{view_name} "
                "to authenticated, service_role",
                self.compact,
            )
        reservations = self.sql.split(
            "create view public.iros_v_model_cost_reservations",
            maxsplit=1,
        )[1].split(
            "create view public.iros_v_model_cost_attempts",
            maxsplit=1,
        )[0]
        self.assertIn("from public.iros_budget_reservations", reservations)
        self.assertIn(
            "from public.iros_synthesis_budget_reservations",
            reservations,
        )
        self.assertNotIn("persistence_state", reservations)
        self.assertIn("reservation.reservation_state", reservations)

    def test_normalizes_cache_write_tokens_without_double_counting(self) -> None:
        attempts = self.sql.split(
            "create view public.iros_v_model_cost_attempts",
            maxsplit=1,
        )[1]
        grader, synthesis = attempts.split("union all", maxsplit=1)

        self.assertIn(
            "attempt.uncached_input_tokens - attempt.cache_write_tokens",
            self.compact,
        )
        self.assertIn("end as uncached_input_tokens", grader)
        self.assertIn(
            "attempt.uncached_input_tokens,\n  attempt.output_tokens",
            synthesis,
        )
        self.assertEqual(
            self.sql.count("attempt.cache_write_tokens,"),
            2,
        )

    def test_exposes_cost_validation_and_retry_metadata_without_provider_bodies(
        self,
    ) -> None:
        for fragment in (
            "attempt.validation_status",
            "jsonb_array_length(attempt.validation_errors) "
            "as validation_error_count",
            "attempt.retry_reason is not null as retry_recorded",
            "attempt.input_tokens",
            "attempt.cached_input_tokens",
            "attempt.cache_write_tokens",
            "attempt.output_tokens",
            "attempt.reasoning_tokens",
            "attempt.total_tokens",
            "reservation.reserved_cost_usd",
            "reservation.actual_cost_usd as reconciled_cost_usd",
            "attempt.estimated_cost_usd",
            "reservation.reservation_state",
            "remaining_cost_usd",
            "remaining_tokens",
        ):
            self.assertIn(fragment, self.sql)

        for prohibited in (
            "iros_model_attempt_payloads",
            "iros_synthesis_attempt_payloads",
            "iros_provider_input_token_preflights",
            "sanitized_request",
            "sanitized_response",
            "request_payload",
            "response_payload",
            "reasoning_content",
            "encrypted_content",
            "attempt.validation_errors,",
            "attempt.retry_reason,",
        ):
            self.assertNotIn(prohibited, self.sql)

    def test_classifies_historical_price_card_state_explicitly(self) -> None:
        for state in (
            "'missing'",
            "'mismatched'",
            "'unknown'",
            "'expired'",
            "'stale'",
            "'valid'",
        ):
            self.assertGreaterEqual(self.sql.count(state), 2)
        self.assertGreaterEqual(
            self.sql.count(
                "price.effective_to = price.verified_at + interval '30 days'"
            ),
            2,
        )
        attempts = self.sql.split(
            "create view public.iros_v_model_cost_attempts",
            maxsplit=1,
        )[1]
        first_branch = attempts.split("union all", maxsplit=1)[0]
        self.assertLess(
            first_branch.index("then 'stale'"),
            first_branch.index("then 'expired'"),
        )

    def test_missing_budget_capacity_is_unknown_not_zero(self) -> None:
        self.assertGreaterEqual(
            self.sql.count("when budget.id is null then null"),
            2,
        )

    def test_passes_iros_namespace_migration_audit(self) -> None:
        self.assertGreater(
            int(self.path.stem.split("_", maxsplit=1)[0]),
            20260803131124,
        )
        report = audit_iros_migration_batch((self.path,))

        self.assertTrue(report.passed, report.violations)
        self.assertNotIn("well_", self.sql)
        self.assertNotIn("grant all on schema", self.sql)
        self.assertNotIn("drop table", self.sql)


if __name__ == "__main__":
    unittest.main()

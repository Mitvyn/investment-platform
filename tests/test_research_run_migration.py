from __future__ import annotations

import unittest
from pathlib import Path


class ResearchRunMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        migrations = sorted(
            Path("supabase/migrations").glob("*_iros_research_run_eligibility.sql")
        )
        if len(migrations) != 1:
            raise AssertionError("expected one Research Run eligibility migration")
        cls.sql = migrations[0].read_text().lower()
        cls.compact_sql = " ".join(cls.sql.split())

    def test_adds_versioned_research_run_and_rule_level_eligibility(self) -> None:
        required_objects = (
            "iros_securities",
            "iros_question_types",
            "iros_workflow_configs",
            "iros_eligibility_evaluations",
            "iros_eligibility_checks",
            "iros_v_research_run_eligibility",
        )
        for name in required_objects:
            self.assertIn(name, self.sql)

        for field in (
            "security_id",
            "question_type_version_id",
            "workflow_config_version_id",
            "thesis_contract_id",
            "as_of_cutoff",
            "operator_focus_original",
            "operator_focus_normalized",
            "security_identity_snapshot",
        ):
            self.assertIn(field, self.sql)

        forbidden_prefix = "we" + "ll_"
        self.assertNotIn(forbidden_prefix, self.sql)
        self.assertIn("with (security_invoker = true)", self.sql)

    def test_view_matches_owner_scoped_repository_contract(self) -> None:
        self.assertIn("q.question_type", self.sql)
        self.assertIn(
            "c.evaluated_at as check_evaluated_at",
            self.compact_sql,
        )
        self.assertIn(
            "using ((select auth.uid()) = operator_id)",
            self.sql,
        )
        self.assertIn(
            "grant select on table public.iros_v_research_run_eligibility "
            "to authenticated",
            self.compact_sql,
        )
        self.assertNotIn(
            "grant select, insert, update, delete on table "
            "public.iros_eligibility_evaluations to authenticated",
            self.compact_sql,
        )

    def test_stable_security_and_eligibility_history_are_immutable(self) -> None:
        self.assertIn("security cik is immutable", self.sql)
        self.assertIn("research run request contract is immutable", self.sql)
        self.assertIn("eligibility results are immutable", self.sql)
        self.assertIn(
            "before update on public.iros_securities",
            self.compact_sql,
        )
        self.assertIn(
            "before update or delete on public.iros_eligibility_evaluations",
            self.compact_sql,
        )

    def test_only_complete_exactly_validated_runs_are_visible(self) -> None:
        self.assertIn("persistence_state", self.sql)
        self.assertIn("research run eligibility finalization failed", self.sql)
        self.assertIn("research committee runs must begin as draft", self.sql)
        self.assertIn(
            "before insert on public.iros_research_runs",
            self.compact_sql,
        )
        self.assertIn("if check_count <> 9", self.compact_sql)
        self.assertIn("bool_and(c.passed)", self.compact_sql)
        self.assertIn("missing verified canonical security", self.sql)
        self.assertIn("r.persistence_state = 'complete'", self.compact_sql)

    def test_version_contracts_are_immutable_but_historical_rows_remain_visible(
        self,
    ) -> None:
        self.assertIn("question type version semantics are immutable", self.sql)
        self.assertIn("workflow config version semantics are immutable", self.sql)
        self.assertIn(
            "before update or delete on public.iros_question_types",
            self.compact_sql,
        )
        self.assertIn(
            "before update or delete on public.iros_workflow_configs",
            self.compact_sql,
        )
        self.assertIn("using (true)", self.sql)
        self.assertNotIn("using (active)", self.sql)

    def test_research_run_contract_enforces_version_and_security_consistency(
        self,
    ) -> None:
        self.assertIn("iros_research_runs_workflow_question_fk", self.sql)
        self.assertIn("iros_research_runs_question_contract_fk", self.sql)
        self.assertIn("operator_id, research_run_id, security_id", self.sql)
        self.assertIn("new.run_type is distinct from old.run_type", self.sql)

    def test_isolates_namespace_and_keeps_authenticated_results_read_only(self) -> None:
        forbidden_prefix = "we" + "ll_"
        self.assertNotIn(forbidden_prefix, self.sql)
        self.assertNotIn("grant all on schema public", self.sql)
        self.assertNotIn("references public.w", self.sql)
        self.assertEqual(self.sql.count("enable row level security"), 5)
        self.assertEqual(
            self.sql.count("using ((select auth.uid()) = operator_id)"),
            3,
        )
        self.assertNotIn(
            "grant select, insert, update, delete on table "
            "public.iros_eligibility_checks to authenticated",
            self.compact_sql,
        )


if __name__ == "__main__":
    unittest.main()

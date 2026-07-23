from __future__ import annotations

import unittest
from pathlib import Path


class FiveGraderCommitteeMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        migrations = sorted(
            Path("supabase/migrations").glob(
                "*_iros_five_grader_committee.sql"
            )
        )
        if len(migrations) != 1:
            raise AssertionError("expected one five-grader committee migration")
        cls.sql = migrations[0].read_text().lower()
        cls.compact_sql = " ".join(cls.sql.split())

    def test_persists_versioned_five_grader_roster_and_committee_links(
        self,
    ) -> None:
        for table in (
            "iros_grader_definitions",
            "iros_committee_results",
            "iros_committee_grader_results",
        ):
            self.assertIn(f"create table public.{table}", self.sql)

        roster_insert = self.sql[
            self.sql.index("insert into public.iros_grader_definitions") :
            self.sql.index(";", self.sql.index(
                "insert into public.iros_grader_definitions"
            ))
        ]
        for grader_id in (
            "moonshot",
            "catalyst",
            "biotech",
            "risk_dilution",
            "valuation",
        ):
            self.assertIn(f"'{grader_id}'", roster_insert)
        self.assertIn("roster_position", roster_insert)
        self.assertIn("owned_decision_question", roster_insert)
        self.assertIn("required", roster_insert)
        for invariant in (
            "unique (operator_id, research_run_id)",
            "unique (operator_id, idempotency_key)",
            "unique (operator_id, committee_result_id, grader_id)",
            "unique (operator_id, committee_result_id, roster_position)",
            "unique (operator_id, committee_result_id, grader_execution_id)",
        ):
            self.assertIn(invariant, self.compact_sql)

    def test_committee_persists_five_distinct_terminal_states(self) -> None:
        result_table = self.sql[
            self.sql.index("create table public.iros_committee_grader_results") :
            self.sql.index(
                ";",
                self.sql.index("create table public.iros_committee_grader_results"),
            )
        ]
        for state in (
            "'accepted'",
            "'abstained'",
            "'failed'",
            "'not_eligible'",
            "'not_executed'",
        ):
            self.assertIn(state, result_table)
        self.assertIn(
            "unique (operator_id, research_run_id, workflow_config_version, grader_id)",
            self.compact_sql,
        )
        self.assertIn(
            "foreign key (workflow_config_version, grader_id, grader_version)",
            self.compact_sql,
        )

    def test_terminal_result_links_require_completed_isolated_executions(
        self,
    ) -> None:
        for message in (
            "grader terminal result requires draft committee",
            "grader terminal result requires complete execution",
            "grader terminal result identity mismatch",
            "grader terminal result opinion mismatch",
            "not eligible execution semantics invalid",
            "committee grader result is immutable",
        ):
            self.assertIn(message, self.sql)

        self.assertIn("e.persistence_state = 'complete'", self.compact_sql)
        self.assertIn("e.evidence_bundle_id = c.evidence_bundle_id", self.compact_sql)
        self.assertIn("e.evidence_bundle_hash = c.evidence_bundle_hash", self.compact_sql)
        self.assertIn("e.execution_state = new.execution_state", self.compact_sql)
        self.assertIn("new.execution_state in ('accepted', 'abstained')", self.compact_sql)
        self.assertIn("new.execution_state not in ('accepted', 'abstained')", self.compact_sql)
        self.assertIn("new.grader_opinion_id is null", self.compact_sql)
        self.assertIn("new.grader_opinion_id is not null", self.compact_sql)

    def test_not_eligible_is_persisted_without_executing_grader(self) -> None:
        result_table = self.sql[
            self.sql.index("create table public.iros_committee_grader_results") :
            self.sql.index(
                ";",
                self.sql.index("create table public.iros_committee_grader_results"),
            )
        ]
        self.assertIn("grader_execution_id uuid", result_table)
        self.assertNotIn("grader_execution_id uuid not null", result_table)
        for field in ("not_eligible jsonb", "not_executed jsonb", "failure jsonb"):
            self.assertIn(field, result_table)
        self.assertIn("persisted_at timestamptz not null", result_table)
        self.assertIn(
            "new.execution_state = 'not_eligible' and ( new.grader_execution_id is not null",
            self.compact_sql,
        )
        self.assertIn("new.not_eligible is null", self.compact_sql)
        self.assertIn("new.not_eligible ->> 'reason_code'", self.compact_sql)
        self.assertIn("new.not_eligible -> 'eligibility_inputs'", self.compact_sql)
        self.assertIn(
            "result.execution_state = 'not_eligible' and result.grader_execution_id is null",
            self.compact_sql,
        )

    def test_committee_status_derives_only_after_exact_roster_is_complete(
        self,
    ) -> None:
        for message in (
            "committee results must begin as draft",
            "committee finalization failed: invalid run or bundle",
            "committee finalization failed: exact five-grader roster required",
            "committee finalization failed: terminal state not persisted",
            "committee finalization failed: accounting mismatch",
            "committee finalization failed: status mismatch",
            "committee finalization failed: canonical result mismatch",
            "committee result is immutable",
        ):
            self.assertIn(message, self.sql)

        self.assertIn("count(*) filter (where execution_state <> 'not_eligible')", self.compact_sql)
        self.assertIn("count(*) filter (where execution_state = 'accepted')", self.compact_sql)
        self.assertIn("count(*) filter (where execution_state = 'abstained')", self.compact_sql)
        self.assertIn("count(*) filter (where execution_state = 'not_eligible')", self.compact_sql)
        self.assertIn("count(*) filter (where execution_state = 'failed' and required)", self.compact_sql)
        self.assertIn("count(*) filter (where execution_state = 'not_executed')", self.compact_sql)
        self.assertIn("count(*) filter (where o.stance = 'supports')", self.compact_sql)
        self.assertIn("count(*) filter (where o.stance = 'mixed')", self.compact_sql)
        self.assertIn("count(*) filter (where o.stance = 'challenges')", self.compact_sql)

        failed = self.compact_sql.index("required_failed_count > 0")
        unavailable = self.compact_sql.index("not_executed_count > 0")
        abstained = self.compact_sql.index("abstained_count > 0")
        complete = self.compact_sql.index("accepted_count = eligible_count")
        self.assertLess(failed, unavailable)
        self.assertLess(unavailable, abstained)
        self.assertLess(abstained, complete)

    def test_canonical_committee_matches_versioned_contract_and_shared_proposition(
        self,
    ) -> None:
        for field in (
            "'committee_state.v1'",
            "research_run_id",
            "evidence_bundle_id",
            "evidence_bundle_hash",
            "workflow_config_version",
            "proposition_id",
            "proposition_version",
            "rendered_proposition_text",
            "committee_status",
            "accounting",
            "stance_counts",
            "stance_matrix",
            "grader_results",
            "derived_at",
        ):
            self.assertIn(field, self.sql)
        self.assertIn(
            "new.canonical_committee -> 'accounting' = new.accounting",
            self.compact_sql,
        )
        self.assertIn(
            "new.canonical_committee -> 'stance_counts' = new.stance_counts",
            self.compact_sql,
        )
        self.assertIn(
            "jsonb_array_length(new.canonical_committee -> 'grader_results') = 5",
            self.compact_sql,
        )
        self.assertIn(
            "o.canonical_opinion -> 'proposition' ->> 'proposition_id'",
            self.compact_sql,
        )

    def test_owner_rls_security_invoker_views_and_explicit_grants(self) -> None:
        tables = (
            "iros_grader_definitions",
            "iros_committee_results",
            "iros_committee_grader_results",
        )
        views = (
            "iros_v_research_run_committees",
            "iros_v_committee_grader_results",
        )
        self.assertEqual(self.sql.count("enable row level security"), 3)
        self.assertGreaterEqual(
            self.sql.count("using ((select auth.uid()) = operator_id"),
            2,
        )
        self.assertIn("using (true)", self.compact_sql)
        self.assertEqual(self.sql.count("with (security_invoker = true)"), 2)

        for name in (*tables, *views):
            self.assertIn(
                f"revoke all on table public.{name} from anon, authenticated",
                self.compact_sql,
            )
            self.assertIn(
                f"grant select on table public.{name} to authenticated",
                self.compact_sql,
            )

        committee_view = self.sql[
            self.sql.index("create view public.iros_v_research_run_committees") :
            self.sql.index(
                ";",
                self.sql.index("create view public.iros_v_research_run_committees"),
            )
        ]
        self.assertIn("canonical_committee", committee_view)
        self.assertNotIn("request_payload", committee_view)
        self.assertNotIn("response_payload", committee_view)
        self.assertNotIn("grant all on schema public", self.compact_sql)
        self.assertNotIn("grant all on all tables", self.compact_sql)

    def test_migration_is_iros_only_and_has_no_cross_project_foreign_keys(self) -> None:
        self.assertNotIn("well_", self.sql)
        self.assertNotIn("references public.well_", self.sql)
        self.assertNotIn("references public.users", self.sql)
        for statement in self.sql.split(";"):
            compact = " ".join(statement.split())
            if compact.startswith(("create table public.", "create view public.")):
                object_name = compact.split("public.", 1)[1].split()[0]
                self.assertTrue(object_name.startswith("iros_"), object_name)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from pathlib import Path


class ReadinessThesisMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        migrations = sorted(
            Path("supabase/migrations").glob("*_iros_readiness_thesis.sql")
        )
        if len(migrations) != 1:
            raise AssertionError("expected one readiness and thesis migration")
        cls.sql = migrations[0].read_text().lower()
        cls.compact_sql = " ".join(cls.sql.split())

    def test_persists_readiness_results_and_individual_checks(self) -> None:
        for table in (
            "iros_readiness_gate_results",
            "iros_readiness_checks",
        ):
            self.assertIn(f"create table public.{table}", self.sql)

        self.assertIn(
            "unique (operator_id, research_run_id)", self.compact_sql
        )
        self.assertIn(
            "unique (operator_id, readiness_gate_result_id, check_id)",
            self.compact_sql,
        )

    def test_readiness_is_bound_to_exact_validated_upstream_identity(self) -> None:
        for field in (
            "security_id uuid not null",
            "thesis_contract_id text not null",
            "evidence_bundle_id uuid not null",
            "evidence_bundle_hash text not null",
            "validated_grader_opinion_ids jsonb not null",
            "committee_result_id uuid not null",
            "committee_memo_id uuid not null",
            "committee_status text not null",
            "requested_disposition text not null",
            "final_disposition text not null",
            "readiness_status text not null",
            "gate_policy_version text not null",
            "canonical_readiness jsonb not null",
        ):
            self.assertIn(field, self.sql)

        for message in (
            "readiness result requires exact completed committee and memo",
            "readiness result opinion identity mismatch",
            "readiness finalization failed: canonical identity mismatch",
        ):
            self.assertIn(message, self.sql)
        self.assertIn(
            "readiness finalization failed: canonical check mismatch",
            self.sql,
        )
        self.assertIn("readiness result is immutable", self.sql)
        self.assertIn("readiness check is immutable", self.sql)

    def test_readiness_is_downgrade_only_and_decision_ready_is_complete(self) -> None:
        for message in (
            "readiness finalization failed: check set mismatch",
            "readiness finalization failed: disposition upgrade prohibited",
            "readiness finalization failed: decision ready requirements not met",
            "readiness finalization failed: blocked downgrade invalid",
            "readiness finalization failed: downgrade target invalid",
        ):
            self.assertIn(message, self.sql)

        for expression in (
            "new.final_disposition <> new.requested_disposition",
            "new.committee_status <> 'complete'",
            "passed_check_count <> 10",
            "failed_check_count <> 0",
            "new.final_disposition not in ('decision_ready', 'deep_research')",
        ):
            self.assertIn(expression, self.compact_sql)

        for bypass in (
            "stance_counts",
            "majority_vote",
            "average_confidence",
            "universal_score",
            "sentiment_score",
            "user_enthusiasm",
        ):
            self.assertNotIn(bypass, self.sql)

    def test_thesis_policy_creates_canonical_provisional_or_no_thesis(self) -> None:
        for table in (
            "iros_thesis_chains",
            "iros_thesis_versions",
            "iros_thesis_creation_results",
        ):
            self.assertIn(f"create table public.{table}", self.sql)

        for invariant in (
            "unique (operator_id, research_run_id)",
            "unique (operator_id, readiness_gate_result_id)",
            "complete committee must create canonical thesis",
            "abstention committee must create provisional thesis",
            "incomplete committee must create no thesis",
            "provisional thesis must branch without superseding canonical",
        ):
            self.assertIn(invariant, self.compact_sql)

        self.assertIn(
            "new.final_disposition = 'decision_ready'", self.compact_sql
        )
        self.assertIn("thesis version is immutable", self.sql)
        self.assertIn("thesis creation result is immutable", self.sql)

    def test_chain_ownership_uses_stable_security_and_contract(self) -> None:
        self.assertIn(
            "primary key (operator_id, security_id, thesis_contract_id)",
            self.compact_sql,
        )
        self.assertIn(
            "active_canonical_thesis_version_id uuid", self.sql
        )
        self.assertIn(
            "thesis chain may advance only to the next canonical version",
            self.sql,
        )
        for expression in (
            "new.previous_canonical_thesis_version_id is distinct from current_canonical_id",
            "new.based_on_thesis_version_id is distinct from current_canonical_id",
            "set active_canonical_thesis_version_id = new.id",
            "thesis.previous_canonical_thesis_version_id is not distinct from old.active_canonical_thesis_version_id",
        ):
            self.assertIn(expression, self.compact_sql)

        self.assertNotIn("symbol text", self.sql)
        self.assertNotIn("issuer_name text", self.sql)

    def test_thesis_retains_exact_contract_policy_and_provenance(self) -> None:
        for field in (
            "evidence_bundle_id uuid not null",
            "evidence_bundle_hash text not null",
            "question_type_version text not null",
            "workflow_config_version text not null",
            "proposition_id text not null",
            "proposition_version text not null",
            "validated_grader_opinion_ids jsonb not null",
            "committee_result_id uuid not null",
            "committee_memo_id uuid not null",
            "readiness_gate_result_id uuid not null",
            "readiness_gate_policy_version text not null",
            "requested_disposition text not null",
            "final_disposition text not null",
            "canonical_thesis jsonb not null",
        ):
            self.assertIn(field, self.sql)

        self.assertIn(
            "thesis version requires exact readiness committee memo and bundle",
            self.sql,
        )
        self.assertIn("thesis version canonical identity mismatch", self.sql)
        self.assertIn("'thesis_version.v1'", self.sql)
        self.assertIn("'thesis_creation_result.v1'", self.sql)
        for canonical_key in (
            "'previous_canonical_thesis_version_id'",
            "'based_on_thesis_version_id'",
            "'question_type_version'",
            "'workflow_config_version'",
            "'proposition_id'",
            "'proposition_version'",
            "'committee_status'",
            "'readiness_gate_policy_version'",
        ):
            self.assertIn(canonical_key, self.sql)

    def test_authenticated_views_expose_only_canonical_contracts(self) -> None:
        expected_views = {
            "iros_v_research_run_readiness": (
                "readiness.operator_id",
                "readiness.research_run_id",
                "readiness.committee_result_id",
                "readiness.committee_memo_id",
                "readiness.canonical_readiness",
            ),
            "iros_v_research_run_thesis": (
                "creation.operator_id",
                "creation.research_run_id",
                "creation.readiness_gate_result_id",
                "creation.creation_outcome",
                "creation.canonical_creation_result",
                "thesis.canonical_thesis",
            ),
            "iros_v_thesis_chains": (
                "chain.operator_id",
                "chain.security_id",
                "chain.thesis_contract_id",
                "as canonical_chain",
            ),
        }
        self.assertEqual(self.sql.count("with (security_invoker = true)"), 3)
        for name, columns in expected_views.items():
            start = self.sql.index(f"create view public.{name}")
            view = self.sql[start : self.sql.index(";", start)]
            for column in columns:
                self.assertIn(column, view)
            self.assertIn(
                f"grant select on table public.{name} to authenticated",
                self.compact_sql,
            )

    def test_rls_grants_and_namespace_are_isolated(self) -> None:
        tables = (
            "iros_readiness_gate_results",
            "iros_readiness_checks",
            "iros_thesis_chains",
            "iros_thesis_versions",
            "iros_thesis_creation_results",
        )
        self.assertEqual(self.sql.count("enable row level security"), 5)
        self.assertGreaterEqual(
            self.sql.count("using ((select auth.uid()) = operator_id"), 5
        )
        for name in tables:
            self.assertIn(
                f"revoke all on table public.{name} from anon, authenticated",
                self.compact_sql,
            )
            self.assertIn(
                f"grant select on table public.{name} to authenticated",
                self.compact_sql,
            )

        self.assertNotIn("well_", self.sql)
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

from __future__ import annotations

from pathlib import Path
import re
import unittest

from investment_research_os.migration_audit import audit_iros_migration_batch


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "supabase" / "migrations"


def migration_path() -> Path:
    matches = sorted(MIGRATIONS.glob("*_iros_personal_research_contract.sql"))
    if len(matches) != 1:
        raise AssertionError("expected one iros_personal_research_contract migration")
    return matches[0]


class PersonalResearchContractMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.path = migration_path()
        cls.sql = cls.path.read_text().lower()
        cls.compact = " ".join(cls.sql.split())

    def test_registers_one_exact_additive_question_workflow_and_roster(self) -> None:
        for identity in (
            "biotech_moonshot_catalyst_personal_research_assessment",
            "biotech_moonshot_catalyst_personal_research_assessment.v1",
            "biotech-moonshot-catalyst-personal-research-v1",
            "biotech_moonshot_catalyst_personal_research_v1",
        ):
            self.assertIn(identity, self.sql)
        self.assertIn("insert into public.iros_question_types", self.sql)
        self.assertIn("insert into public.iros_workflow_configs", self.sql)
        self.assertIn("insert into public.iros_grader_definitions", self.sql)
        self.assertIn(
            "where strict.workflow_config_version = 'biotech-moonshot-catalyst-v1'",
            self.compact,
        )
        self.assertIn("personal research grader roster clone failed", self.sql)
        self.assertRegex(
            self.compact,
            r"array\[\s*'moonshot', 'catalyst', 'biotech', "
            r"'risk_dilution', 'valuation'\s*\]",
        )
        self.assertIn("array_agg(grader_id order by roster_position)", self.compact)
        self.assertIn("count(*) = 5", self.compact)
        self.assertIn("bool_and(required and active)", self.compact)

    def test_command_constraint_and_overload_accept_only_exact_pairs(self) -> None:
        self.assertIn(
            "constraint iros_research_run_commands_workflow_identity",
            self.sql,
        )
        self.assertIn(
            "drop constraint iros_research_run_commands_blockers",
            self.compact,
        )
        self.assertIn(
            "add constraint iros_research_run_commands_blockers",
            self.compact,
        )
        for pair in (
            (
                "biotech_moonshot_catalyst_assessment.v1",
                "biotech-moonshot-catalyst-v1",
            ),
            (
                "biotech_moonshot_catalyst_personal_research_assessment.v1",
                "biotech-moonshot-catalyst-personal-research-v1",
            ),
        ):
            self.assertRegex(
                self.compact,
                re.escape(pair[0]) + r"'.{1,120}" + re.escape(pair[1]),
            )
        self.assertIn(
            "create function public.iros_enqueue_research_run_command( "
            "p_security_id uuid, p_as_of_cutoff timestamptz, "
            "p_operator_focus text, p_question_type_version text, "
            "p_workflow_config_version text )",
            self.compact,
        )
        self.assertIn("unsupported research workflow identity", self.sql)
        self.assertIn(
            "personal_research_valuation_pipeline_unavailable",
            self.sql,
        )
        self.assertNotIn("p_question_type_version text default", self.sql)
        self.assertNotIn("p_workflow_config_version text default", self.sql)
        self.assertNotIn(
            "drop function public.iros_enqueue_research_run_command("
            "uuid, timestamptz, text)",
            self.compact,
        )
        self.assertIn("security definer", self.sql)
        self.assertIn("set search_path = ''", self.sql)
        self.assertIn("grant execute on function", self.sql)
        self.assertIn("to authenticated", self.sql)

    def test_extends_valuation_persistence_without_weakening_strict_pair(self) -> None:
        for column in (
            "valuation_contract_version",
            "valuation_assurance",
            "halt_verification_status",
            "price_timestamp",
        ):
            self.assertIn(f"add column {column}", self.sql)
        self.assertIn(
            "constraint iros_valuation_snapshots_adjustment_status",
            self.sql,
        )
        self.assertIn("'adjusted'", self.sql)
        for identity in (
            "valuation_snapshot.v1",
            "official_unadjusted_close",
            "valuation_snapshot.personal_research.v1",
            "verified_consolidated_end_of_day_close",
            "private_personal_research",
            "not_independently_verified",
        ):
            self.assertIn(identity, self.sql)
        self.assertIn(
            "constraint iros_valuation_snapshots_contract_identity",
            self.sql,
        )
        for canonical_match in (
            "canonical_snapshot -> 'price_basis' ->> 'price_type'",
            "canonical_snapshot -> 'price_basis' ->> 'price_timestamp'",
            "canonical_snapshot -> 'price_basis' ->> 'halt_verification_status'",
            "canonical_snapshot -> 'price_basis' ->> 'share_price'",
            "canonical_snapshot -> 'price_basis' ->> 'provider_source_reference_id'",
        ):
            self.assertIn(canonical_match, self.compact)
        self.assertIn(
            "create function public.iros_validate_valuation_contract_identity",
            self.sql,
        )
        self.assertIn("security invoker", self.sql)
        self.assertIn(
            "create or replace view public.iros_v_research_run_valuation_snapshot",
            self.sql,
        )
        self.assertIn("with (security_invoker = true)", self.sql)

    def test_extends_readiness_and_thesis_with_exact_contract_policy_pairs(
        self,
    ) -> None:
        for constraint in (
            "iros_readiness_gate_results_contract",
            "iros_thesis_chains_contract",
            "iros_thesis_versions_contract",
            "iros_thesis_creation_results_contract",
        ):
            self.assertIn(f"drop constraint {constraint}", self.compact)
            self.assertIn(f"add constraint {constraint}", self.compact)
        self.assertIn("biotech-readiness.v1", self.sql)
        self.assertIn("biotech-personal-readiness.v1", self.sql)
        self.assertIn(
            "create or replace view public.iros_v_research_run_readiness",
            self.sql,
        )
        self.assertIn(
            "create or replace view public.iros_v_research_run_thesis",
            self.sql,
        )
        self.assertIn(
            "create or replace view public.iros_v_thesis_chains",
            self.sql,
        )

    def test_extends_operator_decisions_without_personal_portfolio_handoff(
        self,
    ) -> None:
        self.assertIn(
            "drop constraint iros_operator_decisions_contract",
            self.compact,
        )
        self.assertIn(
            "add constraint iros_operator_decisions_contract",
            self.compact,
        )
        self.assertIn(
            "drop constraint iros_workflow_commands_contract",
            self.compact,
        )
        self.assertIn(
            "add constraint iros_workflow_commands_contract",
            self.compact,
        )
        self.assertRegex(
            self.compact,
            r"thesis_contract_id = "
            r"'biotech_moonshot_catalyst_personal_research_v1'\s+"
            r"and operator_action <> "
            r"'mark_for_future_portfolio_review'",
        )
        self.assertIn(
            "biotech_moonshot_catalyst_assessment",
            self.sql,
        )
        self.assertNotIn(
            "drop constraint iros_portfolio_review_handoff_markers_contract",
            self.compact,
        )

    def test_replaces_checkpoint_contract_lookup_without_strict_literal(self) -> None:
        checkpoint = re.search(
            r"create or replace function\s+"
            r"public\.iros_validate_research_run_command_checkpoint_insert"
            r"\(\).*?\n\$\$;",
            self.sql,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(checkpoint)
        assert checkpoint is not None
        body = checkpoint.group(0)
        self.assertIn("selected_run.thesis_contract_id", body)
        self.assertNotIn(
            "coalesce(creation.canonical_creation_result ->> "
            "'thesis_contract_id', 'biotech_moonshot_catalyst_assessment')",
            body,
        )

    def test_security_and_isolation_remain_explicit(self) -> None:
        self.assertNotIn("well_", self.sql)
        self.assertNotIn("to anon", self.sql)
        self.assertIn("enable row level security", self.sql)
        for view in (
            "iros_v_research_run_valuation_snapshot",
            "iros_v_research_run_readiness",
            "iros_v_research_run_thesis",
            "iros_v_thesis_chains",
        ):
            self.assertIn(
                f"grant select on table public.{view} to authenticated",
                self.compact,
            )
        report = audit_iros_migration_batch((self.path,))
        self.assertTrue(report.passed, report.violations)


if __name__ == "__main__":
    unittest.main()

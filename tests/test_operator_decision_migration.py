from __future__ import annotations

import unittest
from pathlib import Path


class OperatorDecisionMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        migrations = sorted(
            Path("supabase/migrations").glob("*_iros_operator_decisions.sql")
        )
        if len(migrations) != 1:
            raise AssertionError("expected one operator decisions migration")
        cls.sql = migrations[0].read_text().lower()
        cls.compact_sql = " ".join(cls.sql.split())

    def test_persists_exact_append_only_operator_decision_event(self) -> None:
        self.assertIn(
            "create table public.iros_operator_decisions", self.sql
        )
        for field in (
            "id uuid primary key",
            "operator_id uuid not null",
            "security_id uuid not null",
            "thesis_contract_id text not null",
            "thesis_version_id uuid not null",
            "committee_result_id uuid not null",
            "readiness_gate_result_id uuid not null",
            "system_disposition text not null",
            "operator_action text not null",
            "relationship text not null",
            "rationale text not null",
            "supersedes_operator_decision_id uuid",
            "decision_policy_version text not null",
            "idempotency_key text not null",
            "canonical_decision jsonb not null",
            "created_at timestamptz not null",
        ):
            self.assertIn(field, self.sql)

        self.assertIn(
            "unique (operator_id, idempotency_key)", self.compact_sql
        )
        self.assertIn("operator decision is immutable", self.sql)

    def test_validates_upstream_policy_canonical_identity_and_supersession(self) -> None:
        for message in (
            "operator decision requires exact thesis committee readiness and disposition",
            "operator decision relationship does not match policy",
            "operator decision override rationale required",
            "operator decision supersession must reference current ownership head",
            "operator decision canonical identity mismatch",
        ):
            self.assertIn(message, self.sql)

        for expression in (
            "thesis.security_id = new.security_id",
            "thesis.thesis_contract_id = new.thesis_contract_id",
            "thesis.committee_result_id = new.committee_result_id",
            "thesis.readiness_gate_result_id = new.readiness_gate_result_id",
            "thesis.final_disposition = new.system_disposition",
            "readiness.readiness_status",
            "decision.operator_id = new.operator_id",
            "decision.security_id = new.security_id",
            "decision.thesis_contract_id = new.thesis_contract_id",
            "decision.created_at >= new.created_at",
        ):
            self.assertIn(expression, self.compact_sql)

        for canonical_key in (
            "'operator_decision_event.v1'",
            "'operator_decision_id'",
            "'operator_id'",
            "'security_id'",
            "'thesis_contract_id'",
            "'thesis_version_id'",
            "'committee_result_id'",
            "'readiness_gate_result_id'",
            "'system_disposition'",
            "'operator_action'",
            "'relationship'",
            "'rationale'",
            "'supersedes_operator_decision_id'",
            "'decision_policy_version'",
            "'idempotency_key'",
            "'created_at'",
        ):
            self.assertIn(canonical_key, self.sql)

        self.assertIn("when 'no_action' then 'defer'", self.compact_sql)
        self.assertIn("else 'override'", self.compact_sql)

    def test_deep_research_command_is_separate_validated_and_idempotent(self) -> None:
        self.assertIn(
            "create table public.iros_workflow_commands", self.sql
        )
        for field in (
            "id uuid primary key",
            "operator_decision_id uuid not null",
            "operator_id uuid not null",
            "security_id uuid not null",
            "thesis_contract_id text not null",
            "thesis_version_id uuid not null",
            "committee_result_id uuid not null",
            "readiness_gate_result_id uuid not null",
            "command_type text not null",
            "command_policy_version text not null",
            "idempotency_key text not null",
            "command_state text not null",
            "canonical_command jsonb not null",
            "created_at timestamptz not null",
        ):
            self.assertIn(field, self.sql)

        for invariant in (
            "unique (operator_id, operator_decision_id, command_type)",
            "unique (operator_id, idempotency_key)",
            "workflow command requires request deep research decision",
            "workflow command canonical identity mismatch",
            "workflow command is immutable",
            "'operator_workflow_command.v1'",
            "'create_research_request'",
            "'operator_workflow_command_policy.v1'",
            "'pending'",
        ):
            self.assertIn(invariant, self.compact_sql)

    def test_portfolio_review_marker_requires_canonical_ready_passed_research(self) -> None:
        self.assertIn(
            "create table public.iros_portfolio_review_handoff_markers",
            self.sql,
        )
        for field in (
            "id uuid primary key",
            "operator_decision_id uuid not null",
            "operator_id uuid not null",
            "security_id uuid not null",
            "thesis_contract_id text not null",
            "thesis_version_id uuid not null",
            "committee_result_id uuid not null",
            "readiness_gate_result_id uuid not null",
            "thesis_status text not null",
            "final_system_disposition text not null",
            "readiness_status text not null",
            "handoff_policy_version text not null",
            "idempotency_key text not null",
            "canonical_marker jsonb not null",
            "created_at timestamptz not null",
        ):
            self.assertIn(field, self.sql)

        for invariant in (
            "unique (operator_id, operator_decision_id)",
            "unique (operator_id, idempotency_key)",
            "portfolio review handoff requires accepted decision ready action",
            "portfolio review handoff requires canonical decision ready thesis and passed readiness",
            "portfolio review handoff canonical identity mismatch",
            "portfolio review handoff marker is immutable",
            "decision.relationship = 'accept'",
            "decision.operator_action = 'mark_for_future_portfolio_review'",
            "thesis.thesis_status = 'canonical'",
            "thesis.final_disposition = 'decision_ready'",
            "readiness.readiness_status = 'passed'",
            "'portfolio_review_handoff_marker.v1'",
            "'portfolio_review_handoff_policy.v1'",
        ):
            self.assertIn(invariant, self.compact_sql)

    def test_owner_views_separate_history_current_state_and_effects(self) -> None:
        expected_views = {
            "iros_v_operator_decision_history": (
                "decision.operator_id",
                "decision.security_id",
                "decision.thesis_contract_id",
                "as canonical_history",
            ),
            "iros_v_current_operator_decisions": (
                "decision.operator_id",
                "decision.security_id",
                "decision.thesis_contract_id",
                "decision.id as current_operator_decision_id",
                "as canonical_current_state",
            ),
            "iros_v_operator_decision_effects": (
                "decision.operator_id",
                "decision.security_id",
                "decision.thesis_contract_id",
                "decision.id as operator_decision_id",
                "decision.canonical_decision",
                "thesis.canonical_thesis",
                "readiness.canonical_readiness",
                "command.canonical_command",
                "marker.canonical_marker",
            ),
        }
        self.assertEqual(self.sql.count("with (security_invoker = true)"), 3)
        for name, fields in expected_views.items():
            start = self.sql.index(f"create view public.{name}")
            view = self.sql[start : self.sql.index(";", start)]
            for field in fields:
                self.assertIn(field, view)
            self.assertIn(
                f"grant select on table public.{name} to authenticated",
                self.compact_sql,
            )

        for contract in (
            "'operator_decision_history.v1'",
            "'operator_decision_current_state.v1'",
        ):
            self.assertIn(contract, self.sql)
        self.assertIn("not exists", self.sql)
        self.assertIn("child.supersedes_operator_decision_id = decision.id", self.compact_sql)

    def test_rls_grants_and_namespace_are_owner_isolated(self) -> None:
        tables = (
            "iros_operator_decisions",
            "iros_workflow_commands",
            "iros_portfolio_review_handoff_markers",
        )
        self.assertEqual(self.sql.count("enable row level security"), 3)
        self.assertGreaterEqual(
            self.sql.count("using ((select auth.uid()) = operator_id"), 3
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
        for forbidden in (
            "position_size",
            "share_quantity",
            "order_id",
            "trade_action",
            "portfolio_suitability",
        ):
            self.assertNotIn(forbidden, self.sql)

    def test_canonical_payloads_are_exact_and_actions_require_exact_effects(self) -> None:
        for expression in (
            "canonical_decision ?& array[",
            "canonical_decision - array[",
            "canonical_command ?& array[",
            "canonical_command - array[",
            "canonical_marker ?& array[",
            "canonical_marker - array[",
            "operator decision deep research effect mismatch",
            "operator decision portfolio review effect mismatch",
            "operator decision unexpected effect",
            "deferrable initially deferred",
        ):
            self.assertIn(expression, self.compact_sql)

        self.assertIn(
            "create constraint trigger iros_operator_decisions_y_validate_effects",
            self.compact_sql,
        )


if __name__ == "__main__":
    unittest.main()
